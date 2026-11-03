# Reparación de idempotencia de hook-runs

Estado: candidato a revisión adversarial. Autor: agente Codex raíz.
Encargo del Operador 2026-11-02: plan técnico, ronda adversarial y ejecución
por OpenCode. Alcance autorizado: reparación local y validación; no release,
publicación, cambios de versión, memoria canónica ni activación de ADR-0062.

## Base y resultado requerido

Base observada: feat/adr-0062-ci-runner en 0e69ae9, main remoto 83ef2fa.
Conservar íntegra la implementación optativa de CI existente. Usar este
checkout sin reset, checkout destructivo ni inicialización de otro store.
Fuentes: `an_kla/hook_runs.py`, `tests/test_hook_runs.py`,
`docs/benchmarks/hook-run-idempotency-blocker-2026-10-30.md`.
El reloj participa en el digest: O_EXCL sobre digest no deduplica run_id.

Éxito: mismo run_id y payload funcional devuelve los bytes, digest y hora
originales aun tras avance de reloj/reinicio; payload distinto falla cerrado;
procesos concurrentes sobre la misma custodia no publican duplicados.
No renovar recencia, acuñar autoridad ni modificar evidencia previa.

## Contrato que debe cerrar el spike antes de editar producto

Identidad de deduplicación: run_id dentro de una misma custodia/identidad.
Payload funcional: hook_id, trigger, action, exit_code, subject_digest,
project_uuid, store_identity, adapter_fingerprint. observed_at y run_hmac no
son payload funcional; now sólo fija hora de primera publicación.
No interpolar run_id en rutas. Validar tipos y límites antes de efectos.
Proponer códigos saneados para conflicto, evidencia inválida, búsqueda
incompleta y contención; comprobar su propagación CLI/MCP y compatibilidad.

Bajo una exclusión entre procesos anclada en custodia real, revalidar binding,
custodia y llave, descubrir evidencia completa, verificar formato/HMAC,
nombre digest y bytes, comparar payload, y publicar durablemente si no existe.
Reutilizar primitivas existentes sólo tras verificar orden de locks, alias,
reentrancia, timeout y relación con relocate/compactación; no asumir que
el lock de proyecto cubre una bóveda externa. Evitar deadlocks con callers.
No usar read_verified_runs como prueba de ausencia: trunca a 2000 entradas.
Un límite alcanzado debe fallar cerrado, nunca publicar como si no existiera.

Duplicados históricos del mismo run_id: no elegir arbitrariamente ni borrar;
fallar cerrado con diagnóstico saneado y remediación fuera de este encargo.
Entrada ilegible, corrupta, symlink o identidad ajena que impida establecer
unicidad: fallo cerrado, sin reparar ni sobrescribir. Mantener lectura legacy
compatible; no confundir endurecer acuñación con cambiar todos los lectores.
Si se necesita nuevo layout, índice persistente, schema o decisión arquitectónica,
redactar ADR y detener implementación dependiente hasta adopción conforme al repo.

## Tareas ejecutables

