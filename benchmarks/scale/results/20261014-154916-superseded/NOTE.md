# Corrida superseded (instrumentación, no producto)

Primera corrida oficial, invalidada por tres bugs de la batería detectados
al cerrar: (1) la celda de supersedes elegía targets ya sustituidos
(`plan_supersede_target_not_vigente`); (2) `compact commit` omitía
`--bundle` (fail-closed `compaction_bundle_required`); (3) la columna
diagnóstica medía context_view sólo en el régimen de 200 sujetos y sin
registrar el código de resultado. Los escenarios concurrency (4W/8R: 0
LockBusyError, 439 conflictos CAS vs 172 escrituras), crash (10/10 verify
ok) y reads-diagnostic parcial quedan como evidencia histórica útil; la
corrida válida es la posterior con la instrumentación corregida.
