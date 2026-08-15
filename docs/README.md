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
decisional, actualizado al 2026-08-12. `Aceptada` no implica que toda extensión
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
| 0020 | [context-diagnostics-in-write-result](architecture/0020-context-diagnostics-in-write-result.md) | Salud del contrato en el resultado de escritura | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0021 | [verified-at-freshness-v1](architecture/0021-verified-at-freshness-v1.md) | `verified_at` autodeclarado y frescura computada en lectura | Aceptada | Publicada en [beta.9](releases/v0.1.0-beta.9.md) |
| 0022 | [store-project-identity-v1](architecture/0022-store-project-identity-v1.md) | Identidad lógica separada de proyecto y store | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0023 | [governed-checkpoint-handoff-v2](architecture/0023-governed-checkpoint-handoff-v2.md) | Checkpoint exacto y handoff gobernado | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0024 | [commit-outcome-v2](architecture/0024-commit-outcome-v2.md) | Resultado transaccional y durabilidad explícita | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0025 | [retrieval-evaluation-v2](architecture/0025-retrieval-evaluation-v2.md) | Benchmark de ranking y presupuesto sin cambiar retrieval | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0026 | [governed-refute-v1](architecture/0026-governed-refute-v1.md) | Refutación gobernada, auditable y sin sucesor | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0027 | [verifiable-export-restore-v1](architecture/0027-verifiable-export-restore-v1.md) | Export/backup verificable y restore fail-closed | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0028 | [governed-compaction-v1](architecture/0028-governed-compaction-v1.md) | Corte de epoch, tombstones y archivo verificable | Aceptada | Publicada en [beta.11](releases/v0.1.0-beta.11.md) |
| 0029 | [derived-semantic-retrieval-v1](architecture/0029-derived-semantic-retrieval-v1.md) | Índice semántico derivado y recuperación híbrida opt-in | Propuesta | Sin implementación ni proveedor autorizado |
| 0030 | [milestone-checkpoint-obligation-v1](architecture/0030-milestone-checkpoint-obligation-v1.md) | Obligación gobernada de continuidad al cerrar hitos | Propuesta | En reevaluación; sin cambio de contrato ni código |
| 0031 | [agent-owned-memory-host-managed-v1](architecture/0031-agent-owned-memory-host-managed-v1.md) | Memoria del agente con alcance de proyecto y perfil host-managed | Aceptada | Reconocido host-managed como perfil soportado; G1 (observabilidad) no iniciado |
| 0032 | [derived-contextual-view-v1](architecture/0032-derived-contextual-view-v1.md) | Vista contextual vigente derivada, non-authoritative, sobre sustrato de afirmaciones | Aceptada | G-SUBJECT publicado en [beta.12](releases/v0.1.0-beta.12.md); G-VIEW publicado en [beta.13](releases/v0.1.0-beta.13.md) |
| 0033 | [subject-ref-v1](architecture/0033-subject-ref-v1.md) | Identidad contextual estable `subject_ref`, namespace derivado de project identity y binding bajo lock | Aceptada | Publicada en [beta.12](releases/v0.1.0-beta.12.md) |
| 0034 | [derived-context-view-contract-v1](architecture/0034-derived-context-view-contract-v1.md) | Contrato G-VIEW v1: vista contextual determinista, non-authoritative, paginada y recuperable | Aceptada | CORE+CLI+MCP+CAP publicados en [beta.13](releases/v0.1.0-beta.13.md); auditoría REL `proceed` |
| 0035 | [explicit-project-context-baseline-adoption-v1](architecture/0035-explicit-project-context-baseline-adoption-v1.md) | Adopción explícita de baseline project-owned sin debilitar target drift | Propuesta | Sin implementación; issue #45 |

| 0036 | [startup-memory-diagnostic-v1](architecture/0036-startup-memory-diagnostic-v1.md) | Diagnóstico de arranque read-only por ejes observables totales, sin enum de estados compuestos | Propuesta | Sin implementación; issue #76, Fase 0 en `main`; ronda adversarial `fix-and-retry` absorbida |

Resumen: **36 ADRs**, sin huecos; **32 aceptadas** y **4 propuestas**. No hay
ADRs rechazadas ni reemplazadas en el registro actual.

### Documentación normativa

- [`practicas-ingenieria.md`](practicas-ingenieria.md) — Prácticas de ingeniería (ronda adversarial pre-code, spike, ADR-antes-que-código, secuenciación, CI local).
- [`supervision-agente-externo.md`](supervision-agente-externo.md) — Protocolo experimental para operar y auditar un agente externo persistente, con diseño futuro de reactivación programada o por eventos.
- [`context-package.md`](context-package.md) — Guía de integración del bloque administrado.
- [`upgrade-agent-flow.md`](upgrade-agent-flow.md) — Flujo de actualización para agentes.
- [`write-policy-cli.md`](write-policy-cli.md) — CLI de escritura gobernada.
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
[`v0.1.0-beta.14`](releases/v0.1.0-beta.14.md), con su
[ronda adversarial](releases/v0.1.0-beta.14-adversarial.md).

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

La implementación de `subject_ref` v1 (issue #59, ADR-0033) se secuencia en
[plan técnico por fases](planning/issue-59-subject-ref-implementation-2026-08-11.md);
es historia de planificación, no una segunda fuente de estado decisional.
