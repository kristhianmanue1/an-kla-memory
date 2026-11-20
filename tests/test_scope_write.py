"""ADR-0069, pruebas de aceptación 2 y 9 y las reglas de escritura: códigos en su orden, entradas a mano, ``plan-write``."""

from __future__ import annotations

import json

from tests.remember_support import cli, remember
from tests.scope_support import OTHER, ScopeCase


class WriteRejectionTests(ScopeCase):
    """Criterio 2: cada código de §2 y §3 en su orden, sin encolar nada."""

    def assertRejected(self, result: tuple[int, dict], code: str) -> None:
        rc, body = result
        self.assertEqual((rc, body.get("code"), body.get("ok")), (3, code, False), body)
        self.assertEqual(body["schema"], "an-kla/remember-error-v2")
        self.assertEqual(self.pending(), [])  # sin encolar nada

    def good(self, **overrides):
        args = ["--subject", OTHER, "--audience", "agent:orq-otro", "--until-revoked"]
        for flag, value in overrides.items():
            if flag in args:
                index = args.index(flag)
                del args[index:index + (1 if flag == "--until-revoked" else 2)]
            if value is not None:
                args += [flag] if value is True else [flag, value]
        return args

    def test_directive_codes_in_the_adrs_order(self) -> None:
        # 1. el papel; «operador» y «desconocido» tampoco escriben (R69-06)
        for role in ("ejecutor", "revisor", "operador", "desconocido"):
            self.assertRejected(self.directive("orq-otro", "orden", *self.good(), role=role), "directive_role_not_allowed")
        # 2. la sesión de origen real (va antes que lo que falta después)
        self.assertRejected(self.directive("orq-otro", "orden", session=None), "directive_session_missing")
        # 3. subject y 4. audience, sin valor por defecto
        self.assertRejected(self.directive("orq-otro", "orden", "--audience", "all", "--until-revoked"), "directive_missing_subject")
        self.assertRejected(self.directive("orq-otro", "orden", "--subject", OTHER, "--until-revoked"), "directive_missing_audience")
        self.assertRejected(self.directive("orq-otro", "orden", "--until-revoked"), "directive_missing_subject")
        # 5. la vigencia: ninguna, o las dos
        self.assertRejected(self.directive("orq-otro", "orden", "--subject", OTHER, "--audience", "all"), "directive_validity_missing")
        self.assertRejected(
            self.directive("orq-otro", "orden", *self.good(), "--valid-until", "2099-01-01"), "directive_validity_conflict"
        )
        # 6. al menos un ancla de conversación
        self.assertRejected(self.directive("orq-otro", "orden", *self.good(), anchors=False), "directive_anchor_missing")
        self.assertRejected(self.directive("orq-otro", "orden", anchors=False), "directive_missing_subject")  # el orden manda

    def test_syntax_and_fields_of_the_scope(self) -> None:
        for bad in ("proyecto-corto", "UPPER/case", ""):
            self.assertRejected(self.directive("orq-otro", "x", *self.good(**{"--subject": bad})), "remember_subject_invalid")
        for bad in ("todos", "role:desconocido", "role:rey", "agent:sin-nombre", "agent:desconocido", "agent:sin-sesion", "agent:Mal", "all:x"):
            self.assertRejected(self.directive("orq-otro", "x", *self.good(**{"--audience": bad})), "remember_audience_invalid")
        past = self.directive("orq-otro", "x", "--subject", OTHER, "--audience", "all", "--valid-until", "2020-01-01")
        self.assertRejected(past, "directive_valid_until_past")
        # los campos de la directive sólo valen en una directive
        for flag in (("--until-revoked",), ("--valid-until", "2099-01-01")):
            self.assertRejected(remember(self.project, "x", "--kind", "fact", *flag, env=self.env("orq-otro")), "remember_directive_field_not_allowed")
        self.assertRejected(remember(self.project, "x", "--kind", "fact", "--supersedes", "f-1", "--revoke", env=self.env("orq-otro")), "remember_directive_field_not_allowed")
        self.assertRejected(self.directive("orq-otro", "x", *self.good(), "--revoke"), "directive_revoke_without_target")

    def test_scope_on_every_kind_is_accepted_and_stored_as_top_level_fields(self) -> None:
        for kind, extra in (("fact", ()), ("decision", ()), ("state", ("--slot", "lateral"))):
            rc, body = remember(
                self.project, f"{kind} para otro", "--kind", kind, "--subject", OTHER, "--audience", "role:capitan", *extra,
                env=self.env("orq-a"),
            )
            self.assertEqual((rc, body["state"]), (0, "committed"), body)
        listing = self.read("orq-a", "list", "--streams", "facts,episodes", "--include-other-audience")
        scoped = [i for i in listing["items"] if i.get("subject") == OTHER]
        self.assertEqual(sorted(i["kind"] for i in scoped), ["decision", "fact", "state"])
        self.assertTrue(all(i["audience"] == "role:capitan" and i["for_reader"] is False for i in scoped))

    def test_the_scope_is_part_of_the_intention_and_of_the_key(self) -> None:
        first = remember(self.project, "mismo texto", "--subject", OTHER, env=self.env("orq-a"))[1]
        again = remember(self.project, "mismo texto", "--subject", OTHER, env=self.env("orq-a"))[1]
        other_audience = remember(self.project, "mismo texto", "--subject", OTHER, "--audience", "all", env=self.env("orq-a"))[1]
        plain = remember(self.project, "mismo texto", env=self.env("orq-a"))[1]
        self.assertEqual(again["record_id"], first["record_id"])
        self.assertEqual(len({first["record_id"], other_audience["record_id"], plain["record_id"]}), 3)
        # una clave explícita reutilizada con otro ámbito es colisión, no reintento
        remember(self.project, "texto k", "--subject", OTHER, "--idempotency-key", "k", env=self.env("orq-a"))
        rc, clash = remember(self.project, "texto k", "--subject", self.repo_id, "--idempotency-key", "k", env=self.env("orq-a"))
        self.assertEqual((rc, clash["state"], clash["code"]), (3, "rejected", "remember_id_collision"), clash)
        self.assertIn("idempotency_key_other_scope", clash["reason_codes"])

    def test_a_directive_is_written_in_facts_with_its_fields(self) -> None:
        rc, body = self.directive("orq-otro", "usa el puerto 8081", "--subject", OTHER, "--audience", "agent:orq-otro", "--valid-until", "2099-01-01")
        self.assertEqual((rc, body["state"], body["stream"]), (0, "committed", "facts"), body)
        self.assertTrue(body["record_id"].startswith("f-r-"))
        row = next(i for i in self.read("orq-otro", "list", "--include-other-audience")["items"] if i["id"] == body["record_id"])
        self.assertEqual(row["directive"]["valid_until"], "2099-01-01T23:59:59Z")
        self.assertEqual(row["kind"], "directive")


