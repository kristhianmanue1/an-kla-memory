"""Encolado de la bandeja (ADR-0063 D1 «Encolar», D2, «Idempotencia»; mandato B1)."""

from __future__ import annotations

import errno
import itertools
import json
import os
import stat
import unittest
from unittest import mock
from datetime import datetime, timezone

from an_kla import identity_c0 as c0
from an_kla import inbox
from an_kla.identity import IdentityError
from an_kla.reader_gate import ReaderGateError
from an_kla.schemas import schema_document
from tests.inbox_support import AGENT_ENV, InboxCase

CLOCK = lambda: datetime(2026, 11, 15, 12, 0, 0, 123456, tzinfo=timezone.utc)  # noqa: E731
KEY = "sha256:" + "ab" * 32


def enqueue(store, text="recuerdo sobre quetzal", **kwargs):
    kwargs.setdefault("env", AGENT_ENV)
    kwargs.setdefault("clock", CLOCK)
    kwargs.setdefault("wait_seconds", 0.0)
    return inbox.enqueue(store, text, **kwargs)


def read_entry(case: InboxCase, name: str) -> dict:
    return json.loads((case.inbox / "pending" / name).read_bytes())


class EnqueueTests(InboxCase):
    def test_entry_name_and_content_are_valid_and_published_with_one_link(self) -> None:
        result = enqueue(self.store)
        name = result["entry"]
        self.assertTrue(inbox.is_entry_name(name))
        self.assertEqual(inbox.entry_names(self.store), [name])
        info = os.lstat(self.inbox / "pending" / name)
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual(info.st_nlink, 1)
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(os.listdir(self.inbox / "tmp"), [])
        entry = read_entry(self, name)
        self.assertEqual(c0.validate_envelope(entry["envelope"]), [])
        self.assertEqual(entry["envelope"]["enqueued_at"], "2026-11-15T12:00:00.123456Z")
        self.assertEqual(entry["envelope"]["idempotency_key"], entry["idempotency_key"])
        self.assertEqual(entry["envelope"]["kind"], entry["kind"])
        self.assertEqual(entry["payload_sha256"], inbox.payload_digest(entry["text"], "fact", None))
        self.assertNotIn("target_id", entry)
        self.assertEqual(result["record_id"], inbox.record_id("facts", entry["idempotency_key"]))
        self.assertTrue(result["record_id"].startswith("f-r-"))

    def test_entry_validates_against_the_published_schema(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema no instalado (extra de test)")
        validator = Draft202012Validator(schema_document("inbox-entry-v1"))
        for kwargs in ({}, {"target_id": "f-x"}):
            with self.subTest(kwargs=kwargs):
                name = enqueue(self.store, **kwargs)["entry"]
                self.assertEqual(list(validator.iter_errors(read_entry(self, name))), [])
        self.assertTrue(list(validator.iter_errors({"schema": "an-kla/inbox-entry-v1"})))
        # ADR-0065 §3: un `state` lleva casilla y se encola como inbox-entry-v2 (v1 no admite `slot`).
        v2 = Draft202012Validator(schema_document("inbox-entry-v2"))
        for kwargs in ({"kind": "state"}, {"kind": "state", "slot": "lateral"}):
            with self.subTest(kwargs=kwargs):
                name = enqueue(self.store, **kwargs)["entry"]
                entry = read_entry(self, name)
                self.assertEqual(list(v2.iter_errors(entry)), [])
                self.assertEqual(entry["slot"], kwargs.get("slot", "main"))
        self.assertTrue(list(v2.iter_errors({"schema": "an-kla/inbox-entry-v2"})))

    def test_name_collision_regenerates_and_never_overwrites(self) -> None:
        pid = os.getpid()
        taken = self.inbox / "pending" / f"1000-{pid}-{KEY[7:23]}-bbbbbbbb.json"
        (self.inbox / "pending").mkdir(parents=True)
        taken.write_bytes(b"ajeno")
        tokens = iter(["aaaaaaaa", "bbbbbbbb", "cccccccc"])
        result = enqueue(self.store, idempotency_key=KEY, time_ns=lambda: 1000, token=lambda: next(tokens))
        self.assertEqual(result["entry"], f"1000-{pid}-{KEY[7:23]}-cccccccc.json")
        self.assertEqual(taken.read_bytes(), b"ajeno")
        self.assertEqual(sorted(os.listdir(self.inbox / "pending")), sorted([taken.name, result["entry"]]))

    def test_name_exhaustion_fails_and_leaves_the_temporary(self) -> None:
        pid = os.getpid()
        (self.inbox / "pending").mkdir(parents=True)
        (self.inbox / "pending" / f"1-{pid}-{KEY[7:23]}-dddddddd.json").write_bytes(b"x")
        tokens = itertools.chain(["aaaaaaaa"], itertools.repeat("dddddddd"))
        with self.assertRaises(inbox.InboxError) as caught:
            enqueue(self.store, idempotency_key=KEY, time_ns=lambda: 1, token=lambda: next(tokens))
        self.assertEqual(caught.exception.code, "inbox_name_exhausted")
        self.assertEqual(len(os.listdir(self.inbox / "tmp")), 1)

    def test_replace_failure_leaves_nothing_pending_and_the_temporary_in_tmp(self) -> None:
        for code in (errno.EXDEV, errno.ENOSPC, errno.EIO):
            with self.subTest(errno=errno.errorcode[code]):
                def failing(src, dst, code=code):
                    raise OSError(code, os.strerror(code))

                with self.assertRaises(OSError) as caught:
                    enqueue(self.store, text=f"intento {code}", replace=failing)
                self.assertEqual(caught.exception.errno, code)
                self.assertEqual(inbox.entry_names(self.store), [])
                self.assertEqual(os.listdir(self.inbox / "pending"), [])
        self.assertEqual(len(os.listdir(self.inbox / "tmp")), 3)

    def test_durability_order_is_file_fsync_then_replace_then_pending_fsync(self) -> None:
        """R1-05: quitar o reordenar cualquiera de los dos fsync cambia esta secuencia."""

        enqueue(self.store, text="calienta el layout")  # el layout ya existe: sólo se observa la publicación
        events: list = []
        real_fsync, real_dir, real_replace = os.fsync, inbox.fsync_directory, os.replace

        inside_dir = []

        def fsync(fd):
            if not inside_dir:  # `fsync_directory` llama a `os.fsync` por dentro
                events.append(("fsync_file", os.fstat(fd).st_ino))
            return real_fsync(fd)

        def fsync_directory(path):
            events.append(("fsync_dir", path.name))
            inside_dir.append(True)
            try:
                return real_dir(path)
            finally:
                inside_dir.pop()

        def replace(src, dst):
            events.append(("replace", os.lstat(src).st_ino))
            return real_replace(src, dst)

        with mock.patch.object(inbox.os, "fsync", fsync), mock.patch.object(inbox, "fsync_directory", fsync_directory):
            name = enqueue(self.store, text="orden de durabilidad", replace=replace)["entry"]
        inode = os.lstat(self.inbox / "pending" / name).st_ino
        self.assertEqual(events, [("fsync_file", inode), ("replace", inode), ("fsync_dir", "pending")])

    def test_a_temporary_with_two_names_is_never_published(self) -> None:
        """R2-04: publicarlo daría un `queued` que el vaciado rechazaría como `inbox_entry_unsafe`."""

        calls = []

        def token():
            calls.append(1)
            if len(calls) == 2:  # entre escribir el temporal y publicarlo, un tercero lo enlaza
                (temporary,) = os.listdir(self.inbox / "tmp")
                os.link(self.inbox / "tmp" / temporary, self.project / "otro-nombre")
            return f"{len(calls):08x}"

        with self.assertRaises(inbox.InboxError) as caught:
            enqueue(self.store, token=token)
        self.assertEqual(caught.exception.code, "inbox_unsafe_path")
        self.assertEqual(os.listdir(self.inbox / "pending"), [])
        self.assertEqual(len(os.listdir(self.inbox / "tmp")), 1)

    def test_busy_hint_reaches_the_cli_error_surface(self) -> None:
        """R2-06: `main()` imprime `detail`; la pista de `InboxError` viaja por ese mismo campo."""

        self.hold_lock("ex")
        with self.assertRaises(inbox.InboxError) as caught:
            enqueue(self.store)
        self.assertEqual(caught.exception.detail, caught.exception.hint)
        self.assertTrue(caught.exception.detail)
        from an_kla import __main__ as entry

        with mock.patch.object(entry, "_run", side_effect=caught.exception):
            with self.assertRaises(SystemExit) as exited:
                entry.main()
        self.assertEqual(str(exited.exception), f"an-kla error: inbox_busy ({caught.exception.hint})")

    def test_failing_preflight_does_not_create_the_inbox(self) -> None:
        def refuse(_store):
            raise IdentityError("store_root_divergence")

        with self.assertRaises(IdentityError):
            enqueue(self.store, preflight=refuse)
        self.assertFalse(self.inbox.exists())

    def test_custody_change_between_preflights_leaves_no_entry(self) -> None:
        calls = []

        def drifting(_store):
            calls.append(1)
            if len(calls) == 2:
                raise IdentityError("store_identity_changed")

        with self.assertRaises(IdentityError) as caught:
            enqueue(self.store, preflight=drifting)
        self.assertEqual(str(caught.exception), "store_identity_changed")
        self.assertEqual(len(calls), 2)
        self.assertEqual(os.listdir(self.inbox / "pending"), [])
        self.assertEqual(os.listdir(self.inbox / "tmp"), [])

    def test_busy_lock_held_elsewhere_fails_with_inbox_busy_and_writes_nothing(self) -> None:
        self.hold_lock("ex")
        with self.assertRaises(inbox.InboxError) as caught:
            enqueue(self.store)
        self.assertEqual(caught.exception.code, "inbox_busy")
        self.assertTrue(caught.exception.hint)
        self.assertEqual(os.listdir(self.inbox / "pending") if (self.inbox / "pending").exists() else [], [])
        self.assertEqual(os.listdir(self.inbox / "tmp") if (self.inbox / "tmp").exists() else [], [])

    def test_missing_or_invalid_identity_fails_before_writing_anything(self) -> None:
        cases = {
            "identity_env_missing": {k: v for k, v in AGENT_ENV.items() if k != "AN_KLA_AGENT_CLI"},
            "identity_env_invalid": {**AGENT_ENV, "AN_KLA_AGENT_ROLE": "jefe"},
        }
        for code, env in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(c0.IdentityC0Error) as caught:
                    enqueue(self.store, env=env)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse(self.inbox.exists())

    def test_text_limit_is_64_kib_of_utf8(self) -> None:
        enqueue(self.store, text="a" * inbox.MAX_TEXT_BYTES)
        for text, code in (
            ("a" * (inbox.MAX_TEXT_BYTES + 1), "inbox_text_too_large"),
            ("é" * (inbox.MAX_TEXT_BYTES // 2 + 1), "inbox_text_too_large"),
            ("", "inbox_text_empty"),
            ("\ud800", "inbox_text_invalid"),
        ):
            with self.subTest(code=code, size=len(text)):
                with self.assertRaises(inbox.InboxError) as caught:
                    enqueue(self.store, text=text)
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(inbox.entry_names(self.store)), 1)

    def test_same_intent_same_key_and_id_other_target_other_id(self) -> None:
        first, second = enqueue(self.store), enqueue(self.store)
        self.assertEqual(first["idempotency_key"], second["idempotency_key"])
        self.assertEqual(first["record_id"], second["record_id"])
        self.assertNotEqual(first["entry"], second["entry"])
        a = enqueue(self.store, target_id="f-uno")
        b = enqueue(self.store, target_id="f-dos")
        self.assertNotEqual(a["idempotency_key"], b["idempotency_key"])
        self.assertNotEqual(a["idempotency_key"], first["idempotency_key"])
        self.assertNotEqual(
            inbox.record_id("facts", a["idempotency_key"]), inbox.record_id("facts", b["idempotency_key"])
        )
        self.assertNotIn("record_id", a)
        self.assertEqual(read_entry(self, a["entry"])["target_id"], "f-uno")
        # la clave por defecto es la de C0 sobre el escritor, kind, texto y target
        identity = c0.build_identity(self.project, AGENT_ENV)
        self.assertEqual(first["idempotency_key"], c0.derive_idempotency_key(identity, "fact", "recuerdo sobre quetzal"))
        self.assertEqual(
            a["idempotency_key"], c0.derive_idempotency_key(identity, "fact", "recuerdo sobre quetzal", "f-uno")
        )

    def test_given_key_is_kept_and_must_be_a_digest(self) -> None:
        self.assertEqual(enqueue(self.store, idempotency_key=KEY)["idempotency_key"], KEY)
        with self.assertRaises(inbox.InboxError) as caught:
            enqueue(self.store, idempotency_key="mi-clave")
        self.assertEqual(caught.exception.code, "inbox_idempotency_key_invalid")

    def test_invalid_kind_and_target_are_rejected_before_creating_the_inbox(self) -> None:
        for kwargs, code in (
            ({"kind": "evento"}, "inbox_kind_invalid"),
            ({"target_id": ""}, "inbox_target_invalid"),
            ({"target_id": "x" * 257}, "inbox_target_invalid"),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(inbox.InboxError) as caught:
                    enqueue(self.store, **kwargs)
                self.assertEqual(caught.exception.code, code)
        self.assertFalse(self.inbox.exists())


class UninitializedStoreTests(InboxCase):
    init_store = False

    def test_fails_at_the_preflight_without_creating_the_inbox(self) -> None:
        with self.assertRaises(IdentityError):
            enqueue(self.store)
        self.assertFalse(self.inbox.exists())


class KindResolutionTests(InboxCase):
    """ADENDA 1: el `kind` se resuelve al encolar leyendo el snapshot de CURRENT."""

    def entry_of(self, result: dict) -> dict:
        return read_entry(self, result["entry"])

    def test_without_target_defaults_to_fact_and_explicit_kind_is_flagged(self) -> None:
        plain = enqueue(self.store)
        self.assertEqual((plain["kind"], plain["kind_explicit"]), ("fact", False))
        for kind in inbox.KINDS:
            result = enqueue(self.store, kind=kind)
            self.assertEqual((result["kind"], result["kind_explicit"]), (kind, True))
            self.assertEqual(self.entry_of(result)["kind_explicit"], True)

    def test_target_takes_its_envelope_kind_or_the_one_of_its_legacy_stream(self) -> None:
        self.commit_record("f-con-sobre", text="x", an_kla_envelope={"kind": "decision"})
        self.commit_record("f-legado", text="y")
        self.commit_record("ep-legado", stream="episodes", text="z")
        expected = {"f-con-sobre": "decision", "f-legado": "fact", "ep-legado": "state"}
        identity = c0.build_identity(self.project, AGENT_ENV)
        for target, kind in expected.items():
            with self.subTest(target=target):
                result = enqueue(self.store, target_id=target)
                self.assertEqual((result["kind"], result["kind_explicit"]), (kind, False))
                entry = self.entry_of(result)
                self.assertEqual((entry["kind"], entry["kind_explicit"]), (kind, False))
                self.assertEqual(entry["envelope"]["kind"], kind)
                self.assertEqual(
                    entry["idempotency_key"],
                    c0.derive_idempotency_key(
                        identity, kind, "recuerdo sobre quetzal", target, "main" if kind == "state" else None
                    ),
                )

    def test_explicit_kind_wins_over_the_target(self) -> None:
        self.commit_record("ep-legado", stream="episodes", text="z")
        result = enqueue(self.store, target_id="ep-legado", kind="fact")
        self.assertEqual((result["kind"], result["kind_explicit"]), ("fact", True))

    def test_missing_inactive_or_ambiguous_target_falls_back_to_fact(self) -> None:
        self.commit_record("ep-viejo", stream="episodes", text="z", status="sustituida")
        self.commit_record("dup-id", stream="episodes", text="z")
        self.commit_record("dup-id", stream="facts", text="z")
        for target in ("no-existe", "ep-viejo", "dup-id"):
            with self.subTest(target=target):
                result = enqueue(self.store, target_id=target)
                self.assertEqual((result["kind"], result["kind_explicit"]), ("fact", False))

    def test_reader_gate_failure_falls_back_to_fact(self) -> None:
        """R1-07: el docstring promete que cualquier fallo de lectura cae en `fact`."""

        with mock.patch.object(self.store, "snapshot", side_effect=ReaderGateError("reader_gate_mode_reentry")):
            self.assertEqual(inbox.resolve_kind(self.store, None, "f-x"), ("fact", False))

    def test_unreadable_snapshot_falls_back_to_fact_without_writing(self) -> None:
        self.store.current_path.write_bytes(b"basura\n")
        self.assertEqual(inbox.resolve_kind(self.store, None, "f-x"), ("fact", False))
        self.assertFalse(self.inbox.exists())


if __name__ == "__main__":
    unittest.main()
