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

Nada aún.

## [v0.1.0-beta.23]

Release de mantenimiento: el fix #119 (export con perfil host-managed) más
todo el pase de deuda pre-G3 ya mergeado a `main` tras beta.22. Release
**code-only**: contrato gestionado y `TEMPLATE_VERSION` siguen en
`0.1.0-beta.21`.

**Corregido**:
- #119 (P1-beta.23): `export create` fallaba con
  `export_unrecognized_durable_path` en cualquier proyecto con perfil
  host-managed. `hook-runs/**` viaja ahora con la bóveda (`_PATTERNS`) y
  `host-hooks.json` queda excluido (es del proyecto) — ADR-0048 §3.
- #115/T1: replay de ADR-0024 §API/CLI — mismo txid + mismo plan binding
  reproduce el resultado (`replayed: true`) en vez de chocar con el CAS;
  binding distinto → `transaction_binding_conflict`.
- #118/R2: `assemble_context` sostiene un único lease de reader gate
  (patrón `resume`); una compactación intercalada ya no rompe la
  operación compuesta.
- #111/P2: `write_lock` POSIX con `LOCK_NB` + backoff + deadline de 10s →
  `write_lock_busy` (paridad con Windows); `docs/write-policy-cli.md`
  actualizada.
- #116/C1: `verificar_anclaje` cita la ruta, corre el pipeline con
  `pipefail` y falla cerrado ante `refs/` vacío (adiós al anchor_match
  falso con layouts con espacios).

**Añadido**:
- ADR-0048 aceptada (G3, store_root externo): registro en 48 ADRs
  (45 aceptadas, 3 propuestas). Sin implementación aún.
- #119/#115/#117/#111: issues cerrados con evidencia.

**Mantenimiento**:
- #117: `store.py` 812 → 573 líneas; partición en `write_commit.py`,
  `store_locks.py`, `store_recovery.py`, `store_errors.py`; techo
  transitorio retirado.
- Fix #119 vía test de regresión `test_export_with_host_managed_artifacts_issue119`.

## [v0.1.0-beta.22]

Release de consolidación: G2 completo (hooks gobernados del host, ADR-0047),
deuda de proceso pagada (#95/#106/#112) y absorción de la auditoría externa
(#113/R1, #114/A1+A2, #115/T2). Release **code-only**: el contrato gestionado
sigue en `0.1.0-beta.21`.

**Añadido**:
- G2 (ADR-0047, issue #56): declaración read-only `.an-kla/host-hooks.json`
  con límites congelados; evidencia `hook-run-v1` acuñada y verificada por
  el motor vía `--on-behalf-of-hook` (HMAC + binding, caps de lectura,
  idempotente por `run_id`); `integration-status-v2` con bloque `host_hooks`
  y `observed_profile` computado (`unspecified | declared-not-invoked |
  host-managed/v1`, recencia 24h con `--now` inyectable);
  `pending_continuity` computable sobre el vocabulario de ADR-0030; schemas
  `host-hooks-v1`/`hook-run-v1`/`integration-status-v2` publicados; guía
  `docs/host-hooks-guide.md`. v1 queda congelado y es la emisión por defecto.
- CI local: selftest G-3 del redteam como gate automático (#112) y matriz
  de intérpretes soportados (#111/P5) con `AN_KLA_CI_LOCAL_MATRIX=0` como
  escape.
- `examples/agent-integration/`: wrapper de referencia para agentes (#111/P6).
- `docs/write-policy-cli.md`: liveness del write lock y contrato del agente
  (#111/P2-doc).

**Corregido**:
- #113/R1 (P1): un `record.status`/`nu` no escalar admitido por la escritura
  tumbaba a `retrieve`/`rebuild-index`/`evaluate-v2` con `TypeError`. La
  escritura lo rechaza (`record.status`) y los lectores degradan fail-closed
  (`an_kla/vigency.py`) para registros ya persistidos.
- #114/A1: escrituras parciales de `os.write` en `_write_exclusive` dejaban
  claves/receipts truncados; ahora el bucle garantiza el payload completo.
- #114/A2: `verify_receipt_for_authority` recalcula el digest canónico del
  receipt y lo compara con su dirección content-addressed.
- #115/T2: `initialize_with_outcome` preserva el outcome de init ante fallo
  operacional posterior de attest (`attest_init_unwritable`).

**Mantenimiento**: partición de tamaños (#106: README + cinco tests);
techos retirados de `skevi-gate.json`; #95 cerrado con evidencia; techo
transitorio `an_kla/store.py: 820` con issue #117; `TEMPLATE_VERSION` sin
cambio.

## [v0.1.0-beta.21]

Cierre del ciclo attest (issue #102, ADR-0046): plantilla del contrato
bumpada a `0.1.0-beta.21` con el vocabulario de attest en §Resolver
autoridad, ADR-0046 aceptada, y adjuntos de la ronda adversarial externa
(issue #111): techo `requires-python <3.14`, schema `write-proposal-v1`
documenta `text`, warning `record_without_indexable_text` visible en
stderr, runbook `docs/agent-recovery.md`, mensaje canónico del selftest
redteam unificado (#109) y anclaje con `LC_ALL=C` (re-anclaje registrado).

**Cambiado**: contrato gestionado `0.1.0-beta.11` → `0.1.0-beta.21`
(flujos explícitos: adopt-baseline + update; sin cambios fuera de
§Resolver autoridad); entrada histórica `0.1.0-beta.11` añadida al
registro de plantillas (falso `managed_contract_modified` eliminado).
Detalle y límites en la
[nota de release](docs/releases/v0.1.0-beta.21.md) y su
[ronda adversarial](docs/releases/v0.1.0-beta.21-adversarial.md).

## [v0.1.0-beta.20]

Fase H de hardness del issue #102 (reportada por el consumidor real
infosalud), CI local-only (retiro de GitHub Actions, decisión del
operador), ADR-0043/0044 y adopción de Skevi (ADR-0045). Sin cambios de
formato físico ni de política de autoridad; los stores beta.19 se leen
sin migración.

**Cambiado**: `plan-write` falla cerrado con códigos `plan_*` nuevos
(#103); marcadores dentro de un fence reportan
`managed_block_inside_fence` (#105); `commit-write-plan` añade
`record_without_indexable_text` a `outcome.warnings` (#104); el repo ya
no define workflows remotos — verificación canónica local. Detalle y
límites en la
[nota de release](docs/releases/v0.1.0-beta.20.md) y su
[ronda adversarial](docs/releases/v0.1.0-beta.20-adversarial.md).

## [v0.1.0-beta.19]

Preparación documental del ciclo de release: deuda C-2 de la ronda REL
beta.18 resuelta (CHANGELOG sin doble estado, índice `docs/README.md`
actualizado a la release vigente, frase de wheels del README corregida,
`check_clean_wheel.py` versionado con el bump), ADR-0042 partido en ADR
corto + apéndice técnico (#95, gate de tamaños sin gracia) y nota de
release propia. Sin cambios de código: el runtime no muta respecto de
beta.18 salvo el bump de versión.
[Notas](docs/releases/v0.1.0-beta.19.md)

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
