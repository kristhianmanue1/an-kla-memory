"""ADR-0063 D3: sustitución propia, disputa de lo ajeno y `disputes list`.

Sin `remember`: los planes se construyen con `an_kla.disputes` y se comprometen
por el camino existente (`commit_write_plan`) sobre un store desechable.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from an_kla import disputes
from an_kla import identity_c0 as c0
from an_kla.canonical import digest_json
from an_kla.schemas import schema_catalog
from an_kla.store import MemoryStore, Snapshot
from an_kla.vigency import is_active
from an_kla.write_policy import WritePolicyError

ROOT = Path(__file__).resolve().parents[1]
REPO = "github.com/kristhianmanue1/an-kla-memory"
FIXED_CLOCK = lambda: datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def writer(name: str, *, session: str = "s1", repo: str = REPO, cli: str = "claude-code") -> dict:
    identity = {
        "schema": c0.IDENTITY_SCHEMA,
        "repo": {"id": repo},
        "agent": {"name": name, "cli": cli, "model": "claude-sonnet-5-5", "role": "ejecutor"},
        "session": {"id": f"{cli}:{session}"},
    }
    assert c0.validate(identity) == [], c0.validate(identity)
    return identity


def envelope(identity: dict, text: str, kind: str = "fact", target: str | None = None) -> dict:
    key = c0.derive_idempotency_key(identity, kind, text, target)
    return c0.build_envelope(identity, kind, key, FIXED_CLOCK)


class DisputeBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root)
        self.store.initialize()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, proposal: dict) -> dict:
        planning = disputes.build_remember_plan(proposal)
        result = self.store.commit_write_plan(
            expected_current_hash=proposal["base_revision"],
            plan=planning["plan"],
            proposal=planning["proposal"],
            authority=planning["authority"],
            decision=planning["decision"],
        )
        self.assertTrue(result["committed"], result)
        return result

    def remember(self, identity: dict, text: str, *, kind: str = "fact",
                 target: str | None = None, kind_explicit: bool = False) -> disputes.RememberOp:
        """Lo que haría `remember` sin cola: resuelve, planifica y compromete."""
        snapshot = self.store.snapshot()
        op = disputes.resolve_remember(
            snapshot,
            envelope=envelope(identity, text, kind, target),
            text=text,
            kind=kind,
            kind_explicit=kind_explicit,
            target_id=target,
        )
        self.commit(disputes.build_remember_proposal(self.store.read_current(), [op]))
        return op

    def legacy_add(self, record_id: str, stream: str = "facts", text: str = "dato legado") -> None:
        """Un record sin sobre, escrito por la vía `plan-write` de siempre."""
        base = self.store.read_current()
        proposal = {
            "schema": "an-kla/write-proposal-v1",
            "base_revision": base,
            "stream": stream,
            "operation": "add",
            "requested_representation": "summary",
            "record": {"id": record_id, "text": text},
            "lineage": {"derived_from_retrieval": False, "refs": []},
        }
        self.commit(proposal)

    def row(self, record_id: str, stream: str = "facts") -> dict:
        snapshot = self.store.snapshot()
        return next(r for r in snapshot.records[stream] if r["id"] == record_id)

    def raw(self, record_id: str, stream: str = "facts") -> dict:
        snapshot = self.store.snapshot()
        return next(r for r in snapshot.raw_records[stream] if r["id"] == record_id)


class DisputeResolutionTests(DisputeBase):
    def test_foreign_target_is_disputed_and_stays_active(self) -> None:
        a, b = writer("agente-a"), writer("agente-b")
        fact_b = self.remember(b, "el puerto es 8080")
        digest_before = digest_json(self.raw(fact_b.record["id"]))
        op = self.remember(a, "el puerto es 9090", target=fact_b.record["id"])

        self.assertEqual(op.operation, "add")
        self.assertIsNone(op.supersedes)
        expected = {
            "stream": "facts",
            "target_id": fact_b.record["id"],
            "target_record_sha256": digest_before,
        }
        self.assertEqual(op.record["disputes"], expected)
        self.assertEqual(op.result_fields(), {"disputed": expected})
        # El de B sigue vigente, físicamente intacto y sin overlays.
        self.assertTrue(is_active(self.row(fact_b.record["id"])))
        self.assertEqual(digest_json(self.raw(fact_b.record["id"])), digest_before)
        manifest = self.store.snapshot().manifest
        self.assertEqual(manifest.get("supersedes_map", []), [])
        self.assertEqual(manifest.get("refutations_map", []), [])
        # El record de disputa existe, es vigente y lleva el sobre de A.
        dispute = self.row(op.record["id"])
        self.assertTrue(is_active(dispute))
        self.assertEqual(dispute["an_kla_envelope"]["writer"]["agent"]["name"], "agente-a")
        self.assertEqual(
            self.store.snapshot().raw_records["facts"][-1]["id"], op.record["id"]
        )

    def test_own_target_is_superseded(self) -> None:
        a = writer("agente-a")
        first = self.remember(a, "el puerto es 8080")
        op = self.remember(a, "el puerto es 9090", target=first.record["id"])

        self.assertEqual(op.operation, "supersede")
        self.assertEqual(op.supersedes, first.record["id"])
        self.assertNotIn("disputes", op.record)
        self.assertEqual(op.result_fields(), {"superseded": first.record["id"]})
        self.assertEqual(self.row(first.record["id"])["status"], "sustituida")
        self.assertTrue(is_active(self.row(op.record["id"])))
        manifest = self.store.snapshot().manifest
        self.assertEqual(
            manifest["supersedes_map"],
            [{"stream": "facts", "target_id": first.record["id"], "sustituida_por": op.record["id"]}],
        )

    def test_legacy_target_without_envelope_is_disputed(self) -> None:
        self.legacy_add("f-legado")
        op = self.remember(writer("agente-a"), "corrección", target="f-legado")

        self.assertEqual(op.operation, "add")
        self.assertEqual(op.record["disputes"]["target_id"], "f-legado")
        self.assertEqual(
            op.record["disputes"]["target_record_sha256"], digest_json(self.raw("f-legado"))
        )
        self.assertTrue(is_active(self.row("f-legado")))

    def test_sin_nombre_never_owns_even_its_own_fact(self) -> None:
        anonymous = writer(c0.NAME_SENTINEL)
        first = self.remember(anonymous, "dato anónimo")
        op = self.remember(anonymous, "dato anónimo corregido", target=first.record["id"])

        self.assertEqual(op.operation, "add")
        self.assertIn("disputes", op.record)
        self.assertTrue(is_active(self.row(first.record["id"])))

    def test_same_agent_name_other_session_supersedes_without_dispute(self) -> None:
        first = self.remember(writer("agente-a", session="sesion-1"), "versión uno")
        op = self.remember(
            writer("agente-a", session="sesion-2"), "versión dos", target=first.record["id"]
        )

        self.assertEqual(op.operation, "supersede")
        self.assertEqual(self.row(first.record["id"])["status"], "sustituida")
        # Auditable: los dos sobres conservan su session.id.
        sessions = {
            self.raw(r.record["id"])["an_kla_envelope"]["writer"]["session"]["id"]
            for r in (first, op)
        }
        self.assertEqual(sessions, {"claude-code:sesion-1", "claude-code:sesion-2"})

    def test_same_agent_name_in_another_repo_is_foreign(self) -> None:
        first = self.remember(writer("agente-a"), "dato del repo uno")
        op = self.remember(
            writer("agente-a", repo="github.com/otra-org/otro-repo"),
            "dato del repo dos",
            target=first.record["id"],
        )
        self.assertEqual(op.operation, "add")
        self.assertIn("disputes", op.record)

    def test_same_text_with_two_targets_gives_two_records(self) -> None:
        a, b = writer("agente-a"), writer("agente-b")
        t1 = self.remember(b, "primer dato")
        t2 = self.remember(b, "segundo dato")
        d1 = self.remember(a, "no es cierto", target=t1.record["id"])
        d2 = self.remember(a, "no es cierto", target=t2.record["id"])

        self.assertNotEqual(d1.record["id"], d2.record["id"])
        ids = [r["id"] for r in self.store.snapshot().records["facts"]]
        self.assertIn(d1.record["id"], ids)
        self.assertIn(d2.record["id"], ids)
        self.assertEqual(
            {d1.record["disputes"]["target_id"], d2.record["disputes"]["target_id"]},
            {t1.record["id"], t2.record["id"]},
        )

    def test_state_kind_goes_to_episodes_and_target_decides_the_stream(self) -> None:
        a = writer("agente-a")
        state = self.remember(a, "estado inicial", kind="state")
        self.assertEqual(state.stream, "episodes")
        self.assertTrue(state.record["id"].startswith("ep-r-"))
        replacement = self.remember(
            a, "estado nuevo", kind="state", target=state.record["id"], kind_explicit=True
        )
        self.assertEqual(replacement.stream, "episodes")
        self.assertEqual(self.row(state.record["id"], "episodes")["status"], "sustituida")


class DisputeErrorTests(DisputeBase):
    def resolve(self, target: str, *, kind: str = "fact", explicit: bool = False):
        a = writer("agente-a")
        return disputes.resolve_supersede_target(
            self.store.snapshot(), target, kind=kind, kind_explicit=explicit,
            envelope=envelope(a, "x", kind, target),
        )

    def test_missing_target(self) -> None:
        with self.assertRaises(WritePolicyError) as caught:
            self.resolve("f-no-existe")
        self.assertEqual(caught.exception.code, "invalid_supersede_target")

    def test_not_vigente_target(self) -> None:
        a = writer("agente-a")
        first = self.remember(a, "uno")
        self.remember(a, "dos", target=first.record["id"])
        with self.assertRaises(WritePolicyError) as caught:
            self.resolve(first.record["id"])
        self.assertEqual(caught.exception.code, "invalid_supersede_target")
        self.assertEqual(caught.exception.detail, "target_not_vigente")

    def test_ambiguous_target_in_two_streams(self) -> None:
        self.legacy_add("dup-1", "facts")
        self.legacy_add("dup-1", "episodes")
        with self.assertRaises(WritePolicyError) as caught:
            self.resolve("dup-1")
        self.assertEqual(caught.exception.code, "remember_target_ambiguous")

    def test_kind_mismatch_explicit_and_derived(self) -> None:
        self.legacy_add("f-hecho", "facts")
        for explicit, detail in ((True, "kind_explicit"), (False, "kind_derived")):
            with self.subTest(explicit=explicit):
                with self.assertRaises(WritePolicyError) as caught:
                    self.resolve("f-hecho", kind="state", explicit=explicit)
                self.assertEqual(caught.exception.code, "remember_kind_mismatch")
                self.assertEqual(caught.exception.detail, detail)
        self.legacy_add("ep-estado", "episodes")
        with self.assertRaises(WritePolicyError) as caught:
            self.resolve("ep-estado", kind="decision", explicit=True)
        self.assertEqual(caught.exception.code, "remember_kind_mismatch")

    def test_event_target_never_matches_a_kind(self) -> None:
        self.legacy_add("f-semilla", "facts")
        event_id = next(
            r["id"] for r in self.store.snapshot().records["events"]
            if r.get("type") == "write_policy_decision"
        )
        for kind in ("fact", "decision", "state"):
            with self.subTest(kind=kind):
                with self.assertRaises(WritePolicyError) as caught:
                    self.resolve(event_id, kind=kind)
                self.assertEqual(caught.exception.code, "remember_kind_mismatch")

    def test_error_leaves_the_store_untouched(self) -> None:
        before = self.store.read_current()
        with self.assertRaises(WritePolicyError):
            self.resolve("f-no-existe")
        self.assertEqual(self.store.read_current(), before)


class RawRecordsDigestTests(DisputeBase):
    def test_digest_is_taken_over_raw_records_not_over_overlaid_records(self) -> None:
        # Control negativo. Con overlay, `records` y `raw_records` difieren: el
        # digest sobre uno no es el del otro.
        a = writer("agente-a")
        first = self.remember(a, "uno")
        self.remember(a, "dos", target=first.record["id"])
        snapshot = self.store.snapshot()
        raw = next(r for r in snapshot.raw_records["facts"] if r["id"] == first.record["id"])
        overlaid = next(r for r in snapshot.records["facts"] if r["id"] == first.record["id"])
        self.assertEqual(overlaid["status"], "sustituida")
        self.assertNotEqual(digest_json(overlaid), digest_json(raw))

    def test_function_uses_raw_records_even_if_records_diverge(self) -> None:
        # Un objetivo vigente nunca lleva overlay en un snapshot real, así que se
        # fabrica un snapshot cuyo `records` difiere del `raw_records` sin quitar
        # vigencia: sólo el selector correcto da el digest del record canónico.
        self.legacy_add("f-ajeno")
        real = self.store.snapshot()
        index = next(i for i, r in enumerate(real.raw_records["facts"]) if r["id"] == "f-ajeno")
        tampered_rows = list(real.records["facts"])
        tampered_rows[index] = {**tampered_rows[index], "marca_de_overlay": True}
        fake = Snapshot(
            real.revision_id, real.manifest, real.checkpoint,
            {**real.records, "facts": tuple(tampered_rows)}, real.raw_records,
        )
        raw_digest = digest_json(real.raw_records["facts"][index])
        self.assertNotEqual(digest_json(fake.records["facts"][index]), raw_digest)

        resolution = disputes.resolve_supersede_target(
            fake, "f-ajeno", kind="fact", kind_explicit=False,
            envelope=envelope(writer("agente-a"), "x"),
        )
        self.assertEqual(resolution.target_record_sha256, raw_digest)
        self.assertFalse(resolution.own)


class BuildersTests(DisputeBase):
    def test_record_shape_and_id_from_the_key(self) -> None:
        a = writer("agente-a")
        env = envelope(a, "texto")
        op = disputes.build_remember_op(env, "texto", "fact")
        self.assertEqual(op.operation, "add")
        self.assertEqual(set(op.record), {"id", "text", "an_kla_envelope"})
        self.assertEqual(op.record["id"], "f-r-" + env["idempotency_key"][7:31])
        self.assertEqual(op.result_fields(), {})

    def test_batch_proposal_is_homogeneous(self) -> None:
        a = writer("agente-a")
        add = disputes.build_remember_op(envelope(a, "uno"), "uno", "fact")
        state = disputes.build_remember_op(envelope(a, "dos", "state"), "dos", "state")
        with self.assertRaises(ValueError):
            disputes.build_remember_proposal(self.store.read_current(), [add, state])
        with self.assertRaises(ValueError):
            disputes.build_remember_proposal(self.store.read_current(), [])

    def test_batch_of_disputes_commits_as_adds(self) -> None:
        a, b = writer("agente-a"), writer("agente-b")
        t1, t2 = self.remember(b, "uno"), self.remember(b, "dos")
        snapshot = self.store.snapshot()
        ops = [
            disputes.resolve_remember(
                snapshot, envelope=envelope(a, f"no {n}", "fact", t.record["id"]),
                text=f"no {n}", kind="fact", kind_explicit=False, target_id=t.record["id"],
            )
            for n, t in (("uno", t1), ("dos", t2))
        ]
        proposal = disputes.build_remember_proposal(self.store.read_current(), ops)
        self.assertEqual(proposal["schema"], "an-kla/write-proposal-v2")
        self.assertEqual(proposal["operation"], "add")
        self.commit(proposal)
        self.assertEqual(self.store.snapshot().manifest.get("supersedes_map", []), [])
        self.assertTrue(is_active(self.row(t1.record["id"])))
        self.assertEqual(len(disputes.list_disputes(self.store.snapshot())["disputes"]), 2)

    def test_policy_accepts_the_plan_without_skip_reasons(self) -> None:
        a = writer("agente-a")
        op = disputes.build_remember_op(envelope(a, "texto"), "texto", "fact")
        planning = disputes.build_remember_plan(
            disputes.build_remember_proposal(self.store.read_current(), [op])
        )
        self.assertEqual(planning["decision"]["decision"], "write-summary")
        self.assertEqual(
            planning["decision"]["reason_codes"],
            ["derived_authority_capped", "representation_accepted"],
        )


class DisputesListTests(DisputeBase):
    def test_list_filters_by_target_and_reports_digest_and_writer(self) -> None:
        a, b = writer("agente-a"), writer("agente-b")
        t1 = self.remember(b, "uno")
        t2 = self.remember(b, "dos")
        d1 = self.remember(a, "no uno", target=t1.record["id"])
        self.remember(a, "no dos", target=t2.record["id"])
        self.remember(a, "no es disputa")

        everything = disputes.list_disputes(self.store.snapshot())
        self.assertEqual(everything["schema"], "an-kla/disputes-list-v1")
        self.assertTrue(everything["untrusted_memory_data"])
        self.assertEqual(len(everything["disputes"]), 2)

        only = disputes.list_disputes(self.store.snapshot(), target=t1.record["id"])
        self.assertEqual(only["target"], t1.record["id"])
        (item,) = only["disputes"]
        self.assertEqual(item["id"], d1.record["id"])
        self.assertEqual(item["target"]["record_sha256"], digest_json(self.raw(t1.record["id"])))
        self.assertEqual(item["target"]["active"], True)
        self.assertEqual(item["writer"]["agent"]["name"], "agente-a")
        self.assertEqual(item["enqueued_at"], "2026-11-15T12:00:00.000000Z")
        self.assertEqual(item["text"], "no uno")
        self.assertEqual(
            disputes.list_disputes(self.store.snapshot(), target="f-otro")["disputes"], []
        )

    def test_list_omits_a_superseded_dispute(self) -> None:
        a, b = writer("agente-a"), writer("agente-b")
        target = self.remember(b, "uno")
        dispute = self.remember(a, "no uno", target=target.record["id"])
        self.remember(a, "no uno, corregido", target=dispute.record["id"])
        listed = disputes.list_disputes(self.store.snapshot())["disputes"]
        self.assertEqual([i["id"] for i in listed if i["id"] == dispute.record["id"]], [])

    def test_malformed_disputes_object_is_not_a_dispute(self) -> None:
        base = self.store.read_current()
        self.commit({
            "schema": "an-kla/write-proposal-v1", "base_revision": base, "stream": "facts",
            "operation": "add", "requested_representation": "summary",
            "record": {"id": "f-raro", "text": "x", "disputes": {"target_id": "f-1"}},
            "lineage": {"derived_from_retrieval": False, "refs": []},
        })
        self.assertEqual(disputes.list_disputes(self.store.snapshot())["disputes"], [])

    def test_list_is_pure_and_does_not_move_current(self) -> None:
        self.remember(writer("agente-b"), "uno")
        before = self.store.read_current()
        disputes.list_disputes(self.store.snapshot())
        self.assertEqual(self.store.read_current(), before)

    def test_schema_is_registered_and_validates_the_output(self) -> None:
        names = [item["name"] for item in schema_catalog()["schemas"]]
        self.assertIn("disputes-list-v1", names)
        mirror = (ROOT / "docs" / "schemas" / "disputes-list-v1.schema.json").read_bytes()
        from an_kla.schemas import schema_bytes

        self.assertEqual(schema_bytes("disputes-list-v1"), mirror)
        try:
            from jsonschema import Draft202012Validator
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema unavailable")
        a, b = writer("agente-a"), writer("agente-b")
        target = self.remember(b, "uno")
        self.remember(a, "no uno", target=target.record["id"])
        from an_kla.schemas import schema_document

        envelope_doc = schema_document("record-envelope-v1")
        registry = Registry().with_resource(
            envelope_doc["$id"], Resource.from_contents(envelope_doc)
        )
        validator = Draft202012Validator(schema_document("disputes-list-v1"), registry=registry)
        validator.validate(disputes.list_disputes(self.store.snapshot()))
        validator.validate(disputes.list_disputes(self.store.snapshot(), target="f-nada"))


class DisputesListCliTests(DisputeBase):
    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--no-update-check",
             "--project-root", str(self.root), *args],
            cwd=ROOT, capture_output=True, text=True,
        )

    def test_cli_lists_disputes_and_filters_by_target(self) -> None:
        a, b = writer("agente-a"), writer("agente-b")
        t1, t2 = self.remember(b, "uno"), self.remember(b, "dos")
        self.remember(a, "no uno", target=t1.record["id"])
        self.remember(a, "no dos", target=t2.record["id"])
        before = self.store.read_current()

        every = self.cli("disputes", "list")
        self.assertEqual(every.returncode, 0, every.stderr)
        payload = json.loads(every.stdout)
        self.assertEqual(payload["schema"], "an-kla/disputes-list-v1")
        self.assertEqual(len(payload["disputes"]), 2)
        self.assertTrue(payload["untrusted_memory_data"])

        filtered = self.cli("disputes", "list", "--target", t2.record["id"])
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        (item,) = json.loads(filtered.stdout)["disputes"]
        self.assertEqual(item["target"]["id"], t2.record["id"])
        self.assertEqual(self.store.read_current(), before)

    def test_cli_help_documents_the_command(self) -> None:
        top = self.cli("--help")
        self.assertIn("disputes", top.stdout)
        helped = self.cli("disputes", "list", "--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("--target", helped.stdout)

    def test_cli_schema_list_and_capabilities_only_gain_entries(self) -> None:
        listing = json.loads(self.cli("schema", "list").stdout)
        self.assertIn("disputes-list-v1", [s["name"] for s in listing["schemas"]])
        caps = json.loads(self.cli("capabilities").stdout)
        flat = json.dumps(caps)
        self.assertIn("an-kla/disputes-list-v1", flat)

    def test_cli_without_store_reports_gate_not_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-m", "an_kla", "--no-update-check",
                 "--project-root", directory, "disputes", "list"],
                cwd=ROOT, capture_output=True, text=True,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
