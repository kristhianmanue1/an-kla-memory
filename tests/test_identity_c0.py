"""Writer identity C0 and record envelope (ADR-0063 D2).

The conformance vectors are the frozen C0 `8fccbcc` ones plus those of its
errata 1 (`4c0fc1e`), copied under `tests/fixtures/identidad-v1` and checked by
digest before use.  The derivation
cases of `repo.id` that static vectors cannot cover run on temporary repos.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from an_kla import identity_c0 as c0
from an_kla.canonical import digest_json
from an_kla.schemas import schema_bytes, schema_catalog, schema_document, schema_names

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "fixtures" / "identidad-v1" / "vectores.json"
VECTORS_SHA256 = "a169a7f93728f327f2f47282b339ff8a2b4fc1f0e9cd383a6afe7f6441a92643"
ERRATA_1 = VECTORS.parent / "vectores-errata-1.json"
ERRATA_1_SHA256 = "bd6abbae0b135ac6b64910ee0e967d2d9a929763399de6f286d13c126a36654d"
GIT_OK = c0.git_is_usable()
# Isolates repo-building commands from the developer's global Git config.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

VALID_ENV = {
    "AN_KLA_AGENT_NAME": "ankla-ejecutor-1",
    "AN_KLA_AGENT_CLI": "claude-code",
    "AN_KLA_AGENT_MODEL": "claude-sonnet-5-5",
    "AN_KLA_AGENT_ROLE": "ejecutor",
    "AN_KLA_SESSION_ID": "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6",
}


def load_vectors(path: Path = VECTORS, expected_sha256: str = VECTORS_SHA256) -> dict:
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise AssertionError(f"{path.name} digest {digest} != {expected_sha256}")
    return json.loads(payload)


def vector_failures(data: dict) -> list[str]:
    """Run the five vector groups; one line per failing case."""

    failures: list[str] = []

    def check(label: str, expected: object, actual: object) -> None:
        if expected != actual:
            failures.append(f"{label}: expected {expected!r}, got {actual!r}")

    for case in data["validos"]:
        check(f"valido {case['nombre']}", [], c0.validate(case["objeto"]))
    for case in data["invalidos"]:
        reasons = c0.validate(case["objeto"])
        check(f"invalido {case['nombre']} ({case['motivo']} in {reasons})", True, case["motivo"] in reasons)
    for case in data["normalizacion"]:
        check(f"normalizacion {case['url']!r}", case["repo_id"], c0.normalize_remote(case["url"]))
    for case in data["remoto_no_normalizable"]:
        check(f"remoto {case['url']!r} base={case.get('base')!r}", case["repo_id"],
              c0.repo_id_from_remote(case["url"], case.get("base")))
    for case in data["local"]:
        check(f"local {case['ruta_comun']!r}", case["repo_id"], c0.repo_id_from_common_dir(case["ruta_comun"]))
    return failures


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=c0", "-c", "user.email=c0@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        check=True, capture_output=True, env={**os.environ, **GIT_ENV},
    )


def hash16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class VectorTests(unittest.TestCase):
    def test_vectors_file_is_the_frozen_copy(self) -> None:
        self.assertEqual(hashlib.sha256(VECTORS.read_bytes()).hexdigest(), VECTORS_SHA256)
        origin = (VECTORS.parent / "ORIGEN.md").read_text(encoding="utf-8")
        self.assertIn(VECTORS_SHA256, origin)
        self.assertIn("8fccbcc", origin)

    def test_the_five_groups_hold_76_cases(self) -> None:
        data = load_vectors()
        counts = {k: len(data[k]) for k in ("validos", "invalidos", "normalizacion", "remoto_no_normalizable", "local")}
        self.assertEqual(counts, {"validos": 9, "invalidos": 33, "normalizacion": 22,
                                  "remoto_no_normalizable": 10, "local": 2})
        self.assertEqual(sum(counts.values()), 76)

    def test_all_76_vectors_pass(self) -> None:
        self.assertEqual(vector_failures(load_vectors()), [])

    def test_errata_1_file_is_the_copy_from_coordination(self) -> None:
        self.assertEqual(hashlib.sha256(ERRATA_1.read_bytes()).hexdigest(), ERRATA_1_SHA256)
        origin = (VECTORS.parent / "ORIGEN.md").read_text(encoding="utf-8")
        self.assertIn(ERRATA_1_SHA256, origin)
        self.assertIn("4c0fc1e", origin)
        self.assertIn("ERRATAS.md", origin)

    def test_all_11_errata_1_vectors_pass(self) -> None:
        data = load_vectors(ERRATA_1, ERRATA_1_SHA256)
        self.assertEqual((data["schema"], data["errata"]), ("memoria/identidad/v1", 1))
        counts = {k: len(data[k]) for k in ("validos", "invalidos", "normalizacion", "remoto_no_normalizable", "local")}
        self.assertEqual(counts, {"validos": 1, "invalidos": 6, "normalizacion": 3,
                                  "remoto_no_normalizable": 1, "local": 0})
        self.assertEqual(sum(counts.values()), 11)
        self.assertEqual(vector_failures(data), [])

    def test_tampered_errata_1_file_is_detected_by_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / "vectores-errata-1.json"
            tampered.write_bytes(ERRATA_1.read_bytes() + b" ")
            with self.assertRaises(AssertionError):
                load_vectors(tampered, ERRATA_1_SHA256)

    def test_negative_control_an_altered_vector_fails(self) -> None:
        for label, mutate in (
            ("valid object with a role outside the enum", lambda d: d["validos"][0]["objeto"]["agent"].update(role="jefe")),
            ("invalid case expecting a reason it does not raise", lambda d: d["invalidos"][0].update(motivo="no_existe")),
            ("normalization with another id", lambda d: d["normalizacion"][0].update(repo_id="x.example/otro")),
            ("remote hash with a flipped digit", lambda d: d["remoto_no_normalizable"][0].update(repo_id="remoto:0000000000000000")),
            ("local hash with a flipped digit", lambda d: d["local"][0].update(repo_id="local:0000000000000000")),
        ):
            with self.subTest(label):
                data = copy.deepcopy(load_vectors())
                mutate(data)
                self.assertNotEqual(vector_failures(data), [])

    def test_tampered_vectors_file_is_detected_by_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tampered = Path(tmp) / "vectores.json"
            tampered.write_bytes(VECTORS.read_bytes() + b" ")
            with self.assertRaises(AssertionError):
                load_vectors(tampered)
            tampered.write_bytes(VECTORS.read_bytes())
            self.assertEqual(load_vectors(tampered), load_vectors())

    def test_validator_never_raises_on_wrong_types(self) -> None:
        for value in (None, 1, [], "x", {"schema": 1, "repo": [], "agent": None, "session": 3}):
            with self.subTest(value=value):
                self.assertNotEqual(c0.validate(value), [])
        valid = copy.deepcopy(load_vectors()["validos"][0]["objeto"])
        for path, wrong in ((("repo", "id"), 5), (("repo", "branch"), None), (("agent", "name"), ["a"]),
                            (("agent", "model"), 7), (("session", "id"), {"a": 1})):
            with self.subTest(path=path):
                candidate = copy.deepcopy(valid)
                candidate[path[0]][path[1]] = wrong
                self.assertNotEqual(c0.validate(candidate), [])

    def test_a_newline_inside_the_input_changes_the_case_not_just_the_verdict(self) -> None:
        # R1-03, now C0 errata 1 (ERRATAS.md in coordination).  The `8fccbcc` reference's
        # `$` let these through as canonical ids that contain the newline; fullmatch does not.
        self.assertIsNone(c0.normalize_remote("OM\n:eU3"))
        self.assertEqual(c0.repo_id_from_remote("GwXYo\n:Vu", "/base"), "remoto:e720d808474ba2b6")
        self.assertEqual(c0.repo_id_from_remote("GwXYo\n:Vu", "/base"), "remoto:" + hash16("GwXYo\n:Vu"))
        self.assertFalse(c0.is_valid_branch("rama\n"))
        self.assertFalse(c0.is_valid_branch("ra\nma"))
        self.assertFalse(c0.is_canonical_repo_id("om\n/eu3"))

    def test_trailing_newline_is_not_a_valid_branch_or_id(self) -> None:
        # `$` would accept it; the contract says no whitespace.
        self.assertFalse(c0.is_valid_branch("feat/x\n"))
        self.assertFalse(c0.is_canonical_repo_id("github.com/a/b\n"))
        self.assertNotEqual(c0.validate({**copy.deepcopy(load_vectors()["validos"][0]["objeto"]),
                                         "session": {"id": "claude-code:abc\n"}}), [])


@unittest.skipUnless(GIT_OK, f"git >= {c0.GIT_MIN_VERSION} not available: the derivation test needs real repositories")
class DerivationTests(unittest.TestCase):
    """Equivalent of the reference `--prueba-derivacion`: 8 checks on temporary repos."""

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory(prefix="c0-derivacion-")
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()

    def make_repo(self, path: Path) -> Path:
        path.mkdir(parents=True)
        git(path, "init", "-q")
        git(path, "commit", "-q", "--allow-empty", "-m", "c0")
        return path

    def test_local_derivation_and_relative_remote(self) -> None:
        a = self.make_repo(self.base / "a")
        b = self.make_repo(self.base / "sub" / "b")
        worktree = self.base / "wt"
        git(a, "worktree", "add", "-q", str(worktree))
        second = self.base / "wt2"
        git(a, "worktree", "add", "-q", str(second))
        link = self.base / "enlace"
        link.symlink_to(a, target_is_directory=True)
        expected = c0.repo_id_from_common_dir(str((a / ".git").resolve()))

        self.assertEqual(c0.repo_id_for(a), expected)                                   # 1 checkout
        self.assertEqual(c0.repo_id_for(worktree), expected)                            # 2 worktree
        self.assertEqual(c0.repo_id_for(second), expected)                              # 2b another worktree
        self.assertEqual(c0.repo_id_for(link), expected)                                # 3 symlink
        self.assertNotEqual(c0.repo_id_for(a), c0.repo_id_from_common_dir(str(a)))      # 4 not the checkout root
        self.assertNotEqual(c0.repo_id_for(b), expected)                                # 5 another repo
        for repo in (a, b):
            git(repo, "remote", "add", "origin", "./remoto-relativo")
        self.assertEqual(c0.repo_id_for(a), "remoto:" + hash16(str((a / "remoto-relativo").resolve())))  # 6
        self.assertNotEqual(c0.repo_id_for(a), c0.repo_id_for(b))                       # 7 no collision
        self.assertEqual(c0.repo_id_for(worktree),                                      # 8 own root
                         "remoto:" + hash16(str((worktree / "remoto-relativo").resolve())))

    def test_remote_cases_one_and_two_from_a_real_origin(self) -> None:
        repo = self.make_repo(self.base / "r")
        git(repo, "remote", "add", "origin", "git@GitHub.com:Owner/Repo.git")
        self.assertEqual(c0.repo_id_for(repo), "github.com/owner/repo")
        git(repo, "remote", "set-url", "origin", "file:///srv/repos/demo.git")
        self.assertEqual(c0.repo_id_for(repo), "remoto:88b36cf419d13ed6")

    def test_bare_repo_uses_its_own_directory_as_base_for_a_relative_remote(self) -> None:
        bare = self.base / "desnudo.git"
        bare.mkdir()
        git(bare, "init", "-q", "--bare")
        self.assertEqual(c0.repo_id_for(bare), c0.repo_id_from_common_dir(str(bare.resolve())))
        git(bare, "remote", "add", "origin", "./remoto-relativo")
        self.assertEqual(c0.repo_id_for(bare), "remoto:" + hash16(str((bare / "remoto-relativo").resolve())))

    def test_repo_outside_git_is_unavailable(self) -> None:
        plain = self.base / "plano"
        plain.mkdir()
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.base)}):
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.repo_id_for(plain)
        self.assertEqual(caught.exception.code, "identity_repo_unavailable")
        self.assertEqual(str(caught.exception), "identity_repo_unavailable")

    def test_branch_is_short_and_absent_when_detached(self) -> None:
        repo = self.make_repo(self.base / "ramas")
        git(repo, "checkout", "-q", "-b", "feat/e1a-bandeja")
        self.assertEqual(c0.branch_for(repo), "feat/e1a-bandeja")
        git(repo, "tag", "feat/e1a-bandeja", "HEAD")  # a tag sharing the name must not change the answer
        self.assertEqual(c0.branch_for(repo), "feat/e1a-bandeja")
        git(repo, "checkout", "-q", "--detach")
        self.assertIsNone(c0.branch_for(repo))

    def test_identity_from_env_in_a_real_checkout(self) -> None:
        repo = self.make_repo(self.base / "ident")
        git(repo, "checkout", "-q", "-b", "feat/x")
        git(repo, "remote", "add", "origin", "https://github.com/kristhianmanue1/an-kla-memory.git")
        identity = c0.build_identity(repo, VALID_ENV)
        self.assertEqual(c0.validate(identity), [])
        self.assertEqual(identity, {
            "schema": "memoria/identidad/v1",
            "repo": {"id": "github.com/kristhianmanue1/an-kla-memory", "branch": "feat/x"},
            "agent": {"name": "ankla-ejecutor-1", "cli": "claude-code",
                      "model": "claude-sonnet-5-5", "role": "ejecutor"},
            "session": {"id": "claude-code:0a92bdfb-286a-44b5-8c24-8d7a1332c6b6"},
        })
        git(repo, "checkout", "-q", "--detach")
        self.assertNotIn("branch", c0.build_identity(repo, VALID_ENV)["repo"])

    def test_branch_that_violates_c0_is_rejected_not_corrected(self) -> None:
        repo = self.make_repo(self.base / "mala-rama")
        git(repo, "symbolic-ref", "HEAD", "refs/heads/-mala")
        with self.assertRaises(c0.IdentityC0Error) as caught:
            c0.build_identity(repo, VALID_ENV)
        self.assertEqual((caught.exception.code, caught.exception.field), ("identity_env_invalid", "repo.branch"))

    def test_env_is_checked_before_git_is_asked(self) -> None:
        plain = self.base / "sin-repo"
        plain.mkdir()
        with mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.base)}):
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.build_identity(plain, {"AN_KLA_AGENT_CLI": "Claude Code"})
            self.assertEqual(caught.exception.code, "identity_env_invalid")
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.build_identity(plain, VALID_ENV)
            self.assertEqual(caught.exception.code, "identity_repo_unavailable")

    def test_default_env_is_the_process_environment(self) -> None:
        repo = self.make_repo(self.base / "proceso")
        with mock.patch.dict(os.environ, VALID_ENV):
            identity = c0.build_identity(repo)
        self.assertEqual(identity["agent"]["name"], "ankla-ejecutor-1")
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "AN_KLA_AGENT_CLI"}, clear=True):
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.build_identity(repo)
        self.assertEqual(caught.exception.code, "identity_env_missing")


class EnvironmentIdentityTests(unittest.TestCase):
    """Identity construction that needs no repo: the env is validated first, and `git` is stubbed."""

    def setUp(self) -> None:
        for name, value in (("repo_id_for", "github.com/o/r"), ("branch_for", "main"), ("git_problem", None)):
            patcher = mock.patch.object(c0, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build(self, **overrides: str | None) -> dict:
        env = dict(VALID_ENV)
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return c0.build_identity("/ignored", env)

    def error(self, **overrides: str | None) -> c0.IdentityC0Error:
        with self.assertRaises(c0.IdentityC0Error) as caught:
            self.build(**overrides)
        return caught.exception

    def test_sentinels_when_optional_variables_are_absent(self) -> None:
        identity = self.build(AN_KLA_AGENT_NAME=None, AN_KLA_AGENT_MODEL=None,
                              AN_KLA_AGENT_ROLE=None, AN_KLA_SESSION_ID=None)
        self.assertEqual(identity["agent"], {"name": "sin-nombre", "cli": "claude-code",
                                             "model": "desconocido", "role": "desconocido"})
        self.assertEqual(identity["session"], {"id": "claude-code:sin-sesion"})
        self.assertEqual(c0.validate(identity), [])

    def test_only_the_cli_is_required(self) -> None:
        identity = c0.build_identity("/ignored", {"AN_KLA_AGENT_CLI": "codex"})
        self.assertEqual(c0.validate(identity), [])
        self.assertEqual(identity["session"]["id"], "codex:sin-sesion")

    def test_session_id_is_composed_with_the_cli(self) -> None:
        self.assertEqual(self.build(AN_KLA_AGENT_CLI="codex", AN_KLA_SESSION_ID="abc:def")["session"]["id"],
                         "codex:abc:def")

    def test_missing_cli_names_the_variable(self) -> None:
        error = self.error(AN_KLA_AGENT_CLI=None)
        self.assertEqual((error.code, error.field), ("identity_env_missing", "AN_KLA_AGENT_CLI"))

    def test_present_values_that_violate_c0_name_the_culprit_and_are_never_corrected(self) -> None:
        for label, overrides, field in (
            ("name outside the pattern", {"AN_KLA_AGENT_NAME": "Ejecutor 1"}, "AN_KLA_AGENT_NAME"),
            ("name too long", {"AN_KLA_AGENT_NAME": "a" * 33}, "AN_KLA_AGENT_NAME"),
            ("reserved name desconocido", {"AN_KLA_AGENT_NAME": "desconocido"}, "AN_KLA_AGENT_NAME"),
            ("reserved name sin-sesion", {"AN_KLA_AGENT_NAME": "sin-sesion"}, "AN_KLA_AGENT_NAME"),
            ("empty name is present, not a sentinel", {"AN_KLA_AGENT_NAME": ""}, "AN_KLA_AGENT_NAME"),
            ("cli outside the pattern", {"AN_KLA_AGENT_CLI": "Claude Code"}, "AN_KLA_AGENT_CLI"),
            ("empty cli is present, not missing", {"AN_KLA_AGENT_CLI": ""}, "AN_KLA_AGENT_CLI"),
            ("model with outer spaces", {"AN_KLA_AGENT_MODEL": " modelo"}, "AN_KLA_AGENT_MODEL"),
            ("model too long", {"AN_KLA_AGENT_MODEL": "m" * 81}, "AN_KLA_AGENT_MODEL"),
            ("empty model", {"AN_KLA_AGENT_MODEL": ""}, "AN_KLA_AGENT_MODEL"),
            ("role outside the enum", {"AN_KLA_AGENT_ROLE": "jefe"}, "AN_KLA_AGENT_ROLE"),
            ("session id with a space", {"AN_KLA_SESSION_ID": "con espacio"}, "AN_KLA_SESSION_ID"),
            ("session id too long", {"AN_KLA_SESSION_ID": "s" * 201}, "AN_KLA_SESSION_ID"),
            ("empty session id", {"AN_KLA_SESSION_ID": ""}, "AN_KLA_SESSION_ID"),
        ):
            with self.subTest(label):
                error = self.error(**overrides)
                self.assertEqual((error.code, error.field), ("identity_env_invalid", field))
                for value in overrides.values():
                    if value:
                        self.assertNotIn(value, repr(error.args) + str(error))

    def test_boundary_values_are_accepted(self) -> None:
        identity = self.build(AN_KLA_AGENT_NAME="a" * 32, AN_KLA_AGENT_MODEL="m" * 80,
                              AN_KLA_SESSION_ID="s" * 200, AN_KLA_AGENT_ROLE="desconocido")
        self.assertEqual(c0.validate(identity), [])

    def test_the_explicit_sentinel_name_is_accepted(self) -> None:
        self.assertEqual(self.build(AN_KLA_AGENT_NAME="sin-nombre")["agent"]["name"], "sin-nombre")

    def test_every_role_is_accepted(self) -> None:
        for role in sorted(c0.ROLES):
            with self.subTest(role=role):
                self.assertEqual(self.build(AN_KLA_AGENT_ROLE=role)["agent"]["role"], role)

    def test_the_caller_env_is_not_mutated(self) -> None:
        env = dict(VALID_ENV)
        c0.build_identity("/ignored", env)
        self.assertEqual(env, VALID_ENV)

    def test_a_reason_the_module_does_not_know_still_fails(self) -> None:
        with mock.patch.object(c0, "validate", return_value=["motivo_futuro"]):
            error = self.error()
        self.assertEqual((error.code, error.field), ("identity_env_invalid", "motivo_futuro"))

    def test_detached_head_leaves_the_branch_out(self) -> None:
        with mock.patch.object(c0, "branch_for", return_value=None):
            self.assertEqual(self.build()["repo"], {"id": "github.com/o/r"})


@unittest.skipIf(os.name == "nt", "the fake git is a POSIX shell script")
class GitAvailabilityTests(unittest.TestCase):
    """R1-05: a missing or too old git fails first, and says so."""

    def fake_git(self, version_line: str | None) -> Path:
        """A directory to use as the whole PATH, with a `git` that only knows `--version`."""
        directory = Path(tempfile.mkdtemp(prefix="c0-fake-git-"))
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        if version_line is not None:
            script = directory / "git"
            script.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "{version_line}"; exit 0; fi\nexit 1\n')
            script.chmod(0o755)
        return directory

    def error_with_path(self, directory: Path) -> c0.IdentityC0Error:
        with mock.patch.dict(os.environ, {"PATH": str(directory)}):
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.build_identity("/ignored", VALID_ENV)
        return caught.exception

    def test_absent_git_fails_before_anything_else(self) -> None:
        error = self.error_with_path(self.fake_git(None))
        self.assertEqual((error.code, error.field), ("identity_repo_unavailable", "git"))

    def test_old_git_is_told_apart_from_a_missing_one(self) -> None:
        error = self.error_with_path(self.fake_git("git version 2.30.2"))
        self.assertEqual((error.code, error.field), ("identity_repo_unavailable", "git>=2.31"))

    def test_git_check_precedes_the_env_check(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(self.fake_git(None))}):
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.build_identity("/ignored", {})
        self.assertEqual(caught.exception.code, "identity_repo_unavailable")

    def test_version_parsing_and_minimum(self) -> None:
        for line, version, usable in (
            ("git version 2.30.2", (2, 30), False),
            ("git version 2.31.0", (2, 31), True),
            ("git version 2.39.5 (Apple Git-154)", (2, 39), True),
            ("git version 3.0.0", (3, 0), True),
        ):
            with self.subTest(line), mock.patch.dict(os.environ, {"PATH": str(self.fake_git(line))}):
                self.assertEqual(c0.git_version(), version)
                self.assertEqual(c0.git_is_usable(), usable)
        with mock.patch.dict(os.environ, {"PATH": str(self.fake_git("garbage"))}):
            self.assertIsNone(c0.git_version())

    def test_repo_id_without_git_is_unavailable(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": str(self.fake_git(None))}):
            with self.assertRaises(c0.IdentityC0Error) as caught:
                c0.repo_id_for(".")
        self.assertEqual(caught.exception.code, "identity_repo_unavailable")

    def test_public_derivation_functions_require_str(self) -> None:
        for value in (None, 5, b"https://a.example/x", ["a"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "must be str"):
                    c0.normalize_remote(value)
                with self.assertRaisesRegex(TypeError, "must be str"):
                    c0.repo_id_from_remote(value, "/base")
                with self.assertRaisesRegex(TypeError, "must be str"):
                    c0.repo_id_from_common_dir(value)


class EnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = copy.deepcopy(load_vectors()["validos"][0]["objeto"])
        self.key = digest_json({"k": 1})

    def test_envelope_shape_and_injected_clock(self) -> None:
        clock = lambda: datetime(2026, 11, 14, 18, 30, 0, 123456, tzinfo=timezone.utc)
        envelope = c0.build_envelope(self.identity, "fact", self.key, clock)
        self.assertEqual(envelope, {
            "schema": "an-kla/record-envelope-v1",
            "writer": self.identity,
            "enqueued_at": "2026-11-14T18:30:00.123456Z",
            "time_source": "host-clock/v1",
            "idempotency_key": self.key,
            "kind": "fact",
        })
        self.assertEqual(c0.validate_envelope(envelope), [])

    def test_microseconds_are_always_six_digits_and_offsets_become_utc(self) -> None:
        zone = timezone(timedelta(hours=-6))
        stamp = c0.build_envelope(self.identity, "fact", self.key,
                                  lambda: datetime(2026, 1, 2, 3, 4, 5, 0, tzinfo=zone))["enqueued_at"]
        self.assertEqual(stamp, "2026-01-02T09:04:05.000000Z")

    def test_default_clock_is_the_utc_host_clock(self) -> None:
        before = datetime.now(timezone.utc)
        stamp = c0.build_envelope(self.identity, "fact", self.key)["enqueued_at"]
        parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        self.assertLessEqual(before.replace(microsecond=0), parsed)
        self.assertLessEqual(parsed, datetime.now(timezone.utc))

    def test_naive_clock_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            c0.build_envelope(self.identity, "fact", self.key, lambda: datetime(2026, 1, 1))

    def test_envelope_does_not_alias_the_identity(self) -> None:
        envelope = c0.build_envelope(self.identity, "fact", self.key)
        envelope["writer"]["agent"]["name"] = "otro"
        self.assertNotEqual(self.identity["agent"]["name"], "otro")

    def test_invalid_inputs_are_refused(self) -> None:
        broken = copy.deepcopy(self.identity)
        broken["agent"]["role"] = "jefe"
        for label, args in (
            ("identity violating C0", (broken, "fact", self.key)),
            ("kind with uppercase", (self.identity, "Fact", self.key)),
            ("empty kind", (self.identity, "", self.key)),
            ("non-string kind", (self.identity, 3, self.key)),
            ("key without prefix", (self.identity, "fact", "a" * 64)),
            ("key with short digest", (self.identity, "fact", "sha256:abc")),
        ):
            with self.subTest(label), self.assertRaises(ValueError):
                c0.build_envelope(*args)

    def test_validate_envelope_reasons(self) -> None:
        good = c0.build_envelope(self.identity, "fact", self.key)
        for label, mutate, reason in (
            ("extra key", lambda e: e.update(extra=1), "claves_raiz"),
            ("schema", lambda e: e.update(schema="an-kla/record-envelope-v2"), "schema"),
            ("writer role", lambda e: e["writer"]["agent"].update(role="jefe"), "writer:agent_role"),
            ("no microseconds", lambda e: e.update(enqueued_at="2026-11-14T18:30:00Z"), "enqueued_at"),
            ("impossible date", lambda e: e.update(enqueued_at="2026-13-14T18:30:00.000000Z"), "enqueued_at"),
            ("non-utc offset", lambda e: e.update(enqueued_at="2026-11-14T18:30:00.000000+01:00"), "enqueued_at"),
            ("time source", lambda e: e.update(time_source="ntp/v1"), "time_source"),
            ("key", lambda e: e.update(idempotency_key="sha256:x"), "idempotency_key"),
            ("kind", lambda e: e.update(kind="Fact"), "kind"),
        ):
            with self.subTest(label):
                envelope = copy.deepcopy(good)
                mutate(envelope)
                self.assertIn(reason, c0.validate_envelope(envelope))
        self.assertEqual(c0.validate_envelope(None), ["raiz_no_es_objeto"])
        broken = copy.deepcopy(good)
        broken["writer"] = "no es un objeto"
        self.assertEqual(c0.validate_envelope(broken), ["writer:raiz_no_es_objeto"])

    def test_default_idempotency_key_follows_the_adr_formula(self) -> None:
        key = c0.derive_idempotency_key(self.identity, "fact", "texto")
        formula = digest_json({"repo": self.identity["repo"]["id"], "agent": self.identity["agent"]["name"],
                               "session": self.identity["session"]["id"], "kind": "fact",
                               "text": "texto", "supersedes": None})
        self.assertEqual(key, formula)
        self.assertNotEqual(key, c0.derive_idempotency_key(self.identity, "fact", "texto", "f-1"))
        self.assertNotEqual(c0.derive_idempotency_key(self.identity, "fact", "texto", "f-1"),
                            c0.derive_idempotency_key(self.identity, "fact", "texto", "f-2"))
        self.assertNotEqual(key, c0.derive_idempotency_key(self.identity, "decision", "texto"))


class EnvelopeSchemaTests(unittest.TestCase):
    def test_schema_is_registered_and_mirrored(self) -> None:
        self.assertIn("record-envelope-v1", schema_names())
        entry = next(i for i in schema_catalog()["schemas"] if i["name"] == "record-envelope-v1")
        self.assertEqual(entry["id"], "urn:an-kla:schema:record-envelope:v1")
        mirror = (ROOT / "docs" / "schemas" / "record-envelope-v1.schema.json").read_bytes()
        self.assertEqual(schema_bytes("record-envelope-v1"), mirror)

    def test_schema_is_closed_at_every_level(self) -> None:
        document = schema_document("record-envelope-v1")
        self.assertIs(document["additionalProperties"], False)
        defs = document["$defs"]["identity"]
        self.assertIs(defs["additionalProperties"], False)
        for part in ("repo", "agent", "session"):
            self.assertIs(defs["properties"][part]["additionalProperties"], False)

    def validator(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        return Draft202012Validator(schema_document("record-envelope-v1"))

    def test_schema_accepts_what_the_builder_produces(self) -> None:
        validator = self.validator()
        key = digest_json({"k": 1})
        for case in load_vectors()["validos"]:
            with self.subTest(case["nombre"]):
                envelope = c0.build_envelope(case["objeto"], "fact", key)
                self.assertEqual(list(validator.iter_errors(envelope)), [])

    def test_schema_rejects_the_structural_invalid_vectors(self) -> None:
        validator = self.validator()
        key = digest_json({"k": 1})
        # Reasons the grammar can express; the rest (cli/session prefix match) is the validator's job.
        structural = {"claves_raiz", "schema", "repo_forma", "repo_id", "repo_branch", "agent_forma", "agent_name",
                      "agent_name_reservado", "agent_cli", "agent_model", "agent_role", "session_forma", "session_id"}
        rejected = 0
        for case in load_vectors()["invalidos"]:
            if case["motivo"] not in structural or not isinstance(case["objeto"], dict):
                continue
            envelope = {"schema": "an-kla/record-envelope-v1", "writer": case["objeto"],
                        "enqueued_at": "2026-11-14T18:30:00.000000Z", "time_source": "host-clock/v1",
                        "idempotency_key": key, "kind": "fact"}
            with self.subTest(case["nombre"]):
                self.assertNotEqual(list(validator.iter_errors(envelope)), [])
                rejected += 1
        self.assertGreater(rejected, 20)


NODE = shutil.which("node")
# Runs each pattern the way an ECMA-262 engine would (no `u` flag) over the cases.
NODE_SCRIPT = (
    "const d = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
    "const re = d.patterns.map(p => new RegExp(p));"
    "process.stdout.write(d.cases.map(([i, s]) => re[i].test(s) ? '1' : '0').join(''));"
)


def schema_patterns(node: object) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "pattern" and isinstance(value, str):
                found.append(value)
            else:
                found += schema_patterns(value)
    elif isinstance(node, list):
        for item in node:
            found += schema_patterns(item)
    return found


class WhitespaceAgreementTests(unittest.TestCase):
    """R1-01: the validator and the published schema accept and reject the same whitespace."""

    SPACES = ("\u2003", "\u0085", "\x1c", "\xa0", "\u3000", "\u2028", "\t")

    def setUp(self) -> None:
        self.identity = copy.deepcopy(load_vectors()["validos"][0]["objeto"])

    def with_fields(self, **fields: str) -> dict:
        identity = copy.deepcopy(self.identity)
        if "model" in fields:
            identity["agent"]["model"] = fields["model"]
        if "branch" in fields:
            identity["repo"]["branch"] = fields["branch"]
        if "session" in fields:
            identity["session"]["id"] = f"{identity['agent']['cli']}:{fields['session']}"
        return identity

    def test_validator_rejects_unicode_spaces(self) -> None:
        for char in self.SPACES:
            with self.subTest(char=repr(char)):
                self.assertIn("agent_model", c0.validate(self.with_fields(model=char + "m")))
                self.assertIn("agent_model", c0.validate(self.with_fields(model="m" + char)))
                self.assertIn("repo_branch", c0.validate(self.with_fields(branch="a" + char + "b")))
                self.assertIn("session_id", c0.validate(self.with_fields(session="a" + char + "b")))
        # Interior whitespace of a model is allowed (only the ends are constrained).
        self.assertEqual(c0.validate(self.with_fields(model="a\u2003b")), [])
        self.assertEqual(c0.validate(self.with_fields(model="a b")), [])

    def test_whitespace_class_is_exactly_python_s_over_the_whole_unicode_range(self) -> None:
        import re
        explicit = re.compile(f"[{c0.WHITESPACE_CLASS}]")
        builtin = re.compile(r"\s")
        wrong = [hex(code) for code in range(0x110000)
                 if (explicit.fullmatch(chr(code)) is None) != (builtin.fullmatch(chr(code)) is None)]
        self.assertEqual(wrong, [])
        self.assertEqual([hex(c) for c in range(0x110000) if chr(c).isspace() != (explicit.fullmatch(chr(c)) is not None)], [])

    def test_length_bounds_count_code_points_in_the_validator(self) -> None:
        # Documented residual (ORIGEN.md): a schema engine counting UTF-16 units would reject these.
        astral = "\U0001d54f"
        self.assertEqual(c0.validate(self.with_fields(branch=astral * 200)), [])
        self.assertEqual(c0.validate(self.with_fields(model=astral * 80)), [])
        self.assertIn("repo_branch", c0.validate(self.with_fields(branch=astral * 201)))
        self.assertIn("agent_model", c0.validate(self.with_fields(model=astral * 81)))

    def test_bom_is_accepted_like_the_reference_does(self) -> None:
        # U+FEFF is not whitespace for Python's `\s`, which is what the C0 reference validator uses.
        self.assertEqual(c0.validate(self.with_fields(model="\ufeffmodelo")), [])
        self.assertEqual(c0.validate(self.with_fields(model="modelo\ufeff")), [])
        self.assertEqual(c0.validate(self.with_fields(branch="a\ufeffb")), [])
        self.assertEqual(c0.validate(self.with_fields(session="a\ufeffb")), [])
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            return
        validator = Draft202012Validator(schema_document("record-envelope-v1"))
        for fields in ({"model": "\ufeffmodelo"}, {"branch": "a\ufeffb"}, {"session": "a\ufeffb"}):
            envelope = c0.build_envelope(self.with_fields(**fields), "fact", digest_json({"k": 1}))
            self.assertEqual(list(validator.iter_errors(envelope)), [])

    def test_schema_has_no_engine_dependent_classes(self) -> None:
        for pattern in schema_patterns(schema_document("record-envelope-v1")):
            with self.subTest(pattern=pattern[:60]):
                stripped = pattern.replace(r"[\s\S]", "")
                self.assertNotIn(r"\s", stripped)
                self.assertNotIn(r"\S", stripped)
                self.assertNotIn("$", stripped)

    def test_schema_rejects_what_the_validator_rejects_with_python_jsonschema(self) -> None:
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        validator = Draft202012Validator(schema_document("record-envelope-v1"))
        key = digest_json({"k": 1})

        def errors(writer: dict, **overrides: str) -> list:
            envelope = {"schema": "an-kla/record-envelope-v1", "writer": writer,
                        "enqueued_at": "2026-11-14T18:30:00.000000Z", "time_source": "host-clock/v1",
                        "idempotency_key": key, "kind": "fact", **overrides}
            return list(validator.iter_errors(envelope))

        for char in self.SPACES:
            for field in ("model", "branch", "session"):
                with self.subTest(char=repr(char), field=field):
                    value = char + "m" if field == "model" else "a" + char + "b"
                    self.assertNotEqual(errors(self.with_fields(**{field: value})), [])
        # `$` would let Python engines accept a final newline.
        self.assertNotEqual(errors(self.identity, kind="fact\n"), [])
        self.assertNotEqual(errors(self.identity, enqueued_at="2026-11-14T18:30:00.000000Z\n"), [])
        self.assertNotEqual(errors(self.identity, idempotency_key=key + "\n"), [])
        self.assertNotEqual(errors(self.with_fields(session="abc\n")), [])

    @unittest.skipUnless(NODE, "node not available: the ECMA-262 agreement check needs a real ECMA engine")
    def test_ecma_engine_agrees_with_the_validator_on_every_bmp_character(self) -> None:
        document = schema_document("record-envelope-v1")
        defs = document["$defs"]
        patterns = [
            defs["branch"]["pattern"],
            defs["identity"]["properties"]["session"]["properties"]["id"]["pattern"],
            defs["identity"]["properties"]["agent"]["properties"]["model"]["pattern"],
        ]
        cases, expected = [], []
        for code in range(0x10000):
            if 0xD800 <= code <= 0xDFFF:
                continue
            char = chr(code)
            cases += [[0, "a" + char], [1, "claude-code:" + char], [2, char + "b"], [2, "a" + char + "b"]]
            expected += [
                c0._BRANCH.fullmatch("a" + char) is not None,
                c0._SESSION.fullmatch("claude-code:" + char) is not None,
                c0._NO_OUTER_SPACE.fullmatch(char + "b") is not None,
                c0._NO_OUTER_SPACE.fullmatch("a" + char + "b") is not None,
            ]
        done = subprocess.run([NODE, "-e", NODE_SCRIPT], input=json.dumps({"patterns": patterns, "cases": cases}),
                              capture_output=True, text=True, check=True, timeout=60)
        actual = [c == "1" for c in done.stdout]
        self.assertEqual(len(actual), len(expected))
        wrong = [cases[i] for i, (a, e) in enumerate(zip(actual, expected)) if a != e]
        self.assertEqual(wrong, [], f"ECMA engine disagrees with the validator on {len(wrong)} cases")


if __name__ == "__main__":
    unittest.main()
