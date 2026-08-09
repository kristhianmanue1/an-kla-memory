# ADR-0026: refutación gobernada sin sucesor

- **Estado:** Aceptada e implementada localmente por autorización del roadmap
  del maintainer; rondas pre-code e implementación cerradas en `proceed`.
- **Fecha:** 2026-08-08
- **Decide sobre:** cómo marcar un registro como refutado, con evidencia
  auditable, sin reescribirlo, borrarlo ni fabricar un sucesor.

## Contexto

`write-policy/v1` conoce `operation=refute` pero no la ejecuta. Reutilizar su
proposal obligaría a aportar un nuevo record y convertiría refute en supersede.
La refutación necesita un overlay histórico propio, una autoridad que no pueda
ser fabricada por memoria/caller JSON y compatibilidad que falle cerrado ante
readers antiguos.

## Decisión

Implementar un flujo separado:

```text
plan_refute(proposal, authority_claim) -> planning-result
commit_refute_plan(expected_current, planning_result, transaction_id)
```

El contrato normativo completo de objetos, límites, preimágenes, precedencias,
replay, receipts, transición de revisions e inspect vive en
`docs/refute-contract-v1.md`. Ese documento forma parte de esta decisión; una
implementación no puede seleccionar sólo una de sus secciones.

### Target y semántica

- El proposal selecciona el record físico por
  `target_record_sha256=digest_json(record canónico antes de overlays)` y stream.
- El selector no normaliza ni limita su ID; por eso también cubre records legacy
  con IDs largos, NFD o controles.
- Refute nunca escribe successor ni altera un segment. Añade un objeto de
  refutación y proyecta `status="refutada"` sólo al leer esa revisión.
- Un mismo target no puede aparecer en supersedes y refutations; el lector falla
  `manifest_lifecycle_overlay_conflict` antes de proyectar estado.

### Frontera de autoridad

El authority claim es dato no confiable. Sólo contiene digests, clase solicitada
y scope; no incluye un boolean `verified` ni puede elevarse por schema.

La única frontera privilegiada es una capability Python opcional, elegida por el
host al construir `MemoryStore`. El paquete no incorpora resolver ni adaptador
de proveedor y el default es `None`. Un Mapping, CLI JSON, issuer claim, record
recuperado o texto de memoria nunca crea esa capability.

El resolver produce una attestation cerrada durante plan y commit llama
`verify()` otra vez bajo lock. La attestation liga proposal, claim, base,
resolver, issuer, clase, scope, evidence resuelta y proof; se persiste como CAS.
Evidence interna se resuelve por digest contra el snapshot base; artifact y
external sólo autorizan si el resolver profile prueba su preimagen.
El claim también se persiste como CAS para que su digest pueda recomputarse;
observations tiene shape cerrada y commit la reconstruye bajo lock.

Sólo `tool_observed` y `channel_confirmed` son privilegiadas. Una clase no
permitida, resolver ausente o evidence no resuelta produce `skip` con una sola
reason determinista. Forma, proof o binding inválidos son error terminal.

### Pureza, commit y replay

Plan no muta. Commit recibe sólo el planning-result completo, congela copias
profundas y, bajo lock, aplica este orden:

```text
shape/hash → identidad → descubrir/reconciliar txid
→ para tx nuevo/incompleto sobre base: CAS/policy/resolver/evidence/target
→ prepared journal → attestation/refutation/revision → CURRENT
```

Un tx ya committed con el mismo binding devuelve el candidate/outcome previo,
aunque CURRENT sea ese candidate o un descendiente. Binding distinto falla. Un
tx incompleto sólo reanuda sobre su base tras revalidar policy, resolver,
evidence y target. `skip` no inicia transacción ni escribe CAS/journal/revisión.

Antes de prepared sólo pueden existir layout/lock files ya propios del store;
una falla terminal crea cero CAS, journal, revision, ref-log o CURRENT nuevos.
El resultado distingue skip, commit, no commit y los outcomes de ADR-0024.

