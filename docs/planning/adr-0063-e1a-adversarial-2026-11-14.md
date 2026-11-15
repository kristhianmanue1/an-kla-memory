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

## Ronda r2 — `fix-and-retry`

Mismo revisor (DeepSeek), contexto fresco. Cierre de r1: 18 filas cerradas,
6 parciales (H3, H5, M4, M8, L2, y B2 reabierto por otra vía), ninguna
abierta. H3 juzgado «parcial, aceptable, no bloqueante» con dos
condiciones. Hallazgos nuevos: 8 HIGH, 7 MED, 2 LOW. Dictamen íntegro fuera
del repo: `/var/tmp/orquestador-memoria/capitanes/ankla/ronda-adr0063/dictamen-r2-deepseek.md`.

| ID | Sev | Hallazgo | Disposición |
|---|---|---|---|
| H3 (cond.) | — | Exigir nombres únicos al lanzador y probar «dos sesiones, mismo nombre» | Aceptado: requisito del lanzador y caso en el criterio 4 |
| N1 | HIGH | El temporal de `atomic_write` vive en `pending/` y el vaciado lo tomaría | Aceptado: temporales en `tmp/`, publicación por `os.link`, patrón exacto de nombre |
| N2 | HIGH | `assert_unchanged` no detecta divergencia de custodia | Aceptado: preflight completo (`_custody_guard`) antes de crear nada y otra vez con el candado |
| N3 | HIGH | `decision: skip` no lanza y dejaría entradas para siempre | Aceptado: representación y `lineage` fijadas; `skip` → `remember_policy_skip` |
| N4 | HIGH | Orden de candados incompleto; el exclusivo quedaría dentro de `write_lock` | Aceptado: orden total bandeja → identidad → `write_lock` → gate; exclusivo al principio; criterio 9 |
| N5 | HIGH | FIFO, enlace o directorio en `pending/` bloquean el vaciado | Aceptado: `lstat` + `S_ISREG` + `st_nlink == 1`, `inbox_entry_unsafe` |
| N6 | HIGH | El punto de corte «entre `committed` y `CURRENT`» no existe; el replay nunca corre | Aceptado: paso 0 de reconciliación; criterio 3 con el orden real (`transactions.py:687` antes de `:725`) |
| N7 | MED | La deduplicación por clave pierde textos distintos con la misma clave | Aceptado: clave **y** `payload_sha256` |
| N8 | MED | El control «sin variables» es imposible porque `agent.cli` es obligatorio | Aceptado: «sin `AN_KLA_AGENT_NAME`» |
| N9 | HIGH | Record sin forma fijada: podía no ser recuperable | Aceptado: `{"id","text","an_kla_envelope"}`; criterio 1 exige recuperarlo |
| N10 | MED | Compatibilidad reclamada más ancha de lo real; ¿cuarto cambio? | Aceptado: criterio 5 acotado a stores sin bandeja; excepción declarada como parte de D1 |
| N11 | MED | `doctor` vería la bandeja del ancla como residuo tras `relocate` | Aceptado: `memory/inbox/` en `_KEPT_PREFIXES`; residuo 0 en el criterio 7 |
| N12 | MED | Taxonomía de errores del vaciado no casa con el código | Aceptado: máquina de estados explícita; códigos de aborto nunca van a `rejected/` |
| N13 | MED | `flock` compartido no es portable | Aceptado: exclusivo como degradación; prueba por plataforma |
| N14 | MED | Reintento por entrada = N commits bajo un candado | Aceptado: bisección soltando el candado entre intentos; tiempo máximo reportado |
| N15 | MED | Orden de pasos: el id depende del target | Aceptado: resolver target antes de deduplicar |
| N16 | LOW | Citas, rechazos invisibles al llamante, `--kind` omitido, `relocate plan` | Aceptado: citas corregidas; rechazos en las respuestas; regla de `--kind`; `plan` no exige bandeja vacía |
| N17 | LOW | Plazo corto, `inbox_busy`, colisión de nombre, prefijo de sesión, `identity_env_invalid` | Aceptado en los cinco puntos |

## Ronda r3 — `fix-and-retry` (tercera y última ronda; escalada)

Revisor de otra familia distinta de r1 y r2: Gemini vía `agy --mode plan`,
contexto fresco, sólo lectura. Cierre de r2: los 17 hallazgos y la
condición de H3, **cerrados**. Hallazgos nuevos: 3 HIGH, 1 MED, 2 LOW.
Dictamen íntegro fuera del repo:
`/var/tmp/orquestador-memoria/capitanes/ankla/ronda-adr0063/dictamen-r3-gemini.md`.

| ID | Sev | Hallazgo | Disposición |
|---|---|---|---|
| G1 | HIGH | Un corte entre `os.link` y `unlink` deja `st_nlink == 2` y la entrada legítima iría a `rejected/`; `os.link` no es portable | Aceptado: `os.replace` desde `tmp/` |
| G2 | HIGH | La bisección soltando `write_lock` aborta en bucle bajo concurrencia | Aceptado: prevalidación pura por entrada y aislamiento uno a uno sin soltar el candado |
| G3 | HIGH | El paso 0 no puede reconocer sus journals por UUIDv5 y `inspect_transaction` no escribe | Aceptado: marcadores `inflight/<txid>.json` y cierre por la ruta de reconciliación de `_commit_locked` |
| G4 | MED | `remember` sin resultado definido si su entrada no entra en el lote | Aceptado: el lote de `remember` incluye su entrada; si no se compromete, `queued` o rechazo |
| G5 | LOW | Falta `inbox-drain-result-v1` | Aceptado |
| G6 | LOW | Cita de `issuer` | Aceptado: `write_policy.py:414-434` |

**Estado tras r3:** correcciones absorbidas en el texto, **sin ronda que
las verifique**. El tope del mandato (tres rondas) se alcanzó sin `proceed`:
se escala al orquestador. El ADR sigue en `Propuesta` y su PR sin fusionar.

## Ronda r4 — `fix-and-retry` (acotada al delta `3ebf1d4..4e6f9da`; última)

Autorizada por el orquestador (mandato 3, opción a). Revisor: DeepSeek por
OpenCode, contexto fresco, distinto del de r3. Dictamen íntegro fuera del
repo: `/var/tmp/orquestador-memoria/capitanes/ankla/ronda-adr0063/dictamen-r4-deepseek.md`.

Cierre de r3: G1, G5 y G6 cerrados; G2, G3 y G4 parciales. Hallazgos: 2 HIGH,
4 MED, 2 LOW, más una observación heredada.

| ID | Sev | Hallazgo | Disposición |
|---|---|---|---|
| H1 | HIGH | El aislamiento «contra la misma base» es imposible: el primer commit mueve `CURRENT` | Corregido: bisección en memoria contra la misma base; los supervivientes se replanifican contra el `CURRENT` releído; el uno a uno, sólo como último recurso y replanificado |
| H2 | HIGH→MED | Coste del aislamiento no acotado | Corregido: ≤ 8 niveles de evaluación pura por entrada mala y un solo commit; la cifra de las Consecuencias declara qué no incluye |
| H3–H8, heredada | MED/LOW | Ver «Deuda abierta tras la ronda r4» en el ADR | Anotados como deuda obligatoria para la fase B, según el mandato 3 |

**Estado:** H1 y H2 corregidos sin ronda que los verifique. Sin `proceed`:
#199 no se fusiona y se escala al orquestador.
