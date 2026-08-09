# Spike ADR-0027: frontera durable de export/restore

ADR-0001 hace `CURRENT` autoridad; revisions/segments/checkpoints forman el
snapshot; revision-v2 añade refutations, claims y attestations; ADR-0024 necesita
transaction stages, receipts y ref-log. Indexes son vistas regenerables.

Decisión del spike: bundle-directory con manifest de bytes, store durable
completo sin vistas efímeras, restore no-merge por staging+rename y verificación
real de `MemoryStore`, reutilizado como backup. Riesgos adversariales: traversal,
symlink, TOCTOU de CURRENT, extra files, identidad relocalizada, stage omitido,
EIO parcial y manifest autocircular.
