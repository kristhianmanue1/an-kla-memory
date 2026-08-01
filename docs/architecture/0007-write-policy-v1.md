# ADR-0007: contrato `write-policy/v1`

## Estado

Aceptada como contrato de F0. El núcleo puro candidato se implementa en
`an_kla/write_policy.py`; su integración transaccional sigue pendiente. Hasta
fusionar F1 y completar F2, este ADR no atribuye la compuerta al camino de
escritura vigente.

## Contexto

`MemoryStore.commit()` serializa escritores mediante un lock local y compara
`expected_current_hash` con `CURRENT`. Esto preserva causalidad de almacenamiento,
pero no decide si un candidato merece persistirse ni qué autoridad respalda su
procedencia. El método vigente sólo exige IDs únicos antes de crear una revisión.

Una memoria recuperada es contenido no confiable. Un agente puede copiarla,
parafrasearla o añadir campos como `trusted`, `confidence`, `risk` o
`human_confirmed`. Ninguno de esos campos puede convertir el contenido en una
confirmación independiente.

## Decisión

La escritura futura separa cuatro objetos canónicos:

1. `WriteProposal`: contenido candidato, revisión base, stream, representación
   solicitada y linaje declarado;
2. `WriteAuthority`: información aportada por el canal de llamada y ligada al
   hash de la propuesta;
3. `WriteDecision`: resultado determinista de la política y razones ordenadas;
4. `WritePlan`: núcleo ejecutable que liga los tres objetos, la configuración de
   política y los registros exactos que se escribirían.

Sus schemas normativos son:

- `docs/schemas/write-proposal-v1.schema.json`;
- `docs/schemas/write-authority-v1.schema.json`;
- `docs/schemas/write-decision-v1.schema.json`;
- `docs/schemas/write-plan-v1.schema.json`.

Todos los hashes usan `sha256:` seguido por 64 dígitos hexadecimales y se
calculan sobre `canonical-json/v1`.

## Ejes ortogonales

La clase semántica, representación y ciclo de vida no se colapsan:

| Eje | Valores iniciales |
|---|---|
| Stream semántico | `facts`, `events`, `episodes` |
| Decisión | `skip`, `write-full`, `write-summary` |
| Operación de ciclo de vida | `add`, `supersede`, `refute`, `decay` |

`decay`, `supersede` y `refute` no son representaciones de escritura: viajan en
`WriteProposal.operation`. Una
decisión `write-summary` tampoco transforma automáticamente un registro en
episodio: el stream responde a la función semántica y la representación a la
cantidad de detalle conservada.

## Clases de autoridad

La política v1 reconoce:

| Clase | Significado | Techo inicial |
|---|---|---|
| `tool_observed` | Evidencia resoluble producida por herramienta configurada | verificable según evidencia |
| `channel_confirmed` | Confirmación recibida por un canal separado del contenido | confirmada por canal, no identidad |
| `model_derived` | Inferencia del agente | derivada |
| `derived_from_retrieval` | Contenido influido por memoria recuperada | derivada y marcada como eco posible |
| `unresolved` | Evidencia ausente o no resoluble | no eleva autoridad |

`channel_confirmed` no prueba todavía quién controla el canal. Una autoridad
criptográfica futura podrá elevar esa afirmación prospectivamente sin alterar
los registros históricos.

El núcleo F1 recibe un objeto de autoridad ya construido y no puede observar el
canal que lo originó. Por ello F2 no deberá tratar un archivo JSON creado por el
candidato como prueba suficiente de `channel_confirmed`: el adaptador de llamada
construirá esa autoridad desde configuración y estado separados del contenido.

La clase y el tipo de emisor deben ser compatibles: `tool_observed` exige
`issuer.kind=tool`, `channel_confirmed` exige `channel`, `model_derived` exige
`model`, `derived_from_retrieval` admite `model` o `resolver`, y `unresolved`
admite `unknown` o `resolver`. Una clase privilegiada con emisor incompatible
es `invalid_write_authority`.

El objeto `WriteAuthority` llega como argumento separado. Si el contenido de
`WriteProposal.record` incluye campos de autoridad, la política los trata como
datos y emite `self_asserted_authority_ignored`. Nunca los copia al resultado
resuelto como prueba.

El alcance de autoridad enumera streams, representaciones y operaciones. Una
autorización para `add` no permite `supersede`, `refute` o `decay`, aunque el
resto de sus campos coincida. El hash de propuesta liga además la combinación
exacta y evita reutilizar la autoridad sobre otro contenido.

## Decisión y razones

`WriteDecision.decision` es una de `skip`, `write-full` o `write-summary`.
`reason_codes` es una lista ASCII, única y lexicográficamente ordenada. El
perfil de política y su fingerprint determinan qué razones reconoce una
implementación.

