"""ADR-0071 §3 and §4, own cases for what the 61 vectors do not fix: errata 3 (F1, F2), 2 (B1, B2) and 1 (A2, C1), the order
of the reasons (A3) and of the freshness reason (README: the first check that is not ``verified``, in the order ``source``,
``integrity``, ``quote``).  Pure: no process, no Git.
"""

from __future__ import annotations

import unittest
from typing import Any

from an_kla.anchors_document_v2 import Answer, build_request, decide, validate_response, write_precheck

SHA = "719d6da3" + "0" * 56
OTHER = "aaaaaaaa" + "0" * 56
QUOTE = "El personal de base tendrá derecho a veinte días de vacaciones"
TEXT = "Cláusula 47. " + QUOTE + " al año."


def source(locator: Any = {"page": 188, "item_id": "i-13"}, modality: str = "native_text") -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "document", "document_sha256": SHA, "derivation": {
        "custodian": "skopos", "derivation_id": "d" * 64, "manifest_sha256": "m" * 64, "modality": modality}}
    if locator is not None:
        out["locator"] = locator
    return out


def reply(**changes: Any) -> dict[str, Any]:
    base = {"schema": "memoria/custodio-adaptador/v1", "document": "known", "manifest": "match", "derivation": "current",
            "derivation_parent_sha256": SHA, "locator": "match", "truncated": False, "custody": {"retention": "effective"},
            "items": [{"item_id": "i-13", "page": 188, "modality": "native_text", "text": TEXT}]}
    return {**base, **changes}


def verdict(copy: str = "none", response: dict[str, Any] | None = None, moment: str = "audit", **src: Any) -> dict[str, Any]:
    anchor = {"quote": QUOTE, "quote_sha256": "0" * 64, "source": source(**src)}
    answer = None if response is None else Answer(response=response)
    return decide(anchor, moment, copy, answer, "2026-11-19T21:00:00.000000Z")


