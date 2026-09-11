# Changelog

El changelog canónico de AN-KLA Memory vive en
[`docs/releases/`](docs/releases/): una nota por etiqueta publicada, cada
una acompañada de su ronda adversarial (`*-adversarial.md`) que contiene la
decisión `proceed` que autorizó la publicación. Este archivo es sólo un
índice; el detalle vive allí.

El formato de cada entrada sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
por intención, y el proyecto usa [versionado semántico](https://semver.org/lang/es/)
en fase de pre-release `0.1.0`.

## [No publicadas]

Nada aún.

## [v0.1.0-beta.27]

**Ciclo zero_score: paridad de diagnóstico y señal de selección vacía**
(issues #118 y #133; ADR-0049). No cambia la plantilla gestionada
(`TEMPLATE_VERSION` sigue en `0.1.0-beta.26`), pero **sí el contrato de
recuperación**: nuevos ids `retrieval-result-v3`/`mcp-retrieve-v3`.

**Añadido**:
- `empty_reason: "no_lexical_overlap"` de primera clase (#133,
  propuesta 1; ADR-0049): cuando la selección queda vacía por cero
  solapamiento léxico —típico de un agente fresco sin vocabulario del
  store—, el resultado porta la señal con schema `retrieval-result-v3`
  (CLI) o `mcp-retrieve-v3` (MCP). Versiones **dispersas**: v1/v2 siguen
  emitiéndose byte-idénticos en todos los demás casos.
- Tabla de verdad del predicado (ADR-0049 §3): no emiten los vacíos por
  presupuesto (base o corte de envelope MCP), all-inactive, no_text-only
  ni store vacío — la causa real es otra.
- Detectores de freshness migrados a detección estructural
  (`mcp.py`/`context.py`): nunca igualdad de string de id (F-PC2-1/2).
- Hueco del harness de evaluación cerrado (F-PC1-7): `_compare` ahora
  verifica `excluded_summary_equal`; `retrieval-eval-report-v2` editado
  in place (precedente ADR-0037) con paridad byte docs/paquete.

**Corregido**:
- #118/R3: paridad del diagnóstico `zero_score` entre scan e índice fts5 —
  la contabilidad es única, post-sort y previa al narrowing; el índice ya
  no hace desaparecer los zero-score sin contarlos. Test de paridad
  validado: falla contra el código viejo.
- Ronda adversarial de código (F-C1-1..8): test MCP del corte de envelope
  reanclado a la ventana real; tests de detector para MCP/contexto con
  v3+freshness; `allOf` freshness⇔freshness_profile en los schemas v3;
  conteo de ADRs desactualizado en `docs/README.md`.

**Nota de upgrade**: consumidores que parseen el campo `schema` de
respuestas de recuperación verán `an-kla/retrieval-result-v3` /
`an-kla/mcp-retrieve-v3` en el caso de selección vacía por solape cero;
los campos existentes no cambian. `schema show` publica ambos v3.

## [v0.1.0-beta.26]

**DX: diagnóstico por campo en checkpoint y coherencia documental** (issues
#120 y #116). Release code-only respecto del contrato gestionado:
`TEMPLATE_VERSION` sigue en `0.1.0-beta.26`. No expande la superficie de
AN-KLA ni incorpora trabajo de G3/#57.

**Añadido**:
- Diagnóstico por campo en todos los errores de checkpoint (#120, punto 1):
  cada `CheckpointPolicyError` porta `detail` estilo `ruta:razón`
  (convención del merge #125 en `write_policy.py`) — los 52 sitios de
  `checkpoint_policy.py` y los 10 restantes en `resume.py`/
  `checkpoints.py`. `str(error)` sigue siendo el código estable
  (retrocompatible). Los dos repros del issue ahora reportan el campo
  ofensor: `invalid_working_state (source_state:keys:missing=dirty_digest)`
  y `invalid_working_state (captured_at.value:not_canonical_utc)`.
- Checks compuestos divididos para diagnóstico preciso: `scope.fields` →
  `:not_string`/`:empty`/`:order`/`:duplicate`/`:unknown`; `build_plan` →
  `decision:mismatch` vs `revision`; `checkpoint_parent_mismatch` nombra el
  campo editable por el agente (`supersedes_checkpoint:not_current`).
- Nombres de llaves extra sanitizados y acotados en `detail`:
  `[unnamed]` fuera del vocabulario de claves, truncado global a 256
  caracteres — el `detail` nunca incorpora contenido de entrada sin acotar.
- Guía de checkpoint §5 actualizada: el mapa de errores ya no está
  «pendiente de #120.1» y documenta `detail` como informativo/evolutivo.

**Corregido**:
- Desalineación documental activa (#116/C2): `AGENTS.md` ya no niega
  `source_state` `git/v1` (ADR-0038: valores exclusivamente
  `caller_asserted`, sin verificación Git implícita);
  `docs/mathematical-foundations.md` reconcilia prosa y tabla (envelope del
  ensamblador vs host framing sin medir) y separa compactación física
  (implementada) de fusión semántica bajo ε-compatibilidad (pendiente).
- Alcance temporal del anclaje documentado (#116/C3): nueva sección
  «Alcance temporal provisional» en ADR-0044 — `anchor_match` acredita el
  estado de `refs/` sólo en el instante de la verificación; la revalidación
  por consumo queda como pendiente registrado, sin atribuirle enforcement
  al código vigente.

**Tests**: +21 casos de detalle y absorción adversarial
(`CheckpointErrorDetailTests` + casos de store/resume), incluidos los dos
repros de #120, claves hostiles sanitizadas y `scope.fields` no-string;
suite completa verde.

## [v0.1.0-beta.25]

**Estabilización, DX para agentes y coherencia contractual** (issues #125,
#124, #123, #122). Release de saneamiento: no expande la superficie de
AN-KLA. `TEMPLATE_VERSION` queda en `0.1.0-beta.26` — eje separado de la
versión del paquete; no es code-only, el contrato sí cambió.

**Añadido**:
- `plan-write --emit-authority-template` (#125/GAP-2): calcula
  `proposal_sha256`/`base_revision` sin que el agente reconstruya la
  canonicalización a mano. Mismo patrón que
  `checkpoint plan --emit-authority-template`.
- Documentación explícita del checkpoint genésico (#125/GAP-3): `init` ya
  crea uno; `supersedes_checkpoint` siempre es un digest, obtenido de
  `checkpoint show`. `CheckpointPolicyError` ahora porta `detail` de campo
  (`invalid_working_state (supersedes_checkpoint)`), mismo patrón que
  `WritePolicyError`.
- `--expected-current` documentado inequívocamente como la revisión del
  store, nunca el `checkpoint_digest` (#123).
- Forma canónica de instalación (`repositorio + tag exacto`) documentada en
  `AN-KLA.md` (#123).

**Corregido**:
- Falso negativo de contract version skew (#124): un PR previo cambió el
  contrato sin bumpear `TEMPLATE_VERSION`, causando que `context status`
  reportara `ok:true` para un contrato desactualizado. Corregido y con test
  de regresión.
- `docs/write-policy-cli.md` ya no se referencia como disponible tras
  instalar (nunca se empaqueta en el wheel): `--help`/`AN-KLA.md` apuntan a
  `schema show`/`schema list` (#125/GAP-1).
- Endpoint de update-check documentado correctamente
  (`/releases?per_page=1`, no `/releases/latest`).
- `test_adapter_id_grammar_edges_accepted` ya no depende de
  `PYTHONHASHSEED` (#122): destino determinista por índice, no `hash()`.
- `scripts/check_clean_wheel.py`: `NameError` (import de `Path` perdido en
  la preparación de beta.23) y hardcode de `template_version` obsoleto.

**Evidencia**: H-DX-1A/H-DX-1B = PASS (tres agentes frescos independientes,
una corrida contra wheel distribuido, sin lectura de código fuente en las
pruebas black-box); ronda adversarial acotada sin BLOCKER/HIGH en cada PR.
Detalle completo en `docs/releases/v0.1.0-beta.25.md` y su ronda adversarial.

## [v0.1.0-beta.24]

**Checkpoint first-try para agentes** (issues #120.2/.3/.4, #121) y
documentación de instalación/actualización reforzada. Release **code-only**:
contrato gestionado y `TEMPLATE_VERSION` siguen en `0.1.0-beta.21`.

**Añadido**:
- `checkpoint plan --emit-authority-template`: emite la plantilla de
  `checkpoint-authority-v1` con `proposal_sha256`/`base_revision`
  calculados desde el proposal interno (read-only, determinista).
- `--authority` opcional en `checkpoint plan` (falta →
  `missing_checkpoint_authority`, exit 2).
- `docs/agent-checkpoint-guide.md`: cierre de sesión gobernado end-to-end,
  validado e2e.
- "Ruta del agente" en `docs/README.md` (mapa de documentación).
- Aviso de update-check apunta al flujo completo de actualización de
  contexto (#116/G1).
- ADR-0048 aceptada (G3 store_root externo — sin implementación aún).

**Cambiado**:
- `docs/upgrade-agent-flow.md`: ejemplos refrescados a etiquetas vigentes
  y enlace recíproco con uso-diario (#116/G2).
- `checkpoint plan` sin `--authority` ni `--emit-authority-template` ahora
  falla con `missing_checkpoint_authority` en vez de un error de argparse.

## [v0.1.0-beta.23]

Release de mantenimiento: el fix #119 (export con perfil host-managed) más
todo el pase de deuda pre-G3 ya mergeado a `main` tras beta.22. Release
**code-only**: contrato gestionado y `TEMPLATE_VERSION` siguen en
`0.1.0-beta.21`.

**Corregido**:
- #119 (P1-beta.23): `export create` fallaba con
  `export_unrecognized_durable_path` en cualquier proyecto con perfil
  host-managed. `hook-runs/**` viaja ahora con la bóveda (`_PATTERNS`) y
  `host-hooks.json` queda excluido (es del proyecto) — ADR-0048 §3.
- #115/T1: replay de ADR-0024 §API/CLI — mismo txid + mismo plan binding
  reproduce el resultado (`replayed: true`) en vez de chocar con el CAS;
  binding distinto → `transaction_binding_conflict`.
- #118/R2: `assemble_context` sostiene un único lease de reader gate
  (patrón `resume`); una compactación intercalada ya no rompe la
  operación compuesta.
- #111/P2: `write_lock` POSIX con `LOCK_NB` + backoff + deadline de 10s →
  `write_lock_busy` (paridad con Windows); `docs/write-policy-cli.md`
  actualizada.
- #116/C1: `verificar_anclaje` cita la ruta, corre el pipeline con
  `pipefail` y falla cerrado ante `refs/` vacío (adiós al anchor_match
  falso con layouts con espacios).

**Añadido**:
- ADR-0048 aceptada (G3, store_root externo): registro en 48 ADRs
  (45 aceptadas, 3 propuestas). Sin implementación aún.
- #119/#115/#117/#111: issues cerrados con evidencia.

**Mantenimiento**:
- #117: `store.py` 812 → 573 líneas; partición en `write_commit.py`,
  `store_locks.py`, `store_recovery.py`, `store_errors.py`; techo
  transitorio retirado.
- Fix #119 vía test de regresión `test_export_with_host_managed_artifacts_issue119`.

## [v0.1.0-beta.22]

Release de consolidación: G2 completo (hooks gobernados del host, ADR-0047),
deuda de proceso pagada (#95/#106/#112) y absorción de la auditoría externa
(#113/R1, #114/A1+A2, #115/T2). Release **code-only**: el contrato gestionado
sigue en `0.1.0-beta.21`.

**Añadido**:
- G2 (ADR-0047, issue #56): declaración read-only `.an-kla/host-hooks.json`
  con límites congelados; evidencia `hook-run-v1` acuñada y verificada por
  el motor vía `--on-behalf-of-hook` (HMAC + binding, caps de lectura,
  idempotente por `run_id`); `integration-status-v2` con bloque `host_hooks`
  y `observed_profile` computado (`unspecified | declared-not-invoked |
  host-managed/v1`, recencia 24h con `--now` inyectable);
  `pending_continuity` computable sobre el vocabulario de ADR-0030; schemas
  `host-hooks-v1`/`hook-run-v1`/`integration-status-v2` publicados; guía
  `docs/host-hooks-guide.md`. v1 queda congelado y es la emisión por defecto.
- CI local: selftest G-3 del redteam como gate automático (#112) y matriz
  de intérpretes soportados (#111/P5) con `AN_KLA_CI_LOCAL_MATRIX=0` como
  escape.
- `examples/agent-integration/`: wrapper de referencia para agentes (#111/P6).
- `docs/write-policy-cli.md`: liveness del write lock y contrato del agente
  (#111/P2-doc).

**Corregido**:
- #113/R1 (P1): un `record.status`/`nu` no escalar admitido por la escritura
  tumbaba a `retrieve`/`rebuild-index`/`evaluate-v2` con `TypeError`. La
  escritura lo rechaza (`record.status`) y los lectores degradan fail-closed
  (`an_kla/vigency.py`) para registros ya persistidos.
- #114/A1: escrituras parciales de `os.write` en `_write_exclusive` dejaban
  claves/receipts truncados; ahora el bucle garantiza el payload completo.
- #114/A2: `verify_receipt_for_authority` recalcula el digest canónico del
  receipt y lo compara con su dirección content-addressed.
- #115/T2: `initialize_with_outcome` preserva el outcome de init ante fallo
  operacional posterior de attest (`attest_init_unwritable`).

**Mantenimiento**: partición de tamaños (#106: README + cinco tests);
techos retirados de `skevi-gate.json`; #95 cerrado con evidencia; techo
transitorio `an_kla/store.py: 820` con issue #117; `TEMPLATE_VERSION` sin
cambio.

## [v0.1.0-beta.21]

Cierre del ciclo attest (issue #102, ADR-0046): plantilla del contrato
bumpada a `0.1.0-beta.21` con el vocabulario de attest en §Resolver
autoridad, ADR-0046 aceptada, y adjuntos de la ronda adversarial externa
(issue #111): techo `requires-python <3.14`, schema `write-proposal-v1`
documenta `text`, warning `record_without_indexable_text` visible en
stderr, runbook `docs/agent-recovery.md`, mensaje canónico del selftest
redteam unificado (#109) y anclaje con `LC_ALL=C` (re-anclaje registrado).

**Cambiado**: contrato gestionado `0.1.0-beta.11` → `0.1.0-beta.21`
(flujos explícitos: adopt-baseline + update; sin cambios fuera de
§Resolver autoridad); entrada histórica `0.1.0-beta.11` añadida al
registro de plantillas (falso `managed_contract_modified` eliminado).
Detalle y límites en la
[nota de release](docs/releases/v0.1.0-beta.21.md) y su
[ronda adversarial](docs/releases/v0.1.0-beta.21-adversarial.md).

## [v0.1.0-beta.20]

Fase H de hardness del issue #102 (reportada por el consumidor real
infosalud), CI local-only (retiro de GitHub Actions, decisión del
operador), ADR-0043/0044 y adopción de Skevi (ADR-0045). Sin cambios de
formato físico ni de política de autoridad; los stores beta.19 se leen
sin migración.

**Cambiado**: `plan-write` falla cerrado con códigos `plan_*` nuevos
(#103); marcadores dentro de un fence reportan
`managed_block_inside_fence` (#105); `commit-write-plan` añade
`record_without_indexable_text` a `outcome.warnings` (#104); el repo ya
no define workflows remotos — verificación canónica local. Detalle y
límites en la
[nota de release](docs/releases/v0.1.0-beta.20.md) y su
[ronda adversarial](docs/releases/v0.1.0-beta.20-adversarial.md).

## [v0.1.0-beta.19]

Preparación documental del ciclo de release: deuda C-2 de la ronda REL
beta.18 resuelta (CHANGELOG sin doble estado, índice `docs/README.md`
actualizado a la release vigente, frase de wheels del README corregida,
`check_clean_wheel.py` versionado con el bump), ADR-0042 partido en ADR
corto + apéndice técnico (#95, gate de tamaños sin gracia) y nota de
release propia. Sin cambios de código: el runtime no muta respecto de
beta.18 salvo el bump de versión.
[Notas](docs/releases/v0.1.0-beta.19.md)

## [v0.1.0-beta.18]

Perfil sellado `sealed-export/v1` completo (ADR-0042, issue #46):
`export create --seal` con adaptador externo de claves, `export verify`
dual (estructural sin clave / autenticado con clave), `export restore`
sellado fail-closed y matriz de pruebas §9 consolidada. Extra opcional
`[sealed]`; camino `export/v1` intacto. Sin rupturas deliberadas.
[Notas](docs/releases/v0.1.0-beta.18.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.18-adversarial.md)

## [v0.1.0-beta.17] — 2026-08-20

Adopción explícita de baseline (`adopt-baseline`, ADR-0040/0035) con
`context update` fail-closed ante drift no adoptado; inventario físico
por revisión (`inventory --revision`, ADR-0041) metadata-only con planos
físico/observable y bucket `eliminada`; upgrade-plan v3
(`manifest_target_sha256_at_baseline`).
[Notas](docs/releases/v0.1.0-beta.17.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.17-adversarial.md)

## [v0.1.0-beta.16] — 2026-08-20

Denominadores de frescura (ADR-0037), `source_state` `git/v1`
(ADR-0038), `integration status` G1 (ADR-0039), señal de contexto en
`init` (#87) y ayuda CLI completa.
[Notas](docs/releases/v0.1.0-beta.16.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.16-adversarial.md)

## [v0.1.0-beta.15] — 2026-08-20

Diagnóstico de arranque por ejes observables, red de resguardo del CLI ante
excepciones no previstas, `jsonschema` como extra de test y ADR-0036
sincronizada con la implementación.
[Notas](docs/releases/v0.1.0-beta.15.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.15-adversarial.md)

## [v0.1.0-beta.14] — 2026-08-13

Primer write operable: ayuda ampliada de `plan-write`/`commit-write-plan`,
recorrido documentado de extremo a extremo y errores accionables.
[Notas](docs/releases/v0.1.0-beta.14.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.14-adversarial.md)

## [v0.1.0-beta.13] — 2026-08-13

G-VIEW v1: vista contextual derivada sobre `subject_ref`
(CORE+CLI+MCP+CAP). [Notas](docs/releases/v0.1.0-beta.13.md)

## [v0.1.0-beta.12] — 2026-08-12

Identidad contextual estable `subject_ref` y namespaces derivados.
[Notas](docs/releases/v0.1.0-beta.12.md)

## [v0.1.0-beta.11] — 2026-08-09

Checkpoint+resume, outcomes de transacción, refute/export/compactación
gobernados, identidad store/proyecto, retiro del `write` legado.
[Notas](docs/releases/v0.1.0-beta.11.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.11-adversarial.md)

## Anteriores

- v0.1.0-beta.10 (sin nota) ·
  [ronda](docs/releases/v0.1.0-beta.10-adversarial.md)
- [v0.1.0-beta.9](docs/releases/v0.1.0-beta.9.md) ·
  [ronda](docs/releases/v0.1.0-beta.9-adversarial.md)
- [v0.1.0-beta.8](docs/releases/v0.1.0-beta.8.md) ·
  [ronda](docs/releases/v0.1.0-beta.8-adversarial.md)
- [v0.1.0-beta.7](docs/releases/v0.1.0-beta.7.md) ·
  [ronda](docs/releases/v0.1.0-beta.7-adversarial.md)
- [v0.1.0-beta.6](docs/releases/v0.1.0-beta.6.md)
- [v0.1.0-beta.5](docs/releases/v0.1.0-beta.5.md)
- [v0.1.0-beta.4](docs/releases/v0.1.0-beta.4.md)
- [v0.1.0-beta.3](docs/releases/v0.1.0-beta.3.md)
- [v0.1.0-beta.2](docs/releases/v0.1.0-beta.2.md)
- [v0.1.0-beta.1](docs/releases/v0.1.0-beta.1.md) ·
  [ronda](docs/releases/v0.1.0-beta.1-adversarial.md)
- [v0.1.0-alpha.3](docs/releases/v0.1.0-alpha.3.md)
- [v0.1.0-alpha.2](docs/releases/v0.1.0-alpha.2.md)
