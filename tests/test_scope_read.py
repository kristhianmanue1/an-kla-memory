"""ADR-0069, pruebas de aceptación 1, 3, 4, 6, 7 y 8: quién lee, cómo se sirve una `directive`, presupuesto e inyección."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest import mock

from an_kla.anchors_conversation import TurnView
from an_kla.audience import make_reader
from an_kla.canonical import canonical_json
from an_kla.listing import list_records
from an_kla.mcp import ReadOnlyMcp
from tests.inbox_support import EntryFactory
from tests.remember_support import cli, cli_env, remember
from tests.scope_support import OTHER, QUOTE, ScopeCase


class IncidentTests(ScopeCase):
    """Criterio 1: el incidente de extremo a extremo, con la CLI real y dos identidades por entorno, y por MCP."""

    def setUp(self) -> None:
        super().setUp()
        rc, body = self.directive("orq-otro", "el puerto de quetzal es 8081", "--subject", OTHER, "--audience", "agent:orq-otro", "--until-revoked")
        self.assertEqual((rc, body["state"]), (0, "committed"), body)
        self.directive_id = body["record_id"]
        rc, state = remember(
            self.project, "en curso: migrar quetzal", "--kind", "state", "--subject", OTHER, "--audience", "agent:orq-otro",
            env=self.env("orq-otro"),
        )
        self.assertEqual(rc, 0, state)

    def retrieve(self, name: str, *flags: str) -> dict:
        return self.read(name, "retrieve", "--query", "quetzal puerto migrar", "--budget", "100000", *flags)

    def test_the_other_orchestrator_is_not_served_and_the_exclusion_is_counted(self) -> None:
        got = self.retrieve("orq-memoria")
        self.assertEqual(got["selected"], [])
        self.assertEqual(got["excluded_summary"]["other_audience"], 1)
        self.assertEqual(got["schema"], "an-kla/retrieval-result-v4")
        listing = self.read("orq-memoria", "list")
        self.assertEqual((listing["items"], listing["excluded"]["other_audience"], listing["total"]), ([], 1, 0))
        self.assertEqual(listing["schema"], "an-kla/list-result-v2")
        shown = self.read("orq-memoria", "state", "show")
        self.assertEqual((shown["slots"], shown["excluded"]["other_audience"], shown["schema"]), ([], 1, "an-kla/state-result-v2"))

    def test_include_other_audience_serves_it_marked_and_never_actionable(self) -> None:
        got = self.retrieve("orq-memoria", "--include-other-audience")
        item = next(i for i in got["selected"] if i["id"] == self.directive_id)
        self.assertIs(item["for_reader"], False)
        self.assertEqual((item["directive"]["status"], item["directive"]["actionable"]), ("unverified", False))
        listed = self.read("orq-memoria", "list", "--include-other-audience")["items"]
        self.assertTrue(all(i["for_reader"] is False for i in listed))
        self.assertIs(self.read("orq-memoria", "state", "show", "--include-other-audience")["slots"][0]["for_reader"], False)
        # con --subject P tampoco es accionable: `audience` no nombra al lector
        again = self.retrieve("orq-memoria", "--subject", OTHER, "--include-other-audience")
        served = next(i for i in again["selected"] if i["id"] == self.directive_id)
        self.assertEqual((served["directive"]["actionable"], served["for_reader"]), (False, False))
        self.assertEqual(self.retrieve("orq-memoria", "--subject", OTHER)["excluded_summary"]["other_audience"], 1)

    def test_the_addressee_receives_it_only_for_its_project(self) -> None:
        got = self.retrieve("orq-otro", "--subject", OTHER)
        item = next(i for i in got["selected"] if i["id"] == self.directive_id)
        self.assertNotIn("for_reader", item)
        view = item["directive"]
        self.assertEqual((view["status"], view["actionable"], view["audience"], view["subject"]), ("unverified", True, "agent:orq-otro", OTHER))
        self.assertEqual((view["writer"], view["anchor_freshness"]), ({"name": "orq-otro", "role": "orquestador"}, "pending"))
        # sin --subject su proyecto es R: la orden trata de otro proyecto
        self.assertEqual(self.retrieve("orq-otro")["selected"], [])
        self.assertEqual(self.retrieve("orq-otro")["excluded_summary"]["other_audience"], 1)
        listed = self.read("orq-otro", "list", "--subject", OTHER)
        self.assertEqual([i["id"] for i in listed["items"]], [self.directive_id])
        self.assertTrue(listed["items"][0]["directive"]["actionable"])
        slot = self.read("orq-otro", "state", "show", "--subject", OTHER)["slots"]
        self.assertEqual((len(slot), "for_reader" in slot[0]), (1, False))

    def test_a_malformed_subject_is_a_typed_error_per_command(self) -> None:
        for args, code in ((("retrieve", "--query", "x", "--budget", "100"), "retrieve_subject_invalid"),
                           (("list",), "list_subject_invalid"), (("state", "show"), "state_subject_invalid")):
            done = cli(self.project, *args, "--subject", "corto", env=self.env("orq-memoria"))
            self.assertNotEqual(done.returncode, 0)
            self.assertIn(code, done.stderr)

    def test_mcp_filters_always_and_takes_no_new_parameters(self) -> None:
        for name, served in (("orq-memoria", 0), ("orq-otro", 0)):
            with mock.patch.dict(os.environ, {k: v for k, v in cli_env(self.env(name)).items() if k.startswith("AN_KLA_")}):
                payload = ReadOnlyMcp(self.project)._retrieve_payload("quetzal puerto migrar", 100000)
            self.assertEqual(len(payload["records"]), served, payload)
            self.assertEqual(payload["excluded_summary"]["other_audience"], 1)
            self.assertEqual(payload["schema"], "an-kla/mcp-retrieve-v4")
        tool = next(t for t in ReadOnlyMcp.tools() if t["name"] == "an_kla_retrieve")
        self.assertFalse({"subject", "include_other_audience"} & set(tool["inputSchema"]["properties"]))


class VigencyTests(ScopeCase):
    """Criterio 3: vigencia, rotación sin disputa, y los rechazos de sustitución."""

    def served(self, reader: str, *flags: str) -> dict:
        return self.read(reader, "retrieve", "--query", "puerto", "--budget", "100000", "--subject", OTHER, *flags)

    def test_expired_is_not_served_and_until_revoked_is(self) -> None:
        self.hand_entry("el puerto vencido", self.env("orq-a"), subject=OTHER, audience="agent:orq-b", valid_until="2020-01-01")
        _rc, live = self.directive("orq-a", "el puerto vigente", "--subject", OTHER, "--audience", "agent:orq-b", "--until-revoked")
        self.drain()
        got = self.served("orq-b")
        self.assertEqual([i["id"] for i in got["selected"]], [live["record_id"]])
        self.assertEqual(got["excluded_summary"]["directive_inactive"], 1)
        listed = self.read("orq-b", "list", "--subject", OTHER, "--status", "all")["items"]
        self.assertEqual(sorted(i["directive"]["status"] for i in listed), ["expired", "unverified"])

    def test_rotation_by_another_orchestrator_without_dispute_and_the_rejections(self) -> None:
        _rc, old = self.directive("orq-a", "el puerto es 8081", "--subject", OTHER, "--audience", "agent:orq-b", "--until-revoked")
        oid = old["record_id"]
        # un ejecutor no sustituye; un fact tampoco; un subject o un audience distinto, tampoco
        rc, body = self.directive("ejec-1", "x", "--supersedes", oid, "--subject", OTHER, "--audience", "all", "--until-revoked", role="ejecutor")
        self.assertEqual((rc, body["code"]), (3, "directive_role_not_allowed"))
        rc, body = remember(self.project, "un hecho", "--kind", "fact", "--supersedes", oid, env=self.env("orq-b"))
        self.assertEqual((rc, body["state"], body["code"]), (3, "rejected", "remember_kind_mismatch"))
        rc, body = self.directive("orq-b", "x", "--supersedes", oid, "--subject", "example.org/otro/tercero", "--audience", "agent:orq-b", "--until-revoked")
        self.assertEqual((rc, body["code"]), (3, "directive_subject_mismatch"))
        rc, body = self.directive("orq-b", "x", "--supersedes", oid, "--revoke", "--audience", "all")
        self.assertEqual((rc, body["code"]), (3, "directive_audience_mismatch"))
        # un dispute de cualquier papel: sigue vigente, con disputed: 1 y no accionable
        done = cli(self.project, "dispute", oid, "--verdict", "insufficient", "--text-file", "-", stdin="la cita no basta", env=self.env("ejec-1", "ejecutor"))
        self.assertEqual(done.returncode, 0, done.stderr)
        view = next(i for i in self.served("orq-b")["selected"] if i["id"] == oid)["directive"]
        self.assertEqual((view["disputed"], view["actionable"], view["status"]), (1, False, "unverified"))
        # orq-b (otro nombre, mismo subject) la revoca heredando el ámbito, sin disputa
        rc, revoked = self.directive("orq-b", "ya no uses el puerto", "--supersedes", oid, "--revoke")
        self.assertEqual((rc, revoked["state"], revoked["superseded"]), (0, "committed", oid), revoked)
        self.assertNotIn("disputed", revoked)
        got = self.served("orq-b")
        self.assertEqual([i["id"] for i in got["selected"]], [])
        self.assertEqual(got["excluded_summary"].get("directive_inactive", 0), 1)  # el acta de la revocación, nunca como orden
        listed = {i["id"]: i for i in self.read("orq-b", "list", "--subject", OTHER, "--status", "all")["items"]}
        self.assertEqual(listed[revoked["record_id"]]["directive"]["status"], "revocation")
        self.assertEqual((listed[revoked["record_id"]]["subject"], listed[revoked["record_id"]]["audience"]), (OTHER, "agent:orq-b"))
        self.assertEqual(listed[oid]["status"], "superseded")
        chain = self.read("orq-b", "history", oid)
        self.assertEqual(chain["schema"], "an-kla/history-result-v2")
        self.assertEqual({n["id"] for n in chain["nodes"]} & {oid, revoked["record_id"]}, {oid, revoked["record_id"]})
        self.assertTrue(all(n["directive"]["actionable"] is False for n in chain["nodes"] if "directive" in n))  # lector sin proyecto P

    def test_a_revocation_with_validity_is_a_conflict_and_a_missing_target_is_typed(self) -> None:
        _rc, old = self.directive("orq-a", "orden", "--subject", OTHER, "--audience", "agent:orq-b", "--until-revoked")
        rc, body = self.directive("orq-a", "x", "--supersedes", old["record_id"], "--revoke", "--until-revoked")
        self.assertEqual((rc, body["code"]), (3, "directive_validity_conflict"))
        rc, body = self.directive("orq-a", "x", "--supersedes", "f-r-no-existe", "--revoke")
        self.assertEqual((rc, body["code"]), (3, "invalid_supersede_target"))


class AnchorStatusTests(ScopeCase):
    """Criterio 4: `invalidated`, `verified` y `unverified` por la API, con resolución y verificador inyectados."""

    class Verifier:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def turn(self, session: str, turn_id: str) -> TurnView:
            return TurnView("missing") if self.text is None else TurnView("ok", self.text)

    def setUp(self) -> None:
        super().setUp()
        _rc, body = self.directive("orq-a", "usa el puerto 8081", "--subject", OTHER, "--audience", "agent:orq-b", "--until-revoked")
        self.rid = body["record_id"]
        self.factory = EntryFactory(self.store, {**cli_env(self.env("orq-b"))})

    def annotate(self, **resolution) -> None:
        from an_kla.inbox import payload_digest
        from an_kla.inbox_anchors import payload_extra
        from an_kla.inbox_drain import drain

        row = next(r for r in self.store.snapshot().records["facts"] if r["id"] == self.rid)
        res = {"schema": "an-kla/anchor-resolution-v1",
               "target": {"stream": "facts", "record_id": self.rid, "anchor_index": 0, "quote_sha256": row["anchors"][0]["quote_sha256"]},
               "resolution": "resolved", "turn_id": "t2", "seal": "sello", **resolution}
        text = f"anotación {sorted(resolution.items())}"
        key = self.factory.identity_c0.derive_idempotency_key(self.factory.identity, "fact", text, None, None)
        data = self.factory.entry(text, kind="fact", key=key)
        data.update(schema="an-kla/inbox-entry-v3", operation="anchor_resolution", anchor_resolution=res)
        data["payload_sha256"] = payload_digest(data["text"], "fact", None, None, payload_extra(data))
        name = self.factory.name_for(data)
        (self.factory.pending).mkdir(parents=True, exist_ok=True)
        (self.factory.pending / name).write_bytes(canonical_json(data))
        self.assertEqual(len(drain(self.store, include_entry=name, max_batches=1)["committed"]["entries"]), 1)

    def view(self, verifier=None) -> dict:
        env = {k: v for k, v in cli_env(self.env("orq-b")).items() if k.startswith("AN_KLA_")}
        reader = make_reader(self.store, subject=OTHER, env=env)
        listing = list_records(self.store.snapshot(), store=self.store, reader=reader, verifier=verifier)
        return next(i for i in listing["items"] if i["id"] == self.rid)["directive"]

    def test_pending_resolved_without_verifier_not_found_and_verified(self) -> None:
        self.assertEqual(self.view()["status"], "unverified")
        self.annotate()  # resolved, sin verificador instalado: sigue unverified
        self.assertEqual(self.view()["status"], "unverified")
        self.assertEqual(self.view(self.Verifier(QUOTE))["status"], "verified")  # el turno contiene la cita
        self.assertEqual(self.view(self.Verifier("otra cosa distinta"))["status"], "invalidated")  # no la contiene
        self.annotate(resolution="not_found", turn_id=None, seal=None)  # la última anotación manda
        self.assertEqual(self.view()["status"], "invalidated")

    def test_the_clock_is_injectable_in_the_api(self) -> None:
        _rc, short = self.directive("orq-a", "el puerto de la semana", "--subject", OTHER, "--audience", "agent:orq-b", "--valid-until", "2099-06-30")
        env = {k: v for k, v in cli_env(self.env("orq-b")).items() if k.startswith("AN_KLA_")}
        reader = make_reader(self.store, subject=OTHER, env=env)
        for moment, status in ((datetime(2099, 6, 30, 23, 59, 58, tzinfo=timezone.utc), "unverified"),
                               (datetime(2099, 7, 1, tzinfo=timezone.utc), "expired")):
            listing = list_records(self.store.snapshot(), store=self.store, reader=reader, clock=lambda m=moment: m)
            self.assertEqual(next(i for i in listing["items"] if i["id"] == short["record_id"])["directive"]["status"], status)


class BudgetTests(ScopeCase):
    """Criterio 6: `cost_bytes` cuenta el objeto `directive`; el presupuesto exacto sigue siéndolo y MCP cabe."""

    def setUp(self) -> None:
        super().setUp()
        _rc, body = self.directive("orq-a", "puerto de quetzal", "--subject", OTHER, "--audience", "agent:orq-b", "--until-revoked")
        self.rid = body["record_id"]

    def retrieve(self, budget: int) -> dict:
        return self.read("orq-b", "retrieve", "--query", "puerto", "--budget", str(budget), "--subject", OTHER)

    def test_cost_includes_the_directive_object_and_the_budget_is_exact(self) -> None:
        item = self.retrieve(100000)["selected"][0]
        extra = len(canonical_json({"directive": item["directive"]}))
        self.assertEqual(item["cost_bytes"], len(item["render"].encode()) + extra)
        self.assertEqual(self.retrieve(item["cost_bytes"])["used_bytes"], item["cost_bytes"])
        tight = self.retrieve(item["cost_bytes"] - 1)
        self.assertEqual((tight["selected"], tight["excluded_summary"]["budget"]), ([], 1))

    def test_mcp_proves_the_response_fits(self) -> None:
        # MCP no gana --subject: su lector es el del checkout (R); la orden de este caso trata de R y nombra a orq-b
        _rc, body = self.directive("orq-a", "puerto de este repo", "--subject", self.repo_id, "--audience", "agent:orq-b", "--until-revoked")
        env = {k: v for k, v in cli_env(self.env("orq-b")).items() if k.startswith("AN_KLA_")}

        def payload(budget: int) -> dict:
            with mock.patch.dict(os.environ, env):
                return ReadOnlyMcp(self.project)._retrieve_payload("puerto repo", budget)

        full = payload(100000)
        served = full["records"][0]
        self.assertEqual((served["id"], served["directive"]["actionable"]), (body["record_id"], True))
        self.assertEqual(full["schema"], "an-kla/mcp-retrieve-v4")
        self.assertLessEqual(len(canonical_json(full)), full["budget_bytes"])
        self.assertEqual(len(payload(full["used_bytes"])["records"]), 1)  # el presupuesto exacto cabe
        answered = 0
        for budget in range(full["used_bytes"] - 400, full["used_bytes"] + 3):  # y ninguna respuesta se pasa de su presupuesto
            try:
                response = payload(budget)
            except ValueError as exc:  # por debajo del sobre vacío: error tipado, nunca una respuesta que no cabe
                self.assertEqual(str(exc), "budget_too_small_for_envelope")
                continue
            answered += 1
            self.assertLessEqual(len(canonical_json(response)), budget, budget)
        self.assertGreater(answered, 0)


class AudienceMatchTests(ScopeCase):
    """Criterio 7: sin identidad en el entorno, `role:` y `agent:` son para otro; `all` con `subject` propio se sirve sin ser accionable."""

    def test_anonymous_reader_and_all_with_own_subject(self) -> None:
        self.directive("orq-a", "por rol", "--subject", self.repo_id, "--audience", "role:orquestador", "--until-revoked")
        self.directive("orq-a", "por nombre", "--subject", self.repo_id, "--audience", "agent:orq-b", "--until-revoked")
        _rc, everyone = self.directive("orq-a", "para todos del proyecto", "--subject", self.repo_id, "--audience", "all", "--until-revoked")
        anonymous = cli(self.project, "retrieve", "--query", "por para", "--budget", "100000",
                        env={"AN_KLA_AGENT_NAME": None, "AN_KLA_AGENT_ROLE": None})
        got = json.loads(anonymous.stdout)
        self.assertEqual([i["id"] for i in got["selected"]], [everyone["record_id"]])
        self.assertEqual(got["excluded_summary"]["other_audience"], 2)
        self.assertFalse(got["selected"][0]["directive"]["actionable"])  # `all` no basta
        named = self.read("orq-b", "retrieve", "--query", "por para", "--budget", "100000")
        flags = {i["render"]: i["directive"]["actionable"] for i in named["selected"]}
        self.assertEqual(flags, {"por rol": True, "por nombre": True, "para todos del proyecto": False})


class InjectionTests(ScopeCase):
    """Criterio 8: `assemble-context` y `resume` filtran y no inyectan ninguna `directive`."""

    def test_no_directive_is_injected_and_both_are_counted(self) -> None:
        self.directive("orq-a", "orden para el lector", "--subject", self.repo_id, "--audience", "agent:orq-b", "--until-revoked")
        self.directive("orq-a", "orden para otro", "--subject", OTHER, "--audience", "agent:orq-c", "--until-revoked")
        context = self.read("orq-b", "assemble-context", "--query", "orden", "--budget", "100000")
        self.assertEqual(context["schema"], "an-kla/context-assembly-v3")
        self.assertEqual(context["sections"]["retrieved_records"], [])
        self.assertEqual(
            {k: context["excluded_summary"][k] for k in ("other_audience", "directive_not_injected")},
            {"other_audience": 1, "directive_not_injected": 1},
        )
        resumed = self.read("orq-b", "resume", "--query", "orden", "--budget", "100000")
        self.assertEqual(resumed["schema"], "an-kla/resume-v2")
        self.assertEqual(resumed["retrieved_evidence"], [])
        self.assertEqual((resumed["excluded_summary"]["other_audience"], resumed["excluded_summary"]["directive_not_injected"]), (1, 1))
