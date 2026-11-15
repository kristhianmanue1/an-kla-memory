# Ronda adversarial pre-code — ADR-0063 (2026-11-14)

Objeto: `docs/architecture/0063-escritura-una-llamada-bandeja-escritor-disputa-v1.md`
(Propuesta), E1.a del esfuerzo de memoria agéntica.
Método: revisor de **otra familia** (DeepSeek `deepseek-v4.1-flash-1017` vía
`opencode run --standalone`), contexto fresco, sólo lectura, con el ADR, el
código de `main@29c5ec0`, C0 y el spike de sólo lectura de E1.a. Autor del
ADR: capitán de an-kla (Claude Opus 5.5).

## Spike previo (sólo lectura, ejecutor Claude Sonnet)

Veredicto `refine`, absorbido en el ADR antes de la ronda:

| Hallazgo | Evidencia | Absorción |
|---|---|---|
| Un archivo bajo `inbox/` hace fallar `export`, sellado y `relocate plan` | `export_unrecognized_durable_path`, ejecutado; `export_restore.py:84-98` | Exclusión de `memory/inbox/` y precondición `inbox_pending` |
| `commit_write_plan` no es reentrante bajo `write_lock` | `write_lock_busy` a los 10,06 s, ejecutado | Extracción `_commit_write_plan_locked` |
| El tope real del lote con sobre es ≈ 380, no 1000 | bisección: 380 ok, 400 `invalid_write_plan` | Lotes por presupuesto de nodos, 250 por lote |
| El vaciado cuesta ≤ 0,20 s con 1000 records planos sobre 20.000 | 3 repeticiones por celda | Se retira la preocupación por el plazo de 10 s |

## Ronda r1 — `fix-and-retry`

3 BLOCKER, 9 HIGH, 8 MED, 6 LOW. Dictamen íntegro fuera del repo (datos del
revisor): `/var/tmp/orquestador-memoria/capitanes/ankla/ronda-adr0063/dictamen-r1-deepseek.md`.

| ID | Sev | Hallazgo | Disposición |
|---|---|---|---|
| B1 | BLOCKER | C0 citada en `d1d4e6b`; ya está congelada en `main@8fccbcc` con cambios (caso 2, centinela de rol) | Aceptado: se cita `8fccbcc`; rol admite `desconocido`; sólo `agent.cli` obligatorio |
| B2 | BLOCKER | Dos entradas con el mismo id o un error terminal de política bloquean la escritura para siempre | Aceptado: deduplicación dentro de `pending/`, reintento por entrada y `rejected/` con código para errores terminales |
| B3 | BLOCKER | `relocate` pierde o encalla entradas (rename entre volúmenes, `_only_planned_files`, carrera) | Aceptado con otra corrección: no se traslada la bandeja; candado de bandeja exclusivo en `export`/`relocate` y `inbox_pending`; encolado con candado compartido y revalidación de custodia |
| H1 | HIGH | `an_kla_remember` hace escribible el MCP contra ADR-0003/0047 | Aceptado: MCP escribible fuera de E1.a (a E1.c con su ADR) |
| H2 | HIGH | `--supersedes` ambiguo entre streams | Aceptado: búsqueda en los tres streams, `remember_target_ambiguous`, stream heredado, `remember_kind_mismatch` |
| H3 | HIGH | `(repo.id, agent.name)` identifica un rol, no un proceso; sin entorno todo es disputa | Parcial: se mantiene el nombre como unidad (reanudar en otra sesión debe seguir siendo propio), se declara el límite y se añade el caso sin entorno al criterio 4 |
| H4 | HIGH | La clave ignora el target: dos sustituciones distintas colapsan | Aceptado: `supersedes` entra en la clave; colisión de id con otra clave → `remember_id_collision` |
| H5 | HIGH | Sin `transaction_id`, un corte deja journals huérfanos | Aceptado: `transaction_id` uuid5 determinista por lote; punto de corte añadido |
| H6 | HIGH | Falta fsync del temporal antes del rename | Aceptado: `storage_primitives`; punto de corte en el encolado |
| H7 | HIGH | Propia/ajena decidida al encolar, fuera del candado | Aceptado: la entrada guarda sólo `target_id`; se resuelve bajo el candado |
| H8 | HIGH | `target_record_sha256` sobre records con overlay | Aceptado: `digest_json(snapshot.raw_records[…])` |
| H9 | HIGH | `remember` inutilizable sin Git; código de error ambiguo | Aceptado: `identity_repo_unavailable` vs `identity_env_missing`; Git exigido y declarado; `plan-write` sigue como camino sin Git |
| M1 | MED | Tope de 250 contradice el criterio 8 | Aceptado: `inbox drain` itera lotes; `remember` vacía uno |
| M2 | MED | `--text` expone el contenido en `argv` | Aceptado: `--text-file -` recomendado, máximo 64 KiB, canal declarado |
| M3 | MED | `export create` crea el destino antes de comprobar | Aceptado: comprobación antes del `mkdir` y repetida con candado |
| M4 | MED | `rejected/` invisible | Aceptado: `inbox status` lo informa con motivo; sin GC, declarado |
| M5 | MED | La hora es de encolado, no de commit | Aceptado: `enqueued_at`; la hora de commit se declara no registrada |
| M6 | MED | `plan_duplicate_id` no actúa en el camino nuevo | Aceptado: texto corregido (`_assign_records` + deduplicación) |
| M7 | MED | La exclusión de `inbox/` saltaría los chequeos de enlace | Aceptado: exclusión después de los chequeos |
| M8 | MED | Criterios autocumplidos o no medibles | Aceptado: CAS explícito, cuatro puntos de corte, export por `manifest_sha256`, medida de «no toca la bandeja» |
| L1 | LOW | Prefijo de id no definido | Aceptado: `f`/`e`/`ep` |
| L2 | LOW | Citas de línea imprecisas | Aceptado: corregidas |
| L3 | LOW | `derived_from_retrieval` sí sobrevive como razón | Aceptado |
| L4 | LOW | `compact` es seguro por `_RULES`, no por la precondición | Aceptado |
| L5 | LOW | Testigo del candado y post-proceso | Aceptado: `lock_result` al cuerpo y post-proceso común |
| L6 | LOW | Referencias de #197 incoherentes | Aceptado |
