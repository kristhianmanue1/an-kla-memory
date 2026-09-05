"""test_sealed_key_adapter_behavior.py — partición de tests/test_sealed_key_adapter.py por unidad bajo prueba (beta.22, issue #106).

Casos y aserciones sin cambios; el prelude (imports y helpers de módulo) se
copia del archivo de origen para mantener cada archivo autocontenido.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from an_kla.sealed import key_adapter as ka
from an_kla.sealed.key_adapter import (
    ADAPTER_STDERR_LIMIT,
    ADAPTER_STDOUT_LIMIT,
    ADAPTER_TIMEOUT_SECONDS,
    ADAPTER_WRAPPED_CEK_MAX_CHARS,
    SealingAdapterError,
    SealingAdapterRequiredError,
    SealingAdapterRunner,
)

TESTS_DIR = Path(__file__).resolve().parent
ADAPTERS_DIR = TESTS_DIR / "adapters"
REFERENCE_ADAPTER = ADAPTERS_DIR / "file_key_adapter.py"

ENV_KEY_FILE = "ANKLA_TEST_ADAPTER_KEY_FILE"
ENV_VERBOSE = "ANKLA_TEST_ADAPTER_VERBOSE"
ENV_PRINT_ENV = "ANKLA_TEST_ADAPTER_PRINT_ENV"

# Señuelo único: si ESTE texto aparece en un mensaje del core, stderr se
# propagó (violación directa del ADR §4).
STDERR_CANARY = "Zk7-canary-stderr-NEVER-propagate-9qXd"


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _write_key_file(directory: Path) -> Path:
    """Archivo de llave del adaptador de referencia: 32 bytes hex."""
    path = directory / f"key-{secrets.token_hex(4)}.hex"
    path.write_bytes(secrets.token_hex(32).encode("ascii"))
    return path


def _reference_runner(key_file: Path, **kwargs) -> SealingAdapterRunner:
    kwargs.setdefault("env_allowlist", [ENV_KEY_FILE])
    return SealingAdapterRunner(
        [sys.executable, str(REFERENCE_ADAPTER)],
        **kwargs,
    )


class _AdHocAdapter:
    """Escribe un adaptador Python de un solo archivo en un tmp dir."""

    def __init__(self, testcase, body: str, *, argv_prefix=None):
        # TestCase.enterContext llegó en 3.11; el CLT python3 de la matriz
        # es 3.9 — compatibilidad explícita con addCleanup.
        tmp = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp.cleanup)
        base = tmp.name
        self.path = Path(base) / "adhoc_adapter.py"
        self.path.write_text(textwrap.dedent(body), encoding="utf-8")
        self.argv = list(argv_prefix or [sys.executable, str(self.path)])
        # hereda env del runner: none needed
        self.env_allowlist = []

    def runner(self, **kwargs) -> SealingAdapterRunner:
        return SealingAdapterRunner(self.argv, env_allowlist=self.env_allowlist, **kwargs)


# ---------------------------------------------------------------------------
# 1. Roundtrip completo vía runner (adaptador de referencia, stdlib)
# ---------------------------------------------------------------------------


class TestStderrNeverPropagated(unittest.TestCase):
    def _stderr_canary_cases(self):
        return [
            ("exit-nonzero", "raise SystemExit(2)"),
            ("crash", "raise RuntimeError('boom')"),
            ("garbage", "import sys; sys.stdout.write('not-json')"),
        ]

    def test_stderr_canary_absent_from_all_error_messages(self):
        """El señuelo de stderr no aparece en NINGÚN mensaje de error."""
        for label, tail in self._stderr_canary_cases():
            with self.subTest(case=label):
                adapter = _AdHocAdapter(
                    self,
                    f"""
                    import sys
                    sys.stdin.read(65536)
                    sys.stderr.write("{STDERR_CANARY}\\n")
                    {tail}
                    """,
                )
                with self.assertRaises(SealingAdapterError) as ctx:
                    adapter.runner(timeout_seconds=15.0).unwrap_cek(
                        "A" * 88
                    )
                self.assertNotIn(STDERR_CANARY, str(ctx.exception))
                self.assertEqual(
                    ctx.exception.args[0],
                    "sealing key adapter failed (no further detail)",
                )

    def test_error_messages_are_closed_enum(self):
        """Los mensajes del runner son un conjunto cerrado, sin detalle."""
        allowed = {
            "sealing key adapter failed (no further detail)",
            "sealing key adapter timed out (no further detail)",
            "sealing key adapter exceeded i/o limits (no further detail)",
        }
        messages = {
            ka._ADAPTER_ERROR_MSG,
            ka._ADAPTER_TIMEOUT_MSG,
            ka._ADAPTER_IO_LIMIT_MSG,
        }
        self.assertLessEqual(messages, allowed)

    def test_reference_adapter_verbose_mode_clean(self):
        """Modo verbose del adaptador de referencia: contrato intacto."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key_file = _write_key_file(Path(tmp.name))
        os.environ[ENV_KEY_FILE] = str(key_file)
        os.environ[ENV_VERBOSE] = "1"
        self.addCleanup(os.environ.pop, ENV_KEY_FILE, None)
        self.addCleanup(os.environ.pop, ENV_VERBOSE, None)
        runner = _reference_runner(key_file, env_allowlist=[ENV_KEY_FILE, ENV_VERBOSE])
        cek = os.urandom(32)
        wrapped = runner.wrap_cek(cek)
        self.assertEqual(runner.unwrap_cek(wrapped.wrapped_cek).cek, cek)


