# Goldens de `commit_write_plan` (fase A2, ADR-0063)

Salida canónica de `an_kla.write_commit.commit_write_plan` en 14 escenarios
deterministas. Cada archivo guarda el resultado (o el código de error) y el
árbol del store resultante (ruta → sha256).

**Procedencia.** Regenerados con el código de `main` en `5c5750a`
(`an_kla/write_commit.py` sin `_commit_write_plan_locked`), en un worktree
temporal de `main` al que sólo se copió `tests/write_commit_scenarios.py`;
nunca con el código de la extracción. Se comprobó que dos corridas, y una con
otro `TMPDIR`, producen archivos idénticos.

**Regenerar** (sólo si el comportamiento cambia a propósito; la fase A exige
que no cambie). Crea un worktree desechable de `main`, copia allí
`tests/write_commit_scenarios.py` y ejecuta, con el intérprete 3.12 del
checkout canónico (los worktrees no tienen `.venv`):

```bash
git worktree add --detach <dir> 5c5750a
cp tests/write_commit_scenarios.py <dir>/tests/
cd <dir> && AN_KLA_NO_UPDATE_CHECK=1 TMPDIR=<tmp> \
  /Users/krisnova/www/an-kla-memory/.venv/bin/python \
  -m tests.write_commit_scenarios <destino>/tests/fixtures/write-commit-goldens
```

**Determinismo.** `uuid.uuid4` se sustituye por un contador; `attest.key` se
registra sólo por presencia y tamaño (es aleatoria por diseño); el proyecto
usa una raíz testigo inexistente (`/an-kla-golden-root`, `<ROOT>` en la
salida) porque `canonical_project_root_at_init` entra en los digests, y la
ruta temporal real se normaliza a `<TMP>`. Por eso la prueba corre en
cualquier plataforma, con un `TemporaryDirectory` propio, sin omisiones.

**Límite conocido.** Con la raíz testigo, `context_diagnostics` sale
degradado (`context_status_unavailable`) en todos los goldens: se fija el
orden y la presencia del campo, no el contenido de `context_status`, que
cubren `test_write_commit_supersede.py` y `test_auto_reindex.py`.
