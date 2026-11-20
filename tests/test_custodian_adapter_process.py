"""ADR-0071, acceptance 3: the mandatory process tests of ``memoria/custodio-adaptador/v1``, with a real process.

The deadline (short by parameter, and the default fixed at 10 s), exit code other than 0, output that is not JSON, a noisy
standard error (several MiB), output over the cap, the death of the process group, and that the custodian's name never
reaches a path or a command line.  Plus the table: its shapes, the variable that replaces it and the one that cannot be read.
"""

from __future__ import annotations

import inspect
import json
import os
import stat
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from an_kla import custodian_adapter
from an_kla.anchors import AnchorRejected, validate_anchor
from an_kla.custodian_adapter import Adapters, TableError, load_table, parse_table

from tests.custodian_support import FakeCustodian
from tests.test_document_v2_write import DERIVATION, DOC_SHA, MANIFEST, QUOTE, response

SOURCE = {
    "kind": "document", "document_sha256": DOC_SHA, "locator": {"page": 188, "item_id": "i-13"},
    "derivation": {"custodian": "skopos", "derivation_id": DERIVATION, "manifest_sha256": MANIFEST, "modality": "native_text"},
}


class ProcessTests(unittest.TestCase):
    def call(self, scenario: dict[str, Any], timeout: float = 10.0) -> tuple[Any, FakeCustodian]:
        custodian = FakeCustodian(self)
        return custodian.adapters(scenario, timeout).call(SOURCE), custodian

    def test_a_good_answer(self) -> None:
        answer, custodian = self.call({"mode": "response", "response": response()})
        self.assertEqual((answer.failure, answer.response["document"], answer.called), (None, "known", True))
        self.assertEqual(custodian.log()["request"]["locator"], {"page": 188, "item_id": "i-13"})

    def test_a_short_deadline_by_parameter_kills_it(self) -> None:
        started = time.monotonic()
        answer, _ = self.call({"mode": "timeout"}, timeout=0.6)
        self.assertEqual(answer.failure, "timeout")
        self.assertLess(time.monotonic() - started, 6)  # the process sleeps 60 s: it was killed, not waited for

    def test_the_default_deadline_is_10_seconds(self) -> None:
        """Erratum 1, A7: a process test may pass a short deadline; this one fixes the value that rules."""
        self.assertEqual(custodian_adapter.TIMEOUT_SECONDS, 10)
        self.assertEqual(Adapters().timeout, 10)
        self.assertEqual(Adapters.for_store(mock.Mock(store_root="/nonexistent-store")).timeout, 10)

    def test_the_cap_is_8_mib(self) -> None:
        self.assertEqual(custodian_adapter.MAX_STDOUT_BYTES, 8 * 1024 * 1024)
        self.assertEqual(inspect.signature(custodian_adapter.run_process).parameters["limit"].default, 8 * 1024 * 1024)

    def test_each_failure_is_returned_never_raised(self) -> None:
        for scenario, failure in (
            ({"mode": "exit_nonzero"}, "exit_nonzero"), ({"mode": "bad_json"}, "bad_json"),
            ({"mode": "bad_schema"}, "invalid_response"), ({"mode": "raw", "raw": "[1, 2]"}, "bad_json"),
            ({"mode": "raw", "raw": '{"schema": "x", "schema": "y"}'}, "bad_json"),  # a repeated key is not JSON the contract knows
            ({"mode": "raw", "raw": '{"a": NaN}'}, "bad_json"),
            ({"mode": "raw", "raw": ""}, "bad_json"),
            ({"mode": "response", "response": {**response(), "extra": 1}}, "invalid_response"),
            ({"mode": "response", "response": {k: v for k, v in response().items() if k != "custody"}}, "invalid_response"),
        ):
            with self.subTest(scenario.get("raw", scenario["mode"])):
                answer, _ = self.call(scenario)
                self.assertEqual((answer.failure, answer.response, answer.called), (failure, None, True))

    def test_a_noisy_standard_error_is_discarded_and_does_not_block(self) -> None:
        started = time.monotonic()
        answer, _ = self.call({"mode": "noisy_stderr", "response": response()})  # 6 MiB on standard error
        self.assertEqual(answer.failure, None)
        self.assertLess(time.monotonic() - started, 8)

    def test_an_output_over_the_cap_is_a_failure(self) -> None:
        answer, _ = self.call({"mode": "huge_stdout"})  # 9 MiB
        self.assertEqual(answer.failure, "stdout_too_large")

    def test_the_process_group_dies_with_the_deadline(self) -> None:
        custodian = FakeCustodian(self)
        pid_file = custodian.dir / "hijo.pid"
        answer = custodian.adapters({"mode": "grandchild", "pid_file": str(pid_file)}, timeout=1.0).call(SOURCE)
        self.assertEqual(answer.failure, "timeout")
        pid = int(pid_file.read_text())
        for _ in range(40):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, 9)
            self.fail("the grandchild of the adapter survived its deadline")

    def test_a_program_that_cannot_be_started_is_adapter_error_not_an_exception(self) -> None:
        answer = Adapters({"skopos": ("/no/existe/adaptador",)}).call(SOURCE)
        self.assertEqual((answer.failure, answer.called), ("launch_failed", True))


