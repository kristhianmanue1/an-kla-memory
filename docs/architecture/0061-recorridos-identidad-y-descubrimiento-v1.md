# ADR-0061: Consolidar linaje y reutilizar proyecciones verificadas por operación

- **Estado:** Aceptada
- **Implementación:** Parcial (A/B verificadas, ronda proceed y CI local 1304 OK; aceptación integrada a 20k pendiente por presupuesto de disco)
- **Fecha:** 2026-10-29
- **Decide sobre:** reducir trabajo repetido en la construcción de revisiones sin omitir evidencia de identidad ni candidatos transaccionales.

## Contexto

El [perfil diagnóstico](../benchmarks/construction-profile-2026-10-29.md), sobre
`main@14b69f5fcc41ae257588afdd7c2a8a4326f689e8`, atribuye el 70,5 % del tiempo
instrumentado a `mutation_preflight`, el 14,6 % a `_manifest_candidates` y
el 10,0 % a `snapshot`. P1 ya está implementada (ADR-0053); no se propone
repetirla. El snapshot mediano llega a 0,01732 s a 500 revisiones; no se
observó el disparador de #169 en ese rango, ni se midió un régimen productivo.

`identity_status` recorre la historia para resolver raíz/epoch;
`valid_identity_receipt` vuelve a recorrerla para ascendencia, descendencia
ligada y CURRENT protegido. `_manifest_candidates` enumera todos los
manifiestos, incluso los no alcanzables desde CURRENT. Los objetos se
re-hashean, parsean y re-canonicalizan por cada recorrido.

Dos validadores de identidad usan `range(10000)`: un control sintético acepta
9.999 enlaces y rechaza 10.000. Es una frontera de esas funciones, no una
prueba integrada de 20.000 commits. La compactación mantiene como criterio
20.000 revisiones, sin lotes de registros ni compactaciones intermedias.

## Decisión

Aceptada por el Operador el 2026-10-29: «aceptado y autorizado», con
implementación y operaciones Git/GitHub autorizadas durante esta sesión.

Implementar en dos fases: recorrido consolidado de identidad
y reutilización de proyecciones verificadas en el descubrimiento transaccional.
Sin estado persistente nuevo, caché de filas, esquema público nuevo ni
ampliación de autoridad. No se promete complejidad constante ni alcanzar 20k
con esta optimización: manifiestos acumulativos y enumeración permanecen.

### A. Consolidación del linaje de identidad

1. Capturar un CURRENT concreto y el binding de identidad; mantener las
   comprobaciones de custodia y symlinks existentes. Las lecturas de identidad
   antes del lock y su comparación byte a byte bajo lock (ADR-0022) permanecen.
2. Antes de evaluar o aceptar cada recibo, validar forma, hash, intent, paths
   protegidos y demás evidencia independiente de ascendencia. El resumen de
   cadena puede precalcularse para resolver la raíz incluso sin recibo válido;
   ese cálculo no acepta ni eleva recibos. No se exige identidad de trazas u
   orden de I/O bajo toda intercalación concurrente. Conservar todos los candidatos,
   el orden determinista y la selección final actual; no aceptar el primero
   ni convertir un recibo malformado en evidencia de identidad completa.
3. Recorrer la cadena una vez para resolver pertenencia de cada revisión
   capturada por un recibo, continuidad del binding hasta ella y clase de raíz.
   Mantener por recibo la excepción de adopción legacy sólo en la revisión
   capturada que permite el contrato vigente; no permitir huecos intermedios.
   Acumular resumen por digest, sin guardar manifiestos completos ni sus
   listas de segmentos. El coste de metadatos es O(revisiones + recibos).
4. Sustituir el límite fijo de 10.000 por terminación estructural: IDs visitados
   sin repetición, `revision` entero no booleano y no negativo; cada enlace
   disminuye exactamente uno. Raíz ordinaria en cero; raíz de compactación
   y su epoch se validan mediante las reglas vigentes, sin exigir cero donde
   el contrato de compactación no lo exige. Missing, ciclo, transición o
   binding inválido fallan cerrados usando los errores de identidad vigentes.
5. Conservar la validación completa de la cadena v3 y pruebas de epoch que
   hoy exige `identity_status`; esta primera fase no usa el watermark como
   autoridad de identidad ni suprime esa validación. Si comparte el recorrido,
   debe ejecutar todas sus reglas; si no, puede conservar el segundo recorrido
   específico de v3. No se declara "una lectura" para toda la ruta v3.
