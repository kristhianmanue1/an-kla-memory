# ADR-0035: adoptar explícitamente la baseline project-owned de `AGENTS.md`

- **Estado:** Propuesta
- **Implementación:** No iniciada
- **Fecha:** 2026-08-12
- **Decide sobre:** la arquitectura y secuencia para reconocer cambios
  intencionales fuera del bloque sin debilitar el drift del archivo completo;
  el contrato observable exacto se difiere a un spike y ADR sucesor

## Contexto

AN-KLA administra un único bloque delimitado dentro del `AGENTS.md` raíz. El
resto del archivo pertenece al proyecto y puede enlazar `CONTRIBUTING.md`, ADRs,
comandos o convenciones locales. El manifiesto conserva `target_sha256` sobre
el archivo completo; por eso cualquier edición project-owned posterior a la
instalación produce `context_target_changed_outside_managed_block` y un upgrade
exige confirmar su absorción conforme a ADR-0017.

El warning es correcto para un cambio no reconocido, pero hoy falta una
operación cuyo significado sea “revisé estos bytes project-owned y los adopto
como nueva baseline”. Un smoke sobre beta.13 confirmó que `context update`
termina absorbiéndolos: el plan devuelve `action=noop`, reescribe el manifiesto
y el warning desaparece. Esa ruta no declara la adopción y mezcla dos
intenciones distintas: actualizar el template gestionado y aceptar contenido
local.

Evidencia del smoke aislado (proyecto temporal nuevo, beta.13):

```text
context install
→ result.action=create
editar fuera del bloque; context status
→ ok=true; warnings=[context_target_changed_outside_managed_block]
context update
→ plan.action=noop; result.action=noop
context status
→ ok=true; warnings=[]
```

El código explica el resultado: `transform_document()` devuelve `noop` para un
bloque canónico; el fast-path no aplica mientras manifest/target difieren; la
ruta general vuelve a escribir target y manifiesto con el hash observado. No hay
test vigente que cubra toda la transición before→after; el spike debe añadir el
repro comando→resultado y diseñar el fixture. La implementación debe añadir el
test automatizado antes de modificar comportamiento.

Restricciones:

- el bloque gestionado y `AN-KLA.md` conservan propiedad, hashes y flujo
  versionado actuales;
- la memoria y las rutas recuperadas siguen siendo datos no confiables;
- el host decide si el contenido project-owned de `AGENTS.md` es instrucción;
  adoptar su baseline no lo interpreta ni cambia su autoridad;
- una adopción no debe ocultar cambios concurrentes ni reparar bytes;
- el parser sigue reconociendo un solo bloque gestionado;
- no se cambia almacenamiento de memoria ni formato de revisiones.

## Decisión

**Conservar el hash del `AGENTS.md` completo y diseñar una operación explícita
plan→commit que adopte únicamente su estado observado como nueva baseline del
manifiesto. Secuenciar obligatoriamente spike → ADR de contrato →
implementación; este ADR no autoriza código.**

### 1. Propiedad y significado

Los bytes fuera del bloque son `project-owned`; AN-KLA los preserva pero no los
interpreta, valida ni ejecuta. La adopción afirma únicamente que el operador
acepta su digest observado como baseline para detectar cambios posteriores. No
certifica que enlaces existan ni que el texto sea seguro. La autoridad de sus
instrucciones, si el host las reconoce como tales, es independiente de AN-KLA y
no aumenta ni disminuye al adoptar la baseline.

El bloque gestionado debe seguir siendo canónico para la versión instalada. Si
su estructura, metadata o payload difieren, la operación falla cerrado; adoptar
contenido project-owned nunca blanquea `managed_block_modified` ni
`managed_block_structure_invalid`.

Antes de planificar o confirmar, todos los campos no-target verificables del
manifiesto deben concordar semánticamente con el estado observado: como mínimo
`managed_content_sha256` con el payload del bloque, `contract_sha256` con los
bytes de `AN-KLA.md` y `template_version` con la metadata del bloque y la
versión instalada. Un hash bien formado pero falso es corrupción, no drift
adoptable; produce error estable y cero mutación. Ownership y backup conservan
además sus validaciones estructurales y de path actuales.