class NameNeverReachesAPathOrACommandLineTests(unittest.TestCase):
    def test_a_custodian_named_like_an_existing_file_is_not_run(self) -> None:
        custodian = FakeCustodian(self)
        marker = custodian.dir / "se-ejecuto"
        script = "#!/bin/sh\ntouch " + str(marker) + "\n"
        decoys = [custodian.dir / "skopos", custodian.dir / "bin" / "skopos"]
        (custodian.dir / "bin").mkdir()
        for decoy in decoys:
            decoy.write_text(script)
            decoy.chmod(decoy.stat().st_mode | stat.S_IXUSR)
        other = FakeCustodian(self, name="otro")  # a table that has some custodian, but not this one
        adapters = Adapters(other.table({"mode": "response", "response": response()}))
        with mock.patch.dict(os.environ, {"PATH": f"{custodian.dir}:{custodian.dir / 'bin'}:" + os.environ["PATH"]}):
            self.assertIsNone(adapters.call(SOURCE))  # "no adapter", not a lookup by name
        self.assertFalse(marker.exists())
        self.assertFalse(other.called())

    def test_the_name_is_neither_in_argv_nor_in_the_request_and_the_environment_is_minimal(self) -> None:
        custodian = FakeCustodian(self)
        with mock.patch.dict(os.environ, {"AN_KLA_SECRETO": "no-debe-verse", "HOME": "/home/alguien"}):
            answer = custodian.adapters({"mode": "response", "response": response()}).call(SOURCE)
        self.assertIsNone(answer.failure)
        log = custodian.log()
        self.assertNotIn("skopos", log["argv"])
        self.assertNotIn("skopos", json.dumps(log["request"]))
        env = {k: v for k, v in log["env"].items() if k != "__CF_USER_TEXT_ENCODING"}  # macOS adds this one itself
        self.assertEqual(env, {"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        self.assertEqual(log["cwd"], "/")  # the adapter does not see the project's tree

    def test_a_name_with_path_characters_is_a_malformed_anchor(self) -> None:
        for name in ("../skopos", "a/b", "/etc/passwd", "Skopos", "skopos ", "", "-x", "x" * 33, ".", "skopos\n"):
            with self.subTest(name=name):
                anchor = {"schema": "memoria/ancla/v2", "quote": QUOTE, "source": {**SOURCE, "derivation": {**SOURCE["derivation"], "custodian": name}}}
                with self.assertRaises(AnchorRejected) as raised:
                    validate_anchor(anchor, "fact")
                self.assertEqual(raised.exception.code, "anchor_schema_invalid")
        for name in ("skopos", "a", "0x", "a-b_c", "x" * 32):
            anchor = {"schema": "memoria/ancla/v2", "quote": QUOTE, "source": {**SOURCE, "derivation": {**SOURCE["derivation"], "custodian": name}}}
            validate_anchor(anchor, "fact")

    def test_even_a_hand_made_bad_name_never_asks_the_table(self) -> None:
        source = {**SOURCE, "derivation": {**SOURCE["derivation"], "custodian": "../skopos"}}
        self.assertIsNone(Adapters({"../skopos": ("/bin/echo",), "skopos": ("/bin/echo",)}).call(source))


class TableTests(unittest.TestCase):
    def test_the_shape_of_the_table(self) -> None:
        good = {"skopos": {"argv": ["/usr/bin/python3", "-B", "/ruta/adaptador.py"]}}
        self.assertEqual(parse_table(good), {"skopos": ("/usr/bin/python3", "-B", "/ruta/adaptador.py")})
        for bad in ([], "x", {"skopos": []}, {"skopos": {}}, {"skopos": {"argv": []}}, {"skopos": {"argv": "python"}},
                    {"skopos": {"argv": ["relativo"]}}, {"skopos": {"argv": ["/x", 3]}}, {"skopos": {"argv": ["/x"], "shell": True}},
                    {"skopos": {"argv": ["/x", "a\0b"]}}, {"../x": {"argv": ["/x"]}}, {"Mayus": {"argv": ["/x"]}}):
            with self.subTest(bad=bad), self.assertRaises(TableError) as raised:
                parse_table(bad)
            self.assertEqual(str(raised.exception), "custodians_invalid_shape")

    def test_the_stores_table_the_variable_and_what_cannot_be_read(self) -> None:
        scratch = FakeCustodian(self).dir
        store = scratch / "store"
        store.mkdir()
        argv = ["/usr/bin/python3", "/x.py"]
        self.assertEqual(load_table(store, {}), {})  # no config: nothing configured
        (store / "config.json").write_text(json.dumps({"default_branch": "main"}))
        self.assertEqual(load_table(store, {}), {})  # a config without custodians: no adapter, not an error
        (store / "config.json").write_text(json.dumps({"custodians": {"skopos": {"argv": argv}}}))
        self.assertEqual(load_table(store, {}), {"skopos": tuple(argv)})
        other = scratch / "otra.json"
        other.write_text(json.dumps({"custodians": {"otro": {"argv": argv}}}))
        self.assertEqual(load_table(store, {"AN_KLA_CUSTODIANS": str(other)}), {"otro": tuple(argv)})  # replaces the whole
        for env, code in (
            ({"AN_KLA_CUSTODIANS": str(scratch / "no-existe.json")}, "custodians_unreadable"),
            ({"AN_KLA_CUSTODIANS": ""}, "custodians_unreadable"),
            ({"AN_KLA_CUSTODIANS": str(scratch)}, "custodians_unreadable"),
        ):
            with self.subTest(env=env), self.assertRaises(TableError) as raised:
                load_table(store, env)
            self.assertEqual(str(raised.exception), code)
        for content, code in (("{no", "custodians_invalid_json"), ("[]", "custodians_invalid_shape"),
                              ('{"custodians": []}', "custodians_invalid_shape"), ('{"nada": 1}', "custodians_invalid_shape")):
            other.write_text(content)
            with self.subTest(variable=content), self.assertRaises(TableError) as raised:
                load_table(store, {"AN_KLA_CUSTODIANS": str(other)})
            self.assertEqual(str(raised.exception), code)
            (store / "config.json").write_text(content)
            if content != '{"nada": 1}':  # a config.json without the key is "no adapters", not an error
                with self.subTest(store=content), self.assertRaises(TableError) as raised:
                    load_table(store, {})
                self.assertEqual(str(raised.exception), code)

    def test_an_unreadable_table_makes_every_custodian_adapter_error_with_no_process(self) -> None:
        adapters = Adapters.for_store(mock.Mock(store_root="/x"), {"AN_KLA_CUSTODIANS": "/no/existe.json"})
        self.assertEqual(adapters.config_error, "custodians_unreadable")
        for name in ("skopos", "otro"):  # even one nobody configured: the Operator did configure something
            source = {**SOURCE, "derivation": {**SOURCE["derivation"], "custodian": name}}
            answer = adapters.call(source)
            self.assertEqual((answer.failure, answer.called, answer.response), ("custodians_unreadable", False, None))


if __name__ == "__main__":
    unittest.main()
