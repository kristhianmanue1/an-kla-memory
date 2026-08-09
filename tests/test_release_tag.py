from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.check_release_tag import validate_release_gate


TAG = "v0.1.0-beta.9"


class ReleaseGateTests(unittest.TestCase):
    def _root(self, *lines: str) -> tempfile.TemporaryDirectory:
        temp = tempfile.TemporaryDirectory()
        release_dir = Path(temp.name) / "docs" / "releases"
        release_dir.mkdir(parents=True)
        (release_dir / f"{TAG}-adversarial.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        return temp

    def test_accepts_one_exact_candidate_proceed_marker(self) -> None:
        temp = self._root(
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.9"} -->'
        )
        self.addCleanup(temp.cleanup)
        validate_release_gate(Path(temp.name), TAG)

    def test_fails_closed_for_missing_or_duplicate_marker(self) -> None:
        cases = (
            (("# no gate",), "release_gate_missing"),
            (
                (
                    '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.9"} -->',
                    '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.9"} -->',
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
            '<!-- an-kla:release-gate {"decision":"proceed","extra":1,"scope":"release-candidate","tag":"v0.1.0-beta.9"} -->',
            '<!-- an-kla:release-gate {"decision":"fix-and-retry","decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.9"} -->',
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"PR-C","scope":"release-candidate","tag":"v0.1.0-beta.9"} -->',
            '<!-- an-kla:release-gate {"decision":"proceed","scope":"release-candidate","tag":"v0.1.0-beta.8","tag":"v0.1.0-beta.9"} -->',
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
