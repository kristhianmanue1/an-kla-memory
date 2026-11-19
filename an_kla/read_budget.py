"""Presupuesto exacto de las lecturas por prefijo (``history``, ``list``): el mayor prefijo cuya salida cabe.

``build(count, used)`` es la respuesta con los ``count`` primeros elementos y ``used`` como ``used_bytes``. El
tamaño exacto es el de la salida serializada con su salto de línea final (:func:`serialized_size`).
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .state_show import StateReadError, serialized_size

Build = Callable[[int, int], Mapping[str, Any]]


def fit_prefix(build: Build, total: int, budget: int, too_small_code: str) -> Mapping[str, Any]:
    """Respuesta con el mayor prefijo de ``total`` elementos que cabe en ``budget``; nunca lo supera.

    Si ni la respuesta vacía cabe, ``StateReadError(too_small_code)``. ``used_bytes`` acaba siendo la longitud
    real de la salida que lo contiene (punto fijo).
    """

    floor = serialized_size(build(0, budget))
    if floor > budget:
        raise StateReadError(too_small_code, f"la respuesta vacía necesita {floor} bytes")
    if serialized_size(build(total, budget)) <= budget:
        low = total
    else:
        low, high = 0, total - 1  # mayor prefijo que cabe; el tamaño crece con el prefijo
        while low < high:
            middle = (low + high + 1) // 2
            if serialized_size(build(middle, budget)) <= budget:
                low = middle
            else:
                high = middle - 1
    used = budget
    for _ in range(8):  # punto fijo: used_bytes es la longitud de la salida que lo contiene
        result = build(low, used)
        size = serialized_size(result)
        if size == used:
            return result
        used = size
    return build(low, budget)


__all__ = ["fit_prefix"]
