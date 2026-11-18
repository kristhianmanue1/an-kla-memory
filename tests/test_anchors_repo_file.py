"""C3 ``repo_file`` vectors (48) plus the repo-file ones of erratum 1 (W24, R26), on real Git."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from an_kla.anchors import AnchorRejected, validate_anchor
from an_kla.anchors_git import GitRepo
from an_kla.anchors_repo_file import ABSENT, ReadContext, verify_repo_file, write_rejection

from anchors_c3_support import full_anchor, load_vectors, materialize

CHECKED = (
    "source", "source_reason", "quote", "quote_reason", "integrity", "integrity_reason",
    "at", "match", "matched_text", "freshness", "reason",
)


def run_case(case: dict, root: Path) -> dict:
    """The vector's observable result: a rejection code or the check output."""
    commits = materialize(case["setup"], root)
    anchor = validate_anchor(full_anchor(case["anchor"], commits), case["record_type"])
    ctx = ReadContext(
        default_branch=case["default_branch"] if "default_branch" in case else ABSENT,
        envelope_branch=case["envelope_branch"],
    )
    with GitRepo(root) as repo:
        try:
            result = verify_repo_file(repo, anchor, case["record_type"], case["moment"], ctx)
        except AnchorRejected as rejected:
            return {"reject": rejected.code}
    code = write_rejection(result) if case["moment"] == "write" else None
    return {"reject": code} if code else {"reject": None, **result}


class RepoFileVectorsTest(unittest.TestCase):
    def test_vectors(self) -> None:
        cases = load_vectors("vectores.json")["repo_file"] + load_vectors("vectores-errata-1.json")["repo_file"]
        self.assertEqual(len(cases), 50)
        for case in cases:
            with self.subTest(case["id"]), tempfile.TemporaryDirectory() as tmp:
                got = run_case(case, Path(tmp) / "repo")
                for field, wanted in case["expect"].items():
                    if field in CHECKED or field == "reject":
                        self.assertEqual(got.get(field), wanted, f"{case['id']} {field}")


if __name__ == "__main__":
    unittest.main()
