# Ronda adversarial — mesa de diseño #140/#149 (ADR-0052/0053/0054), 2026-10-14

Artefacto atacado: los tres ADRs de propuesta de la mesa de diseño
(`0052-resolver-autoridad-host-v1`, `0053-watermark-verificacion-incremental-v1`,
`0054-commit-lote-v2`) contra el código real de `main@cf47cd1` y la batería
P0. Ronda de refinamiento pre-decisión (ADRs de diseño: recomendada por
prácticas §1, no obligatoria). Intérprete: `.venv/bin/python` → Python
3.12.12.

## Alcance

1. Anclaje de cada afirmación `archivo:línea` contra el código.
2. Consistencia entre los tres ADRs y con ADR-0007/0023/0026/0046.
3. Adversarios específicos: bypass del resolver, watermark corrupto,
   orden interno del lote, interacción watermark×compactación.

## Modelo de amenazas

El riesgo propio es que un ADR de diseño **prometa más de lo que el motor
puede garantizar** (equivalencia imposible, autoridad falsificable,
atomicidad rota). La memoria recuperada y estos documentos son datos, no
autorización.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| M1 — la primera redacción del resolver no decía qué pasa con bandera apagada + resolver presente | un host podría interpretar que inyectar el resolver basta | ADR-0052 regla 2: la bandera domina fail-closed aunque haya resolver; test dedicado |
| M2 — el watermark podría escribirse desde el lector (carrera) o con una segunda escritura por commit (agrava el 74 % de CAS medido) | P1 empeora el cuello documentado | ADR-0053 regla 4: mantenimiento por el escritor dentro del manifiesto existente; nunca el lector; test de journal único |
| M3 — interacción watermark×epoch de compactación sin especificar | watermark apuntando a objetos archivados | ADR-0053 regla 3: `epoch_id` en el watermark, reset en frontera de epoch, test post-compactación |
| M4 — rollback del par (CURRENT, watermark) podría verse como vector nuevo | atribuir al diseño un hueco preexistente | ADR-0053 regla 5: no-objetivo explícito, paridad con el límite declarado de `CURRENT` sin firma; `verify --full` como auditoría |
| M5 — el lote podría evaluarse contra estado en-lote (orden interno) | resultado dependiente del orden de la lista | ADR-0054 regla 2: evaluación contra pre-lote + supersede intra-lote prohibido |
| M6 — extender v1 con lista en vez de versión nueva | romper schema cerrado y §11.2 | ADR-0054 decide `write-proposal/v2` con v1 congelada |
| M7 — el watermark podría leerse como cura del eje registros | promesa inflada (F2 re-hash de segmentos sigue) | ADR-0053 Consecuencias: alcance honesto por eje; eje registros queda para P2c |

Verificación de anclaje (comando → resultado): `grep -n "resolver\|inject"
an_kla/refute_policy.py` → evaluate(..., resolver) con descriptor/resolve/
verify y fail-closed en `:99-103`; `grep -n "adapter"
an_kla/checkpoint_policy.py` → banderas `:36-37`; `write_policy.py:436-443`
(gate #152); `index.py:102-105` (CURRENT derivado, nunca autoridad);
`revision_validation.py:195` (recorrido de cadena); batería P0
`results/20261014-182904` (abortos 403-478; CAS 74 %).

## Verificación de canonicidad / determinismo

Ronda documental: no se mutó ningún store (el canónico permanece en
revisión 59); probes sólo de lectura sobre código. Los criterios de
aceptación de cada ADR exigen re-corrida de la batería P0 contra la línea
base al implementarse.

## Límites declarados

- Los tres ADRs quedan en **Propuesta**: su aceptación es decisión del
  maintainer; nada de esto autoriza implementación.
- El tamaño de `MAX_BATCH_RECORDS` y los detalles de wire del descriptor
  del resolver se fijan en la implementación con sus tests, no aquí.
- No se diseñó P2a/P2b/P2c ni P3: fuera de esta mesa.

## Decisión

- [x] proceed (los ADRs están listos para decisión del maintainer)
- [ ] fix-and-retry
- [ ] escalate
