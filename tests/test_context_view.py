from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import weakref

from jsonschema import Draft202012Validator
from an_kla.canonical import canonical_json, digest_json, exact_sized_payload
from an_kla.context_view import _minimum_budget, context_view
from an_kla.reader_gate import ReaderGateError, reader_gate_mode
from an_kla.schemas import schema_document
from an_kla.store import IntegrityError, MemoryStore, Snapshot
from an_kla.subject_ref import derive_namespace


REVISION = "sha256:" + "1" * 64
NAMESPACE = "p-" + "2" * 32


def subject(name: str, kind: str = "service") -> str:
    return f"an-kla:subject:v1:{kind}:{NAMESPACE}:{name}"


class FakeStore:
    def __init__(self, records=None, manifest=None):
        base = tempfile.mkdtemp()
        self._finalizer = weakref.finalize(self, shutil.rmtree, base, True)
        self.root = Path(base) / "memory"
        self.root.mkdir()
        rows = records or {}
        raw = {stream: tuple(deepcopy(rows.get(stream, ()))) for stream in ("facts", "events", "episodes")}
        self.value = Snapshot(
            REVISION,
            {"supersedes_map": [], "refutations_map": [], **(manifest or {})},
            {}, raw, raw,
        )
        self.revisions = []

    def snapshot(self, revision):
        self.revisions.append(revision)
        return self.value

    def _snapshot_under_gate(self, revision):
        return self.snapshot(revision)


def fact(identifier: str, name: str, text: str, **extra):
    return {
        "id": identifier,
        "schema": "an-kla/fact-v1",
        "subject_ref": subject(name),
        "payload": {"text": text},
        **extra,
    }


def _error_without_detail():
    return {"schema": "an-kla/view-error-v1", "ok": False, "code": "view_invalid_inputs",
            "retryable": False, "untrusted_memory_data": True}


