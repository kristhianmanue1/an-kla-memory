"""Apoyo de las pruebas de ADR-0069: dos orquestadores en un mismo repo, anclas de conversación y entradas a mano."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from an_kla import identity_c0, inbox
from an_kla.inbox_anchors import payload_extra
from an_kla.canonical import canonical_json
from tests.inbox_support import AGENT_ENV, InboxCase
from tests.remember_support import cli, cli_env, remember

OTHER = "example.org/otro/proyecto"  # P: el proyecto del que trata una orden que no es de este repo
QUOTE = "el operador dijo: usa el puerto 8081"


class ScopeCase(InboxCase):
    """Un repo R (``local:…``) con su store; ``env()`` da la identidad de cada orquestador."""

    def setUp(self) -> None:
        super().setUp()
        self.repo_id = identity_c0.repo_id_for(self.project)
        scratch = tempfile.TemporaryDirectory(prefix="scope-")
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)  # fuera del repo y propio de cada prueba
        self.anchor_file = self.scratch / "anclas.json"
        self.anchor_file.write_text(json.dumps([{"source": {"kind": "conversation"}, "quote": QUOTE}]))

    @staticmethod
    def env(name: str, role: str = "orquestador", session: str | None = "sesion-1", **extra: str | None) -> dict[str, str | None]:
        return {"AN_KLA_AGENT_NAME": name, "AN_KLA_AGENT_ROLE": role, "AN_KLA_SESSION_ID": session, **extra}

    def directive(self, name: str, text: str, *args: str, role: str = "orquestador", session: str | None = "sesion-1",
                  anchors: bool = True) -> tuple[int, dict]:
        extra = ("--anchor-file", str(self.anchor_file)) if anchors else ()
        return remember(self.project, text, "--kind", "directive", *extra, *args, env=self.env(name, role, session))

    def read(self, name: str, *args: str, role: str = "orquestador", **options: Any) -> dict:
        done = cli(self.project, *args, env=self.env(name, role), **options)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def pending(self) -> list[str]:
        return sorted(p.name for p in (self.inbox / "pending").glob("*.json"))

    def rejected_codes(self) -> list[str]:
        reasons = sorted((self.inbox / "rejected").glob("*.reason"), key=lambda p: p.stat().st_mtime_ns)
        return [json.loads(p.read_text())["code"] for p in reasons]

    def hand_entry(self, text: str, env: dict[str, str | None], *, kind: str = "directive", anchors: Any = "default",
                   target_id: str | None = None, **fields: Any) -> str:
        """Una entrada ``inbox-entry-v4`` escrita a mano en ``pending/``, sin pasar por el encolado ni sus comprobaciones."""

        merged = {k: v for k, v in cli_env(env).items() if k.startswith("AN_KLA_")}
        identity = identity_c0.build_identity(self.project, merged)
        data: dict[str, Any] = {"text": text, "kind": kind, **fields}
        if anchors == "default":
            anchors = [{
                "schema": "memoria/ancla/v1", "quote": QUOTE, "quote_sha256": None,
                "source": {"kind": "conversation", "session": identity["session"]["id"], "resolution": "pending",
                           "turn_id": None, "seal": None},
            }]
            from an_kla.anchors import quote_sha256
            anchors[0]["quote_sha256"] = quote_sha256(QUOTE)
        if anchors is not None:
            data["anchors"] = anchors
        key = identity_c0.derive_idempotency_key(identity, kind, text, target_id, None, {k: v for k, v in data.items() if k in ("subject", "audience", "valid_until", "until_revoked", "revokes")})
        envelope = identity_c0.build_envelope(identity, kind, key)
        entry: dict[str, Any] = {
            "schema": inbox.ENTRY_SCHEMA_V4, "text": text, "kind": kind, "kind_explicit": True, "envelope": envelope,
            "idempotency_key": key, "payload_sha256": "sha256:" + "0" * 64,
            **{k: v for k, v in data.items() if k not in ("text", "kind")},
        }
        if target_id is not None:
            entry["target_id"] = target_id
        entry["payload_sha256"] = inbox.payload_digest(text, kind, target_id, None, payload_extra(entry) or None)
        inbox.ensure_layout(self.store)
        self.entries = getattr(self, "entries", 0) + 1
        name = f"{10**18 + self.entries}-1-{key[7:23]}-{'0' * 8}.json"
        (self.inbox / "pending" / name).write_bytes(canonical_json(entry))
        return name

    def drain(self) -> dict:
        done = cli(self.project, "inbox", "drain", env=self.env("vaciador"))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)


__all__ = ["AGENT_ENV", "OTHER", "QUOTE", "ScopeCase", "os"]
