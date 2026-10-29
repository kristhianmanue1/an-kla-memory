# ADR-0059: Espera acotada del escritor en el reader gate durante `compact commit`

- **Estado:** Aceptada (implementada)
- **Implementación:** Implementada (`reader_gate::shared_reader_gate_bounded` + `store::writer_gate` en `plan_write`; constante única `WRITE_LOCK_DEADLINE_SECONDS`; código `writer_gate_busy` en capabilities y agente de ejemplo)
- **Fecha:** 2026-10-29
- **Decide sobre:** acotar la espera del camino de escritura sobre el reader gate compartido mientras la compactación mantiene la exclusión, con error estable reintentable; los lectores comunes no cambian.

## Contexto

El reader gate (`an_kla/reader_gate.py`) es un `flock` por store: los
lectores toman `LOCK_SH` y la compactación toma `LOCK_EX`
(`exclusive_reader_gate`, que sí tiene `timeout=10` → `compaction_readers_active`)
durante todo su commit. `shared_reader_gate`, en cambio, hace
`fcntl.flock(handle.fileno(), fcntl.LOCK_SH)` **bloqueante y sin deadline**:
un escritor que entra a `commit_write_plan` durante la ventana de
compactación se queda esperando sin acote.

El deadline de 10 s del lock de escritura (issue #111/P2) vive en **otro**
lock (`write_lock`): no protege esta espera. La batería v2 de #167 lo midió
oficialmente (`benchmarks/scale/results/20261028-110445/compaction-large.json`,
corrida reducida): la sonda de escritura quedó bloqueada **52,3 s** con
`lock_busy_errors: 0` durante la compactación de 302 revisiones, y en la
corrida oficial la ventana de compactación a escala del issue resultó
no terminable pre-P1 (`NOTA-CORTE.md`: 4 h 20 m al 100 % CPU). La ventana de
indisponibilidad de escritura es, por tanto, **no acotada por diseño actual**
y crece con el store. Issue #186.

Restricciones: la compactación necesita drenar lectores antes de tomar `EX`
y sostenerlo durante su commit (ADR de compactación vigente); el caller de
escritura ya trata `LockBusyError` como reintentable (backoff propio de los
consumidores gobernados); los tests congelados de locks y compactación
pinnean comportamientos que no deben moverse.

## Decisión

**Toda adquisición del reader gate por el camino de escritura es acotada**
— tanto en planificación (`plan_write`, cuyo `snapshot` es la espera
desprotegida real) como en commit (`commit_write_plan` y equivalentes de
refute/supersede)— con el deadline de **una sola constante con nombre**:

1. Nueva adquisición acotada en `reader_gate` (mismo patrón de sondeo
   `LOCK_SH | LOCK_NB` + deadline que ya usa `exclusive_reader_gate`),
   usada por **todo el camino de escritura**: `plan_write` y los commits
   gobernados.
2. La constante canónica es **una sola con nombre** — la existente
   `WRITE_LOCK_DEADLINE_SECONDS` (`store_locks.py`) pasa a consumirse
   también por el gate acotado, `exclusive_reader_gate`, la ventana de
   `relocate` y el drenaje de `compaction.py` (hoy hay cuatro 10 s
   independientes: `store_locks.py`, el default de `exclusive_reader_gate`,
   `relocate._GATE_TIMEOUT` y `compaction.py`); el valor sigue siendo 10 s,
   pero con una única fuente de verdad.
3. Al vencer el deadline, el store levanta `LockBusyError` con detalle
   estable **`writer_gate_busy`**: misma clase reintentable que ya manejan
   los callers, código que lo distingue de la espera del lock de escritura.
4. **Declaración del código nuevo (ronda externa 2026-10-29, hallazgo
   alto)**: `writer_gate_busy` se registra en la superficie de errores de
   `capabilities`, en el **conjunto de reintentos del agente de ejemplo**
   (`examples/agent-integration/ankla_agent.py` hoy sólo reintentan ante
   `"write_lock_busy"`; con el código sin declarar el reintento caería a
   fallo terminal) y en la documentación de escritura si lista códigos.
5. **Los lectores comunes no cambian**: siguen bloqueando en `LOCK_SH`
   hasta que la compactación libere. Esperar es el comportamiento correcto
   para lecturas; fallarlas degradaría el caso común para ahorrar en el
   raro.

## Por qué no [alternativas]

- **Acotar también los lectores**: durante la ventana, cada reintento de
  lector fallaría y reintentaría contra una compactación que sigue
  sosteniendo `EX`; degrada el caso común sin comprimir la ventana.
- **Dejar la espera indefinida y documentarla**: deja el presupuesto de
  disponibilidad de escritura indefinido (la queja exacta de #186) y con
  P1 a la vista las ventanas pueden ser largas.
- **Error nuevo no reintentable**: obligaría a cada consumidor a aprender
  un caso nuevo; la clase reintentable ya existe y los callers ya hacen
  backoff sobre ella.

## Consecuencias

- Escritores durante `compact commit`: fallan cerrado a los 10 s con
  `writer_gate_busy`, reintentables; el caller conserva el control del
  backoff. La compactación no cambia.
- La batería queda en condiciones de medir la tasa post-fix (el issue
  #186 pedía exactamente esa tasa).
- `writer_gate_busy` se declara en `capabilities`, en el conjunto de
  reintentos del agente de ejemplo y en la documentación de escritura
  (hallazgo alto de la ronda externa: sin esa declaración el reintento del
  agente caería a fallo terminal).
- La constante única con nombre elimina las cuatro definiciones
  independientes de 10 s que hoy existen (`store_locks.py`, default de
  `exclusive_reader_gate`, `relocate._GATE_TIMEOUT`, `compaction.py`).
- El valor 10 s pasa a significar «toda espera de escritor» (lock de
  escritura, gate y planificación): una sola constante, un solo contrato.

## Test de regresión

- Determinista: un proceso/hilo sostiene `LOCK_EX` (compactación
  simulada) y un `commit_write_plan` concurrente recibe
  `LockBusyError("writer_gate_busy")` al vencer el deadline (con deadline
  inyectable corto para el test).
- Mismo aserto para `plan_write` (la espera desprotegida real detectada
  por la ronda externa: su `snapshot` adquiere `LOCK_SH` sin deadline).
- Lector concurrente en la misma ventana sigue bloqueando y tiene éxito
  al liberarse (comportamiento de lector preservado).
- Sin compactación: camino feliz de escritura idéntico (el gate acotado
  adquiere al primer intento).
- El agente de ejemplo reintenta ante `writer_gate_busy` (su conjunto de
  códigos reintentables incluye el nuevo).
- Ronda adversarial obligatoria antes de implementar: toca el camino de
  escritura del store y `reader_gate.py`. Ronda pre-code ejecutada
  2026-10-29 (externa, otra familia): `fix-and-retry` con tres hallazgos,
  absorbidos en esta versión (alcance plan_write+commit, declaración del
  código en el agente de ejemplo, constante única con nombre).

## Referencias

Issue #186; issue #111/P2 (deadline del lock de escritura, patrón y
constante); batería v2 #167 (`results/20261028-110445/compaction-large.json`
y `NOTA-CORTE.md`); ADR-0060 (hermano del mismo entrelazado
escritor/compactación).
