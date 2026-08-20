# Ronda adversarial — research #69 relaciones entre subjects (2026-08-20)

Punto 11 del plan `plan-backlog-2026-08-20.md`. Revisor independiente
con `gh` real (28 issues inspeccionados), grep de docs/código y lectura
de ADR-0032/0033/0034. Una pasada: fix-and-retry → corregida.
Cierre: **proceed** con `no-action`.

## Hallazgos y correcciones

| Hallazgo | Corrección aplicada |
|---|---|
| Alta — ADR-0032 (aceptada) habla de "superficies y relaciones" e "ineario de navegar entidades y relaciones estables"; el "cero casos en docs" no podía sostenerse sin direccionarlo | Párrafo añadido: relaciones como contenido (facts recuperables) vs aristas navegables del store; el invariante publicado queda cubierto por G-VIEW+lineage; reapertura explícita si el maintainer lee distinto |
| Media — tabla omitía a kratos (#53) y Praxis/Epistates (#54), consumidores nombrados en el tracker | Filas añadidas (verificados sin demanda relacional: demanda a nivel scope); claim acotado a lo inspeccionado |
| Media — el ejemplar de reapertura era respondible hoy (lineage_refs se proyecta en las tres proyecciones) y jamás dispararía | Ejemplar sustituido por travesía transitiva multi-salto vía aristas de dominio (sin representación física actual) |
| Media — amenazas faltantes (contaminación temporal por rotación de ids en supersede; O(páginas) sin índice inverso) | Añadidas junto a amplificación MCP |
| Baja — cita desactualizada (`write_policy.py:236-237` → 238-247) | Corregida |
| Info — memoria AN-KLA exageraba ("Skevi" no es consumidor; sólo precedente normativo) | Registrado en el doc como nota de frontera |

## Decisión

- [x] proceed (research publicable; #69 cerrable con `no-action`)
- [ ] fix-and-retry
- [ ] escalate
