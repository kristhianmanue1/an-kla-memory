"""Apoyo de las pruebas de ``inbox requeue`` e ``inbox purge-rejected`` (ADR-0068): rechazos fabricados."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from an_kla import inbox
from an_kla.canonical import canonical_json
from an_kla.inbox_entries import INVALID, reject_entry
from an_kla.schemas import schema_document
from tests.inbox_support import EntryFactory, InboxCase

POLICY = "remember_state_over_fact"


def validates(result: dict[str, Any], name: str) -> None:
    errors = sorted(Draft202012Validator(schema_document(name)).iter_errors(result), key=str)
    assert not errors, errors[:3]


class RejectedCase(InboxCase):
    """Un store con la bandeja creada y un fabricante de entradas; ``rejected/`` se llena a mano o con ``reject_entry``."""

    def setUp(self) -> None:
        super().setUp()
        inbox.ensure_layout(self.store)
        self.factory = EntryFactory(self.store)
        self.paths = inbox.inbox_paths(self.store)

    def names(self, directory: Path) -> list[str]:
        return sorted(path.name for path in directory.iterdir())

    def reject_pending(self, name: str, code: str = INVALID) -> str:
        """El rechazo real de ``reject_entry`` (entrada + ``.reason``, o sólo ``.reason`` en un inodo inseguro)."""

        return reject_entry(self.store, name, code, [])

    def reject_valid(self, text: str, code: str = INVALID, **options: Any) -> str:
        return self.reject_pending(self.factory.write(text, **options), code)

    def put(self, data: dict[str, Any] | bytes, code: str = INVALID, name: str | None = None) -> str:
        """Un rechazo escrito directo en ``rejected/`` (sin ``fsync``), para los lotes grandes."""

        payload = data if isinstance(data, bytes) else canonical_json(data)
        name = name or self.factory.fresh_name()
        (self.paths.rejected / name).write_bytes(payload)
        (self.paths.rejected / (name + ".reason")).write_bytes(canonical_json({"code": code, "reason_codes": []}))
        return name

    def put_valid(self, text: str, code: str = INVALID) -> str:
        data = self.factory.entry(text)
        return self.put(data, code, self.factory.name_for(data))

    def reject_unsafe(self) -> str:
        name = self.factory.fresh_name()
        os.symlink("no-existe", self.paths.pending / name)
        return self.reject_pending(name, "inbox_entry_unsafe")

    def json_file(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_bytes())
