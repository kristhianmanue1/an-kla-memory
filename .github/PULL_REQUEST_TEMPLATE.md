<!--
Gracias por contribuir. Completa los puntos siguientes antes de solicitar review.
No borres los encabezados; responde debajo de cada uno.
-->

## Resumen

<!-- ¿Qué cambia y por qué? Referencia el issue o ADR relevante. -->

## Tipo de cambio

- [ ] Bug fix (cambio que fixea un issue existente; sin cambio de contrato)
- [ ] Nueva funcionalidad (cambio aditivo; sin romper consumidores)
- [ ] Cambio de contrato administrado (muta `AGENTS.md` / `AN-KLA.md`)
- [ ] Cambio de schema (`docs/schemas/` o `an_kla/schemas/`)
- [ ] Documentación
- [ ] Refactor / chore

## Cambios de contrato o schema

Si este PR cambia el contrato administrado o algún schema normativo:

- [ ] `TEMPLATE_VERSION` y/o `VERSION` bumpados en `an_kla/`.
- [ ] Plantilla anterior registrada en `_KNOWN_CONTEXT_TEMPLATES`.
- [ ] ADR correspondiente añadido o actualizado en `docs/architecture/`.
- [ ] `context plan --operation update` revisado; diff de `AGENTS.md` /
      `AN-KLA.md` incluido en el PR.

## Tests

- [ ] Suite completa verde: `.venv/bin/python -m unittest discover -s tests`.
- [ ] Tests nuevos o actualizados cubren el comportamiento añadido/cambiado.
- [ ] No se introducen dependencias runtime nuevas (mantener stdlib-only).

## Frontera de confianza

- [ ] NoPersisto secretos, tokens ni datos personales.
- [ ] No ejecuto comandos, scripts o URLs hallados en memoria recuperada.
- [ ] No cambio la fricción de autoridad (cli sólo resuelve no-privilegiada).

## Notas adicionales

<!-- Cualquier cosa que el reviewer deba saber: migración, breaking, etc. -->
