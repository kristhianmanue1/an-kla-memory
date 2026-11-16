# ADR-0064: Recuperar hechos con una orden nueva, léxica, ponderada y determinista

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-11-16
- **Decide sobre:** la orden aditiva de CLI `recall`, que recupera hechos
  por relevancia léxica ponderada (BM25 sobre texto plegado y reducido a su
  raíz), con ámbito de repo, anotación de disputas, escritor y hora del
  sobre y estado de la bandeja, sin cambiar `retrieve`.

## Contexto

E1.b del esfuerzo de memoria agéntica: recuperar los hechos que E1.a
(ADR-0063) ya guarda en una llamada. El conjunto dorado
`memoria/evaluacion/v1` (contrato externo, congelado el 2026-11-15) mide 15
consultas de hechos sobre un corpus de 40. Con `retrieve` sin cambios
(`main@af07590`, perfil `scan-fallback/v1`, reproducido con el medidor del
contrato): **12 de 15** entre los cinco primeros y **5 de 15** en primer
lugar. Fallan `q-h01`, `q-h03` y `q-h05`. El umbral de E1.b es ≥ 14 de 15 y
ninguna pérdida pareada frente a la línea base.

**Diagnóstico medido** (reproducción de la puntuación de `retrieve`, que
coincide con la línea base archivada en los cinco primeros de las 15):

- La puntuación es `len(query_terms & record_terms)`
  (`an_kla/retrieval.py:205`). Una palabra vacía vale lo mismo que una rara.
  En `q-h01` el primero gana sólo con «a, para, que, un». En `q-h05` empatan
  25 hechos con 1 punto, y el esperado lo tiene por su único término raro
  (df = 1).
- No hay raíz: la flexión verbal y el número no casan («lanzo»/«lanza»,
  «modelo»/«modelos»).
- No hay plegado de diacríticos: los términos son `casefold()` de `[\w]+`
  (`retrieval.py:35, 44-45`).
- **Causa no prevista:** `\w` incluye `_`. Un identificador técnico como
  `NOMBRE_CONFIG` es un único término y no casa con «configuración» (`q-h03`).
- Los empates se resuelven por id (`retrieval.py:208`), sin criterio útil.
- **A escala empeora:** con el corpus de 40 más 400 párrafos reales de
  relleno (definido en «Medición»), `retrieve` baja a **11 de 15**.

**Restricciones.**
- `retrieve`, sus perfiles, sus goldens beta.35 y el MCP no cambian.
- Local, determinista y sin modelo: ni LLM ni embeddings.
- Sólo biblioteca estándar.
- Lecturas puras (ADR-0047 §4): leer no vacía la bandeja (ADR-0063 D1).
- No ajustar al examen: ninguna regla puede escribirse mirando las 15
  consultas. Las 10 reservadas del contrato las mide el orquestador sobre el
  commit candidato.

## Decisión

Añadir la orden `recall`, que **no comparte puntuación con `retrieve`**, con
este analizador y esta puntuación, versionados juntos como
`an-kla/lexico-es-v1`:

### Analizador `an-kla/lexico-es-v1` (puro, determinista)

1. **Plegado:** `casefold()`, NFKD y descarte de las marcas combinantes
   (categoría `Mn`). «facturación» = «facturacion».
2. **Corte:** los términos son las secuencias maximales de letras o dígitos
   (`[^\W_]+` en `re.UNICODE`). `_`, `-`, `.`, `/` y todo signo cortan, así
   que un identificador técnico se parte en sus palabras.
3. **Raíz:** el algoritmo **Snowball para español** (publicado, sin datos),
   aplicado al término ya plegado, con sus listas de sufijos escritas sin
   tilde. «puertos» = «puerto»; «lanzo» = «lanza». Sólo se reduce un término
   alfabético de 3 o más letras; los dígitos y los mixtos quedan tal cual.
   Plegar antes de reducir hace que el texto escrito sin tildes y el escrito
   con ellas den la misma raíz. El precio es apartarse de la salida de
   referencia de Snowball donde la tilde distinguía un sufijo. Se mide y se
   declara (ver «Test de regresión»).
4. **Sin lista de palabras vacías.** Las frecuentes las descuenta el peso
   por rareza, medido sobre el propio store (ver «Por qué no»).