```text
TAREA H0 — Preflight (OpenCode, exclusivo)
Consumes: AGENTS.md, AN-KLA.md, prácticas, este plan y acta adversarial.
Produce: inventario de estado y bitácora de comandos con rc, duración y SHA.
Steps:
- [ ] Confirmar rama/HEAD/diff, instrucciones y Python explícito >=3.12; verificación: conservar cambios existentes y registrar baseline exacta.
- [ ] Consultar issues/PRs y context status/status/verify sin update-check; verificación: no mutación de memoria ni reparación automática.
- [ ] Ejecutar .venv/bin/python -m unittest discover -s tests -p 'test_*.py' antes de tocar almacenamiento/concurrencia; verificación: guardar resultado real, distinguir defecto conocido de fallos nuevos y no repetir esperando verde.

TAREA H1 — Spike y diseño acotado (OpenCode)
Consumes: H0, hook_runs, attest, custody, locks, callers y ADR-0047/0048.
Produce: nota técnica con archivo:línea, orden de locks y contrato de errores.
Steps:
- [ ] Reproducir control mismo segundo y contraejemplo reloj avanzado en stores temporales; verificación: antes del arreglo uno y dos objetos respectivamente, sin reloj host ni store canónico alterados.
- [ ] Trazar todos los callers y locks, alias de custodia, fsync y recuperación tras publicación incierta; verificación: propuesta explica exclusión interproceso y no deadlock con evidencia de código.
- [ ] Fijar tratamiento de entradas inválidas, duplicados legacy, límites y errores; verificación: revisión pre-code fresca con proceed o bloqueo explícito si requiere ADR nueva.

TAREA H2 — Implementación mínima y regresiones (OpenCode)
Consumes: H1 con proceed y baseline H0.
Produce: reparación local, pruebas deterministas y diff limitado.
Steps:
- [ ] Implementar deduplicación y conflicto bajo exclusión correcta; verificación: mismo resultado y bytes en reintento, cero escrituras ante conflicto.
- [ ] Añadir pruebas de reloj avanzado y now diferente, reinicio de proceso, cambios en cada campo funcional y run_id distintos; verificación: originales inmutables y IDs distintos producen eventos distintos.
- [ ] Añadir carrera multiproceso con barrera, mismo y diferente payload, alias y custodia externa; verificación: un objeto válido por run_id, sin sleeps usados como sincronización ni procesos huérfanos.
- [ ] Cubrir HMAC/tipos/binding/nombre digest inválidos, symlinks, duplicados previos, límite >2000, timeout y fallo de publicación/fsync; verificación: rechazo saneado sin falsas garantías de durabilidad ni publicación adicional tras resultado incierto.
- [ ] Cubrir CLI sin hook, hook exitoso, error saneado y recencia vencida; verificación: contratos previos y autoridad no cambian, reintento no rejuvenece evidencia.

TAREA H3 — Revisión y gates (OpenCode + revisor fresco)
Consumes: diff H2, pruebas y nota H1.
Produce: acta con findings, correcciones, límites y proceed/fix-and-retry/escalate.
Steps:
- [ ] Ejecutar suites focales, check_sizes.py, check_plans.py, check_adr_registry.py y git diff --check; verificación: comandos con .venv/bin/python y resultados reales vinculados al SHA/diff.
- [ ] Revisar con contexto separado sin historial del implementador; verificación: declarar agente/proveedor observado y contexto entregado, atacar concurrencia, autoridad, corrupción y falsa ausencia.
- [ ] Corregir bloqueantes y repetir revisión y pruebas afectadas; verificación: proceed final sin findings bloqueantes abiertos.
- [ ] Ejecutar .venv/bin/python scripts/ci_local.py --simulate-ci sin CI simultáneo; verificación: gate vigente verde o reporte preciso del bloqueo, nunca sustituirlo por auditoría optativa.

TAREA H4 — Entrega local (OpenCode)
Consumes: H3 y evidencia final.
Produce: reporte final y lista exacta de archivos modificados.
Steps:
- [ ] Actualizar nota del bloqueo y crear reporte bajo docs/benchmarks con evidencia; verificación: separar resultados nuevos de los históricos y dejar transición ADR-0062 no activada.
- [ ] Inspeccionar diff/status y ausencia de procesos de prueba residuales; verificación: preservar trabajo previo y no commit/push/merge/tag/build/release ni escritura de memoria en esta ejecución.
- [ ] Informar OK/PARCIAL/BLOQ, riesgos y siguiente decisión; verificación: release y equivalencia de CI siguen fases separadas, no pendientes ocultos del arreglo.
```

## Herramientas y coordinación

Usar rg, git diff/status, .venv/bin/python, unittest y gates del repo.
Evidencia temporal fuera de Git, sin llaves ni payloads privados. Nunca registrar
attest.key. Un solo escritor de código. Revisor sólo lectura salvo su acta;
no pruebas de CI en paralelo. No instalar dependencias ni eludir sandbox.
Ante timeout consultar estado/procesos/archivos antes de reintentar efectos.
Si no hay herramienta de revisión fresca disponible, entregar PARCIAL con
revisión pendiente, sin atribuir independencia al autoanálisis.

OpenCode ejecutará H0–H4 con modelo por defecto y permisos habituales del host.
No asumir nombres de proveedor/modelo a partir de recuerdos. Al terminar,
la aceptación del Operador y cualquier publicación siguen separadas.

## Precisiones de la ronda adversarial

El proceed de este plan permite iniciar H0–H1; H2 conserva su gate pre-code.
La idempotencia cubre acuñación con run_id explícito, no exactly-once de la
acción CLI: el CLI actual no transmite run_id. No añadir esa capacidad aquí.
H1 debe resolver explícitamente archivo completo existente tras error fsync:
existencia e integridad no prueban durabilidad; el retry no puede declarar una
publicación durable sin satisfacer el contrato correspondiente. El lock debe
coordinar con relocate, no sólo con otros acuñadores. Si esto exige cambiar
arquitectura, detener H2 y entregar propuesta de ADR para decisión.
