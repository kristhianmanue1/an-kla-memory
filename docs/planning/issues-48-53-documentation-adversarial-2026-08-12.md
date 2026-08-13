# Ronda adversarial — cierre documental de issues #48 y #53

> **Estado:** `proceed`
> **Fecha:** 2026-08-12
> **Alcance:** README “Fronteras declaradas”, principios A/C en prácticas y
> alineación de CONTRIBUTING

## Invariantes atacados

- La memoria y sus vistas siguen siendo datos no confiables y
  `non-authoritative`.
- `subject_ref` permite navegación contextual, no un catálogo canónico.
- La prueba de amputación no puede interpretarse como instrucción de borrado.
- `signal-at-decision` no revela estados sin autorización ni crea oráculos.
- “Aditivo” no permite reinterpretar schemas cerrados, payloads canónicos ni
  sostener dos fuentes de verdad.

## Intento 1 — `fix-and-retry`

No hubo BLOCKER ni HIGH. Hallazgos:

1. **MEDIUM:** §11.2 no definía la unidad versionada ni cuándo una extensión es
   compatible dentro de la misma versión; `CONTRIBUTING.md` conservaba una
   formulación más laxa.
2. **LOW:** §11.1 no limitaba la señal a información autorizada para el caller
   después de validación/autoridad.
3. **LOW:** la nueva sección del README precedía al índice que la enlazaba.

Correcciones:

- la sección pasó después de la tabla de contenidos;
- §11.1 exige relevancia contractual, autorización y controles previos, y
  prohíbe oráculos de existencia/autorización;
- §11.2 identifica schema/payload/perfil/comando/API como unidad versionada;
  schemas cerrados y payloads canónicos exigen nueva versión o perfil;
- superficies paralelas declaran precedencia, migración y deprecación y derivan
  de una sola semántica/fuente;
- `CONTRIBUTING.md` quedó alineado y se corrigió `versionson`.

## Intento 2 — `proceed`

El revisor no encontró hallazgos BLOCKER, HIGH, MEDIUM ni LOW. Confirmó:

- README mantiene revalidación contra fuentes canónicas y explicita que la
  amputación es mental, no operativa;
- §11.1 queda acotado por contrato y autoridad;
- §11.2 exige extensibilidad declarada o versionado;
- CONTRIBUTING coincide con la práctica normativa.

## Evidencia

- `git diff --check -- README.md docs/practicas-ingenieria.md CONTRIBUTING.md`
  → sin salida.
- `python3 scripts/check_sizes.py` → `check_sizes: OK`.
- `python3 scripts/check_adr_registry.py` durante la ronda → registro vigente
  sin inconsistencias.
- verificación de targets Markdown locales → `missing_local_targets=[]`.

La ronda fue solo lectura; el revisor no editó archivos ni GitHub.
