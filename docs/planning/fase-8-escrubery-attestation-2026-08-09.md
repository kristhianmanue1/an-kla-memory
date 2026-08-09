# F8-E — atestación opcional de perfiles mediante Escrubery

- **Estado:** formalizado como subtrack de investigación; adapter no autorizado.
- **Fecha:** 2026-08-09
- **ADR rector:** ADR-0029 (Propuesta)
- **Dependencia externa:** `kristhianmanue1/escrubery`, issue #1.

## Propósito y decisión de frontera

Escrubery se evalúa como plano de control para observar identidad, procedencia y
política de datos de un modelo de embeddings. No es candidato a almacenar
memoria, vectores ni índices de AN-KLA, y no participa en ranking o escritura.

La frontera propuesta es:

```text
Escrubery observa y atestigua -> host verifica y selecciona
       -> AN-KLA liga el digest -> backend derivado recupera
```

La firma prueba que un emisor produjo ciertos bytes; no prueba por sí sola que
el modelo sea correcto, seguro, privado o adecuado. El host conserva la
autoridad para fijar claves, aceptar el perfil y permitir cualquier transmisión
de datos.

F8-E no es precondición del índice semántico genérico. Sólo se vuelve gate si se
elige implementar o distribuir un adapter de Escrubery.

## Evidencia de entrada

La revisión del 2026-08-09 comparó el checkout local de Escrubery en
`8553110029461f2fea8389093e43583ec7053ee6` con su `origin/main` en
`55d710bf343e6fbaa78713c3a50f5290e912b101`:

- el checkout tenía 48 commits no presentes en el remoto;
- el diff abarcaba 87 archivos, 15 610 inserciones y 788 eliminaciones;
- el remoto no exponía los tags locales, CI, licencia, issues o PRs;
- el unit test observado cubría sólo el smoke “Hello World” y el E2E fallaba al
  cargar Kysely ESM;
- TypeScript compilaba, el size gate pasaba y el escaneo básico no encontró
  secretos;
- no existen embeddings, vector store, BM25 o retrieval semántico en Escrubery.

La auditoría también detectó cuatro bloqueadores para confiar en su output:

1. la fuente remota no reconstruye el sistema analizado;
2. Evidentia puede bifurcar la cadena bajo escritores concurrentes y su replay
   puede modificar campos incluidos en el hash sin recalcular firma;
3. se anuncia un checkpoint firmado, pero el camino observado deja
   `checkpoint_id` en `null` y no implementa el objeto verificable;
4. la introspección F3 usa un `docker run` insuficientemente aislado, sin
   digest/allowlist y puede persistir evidencia vacía tras fallo.

El análisis completo y sus correcciones propuestas quedaron durables en:

https://github.com/kristhianmanue1/escrubery/issues/1

**Veredicto vigente:** `PROCEED` como insumo de diseño; `FIX-AND-RETRY` antes de
integración runtime; `REJECT` como motor vectorial.

## Contrato candidato

El spike debe congelar un JSON Schema exacto. La preimagen de negocio mínima es:

```json
{
  "schema": "escrubery/embedding-profile-attestation-v1",
  "provider": "local|remote",
  "model_id": "...",
  "model_revision": "...",
  "artifact_sha256": "sha256:...",
  "dimensions": 384,
  "normalization": "l2/v1",
  "distance": "cosine",
  "runtime": "...",
  "locality": "local|remote",
  "data_policy": {},
  "observed_at": "RFC3339 UTC",
  "valid_until": "RFC3339 UTC",
  "sources": [],
  "evidentia_checkpoint": "sha256:..."
}
```

El sobre de firma debe separar `payload`, `payload_sha256`, canonicalización,
algoritmo, `signer_kid` y firma. `evidentia_checkpoint` sólo puede emitirse
cuando exista un checkpoint real que el verificador pueda reconstruir; nunca se
rellena con una cabeza autodeclarada.

El manifest de AN-KLA no copia confianza del emisor. Liga, como datos:

- digest de la atestación exacta;
- digest y versión de la clave/política fijada por el host;
- modelo, revisión, artefacto, dimensión, normalización y distancia;
- revisión/project de AN-KLA y fingerprint completo del índice.