# ---------------------------------------------------------------------------
# 9. Entorno mínimo con allowlist (F3)
# ---------------------------------------------------------------------------


class TestEnvironmentAllowlist(unittest.TestCase):
    """Una NO-allowlisted NO llega; una allowlisted SÍ llega."""

    PARENT_SECRET = "ANKLA_T3_PARENT_SECRET"
    PARENT_ALLOWED = "ANKLA_T3_ALLOWED_TOKEN"
    CHILD_SEEN = "ANKLA_T3_CHILD_SAW"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.seen_path = Path(self._tmp.name) / "env_seen.json"

    def _env_probe_runner(self, env_allowlist):
        """Adaptador que vuelca su entorno a un ARCHIVO (el hecho observable
        fuera de stdio, porque stderr se descarta por diseño)."""
        target = str(self.seen_path)
        adapter = _AdHocAdapter(
            self,
            f"""
            import base64, json, os, sys
            sys.stdin.read(65536)
            raw = os.environ.get({self.PARENT_SECRET!r})
            raw2 = os.environ.get({self.PARENT_ALLOWED!r})
            with open({target!r}, "w") as fh:
                json.dump({{"secret_seen": raw is not None,
                            "allowed_seen": raw2 is not None,
                            "all_keys": sorted(os.environ)}}, fh)
            sys.stdout.write(json.dumps(
                {{"cek_b64": base64.b64encode(b"p" * 32).decode()}}))
            """,
        )
        return SealingAdapterRunner(
            adapter.argv, env_allowlist=env_allowlist, timeout_seconds=15.0
        )

    def test_parent_secret_does_not_reach_adapter(self):
        os.environ[self.PARENT_SECRET] = "super-secret-value-xyz"
        self.addCleanup(os.environ.pop, self.PARENT_SECRET, None)
        runner = self._env_probe_runner(env_allowlist=[])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        self.assertFalse(seen["secret_seen"])
        self.assertNotIn(self.PARENT_SECRET, seen["all_keys"])

    def test_allowlisted_variable_reaches_adapter(self):
        os.environ[self.PARENT_ALLOWED] = "allowed-value-123"
        os.environ[self.PARENT_SECRET] = "super-secret-value-xyz"
        self.addCleanup(os.environ.pop, self.PARENT_ALLOWED, None)
        self.addCleanup(os.environ.pop, self.PARENT_SECRET, None)
        runner = self._env_probe_runner(env_allowlist=[self.PARENT_ALLOWED])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        self.assertTrue(seen["allowed_seen"])
        # Y SOLO la allowlisted: la secreta sigue fuera.
        self.assertFalse(seen["secret_seen"])

    def test_no_allowlist_means_no_extra_vars(self):
        """Sin allowlist: sólo PATH/LANG/LC_ALL (mínimo del runner)."""
        os.environ[self.PARENT_SECRET] = "super-secret-value-xyz"
        os.environ[self.PARENT_ALLOWED] = "allowed-value-123"
        self.addCleanup(os.environ.pop, self.PARENT_SECRET, None)
        self.addCleanup(os.environ.pop, self.PARENT_ALLOWED, None)
        runner = self._env_probe_runner(env_allowlist=[])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        # Windows: el runner añade vars de runtime del SO (SystemRoot etc.)
        # para que el proceso hijo pueda inicializar — no son datos del host.
        platform_runtime = (
            {"SystemRoot", "SYSTEMROOT", "SystemDrive", "COMSPEC"}
            if os.name == "nt"
            else set()
        )
        self.assertLessEqual(
            set(seen["all_keys"]),
            {"PATH", "LANG", "LC_ALL", "TMPDIR", "HOME", "__CF_USER_TEXT_ENCODING"}
            | platform_runtime,
        )

    def test_allowlisted_missing_in_parent_is_absent(self):
        """Allowlisted que NO existe en el padre: no se crea de la nada."""
        runner = self._env_probe_runner(env_allowlist=["ANKLA_T3_NONEXISTENT"])
        runner.unwrap_cek("A" * 88)
        seen = json.loads(self.seen_path.read_text())
        self.assertNotIn("ANKLA_T3_NONEXISTENT", seen["all_keys"])

    def test_reference_adapter_requires_key_file_env(self):
        """El adaptador de referencia falla cerrado sin su env allowlisted.

        Sin env_allowlist, la variable no llega → error de contrato del
        adaptador → sealing_adapter_error en el core.
        """
        key_file = _write_key_file(Path(self._tmp.name))
        os.environ[ENV_KEY_FILE] = str(key_file)
        self.addCleanup(os.environ.pop, ENV_KEY_FILE, None)
        runner = SealingAdapterRunner(
            [sys.executable, str(REFERENCE_ADAPTER)], timeout_seconds=15.0
        )
        with self.assertRaises(SealingAdapterError):
            runner.wrap_cek(os.urandom(32))


