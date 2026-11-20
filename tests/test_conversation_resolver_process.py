"""ADR-0073, acceptance 3: the process tests of the conversation resolver, with a real process, and the form of its configuration.

Deadline (short by parameter; the default is 10 s), exit code other than 0, output that is not JSON, the failure object, a noisy standard error
(6 MiB), an output over the 8 MiB cap, and that the custodian's name reaches neither a path nor the command line nor the request.  Plus the
form and the coherence checks of the answer (a closed form: exactly its keys) and the single resolver of the configuration.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from typing import Any
from unittest import mock

from an_kla import custodian_adapter
from an_kla.conversation_resolver import resolve_request, validate_resolve, validate_verify
from an_kla.custodian_adapter import Adapters, TableError, load_config, load_table

from tests.custodian_support import FakeCustodian
from tests.test_conversation_resolver_e2e import QUOTE, SEAL, TURN, pending, resolved, verify

REQUEST = resolve_request("claude-code:0a92bdfb", QUOTE, "0" * 64)


class ProcessTests(unittest.TestCase):
    def call(self, scenario: dict[str, Any] | None, timeout: float = 10.0) -> tuple[Any, FakeCustodian]:
        custodian = FakeCustodian(self)
        return custodian.resolver_adapters(scenario, timeout).call_resolver(REQUEST, validate_resolve), custodian

    def test_a_good_answer(self) -> None:
        answer, custodian = self.call(resolved())
        self.assertEqual((answer.failure, answer.response["resolution"], answer.called), (None, "resolved", True))
        self.assertEqual(custodian.log()["request"]["op"], "resolve")

    def test_no_resolver_is_none(self) -> None:
        self.assertIsNone(Adapters().call_resolver(REQUEST, validate_resolve))

    def test_a_short_deadline_kills_it_and_the_default_is_10_seconds(self) -> None:
        started = time.monotonic()
        answer, _ = self.call({"mode": "timeout"}, timeout=0.6)
        self.assertEqual(answer.failure, "timeout")
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual((custodian_adapter.TIMEOUT_SECONDS, Adapters().timeout), (10, 10))

    def test_each_failure_is_returned_never_raised(self) -> None:
        for scenario, failure in (
            ({"mode": "exit_nonzero"}, "exit_nonzero"), ({"mode": "bad_json"}, "bad_json"), ({"mode": "bad_schema"}, "invalid_response"),  # {"schema": "invalid"}
            ({"mode": "raw", "raw": "[1]"}, "bad_json"), ({"mode": "raw", "raw": '{"schema": "x", "schema": "y"}'}, "bad_json"),
            ({"mode": "response", "response": {**resolved()["response"], "extra": 1}}, "invalid_response"),
            ({"mode": "response", "response": {k: v for k, v in resolved()["response"].items() if k != "tail"}}, "invalid_response"),
        ):
            with self.subTest(scenario.get("raw", scenario["mode"])):
                answer, _ = self.call(scenario)
                self.assertEqual((answer.failure, answer.response, answer.called), (failure, None, True))

    def test_a_noisy_standard_error_and_an_output_over_the_cap(self) -> None:
        answer, _ = self.call({"mode": "noisy_stderr", "response": resolved()["response"]})  # 6 MiB on standard error
        self.assertIsNone(answer.failure)
        answer, _ = self.call({"mode": "huge_stdout"})  # 9 MiB
        self.assertEqual(answer.failure, "stdout_too_large")

    def test_the_custodian_name_never_reaches_argv_the_request_or_a_path(self) -> None:
        custodian = FakeCustodian(self)
        with mock.patch.dict(os.environ, {"AN_KLA_SECRETO": "no-debe-verse"}):
            answer = custodian.resolver_adapters(resolved()).call_resolver(REQUEST, validate_resolve)
        self.assertIsNone(answer.failure)
        log = custodian.log()
        self.assertNotIn("skopos", log["argv"])
        self.assertNotIn("skopos", json.dumps(log["request"]))
        self.assertEqual({k: v for k, v in log["env"].items() if k != "__CF_USER_TEXT_ENCODING"}, {"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        self.assertEqual(log["cwd"], "/")


class FormTests(unittest.TestCase):
    def test_a_closed_form_and_coherence_for_resolve(self) -> None:
        good = resolved()["response"]
        self.assertIsNone(validate_resolve(good))
        self.assertIsNone(validate_resolve(pending()["response"]))
        bad = (
            {**good, "speaker": "pasted"}, {**good, "seal": None}, {**good, "turn_id": None}, {**good, "match": None}, {**good, "candidates": {"user": 0, "pasted": 0, "other": 0}},
            {**good, "candidates": {"user": 1, "pasted": 0}}, {**good, "candidates": {"user": 1, "pasted": 0, "other": True}}, {**good, "reason": "tail_open"},
            {**good, "resolution": "not_found", "turn_id": None, "seal": None, "speaker": None, "match": None},  # not_found with the tail open
            {**good, "resolution": "not_found", "tail": "closed", "turn_id": None, "seal": None, "speaker": None, "match": None, "candidates": {"user": 0, "pasted": 1, "other": 0}},
            {**pending()["response"], "candidates": {"user": 1, "pasted": 0, "other": 0}},  # pending but counts a user message
            {**pending("origin_unreadable")["response"], "tail": "closed"},
            {**pending("session_unavailable")["response"]},  # session known with session_unavailable
            {**pending()["response"], "session": "unknown"}, {**good, "extra": 1}, {"schema": "invalid", "error": "bad_request"}, {**good, "schema": "otro"}, {**good, "speaker": "robot"},
        )
        for index, response in enumerate(bad):
            with self.subTest(index):
                self.assertIsNotNone(validate_resolve(response))
        unavailable = {**pending()["response"], "session": "unknown", "reason": "session_unavailable", "tail": None}
        self.assertIsNone(validate_resolve(unavailable))
        self.assertIsNotNone(validate_resolve({**unavailable, "tail": "open"}))

    def test_a_closed_form_and_coherence_for_verify(self) -> None:
        self.assertIsNone(validate_verify(verify()["response"]))
        self.assertIsNone(validate_verify(verify(seal="turn_missing", quote="unknown", speaker=None)["response"]))
        self.assertIsNone(validate_verify(verify(session="unknown", seal="unknown", quote="unknown", speaker=None, reason="session_unavailable")["response"]))
        for response in (
            verify(seal="turn_missing", quote="found")["response"], verify(seal="turn_missing", quote="unknown", speaker="user")["response"],  # C31
            verify(session="unknown", seal="match", quote="unknown", speaker=None, reason="session_unavailable")["response"],
            verify(quote="unknown")["response"], {**verify()["response"], "extra": 1}, verify(speaker="robot")["response"], verify(reason="session_unavailable")["response"],
        ):
            with self.subTest(str(response)[:60]):
                self.assertIsNotNone(validate_verify(response))

    def test_q01_a_known_session_and_an_existing_message_need_a_speaker(self) -> None:
        """Q-01: ``speaker`` is null only with ``session: unknown`` or ``seal: turn_missing``; with ``match``, ``mismatch`` or ``unknown`` it is a voice."""
        for seal in ("match", "mismatch", "unknown"):
            for quote in ("found", "absent"):
                with self.subTest(seal=seal, quote=quote):
                    self.assertIsNotNone(validate_verify(verify(seal=seal, quote=quote, speaker=None)["response"]))
                    self.assertIsNone(validate_verify(verify(seal=seal, quote=quote, speaker="user")["response"]))
        self.assertIsNone(validate_verify(verify(seal="turn_missing", quote="unknown", speaker=None)["response"]))  # the two exceptions stay
        self.assertIsNone(validate_verify(verify(session="unknown", seal="unknown", quote="unknown", speaker=None, reason="session_unavailable")["response"]))

    def test_q01_with_a_real_process_a_verify_without_speaker_is_resolver_error(self) -> None:
        custodian = FakeCustodian(self)
        answer = custodian.resolver_adapters(verify(speaker=None)).call_resolver(REQUEST, validate_verify)
        self.assertEqual((answer.failure, answer.response, answer.called), ("invalid_response", None, True))
        good = custodian.resolver_adapters(verify()).call_resolver(REQUEST, validate_verify)
        self.assertIsNone(good.failure)

    def test_q02_a_pending_answer_is_coherent_with_its_reason(self) -> None:
        """Q-02: ``tail_open`` requires ``tail: open``; ``only_in_other_voice`` requires ``candidates.pasted + candidates.other >= 1``."""
        base = pending()["response"]
        self.assertIsNone(validate_resolve(base))  # tail_open, tail open
        self.assertIsNotNone(validate_resolve({**base, "tail": "closed"}))
        other = pending("only_in_other_voice")["response"]
        self.assertIsNone(validate_resolve(other))
        self.assertIsNone(validate_resolve({**other, "tail": "closed"}))  # valid with the session closed: never ``not_found``
        self.assertIsNone(validate_resolve({**other, "candidates": {"user": 0, "pasted": 1, "other": 0}}))
        self.assertIsNotNone(validate_resolve({**other, "candidates": {"user": 0, "pasted": 0, "other": 0}}))
        for scenario in ({**pending(), "response": {**base, "tail": "closed"}}, {**pending("only_in_other_voice"), "response": {**other, "candidates": {"user": 0, "pasted": 0, "other": 0}}}):
            answer = FakeCustodian(self).resolver_adapters(scenario).call_resolver(REQUEST, validate_resolve)
            self.assertEqual((answer.failure, answer.response), ("invalid_response", None))


class ConfigurationTests(unittest.TestCase):
    def test_a_single_resolver_with_its_custodian_and_argv(self) -> None:
        scratch = FakeCustodian(self).dir
        argv = ["/usr/bin/python3", "/ruta/resolutor.py"]
        (scratch / "tabla.json").write_text(json.dumps({"custodians": {"skopos": {"argv": argv}}, "conversation_resolver": {"custodian": "skopos", "argv": argv}}))
        table, resolver = load_config(scratch, {"AN_KLA_CUSTODIANS": str(scratch / "tabla.json")})
        self.assertEqual((list(table), resolver), (["skopos"], ("skopos", tuple(argv))))
        (scratch / "solo.json").write_text(json.dumps({"conversation_resolver": {"custodian": "skopos", "argv": argv}}))
        self.assertEqual(load_config(scratch, {"AN_KLA_CUSTODIANS": str(scratch / "solo.json")}), ({}, ("skopos", tuple(argv))))
        self.assertEqual(load_table(scratch, {"AN_KLA_CUSTODIANS": str(scratch / "solo.json")}), {})
        (scratch / "config.json").write_text(json.dumps({"default_branch": "main"}))
        self.assertEqual(load_config(scratch, {}), ({}, None))  # no resolver: nothing is called
        for bad in ({"conversation_resolver": {"argv": argv}}, {"conversation_resolver": {"custodian": "skopos"}}, {"conversation_resolver": {"custodian": "../x", "argv": argv}},
                    {"conversation_resolver": {"custodian": "skopos", "argv": ["relativo"]}}, {"conversation_resolver": {"custodian": "skopos", "argv": argv, "shell": True}},
                    {"conversation_resolver": []}, {"conversation_resolver": {"custodian": "skopos", "argv": []}}):
            (scratch / "config.json").write_text(json.dumps(bad))
            with self.subTest(bad=bad), self.assertRaises(TableError) as raised:
                load_config(scratch, {})
            self.assertEqual(str(raised.exception), "custodians_invalid_shape")

    def test_an_unreadable_file_is_resolver_error_for_the_resolver_too(self) -> None:
        adapters = Adapters.for_store(mock.Mock(store_root="/x"), {"AN_KLA_CUSTODIANS": "/no/existe.json"})
        answer = adapters.call_resolver(REQUEST, validate_resolve)
        self.assertEqual((answer.failure, answer.called, adapters.resolver_state()), ("custodians_unreadable", False, "unreadable"))


if __name__ == "__main__":
    unittest.main()
