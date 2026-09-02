# 04 — Ejecución y verificación (F3)

> **Propósito:** implementar sobre el cascarón sin romperlo, y demostrar con
> evidencia que el trabajo está hecho. Rige también para trabajo continuo en
> proyectos existentes.

## 1. Contrato de tarea

Antes de tocar código, fija la tarea en curso:

```text
TAREA <id>
Objetivo: <un solo resultado, cubre SPEC-<n> o REQ-<n>>
Clase: <Spike | Bounded | Architectural> — según los disparadores de 01 §2
Base: <commit o rama de partida>
Plan: <ruta del plan de implementación, sólo si existe — ver abajo>
Permitido: <archivos/operaciones concretas>
Prohibido: <lo que no se toca; por defecto: push, merge, release, deps nuevas>
DoD: <checks ejecutables — o "ver PLAN <ruta>" si la tarea pertenece a un plan>
Parada: <condición inequívoca para detenerse>
```

Reglas:

- Una tarea = un objetivo. Si aparece un segundo objetivo, es otra tarea.
- La clase sale de los disparadores observables de `01` §2 (ADR-009), no de
  un calificativo. Si a mitad de tarea se descubre complejidad, la clase
  sube — ratchet — y la TAREA se re-fija antes de seguir.
- Si la tarea es parte de un plan de implementación (ADR-010), la TAREA lo
  referencia y **el plan es dueño de los criterios** (DoD, steps): nunca dos
  documentos con criterios de aceptación paralelos. Una tarea sola no lleva
  plan; el plan existe sólo a partir de trabajo multi-tarea.
- Lo no listado en "Permitido" está prohibido. La autoridad se concede por
  operación: editar no implica commit; commit no implica push.
- La condición de parada es obligatoria aunque parezca obvia: es lo que te
  impide seguir "mejorando" más allá del alcance.

## 2. Implementación

- Código nuevo indistinguible en estilo del código vecino: mismas
  convenciones, misma densidad de comentarios, mismos idiomas del proyecto.
- Diff mínimo: ni limpiezas oportunistas ni refactors colados. Si ves algo
  mejorable fuera de alcance, anótalo como hallazgo y sigue.
- Sin placeholders: cada cambio se entrega completo. `// resto igual`,
  funciones vacías y `TODO` sin dueño son entrega a medias.
- No uses una librería por famosa: confirma que el proyecto ya depende de
  ella (manifiesto/imports) o justifica su adición como decisión — ADR si
  cumple el criterio de `02-specs-adr-contratos.md` §3.1.
- Comentarios y docstrings describen el comportamiento actual. Si cambias
  comportamiento, actualiza lo que lo describe; un comentario obsoleto es un
  bug de documentación.

## 3. Tests

- Los casos DADO/CUANDO/ENTONCES de las specs se convierten en tests. Esa es
  la trazabilidad: SPEC → test → evidencia.
- Si el proyecto tiene infraestructura de tests, todo cambio de comportamiento
  sigue RED-GREEN-REFACTOR (ADR-011): (1) RED — escribe primero el test que
  falla y verifica que falla por la razón correcta; (2) GREEN — el código
  mínimo que lo pasa; (3) REFACTOR — limpieza con la suite en verde. El
  reporte de la tarea incluye la **salida del RED** como evidencia: si no
  viste fallar el test, no sabes si prueba lo correcto. La regla hereda la
  condicionalidad del estándar §3.2 — aplicar donde exista infraestructura
  de tests; crearla para un cambio acotado es decisión del contrato de tarea,
  no obligación silenciosa. Excepciones declaradas en la TAREA: throwaway
  (Spike), código generado, configuración.
- Un bug se corrige con un test que falla antes del fix y pasa después.
- Ejecuta primero los tests focales del cambio, después la suite. Ambos
  resultados entran en la evidencia.
- Test rojo = trabajo no terminado. Nunca deshabilites un test para cerrar
  una tarea sin decisión explícita del humano.

## 4. Verificación antes de declarar "hecho"

"Hecho" es una propiedad verificada, no declarada. Secuencia mínima:

1. tests focales en verde;
2. suite completa en verde;
3. diff leído completo, línea a línea, por ti: sin restos de depuración,
   sin cambios fuera de alcance, sin secretos;
4. `git status --short` y `git diff --check` coherentes con la tarea;
5. comentarios/docs actualizados al nuevo comportamiento;
6. DoD de la tarea cumplido punto por punto.

Si un paso no queda `pass`, deriva el estado como indica `00-INDICE.md`
§ «Formato de reporte de fase»; nunca declares `OK`.

## 5. Ronda adversarial (obligatoria antes de cerrar)

Después de tu propia verificación (§4) y antes de reportar "hecho", ataca tu
trabajo como si fuera de otro. Una ronda adversarial no es releer el diff con
actitud positiva: es intentar demostrar que está mal.

### 5.1 Cómo se ejecuta

- **Contexto fresco.** Si tu entorno lo permite, usa un subagente o sesión de
  revisión nueva; idealmente otro modelo. Si no, simula la frescura: revisa
  sólo el diff y las specs, sin apoyarte en tu memoria de lo que "querías"
  hacer.
- **Ataca lo que rompe, no el estilo:** invariantes violados, errores
  silenciados, casos edge sin cubrir, contratos incumplidos byte a byte,
  compatibilidad rota, recursos sin liberar, entrada no confiable sin
  validar, tests que pasan pero no prueban el requisito.
- **Prohibido:** una ronda que sólo elogia o comenta estilo no cuenta como
  adversarial.

### 5.2 Formato del reporte

```text
## Hallazgos
- [BLOCKER] <problema> — <evidencia> — <corrección requerida>
- [HIGH]    <problema> — <evidencia> — <corrección requerida>
- [MED]     <problema> — <evidencia> — <corrección sugerida>
- [LOW]     <problema> — <evidencia> — <seguimiento opcional>

## Verificaciones
- <comando> → <resultado real> [pass | fail | inconclusive]

## Decisión
proceed | fix-and-retry | escalate
```

### 5.3 Reglas de cierre

- `BLOCKER` y `HIGH` se corrigen siempre antes de entregar. `MED` se corrige
  o se justifica por escrito. `LOW` puede quedar como seguimiento.
- Tras corregir un hallazgo, repite los checks afectados y la ronda si el
  cambio fue material — mismos disparadores de abajo. El ciclo termina en
  `proceed` o `escalate`, nunca en "ya está bien".
- `escalate` cuando el hallazgo exige decisión del humano o salir del
  alcance: no lo resuelvas improvisando autoridad.
- **Disparadores objetivos de rigor.** "Material" en esta guía y en
  `AGENTS.md` significa **cualquiera** de estas condiciones, nunca una
  sensación de "cotidiano vs crítico" (procedencia:
  `docs/history/piloto-skopos.md` F3 — ese criterio subjetivo se aplicó
  mal cuatro veces seguidas sobre el mismo tipo de componente, cerrando
  como `OK` una inyección de prompt explotable y una condición de carrera
  real; ADR-008):
  1. el componente persiste datos de un usuario real o de terceros;
  2. el componente consume salida de un LLM y actúa sobre ella (la
     persiste, la ejecuta, la reenvía) sin revisión humana intermedia;
  3. el componente puede ejecutarse con concurrencia (dos instancias, dos
     procesos, una reentrada);
  4. el componente expone una interfaz a un consumidor no controlado por
     el mismo autor.

  Si alguna aplica, el contexto fresco real (subagente o sesión nueva,
  preferiblemente otro modelo) es obligatorio en vez de una ronda propia. Si
  ninguna aplica, una ronda propia honesta basta.

### 5.4 Cómo se ve una ronda que sí cuenta

Rasgos de un reporte adversarial válido, para que compares el tuyo:

- **Los hallazgos son ejecutables, no estilísticos.** Ejemplo real de una
  ronda sobre un protocolo de orquestación: *"la corrección se envía a un
  proceso one-shot que ya terminó, así que el shell interpreta el texto como
  comando"* — un `BLOCKER` que rompe el ciclo completo. Compáralo con
  *"faltan comentarios"*, que no es un hallazgo adversarial.