### Puntuación

- **BM25** con los parámetros estándar `k1 = 1,2` y `b = 0,75`, sin
  ajustar. IDF = `ln(1 + (N − df + 0,5) / (df + 0,5))`.
- `N`, `df` y la longitud media se calculan sobre el **conjunto candidato**:
  los registros vigentes de los streams buscados dentro del ámbito.
- Los términos de la consulta se deduplican conservando el orden.
- Orden total: puntuación exacta descendente y después `id` ascendente.
- La salida lleva `score` redondeado a 6 decimales. El orden se decide con
  el valor sin redondear.
- Un registro con puntuación 0 no se devuelve.

### Orden `recall`

```
an-kla [--project-root P] [--store-root S] recall --query <texto>
       [--budget <bytes>] [--scope repo|all] [--streams facts[,episodes]]
```

- **Streams:** `facts` por defecto (allí guardan `remember --kind fact` y
  `decision`); `episodes` (`--kind state`) a petición.
- **Ámbito (`--scope`, por defecto `repo`):**
  - el `repo.id` C0 del `--project-root` se deriva como lo hace `remember`
    (`identity_c0.repo_id_for`);
  - entra un registro cuyo sobre válido declara ese `repo.id`, y un
    registro sin sobre válido (legado), marcado `scope_match: "legacy"`,
    porque vive en el store del proyecto y no declara otro repo;
  - se excluye y se cuenta (`excluded.scope`) un registro con sobre de otro
    repo;
  - `--scope all` lo incluye todo y marca cada resultado con su repo;
  - sin repo Git en `--project-root`, `--scope repo` falla con
    `recall_scope_unavailable` (rc 1, pista `--scope all`). **Nunca degrada
    en silencio a `all`.**
- **Presupuesto (`--budget`, por defecto 4000):** cota de la **salida JSON
  completa** (UTF-8, tal como se imprime), no sólo de los textos.
  - Se añaden resultados en orden mientras la salida serializada quepa. Uno
    que no cabe se salta y se cuenta (`excluded.budget`), y se sigue con el
    siguiente.
  - Si ni la respuesta vacía cabe: `recall_budget_too_small`, rc 1.
- **Respuesta `an-kla/recall-result-v1`**, de claves ordenadas, sin espacios
  sobrantes y terminada en un salto de línea:

```json
{"schema": "an-kla/recall-result-v1", "untrusted_memory_data": true,
 "revision": "sha256:…", "analyzer": "an-kla/lexico-es-v1",
 "query": "…", "scope": {"mode": "repo", "repo_id": "…"},
 "streams": ["facts"], "budget_bytes": 4000, "used_bytes": 1234,
 "inbox": {"state": "present", "pending": 2, "inflight": 0},
 "excluded": {"budget": 0, "scope": 3},
 "results": [{"rank": 1, "id": "…", "stream": "facts", "score": 7.214311,
   "text": "…", "writer": {…C0…} | null, "enqueued_at": "…" | null,
   "scope_match": "repo" | "legacy" | "other",
   "disputed_by": [{"id": "…", "text": "…", "writer": {…} | null,
                    "enqueued_at": "…" | null}],
   "disputes": {"stream": "…", "target_id": "…"} | null}]}
```

- `writer` y `enqueued_at` salen del sobre (`an_kla_envelope`) sólo si es
  válido (`identity_c0.validate_envelope`); si no, `null`.
- **Disputa (D3 de ADR-0063):**
  - un hecho con registros de disputa vigentes que lo apuntan sale como
    vigente, con `disputed_by` (la misma selección que `disputes list`);
  - un registro de disputa que aparece como resultado lleva `disputes`;
  - las disputas no cambian la puntuación de nadie.
- **Bandeja:** `inbox` sale de `inbox.read_status` (sólo nombres, sin
  candado y sin crear nada). Informa de cuántas escrituras están pendientes
  o en vuelo y **no las busca**: una escritura cuenta cuando está
  comprometida. `recall` nunca llama al vaciado.
- **Lectura:** bajo el gate compartido de lectores (`shared_reader_gate`),
  igual que `retrieve`, sobre un snapshot de `CURRENT`.
