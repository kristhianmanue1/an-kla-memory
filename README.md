# AN-KLA Memory

AN-KLA Memory es una memoria local para proyectos con agentes de IA. Su primera
alfa implementa una memoria única, revisiones inmutables, recuperación lexical
bajo presupuesto, y un punto lógico de commit mediante `.an-kla/memory/refs/CURRENT`.

Estado: alfa pública en GitHub, todavía no publicada en un índice de paquetes.
La disponibilidad jurídica del nombre sigue pendiente de revisión antes de
cualquier distribución comercial.

## Inicio rápido

```bash
python3 -m an_kla init
python3 -m an_kla status
python3 -m an_kla verify
python3 -m an_kla retrieve --query "estado del proyecto" --budget 1200
```

La rama experimental `feat/context-assembly-v1` añade una operación global de
lectura:

```bash
python3 -m an_kla assemble-context \
  --query "estado del proyecto" \
  --new-information "solicitud actual" \
  --budget 2400
```

La salida completa, no sólo los registros recuperados, queda acotada en bytes
UTF-8. Consulta [ADR-0006](docs/architecture/0006-context-assembly-v1.md).

Lee [AN-KLA.md](AN-KLA.md) antes de instalar o integrar AN-KLA en otro proyecto.

## Fundamentos matemáticos

La separación entre teoremas condicionales, garantías implementadas y trabajo
pendiente se documenta en [Fundamentos matemáticos de AN-KLA Memory](docs/mathematical-foundations.md).
La decisión arquitectónica asociada está en
[ADR-0005](docs/architecture/0005-mathematical-alignment.md).

La recuperación usa `scan-fallback/v1` de forma predeterminada. El perfil
experimental `sqlite-fts5/v1` sólo se activa explícitamente y requiere construir
un índice ligado a la revisión actual; consulta
[ADR-0004](docs/architecture/0004-index-reference.md).

## Límites de la alfa

- admite una sola memoria activa;
- no coordina varios equipos;
- no prueba identidad, autoría ni verdad;
- no publica telemetría;
- no implementa aún instaladores de adaptadores ni multi-memoria.
- conserva objetos conflictivos en cuarentena diagnóstica; no ejecuta GC ni
  compactación en la alfa.

## Licencia

Este proyecto se distribuye bajo [Apache License 2.0](LICENSE).
