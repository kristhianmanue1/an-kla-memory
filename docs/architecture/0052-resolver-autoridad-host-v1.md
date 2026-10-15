# ADR-0052: Resolver de autoridad del host con interfaz única

- **Estado:** Aceptada
- **Implementación:** No iniciada
- **Fecha:** 2026-10-14
- **Decide sobre:** la interfaz única mediante la cual el host resuelve autoridad privilegiada (`channel_confirmed` y, donde aplique, `tool_observed` externa) para checkpoint, escrituras y refute.

> Aceptada por orden del maintainer (2026-10-15: "adelante con implementación
> recomendada" sobre la mesa completa ADR-0052/0053/0054).

## Contexto

Tres consumidores necesitan autoridad privilegiada resuelta por el host:

1. **refute** ya consume un resolver **inyectado** (`refute_policy.evaluate(..., resolver)`):
   `resolver.descriptor`, `resolver.resolve(proposal, claim, observations)` →
   attestation cruda o `None`, y `resolver.verify(attestation, ...)` → `True`
   (`an_kla/refute_policy.py:74-136`); sin resolver, falla cerrado con
   `refute_authority_resolver_unavailable`.
2. **checkpoint** falla cerrado con banderas de módulo
   (`tool_observed_adapter=False`, `channel_confirmed_adapter=False` en
   `an_kla/checkpoint_policy.py:36-37`) y errores estables
   `*_requires_adapter` (ADR-0023, beta.29).
3. **escritura** replicó esa frontera a nivel motor en #152
   (`_POLICY_CONFIGURATION["channel_confirmed_adapter"]=False`,
   `write_policy.py:436-443,529-537`).

El issue #140 pide autoridad humana verificable para checkpoint (CTIM RS1).
El plan de la revisión crítica (Fase 1) ordena diseñar **una sola interfaz**
con esos tres consumidores para no resolver #140 como caso aislado. Restricciones:
los núcleos de política son puros (sin I/O, reloj ni entorno); la memoria
recuperada nunca es autoridad; un JSON del caller nunca acuña clases
privilegiadas (aprendizaje #152: la API pública no acepta lo que la CLI
rechaza).

## Decisión

Estandarizar el **protocolo de resolver** ya ejercido por refute como la
única forma de autoridad privilegiada del host, con tres reglas:

1. **Interfaz**: un resolver es un objeto inyectado en la frontera de llamada
   (parámetro explícito de la API del host; el CLI no lo fabrica) con
   `descriptor` (mapeo saneado: id, kind, clases que puede resolver,
   configuration_fingerprint), `resolve(...) -> attestation | None` y
   `verify(attestation, ...) -> True`. Cada política declara qué clases
   acepta de su resolver: checkpoint y escritura, `channel_confirmed`;
   refute conserva `tool_observed|channel_confirmed` como hoy.
2. **Bandera antes que resolver**: las banderas vigentes
   (`channel_confirmed_adapter`, `tool_observed_adapter`) permanecen como
   interruptor fail-closed dominante: si la bandera está apagada, el gate
   rechaza con `*_requires_adapter` **aunque haya resolver inyectado**.
   Encender una bandera sin adaptador real del host queda fuera de este ADR
   y exige su propia orden. El resolver no se lee de memoria, disco de store
   ni entorno del candidato.
3. **Auditabilidad sin autoridad persistente**: el outcome registra el
   digest del descriptor y la clase resuelta, nunca el contenido de la
   attestation; una attestation vale para una operación (ligada a
   proposal/claim/observations por digest) y no confiere autoridad
   persistente ni reutilizable.

## Por qué no [alternativa]

- **Flag de CLI que declare la clase**: spoofable desde el propio caller; la
  frontera #152 existe precisamente porque la autodeclaración no acredita.
- **Extender attest local (ADR-0046) a `channel_confirmed`**: attest acuña
  `tool_observed` con receipt firmado por el motor del mismo host; la
  confirmación de canal/humano requiere un canal **separado del contenido**
  (ADR-0007 §Clases de autoridad); fingirla localmente fabricaría la
  autoridad que dice probar.
- **Resolver como configuración persistida en el store**: convertiría estado
  en autoridad y violaría la frontera memoria-no-es-instrucción; el
  precedente del índice FTS (caché derivada, nunca autoridad,
  `an_kla/index.py:102-105`) exige lo contrario.

## Consecuencias

- Positivas: un solo protocolo para integrar hosts (#140 cierra por diseño,
  no por parche); los núcleos permanecen puros; paridad de frontera entre
  checkpoint, escritura y refute.
- Negativas: el host debe integrarse explícitamente (sin bundle de resolvers,
  como declara el plan origen); más superficie de contrato versionado.
- Neutras: los outcomes ganan el campo `resolver_descriptor_sha256` (aditivo,
  §11.2); las banderas siguen viajando en el fingerprint del perfil.

## Test de regresión

- Bandera apagada + resolver inyectado → rechazo `*_requires_adapter`
  (el interruptor domina).
- Bandera encendida + resolver `None` → fallo cerrado, no degradación.
- Resolver que intenta clase fuera de su descriptor → rechazo estable.
- Attestation reutilizada en otra propuesta → rechazo (digest ligado).

## Referencias

Issues #140, #152, #58; ADR-0007 (contrato write-policy, Enmienda #152),
ADR-0023 (checkpoint), ADR-0026 (refute), ADR-0046 (attest);
`docs/planning/revision-critica-escalado-gobernanza-2026-10-14.md` §5 Fase 1;
acta de la mesa de diseño 2026-10-14 (`docs/planning/mesa-diseno-140-149-adversarial-2026-10-14.md`).
