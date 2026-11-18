"""ADR-0065 (E1.d1): `remember --kind state [--slot]`, la casilla, su idempotencia y sus rechazos."""

from __future__ import annotations

import unittest

from an_kla import inbox_drain
from an_kla.remember import remember
from an_kla.state_show import state_show
from an_kla.vigency import is_active
from tests.inbox_support import AGENT_ENV, EntryFactory, InboxCase

A = {**AGENT_ENV, "AN_KLA_AGENT_NAME": "agente-a", "AN_KLA_SESSION_ID": "sesion-a-1"}
B = {**AGENT_ENV, "AN_KLA_AGENT_NAME": "agente-b", "AN_KLA_SESSION_ID": "sesion-b-1"}
C = {**AGENT_ENV, "AN_KLA_AGENT_NAME": "agente-c", "AN_KLA_SESSION_ID": "sesion-c-1"}


class StateCase(InboxCase):
    def put(self, text: str, env: dict | None = None, **options) -> dict:
        return remember(self.store, text, kind="state", env=env or A, **options)

    def episodes(self) -> dict:
        return {r["id"]: r for r in self.store.snapshot().records["episodes"]}

    def heads(self, **options) -> list[dict]:
        return state_show(self.store, **options)["slots"]


class SlotRetirementTests(StateCase):
    def test_second_state_retires_the_head_of_main(self) -> None:
        first = self.put("estado uno")
        second = self.put("estado dos")
        self.assertEqual((first["state"], first["slot"], first["operation"]), ("committed", "main", "add"))
        self.assertEqual((second["state"], second["operation"]), ("committed", "supersede"))
        self.assertEqual(second["retired"]["id"], first["record_id"])
        self.assertEqual(second["retired"]["enqueued_at"], first["enqueued_at"])
        self.assertEqual(second["retired"]["writer"]["agent"]["name"], "agente-a")
        rows = self.episodes()
        self.assertFalse(is_active(rows[first["record_id"]]))
        self.assertTrue(is_active(rows[second["record_id"]]))
        self.assertEqual(rows[second["record_id"]]["slot"], "main")
        self.assertEqual([h["id"] for h in self.heads()], [second["record_id"]])

    def test_slots_are_independent(self) -> None:
        main = self.put("trabajo principal")
        side = self.put("trabajo lateral", slot="lateral")
        self.assertEqual(side["operation"], "add")
        self.assertNotIn("retired", side)
        self.assertTrue(is_active(self.episodes()[main["record_id"]]))
        self.assertEqual([h["slot"] for h in self.heads(all_slots=True)], ["lateral", "main"])

    def test_another_agent_retires_the_head_without_a_dispute(self) -> None:
        mine = self.put("lo mío", env=A)
        theirs = self.put("lo de b", env=B)
        self.assertEqual((theirs["operation"], theirs["retired"]["id"]), ("supersede", mine["record_id"]))
        self.assertEqual(theirs["retired"]["writer"]["agent"]["name"], "agente-a")
        self.assertNotIn("disputed", theirs)
        self.assertNotIn("disputes", self.episodes()[theirs["record_id"]])

    def test_same_text_in_two_slots_is_two_records(self) -> None:
        one = self.put("igual", slot="uno")
        two = self.put("igual", slot="dos")
        self.assertNotEqual(one["record_id"], two["record_id"])
        self.assertNotEqual(one["idempotency_key"], two["idempotency_key"])
        self.assertEqual(len(self.heads(all_slots=True)), 2)

    def test_slot_is_validated_and_needs_state(self) -> None:
        for bad in ("Mayus", "1abc", "x" * 33, "con espacio"):
            with self.subTest(bad=bad), self.assertRaises(Exception) as caught:
                self.put("x", slot=bad)
            self.assertEqual(str(caught.exception), "inbox_slot_invalid")
        with self.assertRaises(Exception) as caught:
            remember(self.store, "x", kind="fact", slot="main", env=A)
        self.assertEqual(str(caught.exception), "inbox_slot_requires_state")

    def test_queued_state_announces_no_record_id(self) -> None:
        from an_kla.inbox import enqueue

        queued = enqueue(self.store, "pendiente", kind="state", env=A)
        self.assertNotIn("record_id", queued)
        self.assertEqual(queued["slot"], "main")


