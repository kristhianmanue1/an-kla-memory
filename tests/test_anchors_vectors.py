"""C3 vector harness (ADR-0066 §8), every ``expect`` compared field by field.

Sections run here: ``cita`` (24) + Q25, ``busqueda`` (25), ``conversation`` (11) +
S12, S13, ``document`` (17) + D18 (the ``supported: true`` ones are "not applicable"
and must answer ``kind_not_supported``), ``frescura`` (110), errata 2 (10).  The 48 + 2
``repo_file`` cases need real Git and live in ``test_anchors_repo_file``; the coverage
ones in ``test_anchors_coverage``.  ``COUNTS`` feeds the report.
"""

from __future__ import annotations

import unittest
from typing import Any

from an_kla.anchors import (
    AnchorRejected, normalize_quote, prepare_quote, quote_sha256, validate_anchor, validate_anchors,
)
from an_kla.anchors_conversation import ConversationVerifier, TurnView, apply_resolution, check_conversation
from an_kla.anchors_document import check_document
from an_kla.anchors_freshness import derive_freshness
from an_kla.anchors_search import find_quote

from anchors_c3_support import REPO_ID, load_vectors

COUNTS: dict[str, dict[str, int]] = {}
DOC_SHA = "719d6da341bff3733750f05357de50ca09fabc7c31c4354186dae8a7a3a70323"
COMMIT = "0000000000000000000000000000000000000001"


def _note(section: str, key: str) -> None:
    COUNTS.setdefault(section, {"total": 0, "pass": 0, "fail": 0, "n/a": 0})[key] += 1


class _SessionVerifier:
    """Reads the turns of a vector's session; the stand-in for a C2 verifier."""

    def __init__(self, session: dict[str, Any]) -> None:
        self.turns = {t["id"]: t for t in session["turns"]}

    def turn(self, session: str, turn_id: str) -> TurnView:
        turn = self.turns.get(turn_id)
        if turn is None:
            return TurnView("missing")
        if turn.get("purged"):
            return TurnView("purged")
        return TurnView("ok", turn["text"], turn.get("raw", True), turn.get("seal_ok", True))


def _reference_resolution(case: dict[str, Any]) -> dict[str, Any] | None:
    """What a test resolver would annotate for a still-``pending`` anchor (C3 README)."""
    session = case["session"]
    quote = case["anchor"]["quote"]
    if session["state"] != "sealed":
        return None
    purged = False
    for turn in session["turns"]:
        if turn.get("purged"):
            purged = True
        elif find_quote(quote, turn["text"])[0]:
            return {"resolution": "resolved", "turn_id": turn["id"], "seal": "seal-" + turn["id"]}
    if purged:
        return None
    return {"resolution": "not_found", "turn_id": None, "seal": None}


def conversation_anchor(raw: dict[str, Any]) -> dict[str, Any]:
    quote = normalize_quote(raw["quote"])
    return {
        "schema": "memoria/ancla/v1",
        "source": {
            "kind": "conversation", "session": "claude-code:0a92bdfb", "resolution": raw["resolution"],
            "turn_id": raw["turn_id"], "seal": None,
        },
        "quote": quote, "quote_sha256": quote_sha256(quote),
    }


def run_conversation(case: dict[str, Any]) -> dict[str, Any]:
    anchor = validate_anchor(conversation_anchor(case["anchor"]), "fact")
    verifier: ConversationVerifier | None = None
    annotations = []
    if case["resolver"]:
        verifier = _SessionVerifier(case["session"])
        if anchor["source"]["resolution"] == "pending":
            decided = _reference_resolution(case)
            if decided:
                annotations.append({"id": "e-r-1", "enqueued_at": "2026-01-01T00:00:00Z", "anchor_resolution": {
                    "schema": "an-kla/anchor-resolution-v1",
                    "target": {"stream": "facts", "record_id": "f-r-1", "anchor_index": 0,
                               "quote_sha256": anchor["quote_sha256"]},
                    **decided}})
    view = apply_resolution(anchor, "f-r-1", 0, annotations)
    return check_conversation(view, verifier)


def document_anchor(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "memoria/ancla/v1",
        "source": {
            "kind": "document", "document_sha256": DOC_SHA,
            "derivation": {"custodian": "skopos", "derivation_id": "d1", "manifest_sha256": "m1",
                           "modality": raw["modality"]},
            "locator": raw.get("locator", "unknown"),
        },
        "quote": raw["quote"],
    }


