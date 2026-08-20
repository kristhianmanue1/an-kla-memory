# Ronda adversarial FINAL — puntos 1–12 (2026-08-20)

Cierre del plan `plan-backlog-2026-08-20.md`. Revisor independiente con
auditoría integral de los 14 commits de la rama
(`2e06fc6..8d1534c`). Veredicto: **proceed** (condicionado a este
documento, que lo emite).

## Verificación final (evidencia del revisor)

- Suite: **583/583 OK**; `ci_local.py --simulate-ci` OK (4 pasos);
  `check_adr_registry` OK — 39 ADRs (36 aceptadas / 3 propuestas);
  `check_sizes` OK; `docs/schemas/` ≡ `an_kla/schemas/` byte a byte
  (66 JSON).
- Deriva ADR↔código: 0036/0037/0038/0039 consistentes con código y
  registro; supersedes de 0023/0030 vigentes.
- `capabilities()` determinista con 4 bloques aditivos; contrato de
  agente intacto (`TEMPLATE_VERSION` sin cambio).
- Sondas en vivo: `integration status` sobre este checkout correcto
  (verified/main_checkout/present con drift declarado); frescura con
  conteos e invariantes; git/v1 fail-closed por authority inválida;
  catch-all del CLI cubre los comandos nuevos; timeout git 5s heredado.
- 12/12 puntos con ronda + commit; hitos 1 y 2 con `proceed`;
  `escalate` donde el plan lo preveía (#45, #46).
- Beta.15 sigue describiendo `f9984ef` (decisión de hito 1 vigente);
  ningún tag existe (`git tag -l v0.1.0-beta.15` vacío); ninguna doc
  de la rama autoriza publicar sin orden del maintainer.

## Estado de los doce puntos

| # | Punto | Resultado |
|---|---|---|
| 1 | #84 resguardo CLI | Implementado; 2 rondas (fix-and-retry→proceed) |
| 2 | Sync ADR-0036 | Docs; 1 ronda (fix-and-retry→proceed) + errata registrada |
| 3 | Candidata beta.15 | Preparada (bump, notas, gates upgrade beta.12/13/14→b15); sin tag por diseño |
| 4 | #50 G-FRESH | Implementado (ADR-0037); 1 ronda (proceed con H1-H4 plegados) |
| 5 | #45 contexto sin drift | Decisión: ADR-0035 paso 1 recomendado; escalate |
| 6 | #79 git/v1 | Implementado (ADR-0038); 3 rondas; supersede normativo |
| 7 | #67 recall largos | Spike: inversión de relevancia documentada; dispensa pedida |
| 8 | #71 Nivel B | Decisión no-action; escalate de cierre |
| 9 | #68 inventario | Spike ADR-needed; implementación NO autorizada por el issue |
| 10 | #46 export sellado | Decisión: B vs D; escalate |
| 11 | #69 relaciones | Research no-action |
| 12 | G1–G4 | G1 implementado (ADR-0039); G2–G4 diseños de entrada |

Hitos: 1 y 2 con `proceed`; ronda final (este documento) `proceed`.

## Lista consolidada FINAL de decisiones para el maintainer

1. **Tag `v0.1.0-beta.15` sobre `f9984ef` exacto** (HITO 1). Todo lo
   posterior de la rama viaja en **beta.16** con ronda REL propia que
   re-describa la candidata exacta.
2. **#45**: autorizar implementación de ADR-0035 (adopción explícita
   de baseline), secuencia spike→ADR→código.
3. **#46**: decidir **B vs D** (crypto auditada en core con extra
   opt-in `[sealed]` vs delegación total al adaptador zero-dep).
4. **#79**: confirmar el supersede del nombre `git/v1` (ADR-0038 vs la
   reserva de ADR-0023/0030).
5. **#67**: dispensar o exigir las métricas por estrategia
   (`evaluate-v2`); decidir ADR density-aware o archivar la inversión
   de relevancia como límite conocido.
6. **#71 y #69**: cerrar como `no-action` (decisiones documentadas).
7. **#68**: autorizar ADR de `inventory --revision` (siguiente número
   libre de ADR; el spike dejó schema candidato y casos).
8. **G2–G4 (#56/#57/#58)**: diseños de entrada en
   `g2-g4-disenos-2026-08-20.md`; decidir secuenciación (recomendado
   G2→G3→G4).
9. **Merge de la rama y cierre de issues** (#84, #79, #50, #55, #45,
   #46, #67, #68, #69, #71 quedan trabajados; el cierre en GitHub es
   post-merge y del maintainer).

## Límites declarados de la rama

- GitHub Actions sigue sin correr (billing): CI local es el gate.
- `KeyboardInterrupt` sigue imprimiendo traceback (preexistente).
- El denominador de `view context`, el helper de caché compartido y el
  patrón `digest` con `\n` son deuda declarada en sus rondas.
- G2–G4 no implementados (por diseño y presupuesto de revisión).

## Decisión

- [x] proceed — la rama está completa y publiable como PR; sin tag ni
  merge sin orden del maintainer.
- [ ] fix-and-retry
- [ ] escalate
