# Spike read-only — diagnóstico de arranque (#76)

> **Fecha:** 2026-08-15
> **Alcance:** verificar contra el código real qué ocurre hoy cuando un agente
> arranca en un project root sin memoria canónica, y devolver un plan validado.
> **Modo:** sólo lectura. No se modificó código ni store; los experimentos usan
> un directorio temporal fuera del repositorio.
> **Veredicto:** `proceed` con una corrección previa (ver §5, hallazgo H1).
> **Límite de esta ronda:** la investigación la hizo el mismo agente que propone
> el plan. §1 de `practicas-ingenieria.md` pide contexto fresco y decorrelación
> real; eso queda pendiente antes de implementar.

## 1. Preguntas del spike

1. ¿Dónde se resuelve la ubicación del store y qué la ata al `project_root`?
2. ¿Existe hoy algún descubrimiento de memoria vecina o externa?
3. ¿Qué recibe un agente que arranca sin memoria: señal estructurada o error?
4. ¿Hay un precedente de señal correcta dentro del propio CLI?
5. ¿Dónde encajaría el diagnóstico sin tocar superficie sensible?

## 2. Hechos verificados

**Ubicación del store.** `MemoryStore.__init__` resuelve el root sin ninguna
indirección: `self.root = self.project_root / ".an-kla" / "memory"`
(`an_kla/store.py:112-113`). No existe parámetro de store externo, confirmando
lo que ADR-0031 difiere a #57.

**No hay descubrimiento.** Un barrido de `.an-kla` sobre `an_kla/*.py` devuelve
sólo usos que componen rutas bajo el `project_root` propio
(`export_restore.py:81`, `context_package.py:432`, `identity_evidence.py:21`).
Ningún módulo busca una raíz vecina, y ninguno declara una memoria externa. La
hipótesis "el descubrimiento automático ya existe en alguna forma" queda
refutada.

**Arranque sin memoria: traceback, no señal.** Sobre un directorio vacío:

```
$ an-kla --project-root <vacío> status
an_kla.reader_gate.ReaderGateError: reader_gate_unavailable   # + traceback, exit 1
$ an-kla --project-root <vacío> doctor
an_kla.reader_gate.ReaderGateError: reader_gate_unavailable   # + traceback, exit 1
$ an-kla --project-root <vacío> resume --budget 12000
an_kla.reader_gate.ReaderGateError: reader_gate_unavailable   # + traceback, exit 1
$ an-kla --project-root <vacío> checkpoint show
an_kla.reader_gate.ReaderGateError: reader_gate_unavailable   # + traceback, exit 1
```

La causa es de jerarquía de excepciones, no de lógica:
`ReaderGateError(RuntimeError)` (`an_kla/reader_gate.py:14-15`) no desciende de
`StoreError` (`an_kla/store.py:55-56`), y el `except` de `main()`
(`an_kla/__main__.py:654`) enumera `StoreError` y familia pero no
`ReaderGateError`. El resultado es un stack trace crudo por una condición
esperable y benigna: el archivo `.reader-gate` no existe porque la memoria no
existe.

**El precedente correcto existe.** En el mismo directorio vacío:

```
$ an-kla --project-root <vacío> identity status
{"error_code":null,"identity_status":"absent","root_relocated":null,
 "schema":"an-kla/identity-status-v1"}   # exit 0
$ an-kla --project-root <vacío> context status
{... "installed": false ...}             # exit 0, JSON estructurado
```

`identity status` distingue `absent` de `complete` y sale con 0. `verify_upgrade`
hace lo mismo internamente: comprueba `store.current_path.exists()` y clasifica
en `verified` / `not_initialized` (`an_kla/upgrade.py:189-192`). La capacidad de
clasificar ya está en el código; lo que falta es exponerla en el punto de
decisión de arranque.

**Distinguir ausencia de aislamiento es imposible hoy.** Ni `status`, ni
`doctor`, ni `identity status` dicen nada sobre la existencia de otra memoria en
otro checkout. `identity_status: "absent"` es la misma respuesta para "este
proyecto nunca tuvo memoria" y para "la memoria está en el checkout canónico,
tres directorios más arriba". Ése es exactamente el hueco de #76.

## 3. Qué NO se verificó

