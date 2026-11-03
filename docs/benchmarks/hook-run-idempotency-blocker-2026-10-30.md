# Bloqueo de CI: idempotencia de hook-run y cambio de reloj

**Estado:** defecto de producto reproducido; corrección no aplicada.
Detectado durante validación de ADR-0062. El gate legacy falló y no se
considera sustituido por el runner nuevo. Store canónico sin intervención.

## Evidencia

`test_hook_runs.MintTests.test_mint_is_idempotent_by_run_id` encontró dos
JSON en vez de uno durante la captura legacy 3. El test y el código producto
ya existían antes de optimizar CI. Una revisión de contexto separado reprodujo
el contraejemplo con Python 3.12.12 en stores sintéticos independientes.

[Reproductor](evidence/ci-orchestration-20261029/hook-idempotency-probe.py) y
[resultado](evidence/ci-orchestration-20261029/hook-idempotency-counterexample.json):

| Control | Argumentos públicos | Reloj interno | Objetos |
|---|---|---|---|
| Positivo | Mismo run_id y mismos campos | Mismo segundo | 1; mismo digest |
| Contraejemplo | Mismo run_id y mismos campos | Avanza un segundo | 2; digests distintos |

La sonda sustituye `_utc_now` en memoria; no pasa un `now` distinto al API,
no espera ticks ni cambia fuente o reloj del host. Cada escenario inicializa
su propio store efímero y llave de prueba. No expone la llave.

En `an_kla/hook_runs.py:98–116`, `observed_at` entra en el HMAC y el digest;
la ruta de publicación usa ese digest. O_EXCL evita repetir bytes idénticos,
pero no deduplica el `run_id` cuando cambia la hora. ADR-0047 §3/F3-C declara
que el reintento con el mismo run_id es no-op idempotente. La prueba usa reloj
real y por ello también es temporalmente frágil; un pase posterior no refuta
el defecto. Congelar `now` como único reemplazo reduciría el criterio.

## Propuesta acotada para decidir

1. Retry con mismo run_id y payload funcional: devolver la primera evidencia
   válida, conservando sus bytes, hora y digest; no renovar su recientez.
2. Mismo run_id con payload funcional diferente: rechazar cerrado. Precisar
   los campos comparados y el código público antes de implementar.
3. Serializar descubrimiento/publicación entre procesos y alias de la misma
   custodia; no usar caché ni un escaneo parcial como prueba de ausencia.
4. Validar HMAC, binding, custodia y formato de cualquier evidencia reutilizada;
   no convertir registros corruptos o ajenos en autoridad de idempotencia.
5. Preservar el layout y schemas vigentes si es viable bajo ADR-0047. Cualquier
   cambio arquitectónico/público adicional requiere su decisión previa.
6. Probar reloj avanzado, reinicio, concurrencia, conflicto de payload,
   evidencia inválida y límites de búsqueda; revisión adversarial antes de
   código sensible y CI completo después. No hacer retry esperando verde.

La recomendación es autorizar esta reparación como alcance separado. ADR-0062
declara que no cambia storage: los permisos Git de la sesión no deciden por
sí solos esta ampliación. Mientras tanto puede completarse el diagnóstico
independiente del CI; no publicar ni activar el gate con el bloqueo vigente.

## Actualización 2026-11-02 — reparación implementada localmente

El encargo fue ejecutado (H0–H4) según
`docs/plans/2026-11-02-hook-run-idempotency.md`: diseño revisado con
proceed (`hook-run-idempotency-design-review-2026-11-02.md`), delta de
locks con proceed (`hook-idempotency-lock-delta-review-2026-11-02.md`),
implementación con revisión fresca final proceed
(`hook-run-idempotency-implementation-review-2026-11-02.md`) y reporte
completo en `hook-run-idempotency-repair-report-2026-11-02.md`. El
contraejemplo determinista de este documento quedó cubierto por pruebas
deterministas (reloj avanzado, reinicio de proceso, carrera con barrera)
en `tests/test_hook_run_retry.py`; el test que fallaba en la captura
legacy (`test_mint_is_idempotent_by_run_id`) pasa dentro de las piernas
del gate. Los cambios siguen sin commitear: ni commit/push ni publicación;
la aceptación del Operador y cualquier ronda pre-release siguen siendo
pasos separados. El estado de la transición ADR-0062 no cambia aquí: sin
activación de gates ni escritura de memoria canónica en esta ejecución.