class StateOverFactTests(StateCase):
    def test_state_over_a_decision_is_rejected_and_the_decision_stays(self) -> None:
        decision = remember(self.store, "usamos sqlite", kind="decision", env=A)
        result = self.put("estado sobre decisión", supersedes=decision["record_id"])
        self.assertEqual((result["state"], result["code"]), ("rejected", "remember_state_over_fact"))
        self.assertNotIn("record_id", result)
        facts = {r["id"]: r for r in self.store.snapshot().records["facts"]}
        self.assertTrue(is_active(facts[decision["record_id"]]))

    def test_state_over_a_legacy_fact_is_rejected(self) -> None:
        self.commit_record("f-legado", text="estado viejo como hecho")
        result = self.put("ahora sí es estado", supersedes="f-legado")
        self.assertEqual((result["state"], result["code"]), ("rejected", "remember_state_over_fact"))
        self.assertTrue(is_active({r["id"]: r for r in self.store.snapshot().records["facts"]}["f-legado"]))
        self.assertEqual(self.heads(), [])

    def test_fact_over_a_state_keeps_the_old_kind_mismatch(self) -> None:
        state = self.put("estado")
        result = remember(self.store, "hecho", kind="fact", supersedes=state["record_id"], env=A)
        self.assertEqual((result["state"], result["code"]), ("rejected", "remember_kind_mismatch"))

    def test_state_over_a_missing_or_retired_target(self) -> None:
        self.assertEqual(self.put("x", supersedes="ep-no-existe")["code"], "invalid_supersede_target")
        old = self.put("viejo")
        self.put("nuevo")
        self.assertEqual(self.put("otro", supersedes=old["record_id"])["code"], "invalid_supersede_target")


class SlotTargetTests(StateCase):
    def test_target_in_another_slot_is_a_mismatch(self) -> None:
        other = self.put("de otra casilla", slot="otra")
        result = self.put("para main", supersedes=other["record_id"])
        self.assertEqual((result["state"], result["code"]), ("rejected", "remember_state_slot_mismatch"))
        self.assertTrue(is_active(self.episodes()[other["record_id"]]))

    def test_target_equal_to_the_head_is_accepted(self) -> None:
        head = self.put("cabeza")
        result = self.put("siguiente", supersedes=head["record_id"])
        self.assertEqual((result["state"], result["retired"]["id"]), ("committed", head["record_id"]))

    def test_supersedes_a_state_without_kind_takes_its_kind_and_slot(self) -> None:
        head = self.put("en la lateral", slot="lateral")
        result = remember(self.store, "sigo en la lateral", supersedes=head["record_id"], env=B)
        self.assertEqual((result["state"], result["kind"], result["slot"]), ("committed", "state", "lateral"))
        self.assertEqual(result["retired"]["id"], head["record_id"])
        self.assertNotIn("disputed", result)

    def test_an_explicit_slot_that_differs_from_the_target_is_a_mismatch(self) -> None:
        head = self.put("en la lateral", slot="lateral")
        result = remember(self.store, "x", supersedes=head["record_id"], slot="otra", env=A)
        self.assertEqual(result["code"], "remember_state_slot_mismatch")

    def test_a_target_that_is_not_the_head_is_a_mismatch_with_conflict(self) -> None:
        env = self.envelope_for(A, "id-ajeno-1", "2026-01-01T00:00:00.000000Z")
        self.commit_record("ep-m1", stream="episodes", text="uno", an_kla_envelope=env, slot="main")
        env2 = self.envelope_for(A, "id-ajeno-2", "2026-01-02T00:00:00.000000Z")
        self.commit_record("ep-m2", stream="episodes", text="dos", an_kla_envelope=env2, slot="main")
        shown = self.heads()
        self.assertEqual((shown[0]["id"], shown[0]["conflict"]), ("ep-m2", ["ep-m1", "ep-m2"]))
        result = self.put("tres", supersedes="ep-m1")
        self.assertEqual(result["code"], "remember_state_slot_mismatch")
        free = self.put("tres")
        self.assertEqual(free["retired"]["id"], "ep-m2")
        self.assertEqual(free["conflict_remaining"], ["ep-m1"])
        self.assertEqual(self.heads()[0]["conflict"], ["ep-m1", free["record_id"]])

    def envelope_for(self, env: dict, key: str, stamp: str) -> dict:
        from an_kla import identity_c0
        from datetime import datetime, timezone

        identity = identity_c0.build_identity(self.store.project_root, env)
        digest = identity_c0.derive_idempotency_key(identity, "state", key, None, "main")
        moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        return identity_c0.build_envelope(identity, "state", digest, lambda: moment)


