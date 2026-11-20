"""ADR-0073 §8, erratum 7 of ``memoria/ancla/v1``: the 34 cases of ``coverage-evidence-vectors.json``, exact, with their sha256 checked.

The coverage of a record is measured against one evidence per anchor: the quote, and for a ``document`` anchor of valid form also its page and the
path of its copy (``coverage.evidence: "ancla-document/v1"``).  The rules of elements do not change and never receive the anchor.  Plus the end to end
write (``remember``) of the measured case, the schemas and what stays as it was.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from an_kla.anchors import MAX_ANCHORS, AnchorRejected, validate_anchors
from an_kla.anchors_coverage import coverage as coverage_v1
from an_kla.anchors_coverage_evidence import COVERAGE_ERROR, EVIDENCE, MAX_EVIDENCE_BYTES, document_evidence
from an_kla.inbox_anchors import coverage_fields

FIXTURES = Path(__file__).parent / "fixtures" / "conversacion-resolutor-v1"
PINNED = "b303427014e0d36ee084a450691820a7618584f0d37fc182400b07895bec3f50"


def load() -> dict[str, Any]:
    raw = (FIXTURES / "coverage-evidence-vectors.json").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PINNED:
        raise AssertionError(f"coverage-evidence-vectors.json: sha256 {digest} is not the one the contract froze")
    return json.loads(raw)


class VectorTests(unittest.TestCase):
    def test_the_34_cases_are_the_frozen_ones(self) -> None:
        data = load()
        self.assertEqual((len(data["cases"]), data["evidence"], data["coverage_rules_default"]), (34, EVIDENCE, "fact-checks-rules/v2"))

    def test_the_34_cases(self) -> None:
        for case in load()["cases"]:
            with self.subTest(case["id"], note=case["note"]):
                record, expect = case["record"], case["expect"]
                anchors = record["anchors"]
                if "error" in expect:  # too many anchors: the record is rejected whole, before any coverage
                    self.assertGreater(len(anchors), MAX_ANCHORS)
                    with self.assertRaises(AnchorRejected) as raised:
                        validate_anchors(anchors, record["type"])
                    self.assertEqual(raised.exception.code, expect["error"])
                    continue
                if case["coverage_rules"] == "fact-checks-rules/v1":  # only with v2: what was stored with v1 is never recalculated, the evidence does not apply
                    self.assertEqual(coverage_v1(record["text"], [a["quote"] for a in anchors]), expect)
                    continue
                got = coverage_fields(record["text"], anchors, record["type"])
                if "coverage_error" in expect:  # the coverage of the whole record is void: no total, no missing
                    self.assertEqual(got, {"coverage": expect})
                    self.assertEqual(expect["coverage_error"], COVERAGE_ERROR)
                else:
                    self.assertEqual(got, expect)

    def test_the_evidence_each_case_declares_is_the_one_built(self) -> None:
        """The ``evidence`` list of a case is what the contract says is measured against: ours is built from the anchor alone."""
        for case in load()["cases"]:
            if "error" in case["expect"] or case["coverage_rules"] != "fact-checks-rules/v2":
                continue
            built = [document_evidence(a, case["record"]["type"]) if a["source"]["kind"] == "document" else a["quote"] for a in case["record"]["anchors"]]
            if case["id"] == "past-anchor-limit":
                continue  # the limit is a reading one; the evidence is the same
            declared = case["evidence"]
            with self.subTest(case["id"]):
                self.assertEqual([e for e in built], declared if case["id"] != "evidence-over-quote-limit" else built)

    def test_item_ids_never_enter_and_the_limit_is_bytes(self) -> None:
        anchor = {"schema": "memoria/ancla/v2", "quote": "El paciente con sospecha de dengue grave debe referirse de inmediato al segundo nivel de atención.",
                  "source": {"kind": "document", "document_sha256": "a" * 64, "locator": {"page": 7, "item_ids": ["i-1", "i-2"]},
                            "derivation": {"custodian": "skopos", "derivation_id": "d" * 64, "manifest_sha256": "m" * 64, "modality": "native_text"}}}
        anchor["quote_sha256"] = hashlib.sha256(anchor["quote"].encode()).hexdigest()
        self.assertEqual(document_evidence(anchor), anchor["quote"] + "\n7")
        self.assertEqual(MAX_EVIDENCE_BYTES, 16384)


if __name__ == "__main__":
    unittest.main()
