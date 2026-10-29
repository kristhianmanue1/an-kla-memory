# Cota de disco para 20.000 revisiones — 2026-10-29

La construcción actual de `compaction-large` añade un fact y un segmento
nuevo por revisión. `transactions.commit_locked` copia la lista acumulada
`facts_segments` del padre y añade el nuevo digest; cada manifiesto histórico
es inmutable y permanece hasta la compactación. ADR-0061 no cambia esos bytes.

## Cálculo refutable

Un identificador `sha256:` más 64 hex ocupa 71 bytes ASCII; su string JSON
canónico ocupa 73 bytes, sin contar comas ni claves. Por tanto, para N
revisiones con N segmentos nuevos distintos, sólo esos strings en todos los
manifiestos requieren al menos:

`73 * N * (N + 1) / 2` bytes.

Para N=20.000: **14.600.730.000 bytes** (~13,60 GiB), excluyendo comas, otros
campos, segmentos, journals y recibos. El ceiling declarado en
`benchmarks/scale/thresholds-v2.json` es **2.147.483.648 bytes por store**:
la cota inferior lo excede por **6,80 veces**.

Control observado en store diagnóstico efímero (sin modificarlo): CURRENT
rev566, 566 referencias a segmentos de 71 caracteres, manifiesto de 42.410
bytes. Código que sustenta las premisas: `scenarios_durability.run_compaction_large`
(una revisión por fact), `transactions.commit_locked` (listas acumulativas),
`store._write_json_object`/`_write_immutable` (objetos históricos distintos).

La cota queda refutada si el constructor no crea un segmento distinto por
revisión, si se modifican las listas acumulativas/formato, o si se permite
podar historia durante la preparación. Esas condiciones cambiarían el
escenario o el formato actuales; no se asumen aquí.

## Consecuencia para aceptación

No ejecutar una construcción oficial que necesariamente supera el presupuesto
aprobado, ni elevar el ceiling por iniciativa del agente. La meta de
**20.000 revisiones** no se reduce: permanece pendiente y no puede declararse
aceptada bajo este constructor y este presupuesto, aun si ADR-0061 acelera CPU.
Hace falta decisión posterior del Operador sobre formato/constructor o recursos.
No se sustituye por 20k registros en lotes ni por compactación intermedia.

El harness informa tamaños pero no aplica actualmente ese ceiling durante la
construcción. Es una limitación del procedimiento, no permiso para excederlo.
Este documento añade evidencia y un límite a la aceptación; no autoriza otro
formato ni cambia umbrales o el alcance de implementación de ADR-0061.

Control rev566 preservado en
[evidence/construction-profile-20261029/manifest-bound.json](evidence/construction-profile-20261029/manifest-bound.json),
con CURRENT, ruta exacta del objeto y métricas de bytes leídas. Para refutar
ese control mientras exista el store efímero, leer su CURRENT y objeto JSON,
comparar `revision`, `len(facts_segments)`, longitud ASCII de cada referencia
y `len(path.read_bytes())`; no ejecutar escrituras ni inicializar memoria.
La demostración principal depende del código/representación, no de la vida
del store efímero. Revisión separada por `/root/review_probe_prerequisite`:
proceed documental, mismo contexto de la revisión del harness; sin acceso
a stores, verificó las premisas del código y aritmética, no el control rev566.
