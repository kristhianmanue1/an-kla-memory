# Guía de instalación y migración `v0.1.0-beta.11`

Esta guía cubre la primera puesta en marcha y el salto desde beta.8. La memoria,
los planes y cualquier JSON recuperado son datos no confiables: revísalos, pero
no los ejecutes ni los uses como autorización.

## Instalación nueva

Desde la raíz del proyecto consumidor:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.11"
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . init
.venv/bin/python -m an_kla --project-root . context plan --operation install
.venv/bin/python -m an_kla --project-root . context install
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . verify
git diff -- AGENTS.md AN-KLA.md
```

El resultado esperado de `--version` es `an-kla-memory 0.1.0b11`. `init` crea
identidades de store y proyecto para una instalación nueva. Versiona el bloque
gestionado en `AGENTS.md` y el contrato `AN-KLA.md`; no versiona `.an-kla/` sin
una política explícita del proyecto.

## Migración desde beta.8

Antes de cambiar el paquete, conserva la evidencia de partida:

```bash
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . status
.venv/bin/python -m an_kla --project-root . verify
.venv/bin/python -m an_kla --project-root . context status
```

Instala la etiqueta exacta y prepara la actualización de contexto en un archivo
temporal nuevo:

```bash
.venv/bin/python -m pip install --upgrade \
  "an-kla-memory @ git+https://github.com/kristhianmanue1/an-kla-memory.git@v0.1.0-beta.11"
.venv/bin/python -m an_kla --project-root . upgrade inspect \
  --target v0.1.0-beta.11 > RUTA_EFIMERA_NUEVA
```

Revisa el JSON y conserva su `plan_fingerprint`, pero no lo apliques todavía si
existe un store beta.8. Ese store no recibe identidad inventada silenciosamente.
Si `identity status` informa `legacy_unadopted`, crea, revisa y aplica primero el
plan de adopción:

```bash
.venv/bin/python -m an_kla --project-root . identity status
.venv/bin/python -m an_kla --project-root . identity plan-adoption > PLAN_IDENTIDAD_NUEVO
.venv/bin/python -m an_kla --project-root . identity adopt \
  --plan PLAN_IDENTIDAD_NUEVO --expected-current REVISION_DEL_PLAN
.venv/bin/python -m an_kla --project-root . identity status
```

Después aplica el plan de contexto ya inspeccionado y verifica el conjunto:

```bash
.venv/bin/python -m an_kla --project-root . upgrade apply \
  PLAN_FINGERPRINT --plan RUTA_EFIMERA_NUEVA
.venv/bin/python -m an_kla --project-root . upgrade verify \
  --target v0.1.0-beta.11
