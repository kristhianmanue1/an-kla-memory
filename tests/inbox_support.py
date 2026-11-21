"""Apoyo de las pruebas de la bandeja (ADR-0063 D1): proyecto Git con store, entorno y candado ajeno."""

from __future__ import annotations

import atexit
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

from an_kla.store import MemoryStore
from tests import write_commit_scenarios as scenarios
from tests import proc_support

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
AGENT_ENV = {
    "AN_KLA_AGENT_NAME": "ankla-ejecutor-1",
    "AN_KLA_AGENT_CLI": "claude-code",
    "AN_KLA_AGENT_MODEL": "claude-sonnet-5-5",
    "AN_KLA_AGENT_ROLE": "ejecutor",
    "AN_KLA_SESSION_ID": "0a92bdfb-286a-44b5-8c24-8d7a1332c6b6",
}
# Mantiene un candado `flock` en otro proceso hasta que se cierra su stdin.
HOLDER = (
    "import fcntl, os, sys\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX if sys.argv[2] == 'ex' else fcntl.LOCK_SH)\n"
    "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
    "sys.stdin.read()\n"
)


def run_git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        check=True, capture_output=True, env={**os.environ, **GIT_ENV},
    )


#: Plantilla de repo por proceso de prueba (ADR-0074 §4): ``init`` y el commit base se hacen una vez; cada ``make_project`` la copia sin lanzar nada.
#: ``AN_KLA_TEST_NO_REPO_TEMPLATE=1`` vuelve al camino de siempre (para medir antes y después).
_TEMPLATE: dict[str, Any] = {}


def tree_digest(root: Path) -> str:
    """sha256 del árbol: rutas, tipo, modo y contenido (o destino del enlace) de cada entrada, en orden."""

    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            digest.update(f"L {rel} {os.readlink(path)}\n".encode())
        elif path.is_dir():
            digest.update(f"D {rel}\n".encode())
        else:
            digest.update(f"F {rel} {path.stat().st_mode & 0o777:o} ".encode() + hashlib.sha256(path.read_bytes()).digest() + b"\n")
    return digest.hexdigest()


def _build_template() -> None:
    if "base" in _TEMPLATE:  # regenerar: la plantilla tocada se tira
        shutil.rmtree(_TEMPLATE["base"], ignore_errors=True)
    else:
        atexit.register(lambda: shutil.rmtree(_TEMPLATE.get("base", ""), ignore_errors=True))
    base = Path(tempfile.mkdtemp(prefix="repo-template-")).resolve()
    run_git(base, "init", "-q")
    run_git(base, "commit", "-q", "--allow-empty", "-m", "base")
    locks = list(base.rglob("*.lock"))
    if locks:
        raise RuntimeError(f"la plantilla de repo quedó con candados: {locks}")
    _TEMPLATE.update(base=base, digest=tree_digest(base / ".git"))


def make_project(path: Path) -> Path:
    """Directorio con un repo Git y un commit vacío (C0 exige un repo).

    Copia la plantilla del proceso (``shutil.copytree`` del ``.git``, sin candados y sin lanzar ningún proceso). Se protege con una huella, no con
    permisos: antes de cada copia se comprueba el sha256 de su árbol y, si no coincide, se regenera. El ``repo.id`` local depende de la ruta, así que
    sigue siendo distinto en cada copia."""

    if os.environ.get("AN_KLA_TEST_NO_REPO_TEMPLATE") == "1":
        run_git(path, "init", "-q")
        run_git(path, "commit", "-q", "--allow-empty", "-m", "base")
        return path
    if "base" not in _TEMPLATE or tree_digest(_TEMPLATE["base"] / ".git") != _TEMPLATE["digest"]:
        _build_template()
    shutil.copytree(_TEMPLATE["base"] / ".git", path / ".git", ignore=shutil.ignore_patterns("*.lock"))
    return path


