# Plantilla — bloque de registro de contexto

> Norma completa: `../docs/estandar-diseno-software-github.md` §3.5.
> Se usa al crear `AGENTS.md` o `CLAUDE.md` en un proyecto que no los tenía
> (guía F2 §2). Copia el bloque tal cual, ajusta las rutas si cambian los
> nombres de archivo en `.skevi/`, y pégalo al final del archivo de
> instrucciones — no lo mezcles con contenido propio del proyecto en la
> misma sección.

```markdown
<!-- skevi:registry:start -->
[skevi]
usage        = .skevi/usage-guide.md
architecture = .skevi/architecture-overview.md
standard     = docs/estandar-diseno-software-github.md
guide        = docs/ai-agent-guide/00-INDICE.md
<!-- skevi:registry:end -->
```

Reglas al copiarlo:

- Crea `.skevi/usage-guide.md` y `.skevi/architecture-overview.md` **en el
  mismo paso**, antes de correr el gate — un link roto es `BLOQ`.
- Si el proyecto no copió el estándar/guía completos a `docs/`, ajusta esas
  dos rutas a donde realmente vivan, o bórralas si el proyecto sólo adopta
  el patrón de registro sin el resto del método.
- No agregues claves especulativas. Cada línea del bloque apunta a un
  archivo que existe y que alguien va a leer.
