# Ronda adversarial — #84 red de resguardo del CLI (2026-08-20)

Rama `plan/backlog-prioridades-2026-08-20`, punto 1 del plan
`plan-backlog-2026-08-20.md`. Revisor independiente (subagente, sin
autoría del código). Dos pasadas: fix-and-retry → proceed.

## Alcance

`an_kla/cli_error_log.py` (nuevo), catch-all en `__main__.main()`,
bloque `cli_error_surface` en `capabilities()`, 12 tests en
`tests/test_cli_unexpected_failure.py` (incl. e2e subprocess real).
No cambia códigos ni exit codes publicados.

## Modelo de amenazas

El traceback de una excepción no prevista es el vector: filtra rutas
absolutas de código y proyecto (§11.1). El propio handler es superficie
nueva: si lanza, produce el traceback encadenado que promete impedir.
El log local contiene argv (posibles queries/payloads): aceptado como
diseño local 0600 con tope y opt-out (minimización documentada).

## Hallazgos y correcciones

Ronda 1 (veredicto fix-and-retry; 3 MEDIUM demostrados con evidencia):

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| `display_path` podía lanzar (`Path.home` → `KeyError`) dentro del handler | Traceback encadenado a stderr: exactamente la fuga que #84 impide | try/except total → `<unavailable>` |
| Ruta absoluta filtrada con `XDG_CACHE_HOME` fuera de `$HOME` | Estructura de directorios del host en stderr | Cola relativa de 2 componentes fuera de home |
| TOCTOU: nacimiento 0644 + chmod posterior; huérfano degradado; `UnicodeEncodeError` con surrogates | Ventana legible del registro en primera escritura; registro perdido | `os.open(O_CREAT\|O_APPEND, 0o600)` atómico; `errors="replace"` |
| Test insignia vacío (SystemExit(str) no imprime en proceso) y sin e2e | Regresión futura pasaría verde | Aserción exacta del mensaje + e2e subprocess que valida stderr real, exit 1 y log |
| Dir 0755 / log sin tope / capabilities no condicional | Metadatos visibles; crash-loop llena disco; doc infiel | `chmod 0700`; reset >5MB; `stderr_note` + `max_bytes` + `overflow_policy` |

Ronda 2: 7/7 hallazgos cerrados con evidencia (incl. sonda con umask
0000 y verificación de que el reset no pierde el registro en curso).
Nits INFO aplicados igualmente: filtro de `/` en cola de `display_path`;
test que afirma `parent_mode 0700`.

## Verificación de canonicidad / determinismo

Sin cambios en hashes/fingerprints del producto. Mensaje de error
determinista verificado byte a byte en proceso real (e2e). Suites:
`tests.test_cli_unexpected_failure` 12/12; repo completo 544/544 OK
(2026-08-20, 26.2s).

## Límites declarados

- `KeyboardInterrupt` sigue imprimiendo traceback (residual,
  interactivo, preexistente; fuera del alcance declarado de #84).
- `error_log_path` duplica la convención de caché de `update_check`
  (INFO; unificar en helper compartido queda como deuda menor).
- Overflow policy `reset` pierde registros antiguos al superar 5MB:
  política declarada en `capabilities()`, no garantía de retención.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
