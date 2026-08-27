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
