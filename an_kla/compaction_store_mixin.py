"""Store-facing compaction and archived-transaction surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .reader_gate import shared_reader_gate
from .identity import assert_unchanged, mutation_preflight
from .transaction_repair import repair_durability
from .transactions import inspect_transaction


class CompactionStoreMixin:
    def repair_transaction_durability(self, transaction_id: str) -> dict[str, Any]:
        binding = mutation_preflight(self)
        with self.write_lock():
            assert_unchanged(self, binding, self.read_current())
            return repair_durability(self, transaction_id)

    def plan_compaction(
        self, proposal: Mapping[str, Any], bundle: str | Path
    ) -> dict[str, Any]:
        from .compaction import plan_compaction

        return plan_compaction(self, proposal, bundle)

    def commit_compaction(
        self, planning_result: Mapping[str, Any], expected_current: str,
        bundle: str | Path | None = None,
    ) -> dict[str, Any]:
        from .compaction import commit_compaction

        return commit_compaction(self, planning_result, expected_current, bundle)

    def verify_revision(self, revision: str) -> dict[str, Any]:
        from .compaction import verify_revision

        return verify_revision(self, revision)

    def inspect_transaction(self, transaction_id: str) -> dict[str, Any]:
        with shared_reader_gate(self):
            result = inspect_transaction(self, transaction_id)
            if (
                result.get("state") == "outcome_unknown"
                and result.get("operation_error_code")
                == "transaction_evidence_missing_or_invalid"
            ):
                from .compaction import archived_transaction_link_under_gate

                archived = archived_transaction_link_under_gate(self, transaction_id)
                if archived is not None:
                    return {
                        "schema": "an-kla/transaction-archived-v1",
                        "transaction_id": transaction_id,
                        "state": "transaction_archived_by_compaction",
                        **archived,
                    }
            return result


__all__ = ["CompactionStoreMixin"]
