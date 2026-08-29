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
