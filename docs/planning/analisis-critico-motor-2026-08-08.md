# Análisis crítico del motor y consenso dialéctico — 2026-08-08

Documento de continuidad. Recoge verbatim el análisis crítico externo sobre
AN-KLA Memory (sesión del lado consumidor/Kairos), la contra-respuesta del lado
motor y la convergencia final, más el roadmap fijado. Limpieza editorial: se
retiraron dos artefactos de terminal (`[118;1:3u`) de los textos pegados; el
contenido no se alteró.

Relacionado: `docs/architecture/0021-verified-at-freshness-v1.md` (ADR v3
enmendada, aceptada tras retry `proceed`), facts de memoria
`f-adr-0021-verified-at-freshness-2026-08-08` y
`f-roadmap-consenso-2026-08-08-post-adr0021`.

---

## 1. Análisis crítico externo (verbatim, lado consumidor)

Tres frentes verificados: código (222 tests en verde, 3.78s),
gobernanza/proceso, y estado del producto en GitHub. Contexto que cambia la
lectura de todo: el repo tiene 8 días de vida (creado 2026-07-31, 94
commits, 7 releases en 5 días, 1 solo contribuidor, 0 stars/forks externos).
Lo juzga como lo que es: una beta unipersonal muy joven — no como un
proyecto establecido.

### Lo genuinamente sólido (sin repetir lo obvio)

- Núcleo de almacenamiento serio: CAS en dos fases con revalidación dentro
  del lock, O_EXCL + fsync de archivo y directorio, re-hash en cada lectura,
  deepcopy defensivo anti-TOCTOU, cuarentena acotada. Tests de concurrencia
  con 20 procesos reales (test_store.py:361). Cero dependencias runtime.
- La pureza no es declaración, es test: evaluate_write está blindada por un
  test que prohíbe imports de I/O (test_write_policy.py:382).
- Proceso con evidencia real: rondas adversariales con hallazgos materiales
  absorbidos (19 en beta.1, 11 en beta.8, incluyendo el BLOCKER de pureza y
  la regresión del FTS que indexaba targets sustituidos), spike pre-code que
  previno 2 HIGH, ADR-antes-que-código verificable en git log.

### Hallazgos críticos (por severidad)

