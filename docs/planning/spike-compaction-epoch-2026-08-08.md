# Spike ADR-0028: corte de epoch

Una revisión v1/v2 no puede perder ancestors/segments sin invalidar snapshot.
La opción viable es un root v3 que declara el corte, liga export+catálogo y
materializa sólo records activos. Mover bytes a otro directorio no reduce disco;
reescribir parent mantendría referencias. Por eso el cleanup ocurre después de
CURRENT y es reanudable.

La carrera crítica es reader CURRENT-old versus delete. Un lock shared/exclusive
acotado a snapshot resuelve readers locales sin leases stale; v1 restringe el
mutador a POSIX. La ronda debe atacar corte de raíz, sets de delete, replay,
faults post-CURRENT, maps lifecycle, identidad y restaurabilidad real.
