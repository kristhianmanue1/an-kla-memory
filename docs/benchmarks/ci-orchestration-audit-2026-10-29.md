# Auditoría crítica de orquestación CI — 2026-10-29

**Alcance:** inspección estática del CI local y sus tests de orquestación;
no se afirma perfilado exhaustivo de toda función del producto. Base:
`888299251fe269652ee2c28292fb9c2b67bc4ebf`, con diseño documental local.
El Operador pidió revisar y optimizar ciclos y funciones repetidos.

## Diagnóstico y prioridad

1. **Alta, ciclo de orquestación:** `ci_local.paso_tests` → discover →
   `Row15SuiteBothProfilesTests.test_ci_local_both_modes` → `ci_local` →
   discover. La guarda limita profundidad; no elimina la multiplicación.
   `paso_matriz` añade suites con su propia fila 15 cuando encuentra otro
   intérprete. Corrección: un orquestador exterior y trabajadores que no
   puedan invocar de nuevo una auditoría ni discover completo.
2. **Alta, repetición por entorno:** `MatrixReRunTests` reejecuta módulos
   que discover ya ejecuta, en cada padre/hijo. `_ROW_MODULES` deduplica
   dentro de una llamada; no deduplica contra la suite completa. Corrección:
   una ejecución funcional por celda exigida, con casos observados y
   trazabilidad por fila. Eliminar esos re-runs exige probar esa sustitución.
3. **Alta, obligación incompleta:** fila 15 exige CI sin/con extra; dos CI
   usan `sys.executable`, y discover CLT no equivale a CI completo con extra.
   La cobertura exigida debe mandar sobre el comportamiento actual.
4. **Media, duplicación adicional:** fila 11 relanza export/restore y
   compactación ya descubiertos. Mantener sus propios roundtrip y control
   negativo de imports; sustituir sólo el relanzamiento de suites por
   evidencia de ejecución en el perfil sin extra.
5. **Media, modos indistintos:** el hijo llamado normal hereda CI del padre.
   Fijar entornos explícitos; verificar sus valores desde procesos reales.
6. **Media, helpers copiados:** ambos archivos de matriz definen
   `_cryptography_importable`, `_clt_python`, `_make_store`, `FakeAdapterB64`
   y `_create_sealed`. Extraer helpers compartidos a un módulo de soporte
   sin prefijo `test_`, evitando imports entre módulos test y ciclos.
   Es una mejora de mantenimiento; no se atribuye a ella una ganancia de
   tiempo sin medir. Cada test conserva su fixture aislado y su limpieza.
7. **Media, lógica repetida del runner:** lanzamiento de subprocess, entorno,
   rc, logs y disponibilidad repartidos entre CI y tests. Una función común
   del runner debe ejecutar y registrar una celda; otra agrega resultados.
   Los tests del runner comprueban esa frontera con mocks y una integración
   real acotada. No convertir todos los CLI funcionales en mocks.
8. **Baja, documentación falsa de actualidad:** encabezado del CI/§5 de
   prácticas hablan de remoto multisistema; `test_ci_metadata` acredita la
   política local sin workflows. Corregir en la transición; este host no
   verifica otros SO por simular variables de CI.

## Plan concreto de optimización

El grafo objetivo es dirigido sin retorno: **entrada de auditoría → plan →
trabajador de celda → casos funcionales**, y **entrada → gates estructurales**.
Los tests de orquestación no llaman a la entrada completa. El trabajador no
incluye clases que relancen suites. Una integración del runner usa una suite
pequeña controlada, no la auditoría real dentro de unittest.

La identidad de celda incluye intérprete real/versionado, dependencias,
modo normal/simulado, plataforma y opciones relevantes. Resolver alias antes
de deduplicar: compartir versión no basta. No deduplicar perfiles con/sin
criptografía ni casos ejecutados frente a saltados. No reutilizar resultados
entre árboles ni auditorías. Si las obligaciones de dos tareas coinciden,
una ejecución puede acreditar ambas, con trazabilidad explícita.

La base propuesta de auditoría son ambas modalidades en ambos perfiles
sin/con extra: cuatro celdas, combinando la suite completa y el CI de la
misma celda en una sola ejecución. Agregar intérpretes de compatibilidad
disponibles sin duplicar una celda ya cubierta. G-3 y gates se planifican
fuera del discover. Tras el refinamiento pedido por el Operador, ADR-0062
consolida estructura por firma de entradas en el intérprete principal y
distingue G-3/import por entorno efectivo, sujetos a prueba de equivalencia.
No se replica ambos modos en cada versión de compatibilidad automáticamente:
se conserva el modo directo previo y cualquier obligación distinta observada
en los hijos antiguos debe tener sustituto trazable. La ampliación de matriz
es una decisión separada. No se reduce G-3 a una llamada por simple nombre.

No se pretende «ninguna función repetida»: loops de estrés, reintentos CAS
esperados, fallos inyectados, procesos CLI aislados y fixtures por test pueden
ser necesarios. Se retira trabajo sin obligación distinta, no repetición
que constituye la prueba. Tampoco se paraleliza como primera medida: ocultaría
duplicación y podría introducir contención en filesystem y pruebas de carrera.

## Evidencia y aceptación

El [inventario reproducible](evidence/ci-orchestration-20261029/inventory.json)
registra hashes de fuentes y helpers idénticos por AST. Su
[generador](evidence/ci-orchestration-20261029/inventory.py) no importa ni
ejecuta tests. Es evidencia estática acotada: AST igual no demuestra que dos
ejecuciones sean intercambiables ni encuentra todas las llamadas dinámicas.
Las búsquedas de `subprocess`/`discover` se contrastaron con lectura de las
clases nombradas. No hay medida nueva de tiempos del CI optimizado: aún no
está implementado. El CI anterior de A/B tardó 1493,463 s en su discover;
no se promete un porcentaje ni un tiempo objetivo sin comparación controlada.

La [propuesta de perfiles](../planning/ci-profiles-design-2026-10-29.md)
exige inventario de casos/entornos, pruebas de fallos, skips, timeouts y
equivalencia de obligaciones. Añadir como aceptación verificable:

- ninguna arista ejecutada trabajador→auditoría ni suite→discover completo;
- ninguna celda idéntica duplicada dentro del mismo plan;
- cada ejecución retirada enlazada a casos efectivos en una celda sustituta;
- no más de un relanzamiento de la misma suite por celda funcional, excluyendo
  repeticiones intencionales identificadas y justificadas como casos;
- informe de tiempo por celda/proceso, sin sumar doble tiempos anidados;
- fallo de cualquier obligación exigida produce rc distinto de cero.

El refinamiento añade límites de tarea/globales registrados antes de arrancar,
contención y cierre del árbol de procesos y evidencia incremental. Los
presupuestos son propuestos, sin medir aún el runner nuevo. La
[sonda estructural](evidence/ci-orchestration-20261029/gate-environment-probe.json)
comparó los tres gates con control positivo de CI/GITHUB_ACTIONS: resultados
idénticos en el mismo árbol/intérprete. No prueba portabilidad ni equivalencia
de G-3; la ADR exige evidencia adicional donde corresponda.

No se cambia el CI aquí. La optimización se implementará después de aceptar
y fusionar ADR-0062 y pasar sus verificaciones. El criterio de 20.000
revisiones sigue pospuesto por espacio y no forma parte de este CI.
