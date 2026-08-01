# AN-KLA Memory

AN-KLA Memory es una memoria local para proyectos con agentes de IA. Su primera
alfa implementa una memoria única, revisiones inmutables, recuperación lexical
bajo presupuesto, y un punto lógico de commit mediante `.an-kla/memory/refs/CURRENT`.

Estado: alfa local, no publicada. El nombre y la licencia permanecen pendientes
de revisión antes de cualquier distribución.

## Inicio rápido

```bash
python3 -m an_kla init
python3 -m an_kla status
python3 -m an_kla verify
```

Lee [AN-KLA.md](AN-KLA.md) antes de instalar o integrar AN-KLA en otro proyecto.

## Límites de la alfa

- admite una sola memoria activa;
- no coordina varios equipos;
- no prueba identidad, autoría ni verdad;
- no publica telemetría;
- no implementa aún instaladores de adaptadores ni multi-memoria.
- conserva objetos conflictivos en cuarentena diagnóstica; no ejecuta GC ni
  compactación en la alfa.
