# ADR-0043: modelo de amenazas del store (`store-threat-model/v1`)

- **Estado:** Aceptada (🔒 decisión del dueño 2026-08-31, tras ronda
  adversarial fresca con veredicto APROBADO CON CORRECCIONES — 6
  hallazgos, 2 críticos, corregidos en `bd4ba27` y verificados con
  ci_local/selftest en verde; el núcleo tamper-evidence≠tamper-proofness
  resistió todos los ataques, incluido re-anclaje a cadena corta con
  borrado de historial).
- **Fecha:** 2026-08-31 (tarjeta `ankla-g1-g3-threat-model-redteam`, run
  sobre LAUNCH_HEAD `2649ea8`).
- **Decide sobre:** qué adversarios y superficies modela el store
  `.an-kla/memory`, y qué garantías ofrece y NO ofrece frente a cada uno.
  No decide arquitectura de anclaje externo, ni la formulación de hipótesis
  de comparación con otros sistemas (eso excede este ADR y es decisión
  posterior sobre la evidencia aquí caracterizada).
- **Origen:** análisis del mandato de orquestación AN-KLA↔TencentDB
  (`docs/analisis-mandato-orquestacion-2026-08-31.md` §3.3 G-1/G-3) — el
  único ROJO de las 16 comprobaciones §7 era la inexistencia de este
  documento.

## Contexto

AN-KLA declara integridad verificable (content-addressing sha256 de punta a
punta: segmentos, manifiestos, checkpoints, refutaciones; cadena de
revisiones validada estructuralmente hasta la revisión 0; binding de
identidad del store). Esa declaración ha sido leída — incorrectamente —
como resistencia a manipulación deliberada. Este ADR fija la frontera real
con evidencia experimental: **AN-KLA ofrece tamper-evidence (detección de
corrupción y de manipulación inconsistente), no tamper-proofness
(resistencia a un adversario con control del medio de almacenamiento)**.

## Decisión

El store se modela contra los siguientes adversarios, en orden de
capacidad creciente. Para cada uno se declara qué garantía ofrece el diseño
vigente y cuál NO.

### A1 — Fallos accidentales (bit rot, escrituras truncadas, crashes)

- **Qué lo causa:** fallos de disco/RAM, procesos interrumpidos
  mid-write, bugs de herramientas externas.
- **Garantía OFRECIDA:** detección completa de CORRUPCIÓN de objetos. Todo
  objeto se lee re-hasheando su contenido (`_read_json_object` /
  `_read_segment`: `object_hash_mismatch`, `segment_hash_or_framing_invalid`);
  la canonicidad JSON se re-verifica por objeto; `verify` falla cerrado con
  código exacto ante cualquier divergencia. NO cubre rollback: restaurar
  `refs/CURRENT` a una revisión previa LEGÍTIMA (bug de backup/sync,
  sincronizador de archivos, máquina del tiempo) deja `verify → ok:true`
  con datos silenciosamente viejos — la detección de regresión requiere
  anclaje externo (ver Consecuencias).
- **Evidencia:** `tests/test_store.py`, `tests/test_canonical.py`,
  `tests/test_storage_primitives.py`; matriz sellada filas 2-5 (ADR-0042).

### A2 — Manipulación inconsistente (editar un objeto sin recomputar la cadena)

- **Qué lo causa:** edición manual de un registro, sustitución de un
  segmento, borrado selectivo de un manifiesto.
- **Garantía OFRECIDA:** detección completa. El identificador de cada
  objeto ES su hash; cualquier edición cambia el contenido y rompe el
  enlace desde el manifiesto padre o desde `CURRENT`. La validación de
  cadena (`revision_validation.py`) rechaza transiciones inválidas,
  downgrades de schema, y superposiciones de overlay contradictorias.

### A3 — Adversario con control del medio (reescritura CONSISTENTE)

- **Qué lo causa:** un atacante con acceso de escritura al directorio del
  store que fabrica una cadena alternativa internamente coherente:
  nuevos segmentos (incluyendo registros falsos con provenance fabricado),
  un manifiesto nuevo que los referencia, y `CURRENT` apuntando a ese
  manifiesto. Nada existente se corrompe: la cadena parental permanece
  íntegra y cada eslabón sigue verificando.
