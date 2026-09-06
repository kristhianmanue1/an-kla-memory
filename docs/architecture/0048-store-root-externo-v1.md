# ADR-0048: almacenamiento externo — `store_root` separado de `project_root`

- **Estado:** Propuesta
- **Implementación:** No iniciada
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
deuda beta.23, antes de F6.

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