class HandWrittenEntryTests(ScopeCase):
    """Criterio 2, segunda mitad: la misma entrada a mano en ``pending/`` acaba en ``rejected/`` con el mismo código."""

    CASES = (
        ("directive_role_not_allowed", dict(role="ejecutor", fields={"subject": OTHER, "audience": "all", "until_revoked": True})),
        ("directive_session_missing", dict(session=None, fields={"subject": OTHER, "audience": "all", "until_revoked": True})),
        ("directive_missing_subject", dict(fields={"audience": "all", "until_revoked": True})),
        ("directive_missing_audience", dict(fields={"subject": OTHER, "until_revoked": True})),
        ("directive_validity_missing", dict(fields={"subject": OTHER, "audience": "all"})),
        ("directive_validity_conflict", dict(fields={"subject": OTHER, "audience": "all", "until_revoked": True, "valid_until": "2099-01-01"})),
        ("directive_validity_conflict", dict(fields={"subject": OTHER, "audience": "all", "revokes": True, "until_revoked": True})),
        ("directive_anchor_missing", dict(anchors=None, fields={"subject": OTHER, "audience": "all", "until_revoked": True})),
        ("remember_subject_invalid", dict(fields={"subject": "corto", "audience": "all", "until_revoked": True})),
        ("remember_audience_invalid", dict(fields={"subject": OTHER, "audience": "todos", "until_revoked": True})),
    )

    def test_each_code_reaches_rejected_on_drain(self) -> None:
        for code, spec in self.CASES:
            with self.subTest(code=code, spec=spec):
                before = len(self.rejected_codes())
                self.hand_entry(
                    f"orden {len(self.rejected_codes())}", self.env("orq-mano", spec.get("role", "orquestador"), spec.get("session", "sesion-1")),
                    anchors=spec.get("anchors", "default"), **spec["fields"],
                )
                report = self.drain()
                self.assertEqual(report["rejected"]["count"], 1, report)
                self.assertEqual(self.rejected_codes()[before:], [code])
                self.assertEqual(self.pending(), [])

    def test_a_fact_with_directive_fields_and_a_v3_directive_are_rejected_too(self) -> None:
        self.hand_entry("hecho", self.env("orq-mano"), kind="fact", anchors=None, valid_until="2099-01-01")
        self.drain()
        self.assertEqual(self.rejected_codes(), ["remember_directive_field_not_allowed"])