- **Cada hallazgo lleva cuatro campos:** problema, impacto, corrección
  aplicada y estado (`cerrado` / `abierto` / `aceptado como riesgo`). Un
  hallazgo sin impacto declarado no permite priorizar.
- **La evidencia es de comandos, no de lectura.** Versiones reales de las
  herramientas, salidas observadas, la prueba concreta que demuestra que la
  corrección funciona. En esa misma ronda, el fallo *"el prompt se inyectó
  antes de que la interfaz estuviera lista"* sólo se detectó al ejecutar el
  flujo dos veces; ninguna relectura lo habría encontrado.
- **Los riesgos residuales se enumeran y se aceptan explícitamente,** en vez
  de silenciarse. Aceptar un riesgo con nombre es una decisión; omitirlo es
  una omisión.
- **La decisión final es una de las tres palabras**, y viene después de
  repetir los checks afectados.

Si en este repositorio existe una ronda previa, úsala como molde de formato,
nunca como fuente de conclusiones: los hallazgos de otra ronda son historia
de otro cambio, no verificación del tuyo.

## 6. Reporte de evidencia

Al cerrar una tarea, reporta así:

```text
TAREA <id>: <OK | PARCIAL | BLOQ>
DoD: <cumplido / qué falta>
RED: <salida del test en rojo — o por qué no aplica (ADR-011)>
Rama de este cierre: <nombre> | main (si main, justifícalo — ver §4.1
  del estándar: "sin remoto" no es justificación válida por sí sola)
Evidencia:
- <comando> → <resultado real> [pass | fail | inconclusive]
Hallazgos fuera de alcance: <lista o "ninguno">
```

- La evidencia son comandos ejecutados y sus resultados reales. "Debería
  pasar" y "lo he revisado mentalmente" no son evidencia. Cada línea marca su
  resultado como define `00-INDICE.md` § «Formato de reporte de fase».
- Si el formato del reporte importa, cúmplelo exactamente: el cumplimiento
  semántico no equivale al cumplimiento exacto.
- Reporta `fail` e `inconclusive` con la misma precisión que `pass`. Un `BLOQ`
  honesto vale más que un `OK` inflado: el humano decide sobre datos reales.

## 7. Operaciones con autoridad separada

Requieren autorización explícita del humano, una por una, cada vez: push,
force-push, merge, rebase de historia compartida, reset destructivo,
borrado de ramas remotas, tags, releases, publicación, instalación de
dependencias nuevas en el entorno, cualquier comando destructivo. La
autorización de una tarea anterior no se hereda.

Ante un estado inesperado de Git (commit, rama o push que tú no hiciste):
detente, audita (`reflog`, remoto) y reporta. No destruyas trabajo ajeno
para "dejarlo limpio".

## 8. Cuándo detenerte y preguntar

- el requisito resultó ambiguo y la respuesta cambia el diseño;
- la tarea exige salir del alcance permitido;
- evidencia contradictoria: el entorno no coincide con lo que F0 registró;
- falta un permiso o una dependencia;
- llevas dos intentos fallidos en el mismo problema: el tercero empieza con
  un diagnóstico escrito, no con otro intento ciego.

## 9. Gate de F3 (por tarea)

- [ ] contrato de tarea fijado y respetado;
- [ ] tests focales y suite en verde, con evidencia;
- [ ] salida del RED reportada, o su no-aplicación justificada (ADR-011);
- [ ] diff mínimo, leído completo, sin sorpresas;
- [ ] docs y comentarios coherentes con el código;
- [ ] si la tarea toca un componente con CONTRATO (02 §4), cada campo de
      entrada/salida declarado existe literalmente en la firma o esquema
      real del código — verificado leyendo o grepeando el código ahora,
      no de memoria de cuando se escribió el contrato (procedencia:
      `docs/history/piloto-skopos.md` F5 — un contrato prometió una
      interfaz nunca implementada y nada lo detectó hasta una ronda
      adversarial ajena);
- [ ] ronda adversarial ejecutada con decisión `proceed` o `escalate`;
- [ ] reporte de evidencia emitido con estado real;
- [ ] cero operaciones de autoridad separada sin autorización.
