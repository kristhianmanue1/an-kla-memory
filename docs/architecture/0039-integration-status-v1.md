# ADR-0039: contrato observable de la integración (G1)

- **Estado:** Aceptada
- **Implementación:** CORE+CLI+SCHEMAS+CAP en
  `plan/backlog-prioridades-2026-08-20` (#55, post-beta.15)
- **Fecha:** 2026-08-20
- **Decide sobre:** cómo se observa el modo de integración de AN-KLA
  (agent-owned vs host-managed de ADR-0031) sin instalar contexto
  gestionado ni cambiar el formato físico; no decide hooks (#56/G2),
  `store_root` externo (#57/G3) ni multi-scope (#58/G4)

## Contexto

ADR-0031 reconoce contractualmente dos perfiles — `agent-owned/v1`
(el agente opera la memoria directamente) y `host-managed/v1` (el host
opera el ciclo de vida) — pero nada los hace observables: un operador
no puede preguntar "¿qué hay integrado aquí?". ADR-0031 vetó
pre-congelar el enum de G1: la lista de cuatro estados de #54 no
contemplaba combinaciones reales ni la separación store/contexto.

## Decisión

**Comando read-only `integration status` con schema
`an-kla/integration-status-v1`, compuesto por ejes observables
independientes — nunca un enum compuesto** (lección de ADR-0036):

```json
{
  "schema": "an-kla/integration-status-v1",
  "store": {
    "store_presence": "absent",
    "store_integrity": "not_evaluated",
    "integrity_detail": "store_not_present",
    "identity": {"evaluated": false, "identity_status": null,
                 "root_relocated": null},
    "repo_context": "main_checkout",
    "external_memory_evaluated": false
  },
  "managed_context": {
    "target": "AGENTS.md",
    "presence": "absent",
    "template_version": null,
    "context_schema": "an-kla/context-status/v1",
    "ok": false,
    "diagnostics": [],
    "warnings": []
  },
  "integration": {
    "supported_profiles": ["agent-owned/v1", "host-managed/v1"],
    "observed_profile": "unspecified",
    "agent_binding": "unverified",
    "sharing_boundary": "filesystem-access/unverified",
    "host_hooks_evaluated": false
  }
}
```

Reglas congeladas:

1. **`store` re-expone los ejes de ADR-0036 verbatim** (presencia,
   integridad, identidad, contexto de repo). Sin redefinición.
2. **`managed_context` re-expone `context-status/v1`** (`installed` →
   presencia; `diagnostics`/`warnings` verbatim). El significado de
   `context-status/v1.ok` no cambia: vive en su bloque. La
   re-exposición es por selección de ejes, no copia completa: se
   omiten `current_template_version` y claves puramente internas.
   Cuando el target no puede observarse (symlink, permisos), el eje
   reporta `presence: "unreadable"` + `observation_error` con código
   estable y exit 0: la ilegibilidad es estado diagnosticable y la
   superficie de error nunca filtra rutas absolutas (§11.1).
3. **`integration` declara lo observable y lo no verificable, sin
   fingir**: `observed_profile: "unspecified"` porque **nada en disco
   distingue hoy los dos perfiles** (los hooks que lo harían son G2);
   `agent_binding: "unverified"` y
   `sharing_boundary: "filesystem-access/unverified"` permanentes en
   v1 (criterios de aceptación de #55: no prometer privacidad);
   `host_hooks_evaluated: false` hasta que G2 (#56) exista.
4. **Éxito cuando se pudo diagnosticar** (exit 0), incluso sin store ni
   contexto: la ausencia es un estado, no un error (ADR-0036).
5. **Read-only**: no crea store, no muta revisión, no adquiere lock de
   escritura. El eje integridad materializa `.reader-gate` como todo
   lector (documentado en ADR-0036). No ejecuta `git` más allá del eje
   `repo_context` heredado.
6. **`capabilities()` aditivo** declara el comando, el schema y que
   `observed_profile` es `unspecified` en v1.

## Huella `.an-kla/` (documental)

La huella física sigue siendo la ya conocida: `.an-kla/memory/**` +
`.reader-gate` al leer; `.gitignore` del proyecto la excluye. Este ADR
no añade archivos. Verificación operacional:
`git status --porcelain` en un checkout limpio tras `init` +
`integration status` no muestra cambios versionados.

## Por qué ejes y no el enum de cuatro estados de #54

Un enum compuesto (`installed/host-managed/…`) colapsaría tres planos
independientes (store, contexto gestionado, modo de integración) en un
solo valor y reproduciría el problema que ADR-0031 detectó: combinaciones
reales como "store íntegro + contexto ausente + perfil no especificado"
no tienen representación. Los ejes la tienen todos.

## Límites

- `observed_profile` no distingue perfiles en v1: es honestidad, no
  carencia oculta; G2 (#56) define qué observación cambiaría el valor.
- No implementa hooks, no reubica el store, no aísla por agente/scope.
- Sin MCP: superficie de operador local; MCP read-only existente no
  cambia.
- Quirk heredado de ADR-0036 (registrado aquí para su ADR): cuando
  `store_presence: "unreadable"`, `integrity_detail` reporta
  `"store_not_present"`.

## Referencias

- ADR-0031 (perfiles y G0-G4); ADR-0036 (ejes observables, su lección
  y sus ejes re-expuestos); ADR-0009 (contexto gestionado);
  issues #55, #56, #57, #58, #54.