class ContextViewCoreTests(unittest.TestCase):
    def assertSchemaValid(self, name, value):
        Draft202012Validator(schema_document(name)).validate(value)

    def assertSchemaInvalid(self, name, value):
        self.assertFalse(Draft202012Validator(schema_document(name)).is_valid(value))

    def test_revision_is_required_and_snapshot_is_pinned(self):
        store = FakeStore()
        invalid = context_view(store, revision="bad")
        self.assertEqual(invalid["code"], "view_invalid_inputs")
        self.assertEqual(invalid["detail"], "revision")
        self.assertEqual(store.revisions, [])

        output = context_view(store, revision=REVISION)
        self.assertEqual(output["revision"], REVISION)
        self.assertEqual(store.revisions, [REVISION])
        self.assertSchemaValid("context-view-v1", output)

    def test_streams_reject_unbounded_or_oversized_iterables(self):
        store = FakeStore()
        self.assertEqual(context_view(store, revision=REVISION, streams=(x for x in ["facts"]))["detail"], "streams")
        self.assertEqual(context_view(store, revision=REVISION, streams=["facts"] * 4)["detail"], "streams")

    def test_grouping_conflict_order_and_default_text_projection(self):
        store = FakeStore(
            {
                "facts": [fact("f-z", "billing", "same"), fact("f-a", "billing", "same")],
                "events": [{
                    "id": "e-a", "subject_ref": subject("billing"),
                    "payload": {"text": "different"},
                }],
            }
        )
        output = context_view(store, revision=REVISION)
        item = output["subjects"][0]
        self.assertTrue(item["data_conflict"])
        self.assertEqual([(x["stream"], x["id"]) for x in item["alternatives"]],
                         [("facts", "f-z"), ("facts", "f-a"), ("events", "e-a")])
        self.assertTrue(item["content_differs_beyond_text"])
        self.assertIn("record_text", item["alternatives"][0])
        self.assertNotIn("record_raw", item["alternatives"][0])
        self.assertTrue(item["alternatives"][0]["untrusted_memory_data"])

    def test_physical_status_cannot_claim_governed_overlay_or_deny_view(self):
        rows = [
            fact("f-active", "a", "active", status="active"),
            fact("f-missing", "b", "missing"),
            fact("f-hostile", "c", "hostile", status="refutada"),
            fact("f-object", "d", "object", status={"bad": True}),
        ]
        output = context_view(FakeStore({"facts": rows}), revision=REVISION)
        by_subject = {item["subject_ref"]: item for item in output["subjects"]}
        self.assertEqual(len(by_subject[subject("a")]["alternatives"]), 1)
        self.assertEqual(len(by_subject[subject("b")]["alternatives"]), 1)
        for name in ("c", "d"):
            record = by_subject[subject(name)]["history"][0]
            self.assertEqual(record["state"], "inactive_untrusted")
            self.assertEqual(record["state_source"], "physical_status_untrusted")

    def test_governed_overlay_precedes_physical_status_and_links_are_plural(self):
        rows = [fact("f-a", "svc", "A"), fact("f-b", "svc", "B"), fact("f-c", "svc", "C")]
        manifest = {"supersedes_map": [
            {"stream": "facts", "target_id": "f-a", "sustituida_por": "f-b"},
            {"stream": "facts", "target_id": "f-b", "sustituida_por": "f-c"},
        ]}
        output = context_view(FakeStore({"facts": rows}, manifest), revision=REVISION)
        item = output["subjects"][0]
        self.assertEqual([x["id"] for x in item["alternatives"]], ["f-c"])
        middle = next(x for x in item["history"] if x["id"] == "f-b")
        self.assertEqual(middle["state"], "superseded")
        self.assertEqual(middle["state_source"], "governed_overlay")
        self.assertEqual(len(middle["supersede_links"]), 2)

    def test_governed_overlay_still_exposes_untrusted_physical_status(self):
        row = fact("f-a", "svc", "A", status="draft")
        manifest = {"supersedes_map": [
            {"stream": "facts", "target_id": "f-a", "sustituida_por": "f-b"}
        ]}
        successor = fact("f-b", "svc", "B")
        output = context_view(FakeStore({"facts": [row, successor]}, manifest), revision=REVISION)
        old = next(x for x in output["subjects"][0]["history"] if x["id"] == "f-a")
        self.assertEqual(old["state"], "superseded")
        self.assertEqual(old["physical_status_untrusted"], "draft")

    def test_refute_overlay_and_cross_subject_supersede_do_not_merge(self):
        old = fact("f-old", "old", "old")
        new = fact("f-new", "new", "new")
        refuted = fact("f-refuted", "refuted", "refuted")
        manifest = {
            "supersedes_map": [{"stream": "facts", "target_id": "f-old", "sustituida_por": "f-new"}],
            "refutations_map": [{"stream": "facts", "target_record_sha256": digest_json(refuted)}],
        }
        output = context_view(FakeStore({"facts": [old, new, refuted]}, manifest), revision=REVISION)
        by_ref = {item["subject_ref"]: item for item in output["subjects"]}
        self.assertEqual(set(by_ref), {subject("old"), subject("new"), subject("refuted")})
        self.assertEqual(by_ref[subject("old")]["history"][0]["state"], "superseded")
        self.assertEqual(by_ref[subject("new")]["alternatives"][0]["state"], "active")
        self.assertEqual(by_ref[subject("refuted")]["history"][0]["state"], "refuted")

    def test_legacy_counts_invalid_subject_and_projection_guard(self):
        legacy = {"id": "f-legacy", "payload": {"text": "legacy"}}
        output = context_view(FakeStore({"facts": [legacy]}), revision=REVISION)
        self.assertEqual(output["subjects_without_subject_ref"], {"facts": 1, "events": 0, "episodes": 0})
        self.assertEqual(output["warnings"], ["legacy_records_without_subject_ref"])

        invalid = {**legacy, "id": "f-invalid", "subject_ref": "hostile subject"}
        output = context_view(FakeStore({"facts": [invalid]}), revision=REVISION)
        self.assertEqual(output["code"], "view_invalid_subject_ref_in_revision")
        self.assertEqual(output["detail"]["stream"], "facts")
        self.assertEqual(output["detail"]["record_sha256"], digest_json(invalid))
        self.assertNotIn("hostile subject", canonical_json(output).decode())

        output = context_view(FakeStore(), revision=REVISION, projection="full")
        self.assertEqual(output["code"], "view_invalid_inputs")
        self.assertEqual(output["detail"], "subject_filter")

    def test_full_projection_requires_exact_filter_and_preserves_raw(self):
        row = fact("f-a", "svc", "secret")
        output = context_view(
            FakeStore({"facts": [row]}), revision=REVISION,
            projection="full", subject_filter=subject("svc"),
        )
        record = output["subjects"][0]["alternatives"][0]
        self.assertEqual(record["record_raw"], row)
        self.assertEqual(record["record_text"], "secret")

    def test_explicit_now_is_canonical_and_no_clock_is_implicit(self):
        row = fact("f-a", "svc", "fresh", verified_at="2026-08-10T00:00:00Z")
        without = context_view(FakeStore({"facts": [row]}), revision=REVISION)
        record = without["subjects"][0]["alternatives"][0]
        self.assertEqual(without["freshness"], None)
        self.assertNotIn("days_since_verified", record)

        with_now = context_view(
            FakeStore({"facts": [row]}), revision=REVISION,
            now="2026-08-12T00:00:00Z", stale_after_days=1,
        )
        record = with_now["subjects"][0]["alternatives"][0]
        self.assertEqual(with_now["inputs"]["now"], "2026-08-12T00:00:00.000000Z")
        self.assertEqual(record["days_since_verified"], 2)
        self.assertTrue(record["stale"])

    def test_history_is_textual_descending_with_missing_last(self):
        rows = [
            fact("f-a", "svc", "A", status="draft", verified_at="2026-01-01T00:00:00Z"),
            fact("f-b", "svc", "B", status="draft", verified_at="2026-02-01T00:00:00Z"),
            fact("f-c", "svc", "C", status="draft"),
        ]
        output = context_view(FakeStore({"facts": rows}), revision=REVISION)
        self.assertEqual([x["id"] for x in output["subjects"][0]["history"]], ["f-b", "f-a", "f-c"])

    def test_cursor_survives_limit_and_budget_changes_but_not_projection(self):
        rows = [fact(f"f-{name}", name, name * 20) for name in ("a", "b", "c")]
        store = FakeStore({"facts": rows})
        first = context_view(store, revision=REVISION, limit=1, budget_bytes=20000)
        self.assertFalse(first["pagination"]["complete"])
        cursor = first["pagination"]["next_cursor"]
        second = context_view(store, revision=REVISION, limit=2, budget_bytes=30000, cursor=cursor)
        self.assertEqual([x["subject_ref"] for x in second["subjects"]], [subject("b"), subject("c")])
        self.assertTrue(second["pagination"]["complete"])
        self.assertEqual(second["pagination"]["total_subjects"], 3)
        self.assertEqual(second["pagination"]["truncated_subjects"], 0)
        invalid = context_view(store, revision=REVISION, projection="metadata", cursor=cursor)
        self.assertEqual(invalid["code"], "view_cursor_invalid")

    def test_page_two_budget_error_resumes_same_subject(self):
        rows = [fact("f-a", "a", "small"), fact("f-b", "b", "x" * 4000)]
        store = FakeStore({"facts": rows})
        first = context_view(store, revision=REVISION, budget_bytes=2500)
        self.assertEqual([x["subject_ref"] for x in first["subjects"]], [subject("a")])
        cursor = first["pagination"]["next_cursor"]
        blocked = context_view(store, revision=REVISION, budget_bytes=2500, cursor=cursor)
        self.assertEqual(blocked["code"], "view_subject_exceeds_budget")
        self.assertEqual(blocked["resume_cursor"], cursor)
        retried = context_view(
            store, revision=REVISION, budget_bytes=blocked["minimum_budget_bytes"],
            cursor=cursor,
        )
        self.assertEqual([x["subject_ref"] for x in retried["subjects"]], [subject("b")])

    def test_subject_budget_error_retries_exactly_without_cursor_invalidation(self):
        row = fact("f-big", "big", "x" * 3000)
        store = FakeStore({"facts": [row]})
        small = context_view(store, revision=REVISION, budget_bytes=2000)
        self.assertEqual(small["code"], "view_subject_exceeds_budget")
        self.assertSchemaValid("view-error-v1", small)
        self.assertIsNone(small["resume_cursor"])
        minimum = small["minimum_budget_bytes"]
        retried = context_view(store, revision=REVISION, budget_bytes=minimum)
        self.assertEqual(retried["schema"], "an-kla/context-view-v1")
        self.assertLessEqual(len(canonical_json(retried)), minimum)
        if minimum > 1:
            previous = context_view(store, revision=REVISION, budget_bytes=minimum - 1)
            self.assertIn(previous["code"], {"view_subject_exceeds_budget", "view_envelope_exceeds_budget"})

    def test_envelope_budget_error_retries_exactly(self):
        store = FakeStore()
        small = context_view(store, revision=REVISION, budget_bytes=1)
        self.assertEqual(small["code"], "view_envelope_exceeds_budget")
        minimum = small["minimum_budget_bytes"]
        retried = context_view(store, revision=REVISION, budget_bytes=minimum)
        self.assertEqual(retried["schema"], "an-kla/context-view-v1")
        self.assertEqual(len(canonical_json(retried)), minimum)

    def test_minimum_budget_is_exact_across_decimal_bands(self):
        def build(budget, used):
            return {"budget": budget, "budget_again": budget, "used": used, "pad": "x" * 70}

        for provided in (9, 99, 999):
            with self.subTest(provided=provided):
                measured = _minimum_budget(build, provided)
                self.assertIsNotNone(measured)
                brute = next(
                    candidate for candidate in range(provided + 1, measured + 1)
                    if len(canonical_json(exact_sized_payload(lambda used: build(candidate, used))[0])) <= candidate
                )
                self.assertEqual(measured, brute)

    def test_snapshot_error_classification_is_fail_closed(self):
        store = FakeStore()
        for error, code in (
            (IntegrityError("object_missing:revisions"), "view_revision_not_available"),
            (IntegrityError("revision_archived_by_compaction"), "view_revision_not_available"),
            (IntegrityError("revision_hash_mismatch"), "view_internal_error"),
            (OSError("data read denied"), "view_internal_error"),
        ):
            with self.subTest(error=error):
                with patch.object(store, "_snapshot_under_gate", side_effect=error):
                    self.assertEqual(context_view(store, revision=REVISION)["code"], code)
        with patch("an_kla.context_view.shared_reader_gate", side_effect=ReaderGateError("reader_gate_unsafe_file")):
            self.assertEqual(context_view(store, revision=REVISION)["code"], "view_reader_gate_unavailable")

    def test_unavailable_measurement_and_oversized_cursor_fail_closed(self):
        row = fact("f-big", "big", "x" * 3000)
        store = FakeStore({"facts": [row]})
        with patch("an_kla.context_view._minimum_budget", return_value=None):
            output = context_view(store, revision=REVISION, budget_bytes=2000)
        self.assertEqual(output["code"], "view_budget_measurement_unavailable")
        self.assertFalse(output["retryable"])
        oversized = context_view(store, revision=REVISION, cursor="0" * 20_000)
        self.assertEqual(oversized["code"], "view_cursor_invalid")

    def test_reader_gate_is_held_during_projection(self):
        store = FakeStore({"facts": [fact("f-a", "svc", "A")]})
        seen = []
        from an_kla.record_text import record_text as real_record_text
        with patch("an_kla.context_view.record_text", side_effect=lambda record: (seen.append(reader_gate_mode(store)), real_record_text(record))[1]):
            output = context_view(store, revision=REVISION)
        self.assertEqual(output["schema"], "an-kla/context-view-v1")
        self.assertEqual(seen, ["shared"])

    def test_schemas_reject_trust_projection_and_error_confusion(self):
        valid = context_view(FakeStore({"facts": [fact("f-a", "svc", "A")]}), revision=REVISION)
        hostile = deepcopy(valid)
        hostile["subjects"][0]["alternatives"][0].update(
            {"state": "refuted", "state_source": "physical_status_untrusted"}
        )
        self.assertSchemaInvalid("context-view-v1", hostile)
        two_but_false = deepcopy(valid)
        two_but_false["subjects"][0]["alternatives"].append(
            deepcopy(two_but_false["subjects"][0]["alternatives"][0])
        )
        self.assertSchemaInvalid("context-view-v1", two_but_false)
        one_but_true = deepcopy(valid)
        one_but_true["subjects"][0]["data_conflict"] = True
        self.assertSchemaInvalid("context-view-v1", one_but_true)
        inactive_alternative = deepcopy(valid)
        inactive_alternative["subjects"][0]["alternatives"][0]["state"] = "inactive_untrusted"
        self.assertSchemaInvalid("context-view-v1", inactive_alternative)
        active_history = deepcopy(valid)
        active_history["subjects"][0]["history"] = [
            active_history["subjects"][0]["alternatives"].pop()
        ]
        self.assertSchemaInvalid("context-view-v1", active_history)
        wrong_projection = deepcopy(valid)
        wrong_projection["subjects"][0]["alternatives"][0]["record_raw"] = {"secret": True}
        self.assertSchemaInvalid("context-view-v1", wrong_projection)
        wrong_page = deepcopy(valid)
        wrong_page["pagination"]["complete"] = False
        self.assertSchemaInvalid("context-view-v1", wrong_page)
        unmarked_timestamp = deepcopy(valid)
        record = unmarked_timestamp["subjects"][0]["alternatives"][0]
        record["verified_at"] = "ATTACKER"
        self.assertSchemaInvalid("context-view-v1", unmarked_timestamp)
        freshness_without_now = deepcopy(valid)
        freshness_without_now["subjects"][0]["alternatives"][0]["days_since_verified"] = 1
        self.assertSchemaInvalid("context-view-v1", freshness_without_now)
        metadata = context_view(
            FakeStore({"facts": [fact("f-a", "svc", "A")]}),
            revision=REVISION, projection="metadata",
        )
        metadata["subjects"][0]["content_differs_beyond_text"] = True
        self.assertSchemaInvalid("context-view-v1", metadata)

        internal = {"schema": "an-kla/view-error-v1", "ok": False, "code": "view_internal_error",
                    "retryable": True, "untrusted_memory_data": True, "detail": {"host_path": "/secret"}}
        self.assertSchemaInvalid("view-error-v1", internal)
        self.assertSchemaInvalid("view-error-v1", _error_without_detail())
    def test_canonical_bytes_are_stable_across_physical_record_order(self):
        rows = [fact("f-b", "b", "B"), fact("f-a", "a", "A")]
        one = context_view(FakeStore({"facts": rows}), revision=REVISION)
        two = context_view(FakeStore({"facts": list(reversed(rows))}), revision=REVISION)
        self.assertEqual(canonical_json(one), canonical_json(two))

    def test_real_store_uses_pinned_snapshot_without_moving_current(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            base = store.initialize()
            identity_bytes = (Path(directory) / ".an-kla" / "project-identity.json").read_bytes()
            namespace = derive_namespace(identity_bytes)
            ref = f"an-kla:subject:v1:service:{namespace}:svc"
            revision = store.commit(
                expected_current_hash=base,
                checkpoint_patch={},
                facts=[{"id": "f-a", "subject_ref": ref, "payload": {"text": "A"}}],
            )
            current_before = store.current_path.read_bytes()
            output = context_view(store, revision=revision)
            self.assertEqual(output["subjects"][0]["subject_ref"], ref)
            self.assertEqual(store.current_path.read_bytes(), current_before)
            if (store.root / ".reader-gate").exists():
                self.assertEqual((store.root / ".reader-gate").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