class PlanWriteTests(ScopeCase):
    """Criterio 9 (primera parte): ``plan-write`` no escribe el ámbito."""

    def propose(self, record: dict) -> int:
        base = json.loads(cli(self.project, "status").stdout)["revision"]
        proposal = {
            "schema": "an-kla/write-proposal-v1", "base_revision": base, "stream": "facts", "operation": "add",
            "requested_representation": "summary", "lineage": {"derived_from_retrieval": False, "refs": []},
            "record": record,
        }
        path = self.scratch / "propuesta.json"
        path.write_text(json.dumps(proposal))
        done = cli(self.project, "plan-write", "--proposal", str(path), "--emit-authority-template")
        self.last = done
        return done.returncode

    def test_plan_write_rejects_directive_and_scope_fields(self) -> None:
        self.assertEqual(self.propose({"id": "f-ok", "text": "normal"}), 0)
        for extra in ({"subject": OTHER}, {"audience": "all"}, {"valid_until": "2099-01-01"}, {"until_revoked": True}, {"revokes": True}):
            with self.subTest(extra=extra):
                self.assertNotEqual(self.propose({"id": "f-x", "text": "t", **extra}), 0)
                self.assertIn("plan_write_scope_fields_not_allowed", self.last.stderr)
        envelope = {"kind": "directive"}
        self.assertNotEqual(self.propose({"id": "f-d", "text": "t", "an_kla_envelope": envelope}), 0)
        self.assertIn("plan_write_scope_fields_not_allowed", self.last.stderr)


class ApiGuardTests(ScopeCase):
    """Corrección 1 (Q-01): la guarda también está en la API pública de planificación y de compromiso."""

    def proposal(self, **record) -> dict:
        from an_kla.record_text import record_text  # noqa: F401  (el registro sólo necesita id y texto)

        return {
            "schema": "an-kla/write-proposal-v1", "base_revision": self.store.read_current(), "stream": "facts",
            "operation": "add", "requested_representation": "summary",
            "lineage": {"derived_from_retrieval": False, "refs": []},
            "record": {"id": "f-api", "text": "texto", "indexable_text": "texto", **record},
        }

    def test_store_plan_write_rejects_scope_and_directive(self) -> None:
        from an_kla.write_policy import WritePolicyError, emit_write_authority_template

        for extra in ({"subject": OTHER}, {"audience": "all"}, {"revokes": True}, {"an_kla_envelope": {"kind": "directive"}}):
            proposal = self.proposal(**extra)
            with self.subTest(extra=extra):
                with self.assertRaises(WritePolicyError) as caught:
                    self.store.plan_write(proposal, emit_write_authority_template(proposal))
                self.assertEqual(caught.exception.code, "plan_write_scope_fields_not_allowed")
        plain = self.proposal()
        self.assertIn("plan", self.store.plan_write(plain, emit_write_authority_template(plain)))

    def test_a_hand_made_plan_cannot_be_committed_either(self) -> None:
        from an_kla.write_policy import WritePolicyError, build_write_plan, emit_write_authority_template, evaluate_write

        proposal = self.proposal(subject=OTHER, audience="all")
        authority = emit_write_authority_template(proposal)  # las funciones puras no llevan la guarda: así lo arma el vaciado
        decision = evaluate_write(proposal, authority)
        plan = build_write_plan(proposal, authority, decision)
        base = self.store.read_current()
        with self.assertRaises(WritePolicyError) as caught:
            self.store.commit_write_plan(expected_current_hash=base, plan=plan, proposal=proposal, authority=authority, decision=decision)
        self.assertEqual(caught.exception.code, "plan_write_scope_fields_not_allowed")
        self.assertEqual(self.store.read_current(), base)  # nada se escribió
        rc, body = remember(self.project, "por el camino bueno", "--subject", OTHER, env=self.env("orq-a"))  # el vaciado sigue escribiendo ámbito
        self.assertEqual((rc, body["state"]), (0, "committed"))
