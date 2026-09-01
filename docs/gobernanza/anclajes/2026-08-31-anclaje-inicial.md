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
find .an-kla/memory/refs -type f -exec shasum -a 256 {} + | sort -k2 | shasum -a 256
```

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
