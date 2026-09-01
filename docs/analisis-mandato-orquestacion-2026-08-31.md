# Análisis crítico y propositivo — Mandato de orquestación: Evaluación Independiente AN-KLA ↔ TencentDB Agent Memory

**Fecha:** 2026-08-31 · **Autor:** agente-an-kla-tencent (encargo de Krathos, D-oral del dueño)
**Base:** main `0af4ad3`, árbol limpio · **Estado del mandato analizado:** PRE-INTEGRATION / EVIDENCE BUILDING
**Alcance de este documento:** análisis del mandato (no ejecución de su contenido). Regla dura respetada: cero integración con TencentDB, cero PRs upstream, cero modificaciones a TencentDB.

---

## 1. Evaluación crítica del mandato

### 1.1 Puntos fuertes

1. **H1 es falsable y el mandato lo dice en serio.** Las 7 condiciones de refutación (§4) están enumeradas como disyuntivas (`cualquiera de las siguientes`), lo que hace la hipótesis atacable por múltiples vías independientes. Es la estructura correcta: la mayoría de los documentos de "hipótesis" en ecosystems agénticos declaren intenciones, no falsadores.
2. **El principio metodológico (§5) ataca el fallo de diseño más probable.** "Construir AN-KLA específicamente para aprobar una evaluación diseñada alrededor de AN-KLA" es exactamente la validación circular que este repo ya ha documentado como riesgo en su propia historia (la memoria recuperada es `untrusted_memory_data`; AN-KLA.md lo declara en cada inyección). Mantener las líneas A y B independientes hasta la comparación es la contramedida correcta.
3. **§10 (fronteras conceptuales) es la sección más valiosa del mandato.** Las cinco distinciones (íntegro≠verdadero, provenance≠autoridad, persistencia≠confiabilidad, recuperación≠validación, ACL≠assurance) no son decorado: son exactamente las confusiones que producirían una matriz §9 llena de opiniones. Deben promoverse a definiciones operativas (ver §2).
4. **El criterio A/B/C/D incluye D (evidencia insuficiente) y le prohíbe forzar conclusión.** Explícitamente anti-premature-closure.
5. **El incidente 2.0.1 (§8) está correctamente degradado a incidente**, no convertido en evidencia contra TencentDB — coincide con lo que la evidencia real soporta hoy (ver §3.5).

### 1.2 Supuestos débiles

| # | Supuesto | Problema | Severidad |
|---|---|---|---|
| S-1 | «AN-KLA **parece** disponer de mecanismos que podrían ayudar» (§3) | Formulado sobre lectura de documentación. La regla de este repo (y del ecosistema Aria) es que README/docs son afirmación del autor, no evidencia de implementación. El mandato no exige que la caracterización de AN-KLA se haga con puntero a código/test. | ALTA |
| S-2 | H1 agrupa en una sola hipótesis integridad + procedencia + transición gobernada | Son propiedades distintas con niveles de garantía distintos en AN-KLA (ver §3.3): integridad/tamper-evidence está implementada y testeada; procedencia existe con límites declarados; la **independencia del verificador** (condición de refutación 3) es hoy un límite arquitectónico abierto. Una H1 monolítica puede quedar ni confirmada ni refutada por mezclar lo demostrable con lo no. | ALTA |
| S-3 | La condición 3 («garantías dependen del mismo actor auditado») se asume evaluable simétricamente | En AN-KLA el store, los hashes y el verificador viven en el mismo filesystem local sin anclaje externo obligatorio. Un atacante con acceso de escritura al host puede reescribir memoria + índices + `CURRENT` de forma consistente. AN-KLA detecta corrupción accidental y manipulación *inconsistente*; no resiste a un adversario con control del medio. La condición 3 podría refutar H1 **tal como está formulada**, no porque TencentDB sea mejor, sino porque la formulación pide tamper-proofness y AN-KLA ofrece tamper-evidence. | ALTA (afecta la validez de la decisión final) |
| S-4 | «Garantías funcionalmente equivalentes» (condición de refutación 1) sin criterio de equivalencia | "Equivalente" necesita definición por propiedad: ¿equivalente en mecanismo, en garantía demostrable, o en garantía verificable por el *agente consumidor*? Tres respuestas distintas. Sin fijarlo, la opción C (gap no confirmado) queda a discreción del evaluador. | MEDIA |
| S-5 | «Complejidad operacional desproporcionada» (condición 5) sin métrica | No hay unidad de medida (¿pasos de instalación? ¿superficies de fallo nuevas? ¿coste por sesión? ¿líneas de contrato?). Esta condición será invocada por intuición. | MEDIA |
| S-6 | La §7 presenta las 16 comprobaciones como lista plana de una sola pasada | Mezcla verificación puntual (correr tests), trabajo estructurante (modelo de amenazas — que no existe, ver §3.2) y mantenimiento continuo (issues). No todas las 16 tienen el mismo estatus ni el mismo dueño natural. | BAJA |

