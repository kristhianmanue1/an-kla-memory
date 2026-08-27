"""CEK efímera y wrap/unwrap como contrato de función — T2 de issue #46.

Norma vinculante: ``docs/architecture/0042-sealed-export-v1.md`` §1 (F1, F7).

Alcance exacto de esta fase (borde definido; el adaptador real es T3):

- ``generate_cek()``: 32 bytes del CSPRNG del SO (``os.urandom``), una CEK
  nueva por bundle (F1). No requiere el extra ``[sealed]`` — la generación
  es stdlib.
- ``wrap_cek(cek, kek)`` / ``unwrap_cek(wrapped_cek, kek)``: **contrato de
  función pura con KEK inyectable como parámetro**. En T2 el ``kek`` es
  una clave simétrica (bytes) para AES-256-GCM con nonce aleatorio; la
  frontera real con el adaptador externo (subproceso, KEK/custodia que
  JAMÁS entra al core) se materializa en T3 sobre este mismo contrato.
  - Wrap: AES-256-GCM con KEK de 32 bytes, nonce ``os.urandom(12)``
    guardado como prefijo del blob. El blob resultante es opaco.
  - Unwrap: fail-closed — cualquier fallo (KEK erróneo, blob corrupto,
    longitud imposible) es ``SealedCekUnwrapError`` SIN distinguir la
    causa (sin oráculo, ADR §5 ``sealed_payload_auth_failed`` análogo).
    **Jamás hay degradación**: no existe ruta que devuelva la CEK en
    claro sin autenticar el tag GCM.
- **Imports perezosos**: ``cryptography`` solo dentro de las funciones.
  El módulo es importable stdlib-only y falla cerrado con
  ``SealedExtraNotInstalledError`` (código
  ``sealing_extra_not_installed``) cuando el import real falla —
  independiente del flag por-proceso ``sealed_available`` (nota del
  adversarial T1).
- **INVARIANTE F7**: la CEK jamás aparece en ``str``/``repr`` ni
  serializaciones de los objetos/errores de este módulo.
"""

from __future__ import annotations

import os

from an_kla.sealed.kdf import CEK_LENGTH, _as_bytes

#: Longitud fija del nonce AES-GCM usado por el wrap de la CEK (bytes).
WRAP_NONCE_LENGTH = 12

#: Longitud del tag GCM (bytes) que acompaña al ciphertext del wrap.
_GCM_TAG_LENGTH = 16

#: Longitud exacta del blob ``wrapped_cek`` producido por :func:`wrap_cek`
#: (nonce || ciphertext(32) || tag(16)).
WRAPPED_CEK_BLOB_LENGTH = WRAP_NONCE_LENGTH + CEK_LENGTH + _GCM_TAG_LENGTH

_REDACTED_REPR = "<WrappedCek: redacted (F7)>"

_EXTRA_NOT_INSTALLED_MSG = (
    "sealed profile unavailable: the 'sealed' extra is not installed "
    "(pip install 'an-kla-memory[sealed]'); refusing to degrade to cleartext"
)


class SealedCekUnwrapError(RuntimeError):
    """Fallo de unwrap de la CEK — cerrado, SIN oráculo ni degradación.

    Cualquier causa (KEK erróneo, blob corrupto, tag inválido, longitud
    imposible) produce este mismo error con mensaje que no distingue la
    causa ni embebe material del blob. Código canónico asociado en la
    superficie del ADR §5: ``sealed_payload_auth_failed``.
    """

    ERROR_CODE = "sealed_payload_auth_failed"


def generate_cek() -> bytes:
    """CEK efímera: 32 bytes del CSPRNG del SO, una por bundle (F1).

    Stdlib pura — no requiere el extra ``[sealed]`` (generar no es cifrar).
    """
    return os.urandom(CEK_LENGTH)


