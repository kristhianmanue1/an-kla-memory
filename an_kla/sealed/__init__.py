"""Perfil sellado de AN-KLA — esqueleto de disponibilidad (issue #46, T1).

Contrato de esta fase (solo esqueleto; sin criptografía funcional — T2+):

- ``sealed_available``: ``True`` únicamente si el extra ``[sealed]``
  (``cryptography>=42``) está instalado en el intérprete. La detección es
  **perezosa**: este módulo nunca importa ``cryptography`` a nivel top-level
  y el core (``an_kla``) sigue siendo importable stdlib-only.

- **Fail-closed**: sin el extra, TODO comando sellado (``sealed_export``,
  ``sealed_restore``, y cualquier entrada futura del perfil) debe fallar con
  :class:`SealedExtraNotInstalledError`, cuyo código canónico es
  ``sealing_extra_not_installed``. No existe degradación a export/restore en
  claro: la ausencia del extra es un error terminal, no un fallback.

T2+ (KDF/CEK/adaptador/cifrado del bundle) NO vive aquí todavía; las
señales canónicas que ese futuro código consuma se declaran en este módulo
para que el error de disponibilidad sea estable desde ya.

T2 (issue #46) — KDF y CEK YA VIVEN en los submódulos ``an_kla.sealed.kdf``
y ``an_kla.sealed.cek`` (HKDF-SHA256 solo-Expand con separación de dominio
por propósito, y CEK efímera con wrap/unwrap como contrato de función con
KEK inyectable). Se re-exportan aquí para superficie estable, SIN cambiar
nada del contrato T1: estos submódulos importan ``cryptography`` solo
perezosamente (dentro de funciones), por lo que ``import an_kla.sealed``
sigue siendo stdlib-only y fail-closed.

Nota del adversarial T1 honrada: ``sealed_available`` es una señal
**por-proceso** (se calcula al importar este módulo); KDF/CEK NO se acoplan
a ese flag — sus operaciones fallan por su propio import real, de forma
independiente del estado del flag.
"""

from __future__ import annotations

# Código de error canónico del perfil sellado. Estable desde T1: los
# comandos sellados y su superficie de error (CLI/MCP) lo referencian.
SEALED_EXTRA_ERROR_CODE = "sealing_extra_not_installed"

_EXTRA_NOT_INSTALLED_MSG = (
    "sealed profile unavailable: the 'sealed' extra is not installed "
    "(pip install 'an-kla-memory[sealed]'); refusing to degrade to cleartext"
)


class SealedExtraNotInstalledError(RuntimeError):
    """Todo comando sellado sin el extra ``[sealed]`` falla cerrado con esto.

    El código canónico ``sealing_extra_not_installed`` vive en
    ``SEALED_EXTRA_ERROR_CODE`` y NO cambia entre fases (T2+ lo reutilizan).
    """


def _cryptography_installed() -> bool:
    """Detección perezosa y aislada del extra ``[sealed]``.

    Importa ``cryptography`` SOLO dentro de esta función (nunca a nivel
    top-level), de modo que ``import an_kla.sealed`` no arrastre al core
    dependencias fuera de la stdlib. El import se descarta inmediatamente:
    aquí sólo se mide disponibilidad, no se usa la biblioteca.
    """
    try:
        import cryptography  # noqa: F401  (sólo prueba de disponibilidad)
        import cryptography.hazmat.primitives.ciphers.aead  # noqa: F401
    except ImportError:
        return False
    return True


#: Disponibilidad del perfil sellado en este intérprete. ``False`` sin el
#: extra ``[sealed]``; se evalúa perezosamente al primer acceso (attribute
#: de módulo calculado una sola vez al importar este submódulo).
sealed_available: bool = _cryptography_installed()


def _require_sealed_extra() -> None:
    """Fail-closed: raises si el extra ``[sealed]`` no está disponible."""
    if not sealed_available:
        raise SealedExtraNotInstalledError(_EXTRA_NOT_INSTALLED_MSG)


def sealed_export(args: list) -> None:
    """Comando sellado de exportación — esqueleto T1.

    Sin el extra ``[sealed]`` falla SIEMPRE cerrado con
    ``SealedExtraNotInstalledError`` (código ``sealing_extra_not_installed``).
    Con el extra instalado sigue siendo un stub: también falla cerrado
    (``NotImplementedError``) porque la funcionalidad llega en T4.
    """
    _require_sealed_extra()
    raise NotImplementedError("sealed_export arrives in T4 (issue #46)")


def sealed_restore(args: list) -> None:
    """Comando sellado de restauración — esqueleto T1. Contrato idéntico a
    :func:`sealed_export` (fail-closed sin extra; ``NotImplementedError``
    con extra hasta T4)."""
    _require_sealed_extra()
    raise NotImplementedError("sealed_restore arrives in T4 (issue #46)")


# --- T2 (issue #46): re-exportación de la superficie KDF/CEK ----------------
# Import de submódulos stdlib-safe: kdf/cek importan cryptography SOLO dentro
# de funciones (perezoso), así que este import top-level no rompe la promesa
# stdlib-only del core.
from an_kla.sealed.cek import (  # noqa: E402
    WRAP_NONCE_LENGTH,
    WRAPPED_CEK_BLOB_LENGTH,
    SealedCekUnwrapError,
    WrappedCek,
    generate_cek,
    unwrap_cek,
    wrap_cek,
)
from an_kla.sealed.kdf import (  # noqa: E402
    AEAD_KEY_LENGTH,
    BUNDLE_ID_RAW_LENGTH,
    CEK_LENGTH,
    INFO_AEAD_KEY,
    INFO_BUNDLE_ID,
    INFO_MANIFEST_MAC,
    MAC_KEY_LENGTH,
    SealedSubkeys,
    derive_subkeys,
    hkdf_expand,
)

# --- T3 (issue #46): runner seguro del adaptador externo de claves --------
# key_adapter es stdlib PURA (sin cryptography en ningún camino) y ejecuta
# el proceso adaptador externo con el contrato JSON cerrado por stdio del
# ADR-0042 §4. Código de error canónico adicional: sealing_adapter_error /
# sealing_adapter_required (ADR §5).
from an_kla.sealed.key_adapter import (  # noqa: E402
    ADAPTER_STDERR_LIMIT,
    ADAPTER_STDIN_LIMIT,
    ADAPTER_STDOUT_LIMIT,
    ADAPTER_TERM_GRACE_SECONDS,
    ADAPTER_TIMEOUT_SECONDS,
    ADAPTER_WRAPPED_CEK_MAX_CHARS,
    SEALING_ADAPTER_ERROR_CODE,
    SEALING_ADAPTER_REQUIRED_CODE,
    AdapterResult,
    SealingAdapterError,
    SealingAdapterRequiredError,
    SealingAdapterRunner,
)
