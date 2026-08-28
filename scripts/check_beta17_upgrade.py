"""Exercise a beta.17 consumer upgraded to the candidate wheel (ADR-0042 §9).

Gate de upgrade beta.17→beta.18. Requisito del ADR (§9, gate de
publicación): además de preservar el camino ``export/v1`` tras el
upgrade, el gate **ejercita ``--seal`` end-to-end** contra el adaptador
determinístico de ``scripts/gate_sealed_adapter.py`` (sólo para gates,
nunca en el paquete).

Perfil del candidato: SIN el extra ``[sealed]`` (perfil por defecto,
stdlib-only). La parte criptográfica del sellado requiere
``cryptography>=42``; este gate la resuelve creando el venv del
consumidor con ``--system-site-packages`` sobre un intérprete anfitrión
que ya la tenga instalada (la detección del extra en ``an_kla.sealed``
es perezosa; no se instala nada). Si no hay ningún intérprete con
``cryptography``, el gate degrada honestamente: ejercita el fail-closed
``sealing_extra_not_installed`` (que ES parte de la matriz §9, fila 12b)
y declara el REMANENTE (create/verify/restore sellados criptográficos)
como pendiente de un runner con ``cryptography`` — el exit code lo
refleja: 0 sólo si el flujo sellado completo corrió.

El CLI se invoca como ``python -m an_kla`` desde un directorio NEUTRO
(no desde ROOT): ``-m`` antepone el cwd a ``sys.path`` y el árbol fuente
del repo ocultaría el wheel instalado en el venv.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_TAG = "v0.1.0-beta.17"
CANDIDATE_VERSION = "an-kla-memory 0.1.0b18"
GATE_ADAPTER = ROOT / "scripts" / "gate_sealed_adapter.py"


def _run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result


def _wheel(source: Path, destination: Path, error: str) -> Path:
    _run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(destination)],
        cwd=source,
    )
    wheels = list(destination.glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit(error)
    return wheels[0]


def _venv_python_with_cryptography(temporary: Path) -> tuple[Path, bool]:
    """Crea el venv del consumidor, con acceso al extra si es posible.

    El paquete instalado es siempre el wheel (perfil por defecto, sin
    dependencias nuevas). Para ejercitar el flujo sellado completo SIN
    instalar nada, el venv se crea con ``--system-site-packages`` sobre
    un intérprete anfitrión que ya tenga ``cryptography`` (la detección
    del extra en ``an_kla.sealed`` es perezosa y lo ve a través del
    system-site). Devuelve (venv_python, sealed_extra_visible). El CLI
    se invoca como ``python -m an_kla`` desde un cwd neutro.
    """
    interpreters = [sys.executable]
    for candidate in ("/usr/bin/python3", shutil.which("python3") or ""):
        if candidate and candidate != str(sys.executable) and Path(candidate).exists():
            interpreters.append(candidate)
    for interpreter in interpreters:
        probe = subprocess.run(
            [interpreter, "-c",
             "import cryptography.hazmat.primitives.ciphers.aead"],
            capture_output=True,
        )
        if probe.returncode:
            continue
        environment = temporary / "venv-sealed"
        _run([interpreter, "-m", "venv", "--system-site-packages", str(environment)])
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        return scripts / ("python.exe" if os.name == "nt" else "python"), True
    environment = temporary / "venv-plain"
    _run([sys.executable, "-m", "venv", str(environment)])
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    return scripts / ("python.exe" if os.name == "nt" else "python"), False


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        # Cwd neutro para TODO `python -m an_kla`: sin él, el árbol
        # fuente del repo (an_kla/) ocultaría el wheel instalado.
        neutral = temporary / "cwd"
        neutral.mkdir()
        archive = temporary / "beta17.zip"
        _run(["git", "archive", "--format=zip", "--output", str(archive), PREVIOUS_TAG], cwd=ROOT)
        previous_source = temporary / "previous-source"
        previous_source.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise SystemExit("beta17_upgrade_unsafe_archive")
            bundle.extractall(previous_source)

        previous_wheel = _wheel(previous_source, temporary / "prev", "beta17_prev_wheel")
        candidate_wheel = _wheel(ROOT, temporary / "cand", "beta17_cand_wheel")

        python, sealed_available = _venv_python_with_cryptography(temporary)

        def cli(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
            command = [str(python), "-m", "an_kla", "--no-update-check", *args]
            if check:
                return _run(command, cwd=neutral)
            return subprocess.run(command, cwd=neutral, capture_output=True)

        _run([str(python), "-m", "pip", "install", "--no-deps", str(previous_wheel)], cwd=neutral)
        if cli("--version", check=True).stdout.decode().strip() != "an-kla-memory 0.1.0b17":
            raise SystemExit("beta17_upgrade_wrong_previous_version")

        consumer = temporary / "consumer"
        consumer.mkdir()
        root = ["--project-root", str(consumer)]
        cli(*root, "init")
        cli(*root, "context", "plan", "--operation", "install")
        cli(*root, "context", "install")

        # Respaldo v1 creado ANTES del upgrade, con la versión previa.
        pre_upgrade_bundle = temporary / "bundle-pre-upgrade"
        pre = json.loads(cli(*root, "export", "create", "--bundle", str(pre_upgrade_bundle)).stdout)
        if pre.get("schema") != "an-kla/export-result-v1":
            raise SystemExit("beta17_upgrade_pre_upgrade_not_v1")

        _run([str(python), "-m", "pip", "install", "--no-deps", "--upgrade",
              "--force-reinstall", str(candidate_wheel)], cwd=neutral)
        installed = cli("--version", check=True).stdout.decode().strip()
        if installed != CANDIDATE_VERSION:
            # El bump de versión es del maintainer: con el árbol aún en
            # 0.1.0b17 el gate de release NO puede correr completo
            # (patrón check_beta16: el gate se confirma en el commit de
            # release, tras el bump).
            raise SystemExit(
                f"beta17_upgrade_wrong_candidate_version: expected {CANDIDATE_VERSION}, got {installed}"
            )

        verify = json.loads(cli(*root, "verify").stdout)
        if verify.get("ok") is not True:
            raise SystemExit("beta17_upgrade_invalid_baseline")
        context = json.loads(cli(*root, "context", "status").stdout)
        if context.get("ok") is not True or context.get("template_version") != "0.1.0-beta.11":
            raise SystemExit("beta17_upgrade_context_changed")

        # Camino export/v1 intacto TRAS el upgrade (invariante de #46):
        # el bundle v1 creado con beta.17 sigue verificando y restaurando,
        # y un create nuevo sigue siendo export-result-v1 en claro.
        post_verify = json.loads(cli("export", "verify", "--bundle", str(pre_upgrade_bundle)).stdout)
        if post_verify.get("schema") != "an-kla/export-verify-result-v1" or post_verify.get("verified") is not True:
            raise SystemExit("beta17_upgrade_v1_bundle_broken_after_upgrade")
        restore_root = temporary / "restore-v1"
        restore_root.mkdir()
        restored = json.loads(
            cli("--project-root", str(restore_root),
                "export", "restore", "--bundle", str(pre_upgrade_bundle)).stdout
        )
        if restored.get("schema") != "an-kla/restore-result-v1" or restored.get("state") != "published":
            raise SystemExit("beta17_upgrade_v1_restore_broken_after_upgrade")
        fresh_bundle = temporary / "bundle-fresh-v1"
        fresh = json.loads(cli(*root, "export", "create", "--bundle", str(fresh_bundle)).stdout)
        if fresh.get("schema") != "an-kla/export-result-v1":
            raise SystemExit("beta17_upgrade_v1_create_degraded")
        if "plaintext_export_contains_untrusted_memory_data" not in fresh.get("warnings", []):
            raise SystemExit("beta17_upgrade_v1_warning_taxonomy_changed")

        # --seal end-to-end con el adaptador determinístico de gates
        # (ADR-0042 §9). El adaptador corre con el python3 del sistema
        # (stdlib pura, no necesita el extra); el core sí lo necesita.
        sealed_bundle = temporary / "bundle-sealed"
        sealed_command = [
            "--seal", "sealed-export/v1",
            "--key-adapter", "python3",
            "--key-adapter-arg", str(GATE_ADAPTER),
        ]
        if not sealed_available:
            # Perfil por defecto (sin extra en NINGÚN intérprete): el
            # fail-closed ES parte de la matriz (fila 12b) y se ejercita
            # igual — pero el flujo sellado completo queda declarado como
            # REMANENTE para un runner con cryptography (honestidad ante
            # todo: exit 3, no verde).
            failed = cli(*root, "export", "create", "--bundle", str(sealed_bundle),
                         *sealed_command, check=False)
            stderr = failed.stderr.decode()
            if failed.returncode == 0 or "sealing_extra_not_installed" not in stderr:
                raise SystemExit("beta17_upgrade_fail_closed_not_exercised")
            print(
                "check_beta17_upgrade: PARCIAL — camino v1 intacto tras upgrade y "
                "fail-closed sealing_extra_not_installed verificados; el flujo "
                "sellado completo (create/verify/restore con clave) REQUIERE "
                "cryptography y queda como remanente para un runner con el extra "
                "[sealed] (ADR-0042 §9). Exit 3."
            )
            return 3

        created = json.loads(
            cli(*root, "export", "create", "--bundle", str(sealed_bundle),
                *sealed_command).stdout
        )
        if created.get("schema") != "an-kla/export-result-v2":
            raise SystemExit("beta17_upgrade_sealed_create_not_v2")
        if not created.get("bundle_id") or not created.get("manifest_sha256"):
            raise SystemExit("beta17_upgrade_sealed_anchor_missing")
        if "sealed_export_untrusted_memory_data" not in created.get("warnings", []):
            raise SystemExit("beta17_upgrade_sealed_warning_taxonomy_changed")

        # verify sin clave: estructural honesto, jamás verified:true (fila 8).
        unkeyed = json.loads(cli("export", "verify", "--bundle", str(sealed_bundle)).stdout)
        if unkeyed.get("verified") is not False or unkeyed.get("structure_verified") is not True:
            raise SystemExit("beta17_upgrade_unkeyed_verify_dishonest")

        # verify con clave (adaptador determinístico): verified:true.
        keyed = json.loads(
            cli("export", "verify", "--bundle", str(sealed_bundle),
                *sealed_command).stdout
        )
        if keyed.get("verified") is not True or keyed.get("payloads_verified") is not True:
            raise SystemExit("beta17_upgrade_keyed_verify_failed")
        if keyed.get("bundle_id") != created.get("bundle_id"):
            raise SystemExit("beta17_upgrade_bundle_id_mismatch")

        # restore sellado: publicar en destino limpio.
        sealed_restore_root = temporary / "restore-sealed"
        sealed_restore_root.mkdir()
        sealed_restore = json.loads(
            cli("--project-root", str(sealed_restore_root),
                "export", "restore", "--bundle", str(sealed_bundle),
                *sealed_command).stdout
        )
        if sealed_restore.get("schema") != "an-kla/export-restore-result-v2" or sealed_restore.get("state") != "published":
            raise SystemExit("beta17_upgrade_sealed_restore_failed")

    print(
        "check_beta17_upgrade: OK — camino export/v1 intacto tras upgrade "
        "(create/verify/restore v1) y --seal end-to-end con el adaptador "
        "determinístico de gates: create v2 (bundle_id + manifest_sha256), "
        "verify sin clave honesto, verify con clave verified:true y restore "
        "sellado publicado, sobre consumidor actualizado 0.1.0b18"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
