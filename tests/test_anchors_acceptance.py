"""ADR-0066 §8 acceptance criteria, end to end on real Git and a real store (no mocks of the anchors)."""

from __future__ import annotations

import json
import os
from argparse import Namespace
from typing import Any
from unittest import mock

from an_kla import disputes
from an_kla.anchors_git import GitRepo
from an_kla.anchors_read import AnchorServer, verify_command
from an_kla.canonical import canonical_json
from an_kla.inbox import payload_digest
from an_kla.inbox_anchors import payload_extra
from an_kla.remember import RememberError, remember
from an_kla.state_show import state_show
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase, run_git

DOC = "# Bandeja\n\nEl servidor usa port = 8081.\nOtra línea con renovacion indefinida de custodia.\n"


class AnchorCase(InboxCase):
    def setUp(self) -> None:
        super().setUp()
        # A repo without a remote has no ``origin/HEAD``: the tests declare their default branch.
        patcher = mock.patch.dict(os.environ, {"AN_KLA_DEFAULT_BRANCH": "main"})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.project / "docs").mkdir()
        (self.project / "docs" / "a.md").write_text(DOC, encoding="utf-8")
        run_git(self.project, "add", "-A")
        run_git(self.project, "commit", "-q", "-m", "doc")
        with GitRepo(self.project) as repo:
            self.head = repo.head()

    def anchor(self, quote: str = "El servidor usa port = 8081", **source: Any) -> dict[str, Any]:
        return {"source": {"kind": "repo-file", "path": "docs/a.md", "commit": self.head, **source}, "quote": quote}

    def say(self, text: str, **options: Any) -> dict[str, Any]:
        return remember(self.store, text, env=dict(AGENT_ENV), **options)

    def record(self, record_id: str) -> dict[str, Any]:
        snap = self.store.snapshot()
        return next(r for s in snap.records.values() for r in s if r.get("id") == record_id)

    def verify(self, **kw: Any) -> dict[str, Any]:
        args = {"id": None, "all": False, "anchor_limit": 32, **kw}
        return verify_command(self.store, Namespace(**args))

    def pending(self) -> list[str]:
        return sorted(os.listdir(self.inbox / "pending")) if (self.inbox / "pending").exists() else []


