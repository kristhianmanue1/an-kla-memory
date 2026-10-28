# Nota de corte — corrida oficial all-v2 (2026-10-28)

## Qué contiene este directorio

Resultados oficiales de cuatro de las cinco familias v2, con umbrales
aprobados (`thresholds-v2.json`, aprobación maintainer 2026-10-28):

- `ingest-cli.json` — ingesta gobernada por CLI.
- `concurrency-v2.json` — concurrencia 4×8, tasa de `LockBusyError`.
- `rare-query-index.json` — término raro índice sí/no.
- `crash-mid-commit.json` — SIGKILL mid-commit + diagnóstico.

Los cuatro archivos se volcaron en los primeros ~2 minutos de corrida
(11:04–11:06). **`compaction-large` no tiene resultado: la corrida fue
cortada por el integrador.**

## Evidencia del corte

- Proceso `python -m benchmarks.scale.battery --scenario all-v2`:
  ELAPSED 4:22:57, CPU TIME 245:32 (≈ 100 % de CPU constante) — compute-bound,
  no colgado.
- El muro presupuestario aprobado (`total_budget_wall_s` = 14400 s = 4 h)
  se superó en 22 minutos sin que la batería lo cortara (el presupuesto se
  verifica entre escenarios, no dentro de uno).
- Escenario dominante: la construcción de revisiones hacia la meta del
  issue (20.000) es cuadrática; a 4 h 20 m en 100 % CPU no alcanzó a
  terminar. Esto **confirma operativamente** la desviación ya declarada en
  `thresholds-v2.json` (`deviation_declared`: «compactación al máximo
  alcanzable pre-P1; 20k queda como criterio post-P1»).
- Corte con SIGTERM a las 15:27 aprox. (hora local); sin pérdida de los
  cuatro resultados previos.

## Consecuencias

1. Los cuatro JSON de este directorio son **oficiales** para decisiones
   (#166, #168, #169).
2. La compactación a 20 k queda **definitivamente post-P1**: sin una P1
   que abarate la construcción de revisiones, ninguna corrida futura debe
   intentar 20 k en un solo proceso (proyección: decenas de horas).
   Cuando P1 exista, re-corrida: `python -m benchmarks.scale.battery
   --scenario all-v2`.
3. Mejora pendiente de la batería (menor): el presupuesto de pared debería
   verificarse también dentro de los escenarios largos, no sólo entre
   escenarios.
