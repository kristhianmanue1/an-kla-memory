"""ADR-0070, prueba de aceptación 1: los 74 vectores de ``fact-checks-rules/v2`` (C3, errata 4) y los 63 de v1 intactos."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from an_kla import anchors_coverage as v1
from an_kla import anchors_coverage_v2 as v2

FIXTURES = Path(__file__).parent / "fixtures" / "anchors-c3"
V2_SHA256 = "9b06bbe7eded09989d207ae3d7d580be44e1b2f0fae042778a85015cc53b7ca8"
V1_SHA256 = "3ef67fa54dae313d0112cb7cf6ba10fc948d15cc42204323e68a91f4fdcc3bbc"


def _load(name: str, sha256: str) -> dict:
    raw = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha256, name
    return json.loads(raw)


class V2VectorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = _load("fact-checks-v2-vectors.json", V2_SHA256)

    def test_the_file_is_the_one_of_the_erratum(self) -> None:
        self.assertEqual((self.document["rules"], len(self.document["cases"])), (v2.COVERAGE_RULES, 74))
        self.assertTrue(all(c["rules"] == v2.COVERAGE_RULES for c in self.document["cases"]))

    def test_elements_and_missing(self) -> None:
        for case in self.document["cases"]:
            with self.subTest(case["id"]):
                elements = v2.check_elements(case["text"], case["quotes"])
                self.assertEqual(elements, case["elements"])
                missing = [{"type": e["type"], "value": e["value"]} for e in elements if not e["present"]]
                self.assertEqual(sorted(missing, key=repr), sorted(case["missing"], key=repr))

    def test_coverage_in_fact_and_state_mode(self) -> None:
        for case in self.document["cases"]:
            for mode in v2.MODES:
                with self.subTest(case["id"], mode=mode):
                    self.assertEqual(v2.coverage_from_elements(case["elements"], mode), case["coverage"][mode])

    def test_the_stored_coverage_says_its_rules(self) -> None:
        stored = v2.coverage("el puerto es 8080", ["el puerto es 8081"])
        self.assertEqual(stored["coverage"], {"total": 1, "present": 0, "level": "none", "rules": "fact-checks-rules/v2"})
        self.assertEqual(stored["missing"], [{"type": "number", "value": "8080"}])
        with self.assertRaises(ValueError):
            v2.coverage_from_elements([], "otro")


class OwnVectorsTest(unittest.TestCase):
    """Corrección 1: vectores propios de an-kla (archivo aparte del de C3) para lo que el texto de las reglas fija y C3 no cubre."""

    def test_each_own_vector_passes_and_names_its_rule(self) -> None:
        document = json.loads((FIXTURES.parent / "cobertura-v2" / "ankla-vectors.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(document["cases"]), 3)
        for case in document["cases"]:
            with self.subTest(case["id"]):
                self.assertTrue(case["note"] and case["rule"])
                elements = v2.check_elements(case["text"], case["quotes"])
                self.assertEqual(elements, case["elements"])
                missing = [{"type": e["type"], "value": e["value"]} for e in elements if not e["present"]]
                self.assertEqual(missing, case["missing"])

    def test_the_own_vectors_are_counted_and_have_unique_ids(self) -> None:
        cases = json.loads((FIXTURES.parent / "cobertura-v2" / "ankla-vectors.json").read_text(encoding="utf-8"))["cases"]
        self.assertEqual(len(cases), 23)  # Q-04: el informe cuenta lo que hay
        self.assertEqual(len({c["id"] for c in cases}), len(cases))

    def test_a_hash_ellipsis_is_masked_with_the_token_and_not_valued(self) -> None:
        self.assertEqual(v2._hashes("a92b9252…x"), [(0, "a92b9252", 9)])  # el span cubre la elipsis; el valor no
        self.assertEqual(v2._hashes("a92b9252x"), [])
        self.assertEqual(v2._hashes("abcdef12"), [(0, "abcdef12", 8)])

    def test_the_c3_file_was_not_touched(self) -> None:
        self.assertEqual(hashlib.sha256((FIXTURES / "fact-checks-v2-vectors.json").read_bytes()).hexdigest(), V2_SHA256)


class V1UntouchedTest(unittest.TestCase):
    def test_the_63_v1_vectors_still_pass_with_v1(self) -> None:
        cases = _load("fact-checks-v1-vectors.json", V1_SHA256)["cases"]
        self.assertEqual(len(cases), 63)
        for case in cases:
            with self.subTest(case["id"]):
                self.assertEqual(v1.check_elements(case["text"], case["quotes"]), case["elements"])
        self.assertEqual(v1.COVERAGE_RULES, "fact-checks-rules/v1")
        self.assertNotIn("rules", v1.coverage("el puerto es 8080", ["x"])["coverage"])

    def test_only_one_of_the_63_changes_level_between_v1_and_v2(self) -> None:
        changed = []
        for case in _load("fact-checks-v1-vectors.json", V1_SHA256)["cases"]:
            old = v1.coverage_from_elements(v1.check_elements(case["text"], case["quotes"]))["coverage"]["level"]
            new = v2.coverage_from_elements(v2.check_elements(case["text"], case["quotes"]))["coverage"]["level"]
            if old != new:
                changed.append(case["id"])
        self.assertEqual(len(changed), 1, changed)  # ADR-0070 «Neutras»


if __name__ == "__main__":
    unittest.main()