class InboxCase(unittest.TestCase):
    """Un proyecto Git temporal con un store inicializado; el reloj y el entorno son del test."""

    init_store = True

    def setUp(self) -> None:
        patcher = mock.patch.dict(os.environ, GIT_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory(prefix="inbox-")
        self.addCleanup(temp.cleanup)
        self.project = make_project(Path(temp.name).resolve())
        self.store = MemoryStore(self.project)
        if self.init_store:
            self.store.initialize()
        self.inbox = Path(self.store.root) / "inbox"

    def commit_record(self, record_id: str, *, stream: str = "facts", **record: Any) -> str:
        """Añade un record vigente (con los campos extra dados) y devuelve la revisión."""

        base = self.store.read_current()
        candidate = scenarios.proposal_v1(base, record_id, **record)
        candidate["stream"] = stream
        authority = scenarios.authority_for(candidate)
        planning = self.store.plan_write(candidate, authority)
        return self.store.commit_write_plan(
            expected_current_hash=base, plan=planning["plan"], proposal=candidate,
            authority=authority, decision=planning["decision"],
        )["revision"]

    def hold_lock(self, mode: str) -> subprocess.Popen:
        """Otro proceso toma ``memory/inbox/.lock`` (``ex`` o ``sh``) hasta cerrar su stdin."""

        self.inbox.mkdir(exist_ok=True)
        child = proc_support.spawn_for(self,
            [sys.executable, "-I", "-c", HOLDER, str(self.inbox / ".lock"), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.release, child)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    @staticmethod
    def release(child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.stdin.close()
            child.wait(timeout=10)
        child.stdout.close()


class EntryFactory:
    """Fabrica entradas ``inbox-entry-v1`` válidas sin invocar ``git`` por entrada.

    La identidad C0 se construye una vez; cada entrada lleva su sobre, su clave y su
    ``payload_sha256`` como las escribe ``enqueue``. Los nombres crecen con el contador, así
    que el orden de vaciado es el de creación. Sirve para los 1000 pendientes del criterio 8,
    para entradas rotas y para los vaciados que no prueban el encolado.
    """

    def __init__(self, store: MemoryStore, env: dict[str, str] | None = None, start_ns: int = 10**18) -> None:
        from an_kla import identity_c0

        self.store = store
        self.identity_c0 = identity_c0
        self.env = dict(AGENT_ENV if env is None else env)
        self.identity = identity_c0.build_identity(store.project_root, self.env)
        self.counter = start_ns
        self.pending = Path(store.root) / "inbox" / "pending"

    def other_writer(self, **env: str) -> "EntryFactory":
        clone = EntryFactory.__new__(EntryFactory)
        clone.__dict__.update(self.__dict__)
        clone.env = {**self.env, **env}
        clone.identity = self.identity_c0.build_identity(self.store.project_root, clone.env)
        return clone

    def entry(
        self, text: str, *, kind: str = "fact", target_id: str | None = None, kind_explicit: bool | None = None,
        key: str | None = None, slot: str | None = None,
    ) -> dict[str, Any]:
        from an_kla import inbox

        key = key or self.identity_c0.derive_idempotency_key(self.identity, kind, text, target_id, slot)
        envelope = self.identity_c0.build_envelope(self.identity, kind, key)
        data: dict[str, Any] = {
            "schema": inbox.ENTRY_SCHEMA if slot is None else inbox.ENTRY_SCHEMA_V2, "text": text, "kind": kind,
            "kind_explicit": bool(kind_explicit),
            "envelope": envelope, "idempotency_key": key,
            "payload_sha256": inbox.payload_digest(text, kind, target_id, slot),
        }
        if target_id is not None:
            data["target_id"] = target_id
        if slot is not None:
            data["slot"] = slot  # ADR-0065 §3: inbox-entry-v2
        return data

    def name_for(self, data: dict[str, Any]) -> str:
        self.counter += 1000
        return f"{self.counter}-{os.getpid()}-{data['idempotency_key'][7:23]}-{self.counter % 0xFFFFFFFF:08x}.json"

    def write(self, text: str, **options: Any) -> str:
        """Escribe una entrada válida en ``pending/`` y devuelve su nombre."""

        from an_kla.canonical import canonical_json

        data = self.entry(text, **options)
        name = self.name_for(data)
        self.pending.mkdir(parents=True, exist_ok=True)
        (self.pending / name).write_bytes(canonical_json(data))
        return name

    def write_raw(self, payload: bytes, key_hint: str = "0" * 16) -> str:
        """Escribe bytes arbitrarios con un nombre de entrada válido (entrada corrupta)."""

        self.counter += 1000
        name = f"{self.counter}-{os.getpid()}-{key_hint}-{self.counter % 0xFFFFFFFF:08x}.json"
        self.pending.mkdir(parents=True, exist_ok=True)
        (self.pending / name).write_bytes(payload)
        return name

    def fresh_name(self) -> str:
        self.counter += 1000
        return f"{self.counter}-{os.getpid()}-{'0' * 16}-{self.counter % 0xFFFFFFFF:08x}.json"


def hold_flock(path: Path, mode: str = "ex") -> subprocess.Popen:
    """Un proceso ajeno toma un ``flock`` sobre ``path`` hasta cerrar su stdin (ver ``InboxCase.release``)."""

    child = proc_support.spawn(
        [sys.executable, "-I", "-c", HOLDER, str(path), mode],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    assert child.stdout.readline().strip() == "ready"
    return child
