"""Bandeja de entrada de ``remember`` (ADR-0063 D1, fase B1): estructura, candado, encolado y lectura.

Aquí viven las piezas que el vaciado (B2) y la custodia (B4) reutilizan tal cual:
las rutas de ``memory/inbox/``, los patrones de nombre, las definiciones únicas de
«``pending/`` vacío» e «``inflight/`` vacío», el candado de bandeja, el recolector de
``tmp/`` y la lectura de ``inbox status``. Ninguna orden llama todavía a ``enqueue``.

Convención de ``rejected/`` (la escribe el vaciado, la lee ``read_status``): la entrada
conserva su nombre y, si hay motivo, un archivo hermano ``<nombre>.reason`` con
``{"code": <código>, "reason_codes": [<código>, ...]}``. Los motivos que se leen se
reducen a un conjunto cerrado de caracteres: la bandeja no devuelve texto de recuerdos.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import time
from datetime import datetime
from typing import Any, Callable, Iterator, Mapping, NamedTuple

from . import identity_c0, lock_order
from .canonical import canonical_json, digest_json
from .custody import CustodyError, read_pointer
from .identity import IdentityError, _mutation_preflight_with_context, identity_lock
from .reader_gate import ReaderGateError
from .storage_primitives import fsync_directory
from .store import PREFIXES
from .store_errors import StoreError
from .vigency import is_active

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - plataforma sin fcntl
    fcntl = None  # type: ignore[assignment]
try:  # Windows
    import msvcrt
except ImportError:  # pragma: no cover - plataforma con fcntl
    msvcrt = None  # type: ignore[assignment]

ENTRY_SCHEMA = "an-kla/inbox-entry-v1"
STATUS_SCHEMA = "an-kla/inbox-status-v1"
INBOX_DIRNAME = "inbox"
LOCK_NAME = ".lock"
TMP_DIR, PENDING_DIR, INFLIGHT_DIR, REJECTED_DIR = "tmp", "pending", "inflight", "rejected"
REASON_SUFFIX = ".reason"

ENTRY_NAME = re.compile(r"[0-9]+-[0-9]+-[0-9a-f]{16}-[0-9a-f]{8}\.json")
MARKER_NAME = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json")
_REASON_CODE = re.compile(r"[a-z0-9_:.-]{1,80}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

KINDS = ("fact", "decision", "state")
MAX_TEXT_BYTES = 64 * 1024
MAX_TARGET_CHARS = 256
ENQUEUE_LOCK_WAIT_SECONDS = 2.0
_LOCK_BACKOFF_SECONDS = 0.01
_NAME_ATTEMPTS = 16
MAX_LISTED = 1000
_MAX_REASON_BYTES = 4096

# stream por kind (D1 «Orden»); el prefijo de id por stream es `store.PREFIXES`
_KIND_STREAM = {"fact": "facts", "decision": "facts", "state": "episodes"}
_STREAM_DEFAULT_KIND = {"facts": "fact", "episodes": "state"}

# Sin `fcntl` no hay candado compartido: se pide siempre exclusivo (más lento, igual de correcto).
SHARED_SUPPORTED = fcntl is not None


class InboxError(ValueError):
    """Error estable de bandeja; ``str(error)`` es el código y ``hint`` la pista de reintento."""

    def __init__(self, code: str, hint: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.hint = hint
        self.detail = hint  # el CLI (`main`) imprime `detail` entre paréntesis


class InboxPaths(NamedTuple):
    root: Path
    lock: Path
    tmp: Path
    pending: Path
    inflight: Path
    rejected: Path


def inbox_paths(store: Any) -> InboxPaths:
    root = Path(store.root) / INBOX_DIRNAME
    return InboxPaths(
        root, root / LOCK_NAME, root / TMP_DIR, root / PENDING_DIR, root / INFLIGHT_DIR, root / REJECTED_DIR
    )


def is_entry_name(name: str) -> bool:
    return ENTRY_NAME.fullmatch(name) is not None


def is_marker_name(name: str) -> bool:
    return MARKER_NAME.fullmatch(name) is not None


def record_id(stream: str, idempotency_key: str) -> str:
    """``<prefijo>-r-<24 hex de la clave>`` (D1 «Idempotencia»)."""

    if stream not in PREFIXES or not _DIGEST.fullmatch(idempotency_key):
        raise InboxError("inbox_record_id_invalid")
    return f"{PREFIXES[stream]}-r-{idempotency_key[7:31]}"


def stream_for_kind(kind: str) -> str:
    return _KIND_STREAM[kind]


# --- listados de nombres -----------------------------------------------------


def _dir_state(path: Path) -> str:
    """``absent``, ``present`` (directorio real) o ``unsafe`` (enlace, no-directorio o un padre que no lo es)."""

    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return "absent"
    except (NotADirectoryError, OSError) as exc:
        if isinstance(exc, NotADirectoryError) or exc.errno in (errno.ELOOP, errno.ENOTDIR):
            return "unsafe"
        raise InboxError("inbox_unavailable") from None
    return "present" if stat.S_ISDIR(mode) else "unsafe"


def root_state(store: Any) -> str:
    """Inspección única de la raíz de la bandeja y de sus padres (R2-01, R2-02, R2-05).

    Recorre de arriba abajo los componentes bajo ``store.custody_walk_root`` (el ancla del
    store, ``memory/`` e ``inbox/``; el mismo tramo que ``identity_lock``): el primero que
    falta da ``absent``; el primero que es enlace o no-directorio da ``unsafe``; si todos son
    directorios reales, ``present``. La usan ``read_status``, las definiciones de «vacío»,
    ``collect_tmp`` e ``inbox_lock``: nadie afirma «vacío» ni crea nada detrás de un enlace.
    """

    root = inbox_paths(store).root
    walk = Path(store.custody_walk_root)
    try:
        parts = root.relative_to(walk).parts
        chain = [walk.joinpath(*parts[: index + 1]) for index in range(len(parts))]
    except ValueError:  # ancla fuera de la raíz de custodia: sólo se puede juzgar `memory/` e `inbox/`
        chain = [Path(store.root), root]
    for component in chain:
        state = _dir_state(component)
        if state != "present":
            return state
    return "present"


def _names(path: Path) -> list[str]:
    """Nombres de un subdirectorio de la bandeja; ausente = vacío; enlace u otro tipo = error."""

    state = _dir_state(path)
    if state == "absent":
        return []
    if state == "unsafe":
        raise InboxError("inbox_unsafe_path")
    try:
        with os.scandir(path) as entries:
            return sorted(entry.name for entry in entries)
    except OSError:
        raise InboxError("inbox_unavailable") from None


def subdir_names(store: Any, subdir: str) -> list[str]:
    """Todos los nombres de un subdirectorio de la bandeja, sin filtrar (el vaciado clasifica con ``lstat``)."""

    return _subdir_names(store, subdir)


def _subdir_names(store: Any, subdir: str) -> list[str]:
    """Nombres de un subdirectorio vistos a través de ``root_state``: raíz ausente = vacío, insegura = error."""

    state = root_state(store)
    if state == "absent":
        return []
    if state == "unsafe":
        raise InboxError("inbox_unsafe_path")
    return _names(getattr(inbox_paths(store), subdir))


def _is_not_directory(directory: Path, name: str) -> bool:
    """``lstat`` sin abrir: todo lo que no es un directorio cuenta; un nombre que desaparece, no."""

    try:
        return not stat.S_ISDIR(os.lstat(directory / name).st_mode)
    except FileNotFoundError:
        return False
    except OSError:
        raise InboxError("inbox_unavailable") from None


def _counted_names(directory: Path, names: list[str], matches: Callable[[str], bool]) -> list[str]:
    return [name for name in names if matches(name) and _is_not_directory(directory, name)]


def _counted(store: Any, subdir: str, matches: Callable[[str], bool]) -> list[str]:
    return _counted_names(getattr(inbox_paths(store), subdir), _subdir_names(store, subdir), matches)


def entry_names(store: Any) -> list[str]:
    """Entradas de ``pending/``: nombres que casan el patrón y no son directorio, orden de nombre.

    Un directorio con nombre de entrada se ignora (D1 «Directorios»). Un FIFO, enlace, hardlink o
    archivo con ese nombre SÍ cuenta: el vaciado lo envía a ``rejected/`` y la custodia espera.
    Sólo se hace ``lstat``, nunca se abre (un FIFO colgaría la lectura).
    """

    return _counted(store, PENDING_DIR, is_entry_name)


def marker_names(store: Any) -> list[str]:
    """Marcadores de ``inflight/``: nombres que casan el patrón de marcador y no son directorio."""

    return _counted(store, INFLIGHT_DIR, is_marker_name)


def pending_is_empty(store: Any) -> bool:
    """«``pending/`` vacío» (D1 «Directorios»): sin nombres que casen el patrón de entrada."""

    return not entry_names(store)


def inflight_is_empty(store: Any) -> bool:
    """«``inflight/`` vacío»: sin nombres de marcador."""

    return not marker_names(store)


# --- candado de bandeja ------------------------------------------------------


def _try_lock(fd: int, exclusive: bool) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                return False
            raise
        return True
    if msvcrt is not None:  # pragma: no cover - sólo Windows
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    raise InboxError("inbox_lock_unsupported")  # pragma: no cover


def _unlock(fd: int) -> None:
    with contextlib.suppress(OSError):
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:  # pragma: no cover - sólo Windows
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _ensure_layout(store: Any) -> None:
    paths = inbox_paths(store)
    if root_state(store) == "unsafe":  # un componente enlazado: no se crea nada, ni fuera del ancla
        raise InboxError("inbox_unsafe_path")
    created = False
    for directory in (paths.root, paths.tmp, paths.pending, paths.inflight, paths.rejected):
        state = _dir_state(directory)
        if state == "unsafe":
            raise InboxError("inbox_unsafe_path")
        if state == "absent":
            # Otro proceso pudo crearlo entre el lstat y el mkdir: se tolera y se re-inspecciona.
            directory.mkdir(parents=directory is paths.root, exist_ok=True)
            if _dir_state(directory) != "present" or (directory is paths.root and root_state(store) != "present"):
                raise InboxError("inbox_unsafe_path")
            created = True
    if created:
        for directory in (paths.root, paths.tmp, paths.pending, paths.inflight, paths.rejected):
            fsync_directory(directory)
        fsync_directory(paths.root.parent)


def ensure_layout(store: Any) -> None:
    """Crea (si faltan) ``tmp/``, ``pending/``, ``inflight/`` y ``rejected/``; nunca detrás de un enlace."""

    _ensure_layout(store)


def _open_lock_file(path: Path, flags: int) -> int:
    """Abre ``.lock`` como ``reader_gate._open_gate``: archivo regular, no enlace, ``st_nlink == 1``.

    Cualquier otra cosa es ``inbox_unsafe_path``; ningún ``OSError`` crudo (con ruta) sale de aquí.
    """

    try:
        fd = os.open(path, flags, 0o600)
    except FileNotFoundError:
        raise InboxError("inbox_absent") from None
    except FileExistsError:  # sólo con O_EXCL: otro proceso creó el `.lock` entre el intento y la creación
        raise InboxError("inbox_lock_exists") from None
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.EISDIR, errno.ENOTDIR, errno.EMLINK):
            raise InboxError("inbox_unsafe_path") from None
        raise InboxError("inbox_lock_unavailable") from None
    try:
        info = os.fstat(fd)
    except OSError:
        os.close(fd)
        raise InboxError("inbox_lock_unavailable") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise InboxError("inbox_unsafe_path")
    if hasattr(os, "fchmod"):  # un `.lock` preexistente más permisivo se normaliza, como `reader_gate`
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            os.close(fd)
            raise InboxError("inbox_lock_unavailable") from None
    return fd


def _open_lock_creating_only_it(path: Path, flags: int) -> int:
    """Abre ``.lock``; si falta, crea sólo él (``O_CREAT|O_EXCL``, 0600) y aplica las mismas comprobaciones."""

    for _ in range(_NAME_ATTEMPTS):
        try:
            return _open_lock_file(path, flags)
        except InboxError as exc:
            if exc.code != "inbox_absent":
                raise
        try:
            return _open_lock_file(path, flags | os.O_CREAT | os.O_EXCL)
        except InboxError as exc:
            if exc.code != "inbox_lock_exists":
                raise
    raise InboxError("inbox_lock_unavailable")


@contextlib.contextmanager
def inbox_lock(
    store: Any, *, exclusive: bool, wait_seconds: float = 0.0, create: bool = True, layout: bool = True
) -> Iterator[bool]:
    """Candado de bandeja con plazo. Rinde ``True`` si lo tomó en exclusivo.

    Compartido salvo donde no hay ``flock`` compartido (entonces es exclusivo siempre).
    Falla con ``InboxError("inbox_busy")`` si no lo obtiene en ``wait_seconds``. Falla
    cerrado con ``LockOrderError`` si el contexto ya tiene ``identity_lock`` o
    ``write_lock``. Con ``create=False`` no crea nada y exige que la bandeja exista. Con
    ``layout=False`` (la custodia) tampoco crea la estructura: exige la raíz y sólo crea el
    ``.lock`` si falta.
    """

    lock_order.require_inbox_allowed(store)
    paths = inbox_paths(store)
    if create and layout:
        _ensure_layout(store)
    else:
        state = root_state(store)
        if state != "present":
            raise InboxError("inbox_unsafe_path" if state == "unsafe" else "inbox_absent")
    effective_exclusive = exclusive or not SHARED_SUPPORTED
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    if create and not layout:
        fd = _open_lock_creating_only_it(paths.lock, flags & ~os.O_CREAT)
    else:
        fd = _open_lock_file(paths.lock, flags if create else flags & ~os.O_CREAT)
    try:
        if os.fstat(fd).st_size == 0 and msvcrt is not None:  # pragma: no cover - sólo Windows
            os.write(fd, b"0")
        end = time.monotonic() + wait_seconds
        while not _try_lock(fd, effective_exclusive):
            if time.monotonic() >= end:
                raise InboxError("inbox_busy", "reintenta en unos segundos; un export o relocate puede estar en curso")
            time.sleep(_LOCK_BACKOFF_SECONDS)
        try:
            with lock_order.holding(lock_order.INBOX):
                yield effective_exclusive
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


# --- recolector de tmp/ ------------------------------------------------------


def collect_tmp(store: Any) -> dict[str, Any]:
    """Borra los temporales huérfanos de ``tmp/`` con el candado exclusivo y sin esperar.

    Sin reloj: un candado exclusivo sólo se obtiene si ningún encolador vive (cada uno
    tiene el compartido durante todo el encolado y el SO lo suelta al morir, también con
    ``SIGKILL``), así que todo lo que hay en ``tmp/`` es huérfano. Si está ocupado no
    recolecta. Lo llamará el vaciado antes de pedir ``write_lock``. No crea la bandeja.
    """

    lock_order.require_inbox_allowed(store)  # antes de cualquier salida anticipada
    paths = inbox_paths(store)
    state = root_state(store)
    if state == "absent":
        return {"state": "absent", "removed": 0, "errors": 0}
    if state == "unsafe":
        raise InboxError("inbox_unsafe_path")
    # R3-03: con la raíz presente y sin `.lock` (layout hecho a mano) se crea con las mismas garantías.
    create = not os.path.lexists(paths.lock)
    try:
        with inbox_lock(store, exclusive=True, wait_seconds=0.0, create=create):
            return _remove_tmp_contents(paths.tmp)
    except InboxError as exc:
        if exc.code == "inbox_busy":
            return {"state": "busy", "removed": 0, "errors": 0}
        raise


def _remove_tmp_contents(tmp: Path) -> dict[str, Any]:
    state = _dir_state(tmp)
    if state == "unsafe":  # R3-02: nunca se informa «recolectado» sin haber inspeccionado `tmp/`
        raise InboxError("inbox_unsafe_path")
    if state == "absent":
        return {"state": "collected", "removed": 0, "errors": 0}
    removed = errors = 0
    with os.scandir(tmp) as scan:
        children = [(entry.path, entry.is_dir(follow_symlinks=False)) for entry in scan]
    for path, is_dir in children:
        try:
            if is_dir:
                shutil.rmtree(path)
            else:
                os.unlink(path)
            removed += 1
        except FileNotFoundError:
            continue
        except OSError:
            errors += 1
    if removed:
        fsync_directory(tmp)
    return {"state": "collected", "removed": removed, "errors": errors}


# --- encolado ----------------------------------------------------------------


def resolve_kind(store: Any, kind: str | None, target_id: str | None) -> tuple[str, bool]:
    """``kind`` y si fue explícito (ADENDA 1 del mandato B1).

    Sin ``--kind`` y con target, se lee (sin candado ni escritura) el snapshot de
    ``CURRENT``: si el target está en un solo stream y vigente, toma su
    ``an_kla_envelope.kind`` o, si es legado, el de su stream (``facts`` -> ``fact``,
    ``episodes`` -> ``state``); si no, ``fact``, y el vaciado lo rechaza con
    ``invalid_supersede_target``. La lectura toma el gate de lectores compartido (el
    último del orden, pedido antes de cualquier candado de bandeja); cualquier fallo de
    lectura, incluido el del gate, cae en ``fact``.
    """

    if kind is not None:
        if kind not in KINDS:
            raise InboxError("inbox_kind_invalid")
        return kind, True
    if target_id is None:
        return "fact", False
    try:
        snapshot = store.snapshot()
        found = [
            (stream, record)
            for stream in ("facts", "events", "episodes")
            for record in snapshot.records.get(stream, [])
            if isinstance(record, Mapping) and str(record.get("id", "")) == target_id
        ]
    except (StoreError, ReaderGateError, OSError, ValueError, KeyError, AttributeError):
        return "fact", False
    if len(found) != 1 or not is_active(found[0][1]):
        return "fact", False
    stream, record = found[0]
    envelope = record.get("an_kla_envelope")
    declared = envelope.get("kind") if isinstance(envelope, Mapping) else None
    if declared in KINDS:
        return declared, False
    return _STREAM_DEFAULT_KIND.get(stream, "fact"), False


def payload_digest(text: str, kind: str, target_id: str | None) -> str:
    return digest_json({"text": text, "kind": kind, "target": target_id})


def _entry_name(time_ns: int, pid: int, key: str, token: str) -> str:
    return f"{time_ns}-{pid}-{key[7:23]}-{token}.json"


def _write_exclusive(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def enqueue(
    store: Any,
    text: str,
    *,
    kind: str | None = None,
    target_id: str | None = None,
    idempotency_key: str | None = None,
    env: Mapping[str, str] | None = None,
    clock: Callable[[], datetime] | None = None,
    wait_seconds: float = ENQUEUE_LOCK_WAIT_SECONDS,
    time_ns: Callable[[], int] = time.time_ns,
    token: Callable[[], str] = lambda: secrets.token_hex(4),
    replace: Callable[[Any, Any], None] = os.replace,
    preflight: Callable[[Any], Any] = _mutation_preflight_with_context,
) -> dict[str, Any]:
    """Encola un recuerdo en ``memory/inbox/pending/`` (D1 «Encolar»). Nadie lo llama aún.

    Todo lo que puede fallar sin tocar disco falla antes de crear nada: el preflight
    gobernado, el texto, el ``kind`` y la identidad C0 (sus errores salen tal cual).
    ``env`` y ``clock`` (identidad y ``enqueued_at``), ``time_ns`` y ``token`` (nombre),
    ``replace`` (publicación) y ``preflight`` son inyectables; las pruebas los usan para
    forzar EXDEV/ENOSPC, colisiones de nombre y un cambio de custodia entre preflights.
    """

    lock_order.require_inbox_allowed(store)
    preflight(store)
    seen_custody = _custody_view(store)
    data_text = _validated_text(text)
    if target_id is not None and (
        not isinstance(target_id, str) or not 0 < len(target_id) <= MAX_TARGET_CHARS
    ):
        raise InboxError("inbox_target_invalid")
    resolved_kind, explicit = resolve_kind(store, kind, target_id)
    identity = identity_c0.build_identity(store.project_root, env)
    if idempotency_key is None:
        key = identity_c0.derive_idempotency_key(identity, resolved_kind, data_text, target_id)
    elif isinstance(idempotency_key, str) and _DIGEST.fullmatch(idempotency_key):
        key = idempotency_key
    else:
        raise InboxError("inbox_idempotency_key_invalid", "la clave debe ser sha256:<64 hex>")
    paths = inbox_paths(store)
    started = time.monotonic()
    with inbox_lock(store, exclusive=False, wait_seconds=wait_seconds):
        # R2-03: `identity_lock` espera dentro del mismo plazo; vencido, `identity_lock_busy` sin dejar entrada.
        identity_wait = max(0.0, wait_seconds - (time.monotonic() - started))
        # R1-01: una reubicación en curso tiene `identity_lock` durante todo el cambio de custodia;
        # tomarlo aquí (bandeja -> identidad, orden permitido) bloquea la publicación y, al terminar,
        # el preflight repetido falla sin dejar entrada, también con la bandeja ausente al empezar ella.
        with identity_lock(store, wait_seconds=identity_wait):
            _custody_preflight(store, preflight, seen_custody)  # la custodia pudo cambiar mientras se esperaba
            envelope = identity_c0.build_envelope(identity, resolved_kind, key, clock)
            entry: dict[str, Any] = {
                "schema": ENTRY_SCHEMA,
                "text": data_text,
                "kind": resolved_kind,
                "kind_explicit": explicit,
                "envelope": envelope,
                "idempotency_key": key,
                "payload_sha256": payload_digest(data_text, resolved_kind, target_id),
            }
            if target_id is not None:
                entry["target_id"] = target_id
            payload = canonical_json(entry)
            entry_name = _publish(paths, payload, key, time_ns, token, replace)
    result: dict[str, Any] = {
        "state": "queued",
        "entry": entry_name,
        "kind": resolved_kind,
        "kind_explicit": explicit,
        "idempotency_key": key,
        "payload_sha256": entry["payload_sha256"],
        "enqueued_at": envelope["enqueued_at"],
    }
    if target_id is None:
        result["record_id"] = record_id(stream_for_kind(resolved_kind), key)
    return result


def _custody_view(store: Any) -> Any:
    """La custodia tal como la ve un encolado: el puntero (o ``None``); sólo se compara, nunca se interpreta."""

    try:
        return read_pointer(store.project_root)
    except CustodyError:
        return "unreadable"


def _custody_preflight(store: Any, preflight: Callable[[Any], Any], seen_custody: Any) -> Any:
    """El preflight repetido bajo el candado, con ``store_root_divergence`` si la custodia cambió de verdad.

    Tras una reubicación el store obsoleto no ve su identidad (``store_identity_invalid``). Sólo se
    traduce si el puntero ya no es el que vio el primer preflight de este mismo encolado; una
    identidad corrupta con la custodia intacta sigue siendo ``store_identity_invalid`` (R2-02).
    """

    try:
        return preflight(store)
    except IdentityError as exc:
        if str(exc) == "store_identity_invalid" and _custody_view(store) != seen_custody:
            raise CustodyError("store_root_divergence") from None
        raise


def _validated_text(text: Any) -> str:
    if not isinstance(text, str) or text == "":
        raise InboxError("inbox_text_empty")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise InboxError("inbox_text_invalid") from None
    if size > MAX_TEXT_BYTES:
        raise InboxError("inbox_text_too_large", f"máximo {MAX_TEXT_BYTES} bytes UTF-8")
    return text


def _require_private_temporary(path: Path) -> None:
    """El temporal debe ser un archivo regular con un solo nombre justo antes de publicarlo.

    Un ``st_nlink != 1`` se publicaría como ``queued`` y el vaciado (paso 2) lo rechazaría
    como ``inbox_entry_unsafe``; si no, el temporal queda en ``tmp/`` para el recolector.
    """

    try:
        info = os.lstat(path)
    except OSError:
        raise InboxError("inbox_unsafe_path") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise InboxError("inbox_unsafe_path")


def _publish(
    paths: InboxPaths,
    payload: bytes,
    key: str,
    time_ns: Callable[[], int],
    token: Callable[[], str],
    replace: Callable[[Any, Any], None],
) -> str:
    """Temporal con ``O_EXCL`` y fsync, ``lstat`` del destino, ``os.replace`` y fsync de ``pending/``.

    Si ``replace`` falla el temporal queda en ``tmp/`` para el recolector y el error sale
    tal cual. Nunca publica sobre un nombre existente (``os.replace`` sobrescribe en
    silencio); no se usa ``os.link``: ``st_nlink`` valdría 2 un instante.
    """

    pid = os.getpid()
    stamp = time_ns()
    tmp_path = None
    for _ in range(_NAME_ATTEMPTS):
        candidate = paths.tmp / _entry_name(stamp, pid, key, token())
        try:
            _write_exclusive(candidate, payload)
        except FileExistsError:
            continue
        tmp_path = candidate
        break
    if tmp_path is None:
        raise InboxError("inbox_name_exhausted")
    for _ in range(_NAME_ATTEMPTS):
        name = _entry_name(stamp, pid, key, token())
        destination = paths.pending / name
        try:
            os.lstat(destination)
        except FileNotFoundError:
            _require_private_temporary(tmp_path)
            replace(tmp_path, destination)
            fsync_directory(paths.pending)
            return name
    raise InboxError("inbox_name_exhausted")


# --- inbox status (sólo lectura) ---------------------------------------------


def _listing(names: list[str]) -> dict[str, Any]:
    return {"count": len(names), "names": names[:MAX_LISTED], "truncated": len(names) > MAX_LISTED}


def _read_reason(directory: Path, name: str) -> dict[str, Any]:
    """Motivo de un rechazo desde su archivo ``.reason``; nunca bloquea ni devuelve texto libre."""

    path = directory / (name + REASON_SUFFIX)
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return {"reason": None, "reason_codes": []}
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return {"reason": None, "reason_codes": []}
        raw = os.read(fd, _MAX_REASON_BYTES + 1)
    finally:
        os.close(fd)
    try:
        value = json.loads(raw) if len(raw) <= _MAX_REASON_BYTES else None
    except (ValueError, UnicodeError):
        value = None
    if not isinstance(value, dict):
        return {"reason": None, "reason_codes": []}
    code = value.get("code")
    codes = value.get("reason_codes")
    return {
        "reason": code if isinstance(code, str) and _REASON_CODE.fullmatch(code) else None,
        "reason_codes": [c for c in codes if isinstance(c, str) and _REASON_CODE.fullmatch(c)][:32]
        if isinstance(codes, list)
        else [],
    }


def read_status(store: Any) -> dict[str, Any]:
    """Estado de la bandeja para ``inbox status``: sólo lectura, sin candados y sin crear nada.

    Con ``memory/inbox/`` ausente informa ``inbox: "absent"`` y listas vacías. Sólo lista
    nombres (nunca abre una entrada: un FIFO colgaría la lectura); de ``rejected/`` lee,
    acotado y sin bloquear, el archivo ``.reason`` de cada entrada. Es una vista sin
    candado: un encolado o vaciado concurrente puede moverla entre dos lecturas.
    """

    paths = inbox_paths(store)
    top = root_state(store)
    dirs = {"tmp": paths.tmp, "pending": paths.pending, "inflight": paths.inflight, "rejected": paths.rejected}
    states: dict[str, str] = {}
    names: dict[str, list[str]] = {}
    for label, directory in dirs.items():
        state = top if top != "present" else _dir_state(directory)  # raíz ausente o insegura: no se desciende
        names[label] = []
        if state == "present":
            try:
                names[label] = _names(directory)
            except InboxError:
                state = "unsafe"
        states[label] = state
    rejected = []
    for name in names["rejected"]:
        if name.endswith(REASON_SUFFIX):
            continue
        rejected.append({"name": name, **_read_reason(paths.rejected, name)})
    pending_entries = _counted_names(paths.pending, names["pending"], is_entry_name)
    inflight_markers = _counted_names(paths.inflight, names["inflight"], is_marker_name)
    counted_pending, counted_inflight = set(pending_entries), set(inflight_markers)
    return {
        "schema": STATUS_SCHEMA,
        "untrusted_memory_data": True,
        "inbox": top,
        "directories": states,
        "pending": _listing(pending_entries),
        "inflight": _listing(inflight_markers),
        "rejected": {
            "count": len(rejected),
            "entries": rejected[:MAX_LISTED],
            "truncated": len(rejected) > MAX_LISTED,
        },
        "tmp": _listing(names["tmp"]),
        "ignored": {
            "pending": _listing([n for n in names["pending"] if n not in counted_pending]),
            "inflight": _listing([n for n in names["inflight"] if n not in counted_inflight]),
        },
    }


__all__ = [
    "ENTRY_SCHEMA", "InboxError", "InboxPaths", "KINDS", "MAX_TEXT_BYTES", "STATUS_SCHEMA",
    "collect_tmp", "ensure_layout", "enqueue", "entry_names", "inbox_lock", "inbox_paths", "inflight_is_empty",
    "is_entry_name", "is_marker_name", "marker_names", "payload_digest", "pending_is_empty",
    "read_status", "record_id", "resolve_kind", "root_state", "stream_for_kind", "subdir_names",
]
