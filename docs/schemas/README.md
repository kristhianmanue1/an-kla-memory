# JSON Schemas normativos

Esta carpeta contiene los schemas JSON públicos de AN-KLA Memory. Los
schemas **también están embebidos en el paquete** (`an_kla/schemas/`) y se
consultan canónicamente con:

```bash
python -m an_kla schema list
python -m an_kla schema show write-plan-v1
```

## Inventario

| Schema | Propósito |
|---|---|
| `write-proposal-v1.schema.json` | Candidato de escritura (record, stream, lineage). |
| `write-authority-v1.schema.json` | Autoridad separada del proposal (scope, evidence, issuer). |
| `write-decision-v1.schema.json` | Decisión determinista de la política (`skip` / `write-full` / `write-summary`). |
| `write-plan-v1.schema.json` | Plan ejecutable ligado por hashes al proposal + authority + decision. |
| `cost-certificate-v1.schema.json` | Certificado de costo (presupuesto en bytes UTF-8). |
| `upgrade-plan-v1.schema.json` | Plan de upgrade del contrato administrado. |
| `transaction-attempt-v1.schema.json` | Intento con txid separado del plan determinista. |
| `commit-outcome-v2.schema.json` | Autoridad, auditoría y durabilidad del commit. |
| `durability-receipt-v1.schema.json` | Evidencia positiva de fsync previo por transacción. |
| `project-identity-v1.schema.json` | Identidad lógica canónica del proyecto. |
| `store-identity-v1.schema.json` | Identidad del store ligada al proyecto. |
| `identity-intent-v1.schema.json` | Intent durable y resumible de bootstrap/adopción. |
| `identity-adoption-plan-v1.schema.json` | Plan exacto para adopción explícita de store legacy. |
| `identity-operation-result-v1.schema.json` | Resultado separado de bootstrap/adopción/reparación. |
| `identity-durability-receipt-v1.schema.json` | Evidencia durable propia del protocolo de identidad. |
| `identity-status-v1.schema.json` | Clasificación local y relocación sin exponer IDs por defecto. |
| `working-state-v2.schema.json` | Continuidad operacional con procedencia explícita. |
| `checkpoint-v2.schema.json` | Checkpoint exacto ligado a una revisión. |
| `checkpoint-proposal-v1.schema.json` | Propuesta gobernada de working state. |
| `checkpoint-authority-v1.schema.json` | Autoridad y scope separados para checkpoint. |
| `checkpoint-decision-v1.schema.json` | Decisión determinista `skip|write`. |
| `checkpoint-plan-v1.schema.json` | Plan content-addressed ejecutable. |
| `resume-evidence-v1.schema.json` | Evidencia recuperada exacta dentro de resume. |
| `resume-v1.schema.json` | Handoff consistente y limitado por bytes. |
| `retrieval-eval-query-v2.schema.json` | Query cerrada para evaluación ordenada. |
| `retrieval-eval-report-v2.schema.json` | Métricas separadas de ranking, budget y paridad. |
| `retrieval-strategy-report-v1.schema.json` | Rankers experimentales no productivos. |
| `reference-benchmark-v1.schema.json` | Bundle del benchmark de referencia. |
| `provenance-manifest-v1.schema.json` | Saneamiento y gates de privacidad del corpus. |
| `refute-proposal-v1.schema.json` | Selector digest legacy-safe y reason cerrada. |
| `refute-authority-claim-v1.schema.json` | Claim no confiable separado de authority. |
| `refute-observations-v1.schema.json` | Observaciones digest-only del snapshot base. |
| `refute-authority-attestation-v1.schema.json` | Attestation de capability host. |
| `refute-decision-v1.schema.json` | Decisión determinista `skip|refute`. |
| `refute-plan-v1.schema.json` | Plan exacto ligado por fingerprints. |
| `refute-planning-result-v1.schema.json` | Envelope completo para commit/replay. |
| `refutation-v1.schema.json` | Objeto CAS de refutación sin target ID raw. |
| `revision-v2.schema.json` | Manifest fail-closed con refutations map. |
| `refute-policy-transaction-v1.schema.json` | Metadata transaccional cruzable. |
| `refute-policy-config-v1.schema.json` | Preimagen exacta del fingerprint de policy. |
| `refute-commit-result-v1.schema.json` | Resultado triestado y outcome ADR-0024. |
| `refute-inspect-v1.schema.json` | Lifecycle read-only sin IDs legacy raw. |
| `export-manifest-v1.schema.json` | Inventario verificable del backup plaintext. |
| `export-result-v1.schema.json` | Resultado de creación de export. |
| `export-verify-result-v1.schema.json` | Verificación sintáctica y semántica del bundle. |
| `restore-result-v1.schema.json` | Publicación no-replace y estado de durabilidad. |
| `compaction-policy-config-v1.schema.json` | Preimagen exacta de policy de compactación. |
| `compaction-proposal-v1.schema.json` | Base, epoch, txid y export ligados. |
| `compaction-restore-proof-v1.schema.json` | Evidencia de restore real previo al plan. |
| `compaction-tombstone-catalog-v1.schema.json` | Historia archivada y delete-set acumulativo. |
| `compaction-epoch-v1.schema.json` | DAG durable del epoch sin ciclos de hashes. |
| `revision-v3.schema.json` | Nueva raíz de epoch y descendientes heredables. |
| `compaction-plan-v1.schema.json` | Plan content-addressed ligado al candidate. |
| `compaction-planning-result-v1.schema.json` | Envelope completo para commit/replay. |
| `compaction-cleanup-receipt-v1.schema.json` | Evidencia convergente del cleanup exacto. |
| `compaction-result-v1.schema.json` | Resultado separado de autoridad y cleanup. |
| `verify-revision-v1.schema.json` | Disponibilidad histórica present/archived/unknown. |
| `transaction-archived-v1.schema.json` | Outcome histórico ligado al catálogo del epoch. |

## Fuente de verdad

La **fuente de verdad** son los archivos embebidos en el paquete, no estos.
Si los bytes difieren, el paquete es el canónico. Esta carpeta se mantiene
sincronizada con cada release; los consumidores no deben leerla directamente.

## Versionado

Cada schema lleva `$id: urn:an-kla:schema:<name>:v<N>`. Un bump de versión
mayor requiere release etiquetada y nota en `docs/releases/`.
