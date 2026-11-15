# Origen de `vectores.json`

Vectores de conformidad del contrato C0 `memoria/identidad/v1`, copiados sin
modificar (ADR-0063 D2).

- Repo: `/Users/krisnova/www/aria/coordination`, rama `main`.
- Commit: `8fccbcc` (contrato congelado el 2026-11-14).
- Ruta de origen: `cc/memoria/contratos/identidad-v1/vectores.json`.
- sha256: `a169a7f93728f327f2f47282b339ff8a2b4fc1f0e9cd383a6afe7f6441a92643`.
- Contenido: 76 casos en cinco grupos (9 `validos`, 33 `invalidos`,
  22 `normalizacion`, 10 `remoto_no_normalizable`, 2 `local`).

`tests/test_identity_c0.py` comprueba el digest antes de usar el archivo. Un
cambio en C0 es `identidad-v2`: se copia un archivo nuevo, no se edita éste.
El archivo (935 líneas) supera el límite por defecto del gate de tamaños; en
`skevi-gate.json` tiene un límite propio de 935 (`limits`), no una exención:
si crece, el gate lo detecta.

## Errata 1 de C0 (`vectores-errata-1.json`)

El dueño de C0 corrigió el validador de referencia: anclaba con
`re.match(...$)`, y en Python `$` también casa antes de un salto de línea
final, así que aceptaba lo que el contrato rechaza («sin espacios»). El texto
del contrato y `vectores.json` no cambian. Detalle, tabla de efectos y límite
conocido: `cc/memoria/contratos/identidad-v1/ERRATAS.md` en el mismo repo.

- Commit: `4c0fc1e` en `main` (el archivo entró en `4df5fb4` y no cambió
  después).
- Ruta de origen: `cc/memoria/contratos/identidad-v1/vectores-errata-1.json`.
- sha256: `bd6abbae0b135ac6b64910ee0e967d2d9a929763399de6f286d13c126a36654d`.
- Contenido: 11 casos (1 `validos`, 6 `invalidos`, 3 `normalizacion`,
  1 `remoto_no_normalizable`), mismo formato y mismo ejecutor.

`an_kla/identity_c0.py` ya usaba `fullmatch` y pasa los 11 sin cambios; la
prueba comprueba el digest y ejecuta el archivo. Los caracteres invisibles de
formato (`U+200B`, `U+200C`, `U+FEFF`) siguen aceptándose donde C0 los acepta:
prohibirlos sería `identidad-v2`.

Espacio en blanco: el validador y el schema usan una clase enumerada que es
exactamente el `\s` de Python sobre `str` (lo que usa la referencia), de modo
que U+FEFF se acepta como en ella y no hay otra divergencia por este motivo.
`test_whitespace_class_is_exactly_python_s_over_the_whole_unicode_range` lo
comprueba carácter a carácter sobre todo el rango Unicode.

## Residual del schema: cotas de longitud

El schema `record-envelope-v1` coincide con el validador en clases de carácter
y anclas en cualquier motor JSON Schema, pero no en las cotas de longitud:
`maxLength` cuenta code points en los motores conformes y unidades UTF-16 en
algunos. Un motor del segundo tipo rechaza lo que el validador acepta:

| valor | longitud | validador | schema (motor que cuenta UTF-16) |
|---|---|---|---|
| `repo.branch` = `"𝕏" * 200` | 200 code points, 400 unidades | válido | rechazado (`maxLength: 200`) |
| `agent.model` = `"𝕏" * 80` | 80 code points, 160 unidades | válido | rechazado (`maxLength: 80`) |

La cota de 200 del identificador de `session.id` no se expresa en el schema
(sólo `maxLength: 233` sobre el total, con el prefijo variable). Sólo hay
discrepancia con caracteres fuera del plano básico; el validador es la
autoridad y el schema lo declara en su `description`.
