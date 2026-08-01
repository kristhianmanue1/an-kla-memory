# AN-KLA Memory

AN-KLA Memory es una memoria local para proyectos con agentes de IA. La beta
implementa una memoria única, revisiones inmutables, recuperación lexical
bajo presupuesto, y un punto lógico de commit mediante `.an-kla/memory/refs/CURRENT`.

Estado: beta pública en GitHub, todavía no publicada en un índice de paquetes.
La disponibilidad jurídica del nombre sigue pendiente de revisión antes de
cualquier distribución comercial.

## Inicio rápido

```bash
python3 -m an_kla init
python3 -m an_kla status
python3 -m an_kla verify
python3 -m an_kla retrieve --query "estado del proyecto" --budget 1200
```

La versión de desarrollo incluye la operación experimental de lectura
`context-assembly/v1`:

```bash
python3 -m an_kla assemble-context \
  --query "estado del proyecto" \
  --new-information "solicitud actual" \
  --budget 2400
```

La salida completa, no sólo los registros recuperados, queda acotada en bytes
UTF-8. Consulta [ADR-0006](docs/architecture/0006-context-assembly-v1.md).

La rama de desarrollo incluye además la escritura gobernada en dos pasos
`plan-write` / `commit-write-plan`. El plan se reconstruye dentro del lock antes
de mover `CURRENT`; consulta la
[guía del CLI de escritura](docs/write-policy-cli.md). El comando histórico
`write` se conserva por compatibilidad, pero no ofrece esta garantía.

Lee [AN-KLA.md](AN-KLA.md) antes de instalar o integrar AN-KLA en otro proyecto.

## Contexto compacto para agentes

AN-KLA puede añadir un segmento delimitado a un `AGENTS.md` existente sin
adueñarse del resto del archivo. El bloque breve apunta a `AN-KLA.md`; manifiesto
y respaldos locales viven bajo `.an-kla/context/`.

```bash
python3 -m an_kla --project-root . context plan \
  --operation install > an-kla-context-plan.json
python3 -m an_kla --project-root . context apply \
  --plan an-kla-context-plan.json
python3 -m an_kla --project-root . context status
```

También existe el atajo explícito `context install`. Consulta la
[guía de integración](docs/context-package.md) y
[ADR-0009](docs/architecture/0009-managed-agent-context-v1.md).

## Fundamentos matemáticos

La separación entre teoremas condicionales, garantías implementadas y trabajo
pendiente se documenta en [Fundamentos matemáticos de AN-KLA Memory](docs/mathematical-foundations.md).
La decisión arquitectónica asociada está en
[ADR-0005](docs/architecture/0005-mathematical-alignment.md).

La recuperación usa `scan-fallback/v1` de forma predeterminada. El perfil
experimental `sqlite-fts5/v1` sólo se activa explícitamente y requiere construir
un índice ligado a la revisión actual; consulta
[ADR-0004](docs/architecture/0004-index-reference.md).

## Límites de la beta

- admite una sola memoria activa;
- no coordina varios equipos;
- no prueba identidad, autoría ni verdad;
- no publica telemetría;
- instala un bloque neutral en `AGENTS.md`, pero aún no adapta archivos de
  proveedores ni implementa multi-memoria;
- conserva objetos conflictivos en cuarentena diagnóstica; no ejecuta GC ni
  compactación en la beta.

## Licencia

Este proyecto se distribuye bajo [Apache License 2.0](LICENSE).
