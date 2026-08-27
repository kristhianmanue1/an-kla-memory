"""Derivación de subclaves por HKDF-SHA256 (solo Expand) — T2 de issue #46.

Norma vinculante: ``docs/architecture/0042-sealed-export-v1.md`` §1 (F1, F7).

Contrato de este módulo:

- **KDF = HKDF-SHA256 solo Expand** (``cryptography`` ``HKDFExpand``): la CEK
  raíz ya es uniforme (32 bytes del CSPRNG del SO), por lo que el paso
  Extract es innecesario y **está prohibido** aquí (RFC 5869 §3.3; el ADR
  manda ``HKDFExpand`` directo). Sin crypto manual.
- **Separación de dominio por propósito** vía ``info`` literales, sin
  variantes::

      aead_key      = HKDFExpand(CEK, b"aead-key",     32)   # única clave AES-GCM
      bundle_id_raw = HKDFExpand(CEK, b"bundle-id",    16)
      mac_key       = HKDFExpand(CEK, b"manifest-mac", 32)

  La CEK raíz **nunca** se usa como clave AES directa.
- **Imports perezosos**: ``cryptography`` se importa SOLO dentro de las
  funciones, nunca a nivel top-level. El módulo es importable
  stdlib-only, y la operación falla cerrado con
  ``SealedExtraNotInstalledError`` (código ``sealing_extra_not_installed``)
  cuando el import real falla. Este error **no consulta** el flag
  ``sealed_available`` (que es una señal por-proceso calculada al importar
  ``an_kla.sealed``): KDF/CEK fallan por su propia causa, de forma
  independiente del estado del flag (nota del adversarial T1).
- **INVARIANTE F7**: ni la CEK ni las subclaves aparecen JAMÁS en
  ``str``/``repr`` ni en serializaciones (JSON, pickle) de los objetos de
  este módulo. El acceso deliberado al material es explícito (propiedades),
  nunca una conversión implícita. La materialización por el SO/runtime
  (swap, dumps, copias) queda fuera de garantía (ADR §Límites).
"""

from __future__ import annotations

# Longitudes congeladas por el ADR §1. La CEK es siempre de 32 bytes.
CEK_LENGTH = 32
AEAD_KEY_LENGTH = 32
BUNDLE_ID_RAW_LENGTH = 16
MAC_KEY_LENGTH = 32

# Info strings LITERALES del ADR §1 (separación de dominio). No variantes.
INFO_AEAD_KEY: bytes = b"aead-key"
INFO_BUNDLE_ID: bytes = b"bundle-id"
INFO_MANIFEST_MAC: bytes = b"manifest-mac"

_REDACTED_REPR = "<SealedSubkeys: key material redacted (F7)>"

_EXTRA_NOT_INSTALLED_MSG = (
    "sealed profile unavailable: the 'sealed' extra is not installed "
    "(pip install 'an-kla-memory[sealed]'); refusing to degrade to cleartext"
)


