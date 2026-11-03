# Revisión adversarial del plan de idempotencia de hook-runs

Fecha: 2026-11-02. Resultado: **proceed para H0–H1**. Estado: **OK** para
esta revisión documental; no acredita implementación ni autoriza publicación.
H2 conserva el gate de revisión fresca del diseño concreto producido por H1.

## Procedencia y alcance

Productor declarado del plan: agente Codex raíz. Revisor: subagente
`/root/review_hook_plan`, convocado con el plan y el encargo de atacar suficiencia,
autoridad, locks, corrupción y aceptación. No recibió el historial de elaboración
del productor; sí instrucciones generales del entorno y del repositorio, y un
mensaje posterior con resultados de gates atribuidos al productor. No se verifica
independencia de proveedor/modelo ni separación de infraestructura.

Inspección estática del plan y código vigente, sin ejecutar suites ni modificar
producto, llaves o memoria. No se cargó memoria histórica para conservar el
contexto fresco de la revisión. La única escritura del revisor es esta acta.

## Evidencia observada

- `git rev-parse HEAD` → `0e69ae932d1d546bf28534e354ed4a2bc034dc45`.
- `git status --short --branch` → `feat/adr-0062-ci-runner`, sólo el plan
  candidato sin seguimiento al iniciar esta inspección.
- `.venv/bin/python --version` → Python 3.12.12.
- `.venv/bin/python -m an_kla --no-update-check --project-root . context status`
  → `ok: true`, diagnostics vacío; runtime `0.1.0b34`, plantilla beta.33.
- `gh issue list --state open` → #169, #168, #166, #140, #58;
  `gh pr list --state open` → ninguna PR abierta. Ambos rc=0.
- Lectura de `AGENTS.md`, `AN-KLA.md` y `docs/practicas-ingenieria.md`:
  revisión pre-code, gate de intérprete y autoridad explícita aplicables.
- `cat an_kla/hook_runs.py` y `sed` sobre `tests/test_hook_runs.py`:
  hora incluida en contenido firmado; escritura por digest sin búsqueda por
  run_id; prueba existente repite invocaciones sin fijar ni avanzar reloj.
- `rg`/`sed` de `__main__.py`, `attest.py`, `identity.py`, `store.py`,
  `store_locks.py` y `relocate*.py`: fronteras concretas expuestas abajo.

## Ataques y condiciones del siguiente gate

No se halló bloqueante para iniciar el spike: el plan exige cerrar estas
incertidumbres antes de editar producto, en líneas 22–47 y 60–69. No sería
correcto interpretar este proceed como validación de una disciplina de locks
todavía inexistente.

1. **Alcance de idempotencia.** `__main__.py:167` llama a `mint_hook_run` sin
   run_id; cada invocación CLI crea un identificador nuevo. El arreglo del API
   no prueba deduplicación entre comandos CLI ni ejecución única de la acción
   que precede al registro. H1 debe declararlo y H3 no debe presentar los tests
   CLI de compatibilidad como prueba de retry end-to-end. El retorno actual
   es `{run_id, digest}` (`hook_runs.py:121`): conservar bytes/hora en disco
   no requiere añadirlos al contrato de retorno.
2. **Durabilidad tras resultado incierto.** `attest.py:130–149` crea el archivo
   final antes de escribir y hacer fsync. Un error puede dejar un prefijo o un
   archivo completo cuyo fsync falló. H1 debe distinguir ambos casos y explicar
   cómo un retry evita afirmar durabilidad sólo porque el archivo se verifica.
   H2 debe inyectar fallos separados en escritura, fsync de archivo y de
   directorio, y verificar la segunda invocación. El plan ya lo exige en
   líneas 65 y 75; esta acta precisa el contraejemplo.
3. **Exclusión compatible con custodia.** Un mutex privado de hook-runs no
   coordina por sí solo `relocate.py:478–479` (identity lock y write lock).
   `store.py:567–570` hace `_make_layout()` al pedir write lock; usarlo antes
   del preflight podría crear estado en una ubicación desposeída. H1 debe
   justificar orden, revalidación después de esperar, efectos auxiliares y
   manejo de timeout/release, con callers reales. Un lock adquirido no prueba
   que la referencia de custodia siga vigente.
4. **Ausencia y corrupción.** El reader público trunca a 2000 y admite
   degradación; no sirve como índice autoritativo. El plan lo prohíbe y exige
   fallo cerrado ante duplicados o evidencia inválida. H1 debe precisar qué
   entradas forman el universo a explorar, incluidos directorios/symlinks y
   entradas no regulares, sin bloquearse leyendo FIFO ni hacer lectura
   ilimitada. La aceptación de H2 necesita prueba positiva del escaneo y caso
   en que el run buscado queda después del umbral, no sólo contar 2001 archivos.
5. **Autoridad y errores.** Un replay firmado no debe rejuvenecer recencia;
   el plan lo cubre. `__main__.py:175–182` convierte errores de acuñación en
   warning y preserva el resultado de la acción ya ejecutada. H1 debe mantener
   esa distinción, sanear nuevas excepciones de locks/custodia y documentar
   si MCP realmente alcanza esa ruta, sin inventar una integración nueva.

## Decisión y límites

**proceed** con la secuencia propuesta y su gate H1 intacto. La reparación se
considerará suficiente sólo con diseño concreto revisado, pruebas de rechazo
y controles positivos, concurrencia real, gates y revisión final. Ninguna
prueba de ejecución ni propiedad de durabilidad se certifica en esta acta.
No se verificó `main` remoto ni se aceptó riesgo de publicación: no son
necesarios para revisar el candidato local. No hay cambios de producto.

Comprobación de cierre: `tail -25` del plan confirma que el productor incorporó
la sección «Precisiones de la ronda adversarial» con el límite H0–H1, ausencia
de exactly-once CLI, fsync y coordinación con relocate. Gates ejecutados por
este revisor: `.venv/bin/python scripts/check_sizes.py` → OK, 665 archivos;
`.venv/bin/python scripts/check_plans.py` → OK, 5 planes; `git diff --check`
→ rc=0. Los dos documentos nuevos siguen sin seguimiento; ese último comando
no valida su contenido por sí solo.