### 1.3 Riesgos

- **R-1 (asimetría de evaluadores):** TencentDB sería caracterizado por Basanos (agente especialista independiente del código), AN-KLA por su propio equipo de desarrollo (este análisis lo escribe el agente especialista del repo). La condición 3 del mandato, aplicada a la *evaluación misma*, se viola estructuralmente: el lado AN-KLA se auto-caracteriza. Mitigación en §2.2.
- **R-2 (deriva hacia la conclusión cómoda):** el coach construyó AN-KLA; el resultado emocionalmente esperado es A (gap confirmado / AN-KLA lo cubre). El mandato lo compensa con falsadores, pero la matriz §9 debe exigir evidencia ejecutable por celda, no pros.
- **R-3 (incidente 2.0.1 como narrativa):** ya existe un diff semántico 97f9465→v2.0.1 extenso (104 archivos modificados; ver §3.5). Si la reconstrucción del incidente no se convierte en repro, queda como anécdota directionally útil pero no citable en la matriz.

### 1.4 Omisiones

1. **No define quién adjudica** cada condición de refutación ni con qué gate (el ecosistema ya tiene la respuesta institucional: revisión adversarial fresca con veredicto; el mandato no la invoca).
2. **No fija umbral de suficiencia** para pasar de evidence-building a la comparación §9 — «cuando ambas líneas estén suficientemente consolidadas» es la única guía. Riesgo: la comparación arrive tarde (por perfeccionismo) o pronto (por presión de conclusión).
3. **No exige pre-registro del protocolo de comparación** antes de llenar la matriz §9. La experiencia local (protocolo memoria-prioritaria v1→v2, refutado por su propia ronda adversarial) muestra que la matriz sin criterios pre-registrados se llena con sesgo.
4. **No menciona el caso «gap confirmado parcialmente»**: la matriz puede mostrar gap en integridad y no en procedencia. A/B/C/D no tiene salida para cobertura parcial — obliga a B («corregir AN-KLA») cuando la lectura correcta podría ser «gap real en 2 de 13 propiedades».
5. **No explicita la restricción presupuestaria** (CI remota de an-kla-memory está inactiva por presupuesto; autoridad = `scripts/ci_local.py`) — relevante porque las comprobaciones §7.4/§7.16 dependen de qué se considera canon de verificación.

---

## 2. Propuestas de mejora

### 2.1 Sobre el plan

- **P-1 — Desdoblar H1 en tres hipótesis separadas** (resuelve S-2 y parte de S-3):
  - **H1a (tamper-evidence):** AN-KLA permite a un agente *consumidor* detectar modificación posterior de la memoria que lee, sin confiar en el canal de entrega.
  - **H1b (procedencia declarada y verificable):** cada registro recuperable se liga a su revisión de origen y a la política de escritura que lo admitió.
  - **H1c (independencia del verificador):** las garantías de H1a/H1b sobreviven a un adversario con control del medio de almacenamiento.
  H1a y H1b son hoy demostrables en AN-KLA con evidencia existente (§3). H1c es **falsa hoy en la formulación fuerte** y verdadera solo en la formulación débil (con anclaje externo: export sellado + digest publicado fuera del alcance del atacante). El mandato debería declarar cuál formulación de H1c evalúa; recomiendo la débil con anclaje, porque la fuerte excede el diseño declarado de AN-KLA (ADR-0031: frontera de custodia agente-dueño/host).
