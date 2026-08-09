"""Deterministic active-record projection for ADR-0028."""

from __future__ import annotations

from typing import Any, Mapping

from .canonical import canonical_json, digest_bytes, digest_json


STREAMS = ("facts", "events", "episodes")


def project_snapshot(snapshot: Any) -> dict[str, Any]:
    refuted = {
        (item["stream"], item["target_record_sha256"])
        for item in snapshot.manifest.get("refutations_map", [])
    }
    superseded = {
        (item["stream"], item["target_id"])
        for item in snapshot.manifest.get("supersedes_map", [])
    }
    active: dict[str, list[Mapping[str, Any]]] = {stream: [] for stream in STREAMS}
    tombstones: list[dict[str, str]] = []
    for stream in STREAMS:
        for row in snapshot.raw_records[stream]:
            row_digest = digest_json(row)
            key = (stream, str(row.get("id", "")))
            if (stream, row_digest) in refuted:
                state = "refuted"
            elif key in superseded:
                state = "superseded"
            elif row.get("status", row.get("nu")) in {None, "vigente", "active"}:
                state = "active"
            else:
                state = "inactive"
            if state == "active":
                active[stream].append(row)
            else:
                tombstones.append(
                    {"stream": stream, "record_sha256": row_digest, "state": state}
                )
    order = {stream: index for index, stream in enumerate(STREAMS)}
    tombstones.sort(key=lambda item: (order[item["stream"]], item["record_sha256"]))
    payloads: dict[str, bytes] = {}
    segment_ids: dict[str, list[str]] = {}
    for stream in STREAMS:
        if not active[stream]:
            segment_ids[stream] = []
            continue
        payload = b"".join(canonical_json(row) + b"\n" for row in active[stream])
        identifier = digest_bytes(payload)
        payloads[stream] = payload
        segment_ids[stream] = [identifier]
    return {
        "active": active,
        "record_tombstones": tombstones,
        "segment_ids": segment_ids,
        "segment_payloads": payloads,
    }


__all__ = ["project_snapshot"]