class CriteriaTest(AnchorCase):
    def test_8080_against_8081_is_none_with_the_number_pointed_at(self) -> None:
        result = self.say("el servidor usa el puerto 8080", anchors=[self.anchor()])
        self.assertEqual(result["state"], "committed")
        self.assertEqual(result["coverage"], {"total": 1, "present": 0, "level": "none"})
        self.assertEqual(result["missing"], [{"type": "number", "value": "8080"}])
        self.assertEqual(result["missing_total"], 1)
        stored = self.record(result["record_id"])  # top-level siblings of the record, saved as computed
        self.assertEqual((stored["coverage"], stored["missing"], stored["missing_total"]),
                         (result["coverage"], result["missing"], result["missing_total"]))
        self.assertEqual(result["anchors"][0]["freshness"], "fresh")  # the quote is there; the claim is not backed

    def test_a_missing_quote_is_rejected_and_nothing_changes(self) -> None:
        before = self.store.read_current()
        with self.assertRaises(RememberError) as caught:
            self.say("el servidor usa 8081", anchors=[self.anchor("Esto no está en el archivo")])
        self.assertEqual(str(caught.exception), "anchor_quote_not_found")
        self.assertEqual((self.pending(), self.store.read_current()), ([], before))

    def test_seventeen_anchors_are_too_many_before_any_check(self) -> None:
        with self.assertRaises(RememberError) as caught:
            self.say("x" * 12, anchors=[self.anchor()] * 16 + [self.anchor("no existe en el archivo")])
        self.assertEqual(str(caught.exception), "anchor_too_many")
        self.assertEqual(self.pending(), [])

    def test_coverage_is_measured_against_the_quote_not_matched_text(self) -> None:
        # The source has no accent; the quote (what is stored) does: the identifier is present in the quote.
        anchor = self.anchor("Otra línea con renovación indefinida")
        result = self.say("la nota habla de `renovación`", anchors=[anchor])
        self.assertEqual(result["anchors"][0]["match"], "ws-nfc-accents/v1")
        self.assertNotIn("ó", result["anchors"][0]["matched_text"])
        self.assertEqual(result["coverage"]["level"], "full")

    def test_an_explicit_key_with_other_anchors_is_a_collision(self) -> None:
        key = "clave-estable"
        first = self.say("el puerto del servidor es 8081", idempotency_key=key, anchors=[self.anchor()])
        self.assertEqual(first["state"], "committed")
        other = self.say("el puerto del servidor es 8081", idempotency_key=key,
                         anchors=[self.anchor("Otra línea con renovacion indefinida")])
        self.assertEqual((other["state"], other["code"]), ("rejected", "remember_id_collision"))
        self.assertEqual(other["reason_codes"], ["idempotency_key_other_anchors"])
        again = self.say("el puerto del servidor es 8081", idempotency_key=key, anchors=[self.anchor()])
        self.assertTrue(again.get("already_committed"))

    def test_a_state_with_anchors_collides_on_other_anchors_too(self) -> None:
        key = "estado-estable"
        self.assertEqual(self.say("trabajo en curso", kind="state", idempotency_key=key,
                                  anchors=[self.anchor(commit=None)])["state"], "committed")
        other = self.say("trabajo en curso", kind="state", idempotency_key=key,
                         anchors=[self.anchor("Otra línea con renovacion indefinida", commit=None)])
        self.assertEqual((other["state"], other["reason_codes"]), ("rejected", ["idempotency_key_other_anchors"]))

    def test_plain_records_stay_byte_identical(self) -> None:
        result = self.say("un recuerdo sin ancla alguna")
        record = self.record(result["record_id"])
        self.assertEqual(set(record), {"id", "text", "an_kla_envelope"})
        self.assertNotIn("anchors", record)
        self.assertEqual({k: v for k, v in result.items() if k in ("anchors", "coverage", "missing", "missing_total")}, {})


class DisputeTest(AnchorCase):
    def test_a_dispute_never_retires_the_state_it_judges(self) -> None:
        state = self.say("el estado de hoy", kind="state")
        head = state["record_id"] if "record_id" in state else next(
            r["id"] for r in self.store.snapshot().records["episodes"])
        dispute = self.say("el dictamen dice otra cosa", kind="fact", supersedes=head, verdict="contradicted",
                           operation="dispute", idempotency_key="dictamen-1")
        self.assertEqual(dispute["state"], "committed")
        self.assertEqual(dispute["stream"], "facts")
        row = self.record(dispute["record_id"])
        self.assertEqual((row["verdict"], row["disputes"]["stream"], row["disputes"]["target_id"]),
                         ("contradicted", "episodes", head))
        shown = state_show(self.store)
        self.assertEqual([s["id"] for s in shown["slots"]], [head])  # still the head of its slot
        self.assertEqual(shown["slots"][0]["disputed"][0]["verdict"], "contradicted")
        listed = disputes.list_disputes(self.store.snapshot(), target=head)["disputes"]
        self.assertEqual(listed[0]["verdict"], "contradicted")

    def test_the_latest_verdict_of_each_writer_is_the_one_shown(self) -> None:
        fact = self.say("un hecho disputable")["record_id"]
        for n, verdict in enumerate(("insufficient", "contradicted")):
            self.say(f"dictamen número {n}", supersedes=fact, kind="fact", verdict=verdict, operation="dispute")
        server = AnchorServer(self.store, self.store.snapshot())
        served = server.serve("facts", self.record(fact))
        self.assertEqual([d["verdict"] for d in served["disputed"]], ["contradicted"])

    def test_a_dispute_of_nothing_is_refused(self) -> None:
        from an_kla.anchors_cli import run

        with self.assertRaises(RememberError) as caught:
            run(self.store, Namespace(command="dispute", target="f-r-inexistente", verdict="contradicted",
                                      text="x", text_file=None, idempotency_key=None, anchor_file=None))
        self.assertEqual(str(caught.exception), "dispute_target_missing")

    def test_supported_is_not_a_verdict_of_the_store(self) -> None:
        from an_kla.anchors_cli import run

        for verdict in ("supported", "not_reviewed", "otro"):
            with self.assertRaises(RememberError) as caught:
                run(self.store, Namespace(command="dispute", target="x", verdict=verdict, text="t", text_file=None,
                                          idempotency_key=None, anchor_file=None))
            self.assertEqual(str(caught.exception), "dispute_verdict_invalid")