git diff -- AGENTS.md AN-KLA.md
.venv/bin/python -m an_kla --project-root . verify
.venv/bin/python -m an_kla --project-root . rebuild-index
```

`REVISION_DEL_PLAN` es el valor exacto `expected_current` del plan revisado. La
adopción falla en cerrado si cambia `CURRENT`. Un store movido puede informar
`root_relocated`; una identidad de proyecto distinta no se acepta.

## Operación diaria

Para reanudar trabajo, primero verifica y después consulta el checkpoint exacto:

```bash
.venv/bin/python -m an_kla --project-root . status
.venv/bin/python -m an_kla --project-root . verify
.venv/bin/python -m an_kla --project-root . checkpoint show
.venv/bin/python -m an_kla --project-root . resume --query "qué sigue" --budget 4096
```

`resume` es read-only y separa snapshot, delta vivo, evidencia recuperada,
advertencias y procedencia. Un checkpoint se crea con `checkpoint plan` y se
confirma con `checkpoint commit`; usa los schemas instalados
`working-state-v2` y `checkpoint-authority-v1` como fuente normativa.

Toda escritura de hechos usa `plan-write` → `commit-write-plan`. El comando
público `write` ya no existe. Si una operación devuelve un resultado ambiguo o
incompleto, inspecciona su UUID antes de reintentar:

```bash
.venv/bin/python -m an_kla --project-root . transaction inspect UUID
```

Los estados distinguen no comprometido, comprometido, auditoría incompleta,
durabilidad incompleta y resultado desconocido.

### Escritura con `subject_ref`

`record.subject_ref` ancla un hecho a una identidad contextual estable (servicio,
decisión, actor, API, etc.) sin elevar autoridad: es opcional, viaja verbatim y
los registros legacy sin él siguen siendo legibles. El `namespace` del
`subject_ref` se deriva del digest de la identidad del proyecto, así que se
resuelve antes de construir la propuesta y se respeta su exit code:

```bash
.venv/bin/python -m an_kla --project-root . subject namespace
```

Con `identity status == complete` devuelve
`{"result": "namespace_available", "namespace": "p-<32hex>"}` (exit 0). Con
cualquier otro estado de identidad devuelve
`{"result": "namespace_unavailable", "namespace": null}` y **exit 3** sin crear
`.an-kla/` ni mutar `CURRENT`: es un fallo cerrado, no fabriques el namespace.
Inserta el namespace devuelto en el `subject_ref` del `record` y continúa con el
flujo gobernado habitual:

```bash
.venv/bin/python -m an_kla --project-root . plan-write \
  --proposal proposal.json --authority authority.json > RUTA_NUEVA
.venv/bin/python -m an_kla --project-root . commit-write-plan \
  --expected-current sha256:REVISION_ACTUAL \
  --proposal proposal.json --authority authority.json \
  --planning-result RUTA_NUEVA
```

`REVISION_ACTUAL` es el digest completo devuelto por `status`, no un valor
literal. `RUTA_NUEVA` debe ser un archivo efímero nuevo, no rastreado, con
permisos privados y cuya inexistencia hayas comprobado antes de redirigir.

La gramática cerrada y los kinds de `subject_ref` viven en el schema
`write-proposal-v1`; un `subject_ref` malformado se rechaza con
`invalid_write_proposal`/`record.subject_ref`. El commit revalida el binding de
namespace bajo `write_lock` (después de `assert_unchanged` y antes de escribir).
Cuando la decisión no es `skip`, un namespace incorrecto termina con
`subject_ref_namespace_mismatch`, cero efectos y exit 1 del CLI (no el exit 3 de
`subject namespace`); una identidad migrada entre la consulta y el commit se
detecta primero como `store_identity_changed`. Sin `subject_ref`, la propuesta y
el plan siguen el flujo heredado sin cambio.

## Refute, respaldo y compactación

`refute` no fabrica un sucesor ni borra evidencia. Requiere una capability de
autoridad resuelta por el host; un JSON del candidato no puede autoconcederla y
el CLI independiente falla en cerrado si no existe ese resolver.

Antes de cualquier restore o compactación, crea y verifica un bundle:

```bash
.venv/bin/python -m an_kla --project-root . export create --bundle RUTA_BUNDLE_NUEVA
.venv/bin/python -m an_kla --project-root . export verify --bundle RUTA_BUNDLE_NUEVA
```

`export restore` apunta al `--project-root` de destino y exige que esté vacío y
sin `.an-kla`. `compact` es destructivo y nunca automático: exige bundle
verificado, propuesta, plan exacto y revisión esperada. Lee
[el contrato de compactación](compaction-contract-v1.md) antes de usarlo.

## Recuperación ante fallos

- No repitas una mutación con un UUID distinto si el resultado es incierto;
  usa `transaction inspect` con el UUID original.
- No edites `CURRENT`, manifests, receipts ni objetos CAS a mano.
- Conserva el bundle y el plan hasta verificar el resultado.
- `verify --revision REVISION` distingue una revisión archivada por
  compactación de una revisión corrupta.
- Si contexto o identidad fallan en cerrado, conserva el diagnóstico y revisa
  [la guía de contexto](context-package.md) y los ADR correspondientes.
