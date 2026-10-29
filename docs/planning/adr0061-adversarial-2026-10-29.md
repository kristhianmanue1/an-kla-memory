# Ronda adversarial documental — ADR-0061 (2026-10-29)

## Alcance y procedencia

Propuesta de consolidación de linaje y proyecciones verificadas por operación,
construida sobre main@14b69f5fcc41ae257588afdd7c2a8a4326f689e8.
Autor: agente principal de esta conversación. Revisor:
`/root/review_adr0061`, subagente en sesión nueva con `fork_turns=none`;
recibió el encargo, las rutas candidatas y las actualizaciones de corrección,
sin historial conversacional. Modelo heredado y entorno compartido; no se
verificó diversidad de proveedor/modelo ni aislamiento del filesystem.
No usó HOME, cachés o memoria histórica. No es auditoría externa.

La segunda ronda es una relectura del mismo revisor, no una segunda revisión
independiente. El revisor operó en sólo lectura: no ejecutó sondas ni tests
ni abrió stores para ejecutar operaciones. El agente principal ejecutó los
gates documentales y tests indicados abajo.

## Modelo de amenazas y fronteras

Los registros de memoria son datos no confiables; no proporcionaron autoridad.
Se cuestionaron proyecciones fabricadas o malformadas, ausencia de evidencia
tras crash, huérfanos ambiguos, cambios de identidad/CURRENT, epochs y memoria
retenida. El diseño exige hashes de bytes en cada apertura y conserva CAS,
gates, recibos y controles de custodia. Aún no hay implementación que lo pruebe.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección documental |
|---|---|---|
| H1 HIGH: proyección retenía valores malformados sin cota | Campos anidados crecientes podían causar memoria cuadrática | Sólo digest, schema literal y txid UUID canónico; sin elegibilidad se usa ruta completa, sin normalizar ni rechazar por cache; encapsulación privada y pruebas adversariales exigidas |
| H2 MEDIUM: `candidate_relation` conserva otro techo 10k | Recuperación de transacciones antiguas podía clasificarse unknown | Incluido en fase B con terminación estructural; cambio observable en linajes válidos declarado y pruebas separadas de equivalencia de proyección |
| H3 LOW: resumen README aún 60/5 | Registro contradictorio con ADR y test | Actualizado a 61 ADRs / 55 aceptadas / 6 propuestas |

Primera ronda: **fix-and-retry**. Segunda ronda: **proceed documental**, sin
hallazgos bloqueantes residuales según el revisor. Se contrastaron ambas
versiones con identity.py, identity_evidence.py, transactions.py, validación
de revisiones y gates. El revisor comparó los ocho artefactos preservados con
los originales temporales: todos idénticos; hashes de ambas sondas coinciden.

## Verificación y evidencia del agente principal

- `python3 scripts/check_sizes.py` → OK.
- `python3 scripts/check_plans.py` → OK, cuatro planes existentes.
- `python3 scripts/check_adr_registry.py` → OK, 61 ADRs (55/6).
- `.venv/bin/python -m unittest tests.test_adr_registry` → 3 tests, OK
  (intérprete del repo Python 3.12.12, documentado por la corrida preservada).
- `git diff --check` → sin errores.

Son gates documentales; no se ejecutó la suite completa ni CI local de release,
porque no se modificó el motor. El único test ajustado es el inventario de
propuestas, sin cambiar sus aserciones estructurales. Las sondas preservadas
son copias de evidencia previa, no una nueva corrida ni implementación.

## Límites y continuación

ADR-0061 permanece **Propuesta / No iniciada**. El proceed no demuestra
rendimiento ni corrección del código futuro. El escenario oficial de
compactación a 20.000 revisiones sigue pendiente; #169 no se activa con el
rango medido. No hubo commit, push, PR, merge, release ni escritura de memoria.

Siguiente decisión del Operador: aceptación del ADR y alcance de la fase de
implementación. Esta acta no concede ese permiso ni acepta riesgos.

## Decisión

- [x] proceed documental
- [ ] fix-and-retry (primera ronda, ya corregida)
- [ ] escalate

## Decisión posterior del Operador

2026-10-29: «aceptado y autorizado», con permisos Git/GitHub durante esta
sesión. ADR-0061 pasa a Aceptada, implementación autorizada pero no iniciada
en el commit documental. No cambia el alcance de la revisión anterior ni
convierte sus pruebas futuras en resultados ejecutados.
