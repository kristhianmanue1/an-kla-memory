# ADR-0064: Recuperar hechos con una orden nueva, léxica, ponderada y determinista

- **Estado:** Aceptada por delegación del orquestador (mandato de E1.b:
  el ADR se fusiona con su `proceed`), 2026-11-16, tras dos rondas
  adversariales de otra familia (Gemini): r1 `fix-and-retry` (4 HIGH,
  2 MEDIUM, 1 LOW, corregidos) y r2 `proceed`.
- **Implementación:** No iniciada
- **Enmienda 1:** 2026-11-16, recencia, stub y explicación (ver «Enmienda 1»).
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
3. **Raíz:** el programa **canónico de Snowball para español**
   (snowballstem.org), con **dos cambios declarados y sólo dos**:
   1. Opera sobre el término ya plegado: los sufijos de los pasos 0
      (pronombre enclítico), 1 (sufijo estándar) y 2a (verbo en `y`) se
      comparan en su forma plegada (`acion`, `logia`, `ucion`, `iendo`).
   2. En los pasos 2b (verbo) y 3 (residual) **se omiten los sufijos que en
      la referencia llevan tilde** (`ía`, `ían`, `ías`, `ió`, `ís`, `í`,
      `aría`, `ería`, `iría` y sus formas, `éis`, `áis`, `íais`, `ábamos`,
      `íamos`, `áramos`, `iéramos`, `iésemos`, `ásemos`). Plegados chocarían
      con terminaciones nominales átonas que la referencia no toca
      (historia, criterio, crisis, taxi).

   Todo lo demás es el programa canónico:
   - regiones RV, R1 y R2 marcadas una vez, al principio;
   - en cada `among`, el sufijo más largo;
   - en los pasos 2a y 2b, el más largo **dentro de RV** (`setlimit tomark pV`);
   - en el paso 0, la desinencia verbal que precede al pronombre debe empezar
     en RV;
   - si el paso 1 halla sufijo pero falla su región, se intentan 2a y 2b.

   Sólo se reduce un término alfabético de 3 o más letras; los dígitos y los
   mixtos quedan tal cual. «puertos» = «puerto» y «lanzo» = «lanza».

   **Medido contra el vocabulario de referencia de Snowball** (28.378
   palabras):
   - coincide **exactamente en las 22.894 palabras sin tilde**;
   - en total coincide en el 95,60 % (`stem(fold(w)) == fold(ref(w))`);
   - las 1.250 discrepancias son todas de palabras con tilde, por el cambio 2
     (p. ej. `abarcaría` → `abarcari`, frente a `abarc` en la referencia).
4. **Sin lista de palabras vacías.** Las frecuentes las descuenta el peso
   por rareza, medido sobre el propio store (ver «Por qué no»).
5. **Interrogativos, sólo en la consulta.** De la consulta, no de los
   registros, se quitan los interrogativos de la gramática, una clase
   cerrada:
   - español: qué, quién, quiénes, cuál, cuáles, cuánto, cuánta, cuántos,
     cuántas, cómo, dónde, adónde, cuándo;
   - inglés: what, who, whom, which, how, where, when, why;
   - se comparan plegados, así que también caen «que», «como», «cuando» y
     «donde» de la consulta.

   **Razón:** una pregunta marca su tipo con ellos y un hecho es
   declarativo. Con un store pequeño, un interrogativo que aparezca por azar
   en un único hecho tendría el IDF máximo y lo subiría sin relación con la
   pregunta (riesgo señalado por la ronda 1). **Medido:** no cambia el top-5
   en ningún corpus y cambia primeros puestos en los dos sentidos (ver
   «Medición»). Se adopta por la razón gramatical, no por la medida.

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
- Con el conjunto candidato vacío (`N = 0`) o sin ningún término (longitud
  media 0), la respuesta lleva `results: []` y no se calcula nada.

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
  - entra un registro cuyo sobre es válido (`identity_c0.validate_envelope`)
    y declara ese `repo.id` (`scope_match: "repo"`);
  - entra un registro **sin campo `an_kla_envelope`**, el legado anterior a
    E1.a (`scope_match: "legacy"`): vive en el store del proyecto y no
    declara otro repo;
  - se excluye un registro con sobre válido de otro repo (cuenta en
    `excluded.scope`);
  - **se excluye un registro con `an_kla_envelope` presente e inválido**
    (cuenta en `excluded.invalid_envelope`): no se sabe de qué repo es, y
    asimilarlo a legado lo colaría en el ámbito;
  - `--scope all` lo incluye todo y marca cada resultado: `repo` o `other`
    con sobre válido, `legacy` sin sobre e `invalid_envelope` con sobre
    inválido (en todos, `writer: null` si el sobre no es válido);
  - sin repo Git en `--project-root`, `--scope repo` falla con
    `recall_scope_unavailable` (rc 1, pista `--scope all`). **Nunca degrada
    en silencio a `all`.**