# ---------------------------------------------------------------------------
# 10. sealing_adapter_required — borde caller
# ---------------------------------------------------------------------------


class TestAdapterRequired(unittest.TestCase):
    def test_none_command_raises_required(self):
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner(None)

    def test_empty_list_raises_required(self):
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner([])

    def test_string_command_rejected_not_shell(self):
        """Una línea de shell como string se RECHAZA: argv estructurado.

        Jamás ``sh -c``; aceptar una string sería invitar a interpolación.
        """
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner("echo adapter")

    def test_non_string_elements_rejected(self):
        with self.assertRaises(SealingAdapterRequiredError):
            SealingAdapterRunner([sys.executable, 12345])

    def test_required_error_code_canonical(self):
        self.assertEqual(
            SealingAdapterRequiredError.ERROR_CODE, "sealing_adapter_required"
        )
        self.assertEqual(
            ka.SEALING_ADAPTER_REQUIRED_CODE, "sealing_adapter_required"
        )

    def test_nonexistent_executable_is_adapter_error(self):
        """Ejecutable inexistente: error del ADAPTADOR (se ejecutó el borde),
        no del caller — ADR §4: falla/crash → sealing_adapter_error."""
        runner = SealingAdapterRunner(
            ["/nonexistent/ankla-t3-adapter-binary"], timeout_seconds=10.0
        )
        with self.assertRaises(SealingAdapterError) as ctx:
            runner.wrap_cek(os.urandom(32))
        self.assertNotIn("/nonexistent", str(ctx.exception))


