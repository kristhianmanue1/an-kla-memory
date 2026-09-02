# Anclaje externo del digest de `refs/CURRENT` — protocolo y primer ancla

**dureza:** [C] convención de assurance — propuesta por Krathos, aprobada
por el dueño el 2026-08-31 junto con la aceptación de ADR-0043.

## Para qué existe

ADR-0043 (Aceptada) declara la frontera: el store ofrece tamper-evidence,
no tamper-proofness — un atacante con control del medio puede reescribir la
cadena completa de forma internamente coherente y `verify` la acepta. La
mitigación es comparar el digest de `refs/CURRENT` contra una copia fuera
del alcance de ese atacante. Este directorio es esa copia: cada ancla se
commitea y pushea a GitHub; reescribir el historial remoto es ruidoso y
detectable.

Requisitos que el ADR impone (§Consecuencias, hallazgo H6) y cómo los
cumple este protocolo:

1. **Verificación activa** — un digest que nadie consulta no detecta nada.
   El ancla se COMPARA contra el store en el cierre de cada run que toque
   memoria (no basta publicar).
2. **TOFU (trust on first use)** — la primera publicación confiable es el
   ancla inicial de este archivo, en el historial de GitHub desde
   2026-08-31. Cualquier reescritura posterior del historial invalida el
   canal y debe tratarse como incidente.

## Protocolo

**Anclar (cierre de cada run que escriba memoria):**

```bash
find .an-kla/memory/refs -type f -exec shasum -a 256 {} + | LC_ALL=C sort -k2 | shasum -a 256
```

`LC_ALL=C` fija la colación (decisión del dueño, 2026-09-02, issue #109
punto 3): evita divergencia fail-closed espuria por locale en
verificación cruzada macOS/Ubuntu. Fila del 2026-09-01 en adelante usan
este comando.

Añadir una fila a la tabla de abajo con fecha, digest, commit del run, y
veredicto de comparación. Commit + push.

**Verificar (arranque de sesión que consuma memoria, y cierre de run):**

Mismo comando; el digest debe coincidir con el último ancla de esta tabla.
Divergencia = PARADA fail-closed: no consumir memoria, escalar al dueño con
ambos valores. (Un cambio legítimo de `CURRENT` sin ancla previa también
dispara parada — es el costo deliberado del protocolo.)

**Límites declarados:** protege `refs` (la raíz de confianza); no evita que
un atacante que controla el medio fabrique objetos huérfanos ni que toque
segmentos si muta `CURRENT` de forma consistente — para eso, tras cada
parada, correr `verify` completo. El host completo comprometido (A4) queda
fuera de alcance por diseño (ADR-0031).

## Registro de anclas

| Fecha (UTC) | Digest sha256 (refs/) | Commit/origen | Comparación |
|---|---|---|---|
| 2026-09-01T00:41:40Z | `da10e7870477ed89badafb219f4d363f4079f315e4a8a2df8fb85b3c7621a7d8` | anclaje inicial (TOFU) — cierre del ciclo G-1/G-3, ADR-0043 aceptada | primera publicación |
| 2026-09-02T15:32:55Z | `42d3f6be0eb005b0878cc4728454b5e63201a5f2b019bf1138c8e0117dde3eb7` | re-anclaje protocolo `LC_ALL=C` (issue #109 punto 3, decisión del dueño 2026-09-02) — digest idéntico con comando viejo y nuevo en el host canónico; `CURRENT` avanzó legítimamente a rev 37 desde el ancla previa sin fila intermedia | re-anclaje tras parada fail-closed confirmada (`anchor_divergence`, exit 1) |
| 2026-09-02T18:22:59Z | `c706fb7364656b61e5acd4707f14f27665470fa228bea4db9524e9ad82e8962a` | cierre del ciclo beta.21 — checkpoint de continuidad rev 38 (tx c3571c2d), post tag `v0.1.0-beta.21` (commit 3eb7471) | anclaje de cierre; parada esperada confirmada antes de anclar |
