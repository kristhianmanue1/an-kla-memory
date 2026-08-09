"""Validation of immutable transaction audit evidence."""

from __future__ import annotations

from typing import Any, Mapping


def observed_log_complete(
    store: Any, journal: Mapping[str, Any], txid: str, candidate: str
) -> bool:
    identifier = journal.get("observed_log")
    if not isinstance(identifier, str):
        return False
    try:
        observed = store._read_json_object("refs/ref-log", identifier)
        intent_id = observed.get("intent")
        if not isinstance(intent_id, str):
            return False
        intent = store._read_json_object("refs/ref-log", intent_id)
    except Exception:
        return False
    shared = (
        observed.get("schema") == "an-kla/ref-log-v1"
        and observed.get("kind") == "observed_commit"
        and observed.get("transaction_id") == txid
        and observed.get("candidate") == candidate
        and observed.get("parent") == journal.get("parent")
    )
    return shared and (
        intent.get("schema") == "an-kla/ref-log-v1"
        and intent.get("kind") == "intent"
        and intent.get("transaction_id") == txid
        and intent.get("candidate") == candidate
        and intent.get("parent") == journal.get("parent")
    )


__all__ = ["observed_log_complete"]
