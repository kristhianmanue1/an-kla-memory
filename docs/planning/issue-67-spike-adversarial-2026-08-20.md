# Ronda adversarial — spike #67 recall de registros largos (2026-08-20)

Punto 7 del plan `plan-backlog-2026-08-20.md`. Revisor independiente con
re-ejecución propia de los experimentos. Tres pasadas: fix-and-retry →
fix-and-retry (3 correcciones) → corregidas.

## Resumen de las rondas

Ronda 1 (fix-and-retry, 7 hallazgos) — refutaciones clave que la v1 del
spike mereció y absorbió:

| Hallazgo | Corrección en v2 |
|---|---|
| El diseño de un término no podía detectar lo que el doc negaba ("no defecto de ranking") | Experimento 2 multi-término: **inversión de relevancia** medida (score-2 excluidos mientras score-1 servidos; episodes silenciados por completo a 2 000) |
| Remedio "usa summary" inválido (etiqueta sin semántica de tamaño; `text` prioriza en render; `model_derived` ya forzado a summary) | Remedios reales: `full` conciso o `indexable_text` (ADR-0018) |
| "Desplazan a varios cortos" afirmado sin medir; tie-break `(-score,id)` sin nombrar; cifras sólo core; sin semilla | Medido, nombrado, MCP medido (umbrales propios), semilla literal en el doc |

Ronda 2: 7 hallazgos → 5 cerrados, semilla errónea (62 B vs relleno
real ~108 B) y procedencia del recorte de `evaluate-v2` corregidas.

## Lo que el spike establece (verificado por el revisor con re-ejecución)

1. Asimetría de costo: comportamiento especificado del contrato.
2. **Inversión de relevancia bajo presupuesto**: el greedy
   `(-score, id)` sirve menos relevantes cuando los más relevantes son
   largos — defecto real del contrato actual, no bug del motor.
3. ADR-0029 (léxico/semántico) es eje separado.

## Decisión

- [x] proceed (el spike como evidencia; cierre de #67 con la inversión
  registrada)
- [ ] fix-and-retry
- [ ] escalate

En la mesa del maintainer: (1) dispensar o exigir las métricas por
estrategia (`evaluate-v2`) que el issue #67 pide como condición de
salida — este spike las recortó; (2) si la inversión de relevancia
merece ADR futuro (selección density-aware) o se archiva como límite
conocido del contrato.
