"""Command-line interface for the AN-KLA beta."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

from .capabilities import capabilities
from .cli_error_log import DEBUG_ENV, display_path, write_error_log
from .benchmark_fixture import run_reference_benchmark
from .canonical import canonical_json
from .checkpoint_policy import CheckpointPolicyError
from .compaction import CompactionError, commit_compaction, plan_compaction
from .checkpoints import commit_checkpoint, plan_checkpoint, show_checkpoint
from .context import assemble_context
from .context_package import (
    apply_context_plan,
    context_status,
    get_template,
    plan_context_change,
)
from .context_view import (
    DEFAULT_BUDGET_BYTES,
    DEFAULT_LIMIT,
    ERROR_SCHEMA as VIEW_ERROR_SCHEMA,
    PROJECTIONS,
    context_view,
)
from .index import INDEX_PROFILE, build_index, detect_fts5, verify_index_deep
from .identity import IdentityError, adopt, identity_status, plan_adoption, repair
from .integration import integration_status
from .evaluation import evaluate_retrieval, evaluate_retrieval_v2
from .export_restore import ExportError, create_export, restore_export, verify_export
from .reader_gate import ReaderGateError
from .retrieval import SCAN_PROFILE, retrieve
from .resume import resume
from .schemas import schema_bytes, schema_catalog
from .startup import startup_diagnostic
from .store import ConcurrentUpdateError, MemoryStore, StoreError
from .subject import resolve_namespace
from .temporal import FRESHNESS_PROFILE, parse_freshness_now
from .transactions import TransactionError
from .update_check import check_for_update
from .upgrade import apply_upgrade, inspect_upgrade, verify_upgrade
from .version import VERSION


class CliUsageError(ValueError):
    """Stable CLI input error with an optional, sanitized input role."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.detail = detail


def _json(path: str, *, role: str | None = None) -> Any:
    try:
        payload = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise CliUsageError("input_json_unreadable", role) from None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise CliUsageError("input_json_invalid", role) from None


def _cli_authority(value: Any) -> Any:
    """Fail closed when a JSON file claims authority the CLI cannot resolve."""

    if isinstance(value, dict) and value.get("authority_class") in {
        "tool_observed",
        "channel_confirmed",
    }:
        raise ValueError("cli_privileged_authority_unresolved")
    return value


def _planning_result(value: Any, expected_current: str) -> tuple[Any, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "current_revision", "decision", "plan"}
        or value.get("schema") != "an-kla/write-planning-result-v1"
        or value.get("current_revision") != expected_current
    ):
        raise ValueError("invalid_write_planning_result")
    return value["decision"], value["plan"]


def _positive_csv(value: str, code: str) -> list[int]:
    try:
        result = [int(item) for item in value.split(",")]
    except ValueError:
        raise ValueError(code) from None
    if not result or any(item <= 0 for item in result):
        raise ValueError(code)
    return result