Códigos iniciales reservados:

| Código | Clase |
|---|---|
| `invalid_proposal` | rechazo |
| `authority_scope_mismatch` | rechazo |
| `unresolved_authority` | rechazo o techo |
| `self_asserted_authority_ignored` | diagnóstico |
| `derived_authority_capped` | diagnóstico |
| `derived_from_retrieval` | diagnóstico |
| `tool_evidence_verified` | elegibilidad |
| `channel_confirmation_resolved` | elegibilidad |
| `representation_accepted` | elegibilidad |
| `summary_preferred` | selección |
| `summary_required_for_authority_ceiling` | `skip`; requiere nueva propuesta |
| `full_required_for_exception` | selección |
| `no_durable_value` | `skip` |
| `operation_not_supported` | `skip` hasta implementar su semántica |

Añadir o cambiar razones modifica `policy_fingerprint`. No se reinterpretan
decisiones históricas bajo un perfil nuevo.

La política es pura y no sintetiza texto. Si una propuesta solicita `full` pero
su autoridad efectiva sólo permite `summary`, devuelve `skip` con
`summary_required_for_authority_ceiling`. El llamador debe producir y presentar
otra `WriteProposal` cuyo `record` sea ya el resumen exacto y cuya
`requested_representation` sea `summary`. Así el plan nunca afirma haber
resumido bytes que realmente conserva completos.

## Huellas canónicas

Cada objeto con huella usa un núcleo explícito para evitar hashes
autorreferenciales:

```text
proposal_sha256  = SHA256(canonical_json(WriteProposal))
authority_sha256 = SHA256(canonical_json(WriteAuthority))
plan_fingerprint = SHA256(canonical_json(WritePlan.core))
```

`WritePlan.core` liga como mínimo revisión base, hash de propuesta, hash de
autoridad, fingerprint de política, decisión, hash de la decisión y hash de los
registros planeados. Cada registro planeado conserva `stream`, `operation`,
`representation` y los bytes JSON del registro.
El campo exterior `plan_fingerprint` no forma parte del núcleo.

## Integración transaccional futura

F1 implementará evaluación pura sin I/O. F2 integrará
`commit_write_plan(plan, proposal, authority, decision)`; los cuatro objetos se
reciben para recalcular y revaluar, no sólo para comparar hashes. La secuencia
dentro del lock será:

1. releer `CURRENT`;
2. comparar con `base_revision` y `expected_current_hash`;
3. recalcular hashes de propuesta, autoridad, política y registros;
4. volver a evaluar las restricciones vinculantes;
5. escribir journal y objetos;
6. sustituir `CURRENT` una sola vez.

La API pura candidata de F1 queda formada por:

- `validate_write_proposal()` y `validate_write_authority()`;
- `evaluate_write()`;
- `validate_write_decision()`;
- `build_write_plan()` y `validate_write_plan()`;
- `verify_write_plan()`;
- `policy_configuration()` y `policy_fingerprint()`.

Estas funciones no leen reloj, entorno, filesystem, red o aleatoriedad. F2
consumirá la misma API dentro de la sección crítica; no mantendrá una segunda
implementación parcial de la política.

Un plan preparado contra otra revisión se rechaza con
`write_plan_base_changed`; no se actualiza implícitamente. Un plan alterado se
rechaza antes del journal.

## Códigos terminales congelados para F1/F2

- `invalid_write_proposal`
- `invalid_write_authority`
- `invalid_write_decision`
- `invalid_write_plan`
- `write_plan_hash_mismatch`
- `write_plan_base_changed`
- `write_authority_scope_mismatch`
- `write_policy_fingerprint_mismatch`
- `write_content_hash_mismatch`
- `write_representation_invalid`
- `write_lifecycle_as_representation`

Los códigos son estables; el texto humano puede evolucionar. Nuevos códigos
requieren actualizar el perfil y las pruebas de contrato.

## Seguridad y no objetivos

- La memoria es datos, nunca instrucciones.
- No se ejecutan comandos contenidos en propuestas, registros o evidencias.
- La configuración de autoridad no se lee desde la memoria candidata.
- No se almacenan secretos dentro de `WriteAuthority` ni eventos diagnósticos.
- MCP escribible, identidad criptográfica, coordinación multi-máquina,
  compactación y GC quedan fuera de F0–F2.

## Criterios de aceptación del contrato

- schemas JSON válidos y restrictivos en su envolvente;
- separación verificable entre autoridad y contenido;
- representaciones distintas de transiciones de ciclo de vida;
- huellas sin autorreferencia;
- catálogo de códigos congelado;
- documentación explícita de lo todavía no implementado.