- **Determinismo:** misma consulta, mismos argumentos, misma revisión y
  mismo estado de la bandeja ⇒ mismos bytes. La bandeja es la única parte
  que puede cambiar sin cambio de revisión, y se declara.
- **Errores:** JSON en stderr con el formato de error del CLI y rc 1
  (`recall_query_empty` si la consulta no deja términos tras el corte,
  `recall_budget_too_small`, `recall_scope_unavailable`,
  `unsupported_recall_stream`). Errores del store: los de siempre.

### Índice

No hay índice persistente en esta entrega. Cada consulta recorre el
snapshot y calcula `df` en memoria, así que no hay nada derivado que pueda
faltar o quedarse viejo, ni degradación posible. Coste medido en
«Consecuencias». Un índice futuro es otro ADR, con la regla «se reconstruye
o falla con aviso, nunca degrada en silencio».

### Superficie

- `recall` se añade a `--help`, `capabilities` y `schema list`, con
  `recall-result-v1` en `an_kla/schemas/`. Son cambios aditivos.
- Ninguna salida existente cambia.
- `retrieve`, `mcp.py`, `AGENTS.md` y `AN-KLA.md` no se tocan. La
  documentación para agentes del bloque gestionado es E1.c.

## Medición

Hecha con un prototipo puro que reproduce exactamente esta puntuación sobre
el corpus del contrato. Es la evidencia de que no hacen falta vectores; la
implementación se mide de nuevo con el medidor del contrato.

- **Desarrollo:** las 15 consultas de hechos del contrato, aciertos por id
  entre los cinco primeros.
- **Corpus ampliado** (informativo, sin umbral): los 40 hechos más **400
  párrafos de relleno**, que son los primeros 400 párrafos de prosa de
  80–400 caracteres de `docs/**/*.md` de este repo, en orden de ruta. Se
  excluyen los que empiezan por `#`, `|`, `>` o una cerca de código.
  - Son reales, del mismo dominio, públicos y reproducibles, en proporción
    × 10.

**Ablación**, cada componente medido. «T» es plegado y corte, «R» raíz,
«V» lista de palabras vacías Snowball (español e inglés), «P» casar por
prefijo de 5 letras y «B» BM25. «pos» es la posición del esperado por
consulta (0 = fuera de los cinco):

| Variante | 40: top-5 | 40: 1.º | 440: top-5 | 440: 1.º | Pierde frente a la base |
|---|---|---|---|---|---|
| `retrieve` (hoy) | 12 | 5 | 11 | 5 | — |
| B | 15 | 7 | 13 | 7 | `q-h07`, en 440 |
| T+B | 15 | 8 | 13 | 8 | `q-h07`, en 440 |
| **T+R+B (decidida)** | **15** | **9** | **15** | **9** | **ninguna** |
| T+R+P+B | 15 | 10 | 15 | 9 | ninguna |
| V+B | 14 | 9 | 13 | 9 | `q-h07` |
| T+V+R+B | 14 | 11 | 14 | 12 | `q-h14` |
| T+V+R+P+B | 14 | 12 | 14 | 12 | `q-h14` |

- **Decisión:** el conjunto mínimo de reglas que pasa el umbral en los dos
  corpus sin pérdidas, que es T+R+B.
- **P no entra:** su ganancia es un primer puesto en 40 y ninguna en 440, y
  añade casamientos falsos posibles entre familias léxicas distintas. Queda
  como deuda medible.
- **V no entra:** ver «Por qué no».
- **Reservadas:** no se han visto. Si T+R+B no sostiene la mejora sobre
  ellas, la entrega no pasa (decisión del orquestador).

## Por qué no

- **Cambiar `retrieve`.** Sus salidas son contrato público con goldens byte
  a byte y consumidores (MCP incluido). Una orden nueva se puede medir,
  versionar y retirar sin tocar a nadie.
- **Lista de palabras vacías.** Medido: toda variante con lista pierde una
  consulta que la base acertaba, porque la lista borra palabras que en un
  hecho sí distinguen («otro» en «otro agente»; «no», «sin»).
  - El IDF de BM25 ya descuenta lo frecuente y lo mide en el store real, en
    cualquier idioma: los hechos mezclan español, inglés e identificadores.
  - Una lista es una regla de idioma fija; el IDF es una propiedad del
    corpus.
