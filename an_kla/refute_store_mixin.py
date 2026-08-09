"""Thin MemoryStore surface for governed refutation."""

from __future__ import annotations

from typing import Any, Mapping


class RefuteStoreMixin:
    def plan_refute(
        self, proposal: Mapping[str, Any], authority_claim: Mapping[str, Any]
    ) -> dict[str, Any]:
        from .refutations import plan_refute

        return plan_refute(self, proposal, authority_claim)

    def commit_refute_plan(
        self, *, expected_current: str, planning_result: Mapping[str, Any],
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        from .refutations import commit_refute

        return commit_refute(
            self, planning_result, expected_current, transaction_id=transaction_id
        )

    def inspect_refute(
        self, *, stream: str, target_record_sha256: str,
        revision: str | None = None,
    ) -> dict[str, Any]:
        from .refutations import inspect_refute

        return inspect_refute(
            self, stream=stream, target_record_sha256=target_record_sha256,
            revision=revision,
        )


__all__ = ["RefuteStoreMixin"]