- **P-2 — Regla de evidencia por celda (matriz §9):** cada celda importante debe apuntar a **comando ejecutable o fixture**, nunca a documentación ni a changelog. Es la regla que el protocolo an-kla de Krathos ya usó (puntero a archivo o comando, README no cuenta). Adoptarla textualmente en el mandato.
- **P-3 — Pre-registrar el protocolo de comparación ANTES de llenar la matriz:** documento sellado (hash commiteado) con definiciones operativas de las 13 propiedades, antes de recolectar evidencia. Las definiciones de §10 son el punto de partida: convertirlas en tests decidibles (p. ej. «integridad: mutar 1 byte del artefacto de memoria → el lector debe fallar con diagnóstico específico, no servir el dato mutado»).
- **P-4 — Definir equivalencia funcional (S-4):** dos sistemas son equivalentes en una propiedad si el mismo **probe adversarial ejecutable** pasa en ambos. No equivalencia de mecanismo ni de marketing. Esto hace la opción C decidible mecánicamente.
- **P-5 — Métrica de complejidad (S-5):** mínimo conjunto pre-declarado: nº de pasos de instalación nuevas, nº de contratos/schemas nuevos que el operador de TencentDB debe entender, superficie de fallo nueva (procesos, claves, files), y coste por sesión. Umbral: la complejidad es desproporcionada si añade >1 clase de secreto gestionado o >1 servicio con estado sin eliminar ninguno.
- **P-6 — Umbral de salida de evidence-building:** ambas líneas listas para §9 cuando (a) las 16 comprobaciones §7 de la línea B tienen estado verificable (verde/rojo/documentado), y (b) Basanos tiene probes ejecutables para ≥8 de las 13 propiedades de la matriz. No antes; no exige perfección.
- **P-7 — Convertir la reconstrucción del incidente 2.0.1 en tarea con tarjeta** (Basanos), con destino fixture/test si reproduce. Ya existe la base de evidencia (diff semántico F1-T3).

### 2.2 Sobre el criterio de decisión A/B/C/D

Propuesta de criterio en **gates lexicográficos** (no suma compensatoria — misma corrección que la ronda adversarial aplicó al protocolo memoria-prioritaria v1):

1. **Gate D primero (evidencia):** si <80% de las celdas importantes de la matriz tienen probe ejecutable, el veredicto es **D**, sin discusión. D es default, no excepción.
2. **Gate C (gap):** para cada propiedad, C aplica solo si el probe adversarial pasa en TencentDB (equivalencia por P-4). Si el probe no corre en un lado, esa celda es "no demostrado", no "equivalente".
3. **Gate de independencia (condiciones 3-4 del mandato):** si las garantías de AN-KLA en las propiedades con gap dependen del mismo actor auditado sin anclaje externo, el veredicto no puede ser A para esas propiedades — máximo B con corrección (introducir anclaje externo como trabajo previo).
4. **A requiere unanimidad de cobertura:** A solo si TODAS las propiedades con gap confirmado tienen cobertura demostrada por probe en AN-KLA. Cobertura parcial → nuevo veredicto **B-parcial** (extensión propuesta): gap real en subconjunto; corregir AN-KLA solo en ese subconjunto (resuelve la omisión 4).
5. **Anti-ronda-complaciente:** si el veredicto final es A sin que H1c débil haya sido atacada con al menos un ejercicio red-team fresco (tercer contexto, sin participación del desarrollador), el veredicto se degrada a D (resuelve R-1/R-2: este análisis mismo no puede ser la evidencia que lo valide).

