# ADR-0059: Espera acotada del escritor en el reader gate durante `compact commit`

- **Estado:** Propuesta
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

**El camino de escritura adquiere el reader gate con deadline** (el mismo
10 s del lock de escritura: una sola constante para toda espera de
escritor):

1. Nueva adquisición acotada en `reader_gate` (mismo patrón de sondeo
   `LOCK_SH | LOCK_NB` + deadline que ya usa `exclusive_reader_gate`),
   usada **sólo por el camino de escritura gobernada**
   (`commit_write_plan` y equivalentes de refute/supersede).
2. Al vencer el deadline, el store levanta `LockBusyError` con detalle
   estable **`writer_gate_busy`**: misma clase reintentable que ya manejan
   los callers, código que lo distingue de la espera del lock de escritura.
3. **Los lectores comunes no cambian**: siguen bloqueando en `LOCK_SH`
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
- `writer_gate_busy` se documenta en la superficie de errores
  (`capabilities`) y, si la referencia de agentes lista códigos de
  escritura, ahí también.
- El valor 10 s pasa a significar «toda espera de escritor» (lock de
  escritura y gate): una sola constante, un solo contrato.

## Test de regresión

- Determinista: un proceso/hilo sostiene `LOCK_EX` (compactación
  simulada) y un `commit_write_plan` concurrente recibe
  `LockBusyError("writer_gate_busy")` al vencer el deadline (con deadline
  inyectable corto para el test).
- Lector concurrente en la misma ventana sigue bloqueando y tiene éxito
  al liberarse (comportamiento de lector preservado).
- Sin compactación: camino feliz de escritura idéntico (el gate acotado
  adquiere al primer intento).
- Ronda adversarial obligatoria antes de implementar: toca el camino de
  escritura del store y `reader_gate.py`.

## Referencias

Issue #186; issue #111/P2 (deadline del lock de escritura, patrón y
constante); batería v2 #167 (`results/20261028-110445/compaction-large.json`
y `NOTA-CORTE.md`); ADR-0060 (hermano del mismo entrelazado
escritor/compactación).