class ReadTest(AnchorCase):
    def test_forty_anchors_served_are_thirty_two_checked_and_eight_limited(self) -> None:
        ids = []
        for n, count in enumerate((16, 16, 8)):
            anchors = [self.anchor()] * count
            ids.append(self.say(f"registro número {n} con anclas", anchors=anchors)["record_id"])
        out = self.verify(all=True)
        self.assertEqual((out["anchor_limit"], out["anchors_checked"], out["anchors_unchecked"]), (32, 32, 8))
        last = out["records"][-1]["anchors"]
        self.assertEqual({a["reason"] for a in last}, {"anchor_limit"})
        self.assertEqual({a["freshness"] for a in last}, {"unverified"})
        self.assertEqual(out["records"][-1]["anchors_freshness"], "unverified")
        self.assertEqual(out["records"][0]["anchors_freshness"], "fresh")
        small = self.verify(all=True, anchor_limit=3)
        self.assertEqual((small["anchors_checked"], small["anchors_unchecked"]), (3, 37))

    def test_an_empty_default_branch_variable_means_no_default_branch(self) -> None:
        rid = self.say("el servidor usa 8081", anchors=[self.anchor()])["record_id"]
        with mock.patch.dict(os.environ, {"AN_KLA_DEFAULT_BRANCH": ""}):
            out = self.verify(id=rid)
        item = out["records"][0]["anchors"][0]
        self.assertEqual((item["source"], item["source_reason"], item["at"]), ("unverifiable", "no_default_branch", None))
        with mock.patch.dict(os.environ, {"AN_KLA_DEFAULT_BRANCH": "main"}):
            self.assertEqual(self.verify(id=rid)["records"][0]["anchors"][0]["freshness"], "fresh")

    def test_a_changed_file_turns_a_fact_stale_on_read(self) -> None:
        rid = self.say("el servidor usa 8081", anchors=[self.anchor()])["record_id"]
        (self.project / "docs" / "a.md").write_text("otro contenido\n", encoding="utf-8")
        run_git(self.project, "commit", "-q", "-a", "-m", "cambio")
        item = self.verify(id=rid)["records"][0]
        self.assertEqual(item["anchors_freshness"], "stale")
        self.assertEqual(item["anchors"][0]["quote_reason"], "quote_absent")

    def test_state_show_serves_freshness_and_declares_the_limit(self) -> None:
        self.say("trabajo en curso", kind="state", anchors=[self.anchor(commit=None)])
        shown = state_show(self.store, anchor_limit=2)
        head = shown["slots"][0]
        self.assertEqual((head["anchors_freshness"], head["anchors"][0]["at"]), ("fresh", "worktree"))
        self.assertEqual((shown["anchor_limit"], shown["anchors_checked"], shown["anchors_unchecked"]), (2, 1, 0))

    def test_nothing_anchored_leaves_the_plain_output_alone(self) -> None:
        self.say("sin anclas", kind="state")
        shown = state_show(self.store)
        self.assertNotIn("anchor_limit", shown)
        self.assertNotIn("anchors", shown["slots"][0])


