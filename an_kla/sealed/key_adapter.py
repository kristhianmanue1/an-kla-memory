"""Runner seguro del adaptador externo de claves — T3 de issue #46.

Norma vinculante: ``docs/architecture/0042-sealed-export-v1.md`` §4
(ejecución segura congelada en Ronda 4) y §5 (superficie de error).

Esta fase SOLO es el runner: ejecuta el proceso adaptador externo que
provee el caller (``--key-adapter``; superficie CLI en T4) y hace cumplir
el contrato JSON cerrado por stdio (``an-kla/sealing-adapter-contract-v1``).
NO implementa bundle sellado ni manifiesto v2 (T4/T5).

Contrato por stdio (conjunto de claves EXACTO por operación):

- ``wrap``   → in ``{"op": ..., "cek_b64": ...}``
               out ``{"wrapped_cek": ..., "adapter_id": ...}``
- ``unwrap`` → in ``{"op": ..., "wrapped_cek": ...}``
               out ``{"cek_b64": ...}``

Cualquier clave extra, ausente o de tipo incorrecto en la SALIDA es
``sealing_adapter_error``. La ENTRADA la construye el runner y es cerrada
por construcción (métodos :meth:`SealingAdapterRunner.wrap_cek` /
:meth:`SealingAdapterRunner.unwrap_cek`).

Reglas congeladas implementadas aquí (ADR §4, "ejecución segura"):

- **argv estructurado, sin shell**: ``argv = [bin, *args]`` con
  ``Popen(list, shell=False)`` — jamás ``sh -c``, sin interpolación ni
  expansión del entorno shell (cumplimiento literal del ADR).
- **Runner basado en ``Popen``** con **lecturas incrementales y
  acocadas** (NO ``subprocess.run`` con captura ilimitada): stdin 8 KiB,
  stdout 64 KiB, stderr 8 KiB. Exceder cualquier límite es
  ``sealing_adapter_error`` con terminación inmediata del árbol.
  ``stderr`` se DESCARTA: su contenido jamás se propaga a mensajes de
  error, resultados ni logs (podría filtrar secretos del host adaptador).
- **Timeout total** de 30 s por invocación (configurable, tope ADR): al
  expirar, terminación del árbol y ``sealing_adapter_error``.
- **Higiene del proceso**: ``close_fds=True`` (sólo stdio conectado),
  pipes cerrados y proceso reapado en TODA salida (éxito, error, timeout,
  límite), terminación de **grupo/árbol** POSIX (grupo propio +
  ``killpg``) con escalada **TERM → 2 s de gracia → KILL**; en Windows,
  terminación de árbol vía Job Object. stdout y stderr se leen
  **CONCURRENTEMENTE** (un thread por pipe): un adaptador verboso en
  stderr no puede bloquear la lectura de stdout ni viceversa.
- **Exit ≠ 0 = ``sealing_adapter_error`` AUNQUE el JSON de stdout sea
  válido**; el éxito exige exit 0 Y JSON cerrado válido.
- **Payloads de error JAMÁS embeben stdout/stderr del adaptador**: sólo
  el hecho y el código canónico (sin oráculo, sin fuga del host).
- **Entorno mínimo con allowlist explícita** (F3): el adaptador NO hereda
  el entorno del proceso AN-KLA. El runner construye ``PATH`` +
  localización básica y añade EXCLUSIVAMENTE las variables cuyo NOMBRE
  declaró el operador en ``env_allowlist``. Sin allowlist, sin variables
  extra. Los valores allowlisted viajan por el entorno del subproceso,
  jamás por argv/logs/resultados (la allowlist no se persiste).
- **Pre-vuelo por schema** (no por el runner): ``wrapped_cek`` ≤ 4096
  chars base64 y ``cek_b64`` exactamente 32 bytes decodificados con
  base64 canónico con padding — la petición más grande posible cabe de
  sobra en el límite de stdin de 8 KiB.
- **``wrapped_cek`` opaco**: el core jamás lo interpreta (sólo valida el
  techo de longitud pre-vuelo); ``adapter_id`` es metadato de diagnóstico
  con gramática cerrada (ADR §6), nunca autoridad.

Códigos canónicos EXACTOS (ADR §5) — sin ``cryptography`` en ningún
camino de este módulo (el runner es stdlib pura; la criptografía vive en
el adaptador externo y en T4):

- ``sealing_adapter_error``  — adaptador falla/crash/timeout/forma inválida.
- ``sealing_adapter_required`` — adaptador ausente o comando no especificado.

F7: la CEK viaja al adaptador por stdin local (y sólo entonces) y regresa
por stdout del adaptador en ``unwrap``; el runner no serializa ni escribe
la CEK en mensajes de error, excepciones ni logs.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import select
import signal
import subprocess
import sys
import threading

__all__ = [
    "ADAPTER_STDIN_LIMIT",
    "ADAPTER_STDOUT_LIMIT",
    "ADAPTER_STDERR_LIMIT",
    "ADAPTER_TIMEOUT_SECONDS",
    "ADAPTER_TERM_GRACE_SECONDS",
    "ADAPTER_WRAPPED_CEK_MAX_CHARS",
    "CEK_LENGTH",
    "SEALING_ADAPTER_ERROR_CODE",
    "SEALING_ADAPTER_REQUIRED_CODE",
    "SealingAdapterError",
    "SealingAdapterRequiredError",
    "SealingAdapterRunner",
    "AdapterResult",
    "validate_adapter_id",
]

#: Código canónico ADR §5 — adaptador falla/crash/timeout/forma inválida.
SEALING_ADAPTER_ERROR_CODE = "sealing_adapter_error"

#: Código canónico ADR §5 — adaptador ausente / comando no especificado.
SEALING_ADAPTER_REQUIRED_CODE = "sealing_adapter_required"

#: Límite de stdin del adaptador: 8 KiB (ADR §4, aplicado por el runner).
ADAPTER_STDIN_LIMIT = 8 * 1024

#: Límite de stdout del adaptador: 64 KiB (ADR §4, aplicado por el runner).
ADAPTER_STDOUT_LIMIT = 64 * 1024

#: Límite de stderr del adaptador: 8 KiB (ADR §4; contenido DESCARTADO).
ADAPTER_STDERR_LIMIT = 8 * 1024

#: Timeout total por invocación: 30 s (ADR §4). Tope por defecto del ADR.
ADAPTER_TIMEOUT_SECONDS = 30.0

#: Escalada POSIX TERM → ``2 s`` de gracia → KILL (ADR §4, congelada Ronda 4).
ADAPTER_TERM_GRACE_SECONDS = 2.0

#: Techo pre-vuelo por schema para ``wrapped_cek`` (chars base64) — ADR §4.
ADAPTER_WRAPPED_CEK_MAX_CHARS = 4096

#: Longitud exacta de la CEK (bytes) — ADR §1/§4: 32 o ``sealing_adapter_error``.
CEK_LENGTH = 32

# Mensajes de error CERRADOS: sin stdout/stderr del adaptador, sin material
# de la CEK ni del blob (F7), sin distinguir la causa interna (sin oráculo).
_ADAPTER_ERROR_MSG = "sealing key adapter failed (no further detail)"
_ADAPTER_TIMEOUT_MSG = "sealing key adapter timed out (no further detail)"
_ADAPTER_IO_LIMIT_MSG = "sealing key adapter exceeded i/o limits (no further detail)"
_ADAPTER_REQUIRED_MSG = (
    "sealing requires an external key adapter: no adapter command was specified"
)

#: Gramática cerrada de ``adapter_id`` (ADR §6, F4): ASCII,
#: ``^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$``, ``.``/``..`` rechazados.
_ADAPTER_ID_MIN = 1
_ADAPTER_ID_MAX = 64
_ADAPTER_ID_ALPHABET = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)
_ADAPTER_ID_FIRST = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
)


class SealingAdapterError(RuntimeError):
    """Fallo del adaptador externo — cerrado, sin oráculo ni degradación.

    Código canónico ADR §5: ``sealing_adapter_error``. El mensaje NUNCA
    embebe stdout/stderr del adaptador ni material de la CEK/blob.
    """

    ERROR_CODE = SEALING_ADAPTER_ERROR_CODE


class SealingAdapterRequiredError(RuntimeError):
    """Adaptador ausente o comando no especificado — borde del caller.

    Código canónico ADR §5: ``sealing_adapter_required``. Se lanza ANTES
    de ejecutar cualquier proceso: es un error de configuración del
    caller (``--seal`` sin ``--key-adapter``), no del adaptador.
    """

    ERROR_CODE = SEALING_ADAPTER_REQUIRED_CODE


class AdapterResult:
    """Salida validada de una operación del adaptador.

    Porta el artefacto de la operación (``wrapped_cek`` o ``cek``) y el
    ``adapter_id`` (sólo en ``wrap``) como metadato de diagnóstico.
    """

    __slots__ = ("op", "wrapped_cek", "adapter_id", "cek")

    def __init__(self, op: str, wrapped_cek: str | None = None,
                 adapter_id: str | None = None, cek: bytes | None = None) -> None:
        self.op = op
        self.wrapped_cek = wrapped_cek
        self.adapter_id = adapter_id
        self.cek = cek


def validate_adapter_id(adapter_id: object) -> str:
    """Valida ``adapter_id`` contra la gramática cerrada del ADR §6 (F4).

    Devuelve el identificador si es válido; lanza ``SealingAdapterError``
    (NOTA: la gramática de ``adapter_id`` tiene su propio código §5,
    ``sealing_adapter_id_invalid``, que la superficie CLI aplica en T4
    al escribir el manifiesto — aquí, en el borde del runner, un
    ``adapter_id`` inválido en la RESPUESTA del adaptador es forma
    inválida del contrato y se reporta como ``sealing_adapter_error``).

    ``adapter_id`` es metadato de diagnóstico: el core jamás lo interpreta
    como ruta ni lo usa para seleccionar/executar nada.
    """
    if not isinstance(adapter_id, str):
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    if not (_ADAPTER_ID_MIN <= len(adapter_id) <= _ADAPTER_ID_MAX):
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    if adapter_id in (".", ".."):
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    if adapter_id[0] not in _ADAPTER_ID_FIRST:
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    if not set(adapter_id) <= _ADAPTER_ID_ALPHABET:
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    return adapter_id


def _decode_canonical_b64(label: str, value: object,
                          exact_bytes: int | None = None) -> bytes:
    """Decodifica base64 CANÓNICO (alfabeto estándar, con padding).

    - ``value`` debe ser ``str`` (tipo incorrecto = forma inválida).
    - Alfabeto estándar ``A-Za-z0-9+/`` con padding ``=`` obligatorio
      cuando corresponde: se re-codifica y compara byte a byte contra el
      input — cualquier desviación (padding faltante/sobrante, alfabeto
      alternativo, whitespace) es ``SealingAdapterError``.
    - ``exact_bytes``: longitud exacta requerida del binario decodificado.
    """
    if not isinstance(value, str):
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise SealingAdapterError(_ADAPTER_ERROR_MSG) from None
    if base64.b64encode(raw).decode("ascii") != value:
        # No canónico: padding/alfabeto/longitud desviados.
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    if exact_bytes is not None and len(raw) != exact_bytes:
        raise SealingAdapterError(_ADAPTER_ERROR_MSG)
    return raw


class _LimitExceeded(Exception):
    """Señal interna: un pipe del adaptador excedió su límite I/O."""


class SealingAdapterRunner:
    """Runner seguro del adaptador externo de claves (ADR §4).

    Ejecuta ``argv = [bin, *args]`` SIN shell, con límites I/O
    incrementales, timeout total, terminación de grupo/árbol, entorno
    mínimo con allowlist y contrato JSON cerrado por stdio.

    :param adapter_command: argv estructurado del adaptador (lista de
        strings, NO una línea de shell). Se recomienda ruta absoluta
        (ADR §4: resolución del ejecutable).
    :param env_allowlist: nombres de variables de entorno que el operador
        declaró para el adaptador (p. ej. ``--key-adapter-env``). Sin
        allowlist, sin variables extra (F3). Los VALORES se toman del
        entorno del proceso AN-KLA en el momento de la invocación y
        jamás se registran.
    :param timeout_seconds: timeout total por invocación (tope ADR: 30 s).
    """

    def __init__(self, adapter_command: list, *,
                 env_allowlist: "list[str] | tuple[str, ...] | None" = None,
                 timeout_seconds: float = ADAPTER_TIMEOUT_SECONDS) -> None:
        if isinstance(adapter_command, str) or not isinstance(
            adapter_command, (list, tuple)
        ):
            # Contrato del runner: argv ESTRUCTURADO. Una string sería una
            # línea de shell potencial (frontera violada) — se rechaza.
            raise SealingAdapterRequiredError(_ADAPTER_REQUIRED_MSG)
        adapter_command = list(adapter_command)
        if not adapter_command or not all(
            isinstance(a, str) and a for a in adapter_command
        ):
            # Adaptador ausente / comando no especificado (borde caller).
            raise SealingAdapterRequiredError(_ADAPTER_REQUIRED_MSG)
        self._argv = adapter_command
        self._env_allowlist = tuple(env_allowlist or ())
        for name in self._env_allowlist:
            if not isinstance(name, str) or not name or "=" in name:
                raise ValueError(
                    "key_adapter_env expects environment variable names "
                    "(non-empty, without '=')"
                )
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._timeout_seconds = float(timeout_seconds)

    # ------------------------------------------------------------------
    # Operaciones del contrato (entrada cerrada por construcción)
    # ------------------------------------------------------------------

    def wrap_cek(self, cek: bytes) -> AdapterResult:
        """Operación ``wrap``: CEK (32 B) → ``wrapped_cek`` + ``adapter_id``.

        La CEK viaja al adaptador por stdin local (y sólo entonces, ADR
        §1); regresa como blob opaco que el core jamás interpreta.
        """
        request = {"op": "wrap", "cek_b64": self._encode_input_cek(cek)}
        payload = self._invoke(request)
        # Salida cerrada: exactamente {wrapped_cek, adapter_id}.
        if not isinstance(payload, dict) or set(payload) != {
            "wrapped_cek", "adapter_id"
        }:
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        wrapped = payload["wrapped_cek"]
        if not isinstance(wrapped, str):
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        if len(wrapped) > ADAPTER_WRAPPED_CEK_MAX_CHARS:
            # Techo pre-vuelo del ADR aplicado también a la salida.
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        # base64 CANÓNICO también para wrapped_cek (ADR §4): validar
        # canonicidad NO es interpretar el blob — el core sigue sin
        # conocer su estructura (H3 del adversarial attempt 1).
        _decode_canonical_b64("wrapped_cek", wrapped)
        adapter_id = validate_adapter_id(payload["adapter_id"])
        return AdapterResult("wrap", wrapped_cek=wrapped, adapter_id=adapter_id)

    def unwrap_cek(self, wrapped_cek: str) -> AdapterResult:
        """Operación ``unwrap``: ``wrapped_cek`` (blob opaco) → CEK (32 B).

        El blob se trata como opaco: el runner sólo valida el techo de
        longitud y la canonicidad base64 (ADR §4) antes de enviarlo.
        """
        if not isinstance(wrapped_cek, str):
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        if len(wrapped_cek) > ADAPTER_WRAPPED_CEK_MAX_CHARS:
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        # Entrada también canónica (H3): un blob no-b64 del caller es
        # contrato violado ANTES de ejecutar el adaptador.
        _decode_canonical_b64("wrapped_cek", wrapped_cek)
        request = {"op": "unwrap", "wrapped_cek": wrapped_cek}
        payload = self._invoke(request)
        # Salida cerrada: exactamente {cek_b64}.
        if not isinstance(payload, dict) or set(payload) != {"cek_b64"}:
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        cek = _decode_canonical_b64("cek_b64", payload["cek_b64"],
                                    exact_bytes=CEK_LENGTH)
        return AdapterResult("unwrap", cek=cek)

    # ------------------------------------------------------------------
    # Entrada: validación y encoding canónico
    # ------------------------------------------------------------------

    def _encode_input_cek(self, cek: bytes) -> str:
        if not isinstance(cek, (bytes, bytearray)):
            raise ValueError("cek must be bytes of exactly 32 bytes")
        if len(cek) != CEK_LENGTH:
            raise ValueError(
                f"cek must be exactly {CEK_LENGTH} bytes, got {len(cek)}"
            )
        return base64.b64encode(bytes(cek)).decode("ascii")

    # ------------------------------------------------------------------
    # Entorno mínimo con allowlist (F3)
    # ------------------------------------------------------------------

    def _minimal_env(self) -> dict:
        """Entorno mínimo: PATH + localización básica + allowlist explícita.

        El adaptador NO hereda el entorno del proceso AN-KLA (podría
        contener secretos del host). Sin allowlist, sin variables extra.
        Excepción NT: SystemRoot es imprescindible para que el proceso
        hijo (python.exe incluido) inicialice CRT/crypto — sin ella el
        adaptador muere antes de ejecutar una línea. No es un dato del
        host: es infraestructura del SO.
        """
        env = {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if os.name == "nt":
            for runtime_var in ("SystemRoot", "SYSTEMROOT", "SystemDrive", "COMSPEC"):
                value = os.environ.get(runtime_var)
                if value is not None:
                    env[runtime_var] = value
        for name in self._env_allowlist:
            value = os.environ.get(name)
            if value is not None:
                env[name] = value
        return env

    # ------------------------------------------------------------------
    # Ejecución segura: Popen + lecturas incrementales concurrentes
    # ------------------------------------------------------------------

    def _invoke(self, request: dict) -> dict:
        """Ejecuta el adaptador y devuelve el payload JSON validado.

        Cumplimiento LITERAL del ADR §4 (ejecución segura): Popen sin
        shell, close_fds, entorno mínimo, timeout total, lecturas
        incrementales concurrentes con límites, terminación de
        grupo/árbol TERM→2s→KILL, reap y cierre de pipes en TODA salida.
        """
        stdin_bytes = json.dumps(request, sort_keys=True).encode("utf-8")
        if len(stdin_bytes) > ADAPTER_STDIN_LIMIT:
            # Pre-vuelo por schema: no debería ocurrir (techo 4096 chars);
            # defensa en profundidad, mismo código cerrado.
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)

        try:
            # bufsize=0: pipes SIN buffer de texto/bytes del lado Python —
            # los readers usan os.read sobre el fd crudo. Elimina el
            # deadlock de cerrar un BufferedReader con lector vivo (H1) y
            # la detección tardía por acumulación de buffer (H2).
            process = subprocess.Popen(
                self._argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,          # argv estructurado — JAMÁS shell
                close_fds=True,       # sólo stdio conectado
                env=self._minimal_env(),
                bufsize=0,
                start_new_session=(os.name == "posix"),  # grupo propio POSIX
            )
        except (OSError, ValueError):
            # Ejecutable inexistente / sin permisos: fallo del adaptador.
            raise SealingAdapterError(_ADAPTER_ERROR_MSG) from None

        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []  # contado y DESCARTADO (ADR §4)
        limit_event = threading.Event()
        lock = threading.Lock()

        def reader(fd, chunks, limit):
            """Lectura CRUDA (os.read): retorna con lo que haya disponible.

            - Sin buffer de BufferedReader: el fd no comparte lock con un
              objeto file de Python (H1 — cierre sin deadlock).
            - Detección INMEDIATA del exceso: os.read vuelve con el primer
              bloque parcial, no espera completar N bytes (H2).
            """
            total = 0
            while True:
                try:
                    block = os.read(fd, 4096)
                except OSError:
                    return  # pipe cerrado/reapado: fin del stream
                if not block:
                    return
                total += len(block)
                if total > limit:
                    # Terminación INMEDIATA del árbol (ADR §4) — no se
                    # acumula ni un byte más de lo permitido.
                    limit_event.set()
                    self._terminate_tree(process)
                    return
                with lock:
                    chunks.append(block)

        t_out = threading.Thread(
            target=reader,
            args=(process.stdout.fileno(), stdout_chunks, ADAPTER_STDOUT_LIMIT),
        )
        t_err = threading.Thread(
            target=reader,
            args=(process.stderr.fileno(), stderr_chunks, ADAPTER_STDERR_LIMIT),
        )
        t_out.daemon = True
        t_err.daemon = True
        t_out.start()
        t_err.start()

        stdin_error: Exception | None = None
        timed_out = False

        def _mark_timeout() -> None:
            nonlocal timed_out
            timed_out = True

        def _on_deadline() -> None:
            # Marcar ANTES de terminar: _terminate_tree espera al proceso
            # (gracia TERM) y el wait() del hilo principal podría ganar la
            # carrera y leer timed_out == False.
            _mark_timeout()
            self._terminate_tree(process)

        deadline = threading.Timer(self._timeout_seconds, _on_deadline)
        deadline.daemon = True
        try:
            try:
                process.stdin.write(stdin_bytes)
            except (BrokenPipeError, OSError) as exc:
                # El adaptador cerró stdin temprano (p. ej. al morir): el
                # exit status / stdout decidirán; si todo lo demás es válido
                # el contrato se evalúa igual. Guardamos el hecho, no el
                # contenido (no hay contenido que filtrar aquí: stdin es
                # nuestra petición cerrada).
                stdin_error = exc
            finally:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

            deadline.start()
            try:
                process.wait()
            finally:
                deadline.cancel()

            # Join ACOTADO de los readers (H1): un escapee setsid que
            # heredó stdout abierto mantiene el fd sin EOF; los readers
            # son daemon y se abandona el fd sin tocar su lock.
            t_out.join(timeout=1.0)
            t_err.join(timeout=1.0)
        finally:
            # Higiene en TODA salida (H1): cierre del FD crudo — nunca
            # BufferedWriter.close() (toma el lock del buffer y puede
            # bloquear contra un reader vivo). Primero se INVALIDA el fd
            # del objeto Popen (desvinculación), luego os.close directo.
            # Un reader bloqueado en os.read recibe EBADF/OSError y sale.
            self._abandon_pipes(process)
            if process.poll() is None:
                self._terminate_tree(process)
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:  # pragma: no cover
                pass

        if limit_event.is_set():
            # Límite I/O excedido → terminación YA ocurrió arriba.
            raise SealingAdapterError(_ADAPTER_IO_LIMIT_MSG)
        if timed_out:
            # Timeout total → árbol terminado por el timer (arriba, en
            # finally, de no haber completado).
            raise SealingAdapterError(_ADAPTER_TIMEOUT_MSG)
        if process.returncode is None:  # pragma: no cover - defensive
            self._terminate_tree(process)
            raise SealingAdapterError(_ADAPTER_TIMEOUT_MSG)
        if process.returncode != 0:
            # Exit ≠ 0 = error AUNQUE el JSON de stdout sea válido (ADR §4).
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)
        if stdin_error is not None:
            # No pudimos entregar la petición completa: el contrato no se
            # consumió íntegro; cerrado.
            raise SealingAdapterError(_ADAPTER_ERROR_MSG)

        stdout = b"".join(stdout_chunks)
        try:
            text = stdout.decode("utf-8")
        except UnicodeDecodeError:
            raise SealingAdapterError(_ADAPTER_ERROR_MSG) from None
        try:
            payload = json.loads(text)
        except ValueError:
            raise SealingAdapterError(_ADAPTER_ERROR_MSG) from None
        return payload

    # ------------------------------------------------------------------
    # Terminación de grupo/árbol y cierre de pipes
    # ------------------------------------------------------------------

    def _terminate_tree(self, process: subprocess.Popen) -> None:
        """Terminación del GRUPO/árbol: TERM → 2 s → KILL (ADR §4).

        POSIX: el proceso se lanzó con ``start_new_session`` (grupo propio
        + sesión propia), así que la señal va al GRUPO completo. Windows:
        terminación de árbol (``CREATE_NEW_PROCESS_GROUP`` no da árbol;
        se usa taskkill /T como equivalente Job Object en este runner).
        Best-effort: un descendiente que haga ``setsid()`` escapa (F8).
        """
        if os.name == "posix":
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=ADAPTER_TERM_GRACE_SECONDS)
                return
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.kill()
                except OSError:
                    pass
        else:  # pragma: no cover - Windows, sin cobertura local
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )

    @staticmethod
    def _abandon_pipes(process: subprocess.Popen) -> None:
        """Cierra los pipes de forma segura ante readers vivos (H1).

        Con ``bufsize=0`` los pipes son ``FileIO`` crudo (sin el lock de
        ``BufferedReader``): los readers usan ``os.read`` sobre el fd y
        NUNCA comparten el objeto file, así que ``close()`` no puede
        bloquear contra ellos (el deadlock H1 era ``BufferedReader.read``
        vs ``close`` sobre el MISMO objeto con buffer). El ``close()``
        cierra el fd; un reader bloqueado en ``os.read`` despierta con
        OSError y termina. Idempotente ante fds ya cerrados.
        """
        for attr in ("stdin", "stdout", "stderr"):
            pipe = getattr(process, attr, None)
            if pipe is None or pipe.closed:
                continue
            try:
                pipe.close()
            except OSError:
                pass  # ya cerrado/reapado — higiene idempotente
