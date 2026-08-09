# ADR-0022: identidad de proyecto y store v1

## Estado

Aceptada e implementada localmente el 2026-08-08 por autorización del roadmap
del maintainer. Diseño e implementación cerraron sus rondas adversariales en
`proceed`; la implementación se ejecutó después de ADR-0024.

## Contexto

Hoy `MemoryStore(project_root)` deriva el store únicamente de una ruta resuelta.
Dos proyectos pueden apuntar accidentalmente al mismo árbol, una copia puede
parecer el original y ninguna revisión liga de forma verificable el store a una
identidad lógica. La ruta absoluta tampoco sirve como identidad: cambia al
mover un proyecto, restaurar un backup o usar otro worktree.

La identidad debe evitar mezcla accidental sin convertir una ruta local en
autoridad, sin inventar identidad para stores legacy y sin volver inválida una
revisión sólo porque el árbol se reubicó.

## Decisión

Se separan dos objetos canónicos:

```json
{
  "schema": "an-kla/project-identity-v1",
  "project_uuid": "uuid",
  "created_by_version": "0.1.0b9"
}
```

ubicado en `.an-kla/project-identity.json`, y:

```json
{
  "schema": "an-kla/store-identity-v1",
  "store_uuid": "uuid",
  "project_uuid": "uuid",
  "project_identity": "sha256:<digest>",
  "canonical_project_root_at_init": "/ruta/historica",
  "created_by_version": "0.1.0b9"
}
```

ubicado en `.an-kla/memory/identity.json`. Ambos usan JSON canónico, claves
exactas, UUID minúsculo canónico y escritura atómica durable.

`canonical_project_root_at_init` es sólo diagnóstico histórico. No concede
autoridad y no se modifica al reubicar el árbol. La identidad lógica es la
igualdad de `project_uuid`; `store_uuid` distingue stores del mismo proyecto.

### Enlace verificable

Al inicializar un store nuevo se escribe además el objeto inmutable
`identities/sha256/<digest>.json`. `project_identity` cubre los bytes canónicos
exactos de `project-identity-v1`; así el store no liga sólo el UUID. Toda
revisión nueva incluye:

```json
"store_identity": "sha256:<digest>"
```

El digest cubre el objeto `store-identity-v1`, no la ruta actual. Lectores
aceptan revisiones legacy sin el campo. Después de adopción, el primer hijo
nuevo ya contiene el enlace; no se reescriben revisiones históricas.

### Orden de verificación

Los mutadores ordinarios realizan:

1. preflight de ambos archivos antes del lock;
2. adquisición del lock del store objetivo;
3. segunda lectura y comparación byte a byte bajo lock;
4. validación de `project_uuid`, `store_uuid` y del digest que entrará al
   manifiesto;
5. sólo entonces crea journal u objetos.

Cambiar identidad entre preflight y lock falla con
`store_identity_changed`. Un `project_uuid` distinto falla con
`project_identity_mismatch`. Archivos inválidos o incompletos fallan cerrados.

`init` y `identity adopt` son excepciones explícitas: necesariamente comienzan
sin identidad completa y usan el protocolo bootstrap siguiente, no el preflight
ordinario.

### Bootstrap convergente

Init/adopción adquieren primero `.an-kla/.identity.lock`. El primer proceso crea
con `O_EXCL` un intent canónico durable en `.an-kla/identity-intent.json` con
operation, UUIDs candidatos, bytes exactos de ambos archivos y, para adopción,
CURRENT observado. El intent es el único punto que elige UUID; procesos
concurrentes y retries deben reutilizarlo, nunca generar otro candidato.

Bajo ese lock se adquiere después, una sola vez, el lock del store; éste es el
orden global y nunca se invierte. El orden de publicación es:

1. crear/releer intent; si existe, validar shape y operation;
2. escribir el objeto inmutable store-identity;
3. escribir `memory/identity.json`;
4. escribir `project-identity.json`;
5. releer los tres bytes y marcar el intent `identities_ready`;
6. para init nuevo, crear/reconciliar la revisión raíz ya ligada al digest con
   la máquina bootstrap de ADR-0024, sin volver a adquirir el lock;
7. sólo si la raíz es current/ancestor y tiene receipt durable, marcar el intent
   `complete`; adopción, cuyo CURRENT ya existía, pasa de `identities_ready` a
   `complete` sólo tras revalidar ese CURRENT y crear un receipt durable que
   cubra intent, objeto inmutable y ambos archivos identity bajo ambos locks.

Bootstrap/adopción retorna `an-kla/identity-operation-result-v1` con claves
exactas `schema`, `operation=initialize|adopt|repair`, `intent_sha256`,
`identity_state`, `current_observed`, `durability_state`, `receipt` y
`error_code`. Los últimos tres aceptan null según outcome. Este resultado no
usa authority/committed de ADR-0024; la revisión raíz, cuando aplica, incluye
por separado su `commit-outcome-v2`.

La evidencia de identidad tampoco reutiliza el receipt transaccional. Vive en
`.an-kla/identity-receipts/sha256/<digest>.json` y tiene claves exactas:
`schema=an-kla/identity-durability-receipt-v1`,
`operation=initialize|adopt|repair`, `intent_sha256`, `current_observed`,
`predecessor_receipt` y `protected`. Current puede ser null sólo antes de raíz;
predecessor es digest o null. Protected usa la misma shape
path/operation/content_sha256 de ADR-0024, pero paths relativos al project root,
ordenados y limitados al intent, immutable identity, dos archivos live y sus
directorios contenedores necesarios para publicar create/replace. Se
crea sólo después de sus fsync/fsync-dir exitosos. Repair liga el último receipt
si existe o null si no existe; su intent digest, no un txid/candidate, fija el
binding.

Los archivos se crean con semántica create-only o se aceptan sólo si son
byte-idénticos al intent; nunca se sobreescribe un objeto «válido» diferente. Una
diferencia falla `identity_bootstrap_conflict`; no se sobreescribe ni limpia de
forma automática. Crash después de cualquier paso deja un estado resumible por
`init`/`identity adopt` o por `identity repair --plan <mismo intent>`. El intent
completo se conserva como evidencia; no es autoridad de revisiones.

`identity status` clasifica `absent`, `intent_only`, `store_only`,
`project_only`, `partial_consistent`, `identities_ready_root_pending`,
`complete`, `legacy_unadopted` o `conflict`. Para init, archivos completos con
CURRENT ausente o no reconciliado son `identities_ready_root_pending`, nunca
`complete`; ningún mutador ordinario acepta ese estado.

### Resolución de raíz

Un `--project-root` explícito domina `cwd`; el default `.` sigue siendo una
elección explícita del CLI después del parseo. Rutas symlink se resuelven sólo
para diagnóstico y localización, no para comparar identidad lógica.

Si ambos objetos viajan juntos y los UUID coinciden, una ruta actual distinta
de `canonical_project_root_at_init` se acepta y se reporta como
`root_relocated=true`. Mover sólo el store bajo un proyecto con otro
`project_uuid` falla cerrado.

### Stores legacy

Un store con `CURRENT` pero sin identidad nunca recibe UUID silenciosamente.
Los reads existentes siguen disponibles y reportan
`identity_status=legacy_unadopted`; todo comando mutativo falla
`legacy_store_identity_adoption_required` antes del lock.

`init` sobre ese estado también falla con el mismo código: lo detecta en
preflight y lo revalida bajo bootstrap lock antes de crear intent, identities u
otros bytes. Init sólo acepta `absent` o reanuda un intent
`operation=initialize` ya existente; un CURRENT legacy se procesa
exclusivamente mediante plan-adoption/adopt.

La adopción es explícita:

