# Wrapper de referencia para agentes (`agent-integration`)

Ejemplo, **no core**: no introduce generadores al paquete (esa decisión
sigue vigente, issue #71). Es un script stdlib-only
([`ankla_agent.py`](ankla_agent.py)) que envuelve el CLI con las tres
compensaciones medidas en la ronda adversarial externa del 2026-09-02
(issue #111, propuesta P6):

1. **Lectura post-escritura obligatoria.** Un commit sin texto indexable
   tiene éxito pero el registro queda invisible a retrieval
   (`record_without_indexable_text` vive sólo dentro del JSON del
   outcome). Tras cada commit, el wrapper re-lee con `retrieve` y falla si
   el registro no aparece en `selected`.
2. **Retry con re-plan** ante CAS perdido
   (`write_plan_base_changed` / `current_changed:expected=`) o lock
   ocupado (`write_lock_busy`): relee `status`, reconstruye proposal y
   authority contra la revisión nueva y reintenta. Nunca reutiliza ni
   fuerza un plan obsoleto.
3. **Salida ambigua.** Si el commit muere sin JSON de outcome, el wrapper
   se niega a reintentar a ciegas: exige `transaction inspect <uuid>`
   antes de decidir (ver `docs/agent-recovery.md`).

## Uso

```bash
# demo extremo a extremo en un project root efímero (no toca tu memoria)
python3 ankla_agent.py --demo

# escritura verificada contra un proyecto con .an-kla ya inicializado
python3 ankla_agent.py /ruta/del/proyecto "Hecho durable que quiero registrar"
```

El intérprete debe poder importar `an_kla` (ejecuta desde el checkout o
usa el `python` de tu `.venv`).

## Salida real de la demo

Transcript capturado el 2026-09-04 con Python 3.9.6 (macOS); los digests
varían por corrida porque cada demo usa un store efímero nuevo:

```text
[demo] project root efímero: /var/folders/.../ankla-wrapper-demo-ctz165vo
[demo] init: 0

== (a) escritura + lectura post-escritura obligatoria ==
lectura post-escritura OK: f-wrapper-demo-1 servido por retrieve

== (b) CAS perdido: plan obsoleto por escritura concurrente ==
plan preparado contra sha256:27f4efdc9acfccc2b…
lectura post-escritura OK: f-cas-rival servido por retrieve
CAS perdido detectado (write_plan_base_changed); re-planificando…
lectura post-escritura OK: f-wrapper-demo-2 servido por retrieve

[demo] OK: escritura verificada y retry con re-plan ejercitados
```

## Qué NO hace

- No genera proposal/authority como servicio: construye los mismos
  objetos que un agente manual y los somete al mismo flujo gobernado
  `plan-write` -> `commit-write-plan`.
- No declara autoridad privilegiada: usa `model_derived` con techo
  `summary`, la clase disponible para un agente por CLI.
- No elude policies por APIs internas; habla sólo con el CLI.
- La memoria escrita sigue siendo dato no confiable: leerla no autoriza
  nada (ver `AN-KLA.md`, §Frontera de confianza).