Secretos, tokens, endpoints con credenciales, rutas absolutas y evidencia raw
innecesaria quedan fuera de ambos objetos.

## Invariantes

1. AN-KLA no consulta la base, HTTP o MCP de Escrubery en el hot path.
2. Escrubery nunca escribe segmentos, revisiones, índices o checkpoint AN-KLA.
3. La atestación es dato no confiable hasta validar schema, digest, firma,
   algoritmo, clave, vigencia y política local.
4. El perfil se selecciona mediante configuración/autoridad externa, nunca por
   memoria recuperada ni por contenido de la atestación.
5. Expiración, firma inválida, modelo cambiado o resolver ausente hacen el
   índice incompatible/stale y producen degradación visible.
6. Scan/FTS siguen disponibles sin Escrubery.
7. El core depende de una interfaz genérica de perfil; el adapter externo no
   define el contrato canónico interno.
8. Verificar identidad del modelo no autoriza enviar memoria a un proveedor.
9. Ninguna atestación eleva autoridad de facts, events, episodes o propuestas.
10. Una clave revocada o fuera de vigencia no valida una atestación nueva; la
    política para artefactos históricos debe quedar versionada.

## Secuencia ejecutable

### F8-E0 — fuente reproducible

- sincronizar el código evaluado en el remoto privado mediante cambios
  revisables;
- fijar commits/tags, CI local y remoto, suite y decisión explícita de licencia;
- eliminar la dependencia de un checkout único no reconstruible.

**Gate:** clone limpio del commit declarado reproduce build y tests.

### F8-E1 — endurecer Evidentia

- append inmutable y serializado por cadena;
- replay idempotente sin mutar campos hasheados;
- checkpoint firmado real y verificador read-only;
- keyring con algoritmo, vigencia, revocación y sucesión;
- fault injection y test de escritores concurrentes.

**Gate:** golden chain/checkpoint y pruebas de fork, truncamiento, replay y key
rotation pasan sin confiar en la base viva.

### F8-E2 — endurecer F3

- perfiles allowlisted e imágenes/paquetes fijados por digest;
- red deshabilitada, rootfs read-only, capabilities eliminadas, usuario no root
  y límites de PID/CPU/RAM/salida;
- capturar stdout, stderr, exit, signal, timeout, versión y digest;
- cero mutación del inventario ante evidencia inválida o proceso fallido;
- diff estructurado `added/changed/removed`.

**Gate:** fixtures hostiles demuestran aislamiento y no-mutación.

### F8-E3 — perfil de embedding

- implementar de forma contractual `resolver_identidad_modelo` y
  `politica_datos_proveedor`;
- congelar schema, canonicalización, límites y códigos de error;
- producir golden attestations válidas, expiradas, revocadas y manipuladas.

**Gate:** paridad de contrato y tests entre CLI/HTTP/MCP/export.

### F8-E4 — snapshot desacoplado

- exportar payload, firma, checkpoint y material público mínimo;
- verificar offline, sin PostgreSQL vivo, MCP o red;
- documentar retención, revocación y privacidad.

**Gate:** un consumidor limpio verifica el bundle o falla cerrado con razón
estable.

### F8-E5 — spike de adapter AN-KLA

- implementar fuera del core un resolver contra fixtures, no contra servicio
  vivo;
- verificar atestación y ligar su digest al manifest del índice;
- probar expiración, model drift, dimensión distinta, key rotation y ausencia;
- comparar el perfil directo del host con el perfil atestiguado.

**Gate:** ronda adversarial `proceed` y autorización explícita del maintainer
antes de integrar o distribuir el adapter.

## Criterio de cierre

F8-E se cierra como uno de estos resultados:

- **adoptar:** E0–E5 pasan y el adapter opcional preserva todos los invariantes;
- **rechazar:** la atestación no aporta valor suficiente frente a un perfil
  fijado directamente por el host;
- **diferir:** Escrubery sigue siendo insumo documental, sin dependencia runtime
  ni capacidad anunciada.

En ninguno de los tres casos Escrubery se convierte en store autoritativo o
motor de búsqueda de AN-KLA.
