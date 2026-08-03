"""Installed normative JSON Schemas for agent-facing contracts."""

from __future__ import annotations

from importlib.resources import files
import json
from typing import Any

from ..canonical import digest_bytes


SCHEMA_FILES = {
    "cost-certificate-v1": "cost-certificate-v1.schema.json",
    "write-authority-v1": "write-authority-v1.schema.json",
    "write-decision-v1": "write-decision-v1.schema.json",
    "write-plan-v1": "write-plan-v1.schema.json",
    "write-proposal-v1": "write-proposal-v1.schema.json",
}


def schema_names() -> tuple[str, ...]:
    return tuple(sorted(SCHEMA_FILES))


def schema_bytes(name: str) -> bytes:
    if not isinstance(name, str) or name not in SCHEMA_FILES:
        raise ValueError("unknown_schema")
    try:
        return files(__package__).joinpath(SCHEMA_FILES[name]).read_bytes()
    except OSError:
        raise ValueError("schema_resource_unavailable") from None


def schema_document(name: str) -> dict[str, Any]:
    try:
        value = json.loads(schema_bytes(name))
    except json.JSONDecodeError:
        raise ValueError("schema_resource_invalid") from None
    if not isinstance(value, dict):
        raise ValueError("schema_resource_invalid")
    return value


def schema_catalog() -> dict[str, Any]:
    schemas = []
    for name in schema_names():
        payload = schema_bytes(name)
        document = schema_document(name)
        identifier = document.get("$id")
        if not isinstance(identifier, str):
            raise ValueError("schema_resource_invalid")
        schemas.append(
            {
                "name": name,
                "id": identifier,
                "sha256": digest_bytes(payload),
            }
        )
    return {
        "schema": "an-kla/schema-list-v1",
        "canonicalization": "canonical-json/v1",
        "schemas": schemas,
    }


__all__ = [
    "SCHEMA_FILES",
    "schema_bytes",
    "schema_catalog",
    "schema_document",
    "schema_names",
]