---

## 3. Estado real de an-kla-memory (main `0af4ad3`) frente a las 16 comprobaciones de §7 del mandato

Evidencia recolectada hoy (2026-08-31, comandos ejecutados desde el checkout canónico):

- `git status` limpio; HEAD `0af4ad3` (main).
- `.venv/bin/python scripts/ci_local.py` → **4/4 OK** (importabilidad, unittest, check_sizes, check_adr_registry — 42 ADRs: 40 aceptadas, 2 propuesta).
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'` → **886 tests, OK, 72 skips** (skips = camino criptográfico sellado sin el extra instalado — declarado, no silencioso).
- `python3 -m an_kla --project-root … status` → ok, rev 36, identidad completa.
- `python3 -m an_kla … verify` → ok (integridad de la revisión corriente verificada hoy).
- `gh issue list --state open` → 4 abiertos: #95, #56, #57, #58.

### 3.1 Tabla de las 16 comprobaciones

| # | Comprobación (§7 mandato) | Estado | Evidencia / puntero |
|---|---|---|---|
| 1 | Revisar issues abiertos | **VERDE** | `docs/gobernanza/INDEX.md` (índice pre-flight, verificado 29-08); `gh issue list` hoy: #95/#56/#57/#58 |
| 2 | Clasificarlos | **PARCIAL** | Prioridades propuestas en INDEX.md (P1-P3); clasificación por-taxonomía-del-mandato: ver §3.2 (nueva, este documento) |
| 3 | Resolver blockers | **PARCIAL** | Sin BLOCKER-TRUST/INTEGRATION *en issues*; los blockers reales para H1 son gaps sin issue aún (§3.3) |
| 4 | Ejecutar tests | **VERDE** | 886/886 OK hoy (72 skips declarados); `ci_local.py` 4/4 |
| 5 | Revisar modelo de amenazas | **ROJO — NO EXISTE** | No hay documento de threat model del store (44 ADRs, ninguno lo es). Ver §3.3 G-1 |
| 6 | Verificar invariantes | **PARCIAL** | Invariantes dispersos en tests (test_storage_primitives, test_canonical, test_store) sin catálogo central |
| 7 | Pruebas adversariales | **PARCIAL** | Rondas adversariales *de proceso* por release (docs/releases/*-adversarial.md) + matriz sellada 16 filas; falta red-team *técnico* sobre el store (manipulación deliberada end-to-end) |
| 8 | Comprobar recuperación | **VERDE** | `recover`, `rebuild-index`, `startup-diagnostic` + tests (test_auto_reindex, test_startup_diagnostic) |
| 9 | Comprobar integridad | **VERDE** | `verify` (ejecutado hoy, ok); test_store incluye casos de fallo (plan fingerprint alterado → rechazo) |
| 10 | Comprobar provenance | **VERDE con límites** | evidence/identity por registro; límite declarado: memoria recuperada es dato no confiable (`untrusted_memory_data` en cada perfil de export) |
| 11 | Comprobar authority | **VERDE** | write-policy → commit-write-plan; subject_ref (ADR-0033); frontera CLI autodeclaración vs host (write-policy-cli.md §Autoridad separada) |
| 12 | Comprobar concurrencia | **VERDE** | write_lock + LockBusyError (store.py:67-155); test_transactions, test_transaction_faults |
| 13 | Comprobar corrupción | **VERDE** | test_store (corrupción de plan), matriz sellada filas 2-5, 10c (ciphertext alterado, MAC, AAD, tamaño físico) |
| 14 | Comprobar export/restore | **VERDE** | test_export_restore + sealed-export/v1 completo (issue #46 cerrado T1-T6, PRs #96-#101); roundtrip byte-idéntico probado |
| 15 | Comprobar supersede/refute | **VERDE** | test_supersede, test_refute, refute-contract-v1 (JSON canónico cerrado) |
| 16 | Comprobar actualizaciones/migraciones | **VERDE con deuda** | test_upgrade, gates REL por release (beta.17→18→19 verificados); CI remota inactiva por presupuesto → matriz SO×Py no cubierta hoy (deferimiento Windows vigente) |

**Balance: 9 verde, 5 parcial, 1 rojo, 1 verde-con-límites.** El rojo (modelo de amenazas) y tres de los parciales (catálogo de invariantes, red-team técnico, clasificación) son trabajo de baja duración y alto valor para H1 — son exactamente lo que la condición de refutación 3/4 atacaría.

### 3.2 Clasificación de issues abiertos (taxonomía del mandato)

| Issue | Tema | Clasificación | Bloquea H1 | Nota |
|---|---|---|---|---|
| #95 | Deuda ADR-0042 (partir en ADR corto + apéndice) | **NON-BLOCKING** (documental) | No | P1 del ciclo; la partición ya empezó (refs/sealed-export-v1-appendix.md existe — C-B pendiente) |
| #56 | G2: adaptador host, hooks gobernados de recuperación/checkpoint | **RECOVERY** (+ UX operacional) | No directamente | Relevante para la *adopción* futura (un consumidor TencentDB necesitaría ese adaptador), no para la verdad de H1a/H1b. 5 decisiones de maintainer pendientes antes de arrancar |
| #57 | G3: separar store_root de project_root | **DURABILITY/RECOVERY** | No para H1a/b; **BLOCKER-INTEGRATION** para cualquier evaluación de integración futura | Máximo riesgo físico (hoy el store vive dentro del árbol del proyecto); tensión DoD-Windows sin resolver |
| #58 | G4: identidad de agente, aislamiento, multi-scope | **PROVENANCE/AUTHORITY** | **Sí, parcialmente** | La condición de refutación 3 (independencia) y el aislamiento entre identidades son núcleo de H1c; hoy diferido por diseño. Debe declararse como límite explícito en la caracterización, no esconderse |

**Sin SECURITY ni BLOCKER-TRUST abiertos en issues** — pero eso es un artefacto de que el threat model no existe (nadie ha hecho la pasada que los encontraría). Clasificación honesta: el gap G-1 (§3.3) es SECURITY y no tiene issue.

### 3.3 Gaps detectados sin issue (propuesta de alta)

- **G-1 [SECURITY / BLOCKER-TRUST para H1c]:** no existe threat model del store. Sin él, la comprobación §7.5 del mandato no puede cerrarse y las condiciones de refutación 3/4 no son evaluables de forma disciplinada.
- **G-2 [CORRECTNESS/documental]:** catálogo central de invariantes (hoy dispersos en ADRs + tests) — barato, habilita probes reutilizables para la matriz §9.
- **G-3 [adversarial]:** ejercicio red-team técnico sobre el store (no de proceso): ataque de reescritura consistente (memoria+índices+CURRENT+hashes coherentes entre sí) para caracterizar qué detecta `verify` y qué no. **Resultado esperado honesto: la reescritura consistente NO es detectable sin anclaje externo** — documentarlo convierte el límite en frontera declarada (lo que §10 del mandato exige) en vez de sobreafirmación latente.

### 3.4 Estado frente al escenario del mandato

La §11 del mandato pide demostrar seis cosas antes de estudiar integración. Posición actual honesta: (1) existe el gap → **sin demostrar** (requiere lado TencentDB: Basanos); (2) AN-KLA lo cubre → **parcialmente demostrado** (H1a/H1b verdes en §3.1; H1c débil requiere G-1+G-3+anclaje); (3) garantías verificables → verde para el consumidor con CLI; (4) sobreviven ataques → **no probado** (G-3); (5) valor operacional → no probado; (6) complejidad justificada → sin métrica (P-5).

### 3.5 Nota sobre el incidente 2.0.1 (línea A, para no perder el enlace)

La base de evidencia ya existe del lado Basanos: diff semántico 97f9465→a5dcbe6 (v2.0.1) — 104 archivos modificados, 99 nuevos, 46 eliminados, con receipt y clasificación por categoría (`basanos/docs/reports/2026-08-25-f1-t3-diff.md`, run `basanos-f1-auth-20260825-01`). La reconstrucción del incidente (§8 del mandato) debería partir de ese diff + logs del proxy, no desde cero.

---

## 4. Cómo verificar H1 de forma falsable SIN integrar

Principio: la comparación de propiedades no requiere integración — requiere **probes adversariales pareados y pre-registrados**, ejecutados contra cada sistema por su lado, con el mismo protocolo sellado. Propuesta concreta:

### 4.1 Protocolo de probes (pre-registrar antes de ejecutar)

Documento sellado (hash commiteado antes de la primera corrida) que define, por propiedad, un probe decidible. Núcleo mínimo:

| Probe | Propiedad | Predicción AN-KLA (falsable) | Ejecución sin integración |
|---|---|---|---|
| **PR-1 mutación** | Integridad | Mutar 1 byte de cualquier artefacto del store → `verify` falla con diagnóstico específico; `retrieve` jamás sirve el dato mutado silenciosamente | Fixture en tests/ sobre un store clonado a tmp; ya cubierto parcialmente por test_store + matriz sellada — falta consolidarlo como probe único nombrado |
| **PR-2 escritura fuera de plan** | Transición gobernada | Escribir sin plan válido → rechazo con código exacto; no hay camino `write` legado | test_write_commit/test_write_policy ya lo prueban; el probe lo formaliza para la matriz |
| **PR-3 ligazón de origen** | Provenance | Todo registro recuperable cita revisión de origen y plan; ausencia = fallo | Assert sobre retrieve + export (la marca `untrusted_memory_data` debe estar SIEMPRE presente en exports) |
| **PR-4 aislamiento** | Authority/aislamiento | Canario sembrado bajo identidad A jamás aparece en consultas de identidad B; identidad malformada → fail-closed | Store tmp con dos project_uuid (ojo: hoy el scope es proyecto, no agente — límite #58; declararlo) |
| **PR-5 adversario con fs** | Independencia (H1c) | Atacante con escritura en el medio reescribe store+índices+CURRENT coherentemente → `verify` NO detecta (predicción negativa honesta). Con export sellado + digest anclado fuera del alcance del atacante → sí detecta | **RESUELTO (2026-08-31):** red-team G-3 ejecutado (`scripts/redteam_consistent_rewrite.py`, predicción negativa CONFIRMADA: `verify → ok:true` + `retrieve` sirve el falso). H1c formalizada post-evidencia como **débil-con-anclaje** en [ADR-0044](architecture/0044-h1c-formalizacion-v1.md); verificación activa ejecutable: `scripts/verificar_anclaje.py`. Custodia del canal: PENDIENTE-DE-DUEÑO (corrección [e]) |
| **PR-6 concurrencia** | Concurrencia | Dos escrituras concurrentes → una commit, otra `LockBusyError`; sin corrupción intermedia | Ya testeado; formalizar como probe |

Cada probe se registra con: predicción ANTES de correr, resultado observado, comando exacto. **Un probe que no se puede ejecutar se marca NO PROBADO y su propiedad no puede contar como cubierta** (regla del protocolo memoria-prioritaria, ya pagada con una refutación).

### 4.2 El lado TencentDB sin tocar TencentDB

Los mismos probes (misma numeración, mismas predicciones) los ejecuta **Basanos** contra snapshots/instancias de evaluación locales del stack TencentDB Agent Memory — lectura y experimentación sobre copias, sin modificar el upstream ni abrir PRs (dentro de la autorización existente de tarballs por commit exacto, acta 25-08). La celda de la matriz se llena con el receipt del probe de cada lado.

### 4.3 Anti-bucle-circular

El protocolo de comparación (definiciones + probes + predicciones) se sellan ANTES de que ningún lado corra nada, y el veredicto A/B/C/D pasa por revisión adversarial fresca de un tercer contexto que no desarrolló AN-KLA ni caracterizó TencentDB. Este documento — escrito por el especialista del repo — es insumo, no evidencia de validación (regla 6 de mi contrato: nada se da por verificado sin revisión externa fresca).

---

## 5. Recomendación — próximos 3 pasos

1. **Cerrar el rojo de §7.5 del mandato: threat model del store (G-1) + ejercicio red-team PR-5 (G-3).** Un ADR de threat model (activo: host adversario, medio editable, colisiones de identidad) y el script de reescritura consistente con resultado honesto esperado (no detectable sin anclaje externo). Esto convierte el mayor riesgo del mandato (S-3) en frontera declarada y decide si H1c se evalúa en formulación fuerte o débil. Sin esto, cualquier veredicto posterior es frágil. *Dentro de PLAT v2: tarjeta al especialista (este agente), ronda adversarial fresca, receipt.*
2. **Pre-registrar el protocolo de probes pareados (§4.1) y entregarlo a Krathos como propuesta de contrato con Basanos** (probes espejo del lado TencentDB, sobre tarballs autorizados). Incluye la métrica de complejidad (P-5) y el criterio de decisión en gates (§2.2) como enmienda al mandato. Decisión del coach: aceptar la enmienda A/B/C/D con B-parcial y gates.
3. **Cierre documental menor que habilita la comparación:** clasificar los issues con la taxonomía del mandato en GitHub (labels) usando §3.2, abrir G-1/G-2/G-3 como issues, y resolver #95 (P1, ≤ medio día) para dejar la deuda TECH_DEBT en cero antes de la fase de comparación. Paralelo (línea A, vía Krathos→Basanos): tarjeta de reconstrucción del incidente 2.0.1 partiendo del diff F1-T3 ya existente.

---

## Enmienda 1 — 2026-08-31 (incorpora verificación del orquestador, receipt 375162b en krathos)

Verificación de tercera parte: 6/6 comandos re-ejecutados desde contexto distinto con resultados idénticos — `ci_local` 4/4, suite 886 OK/72 skips, status rev 36, `verify` ok, mismos 4 issues. La tabla §3.1 deja de ser auto-certificada. Correcciones abiertas incorporadas:

- **[a] Orden invertido en H1c:** mi recomendación de formulación débil (§2.1 P-1, §4.1 PR-5, §5 paso 1) anticipaba una conclusión antes de la evidencia — exactamente el patrón que el propio mandato prohíbe. **Queda corregido así:** primero se ejecuta G-3 (red-team de reescritura consistente); la formulación de H1c (fuerte vs débil-con-anclaje) se decide **después**, sobre la caracterización observada. Toda mención de "formulación débil" en este documento se lee como hipótesis de trabajo a decidir post-G-3, no como recomendación. **EJECUTADA (2026-08-31):** G-3 corrido (predicción negativa confirmada, run ankla-g1-g3) y H1c decidida post-evidencia como **débil-con-anclaje** en [ADR-0044](architecture/0044-h1c-formalizacion-v1.md); la fila PR-5/§7.5 pasa a estado resuelto con puntero allí.
- **[b] Umbrales sin derivar eliminados:** el 80% de celdas y el ≥8 probes de P-6 quedan sustituidos por regla simple: **celda de la matriz §9 sin probe ejecutable = esa celda cuenta como D (evidencia insuficiente)**. El veredicto global hereda: cualquier celda D bloquea A/B/C en esa propiedad.
- **[c] Costos estimados añadidos** (norma de escalado — ver tabla §E1 abajo).
- **[d] B-parcial con salida definida:** B-parcial se cierra por **re-evaluación obligatoria a 30 días** de emitido el veredicto (o antes, si el subconjunto corregido cierra): a esa fecha, o las propiedades corregidas tienen probe verde (→ re-veredicto), o el ítem se degrada a B pleno con decisión de dueño sobre abandonar el subconjunto. Sin re-evaluación, B-parcial caduca a B.
- **[e] Anclaje externo de PR-5 — custodia desplazada, no resuelta:** el anclaje externo mueve el problema de "¿puede el atacante reescribir la memoria?" a "¿quién custodia el digest y con qué confianza?", que es una decisión de custodia de credenciales/artefactos del **dueño**, no del especialista. Queda marcado **PENDIENTE-DE-DUEÑO**: medio de anclaje, rotación y quién puede publicar digests.

### Tabla §E1 — Costos estimados (honestos, en horas de agente; S<2h, M 2-6h, L >6h)

| Ítem | Costo | Nota |
|---|---|---|
| G-1 threat model (ADR-0043) | M (3-4.5h) | redacción 2-3h + ronda adversarial 1-1.5h |
| G-3 red-team reescritura consistente | M (3-4.5h) | script 2-3h + ejecución/documentación 1-1.5h |
| G-2 catálogo de invariantes | S-M (1.5-3h) | consolidación de lo ya disperso en tests |
| P-1 desdoblar H1 (enmienda del mandato) | S (<1h) | edición del texto del mandato, lado orquestador |
| P-3 pre-registro protocolo de comparación | M (2-4h) | definiciones operativas de 13 propiedades |
| P-7 tarjeta incidente 2.0.1 (línea A, Basanos) | M (2-4h) | parte del diff F1-T3 existente |
| Paso ① (= G-1+G-3) | M-L (7-10h) | una sesión de ejecutor + revisor fresco |
| Paso ② protocolo + contrato Basanos | M (3-5h) | incluye P-3 y P-5 |
| Paso ③ labels + issues + #95 | S-M (2-4h) | #95 ya estimado P1 ≤ medio día |

---

## Anexo — Trazabilidad

- Mandato analizado: recibido in-band por el orquestador (D-oral dueño 2026-08-31), texto íntegro en el mensaje de encargo.
- Comandos ejecutados para §3 (todos read-only sobre el checkout canónico): `git log/status`; `gh issue list --state open`; `gh issue view 95/56/57/58`; `.venv/bin/python scripts/ci_local.py`; `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`; `python3 -m an_kla --project-root … status`; `python3 -m an_kla … verify`.
- Fuentes documentales: `docs/gobernanza/INDEX.md`, `docs/architecture/0042-sealed-export-v1.md` + `refs/sealed-export-v1-appendix.md`, `docs/mathematical-foundations.md` §7, `docs/practicas-ingenieria.md`, `basanos/docs/reports/2026-08-25-f1-t3-diff.md`, `krathos/docs/research/memoria-prioritaria/00-protocolo-v2.md` (patrón de gates lexicográficos), `docs/integrations/enforcement.md` (precedente de límites L3 evadibles).

**VEREDICTO DEL ANÁLISIS: PROCEED-WITH-AMENDMENTS** — el mandato es sólido en estructura falsable e independencia, pero H1 debe desdoblarse (H1a/b/c), el criterio A/B/C/D necesita gates pre-registrados y salida de cobertura parcial, y la línea AN-KLA tiene un rojo (threat model inexistente) y un límite arquitectónico (independencia del verificador sin anclaje externo) que deben declararse antes de cualquier comparación. Ninguna acción de integración fue ejecutada ni lo será bajo este mandato.

**Enmienda 1 (2026-08-31, post-verificación del orquestador — receipt 375162b):** veredicto se mantiene. Correcciones [a]-[e] incorporadas arriba; la formulación de H1c queda explícitamente **pospuesta a post-G-3**. Tarjeta para G-1+G-3 preparada como `docs/planning/task-card-2026-08-31-g1-g3-threat-model-redteam.json` (no ejecutada — pendiente ronda adversarial post-tarjeta y aprobación del dueño).