def _require_aesgcm():
    """Import perezoso y fail-closed de ``AESGCM`` (extra ``[sealed]``).

    No consulta ``sealed_available``: el error lo causa el import real que
    falla, no el flag por-proceso.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - depende del entorno
        from an_kla.sealed import SealedExtraNotInstalledError

        raise SealedExtraNotInstalledError(_EXTRA_NOT_INSTALLED_MSG) from exc
    return AESGCM


class WrappedCek:
    """Blob opaco resultado del wrap de la CEK — acceso explícito, F7.

    ``repr``/``str`` redactados; pickle rechazado (``TypeError``). El
    acceso deliberado al blob (para persistirlo como ``wrapped_cek`` en el
    manifiesto v2 — superficie de T4) es explícito vía ``blob``.
    """

    __slots__ = ("_blob",)

    def __init__(self, blob: bytes) -> None:
        blob = _as_bytes("blob", blob)
        if len(blob) != WRAPPED_CEK_BLOB_LENGTH:
            raise ValueError(
                f"wrapped cek blob must be exactly {WRAPPED_CEK_BLOB_LENGTH} bytes, "
                f"got {len(blob)}"
            )
        self._blob = blob

    @property
    def blob(self) -> bytes:
        """Bytes crudos del blob opaco (nonce || ciphertext || tag)."""
        return self._blob

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return _REDACTED_REPR

    def __str__(self) -> str:  # pragma: no cover - trivial
        return _REDACTED_REPR

    def __reduce__(self):  # noqa: D105 - pickle/consistencia F7
        raise TypeError("WrappedCek refuses serialization (F7: no key material)")


def wrap_cek(cek: bytes, kek: bytes) -> WrappedCek:
    """Envuelve la CEK bajo AES-256-GCM con la KEK inyectada.

    La KEK es un **parámetro inyectable** (contrato de función pura de T2):
    representará la capacidad que custodia el adaptador externo (T3), cuya
    material de custodia jamás entra al core (ADR §1).

    - ``cek``: exactamente 32 bytes (la CEK efímera).
    - ``kek``: exactamente 32 bytes (AES-256).
    - Nonce aleatorio ``os.urandom(12)`` por wrap, prefijado al blob.
    """
    cek_bytes = _as_bytes("cek", cek)
    if len(cek_bytes) != CEK_LENGTH:
        raise ValueError(f"cek must be exactly {CEK_LENGTH} bytes, got {len(cek_bytes)}")
    kek_bytes = _as_bytes("kek", kek)
    if len(kek_bytes) != 32:
        raise ValueError(f"kek must be exactly 32 bytes, got {len(kek_bytes)}")
    aesgcm_cls = _require_aesgcm()
    nonce = os.urandom(WRAP_NONCE_LENGTH)
    ciphertext = aesgcm_cls(kek_bytes).encrypt(nonce, cek_bytes, None)
    return WrappedCek(nonce + ciphertext)


def unwrap_cek(wrapped: WrappedCek | bytes, kek: bytes) -> bytes:
    """Recupera la CEK desde el blob — fail-closed, sin oráculo ni degradación.

    Cualquier fallo (KEK erróneo, blob corrupto, tag inválido) es
    ``SealedCekUnwrapError`` con mensaje uniforme: jamás se distingue clave
    mala de datos corruptos, jamás se devuelve la CEK sin autenticar el tag
    GCM (no existe fallback a claro).

    La longitud del blob se valida ANTES de tocar el extra: un error de
    contrato del caller es independiente del entorno.
    """
    if isinstance(wrapped, WrappedCek):
        blob = wrapped.blob
    else:
        blob = _as_bytes("wrapped", wrapped)
    if len(blob) != WRAPPED_CEK_BLOB_LENGTH:
        raise SealedCekUnwrapError("sealed cek unwrap failed (no further detail)")
    kek_bytes = _as_bytes("kek", kek)
    if len(kek_bytes) != 32:
        raise ValueError(f"kek must be exactly 32 bytes, got {len(kek_bytes)}")
    aesgcm_cls = _require_aesgcm()
    nonce, ciphertext = blob[:WRAP_NONCE_LENGTH], blob[WRAP_NONCE_LENGTH:]
    try:
        cek = aesgcm_cls(kek_bytes).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise SealedCekUnwrapError("sealed cek unwrap failed (no further detail)") from exc
    if len(cek) != CEK_LENGTH:  # paranoia: defensa en profundidad
        raise SealedCekUnwrapError("sealed cek unwrap failed (no further detail)")
    return cek
