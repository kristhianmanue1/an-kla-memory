from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from scripts.check_release_tag import validate_release_gate
from scripts.check_benchmark_corpus import reference_corpus_sha256


TAG = "v0.1.0-beta.12"


class ReleaseGateTests(unittest.TestCase):
    def _root(self, *lines: str) -> tempfile.TemporaryDirectory:
        temp = tempfile.TemporaryDirectory()
        release_dir = Path(temp.name) / "docs" / "releases"
        release_dir.mkdir(parents=True)
        (release_dir / f"{TAG}-adversarial.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        provenance_dir = (
            Path(temp.name)
            / "an_kla"
            / "resources"
            / "retrieval-benchmark-v2"
        )
        provenance_dir.mkdir(parents=True)
        corpus_sha256 = reference_corpus_sha256()
        provenance = {
            "schema": "an-kla/provenance-manifest-v1",
            "corpus_sha256": corpus_sha256,
            "source_kind": "local-untrusted-memory-sanitized/v1",
            "sanitization": {
                "method": "manual-paraphrase/v1",
                "retains_verbatim_source": False,
            },
            "forbidden_content": [
                "hashes", "ids", "logs", "paths", "quotes", "urls", "usernames"
            ],
            "source_specific_denylist": {
                "location": "operator-local-not-versioned",
                "required_before_publication": True,
            },
            "human_review": {
                "status": "passed",
                "corpus_sha256": corpus_sha256,
                "reviewer": "maintainer",
            },
            "scanner": {
                "status": "passed",
                "tool": "check_benchmark_corpus/v1",
                "configuration_sha256": "sha256:4b98ae5dd3d5187627096e74ac394fce6a05f4ff65b87f45d888aebca4234e5d",
            },
        }
        (provenance_dir / "provenance.json").write_text(
            json.dumps(provenance), encoding="utf-8"
        )
        return temp

    def test_fails_closed_when_human_review_is_pending(self) -> None:
        temp = self._root(
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->'
        )
        self.addCleanup(temp.cleanup)
        path = (
            Path(temp.name)
            / "an_kla/resources/retrieval-benchmark-v2/provenance.json"
        )
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["human_review"] = {
            "status": "pending",
            "corpus_sha256": provenance["corpus_sha256"],
            "reviewer": None,
        }
        path.write_text(json.dumps(provenance), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "benchmark_human_review_pending"):
            validate_release_gate(Path(temp.name), TAG)

    def test_fails_closed_when_review_corpus_hash_is_wrong(self) -> None:
        temp = self._root(
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->'
        )
        self.addCleanup(temp.cleanup)
        path = (
            Path(temp.name)
            / "an_kla/resources/retrieval-benchmark-v2/provenance.json"
        )
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["human_review"]["corpus_sha256"] = "sha256:" + "0" * 64
        path.write_text(json.dumps(provenance), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "benchmark_provenance_invalid"):
            validate_release_gate(Path(temp.name), TAG)

    def test_fails_closed_when_reviewer_is_not_maintainer(self) -> None:
        temp = self._root(
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->'
        )
        self.addCleanup(temp.cleanup)
        path = (
            Path(temp.name)
            / "an_kla/resources/retrieval-benchmark-v2/provenance.json"
        )
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["human_review"]["reviewer"] = "agent"
        path.write_text(json.dumps(provenance), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "benchmark_provenance_invalid"):
            validate_release_gate(Path(temp.name), TAG)

    def test_accepts_one_exact_candidate_proceed_marker(self) -> None:
        temp = self._root(
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->'
        )
        self.addCleanup(temp.cleanup)
        validate_release_gate(Path(temp.name), TAG)

    def test_fails_closed_for_missing_or_duplicate_marker(self) -> None:
        cases = (
            (("# no gate",), "release_gate_missing"),
            (
                (
                    '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->',
                    '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->',
                ),
                "release_gate_duplicated",
            ),
        )
        for lines, expected in cases:
            with self.subTest(expected=expected):
                temp = self._root(*lines)
                try:
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_release_gate(Path(temp.name), TAG)
                finally:
                    temp.cleanup()

    def test_fails_closed_for_wrong_decision_scope_or_tag(self) -> None:
        cases = (
            ({"decision": "fix-and-retry", "scope": "release-candidate", "tag": TAG}, "release_gate_not_proceed"),
            ({"decision": "proceed", "scope": "PR-C", "tag": TAG}, "release_gate_scope_mismatch"),
            ({"decision": "proceed", "scope": "release-candidate", "tag": "v0.1.0-beta.8"}, "release_gate_tag_mismatch"),
        )
        for gate, expected in cases:
            marker = (
                '<!-- an-kla:release-gate '
                f'{{"decision":"{gate["decision"]}","scope":"{gate["scope"]}","tag":"{gate["tag"]}"}} -->'
            )
            with self.subTest(expected=expected):
                temp = self._root(marker)
                try:
                    with self.assertRaisesRegex(ValueError, expected):
                        validate_release_gate(Path(temp.name), TAG)
                finally:
                    temp.cleanup()

    def test_fails_closed_for_malformed_or_extra_fields(self) -> None:
        cases = (
            "<!-- an-kla:release-gate not-json -->",
            '<!-- an-kla:release-gate {"decision":"proceed","extra":1,"scope":"release-candidate","tag":"v0.1.0-beta.12"} -->',
            '<!-- an-kla:release-gate {"decision":"fix-and-retry","decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->',
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"PR-C","scope":"release-candidate","tag":"v0.1.0-beta.12"} -->',
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.8","tag":"v0.1.0-beta.12"} -->',
        )
        for marker in cases:
            with self.subTest(marker=marker):
                temp = self._root(marker)
                try:
                    with self.assertRaisesRegex(ValueError, "release_gate_invalid"):
                        validate_release_gate(Path(temp.name), TAG)
                finally:
                    temp.cleanup()


if __name__ == "__main__":
    unittest.main()
