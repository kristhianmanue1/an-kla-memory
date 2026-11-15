# Goldens de `commit_write_plan` (fase A2, ADR-0063)

Salida canónica de `an_kla.write_commit.commit_write_plan` en 11 escenarios
deterministas, generada con el código de `main` en `5c5750a` (antes de la
extracción de `_commit_write_plan_locked`). Cada archivo guarda el resultado
(o el código de error) y el árbol del store resultante (ruta → sha256).

Regenerar (sólo si el comportamiento cambia a propósito; la fase A exige que
no cambie), desde la raíz del repo:

```bash
AN_KLA_NO_UPDATE_CHECK=1 TMPDIR=/var/tmp/ankla-faseA-a2 \
  .venv/bin/python -m tests.write_commit_scenarios tests/fixtures/write-commit-goldens
```

Determinismo: `uuid.uuid4` sustituido por un contador y `attest.key`
registrada sólo por presencia y tamaño (es aleatoria por diseño). El store
vive en `/var/tmp/ankla-write-commit-goldens/<escenario>`: los digests
dependen de la ruta resuelta del proyecto (`canonical_project_root_at_init`),
que `_meta.json` registra; si la plataforma la resuelve distinto (p. ej. Linux
frente a macOS, donde `/var` apunta a `/private/var`), la prueba se omite con
ese motivo en vez de fallar. Dos corridas seguidas producen archivos
idénticos.