def _run() -> None:
    parser = argparse.ArgumentParser(description="AN-KLA Memory beta")
    parser.add_argument("--version", action="version", version=f"an-kla-memory {VERSION}")
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="Omitir la verificación no bloqueante de nuevas versiones.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    init_cmd = sub.add_parser(
        "init", help="Crear la memoria local .an-kla/memory/ en el proyecto."
    )
    init_cmd.add_argument("--transaction-id")
    sub.add_parser(
        "status", help="Resumen verificable de la revisión vigente."
    )
    verify_cmd = sub.add_parser(
        "verify", help="Verificar integridad de la memoria (o de una revisión)."
    )
    verify_cmd.add_argument(
        "--revision", help="Digest sha256 exacto de una revisión específica (histórica)."
    )
    sub.add_parser(
        "startup-diagnostic",
        help="Clasificar la memoria disponible antes de trabajo material.",
    )
    integration_cmd = sub.add_parser(
        "integration",
        help="Observar la integración (store, contexto gestionado, modo).",
    )
    integration_sub = integration_cmd.add_subparsers(
        dest="integration_command", required=True
    )
    integration_status_cmd = integration_sub.add_parser(
        "status",
        help="Ejes observables de la integración (ADR-0039), read-only.",
    )
    integration_status_cmd.add_argument("--target", default="AGENTS.md")
    sub.add_parser(
        "capabilities", help="Descubrir contratos y límites sin leer memoria."
    )
    schema_cmd = sub.add_parser(
        "schema", help="Enumerar o leer JSON Schemas normativos instalados."
    )
    schema_sub = schema_cmd.add_subparsers(dest="schema_command", required=True)
    schema_sub.add_parser("list")
    schema_show_cmd = schema_sub.add_parser("show")
    schema_show_cmd.add_argument("name")
    doctor_cmd = sub.add_parser(
        "doctor", help="Salud del store, índice FTS5 y entorno."
    )
    doctor_cmd.add_argument("--deep-index", action="store_true")
    sub.add_parser(
        "recover", help="Diagnosticar y reportar estado recuperable tras un fallo."
    )
    index_cmd = sub.add_parser(
        "rebuild-index",
        help="Regenerar el índice FTS5 derivado para una revisión."
    )
    index_cmd.add_argument(
        "--revision", default=None,
        help="Revisión objetivo; por defecto la vigente (CURRENT).",
    )
    retrieve_cmd = sub.add_parser(
        "retrieve", help="Recuperar registros por consulta bajo presupuesto exacto."
    )
    retrieve_cmd.add_argument(
        "--query", required=True, help="Consulta léxica; los términos se intersectan con el texto."
    )
    retrieve_cmd.add_argument(
        "--budget", type=int, required=True, help="Presupuesto exacto en bytes UTF-8 del texto servido."
    )
    retrieve_cmd.add_argument(
        "--profile", choices=(SCAN_PROFILE, INDEX_PROFILE), default=SCAN_PROFILE
    )
    retrieve_cmd.add_argument(
        "--freshness-profile", choices=(FRESHNESS_PROFILE,),
        help="Activar proyección de frescura (edad de verified_at); añade denominadores.",
    )
    retrieve_cmd.add_argument(
        "--now", help="Reloj inyectable ISO-8601 (UTC) para frescura reproducible."
    )
    retrieve_cmd.add_argument(
        "--stale-after-days", type=int,
        help="Umbral opcional de días para marcar registros como stale.",
    )
    retrieve_cmd.add_argument(
        "--streams",
        default="facts",
        help="Streams a recuperar (CSV); por defecto 'facts' para respetar la beta.",
    )
    assemble_cmd = sub.add_parser(
        "assemble-context",
        help="Ensamblar checkpoint, información nueva y memoria en un presupuesto."
    )
    assemble_cmd.add_argument(
        "--query", required=True, help="Consulta léxica para la sección de memoria."
    )
    assemble_cmd.add_argument(
        "--budget", type=int, required=True,
        help="Presupuesto global exacto del contenido servido; el framing del host no se mide.",
    )
    assemble_cmd.add_argument(
        "--new-information", help="Texto del caller incluido como sección indivisible."
    )
    assemble_cmd.add_argument(
        "--freshness-profile", choices=(FRESHNESS_PROFILE,),
        help="Activar proyección de frescura; mismo contrato que retrieve.",
    )
    assemble_cmd.add_argument(
        "--now", help="Reloj inyectable ISO-8601 (UTC) para frescura reproducible."
    )
    assemble_cmd.add_argument(
        "--stale-after-days", type=int,
        help="Umbral opcional de días para marcar registros como stale.",
    )
    evaluate_cmd = sub.add_parser(
        "evaluate", help="Evaluar recuperación (v1); para ranking usa evaluate-v2."
    )
    evaluate_cmd.add_argument("--queries", required=True)
    evaluate_cmd.add_argument("--budget", type=int, required=True)
    evaluate_v2_cmd = sub.add_parser(
        "evaluate-v2", help="Evaluar ranking y presupuesto por consulta y k."
    )
    evaluate_v2_cmd.add_argument("--queries", required=True)
    evaluate_v2_cmd.add_argument("--budgets", required=True)
    evaluate_v2_cmd.add_argument("--k-values", default="1,3,5,10")
    evaluate_v2_cmd.add_argument("--measure-latency", action="store_true")
    reference_benchmark_cmd = sub.add_parser(
        "benchmark-reference",
        help="Ejecutar el corpus de referencia empaquetado."
    )
    reference_benchmark_cmd.add_argument("--measure-latency", action="store_true")
    plan_write_cmd = sub.add_parser(
        "plan-write",
        help="Planificar sin mutar; autoridad privilegiada requiere adaptador externo.",
        description=(
            "Validar write-proposal-v1 + write-authority-v1 y emitir el "
            "planning result exacto sin mutar la memoria."
        ),
        epilog=(
            "Obtén base_revision con `status`; guarda stdout en un archivo "
            "efímero nuevo y privado. Consulta docs/write-policy-cli.md."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    plan_write_cmd.add_argument(
        "--proposal",
        required=True,
        help="Archivo JSON con schema an-kla/write-proposal-v1.",
    )
    plan_write_cmd.add_argument(
        "--authority",
        required=True,
        help="Archivo JSON con schema an-kla/write-authority-v1.",
    )
    commit_plan_cmd = sub.add_parser(
        "commit-write-plan",
        help="Revalidar y escribir un plan exacto bajo el lock.",
        description=(
            "Consumir proposal, authority y planning result exactos; revalidar "
            "CURRENT bajo lock antes de escribir."
        ),
        epilog=(
            "Cada commit mueve CURRENT: para otra escritura relee `status` y "
            "vuelve a planificar. Consulta docs/write-policy-cli.md."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    commit_plan_cmd.add_argument(
        "--expected-current",
        required=True,
        help="Digest revision obtenido de status antes de planificar.",
    )
    commit_plan_cmd.add_argument(
        "--proposal",
        required=True,
        help="Mismo archivo write-proposal-v1 usado al planificar.",
    )
    commit_plan_cmd.add_argument(
        "--authority",
        required=True,
        help="Mismo archivo write-authority-v1 usado al planificar.",
    )
    commit_plan_cmd.add_argument(
        "--planning-result",
        required=True,
        help="stdout exacto de plan-write, guardado sin reconstruirlo.",
    )
    commit_plan_cmd.add_argument(
        "--transaction-id",
        help="UUID opcional del caller para inspección idempotente del outcome.",
    )
    transaction_cmd = sub.add_parser(
        "transaction", help="Inspeccionar outcomes por transaction id."
    )
    transaction_sub = transaction_cmd.add_subparsers(
        dest="transaction_command", required=True
    )
    transaction_inspect = transaction_sub.add_parser("inspect")
    transaction_inspect.add_argument("transaction_id")
    transaction_repair = transaction_sub.add_parser(
        "repair-durability",
        help="Reparar registro de durabilidad de un outcome (MUTATIVO; requiere autoridad vigente).",
    )
    transaction_repair.add_argument("transaction_id")
    refute_cmd = sub.add_parser("refute", help="Refutación gobernada sin sucesor.")
    refute_sub = refute_cmd.add_subparsers(dest="refute_command", required=True)
    refute_plan = refute_sub.add_parser("plan")
    refute_plan.add_argument("--proposal", required=True)
    refute_plan.add_argument("--authority-claim", required=True)
    refute_commit = refute_sub.add_parser("commit")
    refute_commit.add_argument("--expected-current", required=True)
    refute_commit.add_argument("--planning-result", required=True)
    refute_commit.add_argument("--transaction-id")
    refute_inspect = refute_sub.add_parser("inspect")
    refute_inspect.add_argument("--stream", required=True, choices=("facts", "events", "episodes"))
    refute_inspect.add_argument("--record-sha256", required=True)
    refute_inspect.add_argument("--revision")
    export_cmd = sub.add_parser("export", help="Export/backup local verificable.")
    export_sub = export_cmd.add_subparsers(dest="export_command", required=True)
    export_create = export_sub.add_parser("create")
    export_create.add_argument("--bundle", required=True)
    export_verify = export_sub.add_parser("verify")
    export_verify.add_argument("--bundle", required=True)
    export_restore = export_sub.add_parser("restore")
    export_restore.add_argument("--bundle", required=True)
    compact_cmd = sub.add_parser("compact", help="Compactación gobernada ligada a export.")
    compact_sub = compact_cmd.add_subparsers(dest="compact_command", required=True)
    compact_plan = compact_sub.add_parser("plan")
    compact_plan.add_argument("--proposal", required=True)
    compact_plan.add_argument("--bundle", required=True)
    compact_commit = compact_sub.add_parser("commit")
    compact_commit.add_argument("--planning-result", required=True)
    compact_commit.add_argument("--expected-current", required=True)
    compact_commit.add_argument("--bundle")
    identity_cmd = sub.add_parser("identity", help="Inspeccionar o adoptar identidad local.")
    identity_sub = identity_cmd.add_subparsers(dest="identity_command", required=True)
    identity_status_cmd = identity_sub.add_parser("status")
    identity_status_cmd.add_argument("--show-ids", action="store_true")
    identity_sub.add_parser("plan-adoption")
    identity_adopt_cmd = identity_sub.add_parser("adopt")
    identity_adopt_cmd.add_argument("--plan", required=True)
    identity_adopt_cmd.add_argument("--expected-current", required=True)
    identity_repair_cmd = identity_sub.add_parser("repair")
    identity_repair_cmd.add_argument("--plan", required=True)
    checkpoint_cmd = sub.add_parser("checkpoint", help="Checkpoint operacional gobernado.")
    checkpoint_sub = checkpoint_cmd.add_subparsers(dest="checkpoint_command", required=True)
    checkpoint_sub.add_parser("show")
    checkpoint_plan_cmd = checkpoint_sub.add_parser("plan")
    checkpoint_plan_cmd.add_argument("--input", required=True)
    checkpoint_plan_cmd.add_argument("--authority", required=True)
    checkpoint_commit_cmd = checkpoint_sub.add_parser("commit")
    checkpoint_commit_cmd.add_argument("--plan", required=True)
    checkpoint_commit_cmd.add_argument("--expected-current", required=True)
    checkpoint_commit_cmd.add_argument("--transaction-id", required=True)
    resume_cmd = sub.add_parser("resume", help="Reanudar desde una revisión consistente.")
    resume_cmd.add_argument("--budget", type=int, required=True)
    resume_cmd.add_argument("--query")
    resume_cmd.add_argument(
        "--profile", choices=(SCAN_PROFILE, INDEX_PROFILE), default=SCAN_PROFILE
    )
    context_cmd = sub.add_parser(
        "context", help="Administrar únicamente el bloque AN-KLA en AGENTS.md."
    )
    context_sub = context_cmd.add_subparsers(dest="context_command", required=True)
    context_status_cmd = context_sub.add_parser("status")
    context_status_cmd.add_argument("--target", default="AGENTS.md")
    context_show_template_cmd = context_sub.add_parser(
        "show-template",
        help="Volcar el texto canónico del bloque y contrato administrado.",
    )
    context_show_template_cmd.add_argument(
        "--version",
        default=None,
        help="Versión de plantilla conocida; por defecto la instalada.",
    )
    context_plan_cmd = context_sub.add_parser("plan")
    context_plan_cmd.add_argument(
        "--operation", choices=("install", "update", "uninstall"), required=True
    )
    context_plan_cmd.add_argument("--target", default="AGENTS.md")
    context_apply_cmd = context_sub.add_parser("apply")
    context_apply_cmd.add_argument("--plan", required=True)
    for operation in ("install", "update", "uninstall"):
        operation_cmd = context_sub.add_parser(operation)
        operation_cmd.add_argument("--target", default="AGENTS.md")
    upgrade_cmd = sub.add_parser(
        "upgrade", help="Planificar y verificar la integración de una versión instalada."
    )
    upgrade_sub = upgrade_cmd.add_subparsers(dest="upgrade_command", required=True)
    upgrade_inspect_cmd = upgrade_sub.add_parser("inspect")
    upgrade_inspect_cmd.add_argument("--target", required=True)
    upgrade_inspect_cmd.add_argument("--context-target", default="AGENTS.md")
    upgrade_apply_cmd = upgrade_sub.add_parser("apply")
    upgrade_apply_cmd.add_argument(
        "expected_fingerprint", help="plan_fingerprint devuelto por upgrade inspect."
    )
    upgrade_apply_cmd.add_argument("--plan", required=True)
    upgrade_apply_cmd.add_argument(
        "--confirm-target-drift",
        action="store_true",
        help="Confirmar absorción de drift fuera-del-bloque (requerido si inspect lo reporta).",
    )
    upgrade_verify_cmd = upgrade_sub.add_parser("verify")
    upgrade_verify_cmd.add_argument("--target", required=True)
    upgrade_verify_cmd.add_argument("--context-target", default="AGENTS.md")
    sub.add_parser(
        "check-updates",
        help="Verificar (sin aplicar) si hay una versión más reciente publicada.",
    )
    subject_cmd = sub.add_parser(
        "subject",
        help="Resolver el namespace contextual del proyecto.",
    )
    subject_sub = subject_cmd.add_subparsers(dest="subject_command", required=True)
    subject_sub.add_parser(
        "namespace",
        help="Devolver el namespace para subject_ref; fail-closed si la identidad no está complete.",
    )
    view_cmd = sub.add_parser(
        "view", help="Proyectar vistas derivadas read-only sobre una revisión fijada."
    )
    view_sub = view_cmd.add_subparsers(dest="view_command", required=True)
    view_context_cmd = view_sub.add_parser(
        "context", help="Vista contextual determinista y non-authoritative."
    )
    view_context_cmd.add_argument("--revision", required=True)
    view_context_cmd.add_argument("--subject", dest="subject_filter")
    view_context_cmd.add_argument("--streams", default=None)
    view_context_cmd.add_argument(
        "--projection", choices=PROJECTIONS, default="text"
    )
    view_context_cmd.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    view_context_cmd.add_argument(
        "--budget", type=int, default=DEFAULT_BUDGET_BYTES
    )
    view_context_cmd.add_argument("--cursor")
    view_context_cmd.add_argument("--now")
    view_context_cmd.add_argument("--stale-after-days", type=int)
    args = parser.parse_args()

    if args.command == "check-updates":
        notice = check_for_update(force=True)
        sys.stdout.buffer.write(canonical_json(notice.as_dict()))
        if notice.notice:
            sys.stderr.write(notice.notice)
        return

    if not args.no_update_check:
        notice = check_for_update(force=False)
        if notice.notice:
            sys.stderr.write(notice.notice)

    store = MemoryStore(args.project_root)
    if args.command == "capabilities":
        result: Any = capabilities()
    elif args.command == "schema":
        if args.schema_command == "show":
            sys.stdout.buffer.write(schema_bytes(args.name))
            return
        result = schema_catalog()
    elif args.command == "context":
        if args.context_command == "status":
            result = context_status(args.project_root, args.target)
        elif args.context_command == "show-template":
            result = get_template(args.version)
        elif args.context_command == "plan":
            result = plan_context_change(
                args.project_root, args.operation, args.target
            )
        elif args.context_command == "apply":
            result = apply_context_plan(args.project_root, _json(args.plan))
        else:
            plan = plan_context_change(
                args.project_root, args.context_command, args.target
            )
            result = {
                "plan": plan,
                "result": apply_context_plan(args.project_root, plan),
            }
    elif args.command == "upgrade":
        if args.upgrade_command == "inspect":
            result = inspect_upgrade(
                args.project_root, args.target, args.context_target
            )
        elif args.upgrade_command == "apply":
            result = apply_upgrade(
                args.project_root,
                _json(args.plan),
                args.expected_fingerprint,
                confirm_target_drift=args.confirm_target_drift,
            )
        else:
            result = verify_upgrade(
                args.project_root, args.target, args.context_target
            )
    elif args.command == "init":
        result = store.initialize_with_outcome(transaction_id=args.transaction_id)
    elif args.command == "status":
        result = store.verify()
    elif args.command == "startup-diagnostic":
        try:
            result = startup_diagnostic(store)
        except Exception:
            # A diagnostic must never answer with a traceback: the caller is an
            # agent deciding whether it has memory, and a stack trace carries
            # absolute paths (§11.1).  Broader CLI coverage is issue #84.
            raise CliUsageError("startup_diagnostic_failed")
    elif args.command == "integration":
        result = integration_status(store, args.target)
    elif args.command == "verify":
        result = (
            store.verify_revision(args.revision)
            if args.revision is not None
            else store.verify()
        )
    elif args.command == "doctor":
        result = {**store.doctor(), "fts5": detect_fts5(), "memory_exists": store.current_path.exists()}
        if args.deep_index:
            result["index_deep"] = verify_index_deep(store)
    elif args.command == "recover":
        result = store.recover()
    elif args.command == "transaction":
        if args.transaction_command == "inspect":
            result = store.inspect_transaction(args.transaction_id)
        else:
            result = store.repair_transaction_durability(args.transaction_id)
    elif args.command == "refute":
        if args.refute_command == "plan":
            result = store.plan_refute(
                _json(args.proposal), _json(args.authority_claim)
            )
        elif args.refute_command == "commit":
            result = store.commit_refute_plan(
                expected_current=args.expected_current,
                planning_result=_json(args.planning_result),
                transaction_id=args.transaction_id,
            )
        else:
            result = store.inspect_refute(
                stream=args.stream,
                target_record_sha256=args.record_sha256,
                revision=args.revision,
            )
    elif args.command == "export":
        if args.export_command == "create":
            result = create_export(store, args.bundle)
        elif args.export_command == "verify":
            result = verify_export(args.bundle)
        else:
            result = restore_export(args.bundle, args.project_root)
    elif args.command == "compact":
        if args.compact_command == "plan":
            result = plan_compaction(store, _json(args.proposal), args.bundle)
        else:
            result = commit_compaction(
                store, _json(args.planning_result), args.expected_current,
                args.bundle,
            )
    elif args.command == "identity":
        if args.identity_command == "status":
            result = identity_status(store, include_ids=args.show_ids)
        elif args.identity_command == "plan-adoption":
            result = plan_adoption(store)
        elif args.identity_command == "repair":
            result = repair(store, _json(args.plan))
        else:
            result = adopt(store, _json(args.plan), args.expected_current)
    elif args.command == "subject":
        result = resolve_namespace(store)
    elif args.command == "view":
        streams = None if args.streams is None else tuple(args.streams.split(","))
        result = context_view(
            store,
            revision=args.revision,
            streams=streams,
            subject_filter=args.subject_filter,
            projection=args.projection,
            limit=args.limit,
            budget_bytes=args.budget,
            cursor=args.cursor,
            now=args.now,
            stale_after_days=args.stale_after_days,
        )
        if result.get("code") == "view_invalid_inputs":
            sys.stderr.write(
                f"an-kla error: view_invalid_inputs ({result.get('detail', 'input')})\n"
            )
            raise SystemExit(2)
        if result.get("code") == "view_internal_error":
            sys.stderr.write("an-kla error: view_internal_error\n")
            raise SystemExit(1)
        sys.stdout.buffer.write(canonical_json(result))
        if result.get("schema") == VIEW_ERROR_SCHEMA:
            raise SystemExit(3)
        return
    elif args.command == "checkpoint":
        if args.checkpoint_command == "show":
            result = show_checkpoint(store)
        elif args.checkpoint_command == "plan":
            result = plan_checkpoint(store, _json(args.input), _json(args.authority))
        else:
            result = commit_checkpoint(
                store,
                _json(args.plan),
                args.expected_current,
                transaction_id=args.transaction_id,
            )
    elif args.command == "resume":
        result = resume(store, args.budget, query=args.query, profile=args.profile)
    elif args.command == "rebuild-index":
        result = build_index(store, revision_id=args.revision)
    elif args.command == "retrieve":
        streams_tuple = tuple(s for s in args.streams.split(",") if s)
        if args.freshness_profile is None and (
            args.now is not None or args.stale_after_days is not None
        ):
            raise ValueError("freshness_profile_required")
        result = retrieve(
            store, args.query, args.budget, profile=args.profile, streams=streams_tuple,
            freshness_profile=args.freshness_profile,
            now=parse_freshness_now(args.now) if args.now is not None else None,
            stale_after_days=args.stale_after_days,
        )
    elif args.command == "assemble-context":
        if args.freshness_profile is None and (
            args.now is not None or args.stale_after_days is not None
        ):
            raise ValueError("freshness_profile_required")
        result = assemble_context(
            store,
            args.query,
            args.budget,
            new_information=args.new_information,
            freshness_profile=args.freshness_profile,
            now=parse_freshness_now(args.now) if args.now is not None else None,
            stale_after_days=args.stale_after_days,
        )
    elif args.command == "evaluate":
        result = evaluate_retrieval(store, args.queries, args.budget)
    elif args.command == "evaluate-v2":
        result = evaluate_retrieval_v2(
            store,
            args.queries,
            _positive_csv(args.budgets, "invalid_evaluation_budget"),
            _positive_csv(args.k_values, "invalid_evaluation_k"),
            measure_latency=args.measure_latency,
        )
    elif args.command == "benchmark-reference":
        result = run_reference_benchmark(measure_latency=args.measure_latency)
    elif args.command == "plan-write":
        result = store.plan_write(
            _json(args.proposal, role="proposal"),
            _cli_authority(_json(args.authority, role="authority")),
        )
    else:
        decision, plan = _planning_result(
            _json(args.planning_result, role="planning_result"),
            args.expected_current,
        )
        result = store.commit_write_plan(
            expected_current_hash=args.expected_current,
            proposal=_json(args.proposal, role="proposal"),
            authority=_cli_authority(_json(args.authority, role="authority")),
            decision=decision,
            plan=plan,
            transaction_id=args.transaction_id,
        )
    if args.command in {
        "assemble-context",
        "benchmark-reference",
        "capabilities",
        "commit-write-plan",
        "compact",
        "checkpoint",
        "init",
        "identity",
        "evaluate-v2",
        "export",
        "resume",
        "refute",
        "schema",
        "subject",
        "transaction",
        "upgrade",
    }:
        sys.stdout.buffer.write(canonical_json(result))
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if (
        args.command == "transaction"
        and result.get("state") != "transaction_archived_by_compaction"
        and result.get("committed") is not True
    ):
        raise SystemExit(3)
    if (
        args.command == "compact"
        and args.compact_command == "commit"
        and result.get("state") != "committed"
    ):
        raise SystemExit(3)
    if (
        args.command == "export"
        and args.export_command == "restore"
        and result.get("state") != "published"
    ):
        raise SystemExit(3)
    if (
        args.command == "refute"
        and args.refute_command == "commit"
        and isinstance(result.get("outcome"), dict)
        and result["outcome"].get("committed") is not True
    ):
        raise SystemExit(3)
    if (
        args.command == "init"
        and isinstance(result.get("outcome"), dict)
        and result["outcome"].get("committed") is not True
    ):
        raise SystemExit(3)
    if (
        args.command == "commit-write-plan"
        and isinstance(result.get("outcome"), dict)
        and result["outcome"].get("committed") is not True
    ):
        raise SystemExit(3)
    if (
        args.command == "subject"
        and args.subject_command == "namespace"
        and result.get("result") == "namespace_unavailable"
    ):
        raise SystemExit(3)


def main() -> None:
    """Console entrypoint with the same safe error surface as ``python -m``."""

    try:
        _run()
    except CliUsageError as exc:
        suffix = f" ({exc.detail})" if exc.detail else ""
        sys.stderr.write(f"an-kla error: {exc}{suffix}\n")
        raise SystemExit(2)
    except (CheckpointPolicyError, CompactionError, ExportError, StoreError, ConcurrentUpdateError, IdentityError, ReaderGateError, TransactionError, ValueError, OSError) as exc:
        if isinstance(exc, TransactionError) and str(exc) == "invalid_transaction_id":
            sys.stderr.write("an-kla error: invalid_transaction_id\n")
            raise SystemExit(2)
        detail = getattr(exc, "detail", None)
        if str(exc) == "write_plan_base_changed" and detail is None:
            detail = "refresh_status_and_replan"
        suffix = f" ({detail})" if detail else ""
        raise SystemExit(f"an-kla error: {exc}{suffix}")
    except Exception:
        # Safety net (#84): an unexpected failure must never answer with a
        # traceback on stderr (it leaks absolute paths, §11.1).  The full
        # traceback goes to a private local log; AN_KLA_DEBUG=1 restores it
        # on stderr for development.  Exit code stays 1, matching the
        # uncaught-crash behavior this replaces.
        traceback_text = traceback.format_exc()
        log_path = write_error_log(traceback_text)
        if os.environ.get(DEBUG_ENV) == "1":
            sys.stderr.write(traceback_text)
            raise SystemExit(1)
        hint = f" (traceback: {display_path(log_path)})" if log_path else ""
        raise SystemExit(f"an-kla error: cli_unexpected_failure{hint}")


if __name__ == "__main__":
    main()
