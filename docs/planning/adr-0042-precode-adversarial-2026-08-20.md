# Ronda adversarial pre-code — ADR-0042 export sellado (2026-08-20)

ADR `docs/architecture/0042-sealed-export-v1.md` (decisión del
maintainer: **opción B** — extra `[sealed]`, criptografía auditada en
core, adaptador externo de claves). Revisor independiente con lectura
contra `export_restore.py`, `compaction.py`, `canonical.py` y
verificación de importes de `cryptography`. Dos pasadas de revisor independiente:
fix-and-retry → proceed. **Tercera pasada: fix-and-retry documental del
maintainer** (2026-08-20) con 8 correcciones de propietario, aplicadas
todas — ver "Ronda 3" abajo.

## Ronda 1 (fix-and-retry, 9 hallazgos)

| Hallazgo | Corrección aplicada al ADR |
|---|---|
| **H1 (Alta)** — layout físico del bundle sellado sin congelar (dónde vive el ciphertext, tamaño, nonce) | §6: ciphertext en `entries/<path>` (misma ruta que v1), nonce jamás en disco (derivado), archivo físico = `entry.size + 16` (tag GCM); verify estructural v2 rechaza tamaño físico ≠ `size+16` |
| **H2 (Alta)** — la compat con `compaction-restore-proof-v1` era falsa contra el código (el lector v1 del flujo de compactación rechaza el manifiesto v2) | Opción conservadora (a): compactación exige bundle v1 claro; sellado es superficie de respaldo, no insumo. Reversible por el maintainer con ADR propio. Test 12 de la matriz actualizado al rechazo esperado |
| **H3 (Alta)** — "denegación posible, falsificación no" era criptográficamente incorrecta (re-sellado con CEK ajena bajo adaptador de clave pública = takeover, no sólo DoS) | Límite reescrito: el sello da integridad bajo una clave, no atestación de origen (F8-E diferido); `export-result-v2` **debe** devolver `bundle_id`+`manifest_sha256` como ancla manual fuera de línea; tests 13 añadidos |
| H4 (Media) — serialización del índice y del KDF ambiguas | `HKDFExpand(SHA256, 12, info=b"nonce"+i.to_bytes(8,"big"))`, CEK como PRK (RFC 5869 §3.3), `i` 0-based en orden de `core.entries`; todas las derivaciones con `info` prefijado |
| H5 (Media) — codificación de `bundle_id` en el AAD sin fijar | 16 bytes crudos en AAD (longitud fija), hex en `seal` |
| H6 (Baja) — límites heredados sin declarar | Topes v1 (100k archivos / 10 GiB) declarados con margen de falsificación |
| H7 (Baja) — `wrapped_cek` sin codificación ni tope | base64, máx 4096 chars en schema normativo |
| H8 (Baja) — `backup` sin cubrir | Comparte la superficie sellada (declarado) |
| H9 (Baja) — gramática CLI sin congelar | `--seal sealed-export/v1` enum cerrado; sin flag = camino v1 exacto |

## Ronda 2

H1–H9 cerrados con evidencia y cross-checks (§2↔Límites, matriz↔gate,
códigos §5↔tests). Un nit N1 (2³³ "bloques" → bytes; margen real ≈2⁻⁷⁰
más holgado que el ≈2⁻⁶² declarado) corregido en dirección conservadora.

Confirmaciones de la ronda 1 que sostienen el diseño: el AAD expone el
hash del plano pero ya vive en claro en el manifiesto (no fuga nueva);
el downgrade de bundle sellado→v1 es estructuralmente imposible
(`unsupported_export_profile`); `sealed_payload_auth_failed` unificado
sin oráculo; gates con y sin extra; adaptador de prueba determinístico
sólo en `scripts/`, jamás en el paquete.

## Ronda 3 — fix-and-retry documental del maintainer (2026-08-20)

Veredicto del dueño sobre el `proceed` del revisor: corregir antes de
volver. **Primera tanda: 8 órdenes; cierre corto: +5 órdenes** (todas
aplicadas). Primera tanda:

| # | Orden del maintainer | Aplicación |
|---|---|---|
| 1 | `restore-result-v2` contractual (v1 cerrado no admite warning sellado); conteo a cinco | §2: schema propio con mismos campos y warning sellado; lista explícita de los cinco empaquetados |
| 2 | Techo explícito por entrada (límite AESGCM 2³¹−1), error cerrado, sin chunking | §6: `max_entry_bytes = 512 MiB` (2²⁹), `sealed_entry_too_large` en el enum §5; chunking fuera de alcance declarado |
| 3 | `manifest_mac` sobre el transcript canónico completo (schema, profile, seal sin mac, core, manifest_sha256); `bundle_id` recalculado desde la clave | §6: MAC autentica TODO el manifiesto incl. `wrapped_cek`; bundle_id observado nunca se confía, se compara |
| 4 | Subclaves separadas para aead-key/nonce/bundle-id/manifest-mac; CEK raíz jamás como clave AES | §1: cuatro subclaves por `info`; §6: nonces encadenan sobre `nonce_stream` dedicada |
| 5 | Ejecución segura del adaptador: argv sin shell, JSON cerrado, base64 canónico, CEK 32 B, límites I/O, timeout, stderr descartado | §4: bloque "ejecución segura" completo (8 KiB stdin / 64 KiB stdout / 8 KiB stderr descartado / 30 s / sin inyección de entorno) |
| 6 | 10 GiB = 2³³ bytes ≈ 2²⁹ bloques AES; retirar garantía absoluta de no-repetición entre bundles | §6: aritmética corregida (≈2⁻⁷⁰); unicidad entre bundles = CEKs aleatorias sin colisionar (≈2⁻²⁵⁶ por par, despreciable, no cero) |
| 7 | Retirar que `compaction-restore-proof-v1` funciona con v2 sin caso especial | §2: nota correctiva — el lector de compactación rechaza v2; ningún claim de compatibilidad |
| 8 | Stop rule: consumidores que prohíban plaintext no pueden compactar sin contrato separado | §3: stop rule explícita tras ratificar H2 conservador |

