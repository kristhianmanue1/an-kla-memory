# 03 — Cascarón de proyecto (F2)

> **Propósito:** crear la estructura inicial mínima y verificable del
> proyecto. Entrada: specs y contratos de F1. Regla madre: el cascarón más
> pequeño que compile, corra y pase su propio verificador. Todo lo demás es
> deuda inventada.

## 1. Principios del cascarón

1. **Mínimo que funciona.** Un cascarón no anticipa la arquitectura final:
   materializa las fronteras decididas en F1 y nada más.
2. **Verificable desde el primer minuto.** El cascarón incluye cómo se
   construye, cómo se corre y cómo se prueba, y los tres comandos pasan
   antes de dar F2 por cerrada.
3. **Cero placeholders vacíos.** Nada de carpetas vacías "por si acaso",
   archivos con `TODO` masivos ni módulos stub sin propósito actual.
4. **Cero dependencias especulativas.** Cada dependencia del cascarón
   responde a un REQ o a una restricción de F0. Confirma su disponibilidad
   real en el entorno (versión incluida) antes de declararla.

## 2. Estructura base

Adapta al ecosistema real del proyecto; no copies una plantilla ajena sin
que cada pieza tenga justificación. El mínimo transversal:

```text
<nombre>/
├── README.md            # qué es, cómo se construye, cómo se corre, cómo se prueba
├── LICENSE              # si el proyecto se publica; preguntar si no está claro
├── .gitignore           # dependencias, builds, secretos, archivos de editor
├── <manifiesto>         # package.json / pyproject.toml / go.mod / Cargo.toml ...
├── src/ o equivalente   # código, organizado por las fronteras de F1
├── tests/ o equivalente # al menos un test real que pasa
└── docs/                # specs, ADRs, contratos (si el tamaño lo justifica)
```

Reglas:

- El `README.md` es el contrato de arranque: un extraño (humano o agente)
  debe poder construir y probar el proyecto leyendo sólo ese archivo.
  Escríbelo con los comandos reales que ejecutaste, no con los que crees
  que funcionan.
- `.gitignore` completo **antes del primer commit**. Un secreto o un build
  en el historial exige revocación y limpieza, no un commit de arreglo.
- Si F1 produjo specs/ADRs/contratos, viven en `docs/` con nombres
  estables: `docs/specs/`, `docs/adr/ADR-001-<titulo>.md`. Los planes de
  implementación multi-tarea (ADR-010) viven en `docs/plans/`.
- Si el proyecto recibirá trabajo de agentes, añade `AGENTS.md` (y `CLAUDE.md`
  si la herramienta lo usa) en raíz con: comandos de build/test,
  convenciones, y lo que está prohibido. Manténlo actualizado cuando cambie
  cualquiera de esas cosas. Si el archivo no existía, créalo con el bloque
  de registro delimitado hacia `.skevi/` en vez de desarrollar el contexto
  en línea (`../estandar-diseno-software-github.md` §3.5) — copia
  `../../templates/registro-contexto.md` y `../../templates/skevi/*` y
  llena los `<...>`, no reinventes el formato.

## 3. Decisiones de cascarón

Decide explícitamente y registra en el README o en un ADR:

- **Gestor de paquetes y lockfile:** el del ecosistema del proyecto, uno
  solo, con lockfile comprometido.
- **Versión del runtime:** fijada en el manifiesto o archivo de versión;
  verificada contra el entorno real.
- **Linter/formateador:** sólo si el proyecto durará más de una sesión;
  configuración por defecto del ecosistema, no una custom.
- **CI:** sólo cuando haya tests que ejecutar y un remoto que los corra. Un
  pipeline que siempre está en verde porque no comprueba nada es peor que
  no tener pipeline.
- **Estructura de módulos:** la mínima que refleje los contratos de F1. Una
  frontera por contrato; ni más capas ni más carpetas.

## 4. Primer commit y ramas

Sigue la capa normativa (`../estandar-diseno-software-github.md` §4):

- rama de trabajo, nunca directo a la principal;
- primer commit: cascarón completo y verificable, mensaje tipo
  `chore: cascarón inicial del proyecto`;
- no crear remoto, push, tags ni releases sin autorización explícita.

## 5. Verificación del cascarón (obligatoria)

Ejecuta y registra como evidencia:

1. **Construcción:** el comando de build/instalación termina con exit 0.
2. **Ejecución:** el punto de entrada corre (aunque sólo imprima su versión
   o un hola-mundo honesto).
3. **Prueba:** el runner de tests ejecuta al menos un test real y pasa.
4. **Limpieza:** `git status --short` muestra sólo lo que decidiste crear;
   `git diff --check` limpio.

Si alguno falla, F2 no está cerrada. No declares el cascarón "listo para
implementar" sin estos cuatro resultados reales.

## 6. Tamaño de archivos en el cascarón

La norma completa —límites, exenciones, qué hacer al exceder y requisitos
del verificador— está en la capa transversal
(`../estandar-diseno-software-github.md` §3.4) y rige en todas las fases,
también sobre los documentos que generaste en F0 y F1.

Lo que corresponde hacer en F2:

- fija los límites del proyecto por escrito (o hereda los del estándar
  declarándolo) en el README o en `AGENTS.md`;
- si el proyecto durará más de una sesión, incluye el gate de estructura y
  tamaños en el cascarón y conéctalo al comando de verificación local;
- ejecútalo antes de cerrar la fase y registra su salida como evidencia.

## 7. Anti-patrones prohibidos en F2

- Generadores de plantilla que crean 40 archivos donde 8 bastan.
- Configuración para features no requeridas (docker, monorepo, multi-env)
  sin REQ que las pida.
- Tests triviales que no prueban nada (`assertTrue(true)`).
- README genérico con badges y sin comandos reales.
- Dependencias "populares" no confirmadas en el entorno.
- Estructura copiada de otro proyecto sin justificar cada pieza.

## 8. Gate de F2

- [ ] estructura mínima creada, cada pieza con justificación;
- [ ] build, ejecución y test verificados con evidencia real;
- [ ] README con comandos reales de build/run/test;
- [ ] `.gitignore` completo antes del primer commit;
- [ ] specs/ADRs/contratos de F1 en `docs/` si aplica;
- [ ] `AGENTS.md`/`CLAUDE.md` si el proyecto recibirá agentes, con el
      bloque de registro hacia `.skevi/` si se crearon en esta fase;
- [ ] ningún archivo de texto excede su límite, o la exención está escrita;
- [ ] cero placeholders, cero dependencias especulativas.

Cierra con el bloque de reporte de fase de `00-INDICE.md`.
