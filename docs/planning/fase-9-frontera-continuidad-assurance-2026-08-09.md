# Fase 9 — nota de frontera: continuidad, assurance y aceptación

- **Estado:** insumo de diseño; no adoptado y sin autorización de implementación.
- **Fecha:** 2026-08-09
- **Origen:** caso especial aportado por el maintainer después de la ronda fresca
  de ADR-0030, para no contaminar su independencia.
- **Pregunta:** cómo preservar contexto de forma agresiva sin convertir AN-KLA
  en burocracia bloqueante ni rebajar controles donde la memoria sí soporta
  decisiones de alto impacto.

## Por qué esta nota no resuelve todavía ADR-0030

La ronda fresca evaluó correctamente el diseño que recibió y terminó
`ESCALATE`. El caso especial no invalida sus hallazgos: demuestra que la
propuesta mezcló dos problemas distintos y aplicó una obligación universal a
proyectos y operaciones con riesgos diferentes.

Esta nota conserva una hipótesis posterior a la ronda. No constituye
consentimiento, perfil activo, cambio de template, reserva de release ni
autorización para implementar.

## Evidencia comparativa observada

### `expertoGobernanza`

El proyecto trabaja con corpus normativo mexicano, vigencia, citas, borradores
con posible efecto institucional, roles jurídicos y enrutamiento de contenido a
proveedores. Su política exige fuente oficial, distingue redacción de
promulgación, prohíbe nivel alto sin corpus temporal y restringe datos
personales/confidenciales.

En ese dominio, perder contexto puede reintroducir una fuente derogada,
confundir borrador con decisión o ignorar una refutación. La continuidad es
crítica y puede ser frecuente. Sin embargo, una prueba unitaria o un refactor
reversible no necesita el mismo quórum que una afirmación jurídica.

Evidencia local read-only del 2026-08-09:

- `AGENTS.md`: 140 líneas; bloque gestionado AN-KLA beta.6;
- `AN-KLA.md`: 255 líneas; `docs/politica-agentes.md`: 586 líneas;
- worktree limpio en `main` `264b15b`;
- política §§6–10: adversarial por hito, fidelidad jurídica, datos, roles y ADR.

### `adrc-python`

Es un framework de desarrollo y orquestación con CMF/SQLite, ChromaDB y Mem0,
gates de lanzamiento, consenso y múltiples artefactos operacionales. Requiere
rigor para seguridad, identidad, migraciones, releases y cambios de memoria
canónica; aplicarlo a cada refactor o test corta innecesariamente el avance.

El snapshot local no demuestra causalidad, pero sí costo operacional que debe
considerarse: 7,511 archivos rastreados, 136,858 archivos bajo `.adrc/`, 5.7 GB
en ese árbol y 456 entradas en `git status --porcelain`. Acumular gobernanza y
memoria también puede producir deriva, navegación costosa y presión de
contexto.

## Hipótesis corregida: dos ejes, no un perfil único

Un perfil único `manual|balanced|strict` mezcla frecuencia de continuidad con
fuerza de evidencia. La candidata revisada los separa:

| Eje | Valores candidatos | Pregunta |
|---|---|---|
| Continuidad | `manual`, `milestone`, `continuous` | ¿Cuándo se evalúa o guarda working state? |
| Assurance | `standard`, `high`, `regulated` | ¿Qué procedencia, revisión y autorización exige una operación? |

La política se aplica por **operación/stream/efecto**, no sólo por nombre de
proyecto. AN-KLA no infiere riesgo leyendo texto ni acepta que memoria
recuperada seleccione o rebaje el perfil.

### Aplicación candidata

| Superficie | Comportamiento candidato |
|---|---|
| `working_state` saneado | automático según continuidad; `model_derived`; error visible pero no bloqueante |
| facts/events/episodes | flujo gobernado actual y assurance asignado al dominio |
| corpus, vigencia o afirmación jurídica | `regulated`; fuente y autoridad externas verificables |
| refactor/test reversible | `standard`; tests locales, sin consentimiento repetido |
| identidad, autorización, migración destructiva, release | `high|regulated`; fail-closed y aprobación de alcance exacto |
| Git, red o publicación | nunca autorizados por el perfil de checkpoint |

Configuraciones ilustrativas, no defaults:

- `expertoGobernanza`: continuidad `milestone|continuous`; assurance
  `regulated` para corpus/afirmaciones/datos/despliegue y `standard` para código
  interno reversible.
- `adrc-python`: continuidad `continuous`; assurance `standard` para desarrollo
  ordinario y `high|regulated` sólo en seguridad, CMF, identidad, migraciones y
  releases.

