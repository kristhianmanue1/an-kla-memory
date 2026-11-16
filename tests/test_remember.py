"""``remember`` (ADR-0063 D1 «Orden», D2 «Quién lo rellena», criterios 1 y 8 del lado de la orden).

Casi todo corre la orden real en un subproceso del CLI sobre un proyecto Git temporal.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from an_kla import inbox, inbox_drain, lock_order, remember as remember_module
from an_kla.schemas import schema_document
from an_kla.store import MemoryStore
from tests.inbox_support import AGENT_ENV, InboxCase, hold_flock
from tests.remember_support import cli, remember

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


def validate(result: dict) -> None:
    if jsonschema is not None:
        jsonschema.Draft202012Validator(schema_document("remember-result-v1")).validate(result)


class CliCase(InboxCase):
    def read_texts(self) -> list[str]:
        return [str(r["text"]) for r in MemoryStore(self.project).snapshot().records["facts"]]


class OneCallTests(CliCase):
    def test_criterion_1_one_invocation_envelope_and_retrieve(self) -> None:
        rc, result = remember(self.project, "el café de la oficina es de cebada")
        validate(result)
        self.assertEqual((rc, result["state"], result["outcome"]), (0, "committed", "known"))
        self.assertEqual((result["stream"], result["operation"], result["kind"]), ("facts", "add", "fact"))
        record = next(r for r in MemoryStore(self.project).snapshot().records["facts"] if r["id"] == result["record_id"])
        envelope = record["an_kla_envelope"]
        self.assertEqual(envelope["schema"], "an-kla/record-envelope-v1")
        self.assertEqual(envelope["writer"]["agent"]["name"], AGENT_ENV["AN_KLA_AGENT_NAME"])
        self.assertEqual(envelope["writer"]["schema"], "memoria/identidad/v1")
        self.assertEqual(envelope["enqueued_at"], result["enqueued_at"])
        self.assertEqual(envelope["time_source"], "host-clock/v1")
        self.assertEqual(set(record) - {"verified_at"}, {"id", "text", "an_kla_envelope"})
        found = cli(self.project, "retrieve", "--query", "cebada", "--budget", "2000")
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertIn("el café de la oficina es de cebada", found.stdout)

    def test_the_text_is_the_only_required_datum_and_state_goes_to_episodes(self) -> None:
        rc, result = remember(self.project, "estado de la sesión", "--kind", "state")
        self.assertEqual((rc, result["state"], result["stream"], result["kind"]), (0, "committed", "episodes", "state"))
        rc, result = remember(self.project, "se decidió usar flock", "--kind", "decision")
        self.assertEqual((result["stream"], result["kind"]), ("facts", "decision"))

    def test_text_and_text_file_are_exclusive_and_one_is_required(self) -> None:
        for args in ((), ("--text", "a", "--text-file", "-")):
            with self.subTest(args=args):
                done = cli(self.project, "remember", *args)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
        done = cli(self.project, "remember", "--text", "desde argv")
        self.assertEqual(json.loads(done.stdout)["state"], "committed")

    def test_text_file_from_a_path_keeps_the_text_verbatim(self) -> None:
        path = self.project / "nota.txt"
        path.write_bytes("línea uno\nlínea dos\n".encode())
        done = cli(self.project, "remember", "--text-file", str(path))
        self.assertEqual(json.loads(done.stdout)["state"], "committed")
        self.assertIn("línea uno\nlínea dos\n", self.read_texts())

    def test_input_errors_have_stable_codes_and_no_paths(self) -> None:
        missing = self.project / "no-existe.txt"
        cases = [
            (("--text-file", str(missing)), None, "remember_text_file_unreadable"),
            (("--text", ""), None, "inbox_text_empty"),
            (("--text", "x" * 70000), None, "inbox_text_too_large"),
            (("--text", "ok", "--idempotency-key", ""), None, "remember_idempotency_key_invalid"),
            (("--text", "ok", "--idempotency-key", "k" * 257), None, "remember_idempotency_key_invalid"),
        ]
        for args, stdin, code in cases:
            with self.subTest(args=args[:2]):
                done = cli(self.project, "remember", *args, stdin=stdin)
                if code is not None:
                    self.assertIn(code, done.stderr)
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(done.stdout, "")
                self.assertNotIn(str(self.project), done.stderr)
                self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(inbox.entry_names(MemoryStore(self.project)), [])

    def test_invalid_utf8_from_a_file_is_a_stable_code(self) -> None:
        path = self.project / "mal.txt"
        path.write_bytes(b"\xff\xfe\xfa")
        done = cli(self.project, "remember", "--text-file", str(path))
        self.assertIn("remember_text_invalid", done.stderr)
        self.assertNotIn(str(self.project), done.stderr)

    def test_size_limit_applies_to_the_file_without_reading_everything(self) -> None:
        stream = io.BytesIO(b"a" * (inbox.MAX_TEXT_BYTES + 1))
        with self.assertRaises(remember_module.RememberError) as caught:
            remember_module.read_text_file("-", stream)
        self.assertEqual(caught.exception.code, "inbox_text_too_large")
        self.assertLessEqual(stream.tell(), inbox.MAX_TEXT_BYTES + 1)


class IdentityEnvironmentTests(CliCase):
    def test_agent_cli_is_mandatory_and_nothing_is_enqueued(self) -> None:
        done = cli(self.project, "remember", "--text", "sin cli", agent=False)
        self.assertEqual(done.returncode, 1)
        self.assertIn("identity_env_missing", done.stderr)
        self.assertIn("AN_KLA_AGENT_CLI", done.stderr)
        self.assertFalse(self.inbox.exists())

    def test_sentinels_fill_what_the_launcher_does_not_set(self) -> None:
        rc, result = remember(self.project, "con centinelas", agent=False, env={"AN_KLA_AGENT_CLI": "codex"})
        self.assertEqual((rc, result["state"]), (0, "committed"))
        record = next(r for r in MemoryStore(self.project).snapshot().records["facts"] if r["id"] == result["record_id"])
        writer = record["an_kla_envelope"]["writer"]
        self.assertEqual(writer["agent"]["name"], "sin-nombre")
        self.assertEqual(writer["agent"]["model"], "desconocido")
        self.assertEqual(writer["agent"]["role"], "desconocido")
        self.assertEqual(writer["session"]["id"], "codex:sin-sesion")

    def test_a_present_value_that_violates_c0_fails_and_is_never_replaced(self) -> None:
        for variable, value in (("AN_KLA_AGENT_NAME", "Nombre Inválido"), ("AN_KLA_AGENT_ROLE", "jefe")):
            with self.subTest(variable=variable):
                done = cli(self.project, "remember", "--text", "x", env={variable: value})
                self.assertEqual(done.returncode, 1)
                self.assertIn("identity_env_invalid", done.stderr)
                self.assertIn(variable, done.stderr)
                self.assertNotIn(value, done.stderr)
        self.assertFalse(self.inbox.exists())

    def test_without_a_git_repo_it_is_identity_repo_unavailable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sin-git-") as temp:
            project = Path(temp).resolve()
            self.assertEqual(cli(project, "init").returncode, 0)
            done = cli(project, "remember", "--text", "x")
            self.assertIn("identity_repo_unavailable", done.stderr)
            self.assertIn("plan-write", done.stderr)


class IdempotencyKeyTests(CliCase):
    def test_free_text_is_hashed_and_a_sha256_key_is_used_as_is(self) -> None:
        free = remember_module.normalize_idempotency_key("mi clave")
        self.assertEqual(free, "sha256:" + hashlib.sha256("mi clave".encode()).hexdigest())
        digest = "sha256:" + "ab" * 32
        self.assertEqual(remember_module.normalize_idempotency_key(digest), digest)
        self.assertEqual(remember_module.normalize_idempotency_key("k" * 256)[:7], "sha256:")
        for bad in ("", "k" * 257, None, 3):
            with self.subTest(bad=bad), self.assertRaises(remember_module.RememberError):
                remember_module.normalize_idempotency_key(bad)

    def test_the_given_key_decides_the_id_and_a_retry_does_not_duplicate(self) -> None:
        first_rc, first = remember(self.project, "uno", "--idempotency-key", "clave-de-prueba")
        _, second = remember(self.project, "uno", "--idempotency-key", "clave-de-prueba")
        _, third = remember(self.project, "otro texto", "--idempotency-key", "clave-de-prueba")
        self.assertEqual(first["idempotency_key"], remember_module.normalize_idempotency_key("clave-de-prueba"))
        self.assertEqual(first["state"], "committed")
        self.assertEqual((second["state"], second.get("already_committed")), ("committed", True))
        self.assertEqual(second["record_id"], first["record_id"])
        self.assertEqual(third["state"], "rejected")  # misma clave, otro payload
        self.assertEqual(third["code"], "remember_id_collision")
        self.assertEqual(self.read_texts().count("uno"), 1)
        self.assertEqual(first_rc, 0)

    def test_same_text_without_a_key_is_the_same_intention(self) -> None:
        _, first = remember(self.project, "repetido")
        _, second = remember(self.project, "repetido")
        self.assertEqual(second["record_id"], first["record_id"])
        self.assertEqual(self.read_texts().count("repetido"), 1)
        self.assertEqual(inbox.entry_names(MemoryStore(self.project)), [])


class OutcomeTests(CliCase):
    def test_rejected_carries_the_code_and_exits_3(self) -> None:
        rc, result = remember(self.project, "sustituye algo", "--supersedes", "f-no-existe")
        validate(result)
        self.assertEqual((rc, result["state"], result["code"]), (3, "rejected", "invalid_supersede_target"))
        self.assertEqual(result["rejected"]["count"], 1)
        self.assertEqual(result["rejected"]["entries"][0]["entry"], result["entry"])
        status = json.loads(cli(self.project, "inbox", "status").stdout)
        self.assertEqual(status["rejected"]["count"], 1)
        self.assertEqual(status["pending"]["count"], 0)

    def test_a_policy_skip_is_rejected_with_its_reason_codes(self) -> None:
        with mock.patch.object(inbox_drain, "plan_batch", side_effect=inbox_drain.BatchFail("remember_policy_skip", ["authority_scope_mismatch"], 1)):
            result = remember_module.remember(self.store, "x", env=AGENT_ENV)
        self.assertEqual((result["state"], result["code"], result["reason_codes"]), ("rejected", "remember_policy_skip", ["authority_scope_mismatch"]))

    def test_busy_write_lock_is_queued_and_a_retry_does_not_duplicate(self) -> None:
        holder = hold_flock(Path(self.store.root) / ".write.lock")
        try:
            rc, queued = remember(self.project, "en cola", "--idempotency-key", "k1")
        finally:
            InboxCase.release(holder)
        validate(queued)
        self.assertEqual((rc, queued["state"], queued["outcome"]), (0, "queued", "known"))
        self.assertNotIn("drain_error", queued)
        self.assertNotIn("revision", queued)
        self.assertEqual(inbox.entry_names(self.store), [queued["entry"]])
        rc, retried = remember(self.project, "en cola", "--idempotency-key", "k1")
        self.assertEqual((rc, retried["state"]), (0, "committed"))
        self.assertEqual(self.read_texts().count("en cola"), 1)
        self.assertEqual(inbox.entry_names(self.store), [])

    def test_queued_with_supersedes_declares_the_resolution_pending(self) -> None:
        self.commit_record("f-viejo", text="viejo")
        holder = hold_flock(Path(self.store.root) / ".write.lock")
        try:
            rc, queued = remember(self.project, "nuevo", "--supersedes", "f-viejo")
        finally:
            InboxCase.release(holder)
        validate(queued)
        self.assertEqual((rc, queued["state"], queued["resolution"]), (0, "queued", "pending"))

    def test_a_drain_that_aborts_with_a_known_result_is_queued_plus_drain_error(self) -> None:
        with mock.patch.object(self.store, "_write_segment", side_effect=OSError(5, "io")):
            result = remember_module.remember(self.store, "no se pudo", env=AGENT_ENV)
        validate(result)
        self.assertEqual((result["state"], result["outcome"], result["drain_error"]), ("queued", "known", "storage_io_failed"))
        self.assertEqual(len(inbox.entry_names(self.store)), 1)
        retried = remember_module.remember(self.store, "no se pudo", env=AGENT_ENV)
        self.assertEqual(retried["state"], "committed")
        self.assertEqual(self.read_texts().count("no se pudo"), 1)

    def test_an_unknown_outcome_is_queued_with_outcome_unknown_and_the_retry_leaves_one_record(self) -> None:
        real_replace, broken = self.store._replace_current, {"on": False}

        def replace(identifier):
            real_replace(identifier)
            broken["on"] = True

        real_read = self.store.read_current

        def read():
            if broken["on"]:
                raise OSError(5, "io")
            return real_read()

        with mock.patch.object(self.store, "_replace_current", replace), mock.patch.object(self.store, "read_current", read):
            result = remember_module.remember(self.store, "dudoso", env=AGENT_ENV)
        broken["on"] = False
        validate(result)
        self.assertEqual((result["state"], result["outcome"]), ("queued", "unknown"))
        retried = remember_module.remember(self.store, "dudoso", env=AGENT_ENV)
        self.assertEqual(retried["state"], "committed")
        self.assertEqual(self.read_texts().count("dudoso"), 1)
        self.assertEqual(inbox.read_status(self.store)["pending"]["count"], 0)

    def test_the_cli_exit_code_for_an_unknown_outcome_is_3(self) -> None:
        from an_kla.__main__ import pending_outcome_reason
        from argparse import Namespace

        args = Namespace(command="remember")
        self.assertEqual(pending_outcome_reason(args, {"state": "queued", "outcome": "unknown"}), "remember_outcome_not_firm")
        self.assertEqual(pending_outcome_reason(args, {"state": "rejected", "outcome": "known"}), "remember_rejected")
        for state in ({"state": "committed", "outcome": "known"}, {"state": "queued", "outcome": "known", "drain_error": "x"}):
            self.assertIsNone(pending_outcome_reason(args, state))

    def test_a_failure_of_the_drain_phase_after_enqueue_is_queued_never_a_trace(self) -> None:
        for error in (OSError(28, "ENOSPC /ruta/secreta"), inbox.InboxError("inbox_unsafe_path")):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(remember_module, "drain", side_effect=error):
                    result = remember_module.remember(self.store, f"t-{type(error).__name__}", env=AGENT_ENV)
                self.assertEqual(result["state"], "queued")
                self.assertRegex(result["drain_error"], r"^[a-z0-9_:.-]+$")
                self.assertNotIn("/ruta", json.dumps(result))

    def test_enqueue_oserror_is_storage_io_failed_without_paths(self) -> None:
        with mock.patch.object(inbox, "_publish", side_effect=OSError(28, "No space left", str(self.project))):
            with self.assertRaises(remember_module.RememberError) as caught:
                remember_module.remember(self.store, "sin espacio", env=AGENT_ENV)
        self.assertEqual(caught.exception.code, "storage_io_failed")
        self.assertNotIn(str(self.project), f"{caught.exception} {caught.exception.detail}")
        self.assertEqual(inbox.entry_names(self.store), [])


class DisputeVisibilityTests(CliCase):
    def test_supersede_of_own_and_visibility_in_the_answer(self) -> None:
        _, first = remember(self.project, "versión uno")
        _, second = remember(self.project, "versión dos", "--supersedes", first["record_id"])
        validate(second)
        self.assertEqual((second["state"], second["operation"], second["superseded"]), ("committed", "supersede", first["record_id"]))
        self.assertNotIn("disputed", second)

    def test_dispute_of_a_foreign_fact_in_the_answer(self) -> None:
        self.commit_record("f-legado", text="hecho legado sin sobre")
        rc, result = remember(self.project, "yo lo veo distinto", "--supersedes", "f-legado")
        validate(result)
        self.assertEqual((rc, result["state"], result["operation"]), (0, "committed", "add"))
        self.assertEqual(result["disputed"]["target_id"], "f-legado")
        self.assertNotIn("superseded", result)


class LockOrderTests(CliCase):
    def test_criterion_9_remember_never_asks_for_the_inbox_lock_holding_a_later_lock(self) -> None:
        seen: list[tuple[str, ...]] = []
        real = lock_order.require_inbox_allowed

        def spy(store=None):
            seen.append(lock_order.held())
            return real(store)

        with mock.patch.object(lock_order, "require_inbox_allowed", spy):
            self.assertEqual(remember_module.remember(self.store, "uno", env=AGENT_ENV)["state"], "committed")
            self.assertEqual(remember_module.remember(self.store, "dos", env=AGENT_ENV)["state"], "committed")
        self.assertTrue(seen)
        for held in seen:
            self.assertFalse({lock_order.IDENTITY, lock_order.WRITE} & set(held), held)

    def test_remember_under_a_later_lock_fails_closed_before_enqueueing(self) -> None:
        with lock_order.holding(lock_order.WRITE):
            with self.assertRaises(lock_order.LockOrderError):
                remember_module.remember(self.store, "no", env=AGENT_ENV)
        self.assertEqual(inbox.entry_names(self.store), [])


class SurfaceTests(unittest.TestCase):
    def test_help_capabilities_and_schema_list_only_gain_entries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="superficie-") as temp:
            project = Path(temp).resolve()
            help_text = cli(project, "remember", "--help").stdout
            for needle in ("--text-file", "ps", "256", "sha256:<64 hex>", "AN_KLA_AGENT_CLI", "sin-nombre"):
                self.assertIn(needle, help_text)
            capabilities = json.loads(cli(project, "capabilities").stdout)
            self.assertIn("an-kla/remember-result-v1", json.dumps(capabilities))
            self.assertIn("remember", capabilities["cli_error_surface"]["pending_outcome"]["cases"])
            listing = cli(project, "schema", "list").stdout
            self.assertIn("remember-result-v1", listing)
            shown = json.loads(cli(project, "schema", "show", "remember-result-v1").stdout)
            self.assertEqual(shown["$id"], "urn:an-kla:schema:remember-result:v1")
            self.assertIn("remember", cli(project, "--help").stdout)

    def test_the_mcp_source_is_untouched_by_this_phase(self) -> None:
        """`tools/list` no cambia: el golden `mcp.tools_list` de `test_legacy_store_byte_identity` lo comprueba;
        aquí, que el módulo del MCP no conoce `remember`."""

        source = (Path(__file__).resolve().parents[1] / "an_kla" / "mcp.py").read_text(encoding="utf-8")
        self.assertNotIn("remember", source)


if __name__ == "__main__":
    unittest.main()