class CallerCheckTests(unittest.TestCase):
    def invalid(self, response: dict[str, Any], **src: Any) -> bool:
        return validate_response(source(**src), response) is not None

    def test_f1_a_truncated_answer_to_a_request_with_a_page_is_not_valid(self) -> None:
        self.assertTrue(self.invalid(reply(truncated=True)))
        self.assertTrue(self.invalid(reply(truncated=True), locator={"page": 188}))
        self.assertFalse(self.invalid(reply(truncated=False)))
        # without a locator it may be truncated (X47): that is where truncation lives
        self.assertFalse(self.invalid(reply(truncated=True, items=[{"item_id": "i-1", "page": 3, "modality": "native_text", "text": TEXT}]), locator=None))

    def test_f2_with_a_locator_other_than_match_items_must_be_empty_in_every_modality(self) -> None:
        item = [{"item_id": "i-13", "page": 188, "modality": "visual", "text": ""}]
        for locator in ("not_found", "invalid"):
            for modality in ("native_text", "ocr_text", "visual"):
                with self.subTest(locator=locator, modality=modality):
                    self.assertTrue(self.invalid(reply(locator=locator, items=item), modality=modality))
                    self.assertFalse(self.invalid(reply(locator=locator, items=[]), modality=modality))

    def test_c1_visual_with_a_match_does_not_look_at_the_items(self) -> None:
        self.assertFalse(self.invalid(reply(items=[{"item_id": "otro", "page": 9, "modality": "ocr_text", "text": "x"}]), modality="visual"))

    def test_b1_a_match_with_no_items_is_not_valid(self) -> None:
        self.assertTrue(self.invalid(reply(items=[])))
        self.assertFalse(self.invalid(reply(items=[]), modality="visual"))

    def test_b2_a_current_or_superseded_derivation_needs_its_parent(self) -> None:
        for derivation in ("current", "superseded"):
            self.assertTrue(self.invalid(reply(derivation=derivation, derivation_parent_sha256=None)))
        self.assertFalse(self.invalid(reply(derivation="unsupported", derivation_parent_sha256=None)))
        self.assertFalse(self.invalid(reply(manifest="mismatch", derivation=None, derivation_parent_sha256=OTHER, items=[], locator="not_found")))

    def test_a2_malformed_and_incoherent_answers(self) -> None:
        good = reply()
        for bad in (
            {k: v for k, v in good.items() if k != "truncated"}, {**good, "extra": 1}, {**good, "document": "maybe"}, {**good, "locator": "no"},
            {**good, "derivation": "old"}, {**good, "truncated": "no"}, {**good, "custody": {"retention": "forever"}},
            {**good, "custody": {"retention": "effective", "x": 1}}, {**good, "items": {}}, {**good, "items": [{"item_id": 3}]},
            {**good, "items": [{"item_id": "i", "page": 0, "modality": "native_text", "text": "t"}]},
            {**good, "items": [{"item_id": "i", "page": True, "modality": "native_text", "text": "t"}]},
            reply(document="unknown", manifest="match"),  # unknown with a manifest that matches
            reply(document="unknown", manifest="missing", derivation="current", derivation_parent_sha256=None, locator="not_found", items=[]),
            reply(document="unknown", manifest="missing", derivation=None, derivation_parent_sha256=SHA, locator="not_found", items=[]),
            reply(manifest="missing"),  # a derivation with no manifest match
            reply(manifest="match", derivation=None),  # no derivation with a match
        ):
            with self.subTest(bad=str(bad)[:80]):
                self.assertTrue(self.invalid(bad))
        self.assertTrue(validate_response(source(), "no es un objeto") is not None)

    def test_c1_the_items_are_those_of_the_page_modality_and_order_requested(self) -> None:
        two = [{"item_id": "i-12", "page": 188, "modality": "native_text", "text": "a"}, {"item_id": "i-13", "page": 188, "modality": "native_text", "text": "b"}]
        wanted = {"page": 188, "item_ids": ["i-12", "i-13"]}
        self.assertFalse(self.invalid(reply(items=two), locator=wanted))
        self.assertTrue(self.invalid(reply(items=two[::-1]), locator=wanted))  # in the custodian's order, which is the requested one
        self.assertTrue(self.invalid(reply(items=two[:1]), locator=wanted))
        self.assertTrue(self.invalid(reply(items=[{**two[0], "page": 189}, two[1]]), locator=wanted))
        self.assertTrue(self.invalid(reply(items=[{**two[0], "modality": "ocr_text"}, two[1]]), locator=wanted))
        self.assertFalse(self.invalid(reply(items=two), locator={"page": 188}))  # `{page}`: all of that page, whatever ids
        self.assertTrue(self.invalid(reply(items=two), locator={"page": 188, "item_id": "i-12"}))  # one asked for, two came


class RequestTests(unittest.TestCase):
    def test_a1_the_request_always_carries_locator(self) -> None:
        for locator, sent in ((None, "unknown"), ("unknown", "unknown"), ({}, "unknown"), ({"page": 3}, {"page": 3})):
            with self.subTest(locator=locator):
                request = build_request(source(locator=locator))
                self.assertEqual(request["locator"], sent)
                self.assertEqual(sorted(request), ["derivation_id", "document_sha256", "locator", "manifest_sha256", "modality", "op", "schema"])


