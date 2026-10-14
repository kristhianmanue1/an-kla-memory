# ADR-0048: almacenamiento externo — `store_root` separado de `project_root`

- **Estado:** Aceptada (2026-09-05, orden explícita del maintainer en
  sesión: "adelante con paso 1 y 3" — aceptar tal cual, con la
  re-verificación H1–H4 ya ejecutada como condición cumplida de F1)
- **Implementación:** En curso — R0 reconciliado (Enmienda 1, 2026-10-13); R2a (Enmienda 2); R2b (Enmienda 3); R3 (Enmienda 4); attach (Enmienda 5); residuales m1/m4 (Enmienda 6); ronda de release beta.30 (Enmiendas 7 a 13; `relocate attach` fuera de la CLI, rediseño en ADR-0051);
  R1a en adelante según `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md`
- **Fecha:** 2026-09-05
- **Decide sobre:** G3 de ADR-0031 — cómo separa AN-KLA la custodia física
  de la memoria (store_root) del proyecto observado (project_root), con
  migración reversible gobernada. No decide identidad de agente ni
  sharing (G4), ni proveedores externos, ni soporte Windows.

## Contexto

La memoria vive acoplada al proyecto: `self.root = self.project_root /
".an-kla" / "memory"` (`an_kla/store.py:100`). El acoplamiento tiene tres
costes declarados: borrar el checkout borra la memoria (ADR-0031
§Consecuencias negativas), los worktrees no pueden tener memoria sin
duplicarla (regla operativa de `AGENTS.md`, sin enforcement en código) y
la ruta del proyecto queda semicargada de significado. G1 (#55) y G2
(#56) están servidas; el triaje de #57 exigía no mezclar G3 con ellas.

F0 firmada por el maintainer (2026-09-05, sesión): **(1) Windows queda
diferido** — G3 v1 declara macOS/Linux y el criterio de aceptación de #57
se enmienda en ese sentido; **(2) los comprobantes viajan con la bóveda**
— `attest.key/whitelist/receipts/nonces` y `hook-runs/` son custodia del
store, no del proyecto; **(3) un proyecto, una bóveda** — todos los
worktrees de un mismo proyecto resuelven al mismo store_root, sin
multiplicación de memorias.

El spike read-only
(`docs/planning/g3-spike-store-root-2026-09-05.md`; S1 refine, S2
proceed, S3 proceed, S4 refine) verificó con experimento que el binding
de identidad liga **bytes, no rutas** — un store movido de ruta padre y
nombre verifica, lee y escribe con `root_relocated: true` como única
huella —, que el acoplamiento pivota sobre una sola línea con ~10 sitios
de cambio real y 5 carve-outs, y que la migración puede componerse con
maquinaria probada: staging+`rename_noreplace` de restore
(`export_restore.py:249-309`, `export_io.py:124-140`) y journal por
etapas con receipts de compaction (`compaction.py:509-675`,
`transactions.py:42-118`).

Restricciones vigentes: el formato físico de revisión (ADR-0001) no
cambia; los schemas congelados exigen versiones nuevas para expresar
memoria externa (`startup-diagnostic-v1.schema.json:26` e
`integration-status-v1/v2` congelan `external_memory_evaluated: const
false`); el contexto gestionado (`AGENTS.md` managed block) es del
proyecto, no de la bóveda.

Esta Propuesta absorbió una ronda adversarial pre-code de contexto
fresco (2026-09-05, veredicto `fix-and-retry`: 1 BLOCKER, 3 HIGH,
5 MEDIUM, 3 LOW; registro y absorción en
`docs/planning/g3-adr0048-adversarial-2026-09-05.md`). H1 (puntero de
custodia), H2 (staging hermano + relocate-back por subárbol), H3
(decisión de export con artefactos G2) y H4 (regla general de
re-anclaje) quedan incorporados en §1–§3; la re-verificación puntual
H1–H4 sobre el texto enmendado es condición para abrir F1.

## Decisión

Introducir `store_root` como raíz de custodia parametrizable y reversible,
con migración gobernada `relocate` (plan→commit), identidad re-anclada a
bytes, y observabilidad versionada. Carve-out explícito: el contexto
gestionado y la declaración de hooks permanecen project-local. Fases F1–F7
según el spike; ADR antes de una línea de código de migración.

### 1. Resolución de raíces (F0-B) y puntero de custodia

- `MemoryStore(project_root, *, store_root=None)`: por defecto,
  `store_root = project_root/.an-kla` (compatibilidad byte-idéntica con
  todo lo existente). `store.root` (la bóveda) =
  `store_root/"memory"`; el anchor de identidad (`project-identity.json`,
  `identity-intent.json`, `identity-intents/`, `identity-receipts/`),
  `attest.*` y `hook-runs/` viven bajo `store_root` (F0-B), fuera de
  `memory/` como hoy.
- **Puntero de custodia** (ronda pre-code H1, BLOCKER): `relocate commit`
  deja en el proyecto un marcador project-local
  (`.an-kla/store-root.txt`) con el fingerprint del binding de custodia
  — un digest, nunca la ruta como autoridad. Sin él, una invocación
  posterior sin flag/env resolvería project-local y un `init` fabricaría
  una bóveda gemela **en silencio** — exactamente lo que #57 prohíbe
  ("no reasigna silenciosamente").
- **Precedencia de resolución** (H11), enunciada: flag `--store-root` >
  env `AN_KLA_STORE_ROOT` > puntero > project-local. Flag y env
  divergentes: el flag gana y la divergencia se diagnostica en stderr.
  Puntero presente y custodia resuelta distinta del fingerprint del
  puntero → error estable **`store_root_divergence`** en toda operación
  mutativa y en `init`/`adopt` — jamás inicialización silenciosa de una
  bóveda gemela.
- Fail-closed de custodia: `attest`/`hook_runs`/`identity_evidence`
  toman el **store** (no rutas sueltas) y verifican que project_root y
  store_root resueltos corresponden al mismo binding antes de acuñar —
  raíces divergentes es error estable, nunca escritura silenciosa en el
  lugar equivocado.

### 2. La ruta deja de ser autoridad (spike S2)

- **Relocation receipt**: la igualdad de ruta en `adopt`
  (`identity.py:478-481`, único gate ruta-como-autoridad que queda) se
  sustituye por un receipt encadenado estilo `identity_evidence.py`
  (rutas relativas + fsync + predecessor): reubicar el proyecto es un
  hecho registrado, no un impedimento.
- **Symlink walk re-anclado — regla general** (ronda H4): TODO argumento
  `root` de walk/creación/sync de identidad (`identity.py:311,347-363`,
  `identity_evidence.py:126,173,218-233`) pasa a la raíz de custodia —
  no sólo las raíces de `_reject_symlink_path` citadas por el spike.
  Sin la regla general, un `init --store-root` fresco moriría con
  `store_identity_invalid`. F1 exige test de init fresco con store
  externo.
- **Receipts de identidad bajo dos raíces** (H9): desde G3, las rutas
  relativas de los receipts de identidad se interpretan respecto a la
  **raíz de custodia**; los receipts anteriores a un relocate viajan con
  la bóveda, por lo que sus rutas relativas siguen resolviendo igual.
  `identity-durability-receipt-v1` no cambia de schema (no fija raíz);
  la convención de raíz queda declarada aquí.
- `repo_context` y `root_relocated` permanecen como clasificación
  observacional, jamás condición de acceso.

### 3. Migración gobernada: `relocate` (plan→commit)

Nuevo flujo `store relocate plan / relocate commit` que compone las dos
plantillas probadas. **Set exacto de movimiento** (ronda H5):
`_PATTERNS` ∪ {`attest.key`, `attest-whitelist.json`, `receipts/`,
`nonces/`, `hook-runs/**`} + anchor de identidad. `attest.key` **sí
viaja** (F0-B) aunque `export` lo excluya por diseño ("never exported"):
son operaciones distintas con listas distintas. `export` permanece sin
llave.

1. **Staging hermano del destino** (ronda H2): copiar el set exacto a
   `<padre-de-store_root>/.staging-<txid>/` — hermano, no interior —
   con hash-check por archivo. El layout interno de la bóveda permanece
   disperso (`memory/` + attest + hook-runs + anchor bajo `store_root`).
2. **Verificación**: `MemoryStore(staging).verify()` en verde.
3. **Publicación atómica**: `rename_noreplace(staging → store_root)` —
   destino ausente garantizado por el plan (fail-closed ante ocupado,
   que es el caso A4: bóveda de otro proyecto). Ventana de crash = un
   `rename`.
4. **Cleanup del origen** con delete-set + receipts
   `candidate-data-durable`/`current-durable` y journal por etapas en
   `transactions/`. Ronda H7: el commit corre bajo `write_lock` +
   reader gate; attest/hook-runs acuñan O_EXCL sin store lock, así que
   el cleanup **sólo borra el delete-set del plan** (cerrado); archivos
   nacidos después del plan en el origen quedan y son reportados por
   `doctor` (evidencia huérfana en árbol muerto, jamás perdida en el
   destino). Origen intacto si el crash es pre-publish; post-publish,
   reconciliable por journal.
5. **relocate-back** (externo → project-local): el destino
   `project_root/.an-kla` persiste por los carve-outs, así que no hay
   rename único posible — se declara publicación **por subárbol** bajo
   `write_lock` + journal + reconciliación (sin la promesa de
   ventana-de-un-rename). Mismo flujo, semántica declarada distinta.
6. **Rollback documentado**: el origen no se borra hasta verify en verde
   sobre el destino + receipt de cleanup; el rollback es restaurar el
   delete-set desde el receipt.

Nunca automática, nunca destructiva: exige plan con base_revision,
confirmación exacta y ejecución bajo locks.

**No se mueve** (carve-outs congelados): `indexes/` (derivable; se
reconstruye con `rebuild-index`), `leases/`, `quarantine/`,
`.context/` + bloque gestionado, `host-hooks.json`, locks/gates.

**Decisión de export heredada** (ronda H3, defecto vivo): `hook-runs/**`
**entra** en `_PATTERNS` del export (evidencia de la bóveda, viaja con
ella) y `host-hooks.json` entra en las **exclusiones** (es del
proyecto). Hoy un proyecto con perfil host-managed **no puede exportar**
(`export_unrecognized_durable_path`) — la reparación se prioriza en la
deuda beta.23, antes de F6. *(Histórico: resuelto en beta.23, #119
cerrado el 2026-09-06; ver Enmienda 1.)*

### 4. Observabilidad versionada

- `startup-diagnostic-v2`: `external_memory_evaluated: true` +
  descriptor de custodia — `custody_fingerprint` (digest del binding de
  custodia) y `store_external: true|false`; **nunca la ruta** (ronda
  H6: las superficies observables no filtran rutas, §11.1).
- `integration-status-v3`: bloque `store` con el mismo descriptor +
  distinción explícita de custodias (declaración host-hooks
  project-local vs hook-runs store-externas). `v1`/`v2` quedan
  congelados; `capabilities()` se actualiza coherentemente y con goldens.
- `doctor` gana el eje `custody_divergence` (ronda H12, aterrizado):
  compara puntero local vs custodia resuelta vs
  `canonical_project_root_at_init`, con códigos estables.

### 5. Worktrees: un proyecto, una bóveda (F0-C)

La regla operativa de `AGENTS.md` ("los worktrees apuntan al checkout
canónico") se vuelve estructural: el store es del proyecto, no del
directorio de trabajo. Un worktree con `--store-root` resuelto (env var,
flag o puntero de custodia) opera la misma bóveda; sin resolución, el
comportamiento de hoy (store ausente + `linked_worktree` en el
diagnóstico) permanece. El puntero de custodia (§1) resuelve también el
caso del hook git del propio repo
(`docs/hooks-template/pre-commit:22-41`, ronda H8): el hook resuelve por
puntero sin heredar env del shell. La edición del contrato gestionado
que esto eventualmente requerirá se hará por su propio flujo
versionado, no en esta fase.

### 6. Plataformas

G3 v1 declara **macOS/Linux** (F0: Windows diferido — el criterio de #57
se enmienda en ese sentido). `rename_noreplace` usa `renex_np`/`renameat2`
con fallback documentado; los caminos Windows de locks quedan intactos
pero fuera de la matriz de soporte de G3.

### 7. Threat model (resumen; desarrollo en §Referencias)

- **A1 — migración a medias**: crash entre etapas → journal por etapas +
  receipts + reconciliación (patrón compaction); origen intacto hasta
  publish; publish atómico.
- **A2 — ruta-como-autoridad residual**: eliminada la igualdad de
  `adopt`; symlink walk re-anclado; todo lo demás ya era bytes (S2).
- **A3 — custodia partida**: attest/hook-runs toman store y fail-closed
  ante raíces divergentes; nunca escritura silenciosa en la raíz
  equivocada.
- **A4 — bóveda compartida entre clones**: el binding de identidad
  rechaza dos project identities distintas apuntando a la misma bóveda
  (`store_identity_changed`/`_validate_pair` ya lo hacen fail-closed);
  un clon NO es el proyecto.
- **A5 — dato no confiable en tránsito**: hash-check por archivo en
  staging; quarantine ante colisión (primitivas existentes).
- Frontera intacta: la memoria sigue siendo dato no confiable; store_root
  externo no añade autoridad a nada.

## Por qué no [alternativa]

### Extender `export/restore` para "restaurar en otro sitio"

Restore exige project root sin `.an-kla` y publica project-local
(`export_restore.py:254-256`): reutiliza el movimiento pero no la
semántica de custodia continua (mismo binding, sin duplicar identidad).
Se reutiliza su mecánica dentro de `relocate`, no como sustituto.
Descartada como solución completa.

### Symlink de `.an-kla/memory` a un directorio externo (sin soporte de primera clase)

Resuelve el bytes-no-dentro-de-la-casa con un truco del filesystem:
rompe silenciosamente con `mv`, `rsync --delete`, restauraciones de
backup; el symlink walk de identidad lo rechazaría o pelearía con él; y
nada queda registrado ni reconciliable. Descartada.

### Migración automática al detectar `AN_KLA_STORE_ROOT`

Los criterios de #57 exigen migración planificada y confirmada, nunca
automática: una variable de entorno no puede mover la bóveda de sitio.
El flag resuelve *dónde leer*; `relocate` decide *cuándo mover*.
Descartada.

### Soporte Windows en v1

El protocolo de anclaje y partes de la suite son POSIX (doctrina vigente
desde beta.18); comprometer Windows multiplicaría la matriz de G3 justo
en su fase más delicada. F0: diferido; el criterio de #57 se enmienda.
Descartado para v1.

### Mezclar G3 con identidad de agente (G4)

El binding actual (project_uuid + store_identity) es suficiente para
custodia externa; `agent_id`/multi-scope exigen threat model propio
(contaminación cross-project) y dependen de los aprendizajes de G3.
Descartado; vedado en esta fase.

## Consecuencias

- **Positivas:**
  - Borrar/recrear el checkout ya no destruye la memoria; el ciclo de
    vida queda desacoplado (cierra la negativa declarada en ADR-0031).
  - Los worktrees dejan de ser ciudadanos de segunda clase por
    estructura, no por disciplina.
  - La ruta del proyecto queda reducida a observación (telemetría),
    culminando ADR-0022.
  - Backup de la bóveda = copiar un directorio ajeno al repo.

- **Negativas:**
  - Dos raíces que mantener: el operador asume la custodia externa
    (backup, permisos, espacio) que antes heredaba del ciclo del repo.
  - Dos versiones nuevas de schemas observables (startup-diagnostic-v2,
    integration-status-v3) y su coste de goldens.
  - La resolución por defecto (env var/flag) añade una decisión de
    configuración real donde antes no existía.

- **Neutras:**
  - Compatibilidad total: sin `--store-root` todo funciona como hoy.
  - El formato físico de revisión (ADR-0001) no cambia; la compactación,
    refute, export/restore y outcomes conservan sus contratos.
  - Registro canónico gana la fila 0048 (48 ADRs: 44 aceptadas,
    4 propuestas) con su conteo en `tests/test_adr_registry.py`.

## Test de regresión

- `scripts/check_adr_registry.py` pasa: fila 0048, estado coherente.
- `tests/test_adr_registry.py`: `Propuesta` 3→4, `Aceptada` 44.
- `scripts/check_sizes.py`: este archivo ≤ 400 líneas.
- Suite canónica en verde (ningún cambio de código en esta fase).

Tests funcionales diferidos a F1–F7 (criterios de #57): relocación con
crash inyectado en cada etapa (pre/post publish, pre/post cleanup) con
reconciliación; consumidores legacy project-local intactos; divergencia
de custodia fail-closed; symlink walk re-anclado; relocation receipt
encadenado; roundtrip relocate → relocate-back; export/sealed contra
store externo; baseline completa, concurrencia y ronda adversarial final
obligatoria antes de cerrar #57.

## Referencias

- **Issue #57** (G3) y su triaje (riesgo alto; no mezclar con G2/G4).
- **Spike** (2026-09-05):
  `docs/planning/g3-spike-store-root-2026-09-05.md`.
- **ADR-0031** — mandato G3 y seis ejes; **ADR-0022** — identidad por
  bytes que esta decisión culmina.
- **ADR-0024** — outcomes y reconciliación, plantilla del crash-safety.
- **ADR-0042/0027** — export/sealed, cuyo anclaje de publicación cambia.
- **ADR-0036/0039** — observabilidad congelada que obliga v2/v3.
- F0 firmada por el maintainer el 2026-09-05 (sesión): Windows diferido;
  comprobantes viajan con la bóveda; un proyecto, una bóveda.

## Enmienda 1 (2026-10-13) — reconciliación R0 de G3

Registro completo: `docs/planning/g3-r0-contrato-baseline-2026-10-13.md`.

1. **Nombre del diagnóstico de custodia.** `startup-diagnostic-v2` quedó
   publicado en beta.28 con el bloque `vocabulary` (ADR-0049). El
   descriptor de custodia de §4 se publica como **`startup-diagnostic-v3`**,
   superconjunto que conserva `vocabulary`; v1 y v2 quedan congelados.
   `integration-status-v3` no cambia. Toda mención de
   `startup-diagnostic-v2` en §4 y §Consecuencias referida a custodia se lee
   como v3. *Decisión normativa: adoptada el 2026-10-13 por el agente
   ejecutor bajo delegación explícita del maintainer («si hay decisiones
   analiza de forma crítica… y toma la mejor»). Alternativas descartadas:
   reabrir ADR-0048 (frena G3 sin beneficio contractual) y extender v2
   (rompe la regla de schemas congelados y a lectores de beta.28).*
2. **#119.** La frase de §3 sobre export host-managed es histórica: el fix
   está en `export_restore.py:43,67` con regresión en
   `tests/test_export_restore.py:44`.
3. **`restore`.** Sigue publicando sólo project-local; un destino de restore
   externo es una decisión separada, fuera de G3.
4. **Convenciones de mecanismo** (no cambian la decisión): walk de symlinks
   anclado en `store_root.parent`; el prefijo `.an-kla/` de las rutas de
   receipts denota la raíz de custodia (H9); `custody_fingerprint` sin
   rutas; formato del puntero; `init` con store externo también deja el
   puntero (cierra H1 para bóvedas frescas); relocation receipts bajo
   `store_root/relocation-receipts/`. Detalle en el registro R0 §5.

## Enmienda 2 (2026-10-13) — mecanismo de `relocate` (R2a)

Registro completo: `docs/planning/g3-r2a-relocate-2026-10-13.md`. Decisiones
de mecanismo tomadas por el agente ejecutor bajo la delegación explícita del
maintainer; no cambian §3, la concretan:

1. **CLI.** `relocate plan|commit|inspect|reconcile` como grupo de primer
   nivel (no existe un grupo `store`); `commit` exige `--plan` y
   `--expected-current`.
2. **Journal** por etapas (`staging → published → pointer_written →
   cleaned`, o `aborted`) en `<proyecto>/.an-kla/relocations/<txid>.json`:
   estado del proyecto, no de la bóveda; `export` lo excluye. No reutiliza
   `memory/transactions/`, cuyo schema es el de commits de memoria.
3. **Receipt `store_root`** escrito en el staging antes de verificar, de
   modo que se publica en el mismo `rename`.
4. **Alcance de R2a:** sólo project-local → externo. Externo → externo
   falla cerrado (`relocate_source_external_unsupported`); el regreso es R2b.
5. **Índices:** el cleanup borra `memory/indexes/` del origen (derivable y
   con texto de registros); el destino lo reconstruye bajo demanda.
6. **Evidencia sin lock** (`receipts/`, `hook-runs/`) acuñada tras el plan
   queda en el origen y se reporta (`lock_free_residue`,
   `doctor.custody_divergence.project_local_residue`); cualquier otro
   cambio del set planificado aborta (`relocate_source_changed`).
7. **`capabilities.storage.custody.relocate`** pasa de `false` a la lista de
   direcciones soportadas (`["project_local_to_external"]`).

## Enmienda 3 (2026-10-13) — relocate-back y recuperación (R2b)

Registro completo: `docs/planning/g3-r2b-regreso-recuperacion-2026-10-13.md`.
Decisiones de mecanismo tomadas por el agente ejecutor bajo la delegación del
maintainer; concretan §3.5–§3.6:

1. **`relocate plan --back`**: misma forma de plan (`direction:
   external_to_project_local`), mismo `commit`, `inspect` y `reconcile`.
2. **Publicación por subárbol**: staging en `<proyecto>/.an-kla.staging-<txid>`
   (mismo filesystem que el destino y raíz de custodia válida para
   `verify`); cada subárbol de primer nivel —y cada hijo de `memory/`— se
   publica con `rename_noreplace`. Un subárbol ya presente en el destino
   aborta (`relocate_destination_occupied`); no se mezcla.
3. **Punto de commit = borrar el puntero** (`pointer_removed`). Antes, la
   lectura sigue yendo a la bóveda externa y `reconcile --abort` retira sólo
   subárboles que son copia exacta del plan; después sólo se avanza.
4. **La raíz externa vaciada no se borra**: conserva archivos de lock; volver
   a salir exige un destino nuevo (`rename_noreplace` no reutiliza
   directorios).
5. **Recuperación tras recrear el checkout**: `--store-root <bóveda> init`
   reescribe el puntero con la misma identidad y revisión, sin store nuevo.
6. **`init` externo no bifurca una bóveda project-local**: si el anchor del
   proyecto ya tiene identidad o CURRENT, falla con `store_root_divergence`
   (cierra la vía de gemela sin puntero).

## Enmienda 4 (2026-10-13) — R3 y ronda adversarial final

Actas: `docs/planning/g3-r3-consumidores-2026-10-13.md` y
`docs/planning/g3-r3-ronda-adversarial-2026-10-13.md`.

1. **Export** claro y sellado lee la raíz de custodia resuelta y falla cerrado
   con puntero divergente; `restore` sigue publicando sólo project-local.
2. **Bóveda externa sin puntero, con bóveda project-local presente:** toda
   mutación falla con `store_root_divergence` (`check_custody`). Cubre la
   copia externa tras el commit de relocate-back y la copia publicada antes
   del puntero en el traslado de ida.
3. **`init` que escribiría un puntero hacia una bóveda existente** exige que
   la bóveda se haya creado en esta misma raíz de proyecto
   (`canonical_project_root_at_init`); si no, `store_root_project_mismatch`.
   Ligar una bóveda creada en otra raíz (checkout recreado en otra ruta)
   **requiere decisión del maintainer** (REQUIRES_DECISION): hoy no hay forma
   gobernada de hacerlo.
4. Las mutaciones por flag/env **sin** puntero hacia una bóveda de otra raíz
   siguen sólo avisando (`store_root_env_unbound_project`): por bytes no se
   distingue un worktree legítimo de otro proyecto. Riesgo residual
   declarado.

## Enmienda 5 (2026-10-13) — ligar una bóveda creada en otra raíz

Resuelve el REQUIRES_DECISION de la Enmienda 4 §3. Decisión del maintainer
(2026-10-13, hilo «Ejecución del roadmap G3», opción 2b confirmada).

1. **`relocate attach --store-root <bóveda> --expected-current <rev>`** es la
   única vía para ligar a un checkout una bóveda externa creada en otra raíz
   de proyecto. Exige: bóveda externa, sin bóveda project-local, sin puntero
   divergente, identidad completa y CURRENT exacto.
2. Bajo el lock de identidad y el de escritura, escribe en la bóveda un
   relocation receipt `project_root` (raíz ligada anterior → raíz actual) y
   después el puntero. La raíz ligada anterior es el `to_root_observed` de la
   cabeza de la cadena `project_root` o, sin cadena,
   `canonical_project_root_at_init`.
3. **Idempotente:** si la cabeza ya está en esta raíz (crash entre receipt y
   puntero, o repetición) sólo escribe el puntero; con puntero coincidente no
   escribe nada (`replayed: true`).
4. `init` sin puntero acepta la bóveda cuando su raíz ligada (cadena o init)
   es la raíz actual; si no, sigue fallando con `store_root_project_mismatch`.
5. **Límite declarado:** el receipt registra la declaración del operador; por
   bytes no prueba que ambas raíces sean el mismo proyecto. Si el checkout
   anterior sigue vivo con su puntero, los dos comparten la bóveda, igual que
   dos worktrees (F0 §3). `attach` no invalida punteros ajenos.

## Enmienda 6 (2026-10-13) — residuales m1 y m4 (#147)

Decisión del maintainer (2026-10-13): corregir #147 antes de beta.30.

1. **Marcador de intención (m1).** Antes del bootstrap de una bóveda
   externa sin puntero, `init` escribe `.an-kla/store-root.intent`
   (`an-kla/store-root-bind-intent-v1`, con la ruta de la bóveda) y lo borra
   tras escribir el puntero. Mientras exista:
   - `init` project-local falla con `store_root_bind_pending`, sin crear
     identidad local;
   - `init` o `attach` hacia otra bóveda fallan con el mismo código;
   - repetir `--store-root <bóveda> init`, o `relocate attach` sobre esa
     bóveda, termina el binding y borra el marcador.

   Un marcador ilegible cuenta como pendiente (fail closed). Abandonar un
   binding a medias exige borrar el marcador a mano: es una decisión humana.
2. **Vista del puntero (m4).** `custody_pointer_present` deja de calcularse
   al construir el store y se relee en cada acceso (un `lstat`). Un proceso
   longevo abierto antes de un `relocate` deja de servir el origen aunque el
   cleanup haya quedado pendiente.
3. Siguen declarados la Enmienda 4 §4 y la Enmienda 5 §5.

## Enmienda 7 (2026-10-13) — correcciones de la ronda de release beta.30

Ronda adversarial con Muse CLI (otra familia de modelo), veredicto
`FIX-AND-RETRY`: `docs/releases/v0.1.0-beta.30-adversarial.md`.

1. **Copia viva de una bóveda (H-01).** Con puntero presente, una mutación
   sobre una raíz externa cuyo fingerprint coincide pero cuya ruta difiere del
   localizador falla con `store_root_divergence` si el localizador todavía
   contiene una bóveda. Una bóveda movida (localizador sin bóveda) sigue
   siendo escribible. La resolución por flag/env avisa
   `pointer_stale_locator`.
2. **`attach` sobre un puntero existente (H-02)** exige CURRENT exacto y, si
   el localizador quedó vacío porque la bóveda se movió, reescribe el puntero
   hacia la ruta actual (mismo fingerprint). Nunca reescribe un localizador
   que todavía contiene una bóveda.
3. **Lecturas con revisión explícita (H-03).** `snapshot(revision)` aplica la
   misma comprobación de puntero que `read_current`.
4. **`stores scan` (H-04)** no lee a través de ningún componente symlink
   dentro de la bóveda candidata; la clasifica `unreadable` con código
   `symlink_in_vault`.

## Enmienda 8 (2026-10-13) — ronda 2 de release beta.30

Segunda ronda con Muse CLI sobre la Enmienda 7, veredicto `FIX-AND-RETRY`:
`docs/releases/v0.1.0-beta.30-adversarial.md` §Ronda 2.

1. **`attach` de una copia con el checkout anterior vivo (N-01).** Antes de
   escribir el receipt, `attach` mira la raíz ligada anterior. Si allí hay
   un puntero con el mismo fingerprint cuyo localizador contiene una bóveda
   en otra ruta, o una bóveda project-local con la misma identidad (o
   ilegible), falla con `relocate_attach_source_live`. Por bytes una copia
   no se distingue de una bóveda movida: el checkout anterior es el único
   testigo. Si ya no existe, `attach` procede como antes.
2. **Un puntero copiado no es replay (N-02).** `attach` sólo responde
   `replayed: true` cuando la raíz ligada (cabeza de la cadena o init) ya es
   la raíz actual. Si no, verifica, aplica §1 y escribe el receipt
   `project_root` aunque el puntero ya exista.
3. **Localizador no canónico (N-03).** `check_custody`,
   `relocate_pointer_locator` y el descriptor de custodia comparan el
   localizador resuelto (`..`, symlinks), así que la misma bóveda escrita
   con otra ortografía no se bloquea ni avisa `pointer_stale_locator`.
4. **Límites declarados:**
   - Sigue la Enmienda 5 §5: dos checkouts vivos que comparten la *misma*
     bóveda (incluido un puntero copiado a mano) escriben en ella; tras
     `attach`, la raíz ligada pasa al último checkout.
   - **N-04 (LOW):** si el operador borra el puntero a mano, `init` en ese
     checkout crea una bóveda project-local nueva y la externa queda
     huérfana. Sin el puntero ni el marcador de intención no hay testigo
     local; `stores scan` la muestra como `orphan_uncertain`.

## Enmienda 9 (2026-10-13) — ronda 3 de release beta.30 y corte de `attach`

Tercera ronda con Muse CLI, veredicto `FIX-AND-RETRY`:
`docs/releases/v0.1.0-beta.30-adversarial.md` §Ronda 3.

1. **`relocate attach` sale de la CLI (R3-01, HIGH).** Basta renombrar el
   checkout anterior para que `attach` acepte una copia viva. Por la regla de
   corte del maintainer (2026-10-13), beta.30 no expone el comando ni lo
   anuncia en `capabilities`. La API y sus tests se quedan; el rediseño es
   ADR-0051 (Propuesta). La Enmienda 5 §4 (`init` acepta la bóveda cuando su
   raíz ligada es la actual) sigue vigente.
2. **Abort tras el punto de compromiso (R3-02, HIGH).** Si el proceso muere
   después de escribir el puntero y antes de registrar `pointer_written`,
   `reconcile --abort` ve un puntero con el fingerprint de la transacción,
   registra `pointer_written` y falla con `relocate_abort_too_late`. Antes
   borraba el destino y dejaba el puntero colgando.
3. **Lo mismo en la vuelta (R3-03, MEDIUM).** Si el puntero ya no existe en
   `published`, el abort de `relocate back` registra `pointer_removed` y falla
   con `relocate_abort_too_late`.
4. **`stores scan` con archivos no regulares (R3-04, LOW).** Lee sólo
   archivos regulares, abiertos sin bloquear y con un tope de 1 MiB. Un FIFO o
   un dispositivo dentro de la bóveda candidata la clasifica `unreadable` con
   código `non_regular_file_in_vault`.
5. R3-05 (LOW, `replayed` de `attach`) queda con el rediseño de ADR-0051.

## Enmienda 10 (2026-10-13) — ronda 4 de release beta.30

Cuarta ronda con Muse CLI, sobre el diff completo desde beta.29, veredicto
`FIX-AND-RETRY`: `docs/releases/v0.1.0-beta.30-adversarial.md` §Ronda 4.

1. **`reconcile` tras el punto de compromiso (R4-01, HIGH).** La Enmienda 9
   §2–§3 sólo cubría `--abort`. Sin abort, si la bóveda ya viva avanzó tras el
   crash, `reconcile` fallaba siempre con `relocate_destination_unrecognized`
   porque la comparaba con la copia planificada. Ahora, en `published`:
   - ida: si existe un puntero con el fingerprint de la transacción,
     `reconcile` registra `pointer_written` y termina la limpieza sin
     comparar el destino con la base;
   - vuelta: si el puntero ya no existe, registra `pointer_removed` y
     termina como cuando esa etapa sí quedó registrada (la bóveda local puede
     haber avanzado).
   Un puntero ilegible falla con `store_root_pointer_invalid`, nunca limpia.
2. **Receipts que no son archivos regulares (R4-02, MEDIUM).** Los receipts
   se leen sin bloquear y sólo si son archivos regulares; un FIFO o un
   directorio es `relocation_receipt_invalid`. `stores scan` clasifica esa
   bóveda `unreadable` con `relocation_receipt_chain_invalid` en vez de
   colgarse. Aplica también a las lecturas normales de la cadena.
3. **Superficies aditivas por defecto (R4-03, LOW).** Sin flag, env ni
   puntero, `capabilities` incluye el bloque `custody`, `doctor` incluye
   `custody_divergence` y el catálogo publica los schemas v3. Son cambios
   aditivos deliberados de G3; el layout y `startup-diagnostic` v1/v2 no
   cambian. La afirmación 1 de la ronda se precisa en ese sentido y las
   notas de beta.30 los listan.

## Enmienda 11 (2026-10-14) — ronda 5 de release beta.30

Quinta ronda con Muse CLI, sobre `5995767` y el diff completo desde beta.29,
veredicto `FIX-AND-RETRY`: `docs/releases/v0.1.0-beta.30-adversarial.md`
§Ronda 5. Precisa la Enmienda 10 §1–§2: el punto de compromiso se reconoce
sólo por evidencia que la propia transacción dejó.

1. **Ida: puntero con otro localizador (R5-01, HIGH).** Tras un crash antes
   del journal `pointer_written`, un puntero con el fingerprint de la
   transacción pero cuyo `store_root` resuelto no es el destino planificado
   (la bóveda local o una copia) ya no cuenta como punto de compromiso:
   `reconcile` falla con `relocate_pointer_unrecognized` y no limpia el
   origen. La forma resuelta del localizador sigue valiendo (N-03).
2. **Vuelta: puntero ausente sin intención registrada (R5-02, MEDIUM).**
   Antes de borrar el puntero, la vuelta registra en el journal
   `pointer_removal_started` (etapa `published`, fsync). Un puntero ausente
   en `published` cuenta como punto de compromiso sólo con esa marca; sin
   ella, `reconcile` falla con `relocate_pointer_unrecognized` y no toca la
   bóveda externa. Con la marca y el puntero todavía presente (crash entre
   ambos), la transacción sigue antes del punto de compromiso: termina o se
   aborta como en `published`. Residual: quien borre el puntero a mano justo
   en esa ventana de crash consuma la vuelta; no hay pérdida de revisiones,
   porque la bóveda local publicada es la que queda viva.
3. **Árbol de receipts que no es directorio (R5-03, LOW).** Si
   `relocation-receipts/` o `relocation-receipts/sha256/` existen y no son
   directorios reales (`lstat`), la cadena es `relocation_receipt_invalid`;
   `stores scan` clasifica la bóveda `unreadable` con
   `relocation_receipt_chain_invalid`.

## Enmienda 12 (2026-10-14) — ronda 6 de release beta.30

Sexta ronda, primera con opencode y GLM 5.3 (`zai-coding-plan/glm-5.3`) como
revisor, sobre `d9e3975`, veredicto `FIX-AND-RETRY`:
`docs/releases/v0.1.0-beta.30-adversarial.md` §Ronda 6.

1. **Vuelta: puntero hacia otra bóveda con la misma custodia (R6-03, HIGH).**
   Espejo de la Enmienda 11 §1 en la vuelta. Antes de borrar el puntero, la
   vuelta exige que su `store_root` resuelto sea el origen planificado; si
   apunta a otra bóveda (por ejemplo una copia que siguió escribiendo), falla
   con `relocate_pointer_unrecognized` sin borrar el puntero ni limpiar nada.
   Vale con y sin la marca `pointer_removal_started`.
2. **Journals que no son archivos regulares (R6-01, MEDIUM; R6-02, LOW).**
   `relocate inspect`, `reconcile`, el replay de `commit` y `doctor` leen los
   journals sin bloquear y sólo si son archivos regulares. Un FIFO o un
   directorio es `relocate_journal_invalid` (antes colgaba o emitía
   `IsADirectoryError`); `doctor` lo cuenta como relocación sin terminar.
3. **Marca forjable (nota del revisor, no hallazgo).** Editar el journal para
   añadir `pointer_removal_started` permite consumir una vuelta; exige el
   mismo acceso que borrar la bóveda y queda dentro de los residuales
   declarados.

## Enmienda 13 (2026-10-14) — ronda 7 de release beta.30

Séptima ronda, opencode con GLM 5.3, sobre `f62341a`, veredicto
`FIX-AND-RETRY` con un único hallazgo MEDIUM:
`docs/releases/v0.1.0-beta.30-adversarial.md` §Ronda 7. Las correcciones de
las Enmiendas 11 y 12 resistieron todas las variantes del revisor.

1. **m4 en la vuelta (R7-01, MEDIUM).** La Enmienda 6 §2 sólo cubría un
   origen project-local: un proceso longevo abierto sobre la bóveda externa
   seguía sirviéndola después del punto de compromiso de `relocate back`, y
   tras la limpieza fallaba con `current_missing` en vez de un código de
   custodia. Ahora un store externo abierto cuando el puntero lo nombraba
   comprueba en cada lectura que el puntero lo siga nombrando (forma
   resuelta); si falta, es ilegible o nombra otra raíz, la lectura falla con
   `store_root_divergence`. Un store externo abierto sin ese puntero (flag,
   env o el destino de una relocación en curso) conserva las comprobaciones
   de apertura y de mutación; no cambia el comportamiento sin custodia
   externa.
