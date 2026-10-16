# Ronda adversarial de la «Referencia rápida para agentes» (plantilla `0.1.0-beta.32`)

Rama `docs/contrato-referencia-agentes`, commit atacado `b8e0f00`. Ronda
obligatoria: cambia el contrato gestionado. Revisor de contexto fresco
(subagente `Explore`, sólo lectura) que actuó como agente nuevo en un
proyecto consumidor con sólo `AGENTS.md` + `AN-KLA.md`, usando
`.venv/bin/python` 3.12.

## Motivación (evidencia)

Sesiones reales recuperadas de Memmy: schemas descubiertos por prueba y
error (`schema write-proposal` inválido), digests recalculados a mano,
confusión entre decisión y outcome (`write` vs `commit`), drivers Python
para encadenar escrituras, instalaciones duplicadas, `pip` con shebang roto
y funciones de lectura omitidas. El contrato no citaba `retrieve`, `view`,
`inventory`, `startup-diagnostic`, `integration status`, `doctor` ni
`recover`, y `retrieve` sólo busca `facts` sin `--streams`.

## Decisión de la ronda: `fix-and-retry` (0 BLOCKER, 4 MAJOR, 7 MINOR)

La receta funcionó tal cual en el consumidor (fact, event y episode
encadenados, checkpoint, resume, verify).

| ID | Hallazgo | Corrección |
|---|---|---|
| MAJOR-1 | `view context` sale vacío para records sin `subject_ref` (todo lo escrito con la receta) | Fila: `inventory` para ids/estado; `view context` sólo con `record.subject_ref` y `subject namespace` |
| MAJOR-2 | «el commit responde `committed: true`» era incondicional; `full` con `model_derived` da `skip` | Prosa de `skip` → `committed: false` y misma `revision`; `full` requiere `tool_observed` |
| MAJOR-3 | Faltaban `invalid_write_planning_result` e `invalid_checkpoint_plan (planning.current_revision)` | Añadidos a la fila de plan obsoleto |
| MAJOR-4 | El test dejaba pasar 12 mutantes de deriva (abreviaturas de argparse, prosa no contrastada) | Test reescrito: flags exactos contra `build_parser()`, decisiones contra el enum de `write-decision-v1`, códigos de error contra el motor, y ejecución de cada afirmación de la prosa |
| MINOR-1 | `python3` de los ejemplos no se traducía en la sección | Nota de sustitución en «Intérprete» |
| MINOR-2 | `resume` no admite `--streams` | Anotado en la fila |
| MINOR-3 | Events, episodes y supersede no explicados | Párrafo tras el JSON (verificado por el revisor) |
| MINOR-4 | pip, `adopt-baseline` y README podían leerse como permiso | Condicionados a autorización del usuario/operador |
| MINOR-5 | Marcador del checkpoint ambiguo | `<REV-vigente>` = `current_revision` del plan; no escribir entre plan y commit |
| MINOR-6 | Texto de beta.32 cambiado sin bump (ya en `origin/main` desde `fcdb776`) | Aceptado: ningún tag lo contiene y la política exige tags exactos; precedente de beta.25. Declarado en el PR |
| MINOR-7 | Lote `write-proposal-v2` no citado | No aplicado: no aparece en `schema list`, así que un agente no puede verificar su forma; queda como límite |

## Verificación de las correcciones

Los 15 mutantes de deriva fallan con el test nuevo (los 12 supervivientes
de la ronda más 3 de control): flag inexistente en tabla y en bash,
abreviaturas, schema, comando o subcomando mal escritos, valores de
decisión, `committed`, código de error inexistente, afirmación falsa sobre
`--streams` y sobre `full`, stream inválido en el JSON.

## Límites declarados

- `write-proposal-v2` (lote) no se documenta hasta que `schema show` lo
  exponga.
- Instalar desde `main` entre `fcdb776` y esta corrección deja el bloque
  beta.32 como modificado: reinstalar el contexto. La política exige tags
  exactos.

## Decisión

Pendiente de re-verificación de las correcciones por el mismo revisor.
