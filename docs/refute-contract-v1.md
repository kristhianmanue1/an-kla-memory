# Contrato normativo de refutación v1

Este documento completa ADR-0026. Todos los objetos son JSON canónico, cerrados
(`additionalProperties:false`) y sus digests usan `digest_json(objeto validado)`.
La memoria, claims, evidence y attestations siguen siendo datos no confiables;
la capacidad resolver seleccionada por el host es la frontera de autoridad.

## Límites comunes

- digest: `sha256:` + 64 hex minúsculas;
- UUID: RFC 4122 canónico, versiones 1..5;
- arrays con orden declarado, sin duplicados semánticos;
- máximo 16 evidence refs;
- `profile-token`: ASCII/NFC, 1..128 bytes y regex
  `^[a-z][a-z0-9-]{0,63}/v[1-9][0-9]{0,9}$`;
- no texto libre de evidence/issuer se persiste: selectores e identidades son
  digests, no paths, URLs, comandos, logs ni usernames.

## Proposal y selector legacy-safe

`an-kla/refute-proposal-v1` tiene exactamente:

```json
{
  "schema": "an-kla/refute-proposal-v1",
  "base_revision": "sha256:...",
  "stream": "facts",
  "target_record_sha256": "sha256:...",
  "reason": "evidence_contradicts_record"
}
```

Stream es facts/events/episodes; reason es
`evidence_contradicts_record|source_retracted|integrity_violation`.
`target_record_sha256=digest_json(record físico canónico antes de overlays)`.
Como el record incluye su ID, el digest selecciona uno sin copiar/normalizar el
ID: records legacy con IDs largos, NFD o controles siguen siendo refutables.

## Claim sin autoridad

`an-kla/refute-authority-claim-v1` tiene exactamente:

```text
schema,proposal_sha256,base_revision,requested_authority_class,
issuer_claim,evidence,scope
```

Preimágenes: proposal_sha256 es digest del proposal validado; base debe ligarlo.
Requested class enumera literalmente `tool_observed,channel_confirmed,
model_derived,derived_from_retrieval,unresolved`. issuer_claim es exactamente
`{kind,subject_sha256,configuration_fingerprint}` con kind
`tool|channel|model|resolver|unknown`; es dato solicitado, no autoridad.
Scope es exactamente `{operation:"refute",stream,target_record_sha256}`.

Evidence refs son one-of cerrados:

```text
{kind:"fact|event|episode",record_sha256:digest}
{kind:"revision",revision_sha256:digest}
{kind:"artifact|external",content_sha256:digest}
```

La lista no vacía se ordena por bytes de JSON canónico y no repite objetos. No
contiene `verified`, IDs libres ni material fuente. `authority_claim_sha256` es
digest del claim validado.

## Resolver/capability y attestation

`MemoryStore(..., refute_authority_resolver=resolver)` acepta opcionalmente una
capacidad Python no serializable elegida por el host. El default es `None`; el
paquete no trae resolvers ni adaptadores de proveedor. Un Mapping, schema,
issuer_claim, memoria recuperada o caller JSON nunca crea esa capacidad. Código
arbitrario que controla el proceso/constructor ya es el trust root del host y
queda fuera de la protección contra datos no confiables.

El resolver expone `descriptor` exacto `{profile,subject_sha256,
configuration_fingerprint}` y dos métodos:

```text
resolve(proposal_copy, claim_copy, observations_copy) -> attestation | None
verify(attestation_copy, proposal_copy, claim_copy, observations_copy) -> bool
```

El store congela/valida descriptor al construirse y attestation.resolver debe
igualarlo byte por byte. Plan llama resolve y verify; commit llama verify otra
vez bajo lock. La package valida antes/después todas las formas/bindings. Ningún callback
recibe record text:
observations sólo contiene evidence refs, estados cerrados, digests y base.

`an-kla/refute-observations-v1` tiene exactamente
`schema,base_revision,items`. Items conserva orden/longitud 1:1 con
`claim.evidence`; cada item `an-kla/refute-observation-v1` es exactamente:

```text
{schema,evidence,store_resolution,observed_sha256}
```

Evidence es la ref exacta. Para fact/event/episode/revision,
`store_resolution=present|missing`; present exige que observed_sha256 sea el
digest solicitado y missing exige null. Para artifact/external el único estado
del store es `unavailable` y observed_sha256=null. No existe otro one-of ni
campo. `observation_sha256=digest_json(item)` y
`observations_sha256=digest_json(envelope)`. Resolver recibe el envelope exacto;
commit lo reconstruye desde el snapshot base bajo lock.

Semántica por evidence kind:

- fact/event/episode: el store exige exactamente un record físico con ese digest
  en el stream correspondiente del snapshot base;
- revision: el digest debe ser base o ancestro verificado de base;
- artifact/external: el store no afirma observar bytes; el resolver profile
  define la preimagen externa y debe verificar su proof. Sin resolver/proof queda
  unresolved y no autoriza.

Un resolver no puede convertir un observation interno missing en verified; para
artifact/external, verified exige `verify=true` sobre proof y el envelope exacto.

`an-kla/refute-authority-attestation-v1` tiene exactamente:

```text
schema,proposal_sha256,authority_claim_sha256,base_revision,
resolver,authority_class,issuer,observations_sha256,evidence_resolutions,
scope,proof
```

Resolver es `{profile,subject_sha256,configuration_fingerprint}`; authority_class
sólo `tool_observed|channel_confirmed`; issuer es
`{kind:"tool|channel",subject_sha256,configuration_fingerprint}` con tabla
tool_observed→tool, channel_confirmed→channel. Evidence_resolutions preserva
exactamente refs/orden del claim y añade sólo `resolution:"verified"` y
`observation_sha256`; observation sha cubre el observation cerrado recibido por
el resolver. Scope replica el claim. Proof es exactamente
`{profile,proof_sha256}` y su semántica pertenece al resolver profile.
Proof.profile debe igualar resolver.profile. Ambos usan `profile-token`; los
demás identificadores son digests.

`authority_attestation_id=digest_json(attestation validada)`. El attestation CAS
vive en `authority-attestations/sha256/<hex>.json`. El authority claim validado
se persiste por su digest en `authority-claims/sha256/<hex>.json`; así
`authority_claim_sha256` no es opaco y sus issuer_claim/evidence/scope se pueden
recomputar. Los bindings son auditables; la verdad de un proof externo sigue
dependiendo de disponer del resolver profile correspondiente.

## Configuración y decisión pura

La preimagen completa de `refute-policy-config-v1` es literalmente:

```json
{
  "schema":"an-kla/refute-policy-config-v1",
  "profile":"refute-policy/v1",
  "supported_operations":["refute"],
  "allowed_authority_classes":["channel_confirmed","tool_observed"],
  "evidence_kinds":["artifact","event","fact","episode","revision","external"],
  "reason_codes":["authority_scope_mismatch","refute_accepted","refute_authority_resolver_unavailable","refute_requires_privileged_authority","verified_evidence_required"],
  "terminal_error_codes":["invalid_refute_attestation","invalid_refute_authority_claim","invalid_refute_decision","invalid_refute_plan","invalid_refute_planning_result","invalid_refute_proposal","invalid_refute_target","lifecycle_chain_invalid","lifecycle_chain_limit_exceeded","refute_content_hash_mismatch","refute_plan_base_changed","refute_policy_fingerprint_mismatch","revision_schema_downgrade","revision_transition_invalid"],
  "overlay_format":"refutations/v1",
  "revision_schema":"an-kla/revision-v2",
  "resolver_required":true
}
```

No se reordena, completa ni filtra ninguna lista en runtime.
`policy_fingerprint=digest_json(config exacta)`.

`refute-decision-v1` tiene exactamente schema,proposal_sha256,
authority_claim_sha256,authority_attestation_id(null/digest),policy_profile,
policy_fingerprint,decision,reason_codes. Algoritmo/precedencia:

