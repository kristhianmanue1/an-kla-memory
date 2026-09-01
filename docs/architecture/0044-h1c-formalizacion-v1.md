# ADR-0044: formalización de H1c (independencia del verificador) — `h1c-formalizacion/v1`

- **Estado:** Propuesta (tarjeta `ankla-h1c-formalizacion-anclaje`; la
  aceptación sigue el flujo ronda → correcciones → dueño — este ADR propone,
  no acepta).
- **Fecha:** 2026-08-31 (run sobre LAUNCH_HEAD `449fb12`).
- **Decide sobre:** la formulación de H1c — independencia del verificador —
  que el análisis del mandato reservó explícitamente a post-G-3 (corrección
  [a]): si se evalúa como **formulación fuerte** (verificación sin anclaje
  externo) o como **formulación débil-con-anclaje** (verify + digest externo
  con verificación activa).
- **No decide sobre:** el medio concreto de anclaje, su custodia ni su
  rotación — ámbito del dueño (corrección [e] del análisis del mandato,
  PENDIENTE-DE-DUEÑO). Este ADR formaliza la forma de la hipótesis y el
  mecanismo de verificación; la custodia del canal queda abierta.

## Contexto

La condición de refutación 3 del programa de evaluación AN-KLA↔TencentDB
exige que las garantías del verificador sobrevivan a un adversario con
control del medio de almacenamiento. El análisis del mandato recomendó la
formulación débil, y su propia ronda de verificación detectó que esa
recomendación anticipaba la conclusión antes de la evidencia (corrección
[a]): la decisión quedó pospuesta a después de caracterizar el ataque. Esa
caracterización existe ahora:

1. **G-3 (evidencia experimental, 2026-08-31):**
   `scripts/redteam_consistent_rewrite.py` ejecutó la reescritura consistente
   (cadena forjada rev 36→37 + `CURRENT` mutado) sobre copia desechable.
   Observado: `verify → ok:true` sobre la revisión falsificada y `retrieve`
   sirviendo el registro falso al consumidor. Reporte:
   `docs/planning/2026-08-31-g1-g3-reporte-rag.md`.
2. **v4 (límite de los tripwires):** incluso la variante dura del ataque —
   re-anclaje a cadena corta reutilizando el checkpoint del génesis y el
   `store_identity` adoptado — produce `verify → ok:true` sobre una revisión
   forjada que reemplaza la 37. Los tripwires (`checkpoint_v2_invalid`,
   `store_identity_lineage_mismatch`) solo atrapan variantes naïve; un
   atacante que los rodea no es detectado (ADR-0043 §Límites).
3. **Protocolo de anclaje vigente:** `docs/gobernanza/anclajes/` publica el
   digest de `refs/CURRENT` fuera del alcance del atacante (GitHub, ancla
   TOFU 2026-08-31) y exige verificación activa comparando el digest del
   store contra el último ancla del registro en el arranque de cada sesión
   que consuma memoria y en el cierre de cada run.

La formulación fuerte de H1c exige que `verify` solo — sin nada fuera del
medio atacable — detecte la reescritura consistente.

## Decisión

**H1c se formaliza en la formulación débil-con-anclaje:**

> H1c (débil-con-anclaje): un adversario con escritura en el medio de
> almacenamiento no puede hacer que una sesión correctamente operada acepte
> memoria falsificada, **condicionado a** (C1)–(C3):
>
> - **(C1)** el digest de `refs/` se comparó contra el último ancla del
>   registro externo (verificación activa) en el arranque de la sesión;
> - **(C2)** el canal del registro (hoy: historial Git de
>   `docs/gobernanza/anclajes/` en GitHub) no está bajo control del
>   atacante modelado, y la primera publicación confiable se fija por TOFU;
> - **(C3)** la verificación activa la ejecuta una herramienta que no está
>   bajo control del atacante de A3 (el atacante de A4 — control del host —
>   la invalida, ver fronteras).

La formulación fuerte queda **refutada por la evidencia**, no descartada por
preferencia: en G-3 y v4 `verify` aceptó la cadena falsificada con `ok:true`.
Con `{verify}` como único mecanismo, H1c fuerte es falsa hoy — y no es un
bug pendiente sino una frontera estructural del content-addressing sin raíz
de confianza externa (ADR-0043 §A3: la verificación es tautológica respecto
de un atacante que puede reescribir el mundo completo que se verifica).

### Qué cubre y qué no la formulación débil

| Adversario (ADR-0043) | H1c débil-con-anclaje |
|---|---|
| A1 accidental / A2 inconsistente | detectado por `verify` solo (H1a/H1b) |
| A3 reescritura consistente | detectado **por la verificación activa del ancla** (el digest de `refs/` diverge del registro externo) |
| A3 + registro externo reescrito | fuera de esta formulación: la reescritura del historial remoto es ruidosa y detectable (protocolo anclajes/), pero la custodia del canal es decisión del dueño (corrección [e]) |
| A4 control del host | fuera de alcance por diseño (ADR-0031): el atacante falsifica la salida de la propia verificación |

### Condiciones de refutación de la formulación débil

La formulación se refuta si se ejecuta cualquiera de:

- **R-1:** una sesión correctamente operada (C1–C3 satisfechas) acepta una
  reescritura consistente — digest de `refs/` divergente del registro y la
  sesión continúa. Hoy el protocolo cumple fail-closed: divergencia = parada
  (`scripts/verificar_anclaje.py` exit 1).
- **R-2:** el digest de `refs/` es igual tras una mutación efectiva del
  contenido — colisión estructural sha256 del agregado (implícita e
  inalcanzable en la práctica; se declara por completitud).
- **R-3:** el registro de anclas pasa a residir en el mismo medio atacable
  que el store (C2 rota) sin que el protocolo lo detecte como incidente.

## Consecuencias

- **Positivas:** H1c queda evaluable como afirmación falsable con
  condiciones explícitas, coherente con la evidencia caracterizada (G-3, v4)
  y con el protocolo ya en operación. El análisis del mandato puede cerrar
  su fila PR-5/§7.5 con puntero aquí. La decisión deja de estar anticipada
  (corrección [a] ejecutada).
- **Negativas:** H1c ya no puede citarse como resistencia del verificador a
  secas: cada cita debe llevar la condicionalidad (C1)–(C3). La evaluación
  de un consumo que requiera resistencia a A3 sin poder garantizar C2/C3
  (p. ej. canal de anclaje en el mismo host) queda fuera.
- **Neutras:** el costo deliberado del protocolo se mantiene: un cambio
  legítimo de `refs/CURRENT` sin ancla previa también dispara la parada
  fail-closed.

## Mecánica de la verificación activa

El mecanismo ejecutable de C1 es `scripts/verificar_anclaje.py`, que corre
el comando EXACTO del protocolo sobre `refs/`:

```bash
find .an-kla/memory/refs -type f -exec shasum -a 256 {} + | sort -k2 | shasum -a 256
```

...compara el resultado contra el último ancla parseable del registro
(`docs/gobernanza/anclajes/2026-08-31-anclaje-inicial.md`, digest sha256 sin
backticks), y sale fail-closed: exit 0 match; exit 1 divergencia (mensaje
canónico + ambos sha256 en stderr, parada y escalamiento al dueño); exit 2
registro presente sin fila parseable; exit 3 store sin `refs/`; exit 4
registro ausente; exit ≥10 errores de uso/IO. El script nunca escribe el
store ni el registro, jamás "corrige" el ancla para coincidir, y opera por
defecto sobre el root del protocolo con overrides `--refs-root`/`--registry`
para pruebas sobre copias tmp.

**Anti-ronda-complaciente (heredado del análisis del mandato, §5):** el
veredicto A del programa de evaluación exige que la H1c débil aquí
formalizada sea atacada con al menos un ejercicio red-team fresco (tercer
contexto, sin participación del desarrollador) — este ADR no es esa
evidencia.

## Límites

- La formulación hereda los límites declarados del protocolo: protege
  `refs/` (la raíz de confianza); no evita objetos huérfanos fabricados sin
  tocar `CURRENT`, ni la falsificación de segmentos previos al primer
  export sellado (ADR-0042, fila export de la tabla ADR-0043).
- La dureza del canal de anclaje es hoy una convención [C] de assurance
  aprobada por el dueño junto con ADR-0043; su endurecimiento (medio,
  rotación, quién publica) es PENDIENTE-DE-DUEÑO.
- Este documento NO es un cambio de arquitectura del verificador: formaliza
  la hipótesis de evaluación. La enforcement de C1 en cada camino de
  consumo es trabajo de la línea de desarrollo si el dueño la ordena.

## Test de regresión

- `tests/test_verificar_anclaje.py` — cubre match → 0, divergencia → 1 con
  mensaje canónico, registro sin fila parseable → 2, registro ausente → 4,
  siempre sobre copias tmp (`--refs-root`/`--registry`), nunca sobre el
  store canónico.

## Referencias

- ADR-0043 (modelo de amenazas: A3, tripwires y v4), ADR-0031 (frontera de
  custodia), ADR-0022 (identidad de store), ADR-0042 (export sellado).
- Protocolo de anclaje: `docs/gobernanza/anclajes/2026-08-31-anclaje-inicial.md`.
- Análisis del mandato: `docs/analisis-mandato-orquestacion-2026-08-31.md`
  (§2.1 P-1, §4.1 PR-5, §5, correcciones [a] y [e]).
- Reporte de evidencia: `docs/planning/2026-08-31-g1-g3-reporte-rag.md`.