- **Garantía OFRECIDA: NINGUNA.** Esta es la frontera declarada.
- **Evidencia experimental (G-3, 2026-08-31):**
  `scripts/redteam_consistent_rewrite.py` ejecuta exactamente este ataque
  sobre una copia del store en tmp. Resultado observado:
  `verify` → `ok:true`, revisión falsificada aceptada como válida
  (rev 36 → 37 forjada); `retrieve` → sirve el registro mentiroso
  (`f-adversarial-consistent-rewrite-v1`) al consumidor como si fuera
  memoria legítima. El attack no usó los writers gobernados de an_kla
  (un atacante no respeta write-policy): escribió objetos content-addressed
  directamente y mutó `CURRENT`.
- **Lectura correcta:** el content-addressing de AN-KLA es una estructura
  de auto-consistencia, no una raíz de confianza. Todo el sistema descansa
  en que `refs/CURRENT` y el árbol de objetos no están bajo control del
  adversario. Sin un anclaje EXTERNO al medio atacable (digest publicado
  en otro canal custodiado), la verificación es tautológica respecto de un
  atacante de A3: verifica la consistencia interna de un mundo que el
  atacante puede reescribir completo.
- **Nota sobre `root_relocated`:** en la corrida experimental el resultado
  falsificado incluyó `root_relocated: true` (la copia vive fuera del
  checkout canónico). Ese campo advierte reubicación del ROOT, no
  falsificación — un atacante que operara sobre el root real no lo
  dispararía. No constituye detección.

### A4 — Adversario con control del host (procesos, memoria, binarios)

- **Garantía OFRECIDA: NINGUNA, y está fuera de alcance por diseño**
  (ADR-0031: frontera de custodia agente-dueño/host). Un adversario que
  controla el proceso puede falsificar resultados de `verify` sin tocar el
  disco. Ninguna herramienta local resistente a su propio host.

## Tabla adversario × superficie

| Superficie | A1 accidental | A2 inconsistente | A3 consistente | A4 host |
|---|---|---|---|---|
| Segmentos (registros) | detecta | detecta | NO detecta | fuera de alcance |
| Manifiestos de revisión | detecta | detecta | NO detecta | fuera de alcance |
| `refs/CURRENT` | detecta (sintaxis/longitud) | detecta (apunta a objeto inexistente/hash ajeno) | NO detecta (apunta a cadena forjada) | fuera de alcance |
| Checkpoint v2 | detecta | detecta | NO detecta (reutilizable tal cual) | fuera de alcance |
| Identidad del store (`identity.json`, binding) | detecta | detecta | NO detecta (reutilizable) | fuera de alcance |
| Índices derivados (sqlite-fts5) | auto-rebuild | auto-rebuild | NO detecta (derivado del mundo falsificado) | fuera de alcance |
| Export sellado (ADR-0042) | detecta | detecta (MAC/AAD) | confidencialidad intacta; autenticidad solo contra sustitución bajo la clave correcta — el EXTRACTO del contenido puede ser falsificado antes del sellado si el ataque precede al export | fuera de alcance |
| Transacciones/staging | detecta | detecta | NO detecta (staging sintético pasa `required_candidate_files`) | fuera de alcance |

**Nota — path de lectura vs path de verify (ronda adversarial 2026-08-31):**
la detección de las celdas "detecta" se ejercita al llamar `verify` (y, para
corrupción de objetos, en toda lectura de segmento vía re-hash). El binding
de identidad NO se enforcea en el camino de `retrieve`/`snapshot`: existen
manipulaciones (p. ej. cadena forjada con `store_identity` ausente) que
`verify` rechaza y que `retrieve` sirve con exit 0 — verificado
experimentalmente. Un consumidor que solo lee NO hereda la detección de
`verify`; el consumo de assurance debe ejecutar `verify` explícitamente
antes de confiar. (Enforce del binding en el camino de lectura: trabajo
futuro de la línea de desarrollo, no de este ADR.)

