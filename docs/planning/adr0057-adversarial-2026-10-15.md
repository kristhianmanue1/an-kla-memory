# Ronda adversarial — ADR-0057 lectura sin re-canonicalización (2026-10-15)

Artefacto atacado: `store.py::_read_segment` (quita la re-serialización
canónica por fila; conserva hash de bytes + framing) + ADR-0057 + Enmienda 1
del ADR-0056 + `tests/test_read_segment.py`. **Toca `store.py`: ronda
obligatoria.** Intérprete: `.venv/bin/python` → Python 3.12.12.

## Alcance

1. La integridad de lectura no depende de la capa retirada.
2. Consumidores del código retirado (`segment_not_canonical`).
3. Superficies que re-usan bytes de segmento (export, compactación,
   restore).
4. Medición del beneficio proyectado vs real.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Resolución |
|---|---|---|
| R1 — ¿la capa retirada cubría algo que el hash no cubre? | pérdida silenciosa de garantía | análisis: el hash ancla los bytes originales; la canonicidad es invariant de escritura (construida por `_write_segment`); los digests derivados de registros se computan sobre el valor parseado, no sobre bytes — sin pérdida de integridad; declarado en ADR-0057 |
| R2 — `segment_not_canonical` sin consumidores | código muerto o pins ocultos | grep: única referencia era el propio `raise`; sin tests ni docs que lo pineen |
| R3 — ¿json.loads puede fallar tras hash válido? | excepción no-IntegrityError en lectura | sólo si el escritor escribió bytes no-JSON con digest correcto (fallo de escritor, no de disco); comportamiento idéntico al previo (JSONDecodeError ya escapaba sin tratar antes de la capa retirada) |
| R4 — proyección optimista del spike | prometer más de lo real | verificado con batería re-corrida (abajo): `snapshot` diagnóstico cae ~2×, consistente con el 56 % proyectado |

## Verificación (comando → resultado)

- `tests.test_read_segment` → 4 OK: filas servidas = escritas; byte
  manipulado → `segment_hash_or_framing_invalid`; truncamiento de framing
  → error; `verify` completo pasa en store sano.
- Dirigidos: 38 OK (read_segment + watermark + store_subject_ref +
  export_restore + relocate).
- Spike de perfilado (stores 1k–50k): re-canonicalización 64,7 % del
  coste de lectura; `snapshot` 0,165 → 0,074 s a 50k con el cambio
  simulado.
- Batería de aceptación: ver INFORME de la corrida post-ADR-0057
  (`snapshot` diagnóstico ~mitad vs línea base).
- Gates: check_adr_registry 57 (52/5), check_sizes, check_plans OK.
- Suite completa: línea final del reporte de sesión.

## Límites declarados

- Un escritor defectuoso que produjera bytes no canónicos ya no se
  detectaría en lectura (se detectaría en auditoría de escritor); riesgo
  aceptado y documentado.
- El beneficio es de CPU de lectura; el coste de I/O (abrir N archivos)
  permanece — la fusión de segmentos por lotes (ADR-0054) y la compactación
  siguen siendo las palancas de I/O.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
