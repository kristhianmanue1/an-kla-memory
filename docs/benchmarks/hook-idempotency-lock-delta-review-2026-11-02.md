# Revisión fresca del delta de lock y flags

Fecha: 2026-11-02. Veredicto: **proceed**, limitado al delta pre-code.
Estado: OK para esta revisión estática; no acredita implementación ni pruebas.

Revisor: subagente Codex `review_lock_delta`, sesión separada, sin historial
del implementador; recibió encargo acotado y leyó fuentes y diseño rev. 3.
No se verificó diversidad de proveedor/modelo. Base observada mediante
`git rev-parse HEAD`: `0e69ae932d1d546bf28534e354ed4a2bc034dc45`;
`git status --short` mostró cambios previos en `an_kla/hook_runs.py` y
documentos nuevos del plan/diseño. No se modificó producto ni ejecutó suite/CI.
`gh issue list --state open --limit 10` devolvió #169, #168, #166, #140, #58;
`gh pr list --state open --limit 10` no devolvió PRs (ambos rc 0).

## Decisión y evidencia

1. Sustituir exclusivamente en el camino B `store.write_lock()` por
   `store_locks.write_lock(store.root)` es viable y elimina la creación de
   ancestros: el wrapper ejecuta `_make_layout()` antes de devolver el mismo
   helper (`an_kla/store.py:567–589`). El helper sólo abre el archivo de lock
   o crea su directorio inmediato, sin `parents=True`
   (`an_kla/store_locks.py:38–40,51–52,75–76`). Conserva anclaje
   `<store_root>/memory` (`an_kla/store.py:132`), exclusión, timeout en ramas
   fcntl/msvcrt y falta de reentrancia. Si falta `memory`, debe fallar;
   no recuperar mediante mkdir. No ampliar el cambio al wrapper global.
2. Requerir `O_NOFOLLOW` y `O_NONBLOCK`, sin fallback cero, corrige la falsa
   garantía de `docs/benchmarks/hook-run-idempotency-design-2026-11-02.md:169–173`:
   fstat posterior no evita que una apertura bloquee en FIFO ni que siga un
   enlace. Validar disponibilidad antes de abrir candidatos, con error
   saneado y rechazo explícito. Mantener fstat, regularidad, nlink y límites.
   Declarar pérdida de disponibilidad del camino B en plataformas sin flags;
   no cambiar el helper global de receipts como parte de este delta.

## Precisiones y riesgos que debe incorporar la implementación

- Mantener preflight y revalidación de identidad/custodia/llave bajo lock.
  La llamada directa no sustituye esos controles ni detecta por sí misma
  una bóveda desposeída. `check_custody` compara puntero e identidad
  (`an_kla/custody.py:119–145`).
- Corregir explicación de relocate: el flujo normal copia origen a staging
  (`an_kla/relocate.py:428`), publica destino, publica puntero y limpia origen
  bajo write lock (`:478–531`); no renombra el origen manteniendo su inode.
  Los locks son residuos inertes (`:581`). La seguridad depende del lock de
  origen y la revalidación, no de que el fd viaje al destino.
- El helper aún puede crear `.write.lock` dentro de un `memory` existente.
  La garantía precisa es «no recrear layout/ancestros», no cero efectos
  previos a revalidación. Su apertura ordinaria tampoco endurece el propio
  archivo de lock contra symlink/FIFO (`store_locks.py:76`); no atribuir al
  delta protección integral frente a sustituciones hostiles de rutas.
- El fallback sin fcntl/msvcrt falla inmediatamente por contención
  (`store_locks.py:38–42`), sin deadline de 10 s: no afirmar paridad universal.

## Casos de refutación para H2/H3

Pruebas pendientes del implementador: raíz `memory` desaparece entre
preflight y lock (sin recreación); relocate gana el lock y cambia custodia
antes de que el acuñador continúe (cero publicación); misma custodia por
alias conserva exclusión; ausencia simulada de cada flag rechaza sin abrir
candidatos ni publicar; FIFO/symlink se rechazan sin bloqueo. Los tests del
delta y la revisión final deben vincularse al diff implementado. Este
proceed no sustituye esos gates ni autoriza publicación.
