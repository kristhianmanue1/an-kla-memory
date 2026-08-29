# Guía del perfil sellado `sealed-export/v1`

Esta guía describe el uso del perfil sellado de export/restore
(ADR-0042): respaldos cifrados en reposo con verificación autenticada.
La norma vinculante es
[`docs/architecture/0042-sealed-export-v1.md`](architecture/0042-sealed-export-v1.md),
con el desglose técnico de sus reglas congeladas en
[`docs/architecture/refs/sealed-export-v1-appendix.md`](architecture/refs/sealed-export-v1-appendix.md)
(#95); aquí sólo el uso práctico.

## Qué da y qué no da

**Da**: confidencialidad del bundle en reposo (cifrado AES-256-GCM por
entrada; el manifiesto lista rutas/tamaños pero no contenidos),
integridad autenticada bajo la clave (todo fallo es un único código
`sealed_payload_auth_failed`, sin oráculo), y verificación estructural
sin clave (honesto: jamás `verified: true` sin la clave).

**No da** (ver §Límites del ADR): no protege el store vivo, ni el
transporte, ni autentica al operador, ni es atestación de origen — un
atacante con un adaptador de clave pública puede re-sellar un bundle
completo con su propia CEK. La defensa disponible es manual: al crear,
`export-result-v2` devuelve `bundle_id` y `manifest_sha256`; regístralos
y compáralos antes de restaurar un respaldo.

El contenido restaurado sigue siendo dato no confiable
(`untrusted_memory_data`): el sellado no cambia la semántica de la
memoria.

## Instalación

El perfil es un extra opcional; sin él el paquete sigue siendo
stdlib-only:

```bash
pip install 'an-kla-memory[sealed]'   # cryptography>=42
```

Sin el extra, todo comando sellado falla cerrado con
`sealing_extra_not_installed` (con hint en stderr). No existe
degradación a export en claro.

## El adaptador de claves

El sellado exige un **adaptador externo de claves**: un ejecutable
separado que custodia la capacidad de envolver/desenvolver la CEK
efímera de cada bundle (la CEK jamás entra al core de AN-KLA en
reposo). El contrato es JSON cerrado por stdio
(`an-kla/sealing-adapter-contract-v1`):

- `wrap` → entrada `{"op","cek_b64"}` → salida
  `{"wrapped_cek","adapter_id"}`
- `unwrap` → entrada `{"op","wrapped_cek"}` → salida `{"cek_b64"}`

El runner del core ejecuta el adaptador **sin shell** (argv
estructurado), con entorno mínimo (allowlist explícita), límites I/O,
timeout de 30 s y terminación del árbol de procesos ante cualquier
exceso. Cualquier desviación del contrato es `sealing_adapter_error`.

En producción, el adaptador debe tener custodia real (Keychain, KMS,
age con passphrase, YubiKey). El de `tests/adapters/` y el de
`scripts/gate_sealed_adapter.py` son NO-producción.

## Uso

Crear un respaldo sellado:

```bash
python -m an_kla --project-root . export create \
    --bundle RESPALDO_SELLADO \
    --seal sealed-export/v1 \
    --key-adapter /ruta/al/adaptador \
    --key-adapter-arg --flag-con-espacios  # repetible: un elemento de argv
    --key-adapter-env NOMBRE_DE_VARIABLE  # repetible: allowlist F3
```

Registra la salida (`bundle_id`, `manifest_sha256`) fuera de línea.

Verificar sin clave (estructural, jamás afirma autenticidad):

```bash
python -m an_kla export verify --bundle RESPALDO_SELLADO
# → verified:false, structure_verified:true,
#   warnings:["sealed_payloads_unverified_without_key"]
```

Verificar autenticado y restaurar:

```bash
python -m an_kla export verify --bundle RESPALDO_SELLADO \
    --key-adapter /ruta/al/adaptador ...
python -m an_kla --project-root DESTINO export restore \
    --bundle RESPALDO_SELLADO \
    --key-adapter /ruta/al/adaptador ...
```

**Antes de restaurar**, compara `bundle_id` contra el registrado al
crear (ancla manual anti re-sellado).

## Errores canónicos (stderr)

| Código | Causa |
|---|---|
| `sealing_adapter_required` | `--seal` sin `--key-adapter` |
| `sealing_adapter_error` | adaptador falla/crash/timeout/contrato violado |
| `sealed_payload_auth_failed` | clave equivocada o bundle alterado (un solo código, sin oráculo) |
| `sealing_extra_not_installed` | falta el extra `[sealed]` (con hint de instalación) |
| `unsupported_export_profile` | downgrade: sellado pedido como v1 o perfil desconocido |
| `sealing_key_adapter_spaces_forbidden` | `--key-adapter` con espacios (prohibido el split; usa `--key-adapter-arg`) |
| `sealing_adapter_id_invalid` | `adapter_id` del adaptador fuera de gramática |
| `sealed_entry_too_large` | entrada > 512 MiB (sin chunking) |

## Warnings por perfil (taxonomía §7, sin cruce)

| Camino | Warnings |
|---|---|
| v1 create/verify | `plaintext_export_contains_untrusted_memory_data` |
| sellado create/verify con clave/restore | `sealed_export_untrusted_memory_data` |
| verify sellado sin clave | `sealed_payloads_unverified_without_key` |

## Matriz de pruebas

`tests/test_sealed_matrix.py` consoliza la matriz §9 del ADR (filas
1-16), cada fila identificable una a una. Corre con el extra
(criptografía real) y sin él (skips honestos en lo criptográfico).

## Gates de publicación (procedimiento REL)

El gate de upgrade beta.17→18 ejercita `--seal` contra el adaptador
determinístico `scripts/gate_sealed_adapter.py` (mismo input → mismo
`wrapped_cek`; sólo para gates, nunca en el paquete):

1. Clean wheel SIN extra: camino v1 intacto, suite completa verde.
2. Con extra `[sealed]`: matriz sellada completa verde.
3. Upgrade real: instalar la versión previa, upgrade, y ejercitar
   `export create --seal ... --key-adapter python3 --key-adapter-arg
   scripts/gate_sealed_adapter.py` + verify con clave + restore.

El bump de versión y la publicación siguen siendo del maintainer.