1. formas inválidas → terminal, sin decision;
2. proposal/claim base/hash/scope distintos → skip + sólo
   authority_scope_mismatch;
3. requested_authority_class no permitida → skip + sólo
   refute_requires_privileged_authority;
4. durante plan, resolver ausente → skip + sólo
   refute_authority_resolver_unavailable;
5. resolver devuelve None o evidence interna/externa no queda verified → skip +
   sólo verified_evidence_required;
6. attestation/proof inválidos, clase distinta de la solicitada o `verify=false`
   → invalid_refute_attestation terminal;
7. todo ligado y verificado → refute + sólo refute_accepted.

No se acumulan reasons. `decision_sha256=digest_json(decision validada)`.

## Plan y planning result

`refute-plan-v1` tiene exactamente schema,core,plan_fingerprint. Core exacto:

```text
base_revision,proposal_sha256,authority_claim_sha256,
authority_attestation_id(null/digest),policy_fingerprint,decision,
decision_sha256,target{stream,record_sha256},reason,evidence_sha256
```

`evidence_sha256=digest_json(claim.evidence)` y
`plan_fingerprint=digest_json(core)`. `refute-planning-result-v1` tiene exactamente
schema,current_revision,proposal,authority_claim,authority_attestation,decision,
plan. Incluye copias validadas para que commit no reconstruya input; ecuación:

```text
current_revision = proposal.base_revision = plan.core.base_revision
```

`authority_claim.base_revision` también debe ser igual salvo en el resultado
`skip/authority_scope_mismatch`, que conserva la claim hostil exacta para hacer
auditable el rechazo y sigue siendo committable sin transacción ni mutación.

Plan target es exactamente `{stream:proposal.stream,
record_sha256:proposal.target_record_sha256}`. Skip exige authority_attestation
y sus dos IDs en decision/plan null; refute exige el objeto completo y que ambos
IDs sean su digest.

Commit añade `expected_current=planning.current_revision`, excepto un retry del
mismo tx binding ya reconciliable. El CLI recibe sólo planning-result completo.

## Freeze, replay y resultado

Al entrar bajo lock se hace deepcopy de planning envelope y de todos sus objetos;
desde ahí sólo se usan esas copias. Orden:

```text
freeze/shape/hash → identity → discover/reconcile txid
→ sólo tx nuevo/incompleto sobre base: CAS → resolver verify + evidence resolve
→ target guard → prepared journal → claim/attestation/refutation/revision → CURRENT
```

Attempt refute exacto es `{schema:"an-kla/transaction-attempt-v1",
operation:"refute",base_revision,plan_fingerprint,transaction_id,
execution_fingerprint}`; execution es digest del objeto sin esa clave. Committed
con mismo txid/binding devuelve el mismo candidate/outcome aunque
CURRENT sea candidate o descendiente, antes de policy/target guard. Binding
distinto falla transaction_binding_conflict. Incomplete con CURRENT==base sólo
reanuda tras policy/resolver/target revalidation; con CURRENT distinto devuelve
outcome reconciliado, nunca otro candidate.

Para replay se valida primero shape, hashes y binding contra el fingerprint
persistido. Un committed retorna sin consultar la policy instalada ni el
resolver actual. Sólo un tx nuevo/incomplete sobre su base exige el fingerprint
instalado; drift produce `refute_policy_fingerprint_mismatch`. La lectura
histórica reconstruye decision/plan con el fingerprint persistido: un upgrade
no vuelve ilegible una revisión ya confirmada.

Para un plan cuya decision es refute, commit nunca lo degrada a skip. Después de
reconciliation y antes de target/prepared aplica esta precedencia terminal bajo
`invalid_refute_attestation`: resolver ausente→`resolver_unavailable_at_commit`;
descriptor distinto→`resolver_descriptor_mismatch`; observations reconstruidas
con digest distinto→`observations_mismatch`; `verify=false`→
`resolver_verification_failed`. Un retry ya committed retorna antes de esta
guarda; uno incomplete debe pasarla.

