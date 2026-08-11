# ADR-0001: revisión content-addressed y `CURRENT`

- **Estado:** Aceptada
- **Implementación:** núcleo publicado desde `v0.1.0-alpha.1`; formato físico
  vigente.

La fuente de verdad es un manifiesto de revisión y los objetos inmutables que
este enumera. `.an-kla/memory/refs/CURRENT` contiene el hash del manifiesto
confirmado. Su reemplazo atómico local es el punto lógico de commit.

Un ref-log de objetos inmutables es diagnóstico; no es autoridad alternativa.
Si `CURRENT` no puede verificarse, la recuperación falla cerrada y exige una
selección explícita o un respaldo externo.

Los índices son vistas inmutables identificadas por revisión, perfil y hash de
contenido. Una vista ausente nunca invalida una revisión; el lector usa scan
fallback o devuelve `index_unavailable`.
