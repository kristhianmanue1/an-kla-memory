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
El archivo supera el límite de líneas del gate de tamaños; está exento por
nombre en `skevi-gate.json` porque es una copia exacta.