class ResolutionTest(AnchorCase):
    def _conversation_record(self) -> str:
        anchor = {"source": {"kind": "conversation"}, "quote": "manda renovar de manera indefinida"}
        result = self.say("se pidió renovar sin fin", anchors=[anchor])
        self.assertEqual(result["anchors"][0]["freshness"], "pending")
        return result["record_id"]

    def _resolution_entry(self, factory: EntryFactory, record_id: str, index: int, **resolution: Any) -> str:
        rec = self.record(record_id)
        res = {"schema": "an-kla/anchor-resolution-v1",
               "target": {"stream": "facts", "record_id": record_id, "anchor_index": index,
                          "quote_sha256": rec["anchors"][0]["quote_sha256"]},
               "resolution": "resolved", "turn_id": "t2", "seal": "sello", **resolution}
        data = factory.entry("anotación de resolución", kind="fact", key=factory.identity_c0.derive_idempotency_key(
            factory.identity, "fact", "anotación de resolución " + str(index) + str(resolution), None, None))
        data.update(schema="an-kla/inbox-entry-v3", operation="anchor_resolution", anchor_resolution=res)
        data["payload_sha256"] = payload_digest(data["text"], "fact", None, None, payload_extra(data))
        name = factory.name_for(data)
        (factory.pending).mkdir(parents=True, exist_ok=True)
        (factory.pending / name).write_bytes(canonical_json(data))
        return name

    def test_an_index_out_of_range_is_anchor_resolution_invalid(self) -> None:
        from an_kla.inbox_drain import drain

        rid = self._conversation_record()
        name = self._resolution_entry(EntryFactory(self.store), rid, 5)
        report = drain(self.store, include_entry=name, max_batches=1)
        self.assertEqual([r["code"] for r in report["rejected"]["entries"]], ["anchor_resolution_invalid"])

    def test_the_last_resolution_wins_in_the_view_and_a_valid_one_is_stored_as_an_event(self) -> None:
        from an_kla.inbox_drain import drain

        rid = self._conversation_record()
        factory = EntryFactory(self.store)
        names = [self._resolution_entry(factory, rid, 0, resolution="not_found", turn_id=None, seal=None),
                 self._resolution_entry(factory, rid, 0)]
        report = drain(self.store, include_entry=names[0], max_batches=1)  # both are pending: one batch
        self.assertEqual(len(report["committed"]["entries"]), 2, report)
        events = [e for e in self.store.snapshot().records["events"] if e.get("kind") == "anchor_resolution"]
        self.assertEqual(len(events), 2)  # annotations live in `events`, beside the policy decisions
        item = self.verify(id=rid)["records"][0]["anchors"][0]
        # The later annotation (resolved) wins; with no verifier installed the turn cannot be read.
        self.assertEqual((item["resolution"], item["turn_id"], item["reason"]), ("resolved", "t2", "no_verifier"))
        self.assertEqual(item["freshness"], "unverified")