# ---------------------------------------------------------------------------
# 11. wrapped_cek opaco + pre-vuelo por schema
# ---------------------------------------------------------------------------


class TestWrappedCekOpacity(unittest.TestCase):
    def test_pre_flight_max_chars_enforced(self):
        self.assertEqual(ADAPTER_WRAPPED_CEK_MAX_CHARS, 4096)
        adapter = _AdHocAdapter(
            self,
            """
            import sys
            sys.stdin.read(65536)
            sys.stdout.write('{"cek_b64": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}')
            """,
        )
        runner = adapter.runner(timeout_seconds=10.0)
        # Entrada al unwrap mayor que el techo → error ANTES de ejecutar.
        too_long = "A" * (ADAPTER_WRAPPED_CEK_MAX_CHARS + 1)
        with self.assertRaises(SealingAdapterError):
            runner.unwrap_cek(too_long)

    def test_runner_does_not_interpret_blob(self):
        """El blob viaja tal cual; el adaptador decide su forma.

        Un adaptador ad-hoc acepta CUALQUIER blob opaco y devuelve CEK
        fija: el core no inspecciona el contenido del blob (solo techo).
        """
        adapter = _AdHocAdapter(
            self,
            """
            import base64, sys
            req = sys.stdin.read(65536)
            assert '"op": "unwrap"' in req or '"op":"unwrap"' in req
            sys.stdout.write('{"cek_b64": "'
                + base64.b64encode(b"k" * 32).decode() + '"}')
            """,
        )
        runner = adapter.runner(timeout_seconds=10.0)
        # b64 canónico de 32 bytes arbitrarios: canonicidad validada, pero
        # el CONTENIDO decodificado jamás se interpreta (opacidad intacta).
        import base64 as _b64

        opaque = _b64.b64encode(b"\x00\xffopaque-contents\xfe\x00" + b"Z" * 16).decode()
        result = runner.unwrap_cek(opaque)
        self.assertEqual(result.cek, b"k" * 32)

    def test_wrap_output_above_ceiling_rejected(self):
        adapter = _AdHocAdapter(
            self,
            """
            import sys
            sys.stdin.read(65536)
            sys.stdout.write('{"adapter_id": "a.b", "wrapped_cek": "'
                + "B" * 5000 + '"}')
            """,
        )
        with self.assertRaises(SealingAdapterError):
            adapter.runner(timeout_seconds=10.0).wrap_cek(os.urandom(32))

    def test_input_cek_must_be_32_bytes(self):
        """CEK de entrada con longitud errónea: ValueError de contrato del
        CALLER (pre-vuelo, sin ejecutar el adaptador)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key_file = _write_key_file(Path(tmp.name))
        runner = _reference_runner(key_file)
        with self.assertRaises(ValueError):
            runner.wrap_cek(b"short")
        with self.assertRaises(ValueError):
            runner.wrap_cek(b"x" * 33)
        with self.assertRaises(ValueError):
            runner.wrap_cek("not-bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 12. Sin cryptography: import + independencia del flag
# ---------------------------------------------------------------------------


class TestNoCryptographyIndependence(unittest.TestCase):
    """El runner es stdlib pura: nada acopla a sealed_available."""

    def _run_blocked(self, code: str) -> subprocess.CompletedProcess:
        """Subproceso con cryptography BLOQUEADO vía meta-path."""
        blocker = textwrap.dedent(
            """
            import sys
            class _Block:
                def find_spec(self, name, path=None, target=None):
                    if name == 'cryptography' or name.startswith(
                            'cryptography.'):
                        raise ImportError('blocked for test')
                    return None
            sys.meta_path.insert(0, _Block())
            """
        )
        return subprocess.run(
            [sys.executable, "-c", blocker + textwrap.dedent(code)],
            capture_output=True,
            text=True,
            cwd=str(TESTS_DIR.parent),
        )

    def test_key_adapter_importable_without_extra(self):
        result = self._run_blocked(
            """
            import sys
            from an_kla.sealed import key_adapter
            assert 'cryptography' not in sys.modules
            assert key_adapter.SEALING_ADAPTER_ERROR_CODE == 'sealing_adapter_error'
            """
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_runner_errors_independent_of_availability_flag(self):
        """Con sealed_available mentido a True y sin cryptography real,
        el runner sigue operando igual: el flag no acopla nada."""
        result = self._run_blocked(
            """
            import an_kla.sealed as s
            from an_kla.sealed import key_adapter
            s.sealed_available = True  # mentira deliberada (nota T1)
            r = key_adapter.SealingAdapterRunner(
                ['/nonexistent/ankla-t3-adapter'])
            try:
                r.wrap_cek(b'k' * 32)
            except key_adapter.SealingAdapterError:
                pass
            else:
                raise AssertionError('runner debio fallar cerrado')
            try:
                key_adapter.SealingAdapterRunner(None)
            except key_adapter.SealingAdapterRequiredError:
                pass
            else:
                raise AssertionError('required esperado')
            """
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_sealed_package_importable_without_extra(self):
        """import an_kla.sealed (con el wiring T3) exit 0 sin cryptography."""
        result = self._run_blocked(
            """
            import sys
            import an_kla.sealed as s
            assert 'cryptography' not in sys.modules
            assert s.SEALING_ADAPTER_ERROR_CODE == 'sealing_adapter_error'
            assert s.SealingAdapterRunner is not None
            """
        )
        self.assertEqual(result.returncode, 0,
                         msg=f"stderr: {result.stderr}\nstdout: {result.stdout}")

    def test_no_cryptography_import_in_key_adapter(self):
        """grep estructural: key_adapter jamás importa cryptography."""
        source = ka.__file__
        text = Path(source).read_text(encoding="utf-8")
        self.assertNotIn("import cryptography", text)


# ---------------------------------------------------------------------------
# 13. Higiene: argv estructurado / sin shell
# ---------------------------------------------------------------------------


class TestNoShellExecution(unittest.TestCase):
    def test_no_shell_metacharacter_interpretation(self):
        """Metacaracteres de shell en un arg NO se interpretan JAMÁS.

        Si el runner usara shell, ``;`` ejecutaría el segundo comando y
        el archivo señuelo aparecería. Con argv estructurado, el archivo
        con nombre malicioso simplemente NO existe (OSError → error).
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        canary = Path(tmp.name) / "canary.txt"
        evil = f"/usr/bin/touch;touch {canary}"
        runner = SealingAdapterRunner([evil], timeout_seconds=10.0)
        with self.assertRaises(SealingAdapterError):
            runner.wrap_cek(os.urandom(32))
        self.assertFalse(canary.exists())

    def test_arguments_passed_verbatim(self):
        """Args con espacios/comillas llegan ÍNTEGROS al adaptador."""
        magic = "arg with 'quotes' and $shell and \\backslash"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        seen = Path(tmp.name) / "argv.json"
        adapter = _AdHocAdapter(
            self,
            f"""
            import base64, json, sys
            sys.stdin.read(65536)
            json.dump(sys.argv[1:], open({str(seen)!r}, "w"))
            sys.stdout.write(json.dumps(
                {{"cek_b64": base64.b64encode(b"p" * 32).decode()}}))
            """,
            argv_prefix=None,
        )
        runner = SealingAdapterRunner(
            [sys.executable, str(adapter.path), magic], timeout_seconds=10.0
        )
        runner.unwrap_cek("A" * 88)
        self.assertEqual(json.loads(seen.read_text()), [magic])

    def test_reference_adapter_documented_not_production(self):
        """El adaptador de referencia declara NO-producción en su fuente."""
        text = REFERENCE_ADAPTER.read_text(encoding="utf-8")
        self.assertIn("NO-producción".upper().replace("Ó", "O"), text.upper().replace("Ó", "O"))


# ---------------------------------------------------------------------------
# 14. adapter_id: gramática cerrada (ADR §6)
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
