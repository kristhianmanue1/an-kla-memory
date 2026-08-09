"""Read-only lifecycle inspection for governed refutation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .canonical import digest_json
from .refute_contracts import RefutePolicyError, STREAMS, digest


def _physical(row: Mapping[str, Any]) -> tuple[str | None, str]:
    if "status" in row:
        return digest_json(row["status"]), "physical_untrusted"
    if "nu" in row:
        return digest_json(row["nu"]), "physical_untrusted"
    return None, "default_active"


def _maps(snapshot: Any) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    supersedes = {
        (item["stream"], item["target_id"]): item["sustituida_por"]
        for item in snapshot.manifest.get("supersedes_map", [])
    }
    refutations = {
        (item["stream"], item["target_record_sha256"]): item["refutation_id"]
        for item in snapshot.manifest.get("refutations_map", [])
    }
    return supersedes, refutations


def _state(
    row: Mapping[str, Any], stream: str, supersedes: Mapping[tuple[str, str], str],
    refutations: Mapping[tuple[str, str], str],
) -> tuple[str, str, str | None, str | None]:
    record_sha = digest_json(row)
    record_id = str(row.get("id", ""))
    if (stream, record_sha) in refutations:
        return "refuted", "refutations_overlay", None, refutations[(stream, record_sha)]
    if (stream, record_id) in supersedes:
        return "superseded", "supersedes_overlay", supersedes[(stream, record_id)], None
    physical, source = _physical(row)
    value = row.get("status", row.get("nu", "vigente"))
    return (
        ("active" if value in {"vigente", "active", None} else "inactive"),
        source,
        None,
        None,
    )


def _missing(revision: str, stream: str, target: str) -> dict[str, Any]:
    return {
        "schema": "an-kla/refute-inspect-v1",
        "untrusted_memory_data": True,
        "revision": revision,
        "stream": stream,
        "target_record_sha256": target,
        "found": False,
        "target_id_sha256": None,
        "state": None,
        "state_source": None,
        "physical_status_sha256": None,
        "links": None,
        "chain": [],
        "refutation": None,
        "authority_claim": None,
        "authority_attestation": None,
    }


def inspect_refute(
    store: Any, *, stream: str, target_record_sha256: str,
    revision: str | None = None,
) -> dict[str, Any]:
    if stream not in STREAMS:
        raise RefutePolicyError("invalid_refute_target", "stream")
    digest(target_record_sha256, "invalid_refute_target", "target_record_sha256")
    if revision is not None:
        digest(revision, "revision_not_found", "revision")
    try:
        snapshot = store.snapshot(revision)
    except Exception as exc:
        if revision is not None and "object_missing:revisions" in str(exc):
            raise RefutePolicyError("revision_not_found") from exc
        raise
    by_id = {
        str(row.get("id", "")): row for row in snapshot.raw_records[stream]
    }
    matches = [
        row for row in snapshot.raw_records[stream]
        if digest_json(row) == target_record_sha256
    ]
    if not matches:
        return _missing(snapshot.revision_id, stream, target_record_sha256)
    if len(matches) != 1:
        raise RefutePolicyError("lifecycle_chain_invalid", "target_ambiguous")
    target = matches[0]
    supersedes, refutations = _maps(snapshot)
    state, source, successor_id, refutation_id = _state(
        target, stream, supersedes, refutations
    )
    physical, _physical_source = _physical(target)
    chain = []
    visited: set[str] = set()
    cursor = target
    limit = len(snapshot.raw_records[stream]) + 1
    for _ in range(limit):
        record_sha = digest_json(cursor)
        if record_sha in visited:
            raise RefutePolicyError("lifecycle_chain_invalid", "cycle")
        visited.add(record_sha)
        hop_state, _source, next_id, hop_refutation = _state(
            cursor, stream, supersedes, refutations
        )
        next_sha = None
        if next_id is not None:
            next_row = by_id.get(next_id)
            if next_row is None:
                raise RefutePolicyError("lifecycle_chain_invalid", "successor_missing")
            next_sha = digest_json(next_row)
        chain.append(
            {
                "record_sha256": record_sha,
                "id_sha256": digest_json(str(cursor.get("id", ""))),
                "state": hop_state,
                "superseded_by_sha256": next_sha,
                "refutation_id": hop_refutation,
            }
        )
        if next_id is None:
            break
        cursor = by_id[next_id]
    else:
        raise RefutePolicyError("lifecycle_chain_limit_exceeded")
    refutation = claim = attestation = None
    successor_sha = None
    if successor_id is not None:
        successor = by_id.get(successor_id)
        if successor is None:
            raise RefutePolicyError("lifecycle_chain_invalid", "successor_missing")
        successor_sha = digest_json(successor)
    if refutation_id is not None:
        refutation = deepcopy(dict(store._read_json_object("refutations", refutation_id)))
        claim = deepcopy(dict(store._read_json_object(
            "authority-claims", refutation["authority_claim_sha256"]
        )))
        attestation = deepcopy(dict(store._read_json_object(
            "authority-attestations", refutation["authority_attestation_id"]
        )))
    return {
        "schema": "an-kla/refute-inspect-v1",
        "untrusted_memory_data": True,
        "revision": snapshot.revision_id,
        "stream": stream,
        "target_record_sha256": target_record_sha256,
        "found": True,
        "target_id_sha256": digest_json(str(target.get("id", ""))),
        "state": state,
        "state_source": source,
        "physical_status_sha256": physical,
        "links": {
            "superseded_by_sha256": successor_sha,
            "refutation_id": refutation_id,
        },
        "chain": chain,
        "refutation": refutation,
        "authority_claim": claim,
        "authority_attestation": attestation,
    }


__all__ = ["inspect_refute"]
