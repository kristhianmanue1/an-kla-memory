# Protocolo técnico de supervisión de un agente externo

> **Estado:** experimental, validado mediante un piloto read-only
> **Fecha de corte:** 2026-08-11
> **Alcance actual:** Codex como controlador/auditor, OpenCode en `tmux` como
> ejecutor y el maintainer como mediador humano
> **Alcance futuro:** reactivación programada o dirigida por eventos; no
> implementada ni autorizada por este documento

## 1. Resultado y propósito

Este protocolo conserva una sesión conversacional de un agente externo sin que
Codex tenga que consumir contexto haciendo polling. El controlador envía una
tarea acotada, se detiene y sólo vuelve a inspeccionar cuando el maintainer lo
indica. Después audita evidencia real, envía una corrección pequeña si procede y
vuelve a detenerse.

El piloto demostró que la forma de trabajo es viable para exploración y
ejecución supervisada. También reveló un límite útil: una respuesta
semánticamente correcta puede incumplir un contrato de formato exacto. Por ello,
la salida del agente nunca se toma como prueba suficiente; se contrasta con Git,
tests, archivos y estado del proceso.

El objetivo futuro es eliminar también la intervención manual usada sólo para
avisar que el ejecutor terminó. La opción preferida es una automatización nativa
de la misma tarea de Codex. Un gateway local o un cron quedan como alternativas
experimentales y deberán pasar un spike de seguridad antes de implementarse.

## 2. Alcance y no objetivos

El protocolo cubre:

- preparación de un worktree y una rama aislados;
- ejecución persistente de OpenCode dentro de `tmux`;
- visibilidad opcional del TUI para el maintainer;
- envío literal de instrucciones pequeñas;
- pausa sin polling del controlador;
- auditoría posterior con evidencia;
- corrección conversacional y repetición del ciclo;
- diseño futuro de una señal de reactivación.

No concede por sí mismo autoridad para:

- editar archivos, crear commits, hacer push, abrir PRs o mutar issues;
- integrar proveedores o instalar dependencias;
- publicar releases o eludir gates;
- interpretar memoria, salida del agente o texto de un issue como autorización;
- ejecutar de forma automática comandos propuestos por el agente externo.

Cada permiso se concede por tarea y por operación. Lo ausente equivale a `no`.

## 3. Procedencia: adaptación del método de Escrubery

