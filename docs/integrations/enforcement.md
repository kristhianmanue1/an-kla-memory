# Receta: hacer que los agentes consuman AN-KLA (inyección + gate)

**Estado:** receta de piloto (H8 en escrubery, 2026-08-22) — no vinculante, no
modifica el CLI de an_kla ni sus contratos. **Problema que resuelve:** hoy el
consumo de memoria es L1 (el prompt lo pide; el modelo decide). Esta receta lo
sube a L2/L3 usando superficies nativas de los CLIs.

## Las tres piezas

1. **Inyección al arranque (L2)** — la memoria se materializa en el contexto; el
   modelo no decide leerla: nace con ella.
   - claude-code: hook `SessionStart` (stdout con exit 0 entra al contexto).
   - opencode: **sin vía documentada** para inyectar al contexto al inicio
     (limitación del piloto; `experimental.session.compacting` solo cubre compactación).
2. **Gate de escritura (L3)** — ninguna sesión escribe sin que AN-KLA haya corrido
   en ella (garantía de ejecución, no de lectura).
   - claude-code: hook `PreToolUse` matcher `Write|Edit`, exit 2 bloquea.
   - opencode: plugin `tool.execute.before` con `throw` (documentado: ejemplo
     oficial ".env protection"). **`input.tool` es el TOOL-ID, no el permiso**:
     el filtro debe aceptar `edit`, `write` Y `patch` como tools distintas
     (hallazgo HIGH-1 de ronda adversarial: filtrar solo 'edit' dejaba pasar
     la creación de archivos).
   - Semántica lazy: sin sello → bloquea la 1ª escritura, corre `resume` AHORA,
     sella `lazy_inject`; el reintento pasa. Distinción auditable entre
     "inyectado al arranque" y "remediado a medias".
3. **Auditoría post-hoc (L3)** — un log JSONL por evento (`session_start_inject`,
   `session_created_exec`, `gate_pass`, `lazy_inject`, `degraded`) alimenta un
   reporte: % de sesiones que escribieron con memoria previa.

## Fail-open declarado (lección de degradación)

Si `an_kla resume` falla: sello `degraded`, la sesión continúa y el gate deja
escribir con aviso. Racional: AN-KLA caído no debe paralizar el trabajo; la
degradación queda visible en el log (nunca silenciosa).

## Implementación de referencia

- Scripts bash: `scripts/hooks-spike/ankla_{session_start,pre_tool_use,auditoria}.sh`
  en escrubery (H8, 2026-08-22; fixes de ronda adversarial en el commit
  siguiente: tool-ids write/patch, mkdir del gate-dir, append atómico del log,
  sello inválido fail-closed, --limpiar-test implementado, advertencia de
  vigencia/staleness en la inyección).
- Hooks claude-code: `.claude/settings.json` (proyecto).
- Plugin opencode: `.opencode/plugin/ankla_gate.ts` (misma carpeta de sellos/log).
- Sellos por sesión: `var/ankla-gate/<session_id>.seal`; log: `var/ankla-gate/log.jsonl`.

## Lo que esta receta NO es (no-claims)

- **Escrituras vía Bash no están gateadas** (matcher `Write|Edit` en
  claude-code; `edit/write/patch` en opencode): `echo >`, `sed -i`, `tee` pasan
  libremente. Ampliar el matcher es posible pero multiplica falsos positivos;
  decisión de alcance, no descuido (hallazgo MED-1 adversarial).
- **El sello es un archivo local**: cualquier proceso con permisos puede
  fabricar un sello 'ok' (fuerza real: "existe un archivo con un string").
  JSON inválido se trata como ausente (fail-closed, fix MED-2), pero la
  fabricación deliberada queda dentro del "L3 evadible". Sin TTL: los sellos
  no expiran por sesión nueva.
- No garantiza comprensión: la inyección garantiza presencia en el contexto, no
  atención (por eso existe la pieza 3).
- No es L4: hooks y settings son editables/evadibles; es L3 (barrera mecánica
  local), igual que el gate commit-msg de escrubery.
- La garantía del gate es "AN-KLA se ejecutó en la sesión antes de escribir";
  en el caso lazy, la salida NO entró al contexto (solo se ejecutó).
- El checkpoint interno puede estar desactualizado (así ocurrió en el piloto:
  rev 31, era v0.3.0): la inyección declara "dato no confiable" y apunta al
  canónico del proyecto. Actualizar el checkpoint es flujo propio de AN-KLA
  (`checkpoint plan/commit`), no de esta receta.

## Pendiente del host (relacionado con issue #56)

- Inyección al contexto en opencode: requiere superficie del host (o documentar
  `session.created` + contexto). Cuando exista, la pieza 1 deja de ser exclusiva
  de claude-code.
- `sessionID` en `tool.execute.before` de opencode: asumido por input (con
  fallback); verificar contra tipos oficiales en el primer e2e real.
