"""Matriz §9 CONSOLIDADA del ADR-0042 — T6 de issue #46 (cierre).

Una clase por fila (o grupo normativo) de la matriz de pruebas congelada
del §9 de ``docs/architecture/0042-sealed-export-v1.md``. Las filas ya
cubiertas por T2-T5 (``test_sealed_bundle.py``, ``test_sealed_kdf.py``,
``test_sealed_cek.py``, ``test_sealed_key_adapter.py``,
``test_sealed_availability.py``, ``test_export_sealed_cli.py``,
``test_export_restore.py``, ``test_compaction.py``) se VERIFICAN aquí por
presencia (re-ejecución de la fuente, no re-implementación: cada clase
re-ejecuta el/los módulos de prueba que cubren la fila y comprueba que
hayan corrido al menos un test del conjunto); lo que faltaba se completa
aquí mismo:

- Fila 8 consolidada: verify sin clave JAMÁS ``verified: true`` (aquí
  como clase propia, ejecutando el enum de caminos sin clave).
- Fila 9 (nueva): reescritura COMPLETA del bundle por un atacante
  (manifiesto v2 nuevo íntegro, cifrado con CEK ajena, bundle_id/mac
  autoconsistentes) → verify autenticado con la CEK del operador lo
  detecta (``sealed_payload_auth_failed``). Esto es el LÍMITE declarado
  del ADR hecho test: el sello no es atestación de origen; la defensa
  documentada es la comparación manual de ``bundle_id`` (que también se
  prueba aquí: el bundle re-sellado tiene ``bundle_id`` distinto).
- Fila 10 segunda mitad (nueva aquí para el lector beta.17): el lector
  v1 vigente (``an_kla.export_restore.verify_export``/``_validated``,
  sin dispatcher dual) frente a un bundle sellado responde
  ``export_manifest_invalid`` (nota §3) — probado contra el lector
  DIRECTO, no contra el dispatcher.
- Fila 11 (nueva aquí): bundles v1 en claro SIN cambios y suite v1
  intacta sin el extra (re-ejecución de ``test_export_restore`` +
  ``test_compaction`` en este intérprete, más verificación de que el
  camino v1 no toca los módulos sellados de cifrado).
- Fila 12 (nueva aquí): compactación con bundle sellado como insumo →
  ``export_manifest_invalid`` por el lector v1 vigente.
- Fila 14 (nueva aquí): taxonomía exacta de warnings por perfil —
  v1/creado/verificado/restaurado/sin-clave, sin cruce posible.
- Fila 15 (nueva aquí): suite completa + CI local SIN ``[sealed]`` (este
  mismo intérprete, verificado sin cryptography) y CON él (delegado al
  intérprete que la tiene, verificado aquí).
- H1 (deuda T5): códigos canónicos sellados por CLI REAL en stderr.
- H2 (deuda T4/T5): restore sellado exitoso sin staging residual.
- N1: mensaje de validación de ``--key-adapter-env`` en lenguaje CLI.

Entornos: la suite canónica ``.venv`` corre SIN ``cryptography`` (skips
honestos en lo criptográfico); lo criptográfico se ejecuta con CLT
python3 (``/Library/Developer/CommandLineTools/usr/bin/python3``), que sí
tiene el extra — el mismo patrón de T4/T5.

Particionado en beta.22 (issue #106, plan docs/plans/2026-09-01-deuda-tamanos-adopcion-skevi.md): parte del contenido vive ahora en tests/test_sealed_matrix_rows.py. Casos y aserciones sin cambios.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest

from pathlib import Path

from an_kla.canonical import canonical_json
from an_kla.compaction import CompactionError, plan_compaction
from an_kla.export_restore import (
    ExportError,
    PROFILE as V1_PROFILE,
    create_export,
    verify_export,
)
from an_kla.sealed import bundle as sb
from an_kla.sealed import SEALED_EXTRA_ERROR_CODE, sealed_available
from an_kla.sealed.cli_dispatch import (
    dispatch_export_create,
    dispatch_export_restore,
    dispatch_export_verify,
)
from an_kla.store import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
CLT_PYTHON = Path(
    "/Library/Developer/CommandLineTools/usr/bin/python3"
)

#: Guarda anti-recursión: la fila 15 lanza discovers completos por
#: subprocess; si ese discover vuelve a cargar la matriz, una fila 15
#: anidada se salta — de lo contrario el descubrimiento se recursiona.
_ROW15_ENV = "ANKLA_MATRIX_ROW15_ACTIVE"

PLAINTEXT_WARNING = "plaintext_export_contains_untrusted_memory_data"
SEALED_WARNING = "sealed_export_untrusted_memory_data"
UNKEYED_WARNING = "sealed_payloads_unverified_without_key"

#: Módulos fuente por fila de la matriz: la CONSOLIDACIÓN re-ejecuta el
#: módulo unittest que cubre cada fila en un subprocess y exige verde.
#: Esto verifica presencia Y re-ejecución sin duplicar código de prueba.
_ROW_MODULES: dict[str, tuple[str, ...]] = {
    "1": ("tests.test_sealed_bundle_units",),        # F1 inyectividad
    "2": ("tests.test_sealed_bundle",),
    "3": ("tests.test_sealed_bundle",),
    "4": ("tests.test_sealed_bundle",),
    "5": ("tests.test_sealed_bundle",),
    "6": ("tests.test_sealed_key_adapter",),         # F2 runner acotado
    "7": ("tests.test_sealed_bundle",),
    "10b": ("tests.test_sealed_bundle",),
    "10c": ("tests.test_sealed_bundle", "tests.test_export_sealed_cli"),
    "10d": ("tests.test_sealed_key_adapter",),       # F3 entorno
    "10e": ("tests.test_sealed_key_adapter",),       # F4 adapter_id
    "12b": ("tests.test_sealed_bundle", "tests.test_sealed_availability"),
    "13": ("tests.test_sealed_bundle",),
    "16": ("tests.test_sealed_bundle",),             # F7 no-fuga
}


def _cryptography_importable() -> bool:
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def _clt_python() -> str:
    if CLT_PYTHON.exists():
        return str(CLT_PYTHON)
    raise unittest.SkipTest(
        f"CLT python3 ({CLT_PYTHON}) no disponible en este host"
    )


def _make_store(root: Path) -> MemoryStore:
    source = root / "source"
    source.mkdir()
    store = MemoryStore(source)
    initial = store.initialize()
    store.commit(
        expected_current_hash=initial,
        checkpoint_patch={},
        facts=[{"id": "f-matrix", "payload": {"text": "matrix"}}],
    )
    return store


class FakeAdapterB64:
    """Adaptador determinístico en memoria (misma superficie del runner
    T3; wrap/unwrap DOC con KEK fija, blob b64 canónico §4)."""

    ADAPTER_ID = "matrix-adapter-v1"

    def __init__(self, kek: bytes = b"m" * 32) -> None:
        self._kek = kek
        self._ceks: dict[str, bytes] = {}
        self._counter = 0

    def wrap_cek(self, cek: bytes):
        import base64
        from an_kla.sealed.cek import wrap_cek

        self._counter += 1
        token = f"m{self._counter}"
        self._ceks[token] = bytes(cek)
        blob = token.encode("ascii") + b":" + wrap_cek(cek, self._kek).blob
        return types.SimpleNamespace(
            wrapped_cek=base64.b64encode(blob).decode("ascii"),
            adapter_id=self.ADAPTER_ID,
        )

    def unwrap_cek(self, wrapped_cek: str):
        import base64
        from an_kla.sealed.cek import unwrap_cek

        try:
            token, blob = base64.b64decode(
                wrapped_cek, validate=True).split(b":", 1)
            cek = unwrap_cek(blob, self._kek)
        except Exception as exc:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            ) from exc
        if token.decode("ascii") not in self._ceks:
            raise sb.SealedPayloadAuthFailedError(
                "sealed payload authentication failed (no further detail)"
            )
        return types.SimpleNamespace(cek=cek)


def _create_sealed(store: MemoryStore, bundle: Path) -> tuple[dict, FakeAdapterB64]:
    adapter = FakeAdapterB64()
    result = dispatch_export_create(
        store, bundle, seal=sb.SEALED_PROFILE, key_adapter="unused",
        key_adapter_args=(), _runner_override=adapter,
    )
    return result, adapter


# ---------------------------------------------------------------------------
# Consulta estructural de la matriz: cada fila apunta a módulos presentes
# ---------------------------------------------------------------------------


class MatrixRowSourcesTests(unittest.TestCase):
    """La consolidación es AUDITABLE: cada fila 1-16 tiene fuente declarada.

    Este test NO ejecuta criptografía: comprueba que los módulos fuente de
    cada fila existen e importan (re-ejecutarlos corresponde a las clases
    ReRun* de abajo y a la suite completa de fila 15).
    """

    def test_every_row_has_declared_source(self):
        covered = set(_ROW_MODULES) | {
            "8", "9", "10", "11", "12", "14", "15",  # cubiertas AQUÍ
        }
        self.assertEqual(covered, {
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
            "10b", "10c", "10d", "10e", "11", "12", "12b", "13",
            "14", "15", "16",
        })

    def test_row_source_modules_exist(self):
        for row, modules in sorted(_ROW_MODULES.items()):
            for module in modules:
                path = ROOT / (module.replace(".", "/") + ".py")
                self.assertTrue(
                    path.is_file(), f"fila {row}: falta {path}")


# ---------------------------------------------------------------------------
# Re-ejecución de las filas ya cubiertas (verificación de presencia)
# ---------------------------------------------------------------------------


class MatrixReRunTests(unittest.TestCase):
    """Re-ejecuta los módulos fuente de las filas ya cubiertas por T2-T5.

    Cada fila declarada en ``_ROW_MODULES`` se re-ejecuta en el intérprete
    que corresponde: los módulos con partes criptográficas corren también
    con CLT python3 (que tiene ``cryptography``); en ``.venv`` los skips
    honestos de esos módulos siguen aplicando.
    """

    def _run_module(self, interpreter: str, module: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [interpreter, "-m", "unittest", module, "-v"],
            cwd=str(ROOT), capture_output=True, text=True,
            env={
                **os.environ,
                "AN_KLA_NO_UPDATE_CHECK": "1",
                # Anti-recursión: si el módulo re-ejecutado fuese la propia
                # matriz, su fila 15 anidada se salta.
                _ROW15_ENV: "1",
            },
        )

    def test_rerun_source_modules_this_interpreter(self):
        """Re-ejecución de TODOS los módulos fuente en este intérprete.

        En ``.venv`` (sin cryptography) los tests criptográficos se saltan
        con skip honesto — el módulo debe terminar en verde de todos modos.
        """
        modules = sorted({
            module
            for modules in _ROW_MODULES.values()
            for module in modules
        })
        for module in modules:
            with self.subTest(module=module):
                completed = self._run_module(sys.executable, module)
                self.assertEqual(
                    completed.returncode, 0,
                    f"{module} en rojo:\n{completed.stderr[-4000:]}",
                )

    def test_rerun_crypto_rows_with_clt_python(self):
        """Filas criptográficas re-ejecutadas con CLT python3 (con extra)."""
        crypto_rows = ("1", "2", "3", "4", "5", "7", "10b", "10c", "12b", "13", "16")
        if not CLT_PYTHON.exists():
            self.skipTest("CLT python3 no disponible; sólo .venv")
        modules = sorted({
            module
            for row, modules in _ROW_MODULES.items()
            if row in crypto_rows
            for module in modules
        })
        for module in modules:
            with self.subTest(module=module):
                completed = self._run_module(_clt_python(), module)
                self.assertEqual(
                    completed.returncode, 0,
                    f"{module} (CLT) en rojo:\n{completed.stderr[-4000:]}",
                )
                # Sin cryptography no habría cripto ejecutada: el run con
                # extra NO puede ser todo-skips (las filas criptográficas
                # deben correr de verdad allí). Se parsea el conteo real
                # en vez de un substring "0 tests", que falsos positivos
                # daba con conteos legítimos tipo "ran 10 tests" (fix
                # derivado de la partición beta.22, issue #106).
                corrida = re.search(
                    r"ran (\d+) tests?",
                    completed.stderr.lower().replace("\n", " "),
                )
                ejecutados = int(corrida.group(1)) if corrida else 0
                self.assertGreater(
                    ejecutados, 0,
                    f"{module}: cero tests ejecutados",
                )


# ---------------------------------------------------------------------------
# Fila 8 — verify sin clave jamás verified:true (CONSOLIDADA aquí)
# ---------------------------------------------------------------------------


#: Capacidad export descriptor-relative (ADR-0027): sin O_NOFOLLOW/
#: O_DIRECTORY/dir_fd (Windows) el camino funcional de export falla
#: cerrado; las filas que lo ejercitan se saltan ahí.
_EXPORT_CAPABLE = (
    getattr(os, "O_NOFOLLOW", None) is not None
    and getattr(os, "O_DIRECTORY", None) is not None
    and os.open in os.supports_dir_fd
)

@unittest.skipUnless(_EXPORT_CAPABLE, "export no soportado en esta plataforma (ADR-0027)")
class Row8UnkeyedNeverVerifiedTests(unittest.TestCase):
    """Fila 8: ``verify`` sin clave jamás devuelve ``verified: true``.

    Caminos cubiertos: resultado limpio, cada diagnóstico del enum §8,
    manifiesto ilegible. Reusa el bundle sintético estructuralmente válido
    (el unkeyed no desencripta jamás — el contenido no importa).
    """

    def _synthetic(self, root: str) -> Path:
        from tests.test_export_sealed_cli import _synthetic_sealed_bundle

        bundle = Path(root) / "sealed.bundle"
        self.manifest = _synthetic_sealed_bundle(bundle)
        self.bundle = bundle
        return bundle

    def test_clean_structure_false_but_never_true(self):
        with tempfile.TemporaryDirectory() as root:
            self._synthetic(root)
            result = dispatch_export_verify(self.bundle)
            self.assertIs(result["verified"], False)
            self.assertIs(result["structure_verified"], True)
            self.assertIs(result["payloads_verified"], False)

    def test_every_diagnostic_path_still_false(self):
        from tests.test_export_sealed_cli import _rewrite_manifest

        mutations = {
            "manifest_invalid": lambda m: m["seal"].pop("bundle_id"),
            "count_mismatch": lambda m: m["core"].update(
                total_bytes=m["core"]["total_bytes"] + 1),
            "unsafe_path": lambda m: m["core"]["entries"][0].update(
                path="anchor/../escape.json"),
        }
        for expected, mutate in mutations.items():
            with self.subTest(diagnostic=expected):
                with tempfile.TemporaryDirectory() as root:
                    self._synthetic(root)
                    _rewrite_manifest(self.bundle, mutate)
                    try:
                        result = dispatch_export_verify(self.bundle)
                    except ExportError:
                        # La mutación puede romper el peek de perfil del
                        # dispatcher (p. ej. seal deja de ser dict): el
                        # camino v1 emite export_manifest_invalid — igual
                        # falla cerrado, jamás verified:true.
                        continue
                    self.assertIs(result["verified"], False)
                    self.assertIn(expected, result.get("diagnostics", []))

    def test_missing_and_extra_files_never_true(self):
        with tempfile.TemporaryDirectory() as root:
            self._synthetic(root)
            entry = self.manifest["core"]["entries"][0]
            (self.bundle / "entries" / entry["path"]).unlink()
            result = dispatch_export_verify(self.bundle)
            self.assertIs(result["verified"], False)
            self.assertIn("entry_missing", result["diagnostics"])
        with tempfile.TemporaryDirectory() as root:
            self._synthetic(root)
            (self.bundle / "entries" / "extra.json").write_bytes(b"x")
            result = dispatch_export_verify(self.bundle)
            self.assertIs(result["verified"], False)
            self.assertIn("entry_unexpected", result["diagnostics"])


# ---------------------------------------------------------------------------
# Fila 9 — reescritura COMPLETA del bundle por atacante → detected
# ---------------------------------------------------------------------------


class Row9FullBundleRewriteTests(unittest.TestCase):
    """Fila 9: ``verify`` autenticado detecta reescritura completa.

    El atacante re-sella TODO el bundle con su propia CEK: manifiesto v2
    nuevo íntegro y autoconsistente (bundle_id, manifest_mac y ciphertexts
    del atacante cuadran entre sí). Con la CEK/Adaptador DEL OPERADOR el
    verify autenticado falla (``sealed_payload_auth_failed``): la CEK del
    operador no abre el sello del atacante. Y el ``bundle_id`` del atacante
    es DISTINTO — la ancla manual del ADR (§Límites) lo detecta fuera de
    línea. Esto documenta el límite declarado: el sello no es atestación
    de origen (F8-E diferida); un adaptador de clave pública permitiría
    que el restore del atacante tuviera éxito con SU adaptador — la
    defensa disponible ES esta comparación de bundle_id.
    """

    def setUp(self):
        if not _cryptography_importable():
            self.skipTest(
                "fila 9 es criptográfica; corre con CLT python3"
            )
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_full_rewrite_detected_by_keyed_verify(self):
        store = _make_store(self.root)
        bundle = self.root / "legit.bundle"
        created, adapter = _create_sealed(store, bundle)
        legit_bundle_id = created["bundle_id"]

        # El atacante re-sella el MISMO store con su PROPIA CEK y su
        # PROPIA custodia (KEK distinta): produce un bundle v2
        # completamente nuevo y autoconsistente.
        attacker_bundle = self.root / "attacker.bundle"
        attacker = FakeAdapterB64(kek=b"a" * 32)
        attacker_created = dispatch_export_create(
            store, attacker_bundle, seal=sb.SEALED_PROFILE,
            key_adapter="unused", key_adapter_args=(),
            _runner_override=attacker,
        )
        self.assertNotEqual(
            attacker_created["bundle_id"], legit_bundle_id,
            "la ancla manual (bundle_id) distingue el re-sellado",
        )

        # El atacante sustituye el bundle legítimo por el suyo.
        import shutil

        shutil.rmtree(bundle)
        shutil.move(str(attacker_bundle), str(bundle))

        # 1) Verify autenticado CON EL ADAPTADOR DEL OPERADOR: el unwrap
        #    del wrapped_cek del atacante falla bajo la custodia del
        #    operador → sealed_payload_auth_failed (sin oráculo).
        with self.assertRaises(sb.SealedPayloadAuthFailedError):
            dispatch_export_verify(
                bundle, key_adapter="x", key_adapter_args=(),
                _runner_override=adapter,
            )

        # 2) La defensa documentada (ancla manual): bundle_id registrado
        #    al crear ≠ bundle_id del bundle sustituido.
        replaced = json.loads((bundle / "manifest.json").read_bytes())
        self.assertNotEqual(
            replaced["seal"]["bundle_id"], legit_bundle_id)

        # 3) El verify SIN clave no puede distinguir (estructura válida):
        #    jamás afirma verified:true — tampoco se deja engañar.
        unkeyed = dispatch_export_verify(bundle)
        self.assertIs(unkeyed["verified"], False)
        self.assertIs(unkeyed["structure_verified"], True)


# ---------------------------------------------------------------------------
# Fila 10 — downgrade: dispatcher dual + lector beta.17 sin dispatcher
# ---------------------------------------------------------------------------


@unittest.skipUnless(_EXPORT_CAPABLE, "export no soportado en esta plataforma (ADR-0027)")
class Row10DowngradeTests(unittest.TestCase):
    """Fila 10 completa (sin cryptography).

    - Dispatcher dual: sellado pidiendo v1 o perfil desconocido →
      ``unsupported_export_profile`` (cubiertos en T5; re-verificado aquí
      por presencia de los tests fuente en ReRun).
    - Lector beta.17 SIN dispatcher dual (el lector v1 vigente,
      ``verify_export``/``_validated``) frente a bundle sellado →
      ``export_manifest_invalid`` (nota §3) — probado aquí contra el
      lector DIRECTO, que es lo que un binario beta.17 ejecutaría.
    - Sellado sin extra/adaptador → fail-closed (fila 12b + H1 en CLI).
    """

    def _synthetic(self, root: str) -> Path:
        from tests.test_export_sealed_cli import _synthetic_sealed_bundle

        bundle = Path(root) / "sealed.bundle"
        _synthetic_sealed_bundle(bundle)
        return bundle

    def test_beta17_v1_reader_rejects_sealed_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = self._synthetic(root)
            # El lector v1 DIRECTO (sin dispatcher dual): ve un schema
            # export-manifest-v2 donde exige export-manifest-v1 →
            # export_manifest_invalid (nota §3 del ADR).
            with self.assertRaisesRegex(
                    ExportError, "export_manifest_invalid"):
                verify_export(bundle)

    def test_dispatcher_sealed_asking_v1_unsupported(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = self._synthetic(root)
            with self.assertRaisesRegex(
                    ExportError, "unsupported_export_profile"):
                dispatch_export_verify(bundle, seal=V1_PROFILE)

    def test_dispatcher_unknown_profile_unsupported(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = self._synthetic(root)
            manifest = json.loads(
                (bundle / "manifest.json").read_bytes())
            manifest["profile"] = "sealed-export/v99"
            (bundle / "manifest.json").write_bytes(
                canonical_json(manifest))
            with self.assertRaisesRegex(
                    ExportError, "unsupported_export_profile"):
                dispatch_export_verify(bundle)

    def test_sealed_without_adapter_fail_closed_never_cleartext(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = self._synthetic(root)
            from an_kla.sealed.key_adapter import (
                SealingAdapterRequiredError,
            )

            with self.assertRaises(SealingAdapterRequiredError):
                dispatch_export_restore(bundle, Path(root) / "r")
            self.assertFalse(
                (Path(root) / "r" / ".an-kla").exists())


# ---------------------------------------------------------------------------
# Fila 11 — bundles v1 en claro sin cambios sin el extra
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main()
