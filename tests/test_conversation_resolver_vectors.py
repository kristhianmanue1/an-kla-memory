"""ADR-0073, acceptance 1: the 31 cases of ``memoria/conversacion-resolutor/v1`` with a resolver that is a **real process**.

The script (``fixtures/custodian_adapter_fake.py``, the same one of the document adapter) answers what each case says or fails as it says
(``none``, ``timeout``, ``bad_json``, ``failure_object``, ``exit_nonzero``); every ``expect`` field is exact, ``resolver_called`` included
(what the decision says and whether the process was started, with the request it received) and ``served`` (``new`` or ``stored``).
Acceptance 2 (S01–S13 of ``ancla/v1``, read with erratum 6) is ``test_anchors_vectors.ConversationVectors``, which this change leaves untouched.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from an_kla.anchors_conversation_check import evaluate, served_after
from an_kla.conversation_resolver import decide_verify

from tests.custodian_support import FakeCustodian

FIXTURES = Path(__file__).parent / "fixtures" / "conversacion-resolutor-v1"
PINNED = "1e9187a924f30fd7c3bed789487a3879f66d16f70f85efd0b08a7f1768de7e78"
SESSION = "claude-code:0a92bdfb"
QUOTE = "Adelante con el cambio de puerto del servidor de quetzal, a 8081."
AT = "2026-11-20T10:00:00.000000Z"
FAILURES = {"timeout": "timeout", "bad_json": "bad_json", "failure_object": "bad_schema", "exit_nonzero": "exit_nonzero"}


def load_cases() -> list[dict[str, Any]]:
    raw = (FIXTURES / "vectores.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED:
        raise AssertionError(f"vectores.json: sha256 {digest} is not the one the contract froze")
    return json.loads(raw)["cases"]


class VectorTests(unittest.TestCase):
    def test_the_vectors_are_the_frozen_31(self) -> None:
        cases = load_cases()
        self.assertEqual(len(cases), 31)
        self.assertEqual(sorted(c["id"] for c in cases), sorted([f"C{n:02d}" for n in list(range(1, 18)) + list(range(20, 34))]))

    def run_case(self, case: dict[str, Any]) -> tuple[dict[str, Any], str, FakeCustodian]:
        custodian = FakeCustodian(self)
        resolver = case["resolver"]
        if resolver == "none":
            scenario = None
        elif isinstance(resolver, dict):
            scenario = {"mode": "response", "response": resolver}
        else:
            scenario = {"mode": FAILURES[resolver]}
        adapters = custodian.resolver_adapters(scenario, timeout=1.0 if resolver == "timeout" else 10.0)
        anchor = {"quote": QUOTE, "quote_sha256": hashlib.sha256(QUOTE.encode()).hexdigest(),
                  "source": {"kind": "conversation", "session": SESSION, **case["anchor"]}}
        prior = None
        if case["anchor"]["resolution"] == "resolved":  # the anchor as served: what a verify is asked about
            prior = {"resolution": "resolved", "turn_id": case["anchor"]["turn_id"], "seal": case["anchor"]["seal"]}
        out = evaluate(anchor, prior, adapters, AT)
        conclusive_before = None
        if case["stored_conclusive"]:
            conclusive_before = {**decide_verify(case["anchor"]["turn_id"], case["anchor"]["seal"], {
                "session": "known", "seal": "match", "quote": "found", "speaker": "user", "reason": None, "schema": "memoria/conversacion-resolutor/v1"}), "checked_at": AT}
        return out, served_after(conclusive_before, out)[0], custodian

    def test_the_31_cases(self) -> None:
        for case in load_cases():
            with self.subTest(case["id"], note=case["note"]):
                out, served, custodian = self.run_case(case)
                for key, wanted in case["expect"].items():
                    if key == "resolver_called":
                        self.assertEqual((out["resolver_called"], custodian.called()), (wanted, wanted is not None), key)
                    elif key == "served":
                        self.assertEqual(served, wanted, key)
                    else:
                        self.assertEqual(out[key], wanted, key)

    def test_what_the_resolver_receives(self) -> None:
        """The request carries the session of the anchor, the quote and its sha256 (and, for ``verify``, ``turn_id`` and ``seal``)."""
        by_id = {c["id"]: c for c in load_cases()}
        _, _, resolve = self.run_case(by_id["C01"])
        request = resolve.log()["request"]
        self.assertEqual((request["op"], request["session"], request["quote"], request["quote_sha256"]), ("resolve", SESSION, QUOTE, hashlib.sha256(QUOTE.encode()).hexdigest()))
        self.assertNotIn("turn_id", request)
        _, _, verify = self.run_case(by_id["C20"])
        request = verify.log()["request"]
        self.assertEqual((request["op"], request["turn_id"], request["seal"]), ("verify", "claude-code:msg-0042", "m1:" + "ab" * 32))
        self.assertNotIn("skopos", json.dumps(request))  # the custodian's name never travels in the request


if __name__ == "__main__":
    unittest.main()
