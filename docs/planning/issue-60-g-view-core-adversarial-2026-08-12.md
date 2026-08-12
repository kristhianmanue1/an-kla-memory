# Ronda adversarial — G-VIEW CORE (issue #60)

- **Base:** `820b93dcedfb51831cfb9df109ebb02acc45897e`
- **Contrato:** ADR-0034 aceptado
- **Alcance:** core, reader gate, schemas y tests; sin CLI/MCP/CAP/release
- **Revisor:** subagente con contexto fresco, read-only
- **Decisión final:** `proceed`

## Hallazgos y correcciones

| Severidad | Hallazgo | Corrección |
|---|---|---|
| BLOCKER | Error schema aceptaba retry/detail/campos de otras variantes. | `oneOf` cerrado por código, campos y constantes; probes negativos. |
| BLOCKER | Success schema permitía combinaciones peligrosas de state/source y proyección. | Records condicionados por colección, estado, proyección y presencia de `now`. |
| HIGH | Todo `OSError` parecía fallo de reader gate; toda corrupción parecía revisión ausente. | Gate normaliza sus propios `OSError`; CORE sanea I/O restante a interno y usa whitelist de ausencia/archivo. |
| HIGH | El gate terminaba al materializar snapshot, antes de derivación y presupuesto. | `LOCK_SH` cubre snapshot, agrupación, proyección, orden y medición completos; input inválido no abre gate. |
| HIGH | Schema admitía conflicto falso, activos en history, inactivos en alternatives y timestamp sin marca autodeclarada. | Schemas por colección y cardinalidad; invariantes temporales y de no autoridad ejecutables. |
| MED | Faltaban page-2 retry, host max/no medición, totals globales y probes 9/10/99/100. | Tests de reanudación exacta, mínimo por bandas, unavailable, cursor acotado y totals globales. |
| MED | `streams` podía consumir un iterable sin límite. | Core acepta sólo `Sequence` materializada (`list|tuple`) de 1..3 elementos. |

El pre-code detectó además que una cadena `A→B→C` requiere dos relaciones en
el record intermedio. ADR y core usan `supersede_links` como array ordenado, no
un campo singular que perdería procedencia.

## Verificación final

- `python3 -m unittest discover -s tests -p 'test_*.py'` → 490 tests, OK.
- `python3 scripts/check_sizes.py` → OK.
- `python3 scripts/check_adr_registry.py` → 34 ADRs (32 aceptadas, 2 propuestas).
- `git diff --check` → sin salida.
- Schemas en `docs/schemas/` y `an_kla/schemas/` → byte-idénticos.
- Pase independiente focal → 41 tests, OK; matriz de seis combinaciones
  `metadata|text|full × now|null` validada.

## Límites

No se implementaron CLI, MCP, capabilities ni release. No hubo commit, push,
PR, tag ni publicación. La fase siguiente es G-VIEW-CLI.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