### 2. Plan read-only

El spike debe proponer una superficie versionada y el ADR de contrato sucesor
debe congelar antes del código: nombre CLI, schemas exactos, tipos, códigos,
exits, forma noop, fingerprint y compatibilidad. Como inputs mínimos del diseño
debe evaluar:

- schema y operation específicos de adopción de baseline;
- target exacto `AGENTS.md` y versión de template observada;
- `base_manifest_sha256`;
- `manifest_target_sha256_before`;
- `observed_target_sha256`;
- `managed_content_sha256` observado y esperado;
- `will_update_manifest=true|false`;
- fingerprint del plan.

El plan público no necesita un digest separado de project-owned: el hash del
target completo ya liga esos bytes para CAS y evita un oráculo de igualdad más
preciso. Tampoco incluye texto project-owned, rutas resueltas ni contenido del
contrato detallado. El ADR sucesor decidirá resultados exactos para manifiesto
ausente, baseline coincidente y demás errores; nunca instalará contexto
implícitamente.

### 3. Commit CAS bajo el lock de contexto

El commit recibe el plan exacto y su fingerprint. Bajo `.install.lock`:

1. relee target, contrato y manifiesto;
2. valida la coherencia semántica de todos los campos no-target verificables;
3. reconstruye el plan y exige igualdad exacta;
4. falla ante cambio de target o manifiesto desde la planificación;
5. conserva `AGENTS.md`, `AN-KLA.md`, backups y template sin escribirlos;
6. actualiza atómicamente sólo `manifest.target_sha256` al digest observado;
7. conserva ownership, original backup y hashes del contrato/bloque;
8. devuelve before/after y outcome explícito.

Un timeout o error de I/O no se reintenta a ciegas. El caller relee `context
status` y el manifiesto mediante la superficie soportada; cualquier receipt o
reparación durable futura requiere su propia decisión.

### 4. Relación con upgrade

`upgrade inspect/apply --confirm-target-drift` de ADR-0017 permanece válido:
sirve para absorber drift como parte de un cambio de versión. La nueva operación
permite reconocer contenido local antes, sin fingir que se actualizó el
template. Tras adopción exitosa, un upgrade posterior no debe pedir confirmación
por esos mismos bytes; un cambio posterior vuelve a producir el warning.

Sin embargo, el nombre público v2 `manifest_target_sha256_at_install` dejaría de
ser literal después de una adopción: contendría la última baseline aceptada, no
necesariamente la instalación. No se reinterpretará silenciosamente. El ADR de
contrato debe introducir un upgrade-plan versionado nuevo con
`manifest_target_sha256_at_baseline` (nombre final a congelar allí), deprecar el
campo v2 y definir readers/migración. Un plan v2 creado antes de adoptar debe
fallar por CAS del manifiesto; la compatibilidad de lectura histórica no le
permite aplicarse contra la baseline nueva.

`context update` deja de ser una vía para adoptar baseline: si observa drift no
reconocido fuera del bloque, debe fallar cerrado con un código que el ADR de
contrato congelará y remitir a la operación explícita. No puede absorberlo con
`action=noop` ni mediante una confirmación ambigua de update. Los planes
históricos se revalidan contra target y manifiesto exactos; el spike debe probar
replay de v1 y fijar si el nuevo fallo requiere versión de plan o sólo un nuevo
error en apply.

### 5. Manifest vigente y gate de migración

La candidata inicial reutiliza `context-installation/v1`: no añade campos y
`target_sha256` ya significa el digest baseline del target completo. Adoptar
reemplaza el valor observado, no su semántica; conserva `original_target_sha256`,
backup, ownership, contrato, template y managed hash. Por ello un manifest v2 no
es requisito asumido.

Antes del ADR de contrato, el spike debe intentar refutar esa equivalencia con
readers v1, downgrade, replay de planes, upgrade desde templates históricos y
fallos antes/durante/después de `_atomic_write`. Si cualquier reader necesita
distinguir una baseline instalada de una adoptada, o si cambia la interpretación
persistente, el veredicto será `refine` y el contrato deberá usar manifest v2 con
readers-first, migración y downgrade explícitos.