```text
an-kla identity plan-adoption
an-kla identity adopt --plan <json> --expected-current <sha256:...>
an-kla identity status
```

El plan liga `CURRENT`, raíz observada y bytes candidatos. `adopt` revalida
CURRENT y el estado `legacy_unadopted|partial_consistent` bajo el bootstrap
lock; crea o completa los objetos byte-idénticos del intent. Un retry devuelve
el mismo resultado. No se adopta un store con identidad completa diferente.

### Verificación del enlace

Para una revisión con `store_identity`, `snapshot(revision)` lee el objeto
inmutable y verifica schema+hash. `verify()` sobre CURRENT compara además ese
digest con el digest canónico de `memory/identity.json`, verifica que
`store_identity.project_identity` sea el digest canónico exacto del archivo
live `project-identity.json` y luego compara `project_uuid`. Alterar cualquier
campo exacto, incluido `created_by_version`, falla aunque el UUID permanezca.

Antes de cualquier hijo, el mutador exige:

- padre ligado → digest del padre igual al identity live;
- padre legacy → sólo permitido si un intent de adopción `complete` liga
  exactamente ese CURRENT;
- padre ligado a otro digest → `store_identity_lineage_mismatch`.

Así, reemplazar conjuntamente ambos archivos live no permite continuar una
cadena ligada a otro store. Reads históricos pueden verificar el objeto
inmutable sin depender de los archivos live; status declara cualquier mismatch.

### Backup, clone y worktree

- Backup/restore que incluye `.an-kla/project-identity.json` y
  `.an-kla/memory/` conserva identidad y puede reportar relocación.
- Copiar sólo el código no copia identidad; `init` crea un proyecto/store nuevo.
- Cada worktree con su propio `.an-kla` tiene `project_uuid` distinto salvo una
  adopción/copia explícita del operador.
- Una copia completa tiene inicialmente los mismos UUID: se considera restore,
  no un proyecto nuevo. Para bifurcarla se requiere una operación futura
  explícita; nunca se rota UUID automáticamente.

## Errores seguros

Los errores públicos son códigos estables sin rutas ni UUID:

- `project_identity_missing`, `project_identity_invalid`;
- `store_identity_missing`, `store_identity_invalid`;
- `project_identity_mismatch`, `store_identity_changed`;
- `store_identity_lineage_mismatch`, `identity_bootstrap_conflict`;
- `legacy_store_identity_adoption_required`;
- `identity_adoption_plan_invalid`, `identity_adoption_base_changed`.

`identity status` puede mostrar UUID sólo por solicitud local explícita; MCP y
errores saneados no los exponen.

## Alternativas descartadas

- Usar sólo la ruta: confunde relocación con otra identidad.
- Copiar la base de proyectos de otro sistema: añade autoridad y complejidad
  que AN-KLA no necesita.
- Generar UUID al primer write legacy: borra la distinción entre adopción y
  accidente.
- Guardar la ruta actual dentro de cada revisión: hace que una relocación cambie
  identidad content-addressed sin cambio semántico.

## Consecuencias y pruebas

El init nuevo gana dos archivos y un objeto inmutable; revisiones legacy siguen
legibles. Se requieren matrices para init concurrente, identidad cambiada
preflight→lock, proyecto distinto, relocación, symlink, clone, worktree,
backup/restore, adopción/retry y cero objetos ante error.

La implementación vive fuera de `store.py` cuando sea posible. El formato
físico base de ADR-0001 se conserva; ésta es una extensión aditiva del
manifiesto `revision-v1`.

ADR-0024 se implementa primero: bootstrap usa sus primitives estrictas y su
outcome para no prometer durabilidad sobre el `_fsync_directory()` silencioso
actual. Su modo bootstrap de inspect/repair exige el digest del intent, adquiere
`.identity.lock` antes del lock del store y sólo opera paths enumerados por ese
intent; no presupone identidad completa. Sólo después se habilitan init/adopt
v1.
