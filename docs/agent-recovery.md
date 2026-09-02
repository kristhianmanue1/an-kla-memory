# Runbook de recuperación para agentes — resultado ambiguo de escritura

Ante timeout, `OSError` o respuesta perdida durante `commit-write-plan`,
**no reintentes a ciegas**. La ventana entre el flip de `CURRENT` y el
registro del outcome puede dejar un commit aterrizado sin outcome visible
(matriz de fallos con convergencia verificada en
`tests/test_transaction_faults.py`).

## 1. Inspecciona el transaction id (read-only)

```bash
.venv/bin/python -m an_kla --project-root . transaction inspect <UUID>
```

`inspect` no muta nada. Usa el `transaction_id` que emitiste en el commit
(`--transaction-id`); sin él no hay reconciliación posible.

## 2. Clasifica el estado

| `state` | `committed` | Significado | Decisión |
|---|---|---|---|
| `committed` | `true` | Escritura durable y auditoría completa | Termina: corre `verify` y continúa. No reescribas |
| `committed_audit_incomplete` | `true` | `CURRENT` avanzó; falta parte de la auditoría (journal/receipts) | Corre `verify`; si no degrada, el registro está y el gap es de auditoría. Repara sólo con autorización vigente |
| `durability_incomplete` | `true` | `CURRENT` avanzó pero receipts/journal quedaron sin fsync registrado | Verifica el store; decide `repair-durability` con autorización vigente o documenta el gap. El contenido está en la revisión |
| `not_committed` | `false` | La escritura no aterrizó y `CURRENT` no avanzó | Reintenta con flujo completo: relee `status`, **re-planifica** (`plan-write` → `commit-write-plan`). Nunca reutilices el plan viejo |
| `outcome_unknown` | `null` | No se puede determinar relación entre candidato y `CURRENT` | No reintentes. Corre `verify`, preserva evidencia y escala al humano |

## 3. Ejemplo real capturado (ronda adversarial 2026-09-02, issue #111)

`os._exit` justo tras `_replace_current` produjo:

```json
{
  "transaction_id": "…",
  "state": "durability_incomplete",
  "committed": true,
  "audit_state": "incomplete",
  "durability_state": "incomplete"
}
```

El store quedó consistente (`verify` OK, contenido en la revisión nueva),
pero los receipts `committed` y el journal se perdieron: el writer crasheado
no puede saber por sí solo si aterrizó — por eso existe este runbook.

## 4. Reglas firmes

- `repair-durability` es mutativo y requiere autorización vigente; no
  convierte datos legibles en prueba retroactiva de fsync:

  ```bash
  .venv/bin/python -m an_kla --project-root . transaction repair-durability <UUID>
  ```

- Después de cualquier reparación: `status` + `verify` y contrasta.
- El CAS revalida `CURRENT` dentro del lock: si cambió, el plan viejo
  muere (`current_changed`); re-lee y re-planifica. Nada se escribe dos
  veces por reintentar.
- El lock es local: la exclusión mutua no cruza máquinas.
- Tras `verify`, `archived_by_compaction` es disponibilidad histórica
  explícita, no corrupción.