class OrderOfReasonsTests(unittest.TestCase):
    def test_a3_what_contradicts_comes_before_what_cannot_be_checked(self) -> None:
        # copy of another sha256 wins over a mismatching manifest and an unknown parent
        out = verdict("bad_sha", reply(manifest="mismatch", derivation=None, derivation_parent_sha256=None, items=[], locator="not_found"))
        self.assertEqual((out["integrity"], out["integrity_reason"]), ("not_found", "copy_sha_mismatch"))
        out = verdict("ok", reply(manifest="mismatch", derivation=None, derivation_parent_sha256=OTHER, items=[], locator="not_found"))
        self.assertEqual(out["integrity_reason"], "manifest_mismatch")
        out = verdict("ok", reply(derivation_parent_sha256=OTHER))
        self.assertEqual(out["integrity_reason"], "derivation_parent_mismatch")
        # an unsupported derivation does not compare its parent (it is not a document)
        out = verdict("ok", reply(derivation="unsupported", derivation_parent_sha256=OTHER, items=[], locator="not_found"))
        self.assertEqual((out["integrity"], out["integrity_reason"]), ("unverifiable", "derivation_unsupported"))
        # then, in order: document_unknown, manifest_missing, derivation_unsupported, derivation_superseded
        out = verdict("ok", reply(document="unknown", manifest="missing", derivation=None, derivation_parent_sha256=None, items=[], locator="not_found"))
        self.assertEqual(out["integrity_reason"], "document_unknown")
        out = verdict("ok", reply(manifest="missing", derivation=None, derivation_parent_sha256=None, items=[], locator="not_found"))
        self.assertEqual(out["integrity_reason"], "manifest_missing")
        out = verdict("ok", reply(derivation="superseded"))
        self.assertEqual(out["integrity_reason"], "derivation_superseded")

    def test_the_freshness_reason_is_the_first_check_that_is_not_verified_in_the_order_source_integrity_quote(self) -> None:
        # source unverifiable (copy_missing), integrity contradicted: broken, and the cause is the first not verified: the source
        out = verdict("missing", reply(manifest="mismatch", derivation=None, derivation_parent_sha256=None, items=[], locator="not_found"))
        self.assertEqual((out["freshness"], out["source"], out["integrity_reason"]), ("broken", "verified", "manifest_mismatch"))
        self.assertEqual(out["reason"], "manifest_mismatch")  # the custodian knows the document: the source is verified, so the first is the integrity's
        out = verdict("missing", None)  # here the source is the first that is not verified
        self.assertEqual(out["reason"], "copy_missing")
        # without a response, copy missing: unverified with `copy_missing`, the source's reason, not the quote's
        out = verdict("missing", None)
        self.assertEqual((out["freshness"], out["reason"], out["integrity_reason"], out["quote_reason"]), ("unverified", "copy_missing", "no_adapter", "source_not_verified"))
        # all verified but not native text: derived_modality
        out = verdict("ok", reply(items=[{"item_id": "i-13", "page": 188, "modality": "ocr_text", "text": TEXT}]), modality="ocr_text")
        self.assertEqual((out["freshness"], out["reason"], out["quote"]), ("unverified", "derived_modality", "verified"))
        # integrity unverifiable before a quote that cannot be checked: the integrity's reason
        out = verdict("ok", reply(derivation="superseded"))
        self.assertEqual((out["freshness"], out["reason"], out["quote_reason"]), ("unverified", "derivation_superseded", "integrity_not_verified"))

    def test_a_copy_alone_verifies_the_source_but_not_the_integrity(self) -> None:
        out = verdict("ok", None)
        self.assertEqual((out["source"], out["integrity"], out["integrity_reason"], out["freshness"], out["reason"]), ("verified", "unverifiable", "no_adapter", "unverified", "no_adapter"))

    def test_an_audit_never_rejects_and_a_write_rejects_only_with_an_answer(self) -> None:
        bad = reply(document="unknown", manifest="missing", derivation=None, derivation_parent_sha256=None, items=[], locator="not_found")
        self.assertIsNone(verdict("none", bad, moment="audit")["reject"])
        self.assertEqual(verdict("none", bad, moment="write")["reject"], "anchor_source_not_found")
        anchor = {"quote": QUOTE, "quote_sha256": "0" * 64, "source": source()}
        self.assertIsNone(decide(anchor, "write", "none", Answer(failure="timeout"), None)["reject"])  # a failing adapter: accepted unverified
        self.assertIsNone(decide(anchor, "write", "none", None, None)["reject"])

    def test_the_precheck_order_page_copy_sha(self) -> None:
        anchor = {"source": source(locator={"item_id": "i-1"})}
        self.assertEqual(write_precheck(anchor, "missing"), "anchor_locator_required")  # the page first
        anchor = {"source": source()}
        self.assertEqual(write_precheck(anchor, "missing"), "anchor_copy_not_found")
        self.assertEqual(write_precheck(anchor, "bad_sha"), "anchor_integrity_not_found")
        self.assertIsNone(write_precheck(anchor, "ok"))
        self.assertIsNone(write_precheck(anchor, "none"))


if __name__ == "__main__":
    unittest.main()
