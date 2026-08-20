# ADR-0038: `source_state` con perfil `git/v1`

- **Estado:** Aceptada
- **Implementación:** CORE+SCHEMAS+CAP en `plan/backlog-prioridades-2026-08-20`
  (post-beta.15)
- **Fecha:** 2026-08-20
- **Decide sobre:** cómo liga un checkpoint el estado del repositorio que
  describe; no decide ejecutar Git desde el CLI, hooks del host (#56) ni
  verificación automática contra el repositorio

## Contexto

`working-state-v2` sólo admite `source_state.profile: none/v1` con
`head`/`branch`/`dirty_digest` en `unavailable`: por schema, un
checkpoint no puede declarar el commit que describe. La consecuencia
medida en #79: el desfase entre memoria y repositorio es indetectable
desde el propio checkpoint (el de la revisión 29 describía un estado de
dos días antes con integridad `verified`). La práctica actual (SHA en
`evidence`, como hace este repo) mezcla provenance del repositorio con
evidencia arbitraria y no es consultable como eje.

`checkpoint_policy.py` rechaza hoy `git/v1` con
`tool_observed_requires_adapter`: la postura era que sólo un adaptador
del host podría observar Git.

## Decisión

**Evolutionar `working-state-v2` (aditiva) con un segundo perfil
`source_state` llamado `git/v1`, cuyos valores son exclusivamente
`caller_asserted`:**

```json
"source_state": {
  "profile": "git/v1",
  "head":       {"value": "3f9c…(40 o 64 hex)", "provenance": "caller_asserted"},
  "branch":     {"value": "plan/backlog-…",      "provenance": "caller_asserted"},
  "dirty_digest": {"value": null,                "provenance": "caller_asserted"}
}
```

Reglas congeladas:

1. **El caller observa Git, no el CLI.** AN-KLA no ejecuta `git` al
   planificar checkpoints: el caller (agente/host) obtiene
   `rev-parse HEAD`, la branch y un digest del árbol sucio por sus
   medios, y los declara. Sin subprocesos, sin dependencia de PATH.
2. **`caller_asserted`, nunca `tool_observed`, desde JSON.** Elegir
   `git/v1` es declarar observación propia. Fabricar `tool_observed`
   sigue siendo imposible sin adaptador (regla invariante del
   proyecto). El cambio de postura es honesto sobre lo que es: un dato
   autodeclarado más, ahora con eje propio y consultable.
3. **Forma de los campos bajo `git/v1`:** `head` es `caller_asserted`
   con object-id hex completo (40 SHA-1 o 64 SHA-256); `branch` es
   `caller_asserted` string o `null` (HEAD detached); `dirty_digest` es
   `caller_asserted` string opaco (digest del árbol sucio computado por
   el caller) o `null` (árbol limpio). Dentro de `git/v1` no se admite
   `unavailable`: si el caller no pudo observar, el perfil correcto es
   `none/v1`.
4. **`none/v1` intacto.** Mismos tres campos `unavailable`; los
   documentos válidos hoy siguen siéndolo byte a byte.
5. **`policy_fingerprint` cambia**: `_CONFIG.source_profiles` pasa a
   `["none/v1", "git/v1"]`. Evolución de perfil permitida por ADR-0007;
   el fingerprint nuevo es el que liga los checkpoints creados después.
6. **Sin verificación, sin vigencia.** `git/v1` hace detectable el
   desfase (checkpoint declara su SHA; el consumidor lo compara con el
   repositorio), no lo resuelve ni certifica correspondencia. La memoria
   sigue siendo dato no confiable: un HEAD autodeclarado falso no
   eleva autoridad; los consumidores revalidan contra Git.

## Por qué caller_asserted y no sólo adaptador

La alternativa (mantener `git/v1` como clase `tool_observed` pura) deja
el problema intacto hasta que #56 exista: ningún checkpoint real podría
ligarse al SHA, que es exactamente el estado actual. `caller_asserted`
ya es la clase de todo el resto del working state (incluidos SHAs en
evidence): añadir el eje no introduce una clase de confianza nueva,
sólo deja de mentir diciendo "no evaluado" cuando el caller sí observó.
El riesgo de fabricación no sube: fabricar un SHA en `evidence` ya era
posible y es equivalente; la contrapartida es que ahora hay un lugar
estructurado, validado por forma, donde esperarlo — y donde un
consumidor puede detectar que falta.

## Supersede normativo del nombre `git/v1`

ADR-0023 (§ perfil reservado) condicionaba `git/v1` a un digest
porcelain congelado con `observed_at` observado por adaptador, y
ADR-0030 §4 lo reservaba para `working-state-v3` con `tool_observed`.
**Esta decisión supersede esa reserva**: el issue #79 pide
explícitamente `git/v1` como ligadura caller_asserted del checkpoint al
SHA que describe, y esa semántica es la publicada aquí. La variante
por-adaptador (observación live, digest porcelain-v2, `observed_at`)
queda disponible para un perfil futuro con otro nombre (p. ej.
`git-observed/v1`) cuando #56 exista; ADR-0030 §4 debe revisarse en su
reevaluación a la luz de esto. Filas 0023/0030 del registro anotadas.

## Límites

- No hay detección de dirty-tree en runtime ni recálculo de
  `dirty_digest` por AN-KLA: el caller define su digest y su método.
- No hay comparación automática checkpoint↔repositorio (ningún comando
  la exige hoy); el eje habilita a consumidores y a un futuro hook (#56).
- Un checkpoint de repositorio no Git sigue usando `none/v1`.
- **Evolución unidireccional**: un checkpoint con `git/v1` exige un
  binario ≥ esta decisión para `resume`/`show` (un binario anterior lo
  rechaza con `tool_observed_requires_adapter`); no hay downgrade.
- `branch`/`dirty_digest` son strings caller_asserted sin cota de forma
  propia (mismo nivel de confianza que el resto del working state; tope
  global de 64 KiB del estado).
- Deuda preexistente diferida: el patrón `digest` del schema tolera `\n`
  final bajo semántica ECMA (`$`); el runtime es fail-closed
  (`bare_digest` rechaza longitudes incorrectas), por lo que jamás
  aprueba un write; corrección diferida al tocar ese schema por otra
  causa. El patrón de `head` de esta decisión ya es inmune
  (`(?![\s\S])`).

## Alternativas descartadas

- **`working-state-v3`**: rompe compatibilidad sin necesidad; la
  evolución es aditiva (rama nueva del oneOf).
- **`tool_observed` puro**: bloqueado por la inexistencia de adaptador
  (#56) y no resuelve nada que `caller_asserted` + revalidación no
  resuelvan.
- **SHA en `evidence` como convención**: ya probado en este repo;
  mezcla ejes y no es validado por forma.

## Referencias

- Issue #79; ADR-0023 (checkpoint handoff v2); ADR-0007 (evolución de
  perfil y policy_fingerprint); ADR-0036 (detección de arranque, eje
  ortogonal: presencia de memoria, no su desfase); #56 (hooks).
