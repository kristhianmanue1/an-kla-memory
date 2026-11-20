"""ADR-0071, acceptance 1: the 61 exigible cases of ``memoria/ancla/v2`` with an adapter that is a **real process**.

The script (``fixtures/custodian_adapter_fake.py``) answers what each case says or fails as it says (``none``,
``exit_nonzero``, ``timeout``, ``bad_json``, ``bad_schema``), and every ``expect`` field is exact, ``adapter_called``
included (observed twice: what the decision says and whether the process was ever started).

**Declared:** D01–D18 of ``memoria/ancla/v1`` are *replaced* by these cases (README of v2; see ``test_anchors_vectors``), and
X14 is *not exigible* (erratum 2 replaces it with E11: its response was incoherent, ``manifest: mismatch`` with ``derivation:
current``).  The two cases that name an implementation other than this one (X71, no ``document`` support; X72, only v1) are
run as what they say: X71 with the ``kind_not_supported`` answer, X72 against beta.38 itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from an_kla.anchor_checks import latest_check
from an_kla.anchors import AnchorRejected, validate_anchor
from an_kla.anchors_document_v2 import evaluate, kind_not_supported, not_checked, served

from tests.custodian_support import NOT_EXIGIBLE, PINNED, FakeCustodian, exigible_cases, load_vectors
from tests.test_scope_compat import BASELINE_TAG, baseline_tree

_BETA_VALIDATES = (
    "import json, sys\nsys.path.insert(0, sys.argv[1])\nfrom an_kla import anchors\n"
    "assert anchors.__file__.startswith(sys.argv[1])\n"
    "try:\n    anchors.validate_anchor(json.loads(sys.argv[2]), 'fact')\n    print('null')\n"
    "except anchors.AnchorRejected as rejected:\n    print(rejected.code)\n"
)


def scenario_of(adapter: Any) -> dict[str, Any] | None:
    if adapter == "none":
        return None
    return {"mode": "response", "response": adapter} if isinstance(adapter, dict) else {"mode": adapter}


class DeclarationTests(unittest.TestCase):
    def test_the_vectors_are_the_frozen_ones(self) -> None:
        self.assertEqual({name: len(load_vectors(name)) for name in PINNED}, {"vectores.json": 49, "vectores-errata-1.json": 10, "vectores-errata-2.json": 3})

    def test_61_cases_are_exigible_and_x14_is_not(self) -> None:
        self.assertEqual(NOT_EXIGIBLE, {"X14"})
        self.assertIn("X14", [case["id"] for case in load_vectors("vectores.json")])  # loaded, not run
        self.assertEqual(len(exigible_cases()), 61)
        self.assertNotIn("X14", {case["id"] for case in exigible_cases()})
        self.assertIn("E11", {case["id"] for case in exigible_cases()})  # the one that replaces it

    def test_d01_to_d18_of_v1_are_replaced(self) -> None:
        """Declared: those 18 cases of ``memoria/ancla/v1`` are not run any more; see ``test_anchors_vectors``."""
        v1 = json.loads((Path(__file__).parent / "fixtures" / "anchors-c3" / "vectores.json").read_text(encoding="utf-8"))["document"]
        self.assertEqual(len([c for c in v1 if c["id"].startswith("D")]), 17)  # D01–D17 here, D18 in errata 1 of v1


class VectorTests(unittest.TestCase):
    def run_case(self, case: dict[str, Any]) -> tuple[dict[str, Any], FakeCustodian]:
        custodian = FakeCustodian(self)
        scenario = scenario_of(case["adapter"])
        anchor, moment = case["anchor"], case["moment"]
        adapters = custodian.adapters(scenario, timeout=1.0 if scenario and scenario["mode"] == "timeout" else 10.0)
        if case.get("implementation") == "no-document":  # X71: an implementation of v2 without `document`: kept intact, nobody called
            return {**kind_not_supported(anchor), "adapter_called": False, "reject": None}, custodian
        if moment == "read":  # X60 / X61: serve what is stored; nobody is called
            if case["stored"] is None:
                return {**not_checked(anchor), "adapter_called": False, "reject": None}, custodian
            stored = {"index": 0, "quote_sha256": anchor["quote_sha256"], "custody": None, **case["stored"]}
            row = {"id": "f-1", "anchors": [anchor], "anchor_checks": [stored]}
            return {**served(latest_check(row, "facts", 0, anchor, {})), "adapter_called": False, "reject": None}, custodian
        if moment == "write":
            try:
                validate_anchor(anchor, "fact")  # form and size, before anybody is asked
            except AnchorRejected as rejected:
                return {"reject": rejected.code, "adapter_called": False}, custodian
        return evaluate(anchor, moment, case["copy_state"], adapters, None), custodian

    def test_the_61_exigible_cases(self) -> None:
        cases = [case for case in exigible_cases() if case.get("implementation") != "v1-only"]
        self.assertEqual(len(cases), 60)  # the 61st, X72, is the one that is not this implementation's: next test
        for case in cases:
            with self.subTest(case["id"], note=case["note"]):
                got, custodian = self.run_case(case)
                for key, wanted in case["expect"].items():
                    if key == "adapter_called":
                        self.assertEqual((got["adapter_called"], custodian.called()), (wanted, wanted), key)
                    else:
                        self.assertEqual(got.get(key), wanted, key)

    def test_x72_an_implementation_that_only_knows_v1_rejects_a_v2_anchor(self) -> None:
        """The 61st case, against beta.38 (``git archive``, no install): ``anchor_schema_invalid``.  This implementation accepts it."""
        case = next(c for c in exigible_cases() if c["id"] == "X72")
        self.assertEqual((case["implementation"], case["expect"]["reject"]), ("v1-only", "anchor_schema_invalid"))
        validate_anchor(case["anchor"], "fact")  # v2 knows it
        with tempfile.TemporaryDirectory(prefix="beta38-") as scratch:
            tree = baseline_tree(Path(scratch))
            if tree is None:
                self.skipTest(f"la etiqueta {BASELINE_TAG} no está en este clon")
            done = subprocess.run([sys.executable, "-I", "-c", _BETA_VALIDATES, str(tree), json.dumps(case["anchor"])], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "anchor_schema_invalid"), done.stderr[-300:])

    def test_the_request_always_carries_locator_and_never_the_custodian_name(self) -> None:
        """Erratum 1, A1: the key ``locator`` is always there (``"unknown"`` without one); the name stays out of ``argv``."""
        for case in exigible_cases():
            if case["moment"] == "read" or case["adapter"] == "none" or case.get("implementation"):
                continue
            got, custodian = self.run_case(case)
            log = custodian.log()
            if log is None:
                continue
            with self.subTest(case["id"]):
                self.assertIn("locator", log["request"])
                if case["anchor"]["source"].get("locator") in (None, "unknown", {}):
                    self.assertEqual(log["request"]["locator"], "unknown")
                self.assertEqual(log["request"]["op"], "locate")
