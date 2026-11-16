"""Criterio 4 (ADR-0063 D3) de extremo a extremo: ``remember --supersedes`` con variables de lanzador distintas."""

from __future__ import annotations

import json
import unittest

from an_kla.canonical import digest_json
from an_kla.store import MemoryStore
from an_kla.vigency import is_active
from tests.inbox_support import InboxCase
from tests.remember_support import cli, remember

A = {"AN_KLA_AGENT_NAME": "agente-a", "AN_KLA_SESSION_ID": "sesion-a-1"}
B = {"AN_KLA_AGENT_NAME": "agente-b", "AN_KLA_SESSION_ID": "sesion-b-1"}


class DisputeTests(InboxCase):
    def rows(self) -> tuple:
        snapshot = MemoryStore(self.project).snapshot()
        return snapshot, {r["id"]: r for r in snapshot.records["facts"]}

    def disputes(self, target: str) -> dict:
        done = cli(self.project, "disputes", "list", "--target", target)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_disputes_a_fact_of_b_and_the_original_stays_vigent(self) -> None:
        _, theirs = remember(self.project, "el servidor es debian", env=B)
        rc, mine = remember(self.project, "el servidor es ubuntu", "--supersedes", theirs["record_id"], env=A)
        self.assertEqual((rc, mine["state"], mine["operation"]), (0, "committed", "add"))
        self.assertEqual(mine["disputed"]["target_id"], theirs["record_id"])
        self.assertNotIn("superseded", mine)
        snapshot, rows = self.rows()
        self.assertTrue(is_active(rows[theirs["record_id"]]))
        raw = next(r for r in snapshot.raw_records["facts"] if r["id"] == theirs["record_id"])
        self.assertEqual(mine["disputed"]["target_record_sha256"], digest_json(raw))
        listed = self.disputes(theirs["record_id"])
        self.assertEqual([d["id"] for d in listed["disputes"]], [mine["record_id"]])
        self.assertEqual(listed["disputes"][0]["target"]["record_sha256"], digest_json(raw))
        self.assertIs(listed["disputes"][0]["target"]["active"], True)
        self.assertEqual(listed["disputes"][0]["writer"]["agent"]["name"], "agente-a")

    def test_control_a_supersedes_its_own_fact_and_the_old_one_is_replaced(self) -> None:
        _, first = remember(self.project, "versión uno", env=A)
        _, second = remember(self.project, "versión dos", "--supersedes", first["record_id"], env=A)
        self.assertEqual((second["operation"], second["superseded"]), ("supersede", first["record_id"]))
        _, rows = self.rows()
        self.assertFalse(is_active(rows[first["record_id"]]))
        self.assertEqual(rows[first["record_id"]].get("status"), "sustituida")
        self.assertEqual(self.disputes(first["record_id"])["disputes"], [])

    def test_a_legacy_target_without_envelope_is_disputed(self) -> None:
        self.commit_record("f-legado", text="hecho de antes del sobre")
        _, mine = remember(self.project, "lo contradigo", "--supersedes", "f-legado", env=A)
        self.assertEqual(mine["operation"], "add")
        self.assertEqual(mine["disputed"]["target_id"], "f-legado")
        _, rows = self.rows()
        self.assertTrue(is_active(rows["f-legado"]))

    def test_without_agent_name_the_sentinel_is_never_owner_even_of_its_own_fact(self) -> None:
        env = {"AN_KLA_AGENT_NAME": None}
        _, first = remember(self.project, "hecho sin nombre", env=env)
        _, second = remember(self.project, "lo corrijo", "--supersedes", first["record_id"], env=env)
        self.assertEqual(second["operation"], "add")
        self.assertEqual(second["disputed"]["target_id"], first["record_id"])
        _, rows = self.rows()
        self.assertTrue(is_active(rows[first["record_id"]]))
        self.assertEqual(rows[first["record_id"]]["an_kla_envelope"]["writer"]["agent"]["name"], "sin-nombre")

    def test_two_sessions_with_the_same_agent_name_supersede_without_dispute(self) -> None:
        one = {"AN_KLA_AGENT_NAME": "agente-a", "AN_KLA_SESSION_ID": "sesion-uno"}
        two = {"AN_KLA_AGENT_NAME": "agente-a", "AN_KLA_SESSION_ID": "sesion-dos"}
        _, first = remember(self.project, "de la sesión uno", env=one)
        _, second = remember(self.project, "de la sesión dos", "--supersedes", first["record_id"], env=two)
        self.assertEqual((second["operation"], second["superseded"]), ("supersede", first["record_id"]))
        _, rows = self.rows()
        sessions = [rows[first["record_id"]]["an_kla_envelope"]["writer"]["session"]["id"],
                    rows[second["record_id"]]["an_kla_envelope"]["writer"]["session"]["id"]]
        self.assertEqual(sessions, ["claude-code:sesion-uno", "claude-code:sesion-dos"])  # límite declarado, auditable

    def test_the_same_text_with_two_targets_makes_two_records(self) -> None:
        _, one = remember(self.project, "uno", env=B)
        _, two = remember(self.project, "dos", env=B)
        _, d1 = remember(self.project, "mismo texto", "--supersedes", one["record_id"], env=A)
        _, d2 = remember(self.project, "mismo texto", "--supersedes", two["record_id"], env=A)
        self.assertNotEqual(d1["record_id"], d2["record_id"])
        self.assertEqual(d1["state"], d2["state"])
        _, rows = self.rows()
        self.assertEqual(sum(1 for r in rows.values() if r.get("text") == "mismo texto"), 2)

    def test_a_foreign_dispute_across_repos_is_foreign(self) -> None:
        """Mismo nombre de agente en otro repo (otro `repo.id`) no es dueño."""

        from tests.inbox_support import make_project
        import tempfile
        from pathlib import Path

        _, theirs = remember(self.project, "hecho del repo uno", env=A)
        with tempfile.TemporaryDirectory(prefix="otro-repo-") as temp:
            other = make_project(Path(temp).resolve())
            rc, mine = remember(other, "desde otro repo", "--supersedes", theirs["record_id"], env=A, store_root=Path(self.store.root).parent)
        self.assertEqual((rc, mine["operation"]), (0, "add"), mine)
        self.assertEqual(mine["disputed"]["target_id"], theirs["record_id"])


if __name__ == "__main__":
    unittest.main()
