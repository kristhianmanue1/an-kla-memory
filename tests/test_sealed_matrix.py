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
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest

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
    "1": ("tests.test_sealed_bundle",),              # F1 inyectividad
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
                "ANKLA_NO_UPDATE_CHECK": "1",
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
                # deben correr de verdad allí).
                self.assertNotIn(
                    "0 tests", completed.stderr.lower().replace("\n", " "),
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


@unittest.skipUnless(_EXPORT_CAPABLE, "export no soportado en esta plataforma (ADR-0027)")
class Row11V1BundlesUnchangedTests(unittest.TestCase):
    """Fila 11: bundles v1 en claro: create/verify/restore sin cambios y
    suite v1 intacta sin el extra instalado.

    1) Re-ejecución de la suite v1 (``test_export_restore`` +
       ``test_compaction``) en ESTE intérprete (sin cryptography en
       ``.venv``: demuestra que v1 no depende del extra).
    2) El camino v1 no importa los módulos de cifrado sellado al
       ejecutarse (sin extra, el import real fallaría si lo hiciera).
    """

    def test_v1_roundtrip_works_without_extra(self):
        with tempfile.TemporaryDirectory() as root:
            store = _make_store(Path(root))
            bundle = Path(root) / "plain.bundle"
            created = create_export(store, bundle)
            self.assertEqual(created["schema"], "an-kla/export-result-v1")
            verified = verify_export(bundle)
            self.assertTrue(verified["verified"])
            restored = Path(root) / "restored"
            from an_kla.export_restore import restore_export

            restore_export(bundle, restored)
            self.assertEqual(
                MemoryStore(restored).read_current(),
                store.read_current(),
            )

    def test_v1_suite_reruns_in_this_interpreter(self):
        for module in ("tests.test_export_restore", "tests.test_compaction"):
            with self.subTest(module=module):
                completed = subprocess.run(
                    [sys.executable, "-m", "unittest", module],
                    cwd=str(ROOT), capture_output=True, text=True,
                    env={
                        **os.environ,
                        "ANKLA_NO_UPDATE_CHECK": "1",
                        _ROW15_ENV: "1",
                    },
                )
                self.assertEqual(
                    completed.returncode, 0,
                    f"{module} en rojo:\n{completed.stderr[-4000:]}",
                )

    def test_v1_path_does_not_touch_sealed_crypto(self):
        """Un proceso hijo ejecuta create+verify v1 SIN cryptography
        (bloqueada por meta_path) y SIN ``sealed_available``: verde."""
        code = (
            "import sys\n"
            "class _Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'cryptography' or name.startswith("
            "'cryptography.'):\n"
            "            raise ImportError('blocked for test')\n"
            "        return None\n"
            "sys.meta_path.insert(0, _Block())\n"
            "import tempfile\n"
            "from pathlib import Path\n"
            "from an_kla.export_restore import create_export, verify_export\n"
            "from an_kla.store import MemoryStore\n"
            "with tempfile.TemporaryDirectory() as root:\n"
            "    store = MemoryStore(Path(root))\n"
            "    initial = store.initialize()\n"
            "    store.commit(expected_current_hash=initial,\n"
            "                 checkpoint_patch={},\n"
            "                 facts=[{'id': 'f', 'payload': {}}])\n"
            "    bundle = Path(root) / 'b.bundle'\n"
            "    create_export(store, bundle)\n"
            "    assert verify_export(bundle)['verified'] is True\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


# ---------------------------------------------------------------------------
# Fila 12 — compactación con bundle sellado como insumo → rechazado
# ---------------------------------------------------------------------------


@unittest.skipUnless(_EXPORT_CAPABLE, "export no soportado en esta plataforma (ADR-0027)")
class Row12CompactionRejectsSealedTests(unittest.TestCase):
    """Fila 12: compactación con bundle sellado como insumo → rechazado
    con ``export_manifest_invalid`` por el lector v1 vigente. Sellado es
    respaldo, no insumo; la proof sobre bundles v1 queda intacta
    (fila 11 la re-ejecuta)."""

    def test_plan_compaction_with_sealed_bundle_rejected(self):
        import uuid

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            # Bundle v1 legítimo para tener el manifest_sha256 de un export
            # real v1 (que la propuesta exige cuadre con el BUNDLE usado).
            plain = root_path / "plain.bundle"
            exported = create_export(store, plain)
            # Sustituimos el insumo por un bundle SELLADO (sintético en
            # estructura): plan_compaction debe rechazarlo por el lector v1.
            sealed = root_path / "sealed.bundle"
            from tests.test_export_sealed_cli import _synthetic_sealed_bundle

            _synthetic_sealed_bundle(sealed)
            # El lector v1 (_validated) rechaza el manifiesto sellado ANTES
            # de cualquier binding: export_manifest_invalid (nota §3). Se
            # prueba directamente contra _validated — lo primero que
            # plan_compaction ejecuta sobre el insumo — porque
            # plan_compaction puede traducir/envolver el error.
            from an_kla.export_restore import _validated

            with self.assertRaisesRegex(
                    ExportError, "export_manifest_invalid"):
                _validated(sealed, 100000, 10 * 1024**3)
            # Y el plan completo con el bundle sellado como insumo también
            # falla (CompactionError del borde de compactación).
            proposal = {
                "schema": "an-kla/compaction-proposal-v1",
                "base_revision": store.read_current(),
                "epoch_id": str(uuid.uuid4()),
                "transaction_id": str(uuid.uuid4()),
                "export_manifest_sha256": exported["manifest_sha256"],
            }
            with self.assertRaises((CompactionError, ExportError)):
                plan_compaction(store, proposal, sealed)


# ---------------------------------------------------------------------------
# Fila 14 — taxonomía de warnings EXACTA por perfil
# ---------------------------------------------------------------------------


class Row14WarningTaxonomyTests(unittest.TestCase):
    """Fila 14: warning taxonomía exacta por perfil, SIN cruce posible.

    | Camino                        | Warnings exactos                     |
    |-------------------------------|--------------------------------------|
    | v1 create/verify (correcto)   | [plaintext_export_contains_…]        |
    | v1 restore                    | {plaintext…, root_relocated?}        |
    | sellado create/verify-keyed/  | [sealed_export_untrusted_memory_data]|
    | restore sellado               | {sealed…, root_relocated?}           |
    | verify sellado sin clave      | [sealed_payloads_unverified_without_ |
    |                               |  key] (JAMÁS los otros)              |

    Ningún resultado sellado contiene el warning v1 y viceversa (§7).
    """

    def setUp(self):
        if not _cryptography_importable():
            self.skipTest(
                "taxonomía sellada completa requiere cryptography; "
                "los caminos v1/unkeyed corren en cualquier intérprete "
                "(verificados en fila 11/8)"
            )
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_taxonomy_exact_per_profile(self):
        store = _make_store(self.root)
        # v1 en claro.
        plain = self.root / "plain.bundle"
        v1_created = create_export(store, plain)
        self.assertEqual(v1_created["warnings"], [PLAINTEXT_WARNING])
        v1_verified = verify_export(plain)
        self.assertEqual(v1_verified["warnings"], [PLAINTEXT_WARNING])
        v1_restored = self.root / "v1-restored"
        from an_kla.export_restore import restore_export

        v1_outcome = restore_export(plain, v1_restored)
        self.assertIn(PLAINTEXT_WARNING, v1_outcome["warnings"])
        self.assertTrue(set(v1_outcome["warnings"]) <= {
            PLAINTEXT_WARNING, "root_relocated"})
        self.assertNotIn(SEALED_WARNING, v1_outcome["warnings"])
        self.assertNotIn(UNKEYED_WARNING, v1_outcome["warnings"])

        # Sellado: create → verify keyed/unkeyed → restore.
        sealed = self.root / "sealed.bundle"
        created, adapter = _create_sealed(store, sealed)
        self.assertEqual(created["warnings"], [SEALED_WARNING])
        self.assertNotIn(PLAINTEXT_WARNING, created["warnings"])

        keyed = dispatch_export_verify(
            sealed, key_adapter="x", key_adapter_args=(),
            _runner_override=adapter,
        )
        self.assertEqual(keyed["warnings"], [SEALED_WARNING])
        self.assertNotIn(PLAINTEXT_WARNING, keyed["warnings"])

        unkeyed = dispatch_export_verify(sealed)
        self.assertEqual(unkeyed["warnings"], [UNKEYED_WARNING])
        self.assertNotIn(SEALED_WARNING, unkeyed["warnings"])
        self.assertNotIn(PLAINTEXT_WARNING, unkeyed["warnings"])

        destination = self.root / "sealed-restored"
        outcome = dispatch_export_restore(
            sealed, destination, key_adapter="x", key_adapter_args=(),
            _runner_override=adapter,
        )
        self.assertIn(SEALED_WARNING, outcome["warnings"])
        self.assertTrue(set(outcome["warnings"]) <= {
            SEALED_WARNING, "root_relocated"})
        self.assertNotIn(PLAINTEXT_WARNING, outcome["warnings"])
        self.assertNotIn(UNKEYED_WARNING, outcome["warnings"])

    def test_h2_no_staging_residue_after_sealed_restore(self):
        """H2 (deuda T4/T5): restore sellado exitoso → CERO directorios
        ``.an-kla-sealed-restore-*`` residuales."""
        store = _make_store(self.root)
        sealed = self.root / "sealed.bundle"
        _created, adapter = _create_sealed(store, sealed)
        destination = self.root / "dest"
        outcome = dispatch_export_restore(
            sealed, destination, key_adapter="x", key_adapter_args=(),
            _runner_override=adapter,
        )
        self.assertIs(outcome["published"], True)
        residues = list(destination.glob(".an-kla-sealed-restore-*"))
        self.assertEqual(residues, [])


# ---------------------------------------------------------------------------
# Fila 15 — suite completa con y sin extra + CI local
# ---------------------------------------------------------------------------


#: (Guarda anti-recursión declarada junto a ROOT, arriba.)


class Row15SuiteBothProfilesTests(unittest.TestCase):
    """Fila 15: suite completa + CI local SIN ``[sealed]`` instalado y con él.

    - Este intérprete SIN cryptography (``.venv``): discover completo de
      ``tests/`` debe ser verde (skips honestos en lo criptográfico).
    - CLT python3 CON cryptography: discover completo verde, y los tests
      criptográficos (p. ej. ``tests.test_sealed_bundle``) corren SIN
      saltarse.
    - ``scripts/ci_local.py`` en ambos modos (con y sin --simulate-ci).

    NOTA de costo: el discover completo se ejecuta UNA vez por intérprete
    (2 subprocesses) + ci_local dos modos. Anti-recursión: los discovers
    lanzados aquí marcan ``ANKLA_MATRIX_ROW15_ACTIVE`` y una fila 15
    anidada dentro de esos runs se salta (la ejecución de nivel superior
    ya la cubre).
    """

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get(_ROW15_ENV) == "1":
            raise unittest.SkipTest(
                "fila 15 anidada: el discover de nivel superior ya la "
                "cubre (anti-recursión)"
            )

    def _discover(self, interpreter: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [interpreter, "-m", "unittest", "discover",
             "-s", "tests", "-p", "test_*.py"],
            cwd=str(ROOT), capture_output=True, text=True,
            env={
                **os.environ,
                "ANKLA_NO_UPDATE_CHECK": "1",
                _ROW15_ENV: "1",
            },
        )

    def test_full_suite_this_interpreter(self):
        completed = self._discover(sys.executable)
        self.assertEqual(
            completed.returncode, 0,
            f"discover en rojo ({sys.executable}):\n"
            f"{completed.stderr[-6000:]}",
        )

    def test_full_suite_with_extra_clt_python(self):
        interpreter = _clt_python()
        completed = self._discover(interpreter)
        self.assertEqual(
            completed.returncode, 0,
            f"discover (CLT) en rojo:\n{completed.stderr[-6000:]}",
        )
        if not _cryptography_importable():
            # En .venv, verificamos que el run CLT ejecutó la cripto: el
            # módulo criptográfico canonical NO puede terminar en
            # "skipped" masivo — lo comprobamos con un run dirigido -v.
            probe = subprocess.run(
                [interpreter, "-m", "unittest",
                 "tests.test_sealed_bundle", "-v"],
                cwd=str(ROOT), capture_output=True, text=True,
                env={**os.environ, "ANKLA_NO_UPDATE_CHECK": "1"},
            )
            self.assertEqual(probe.returncode, 0, probe.stderr[-4000:])
            self.assertIn("... ok", probe.stderr)

    def test_ci_local_both_modes(self):
        """``scripts/ci_local.py`` verde en modo normal y --simulate-ci.

        Corre con el intérprete SIN extra (``sys.executable`` cuando es
        .venv): es el modo canónico de desarrollo. Se coteja que la
        salida termina en ``ci_local: OK``.
        """
        for mode in ([], ["--simulate-ci"]):
            with self.subTest(mode=mode or "normal"):
                completed = subprocess.run(
                    [sys.executable, "scripts/ci_local.py", *mode],
                    cwd=str(ROOT), capture_output=True, text=True,
                    env={
                        **os.environ,
                        "ANKLA_NO_UPDATE_CHECK": "1",
                        # Anti-recursión: ci_local lanza un discover que
                        # vuelve a cargar esta matriz; su fila 15 anidada
                        # se salta.
                        _ROW15_ENV: "1",
                    },
                )
                self.assertEqual(
                    completed.returncode, 0,
                    completed.stdout[-4000:] + completed.stderr[-2000:],
                )
                self.assertIn("ci_local: OK", completed.stdout)


# ---------------------------------------------------------------------------
# H1 — códigos canónicos sellados por CLI REAL en stderr
# ---------------------------------------------------------------------------


class H1CanonicalCodesOnCLITests(unittest.TestCase):
    """H1 (deuda T5): el CLI emite el código canónico en stderr.

    Por CLI REAL (subprocess ``python -m an_kla``):

    - ``--seal`` sin adaptador → stderr contiene ``sealing_adapter_required``.
    - adaptador inexistente → ``sealing_adapter_error``.
    - clave equivocada (adaptador con OTRA llave) →
      ``sealed_payload_auth_failed``.
    - ``--seal`` sin extra (venv) → ``sealing_extra_not_installed`` + hint.
    """

    def _cli(self, arguments: list[str], env: dict | None = None,
             cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "an_kla", "--no-update-check", *arguments],
            cwd=str(cwd or ROOT), capture_output=True, text=True,
            env={**os.environ, **(env or {})},
        )

    def test_seal_without_adapter_canonical_code(self):
        if not _cryptography_importable():
            self.skipTest("camino criptográfico; con .venv el caso es el "
                          "de extra ausente (test abajo)")
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            completed = self._cli([
                "--project-root", str(store.project_root),
                "export", "create", "--bundle",
                str(root_path / "nope.bundle"),
                "--seal", "sealed-export/v1",
            ])
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("sealing_adapter_required", completed.stderr)
            self.assertNotIn("cli_unexpected_failure", completed.stderr)
            self.assertFalse((root_path / "nope.bundle").exists())

    def test_nonexistent_adapter_canonical_code(self):
        if not _cryptography_importable():
            self.skipTest("camino criptográfico")
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            completed = self._cli([
                "--project-root", str(store.project_root),
                "export", "create", "--bundle",
                str(root_path / "nope.bundle"),
                "--seal", "sealed-export/v1",
                "--key-adapter", str(root_path / "does-not-exist"),
            ])
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("sealing_adapter_error", completed.stderr)
            self.assertNotIn("cli_unexpected_failure", completed.stderr)

    def test_wrong_key_canonical_code(self):
        if not _cryptography_importable():
            self.skipTest("camino criptográfico")
        adapter = ROOT / "tests" / "adapters" / "file_key_adapter.py"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            bundle = root_path / "b.bundle"
            good = root_path / "good.key"
            good.write_text("ab" * 32)
            env = {"ANKLA_TEST_ADAPTER_KEY_FILE": str(good)}
            created = self._cli([
                "--project-root", str(store.project_root),
                "export", "create", "--bundle", str(bundle),
                "--seal", "sealed-export/v1",
                "--key-adapter", sys.executable,
                "--key-adapter-arg", str(adapter),
                "--key-adapter-env", "ANKLA_TEST_ADAPTER_KEY_FILE",
            ], env=env)
            self.assertEqual(created.returncode, 0, created.stderr)
            # Clave equivocada al verificar → sealed_payload_auth_failed.
            # Se usa un adaptador cuyo unwrap SÍ responde (CEK de 32 bytes
            # b64 canónico) pero con la CEK EQUIVOCADA: así el fallo cae
            # en la autenticación del BUNDLE (§5), no en el contrato del
            # adaptador (que sería sealing_adapter_error — caso cubierto
            # por el test de adaptador inexistente).
            wrong = root_path / "wrong_cek_adapter.py"
            wrong.write_text(
                "import base64, json, sys\n"
                "req = json.loads(sys.stdin.read())\n"
                "assert set(req) == {'op', 'wrapped_cek'}\n"
                "sys.stdout.write(json.dumps({'cek_b64': "
                "base64.b64encode(b'W'*32).decode()}, sort_keys=True))\n"
            )
            completed = self._cli([
                "export", "verify", "--bundle", str(bundle),
                "--key-adapter", sys.executable,
                "--key-adapter-arg", str(wrong),
            ])
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(
                "sealed_payload_auth_failed", completed.stderr)
            self.assertNotIn("cli_unexpected_failure", completed.stderr)

    def test_seal_without_extra_canonical_code_and_hint(self):
        if _cryptography_importable() or sealed_available:
            self.skipTest(
                "este intérprete tiene el extra; el caso sin extra corre "
                "en .venv (suite canónica)"
            )
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            completed = self._cli([
                "--project-root", str(store.project_root),
                "export", "create", "--bundle",
                str(root_path / "nope.bundle"),
                "--seal", "sealed-export/v1",
                "--key-adapter", sys.executable,
            ])
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("sealing_extra_not_installed", completed.stderr)
            self.assertIn("[sealed]", completed.stderr)
            self.assertNotIn("cli_unexpected_failure", completed.stderr)

    def test_h2_cli_restore_leaves_no_residue(self):
        """H2 por CLI REAL: restore sellado exitoso sin residuo staging."""
        if not _cryptography_importable():
            self.skipTest("camino criptográfico")
        adapter = ROOT / "tests" / "adapters" / "file_key_adapter.py"
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            store = _make_store(root_path)
            key = root_path / "adapter.key"
            key.write_text("ab" * 32)
            env = {"ANKLA_TEST_ADAPTER_KEY_FILE": str(key)}
            bundle = root_path / "b.bundle"
            created = self._cli([
                "--project-root", str(store.project_root),
                "export", "create", "--bundle", str(bundle),
                "--seal", "sealed-export/v1",
                "--key-adapter", sys.executable,
                "--key-adapter-arg", str(adapter),
                "--key-adapter-env", "ANKLA_TEST_ADAPTER_KEY_FILE",
            ], env=env)
            self.assertEqual(created.returncode, 0, created.stderr)
            destination = root_path / "dest"
            destination.mkdir()
            restored = self._cli([
                "--project-root", str(destination),
                "export", "restore", "--bundle", str(bundle),
                "--key-adapter", sys.executable,
                "--key-adapter-arg", str(adapter),
                "--key-adapter-env", "ANKLA_TEST_ADAPTER_KEY_FILE",
            ], env=env)
            self.assertEqual(restored.returncode, 0, restored.stderr)
            residues = list(destination.glob(".an-kla-sealed-restore-*"))
            self.assertEqual(residues, [])


# ---------------------------------------------------------------------------
# N1 — mensaje de --key-adapter-env en lenguaje CLI
# ---------------------------------------------------------------------------


class N1KeyAdapterEnvMessageTests(unittest.TestCase):
    """N1 (deuda T5): el mensaje de validación de ``--key-adapter-env`` en
    lenguaje CLI (sin jerga interna 'env_allowlist entries')."""

    def test_env_validation_message_is_cli_language(self):
        from an_kla.sealed.key_adapter import SealingAdapterRunner

        with self.assertRaises(ValueError) as caught:
            SealingAdapterRunner(
                ["/bin/true"], env_allowlist=["BAD=NAME"])
        message = str(caught.exception)
        self.assertNotIn("env_allowlist entries", message)
        self.assertIn("key_adapter_env", message)
        self.assertIn("environment variable names", message)


if __name__ == "__main__":
    unittest.main()
