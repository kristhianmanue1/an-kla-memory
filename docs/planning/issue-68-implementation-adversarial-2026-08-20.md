# Ronda adversarial — #68 inventario físico (ADR-0041, 2026-08-20)

Rama `feat/issue-68-inventario`. Ronda post-code pre-commit (2 pasadas)
+ verificación. Cierre: **proceed**.

## Ronda 1 (fix-and-retry, 5 hallazgos)

| Hallazgo | Corrección |
|---|---|
| **H1 (Alta)** — el chequeo de archivado consultaba el catálogo sólo si la lectura fallaba: la ventana `committed_cleanup_incomplete` (manifest archivado aún en disco) **se servía** | Reordenado a catalog-first (`bare_digest` → CURRENT → si v3 `archived_revision_link_under_gate` SIEMPRE, antes del snapshot), patrón `verify_revision` exacto. Verificado por el revisor con ventana fabricada real |
| **H2 (Alta)** — invariante `total = Σ` rota con `eliminada`-físico (sin bucket) | Decisión del maintainer (🔒): bucket `eliminada` + extras enteros para exóticos; 5 buckets canónicos exigidos por schema. Mezcla real verificada: `4 = 2+1+0+1` |
| **H3 (Media)** — helper de tests muerto/roto (3 bugs) | Eliminado; tests reales: supersede **gobernado** (`plan_write`/`commit_write_plan`) + compactación **e2e** (`create_export`/`plan_compaction`/`commit_compaction`) |
| H4 (Baja) — cursor no liga `--streams` | Documentado en ADR §3 (caller mantiene selección; engordar el cursor se rechazó) |
| H5 (Info) — `physical_status` strings arbitrarios | Declarado untrusted en §2 |

## Ronda 2 (fix-and-retry, residuos + 1 nuevo)

| Hallazgo | Corrección |
|---|---|
| H1/H2/H5 cerrados con evidencia propia del revisor (ventana real: `revision_archived_by_compaction`; invariante OK; schema valida) | — |
| H3-residuo — el test de la ventana NO escribía el manifest restaurado (variable muerta; presentaba evidencia que no producía) | Reescrito: localiza el manifest por digest canónico en el bundle y lo **escribe** a disco antes de asertar el rechazo |
| **N1 (Low)** — status autodeclarado `"total"` colisionaba con la clave reservada: `total=2` con 1 record, instancia válida, operador engañado | `"total"` cuenta como exótico (`status:total`); test con el caso |
| `__main__` duplicado | Limpiado |

## Verificación final

Suite **632/632 OK** (14 tests de inventario); `ci_local --simulate-ci` OK;
`check_sizes` OK (parser extraído a `cli_parser.py`, superficie CLI intacta
— 29/30 helps idénticos vs beta.16, único diff `adopt-baseline` de main);
`check_adr_registry` OK (41/39/2); gates beta.14/15 upgrade OK; cursor
probado con 13 vectores de manipulación; metadata-only verificado con
texto señuelo (SECRETOXYZ ausente de stdout/stderr).

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate
