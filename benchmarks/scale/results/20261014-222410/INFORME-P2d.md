# Informe comparativo P2d — lote gobernado (issue #149)

Corrida: `benchmarks/scale/results/20261014-222410/` (umbrales v1, Python
3.12.12, macOS arm64; candidato `feat/p2d-lote-gobernado@9597969`).
Escenario nuevo `ingest-batch`: lotes v2 de 50 registros, 600 registros
objetivo, mismas reglas de aborto por registro amortizado.

## Resultado

| Métrica | P1 single (600 escrituras) | **P2d lote (600 registros)** |
|---|---|---|
| Revisiones creadas | 600 | **12** |
| Pared total | 187 s | **0,2 s** |
| p50 por registro | 0,27 s | **~0,0004 s** |
| p50 por commit | 0,27 s | 0,02 s (lote de 50) |
| Aborto por umbral | no | no |

**~1000× en ingesta** frente a la vía de registro único con watermark, y
sin aborto de umbral. La ganancia es doble y explicable:

1. **Amortización de política/CAS**: una decisión, un plan, una revisión y
   un CAS por lote (el diseño del ADR-0054).
2. **Alivio de F2 no anticipado cuantitativamente**: 12 segmentos grandes
   en lugar de 601 diminutos — la re-lectura de segmentos del snapshot
   (eje registros que el watermark no toca) queda amortizada por la forma
   del lote. Esto convierte a P2d en acelerador también de lecturas bajo
   ingesta por lotes.

Snapshot dentro de la celda: 0,001–0,004 s (crece con registros, no con
revisiones). El resto de los escenarios (gobernada single, diagnóstica,
concurrencia, crash, compactación) sin regresiones.

## Lectura contra los criterios del issue (P2)

- "Commit gobernado en lote para ingestas que no debilite CAS ni política
  por record": **cumplido** (tests de contrato: pre-lote, intra-lote
  prohibido, all-or-nothing con efectos cero, techo por registro).
- El criterio de "retrieve/context_view independientes del N a 100k"
  (P2a/b) NO se aborda aquí: sigue pendiente.

## Caveats

Una máquina concreta; la forma es el hallazgo. Los números de lote son de
celda sintética con subjects=1; la concurrencia de escritores compitiendo
por lotes no se midió en esta corrida (la celda de concurrencia sigue en
vía single).