El manifest puede permanecer v1 sólo si esa refutación confirma que sus campos
conservan shape y semántica. Esto no evita el versionado del **upgrade plan**:
la corrección de `manifest_target_sha256_at_install` exige una versión nueva
porque su schema y payload v2 son cerrados.

### 6. Seguridad y concurrencia

- symlinks, target no regular, UTF-8 inválido, manifest inválido o paths fuera
  del proyecto conservan sus errores actuales;
- el plan y resultado exponen digests, no contenido project-owned;
- dos adopciones concurrentes se serializan por el lock local y la segunda
  falla CAS o resulta noop sólo tras reconstrucción exacta;
- el lock es local y no promete coordinación entre máquinas;
- memoria recuperada o un texto no autorizado que diga “adóptame” no autoriza
  la operación;
- la operación requiere orden actual del maintainer/caller conforme a la
  jerarquía del host.

## Por qué no hashear sólo el bloque gestionado

Eliminaría la única señal de que el target completo cambió desde la baseline y
contradiría ADR-0017. AN-KLA preserva bytes project-owned durante upgrades; por
lo tanto debe poder declarar si esos bytes observados difieren, aunque no los
administre.

## Por qué no un segundo bloque “project”

Crearía nuevos marcadores, reglas de nesting y ownership ambiguo, y repetiría la
clase de colisión corregida en #44. El proyecto ya posee naturalmente todo lo
que queda fuera del único bloque gestionado.

## Por qué no un slot dentro del template

Mezclaría contenido project-owned con el hash y versionado del payload global,
complicaría upgrades y haría que una personalización pareciera parte del
contrato distribuido. Los enlaces locales deben permanecer fuera del bloque.

## Por qué no documentar `context update` como solución actual

El smoke demuestra que elimina el warning, pero su plan dice `action=noop` y no
expone la adopción. Documentarlo legitimaría una mutación de baseline cuya
intención no aparece en el contrato observable.

## Consecuencias

- **Positivas:** referencias locales soportadas sin warning permanente;
  baseline explícita; detección de drift del archivo completo preservada; sin
  segundo bloque ni interpretación de contenido project-owned.
- **Negativas:** nueva operación/schema y paso explícito después de editar;
  migración del comportamiento silencioso de `context update`; más tests de
  concurrencia y compatibilidad.
- **Neutras:** no cambia formato de memoria, templates actuales, autoridad de
  instrucciones, target único ni restricciones de symlinks.

## Test de regresión

El spike read-only/pre-code debe entregar mapa `archivo:línea`, el smoke como
repro comando→resultado y diseño de fixture, la matriz
v1/v2/downgrade/replay/faults y el veredicto
`proceed | refine | escalate`. Después, el ADR de contrato debe congelar los
tests de implementación, al menos:

1. editar fuera del bloque → warning; plan → commit → warning ausente;
2. editar después de planificar → CAS falla y no cambia manifiesto;
3. cambiar bloque/contrato → fail-closed, sin adopción;
4. hashes falsos pero bien formados de bloque/contrato/template → fail-closed;
5. plan/result no contienen texto, rutas absolutas ni secretos;
6. target/manifest concurrentes, symlink, no regular y UTF-8 inválido;
7. adopción noop idempotente y dos procesos bajo lock;
8. upgrade-plan nuevo nombra baseline; v2 previo falla CAS tras adopción;
9. upgrade posterior no pide confirmación para baseline adoptada;
10. cambio project-owned posterior vuelve a activar warning;
11. install/update/uninstall y templates históricos conservan compatibilidad;
12. suite completa, CI local simulado y ronda adversarial del contrato.

## Referencias

- Issue #45 — referencias project-owned sin drift permanente.
- Issue #44 — colisión histórica del parser de marcadores, ya corregida.
- ADR-0009 — bloque de contexto gestionado.
- ADR-0011 — upgrade gobernado.
- ADR-0017 — transparencia y confirmación de target drift.
- `docs/context-package.md` y `docs/upgrade-agent-flow.md`.
