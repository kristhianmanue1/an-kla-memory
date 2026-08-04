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

## Fuente de verdad

La **fuente de verdad** son los archivos embebidos en el paquete, no estos.
Si los bytes difieren, el paquete es el canónico. Esta carpeta se mantiene
sincronizada con cada release; los consumidores no deben leerla directamente.

## Versionado

Cada schema lleva `$id: urn:an-kla:schema:<name>:v<N>`. Un bump de versión
mayor requiere release etiquetada y nota en `docs/releases/`.