class StateIdempotencyTests(StateCase):
    def test_s1_s2_s1_by_the_same_writer_leaves_the_second_s1_vigent(self) -> None:
        s1 = self.put("S1")
        s2 = self.put("S2")
        again = self.put("S1")
        self.assertEqual((again["state"], again["operation"]), ("committed", "supersede"))
        self.assertNotIn("already_committed", again)
        self.assertNotEqual(again["record_id"], s1["record_id"])
        self.assertEqual(again["retired"]["id"], s2["record_id"])
        self.assertEqual([h["id"] for h in self.heads()], [again["record_id"]])
        self.assertEqual(self.heads()[0]["text"], "S1")

    def test_a_retry_after_commit_does_not_duplicate(self) -> None:
        first = self.put("estado")
        retry = self.put("estado")
        self.assertEqual((retry["state"], retry["already_committed"], retry["record_id"]), ("committed", True, first["record_id"]))
        self.assertEqual(len(self.episodes()), 1)

    def test_a_late_retry_does_not_overwrite_another_agent(self) -> None:
        mine = self.put("S1", env=A)
        theirs = self.put("X", env=B)
        retry = self.put("S1", env=A)
        self.assertEqual((retry["already_committed"], retry["record_id"]), (True, mine["record_id"]))
        self.assertEqual(retry["retired_by"], theirs["record_id"])
        self.assertEqual([h["id"] for h in self.heads()], [theirs["record_id"]])
        self.assertEqual(len(self.episodes()), 2)

    def test_two_pending_copies_write_one_record(self) -> None:
        factory = EntryFactory(self.store, A)
        names = [factory.write("copia", kind="state", slot="main", key=None) for _ in range(2)]
        report = inbox_drain.drain(self.store)
        self.assertEqual((report["committed"]["count"], report["already_committed"]["count"]), (1, 1))
        self.assertEqual(report["already_committed"]["entries"][0]["entry"], names[1])
        self.assertEqual(len(self.episodes()), 1)

    def test_a_cut_after_the_commit_leaves_the_entry_and_the_retry_does_not_duplicate(self) -> None:
        factory = EntryFactory(self.store, A)
        name = factory.write("corte", kind="state", slot="main")
        saved = (factory.pending / name).read_bytes()
        self.assertEqual(inbox_drain.drain(self.store)["committed"]["count"], 1)
        (factory.pending / name).write_bytes(saved)  # kill -9 entre el commit y el borrado de la entrada
        report = inbox_drain.drain(self.store)
        self.assertEqual((report["committed"]["count"], report["already_committed"]["count"]), (0, 1))
        self.assertEqual(len(self.episodes()), 1)

    def test_a_key_reused_with_another_text_is_a_collision(self) -> None:
        first = self.put("uno", idempotency_key="clave-fija")
        second = self.put("dos", idempotency_key="clave-fija")
        self.assertEqual(first["state"], "committed")
        self.assertEqual((second["state"], second["code"]), ("rejected", "remember_id_collision"))


class SplitBatchTests(StateCase):
    def test_three_states_of_one_slot_and_one_of_another_make_three_transactions(self) -> None:
        factory = EntryFactory(self.store, A)
        factory.write("m1", kind="state", slot="main")
        factory.write("otra", kind="state", slot="otra")
        factory.write("m2", kind="state", slot="main")
        factory.write("m3", kind="state", slot="main")
        report = inbox_drain.drain(self.store)
        self.assertEqual(report["state"], "drained")
        # m1 y otra (ambos `add`) van juntos; m2 y m3 repiten la casilla main: una transacción cada uno.
        self.assertEqual((report["committed"]["count"], len(report["batches"])), (4, 3))
        by_text = {self.episodes()[e["record_id"]]["text"]: e for e in report["committed"]["entries"]}
        self.assertEqual(by_text["m1"]["retired_by"], by_text["m2"]["record_id"])
        self.assertEqual(by_text["m2"]["retired_by"], by_text["m3"]["record_id"])
        self.assertNotIn("retired_by", by_text["m3"])
        self.assertNotIn("retired_by", by_text["otra"])
        self.assertEqual([h["text"] for h in self.heads(all_slots=True)], ["m3", "otra"])

    def test_an_add_and_a_supersede_never_share_a_transaction(self) -> None:
        factory = EntryFactory(self.store, A)
        for text, slot in (("m1", "main"), ("m2", "main"), ("otra", "otra"), ("m3", "main")):
            factory.write(text, kind="state", slot=slot)
        report = inbox_drain.drain(self.store)
        self.assertEqual((report["committed"]["count"], len(report["batches"])), (4, 4))
        self.assertEqual([h["text"] for h in self.heads(all_slots=True)], ["m3", "otra"])

    def test_the_last_enqueued_wins_even_if_the_requester_is_older(self) -> None:
        factory = EntryFactory(self.store, A)
        old = factory.write("encolado antes", kind="state", slot="main")
        newer = EntryFactory(self.store, B)
        newer.counter = factory.counter
        newer.write("encolado después", kind="state", slot="main")
        report = inbox_drain.drain(self.store, include_entry=old, max_batches=1)
        self.assertEqual(report["committed"]["entries"][0]["entry"], old)
        inbox_drain.drain(self.store)
        self.assertEqual([h["text"] for h in self.heads()], ["encolado después"])

    def test_a_v1_state_entry_belongs_to_main(self) -> None:
        factory = EntryFactory(self.store, A)
        factory.write("estado de antes del ADR", kind="state")
        inbox_drain.drain(self.store)
        self.assertEqual(self.episodes().popitem()[1]["slot"], "main")
        self.assertEqual(self.heads()[0]["text"], "estado de antes del ADR")

    def test_a_v2_entry_with_a_bad_slot_is_rejected(self) -> None:
        factory = EntryFactory(self.store, A)
        data = factory.entry("x", kind="state", slot="main")
        data["slot"] = "MAL"
        from an_kla.canonical import canonical_json

        name = factory.write_raw(canonical_json(data))
        report = inbox_drain.drain(self.store)
        self.assertEqual([e["entry"] for e in report["rejected"]["entries"]], [name])


if __name__ == "__main__":
    unittest.main()
