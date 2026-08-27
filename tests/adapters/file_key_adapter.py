#!/usr/bin/env python3
"""Adaptador de REFERENCIA archivo-llave — SOLO para tests (NO-producción).

Este script implementa ``an-kla/sealing-adapter-contract-v1`` por stdio
(adaptador del ADR §4 de ``docs/architecture/0042-sealed-export-v1.md``)
usando exclusivamente la stdlib de Python. Es el ADAPTADOR DE REFERENCIA
que usan los tests del runner (``tests/test_sealed_key_adapter.py``) para
ejercer el contrato wrap/unwrap de extremo a extremo.

*** NO-PRODUCCIÓN (declarado deliberadamente): ***

- La "custodia" es un archivo de llave en disco del host de tests, con
  permisos POSIX dependientes del creador: NO es Keychain, ni KMS, ni
  YubiKey, ni passphrase. Cualquier proceso con acceso de lectura al
  archivo recupera la CEK: la frontera de custodia del ADR (§1, F1) NO
  existe aquí.
- El cifrado es una composición DOC de primitivas stdlib con un XOR
  pseudoaleatorio derivado por SHA-256 y un MAC truncado (EtM). Es
  suficiente para verificar el CONTRATO y el RUNNER (opacidad del blob,
  roundtrip, fail-closed), NO para custodiar material real. Producción
  exige un adaptador con criptografía auditada (age, Keychain, KMS...).
- Sin versión, sin rotación, sin auditoría: vive bajo ``tests/``.

Contrato (conjunto de claves exacto por operación):

- ``wrap``   → in ``{"op","cek_b64"}``       out ``{"wrapped_cek","adapter_id"}``
- ``unwrap`` → in ``{"op","wrapped_cek"}``   out ``{"cek_b64"}``
- Clave extra/ausente/tipo incorrecto → exit 1 con ``{"error":"..."}``
  en stdout (el runner lo colapsa a ``sealing_adapter_error``; NUNCA
  embebe este texto).
- CEK decodificada ≠ 32 bytes → error de contrato (exit 1).
- ``wrapped_cek`` canónico: ``b64(nonce||mac||xored)`` puro — alfabeto
  estándar con padding, SIN prefijos (el ADR §4 congela base64 canónico
  para wrapped_cek; un prefijo no-b64 violaría el contrato). El core lo
  trata como opaco.

Variables de entorno (borde del runner, F3 — el runner decide qué llega):

- ``ANKLA_TEST_ADAPTER_KEY_FILE``: ruta del archivo de llave (32 bytes
  hex). Requerida. En los tests la inyecta el runner vía allowlist.
- ``ANKLA_TEST_ADAPTER_VERBOSE``: si existe (cualquier valor), escribe
  ruido en stderr — para verificar que stderr se DESCARTA.
- ``ANKLA_TEST_ADAPTER_PRINT_ENV``: si existe, imprime el entorno AL
  STDERR (se descarta) y termina; para verificar la allowlist leyendo el
  hecho (exit/contrato), no el contenido.

Uso directo (depuración): ver tests/test_sealed_key_adapter.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

ADAPTER_ID = "tests.file-key-adapter.v1"

#: Etiqueta de la variable de entorno con el archivo de llave (allowlist).
ENV_KEY_FILE = "ANKLA_TEST_ADAPTER_KEY_FILE"
ENV_VERBOSE = "ANKLA_TEST_ADAPTER_VERBOSE"
ENV_PRINT_ENV = "ANKLA_TEST_ADAPTER_PRINT_ENV"

_CONTRACT_ERROR_EXIT = 1


def _fail(message: str) -> None:
    """Error de contrato: exit != 0 con JSON mínimo en stdout.

    El runner exige exit 0 + JSON cerrado: cualquier violación es
    ``sealing_adapter_error`` en el core, AUNQUE este JSON sea válido.
    """
    sys.stdout.write(json.dumps({"error": message}, sort_keys=True))
    sys.stdout.flush()
    raise SystemExit(_CONTRACT_ERROR_EXIT)


def _load_key() -> bytes:
    path = os.environ.get(ENV_KEY_FILE)
    if not path:
        _fail("missing key file env")
    try:
        with open(path, "rb") as fh:
            data = fh.read().strip()
    except OSError:
        _fail("key file unreadable")
    try:
        key = bytes.fromhex(data.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        _fail("key file not hex")
    if len(key) != 32:
        _fail("key file not 32 bytes")
    return key


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """SHA-256 en modo contador (DOC — ver cabecera NO-producción)."""
    out = bytearray()
    counter = 0
    while len(out) < length:
        out.extend(hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(out[:length])


def do_wrap(cek: bytes, key: bytes) -> str:
    nonce = os.urandom(16)
    mac = hmac.new(key, b"wrap" + nonce + cek, hashlib.sha256).digest()[:16]
    xored = bytes(a ^ b for a, b in zip(cek, _keystream(key, nonce, len(cek))))
    blob = nonce + mac + xored
    return base64.b64encode(blob).decode("ascii")


def do_unwrap(wrapped_cek: str, key: bytes) -> bytes:
    if not isinstance(wrapped_cek, str):
        _fail("wrapped_cek not str")
    try:
        blob = base64.b64decode(wrapped_cek, validate=True)
    except Exception:
        _fail("bad wrapped_cek b64")
    if len(blob) != 16 + 16 + 32:
        _fail("bad wrapped_cek length")
    nonce, mac, xored = blob[:16], blob[16:32], blob[32:]
    cek = bytes(a ^ b for a, b in zip(xored, _keystream(key, nonce, 32)))
    expected = hmac.new(key, b"wrap" + nonce + cek, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, expected):
        _fail("unwrap authentication failed")
    return cek


def main() -> None:
    if os.environ.get(ENV_PRINT_ENV):
        # El entorno visible por el adaptador va a STDERR — que el runner
        # DESCARTA por diseño. El test de allowlist observa por otros
        # medios (ver tests/test_sealed_key_adapter.py).
        sys.stderr.write(json.dumps(dict(os.environ), sort_keys=True))
        sys.stderr.flush()
        raise SystemExit(0)

    if os.environ.get(ENV_VERBOSE):
        sys.stderr.write("adapter stderr noise: internal path /tmp/adapter-keks\n")
        sys.stderr.flush()

    raw = sys.stdin.read(64 * 1024)
    try:
        request = json.loads(raw)
    except ValueError:
        _fail("stdin not json")
    if not isinstance(request, dict):
        _fail("stdin not object")

    op = request.get("op")
    if op == "wrap":
        if set(request) != {"op", "cek_b64"}:
            _fail("wrap keys not exact")
        cek_b64 = request.get("cek_b64")
        if not isinstance(cek_b64, str):
            _fail("cek_b64 not str")
        try:
            cek = base64.b64decode(cek_b64, validate=True)
        except Exception:
            _fail("cek_b64 not b64")
        if base64.b64encode(cek).decode("ascii") != cek_b64:
            _fail("cek_b64 not canonical")
        if len(cek) != 32:
            _fail("cek not 32 bytes")
        key = _load_key()
        response = {"adapter_id": ADAPTER_ID,
                    "wrapped_cek": do_wrap(cek, key)}
    elif op == "unwrap":
        if set(request) != {"op", "wrapped_cek"}:
            _fail("unwrap keys not exact")
        wrapped = request.get("wrapped_cek")
        if not isinstance(wrapped, str):
            _fail("wrapped_cek not str")
        key = _load_key()
        cek = do_unwrap(wrapped, key)
        response = {"cek_b64": base64.b64encode(cek).decode("ascii")}
    else:
        _fail("unknown op")

    sys.stdout.write(json.dumps(response, sort_keys=True))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
