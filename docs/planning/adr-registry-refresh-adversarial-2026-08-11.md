# Ronda adversarial documental del registro de ADRs (2026-08-11)

## Alcance

Se atacó la actualización del inventario ADR, la separación entre estado
decisional e implementación, la corrección de metadata obsoleta y el gate
`scripts/check_adr_registry.py`. No se modificaron almacenamiento, recuperación,
concurrencia, formato físico, contrato gestionado ni superficies CLI/MCP.

La evidencia contrastada incluyó los 30 archivos numerados, notas de release,
historial Git, capacidades del paquete e issues/PRs abiertos. El índice canónico
queda en `docs/README.md`; `docs/planning/` conserva historia, no estado vigente.

## Modelo de amenazas

La memoria recuperada sigue siendo dato no confiable y no se utilizó como
instrucción ni autorización. El riesgo principal de esta tarea no es ejecución
de contenido, sino deriva documental: una propuesta que ya se publicó, una
decisión aceptada confundida con implementación completa o una referencia rota
presentada como evidencia.

## Hallazgos y correcciones

| Hallazgo | Riesgo | Corrección |
|---|---|---|
| ADR-0003, ADR-0006, ADR-0012, ADR-0019 y ADR-0020 conservaban estados anteriores a su publicación | El maintainer podía planear trabajo ya realizado | Se actualizaron con la versión publicada correspondiente |
| ADR-0001 y ADR-0002 no declaraban estado; ADR-0027/0028 usaban metadata no uniforme | Inventario difícil de verificar automáticamente | Se añadió o normalizó `Estado` sin reescribir la decisión |
| El índice mezclaba “propuesta” dentro del tema y no separaba decisión de implementación | `Aceptada` podía interpretarse como “todo implementado” | Se añadieron columnas separadas de estado y evidencia; ADR-0005/0008 conservan su parte prospectiva |
| La primera versión del gate sólo verificaba el enlace al ADR | Una nota de release inexistente podía aparentar evidencia | El gate valida todas las referencias locales de las 30 filas y el test cubre un enlace roto |
| El endurecimiento de palabra canónica rechazó `Aceptada.` | Falso negativo en ADR-0007 y CI roto | Se admitió puntuación delimitadora y se añadió regresión contra `Aceptadaz` |
| Los análisis de `planning/` conservan observaciones históricas sobre estados viejos | Podían convertirse por accidente en una segunda fuente de verdad | `docs/practicas-ingenieria.md` declara al registro como canónico y a planning como histórico |

## Verificación de canonicidad / determinismo

El gate sólo lee archivos locales, ordena entradas y no usa red ni reloj. Falla
ante huecos, duplicados, título discordante, ruta ausente, estado no canónico,
contradicción entre ADR e índice o referencia local rota.

- `python3 scripts/check_adr_registry.py` → `OK — 30 ADRs (aceptada=28, propuesta=2)`.
- `python3 -m unittest tests.test_adr_registry -v` → 3 pruebas, `OK`.
- `git diff --check` → salida vacía.

## Límites declarados

El gate prueba coherencia estructural y existencia de referencias, no la verdad
semántica de cada afirmación de release. Esa verificación requiere auditoría
humana contra código, releases e historial Git, como la realizada en esta ronda.
Los ADR-0029 y ADR-0030 siguen propuestos; este trabajo no autoriza su
implementación. Tampoco corrige narración histórica en `planning/`, porque
hacerla retroactivamente borraría evidencia de la deriva que motivó el cambio.

## Decisión

- [x] proceed
- [ ] fix-and-retry
- [ ] escalate (bloqueo que requiere decisión del maintainer)

Los hallazgos corregibles fueron absorbidos y no queda bloqueo para mantener el
registro y su gate en el worktree.