## Consecuencias

- **Positivas:** la frontera queda declarada con evidencia ejecutable, no
  como sobreafirmación latente. Cualquier evaluación futura de AN-KLA como
  capa de assurance puede citar este ADR y su script para saber exactamente
  qué prueba y qué no. La distinción memoria-legible/memoria-íntegra/
  memoria-auténtica del mandato de orquestación queda materializada: AN-KLA
  certifica íntegra (A1/A2), no auténtica (A3/A4).
- **Negativas:** confirmado que la independencia del verificador NO está
  cubierta por el diseño vigente sin anclaje externo. Cualquier consumo que
  requiera resistencia a A3 necesita un mecanismo adicional fuera del scope
  de este ADR (p. ej. digest de `CURRENT` publicado en canal custodiado).
  La mitigación exige además verificación ACTIVA del digest en el camino de
  lectura (un digest que nadie consulta no detecta nada) y anclaje
  confiable de la primera publicación (TOFU); la mecánica es trabajo
  posterior del dueño. La elección del medio de anclaje, su custodia y
  rotación es decisión del dueño (custodia de artefactos de confianza =
  ámbito del dueño), no de la línea de desarrollo.
- **Neutras:** el ataque de A3 es, hoy, el camino de MÍNIMO esfuerzo para
  un atacante con control del medio — no se necesitan colisiones sha256 ni
  romper criptografía alguna; basta fabricar objetos nuevos coherentes.

## Límites de esta modelización

- No modela canales de red (el store es local; el transporte es de otros
  componentes).
- No modela ataques de canal lateral ni Timing.
- La evidencia A3 fue producida sobre una bifurcación de la revisión
  corriente con un fact añadido. Las variantes naïve del ataque encuentran
  TRIPWIRES PARCIALES en `verify` — la ventana de revisión del checkpoint
  (`1 <= revision <= manifest_revision` → `checkpoint_v2_invalid`) y el
  binding de `store_identity` (`store_identity_lineage_mismatch`). Lo no
  garantizado es la resistencia contra un atacante que los rodee
  reutilizando el checkpoint del génesis y el `store_identity` adoptado:
  verificado experimentalmente (re-anclaje a cadena corta con ambos
  reutilizados → `verify → ok:true` sobre 1 revisión forjada que reemplaza
  37). Falsificar refutaciones comparte la misma causa raíz (ausencia de
  raíz de confianza externa) y no se ejecutó.
- Sin confidencialidad en reposo: el store local (~2.7 MB) vive en claro;
  un adversario de solo lectura (robo de backup) lee toda la memoria sin
  tocar nada. La confidencialidad del export es de ADR-0042, no del store.
- `verify` valida la revisión corriente y su cadena; no promete auditoría
  forense del árbol completo de objetos huérfanos.

## Test de regresión

- `tests/test_redteam_consistent_rewrite.py` — guard mecánico fail-closed
  del script (rechaza roots con `.git/` o `docs/architecture/`; exit codes
  canónicos) y forma del ataque.
- `scripts/redteam_consistent_rewrite.py --selftest` — camino completo:
  guard + copia desechable + ataque + verificación post-ataque. El
  resultado esperado (`forgery_accepted_by_verify: true` AND
  `lie_served_to_consumer: true`) ES la frontera: el selftest exige ambas
  condiciones mecánicamente y si `verify` deja de aceptar la falsificación
  sale con exit code 5 y mensaje canónico
  (`redteam_boundary_changed: … ADR-0043 must be reviewed`) — el cambio de
  frontera es un evento visible, no un éxito silencioso.

## Referencias

- ADR-0027 (export/restore verificable; "hashes dan integridad accidental,
  no autenticidad"), ADR-0031 (frontera de custodia agente/host),
  ADR-0022 (identidad de store), ADR-0042 (export sellado).
- Mandato de orquestación y su análisis
  (`docs/analisis-mandato-orquestacion-2026-08-31.md`, §3.3, §4.1 PR-5).
- Reporte del run: `docs/planning/2026-08-31-g1-g3-reporte-rag.md`.