class Errata3OwnTest(AnchorCase):
    """The nine readings of erratum 3 have no vectors: their own cases (a discrepancy becomes a vector proposal)."""

    def test_2_the_machine_ignore_never_counts_and_1_tracked_wins_over_ignore(self) -> None:
        from an_kla.anchors_repo_file import verify_repo_file

        glob = self.project.parent / "ignorados-globales"
        glob.write_text("sombra.md\n")
        (self.project / "sombra.md").write_text("El servidor usa port = 8081\n")
        run_git(self.project, "config", "core.excludesFile", str(glob))
        anchor = {"schema": "memoria/ancla/v1", "source": {"kind": "repo-file", "repo": "r", "commit": None,
                                                              "path": "sombra.md"}, "quote": "El servidor usa port = 8081"}
        with GitRepo(self.project) as repo:
            got = verify_repo_file(repo, anchor, "state", "write")
        self.assertEqual((got["source"], got["freshness"]), ("verified", "fresh"))  # core.excludesFile is not an ignore
        with (self.project / ".git" / "info" / "exclude").open("a") as handle:
            handle.write("rastreado.md\n")
        (self.project / "rastreado.md").write_text("El servidor usa port = 8081\n")
        run_git(self.project, "add", "-f", "rastreado.md")
        anchor["source"]["path"] = "rastreado.md"
        with GitRepo(self.project) as repo:
            self.assertEqual(verify_repo_file(repo, anchor, "state", "write")["source"], "verified")

    def test_3_an_unreadable_state_file_is_repo_unavailable_and_never_rejects(self) -> None:
        from an_kla.anchors_repo_file import verify_repo_file, write_rejection

        path = self.project / "docs" / "a.md"
        anchor = {"schema": "memoria/ancla/v1", "source": {"kind": "repo-file", "repo": "r", "commit": None,
                                                              "path": "docs/a.md"}, "quote": "El servidor usa port = 8081"}
        path.chmod(0)
        self.addCleanup(path.chmod, 0o644)
        if os.access(path, os.R_OK):
            self.skipTest("root reads anything")
        with GitRepo(self.project) as repo:
            got = verify_repo_file(repo, anchor, "state", "write")
        self.assertEqual((got["source"], got["source_reason"]), ("unverifiable", "repo_unavailable"))
        self.assertEqual((got["quote_reason"], got["integrity_reason"]), ("source_not_verified", "source_not_verified"))
        self.assertIsNone(write_rejection(got))

    def test_5_the_order_applies_anchor_by_anchor(self) -> None:
        bad_shape = {"source": {"kind": "wiki"}, "quote": "x"}
        missing = self.anchor("no está en el archivo del todo")
        for anchors, code in (([missing, bad_shape], "anchor_quote_not_found"), ([bad_shape, missing], "anchor_schema_invalid")):
            with self.assertRaises(RememberError) as caught:
                self.say("texto del registro", anchors=anchors)
            self.assertEqual(str(caught.exception), code)

    def test_6_to_9_document_locator_conversation_turn_hex_and_normalised_quotes(self) -> None:
        from an_kla.anchors import AnchorRejected, quote_sha256, validate_anchor
        from an_kla.anchors_conversation import check_conversation

        doc = {"schema": "memoria/ancla/v1", "source": {"kind": "document", "document_sha256": "a" * 64,
               "derivation": {"custodian": "c", "derivation_id": "d", "manifest_sha256": "m", "modality": "native_text"}},
               "quote": "El personal de base tendrá derecho a veinte días de vacaciones"}
        self.assertEqual(validate_anchor(doc, "fact")["source"]["document_sha256"], "a" * 64)  # no locator: "unknown"
        upper = json.loads(json.dumps(doc))
        upper["source"]["document_sha256"] = "A" * 64
        with self.assertRaises(AnchorRejected) as caught:
            validate_anchor(upper, "fact")
        self.assertEqual(caught.exception.code, "anchor_schema_invalid")
        conv = {"schema": "memoria/ancla/v1", "source": {"kind": "conversation", "session": "s", "resolution": "resolved",
                                                          "turn_id": None, "seal": None}, "quote": "manda renovar de manera"}

        class Never:
            def turn(self, *_: Any) -> Any:
                raise AssertionError("a null turn is never looked up")

        got = check_conversation(conv, Never())
        self.assertEqual((got["source"], got["source_reason"], got["freshness"]), ("not_found", "turn_purged", "broken"))
        padded = {"schema": "memoria/ancla/v1", "source": {"kind": "conversation", "session": "s", "resolution": "pending",
                  "turn_id": None, "seal": None}, "quote": "manda renovar de manera ", "quote_sha256": "0" * 64}
        with self.assertRaises(AnchorRejected) as caught:
            validate_anchor(padded, "fact")
        self.assertEqual(caught.exception.code, "anchor_quote_not_normalized")
        long_padded = {**padded, "quote": "a" * 301 + " "}  # not-normalised is decided before the size
        with self.assertRaises(AnchorRejected) as caught:
            validate_anchor(long_padded, "fact")
        self.assertEqual(caught.exception.code, "anchor_quote_not_normalized")
        ok = {**padded, "quote": "manda renovar de manera"}
        ok["quote_sha256"] = quote_sha256(ok["quote"])
        self.assertEqual(validate_anchor(ok, "fact")["quote_sha256"], ok["quote_sha256"])
