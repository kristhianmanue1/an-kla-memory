"""CLI parser construction (extracted from __main__ for size limits)."""

from __future__ import annotations

import argparse

from .context_view import DEFAULT_BUDGET_BYTES, DEFAULT_LIMIT, PROJECTIONS
from .index import INDEX_PROFILE
from .inventory import DEFAULT_LIMIT as INVENTORY_DEFAULT_LIMIT
from .inventory import MAX_LIMIT as INVENTORY_MAX_LIMIT
from .retrieval import SCAN_PROFILE
from .sealed.bundle import SEALED_PROFILE
from .temporal import FRESHNESS_PROFILE
from .version import VERSION

__all__ = ["build_parser"]


def build_parser() -> argparse.ArgumentParser:
    """Build the full CLI parser (single source of subcommands)."""
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
    inventory_cmd = sub.add_parser(
        "inventory",
        help="Inventariar la población física de records de una revisión (metadata).",
    )
    inventory_cmd.add_argument(
        "--revision", required=True,
        help="Digest sha256 exacto de la revisión a inventariar (obligatorio).",
    )
    inventory_cmd.add_argument(
        "--streams", default=None,
        help="Streams a inventariar (CSV); por defecto los tres.",
    )
    inventory_cmd.add_argument(
        "--cursor", default=None, help="Cursor opaco de paginación."
    )
    inventory_cmd.add_argument(
        "--limit", type=int, default=INVENTORY_DEFAULT_LIMIT,
        help=f"Registros por página (default {INVENTORY_DEFAULT_LIMIT}, max {INVENTORY_MAX_LIMIT}).",
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
    export_create.add_argument(
        "--seal",
        choices=(SEALED_PROFILE,),
        help=(
            "Sellar el bundle (perfil sealed-export/v1, ADR-0042); sin este "
            "flag el camino es exactamente export/v1."
        ),
    )
    export_create.add_argument(
        "--key-adapter",
        help=(
            "Ejecutable del adaptador externo de claves (ruta absoluta "
            "recomendada); jamás una línea con espacios (sin split)."
        ),
    )
    export_create.add_argument(
        "--key-adapter-arg",
        action="append",
        default=[],
        help=(
            "Argumento del adaptador (flag repetible; un elemento de argv "
            "por uso, sin shell)."
        ),
    )
    export_create.add_argument(
        "--key-adapter-env",
        action="append",
        default=[],
        help="Nombre de variable de entorno autorizada para el adaptador (repetible).",
    )
    export_verify = export_sub.add_parser("verify")
    export_verify.add_argument("--bundle", required=True)
    export_verify.add_argument(
        "--seal",
        choices=(SEALED_PROFILE,),
        help=(
            "Exigir el perfil sellado; sin este flag el camino sigue al "
            "manifiesto (dispatcher dual, ADR-0042 §3)."
        ),
    )
    export_verify.add_argument("--key-adapter", help="Ejecutable del adaptador (solo bundles sellados).")
    export_verify.add_argument(
        "--key-adapter-arg", action="append", default=[],
        help="Argumento del adaptador (flag repetible, sin shell).",
    )
    export_verify.add_argument(
        "--key-adapter-env", action="append", default=[],
        help="Nombre de variable de entorno autorizada para el adaptador (repetible).",
    )
    export_restore = export_sub.add_parser("restore")
    export_restore.add_argument("--bundle", required=True)
    export_restore.add_argument(
        "--seal",
        choices=(SEALED_PROFILE,),
        help=(
            "Exigir el perfil sellado; sin este flag el camino sigue al "
            "manifiesto (dispatcher dual, ADR-0042 §3)."
        ),
    )
    export_restore.add_argument("--key-adapter", help="Ejecutable del adaptador (solo bundles sellados).")
    export_restore.add_argument(
        "--key-adapter-arg", action="append", default=[],
        help="Argumento del adaptador (flag repetible, sin shell).",
    )
    export_restore.add_argument(
        "--key-adapter-env", action="append", default=[],
        help="Nombre de variable de entorno autorizada para el adaptador (repetible).",
    )
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
        "--operation",
        choices=("install", "update", "uninstall", "adopt-baseline"),
        required=True,
    )
    context_plan_cmd.add_argument("--target", default="AGENTS.md")
    context_apply_cmd = context_sub.add_parser("apply")
    context_apply_cmd.add_argument("--plan", required=True)
    for operation in ("install", "update", "uninstall"):
        operation_cmd = context_sub.add_parser(operation)
        operation_cmd.add_argument("--target", default="AGENTS.md")
    adopt_cmd = context_sub.add_parser(
        "adopt-baseline",
        help="Adoptar los bytes observados del target como baseline (ADR-0040).",
    )
    adopt_cmd.add_argument("--target", default="AGENTS.md")
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

    return parser