def repo_anchor(commit: str | None = COMMIT, quote: str = "El servidor usa port = 8080") -> dict[str, Any]:
    return {"schema": "memoria/ancla/v1",
            "source": {"kind": "repo-file", "repo": REPO_ID, "commit": commit, "path": "docs/a.md"},
            "quote": quote}


def _check(testcase: unittest.TestCase, section: str, label: str, got: Any, wanted: Any) -> None:
    _note(section, "total")
    try:
        testcase.assertEqual(got, wanted, label)
    except AssertionError:
        _note(section, "fail")
        raise
    _note(section, "pass")


class QuoteVectors(unittest.TestCase):
    def test_cita(self) -> None:
        cases = load_vectors("vectores.json")["cita"] + load_vectors("vectores-errata-1.json")["cita"]
        self.assertEqual(len(cases), 25)
        for case in cases:
            with self.subTest(case["id"]):
                expect = case["expect"]
                try:
                    stored = prepare_quote(case["input"], case["kind"])
                    got = {"reject": None, "stored": stored, "quote_sha256": quote_sha256(stored),
                           "stored_bytes": len(stored.encode("utf-8"))}
                    got["stored_hex"] = None if got["stored_bytes"] > 64 else stored.encode("utf-8").hex()
                except AnchorRejected as rejected:
                    got = {"reject": rejected.code, "stored": None}
                _check(self, "cita", case["id"], {k: got[k] for k in expect}, expect)

    def test_busqueda(self) -> None:
        cases = load_vectors("vectores.json")["busqueda"]
        self.assertEqual(len(cases), 25)
        for case in cases:
            with self.subTest(case["id"]):
                match, matched = find_quote(normalize_quote(case["quote"]), case["source_text"])
                _check(self, "busqueda", case["id"], {"match": match, "matched_text": matched}, case["expect"])

    def test_frescura(self) -> None:
        cases = load_vectors("vectores.json")["frescura"]
        self.assertEqual(len(cases), 110)
        for index, case in enumerate(cases):
            with self.subTest(index):
                fresh, decided = derive_freshness(
                    case["kind"], case["source"], case["quote"], case["integrity"],
                    case.get("resolution"), case.get("modality"),
                )
                _check(self, "frescura", str(index), {"freshness": fresh, "decided_by": decided},
                       {"freshness": case["freshness"], "decided_by": case["decided_by"]})


class ConversationVectors(unittest.TestCase):
    def test_conversation(self) -> None:
        cases = load_vectors("vectores.json")["conversation"] + load_vectors("vectores-errata-1.json")["conversation"]
        self.assertEqual(len(cases), 13)
        for case in cases:
            with self.subTest(case["id"]):
                got = run_conversation(case)
                _check(self, "conversation", case["id"], {k: got.get(k) for k in case["expect"]}, case["expect"])


class DocumentVectors(unittest.TestCase):
    def test_document(self) -> None:
        cases = load_vectors("vectores.json")["document"] + load_vectors("vectores-errata-1.json")["document"]
        self.assertEqual(len(cases), 18)
        for case in cases:
            with self.subTest(case["id"]):
                anchor = validate_anchor(document_anchor(case["anchor"]), "fact")
                got = check_document(anchor)
                if case["supported"]:
                    # D01..D16 and D18 need a custodian: not applicable here, but never rejected.
                    _note("document", "total")
                    _note("document", "n/a")
                    self.assertEqual((got["freshness"], got["reason"]), ("unverified", "kind_not_supported"))
                else:
                    _check(self, "document", case["id"], {k: got[k] for k in case["expect"] if k != "reject"},
                           {k: v for k, v in case["expect"].items() if k != "reject"})


class Errata2Vectors(unittest.TestCase):
    def test_registro_and_forma(self) -> None:
        data = load_vectors("vectores-errata-2.json")
        ok = repo_anchor()
        short = repo_anchor(quote="abc")
        anchors = {
            "F01": [ok] * 16, "F02": [ok] * 17, "F03": [ok] * 16 + [short],
        }
        for case in data["registro"]:
            with self.subTest(case["id"]):
                try:
                    validate_anchors(anchors[case["id"]], "fact")
                    got = None
                except AnchorRejected as rejected:
                    got = rejected.code
                _check(self, "errata2", case["id"], got, case["expect"]["reject"])
        for case in data["forma"]:
            with self.subTest(case["id"]):
                try:
                    validate_anchor(case["anchor"], case["record_type"])
                    got = None
                except AnchorRejected as rejected:
                    got = rejected.code
                _check(self, "errata2", case["id"], got, case["expect"]["reject"])


if __name__ == "__main__":
    unittest.main()
