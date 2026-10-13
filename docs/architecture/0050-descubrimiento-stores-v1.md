# ADR-0050: descubrir stores por escaneo explícito y de sólo lectura, sin registro con autoridad

- **Estado:** Aceptada (decisión del maintainer, 2026-10-13, hilo «Ejecución
  del roadmap G3»: «Confirmado» a la recomendación de aceptar el ADR tal cual
  y censar `/Users/krisnova/www` a profundidad 4). Ver Enmienda 1.
- **Implementación:** Implementada — `stores scan` (`an_kla/stores_scan.py`,
  `tests/test_stores_scan.py`). D1 (índice orientativo) no iniciado.
- **Fecha:** 2026-10-13
- **Decide sobre:** cómo descubre el operador las bóvedas AN-KLA de una
  máquina (#134) sin que el mecanismo de descubrimiento se convierta en
  autoridad sobre `init`, lectura, borrado o reasignación. No decide
  memoria global ni multi-scope (#58).

## Contexto

#134 reporta 25 stores en una máquina, 4 huérfanos de pruebas, y ningún
comando para enumerarlos. El dato es **histórico** (0.1.0b24, 2026-09-11):
no es el estado actual y no se repitió el censo para este ADR (ver
`docs/planning/g3-d0-descubrimiento-2026-10-13.md`).

G3 (ADR-0048) cambia el problema:

- Una bóveda puede vivir fuera del checkout (`store_root` externo). El
  checkout guarda sólo un puntero (`.an-kla/store-root.txt`) con
  `custody_fingerprint`, que no contiene rutas.
- La identidad es por bytes (`project_uuid` + `store_identity`). La ruta en
  el puntero y en `canonical_project_root_at_init` es localizador u
  observación, nunca autoridad.
- `relocate` deja relocation receipts encadenados que viajan con la bóveda.

Con esto, un escaneo puede clasificar lo que encuentra usando únicamente
artefactos que ya existen. No hace falta un padrón nuevo.

## Decisión

Proponer un comando **`stores scan --root <dir> [--max-depth N]`** de sólo
lectura que:

1. Recorre sólo las raíces que el operador nombra, sin seguir symlinks y con
   un límite de profundidad. Nunca escanea `~` por defecto.
2. Reconoce tres artefactos:
   - anchor project-local: `.an-kla/` con `project-identity.json` o CURRENT;
   - puntero: `.an-kla/store-root.txt`;
   - raíz de custodia externa: un directorio con `memory/identity.json` y
     `project-identity.json`.
3. Clasifica cada hallazgo por bytes, nunca por nombre de ruta:
   - `active`: identidad completa y `verify` OK;
   - `external_bound`: bóveda externa cuyo fingerprint coincide con un
     puntero encontrado;
   - `copy`: el mismo `store_identity` aparece en más de una ubicación;
   - `moved`: la ubicación difiere de la registrada en identidad o en la
     cabeza de la cadena de receipts;
   - `orphan_uncertain`: bóveda sin puntero conocido dentro del alcance
     escaneado. Es «incierto» porque el proyecto puede estar fuera del
     alcance;
   - `unreadable`: ilegible o con integridad rota, con su código estable.
4. Por defecto emite agregados y fingerprints sin rutas. Las rutas salen
   sólo con `--show-paths`, para un artefacto efímero del operador.
5. **No escribe nada**: no crea `.an-kla/`, no repara, no borra, no adopta,
   no reescribe punteros y no guarda resultados. «Retirar» un store sigue
   siendo una acción humana separada.

Un **índice local orientativo** (opción de #134 §1) queda como D1
condicionado. Sólo se haría con aceptación de este ADR y autorización del
maintainer, y bajo esta regla: el índice es caché de localizadores.
Toda acción vuelve a resolver por identidad y `verify`. Una entrada falsa,
vieja o duplicada nunca habilita `init`, lectura, borrado ni reasignación.

## Por qué no [alternativa]

### Registro global escrito por `init`/`adopt` (`~/.an-kla/stores.json`)

- Crea un archivo fuera del proyecto en cada `init`, incluidos tests y CI.
  Es la misma clase de efecto lateral que produjo los huérfanos.
- Concentra rutas de todos los proyectos en un solo archivo legible: es
  divulgación por diseño.
- Envejece con cada `mv`, clon, `relocate` o restauración de backup.
- Abre una superficie de confusión: un agente que «confíe» en el registro
  para elegir bóveda reintroduce la ruta como autoridad, lo que ADR-0048
  eliminó.
- Exige concurrencia entre procesos de proyectos distintos sobre un archivo
  compartido.

Descartado como primer paso. Su variante orientativa es D1.

### Ningún mecanismo (statu quo + `find` documentado)

No distingue copias, movidos ni externos ligados, y no lee punteros. Tras G3,
`find -name .an-kla` ya no encuentra las bóvedas externas. Insuficiente.

### Escaneo automático al arrancar (`startup-diagnostic`)

Coste y privacidad impredecibles en cada sesión. Mezcla el diagnóstico del
proyecto con el inventario de la máquina. Descartado.

## Threat model resumido

| Amenaza | Escaneo explícito (propuesta) | Índice orientativo (D1) | Registro con autoridad |
| --- | --- | --- | --- |
| Entrada falsa plantada por otro proceso | no hay entradas | no habilita nada; se reverifica | podría dirigir `init`/lectura |
| Ruta obsoleta tras `mv`/`relocate` | se observa en vivo | `stale` hasta reescanear | apunta a nada o a otra bóveda |
| Clon o copia del store | `copy` por `store_identity` | igual tras reescanear | dos «dueños» del mismo registro |
| Divulgación de rutas | sin rutas por defecto | archivo con rutas en `~` | archivo con rutas en `~` |
| Bóveda externa sin checkout | `orphan_uncertain`, nunca borrada | igual | podría «limpiarse» por error |
| Reasignación silenciosa | imposible: sólo lectura | prohibida por regla | posible |

## Consecuencias

- Positivas: resuelve la indescubribilidad de #134 sin estado nuevo y sin
  rutas como autoridad; reutiliza identidad, puntero y receipts de G3.
- Negativas: el operador debe nombrar raíces; no hay vista instantánea sin
  escanear; `orphan_uncertain` puede incluir bóvedas legítimas fuera del
  alcance.
- Neutras: un schema `stores-scan-v1` y su CLI quedan para la
  implementación, si se acepta.

## Criterios de aceptación propuestos (#134)

1. Fixtures con proyecto local, bóveda externa con puntero, copia, bóveda
   movida y bóveda sin puntero, clasificados como arriba.
2. Ningún archivo creado ni modificado bajo las raíces escaneadas (árbol y
   mtimes antes/después).
3. Symlinks no seguidos y profundidad respetada, con control positivo.
4. Sin rutas en la salida por defecto.
5. Un índice o puntero falso no cambia ninguna clasificación de identidad.

## Test de regresión

No aplica hasta la implementación; los criterios 1–5 son los tests a escribir.

## Referencias

- #134 (problema), #58 (G4, fuera de alcance), #57 y ADR-0048 (custodia
  externa, puntero, receipts).
- `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md` (D0, D1).
- `docs/planning/g3-d0-descubrimiento-2026-10-13.md` (método de censo y estado).

## Enmienda 1 (2026-10-13) — censo e implementación

Acta del censo: `docs/planning/g3-d0-censo-2026-10-13.md`.

1. **Paquetes de export:** el censo encontró dos directorios `entries/anchor`
   de bundles de export que el patrón «raíz de custodia externa» de §Decisión 2
   habría contado como bóvedas huérfanas. `stores scan` reconoce un
   directorio con `manifest.json` y `entries/anchor/` como clase
   `export_bundle`, que no es bóveda ni cuenta como copia.
2. **Sin `verify`:** la clase `active` significa «identidad completa por
   bytes y CURRENT con forma válida», no `verify` OK. `verify` abre el
   reader gate, que puede crear un archivo de lock, y eso violaría el
   criterio 2. La salida lo declara con `verify_run: false`; integridad
   completa sigue siendo `status` sobre la bóveda elegida.
3. **Clases y banderas:** `copy` y `moved` son banderas sobre la clase, no
   clases excluyentes. Se añaden `pointer_only` (anchor con puntero y sin
   bóveda local) y las banderas `pointer_divergent` y
   `pointer_target_out_of_scope`.
4. **Poda declarada:** `.git` y `node_modules` no se recorren
   (`pruned_names` en la salida).