6. Si un recibo requiere observar un CURRENT diferente del capturado al inicio,
   no reutilizar el veredicto de ascendencia del anterior. Re-evaluar ese caso
   contra el nuevo CURRENT según las comprobaciones vigentes, sin bucle de
   reintento ilimitado ni aceptar identidad por una observación obsoleta.

### B. Proyección efímera para descubrimiento, nunca índice de ausencia

Cada objeto de revisión leído y validado durante A puede aportar una
proyección interna inmutable mínima: `{digest, schema, transaction_id}`.
Sólo es elegible si digest es el identificador SHA256 validado, schema es
uno de los tres literales revision-v1/v2/v3 y transaction_id es un UUID
canónico admitido por el contrato (36 caracteres). No retener contenedores,
strings arbitrarios, revisión numérica ni listas del manifiesto. Si no cumple,
no construir proyección ni normalizar o rechazar por esa sola razón: ejecutar
la ruta completa actual. `_read_json_object` no valida esos tipos por sí solo.
Así el resumen tiene tamaño acotado por entrada; la memoria retenida es O(N)
además del manifiesto temporal máximo y los recibos ya necesarios.
Sólo se construye después de todas las comprobaciones de `_read_json_object`
(hash, parseo y canonicalidad); su ciclo de vida es **una invocación**.
No se guarda en `MemoryStore` entre operaciones ni se exporta. No se acepta
un diccionario del caller como proyección validada: construcción y consumo
quedan encapsulados en el contexto privado de esa invocación.

`_manifest_candidates` continúa enumerando TODOS los archivos de revisión,
no sólo los alcanzables. Para cada archivo:

1. Leer los bytes del archivo enumerado y verificar el digest contra su
   identificador, incluso cuando exista proyección. Un error de lectura o
   hash sigue las reglas actuales; no se sirve la proyección ante un fallo.
2. Si el digest coincide con una proyección validada en esta invocación,
   reutilizar sólo `schema` y `transaction_id` para la comparación. La misma
   identidad de contenido ancla la misma entrada de JSON canónico; no se
   confía en mtime, inode, nombre aislado ni en un digest recalculado en caché.
3. Sin proyección, ejecutar la ruta completa actual. Los manifiestos huérfanos,
   raíces y formatos legados no cubiertos por A no se omiten.
4. Conservar lista completa de candidatos, detección de ambigüedad, vínculo
   con stages/receipts/journal, replay idempotente, conflictos y orden de
   errores. La proyección no constituye permiso ni prueba de inexistencia.

Además, `transactions.candidate_relation` contiene otro tope de 10.000 pasos:
puede clasificar como `unknown` un ancestro válido más lejano. La fase B
sustituye ese techo por terminación estructural como A, conservando las
categorías `current`/`ancestor`/`orphan`/`unknown`, el aislamiento por epoch y
el fallo cerrado ante corrupción. Cadena conforme de más de 10k debe producir
`ancestor`, sin reclasificar un archivo huérfano como alcanzable. Es cambio
observable deliberado para linaje válido antes fuera del horizonte, no una
promesa de igualdad con el corte arbitrario legado. Los demás contratos se
comparan con/sin proyección sobre el MISMO algoritmo sin ese techo.

Refinamiento de la ronda sobre código: antes de devolver `ancestor` u
`orphan`, la clasificación histórica ejecuta la validación canónica completa
de la cadena, sin watermark, incluyendo la prueba de raíz v3; no puede salir
antes por haber encontrado el candidato. La igualdad `candidate == current`
sigue siendo clasificación posicional `current`, no prueba de integridad.
La auditoría histórica puede costar más; no está en el camino común del
commit nuevo (`candidate == current`) ni se promete acelerarla con la proyección.

La proyección se pasa explícitamente de preflight al commit y no puede alterar
el binding ni el gate. Bajo lock se conservan CAS y revalidación de identidad.
Un avance concurrente o cambio de epoch reduce la cobertura reutilizable;
los objetos nuevos siguen la ruta completa. La compactación y sus gates
conservan su orden vigente (ADR-0059/0060); no se añade un lock inverso.
Si esta transferencia exige ampliar un contrato público, detener la fase B
y diseñar esa versión por separado: no introducirla como campo JSON aditivo.

### Compatibilidad, seguridad y límites

- No se cambian bytes CAS, manifiestos, recibos, intents, export ni sidecars.
- Mantener detección de manipulación de bytes en cada apertura; un hash
  coincidente permite reutilizar sólo una derivación ya validada de esos bytes.
