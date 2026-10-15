# Ronda adversarial — P1 watermark (ADR-0053, issue #149), 2026-10-15

Artefacto atacado: `feat/p1-watermark@bc054be` — `an_kla/watermark.py`,
sufijo en `validate_revision_chain(stop=...)`, `snapshot(use_watermark=)`,
refresco del escritor en `transactions.py` tras `_replace_current`,
exclusión del sidecar en `export_restore.py`, y `tests/test_watermark.py`.
**Toca `store.py`: ronda obligatoria** (AGENTS.md). Intérprete:
`.venv/bin/python` → Python 3.12.12.

## Alcance

1. Equivalencia de resultado ante watermark sano/corrupto/atrasado/ajeno.
2. Frontera de confianza: el watermark nunca eleva autoridad ni cambia el
   contenido servido.
3. Auditoría completa (`verify`) inmune al watermark.
4. Superficies colaterales: export/restore, compactación, identidad,
   concurrencia, crash.
5. Criterio de aceptación del ADR: batería re-corrida contra línea base.

## Modelo de amenazas

El watermark es caché derivada en disco sin firma: un atacante de disco
puede reescribirlo. La pregunta adversarial es si esa reescritura puede
cambiar un resultado aceptado (debe: sólo degradar a recorrido completo o
ya venir fallando cerrado) o fabricar confianza (no-objetivo rollback,
paridad con el límite preexistente de `CURRENT`).

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| W1 — el export fallaba cerrado (`export_unrecognized_durable_path`) ante el directorio nuevo `watermarks/` | bundles rotos para cualquier store con commit post-P1 | exclusión por lista de derivadas (junto a `indexes/`, `leases/`, `quarantine/`); 5 errores de test export_restore absorbidos |
| W2 — un watermark cuya revisión no existe en la cadena podría interpretarse como error | lectura sana rechazada por culpa de una caché | `usable_watermark` sólo valida shape; la no-existencia se resuelve al caminar (nunca se alcanza el stop → recorrido completo); testeado |
| W3 — refresco del watermark tras `_replace_current` pero antes de los receipts de CURRENT | un crash en esa ventana deja watermark atrasado | aceptable por diseño: watermark atrasado ≡ sufijo más largo ≡ mismo resultado (test `stale`); el crash de la batería (10/10 verify ok) cubre la clase |
| W4 — `identity.py` (adopción) y compactación validan cadenas completas sin watermark | inconsistencia de criterio | intencional: rutas frías de auditoría/adopción; el caliente (lecturas/escrituras) usa el watermark; documentado aquí |
| W5 — relocate dejaba `memory/watermarks/CURRENT` como residuo en el origen (14 fallas de suite por propagación) | custodia migrada con basura en el checkout antiguo | mismo tratamiento que `indexes/`: rmtree de derivadas en `_cleanup_under_gate`; tests relocate/relocate_back en verde |
| W6 — `test_refutation_delta_requires_immutable_refute_attempt` esperaba que la lectura normal detectara manipulación del prefijo | contradicción con el contrato aceptado (ADR-0053: el prefijo cacheado no se revalida en lectura normal) | test apuntado al camino de auditoría (`use_watermark=False` exige `revision_transition_invalid`) + aserción de que la lectura normal sigue sirviendo la revisión vigente: la inmutabilidad se exige donde el contrato la pone |

## Verificación de canonicidad / determinismo (comando → resultado)

- `python -m unittest tests.test_watermark -v` → 7 OK: equivalencia
  con/sin; corrupto (basura y JSON inválido) degrada; atrasado sirve lo
  mismo; binding errado (parent) se ignora; epoch equivocada se ignora;
  refresco del escritor ligado a CURRENT; **corrupción de un manifiesto
  ancestro: `snapshot(use_watermark=False)` la expone, la lectura normal
  sigue sirviendo el estado vigente** (la auditoría es la que descubre).
- Dirigidos: 83 OK (write_commit×3, supersede×2, checkpoints,
  store_subject_ref, export_restore, watermark).
- Batería de aceptación (`results/20261014-213523`): 3/3 celdas alcanzaron
  n=600 sin aborto (base: 403-478 con aborto); p50 0,57→0,27 s; p95
  1,82→0,73 s; snapshot 0,046 s a 600 revs (lineal en registros, no en
  cadena); concurrencia/crash/compactación sin regresiones.
- Gates: check_sizes OK (526), check_adr_registry OK (54),
  check_plans OK (4).
- Suite completa con Row15: ver línea final del reporte de sesión.

## Límites declarados

- Rollback del par (CURRENT, watermark) a un estado antiguo coherente:
  no-objetivo (ADR-0053 §5); paridad exacta con el límite preexistente de
  revertir CURRENT solo.
- El eje registros sigue lineal por re-lectura de segmentos (F2 → P2c).
- La ventaja medida es de la misma máquina e intérprete de la línea base;
  la comparación es de forma, no de cifra absoluta.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