- **Presupuesto (`--budget`, por defecto 4000):** cota de la **salida JSON
  completa** (UTF-8, tal como se imprime), no sólo de los textos.
  - El algoritmo es exacto y no puede pasarse. Se recorren los candidatos
    en orden. Para cada uno se serializa la respuesta **completa, con su
    salto de línea final**, tal como quedaría si se añadiera, con dos cotas
    superiores en lugar de los contadores aún desconocidos:
    - `used_bytes` = el valor de `--budget`, que tiene al menos tantas
      cifras como el real;
    - `excluded.budget` = candidatos aún no incluidos, que sólo puede bajar.
  - Si esa serialización cabe, el candidato entra; si no, se salta y se
    sigue con el siguiente.
  - La respuesta final, con los contadores reales, mide lo mismo o menos que
    la última comprobada.
  - `used_bytes` es la longitud real de la salida impresa, salto incluido.
  - Si ni la respuesta vacía cabe con esas cotas: `recall_budget_too_small`,
    rc 1.
  - `rank` es la posición en el orden total, contada sobre todos los
    candidatos, no sobre los entregados: un hueco en `rank` muestra un
    resultado saltado por presupuesto.
- **Respuesta `an-kla/recall-result-v1`**, de claves ordenadas, sin espacios
  sobrantes y terminada en un salto de línea:

```json
{"schema": "an-kla/recall-result-v1", "untrusted_memory_data": true,
 "revision": "sha256:…", "analyzer": "an-kla/lexico-es-v1",
 "query": "…", "scope": {"mode": "repo", "repo_id": "…"},
 "streams": ["facts"], "budget_bytes": 4000, "used_bytes": 1234,
 "inbox": {"state": "present", "pending": 2, "inflight": 0},
 "excluded": {"budget": 0, "invalid_envelope": 0, "scope": 3},
 "results": [{"rank": 1, "id": "…", "stream": "facts", "score": 7.214311,
   "text": "…", "writer": {…C0…} | null, "enqueued_at": "…" | null,
   "scope_match": "repo" | "legacy" | "other" | "invalid_envelope",
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
  candado y sin crear nada).
  - Informa de cuántas escrituras están pendientes o en vuelo y **no las
    busca**: una escritura cuenta cuando está comprometida.
  - `recall` nunca llama al vaciado.
  - `state` es el de `read_status`:
    - `present`, con `pending` e `inflight` enteros;
    - `absent` (store sin bandeja), con `0` y `0`;
    - `unsafe` (raíz o subdirectorio inseguro), con `null` en el conteo
      afectado. Nunca falla la consulta por la bandeja.
- **Lectura:** bajo el gate compartido de lectores (`shared_reader_gate`),
  igual que `retrieve`, sobre un snapshot de `CURRENT`.
- **Determinismo:** misma consulta, mismos argumentos, misma revisión y
  mismo estado de la bandeja ⇒ mismos bytes. La bandeja es la única parte
  que puede cambiar sin cambio de revisión, y se declara.
- **Errores:** JSON en stderr con el formato de error del CLI y rc 1
  (`recall_query_empty` si la consulta no deja términos tras el corte,
  `recall_budget_too_small`, `recall_scope_unavailable`,
  `unsupported_recall_stream`). Errores del store: los de siempre.

### Enmienda 1 (2026-11-16): recencia, el mejor no desaparece, explicación

Pedida por la primera medición de uso real de un consumidor (16 consultas
de reanudación): ninguno de sus fallos era morfológico. Estos tres cambios
entran en `recall-result-v1` antes de su primera publicación. **Prevalecen
sobre lo anterior** donde chocan. No cambian el conjunto dorado: el corpus
se carga sin sobre y con presupuesto holgado.

1. **La recencia desempata** (criterio de orden declarado). El orden total
   pasa a ser:
   - puntuación exacta descendente;
   - después, `enqueued_at` descendente: es el `enqueued_at` del sobre
     válido, una cadena de formato fijo (`AAAA-MM-DDTHH:MM:SS.ffffffZ`), así
     que su orden lexicográfico es el cronológico; un registro sin sobre
     válido va detrás de todos los que lo tienen;
   - después, `id` ascendente.

   Sólo actúa con puntuaciones exactamente iguales y no cambia ninguna
   puntuación. Es determinista porque usa un dato persistido, no el reloj.
2. **El presupuesto no hace desaparecer a un resultado que cabría
   resumido.**
   - Cuando la entrada completa de un candidato no cabe, se prueba su
     **stub**:
     `{"rank", "id", "stream", "score", "enqueued_at", "scope_match",
     "matched_terms", "truncated": true}`, sin `text`, `writer` ni
     `disputed_by` (con `"disputed": true|false` en su lugar).
   - Si el stub cabe, entra; si no, se salta como antes.
   - Las entradas completas llevan `"truncated": false`.
   - `excluded` gana `truncated`, el número de stubs entregados;
     `excluded.budget` cuenta sólo los que no entraron ni como stub.
   - Cota superior del algoritmo de presupuesto, que reemplaza a las dos
     anteriores para los contadores que dependen del recorrido: en las
     serializaciones de prueba, `excluded.budget` y `excluded.truncated`
     valen ambos el número total de candidatos, que acota sus valores
     finales. `used_bytes` sigue acotado por `--budget`.
   - Así el mejor resultado sólo falta si ni su stub cabe, y entonces
     tampoco cabe nada.
3. **Explicación y umbral opcional.**
   - La respuesta lleva `query_terms`: los términos de la consulta tras el
     analizador (plegados, reducidos, sin interrogativos ni duplicados), en
     orden.
   - Cada resultado, completo o stub, lleva `matched_terms`: los de
     `query_terms` presentes en el registro, en ese orden.
   - Nueva opción `--min-terms <n>` (entero ≥ 1, por defecto 1, que es el
     comportamiento anterior): un candidato con menos de `n` términos
     distintos de la consulta presentes se excluye (`excluded.min_terms`).
   - La respuesta lleva `no_strong_match`, que vale `true` si y sólo si
     había candidatos con puntuación mayor que 0 y ninguno alcanzó
     `--min-terms`.
   - El umbral es una cuenta de términos de la consulta, no una puntuación
     BM25: no depende del tamaño del store y no hay constante que ajustar.
     El valor lo elige quien consulta.

**Queda para la entrega siguiente (E1.d, «estado y anclas»):**
- los filtros `--kind`, `--since`/`--until`, `--agent` y `--status`,
  `--status superseded` incluido;
- la casilla de estado (`kind: state` con `slot`);
- la regla de que un `state` no sustituye un `fact` ni una `decision`;
- `history <id>`;
- `valid_until`;
- las anclas.

Los filtros cambian el conjunto candidato y, por tanto, el IDF, así que se
diseñan junto con la casilla de estado.

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

**Ablación**, cada componente medido con el stemmer ya validado. «T» es
plegado y corte, «R» raíz, «Q» interrogativos fuera de la consulta, «V»
lista de palabras vacías Snowball (español e inglés), «P» casar por prefijo
de 5 letras y «B» BM25. «Pierde» compara con los aciertos de la línea base
del contrato:

| Variante | 40: top-5 | 40: 1.º | 440: top-5 | 440: 1.º | Pierde |
|---|---|---|---|---|---|
| `retrieve` (hoy) | 12 | 5 | 11 | 5 | `q-h10` en 440 |
| B | 15 | 7 | 13 | 7 | `q-h07`, `q-h10` en 440 |
| T+B | 15 | 8 | 13 | 8 | `q-h07` en 440 |
| T+R+B | 15 | 9 | 15 | 10 | ninguna |
| **T+R+Q+B (decidida)** | **15** | **8** | **15** | **11** | **ninguna** |
| T+R+P+B | 15 | 9 | 15 | 10 | ninguna |
| V+B | 14 | 9 | 13 | 9 | `q-h07` |
| T+V+R+B | 14 | 11 | 14 | 12 | `q-h14` |
| T+V+R+P+B | 14 | 12 | 14 | 12 | `q-h14` |

- **Decisión:** T+R+B es el conjunto mínimo de reglas que pasa el umbral en
  los dos corpus sin pérdidas, más Q por su razón gramatical (punto 5 del
  analizador).
- **P no entra:** con el stemmer validado no gana nada sobre T+R+B, y
  añade casamientos falsos posibles entre familias léxicas distintas.
- **V no entra:** ver «Por qué no».
- **Reservadas:** no se han visto. Si la mejora no se sostiene sobre ellas,
  la entrega no pasa (decisión del orquestador).

**Medidor.** `medir_ankla.py` del contrato sólo llama a `retrieve`. Para
medir `recall` hace falta una opción `--orden recall`, que llame a `recall
--scope all` (el proyecto desechable no es un repo Git) con el mismo
presupuesto y que aborte si la respuesta no es `recall-result-v1` con este
analizador. El contrato no es de este repo: se propone al custodio como
errata, sin editarlo.

## Por qué no

- **Cambiar `retrieve`.** Sus salidas son contrato público con goldens byte
  a byte y consumidores (MCP incluido). Una orden nueva se puede medir,
  versionar y retirar sin tocar a nadie.
- **Lista de palabras vacías completa.** Medido: toda variante con lista pierde una
  consulta que la base acertaba, porque la lista borra palabras que en un
  hecho sí distinguen («otro» en «otro agente»; «no», «sin»).
  - El IDF de BM25 ya descuenta lo frecuente y lo mide en el store real, en
    cualquier idioma: los hechos mezclan español, inglés e identificadores.
  - Una lista es una regla de idioma fija; el IDF es una propiedad del
    corpus.
  - La excepción es Q: una clase gramatical cerrada, sólo en la consulta,
    que no borra nada de los registros.
- **Embeddings o LLM.** Prohibidos en esta entrega, y la medición muestra
  que no hacen falta para el umbral.
- **Sinónimos.** Ajustarían al examen y no se justifican por el idioma.
- **Usar el índice FTS5 existente.** Su tokenizador no pliega con raíz
  Snowball ni corta `_` igual, y su ausencia o vejez ya degradó en silencio
  una medida de la línea base. Recorrer el snapshot elimina esa clase de
  fallo; el coste medido es aceptable a este tamaño.
- **Snowball con tildes, tal cual la referencia.** El texto sin tildes
  («configuracion») y el acentuado darían raíces distintas, y rompería la
  prueba «facturación»/«facturacion».
- **Snowball plegado con todos los sufijos plegados.** Sobre-reduce nombres
  átonos (`criterio` → `criter`, `taxi` → `tax`). Por eso existe el cambio 2.
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
   - una muestra fija y declarada del vocabulario de referencia
     (`snowball-data`, licencia BSD de 3 cláusulas, con su origen y su
     licencia junto a la muestra);
   - toda palabra sin tilde de la muestra coincide exactamente;
   - toda discrepancia de la muestra es una palabra con tilde;
   - nombres átonos sin sobre-reducir (`criterio`, `crisis`, `taxi`), y
     enclíticos fuera de RV sin cortar (`darme`, `verlo`).
3. **Determinismo:**
   - dos invocaciones, mismos bytes;
   - orden total con empates exactos resuelto por `id`.
4. **Presupuesto:**
   - `len(stdout) ≤ --budget` y `used_bytes == len(stdout)` para cada
     presupuesto de 1 en 1 alrededor de los cambios de cifras (99/100,
     999/1000, 9999/10000) y en saltos hasta 20.000;
   - un hueco en `rank` cuando se salta un resultado;
   - store vacío y consulta sin coincidencias: `results: []`;
   - `recall_budget_too_small` por debajo de la respuesta vacía.
5. **Ámbito:**
   - repo propio, legado, ajeno y sobre inválido, con `repo` y con `all`;
   - un registro de otro repo con sobre corrupto nunca entra en `repo`;
   - `recall_scope_unavailable` sin Git, sin degradar.
6. **Disputa:** el hecho disputado sale vigente con `disputed_by`, y el de
   la disputa con `disputes`, por el CLI real tras `remember --supersedes`.
7. **Bandeja:**
   - con entradas pendientes, `recall` informa de su número;
   - store sin bandeja (`absent`) y bandeja insegura (`unsafe`): la consulta
     responde;
   - `CURRENT` y el listado `(ruta, tamaño, mtime_ns, sha256)` de
     `memory/inbox/` quedan idénticos tras 10 `recall`.
8. **Sobre:** `writer` y `enqueued_at` de un `remember`; `null` en legado y
   en sobre inválido.
9. **No regresión:**
   - los goldens beta.35 de `retrieve` y del MCP pasan sin tocarlos;
   - `retrieval.py` y `mcp.py` sin diff.
10. **Enmienda 1:**
    - con puntuación igual, el más reciente primero, y el legado detrás;
    - un mejor resultado mayor que el presupuesto sale como stub en `rank` 1
      con `truncated: true`;
    - `matched_terms` y `query_terms` exactos en un vector propio;
    - `--min-terms 2` sobre un corpus en que todo casa con un solo término da
      `results: []` y `no_strong_match: true`;
    - `--min-terms 1` da los mismos bytes que sin la opción.

## Referencias

- ADR-0063 (escritura en una llamada, sobre C0, disputa, bandeja).
- ADR-0047 §4 (lecturas puras).
- ADR-0015 (orden determinista de `retrieve`).
- Contratos externos: `memoria/identidad/v1` (C0) y `memoria/evaluacion/v1`
  (conjunto dorado, puntuador y medidor).
- Robertson y Zaragoza, «The Probabilistic Relevance Framework: BM25 and
  Beyond» (2009).
- Algoritmo Snowball para español (snowballstem.org).