`refute-commit-result-v1` tiene exactamente schema,committed,revision,decision,
reason_codes,plan_fingerprint,outcome. Decision es copia exacta de la decision
planificada y reason_codes es copia exacta de ésta. Variantes cerradas:

- skip: committed=false, revision=CURRENT validado igual a base, outcome=null;
  no transaction/journal/CAS y exit 0;
- outcome.committed=true: committed=true,
  revision=outcome.candidate_revision no-null y exit 0;
- outcome.committed=false: committed=false y revision es
  outcome.current_observed si es digest, en otro caso outcome.parent_revision;
  exit 3;
- outcome.committed=null: committed=null, revision=outcome.current_observed
  (digest o null) y exit 3.

El schema hace revision nullable sólo para la última variante. Error operacional
o validación terminal usa exit 1; JSON/archivo/flag/UUID de uso inválido usa exit
2. Un txid entregado con skip no se inicia. Antes de retornar skip, commit valida
shape/hash, identidad y `CURRENT==expected_current==base`, pero no reinterpreta
la decisión ni invoca resolver.

Terminal previo a prepared permite sólo layout/lock files ya propios del store:
cero objetos CAS, journal, revision, ref-log o CURRENT nuevos.

## Target, attestation, refutation y journal

Target guard busca por raw record digest en el stream: cero matches →
target_missing; más de uno → target_ambiguous; si el ID derivado del único match
está en supersedes o su digest está en refutations → overlay_conflict; después
status/nu físico fuera de vigente|active|null → target_not_active. Ese orden es
único y los cuatro valores son details de `invalid_refute_target`.

Commit persiste claim CAS, attestation CAS y `refutation-v1` en
`refutations/sha256/<hex>.json`. Refutation tiene exactamente:

```text
schema,target_revision,stream,target_record_sha256,reason,
proposal_sha256,authority_claim_sha256,authority_attestation_id,
policy_fingerprint,decision_sha256,evidence_sha256,plan_fingerprint
```

No copia target ID/evidence/issuer: son recuperables desde el record, claim y
attestation CAS ligados. El proposal se reconstruye exactamente con
base=target_revision, stream, target_record_sha256 y reason y su digest debe
igualar proposal_sha256. Target_revision es parent. Refutation ID es su digest.

Journal/stages llevan `refute_policy` iff attempt.operation=refute, exacto:

```text
schema=an-kla/refute-policy-transaction-v1, proposal_sha256,
authority_claim_sha256,authority_attestation_id,policy_fingerprint,
decision_sha256,evidence_sha256,plan_fingerprint,decision="refute",reason,
target{stream,record_sha256},refutation_id
```

Reconciliation/inspect/repair cruzan attempt.plan_fingerprint, metadata, claim,
attestation, refutation, manifest delta y candidate. Diferencia falla cerrado.

El protected set de `candidate-data-durable`, ordenado según ADR-0024, contiene
exactamente estos file patterns y su content digest real:

```text
revisions/sha256/<candidate>.json
checkpoints/sha256/<checkpoint>.json
refs/ref-log/sha256/<intent>.json
transactions/<txid>/stages/sha256/<stage>.json
segments/<stream>/sha256/<new-segment>.jsonl  (sólo delta parent→candidate)
authority-claims/sha256/<claim>.json
authority-attestations/sha256/<attestation>.json
refutations/sha256/<refutation>.json
```

Añade exactamente cada parent directory único de esos files como
directory_fsync. Checkpoint se protege aunque sea heredado; segments heredados
no. Los tres CAS nuevos se fsync/protegen aun si sus bytes preexistían por retry.
No se acepta path extra ni map entry extra. Repair de candidate reconstruye el
mismo set; repair de CURRENT conserva el set exacto de ADR-0024.

## Revision v1/v2 y ancestry

