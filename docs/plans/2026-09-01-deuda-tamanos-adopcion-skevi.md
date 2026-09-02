# Plan: pagar la deuda de tamaños declarada por ADR-0045

La adopción de Skevi (ADR-0045) declaró techos transitorios para archivos
que exceden el default de 800 líneas o que conviene partir. Este plan
estructura esa deuda como tareas verificables. Estado de partida:
`skevi-gate.json` con límites declarados y gate en verde.

```text
TAREA T1 partir README.md al límite por defecto de 300
Consumes: `README.md`, `skevi-gate.json`
Produce: `README.md` reducido con índice recíproco, material movido a `docs/`
Steps:
  - [ ] identificar secciones de README.md que son referencia estable y
    no primera-lectura; moverlas a un documento nuevo en `docs/` y dejar
    índice recíproco; verificación: `scripts/check_sizes.py`
    termina OK con `README.md` ≤ 300.
  - [ ] retirar el límite declarado de README.md en `skevi-gate.json`;
    verificación: `scripts/check_sizes.py` sigue OK sin el techo
    de 500 y `git diff` no muestra otros cambios de configuración.
TAREA T2 partir los cinco tests grandes bajo el default de 800
Consumes: `tests/test_sealed_key_adapter.py`, `tests/test_write_commit.py`,
`tests/test_sealed_matrix.py`, `tests/test_sealed_bundle.py`,
`tests/test_store.py`, `skevi-gate.json`
Produce: tests particionados por unidad, techos retirados de `skevi-gate.json`
Steps:
  - [ ] partir cada archivo por unidad bajo prueba, sin cambiar casos ni
    aserciones, una unidad por commit; verificación:
    suite unittest (`unittest discover`) en verde tras
    cada partición.
  - [ ] retirar los cinco techos de `skevi-gate.json`; verificación:
    `scripts/check_sizes.py` OK sin techos de tests declarados.
```

Fuera de alcance aquí: `an_kla/store.py` (818 líneas en curso por
#103/#104) se resuelve en el PR que mergea ese trabajo — partirlo o
declarar techo con issue, no en este plan.