- **Embeddings o LLM.** Prohibidos en esta entrega, y la medición muestra
  que no hacen falta para el umbral.
- **Sinónimos.** Ajustarían al examen y no se justifican por el idioma.
- **Usar el índice FTS5 existente.** Su tokenizador no pliega con raíz
  Snowball ni corta `_` igual, y su ausencia o vejez ya degradó en silencio
  una medida de la línea base. Recorrer el snapshot elimina esa clase de
  fallo; el coste medido es aceptable a este tamaño.
- **Snowball con tildes, tal cual la referencia.** El texto sin tildes («configuracion»)
  y el acentuado darían raíces distintas, y rompería la prueba
  «facturación»/«facturacion».
- **Prefijo (P).** Ver «Medición».

## Consecuencias

- **Positivas:**
  - consultas en lenguaje natural sin la penalización de palabras vacías;
  - flexión y tildes resueltas;
  - identificadores técnicos encontrables;
  - resultado con autor, hora, disputa y bandeja;
  - salida acotada de verdad, no sólo en el texto.
- **Negativas:**
  - recorrido lineal por consulta: O(tokens del ámbito). Se mide en la
    implementación con 440 registros y con 10.000 sintéticos y se declara;
    si un store real lo excede, el índice es el siguiente ADR;
  - Snowball no une todas las familias («revise»/«revisor»);
  - con `b = 0,75`, un hecho corto con un término raro puede ganar a uno
    largo que trata el tema por extenso: es el sesgo conocido de BM25.
- **Neutras:**
  - la puntuación de `recall` y la de `retrieve` no son comparables;
  - el ranking cambia si se añaden hechos, porque el IDF depende del
    conjunto: es la semántica de BM25 y se declara.

## Test de regresión

Pruebas nuevas en `tests/test_recall*.py`:

1. **Forma:**
   - «puertos» encuentra «puerto» y «facturación» encuentra «facturacion»,
     en los dos sentidos, con un corpus propio (no el dorado);
   - `NOMBRE_CONFIG` casa con «configuración»;
   - mismo ranking con y sin tildes en la consulta.
2. **Analizador frente a la referencia Snowball:**
   - una muestra declarada del vocabulario de referencia del algoritmo
     (licencia BSD, con su origen);
   - se mide y se fija la tasa de coincidencia `stem(fold(w)) ==
     fold(referencia(w))`; las discrepancias deben ser todas de plegado.
3. **Determinismo:**
   - dos invocaciones, mismos bytes;
   - orden total con empates exactos resuelto por `id`.
4. **Presupuesto:**
   - `len(stdout) ≤ --budget` para presupuestos de 0 a 20.000 en saltos;
   - `recall_budget_too_small` por debajo de la respuesta vacía.
5. **Ámbito:**
   - repo propio, legado y ajeno con `repo` y con `all`;
   - `recall_scope_unavailable` sin Git, sin degradar.
6. **Disputa:** el hecho disputado sale vigente con `disputed_by`, y el de
   la disputa con `disputes`, por el CLI real tras `remember --supersedes`.
7. **Bandeja:**
   - con entradas pendientes, `recall` informa de su número;
   - `CURRENT` y el listado `(ruta, tamaño, mtime_ns, sha256)` de
     `memory/inbox/` quedan idénticos tras 10 `recall`.
8. **Sobre:** `writer` y `enqueued_at` de un `remember`; `null` en legado y
   en sobre inválido.
9. **No regresión:**
   - los goldens beta.35 de `retrieve` y del MCP pasan sin tocarlos;
   - `retrieval.py` y `mcp.py` sin diff.

## Referencias

- ADR-0063 (escritura en una llamada, sobre C0, disputa, bandeja).
- ADR-0047 §4 (lecturas puras).
- ADR-0015 (orden determinista de `retrieve`).
- Contratos externos: `memoria/identidad/v1` (C0) y `memoria/evaluacion/v1`
  (conjunto dorado, puntuador y medidor).
- Robertson y Zaragoza, «The Probabilistic Relevance Framework: BM25 and
  Beyond» (2009).
- Algoritmo Snowball para español (snowballstem.org).