Revision-v1 exige exactamente las claves requeridas `schema,revision,parent,
facts_segments,events_segments,episodes_segments,checkpoint,transaction_id,
canonicalization,integrity_claim`; sólo `store_identity,supersedes_map` son
opcionales. Prohíbe features/refutations_map/cualquier unknown. Schema y las dos
constantes históricas son literales; revision es int no-bool >=0; parent es null
si y sólo si revision=0 y digest en las demás; checkpoint/segment/store_identity
son digests. Transaction_id es UUID canónico salvo la raíz legacy, donde
literalmente `"root"` se permite si y sólo si revision=0 y parent=null. Segment
arrays pueden ser vacíos, conservan orden físico y no repiten digest.
Supersedes entries tienen exactamente `stream,target_id,sustituida_por`, target
único, successor existente en mismo stream y grafo acíclico. Store sin identidad
o supersedes legacy ambiguo exige adopción explícita antes de migrar a v2.

Revision-v2 exige exactamente las mismas claves requeridas más
`store_identity,features,refutations_map`; sólo supersedes_map es opcional.
Revision es int no-bool >=1; parent/store_identity y demás identificadores usan
las reglas v1 y `features` es literalmente `["refutations/v1"]`.
`refutations_map` es no vacío; cada entry tiene exactamente
`{stream,target_record_sha256,refutation_id}`, es única por
`(stream,target_record_sha256)` y resuelve exactamente un record físico. Su CAS
liga esos campos y target_revision=parent en el edge donde aparece.

Primer v1→v2 agrega exactamente una refutation. Todo hijo de v2 por
write/checkpoint/internal commit sigue v2, conserva features/maps como prefijo
byte-idéntico y agrega cero entries, o una sola sólo en tx refute. Nunca
drop/reorder/rewrite/downgrade. Para conflicto con supersedes, el reader deriva
el raw ID del record resuelto; refutations_map nunca lo copia.

Validador iterativo compartido por snapshot/verify/inspect/candidate reconciliation:
visited set antes de dereference; parent digest/schema; revision=parent+1; máximo
`current.revision+1` hops; transición/map prefix en cada edge; termina en v1
válida. Cycle/missing/delta/downgrade son errores estables. Así también prueba
que cada refutation.target_revision es el parent donde apareció por primera vez.

## Snapshot e inspect total

Overlay doble falla manifest_lifecycle_overlay_conflict. Refute proyecta
status="refutada" sólo en memoria; segments no cambian. Estado inspect se deriva:
refutations map→refuted; supersedes map→superseded; sin overlay y status/nu físico
activo/ausente→active; cualquier otro status físico→inactive. Nunca infiere
refuted de texto físico.

`refute-inspect-v1` exacto: schema,untrusted_memory_data,revision,stream,
target_record_sha256,found,target_id_sha256,state,state_source,
physical_status_sha256,links,chain,refutation,authority_claim,
authority_attestation. `untrusted_memory_data=true`; state enum
active|inactive|superseded|refuted;
state_source enum default_active|physical_untrusted|supersedes_overlay|
refutations_overlay.

`target_id_sha256=digest_json(id físico)`; nunca publica el ID legacy crudo.
Si status existe, domina nu; si no, nu es fallback. Campo ausente produce
physical_status_sha256=null y default_active; campo presente, incluso null,
produce digest_json(valor) y physical_untrusted salvo que un overlay domine.

Found=false exige target_id_sha256/state/state_source/physical_status_sha256/
links/refutation/authority_claim/authority_attestation null y chain vacía.
Found=true exige target_id_sha256/state/state_source no-null,
physical_status_sha256 según las reglas anteriores, links objeto y chain no
vacía comenzando en target. Links es exactamente
`{superseded_by_sha256,refutation_id}`. Active/inactive tienen ambos links null;
superseded tiene successor record digest y objetos refute null; refuted tiene
refutation_id, claim/attestation/refutation validados y successor null.

Chain desde target usa hops
`{record_sha256,id_sha256,state,superseded_by_sha256,refutation_id}`: no publica
IDs legacy. visited antes de dereference; max_hops=`raw record count del stream+1`;
cycle/missing/overflow falla sin parcial. Refutation, claim y attestation aparecen
sólo cuando el target exacto es refuted. Revision inexistente→revision_not_found;
target ausente→found=false.
