# Changelog

El changelog canónico de AN-KLA Memory vive en
[`docs/releases/`](docs/releases/): una nota por etiqueta publicada, cada
una acompañada de su ronda adversarial (`*-adversarial.md`) que contiene la
decisión `proceed` que autorizó la publicación. Este archivo es sólo un
índice; el detalle vive allí.

El formato de cada entrada sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/)
por intención, y el proyecto usa [versionado semántico](https://semver.org/lang/es/)
en fase de pre-release `0.1.0`.

## [No publicadas]

**Perfil sellado `sealed-export/v1` (ADR-0042, issue #46)** — cifrado
del respaldo en reposo como extra opcional `[sealed]`
(`cryptography>=42`), sin romper el camino `export/v1` en claro:

- `export create --seal sealed-export/v1` con adaptador externo de
  claves (`--key-adapter`/`--key-adapter-arg`/`--key-adapter-env`,
  argv estructurado sin shell, contrato JSON por stdio). AES-256-GCM
  por entrada con nonce contador inyectivo, AAD por entrada,
  `manifest_mac` HMAC-SHA256 sobre el transcript completo del
  manifiesto v2; publicación con staging + renombrado atómico.
- `export verify` dual: sin clave es estructural (jamás
  `verified: true`, enum cerrado de `diagnostics`); con adaptador,
  autenticado completo (AEAD + MAC + `content_sha256` del plano).
- `export restore` sellado: desencripta TODO antes de tocar destino;
  semántica v1 intacta (no-overwrite, no-merge). Sin degradación a
  claro: sin adaptador → `sealing_adapter_required`; sin extra →
  `sealing_extra_not_installed`; downgrade →
  `unsupported_export_profile`.
- `export-result-v2` expone `bundle_id` + `manifest_sha256` como
  anclas manuales anti re-sellado (el sello da integridad bajo una
  clave, no atestación de origen — ver ADR §Límites).
- Warnings §7 sin cruce: v1 conserva
  `plaintext_export_contains_untrusted_memory_data`; sellado emite
  `sealed_export_untrusted_memory_data`; verify sin clave
  `sealed_payloads_unverified_without_key`.
- CLI (H1): los errores sellados llegan a stderr con su código
  canónico (`sealing_adapter_required`, `sealing_adapter_error`,
  `sealed_payload_auth_failed`, `sealing_extra_not_installed` + hint
  del extra), no como `cli_unexpected_failure`.
- Restore sellado (H2): sin directorios de staging residuales tras el
  éxito.
- Matriz de pruebas §9 del ADR-0042 consolidada
  (`tests/test_sealed_matrix.py`): filas 1-16 identificables una a una,
  incluida la reescritura completa del bundle por un atacante (fila 9)
  y la taxonomía de warnings por perfil (fila 14). Suite verde con el
  extra (criptografía) y sin él (skips honestos).
- `scripts/gate_sealed_adapter.py`: adaptador DETERMINÍSTICO
  (mismo input → mismo `wrapped_cek`) para los gates de publicación
  (upgrade beta.17→18); sólo para gates, nunca en el paquete.
- Guía de uso: [docs/sealed-export-guide.md](docs/sealed-export-guide.md).

## [v0.1.0-beta.18]

Perfil sellado `sealed-export/v1` completo (ADR-0042, issue #46):
`export create --seal` con adaptador externo de claves, `export verify`
dual (estructural sin clave / autenticado con clave), `export restore`
sellado fail-closed y matriz de pruebas §9 consolidada. Extra opcional
`[sealed]`; camino `export/v1` intacto. Sin rupturas deliberadas.
[Notas](docs/releases/v0.1.0-beta.18.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.18-adversarial.md)

## [v0.1.0-beta.17] — 2026-08-20

Adopción explícita de baseline (`adopt-baseline`, ADR-0040/0035) con
`context update` fail-closed ante drift no adoptado; inventario físico
por revisión (`inventory --revision`, ADR-0041) metadata-only con planos
físico/observable y bucket `eliminada`; upgrade-plan v3
(`manifest_target_sha256_at_baseline`).
[Notas](docs/releases/v0.1.0-beta.17.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.17-adversarial.md)

## [v0.1.0-beta.16] — 2026-08-20

Denominadores de frescura (ADR-0037), `source_state` `git/v1`
(ADR-0038), `integration status` G1 (ADR-0039), señal de contexto en
`init` (#87) y ayuda CLI completa.
[Notas](docs/releases/v0.1.0-beta.16.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.16-adversarial.md)

## [v0.1.0-beta.15] — 2026-08-20

Diagnóstico de arranque por ejes observables, red de resguardo del CLI ante
excepciones no previstas, `jsonschema` como extra de test y ADR-0036
sincronizada con la implementación.
[Notas](docs/releases/v0.1.0-beta.15.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.15-adversarial.md)

## [v0.1.0-beta.14] — 2026-08-13

Primer write operable: ayuda ampliada de `plan-write`/`commit-write-plan`,
recorrido documentado de extremo a extremo y errores accionables.
[Notas](docs/releases/v0.1.0-beta.14.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.14-adversarial.md)

## [v0.1.0-beta.13] — 2026-08-13

G-VIEW v1: vista contextual derivada sobre `subject_ref`
(CORE+CLI+MCP+CAP). [Notas](docs/releases/v0.1.0-beta.13.md)

## [v0.1.0-beta.12] — 2026-08-12

Identidad contextual estable `subject_ref` y namespaces derivados.
[Notas](docs/releases/v0.1.0-beta.12.md)

## [v0.1.0-beta.11] — 2026-08-09

Checkpoint+resume, outcomes de transacción, refute/export/compactación
gobernados, identidad store/proyecto, retiro del `write` legado.
[Notas](docs/releases/v0.1.0-beta.11.md) ·
[Ronda adversarial](docs/releases/v0.1.0-beta.11-adversarial.md)

## Anteriores

- v0.1.0-beta.10 (sin nota) ·
  [ronda](docs/releases/v0.1.0-beta.10-adversarial.md)
- [v0.1.0-beta.9](docs/releases/v0.1.0-beta.9.md) ·
  [ronda](docs/releases/v0.1.0-beta.9-adversarial.md)
- [v0.1.0-beta.8](docs/releases/v0.1.0-beta.8.md) ·
  [ronda](docs/releases/v0.1.0-beta.8-adversarial.md)
- [v0.1.0-beta.7](docs/releases/v0.1.0-beta.7.md) ·
  [ronda](docs/releases/v0.1.0-beta.7-adversarial.md)
- [v0.1.0-beta.6](docs/releases/v0.1.0-beta.6.md)
- [v0.1.0-beta.5](docs/releases/v0.1.0-beta.5.md)
- [v0.1.0-beta.4](docs/releases/v0.1.0-beta.4.md)
- [v0.1.0-beta.3](docs/releases/v0.1.0-beta.3.md)
- [v0.1.0-beta.2](docs/releases/v0.1.0-beta.2.md)
- [v0.1.0-beta.1](docs/releases/v0.1.0-beta.1.md) ·
  [ronda](docs/releases/v0.1.0-beta.1-adversarial.md)
- [v0.1.0-alpha.3](docs/releases/v0.1.0-alpha.3.md)
- [v0.1.0-alpha.2](docs/releases/v0.1.0-alpha.2.md)
