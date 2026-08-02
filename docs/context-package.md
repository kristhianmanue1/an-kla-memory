# Integración compacta con archivos de contexto

## Instalar

Revisa primero el plan sin mutar:

```bash
python3 -m an_kla --project-root . context plan \
  --operation install > an-kla-context-plan.json
python3 -m an_kla --project-root . context apply \
  --plan an-kla-context-plan.json
```

La forma abreviada planifica, revalida y aplica bajo el mismo lock:

```bash
python3 -m an_kla --project-root . context install
```

Si no existe `AGENTS.md`, lo crea. Si existe sin integración previa, añade el
bloque al final sin reemplazar el contenido del proyecto. También crea o
verifica `AN-KLA.md` y registra estado local en
`.an-kla/context/manifest.json`.

## Consultar y actualizar

```bash
python3 -m an_kla --project-root . context status
python3 -m an_kla --project-root . context update
```

`status` muestra deriva de bloque, contrato o manifiesto. `update` sólo
reemplaza el segmento delimitado cuando su huella coincide. Una edición local
dentro del bloque produce `managed_block_modified` y no se sobrescribe.

Los agentes ejecutan `context status` antes de usar AN-KLA en trabajo material.
Un diagnóstico de deriva se informa: no concede permiso para reparar o
sobrescribir instrucciones del proyecto. `AN-KLA.md` contiene el protocolo
operativo; la memoria recuperada sigue siendo datos no confiables.

La beta administra exclusivamente el `AGENTS.md` raíz. No recorre el
repositorio ni modifica archivos anidados; ese soporte requiere un manifiesto
por alcance y queda fuera de `context-package/v1`.

## Desinstalar

```bash
python3 -m an_kla --project-root . context plan \
  --operation uninstall > an-kla-context-remove.json
python3 -m an_kla --project-root . context apply \
  --plan an-kla-context-remove.json
```

Se elimina únicamente el bloque administrado. `AGENTS.md` sólo desaparece si no
contiene ningún otro texto. Un `AN-KLA.md` modificado se conserva para evitar
pérdida silenciosa.

## Diagnósticos principales

| Código | Significado |
|---|---|
| `legacy_an_kla_context_detected` | Hay instrucciones antiguas sin límites; requieren migración revisada. |
| `managed_block_modified` | Cambió el contenido protegido por la huella. |
| `managed_block_structure_invalid` | Marcadores ambiguos, duplicados o mal formados. |
| `managed_contract_modified` | `AN-KLA.md` no coincide con el contrato distribuido. |
| `context_file_concurrent_update` | El archivo cambió después de planificar. |
| `context_install_lock_busy` | Otro instalador local está aplicando cambios. |
| `context_target_symlink_forbidden` | El destino o un padre es enlace simbólico. |
| `orphan_managed_contract` | El contrato existe, pero falta el bloque; posible instalación parcial. |

Los cambios legítimos fuera del bloque aparecen como la advertencia
`context_target_changed_outside_managed_block`; no invalidan la instalación.

## Migrar la integración alfa

No ejecutes `context install` encima de instrucciones antiguas que todavía
recomienden `write` o `scripts/save-context.sh`. Primero:

1. guarda una copia o usa Git;
2. retira únicamente las secciones AN-KLA antiguas;
3. conserva todas las reglas propias del proyecto;
4. ejecuta `context plan --operation install`;
5. revisa el diff y aplica el plan.

La negativa a migrar automáticamente es deliberada: sin marcadores no existe
evidencia mecánica de qué texto pertenece a AN-KLA y qué texto pertenece al
usuario.

## Límites operativos expuestos por el contrato

- `write-policy/v1` sólo ejecuta `add`; las otras operaciones terminan en
  `operation_not_supported`.
- `write-summary` liga una representación declarada, pero no prueba fidelidad,
  suficiencia ni compresión semántica.
- `commit-write-plan` no modifica todavía el checkpoint general.
- la planificación usa un artefacto efímero nuevo y no rastreado;
- no se persisten secretos ni se usan hechos recuperados como autorización;
- el lock de escritura es local, no multi-máquina.