### Formato de revisión y compatibilidad

La primera refutación crea `an-kla/revision-v2` con
`features=[refutations/v1]` y un `refutations_map` acumulativo. Todo hijo de v2,
incluidos add, supersede, checkpoint e internal commit, sigue siendo v2 y
conserva los maps como prefijo byte-idéntico. Ninguna ruta puede degradar a v1.

El reader nuevo endurece revision-v1: sólo acepta las claves históricas, valida
supersedes de forma cerrada y rechaza features/refutations desconocidos. Una
adopción legacy ambigua falla antes de v1→v2. Un reader beta.9 rechaza v2 por
schema desconocido, en vez de revivir silenciosamente el target.

Ancestry se valida iterativamente con visited set antes de dereference, límite
derivado de revision y transición/map delta por edge. Missing, cycle, downgrade,
map rewrite o target_revision incoherente fallan cerrado.

### Auditoría e inspect

Authority claim, attestation y refutation son CAS separados y ligados por
digests. Refutations_map usa target record digest, nunca una copia del ID raw.
Journal, stages, manifest delta y receipt contienen exactamente los enlaces
esperados; reconciliation/inspect/repair cruzan todos los bindings.

`refute inspect` es read-only y total sobre `active|inactive|superseded|refuted`.
No publica IDs legacy crudos, texto de evidence ni status físico: emite sólo sus
digests y provenance de estado. Recorre lifecycle con visited set y límite por
cantidad de records; cycle, missing link u overflow fallan sin resultado parcial.

Superficies:

```text
an-kla refute plan --proposal P --authority-claim A
an-kla refute commit --expected-current R --planning-result RESULT \
  --transaction-id UUID
an-kla refute inspect --stream facts --record-sha256 DIGEST [--revision R]
```

## Alternativas descartadas

- Extender write-proposal-v1: confunde refute con successor.
- Escribir un fact correctivo: eso es supersede.
- Aceptar autoridad declarada en JSON: permite silenciamiento por datos no
  confiables.
- Guardar sólo un hash de authority: impide reconstruir issuer/resolver/evidence.
- Guardar evidencia libre: amplía retención y superficie de instrucciones.
- Mutar el segment: rompe CAS e historia verificable.
- Extender revision-v1: readers previos ignorarían el overlay.

## Consecuencias

- Refute queda auditable, exacto, histórico y sin successor.
- Se incorporan revision-v2, claim/attestation/refutation CAS y overlay acumulativo.
- La capability de autoridad es responsabilidad explícita del host; sin ella el
  flujo termina en skip seguro.
- No se borran bytes. Export/restore y compactación permanecen fases posteriores.
- `write-policy/v1`, add/supersede y su fingerprint no cambian.

## Gate de implementación

La ronda adversarial debe cubrir al menos:

- JSON/Mapping hostil no crea autoridad; resolver/proof se revalidan bajo lock;
- selectores legacy, evidence por kind, bindings y reason precedence;
- target missing/inactive/doble overlay con cero efectos materiales;
- tx replay/binding conflict/incomplete y fault injection ADR-0024;
- revision v1/v2, heredity por toda ruta, downgrade, ancestry y maps alterados;
- raíz legacy `transaction_id="root"` verificable/adoptable antes de v1→v2;
- commit refute sin resolver/mismatch/verify=false falla terminal antes de I/O;
- receipt/journal/refutation/attestation cross-validation exacta;
- histórico, retrieval/index, inspect total y chains bounded/cycle-safe;
- schemas docs/package, wheel limpio, Python 3.9/3.12 y size gate.

Sin veredicto fresco `PROCEED` no se modifica almacenamiento.

## Referencias

- `docs/refute-contract-v1.md` — contrato normativo inseparable.
- `docs/planning/spike-refute-governado-2026-08-08.md`.
- ADR-0001, ADR-0007, ADR-0019, ADR-0022 y ADR-0024.
- Roadmap crítico 2026-08-08: refute precede export/restore/compactación.