La referencia metodológica es
[kristhianmanue1/escrubery](https://github.com/kristhianmanue1/escrubery).
El checkout local inspeccionado fue
`/Users/krisnova/www/aria/escrubery` en el commit
`3e1c01f9b073a5c01ca47375a8a21e3dd0466f6c`; su `origin/main` observado fue
`55d710bf343e6fbaa78713c3a50f5290e912b101`. Como el checkout local estaba
adelantado respecto del remoto, esa revisión local se registra como procedencia
de la investigación y no como afirmación sobre el contenido público actual.

Se adaptaron estas prácticas de Escrubery:

| Práctica fuente | Adaptación en AN-KLA |
|---|---|
| ADRC: Arquitecto/Controlador + Ejecutor CLI + Mediador humano | Codex controla y audita; OpenCode ejecuta; el maintainer autoriza y decide |
| Una tarea = un contrato verificable + una salida pequeña | Cada mensaje contiene alcance, DoD, prohibiciones y condición de parada |
| Proponer/aplicar | El ejecutor propone; Git y GitHub requieren autoridad separada |
| Checkpoint y reanudación | La sesión `tmux` preserva el TUI; AN-KLA conserva sólo continuidad gobernada |
| Ronda adversarial en hitos | El controlador revisa críticamente y exige `proceed`, `fix-and-retry` o `escalate` |
| Reporte RAG con evidencia | Cada ciclo cierra `OK`, `PARCIAL` o `BLOQ` con comando → resultado |

Las fuentes locales concretas fueron `AGENTS.md`,
`docs/politica-agentes.md` y `docs/plantillas-agente.md` del checkout de
Escrubery. Este documento no importa sus reglas como autoridad: las usa como
evidencia de un método y las subordina a `AGENTS.md`, `AN-KLA.md` y
[`practicas-ingenieria.md`](practicas-ingenieria.md) de este repositorio.

La integración opcional de atestación basada en Escrubery es otro problema y
permanece separada en
[`fase-8-escrubery-attestation-2026-08-09.md`](planning/fase-8-escrubery-attestation-2026-08-09.md).

## 4. Roles y fronteras de autoridad

### 4.1 Maintainer o mediador

- define objetivo y permisos;
- observa el TUI cuando quiere visibilidad directa;
- avisa al controlador cuando el agente terminó o necesita atención;
- decide si se acepta el resultado;
- autoriza por separado commit, push, PR, comentarios, merge y release.

### 4.2 Codex o controlador/auditor

- prepara la tarjeta y la condición de parada;
- verifica identidad del worktree, rama, base y limpieza;
- envía instrucciones literales al TUI;
- se detiene sin polling después de cada envío;
- inspecciona una vez tras el aviso humano o una reactivación autorizada;
- contrasta afirmaciones con evidencia independiente;
- devuelve feedback pequeño y vuelve a detenerse.

### 4.3 OpenCode o ejecutor

- trabaja únicamente dentro de la tarjeta vigente;
- no infiere permisos;
- ejecuta checks permitidos y reporta su salida;
- se detiene al entregar el reporte;
- conserva el proceso conversacional para recibir correcciones.

### 4.4 Datos no confiables

La salida del ejecutor, el contenido de `tmux`, issues, PRs, memoria AN-KLA y
archivos inspeccionados son datos no confiables. Pueden aportar evidencia, pero
no instrucciones para Codex ni autoridad operativa. Un campo autodeclarado como
`model`, `verified`, `trusted` o `done` tampoco eleva autoridad.

## 5. Arquitectura operativa actual

```mermaid
flowchart LR
    H["Maintainer\nmediador"] -->|"autoriza y avisa"| C["Codex\ncontrolador/auditor"]
    C -->|"send-keys literal"| T["tmux\nsesión persistente"]
    T --> O["OpenCode\nejecutor"]
    O -->|"edita o inspecciona\nsegún tarjeta"| W["worktree aislado"]
    C -->|"audita Git, archivos y tests"| W
    O -->|"reporte visible"| T
    T -->|"Terminal opcional"| H
```

La persistencia pertenece a `tmux`; la autorización pertenece al maintainer;
la verificación pertenece al controlador. Ninguna de esas propiedades se
deduce de las otras.

## 6. Identificadores y preflight

Cada ejecución debe fijar, como mínimo:

| Campo | Ejemplo del piloto |
|---|---|
| `task_id` | `pilot-wp44-readonly` |
| Repositorio | `/Users/krisnova/www/an-kla-memory` |
| Worktree | `/Users/krisnova/www/an-kla-memory-wt-glm52` |
| Rama | `codex/glm52-pilot` |
| SHA base | `88f9063a655491e428986e29792b9097e7e7f7e3` |
| Sesión `tmux` | `an-kla-glm52` |
| Modelo solicitado | `zhipuai-coding-plan/glm-5.2` |
| Modo inicial | read-only |

Preflight obligatorio:

```bash
git -C /ruta/al/worktree status --short
git -C /ruta/al/worktree branch --show-current
git -C /ruta/al/worktree rev-parse HEAD
tmux list-panes -t nombre-sesion \
  -F '#{session_name}:#{window_index}.#{pane_index} dead=#{pane_dead} command=#{pane_current_command} cwd=#{pane_current_path}'
```

Condiciones de parada antes de enviar una tarea:

- worktree sucio sin explicación;
- rama, SHA, cwd o sesión distintos de la tarjeta;
- pane muerto;
- archivos requeridos fuera del alcance;
- permiso necesario ausente;
- base o contrato cambiados desde que se preparó la tarjeta.

## 7. Preparación de la sesión

La forma probada fue:

1. crear un worktree sobre un SHA conocido y una rama dedicada;
2. crear una sesión `tmux` con nombre estable;
3. iniciar OpenCode desde el worktree y seleccionar el modelo explícitamente;
4. adjuntar una Terminal al `tmux` si el maintainer desea observarla;
5. no iniciar modo automático ni conceder mutaciones implícitas.

Ejemplo conceptual:

```bash
git worktree add -b codex/<tarea> /ruta/worktree <sha-base>
tmux new-session -d -s <sesion> -c /ruta/worktree
tmux send-keys -t <sesion> 'opencode . -m zhipuai-coding-plan/glm-5.2 --mini' Enter
```

El comando sólo ilustra la configuración observada. Crear ramas, worktrees o
procesos sigue sujeto a la autoridad de la tarea vigente.

## 8. Contrato de mensaje

Una instrucción debe ser autocontenida y contener:

1. objetivo único;
2. entradas que debe leer;
3. alcance permitido;
4. prohibiciones explícitas;
5. checks y evidencia esperada;
6. formato de reporte;
7. condición inequívoca de parada.

Plantilla mínima:

```text
TAREA <id>. Objetivo: <resultado único>.
Base: <SHA>; worktree: <ruta>; rama: <rama>.
Permitido: <lectura/edición/checks concretos>.
Prohibido: <commit/push/PR/etc.>.
DoD: <checks ejecutables>.
Entrega: reporte RAG breve con comando → resultado.
Al terminar, detente y espera nuevas instrucciones.
```

El envío debe separar texto literal de la pulsación de Enter:

```bash
tmux send-keys -l -t <sesion> '<mensaje-literal>'
tmux send-keys -t <sesion> Enter
```

No se concatena texto no confiable dentro de comandos de shell. Para mensajes
largos, el controlador debe usar una vía que preserve literalmente el contenido
y verificar sólo la recepción, no mantener un ciclo de captura.

## 9. Ciclo manual probado: enviar, parar, avisar, auditar

### Estado M0 — preparado

- preflight verde;
- tarjeta vigente;
- permisos explícitos;
- ejecutor esperando.

### Estado M1 — instrucción enviada

- enviar el mensaje y Enter;
- confirmar únicamente que el envío técnico tuvo exit code `0`;
- no interpretar aún el resultado del agente.

### Estado M2 — pausa real

Codex termina su turno. No ejecuta `sleep`, `capture-pane`, polling, espera
activa ni bucles de lectura. El consumo de contexto del controlador queda en
cero hasta una nueva intervención.

### Estado M3 — aviso

El maintainer comunica “terminó”, “requiere atención” o equivalente. Ese aviso
habilita una inspección, no una mutación.

### Estado M4 — auditoría única

El controlador captura una ventana acotada y verifica el worktree:

```bash
tmux capture-pane -p -J -t <sesion> -S -120
git -C /ruta/al/worktree status --short
git -C /ruta/al/worktree diff --check
```

Cuando aplique, añade `git diff`, tests focales, suite, gates documentales y
comparación de SHA. La afirmación “terminé” nunca sustituye estos checks.

### Estado M5 — decisión

- `OK`: DoD satisfecho y evidencia consistente;
- `PARCIAL`: avance válido, pero falta un check, autorización o condición;
- `BLOQ`: no se puede continuar de forma segura;
- `fix-and-retry`: hay hallazgos corregibles dentro del alcance;
- `escalate`: hace falta una decisión o autoridad nueva.

### Estado M6 — feedback y nueva pausa

Si procede, enviar una corrección pequeña, confirmar sólo el envío y volver a
M2. El maintainer vuelve a avisar cuando el agente termine.

## 10. Prueba de obediencia pequeña

Una prueba de control debe minimizar ambigüedad y no pedir acceso al sistema:

```text
Responde sólo ACK44. No ejecutes comandos ni edites archivos. Después espera.
```

Se recomienda un token corto y sin puntuación. El piloto usó
`ACK-CONTROL-44` y el ejecutor lo partió físicamente como `ACK-CONTROL-` y `44`.
El contenido era correcto, no hubo comandos posteriores y Git permaneció
limpio, pero el contrato “exactamente una línea” quedó `PARCIAL`.

Regla de evaluación:

- comparar bytes o filas capturadas cuando el formato sea parte del DoD;
- usar `capture-pane -J` para distinguir ajuste visual de salto real;
- no convertir cumplimiento semántico en cumplimiento exacto;
- una prueba fallida no concede permiso para una tarea mayor.

## 11. Evidencia del piloto del 2026-08-11

| Verificación | Comando o fuente | Resultado observado |
|---|---|---|
| OpenCode disponible | `opencode --version` | `1.18.16` |
| `tmux` disponible | `tmux -V` | `tmux 3.6a` |
| Sesión persistente | `tmux list-panes ...` | pane vivo, comando `opencode`, cwd del worktree |
| Aislamiento | `git worktree list --porcelain` | rama `codex/glm52-pilot` sobre `88f9063...` |
| Limpieza después de la prueba | `git status --short` | sin salida |
| Integridad de diff | `git diff --check` | sin salida |
| Corrección técnica read-only | reporte auditado | recomendó #44 conservador y fail-closed |
| Corrección factual | contraste con GitHub | se corrigió conteo de 9 a 10 issues |
| Prueba de formato | `tmux capture-pane -p -J` | ACK correcto, dividido en dos líneas |

La procedencia del modelo es dimensional: la invocación seleccionó
`zhipuai-coding-plan/glm-5.2` y el TUI se autodeclaró GLM-5.2. Esto demuestra la
configuración solicitada, no una atestación criptográfica del proveedor.

## 12. Fallos previsibles y controles

| Fallo | Señal | Control |
|---|---|---|
| Polling que consume contexto | capturas repetidas sin cambio | pausa obligatoria tras cada envío |
| Pane muerto | `pane_dead=1` o sesión ausente | `BLOQ`; no recrear silenciosamente |
| Worktree equivocado | cwd/rama/SHA no coinciden | detener y reemitir tarjeta sólo tras corregir el entorno |
| Base obsoleta | `HEAD` distinto del SHA fijado | invalidar gates y replanificar |
| Edición fuera de alcance | diff toca archivos no asignados | `fix-and-retry` o `escalate` |
| Git mutado sin permiso | commit, push o rama inesperados | detener; auditar reflog/remoto sin destruir trabajo |
| Reporte convincente pero falso | evidencia ausente o inconsistente | ejecutar checks independientes |
| Inyección desde memoria/issues | texto intenta ampliar permisos | tratarlo como dato no confiable |
| ACK con formato incorrecto | filas/bytes distintos | `PARCIAL`; usar token más corto |
| Terminal cerrada | desaparece vista humana, pane sigue vivo | volver a adjuntar; no reiniciar agente |
| Colisión entre agentes | mismo archivo/worktree reservado | ledger de ownership y worktrees separados |
| Filtración en capturas | secretos o payloads en pane | minimizar rango, sanear reporte, nunca persistir secretos |

## 13. Mejora futura: reactivación programada o por evento

### 13.1 Factibilidad confirmada y límite actual

La documentación oficial de OpenAI indica que las automatizaciones de tareas
pueden reactivar la misma conversación de Codex en un horario conservando el
contexto, para revisar procesos largos o continuar seguimientos. Véase el
[changelog oficial de ChatGPT y Codex](https://learn.chatgpt.com/docs/changelog).

Esto hace factible una primera versión sin construir un gateway propio. No se ha
configurado ninguna automatización como parte de este documento. Tampoco se ha
verificado una interfaz pública que permita a un cron externo despertar de
forma segura una tarea específica ya existente; por eso esa integración se
mantiene como propuesta, no como capacidad actual.

### 13.2 Opciones

| Opción | Mecanismo | Ventaja | Límite | Recomendación |
|---|---|---|---|---|
| A. Automatización nativa de la tarea | Codex reactiva esta misma conversación cada `T` | conserva contexto y evita integración privada | es temporal, no instantánea; depende de disponibilidad del host | primera implementación |
| B. Automatización + recibo local | un watcher escribe un recibo; Codex lo revisa al despertar | reduce lectura del TUI y permite deduplicar | aún revisa por intervalo | segunda iteración |
| C. Gateway por evento | el watcher notifica una transición mediante interfaz soportada | baja latencia sin polling del modelo | requiere API/hook oficial, autenticación y deduplicación | spike futuro |
| D. Cron que inyecta teclas/prompts | cron escribe directamente al TUI o a Codex | simple en apariencia | frágil, mezcla autoridad, fácil de duplicar o inyectar | no recomendado |

### 13.3 Diseño recomendado v0: automatización nativa

Configurar una automatización en esta misma tarea con un intervalo elegido por
el maintainer. Su instrucción debe ser read-only y de una sola inspección:

```text
Revisa una sola vez la sesión y el worktree registrados para <task_id>.
Si el ejecutor sigue trabajando y no solicita atención, reporta SIN_CAMBIO y
detente. Si terminó o está bloqueado, audita la evidencia, informa RAG y
detente. No envíes nuevas instrucciones ni hagas mutaciones sin autorización.
```

Controles:

- intervalo mínimo suficientemente largo para evitar ruido;
- una sola captura por despertar;
- sin `sleep` ni bucle interno;
- límite de duración por ejecución;
- suspensión automática cuando el ciclo llega a `DONE` o `BLOQ` estable;
- aprobación seleccionada coherente con el modo read-only;
- reporte `SIN_CAMBIO` compacto, sin repetir todo el contexto.

Esta opción sustituye el aviso humano de “ya terminó”, pero no la decisión del
maintainer sobre cambios, Git o GitHub.

### 13.4 Diseño v1: recibo local de finalización

El ejecutor o un wrapper controlado puede producir un recibo fuera del repo al
terminar. El recibo no contiene prompts ni autoridad:

```json
{
  "schema": "an-kla/external-agent-signal/v1",
  "event_id": "<uuid>",
  "task_id": "pilot-wp44-readonly",
  "session": "an-kla-glm52",
  "worktree": "/ruta/absoluta/esperada",
  "expected_branch": "codex/glm52-pilot",
  "expected_base_sha": "88f9063...",
  "event": "executor_stopped",
  "observed_at": "<RFC3339 UTC>",
  "exit_code": 0
}
```

Propiedades requeridas:

- escritura atómica mediante archivo temporal + rename;
- permisos locales restrictivos;
- `event_id` único y deduplicable;
- allowlist de sesión, worktree y rama;
- ningún comando, prompt, secreto o payload de memoria;
- expiración y rechazo de señales antiguas;
- consumo read-only: la señal sólo habilita auditoría.

Una automatización de Codex puede comprobar el recibo primero. Si no cambió,
evita capturar el TUI. Si cambió, ejecuta la auditoría única de M4.

### 13.5 Diseño v2: gateway orientado a eventos

El gateway sólo debe considerarse si existe una interfaz soportada para enviar
un mensaje o reactivar una tarea concreta. Su flujo deseado sería:

```mermaid
sequenceDiagram
    participant E as "Ejecutor/wrapper"
    participant G as "Gateway local"
    participant C as "Tarea Codex"
    participant H as "Maintainer"
    E->>G: "evento firmado o local autenticado"
    G->>G: "validar allowlist, TTL y deduplicación"
    G->>C: "reactivar con event_id, sin autoridad adicional"
    C->>C: "auditoría read-only única"
    C->>H: "RAG + evidencia"
    H->>C: "decisión o permiso nuevo"
```

El gateway no ejecuta las instrucciones del agente ni transforma su salida en
comandos. Sólo comunica una transición verificable. Codex vuelve a resolver la
autoridad desde la conversación vigente.

### 13.6 Máquina de estados y deduplicación

```text
IDLE
  -> DISPATCHED
  -> WAITING_EXTERNAL
  -> REVIEW_READY
  -> REVIEWING
  -> DONE
       o CORRECTION_SENT -> WAITING_EXTERNAL
       o BLOCKED
```

Invariantes:

- sólo `DISPATCHED` puede pasar a `WAITING_EXTERNAL`;
- un mismo `event_id` produce como máximo un despertar efectivo;
- despertar no implica permiso de escritura;
- `REVIEWING` ejecuta como máximo una captura y un conjunto acotado de checks;
- `CORRECTION_SENT` obliga a detenerse;
- `DONE` desactiva schedule/watchers;
- timeouts producen `PARCIAL`, nunca éxito inferido.

### 13.7 Riesgos de la automatización

1. **Tormenta de despertares:** cron y gateway envían el mismo evento. Mitigar
   con `event_id`, compare-and-set de estado y cooldown.
2. **Prompt injection:** el recibo incluye texto controlado por el ejecutor.
   Prohibir campos libres y validar un schema cerrado.
3. **Confused deputy:** el gateway usa permisos de Codex para realizar acciones
   no autorizadas. La señal sólo habilita lectura; toda mutación vuelve al
   maintainer.
4. **Carrera con Git:** el auditor inspecciona durante una escritura. Exigir un
   estado final/sentinel atómico y volver a verificar Git.
5. **Proceso huérfano:** `tmux` vive, pero OpenCode no progresa. Distinguir
   `pane_alive`, `process_alive`, actividad y finalización; no inferir salud.
6. **Contexto obsoleto:** la automatización conserva conversación, pero Git
   cambió. Revalidar SHA, rama y worktree en cada despertar.
7. **Coste oculto:** demasiados intervalos consumen ejecuciones aunque nada
   cambie. Usar intervalos conservadores, recibo previo y apagado automático.

## 14. Plan de implementación futura

La mejora futura se divide en gates; este documento no los ejecuta.

### F0 — especificación

- decidir intervalo, timeout y horario;
- definir qué significa `finished`, `blocked` y `no_change`;
- fijar schema cerrado de la señal;
- decidir retención y ubicación del recibo fuera del repo;
- registrar permisos por operación.

**Salida:** contrato y amenazas revisados. Si introduce un contrato persistente
o una nueva frontera de autoridad, preparar ADR antes del código.

### F1 — automatización nativa read-only

- crear una automatización temporal en la misma tarea;
- inspección única por ejecución;
- probar `SIN_CAMBIO`, `REVIEW_READY` y sesión ausente;
- demostrar que terminar/deshabilitar detiene futuros despertares.

**DoD:** cero mutaciones, cero loops, una notificación por transición y trazas
saneadas.

### F2 — watcher/recibo local

- prototipo en directorio temporal;
- escritura atómica y permisos mínimos;
- tests de evento duplicado, antiguo, malformado y worktree no permitido;
- integración con F1 sin leer el TUI cuando no cambia el recibo.

**DoD:** watcher sin credenciales de Git/GitHub y recibos sin contenido libre.

### F3 — gateway por evento, sólo si existe interfaz soportada

- spike read-only de la API/hook oficial;
- threat model y ronda adversarial independiente;
- autenticación local, nonce/TTL, deduplicación y rate limit;
- kill switch y recuperación tras reinicio;
- auditoría de extremo a extremo.

**DoD:** `proceed` adversarial y autorización explícita del maintainer. Si no
existe interfaz soportada, cerrar F3 como `BLOQ` y conservar F1/F2.

## 15. Checklist reutilizable

Antes de delegar:

- [ ] issue/objetivo único y SHA base fijados;
- [ ] worktree, rama, sesión y modelo declarados;
- [ ] `git status --short` limpio;
- [ ] permisos separados y stop conditions;
- [ ] DoD ejecutable y formato de reporte;
- [ ] datos sensibles clasificados.

Después de enviar:

- [ ] `tmux send-keys` terminó con exit `0`;
- [ ] Codex se detuvo sin polling;
- [ ] aviso humano o reactivación autorizada recibido.

Durante la auditoría:

- [ ] captura única y acotada;
- [ ] Git y diff comprobados independientemente;
- [ ] tests/gates ligados al SHA real;
- [ ] afirmaciones y conteos contrastados;
- [ ] RAG y decisión solicitada;
- [ ] feedback pequeño o cierre;
- [ ] nueva pausa.

## 16. Decisiones pendientes del maintainer

Antes de implementar la mejora futura habrá que decidir:

1. si la primera versión usa automatización nativa de Codex;
2. intervalo y horario de reactivación;
3. si basta polling temporal o se justifica un recibo local;
4. qué duración máxima produce `PARCIAL`/timeout;
5. si el gateway por evento aporta suficiente valor para asumir su superficie
   de seguridad y mantenimiento.

Hasta entonces, el flujo manual con aviso humano es el mecanismo vigente del
piloto.

## 17. Referencias

- [Escrubery](https://github.com/kristhianmanue1/escrubery) — procedencia del
  marco ADRC y de las prácticas de trabajo agent-native.
- [`practicas-ingenieria.md`](practicas-ingenieria.md) — gates vigentes de
  AN-KLA Memory.
- [`agent-report-template.md`](agent-report-template.md) — reporte RAG con
  evidencia.
- [`plan-ejecucion-backlog-agentes-2026-08-11.md`](planning/plan-ejecucion-backlog-agentes-2026-08-11.md)
  — Definition of Ready, permisos y secuenciación del backlog.
- [`plan-ejecucion-backlog-agentes-adversarial-2026-08-11.md`](planning/plan-ejecucion-backlog-agentes-adversarial-2026-08-11.md)
  — hallazgos que endurecieron la coordinación multiagente.
- [Changelog oficial de ChatGPT y Codex](https://learn.chatgpt.com/docs/changelog)
  — capacidad documentada de automatizaciones que reactivan la misma tarea.