class SealedSubkeys:
    """Las tres subclaves derivadas de una CEK (ADR §1, F7).

    Contenedor opaco: ``repr``/``str`` redactados, serialización (pickle)
    rechazada con ``TypeError``. El acceso al material es deliberado y
    explícito vía las propiedades ``aead_key``, ``bundle_id_raw`` y
    ``mac_key`` (bytes crudos para uso criptográfico inmediato).

    Los tres campos se tratan como material secreto a efectos de F7
    (lectura conservadora del ADR: ``bundle_id`` sólo se persiste de forma
    explícita como hex en el manifiesto v2 — superficie de T4 —, nunca por
    una serialización implícita de este objeto).
    """

    __slots__ = ("_aead_key", "_bundle_id_raw", "_mac_key")

    def __init__(
        self,
        aead_key: bytes,
        bundle_id_raw: bytes,
        mac_key: bytes,
    ) -> None:
        for name, material, expected in (
            ("aead_key", aead_key, AEAD_KEY_LENGTH),
            ("bundle_id_raw", bundle_id_raw, BUNDLE_ID_RAW_LENGTH),
            ("mac_key", mac_key, MAC_KEY_LENGTH),
        ):
            if not isinstance(material, (bytes, bytearray)):
                raise TypeError(f"{name} must be bytes, got {type(material).__name__}")
            if len(material) != expected:
                raise ValueError(
                    f"{name} must be exactly {expected} bytes, got {len(material)}"
                )
        self._aead_key = bytes(aead_key)
        self._bundle_id_raw = bytes(bundle_id_raw)
        self._mac_key = bytes(mac_key)

    @property
    def aead_key(self) -> bytes:
        """Clave AES-256-GCM del bundle (uso deliberado; 32 bytes)."""
        return self._aead_key

    @property
    def bundle_id_raw(self) -> bytes:
        """16 bytes crudos del bundle_id (hex sólo al persistir, T4)."""
        return self._bundle_id_raw

    @property
    def mac_key(self) -> bytes:
        """Clave HMAC-SHA256 del manifiesto (32 bytes)."""
        return self._mac_key

    # --- F7: jamás material clave en representaciones ni serializaciones ---

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return _REDACTED_REPR

    def __str__(self) -> str:  # pragma: no cover - trivial
        return _REDACTED_REPR

    def __reduce__(self):  # noqa: D105 - pickle/consistencia F7
        raise TypeError("SealedSubkeys refuses serialization (F7: no key material)")

    def __eq__(self, other: object) -> bool:
        import hmac as _hmac

        if not isinstance(other, SealedSubkeys):
            return NotImplemented
        return (
            _hmac.compare_digest(self._aead_key, other._aead_key)
            and _hmac.compare_digest(self._bundle_id_raw, other._bundle_id_raw)
            and _hmac.compare_digest(self._mac_key, other._mac_key)
        )

    __hash__ = None  # mutable-equivalent semantics: no hash junto a __eq__ custom


def _require_hkdf_expand():
    """Import perezoso y fail-closed de ``HKDFExpand`` (extra ``[sealed]``).

    Deliberadamente NO consulta ``an_kla.sealed.sealed_available``: el error
    lo produce el import real que falla, no el flag por-proceso.
    """
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
    except ImportError as exc:  # pragma: no cover - depende del entorno
        from an_kla.sealed import SealedExtraNotInstalledError

        raise SealedExtraNotInstalledError(_EXTRA_NOT_INSTALLED_MSG) from exc
    return hashes, HKDFExpand


def _as_bytes(name: str, value: object) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    raise TypeError(f"{name} must be bytes, got {type(value).__name__}")


def hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-Expand HMAC-SHA256 (RFC 5869 §2.3) sobre una PRK uniforme.

    Aquí la PRK es la CEK (32 bytes uniformes del CSPRNG): **sin Extract**
    (ADR §1 / RFC 5869 §3.3). ``info`` provee la separación de dominio.
    """
    material = _as_bytes("prk", prk)
    info_bytes = _as_bytes("info", info)
    if not isinstance(length, int) or isinstance(length, bool):
        raise TypeError("length must be int")
    if length < 1:
        raise ValueError("length must be >= 1")
    if length > 255 * 32:  # límite estructural de HKDF-Expand con SHA-256
        raise ValueError("length exceeds 255 * 32 (HKDF-Expand limit)")
    hashes, hkdf_expand_cls = _require_hkdf_expand()
    return hkdf_expand_cls(
        algorithm=hashes.SHA256(), length=length, info=info_bytes
    ).derive(material)


def derive_subkeys(cek: bytes) -> SealedSubkeys:
    """Deriva las TRES subclaves exactas del ADR §1 desde la CEK.

    - ``aead_key      = HKDFExpand(CEK, b"aead-key",     32)``
    - ``bundle_id_raw = HKDFExpand(CEK, b"bundle-id",    16)``
    - ``mac_key       = HKDFExpand(CEK, b"manifest-mac", 32)``

    La CEK debe ser exactamente 32 bytes (validado ANTES del import del
    extra: un error de contrato del caller no depende del entorno).
    """
    material = _as_bytes("cek", cek)
    if len(material) != CEK_LENGTH:
        raise ValueError(f"cek must be exactly {CEK_LENGTH} bytes, got {len(material)}")
    return SealedSubkeys(
        aead_key=hkdf_expand(material, INFO_AEAD_KEY, AEAD_KEY_LENGTH),
        bundle_id_raw=hkdf_expand(material, INFO_BUNDLE_ID, BUNDLE_ID_RAW_LENGTH),
        mac_key=hkdf_expand(material, INFO_MANIFEST_MAC, MAC_KEY_LENGTH),
    )