- Si el descubrimiento de una raíz vecina sería seguro: no se investigó, y el
  plan de §4 deliberadamente no lo necesita.
- Comportamiento en Windows: `durability_profile` ramifica por `os.name`
  (`an_kla/store.py:133`), pero el spike corrió sólo en macOS.
- Si un `.an-kla/` parcialmente escrito produce una tercera clase de fallo
  distinta de ausencia e integridad rota.

## 4. Plan validado

**Fase 0 — corregir H1 antes de nada.** Añadir `ReaderGateError` al `except` de
`main()`, o hacerlo descender de `StoreError`. Es la corrección mínima que
convierte cuatro tracebacks en el error surface ya existente. Sin ADR: no cambia
contrato observable, sólo deja de filtrar un stack trace.

**Fase 1 — ADR.** Congelar el contrato del diagnóstico antes de escribir código,
según §3 de `practicas-ingenieria.md`. El contrato clasifica en cuatro estados:

| Estado | Significado |
|---|---|
| `local_valid` | `.an-kla/memory/refs/CURRENT` existe y `verify` pasa |
| `absent` | no hay memoria bajo este project root |
| `external_declared` | una memoria externa está declarada y fue verificada |
| `external_candidate` | hay indicio de memoria externa, no adoptada o no accesible |

Los dos primeros son implementables hoy con lo que ya existe
(`current_path.exists()` + `verify`). Los dos últimos requieren un mecanismo de
declaración que pertenece a #57; el ADR debe definir sus nombres y su semántica
ahora para que el schema no cambie después, pero el diagnóstico puede emitirlos
como inalcanzables hasta que #57 exista.

**Fase 2 — implementación.** Comando nuevo, `an-kla startup-diagnostic` o
equivalente, read-only, exit 0 en los cuatro estados: un diagnóstico que falla
no diagnostica. Schema versionado `an-kla/startup-diagnostic-v1`, con
`untrusted_memory_data: true` como el resto de salidas.

**Fase 3 — ronda adversarial** con contexto fresco, y recién entonces el PR.

## 5. Hallazgos

**H1 — HIGH — traceback en lugar de señal.** Cuatro comandos de arranque
revientan con stack trace ante la condición más común de un proyecto nuevo. Un
agente que lo reciba no puede distinguir "no hay memoria" de "AN-KLA está roto",
y la reacción razonable —pedirle al usuario que administre la persistencia— es
justo la que #76 describe como indebida. Corregir antes de construir encima.

**H2 — MED — `identity_status: "absent"` es ambiguo.** Colapsa ausencia y
aislamiento en un solo valor. El diagnóstico nuevo no debe heredar esa
ambigüedad, y conviene revisar si `identity status` debería referenciar el
diagnóstico en lugar de duplicar la clasificación.

**H3 — LOW — la clasificación ya existe duplicada.** `verify_upgrade`
(`an_kla/upgrade.py:189-192`) implementa su propia versión de
`verified | not_initialized`. Si el diagnóstico nace como fuente única, ese
código debería consumirlo en vez de repetirlo.

## 6. Riesgos del plan

1. **Alcance que se desborda hacia #57.** `external_declared` es la puerta por la
   que entra la reubicación de store. Mitigación: el ADR define el vocabulario;
   la implementación emite sólo los estados alcanzables.
2. **Un diagnóstico que se lee como autoridad.** Decir `local_valid` no dice que
   la memoria sea vigente ni verdadera — el drift de la revisión 29 era
   `local_valid` perfecto. El schema debe declarar `canonicality` explícita.
3. **Duplicar el precedente en vez de unificarlo.** Si el diagnóstico nace junto
   a `identity status` y `verify_upgrade` sin absorberlos, quedan tres
   clasificaciones que pueden divergir.

## 7. Evidencia

- `an_kla/store.py:112-113`, `an_kla/store.py:55-56`
- `an_kla/reader_gate.py:14-15`, `an_kla/reader_gate.py:44-46`
- `an_kla/__main__.py:654`, `an_kla/upgrade.py:189-192`
- Ejecuciones sobre directorio temporal vacío, transcritas en §2.
- Store canónico intacto durante el spike: `verify` → `ok=true`, revisión 30,
  `23 facts / 21 events / 10 episodes`.