**Cierre corto (segunda tanda, misma fecha) — 5 órdenes más:**

| # | Orden del maintainer | Aplicación |
|---|---|---|
| 9 | `sealed_entry_too_large` al enum §5 y a la matriz | Fila nueva en §5 (fail-closed antes de cifrar) + prueba 10b |
| 10 | Gramática CLI argv sin shell: ejecutable separado y argumentos repetibles, sin split de strings | §2: `--key-adapter bin` + `--key-adapter-arg` repetible; `argv=[bin,*args]`, `shell=False`; split de string prohibido explícitamente |
| 11 | Honestidad de versión: beta.17 rechaza v2 como `export_manifest_invalid`; `unsupported_export_profile` pertenece al dispatcher dual nuevo | §3: nota de versión completa; matriz 10 prueba ambos códigos según versión |
| 12 | `backup` no existe en el dispatch actual: retirar o declarar alias nuevo pendiente | §2: verificado contra `cli_parser.py` (sólo aparece en el help de `export`); declarado superficie nueva pendiente, no herencia |
| 13 | Congelar encoding de `manifest_mac`, comparación constante, límites de `adapter_id` | §6: hex minúscula 64 chars, `hmac.compare_digest` (nunca `==`), `T` siempre canonical_json; `adapter_id` NFC 1–128 chars sin rutas absolutas, validado por schema y core |

H2 conservador **ratificado** por el dueño; ADR de compactación sellada
**no se abre** (orden expresa).

**Supersesión de premisa criptográfica (F2 del cierre de honestidad
normativa, 2026-08-20)**: la decisión histórica
(`issue-46-decision-2026-08-20.md`) afirmaba "AN-KLA no acuña, deriva ni
almacena material de clave" como premisa previa a la elección. Al
ratificarse la **opción B**, ADR-0042 la supersede: el core genera una
CEK efímera y deriva subclaves; lo externo exclusivo es la custodia de
wrap/unwrap; el core no persiste claves en disco *(redacción pre-F7 de
este párrafo histórico; la forma vigente acota a **escritura
intencional** — ver R6/F7 y R9)*. Nota visible añadida
al documento histórico (que se conserva íntegro). El ADR también retiró
la atribución criptográfica falsa a ADR-0031 (referido sólo por su
frontera general de custodia).

