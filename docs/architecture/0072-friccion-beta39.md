# ADR-0072: Un intento que no concluye no rebaja lo comprobado, y lo guardado se ve al escribir

- **Estado:** Aceptada por delegación del orquestador (mandato 15), 2026-11-20, tras r1 `fix-and-retry` (2 HIGH, 2 MEDIUM, 1 LOW) y r2 `proceed` de otra familia (Gemini); todo incorporado
- **Implementación:** No iniciada
- **Fecha:** 2026-11-20
- **Decide sobre:** las correcciones del primer día de uso real de beta.39:
  - la errata 6 de `memoria/ancla/v2` en la auditoría y la lectura de anclas `document`;
  - la pista y la normalización de `--subject`;
  - que `remember` y `state show` devuelvan el ámbito guardado.
- **Enmienda:** ADR-0071 §5 (qué resultado guardado se sirve) y ADR-0069 §4 (qué claves lleva un registro servido).
- **Contrato:** `memoria/ancla/v2`, errata 6 (2026-11-20). C0 sin cambios.
- **Origen:** informe de adopción de beta.39 del segundo usuario real, §7.2, §7.4, §7.5 y §7.6.

## Contexto

- **El caso.** Un consumidor auditó una cita `fresh` desde un entorno sin tabla de custodios. `anchors verify` dio rc 0 y guardó una anotación `unverified` / `no_adapter`. ADR-0071 §5 sirve el último resultado por fecha, así que la cita pasó a servirse como no comprobada **sin que nada hubiera cambiado**. Tampoco hubo ningún aviso.
- **El contrato.** La errata 6 lo corrige: un intento que no concluye no sustituye a un resultado concluyente.
- **Las otras dos fricciones:**
  - el error de `--subject` no dice qué valor espera, aunque la herramienta lo conoce;
  - lo que se guardó con ámbito no se ve ni en la respuesta de `remember` ni en `state show`.

## Decisión

### 1. Concluyente y no concluyente (errata 6)

- **Un resultado guardado no concluye** si su `integrity_reason` es `no_adapter` o `adapter_error`. Si no, **concluye**: el adaptador respondió de forma válida, o la copia local contradijo, porque A3 pone `copy_sha_mismatch` antes que `no_adapter` y `adapter_error`.
  - Se deriva de lo guardado, sin campo nuevo. Por eso vale también para las anotaciones que ya escribió beta.39.
  - `custodians_config_error` es un `adapter_error`, así que tampoco concluye.
- **Al leer** se sirve, de entre los candidatos de ADR-0071 §5:
  - el último **concluyente**, con el mismo orden total `(checked_at, origen, enqueued_at, id)`;
  - si no hay ninguno concluyente, el último a secas, como hasta ahora.
- **Efecto sobre lo ya escrito.** La cita del caso vuelve a servirse `fresh` sin tocar el store: la anotación `no_adapter` sigue ahí y simplemente deja de ganar. Es el único cambio de lectura de esta versión, y sólo afecta a anclas `document` con un intento no concluyente posterior a uno concluyente.

### 2. La auditoría informa y avisa

- `anchors verify` sigue guardando cada intento, también el que no concluye, porque la errata lo permite («puede guardarse aparte»). Así queda la fecha y el motivo del último intento. Al leer no gana (§1).
- **La respuesta, por ancla `document`:**
  - si el intento no concluye y hay un resultado concluyente anterior, lleva además `served: {freshness, reason, checked_at}`, lo que leer seguirá sirviendo;
  - las tres comprobaciones del intento salen tal cual;
  - el agregado `anchors_freshness` del registro se sigue calculando sobre las comprobaciones **del intento** (r1, R72-03). La respuesta de `anchors verify` describe la auditoría que se acaba de hacer, y `served` dice lo que leer seguirá sirviendo.
- **Aviso** (r1, R72-02: tres casos distintos):
  - custodio que **no está en la tabla**, o **no hay tabla**: `warnings` con `custodian_not_configured` (abajo);
  - **tabla ilegible**: `custodians_config_error`, como en ADR-0071 §3, sin `custodian_not_configured`;
  - **proceso que falla** (`adapter_error` con el custodio sí configurado): ningún aviso de configuración, porque la configuración está bien.

  En los tres casos, `served` conserva el concluyente anterior.
- **Forma del aviso.** La respuesta lleva en su raíz `warnings: [{"code": "custodian_not_configured", "custodian": "<id>", "anchors": <n>}]`, una entrada por custodio, cuando algún ancla auditada nombra un custodio que no está en la tabla, o cuando no hay tabla. El rc no cambia: es un aviso, no un fallo.
- **Esquema:** `anchors-verify-v2` está publicado (beta.39), así que una respuesta con `served` o `warnings` sube, de forma dispersa, a `anchors-verify-v3`.

### 3. `--subject`: pista con el valor esperado y mayúsculas

- **Pista.** `remember_subject_invalid` (y `retrieve_subject_invalid`, `list_subject_invalid` y `state_subject_invalid`) lleva en su pista el `repo.id` canónico del proyecto: «se esperaba un `repo.id` de C0 canónico, en minúsculas; por ejemplo, el de este proyecto es `<repo.id>`» (r1, R72-05: una `directive` puede tratar de otro proyecto). Si no se puede calcular (sin `git`), la pista de hoy.
- **Mayúsculas.** C0 normaliza el `repo.id` de un remoto pasándolo entero a minúsculas (`normalize_remote`), y las formas `local:`/`remoto:` llevan hexadecimal en minúsculas. Una entrada que sólo difiere de un `repo.id` canónico por mayúsculas, es decir, cuya versión en minúsculas es canónica, no tiene otra lectura posible.
  - Se acepta y se guarda **en minúsculas**, al escribir y al leer.
  - La respuesta de `remember` lo dice con `subject_normalized_from: <lo dado>`.
  - Cualquier otra diferencia (esquema `https://`, `.git` final, espacios) se sigue rechazando con la pista: no se adivina.

