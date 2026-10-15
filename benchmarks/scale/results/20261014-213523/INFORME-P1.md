# Comparativa P0 → P1 — batería de escala (issue #149)

Corrida P1: `benchmarks/scale/results/20261014-213523/` (mismos umbrales v1,
misma máquina: Python 3.12.12, macOS arm64; git del candidato
`feat/p1-watermark`). Línea base P0: `results/20261014-182904/`.

## Celdas gobernadas (vía pública)

| Celda | n P0→P1 | abort P0→P1 | p50 s | p95 s | wall s |
|---|---|---|---|---|---|
| s1-r0 | 472→**600** | sí→**no** | 0,57→0,27 | 1,82→0,73 | 343→187 |
| s200-r0 | 478→**600** | sí→**no** | 0,60→0,26 | 1,92→0,73 | 359→183 |
| s1-r10 | 403→**600** | sí→**no** | 0,47→0,28 | 1,74→0,79 | 254→198 |

Las tres celdas alcanzaron el objetivo de 600 escrituras sin disparar el
umbral de 2 s sostenidos: **el techo práctico de la vía gobernada superó la
línea base** (criterio de aceptación del ADR-0053).

## Forma de la curva

`snapshot` en la celda s1-r0: 0,004 s (50 revs) → 0,046 s (600 revs) —
crecimiento **lineal con los registros** (segmentos re-leídos por lectura,
F2), ya no cuadrático con la cadena (F1). El p50 de escritura se reduce a
la mitad porque plan y commit dejan de recorrer la historia completa.

Escenarios restantes en verde (concurrencia, crash, compactación,
diagnóstica): sin regresiones; los números completos en los JSON de la
corrida.

## Lectura contra los criterios del issue #149 (P1)

- "Las lecturas normales dejan de crecer con la historia total (crecen con
  el sufijo no verificado)": **cumplido para el eje revisiones**; el eje
  registros mantiene crecimiento lineal por re-lectura de segmentos, tal
  como el ADR declaró (F2 → P2c).
- "Test que corrompe el checkpoint derivado y demuestra equivalencia o
  fallo cerrado": `tests/test_watermark.py` (7 casos).

## Caveats

Números de una máquina concreta; la forma de la curva es el hallazgo. La
corrida usó los mismos umbrales commiteados pre-P0 (sin reajuste).
