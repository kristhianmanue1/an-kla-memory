"""Plan-time validation of write proposals against the base snapshot (issue #103).

H1 of issue #102: conditions that previously surfaced only as terminal commit
errors (``duplicate_<stream>_id``, ``invalid_supersede_target``) fail closed at
``plan_write`` with stable ``plan_*`` codes. Read-only checks against the base
snapshot; the authoritative resolution under the write lock (``supersede.py``,
``MemoryStore._assign_records``) is kept so the TOCTOU window stays closed.
The policy core remains pure: nothing here feeds ``evaluate_write`` or the
decision object.
"""

from __future__ import annotations

from typing import Any, Mapping

from .write_policy import WritePolicyError


def guard_plan_against_snapshot(
    records: Mapping[str, tuple[Mapping[str, Any], ...]],
    proposal: Mapping[str, Any],
) -> None:
    """Raise ``WritePolicyError`` with a ``plan_*`` code, or return None."""

    stream_records = records.get(proposal["stream"], ())
    record_id = str(proposal["record"].get("id", ""))
    if any(str(row.get("id", "")) == record_id for row in stream_records):
        raise WritePolicyError("plan_duplicate_id")
    if proposal["operation"] == "supersede":
        target = next(
            (
                row
                for row in stream_records
                if str(row.get("id", "")) == proposal["supersedes"]
            ),
            None,
        )
        if target is None:
            raise WritePolicyError("plan_supersede_target_missing")
        if target.get("status", target.get("nu", "vigente")) not in {
            "vigente",
            "active",
            None,
        }:
            raise WritePolicyError("plan_supersede_target_not_vigente")


__all__ = ["guard_plan_against_snapshot"]
