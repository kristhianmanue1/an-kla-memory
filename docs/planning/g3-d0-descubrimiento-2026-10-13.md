# G3 · D0 — diseño de descubrimiento de stores (#134)

- **Tarea:** D0 del plan `docs/plans/2026-10-10-g3-discovery-agent-roadmap.md`.
- **Estado:** `partial`.
  - Comparación de alternativas, threat model y ADR propuesto: entregados
    (`docs/architecture/0050-descubrimiento-stores-v1.md`).
  - Censo nuevo: **no ejecutado** (ver §Censo).
  - Decisión de contrato: pendiente del maintainer.
- **Fecha:** 2026-10-13.
- **Ejecutor:** agente Claude Code (modelo efectivo `unknown`). **Revisión:**
  autorrevisión.

## Decisión tomada bajo delegación, y lo que no se decidió

El maintainer delegó las decisiones del plan al agente. Aun así, D0 exige
explícitamente «presentar decisión de contrato al maintainer antes de
schema/código», y D1 sólo procede «si el maintainer lo autoriza». Por eso el
ADR-0050 queda **Propuesta**: el agente recomienda el escaneo explícito de
sólo lectura, pero no lo acepta ni crea ningún registro.

## Censo

El censo pedido se hace en el Mac del maintainer, sobre las raíces que él
autorice. En esta sesión eso no es posible:

- el entorno de ejecución es un contenedor en la nube, sin los stores del
  maintainer;
- recorrer su filesystem exige una autorización de alcance que el maintainer
  no dio (y no está disponible para darla).

No se usaron los 25/4 de #134 como estado actual.

Método propuesto para cuando se autorice: sólo lectura, sin abrir secretos
y sin borrar.

1. **Raíces:** el maintainer nombra una lista explícita (p. ej. su directorio
   de proyectos). No se escanea `~` completo por defecto.
2. **Recorrido:** `os.walk(followlinks=False)` con profundidad máxima
   declarada. Se registran sólo:
   - la presencia de `.an-kla/`, `store-root.txt`, `project-identity.json`,
     `memory/identity.json` y `memory/refs/CURRENT`;
   - `verify` en un proceso de sólo lectura;
   - `store_identity` y `custody_fingerprint`;
   - tamaño agregado.
3. **Clasificación:** la de ADR-0050 §Decisión 3 (`active`,
   `external_bound`, `copy`, `moved`, `orphan_uncertain`, `unreadable`).
4. **Salidas:**
   - rutas crudas sólo en un archivo efímero privado, fuera del repo y no
     rastreado;
   - reporte compartible con fecha, raíces (saneadas), profundidad,
     denominador (directorios recorridos), conteo por clase y límites:
     alcance parcial, permisos y versiones de AN-KLA encontradas.
5. **Prohibido:** `init`, `adopt`, `repair`, borrar, mover o escribir en las
   raíces escaneadas.

## Siguiente acción

Pendiente del maintainer:
1. Aceptar, rechazar o enmendar ADR-0050.
2. Autorizar o no el censo, con sus raíces.

Si acepta, la implementación sigue los criterios de aceptación del ADR. D1
(índice orientativo) requiere una autorización separada.
