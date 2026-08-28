#!/usr/bin/env python3
"""gate_sealed_adapter.py — adaptador DETERMINÍSTICO, SOLO para gates.

ADR-0042 §9 (gate de publicación): el gate de upgrade beta.17→18 debe
ejercitar ``--seal`` contra un adaptador de prueba determinístico
incluido en ``scripts/`` — "sólo para gates, nunca en el paquete". Este
script implementa ese adaptador: el contrato
``an-kla/sealing-adapter-contract-v1`` por stdio (wrap/unwrap, claves
exactas cerradas, exit 0 + JSON canónico) con stdlib PURA.

*** DETERMINÍSTICO (la razón de ser de este adaptador): ***

A diferencia del adaptador de referencia de ``tests/adapters/`` (nonce
aleatorio por wrap), aquí el mismo input produce SIEMPRE el mismo
``wrapped_cek``: la aleatoriedad del wrap es un flujo SHA-256 derivado
de la PROPIA CEK (no del reloj ni del CSPRNG). Eso permite a un gate
verificar estabilidad byte a byte entre corridas:

    $ printf '{"op":"wrap","cek_b64":"..."}' | scripts/gate_sealed_adapter.py
    $ printf '{"op":"wrap","cek_b64":"..."}' | scripts/gate_sealed_adapter.py
    # → idéntico wrapped_cek en ambas

La construcción NO es criptografía de producción ni pretende serlo
(composición DOC: XOR pseudoaleatorio por SHA-256 con MAC truncado,
EtM — suficiente para verificar el CONTRATO y el determinismo, no para
custodiar material). Un KEK real vive en un adaptador con custodia
auditada (Keychain/KMS/age); aquí el "secreto" es una constante pública
porque el objetivo del gate es verificar plumbing determinista.

*** SOLO PARA GATES / NO-PRODUCCIÓN: ***

- Vive en ``scripts/``: NO se distribuye en el paquete (el ADR lo
  excluye expresamente del wheel).
- Sin custodia: la "KEK" es una constante pública del script.
- Sin versión, sin rotación, sin auditoría.

Entorno: acepta opcionalmente ``ANKLA_GATE_ADAPTER_ID`` (allowlist F3)
para variar el ``adapter_id`` reportado en gates de gramática; por
defecto ``gate.deterministic-adapter.v1``.

Contrato por stdio (conjunto de claves EXACTO por operación):

- ``wrap``   → in ``{"op","cek_b64"}``       out ``{"wrapped_cek","adapter_id"}``
- ``unwrap`` → in ``{"op","wrapped_cek"}``   out ``{"cek_b64"}``
- Clave extra/ausente/tipo incorrecto → exit 1 con ``{"error":...}``
  (el runner del core lo colapsa a ``sealing_adapter_error``).

Uso (desde la raíz del repo):

    python3 -m an_kla export create --bundle B --seal sealed-export/v1 \
        --key-adapter python3 \
        --key-adapter-arg scripts/gate_sealed_adapter.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys

ADAPTER_ID = "gate.deterministic-adapter.v1"

#: KEK fija y PÚBLICA (no-producción; ver cabecera). 32 bytes.
_KEK = b"ankla-gate-adapter-public-kek-v1".ljust(32, b"\x00")

_NONCE_LEN = 12
_TAG_LEN = 16
_CEK_LEN = 32

_ERROR_EXIT = 1


def _fail(message: str) -> None:
    """Error de contrato: exit 1 con JSON mínimo (el runner colapsa a
    ``sealing_adapter_error``; este texto nunca se propaga)."""
    sys.stdout.write(json.dumps({"error": message}, sort_keys=True))
    sys.stdout.flush()
    raise SystemExit(_ERROR_EXIT)


def _keystream(seed: bytes, length: int) -> bytes:
    """Flujo pseudoaleatorio DETERMINÍSTICO: bloques SHA-256 encadenados
    por contador. Misma semilla → mismo flujo (sin CSPRNG, sin reloj)."""
    blocks = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(
            hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return b"".join(blocks)[:length]


def _wrap(cek: bytes) -> str:
    """wrap determinístico: nonce y keystream derivados de la CEK.

    nonce = SHA-stream("gate-nonce" || cek) — determinístico por input;
    stream = SHA-stream("gate-stream" || nonce) — reconstruible en el
    unwrap desde el blob (el nonce viaja como prefijo).
    blob = nonce || mac-truncado || (cek XOR stream), base64 canónico
    estándar con padding, sin prefijos (ADR §4: opaco para el core).
    """
    nonce = _keystream(b"gate-nonce" + cek, _NONCE_LEN)
    stream = _keystream(b"gate-stream" + nonce, _CEK_LEN)
    xored = bytes(a ^ b for a, b in zip(cek, stream))
    tag = hmac.new(_KEK, nonce + xored, hashlib.sha256).digest()[:_TAG_LEN]
    blob = nonce + tag + xored
    return base64.b64encode(blob).decode("ascii")


def _unwrap(wrapped_cek: str) -> str:
    """unwrap: verifica el MAC (EtM) y devuelve la CEK en b64 canónico.

    El keystream se reconstruye desde el NONCE del propio blob (prefijo)
    — el wrap lo derivó de la CEK, pero el unwrap no necesita la CEK
    para reconstruir el flujo, sólo el nonce. Cualquier fallo (blob
    corrupto, MAC distinto, longitud imposible) es un error cerrado
    único — sin oráculo.
    """
    try:
        blob = base64.b64decode(wrapped_cek, validate=True)
    except Exception:
        _fail("invalid wrapped_cek encoding")
    if len(blob) != _NONCE_LEN + _TAG_LEN + _CEK_LEN:
        _fail("invalid wrapped_cek length")
    nonce = blob[:_NONCE_LEN]
    tag = blob[_NONCE_LEN:_NONCE_LEN + _TAG_LEN]
    xored = blob[_NONCE_LEN + _TAG_LEN:]
    expected = hmac.new(_KEK, nonce + xored, hashlib.sha256).digest()[:_TAG_LEN]
    if not hmac.compare_digest(tag, expected):
        _fail("wrapped_cek authentication failed")
    stream = _keystream(b"gate-stream" + nonce, _CEK_LEN)
    cek = bytes(a ^ b for a, b in zip(xored, stream))
    return base64.b64encode(cek).decode("ascii")


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
    except ValueError:
        _fail("request is not valid json")
    if not isinstance(request, dict) or "op" not in request:
        _fail("request must be an object with op")
    op = request["op"]
    if op == "wrap":
        if set(request) != {"op", "cek_b64"}:
            _fail("wrap takes exactly op and cek_b64")
        if not isinstance(request["cek_b64"], str):
            _fail("cek_b64 must be a string")
        try:
            cek = base64.b64decode(request["cek_b64"], validate=True)
        except Exception:
            _fail("invalid cek_b64 encoding")
        if len(cek) != _CEK_LEN:
            _fail("cek must be 32 bytes")
        sys.stdout.write(json.dumps(
            {"wrapped_cek": _wrap(cek),
             "adapter_id": os.environ.get(
                 "ANKLA_GATE_ADAPTER_ID", ADAPTER_ID)},
            sort_keys=True))
        raise SystemExit(0)
    if op == "unwrap":
        if set(request) != {"op", "wrapped_cek"}:
            _fail("unwrap takes exactly op and wrapped_cek")
        if not isinstance(request["wrapped_cek"], str):
            _fail("wrapped_cek must be a string")
        cek_b64 = _unwrap(request["wrapped_cek"])
        sys.stdout.write(json.dumps({"cek_b64": cek_b64}, sort_keys=True))
        raise SystemExit(0)
    _fail("unknown op")


if __name__ == "__main__":
    main()
