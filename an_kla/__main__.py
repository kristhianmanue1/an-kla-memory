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
from .cli_parser import build_parser
from .cli_error_log import DEBUG_ENV, display_path, write_error_log
from .benchmark_fixture import run_reference_benchmark
from .canonical import canonical_json
from .checkpoint_policy import CheckpointPolicyError
from .compaction import CompactionError, commit_compaction, plan_compaction
from .checkpoints import commit_checkpoint, plan_checkpoint, show_checkpoint
from .context import assemble_context
from an_kla.baseline_adoption import (
    apply_baseline_adoption,
    plan_baseline_adoption,
)
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
from .inventory import DEFAULT_LIMIT as INVENTORY_DEFAULT_LIMIT
from .inventory import MAX_LIMIT as INVENTORY_MAX_LIMIT
from .inventory import STREAMS as INVENTORY_STREAMS
from .inventory import inventory
from .integration import integration_status
from .evaluation import evaluate_retrieval, evaluate_retrieval_v2
from .export_restore import ExportError
from .sealed.cli_dispatch import (
    dispatch_export_create,
    dispatch_export_restore,
    dispatch_export_verify,
)
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
    parser = build_parser()
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
            if args.operation == "adopt-baseline":
                result = plan_baseline_adoption(args.project_root, args.target)
            else:
                result = plan_context_change(
                    args.project_root, args.operation, args.target
                )
        elif args.context_command == "apply":
            result = apply_context_plan(args.project_root, _json(args.plan))
        elif args.context_command == "adopt-baseline":
            plan = plan_baseline_adoption(args.project_root, args.target)
            result = {
                "plan": plan,
                "result": apply_baseline_adoption(args.project_root, plan),
            }
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
    elif args.command == "inventory":
        streams = None if args.streams is None else tuple(
            s for s in args.streams.split(",") if s
        )
        result = inventory(
            store,
            args.revision,
            streams=streams,
            cursor=args.cursor,
            limit=args.limit,
        )
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
        # Dispatcher dual ADR-0042 §2/§3/§8 (T5): sin --seal el camino es
        # EXACTAMENTE export/v1 (delega en create_export/verify_export/
        # restore_export sin cambios); con --seal sealed-export/v1 exige
        # adaptador y usa la capa sellada de T4.
        if args.export_command == "create":
            result = dispatch_export_create(
                store, args.bundle,
                seal=args.seal,
                key_adapter=args.key_adapter,
                key_adapter_args=args.key_adapter_arg,
                key_adapter_env=args.key_adapter_env,
            )
        elif args.export_command == "verify":
            result = dispatch_export_verify(
                args.bundle,
                seal=args.seal,
                key_adapter=args.key_adapter,
                key_adapter_args=args.key_adapter_arg,
                key_adapter_env=args.key_adapter_env,
            )
        else:
            result = dispatch_export_restore(
                args.bundle, args.project_root,
                seal=args.seal,
                key_adapter=args.key_adapter,
                key_adapter_args=args.key_adapter_arg,
                key_adapter_env=args.key_adapter_env,
            )
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
