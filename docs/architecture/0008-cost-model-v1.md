# ADR-0008: contrato `cost-model/v1`

## Estado

Aceptada como contrato de F0. El producto continúa ejecutando exclusivamente
presupuestos exactos en bytes UTF-8 hasta que F3 implemente este contrato.

## Contexto

AN-KLA mide hoy el payload canónico completo de `context-assembly/v1` en bytes.
Esta garantía es reproducible y no depende de proveedor, pero no equivale al
conteo de tokens de un modelo. Tampoco incluye framing adicional que el host
pueda insertar después de recibir el resultado.

No existe un tokenizer universal. Una garantía exacta requiere identificar el
algoritmo, vocabulario, versión, configuración y payload medido. La ausencia o
falla del tokenizer no puede convertirse silenciosamente en una estimación.

## Decisión

F3 introducirá una interfaz `CostModel` con tres perfiles:

| Perfil | Estado previsto | Dependencias del núcleo |
|---|---|---|
| `utf8-bytes/v1` | universal, exacto y predeterminado | ninguna |
| `tokenizer-callback/v1` | exacto para callback configurado | ninguna |
| `external-tokenizer/v1` | exacto para proceso y fingerprint configurados | ninguna biblioteca; proceso opt-in |

El adaptador externo recibe bytes canónicos y una lista `argv` configurada fuera
de la memoria. No usa shell, red por defecto ni comandos provenientes de datos
recuperados.

El resultado normativo usa
`docs/schemas/cost-certificate-v1.schema.json`.

## Certificado de costo

Un `CostCertificate` liga:

- `payload_sha256` del payload canónico exacto;
- `canonicalization_profile`;
- `cost_unit`, `count` y `status`;
- `cost_model_profile` y `configuration_fingerprint`;
- identidad y fingerprint del tokenizer cuando la unidad es `tokens`;
- códigos de diagnóstico ordenados y únicos;
- declaración `host_framing_measured`.

Un certificado dentro de un registro de memoria es sólo dato. Se acepta para
una garantía únicamente si lo produjo el `CostModel` elegido por configuración
externa durante esa operación.

## Semántica de exactitud y degradación

`status=exact` significa exactitud respecto del payload, unidad y configuración
declarados. No significa exactitud del prompt total del host.

`status=degraded` sólo es válido cuando el llamador autorizó explícitamente un
perfil alterno. Al pedir un presupuesto de tokens estricto, ausencia, timeout,
salida inválida, fingerprint distinto o no convergencia fallan cerrado.

El perfil de bytes actual conserva los campos `budget_bytes` y `used_bytes` sin
cambiar su significado. Los perfiles de tokens añaden campos separados
`budget_tokens` y `used_tokens`; nunca reutilizan los nombres de bytes.

## Payload y punto fijo

El conteo cubre la envolvente canónica completa que entrega AN-KLA, no sólo el
texto de los registros. Si el payload incluye su propio conteo, la construcción
itera hasta que el valor declarado coincide con el conteo observado.

Una implementación debe:

1. detectar ciclos de valores observados;
2. imponer un máximo de iteraciones versionado;
3. devolver `cost_not_converged` si no encuentra punto fijo;
4. no emitir un payload presentado como presupuestado después del fallo.

`host_framing_measured` permanece `false` salvo que un adaptador de host mida y
pruebe explícitamente los marcadores que agrega. El tokenizer por sí solo no
cierra esa frontera.

## Fingerprints

```text
payload_sha256 = SHA256(payload_canónico)
configuration_fingerprint = SHA256(canonical_json(configuración_saneada))
tokenizer_fingerprint = identificador content-addressed del tokenizer efectivo
```

La configuración saneada excluye secretos y rutas absolutas. Cambiar tokenizer,
vocabulario, normalización, argumentos, serialización o política de fallback
produce un fingerprint distinto.

## Códigos terminales congelados para F3

- `invalid_cost_model`
- `invalid_cost_certificate`
- `cost_payload_hash_mismatch`
- `tokenizer_fingerprint_mismatch`
- `tokenizer_unavailable`
- `tokenizer_timeout`
- `tokenizer_invalid_output`
- `negative_cost`
- `cost_not_converged`
- `cost_fallback_not_authorized`

Diagnósticos no terminales iniciales:

- `degraded_to_utf8_bytes`
- `host_framing_unmeasured`

Los códigos son estables y forman parte del contrato observable.

## Seguridad

- `argv` se recibe desde configuración del proceso, nunca desde memoria.
- No se usa `shell=True`.
- stdout tiene un límite y un schema estricto; stderr se sanea.
- Timeout y terminación son obligatorios para procesos externos.
- No se copian secretos ni rutas absolutas al certificado.
- Un conteo negativo, booleano, flotante o fuera de rango se rechaza.

## Compatibilidad

F3 debe demostrar que `utf8-bytes/v1` produce exactamente los mismos payloads,
selecciones y conteos que el perfil vigente. Tokenizer es opt-in; su ausencia no
rompe recuperación o ensamblado por bytes.

## No objetivos

- escoger un tokenizer universal;
- descargar vocabularios o modelos;
- medir framing desconocido del host;
- afirmar equivalencia entre tokens de proveedores distintos;
- cambiar el objetivo de recuperación;
- implementar compactación, firma o coordinación distribuida.

## Criterios de aceptación del contrato

- certificado ligado al payload y configuración exactos;
- perfiles y unidades no ambiguos;
- fallback explícito y diagnosticado;
- fallo cerrado para garantía estricta de tokens;
- compatibilidad byte a byte preservada;
- frontera del host declarada sin sobreafirmar.
