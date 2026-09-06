# Ronda adversarial pre-code — ADR-0048 (2026-09-05)

Objeto: `docs/architecture/0048-store-root-externo-v1.md` (Propuesta).
Método: atacante de contexto fresco (sólo lectura), lectura línea a línea
de la cartografía del ADR + 3 experimentos con stores sintéticos.

## Veredicto: `fix-and-retry` — absorbido

1 BLOCKER, 3 HIGH, 5 MEDIUM, 3 LOW. La cartografía de código del ADR fue
verificada línea a línea y resultó exacta (pivote `store.py:100`, `adopt`
en `identity.py:478-481`, const false en schemas, `_PATTERNS`,
`rename_noreplace` en `export_io.py:124-140`, 92 referencias `.an-kla` en
tests, conteo de registro 47/44/3 → 48/44/4).

## Hallazgos y absorción

| ID | Sev | Hallazgo | Absorción |
|---|---|---|---|
| H1 | BLOCKER | Fork silencioso de identidad: sin puntero persistente, tras relocate un `init` sin flag/env crea una bóveda gemela con UUID nuevo (experimento: uuid 1305edd8 vs f13fd59e) — viola #57 ("no reasigna silenciosamente") | §1: puntero de custodia `.an-kla/store-root.txt` con fingerprint del binding; precedencia flag > env > puntero > project-local; divergencia → `store_root_divergence` fail-closed |
| H2 | HIGH | "Ventana de crash = un rename" irrealizable: staging interior al destino + bóveda dispersa; relocate-back imposible (destino ocupado por carve-outs) | §3: staging hermano del destino + publish `rename_noreplace` único para relocate; relocate-back declarado por subárbol bajo locks + journal (sin promesa de rename único) |
| H3 | HIGH | Defecto vivo: `export` falla hoy (`export_unrecognized_durable_path`) ante `hook-runs/` y `host-hooks.json` — cualquier proyecto host-managed no puede exportar | §3: decisión congelada — `hook-runs/**` entra a `_PATTERNS` (viaja), `host-hooks.json` a exclusiones; reparación priorizada en deuda beta.23 (issue #119) |
| H4 | HIGH | Enumeración de re-anclaje de symlinks incompleta: bootstrap externo fallaría (`identity.py:311,347-363`, `identity_evidence.py:126,173,218-233`) | §2: regla general (todo `root` de walk/create/sync de identidad → raíz de custodia) + test F1 de init fresco externo |
| H5 | MED | `attest.key` ambiguo en el set de staging (export lo excluye por diseño; relocate debe moverlo) | §3: set exacto = `_PATTERNS` ∪ {attest.key, whitelist, receipts/, nonces/, hook-runs/} + anchor; export permanece sin llave |
| H6 | MED | `store_root_resolved` (ruta) rompe la doctrina sin-rutas de superficies observables | §4: descriptor = `custody_fingerprint` + `store_external` |
| H7 | MED | "Sin writers activos" sin mecanismo; attest/hook-runs acuñan sin store lock → evidencia huérfana posible | §3.4: commit bajo write_lock + reader gate; cleanup sólo borra el delete-set del plan; nacidos después → reportados por doctor |
| H8 | MED | Hook git del propio repo no hereda `AN_KLA_STORE_ROOT` post-relocate | §5: el puntero de H1 lo resuelve estructuralmente |
| H9 | MED | Semántica de receipts de identidad bajo dos raíces no declarada | §2: rutas relativas interpretadas respecto a la raíz de custodia; los receipts viajan con la bóveda; schema sin cambio |
| H10 | LOW | Colisión de etiqueta F0-C (spike vs ADR) | §2 renombrada a "(spike S2)" |
| H11 | LOW | Precedencia de resolución implícita | §1: orden explícito flag > env > puntero > default; divergencia flag/env diagnosticada |
| H12 | LOW | Eje de doctor "raíces que debían coincidir" indefinido | §4: `custody_divergence` = puntero vs custodia resuelta vs `canonical_project_root_at_init` |

## Re-verificación post-absorción (2026-09-05, ejecutada)

- **H1**: §1 — puntero `.an-kla/store-root.txt` con fingerprint, precedencia
  flag > env > puntero > project-local, divergencia →
  `store_root_divergence` fail-closed incluido `init`/`adopt`. ✓
- **H2**: §3 — staging **hermano** del destino + publish
  `rename_noreplace` único para relocate; relocate-back declarado por
  subárbol bajo locks sin promesa de rename único. ✓
- **H3**: §3 — decisión congelada: `hook-runs/**` a `_PATTERNS`,
  `host-hooks.json` a exclusiones; defecto vivo derivado a issue #119
  (fix servido el mismo día). ✓
- **H4**: §2 — regla general: todo `root` de walk/create/sync de
  identidad pasa a la raíz de custodia; test F1 de init fresco externo
  exigido. ✓
