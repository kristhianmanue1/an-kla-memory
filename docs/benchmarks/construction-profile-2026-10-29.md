# Perfilado acotado AN-KLA — 2026-10-29

Resultado: priorizar diseño de reducción de recorridos de identidad y descubrimiento transaccional; no activar caché de segmentos (#169) con esta evidencia.

## Artefacto y método

- Checkout: main@14b69f5fcc41ae257588afdd7c2a8a4326f689e8, sin modificaciones.
- Python 3.12.12; macOS 27.2 arm64 (platform reportada por el proceso).
- Script reproducible: `probe.py`; ejecución desde el checkout con `.venv/bin/python /private/tmp/ankla-profile-20261029/probe.py`.
- Dos stores nuevos e independientes: plain y profiled; mismo constructor de la batería (`internal_commit`, primitiva interna no gobernada), un registro y una revisión por commit, sin índice FTS. No se usa el store canónico.
- Objetivo 20.000 revisiones; presupuesto diagnóstico 90 s por construcción, corte SIGALRM dentro del escenario. No se alteraron umbrales oficiales. Cinco snapshots sin profiler en cada punto de 100 revisiones; tramos consecutivos de 100 commits. El profiler sólo está activo durante los commits de la segunda corrida.
- Plain: 566 commits confirmados, 90,003 s; profiled: 506, 90,003 s. Un commit adicional interrumpido puede haber alcanzado alguna fase persistente en cada store efímero: no se reintentó ni recuperó. Ver `read-only-checks.json` para CURRENT y verificación tras el corte.
- Son corridas diagnósticas, no resultados oficiales all-v2 ni prueba de compactación a 20k. El script no ejecuta compactación.

## Crecimiento observado sin profiler

| Revisiones | Tiempo acumulado s | Commit medio del tramo s | Snapshot mediano s (5 muestras) |
|---:|---:|---:|---:|
| 100 | 1,932 | 0,0191 | 0,00354 |
| 200 | 7,732 | 0,0577 | 0,00685 |
| 300 | 19,445 | 0,1166 | 0,01034 |
| 400 | 38,386 | 0,1886 | 0,01511 |
| 500 | 66,111 | 0,2764 | 0,01732 |

La construcción crece mucho más deprisa que el snapshot en este rango. No se ajusta ni extrapola una duración de 20k a partir de cinco puntos. Los datos crudos son `plain.jsonl`, `profiled.jsonl` y sus JSON finales. El profiler añade overhead (500 revisiones: 87,48 s frente a 66,11 s); sus porcentajes son atribución instrumentada, no tiempos absolutos de producción.

## Atribución del coste

Perfil acumulado: 89,734 s; incluye parte del último intento interrumpido. Estas filas son ramas distintas; las subfilas citadas después NO se suman otra vez.

| Rama | Segundos acumulados | Fracción del total instrumentado |
|---|---:|---:|
| mutation_preflight (principalmente identity_status) | 63,222 | 70,5 % |
| _manifest_candidates | 13,116 | 14,6 % |
| snapshot | 8,957 | 10,0 % |

Dentro de identidad: valid_identity_receipt 47,093 s; _is_ancestor 30,928 s (incluye llamadas desde distintas rutas); validate_bound_descendants 15,433 s. identity_status también recorre hacia la raíz. Estas cifras se solapan y no forman una partición.

La validación de cadena del snapshot vía watermark consume sólo 0,00523 s acumulados en validate_revision_chain. P1 ya está funcionando en este escenario. La lectura de segmentos ocupa 7,407 s dentro del snapshot.

Persistencia separada: primitivas storage_primitives.atomic_write 1,011 s y write_immutable 0,730 s acumulados (no se suman a ciegas con otras ramas; puede haber anidamiento). Las 20.240 llamadas a posix.fsync consumen 0,273 s propios, 0,30 % del total. No hay evidencia aquí para priorizar eliminar fsync ni relajar durabilidad. Los números no prometen el mismo coste en otro hardware o bajo presión de disco.

## Corrección: frontera de linaje

`identity_evidence._is_ancestor` y `validate_bound_descendants` limitan el recorrido a `range(10000)`. Control con un objeto sintético que proporciona una cadena en memoria, sin store en disco:

- 9.999 enlaces: ancestor=true y descendants aceptado (control positivo).
- 10.000 y 20.000 enlaces: ancestor=false y store_identity_lineage_mismatch.

Evidencia: `lineage_control.py`, `lineage-control.json`. Esto demuestra la frontera de esas funciones; no equivale a una ejecución integrada de 20k commits. En la ruta de identidad actual es un riesgo concreto para ese objetivo y debe abordarse junto con el rendimiento, sin simplemente elevar o quitar límites de seguridad.

## Elección de optimización y criterios

1. Prioridad: diseñar validación de identidad que evite múltiples recorridos completos repetidos; consolidar comprobaciones en un recorrido es la primera alternativa a estudiar. Cualquier verificación incremental adicional exige un anclaje y una frontera de confianza explícitos: no se presupone que reutilizar el watermark sea seguro para identidad.
2. Segundo frente: evitar barrer y decodificar todos los manifiestos para descubrir candidatos de cada transacción nueva. Diseñar localización verificable y fallback de recuperación, conservando detección de candidatos ambiguos, huérfanos, replay y binding conflictivo. No basta con omitir el scan si no hay journal.
3. Sólo tras medir esas mejoras, evaluar el coste residual de snapshots y el disparador de #169. Ninguna de las cinco muestras por punto llegó a 0,5 s. El disparador no se observó hasta 500 revisiones; queda sin determinar en regímenes mayores o de producción.
4. Mantener 20.000 revisiones reales como aceptación de compactación, una por commit en la construcción de este escenario. Lotes de registros, cambiar la meta o compactar durante la preparación probarían otra condición.
5. Antes de código: diseño/ADR aplicable y revisión adversarial fresca; después suite previa requerida, controles de integridad/identidad/recuperación y gates, comparación acotada a igual N y posterior corrida oficial bajo umbrales aprobados.

## Refutación y límites

- La hipótesis inicial de que el snapshot domina queda refutada en el rango observado: identidad y descubrimiento transaccional dominan el perfil.
- Los snapshots medidos no activan #169, pero no refutan que el umbral aparezca más adelante.
- Consolidar recorridos puede mejorar constantes sin resolver todo el crecimiento: manifiestos acumulativos y lecturas históricas conservan costes que deben medirse después. No se promete que baste para 20k.
- La ruta medida es la construcción interna usada por compaction-large; no es latencia de escritura gobernada CLI ni de un store postcompactación. Ambas rutas requieren validación posterior.
- Autor y revisión: agente principal, con historial de esta conversación; autocuestionamiento mediante ramas del perfil y control positivo/negativo de linaje. No hubo revisor con contexto separado y no se afirma independencia.
- Veredicto: proceed para diseñar la optimización descrita; no autoriza implementación, commit, push, publicación ni actualización de memoria.

Estado del encargo: OK, perfilado y elección de prioridad entregados. La compactación a 20k permanece como criterio futuro, sin afirmar que pasó. El informe y los datos quedan en /private/tmp y no son custodia durable ni documentación canónica.

Comprobación posterior de sólo lectura: CURRENT quedó exactamente en las revisiones 566 y 506 confirmadas; verify completo devolvió ok=true en ambos stores (1,113 s y 0,904 s). Esto verifica las revisiones vigentes, no acredita ausencia de objetos huérfanos del intento interrumpido. No se ejecutó recover ni se reintentó ninguna operación.

## Preservación para revisión documental

Este informe describe la corrida anterior al diseño, sobre el HEAD citado.
Ahora se conservan junto al diseño copias de los JSON finales y las sondas
originales en [evidence/construction-profile-20261029/](evidence/construction-profile-20261029/),
además del perfil textual. El binario `.prof` y los stores siguen sólo en tmp;
las referencias anteriores a archivos sueltos designan el directorio temporal.
No se afirma custodia durable fuera del checkout mientras no se publique.

Para reproducir, copiar la sonda fuera del repo y cambiar únicamente `OUT`
a un directorio efímero **nuevo** y la ruta de checkout si procede. El script
original usa un destino fijo y `mkdir()` sin `exist_ok`: no reejecutarlo sobre
el destino ya existente ni borrar los stores para forzar el reintento.

SHA256 de fuentes originales: `probe.py` =
`a3fb69177d5fc44a35ac7b07e68595089a69678598eab0ece1db4439abe3cd8c`;
`lineage_control.py` =
`831b0389d87a32524b86b38441f7faa45a23a7a987b5e08c0f67c14ac640586f`.
Cambiar OUT altera el digest; conservar y declarar esa diferencia al reproducir.
