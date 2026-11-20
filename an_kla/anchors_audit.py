"""The audit of ``document`` anchors: ``anchors verify`` calls the adapter and **stores** what it found (ADR-0071 §5).

Reading serves what is stored and calls nobody; auditing is the moment that calls (README: "al escribir y al auditar").
Each audited record gets one ``an-kla/anchor-check-v1`` annotation in ``events``, even when the result did not change
(the date of the last check is data too).  It enters through the inbox with the C0 envelope of whoever audits and is drained
in the same invocation.  Without a C0 identity in the environment, or with the inbox busy, the audit still answers, with
``recorded: false`` and ``record_error: <code>``.  Nothing but ``document`` anchors is ever written.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .anchor_checks import CHECK_SCHEMA, stored_check
from .anchors_document_copy import copy_state
from .anchors_document_v2 import evaluate
from .anchors_git import GitRepo
from .custodian_adapter import Adapters
from .identity_c0 import repo_id_for
from .temporal import format_utc

RECORD_ERROR_QUEUED = "anchor_check_not_committed"


class AuditSession:
    """What an audit needs: the adapters, this project's ``repo.id`` (for the copy), the default-branch setting and the clock."""

    def __init__(
        self, store: Any, setting: Any, env: Mapping[str, str] | None = None, adapters: Adapters | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store, self.setting, self.env = store, setting, env
        self.adapters = adapters if adapters is not None else Adapters.for_store(store, env)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._repo_id: str | None | bool = False
        self._pending: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._at: dict[tuple[str, str], str] = {}
        self._unconfigured: dict[str, int] = {}
        self.used_adapters = False  # a ``document`` anchor was audited: the answer says if the table could not be read

    def repo_id(self) -> str | None:
        if self._repo_id is False:
            try:
                self._repo_id = repo_id_for(self.store.project_root)
            except (ValueError, OSError):
                self._repo_id = None  # no repository: a declared copy counts as missing
        return self._repo_id  # type: ignore[return-value]

    def audit(self, repo: GitRepo, stream: str, record_id: str, index: int, anchor: Mapping[str, Any]) -> dict[str, Any]:
        """Check one ``document`` anchor now and remember the result for the record's annotation."""
        key = (stream, record_id)
        at = self._at.setdefault(key, format_utc(self.clock()))  # one date per audited record
        state = copy_state(repo, anchor, self.repo_id(), self.setting)
        out = evaluate(anchor, "audit", state, self.adapters, at)
        self._pending.setdefault(key, []).append(stored_check(index, anchor["quote_sha256"], out))
        self.used_adapters = True
        name = anchor["source"]["derivation"]["custodian"]
        if self.adapters.config_error is None and name not in self.adapters.table:
            self._unconfigured[name] = self._unconfigured.get(name, 0) + 1  # ADR-0072 §2: not in the table, or no table
        del out["reject"]
        return out

    def warnings(self) -> list[dict[str, Any]]:
        """``custodian_not_configured``, one per custodian an audited anchor named that the table does not have (or there is no
        table).  A table that cannot be read says ``custodians_config_error`` instead, and a process that fails with its
        custodian configured is no configuration warning (ADR-0072 §2)."""
        return [{"code": "custodian_not_configured", "custodian": name, "anchors": count} for name, count in self._unconfigured.items()]

    def finish(self, stream: str, record_id: str) -> dict[str, Any]:
        """Store the record's audited results; ``{}`` when it had no ``document`` anchor audited."""
        key = (stream, record_id)
        checks = self._pending.pop(key, None)
        self._at.pop(key, None)
        if not checks:
            return {}
        return self._record(stream, record_id, checks)

    def _record(self, stream: str, record_id: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
        from .inbox import enqueue  # late: the inbox imports the anchors' modules
        from .inbox_drain import drain, error_code

        annotation = {"schema": CHECK_SCHEMA, "target": {"stream": stream, "record_id": record_id}, "checks": checks}
        try:
            queued = enqueue(
                self.store, f"anchor_check {stream}/{record_id}", kind="fact", operation="anchor_check",
                anchor_check=annotation, env=self.env, clock=self.clock,
            )
        except Exception as error:  # noqa: BLE001 - the audit always answers; whatever stopped the annotation is its code
            return {"recorded": False, "record_error": error_code(error)}
        name = queued["entry"]
        try:
            report = drain(self.store, include_entry=name, max_batches=1)
        except Exception as error:  # noqa: BLE001
            return {"recorded": False, "record_error": error_code(error)}
        done = [item for key in ("committed", "already_committed") for item in report[key]["entries"] if item.get("entry") == name]
        if done or name in report["duplicates_removed"]["names"]:
            return {"recorded": True}
        rejected = next((item for item in report["rejected"]["entries"] if item.get("entry") == name), None)
        return {"recorded": False, "record_error": rejected["code"] if rejected else report.get("drain_error") or RECORD_ERROR_QUEUED}
