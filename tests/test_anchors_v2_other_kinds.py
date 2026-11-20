"""ADR-0071, acceptance 2: the v1 vectors of ``repo-file`` and ``conversation``, with ``schema`` changed to ``memoria/ancla/v2``.

Erratum 2 of the contract (B3): a v2 anchor may be of any kind; those of ``repo-file`` and ``conversation`` are accepted
and checked exactly as in v1.  Every vector runs twice, with v1 and with v2, and the two results must be the same (and
the vector's own ``expect``).  What is *written* stays v1 for those kinds (ADR-0071 §1): that is checked in ``test_document_v2_write``.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from an_kla.anchors import ANCHOR_SCHEMA_V2, validate_anchor

from tests import test_anchors_repo_file as repo_file
from tests import test_anchors_vectors as conversation
from tests.anchors_c3_support import full_anchor, load_vectors


def as_v2(builder):
    return lambda *args, **kwargs: {**builder(*args, **kwargs), "schema": ANCHOR_SCHEMA_V2}


class RepoFileAsV2(unittest.TestCase):
    def test_the_50_vectors_give_the_same_with_v2(self) -> None:
        cases = load_vectors("vectores.json")["repo_file"] + load_vectors("vectores-errata-1.json")["repo_file"]
        self.assertEqual(len(cases), 50)
        for case in cases:
            with self.subTest(case["id"]), tempfile.TemporaryDirectory() as tmp:
                v1 = repo_file.run_case(case, Path(tmp) / "uno")
                with mock.patch.object(repo_file, "full_anchor", as_v2(full_anchor)):
                    v2 = repo_file.run_case(case, Path(tmp) / "dos")
                self.assertEqual(v2, v1, case["id"])
                for field, wanted in case["expect"].items():
                    if field in repo_file.CHECKED or field == "reject":
                        self.assertEqual(v2.get(field), wanted, f"{case['id']} {field}")


class ConversationAsV2(unittest.TestCase):
    def test_the_13_vectors_give_the_same_with_v2(self) -> None:
        cases = load_vectors("vectores.json")["conversation"] + load_vectors("vectores-errata-1.json")["conversation"]
        self.assertEqual(len(cases), 13)
        for case in cases:
            with self.subTest(case["id"]):
                v1 = conversation.run_conversation(case)
                with mock.patch.object(conversation, "conversation_anchor", as_v2(conversation.conversation_anchor)):
                    v2 = conversation.run_conversation(case)
                self.assertEqual(v2, v1, case["id"])
                self.assertEqual({k: v2.get(k) for k in case["expect"]}, case["expect"])

    def test_a_v2_anchor_of_these_kinds_validates(self) -> None:
        anchor = as_v2(conversation.conversation_anchor)({"resolution": "pending", "turn_id": None, "quote": "manda renovar de manera indefinida"})
        self.assertEqual(validate_anchor(anchor, "fact")["schema"], ANCHOR_SCHEMA_V2)


if __name__ == "__main__":
    unittest.main()
