# ADR-0011: actualización gobernada para agentes

## Estado

Aceptada para `v0.1.0-beta.3`.

## Contexto

La actualización de AN-KLA tiene dos superficies distintas: distribución del
paquete e integración del contexto en un proyecto. Un comando que ejecute el
gestor de paquetes desde el mismo proceso no puede garantizar rollback atómico,
procedencia del artefacto ni continuidad del intérprete que se reemplaza.

La integración de contexto sí dispone de planificación no mutante, hashes, CAS,
lock local, respaldos content-addressed y reemplazo atómico. Esas primitivas
deben componerse, no duplicarse.

## Decisión

Se adopta `project-context-upgrade/v1` con tres operaciones:

- `inspect`: exige una etiqueta exacta correspondiente a la versión instalada y
  produce `an-kla/upgrade-plan-v1` sin escribir;
- `apply`: recibe el plan y su fingerprint por canales separados, reconstruye
  el estado bajo lock y aplica el plan exacto de contexto;
- `verify`: comprueba versión e integración y verifica memoria sólo si existe.

El núcleo del plan contiene el hash canónico del plan de contexto y su
fingerprint se calcula sobre ese núcleo. La salida CLI es JSON canónico.

El paquete declara `package_action=already_installed`. AN-KLA no ejecuta el
gestor externo, no resuelve una versión móvil y no presenta la memoria como
autoridad para elegir la etiqueta.

## Consecuencias

Los agentes obtienen una transición inspeccionable y resistente a deriva sin
debilitar la propiedad de los archivos del proyecto. La actualización completa
continúa teniendo dos fases, porque sólo el gestor del entorno puede instalar o
revertir el paquete.

No existe rollback automático de instrucciones. Los respaldos se preservan para
revisión explícita. El flujo tampoco añade coordinación multi-máquina.
