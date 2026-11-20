"""ADR-0071 §5: the total order that serves a stored result, and the form of what is stored.

Candidates: the entry of ``anchor_checks`` of the record itself with that ``index`` and the vigent ``anchor_check``
annotations of that target and ``index``, whenever their ``quote_sha256`` is the anchor's.  The greatest
``(checked_at, origin, enqueued_at, id)`` wins: origin 0 for the record and 1 for an annotation (on the same date the audit
rules), ``enqueued_at`` is the envelope's (``""`` without one) and ``id`` that of the record or the annotation, as strings.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

from an_kla.anchor_checks import check_annotations, has_checks, latest_check, normalized, valid_check

SHA = "a" * 64


def check(at: str, *, reason: str | None = None, index: int = 0, sha: str = SHA, freshness: str = "fresh") -> dict[str, Any]:
    return {"index": index, "quote_sha256": sha, "checked_at": at, "manifest_sha256": "m", "derivation": "current", "source": "verified",
            "source_reason": None, "integrity": "verified", "integrity_reason": None, "quote": "verified", "quote_reason": None,
            "match": "literal", "freshness": freshness, "reason": reason, "custody": None}


def note(ident: str, at: str | None, *checks: dict[str, Any], status: str | None = None, target: str = "f-1", stream: str = "facts") -> dict[str, Any]:
    row: dict[str, Any] = {"id": ident, "kind": "anchor_check",
                           "anchor_check": {"schema": "an-kla/anchor-check-v1", "target": {"stream": stream, "record_id": target}, "checks": list(checks)}}
    if at is not None:
        row["an_kla_envelope"] = {"enqueued_at": at}
    if status is not None:
        row["status"] = status
    return row


def pick(own: list[dict[str, Any]] | None, *notes: dict[str, Any], own_at: str | None = "2026-11-19T20:00:00.000000Z") -> str | None:
    row: dict[str, Any] = {"id": "f-1", "anchors": [{"quote_sha256": SHA}]}
    if own is not None:
        row["anchor_checks"] = own
    if own_at is not None:
        row["an_kla_envelope"] = {"enqueued_at": own_at}
    found = latest_check(row, "facts", 0, {"quote_sha256": SHA}, check_annotations(SimpleNamespace(records={"events": list(notes)})))
    return None if found is None else found["reason"]


class OrderTests(unittest.TestCase):
    def test_the_records_own_result_alone(self) -> None:
        self.assertEqual(pick([check("2026-11-19T21:00:00.000000Z", reason="propio")]), "propio")

    def test_nothing_stored_is_none(self) -> None:
        self.assertIsNone(pick(None))
        self.assertIsNone(pick([], note("e-1", "t", check("2026-11-19T21:00:00.000000Z"), target="otro")))

    def test_the_later_date_wins_whoever_it_comes_from(self) -> None:
        own = [check("2026-11-19T21:00:00.000000Z", reason="propio")]
        self.assertEqual(pick(own, note("e-1", "2026-11-19T22:00:00.000000Z", check("2026-11-19T22:00:00.000000Z", reason="auditoria"))), "auditoria")
        self.assertEqual(pick(own, note("e-1", "2026-11-19T22:00:00.000000Z", check("2026-11-19T20:30:00.000000Z", reason="vieja"))), "propio")

    def test_on_the_same_date_the_audit_rules(self) -> None:
        at = "2026-11-19T21:00:00.000000Z"
        self.assertEqual(pick([check(at, reason="propio")], note("e-1", "2026-11-19T21:00:01.000000Z", check(at, reason="auditoria"))), "auditoria")
        # even when the annotation was enqueued before the record: origin comes before enqueued_at
        self.assertEqual(pick([check(at, reason="propio")], note("e-1", "2026-11-19T10:00:00.000000Z", check(at, reason="auditoria"))), "auditoria")

    def test_between_audits_of_the_same_date_the_later_enqueued_wins_then_the_greater_id(self) -> None:
        at = "2026-11-19T21:00:00.000000Z"
        a = note("e-9", "2026-11-19T21:00:01.000000Z", check(at, reason="antigua"))
        b = note("e-1", "2026-11-19T21:00:02.000000Z", check(at, reason="nueva"))
        self.assertEqual(pick(None, a, b), "nueva")
        self.assertEqual(pick(None, b, a), "nueva")  # whatever the order they arrive in
        c = note("e-2", "2026-11-19T21:00:02.000000Z", check(at, reason="mayor id"))
        self.assertEqual(pick(None, b, c), "mayor id")
        self.assertEqual(pick(None, c, b), "mayor id")

    def test_an_annotation_without_an_envelope_counts_with_empty_enqueued_at(self) -> None:
        at = "2026-11-19T21:00:00.000000Z"
        self.assertEqual(pick(None, note("e-1", None, check(at, reason="sin sobre")), note("e-2", "2026-11-19T21:00:00.000000Z", check(at, reason="con sobre"))), "con sobre")

    def test_dates_of_different_precision_compare_as_dates(self) -> None:
        self.assertEqual(normalized("2026-11-19T21:00:00Z"), "2026-11-19T21:00:00.000000Z")
        self.assertEqual(normalized("2026-11-19T21:00:00.5Z"), "2026-11-19T21:00:00.500000Z")
        own = [check("2026-11-19T21:00:00Z", reason="propio")]
        self.assertEqual(pick(own, note("e-1", "t", check("2026-11-19T21:00:00.000001Z", reason="un micro despues"))), "un micro despues")
        self.assertEqual(pick(own, note("e-1", "t", check("2026-11-19T20:59:59.999999Z", reason="un micro antes"))), "propio")

    def test_a_result_of_another_quote_or_another_index_is_not_a_candidate(self) -> None:
        at = "2026-11-19T22:00:00.000000Z"
        own = [check("2026-11-19T21:00:00.000000Z", reason="propio")]
        self.assertEqual(pick(own, note("e-1", "t", check(at, sha="b" * 64, reason="otra cita"))), "propio")
        self.assertEqual(pick(own, note("e-1", "t", check(at, index=1, reason="otro indice"))), "propio")
        self.assertIsNone(pick([check(at, sha="b" * 64)]))

    def test_a_retired_annotation_or_one_that_is_not_well_formed_is_ignored(self) -> None:
        at = "2026-11-19T22:00:00.000000Z"
        own = [check("2026-11-19T21:00:00.000000Z", reason="propio")]
        self.assertEqual(pick(own, note("e-1", "t", check(at, reason="retirada"), status="sustituida")), "propio")
        broken = {**check(at, reason="rota"), "freshness": "stale"}
        self.assertEqual(pick(own, note("e-2", "t", broken)), "propio")
        self.assertEqual(pick(own, {"id": "e-3", "kind": "anchor_check", "anchor_check": "no es un objeto"}), "propio")

    def test_a_result_is_served_only_for_the_stream_and_record_it_names(self) -> None:
        at = "2026-11-19T22:00:00.000000Z"
        self.assertIsNone(pick(None, note("e-1", "t", check(at), stream="episodes")))


class FormTests(unittest.TestCase):
    def test_what_is_a_valid_result(self) -> None:
        good = check("2026-11-19T21:00:00Z")
        self.assertTrue(valid_check(good))
        for key, value in (("index", True), ("index", -1), ("quote_sha256", "x"), ("checked_at", "ayer"), ("checked_at", "2026-11-19 21:00:00"),
                           ("source", "maybe"), ("freshness", "stale"), ("freshness", "pending"), ("derivation", "old"), ("match", "fuzzy"),
                           ("custody", "x"), ("reason", 3)):
            with self.subTest(key=key, value=value):
                self.assertFalse(valid_check({**good, key: value}))
        self.assertFalse(valid_check({**good, "extra": 1}))
        self.assertFalse(valid_check({k: v for k, v in good.items() if k != "custody"}))

    def test_the_sparse_schema_trigger(self) -> None:
        self.assertTrue(has_checks({"anchors": [{"freshness": "x", "checked_at": None}]}))
        self.assertFalse(has_checks({"anchors": [{"freshness": "x"}]}))
        self.assertFalse(has_checks({}))


def attempt(at: str, integrity_reason: str, **changes: Any) -> dict[str, Any]:
    """Un intento que no concluye: lo que guarda una auditoría sin tabla o con el adaptador fallando."""
    return {**check(at, freshness="unverified", reason=integrity_reason), "source": "unverifiable", "integrity": "unverifiable",
            "integrity_reason": integrity_reason, "quote": "unverifiable", "quote_reason": "source_not_verified", **changes}


class ConclusiveTests(unittest.TestCase):
    """ADR-0072 §1 (errata 6): el último concluyente manda; sin ninguno, el último a secas."""

    def test_what_is_conclusive_comes_from_the_integrity_reason(self) -> None:
        from an_kla.anchor_checks import is_conclusive

        self.assertTrue(is_conclusive(check("2026-11-19T21:00:00Z")))
        self.assertTrue(is_conclusive({**attempt("2026-11-19T21:00:00Z", "copy_sha_mismatch")}))  # A3: a contradicting copy concludes
        for reason in ("no_adapter", "adapter_error"):
            self.assertFalse(is_conclusive(attempt("2026-11-19T21:00:00Z", reason)))
        for reason in ("manifest_mismatch", "derivation_superseded", "document_unknown", "manifest_missing", "derivation_unsupported"):
            self.assertTrue(is_conclusive(attempt("2026-11-19T21:00:00Z", reason)), reason)  # the adapter answered validly

    def test_an_attempt_that_does_not_conclude_does_not_cover_a_conclusive_result(self) -> None:
        own = [check("2026-11-19T21:00:00.000000Z", reason="concluyente")]
        later = note("e-1", "2026-11-19T22:00:00.000000Z", attempt("2026-11-19T22:00:00.000000Z", "no_adapter"))
        self.assertEqual(pick(own, later), "concluyente")
        self.assertEqual(pick(own, note("e-2", "t", attempt("2026-11-19T23:00:00.000000Z", "adapter_error"))), "concluyente")

    def test_fresh_then_broken_then_no_adapter_is_broken(self) -> None:
        own = [check("2026-11-19T21:00:00.000000Z", reason="fresco")]
        broken = note("e-1", "2026-11-19T22:00:00.000000Z", check("2026-11-19T22:00:00.000000Z", reason="quote_absent", freshness="broken"))
        none = note("e-2", "2026-11-19T23:00:00.000000Z", attempt("2026-11-19T23:00:00.000000Z", "no_adapter"))
        self.assertEqual(pick(own, broken, none), "quote_absent")

    def test_a_later_conclusive_result_still_wins_over_an_earlier_one(self) -> None:
        own = [check("2026-11-19T21:00:00.000000Z", reason="antiguo")]
        newer = note("e-1", "2026-11-19T22:00:00.000000Z", check("2026-11-19T22:00:00.000000Z", reason="nuevo"))
        self.assertEqual(pick(own, newer), "nuevo")

    def test_with_no_conclusive_result_the_latest_attempt_is_served(self) -> None:
        first = [attempt("2026-11-19T21:00:00.000000Z", "no_adapter")]
        second = note("e-1", "2026-11-19T22:00:00.000000Z", attempt("2026-11-19T22:00:00.000000Z", "adapter_error"))
        self.assertEqual(pick(first, second), "adapter_error")
        self.assertEqual(pick(first), "no_adapter")


if __name__ == "__main__":
    unittest.main()
