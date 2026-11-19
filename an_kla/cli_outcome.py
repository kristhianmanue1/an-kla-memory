"""Matriz comando→rc=3 del CLI (issue #188), fuera de ``__main__`` por el tope de tamaño; éste la reexporta."""

from __future__ import annotations

from typing import Any


def pending_outcome_reason(args: Any, result: Any) -> str | None:
    """Matriz comando→rc=3 (issue #188): estado no terminal firme.

    Devuelve el identificador del caso cuando el comando terminó sin su
    estado terminal (payload completo en stdout, exit 3) y None cuando
    corresponde rc 0. Fuente de verdad de la matriz también publicada en
    ``capabilities()`` bajo ``cli_error_surface.pending_outcome``.
    """

    result = result if isinstance(result, dict) else {}
    if args.command == "transaction" and args.transaction_command == "inspect":
        if (
            result.get("state") != "transaction_archived_by_compaction"
            and result.get("committed") is not True
        ):
            return "transaction_inspect_outcome_not_firm"
    if args.command == "compact" and args.compact_command == "commit":
        if result.get("state") != "committed":
            return "compact_commit_outcome_not_firm"
    if args.command == "export" and args.export_command == "restore":
        if result.get("state") != "published":
            return "export_restore_outcome_not_firm"
    if args.command == "refute" and args.refute_command == "commit":
        if (
            isinstance(result.get("outcome"), dict)
            and result["outcome"].get("committed") is not True
        ):
            return "refute_commit_outcome_not_firm"
    if args.command == "init":
        if (
            isinstance(result.get("outcome"), dict)
            and result["outcome"].get("committed") is not True
        ):
            return "init_outcome_not_firm"
    if args.command == "commit-write-plan":
        if (
            isinstance(result.get("outcome"), dict)
            and result["outcome"].get("committed") is not True
        ):
            return "commit_write_plan_outcome_not_firm"
    if args.command == "inbox" and getattr(args, "inbox_command", None) == "drain":
        # R1-01: un vaciado abortado o con resultado desconocido no es un estado terminal firme;
        # `drained`, `queued` y el corte por presupuesto (`partial`) salen con 0.
        if result.get("state") == "aborted" or result.get("outcome") != "known":
            return "inbox_drain_outcome_not_firm"
    if args.command in ("remember", "dispute"):
        # `committed` y `queued` sin `drain_error` salen con 0 (la entrada está confirmada); `rejected`,
        # `queued` + `drain_error` (el vaciado abortó) y `outcome` desconocido, con 3 y el JSON íntegro (R1-02).
        if result.get("state") == "rejected":
            return "remember_rejected"
        if result.get("drain_error"):
            return "remember_drain_error"
        if result.get("outcome") != "known":
            return "remember_outcome_not_firm"
    if args.command == "subject" and args.subject_command == "namespace":
        if result.get("result") == "namespace_unavailable":
            return "subject_namespace_unavailable"
    return None
