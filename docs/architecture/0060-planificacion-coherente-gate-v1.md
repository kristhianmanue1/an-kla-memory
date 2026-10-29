# ADR-0060: Planificación coherente bajo un solo gate (elimina el TOCTOU de `plan_write` con compactación)

- **Estado:** Aceptada (implementada)
- **Implementación:** Implementada (`store::plan_write`, `refutations::plan_refute` y `evaluation_strategies` bajo un solo gate; commit CAS sin cambios)
- **Fecha:** 2026-10-29
- **Decide sobre:** eliminar la carrera de `plan_write` con la compactación sosteniendo el par `read_current` + `snapshot` bajo una sola adquisición del reader gate; el CAS benigno del commit queda como única señal que necesita el caller.

## Contexto

`plan_write` (`an_kla/store.py`) hoy hace:

```python
observed = self.read_current()
...
guard_plan_against_snapshot(self.snapshot(observed).records, proposal)
```

`read_current` **no toma el reader gate** (lee CURRENT directamente) y
`snapshot()` abre su propia adquisición `LOCK_SH` después. Entre ambas hay
una ventana: si la compactación commitea justo ahí, archiva la revisión `R`
que `plan_write` leyó como base y el `snapshot(R)` posterior falla con
`IntegrityError("revision_archived_by_compaction")` — el código de
integridad que reservan las lecturas de revisiones archivadas.

La batería v2 (#167) registró la carrera en carrera real
(`results/20261028-110445/`: `epoch_archived_events: 1`), y el hallazgo se
abrió como issue #187. Corrección del registro respecto del issue: el
**commit** ya es benigno — `write_commit` compara `read_current()` contra
`expected_current_hash` bajo lock y levanta el CAS
`write_plan_base_changed` (`write_commit.py`: "antes de rechazar por CAS...")
antes de resolver nada de la base. La carrera vive en la **planificación**,
no en el commit.

El efecto práctico: una carrera benigna («el store avanzó; re-planifica»)
se reporta con el código de integridad que reservan las lecturas rotas, y
el caller no puede distinguir «re-planifica» de «escala el problema».

## Decisión

**Coherencia por construcción en toda la planificación**: el par
`read_current` + `snapshot` se ejecuta bajo **una sola adquisición** del
reader gate compartido en **todos los caminos que lo forman hoy** — no sólo
`plan_write`:

1. `plan_write` (`store.py`): abre `shared_reader_gate` y dentro resuelve
   `read_current`, la guardia temprana (`guard_plan_against_snapshot`) y el
   snapshot que necesite.
2. `plan_refute` (`refutations.py`): mismo par no atómico detectado por la
   ronda externa (`read_current()` seguido de `snapshot(observed)`) —
   mismo tratamiento.
3. `evaluation_strategies.py` (ambas funciones de evaluación): mismo par
   para el corpus de evaluación — mismo tratamiento.
4. El gate es reentrante por hilo: las adquisiciones internas de
   `read_current`/`snapshot` incrementan profundidad, no compiten.
5. Con el gate sostenido, la compactación no puede tomar `LOCK_EX` a medio
   plan: la revisión base permanece legible durante toda la planificación.
6. **Interacción con el drenaje de la compactación (hallazgo medio de la
   ronda)**: la compactación espera drenaje con su propio presupuesto
   (`compaction.py`: `gate_deadline` +10 s → `compaction_readers_active`
   fail-closed). Las retenciones de planificación son cortas y de sólo
   lectura; con planificación frecuente, el fail-closed existente + reintento
   de la compactación es la mitigación aceptada, y ADR-0059 acota además
   toda espera de escritor. Se deja anotado: si la hambruna del compactador
   se midiera real, la escalación es un indicador de peso (`yield` del gate
   entre fases de planificación), no un cambio de esta decisión.
7. **Sin código nuevo de error**: si la base se mueve después de
   planificar, el caller recibe el CAS ya existente `write_plan_base_changed`
   en el commit — única señal necesaria, ya documentada. La invariante que
   deja fijada esta ADR: *todo par `read_current`+`snapshot` coherente vive
   bajo una sola adquisición del gate* (patrón que `inventory` ya sigue).

## Por qué no [alternativas]

- **Mapear `revision_archived_by_compaction` a un error benigno en
  planificación**: clasifica la carrera pero no la elimina; dejaría una
  ventana conocida con parche semántico en vez de cerrarla.
- **Reintentar `plan_write` internamente ante el IntegrityError**: reintento
  a ciegas tras un fallo (contra la práctica de la casa: inspeccionar
  primero); además escondría del caller un movimiento real del store.
- **Cambiar el commit para reordenar CAS/snapshot**: innecesario — el
  commit ya compara `read_current` antes de tocar la base
  (`write_plan_base_changed`); la carrera no está ahí.
- **Tocar las lecturas de revisiones archivadas** (`inventory`, `snapshot`
  explícito): ahí `revision_archived_by_compaction` es la señal correcta y
  fail-closed; no se toca.

## Consecuencias

- `plan_write` no puede fallar por la carrera con compactación; el coste es
  retener `LOCK_SH` unos milisegundos más por planificación (la
  compactación espera drenaje, dentro de su propio presupuesto).
- El caller de escritura gobierna todo el ciclo con dos señales claras:
  planificación coherente + `write_plan_base_changed` al commit. La batería
  puede seguir contando `epoch_archived_events` desde el CAS.
- La invariante «par coherente bajo un gate» queda documentada para
  revisión en cualquier nuevo camino de lectura compuesta.
- Ronda adversarial obligatoria antes de implementar: el fix toca el camino
  de planificación del store (`store.py`).

## Test de regresión

- Determinista: con la guardia de planificación ralentizada (patch de
  `guard_plan_against_snapshot`), un hilo que intenta `LOCK_EX` durante
  `plan_write` no la obtiene hasta que la planificación termina, y el plan
  resultante es coherente con la revisión devuelta.
- La carrera sembrada (archivado de la base entre `read_current` y
  `snapshot`) deja de ser alcanzable: con el gate sostenido no hay ventana.
- Mismo aserto de coherencia para `plan_refute` y para las funciones de
  `evaluation_strategies` (pares detectados por la ronda externa).
- El commit ante base movida sigue respondiendo exactamente
  `write_plan_base_changed` (sin cambios — pinneo el comportamiento).
- `inventory`/`snapshot` explícito de revisión archivada siguen levantando
  `revision_archived_by_compaction` (sin cambios).

## Referencias

Issue #187 (con corrección del mecanismo: la carrera es de planificación,
no de commit); ADR-0059 (hermano: espera acotada del escritor); batería v2
#167 (`results/20261028-110445/`); contrato de escritura ADR-0024 §API/CLI
(CAS `write_plan_base_changed`).
