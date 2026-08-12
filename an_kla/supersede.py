"""Supersede target resolution extracted from :mod:`an_kla.store` (issue #59 Fase 0).

This module holds the behavior-preserving extraction of the supersede resolution
block that previously lived inline in ``MemoryStore.commit_write_plan``. It is
invoked under the store's ``write_lock``, after ``assert_unchanged`` and
``verify_write_plan`` and before any object/journal is written. A failure raises
``WritePolicyError("invalid_supersede_target", ...)`` with no side effects.
"""

from __future__ import annotations

from typing import Any, Mapping

from .write_policy import WritePolicyError


def resolve_supersede_targets(
    store: Any, checked_plan: Mapping[str, Any], observed: str
) -> list[dict[str, str]]:
    # ADR-0019 (PR-B): resolve supersede targets against the authoritative
    # snapshot under the lock, before any object/journal is written. A
    # failure here raises invalid_supersede_target (terminal) with no
    # side effects (no orphan objects, no prepared journal).
    pending_supersedes: list[dict[str, str]] = []
    if any(item["operation"] == "supersede" for item in checked_plan["records"]):
        base_snapshot = store.snapshot(observed)
        for item in checked_plan["records"]:
            if item["operation"] != "supersede":
                continue
            stream = item["stream"]
            target_id = item["supersedes"]
            # self-ref is already enforced by the policy core
            # (write_policy.py); keep a defense-in-depth check here.
            if target_id == item["record"]["id"]:
                raise WritePolicyError("invalid_supersede_target", "self_reference")
            target = next(
                (
                    r
                    for r in base_snapshot.records[stream]
                    if str(r.get("id", "")) == target_id
                ),
                None,
            )
            if target is None:
                raise WritePolicyError("invalid_supersede_target", "target_missing")
            if target.get("status", target.get("nu", "vigente")) not in {
                "vigente",
                "active",
                None,
            }:
                raise WritePolicyError(
                    "invalid_supersede_target", "target_not_vigente"
                )
            pending_supersedes.append(
                {
                    "stream": stream,
                    "target_id": target_id,
                    "sustituida_por": str(item["record"]["id"]),
                }
            )
    return pending_supersedes


__all__ = ["resolve_supersede_targets"]
