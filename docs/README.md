# Documentación de AN-KLA Memory

Esta carpeta contiene la documentación evergreen del proyecto. Para hallazgos
puntuales, planificación y respuestas a revisiones externas, ver
[`planning/`](planning/).

Para instalar o migrar un proyecto consumidor, empieza por la
[guía de beta.11](beta11-user-guide.md).

## Índice

### Decisiones de arquitectura (ADRs)

Los ADRs viven en [`architecture/`](architecture/) y siguen una numeración
secuencial. Cada uno documenta una decisión arquitectónica irreversible o
difícil de revertir. Este índice es el registro canónico de inventario y estado
decisional, actualizado al 2026-08-20. `Aceptada` no implica que toda extensión
prospectiva esté implementada; la última columna conserva esa distinción.

| # | ADR | Tema | Estado | Vigencia o evidencia |
|---|---|---|---|---|
| 0001 | [revision-commit](architecture/0001-revision-commit.md) | Revisión content-addressed y `CURRENT` | Aceptada | Núcleo de alpha.1; formato físico vigente |
| 0002 | [alpha-scope](architecture/0002-alpha-scope.md) | Alcance alfa | Aceptada | Alcance histórico de alpha.1 |
| 0003 | [mcp-worktree-and-safety-gates](architecture/0003-mcp-worktree-and-safety-gates.md) | MCP y compuertas de seguridad | Aceptada | Publicada en [alpha.2](releases/v0.1.0-alpha.2.md) |
| 0004 | [index-reference](architecture/0004-index-reference.md) | Referencia de índice (FTS5) | Aceptada | Publicada en [alpha.3](releases/v0.1.0-alpha.3.md) |
| 0005 | [mathematical-alignment](architecture/0005-mathematical-alignment.md) | Alineación matemática | Aceptada | Norma vigente; diseño prospectivo explícito |
| 0006 | [context-assembly-v1](architecture/0006-context-assembly-v1.md) | Ensamblado de contexto con presupuesto | Aceptada | Publicada en [beta.1](releases/v0.1.0-beta.1.md) |
| 0007 | [write-policy-v1](architecture/0007-write-policy-v1.md) | Política de escritura gobernada | Aceptada | Beta.1; transición cerrada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0008 | [cost-model-v1](architecture/0008-cost-model-v1.md) | Modelo de costos (bytes UTF-8) | Aceptada | F0 vigente; tokenización exacta F3 pendiente |
| 0009 | [managed-agent-context-v1](architecture/0009-managed-agent-context-v1.md) | Contexto administrado para agentes | Aceptada | Publicada en [beta.1](releases/v0.1.0-beta.1.md) |
| 0010 | [agent-first-public-contracts](architecture/0010-agent-first-public-contracts.md) | Contratos públicos agent-first | Aceptada | Publicada en [beta.2](releases/v0.1.0-beta.2.md) |
| 0011 | [governed-agent-upgrade](architecture/0011-governed-agent-upgrade.md) | Upgrade gobernado del proyecto | Aceptada | Publicada en [beta.3](releases/v0.1.0-beta.3.md) |
| 0012 | [update-check-v1](architecture/0012-update-check-v1.md) | Verificación no bloqueante de versiones | Aceptada | Publicada en [beta.4](releases/v0.1.0-beta.4.md) |
| 0013 | [multi-stream-retrieval](architecture/0013-multi-stream-retrieval.md) | Recuperación multi-stream opt-in | Aceptada | Publicada en [beta.4](releases/v0.1.0-beta.4.md) |
| 0014 | [index-v2-multistream](architecture/0014-index-v2-multistream.md) | Índice FTS5 multi-stream | Aceptada | Publicada en [beta.4](releases/v0.1.0-beta.4.md) |
| 0015 | [excluded-detail-v1](architecture/0015-excluded-detail-v1.md) | Transparencia en exclusiones | Aceptada | Publicada en [beta.4](releases/v0.1.0-beta.4.md) |
| 0016 | [auto-reindex-post-commit](architecture/0016-auto-reindex-post-commit.md) | Reindexado best-effort tras commit | Aceptada | Publicada en [beta.4](releases/v0.1.0-beta.4.md) |
| 0017 | [target-drift-transparency](architecture/0017-target-drift-transparency.md) | Transparencia de target drift en upgrade | Aceptada | Publicada en [beta.5](releases/v0.1.0-beta.5.md) |
| 0018 | [indexable-text-field](architecture/0018-indexable-text-field.md) | Campo explícito `indexable_text` para FTS | Aceptada | Publicada en [beta.5](releases/v0.1.0-beta.5.md) |
| 0019 | [governed-supersede](architecture/0019-governed-supersede.md) | Operación `supersede` gobernada | Aceptada | Publicada en [beta.8](releases/v0.1.0-beta.8.md) |
| 0020 | [context-diagnostics-in-write-result](architecture/0020-context-diagnostics-in-write-result.md) | Salud del contrato en el resultado de escritura e `init` | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md); nota v3 extiende el patrón a `init` (#87) |
| 0021 | [verified-at-freshness-v1](architecture/0021-verified-at-freshness-v1.md) | `verified_at` autodeclarado y frescura computada en lectura | Aceptada | Publicada en [beta.9](releases/v0.1.0-beta.9.md) |
| 0022 | [store-project-identity-v1](architecture/0022-store-project-identity-v1.md) | Identidad lógica separada de proyecto y store | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0023 | [governed-checkpoint-handoff-v2](architecture/0023-governed-checkpoint-handoff-v2.md) | Checkpoint exacto y handoff gobernado | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md); su perfil reservado `git/v1` fue supersedido por ADR-0038 |
| 0024 | [commit-outcome-v2](architecture/0024-commit-outcome-v2.md) | Resultado transaccional y durabilidad explícita | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0025 | [retrieval-evaluation-v2](architecture/0025-retrieval-evaluation-v2.md) | Benchmark de ranking y presupuesto sin cambiar retrieval | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0026 | [governed-refute-v1](architecture/0026-governed-refute-v1.md) | Refutación gobernada, auditable y sin sucesor | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0027 | [verifiable-export-restore-v1](architecture/0027-verifiable-export-restore-v1.md) | Export/backup verificable y restore fail-closed | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0028 | [governed-compaction-v1](architecture/0028-governed-compaction-v1.md) | Corte de epoch, tombstones y archivo verificable | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0029 | [derived-semantic-retrieval-v1](architecture/0029-derived-semantic-retrieval-v1.md) | Índice semántico derivado y recuperación híbrida opt-in | Propuesta | Sin implementación ni proveedor autorizado |
| 0030 | [milestone-checkpoint-obligation-v1](architecture/0030-milestone-checkpoint-obligation-v1.md) | Obligación gobernada de continuidad al cerrar hitos | Propuesta | En reevaluación; §4 reserva `git/v1` para tool_observed, supersedido por ADR-0038 |
| 0031 | [agent-owned-memory-host-managed-v1](architecture/0031-agent-owned-memory-host-managed-v1.md) | Memoria del agente con alcance de proyecto y perfil host-managed | Aceptada | Reconocido host-managed como perfil soportado; G1 publicado como ADR-0039 (PR #85); G2–G4 con diseños de entrada |
| 0032 | [derived-contextual-view-v1](architecture/0032-derived-contextual-view-v1.md) | Vista contextual vigente derivada, non-authoritative, sobre sustrato de afirmaciones | Aceptada | G-SUBJECT publicado en [beta.12](releases/v0.1.0-beta.12.md); G-VIEW publicado en [beta.13](releases/v0.1.0-beta.13.md) |
| 0033 | [subject-ref-v1](architecture/0033-subject-ref-v1.md) | Identidad contextual estable `subject_ref`, namespace derivado de project identity y binding bajo lock | Aceptada | Publicada en [beta.12](releases/v0.1.0-beta.12.md) |
| 0034 | [derived-context-view-contract-v1](architecture/0034-derived-context-view-contract-v1.md) | Contrato G-VIEW v1: vista contextual determinista, non-authoritative, paginada y recuperable | Aceptada | CORE+CLI+MCP+CAP publicados en [beta.13](releases/v0.1.0-beta.13.md); auditoría REL `proceed` |
| 0035 | [explicit-project-context-baseline-adoption-v1](architecture/0035-explicit-project-context-baseline-adoption-v1.md) | Adopción explícita de baseline project-owned sin debilitar target drift | Aceptada | Arquitectura; contrato congelado e implementado por ADR-0040 (#45) |
| 0036 | [startup-memory-diagnostic-v1](architecture/0036-startup-memory-diagnostic-v1.md) | Diagnóstico de arranque read-only por ejes observables totales, sin enum de estados compuestos | Aceptada | Implementada en `main` (#83, post-beta.14): comando `startup-diagnostic`; `repo_context` refinado a `git rev-parse` tras rondas adversariales de #76 |
| 0037 | [freshness-denominators-v1](architecture/0037-freshness-denominators-v1.md) | G-FRESH: recuentos evaluated/not_evaluable/unparseable/stale sobre la selección final en el bloque freshness | Aceptada | Implementada en `main` (PR #85, hacia beta.16): retrieve, assemble-context y MCP; denominador de view diferido |
| 0038 | [source-state-git-v1](architecture/0038-source-state-git-v1.md) | `source_state` con perfil `git/v1` caller_asserted para ligar el checkpoint al commit que describe (#79) | Aceptada | Implementada en `main` (PR #85, hacia beta.16): policy+schema aditivos, CLI sin subprocesos |
| 0039 | [integration-status-v1](architecture/0039-integration-status-v1.md) | G1: contrato observable de la integración por ejes (store, contexto gestionado, modo) sin enum compuesto (#55) | Aceptada | Implementada en `main` (PR #85, hacia beta.16): comando `integration status`, read-only |
| 0040 | [baseline-adoption-contract-v1](architecture/0040-baseline-adoption-contract-v1.md) | Adopción explícita de baseline project-owned (`adopt-baseline` plan→commit, update fail-closed, upgrade-plan v3) | Aceptada | Implementada en `main` (PR #90, hacia beta.17); cierra el ciclo ADR-0035 |
| 0041 | [inventory-v1](architecture/0041-inventory-v1.md) | Inventario físico por revisión: metadata-only, paginado, planos físico/observable separados (#68) | Aceptada | Implementada en `main` (PR #91, hacia beta.17); sin MCP en v1 |
| 0042 | [sealed-export-v1](architecture/0042-sealed-export-v1.md) | Export sellado: AES-256-GCM con extra opcional `[sealed]`, adaptador externo de claves, fail-closed sin downgrade (#46) | Aceptada | Diseño pre-code aceptado por decisión del dueño (🔒 2026-08-21; once rondas R1–R11); implementada en beta.18 (PRs #93–#101). Detalle técnico en [refs/sealed-export-v1-appendix.md](architecture/refs/sealed-export-v1-appendix.md) (#95) |
| 0043 | [store-threat-model-v1](architecture/0043-store-threat-model-v1.md) | Modelo de amenazas del store: adversarios A1-A4, frontera declarada tamper-evidence≠tamper-proofness con evidencia experimental de reescritura consistente | Aceptada | Producida por tarjeta ankla-g1-g3 (2026-08-31); ronda adversarial fresca (APROBADO CON CORRECCIONES, 6 hallazgos corregidos en `bd4ba27`); 🔒 aceptada por decisión del dueño 2026-08-31 con anclaje externo de digest (protocolo anclajes/) |
| 0044 | [h1c-formalizacion-v1](architecture/0044-h1c-formalizacion-v1.md) | Formalización de H1c (independencia del verificador): formulación débil-con-anclaje decidida post-evidencia G-3/v4, con condiciones (C1)-(C3) y verificación activa ejecutable (`scripts/verificar_anclaje.py`) | Propuesta | Producida por tarjeta ankla-h1c-formalizacion-anclaje (2026-08-31); cierra la fila PR-5/§7.5 y la corrección [a] del análisis del mandato; pendiente ronda adversarial + decisión del dueño |
| 0045 | [adopcion-skevi](architecture/0045-adopcion-skevi.md) | Adopción formal del estándar de proceso Skevi: corpus copiado sin edición, gate propio reemplazado por `check_sizes.py`/`check_plans.py` de Skevi configurados vía `skevi-gate.json`, registro en `AGENTS.md` + `.skevi/`, gates en CI | Aceptada | Orden explícita del maintainer (2026-09-01); corpus pinneado a skevi @ `ee309bb`; implementada en rama `feat/adopcion-skevi`, vigente al merge |
| 0046 | [attest-local-signed-observation-v1](architecture/0046-attest-local-signed-observation-v1.md) | Atestación de observación local firmada (`attest`): receipts HMAC-SHA256 acuñados por el motor con whitelist fail-closed, nonce-addressing y binding vigente; convierte receipts verificados en autoridad `tool_observed` vía `write-authority-v2` | Aceptada | F0 adoptadas por orden del maintainer (2026-09-01); spike S0 proceed; ronda adversarial pre-code fix-and-retry absorbida (`planning/adr-0046-attest-precode-adversarial-2026-09-01.md`); S2 implementada (ed64994) y contrato bumped en beta.21 |

Resumen: **46 ADRs**, sin huecos; **43 aceptadas** y **3 propuestas**. No hay
ADRs rechazadas ni reemplazadas en el registro actual.

### Documentación normativa

- [`practicas-ingenieria.md`](practicas-ingenieria.md) — Prácticas de ingeniería (ronda adversarial pre-code, spike, ADR-antes-que-código, secuenciación, CI local).
- [`uso-diario.md`](uso-diario.md) — Referencia estable del consumidor: actualizar entre betas, desinstalar, comandos cotidianos y respaldo sellado.
- [`supervision-agente-externo.md`](supervision-agente-externo.md) — Protocolo experimental para operar y auditar un agente externo persistente, con diseño futuro de reactivación programada o por eventos.
- [`context-package.md`](context-package.md) — Guía de integración del bloque administrado.
- [`upgrade-agent-flow.md`](upgrade-agent-flow.md) — Flujo de actualización para agentes.
- [`write-policy-cli.md`](write-policy-cli.md) — CLI de escritura gobernada.
- [`sealed-export-guide.md`](sealed-export-guide.md) — Guía del perfil sellado `sealed-export/v1` (ADR-0042): uso, adaptador de claves, warnings y errores canónicos.
- [`mcp-readonly.md`](mcp-readonly.md) — Servidor MCP de sólo lectura.
- [`mathematical-foundations.md`](mathematical-foundations.md) — Fundamentos matemáticos.

### Schemas JSON

Los schemas normativos están bajo [`schemas/`](schemas/) y también embebidos
en el paquete (`an_kla/schemas/`). Se consultan con
`python -m an_kla schema list` / `schema show <name>`.
El contrato de objetos que completa ADR-0026 está en
[`refute-contract-v1.md`](refute-contract-v1.md).
El contrato ejecutable que completa ADR-0028 está en
[`compaction-contract-v1.md`](compaction-contract-v1.md).

### Benchmarks reproducibles

[`benchmarks/`](benchmarks/) conserva reportes interpretados ligados a digests;
el primer baseline es
[`retrieval-v2-reference-2026-08-08.md`](benchmarks/retrieval-v2-reference-2026-08-08.md).
Los reportes son evidencia experimental, no decisiones de ranking.

### Notas de release

[`releases/`](releases/) contiene las notas por etiqueta, en orden inverso
de publicación. Cumplen el rol de `CHANGELOG.md`.

La release documentada más reciente es
[`v0.1.0-beta.21`](releases/v0.1.0-beta.21.md), con su
[ronda adversarial](releases/v0.1.0-beta.21-adversarial.md); la anterior
con ronda cerrada es [`v0.1.0-beta.20`](releases/v0.1.0-beta.20.md).

### Planificación y respuestas históricas

[`planning/`](planning/) contiene documentos puntuales: respuestas a
revisiones externas (argos), planes de iteración, investigaciones de bugs.
No son evergreen; se conservan como histórico.

La iniciativa vigente de recuperación semántica está documentada en el
[plan de Fase 8](planning/fase-8-recuperacion-semantica-2026-08-09.md), su
[ronda adversarial documental](planning/fase-8-recuperacion-semantica-adversarial-2026-08-09.md)
y el subtrack opcional
[F8-E para atestación mediante Escrubery](planning/fase-8-escrubery-attestation-2026-08-09.md).

La política propuesta para evitar checkpoints obsoletos está en el
[plan de Fase 9](planning/fase-9-continuidad-obligatoria-2026-08-09.md) y su
[ronda adversarial documental](planning/fase-9-continuidad-obligatoria-adversarial-2026-08-09.md).
La reevaluación posterior a la ronda —continuidad frente a assurance, casos
`expertoGobernanza`/`adrc-python`, oportunidad y aceptación del usuario— vive en
la [nota de frontera de Fase 9](planning/fase-9-frontera-continuidad-assurance-2026-08-09.md).

El backlog abierto y su secuencia para trabajo con agentes están en el
[plan técnico de ejecución](planning/plan-ejecucion-backlog-agentes-2026-08-11.md),
acompañado por su
[ronda adversarial documental](planning/plan-ejecucion-backlog-agentes-adversarial-2026-08-11.md).

La ejecución más reciente del backlog prioritario (doce puntos con ronda
adversarial por punto, tres rondas de hito y acta final con las decisiones
pendientes del maintainer) es el
[plan 2026-08-20](planning/plan-backlog-2026-08-20.md), cerrado por el
[PR #85](https://github.com/kristhianmanue1/an-kla-memory/pull/85); su
priorización adversarial vive en
[`backlog-prioridades-adversarial-2026-08-20.md`](planning/backlog-prioridades-adversarial-2026-08-20.md)
y el cierre en
[`hito-final-adversarial-2026-08-20.md`](planning/hito-final-adversarial-2026-08-20.md).

La implementación de `subject_ref` v1 (issue #59, ADR-0033) se secuencia en
[plan técnico por fases](planning/issue-59-subject-ref-implementation-2026-08-11.md);
es historia de planificación, no una segunda fuente de estado decisional.
