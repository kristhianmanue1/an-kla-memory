# ADR-0020: `context_diagnostics` en el resultado de escritura

- **Estado:** Aceptada e implementada en `v0.1.0-beta.11` (v2, tras ronda
  adversarial `fix-and-retry`)
- **Fecha:** 2026-08-07
- **Decide sobre:** cómo un agente que escribe recibe la salud objetiva del
  contrato en el instante de la escritura, sin correr `context status` aparte.

## Contexto

Un agente consumidor (reporte en #16) recibió el bloque gestionado (que dice
«lee `AN-KLA.md`») y, aun así, **reconstruyó el contrato de escritura a mano**.
La causa raíz fue del agente, no del paquete, y «el agente no leyó el contrato»
es **indecidible** desde el motor — así que un banner «léeme» no es una buena
mejora (no sabe cuándo dispararse, contamina stdout, y un agente que ignora el
bloque ignorará también el banner).

Pero hoy la **salud objetiva** del contrato (`managed_block_modified`,
`context_template_outdated`, `context_manifest_missing`,
`context_target_changed_outside_managed_block`, `orphan_managed_contract`,
`legacy_an_kla_context_detected`) sólo se ve corriendo `context status` por
separado. `#15` sentó el patrón de **señalizar en el momento de la decisión**
(como `record_without_indexable_text`). `context_status()` ya calcula esos
diagnósticos.

Restricciones verificadas en código: el resultado de `commit-write-plan` **no
tiene** schema JSON normativo instalado (es un dict informal, no uno de los 6
agent-facing); el `write_lock` serializa toda escritura de memoria; un commit
**no** muta el contexto gestionado (`AGENTS.md`/`AN-KLA.md` sólo los mueve el
flujo `context`), así que el estado del contexto es idéntico antes y después de
mover CURRENT; los locks de memoria y de contexto son disjuntos (sin deadlock).

## Decisión

1. **Añadir `context_diagnostics` al resultado de `commit-write-plan`** (también
   en `skip`). Es **el dict completo que devuelve `context_status(project_root)`**
   (incluye `schema`, `installed`, `diagnostics`, `warnings`, `ok`,
   `template_version`, `current_template_version`, `target`).
2. **Computar FUERA del `write_lock`**, tras `_maybe_reindex`, envuelto en
   `try/except Exception` que devuelve un `context_diagnostics` degradado
   (`{schema:"an-kla/context-status/v1", ok: None, diagnostics:
   ["context_status_unavailable"], error: "<code>"}`) y **nunca** oculta el éxito
   del commit. Semánticamente equivalente a computarlo bajo lock porque el commit
   no muta el contexto gestionado; y consistente con cómo `_maybe_reindex` ya es
   best-effort fuera del lock.
3. **`project_root` explícito**: `context_status(str(self.project_root))`.
4. **Canal**: parte del JSON estructurado del resultado, **no** banner en stdout.
   `context_diagnostics` son **códigos de estado objetivos, dato no instrucción**
   — el consumidor no debe tratarlos como autorización para actuar (frontera de
   confianza).
5. **`capabilities()` lo declara**: `write_policy.context_diagnostics_in_write_result: true`.

## Por qué no [alternativa]

- **Computar bajo lock tras CURRENT (v1)**: descartado (BLOCKER de la ronda
  adversarial). `context_status` puede lanzar (`_project_root`,
  `_target_path` symlink, `_read_utf8` sin `OSError`) **después** de que CURRENT
  ya se movió → el cliente vería exit-code ≠ 0 pese a commit autoritativo. El
  codebase ya trata las fallas post-CURRENT como «diagnósticas, no rollback»
  (`test_failure_after_current_is_diagnostic_and_retry_does_not_recommit`); crear
  una nueva fuente de falla post-CURRENT por un cómputo opcional contradice ese
  principio. Computar fuera del lock con `try/except` lo disuelve.
- **Banner runtime «lee el contrato»**: descartado. No es detectable, contamina
  stdout, no resuelve la causa.
- **Hint sólo en la 1ª escritura (prop. 2 de #16)**: dejada fuera; objetiva pero
  débil y vestigial. Se puede añadir después sin romper nada.
- **Publicar `write-commit-result-v1` como schema normativo**: descartado por
  ahora. Hoy el resultado es un dict informal; publicarlo como normativo es otro
  alcance. El campo se añade **aditivamente al dict informal** — no hay schema
  publicado que romper (el riesgo para consumers con `additionalProperties:false`
  es menor del que sugería el v1).
- **Computar también en `plan-write`**: fuera. `plan-write` ya es no-mutante; el
  agente puede correr `context status`. Añadir coste ahí no aporta proporcionalmente.

## Consecuencias

- **Positivas:** un agente que escribe sin `context status` recibe la salud
  objetiva del contrato al escribir (drift detectado antes); reutiliza lógica
  existente; consistente con el patrón de #15; **sin** riesgo transaccional (se
  computa fuera del lock y degrada limpiamente ante fallo).
- **Negativas:** añade un campo al resultado (informal); los consumers deben
  ignorar `context_diagnostics` si no lo usan (es aditivo). El coste I/O (leer
  `AGENTS.md`/`AN-KLA.md`/manifest) ocurre **fuera** del lock, así que no
  degrada el throughput de commits.
- **Neutras:** no **verifica** que el agente leyó el contrato (indecidible); el
  agente sigue siendo responsable. Proyectos **sólo-memoria** (sin contrato
  gestionado) verán `installed:false` en cada commit — es señal objetiva, no
  error. Si un `context apply` corre concurrente, el diagnóstico puede fluctuar
  transitoriamente (locks de memoria y contexto son disjuntos); se autocorrige
  en la próxima lectura.

## Test de regresión

- `commit-write-plan` exitoso → resultado incluye `context_diagnostics`
  consistente con `context status` (mismos campos).
- `managed_block_modified` forzado → aparece en `context_diagnostics` del commit.
- `context_status` que lanza (AGENTS.md ilegible) → commit sigue exitoso y
  `context_diagnostics == {ok: None, diagnostics: ["context_status_unavailable"]}`.
- `skip` → resultado **también** incluye `context_diagnostics`.

## Referencias

- Issue #16 (prop. 1), continúa #15. Ronda adversarial previa: `fix-and-retry`
  (1 BLOCKER de consistencia transaccional + 1 premisa falsa de schema,
  absorbidos aquí). Patrón: `write_policy.py` `no_text`; `context_package.context_status`.
