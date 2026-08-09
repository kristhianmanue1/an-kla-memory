# Spike: identidad, resultado de commit y durabilidad — 2026-08-08

## Objetivo

Verificar las premisas de ADR-0022 y ADR-0024 contra el camino real antes de
implementar. Este spike no autoriza mutaciones de formato por sí mismo.

## Evidencia del código actual

Orden observado en `_commit_locked()`:

1. journal `prepared` sólo con parent;
2. segmentos/checkpoint/manifest;
3. ref-log `intent` con candidato;
4. CAS de CURRENT y `_replace_current(candidate)`;
5. journal `committed`;
6. ref-log `observed_commit`, cuyo `OSError` se descarta.

Consecuencias reproducibles:

- si falla el paso 5, CURRENT ya puede ser candidato pero el caller recibe
  `OSError` y el journal queda `prepared` sin candidato;
- `recover()` reporta ese journal pendiente, pero no reconcilia su txid contra
  el manifest CURRENT;
- si falla el paso 6, el caller recibe éxito sin saber que audit quedó
  incompleto;
- `_fsync_directory()` retorna silenciosamente si `os.open(directory)` falla,
  aunque el perfil POSIX promete fsync-dir.

## Identidad

`MemoryStore.__init__()` sólo resuelve `project_root` y concatena
`.an-kla/memory`; no existe ancla lógica. El manifest `revision-v1` no contiene
identidad. Por tanto path, clone, worktree, relocación y restore son hoy
indistinguibles.

La separación project/store evita dos falsos equivalentes:

- misma ruta no implica mismo proyecto;
- ruta distinta no implica proyecto distinto.

El enlace content-addressed debe cubrir el store identity sin incorporar la
ruta actual. Legacy debe seguir legible y requerir adopción sólo al mutar.

## Restricción estructural

`an_kla/store.py` tiene 798 líneas frente al límite duro de 800. Antes de añadir
identidad/outcome se extraerán primitives a módulos pequeños. La extracción debe
ser mecánica, con tests verdes antes y después, y sin cambiar el formato de
ADR-0001.

## Matriz de fault injection prevista

| Punto | CURRENT esperado | Clasificación |
|---|---|---|
| primer journal falla | parent | runtime `recorded=false`; inspect posterior `outcome_unknown` |
| prepared/objetos/manifest/intent antes de receipt | parent | `durability_incomplete` |
| candidate receipt completo | parent | `not_committed`, candidate `orphan` |
| replace antes de mover | parent | `not_committed` |
| replace movió, fsync-dir/receipt falla | candidate | `durability_incomplete` |
| relectura CURRENT falla | desconocido | `outcome_unknown` |
| journal committed falla | candidate | `committed_audit_incomplete` |
| observed ref-log falla | candidate | `committed_audit_incomplete` |

El harness parcheará primitives individuales, no reemplazará todo
`_commit_locked()`. Después de cada fallo inspeccionará bytes reales, receipts
positivos y cadena histórica, y ejecutará un retry para probar convergencia. La
matriz completa cruza punto × `EIO|ENOSPC|truncado` × candidato
`current|ancestor|orphan` × journal `válido|ausente|corrupto`, además de errores
de cleanup/unlock que no deben enmascarar el primario.

## Secuencia recomendada

1. ronda adversarial de los tres ADRs y este spike;
2. extracción mecánica de primitives, CI, sin cambio de formato;
3. outcome/journal v2, fsync estricto y fault injection completo;
4. identidad bootstrap/adopción sobre esas primitives;
5. checkpoint/handoff exacto al final.

## Resultado

La ambigüedad post-CURRENT es real. Cinco pasadas cerraron txid, receipts, fsync,
bootstrap, provenance, replay y consistencia de revisión. Retry v5:
**proceed**; queda habilitada la implementación en orden ADR-0024 → ADR-0022 →
ADR-0023, cada fase con fault injection antes de completarse.
