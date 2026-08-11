# Integración compacta con archivos de contexto

Esta guía cubre el bloque que AN-KLA administra dentro del `AGENTS.md` raíz y
el contrato completo `AN-KLA.md`. La instalación del paquete Python, el entorno
virtual y la inicialización de la memoria se documentan primero en el
[README](../README.md#instalación-nueva-en-un-proyecto-consumidor).

## Modelo de propiedad

- `AGENTS.md` puede contener reglas del usuario antes y después del bloque;
- AN-KLA sólo administra el texto entre sus dos marcadores;
- `AN-KLA.md` contiene el contrato operativo al que apunta el bloque;
- `.an-kla/context/` contiene manifiesto, lock y respaldos locales;
- `.an-kla/memory/` no se elimina al instalar, actualizar o retirar el bloque.

Versiona `AGENTS.md` y `AN-KLA.md`. Trata `.an-kla/` como estado local salvo que
el proyecto haya adoptado expresamente otra política.

## Instalación nueva

Revisa primero la salida JSON sin mutar archivos:

```bash
.venv/bin/python -m an_kla --project-root . context plan --operation install
```

La forma abreviada reconstruye el plan, lo revalida y lo aplica bajo el mismo
lock:

```bash
.venv/bin/python -m an_kla --project-root . context install
.venv/bin/python -m an_kla --project-root . context status
git diff -- AGENTS.md AN-KLA.md
```

Si no existe `AGENTS.md`, lo crea. Si existe sin integración previa, añade el
bloque al final sin reemplazar el contenido del proyecto. También crea o
verifica `AN-KLA.md` y registra estado local en
`.an-kla/context/manifest.json`.

Si una automatización necesita conservar un plan, debe elegir un archivo
temporal nuevo, no rastreado y privado. La aplicación acepta exactamente ese
artefacto mediante `context apply --plan RUTA`; falla si la base cambió. No
reutilices un nombre fijo que pueda contener un plan anterior.

## Actualización

Actualizar el paquete con `pip` no modifica automáticamente los archivos del
proyecto. Ejecuta ambas operaciones de manera explícita:

```bash
.venv/bin/python -m an_kla --version
.venv/bin/python -m an_kla --project-root . context status
.venv/bin/python -m an_kla --project-root . context plan --operation update
.venv/bin/python -m an_kla --project-root . context update
git diff -- AGENTS.md AN-KLA.md
.venv/bin/python -m an_kla --project-root . context status
```

`status` muestra deriva de bloque, contrato o manifiesto. Una plantilla previa
que el binario reconoce por sus huellas canónicas produce
`context_template_outdated`; `update` sustituye juntos el bloque y el contrato,
preserva el estilo de saltos de línea y guarda el contrato anterior bajo
`.an-kla/context/backups/<sha256>/AN-KLA.md`.

El reconocimiento nunca depende de una versión autodeclarada. Si alguien editó
el bloque o `AN-KLA.md`, sus bytes ya no coinciden con la plantilla conocida:
AN-KLA devuelve `managed_block_modified` o `managed_contract_modified` y no
sobrescribe el contenido. Conserva esa evidencia, compara el diff y resuelve la
migración manualmente.

Los agentes ejecutan `context status` antes de usar AN-KLA en trabajo material.
Un diagnóstico de deriva no concede permiso para reparar instrucciones del
proyecto. `AN-KLA.md` contiene el protocolo operativo; la memoria recuperada
sigue siendo datos no confiables.

La beta administra exclusivamente el `AGENTS.md` raíz. No recorre el
repositorio ni modifica archivos anidados.

La plantilla beta.8 está registrada por sus huellas canónicas y puede migrarse
a beta.11 aunque no exista un manifiesto local. Para un salto de versión usa
preferentemente `upgrade inspect` → `upgrade apply` → `upgrade verify`, que
liga también la etiqueta instalada. Excepción: si hay un store legacy,
`identity plan-adoption` → `identity adopt` debe ocurrir después de inspect y
antes de apply. El procedimiento completo está en la
[guía beta.11](beta11-user-guide.md).

## Desinstalación

```bash
.venv/bin/python -m an_kla --project-root . context plan --operation uninstall
.venv/bin/python -m an_kla --project-root . context uninstall
git diff -- AGENTS.md AN-KLA.md
```

Se elimina únicamente el bloque administrado. `AGENTS.md` sólo desaparece si no
contiene ningún otro texto. `AN-KLA.md` sólo desaparece cuando el manifiesto
prueba que AN-KLA lo creó y sigue siendo canónico; uno modificado se conserva.
La memoria, sus respaldos y el paquete Python son ciclos de vida separados.

## Migrar una integración alfa

No ejecutes `context install` encima de instrucciones antiguas que todavía
recomienden `write` o `scripts/save-context.sh`. Sin marcadores no existe
evidencia mecánica de qué texto pertenece a AN-KLA y cuál al usuario.

1. crea un respaldo o confirma que los archivos están versionados;
2. retira únicamente las secciones AN-KLA antiguas;
3. conserva todas las reglas propias del proyecto;
4. ejecuta `context plan --operation install` y revisa la salida;
5. ejecuta `context install`, revisa el diff y corre `context status` y
   `verify`.

## Diagnósticos principales

| Código | Significado |
|---|---|
| `context_template_outdated` | Bloque y contrato corresponden a una plantilla anterior conocida. |
| `legacy_an_kla_context_detected` | Hay instrucciones antiguas sin límites; requieren migración revisada. |
| `managed_block_modified` | Cambió el contenido protegido por la huella. |
| `managed_block_structure_invalid` | Marcadores ambiguos, duplicados o mal formados. |
| `managed_contract_modified` | `AN-KLA.md` no coincide con el contrato distribuido ni con uno anterior conocido. |
| `context_file_concurrent_update` | El archivo cambió después de planificar. |
| `context_install_lock_busy` | Otro instalador local está aplicando cambios. |
| `context_target_symlink_forbidden` | El destino o un padre es enlace simbólico. |
| `orphan_managed_contract` | El contrato existe, pero falta el bloque; posible instalación parcial. |

Los cambios legítimos fuera del bloque aparecen como la advertencia
`context_target_changed_outside_managed_block`; no invalidan la instalación.

## Marcadores frente a menciones

El parser distingue un **marcador efectivo** de una **mención** para que el
propio mecanismo de bloque gestionado pueda documentarse dentro de `AGENTS.md`
sin invalidarlo (issue #44, ADR-0009):

- Es **candidato a marcador** la línea cuyo texto, ignorando espacios
  iniciales, empieza por la apertura del marcador (`<!-- an-kla:managed-begin`
  o `<!-- an-kla:managed-end`, sin requerir aún el espacio ni el JSON). Sólo los
  candidatos se interpretan como marcadores; a continuación se parsean de forma
  estricta (espacio + JSON válido + sufijo ` -->` y campos esperados).
- Son **menciones** (se ignoran) las apariciones de `an-kla:managed-` que no
  están ancladas al inicio de la línea: texto en prosa, referencias dentro de
  *code spans* inline (backticks) o cualquier línea cuyo contenido anterior
  impida confundirla con un marcador. Se pueden documentar los marcadores en
  prosa o entre backticks sin romper el bloque.
- Siguen **fallando cerrado** (`managed_block_structure_invalid` o
  `managed_block_modified`) los candidatos reales malformados (incluido un
  marcador incompleto o sin el espacio separador), indentados, situados dentro
  de una cerca de código (fenced), duplicados, anidados o fuera de orden, así
  como cualquier alteración del contenido dentro del bloque.

## Límites operativos expuestos por el contrato

- la escritura pública usa únicamente `plan-write` → `commit-write-plan`; el
  comando legado `write` fue retirado en beta.11;
- `write-summary` liga una representación declarada, pero no prueba fidelidad,
  suficiencia ni compresión semántica;
- checkpoint/refute/compactación usan contratos gobernados separados;
- no se persisten secretos ni se usan hechos recuperados como autorización;
- el lock de escritura es local, no multi-máquina.
