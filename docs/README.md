# Documentación de AN-KLA Memory

Esta carpeta contiene la documentación evergreen del proyecto. Para hallazgos
puntuales, planificación y respuestas a revisiones externas, ver
[`planning/`](planning/).

## Índice

### Decisiones de arquitectura (ADRs)

Los ADRs viven en [`architecture/`](architecture/) y siguen una numeración
secuencial. Cada uno documenta una decisión arquitectónica irreversible o
diffícil de revertir.

| # | ADR | Tema |
|---|---|---|
| 0001 | [revision-commit](architecture/0001-revision-commit.md) | Revisión content-addressed y `CURRENT` |
| 0002 | [alpha-scope](architecture/0002-alpha-scope.md) | Alcance alfa |
| 0003 | [mcp-worktree-and-safety-gates](architecture/0003-mcp-worktree-and-safety-gates.md) | MCP y compuertas de seguridad |
| 0004 | [index-reference](architecture/0004-index-reference.md) | Referencia de índice (FTS5) |
| 0005 | [mathematical-alignment](architecture/0005-mathematical-alignment.md) | Alineación matemática |
| 0006 | [context-assembly-v1](architecture/0006-context-assembly-v1.md) | Ensamblado de contexto con presupuesto |
| 0007 | [write-policy-v1](architecture/0007-write-policy-v1.md) | Política de escritura gobernada |
| 0008 | [cost-model-v1](architecture/0008-cost-model-v1.md) | Modelo de costos (bytes UTF-8) |
| 0009 | [managed-agent-context-v1](architecture/0009-managed-agent-context-v1.md) | Contexto administrado para agentes |
| 0010 | [agent-first-public-contracts](architecture/0010-agent-first-public-contracts.md) | Contratos públicos agent-first |
| 0011 | [governed-agent-upgrade](architecture/0011-governed-agent-upgrade.md) | Upgrade gobernado del proyecto |
| 0012 | [update-check-v1](architecture/0012-update-check-v1.md) | Verificación no bloqueante de versiones |
| 0013 | [multi-stream-retrieval](architecture/0013-multi-stream-retrieval.md) | Recuperación multi-stream opt-in |
| 0014 | [index-v2-multistream](architecture/0014-index-v2-multistream.md) | Índice FTS5 multi-stream |
| 0015 | [excluded-detail-v1](architecture/0015-excluded-detail-v1.md) | Transparencia en exclusiones |
| 0016 | [auto-reindex-post-commit](architecture/0016-auto-reindex-post-commit.md) | Reindexado best-effort tras commit |
| 0017 | [target-drift-transparency](architecture/0017-target-drift-transparency.md) | Transparencia de target drift en upgrade (Propuesta) |

### Documentación normativa

- [`context-package.md`](context-package.md) — Guía de integración del bloque administrado.
- [`upgrade-agent-flow.md`](upgrade-agent-flow.md) — Flujo de actualización para agentes.
- [`write-policy-cli.md`](write-policy-cli.md) — CLI de escritura gobernada.
- [`mcp-readonly.md`](mcp-readonly.md) — Servidor MCP de sólo lectura.
- [`mathematical-foundations.md`](mathematical-foundations.md) — Fundamentos matemáticos.

### Schemas JSON

Los schemas normativos están bajo [`schemas/`](schemas/) y también embebidos
en el paquete (`an_kla/schemas/`). Se consultan con
`python -m an_kla schema list` / `schema show <name>`.

### Notas de release

[`releases/`](releases/) contiene las notas por etiqueta, en orden inverso
de publicación. Cumplen el rol de `CHANGELOG.md`.

### Planificación y respuestas históricas

[`planning/`](planning/) contiene documentos puntuales: respuestas a
revisiones externas (argos), planes de iteración, investigaciones de bugs.
No son evergreen; se conservan como histórico.
