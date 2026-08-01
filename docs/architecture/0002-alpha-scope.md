# ADR-0002: alcance alfa

La alfa implementa una sola memoria activa, objetos inmutables, locks locales,
CAS, recuperación lexical y contexto con presupuesto en bytes. Multi-memoria,
instaladores de adaptadores, firma externa, compactación y sincronización quedan
fuera de alcance.

La cuarentena es solo diagnóstica en esta fase: admite hasta 128 objetos o 64 MiB
y no ejecuta garbage collection automático. Los leases existen como directorio
reservado, pero no son necesarios hasta que se diseñe compactación.

La licencia y la disponibilidad jurídica del nombre AN-KLA se revisarán antes de
publicar o distribuir el proyecto.