- Las comprobaciones estructurales de A pueden rechazar cadenas inválidas
  antes toleradas. Se documentará ese endurecimiento sin declararlo una nueva
  causa válida de fallo para stores producidos por escritores conformes.
- El presupuesto temporal de la sonda es externo al motor. No se sustituye
  el tope de 10k por otro que vuelva a impedir cadenas conformes de 20k.
- La evidencia de perfilado incluye commits internos ordinarios; rendimiento
  de CLI gobernado, adopción, relocate y postcompactación aún no está medido.

## Por qué no [alternativa]

- **Watermark de identidad o caché persistente:** introduciría otra frontera
  de confianza; no basta trasladar ADR-0053 a comprobaciones distintas.
- **Índice transaccional derivado y ausencia de journal como atajo:** no prueban
  inexistencia de candidatos tras crash, pérdida de sidecars o corrupción.
- **Catálogo transaccional autoritativo:** exige formato/migración/durabilidad
  nuevos; se difiere hasta medir el residuo de estas fases conservadoras.
- **Cachear manifiestos completos:** sus listas crecen con la historia;
  memoria acumulada potencialmente cuadrática. Usar sólo proyecciones pequeñas.
- **Sólo ampliar 10k o retirar fsync:** lo primero conserva un techo arbitrario;
  lo segundo relaja durabilidad sin atacar el coste dominante medido.
- **Lotes para construir 20k registros:** no producen 20k revisiones y cambian
  la condición probada por el escenario de compactación.

## Consecuencias

Se eliminan recorridos y decodificaciones redundantes, conservando el scan
transaccional y la verificación de bytes. Habrá metadatos efímeros O(N),
complejidad de control mayor y costes residuales históricos; medir cada fase
por separado antes de ampliar diseño. #169 conserva su disparador.

## Test de regresión y aceptación futura

- Suite antes de tocar almacenamiento; gates sizes/plans/adr_registry; CI local
  exigido y ronda fresca sobre el código final, además de esta ronda documental.
- Identidad: init/adopt/repair/relocate; identidad cambiada entre preflight y
  lock; varios recibos, orden y fallback; legacy permitido sólo donde aplica;
  archivos malformados, cadena corrupta/cíclica/no decreciente, parent ausente.
- Linaje: controles positivos de 9.999, 10.000 y 20.000 enlaces conformes,
  negativos de ciclos y binding ajeno; `candidate_relation` debe distinguir
  ancestro a 20k de huérfano/cadena inválida; prueba integrada separada de 20k
  revisiones reales. Un doble sintético no sustituye el criterio integrado.
- Epoch: store v3 válido, pruebas/catálogo/raíz alterados, avance de CURRENT,
  compactación concurrente y revisión archivada; no sustituir auditoría por cache.
- Proyección: con/sin ella debe producir idénticos candidatos/resultados/errores;
  objeto alterado, borrado o reemplazado tras A; recibo/intent modificado;
  proyección descartada entre invocaciones; objeto nuevo requiere ruta completa;
  schema/txid anidados o enormes no se retienen, usan fallback sin cambiar
  candidatos/errores; medir memoria con esta entrada adversarial.
- Transacciones: candidatos huérfanos únicos/ambiguos, journal ausente/corrupto,
  stages ausentes/alterados, replay, txid repetido con otro binding y crashes
  en los puntos persistentes; nunca aceptar sólo por la proyección.
- Rendimiento: comparar mismo N y datos a 100/200/300/400/500, cinco snapshots
  por punto y media del tramo, límite interno de 90 s como el diagnóstico.
  Exigir menos lecturas/parseos redundantes y mejora frente a baseline en
  repeticiones sin profiler; cuantificar residuo y no atribuir una mejora al
  disco sin separar fsync. Si no mejora, fix-and-retry, no reducir la meta.
- Aceptación final de escala: corrida oficial bajo umbrales previamente
  aprobados, construcción de **20.000 revisiones** y ceremonia completa de
  compactación, ventana de escritor, verify y recuperación. Si el presupuesto
  impide terminar, registrar resultado incompleto, sin extrapolar éxito.

## Referencias

ADR-0001, ADR-0022, ADR-0024, ADR-0028, ADR-0053, ADR-0057, ADR-0059/0060;
issues #149 (histórico), #169 (condicional).
Límite de aceptación: [cota de disco a 20k](../benchmarks/construction-manifest-bound-2026-10-29.md). [Evidencia](../benchmarks/construction-profile-2026-10-29.md).
La aceptación autoriza implementación; no publica release ni acredita pruebas futuras.
