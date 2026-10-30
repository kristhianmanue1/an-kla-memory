# ADR-0062 — implementación optativa y validación

**Estado:** en verificación. ADR aceptada/fusionada en PR #194,
`83ef2fab90aaaf40d39df8f8cfb516182f9181af` antes del código.
El Operador autorizó las fases; activar un gate nuevo se presentará después
de verificar resultados. Escala 20.000 sigue pospuesta por espacio.

## Cambios

- `ci_audit.py`: plan exterior con perfiles desarrollo/auditoría, presupuesto
  global, evidencia fuera del árbol y gates estructurales por firma de entradas.
- `ci_worker.py`/`ci_results.py`: casos observados, subtests y skips, seis
  retiros de orquestación exactos; nunca llama a CI ni a otro discover completo.
- `ci_obligations.json`: listas cerradas de casos por fila, incluyendo 10b–e
  y 12b; fila 15 se acredita por el plan exterior, no por un test ficticio.
- `ci_process.py`/`ci_fixture_registry.py`: logs con cuota, deadline monotónico,
  cierre de grupo y fixtures cooperativos registrados antes de trabajo.
  Se retiene el PID líder mediante waitid/WNOWAIT hasta terminar señales;
  el prefacio de fixture no altera argv, env, stdin/stdout ni código producto.
  Grupo con líder muerto requiere miembro actual con token antes de señalar.
- Helpers compartidos de matrices y bundles sintéticos, sin imports entre
  módulos de tests en el camino funcional. CI anterior/seis tests legacy
  permanecen disponibles y activos durante la transición.
- `ci_legacy_capture.py`: observador declarado mediante bootstrap runpy;
  manifiesto de corrida con nonce, archivos enlazados por hash, inventario
  completo por runtime/modo y firma integral antes/después (incluye store
  canónico leído por G-3). No transforma logs anteriores en evidencia retroactiva.

## Uso y límites

Ejecutar con intérprete principal soportado ≥3.12. Ejemplo local optativo:

```bash
.venv/bin/python scripts/ci_audit.py --profile development --output /private/tmp/ankla-ci-dev-new
.venv/bin/python scripts/ci_legacy_capture.py --output /private/tmp/ankla-ci-legacy-new
.venv/bin/python scripts/ci_audit.py --sealed-python /Library/Developer/CommandLineTools/usr/bin/python3 --baseline /private/tmp/ankla-ci-legacy-new --output /private/tmp/ankla-ci-audit-new
```

Los directorios de salida deben estar vacíos/fuera del repo. Sin `--baseline`
una auditoría puede comprobar casos pero declara `transition_verified=false`;
no acredita equivalencia ni activa el gate. Desarrollo tampoco habilita
publicación. `ci_local.py --simulate-ci` sigue siendo obligatorio.

Contención implementada/verificada en POSIX; otro SO falla explícitamente,
sin instalación ni promesa de cobertura Windows. Se necesita permiso de
inspección/señalización de procesos propios; acceso bloqueado no prueba
ausencia. La propiedad cubre grupos propios y el inventario de fixtures
cooperativos registrados, no código hostil que omita deliberadamente el
protocolo. Un cierre incierto falla. No se modificó `an_kla/sealed/key_adapter.py`
ni su contrato para simular éxito de las pruebas.

La captura preserva sitecustomize/PYTHONPATH originales; sólo instrumenta el
transporte de comandos CI/unittest. Un primer preflight con otra estrategia
se detuvo al detectar sitecustomize existente, antes de lanzar el CI completo.
Se conservó ese resultado y se cambió el diagnóstico para no reemplazarlo.
Por ahora se rechazan piernas de matriz extranjeras no verificadas. Es límite
del diagnóstico, no un SKIP convertido en cobertura. En este host 3.9/3.13
no se resolvían por nombre; CLT cubre el perfil criptográfico separado.

La instrumentación añade contexto de arranque; sus tiempos no son un ensayo
causal aislado. Se informarán contadores y tiempos sin atribuir toda diferencia
a eliminación de ciclos. La referencia documental reciente del CI anterior
sin observador es 1304 tests/74 skips/712,498 s, frente a 1493,463 s históricos:
esa variabilidad existía antes de implementar la optimización.

## Resultado observado, 2026-10-30

**PARCIAL (incompleto): implementación optativa comprobada; transición bloqueada.**
Comando ejecutado:

```bash
.venv/bin/python scripts/ci_audit.py --sealed-python /Library/Developer/CommandLineTools/usr/bin/python3 --output /private/tmp/adr0062-audit-diagnostic-3
```

Resultado: 19 tareas OK, rc=0 y cleanup=complete; firma de entradas idéntica
antes/después. Duración total 513,703 s (8 min 34 s). Cada celda ejecutó
1327 casos, excluyendo exactamente los seis orquestadores legacy:

