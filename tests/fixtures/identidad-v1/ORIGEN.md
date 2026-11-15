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

## Divergencia conocida con el validador de referencia

`an_kla/identity_c0.py` usa `fullmatch` donde `scripts/validate_identidad.py`
(`8fccbcc`) usa `re.match(...$)`, y en Python `$` también casa antes de un
salto de línea final. Con un `\n` en la entrada los dos dan resultados
distintos, y no sólo «aceptar o rechazar»: el `repo.id` puede cambiar de caso.

| entrada | referencia | an-kla |
|---|---|---|
| `normalize_remote("OM\n:eU3")` | `"om\n/eu3"` (id canónico con el salto) | `None` |
| `repo_id_from_remote("GwXYo\n:Vu", "/base")` | `"gwxyo\n/vu"` (caso 1) | `"remoto:e720d808474ba2b6"` (caso 2) |
| `is_valid_branch("rama\n")` | válida | no válida |

Los 76 vectores no incluyen ningún `\n`, así que ambos los pasan. an-kla sigue
la lectura del contrato («sin espacios»); la prueba
`test_a_newline_inside_the_input_changes_the_case_not_just_the_verdict` lo fija.
Es un defecto del validador de referencia, no del contrato: queda para que el
dueño de C0 decida una errata. Hasta entonces, dos implementaciones pueden dar
identidades distintas para un remoto con salto de línea interno.
