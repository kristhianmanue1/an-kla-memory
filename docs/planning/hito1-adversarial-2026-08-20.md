# Ronda adversarial HITO 1 — puntos 1–4 (2026-08-20)

Re-ataque de conjunto tras cerrar los puntos 1–4 del plan
`plan-backlog-2026-08-20.md`. Revisor independiente (subagente) con
evidencia propia. Veredicto de la ronda: **fix-and-retry** por H1;
corrección documental aplicada en este mismo documento; cierre
**proceed** condicionado a la decisión registrada abajo.

## Alcance

Commits del hito: `e15f019` (#84), `17acefe` (ADR-0036),
`f9984ef` (candidata beta.15), `f3f5d9f` (G-FRESH). Interacciones
catch-all×G-FRESH, coherencia candidata↔árbol, schemas, registro ADR,
deuda no nombrada.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1 (ALTA, proceso): las notas y ronda REL de beta.15 dicen "sin cambios en retrieval.py / no incluye G-FRESH", pero HEAD ya no es ese árbol: taguear HEAD publicaría G-FRESH sin notas y contradiría tres documentos fechados. `test_release_metadata` no puede verlo (sólo verifica cadena de versión y existencia de archivos) | Tag erróneo silencioso | **Decisión registrada (ver abajo): el tag `v0.1.0-beta.15` se crea sobre `f9984ef` exacto**; G-FRESH y los puntos 5–12 viajan en beta.16 con ronda REL propia. Alternativa (absorber G-FRESH en beta.15) exigiría re-escribir documentos fechados: rechazada |
| H2 (MED-BAJA): README afirma "prerelease pública más reciente v0.1.0-beta.15" antes de que el tag exista; conserva "544 pruebas" | Ventana pre-tag alargada por la rama | Consistente con la convención del repo (el commit de release y el tag van juntos en `main` tras el merge; los 8 commits post-beta.14 mantuvieron `VERSION=b14` igual). Se corrige al taggear; si la rama se abandona sin tag, el maintainer debe revertir `f9984ef` |
| H3 (INFO): catch-all × G-FRESH seguro: `TemporalError` ⊂ `ValueError` atrapado antes del catch-all (verificado en vivo: `--now garbage` → `invalid_freshness_now`); datos corruptos se clasifican en buckets, no lanzan | Ninguno | Ninguna |
| H4 (INFO): `check_beta14_upgrade` construye el wheel desde HEAD (ya con G-FRESH) pero no afirma frescura | Gate no distingue candidata descrita vs probada | Si beta.15 se taguea en `f9984ef` (decisión H1): sin acción. El gate de beta.16 deberá afirmar los denominadores |
| H5 (MED): el drift de tag-point no estaba nombrado en ninguna ronda puntual | Deuda implícita | Nombrado aquí |
| H6 (OK): 66/66 schemas byte-idénticos docs/≡an_kla/; registro 37 ADRs 34/3 coincide gate↔test↔tabla; ADR-0036/0037 sin contradicción | — | — |

## Decisión registrada (pendiente de orden del maintainer)

**Punto de tag**: `v0.1.0-beta.15` sobre `f9984ef` exacto. Ese árbol es
el descrito por la única decisión `proceed` válida de
`docs/releases/v0.1.0-beta.15-adversarial.md` (verificado: diff
`v0.1.0-beta.14..f9984ef` sobre `store.py`/`retrieval.py`/`index.py`/
`write_policy.py` vacío). Todo commit posterior (G-FRESH, puntos 5–12)
es desarrollo hacia **beta.16**, que exigirá ronda REL propia que
re-describa la candidata exacta antes de cualquier tag. Desviarse de
esta secuencia (taguear HEAD como beta.15) requiere nueva ronda REL y
ordena explícita.

## Verificación

- Suite completa: 560/560 OK (88.9s, revisor).
- `ci_local.py --simulate-ci`: OK.
- `check_beta14_upgrade.py`: OK (con matiz H4).
- Sonda CLI: `retrieve --now garbage` → `invalid_freshness_now` exit 1
  (superficie específica, no catch-all).
- `git ls-remote --tags origin`: último tag `v0.1.0-beta.14`.

## Decisión

- [x] proceed (condicionado a la decisión de tag registrada arriba)
- [ ] fix-and-retry
- [ ] escalate (la elección final del punto de tag queda en la mesa del
  maintainer; la recomendación unánime de las dos rondas es `f9984ef`)