| Variante | Runtime | Duración de suite | Resultados de casos padre |
|---|---|---:|---|
| Plain normal | 3.12.12 | 106,141 s | 1253 success; 74 skip |
| Plain CI simulado | 3.12.12 | 105,766 s | 1253 success; 74 skip |
| Sealed normal | CLT 3.9.6 + cryptography 46.0.3 | 145,160 s | 1323 success; 3 skip; 1 subtest_skip |
| Sealed CI simulado | CLT 3.9.6 + cryptography 46.0.3 | 148,059 s | 1323 success; 3 skip; 1 subtest_skip |

El caso parcial contiene los dos subtests de ausencia de extra que no son
observables con cryptography instalada; sólo esa combinación exacta de caso,
capacidad, motivo y sufijos está autorizada por el inventario cerrado.
Los 186 requisitos de casos y 15 obligaciones externas se verificaron sin
errores. Esto no acredita Windows ni Python 3.13.

`.venv/bin/python -m unittest tests.test_ci_audit` → 29 tests OK, 9,949 s,
después del ajuste final del supervisor. Cuatro módulos de adaptadores bajo
supervisión habían producido 79 tests OK/1 skip (13,891 s).

## Intentos conservados y límites

| Evidencia | Resultado y causa |
|---|---|
| Legacy observado 2 | CI verde, tarea 1043,409 s; baseline rechazado: el observador representaba incorrectamente dos skips de subtests. Se corrigió el observador y se añadió regresión; ese baseline no se reutiliza. |
| Legacy observado 3 | CI rojo, tarea 745,083 s; defecto previo de idempotencia de hooks al cambiar el segundo. Referencia incompleta, no aceptada. |
| Audit diagnóstico 1 | Incompleto, 375,623 s; falsa clasificación de pipes residuales por carrera de lectura de EOF. |
| Audit diagnóstico 2 | Incompleto, 361,083 s; cierre asíncrono de resource_tracker de multiprocessing 3.9. Se reprodujo aisladamente y se añadió gracia acotada a 1 s dentro del deadline, sin tolerar descendientes vivos. |
| Audit diagnóstico 3 | Completo, 513,703 s; cuatro celdas verdes. Sin referencia legacy válida. |

Los registros y logs están conservados en archivos comprimidos bajo
`evidence/ci-orchestration-20261029/`; el índice
`execution-archive-index.json` identifica alcance, tamaño y SHA-256. Excluyen
stores, llaves, copias de fixtures y sus registros de procesos.
Las rutas absolutas de los manifiestos describen la ejecución original;
los archivos comprimidos son copias para revisión, no nuevas corridas.

No se compara 513,703 s con el legacy como porcentaje causal de aceleración:
el árbol, la instrumentación y el trabajo ejecutado difieren. Falta una
referencia válida para comprobar equivalencia. Un pase posterior del test
temporal de hooks tampoco refutaría su contraejemplo determinista.

## Revisión y continuación

Producción: agente raíz. Revisión de código y evidencia: agente
`/root/review_ci_runner_code`, sesión iniciada sin historial del padre y
posteriormente acumulada mediante revisiones de esta implementación; mismo
entorno y configuración de modelo, sin independencia de proveedor acreditada.
Comprobó catálogo, obligaciones, identidades, hashes de fuentes, firma,
las 19 tareas y las cuatro celdas. Veredicto: **proceed para implementación
optativa local; activación BLOQ**. La ausencia de señales registradas al grupo
raíz no significa ausencia de señales de limpieza en fixtures.

La revisión separada `/root/review_hook_clock_blocker` reprodujo el defecto
de producto: **escalate** para ampliar alcance. Véase
[bloqueo y propuesta](hook-run-idempotency-blocker-2026-10-30.md).
La decisión solicitada al Operador sigue pendiente; no se cambió producto
para hacer pasar el gate ni se repitió legacy esperando verde.

`transition_verified=false` y `active_publication_gate=false` permanecen
explícitos. No hay push/merge de implementación ni activación con este
bloqueo; `ci_local.py --simulate-ci` sigue vigente. Las 20.000 revisiones
siguen pospuestas por espacio. El paquete conserva versión y no se crea release.

Gates finales con `.venv/bin/python`: `check_sizes.py` → OK (663 textos),
`check_plans.py` → OK (4 planes), `check_adr_registry.py` → OK (62 ADRs,
57 aceptadas y 5 propuestas). `git diff --check` → rc=0. `context status`
→ ok=true; `status` → ok=true, revisión canónica 87 sin cambio. Estos gates
no sustituyen el CI legacy fallido. Conservación mediante commit local de
la implementación optativa; push, merge y activación quedan pendientes.