## Frontera de bloqueo

Principio candidato:

> AN-KLA preserva contexto agresivamente, atribuye verdad conservadoramente y
> bloquea excepcionalmente.

Fallar al guardar continuidad no bloquea el trabajo primario en `standard`: se
reporta `checkpoint_pending`. Sólo una acción declarada crítica por política
vigente puede usar fail-closed. Un proyecto no puede degradar invariantes del
motor ni transformar memoria en autoridad.

## Aceptación del usuario: alternativas aún abiertas

La presencia o hash de un template no prueba consentimiento. Tampoco existe un
mecanismo universal que demuestre que detrás de un CLI había una persona y no
el propio agente. La semántica debe ser honesta y graduada.

### A — activación local explícita

Un flujo interactivo crea un recibo local ligado a `project_uuid`, `store_uuid`,
digest de policy/template, alcance y versión. Es revocable y adecuado sólo para
checkpoint local saneado de bajo impacto. Demuestra `operator_activated`, no
identidad humana criptográfica.

### B — capability opaca del host

El host confirma una vez el alcance y entrega un handle no serializable. Permite
`channel_confirmed` real mientras el adapter esté activo. Es la candidata para
`high`, pero depende de integración específica con cada host.

### C — aceptación firmada o externa

Firma, WebAuthn o policy administrada fuera del proceso liga identidad, alcance,
expiración y revocación. Es apropiada para `regulated`, pero su costo no debe
imponerse al checkpoint ordinario.

Reglas comunes candidatas:

1. upgrades existentes conservan comportamiento; no activan automatismo;
2. plan/inspect son read-only y preceden aceptación;
3. la aceptación es local, explícita, limitada y revocable;
4. no se vuelve a solicitar mientras scope, identidad y policy permanezcan;
5. cambio de scope, elevación de assurance o acción externa exige nueva
   aceptación exacta;
6. `status` muestra quién/qué mecanismo activó el perfil sin sobreafirmar
   identidad;
7. memoria, template clonado y JSON del caller no crean aceptación;
8. revocar detiene futuras mutaciones, sin borrar historial.

## Gate de oportunidad: ahora o versión futura

Antes de decidir implementación se requiere evidencia sobre:

- frecuencia real de checkpoints obsoletos y trabajo repetido;
- tasa de reanudación correcta con y sin checkpoint;
- tamaño/tokens del working state y falsos triggers;
- latencia e intervenciones humanas por hito;
- capacidad de un sanitizer para producir un subconjunto pequeño y seguro;
- disponibilidad real de adapters de host;
- comprensión de los perfiles por usuarios nuevos y migrados.

### Integrar ahora sólo si

1. el spoof de autoridad está corregido por separado;
2. existe `checkpoint-auto-safe/v1` con allowlists y límites ejecutables;
3. upgrades quedan en manual y no cambian comportamiento silenciosamente;
4. la aceptación local puede inspeccionarse y revocarse;
5. un MVP evita `git/v1`, checkpoint-v3 y hooks obligatorios;
6. pruebas de `expertoGobernanza` y `adrc-python` muestran menos pérdida de
   contexto sin falsos bloqueos relevantes.

### Diferir si

- el valor depende de observer Git, v3 o integración de host todavía ausente;
- no hay evidencia de que el checkpoint automático mejore reanudación;
- el sanitizer no puede limitar contenido libre con seguridad;
- el mecanismo de aceptación introduce prompts repetidos o claims de identidad
  que el sistema no puede probar.

## Secuencia de análisis propuesta

1. Mantener ADR-0030 en `Propuesta` y F9.1 sin iniciar.
2. Tratar el spoof `channel_confirmed` como hotfix independiente de seguridad.
3. Congelar una matriz de riesgo por operación/stream con fixtures de los dos
   proyectos, sin código de automatismo.
4. Prototipar en papel A/B/C y sus threat models; no elegir todavía.
5. Diseñar el sanitizer y métricas antes del evaluador.
6. Decidir `integrar ahora | experimento opt-in | diferir` mediante ADR-0030
   revisado y aceptación explícita del maintainer.
7. Sólo después ejecutar nueva ronda fresca pre-code.

## Decisiones abiertas

- defaults de continuidad y assurance para instalaciones nuevas;
- si la activación A es suficiente para mutación local de bajo impacto;
- formato, ubicación y duración del recibo local;
- cómo un host entrega y revoca B;
- qué dominios justifican C;
- si el primer producto debe ser sólo evaluator/sanitizer read-only;
- versión objetivo o decisión de diferimiento.