1. **La revisión "independiente" no es independiente.** Todas las rondas
   adversariales, la validación externa de argos-epistemic (#10) y el 100% de
   los commits son la misma persona. El proceso adversarial es real y atrapa
   bugs — pero contra sesgos de diseño no protege, porque revisor y autor
   comparten los mismos supuestos. Dato honesto: lo más cercano a revisión
   externa que ha tenido el proyecto son los tres insumos del issue #41 — y
   funcionaron (ADR-0021 absorbió 1 HIGH + 4 MEDIUM de ellos). Propuesta:
   institucionalizar revisión cruzada: un agente/persona distinta del autor
   como revisor adversarial por defecto (ya demostrado que aporta), y registrar
   en cada ronda la identidad del revisor.
2. **Sin GC, supersede crea un sumidero inmutable — y el consumidor principal
   va a superseder mucho.** supersede solo superpone status vía supersedes_map;
   los segmentos jamás se podan (store.py:418-443, garbage_collection: false).
   El patrón oficial de refresco de frescura (ADR-0021) es supersede con nuevo
   verified_at → Kairos reconfirmará facts periódicamente, y cada
   reconfirmación deja un objeto inmutable eterno. En 1 año de ritual semanal,
   Kairos acumulará ~52 objetos muertos por fact vivo. Es el riesgo operacional
   #1 del motor, y ADR-0021 lo acelera. Propuesta: ADR de compactación
   gobernada (poda de cadenas completamente sustituidas, con journal y
   verificación) como candidato fuerte a beta.10 — antes de que el problema sea
   grande.
3. **El CLI expone write legado que bypassea toda la política.**
   __main__.py:261-271 permite escribir sin autoridad ni evento de decisión. La
   historia de gobernanza del motor ("toda escritura es gobernada") tiene una
   puerta trasera pública, y los consumidores deben defenderse por convención
   ("nunca uses write" dice Kairos) en vez de por construcción. Propuesta:
   mover write detrás de un flag explícito (--i-know-this-bypasses-governance)
   o eliminarlo en beta.9/10 — el coste es mínimo y cierra la contradicción
   central.
4. **refute/eliminada declarados pero inexistentes.** Hoy un hecho falso no
   puede marcarse como falso: solo puede "sustituirse" (que implica sucesor).
   Corregir "Manuel vive en Bristol" cuando nunca fue cierto requiere fingir un
   reemplazo. Es el siguiente gap semántico después de frescura. Propuesta: ADR
   de refute gobernado (mismo flujo, sin sucesor, visible en retrieval como
   refutada con evidencia).
5. **Deriva documental — otra vez la enfermedad de la frescura, en el repo que
   la combate.** SECURITY.md soporta "beta.4" (4 releases atrás), CITATION.cff
   en beta.5, índice de ADRs termina en 0020 (0021 existe), y los ADR-0019/0020
   implementados y publicados siguen en estado "Propuesta" — el ciclo
   Propuesta→Aceptado nunca se cierra. La práctica §9 lo exigía en el checklist
   de release y no se ejecutó. Propuesta barata: checklist ejecutable (script
   check_docs_freshness.py que falle si SECURITY/CITATION/índice/estados
   difieren de la versión) — mismo remedio que para Kairos: no mantener a mano
   lo que un gate puede verificar.
6. **Cobertura adversarial 3/9 betas, presentada como siempre-vigente.**
   beta.4/beta.5 tocaron index.py (superficie declarada obligatoria) sin ronda.
   La práctica nació en beta.7 — está bien que nazca tarde, mal que se narre
   como retroactiva. Propuesta: una línea honesta en practicas-ingenieria.md
   ("institucionalizada en beta.7") resuelve la disonancia.
7. **Menores pero reales:** ventana lost-update multi-máquina declarada (flock
   advisory; relevante si se sincronizan memorias entre dos Macs algún día);
   sin [project.scripts] (el CLI no instala comando an-kla — fricción de
   adopción absurda de barata de arreglar); versión duplicada a mano en
   pyproject.toml y version.py; MCP lee stdin sin límite de línea (aceptable en
   stdio local, documentar si algún día se expone a red); sin política de
   compatibilidad entre betas pese a 7 releases en 5 días (Kairos se protege
   pineando tags exactos — bien — pero conviene una sección "compatibilidad
   entre betas" en el README).

### Roadmap histórico propuesto por el análisis (reemplazado por §4)

1. beta.9 = ADR-0021 (verified_at, PR-A/B/C) — desbloquea al único consumidor
   real.
2. Compactación gobernada (GC) — el refresco por supersede la convierte en
   urgente (hallazgo #2).
3. refute gobernado — cierra la semántica de corrección sin sucesor.
4. Cerrar puerta trasera write + entry point an-kla + single-source version —
   barato, coherencia y adopción.
5. Gate de frescura documental + transición de estados ADR + honestidad de
   cobertura adversarial — ejecutar lo ya declarado.
6. Revisor adversarial externo institucionalizado — el único fix contra el bus
   factor intelectual.

### Veredicto del análisis

Calidad de código y de proceso muy por encima de lo esperable en una beta
unipersonal de 8 días: núcleo honesto (los límites están declarados en
capabilities(), no escondidos), tests serios, diseño adversarial con
hallazgos reales. Los riesgos no están en el código sino en tres ejes:
organizacional (bus factor 1, revisión autorreferencial), operacional
(crecimiento inmutable sin GC, amplificado por el propio remedio de
frescura), y de ejecución de proceso (prácticas declaradas que no siempre se
ejecutan: docs desfasadas, ADRs sin transicionar, cobertura adversarial
parcial). Ninguno requiere arquitectura nueva — requieren compactación, un
gate de frescura documental y un revisor que no sea el autor.

---

## 2. Contra-respuesta del lado motor (resumen de la verificación)

Se verificaron las afirmaciones contra el repo antes de juzgarlas. Resultado:
casi todo correcto; matices y puntos ciegos:

- **Empeora el hallazgo #5**: ADR-0012 (implementado en beta.4) también sigue
  en "Propuesta" — la deriva del ciclo de estados es peor de lo reportado.
- **#3 matizado**: `write` legado no es puerta trasera oculta — devuelve
  `"deprecation": "legacy_write_bypasses_write_policy"` en su resultado y está
  documentado en README y contrato. Es superficie legada declarada; la acción
  propuesta (flag/eliminación) sigue siendo correcta, y el flag ya emitido es
  la mitad del trabajo.
- **#1 matizado**: la ronda de ADR-0021 corrió en un subagente con modelo
  distinto (glm-5.2 vs kimi) — decorrelación parcial ya practicada
  (`practicas-ingenieria.md §1` pide "idealmente otro proveedor/modelo").
  Institucionalizar = registrar identidad del revisor por ronda.
- **Atribución corregida**: el 1 HIGH + 4 MEDIUM de ADR-0021 salieron de la
  ronda adversarial sobre el ADR (premisas falsas verificadas contra código),
  no directamente de los insumos #41; los insumos moldearon el diseño.
- **Punto ciego 1 — checkpoint desfasado**: el working_state vigente apunta a
  "iniciar F3 desde main 47c9c6f" con plan del repo antiguo; no existe interfaz
  gobernada para actualizarlo (`commit-write-plan` no parchea checkpoints) →
  `governed_checkpoint_update_unavailable`. La enfermedad de frescura dentro de
  la propia memoria del proyecto.
- **Punto ciego 2 — recall BM25 (#10-a)**: omitido del roadmap externo; es el
  dolor de consumidor más agudo (registros nuevos irrecuperables tras
  rebuild-index). Spike adversarial antes que refute.
- **GC más ancho y más peligroso**: el sumidero incluye events
  `write_policy_decision` y journal, no solo supersede; y podar objetos rompe
  manifests hash-referenciados de revisiones históricas → la compactación
  necesita semántica de época/tombstone para que `verify` de revisiones viejas
  degrade explícito en vez de fallar. ADR + spike, no PR rápido.

Roadmap corregido propuesto desde el motor: (1) beta.9 ADR-0021; (2) gate de
frescura documental + estados ADR + línea honesta (una tarde, ejercita el
músculo "ejecutar lo declarado"); (3) cerrar write legado + entry point +
single-source version; (4) ADR de compactación (diseño ya, código despacio);
(5) spike recall BM25; (6) refute + gobernanza del checkpoint; (7) revisor
externo institucionalizado (transversal).

---

## 3. Convergencia (verbatim, lado consumidor)

La respuesta es mejor que el análisis original en tres puntos, correcta en
todas sus correcciones verificables, y su roadmap corregido es superior.
Detalle verificado de primera mano: ADR-0012 también sigue en "Propuesta";
practicas-ingenieria.md:30-31 sí dice "idealmente otro proveedor/modelo".
Los tres matices aceptados (write legado, revisión autorreferencial,
atribución). Puntos ciegos verificados:

- **Checkpoint desfasado: CONFIRMADO, con agravante nuevo** — el checkpoint ni
  siquiera es legible por CLI: `get-checkpoint` existe solo como tool MCP (el
  CLI lista 18 subcomandos y lo rechaza). No actualizable por flujo gobernado
  y apenas inspeccionable. Conexión causal: AN-KLA.md instruye "conserva el
  estado real en Git hasta disponer de interfaz gobernada de checkpoint" — y
  ese estado-en-Git fue lo que se pudrió en AGENTS.md/PLAN.md de Kairos. La
  gobernanza del checkpoint cierra la historia de frescura de punta a punta:
  **abrir issue ya**, diseño en la misma capa que refute.
- Recall BM25: aceptado, antes que refute.
- Sumidero más ancho + prudencia en GC: aceptados; la compactación necesita
  semántica de época/tombstone para que verify degrade explícito. Diseño ya,
  código despacio.
- Roadmap corregido del motor: **gana** — prioriza por riesgo técnico y
  reparación del hábito organizacional, no solo por riesgo abstracto.

Meta-lección: el intercambio es la revisión externa institucionalizada
funcionando antes de institucionalizarse: análisis desde el consumidor →
respuesta desde el motor con verificación propia → convergencia mejor que
ambas posiciones. Ninguna sesión tenía sola el panorama completo. El consenso
dialéctico no fue cortesía — fue corrección de errores en ambas direcciones
con evidencia.

---

## 4. Camino ejecutable autorizado por el maintainer (2026-08-08)

El maintainer autorizó documentar e iniciar este camino localmente hasta
completarlo. La autorización inicial no incluía operaciones GitHub; el
2026-08-08 habilitó commit, push, PR y merge mediante acceso administrativo.
Publicar, crear tags, integrar proveedores o elegir licencia siguen fuera de
alcance. Cada cambio material conserva ADR o spike previo, CI local y ronda
adversarial propia.

### Fase 0 — decisión durable

- Enmendar ADR-0021 sin código: `verified_at` sigue siendo timestamp
  autodeclarado, nunca autoridad; `semantics=self_asserted_timestamp` y
  `source_field=record.verified_at` viven una vez en el bloque raíz de frescura.
- Dividir beta.9 en A/B1/B2/C, sacar #32 a un PR independiente y actualizar el
  índice de ADRs, esta bitácora y la ronda adversarial.
- Mantener ADR-0021 en `Propuesta` hasta decisión explícita del maintainer y
  obtener `proceed` fresco para la enmienda antes de PR-A.

### Fase 1 — beta.9 temporal

1. **PR-A, core temporal puro:** `an_kla/temporal.py`, validación de
   `write_policy.py`, schema write-proposal, fingerprint y replay. El parser
   devuelve `datetime` aware UTC; el formateador produce UTC canónico. El core
   no lee reloj, el dato no eleva autoridad y ningún error crea objetos.
2. **PR-B1, retrieval v2:** proyección posterior al ranking/selección para que
   score, orden, ids y `used_bytes` de retrieve permanezcan iguales a v1 bajo
   los mismos inputs y presupuesto de render.
3. **PR-B2, wrappers v2:** assembly, MCP, CLI y capabilities; una captura de
   `now`, allowlists exactas y presupuesto del payload completo. Los wrappers
   copian la proyección de retrieval y conservan `untrusted_memory_data`.
4. **PR-C, cierre local:** versión, notas, wheel limpio y auditoría. `main` no
   es etiquetable hasta C; no crear tag ni publicar sin otra autorización.

#32 se implementa en cambio aislado sobre `store.py`, serializado respecto de
PR-A; no se mezclan modificaciones simultáneas de store y write-policy.

### Fase 2 — incoherencias de adopción

- Añadir `[project.scripts]` y una sola fuente de versión en un cambio pequeño.
- Después exigir `--allow-legacy-unguarded-write`, emitir warning estable y
  declarar la retirada de `write` para beta.10 tras buscar consumidores. La API
  `MemoryStore.commit()` queda interna para mantenimiento y tests.

### Fase 3 — identidad de proyecto y store

- ADR de identidad con ancla de proyecto separada de identidad de store,
  revalidación bajo lock y rutas absolutas sólo diagnósticas, fuera de la cadena
  CAS. Cubrir clones, worktrees, relocación, backup y adopción legacy.

### Fase 4 — checkpoint/handoff gobernado

Evolucionar el checkpoint exacto ligado a revisión a `checkpoint-v2` con un
`working_state-v2` anidado, no un cuarto stream ni un fact lexical. Añadir
show/plan/commit/resume; procedencia por campo (`tool_observed`,
`caller_asserted`, `unavailable`), reloj explícito, digest Git canónico y
saneado, enlace exacto al checkpoint padre y `live_delta` read-only
presupuestado. Un JSON del caller nunca se eleva a `tool_observed`.

### Fase 5 — resultado de commit y durabilidad

Separar `authority_state`, `audit_state` y `durability_state`; exponer txid
antes de una falla ambigua, inspeccionar/reparar outcomes y hacer fault
injection de fallos post-CURRENT/fsync. Un error operativo no puede ocultar si
CURRENT ya avanzó ni degradar silenciosamente `posix-fsync-dir/v1`.

### Fase 6 — benchmark de recuperación v2

Contrato fijado en ADR-0025.

Preservar el orden de `selected`; separar métricas de ranking (`Precision@k`,
`Recall@k`, MRR, primer relevante) de métricas bajo presupuesto
(`precision_at_budget`, `budget_recall`, relevantes excluidos). Registrar perfil
pedido/real y degradación. Corpus: largos/cortos, distractores, cadenas
supersede, budgets 256/512/1024/4096, índice ausente/fresco/corrupto/stale y
consultas saneadas de Kairos/handoff. Medir antes de decidir BM25.

### Fase 7 — corrección y retención

Implementar `refute` gobernado sin sucesor y conservar evidencia. Después:
export/import verificable, backup/restore probado, ADR de compactación y por
último código de compactación. Separar vigencia epistémica
(`active/superseded/refuted`), integridad física (`present/quarantined`) y
disponibilidad histórica (`present/archived_by_compaction`). Ningún borrado
físico precede manifest de export, restore validado, tombstones, época y
respuesta explícita `archived` al verificar revisiones antiguas.

### Fase 8 — recuperación semántica derivada

Formalizada el 2026-08-09 en ADR-0029 y
`docs/planning/fase-8-recuperacion-semantica-2026-08-09.md`. Separa dos tracks:
recuperar registros existentes por significado y generar propuestas semánticas
desde evidencia. El segundo no comienza ni integra proveedor por efecto de esta
fase.

Secuencia: cerrar validación externa #10; ejecutar spike read-only de
portabilidad/privacidad; ampliar benchmark con paráfrasis, sinónimos, negaciones
y model drift; decidir ADR-0029; sólo entonces implementar índice derivado,
perfil vectorial opt-in y fusión híbrida experimental. CAS sigue siendo la
única autoridad, el índice es descartable, los filtros epistémicos se aplican
uniformemente y el ranking/default productivo no cambia sin otro gate.

La preferencia histórica por `sqlite-vec` frente a un segundo store ChromaDB es
una hipótesis del spike, no una selección. Memoria L0→L3/persona requiere ADR y
autorización separadas; toda salida de modelo sería propuesta no confiable y
pasaría por la escritura gobernada.

Escrubery queda formalizado como subtrack **F8-E** de atestación opcional, no
como motor vectorial. Su contrato candidato permite observar modelo, artefacto,
dimensión, normalización y política de datos en un snapshot firmado cuyo digest
AN-KLA puede ligar al manifest. No habrá consulta viva al catálogo en retrieval
ni selección de perfil desde memoria recuperada.

La revisión externa dejó `FIX-AND-RETRY` antes de runtime: el remoto debe
reconstruir el sistema, Evidentia necesita append inmutable/serializado y
checkpoint real, y F3 requiere sandbox/artefactos endurecidos. Secuencia
F8-E0..E5: fuente reproducible; Evidentia; F3; schema de atestación; snapshot
offline; spike de adapter. El detalle durable está en
`docs/planning/fase-8-escrubery-attestation-2026-08-09.md` y en
`https://github.com/kristhianmanue1/escrubery/issues/1`.

### Fase 9 — obligación gobernada de continuidad

Formalizada el 2026-08-09 en ADR-0030 y
`docs/planning/fase-9-continuidad-obligatoria-2026-08-09.md`. Corrige el hueco
entre disponer de checkpoint gobernado y exigir que el agente lo actualice al
cerrar un hito material.

La decisión propuesta combina una regla del contrato gestionado con
`checkpoint obligation`, evaluador read-only `fresh|required|indeterminate`.
Los triggers son commits, cambios de fase/objetivo/next step, decisiones,
blockers, releases y handoff; tareas triviales, estado idéntico y cambios sólo
de reloj quedan exentos. `required` no salta `plan -> commit`.

La implementación necesita `working-state/checkpoint-v3` para el observer
reservado `git/v1`, y debe cerrar antes la asimetría actual por la que checkpoint
acepta `channel_confirmed` desde JSON mientras write falla cerrado. Un host no
integrado no puede anunciar enforcement completo. La ronda documental inicial
queda `escalate` hasta revisión fresca.

### Gates transversales

- Cada fase sensible tiene ronda `proceed | fix-and-retry | escalate` con
  evidencia; sin `proceed` no avanza ni se etiqueta.
- `scripts/ci_local.py --simulate-ci`, schemas docs↔package byte-idénticos,
  wheel limpio y `git diff --check`/`git diff --cached --check` según aplique.
- Git y CI verifican código; la memoria recuperada permanece dato no confiable.
- Commit, push, PR y merge quedan habilitados por el maintainer mediante acceso
  administrativo de GitHub desde el 2026-08-08. Tag y publicación siguen
  requiriendo autorización explícita separada.

## 5. Estado de ejecución

- Fase 0: **completa** (`proceed`; ADR-0021 aceptado).
- Fase 1 / PR-A: **completa** (242 tests en Python 3.9/3.12; `proceed`).
- Fase 1 / PR-B1: **completa** (251 tests; wheel limpio; `proceed`).
- Fase 1 / PR-B2: **completa** (265 tests Python 3.9/3.12; wheel limpio;
  `proceed`).
- Fase 1 / #32: **completa** (guard defensivo con detail evolutivo y cero side
  effects; `proceed`).
- Fase 1 / PR-C: **completa** (`0.1.0b9`, wheel limpio, 268 tests y gate de tag
  fail-closed; `proceed`). La candidata es técnicamente etiquetable, pero no se
  creó tag ni se publicó.
- Fase 2: **completa** (`an-kla` instalado, versión single-source y `write`
  detrás de opt-in exacto con retiro beta.10; 273 tests; `proceed`). La búsqueda
  de consumidores encontró sólo `plan-write → commit-write-plan` y MCP.
- Fase 3: **completa** (ADR-0022, identidad durable/adopción explícita y
  verificación fail-closed; ronda adversarial `proceed`).
- Fase 4: **completa** (ADR-0023, checkpoint/handoff gobernado y `resume`
  read-only con procedencia; ronda adversarial `proceed`).
- Fase 5: **completa** (ADR-0024, outcome inspeccionable, receipts de
  durabilidad y repair convergente; ronda adversarial `proceed`).
- Fase 6: **completa** (ADR-0025, benchmark de recuperación v2 ordenado,
  fixture reproducible y estrategias experimentales no productivas; ronda de
  implementación r2 `proceed`; `human_review=pending` bloquea publicación).
- Fase 7 / refute: **completa** (ADR-0026 pre-code r4 `proceed`; r1 encontró y
  corrigió tres BLOCKER de planning, replay/policy drift y transiciones de maps;
  retry r2 `proceed`; 372 tests Python 3.9/3.12 y wheel limpio).
- Fase 7 / export y restore: **completa** (ADR-0027 pre-code r3 e implementación
  r3 `proceed`; 379 tests Python 3.9/3.12, wheel limpio y 49 schemas
  byte-idénticos). Bundle y restore cubren identidad, CAS, auditoría,
  filesystem hostil, publicación create-only y outcomes degradados.
- Fase 7 / compactación: **completa** (ADR-0028 y contrato cerrado pasaron
  pre-code r4 e implementación final `proceed`; `revision-v3`, reader gate,
  restore proof, epochs/catálogos acumulativos, cleanup exacto fail-closed,
  replay, CLI y disponibilidad histórica están implementados localmente).
  Suite final: 393 tests en Python 3.9 y 3.12 (un skip esperado en 3.12), wheel
  limpio y 61 schemas docs/package byte-idénticos. El retry final reprodujo
  cero borrados sin recibo durable y lectura histórica bajo deriva de política.
- Fase 8: **formalizada, no iniciada** (ADR-0029 en `Propuesta`; F8.0 depende de
  la validación externa #10 y F8.1 es un spike read-only). No hay backend,
  modelo, proveedor, profile ni cambio de ranking autorizados. La ronda
  documental preliminar terminó `escalate` hasta evidencia y revisión fresca.
- Fase 9: **formalizada, no iniciada** (ADR-0030 en `Propuesta`). El checkpoint
  de Fase 8 fue actualizado manualmente a revisión AN-KLA 20, demostrando el
  hueco de obligación. No hay template vNext, observer Git, hook o enforcement
  implementados. La ronda fresca r2 sobre `277dea5` terminó `ESCALATE`: exige
  consentimiento local explícito, semántica de frescura basada en cobertura,
  hotfix del spoof de canal, boundary real del observer, readers-first para v3
  y sanitización ejecutable. El caso especial posterior a la ronda ya fue
  incorporado como insumo, no como decisión: separa continuidad
  `manual|milestone|continuous` de assurance `standard|high|regulated`, con
  aplicación por operación/stream y aceptación graduada. Antes de implementar
  se decidirá `integrar ahora | experimento opt-in | diferir`; detalle en
  `docs/planning/fase-9-frontera-continuidad-assurance-2026-08-09.md`.
- Decisión vigente del maintainer: continuar localmente hasta completar el
  camino y permitir su integración administrativa en GitHub; tag y publicación
  permanecen excluidos.

## 6. Auditoría de cierre local

La suite completa no sustituye la cobertura por requisito. El cierre se volvió
a ejecutar por fase sobre las superficies normativas:

| Alcance | Evidencia ejecutada | Resultado |
|---|---|---|
| Fase 1, temporal/retrieval/wrappers/write | módulos temporal, retrieval freshness, context, MCP y write policy/commit | 124 tests, `OK` |
| Fase 2, entrypoint/version/write legacy | legacy CLI, metadata y gate de tag | 15 tests, `OK` |
| Fase 3, identidad | `tests.test_identity` | 20 tests, `OK` |
| Fase 4, checkpoint/handoff | `tests.test_checkpoints` | 14 tests, `OK` |
| Fase 5, outcome/durabilidad | transactions, fault matrix y primitives | 29 tests, `OK` |
| Fase 6, benchmark | `tests.test_evaluation_v2` + scanner del corpus | 12 tests, `OK`; corpus ligado, `human_review=pending` |
| Fase 7, refute/export/restore/compact | refute, export/restore, reader gate y compactación | 41 tests, `OK`; adversarial final `PROCEED` |

Gates transversales finales: suite completa 393/393 en Python 3.9 y 3.12
(un skip de plataforma esperado en 3.12), `ci_local --simulate-ci` OK, wheel
aislado `0.1.0b9` OK, 61 schemas por árbol con nombres y bytes idénticos,
size gate OK y `git diff --check` limpio. `human_review=pending` bloquea una
publicación del benchmark, no la implementación local ni el cierre técnico del
roadmap. No se creó tag ni se publicó artefacto.