### 4. Lo guardado se ve al escribir y en `state show`

- **`remember`** devuelve en su respuesta el ámbito y la vigencia guardados, cuando los hay: `subject`, `audience`, `valid_until`, `valid_until_input`, `until_revoked` y `revokes`, más `subject_normalized_from` (§3; r1, R72-01). Una respuesta con alguna de esas claves sube, de forma dispersa, a `remember-result-v3`, porque `remember-result-v2` está publicado.
- **`state show`** muestra `subject` y `audience` de una casilla cuya cabeza los trae explícitos, sea o no para el lector. `state-result-v2` ya tiene esas claves opcionales (ADR-0069), así que no sube de versión. Enmienda ADR-0069 §4, que sólo las mostraba con `--include-other-audience`.
- Sin ámbito explícito, ninguna respuesta cambia.

### 5. Lo que no cambia

- Un localizador con elementos en orden inverso sigue respondiendo `anchor_locator_invalid`. El adaptador sólo dice `locator: invalid` (contrato), y no se inventa un motivo más fino que el contrato no tiene (§7.9).
- `ocr_text` sigue saliendo `unverified` / `derived_modality` con las tres comprobaciones en `verified`, como fija el contrato. Se documenta en la guía (§7.3); un nivel `derived` sería un cambio de contrato.
- Retrieve, MCP, la cobertura y los 61 casos de v2 no cambian: la errata 6 dice que todos describen una sola comprobación.

## Por qué no

- **No guardar el intento que no concluye:** se perdería la fecha y el motivo del último intento, que es justo lo que ayuda a ver que el entorno está mal configurado. La errata lo permite, y la lectura ya no le da peso.
- **Un campo `conclusive` en la anotación:** cambiaría `anchor-check-v1`, que está publicado, y no arreglaría lo ya escrito. Derivarlo de `integrity_reason` sí lo arregla.
- **Normalizar más que las mayúsculas:** quitar `https://` o `.git` es adivinar un remoto, y C0 no lo hace sobre un `repo.id` ya dado.

## Consecuencias

- **Positivas:**
  - una auditoría desde un entorno mal configurado ya no rebaja en silencio lo comprobado, y además avisa;
  - lo que el consumidor ya tiene rebajado vuelve a `fresh` sin migración;
  - escribir con ámbito se puede comprobar en la misma respuesta.
- **Negativas:** si el documento cambia de verdad y las auditorías posteriores fallan siempre, se sigue sirviendo el último concluyente, con su `checked_at` antiguo. Es lo que pide la errata, y la fecha lo dice.
- **Neutras:** las anotaciones siguen sin poda (límite de ADR-0071).

## Pruebas de aceptación

1. **El caso exacto:**
   - un ancla `document` escrita `fresh` con un adaptador de prueba;
   - `anchors verify` sin tabla de custodios: rc 0, la respuesta lleva `warnings` con `custodian_not_configured` y el ancla con `served.freshness: fresh`;
   - después se lee con `history` y `state show`: sigue `fresh`, con el `checked_at` de la escritura.
   - Con un adaptador que falla (`adapter_error`, custodio configurado): sin aviso de configuración, `served.freshness: fresh`, y leer sigue `fresh`.
   - Con la tabla ilegible: `custodians_config_error`, sin `custodian_not_configured`, `served.freshness: fresh`, y leer sigue `fresh` (r1, R72-02).
2. **Lo concluyente sí manda:**
   - tras un `fresh`, una auditoría con respuesta válida que da `broken` (`quote_absent`) se sirve `broken`; con `copy_sha_mismatch`, también;
   - la secuencia `fresh` → `broken` → `no_adapter` se sirve **`broken`**: un intento que no concluye no tapa una contradicción (r1, R72-04).
3. **Sin resultado concluyente previo,** el intento se sirve como hasta ahora (`unverified`/`no_adapter`).
4. **Store escrito por beta.39** con la anotación `no_adapter` posterior a un `fresh` (`git archive v0.1.0-beta.39`, `PYTHONPATH`): esta versión lo sirve `fresh` sin escribir nada.
5. **`--subject`:**
   - en mayúsculas se guarda en minúsculas, con `subject_normalized_from`;
   - en `retrieve`, `list` y `state show`, un `--subject` en mayúsculas lee igual que en minúsculas (r1, R72-04);
   - con `https://` o `.git` se rechaza, y la pista trae el `repo.id` del proyecto;
   - sin `git`, la pista de siempre.
6. **`remember` y `state show`:**
   - un `remember` con `--subject`/`--audience`, y una `directive`, devuelven lo guardado, con `remember-result-v3`;
   - `state show` muestra el `subject` de su casilla;
   - sin ámbito, las dos salidas son byte a byte las de beta.39.
7. **Compatibilidad:** los goldens de `retrieve` y MCP, `test_scope_compat` y `test_document_v2_compat` sin regenerar. Los 61 casos siguen exactos.

## Referencias

`memoria/ancla/v2`, errata 6; ADR-0069 §4; ADR-0071 §5; informe de adopción de beta.39 del segundo usuario, §7.
