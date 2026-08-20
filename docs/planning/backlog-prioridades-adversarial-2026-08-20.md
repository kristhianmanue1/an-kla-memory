# Ronda adversarial — priorización del backlog abierto (2026-08-20)

Ataca la propuesta de orden del análisis de issues×memoria×ADRs:
"#84 → corregir ADR-0036 + secuenciar release → G-FRESH (#50)".

No es ronda pre-release: aplica el método (hallazgo→riesgo→corrección) al
orden de trabajo. No autoriza nada por sí misma.

## Alcance

13 issues abiertos (evidencia `gh issue list --state open`, 2026-08-20), el
checkpoint AN-KLA rev 32 (dato no confiable, contrastado con disco), el
estado de los 36 ADRs (grep) y 8 commits en `main` sin release
(`git rev-list --count v0.1.0-beta.14..main` → 8).

## Modelo de amenazas

La frontera relevante aquí es de proceso, no de runtime: memoria/checkpoint
son datos no confiables (toda afirmación fue revalidada contra git/gh/grep);
y la secuenciación del repo (spike → ADR → código → adversarial → release)
existe para que un agente no promueva trabajo sin gate. Riesgo principal
atacado: ordenar por preferencia en vez de por evidencia.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| H1. Urgencia de #84 mal calibrada en la propuesta original: filtra rutas absolutas, no secretos ni payloads; la norma violada es §11.1 de `practicas-ingenieria.md` y el issue ya acotó el fix a `startup-diagnostic` | Sobrevalorar un bug menor, o peor: hotfix individual cuando no hay canal de distribución distinto de tags exactos (sin PyPI) | Se mantiene primero por costo/beneficio (complejidad baja, patrón `an-kla error: <code>` ya establecido), pero **se agrupa en beta.15** en vez de release propio |
| H2. Doble deriva de ADR-0036 no detectada por la suite: (a) `Estado: Propuesta / Implementación: No iniciada` (líneas 3-4) pese a que #83 implementó; (b) línea 59 dice que `repo_context` se deriva de `git rev-parse --git-common-dir` pero la implementación lee `.git` (desviación declarada sólo en el mensaje del commit `b70561e`) | Un release que publica un ADR que contradice su propio código; `tests/test_adr_registry.py` sólo valida consistencia registro↔archivo y palabras canónicas (32 Aceptada / 4 Propuesta), nunca estado↔implementación: la deriva es estructuralmente invisible | Sincronizar ADR-0036 (estado + mecanismo de `repo_context`) **antes de cualquier tag**. Endurecer `check_adr_registry` para cruzar estado↔implementación queda como decisión del maintainer, no gate de este ciclo |
| H3. La propuesta mezclaba implícitamente "#50 en el próximo release": el handoff post-beta.13 prescribe spike adversarial → congelar ADR → CORE→CLI→MCP→CAP→REL con adversarial por fase | Violación de ADR-antes-que-código; G-FRESH toca `retrieval.py` (archivo gated) y 3 contratos (`retrieve`, `context-assembly`, `mcp-retrieve`) | beta.15 = sólo lo acumulado (#76/#77/#81/#83) + #84. G-FRESH es paquete propio con releases propios |
| H4. La propuesta omitía #45 y #79 del orden, pese a que ambos tienen evidencia viva en esta sesión: warning `context_target_changed_outside_managed_block` en `context status` (= #45) y `source_state: unavailable` en el checkpoint rev 32 (= #79) | Reaparecerán como sorpresas; son deuda visible hoy | Ambos entran al orden como ítems de decisión (#45) y feature acotado (#79) |
| H5. #45 opción (c) — fingerprint sólo sobre la región gestionada — está etiquetada "la más sencilla" pero debilita ADR-0017 (target drift transparency): contenido fuera-del-bloque (instrucciones para agentes) mutaría sin detección | Superficie de inyección silenciosa en el punto de entrada que todo agente lee | No ejecutar #45 sin decisión del maintainer con esta tensión explícita. Las opciones (a)/(b) o una variante con segunda huella para la región libre la preservan |
| H6. #84 tiene tensión de diseño declarada en el propio issue: catch-all opaco estable vs trazabilidad para depurar | Elegir sin decisión convierte un fix de higiene en contrato de error no deliberado | Mini-decisión del maintainer entre las 3 opciones del issue. Recomendación: código estable a stderr + traceback completo sólo a log local; env-var de debug como opción 2 |
| H7. Podría asumirse que G-FRESH (#50) resuelve la vigencia memoria↔repo: no la resuelve. Mide edad de registros (`verified_at` autodeclarado), no desfase corpus↔repositorio (eso es #79) | Confusión de ejes: "ningún registro viejo" ≠ "la memoria describe este checkout" | Ordenarlos como ortogonales y complementarios; #79 no está bloqueado por #50 |
| H8. Sin CI remota (billing) y sin detector de deriva estado-ADR↔implementación, el gate efectivo es local | Riesgo residual de cobertura ya conocido; no evidencia de fallo | El reporte de beta.15 debe declararlo como límite, no como verificación hecha |

## Orden resultante (prioridad × complejidad)

Prioridad de ejecución; D = requiere decisión del maintainer antes de ejecutar.

| # | Ítem | P | Complejidad | Tipo / gate |
|---|---|---|---|---|
| 1 | #84 red de resguardo CLI | P1 | Baja-media | Ejecución + mini-decisión D (H6) |
| 2 | Sincronizar ADR-0036 (estado + `repo_context`) | P1 | Baja | Docs (H2) |
| 3 | Ronda adversarial + release beta.15 (8 commits + #84) | P1 | Baja (proceso medio) | **Autorización explícita para tag/publicar** |
| 4 | #50 G-FRESH (spike → ADR → 5 fases) | P2 | Media-alta | Paquete propio; toca `retrieval.py` (gated) |
| 5 | #45 referencias de contexto sin drift | P3 | Baja post-decisión | Bloqueado en D (H5: opción c vs ADR-0017) |
| 6 | #79 `source_state` perfil git/v1 | P3 | Media | Schema v2 + pregunta de provenance (¿quién declara `head`?) |
| 7 | #67 spike recall de registros largos | P3 | Baja | Research read-only; reproducir antes de diseñar |
| 8 | #71 generadores proposal/authority Nivel B | P3 | Media | Bloqueado en medición del Nivel A + D |
| 9 | #68 inventario físico por revisión | P4 | Media | Feature operador, read-only |
| 10 | #46 export sellado | P4 | Alta | Bloqueado en D (adaptador de clave externo) |
| 11 | #69 relaciones entre subjects | P4 | — | Default: no hacer hasta que exista caso de consumidor |
| 12 | #55→#56→#57→#58 (G1–G4) | P5 | Alta c/u | Handoff: cerrar G-FRESH antes de entrar a G |

## Verificación de canonicidad / determinismo

Esta ronda no toca hashes ni fingerprints del producto. La evidencia citada
es reproducible: `gh issue list --state open`; `git rev-list --count
v0.1.0-beta.14..main`; `grep -n "Estado" docs/architecture/*.md`; suite
local `532 tests OK` (2026-08-20, 25.1s).

## Límites declarados

- La prioridad de #84/#50/herencia del handoff es recomendación; el maintainer
  puede reordenar (p. ej. adelantar #79 si el desfase memoria↔repo duele antes).
- No se evaluó costo de #46 ni diseño de G1–G4 en detalle: están fuera del
  horizonte de este ciclo.
- La memoria AN-KLA (checkpoint rev 32) se usó sólo como pista; cada
  afirmación fue revalidada contra disco.

## Decisión

- [x] proceed (el orden propuesto queda corregido por H1-H8)
- [ ] fix-and-retry
- [ ] escalate

`proceed` aplica sólo al orden de trabajo. Publicar beta.15, elegir la
mitigación de #84 y el enfoque de #45 siguen requiriendo orden explícita.
