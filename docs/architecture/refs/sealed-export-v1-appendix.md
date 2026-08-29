# Apéndice técnico — ADR-0042 (`sealed-export/v1`)

> **Estado:** contenido normativo de detalle del ADR-0042, separado de la
> decisión por el gate de tamaños (#95). La norma vinculante vive en
> [`../0042-sealed-export-v1.md`](../0042-sealed-export-v1.md); las secciones
> `§N` conservan aquí su numeración original — este apéndice desglosa las
> reglas congeladas fila a fila y el ADR corto las declara en resumen.
> En caso de divergencia aparente, manda el ADR; reportar el desajuste
> como defecto documental, no resolverlo editando una sola de las dos
> partes.

## §1 Algoritmo y librería — detalle

- **AEAD: AES-256-GCM** vía `cryptography.hazmat.primitives.ciphers.aead.AESGCM`.
  Único candidato viable en la librería elegida sin bindings de bajo
  nivel (XChaCha20 descartado por precisión de la ronda de decisión).
- **KDF: HKDF-SHA256** de la misma librería para todas las derivaciones.
  **Subclaves separadas por propósito** (separación de dominio vía
  `info`); la CEK raíz **nunca** se usa como clave AES directa:
  `aead_key = HKDFExpand(CEK, b"aead-key", 32)` (única clave AES-GCM),
  `bundle_id_raw = HKDFExpand(CEK, b"bundle-id", 16)`,
  `mac_key = HKDFExpand(CEK, b"manifest-mac", 32)`. Usar `HKDFExpand`
  sin extract es correcto aquí porque la CEK ya es uniforme
  (RFC 5869 §3.3). El nonce **no se deriva**: es un contador puro (§6).
  Sin crypto manual.
- **CEK — generación y ciclo de vida (F1, custodia precisa)**: 32 bytes
  del CSPRNG del SO (`os.urandom`), una por bundle. **El core genera y
  mantiene temporalmente** la CEK y sus subclaves (`aead_key`,
  `bundle_id_raw`, `mac_key`) en memoria del proceso: cifra, calcula el
  MAC y las descarta al terminar la operación. Durante `wrap`, **la CEK
  viaja al adaptador por stdin local** (y sólo entonces); durante
  `unwrap`, regresa por stdout del adaptador. **El core no serializa ni
  escribe intencionalmente la CEK ni las subclaves** en bundle, staging,
  logs, warnings ni resultados (separación congelada abajo, F7). La
  **custodia de la capacidad de wrap/unwrap es exclusiva del adaptador**:
  su KEK, clave privada, passphrase, Keychain, KMS o equivalente — **ese
  material de custodia jamás entra al core**. **Persistencia, separación
  congelada (F7)**:
  - **CEK y subclaves** (`aead_key`, `bundle_id_raw`, `mac_key`):
    material **secreto** que el core no serializa ni escribe
    **intencionalmente** en bundle, staging, logs, warnings ni
    resultados;
  - **`wrapped_cek`**: el **único artefacto persistente destinado a
    recuperar la CEK**;
  - **`bundle_id` y `manifest_mac`**: valores derivados de la CEK que
    **también persisten** (en el manifiesto), pero **no son material
    secreto ni permiten recuperar la CEK** (salidas unidireccionales de
    HKDF/HMAC).

  El claim "el core nunca persiste claves en disco" queda **acotado a
  escritura intencional**: swap, hibernación, crash dumps y copias del
  runtime (fork, snapshots de VM, backups de memoria) quedan **fuera de
  la garantía** y constan en §Límites del ADR. **Riesgo residual
  explícito**: borrar objetos Python no garantiza zeroization física de
  memoria; la CEK puede permanecer en copias/buffers hasta que el
  runtime/SO recuperen esa memoria. El modelo de amenaza cubre al
  lector del bundle en destino, no a un adversario con acceso al
  proceso vivo.
- Extra: `[sealed]` → `cryptography>=42`. Sin el extra instalado, toda
  operación de sellado falla con `sealing_extra_not_installed` (§5);
  nada del camino v1 se importa con dependencia nueva.

## §2 Schemas y perfiles v2 — detalle

- `an-kla/export-manifest-v2`: `{schema, profile:
  "sealed-export/v1", seal, core, manifest_sha256}` donde
  - `seal = {algorithm: "aes-256-gcm", kdf: "hkdf-sha256",
    adapter_id, wrapped_cek, bundle_id, manifest_mac}`,
  - `core` y `manifest_sha256` mantienen **shape y semántica exactos de
    v1** (mismo `core` con entradas `{path, size, content_sha256}` en
    claro; `manifest_sha256 = digest_json(core)`), para que la
    verificación estructural sin clave funcione sin caso especial.
    **Nota correctiva**: la `compaction-restore-proof-v1` de ADR-0028
    **no** opera sobre bundles v2 — el lector de compactación los
    rechaza (§3); ningún claim de compatibilidad con ella se hace,
  - `wrapped_cek` es el blob opaco del adaptador (string); `bundle_id`
    y `manifest_mac` en §6.
- `an-kla/export-result-v2` (create sellado): incluye **`bundle_id` y
  `manifest_sha256`** como ancla de comparación fuera de línea
  (§Límites del ADR, hallazgo H3 de la ronda) más `warnings`.
- `an-kla/export-restore-result-v2` (restore sellado): **schema propio**
  — `restore-result-v1` es cerrado y no admite el warning
  `sealed_export_untrusted_memory_data` (§7); reutilizarlo exigiría
  romper su contrato. Mismos campos que v1, warning sellado.
- `an-kla/export-verify-result-v2` (§8).
- `wrapped_cek`: **base64**, longitud máxima **4096 caracteres** en el
  schema normativo (blob del adaptador acotado; sin superficie de bloat).
- **Los cinco schemas nuevos** — `export-manifest-v2`,
  `export-result-v2`, `export-restore-result-v2`,
  `export-verify-result-v2`, `sealing-adapter-contract-v1` (el contrato
  stdio del §4, normativo para que un tercero lo implemente sin leer
  código) — se empaquetan en `docs/schemas/` + `an_kla/schemas/`.

## §2 Gramática CLI congelada

- `export create --bundle RUTA --seal sealed-export/v1 --key-adapter
  COMANDO` — el valor de `--seal` es un enum cerrado de un elemento; sin
  `--seal` el camino es exactamente `export/v1`.
- **`--key-adapter` argv sin shell, congelado**: el caller provee
  **ejecutable separado + argumentos repetibles**
  (`--key-adapter bin --key-adapter-arg arg1 --key-adapter-arg arg2 …`,
  o equivalentemente un valor tipo lista en la API); el core construye
  `argv = [bin, *args]` y lo ejecuta **sin shell** con el runner acotado
  del §4. **Prohibido** aceptar un string con espacios y hacer split:
  el separador es estructural (flag repetible), no sintáctico.
- **`backup`**: **no existe** como subcomando en el dispatch actual
  (verificado: sólo la palabra aparece en el help de `export`). Si se
  quiere un alias `backup create --seal` es **superficie nueva pendiente
  de implementación**, no herencia; esta decisión no lo crea. El sellado
  vive sólo bajo `export` (y `restore`), y cualquier alias futuro será
  azúcar sobre esa misma superficie con ADR/orden propios.
- `capabilities().storage.export_restore` gana
  `sealing: {profiles: ["export/v1", "sealed-export/v1"] /* perfiles de
  la superficie export_restore, sellados o no */, extra: "[sealed]",
  adapter_required: true}`.

## §3 Compatibilidad y restauración de plaintext v1 — detalle

- `export/v1` **no cambia**: mismo comando por defecto, mismo warning,
  mismos schemas. Ningún consumidor actual se rompe.
- Un bundle v1 en claro **sigue siendo restaurable para siempre** por
  cualquier binario ≥ su versión (política: sin deprecación anunciada de
  v1 en esta decisión; retirar soporte exigiría ADR propio).
- Un bundle sellado **jamás** es restaurable por el camino v1: su
  `profile` y schema de manifiesto difieren y el lector lo rechaza.
  **Nota de versión (honestidad)**: en beta.17 y anteriores el lector
  v1 —que no conoce el perfil— responde `export_manifest_invalid`
  (rechazo genérico de manifiesto); `unsupported_export_profile` es el
  código del **dispatcher dual nuevo** que esta decisión introduce
  (elige camino por `profile` del manifiesto y falla si se le pide v1
  contra un v2, o ante perfil desconocido). Ambos fallan cerrado; el
  código específico sólo existe desde la versión que implementa esta
  decisión. La ausencia de downgrade es estructural, no de disciplina
  (§5).
- `restore` sellado exige extra + adaptador; tras desencriptar, la
  verificación semántica (`verify_semantic_store`), `no overwrite` y
  `no merge` quedan **idénticos** a v1.
- `content_sha256` se calcula **siempre sobre el plano**: el manifiesto
  v2 registra los hashes del contenido original, no del ciphertext.
- **Compactación exige bundle v1 en claro** (decisión conservadora de la
  ronda pre-code, **ratificada por el maintainer** en el fix-and-retry
  documental): el flujo de ADR-0028 valida y restaura el bundle con el
  lector v1, que rechaza el manifiesto v2. Un bundle sellado no sirve
  como insumo de `compact plan/commit` — el sellado es superficie de
  **respaldo**, no de compactación. Habilitar compaction sellado exigiría
  adaptador en `plan/commit` y cambia el contrato vigente: ADR propio si
  algún día se pide.
- **Stop rule derivada**: un consumidor cuya política prohíbe producir
  respaldos plaintext **no puede compactar** hasta que exista un
  contrato separado de compactación sellada. No hay ruta intermedia:
  compactación y "nunca en claro" son incompatibles bajo esta decisión,
  y elegir entre ellas es política del consumidor, no un defecto del
  contrato. (Matiz: una política "sin plaintext **en reposo**" podría
  teóricamente compactar produciendo el v1 en almacenamiento efímero —
  tmpfs — y destruyéndolo tras la prueba; el contrato exige *producir*
  un v1 claro, no conservarlo: la interpretación es de la política del
  consumidor.)

## §4 Adaptador externo de claves — contrato stdio y runner acotado

Proceso externo invocado por el CLI con contrato JSON por stdio
(`an-kla/sealing-adapter-contract-v1`), dos operaciones:

- `wrap`: recibe `{"op":"wrap","cek_b64":...}`, devuelve
  `{"wrapped_cek": "<blob opaco>", "adapter_id": "<id estable>"}`;
- `unwrap`: recibe `{"op":"unwrap","wrapped_cek":...}`, devuelve
  `{"cek_b64":...}`.

Reglas congeladas — comportamiento del protocolo:

- El core trata `wrapped_cek` como opaco: nunca lo interpreta. Eso
  permite Keychain, `age`, KMS, YubiKey o passphrase sin que AN-KLA
  conozca ninguno.
- El comando del adaptador lo provee el caller (`--key-adapter`);
  **ningún texto recuperado de memoria puede proponerlo** (frontera base).
- Adaptador ausente → `sealing_adapter_required`. Adaptador que devuelve
  basura, crashea o excede timeout → `sealing_adapter_error`,
  **antes de escribir nada en destino**; cero bundle parcial (definición
  precisa abajo, F6).
- `adapter_id` se registra en el manifiesto para diagnóstico, nunca como
  autoridad: no valida nada por sí mismo.
- **Qué significa "cero bundle parcial" (F6, corregido en Ronda 4)**: el
  **destino publicado** jamás queda a medias — se materializa íntegro o
  no existe, mediante escritura en **staging hermano + renombrado
  atómico** al final. **Precisión de atribución**: ese patrón
  staging+renombrado es el de **restore** v1; `create` v1 escribe
  directo en destino y limpia sólo on-exception — el **create sellado
  es deliberadamente más fuerte que el create v1** y exige staging
  propio. El **staging temporal** se elimina best-effort en toda salida,
  incluidas las de error. **No se promete ausencia absoluta de restos
  tras crash o pérdida de energía**: sin un protocolo de recuperación no
  existe esa garantía. En la ventana crash-entre-staging-completo-y-
  renombrado, el staging huérfano **es un bundle completo verificable**
  — la promesa acotada es: nunca un **destino** publicado parcial; un
  staging huérfano completo puede existir y verificar. **Memoria/buffers
  del proceso** y **proceso del adaptador** quedan fuera de esta
  promesa: la CEK existe en memoria durante la operación y el adaptador
  se termina según el runner, pero su estado interno no es observable
  por el core.

Reglas congeladas — **ejecución segura** (añadidas por el
fix-and-retry documental):

- **argv estructurado, sin shell, con runner acotado**: el core ejecuta
  `argv = [bin, *args]` sin shell — jamás `sh -c`, sin interpolación,
  sin expansión del entorno shell. La ejecución **no se congela sobre
  `subprocess.run`** (acumularía salida ilimitada antes de que el core
  la inspeccione): exige un **runner basado en `Popen` o equivalente**
  con lecturas incrementales y acotadas, según los límites de abajo.
- **JSON cerrado**: la petición y la respuesta son un único objeto JSON
  por stdio con conjunto de claves **exacto** por operación
  (`wrap` → in `{op, cek_b64}` / out `{wrapped_cek, adapter_id}`;
  `unwrap` → in `{op, wrapped_cek}` / out `{cek_b64}`); cualquier clave
  extra, ausente o de tipo incorrecto es `sealing_adapter_error`.
- **base64 canónico** (alfabeto estándar, con padding) para `cek_b64` y
  `wrapped_cek`; la CEK decodificada debe ser **exactamente 32 bytes**
  o es `sealing_adapter_error`.
- **Límites de I/O aplicados por el runner, no por inspección
  posterior**: stdin limitado a 8 KiB (la petición más grande posible +
  margen), stdout a 64 KiB, stderr a 8 KiB, **leídos incrementalmente**
  con terminación inmediata del árbol al superarlos; exceder cualquier
  límite es `sealing_adapter_error`. El contenido de stderr **se
  descarta**: nunca se propaga a la salida de error de AN-KLA ni al
  resultado (podría filtrar secretos o rutas del host del adaptador).
- **Timeout total**: 30 s por invocación; al expirar, terminación del
  árbol y `sealing_adapter_error`.
- **Higiene del proceso (congelada en Ronda 4)**: cierre de todos los
  pipes, reap del proceso y **terminación del grupo/árbol, no sólo del
  padre** — POSIX: grupo propio y señal al grupo, con escalada
  **TERM → 2 s de gracia → KILL**; Windows: terminación de árbol (Job
  Object o equivalente). `close_fds=True` (sólo stdio conectado). La
  terminación del árbol es **best-effort**: un descendiente que haga
  `setsid()` escapa del kill de grupo en POSIX — el runner permanece
  acotado de todos modos (pipes cerrados, proceso padre reapado, límites
  ya cumplidos). **Garantía precisa (F8)**: "ningún proceso residual"
  significa **ningún proceso _gestionado_ residual** — el adaptador y
  los descendientes que permanezcan en el grupo/Job Object controlado
  por el runner; los escapes por `setsid()`/breakaway quedan fuera de
  esa garantía, como riesgo residual, y no se promete que el core pueda
  eliminarlos. La garantía fuerte y separada de publicación (ningún
  **destino publicado** parcial) es independiente de ésta. stdout y
  stderr se leen **concurrentemente** (select/threads): un adaptador
  verboso en stderr no puede bloquear la lectura de stdout ni
  viceversa.
- **Semántica de salida**: exit status ≠ 0 → `sealing_adapter_error`
  **aunque el JSON de stdout sea válido**; el éxito exige exit 0 y JSON
  cerrado válido. Los payloads de error del core **jamás embeben**
  stdout ni stderr del adaptador (sólo el hecho y el código).
- **Resolución del ejecutable**: se recomienda **ruta absoluta** en
  `--key-adapter`; una ruta relativa resuelve contra el `PATH` del
  entorno mínimo (confianza declarada: quien controla ese PATH controla
  qué binario corre).
- El límite de stdin (8 KiB) se garantiza **pre-vuelo por schema**
  (`wrapped_cek` ≤ 4096 chars b64), no por el runner: la petición más
  grande posible ya cabe; se declara para no dejarlo al lector.
- **Política de entorno — mínima con allowlist** (F3): el adaptador
  **no hereda** el entorno del proceso AN-KLA (que puede contener
  secretos del host). El core construye un **entorno mínimo** (`PATH` y
  localización básica) y añade exclusivamente las variables cuyo
  **nombre** el operador declaró en una allowlist explícita para
  credenciales del adaptador (p. ej. `--key-adapter-env VAR`). Sin
  allowlist, sin variables extra. **Nunca** valores secretos en argv,
  logs, warnings ni resultados; la allowlist viaja en la invocación y
  no se persiste.

## §6 Nonce, AAD y autenticación del manifiesto — detalle

- **Nonce por entrada = contador puro**, congelado al byte:
  `nonce_i = i.to_bytes(12, "big")` con `i` el índice **0-based** en el
  orden canónico de `core.entries` (la serialización del manifiesto).
  La construcción es **inyectiva por dominio**: `i` está acotado por
  `max_files = 100000` y la codificación big-endian de 12 bytes es
  inyectiva en todo `0 ≤ i < 2⁹⁶ ≫ 10⁵` — el dominio cabe con margen
  abrumador. El nonce **no necesita ser secreto**
  (GCM lo trata como valor público) y **no se deriva criptográficamente**:
  bajo una misma `aead_key` — exclusiva del bundle — dos entradas no
  pueden compartir nonce porque no pueden compartir índice. **La
  separación entre bundles no es propiedad del nonce**: procede íntegra
  de la independencia de `aead_key` (una CEK aleatoria nueva por bundle;
  reusar el mismo valor de contador en bundles distintos es
  irrelevante bajo claves distintas — salvo colisión de CEK, §Límites
  del ADR).
- **AAD por entrada**: `UTF8("sealed-export/v1") || bundle_id ||
  canonical_json(entry)` — reordenar entradas, intercambiarlas entre
  bundles o injertar una de otro export falla al desencriptar, como
  chequeo estructural del propio AEAD, no como validación aparte que
  alguien pueda omitir.
- **`bundle_id`**: `bundle_id_raw = HKDFExpand(CEK, b"bundle-id", 16)`
  (§1); se almacena **hex** en `seal` y entra al AAD como sus **16 bytes
  crudos** (longitud fija: elimina toda ambigüedad de concatenación con
  el prefijo de perfil). En toda verificación autenticada se
  **recalcula desde la CEK y se compara**: el valor del manifiesto no se
  confía, se comprueba.
- **Layout físico congelado**: el ciphertext vive en `entries/<path>`
  — exactamente la misma ruta que en v1 —; el nonce **jamás se escribe
  en disco** (es el contador del índice); el archivo físico mide
  `entry.size + 16` bytes (tag GCM). Un tamaño físico ≠ `size + 16` se
  reconcilia así (F5): en **verify/restore autenticado** es
  `sealed_payload_auth_failed` — sin distinguir tamaño, tag, clave o
  corrupción (sin oráculo); en **verify sin clave** degrada
  `structure_verified` a `false` con diagnóstico estructural cerrado
  (§8), jamás intenta desencriptar ni afirmar autenticidad.
- **Techo explícito por entrada**: AESGCM de `cryptography` limita el
  plaintext a 2³¹−1 bytes por operación. `sealed-export/v1` fija
  **`max_entry_bytes = 512 MiB` (2²⁹)** por entrada — holgado frente a
  los objetos reales del store (segmentos JSON) y muy por debajo del
  límite de la librería — y una entrada que lo exceda falla cerrado con
  `sealed_entry_too_large` (se suma al enum §5). **Sin chunking en este
  hito**: partir entradas exigiría rediseñar AAD/nonce por fragmento y
  queda expresamente fuera de alcance.
- **Límites heredados declarados**: el camino sellado hereda los topes
  de v1 (`max_files=100000`, `max_bytes=10 GiB`); 10 GiB = 2³³ bytes ≈
  2²⁹ bloques AES deja el límite de falsificación GCM en ≈2⁻⁷⁰ — margen
  amplio. "Millones de entradas" queda excluido por el tope de 100k.
  La seguridad **entre** bundles descansa en que dos CEKs aleatorias de
  32 bytes no colisionen (probabilidad ≈2⁻²⁵⁶ por par: despreciable,
  no cero). Los nonces, al ser contadores puros, **se repiten entre
  bundles por diseño** (todo bundle usa 0,1,2,…): eso es seguro porque
  cada bundle cifra bajo su propia `aead_key`; la única relación
  peligrosa sería una CEK repetida, no un nonce repetido. Ninguna
  garantía absoluta de unicidad global se afirma.
- **`manifest_mac`**: `HMAC-SHA256(mac_key, canonical_json(T))` con
  `mac_key = HKDFExpand(CEK, b"manifest-mac", 32)` (§1) y `T` el
  **transcript canónico completo del manifiesto**:
  `{schema, profile, seal_sin_manifest_mac, core, manifest_sha256}` —
  autentica TODO, incluido `seal` (`algorithm`, `kdf`, `adapter_id`,
  `wrapped_cek`, `bundle_id`), no sólo `core`. Cierra el hueco que
  ADR-0027 declara: quien reescribe el bundle entero — incluso
  sustituyendo `wrapped_cek` — no pasa la verificación autenticada sin
  la CEK correcta. `manifest_sha256` (digest sin clave) se conserva para
  el camino estructural.
- **Encoding y comparación de `manifest_mac`**: se almacena y compara
  como **hex minúsculo de 64 caracteres** (32 bytes HMAC-SHA256); la
  comparación en verificación es **constante en tiempo**
  (`hmac.compare_digest`) — jamás `==` sobre el digest; el transcript
  `T` se reordena/serializa siempre por `canonical_json` antes de
  MAC/verificar, sin campos opcionales.
- **`adapter_id` — etiqueta opaca con gramática cerrada** (F4,
  corregido): ASCII puro, patrón `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$` —
  **1 a 64 bytes** (bytes = code points; NFC retirada como redundante),
  sensible a mayúsculas, con `.`/`_`/`-` como únicos separadores, y
  **`.` y `..` rechazados** expresamente (evita confusión visual aunque
  nunca se interpreten como paths). **La garantía es semántica, no
  sintáctica**: `adapter_id` es una etiqueta de diagnóstico y el core
  **jamás** la pasa a `Path`, `open`, `exec`, shell, resolución de
  archivos ni selección de adaptador — nunca se interpreta como ruta, y
  ésa es la seguridad real; la gramática sin `/` `\` `:` sólo reduce
  confusión visual (un valor como `foo` seguiría siendo interpretable
  como ruta relativa en otro contexto: por eso el claim "no puede ser
  ruta" está retirado). Incumplimiento de gramática →
  `sealing_adapter_id_invalid` (metadato público: sin oráculo sobre
  claves). El core valida antes de escribir el manifiesto.

## §7 Fugas residuales — detalle

- **Fuga aceptada y declarada — alcance exacto (F5, corregido)**: el
  manifiesto v2 va en claro y las rutas del bundle revelan más que
  "digests content-addressed": el layout v1 incluye **nombres
  estructurales fijos** (`entries/anchor/…`, `refs/CURRENT` y otros
  refs), **categorías de objetos** (checkpoints, revisiones, segmentos,
  catálogos de compactación, transacciones), **UUIDs de transacción**
  cuando forman parte de la ruta, y digests cuando aplican. En conjunto,
  el manifiesto expone: conteo y tamaños; tipos/categorías de objetos;
  **estructura relativa del store**; identificadores digest/UUID por
  ruta; y **patrón de crecimiento y actividad** del corpus. **No**
  expone rutas absolutas del host — pero sí metadatos suficientes para
  inferir composición y actividad. Es el precio de la verificación
  estructural sin clave; un hipotético `sealed-export/v2` podría sellar
  también el manifiesto a costa de perderla. No es algo que este diseño
  resuelva.
- **No-reproducibilidad declarada**: la CEK es aleatoria → un bundle
  sellado no es byte-reproducible entre corridas. Lo que se preserva y
  se prueba: `core` idéntico entrada a entrada (se calcula sobre el
  plano) y el **store restaurado byte-idéntico**.

## §8 Verify sin clave — mapeo de diagnósticos estructurales

`diagnostics` es un **enum estructural cerrado** del schema, con
**mapeo completo y congelado** de cada chequeo estructural (Ronda 4):

| Chequeo estructural (sin clave) | Código en `diagnostics` |
|---|---|
| Shape de manifiesto, keys, perfil, `manifest_sha256` vs core | `manifest_invalid` |
| Tamaño físico ≠ `entry.size + 16` | `entry_size_mismatch` |
| Entrada listada sin archivo | `entry_missing` |
| Archivo sin entrada en lista | `entry_unexpected` |
| Path fuera de `entries/`, links, traversal | `unsafe_path` |
| `entry_count`/`total_bytes` no cuadran | `count_mismatch` |

Opcional, sólo presente con `structure_verified: false`, y **jamás**
afirma nada criptográfico: el camino sin clave no desencripta ni
autentica nada, en ningún caso.

## §9 Matriz de pruebas — detalle fila a fila

Pruebas congeladas (amplían §9 del issue #46; numeración cerrada):

1. **F1 — inyectividad del contador**: recorrer **todo** el dominio
   permitido `0..99999` y demostrar **100000 nonces distintos, todos de
   exactamente 12 bytes** (`i.to_bytes(12,"big")`); más la prueba
   negativa: bundles distintos con los mismos valores de contador son
   seguros porque cambian `aead_key` (la separación NO se prueba sobre
   el nonce);
2. ciphertext alterado en 1 byte → `sealed_payload_auth_failed`, sin
   restauración parcial;
3. CEK incorrecta → `sealed_payload_auth_failed` (indistinguible de
   corrupción);
4. `manifest_mac` alterado con `content_sha256` cuadrando → falla
   cerrado;
5. entrada movida entre bundles del mismo store → falla por AAD;
6. **F2 — runner acotado**: adaptador ausente/basura/timeout →
   `sealing_adapter_required` / `sealing_adapter_error`; además:
   (6a) stdout infinito → terminación del árbol y
   `sealing_adapter_error`;
   (6b) stderr infinito → ídem, y el contenido jamás aparece en el
   resultado; (6c) proceso que excede los 30 s → ídem; (6d)
   descendiente que conserva pipes abiertos **dentro del
   grupo/Job Object** → terminado con el grupo, runner no queda
   colgado; (6e) tras cada fallo: **ningún proceso *gestionado*
   residual** — gestionado = proceso adaptador y descendientes que
   permanezcan en el grupo/Job Object controlado por el runner — y
   **ningún destino publicado parcial** (staging best-effort, F6);
   (6f) **caracterización del escape**: un descendiente POSIX que hace
   `setsid()` (o breakaway del Job Object en Windows) **escapa de la
   terminación** — el test lo caracteriza (proceso vivo tras el fallo)
   sin prometer que el core pueda eliminarlo; el runner **siempre**
   cierra sus pipes, reapea al padre y retorna acotadamente;
7. roundtrip sellado preserva `CURRENT`, identidad, snapshots,
   refutaciones y outcomes (store restaurado byte-idéntico);
8. `verify` sin clave jamás devuelve `verified: true`;
9. `verify` autenticado detecta reescritura completa del bundle;
10. downgrade: dispatcher dual frente a sellado pidiendo v1 **o perfil
    desconocido** → `unsupported_export_profile`; y lector **beta.17**
    (sin dispatcher dual) frente a sellado → `export_manifest_invalid`
    (nota §3); sellado sin extra/adaptador → fail-closed, nunca claro;
10b. entrada > `max_entry_bytes` → `sealed_entry_too_large` antes de
     cifrar; sin bundle parcial;
10c. **F5 — tamaño físico ≠ `size+16`**: autenticado →
     `sealed_payload_auth_failed` (sin distinguir causa); sin clave →
     `structure_verified:false` + `diagnostics:["entry_size_mismatch"]`,
     sin desencriptar jamás;
10d. **F3 — entorno**: el adaptador NO recibe variables del entorno
     AN-KLA fuera de la allowlist (probe con variable señuelo); ningún
     secreto en argv/logs/warnings/resultados;
10e. **F4 — `adapter_id`**: gramática ASCII cerrada (rechaza Unicode,
     vacío, >64 B, **y expresamente `.` y `..`**) →
     `sealing_adapter_id_invalid` sin bundle escrito; el core jamás lo
     pasa a `Path`/`open`/`exec` (garantía semántica);
11. bundles v1 en claro: create/verify/restore sin cambios y suite v1
    intacta sin el extra instalado;
12. compactación con bundle sellado como insumo → rechazado con
    `export_manifest_invalid` por el lector v1 vigente (corregido en
    Ronda 4: ese lector no conoce el perfil; `unsupported_export_profile`
    es del dispatcher dual nuevo): sellado es respaldo, no insumo; la
    proof sobre bundles v1 queda intacta;
12b. operación de sellado sin el extra instalado → código exacto
     `sealing_extra_not_installed` (prueba explícita, no implícita);
13. `export-result-v2` expone `bundle_id`+`manifest_sha256`; re-sellado
    con CEK ajena produce `bundle_id` distinto (visible en result y
    manifiesto: ancla manual anti re-sellado);
14. warning taxonomía exacta por perfil;
15. suite completa + CI local **sin** `[sealed]` instalado y con él;
16. **F7 — no-fuga de material secreto**: tras un create sellado, la
    CEK y las subclaves no aparecen —ni directa ni derivablemente— en
    bundle publicado, staging, stdout, stderr, warnings, resultados ni
    logs gestionados por el core (barrido del artefacto + greps de las
    representaciones hex/base64 de los bytes de CEK/subclaves);
    `bundle_id` y `manifest_mac` sí, como derivados no-secretos.
    **Alcance declarado del test**: este caso comprueba la ausencia de
    escritura intencional del core en los artefactos y canales
    enumerados; **NO puede demostrar ausencia en swap, hibernación,
    crash/core dumps ni copias del runtime/SO** — esa materialización es
    invisible a un test de proceso y queda como riesgo residual
    (§Límites del ADR).

## Referencias

- ADR-0042 (`docs/architecture/0042-sealed-export-v1.md`) — decisión y
  norma vinculante de la que este apéndice es desglose (#95).
- Issue #46 (diseño del consumidor, §§1-10) y su ronda
  (`issue-46-decision-adversarial-2026-08-20.md`); decisión del
  maintainer 2026-08-20 (opción B).
- Guía de uso: `docs/sealed-export-guide.md`.