**Supersesiones registradas (E1, detectadas en Ronda 4)**: la orden 4
("nonces encadenan sobre `nonce_stream` dedicada") quedó **superseda**
por la orden F1 posterior (contador puro `i.to_bytes(12,"big")`; el
maintainer retiró la derivación HKDF del nonce al constatar que truncar
a 96 bits no es inyectiva). La orden 13 ("`adapter_id` NFC, 1–128")
quedó **superseda** por la orden F4 posterior (gramática ASCII cerrada
`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, 1–64 bytes; NFC retirada como
redundante). En ambos casos la versión vigente del ADR es la posterior,
que es también criptográficamente superior.

## Gate documental tras la ronda 3 (repetido tras el cierre corto)

- `git diff --check` → limpio.
- `scripts/check_adr_registry.py` → OK (42 ADRs, 40/2).
- `python3 -m unittest discover -s tests` → 632/632 OK (sólo docs + el conteo
  mecánico de `tests/test_adr_registry.py`, 39→40, exigido por el
  registro del ADR nº42).

## Ronda 4 — revisor independiente de contexto fresco (2026-08-20)

**Identidad**: agente opencode CLI, modelo GLM (zai-coding-plan/glm-5.2),
contexto fresco sin exposición a iteraciones previas. **Alcance**: ADR-0042
íntegro, código beta.17 (`export_restore.py`, `compaction.py`,
`capabilities.py`, `cli_parser.py`), verificación runtime de
`cryptography` 46.0.3 (incluye ejecución de la inyectividad del contador
sobre el dominio completo), acta leída sólo al final.

**Veredicto**: `fix-and-retry` documental, lista corta. La criptografía
resiste (puntos 1–3 sin hallazgo: contador inyectivo sin sobre-claim,
separación entre bundles bien atribuida a `aead_key`, sin camino de clave
compartida; aritmética verificada).

| Hallazgo | Severidad | Corrección aplicada |
|---|---|---|
| F6 atribuía staging+renombrado al "patrón del bundle v1": falso para `create` (escribe directo, limpia on-exception; el patrón es de restore) | Media | Atribución corregida + create sellado declarado deliberadamente más fuerte que v1 |
| F6 sobre-aseveraba "nunca un bundle que `verify` dé por bueno": en la ventana crash-pre-rename el staging huérfano es un bundle completo verificable | Media | Promesa acotada: nunca un **destino** publicado parcial; staging huérfano completo puede verificar |
| Test 12 esperaba `unsupported_export_profile` "del lector v1" — contradicción con §3/§5 y el código (el lector v1 emite `export_manifest_invalid`) | Media | Test 12 corregido al código real + 12b prueba explícita de `sealing_extra_not_installed` |
| Enum de `diagnostics` no cubría links/traversal/conteos | Media | Enum ampliado (`unsafe_path`, `count_mismatch`) + tabla de mapeo completo chequeo→código |
| Acta desincronizada (órdenes 4 y 13 supersedas sin registro; labels F1–F6 ausentes) | Media | Supersesiones registradas arriba (E1); esta sección (E2) |
| Runner: exit status, `close_fds`, escalada TERM→KILL, lectura concurrente stdout/stderr, stdin pre-vuelo sin congelar | Baja | Bloque de higiene congelado (TERM → 2 s → KILL; `close_fds=True`; lectura concurrente; stdin por schema pre-vuelo) |
| Terminación "del árbol completo" sobre-asevera (`setsid()` escapa del kill de grupo) | Baja | Best-effort declarado; claim acotada a procesos gestionados |
| stdout del adaptador podía embeberse en diagnósticos; `bin` relativo resuelve contra PATH heredado | Baja | Payloads de error jamás embeben stdout/stderr; ruta absoluta recomendada, confianza en PATH declarada |
| §5 "bundle corrupto" ambiguo frente a §8 | Baja | Acotado a "corrupción detectable en la capa autenticada" |
| RFC 5869 §3.3 no citado para HKDFExpand-sin-extract | Info | Citado en §1 |
| Stop rule "no hay ruta intermedia" absolutista | Info | Matiz tmpfs añadido (interpretación de política del consumidor) |

**Ejecución del fix-and-retry**: todas las correcciones aplicadas al ADR
en la misma fecha; ver Ronda 5 para la re-validación fresca exigida por
el maintainer.

## Ronda 5 — segunda revisión independiente de contexto fresco (2026-08-20)

**Identidad**: agente opencode CLI, modelo GLM (zai-coding-plan/glm-5.2),
primera exposición al artefacto; ADR leído íntegro antes del acta, código
beta.17 contrastado, verificaciones runtime propias (dominio completo del
contador: 100000 nonces distintos de 12 bytes; imports de `cryptography`;
suite 632/632 re-ejecutada).

**Veredicto: `proceed`.** Los 6 grupos de correcciones de Ronda 4
cerrados con evidencia (staging/honestidad F6, matriz 12/12b, enum
diagnostics con mapeo, runner §4 completo, nonce contador sin residuos,
acta E1/E2). Nits nuevos, todos no bloqueantes y resueltos en esta misma
edición: N1 casilla de decisión anticipada (corregida: la decisión final
pasa a esta sección), N2 rama "perfil desconocido" sin test propio
(absorbida en el test 10), N3 shape `sealing.profiles` aclarada en el
ADR, N4 paréntesis 2¹⁷ reformulado (el argumento es 2⁹⁶ ≫ 10⁵).

## Decisión final de la secuencia pre-code

- [x] proceed — anclado originalmente en Ronda 5, **ratificado por
  Ronda 9** (validación fresca final del artefacto consolidado con F7
  íntegro; la Ronda 8 validó el estado intermedio post-re-aplicación);
  el ADR queda listo para el arreglo del maintainer; **sin
  commit/push/rama/PR ni implementación** (esperan autorización
  separada por operación)
- [ ] fix-and-retry
- [ ] escalate — revertir H2 (compaction sellado) exige ADR propio y
  orden explícita, cerrado por decisión del dueño

Cadena completa de la secuencia: R1 (revisor, fix-and-retry) → R2
(revisor, proceed) → R3 (maintainer, fix-and-retry ×13) → R4 (revisor
fresco, fix-and-retry, 6+6 hallazgos aplicados) → R5 (revisor fresco,
proceed) → R6 (maintainer F1–F6 + revisor fresco, proceed) → R7
(revisor fresco, fix-and-retry: F7 perdido por fallo de script,
re-aplicado con errata honesta) → R8 (revisor fresco, proceed sobre el
estado intermedio de 606 líneas) → **R9 (revisor fresco final,
`PROCEED` sobre el artefacto consolidado de 615 líneas)**.

## Ronda 6 — fix-and-retry de honestidad normativa del maintainer (2026-08-20)

Orden del maintainer previo al commit documental: corregir seis defectos
de honestidad del ADR (etiquetas F1–F6 de ESTA ronda). Alcance
exclusivamente documental (ADR-0042, este acta, nota en la decisión
histórica, docs/README). **Nota de proceso**: dos sesiones de agente
trabajaron este encargo de forma concurrente sobre los mismos archivos;
la consolidación final (esta sección única) preserva el registro de
ambas: las correcciones F1–F6, los gates, la verificación fresca y los
hallazgos de higiene.

| # | Defecto | Corrección aplicada |
|---|---|---|
| F1 | "el material de clave vive sólo en un adaptador externo" contradecía el diseño (el core genera la CEK con os.urandom, deriva subclaves, cifra, calcula MAC) | §Decisión y §1 reescritos con separación precisa: el core genera y mantiene temporalmente CEK+subclaves; la CEK viaja al adaptador por stdin local durante wrap; el core nunca persiste en disco; la custodia de wrap/unwrap (KEK/clave privada/passphrase/Keychain/KMS) es exclusiva del adaptador y jamás entra al core; sólo `wrapped_cek` es persistente; riesgo residual explícito: borrar objetos Python no garantiza zeroización física, la CEK puede quedar en copias/buffers hasta que runtime/SO recuperen la memoria |
| F2 | ADR-0031 citado como "AN-KLA no acuña ni almacena material de clave" (decisión criptográfica que no contiene) y frase histórica de issue-46 sin supersesión | Referencias: ADR-0031 sólo por su frontera general de custodia, sin atribución criptográfica. issue-46 conserva el registro histórico con NOTA DE SUPERSESIÓN visible cubriendo AMBAS frases (custodia y nonce HKDF; premisa pre-B, superseda por ADR-0042; bajo B el core genera CEK efímera y deriva subclaves; lo externo exclusivo es la custodia wrap/unwrap; sin persistencia en disco). Registrado también arriba ("Supersesión de premisa criptográfica") |
| F3 | Encabezado simultáneamente "implementación autorizada tras esta ronda" y "no autoriza código hasta orden" | Una sola posición: Implementación No iniciada y NO autorizada por este ADR; el diseño queda preparado para una futura orden; arrancar código/instalar [sealed]/rama/PR exige autorización nueva. Bullet "Autoriza" reescrito a "nada por sí misma" (proceso futuro, no autorización anticipada). docs/README: "Diseño pre-code aceptado; implementación no iniciada y pendiente de orden separada" |
| F4 | "un valor así no puede ser ruta POSIX ni Windows" — falso (gramática sin separadores no impide interpretación como ruta relativa en otro contexto) | §6: adapter_id es etiqueta opaca; el core jamás la pasa a Path/open/exec/shell/resolución/selección de adaptador; la gramática sin `/\:` sólo reduce confusión visual; la garantía es semántica (nunca interpretada como ruta); claim "no puede ser ruta" retirado. `.` y `..` rechazados expresamente (ya excluidos por el primer carácter alfabético; decisión explícita) y añadidos a la matriz (10e) |
| F5 | "las rutas expuestas son digests content-addressed" — cierto sólo en parte | §7: el manifiesto revela nombres estructurales fijos, refs (CURRENT y otros), categorías de objetos, UUIDs de transacción, rutas de checkpoints/revisiones/segmentos/catálogos; en conjunto expone conteo/tamaños, tipos, estructura relativa, identificadores y patrón de crecimiento. No expone rutas absolutas del host, pero sí metadatos suficientes para inferir composición y actividad |
| F6 | Alternativas conservaba "nonce derivado por construcción" (mecanismo retirado) | Sustituido por "nonce contador inyectivo dentro de cada bundle y aead_key independiente por CEK". nonce_stream permanece sólo en este acta, etiquetado como supersedo (E1). Referencias normativas activas a nonce_stream: **0** |

Gate documental tras la Ronda 6:

- `git diff --check` → limpio.
- `scripts/check_adr_registry.py` → OK (42 ADRs, 40/2).
- `python3 -m unittest discover -s tests` → 632/632 OK (sólo docs + el
  conteo mecánico de `tests/test_adr_registry.py`, 39→40, exigido por el
  registro del ADR nº42).

Verificación fresca de la Ronda 6 (revisor independiente de contexto
fresco, agente opencode CLI/GLM, misma fecha): **`proceed`**, 11/11
blancos NO REFUTADOS con lectura íntegra del ADR y contraste contra
README, decisión histórica y este acta; rg de contradicciones con **0
coincidencias activas** (todas corregidas o históricas-etiquetadas).

**Evidencia de la Ronda 6, blanco por blanco (F9: asentada desde la
salida auténtica del revisor; procedencia = reporte del subagente
fresco, no verificación independiente adicional por este agente.
Números de línea RE-ANCLADOS al ADR vigente post-F7 en la Ronda 8 —
los números de línea no son evidencia estable: el texto manda):**

| # | Blanco | Evidencia inspeccionada (anclas vigentes) | Resultado |
|---|---|---|---|
| 1 | CEK: quién la genera | ADR §1 ("El core genera y mantiene temporalmente…", bloque CEK/F1) + rg sin "vive solo"/"no acuña" en el ADR | PASS |
| 2 | CEK en tránsito | ADR §1 ("viaja al adaptador por stdin local"; unwrap → stdout) + política de entorno allowlist de §4 | PASS |
| 3 | Custodia | ADR §1 ("ese material de custodia jamás entra al core") | PASS |
| 4 | Persistencia | ADR §1 bloque "Persistencia, separación congelada (F7)" + §6 (nonce jamás en disco) | PASS |
| 5 | Zeroization | ADR §1 ("borrar objetos Python no garantiza zeroization física…") + §Límites (entrada de swap/hibernación/dumps/copias) | PASS |
| 6 | Autoridad | Encabezado del ADR ("No iniciada y no autorizada por este ADR") + fila README 0042 | PASS |
| 7 | adapter_id | ADR §6 (garantía semántica; `.`/`..` rechazados) + prueba 10e de §9 | PASS |
| 8 | Metadatos | ADR §7 ("alcance exacto"; sin rutas absolutas del host) | PASS |
| 9 | Nonce | ADR §1 ("El nonce no se deriva") + §6 (contador puro inyectivo) + Alternativas ("nonce contador inyectivo…"); rg HKDF: sólo subclaves | PASS |
| 10 | Coherencia cruzada | Decisión histórica (texto original + nota que cubre ambas frases) + README 42/40/2 | PASS |
| 11 | Alcance documental | `git status`/diff: docs + ADR/acta untracked + conteo mecánico del test del registro; sin runtime/dependencias | PASS |

Dos observaciones no bloqueantes del revisor: (a) dos retracciones
explícitas del ADR —"no puede ser ruta", "rutas digests"— quedan
invisibles al rg line-based por salto de línea (útil saberlo para
futuros sweeps); (b) la supersesión de la orden 4 está etiquetada en el
bloque E1 y no inline en la tabla (aceptable; inline sería más robusto
ante lecturas parciales).

**F7–F9 (cierre final del maintainer, 2026-08-20)**: F7 persistencia
de material derivado y límites del SO (separación CEK/subclaves =
secreto no serializado · `wrapped_cek` = único artefacto destinado a
recuperarla · `bundle_id`/`manifest_mac` = derivados persistentes no
secretos; claim acotado a escritura intencional; swap/hibernación/
crash dumps/copias de runtime fuera de garantía y en riesgos
residuales; prueba negativa 16 en matriz). F8 terminación
**gestionada** (redefinida; `setsid`/breakaway caracterizados en 6f,
fuera de garantía; destino publicado parcial = garantía fuerte
separada; staging best-effort). F9 esta misma sección (evidencia
asentada con procedencia declarada; sin retractación: la salida
auténtica existía).

> **Errata honesta (registrada por Ronda 7, ampliada por Ronda 8)**: la
> primera aplicación de F7 al ADR se **perdió por un fallo parcial de
> script** (el lote F7+F8 abortó en un assert de F8; sólo sobrevivió el
> cambio en la decisión histórica y, tras rehacer F8 por edit, el bloque
> F7 del ADR no se re-aplicó). El acta lo dio por aplicado sin
> verificación posterior del artefacto. Ronda 7 lo detectó (N1: rg
> "intencional" → 0 en el ADR; frase pre-F7 intacta; prueba 16 ausente)
> y F7 fue re-aplicado íntegro al ADR tras esa detección. N2-N5 de
> Ronda 7 (referencia muerta, prueba integral, claim absoluto, deriva de
> line-numbers) quedaron cerrados con la misma edición.
>
> **Incidencia de edición concurrente (F9, registro completo)**: durante
> el cierre de F7-F9 **dos sesiones de agente escribieron los mismos
> archivos de forma solapada** (observado por hash: escrituras a las
> 05:02-05:07 del 2026-08-21 mientras la otra sesión releía). El
> solapamiento dejó restos inconsistentes que esta acta registra y
> corrige: dos frases absolutas pre-F7 sobrevivieron en §Decisión y §1
> del ADR ("nunca persiste material de clave en disco"; "El core nunca
> persiste CEK ni subclaves en disco"), la prueba 16 carecía de la
> declaración expresa de incapacidad ante swap/dumps, este acta
> referenciaba una "Ronda 8" inexistente y la "Cadena final" seguía
> terminando en R6. **Resolución**: la sesión que tomó el relevo esperó
> quiescencia sostenida (tres lecturas de hash estables consecutivas),
> se designó único escritor, releyó el worktree vivo sin confiar en
> reportes previos, completó F7/F9 y ejecutó la validación fresca final
> (Ronda 8). **La versión que prevalece es la consolidada post-
> quiescencia por esa sesión** — la presente.

## Ronda 7 — revisión adversarial final de contexto fresco (2026-08-21)

**Identidad**: modelo GLM (zai-coding-plan/glm-5.2) vía opencode CLI,
primera exposición; ADR íntegro (583 líneas) antes de acta/decisión;
contraste contra `cli_parser.py`/`export_restore.py`; gates ejecutados
por el revisor.

**Veredicto: `fix-and-retry` documental corto.** Blancos 4,5,7,8,11 NO
REFUTADOS (terminación gestionada; destino/staging; nonce/AAD/MAC con
`compare_digest`; autoridad; alcance). **Tres refutados por omisión**:
(2) frase pre-F7 "Lo único persistente… es wrapped_cek" intacta en el
ADR; (3) swap/hibernación/crash dumps/copias de runtime ausentes del
ADR (referencia muerta desde la decisión); (6) prueba 16 declarada en
acta pero inexistente en matriz — todos efectos del fallo de script
documentado arriba. Criptografía, fail-closed, matriz restante y
alcance intactos: nada reabre el diseño.

**Cierre**: F7 re-aplicado al ADR (§1 separación destinado/derivados +
acotamiento intencional; §Límites entrada nueva de SO; §9 prueba 16),
referencia de la decisión ahora viva. Ver Ronda 8 para la validación
fresca final del artefacto corregido.

Hallazgos de higiene del acta, cerrados en esta edición:
- **H1-R6**: colisión de espacios de etiquetas "F" (los F del ADR de
  rondas 3-4 ≠ los F1-F6 de esta ronda). Desambiguación: las etiquetas
  "F2/F3/F5/F6" impresas en el ADR (runner, entorno, tamaño físico,
  staging) se refieren a las **órdenes de las Rondas 3-4**; los F1-F6 de
  la tabla anterior son los de **esta Ronda 6**. E1 queda precisado: el
  contador puro fue introducido por la orden "F1" del **cierre largo
  previo** y verificado por R5 antes de R6.
- **H2-R6**: el gate declara "(sólo docs + conteo mecánico del test del
  registro)" — la suite toca un test, sin cambio conductual del código.
- **H3-R6 (info)**: la decisión histórica usa `sealed_extra_not_installed`
  (pre-ADR); el nombre normativo vigente es `sealing_extra_not_installed`
  — discrepancia histórica documentada aquí, sin edición del registro.

Cadena final: R1 → R2 → R3 → R4 → R5 → R6 (proceed) → R7 (fix-and-retry
documental: F7 re-aplicado tras pérdida por script) → R8 (proceed
intermedio) → **R9 (validación fresca final del artefacto consolidado
post-concurrencia: `PROCEED` definitivo — ver sección Ronda 9)**. El
paquete queda listo para el commit documental que autorice el
maintainer; este acta no lo autoriza por sí misma.

## Ronda 8 — validación fresca final (2026-08-21)

**Contexto post-concurrencia**: valida el artefacto post-F7/F8/F9
consolidado por la sesión única post-quiescencia (ver "Incidencia de
edición concurrente" arriba). Nota de numeración: la orden del
maintainer llamaba "Ronda 7 fresca" a esta validación; el número 7 ya
estaba usado por la ronda intermedia del cierre concurrente, así que se
materializó como Ronda 8 para mantener coherente la numeración del acta.

**Identidad/procedencia declarada**: modelo GLM
(zai-coding-plan/glm-5.2) vía opencode CLI, primera exposición; **objeto
exacto revisado**: ADR-0042 íntegro (606 líneas al momento de la
revisión; **615 tras los cierres post-concurrencia** de la misma
sesión consolidante — la cuenta declarada quedó desactualizada en el
registro original, precisada aquí por Ronda 9/H1) con F7 re-aplicado,
leído antes del acta; contraste contra `cli_parser.py` y
`export_restore.py`. **Procedencia declarada**: reporte de subagente
revisor fresco; verificación final de este agente = re-ejecución de
gates y rg de contradicciones.

**Gates ejecutados (por el revisor)**: `git diff --check` limpio ·
`check_adr_registry.py` OK (42/40/2) · suite 632/632 OK · sin
movimiento de HEAD (d83107e).

**Blancos, individualmente:**

| # | Blanco | Evidencia inspeccionada | Resultado |
|---|---|---|---|
| 1 | F7 en §1 | `wrapped_cek` "único artefacto persistente destinado a recuperar la CEK"; `bundle_id`/`manifest_mac` derivados no-secretos; acotado a escritura intencional | PASS |
| 2 | Frase pre-F7 | rg "Lo único persistente relacionado con la clave" → 0 en corpus normativo | PASS |
| 3 | §Límites de SO | Entrada dedicada swap/hibernación/crash dumps/copias de runtime, "fuera de toda garantía" | PASS |
| 4 | Prueba 16 | §9: no-fuga en bundle/staging/stdout/stderr/warnings/resultados/logs | PASS |
| 5 | Terminación gestionada (F8) | "ningún proceso _gestionado_ residual"; setsid/breakaway fuera de garantía (6f); publicación = garantía separada | PASS |
| 6 | Nonce/MAC | Contador puro; transcript completo T; `hmac.compare_digest`; 0 refs activas a `nonce_stream` | PASS |
| 7 | Autoridad | "No iniciada y no autorizada por este ADR"; README coherente | PASS |
| 8 | Coherencia cruzada | Nota de supersesión de la decisión con referencias vivas al ADR §1/§Límites | PASS |
| 9 | Integridad de rondas | Cadena R1→R8 registrada; supersesiones etiquetadas; evidencia R6 con procedencia | PASS |
| 10 | Contradicciones/restos | F7 single-applied; sin secciones truncadas (606 líneas íntegras); duplicados sólo en ejemplos §8 | PASS |

**Correcciones de higiene** (aplicadas en la misma edición, post-reporte
del revisor): cadena final extendida a R7; refs de la tabla R6
re-ancladas **por sección** (los números de línea no son evidencia
estable: el texto manda); typo "Blanos"→"Blancos".

**Veredicto: `proceed`** — 10/10 blancos PASS; gates limpios; los
hallazgos eran higiene del acta y quedaron cerrados.

*Nota de procedencia general*: las tablas de evidencia de R6/R7/R8
provienen de reportes de subagentes revisores (declarado); su
verificación final por este agente fue la re-ejecución de gates y los rg
de contradicciones.

> **Precisión de alcance (asentada por R9)**: esta Ronda 8 revisó el ADR
> de **606 líneas** — el artefacto con F7 re-aplicado pero ANTES de la
> completación final de F7 (dos frases absolutas sobrevivían en
> §Decisión y §1) — y su blanco 2 usó un patrón rg más estrecho que el
> del encargo. El artefacto FINAL (615 líneas, frases absolutas
> eliminadas y prueba 16 con declaración de incapacidad) fue validado
> por la **Ronda 9** con el rg exacto del encargo. El `proceed` de esta
> ronda describe el estado que validó; el definitivo es el de R9.

## Registro de duplicación de "Ronda 8" (residuo de edición concurrente)

La incidencia de edición concurrente (arriba) dejó **dos secciones**
tituladas "Ronda 8": la validación completa (consolidada en la sección
única "Ronda 8 — validación fresca final") y un **stub sin veredicto**
(un marcador de posición que remitía el veredicto al cierre de la
ronda, sin asentar nada) creado por la sesión solapada. Este
registro no oculta la duplicación ni reescribe la historia: el stub se
eliminó en la consolidación registral ordenada por el maintainer
(corrección final exclusivamente registral, 2026-08-21); toda su
información única — el contexto post-concurrencia y la aclaración de
numeración (la orden llamaba "Ronda 7 fresca" a esta validación; el 7
ya estaba usado) — quedó absorbida en la sección consolidada. La
validación que aquel stub esperaba quedó registrada al final como
**Ronda 9** (ver abajo), ejecutada por la sesión que había dejado el
marcador.

## Registro de duplicación de "Ronda 9" (segundo residuo de edición concurrente)

La incidencia de edición concurrente descrita en Ronda 6 dejó un
**segundo residuo**: dos secciones tituladas "Ronda 9" —una
"verificación registral de contexto fresco" y una "validación
adversarial fresca final del artefacto consolidado"—, escritas por
sesiones solapadas (la segunda además reordenó físicamente el acta,
dejando R6/R7 después de la primera R9). La consolidación final
ordenada por el maintainer (2026-08-21, única escritora tras
quiescencia) las **fusionó preservando toda la evidencia única de
ambas** — identidad/procedencia declaradas, los diez puntos
registrales, los diez blancos adversariales, H1–H4 con su resolución,
el control post-objeto y un único veredicto PROCEED — y restauró el
orden físico R1→R9. Este registro no oculta la duplicación: deja
constancia de que existió, de quién la produjo y de cómo se resolvió.

## Ronda 9 — verificación registral + validación adversarial final del artefacto consolidado (2026-08-21)

> **Nota de fusión**: esta sección consolida las dos rondas novenas
> creadas por sesiones concurrentes (ver "Registro de duplicación de
> Ronda 9" inmediatamente arriba). Ambas verificaciones se conservan
> íntegras en lo sustantivo: primero la registral, luego la
> adversarial; un único veredicto al cierre.

**Encargo**: corrección final exclusivamente registral del maintainer —
consolidar las dos secciones duplicadas de "Ronda 8" (residuo de la
edición concurrente), eliminar el stub sin veredicto, asentar los 10
blancos individualmente, registrar la duplicación sin ocultarla, cadena
con R8 una sola vez.

**Consolidación ejecutada antes de esta ronda**: sección única
"Ronda 8 — validación fresca final" (contexto post-concurrencia,
identidad/procedencia, objeto, gates, tabla de 10 blancos, higiene,
veredicto `proceed`); stub eliminado con "Registro de duplicación"
expreso; cadena final R1→R8 con R8 una vez; cita del placeholder
reformulada sin la frase literal (el gate del maintainer exige cero
coincidencias del rg sobre ella; el registro describe el stub sin
reproducirlo).

**Verificación fresca (salida auténtica del revisor, registrada
textualmente en lo sustantivo)** — identidad: modelo GLM
(zai-coding-plan/glm-5.2) vía opencode CLI, contexto fresco/primera
exposición, 2026-08-21:

1. `^## Ronda 8` → **exactamente 1** coincidencia (acta:166). PASS
2. La frase-placeholder del stub (veredicto diferido al cierre, citada
   parafraseada para que el gate del maintainer —rg de la frase
   literal— siga dando cero) → **0** coincidencias. PASS
3. R8 contiene contexto post-concurrencia, identidad/procedencia,
   objeto exacto, gates, tabla de 10 blancos (4 columnas), higiene y
   `proceed`. PASS
4. Duplicación registrada sin ocultación ("Registro de duplicación",
   acta:359). PASS
5. Cadena final con R8 exactamente una vez, coherente R1→R8. PASS
6. F7 intacta en el ADR: `intencional` ×6, `swap` ×4, prueba
   `16. **F7` en §9, entrada de SO en §Límites. PASS
7. Prueba 16 íntegra (con declaración de incapacidad ante
   swap/hibernación/dumps/copias); F8 intacta ("gestionado",
   6f setsid/breakaway fuera de garantía). PASS
8. Referencias históricas clasificadas (NOTA DE SUPERSESIÓN, errata
   honesta, "históricas-etiquetadas"; el rótulo literal
   `historica-supersedida` no existe como string — clasificación
   vigente por los otros rótulos). PASS
9. Sólo el acta cambió en esta pasada (diff/name-only + mtime
   consistentes; evidencia circunstancial, no criptográfica —
   registrado con honestidad). PASS
10. Gates: `git diff --check` limpio · `check_adr_registry.py` OK
    (42/40/2) · suite **632/632 OK**. PASS

**Hallazgo H1 (menor, cerrado en esta edición)**: R8 declaraba "606
líneas" y el ADR consolidado tiene 615 — delta de los cierres
post-concurrencia aplicados por la misma sesión consolidante; precisado
arriba en el objeto declarado de R8 ("el texto manda", ya establecido).

**Resultado registral: 10/10 con evidencia; gates limpios** (el
veredicto único de la Ronda 9 fusionada queda registrado al final de la
sección, tras la validación adversarial).

*Control post-objeto*: tras el objeto revisado por Ronda 9 (acta
consolidada), el único cambio posterior fue **el registro fiel de esta
misma Ronda 9** (más la precisión H1 de una frase), verificado por
lectura; ningún otro archivo tocado en esta pasada.

---

**Validación adversarial del artefacto consolidado (segunda mitad de la
fusión; texto sustantivo de la otra sesión):**

**Identidad/procedencia**: subagente revisor de contexto fresco (agente
opencode CLI, modelo GLM, primera exposición), lanzado por la sesión
consolidadora post-quiescencia; lectura íntegra del ADR **antes** del
acta; procedencia del reporte declarada aquí; verificación del agente
consolidador = re-ejecución de gates y del rg exacto del encargo.
**Objeto exacto**: ADR-0042 de **615 líneas** (F7 completo: bloque de
persistencia §1, frase intencional de §Decisión, límite de
swap/hibernación/dumps/copias, prueba 16 con declaración expresa de
incapacidad; F8 intacto; F9 aplicado).

**Blancos del encargo, individualmente** (mapean 1:1 los diez puntos
exigidos): escritura intencional vs persistencia posible (§Decisión,
§1, §Límites) — NO REFUTADO · CEK/subclaves vs
wrapped_cek/bundle_id/manifest_mac (separación congelada, sin
absolutos) — NO REFUTADO · prueba 16 presente con alcance honesto — NO
REFUTADO · procesos gestionados vs setsid/breakaway (§4 + 6d/6e/6f) —
NO REFUTADO · destino publicado vs staging (F6/R4 intacto) — NO
REFUTADO · autoridad (implementación NO autorizada; README coherente) —
NO REFUTADO · coherencia cruzada ADR↔decisión↔README↔acta — NO
REFUTADO · **rg del encargo → 0 coincidencias** — NO REFUTADO ·
integridad tras concurrencia — NO REFUTADO (con hallazgos) · alcance
exclusivamente documental (5 archivos, nada de código) — NO REFUTADO.

**Gates re-ejecutados**: `git diff --check` limpio ·
`scripts/check_adr_registry.py` OK (42 ADRs, 40/2) · suite 632/632 OK ·
HEAD sin movimiento (d83107e).

**Hallazgos y cierre**:
- **H1-R9 (menor)**: duplicación de "Ronda 8" en el acta (la sección
  completa y el stub). Cerrado por la consolidación registral (ver
  "Registro de duplicación" arriba); esta R9 queda como validación
  final única del artefacto definitivo.
- **H2-R9 (observación)**: la R8 citaba 606 líneas frente a las 615
  vigentes; precisado con nota de alcance dentro de la propia R8.
- **H3-R9 (observación)**: el bullet F7 de §1 omitía "warnings" en su
  enumeración de canales frente a §Decisión/§1/prueba 16. Cerrado en
  esta edición (enumeración unificada).
- **H4-R9 (observación)**: el párrafo de supersesión criptográfica del
  acta usaba la redacción pre-F7 ("no persiste claves en disco" sin
  calificativo). Anotado como histórico; el texto normativo (ADR)
  quedó limpio.

**Veredicto: `PROCEED`** — 10/10 blancos NO REFUTADOS sobre el
artefacto final; cero bloqueantes. Cadena final: R1 → R2 → R3 → R4 →
R5 → R6 → R7 → R8 (intermedio) → **R9 (PROCEED, definitivo)**. El
paquete queda listo para el commit documental que autorice el
maintainer; este acta no lo autoriza por sí misma.

## Ronda 10 — verificación de consolidación registral (2026-08-21)

**Encargo**: consolidación final del acta por escritora única — orden
físico R1→R9, un encabezado por ronda, fusión de las dos R9 preservando
evidencia única, registro del segundo residuo de concurrencia.

**Consolidación ejecutada antes de esta ronda**: bloques reordenados
R1→R5 → Decisión final → R6 → R7 → R8 → Registro duplicación R8 →
**Registro duplicación R9 (nuevo)** → R9 fusionada (nota de fusión;
encargo registral; consolidación ejecutada; identidad/procedencia de
ambas verificaciones; diez puntos registrales numerados con PASS; diez
blancos adversariales con mapeo 1:1; H1–R9 a H4–R9; control
post-objeto; veredicto intermedio reformulado a "Resultado registral"
para dejar un único veredicto al cierre). Ningún contenido normativo ni
resultado histórico alterado.

**Verificación fresca (salida auténtica del revisor, en lo sustantivo)**
— identidad: modelo GLM (zai-coding-plan/glm-5.2) vía opencode CLI,
primera exposición, 2026-08-21; objeto: acta (527 líneas) + ADR (615),
sólo lectura:

1. Nueve encabezados R1→R9 en orden, sin repetidos (12/26/39/100/132/
   170/272/315/409). **PASS**
2. R8 ×1 (315); R9 ×1 con título fusionado (409). **PASS**
3. R9 fusionada completa: nota de fusión, encargo, consolidación,
   identidad/procedencia de ambas, 10 puntos registrales con PASS,
   10 blancos adversariales NO REFUTADOS, H1–R9 a H4–R9 con resolución,
   control post-objeto, único veredicto `PROCEED` final; sin veredicto
   intermedio (467 = "Resultado registral", permitido). **PASS**
4. Dos registros de duplicación presentes (R8 en 376; R9 — segundo
   residuo — en 393, con fusión y restauración de orden). **PASS**
5. F7/F8/prueba 16 intactos por lectura del ADR (`intencional` ×6;
   `swap, hibernaci…` ×3; `16. **F7` en §9; `gestionado` en §4; `6f`). **PASS**
6. Cadena histórica coherente (Decisión final → R9 PROCEED sobre 615;
   cadena R7 → R9 definitivo; cadena R9 → R8 intermedio → R9). **PASS**
7. Cero placeholders — **FALLO literal en la primera pasada**: la frase
   de fusión "…se asienta al cierre…" coincidía con el patrón del
   gate. **Corregido en el fix de esta ronda** (reformulada a "queda
   registrado al final de la sección"); re-verificado: ambos rg → 0. **PASS (post-fix)**
8. Sólo el acta cambió en esta pasada (diff/name-only de pasadas previas
   + mtime: acta 05:27 > ADR 05:21 > resto; HEAD d83107e). **PASS**
9. Gates: `git diff --check` limpio · `check_adr_registry.py` OK
   (42/40/2) · suite **632/632 OK**. **PASS**
10. Sin secciones truncadas; transiciones íntegras; referencia cruzada
    "inmediatamente arriba" resuelve al registro correcto. **PASS**

**Hallazgos**: H1-R10 (media-baja) la frase literal del punto 7 —
cerrada con el fix de una frase y re-verificación (arriba). H2-R10
(info) el hallazgo "606 vs 615" aparece dos veces dentro de R9 con
etiquetado no uniforme (H1 sin sufijo ≡ H2-R9; mismo contenido y
resolución). H3-R10 (info) secciones auxiliares intercaladas
("Gate documental tras la ronda 3", "Decisión final…") coherentes con
el orden de encabezados exigido.

**Veredicto: `PROCEED`** — consolidación registral sana; el único fallo
literal quedó corregido y re-verificado en la misma ronda.

*Control post-objeto*: tras el objeto verificado por Ronda 10 (acta
consolidada), los únicos cambios posteriores fueron **el registro fiel
de esta Ronda 10 y la corrección de la frase que su propio hallazgo
H1-R10 exigió** — nada más tocado, verificado por lectura y gates.

## Aceptación del dueño (🔒 2026-08-21)

El maintainer **acepta ADR-0042 (`sealed-export/v1`, opción B) como
diseño pre-code**. Alcance exacto de la aceptación, citado del acto:

- autoriza **registrar documentalmente** la decisión;
- **no** autoriza implementación;
- **no** autoriza instalar `cryptography`/`[sealed]`;
- **no** autoriza rama, PR, release ni push;
- **no** autoriza cerrar #46 como implementado.

**Acto registral derivado** (tres piezas): encabezado del ADR con la
traza (🔒 2026-08-21); fila del registro en `docs/README.md` alineada;
esta misma sección "Aceptación del dueño". Conteo unificado por H1-R11:
la aceptación **no** es una ronda de revisión; las rondas del acta son
**once** al asentarse R11 (R1–R10 previas + R11, la verificación de
este acto registral).
Orden adicional del dueño en el mismo acto: corregir el registro para
esta trazabilidad (hecho), **ejecutar una ronda adversarial fresca
sobre el acto registral** (ver Ronda 11) y regresar con el diff final.
**Sin commit y sin push** — confirmado.

## Ronda 11 — verificación del acto registral de aceptación (2026-08-21)

**Encargo**: ronda adversarial fresca sobre el acto registral de la
aceptación del dueño (ordenada en el mismo acto). **Objeto**: encabezado
del ADR, fila de README, sección "Aceptación del dueño" de este acta.

**Verificación fresca (salida auténtica del revisor, en lo sustantivo)**
— identidad: modelo GLM (zai-coding-plan/glm-5.2) vía opencode CLI,
contexto fresco/primera exposición, 2026-08-21, sólo lectura:

1. Encabezado del ADR traza la aceptación al dueño con fecha y las
   **cinco cláusulas exactas**; "Implementación: No iniciada y no
   autorizada por este ADR" intacta; resto del ADR íntegro (cambio
   limitado al bloque Estado; evidencia circunstancial declarada con
   honestidad — ADR untracked). **PASS**
2. README: "aceptado por decisión del dueño (🔒 2026-08-21)";
   "implementación no iniciada y pendiente de orden separada"
   conservada; resumen 42/40/2. **PASS**
3. Acta: sección de aceptación con las 5 cláusulas citadas, acto
   derivado, orden de R11 y "sin commit ni push" confirmado; R1–R10
   intactas y ordenadas (once encabezados monotónicos al añadirse
   R11); contenido histórico sin alteración. **PASS**
4. Coherencia: "Aceptada como diseño pre-code" ⊕ bullet "Autoriza:
   nada por sí misma" ⊕ README — ninguna lectura posible como
   autorización de implementación. **PASS**
5. Alcance de la pasada: mismos 5 archivos (3 M de pasadas previas +
   2 untracked); HEAD d83107e; mtimes consistentes (sólo
   ADR/README/acta frescos). **PASS**
6. Gates: `git diff --check` limpio · `check_adr_registry.py` OK
   (42/40/2) · suite **632/632 OK**. **PASS**
7. Sin contradicciones nuevas (bullet "Autoriza" vs aceptación:
   el bullet restringe al documento; la aceptación es acto del dueño
   auto-limitado al registro documental). **PASS**

**Hallazgos**: H1-R11 (baja) conteo de rondas inconsistente entre los
tres artefactos (once/diez/"diez más aceptación") — **cerrado en esta
misma edición** con el conteo unificado arriba (aceptación ≠ ronda;
once rondas R1–R11). H2-R11 (info) tercera pieza del acto no listada —
cerrado (ahora lista tres). H3-R11 (info) evidencia circunstancial del
alcance del cambio — registrada con honestidad, práctica establecida.

**Veredicto: `PROCEED`** — 7/7 puntos PASS sobre el acto registral; la
aceptación del dueño queda trazada con su alcance exacto y sin ninguna
lectura posible como autorización de código.