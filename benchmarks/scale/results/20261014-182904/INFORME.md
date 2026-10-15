# Informe — batería P0 de escala, corrida oficial 20261014-182904 (issue #149)

Entorno: Python 3.12.12 (.venv), macOS 26.6.2 arm64, SQLite 3.53.4, FTS5
disponible; git del informe origen `5b073ec` (beta.30), batería sobre
`claude/bateria-p0-escala-149@6646669`. Umbrales aprobados por el
maintainer y commiteados **antes** de correr (`54efb65`); copia exacta en
`thresholds-used.json`. Números absolutos dependientes de máquina: la forma
de la curva es el hallazgo.

## 1. Columna gobernada (vía pública `plan_write`+`commit_write_plan`)

| Celda | n alcanzado | abort | p50 s | p95 s | wall s |
|---|---:|---|---:|---:|---:|
| sujetos=1, supersede 0 % | 472 | `sustained_latency` (mediana 20-ventana 2,02 s) | 0,57 | 1,82 | 343 |
| sujetos=200, supersede 0 % | 478 | `sustained_latency` (2,00 s) | 0,60 | 1,92 | 359 |
| sujetos=1, supersede 10 % | 403 | `sustained_latency` (2,05 s) | 0,47 | 1,74 | 254 |

**Lectura falsable**: ninguna celda alcanzó las 600 escrituras bajo el
umbral de 2 s sostenidos; el techo práctico de la vía gobernada en esta
máquina ronda las ~400–480 revisiones. Consistente con el eje revisiones
del issue (0,472 s/commit medio a 400 revs en sonda interna; la vía
gobernada añade el coste de plan). **P1 (watermark) y P2d (commit en lote
gobernado) son prerrequisito para escalas mayores**, como anticipó el
propio issue. El eje sujetos no escala la escritura (472 vs 478).

## 2. Columna diagnóstica interna (`MemoryStore.commit`, etiquetada)

A 20.000 registros (42 revs aprox., sujetos indicados):

| Medida | 200 sujetos | 1 sujeto |
|---|---:|---:|
| `snapshot` s | 0,126 | 0,119 |
| `context_view limit=50` s | 0,442 (**ok**) | 4,080 (`view_subject_exceeds_budget`) |

- `retrieve` término común scan 0,212 s; término raro scan 0,215 s; término
  raro **índice 0,210 s** — el FTS no acelera `retrieve`: confirma el
  hallazgo F4 del issue (paridad diagnóstica #118, no rendimiento).
- `context_view` es **bimodal por sujetos**: con sujetos pequeños pagina y
  responde; con un único sujeto gigante deriva todo y cae en
  `view_subject_exceeds_budget` — el régimen que la sonda origen midió como
  3,2–5,1 s. Ambos regímenes son oficiales ahora.
- Disco 3,7 MB a 20k **pre-índice** (la sonda del issue reportó 35 MB con
  índices FTS construidos: diferencia de método, declarada).

## 3. Concurrencia (4 escritores / 8 lectores, 60 s)

| Métrica | Valor |
|---|---:|
| `LockBusyError` total | **0** |
| Conflictos CAS (`write_plan_base_changed`) | 399 |
| Escrituras gobernadas OK | 139 |
| p50 por escritor s | 0,35–0,39 |
| Rondas de lectura (scan×2 + context_view) | 275 |

El cuello no es el lock (nunca se agota el deadline de 10 s): es el CAS por
revisión base — ~74 % de los intentos de escritura chocan bajo 4 escritores
competidores. Reproducido en dos corridas (439/172 en la superseded).

## 4. Crash mid-commit (SIGKILL sembrado ×10)

`verify` OK tras cada kill (10/10); `recover` OK al final. El par
journal/CURRENT sobrevive mataduras duras del escritor en proceso.

## 5. Compactación gobernada (400 revs; desviación declarada)

Issue pedía ~20.000 revs — inalcanzable pre-P1 (ver §1). A 400 revs:

| Paso | s |
|---|---:|
| export create | 3,2 |
| compact plan (con restore-proof) | 69,9 |
| compact commit | 73,5 |

`verify` OK en la revisión 401 post-epoch; `snapshot` **0,299 → 0,057 s
(5,2×)** tras compactar. El directorio crece 8,2→11,4 MB porque conserva
bundle y plan de la ceremonia (artefactos, no store).

## 6. Notas de instrumentación (lecciones de esta corrida)

- Corridas 1 y 2 invalidadas por bugs de la batería (targets de supersede
  no vigentes; `--bundle` omitido; régimen único de sujetos; muerte dura
  del padre durante compact plan con resultados sólo-en-memoria). Corrida 1
  conservada como `20261014-154916-superseded`; las correcciones viven en
  `536e281`, `f6d2eac`, `b6cc8e8`, `6646669`. Persistencia inmediata por
  escenario desde entonces.
- La re-corrida parcial de compaction fusionó su resultado en este
  directorio sin fragmentar la oficial.

## 7. Conclusión contra los criterios del issue

- Batería en el repo con resultados versionados y umbrales previos
  escritos: **cumplido** (commit `54efb65` anterior a toda corrida).
- Resultados que empeoran el baseline reportados igual: cumplido (el
  índice no acelera; la vía gobernada aborta bajo umbral).
- Próximo paso según el plan del informe origen: Fase 1 (#140, diseño de
  una sola interfaz de resolver) y Fase 2 (P1 watermark + P2 acceso
  índice-primero y lote gobernado), ahora con línea base oficial.
