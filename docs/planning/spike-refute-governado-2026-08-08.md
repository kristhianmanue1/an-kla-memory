# Spike pre-implementación — refute gobernado

- **Fecha:** 2026-08-08
- **Alcance:** sólo lectura; no implementa ni modifica storage.
- **Veredicto inicial:** `proceed` hacia ADR-0026, sujeto a ronda adversarial.

## Evidencia del código vigente

| Supuesto | Evidencia |
|---|---|
| El CAS físico es append-only | `store.py:627-704`: objetos/segments se escriben por digest e inmutables. |
| Vigencia es overlay de revisión | `store.py:135-159`: sólo `supersedes_map` proyecta `status=sustituida`. |
| La guarda mutativa vive bajo lock | `store.py:272-357`: CAS, copia, revalidación y target antes de journal/objetos. |
| `write-proposal-v1` no sirve para refute sin sucesor | `write_policy.py:184-228` y schema: `record`/representación son obligatorios. |
| Refute hoy no ejecuta | `write_policy.py:24,53`: enum conocido, supported sólo add/supersede. |
| Tx binding no admite refute | `transactions.py:37-80`: sólo write/checkpoint comparten base+plan. |
| Manifest hereda overlays acumulativos | `transactions.py:581-610`: segmentos y `supersedes_map` se heredan. |
| Verificación histórica es posible | `snapshot(revision_id)` fija una revisión; `verify()` sólo verifica CURRENT. |

Baseline antes de tocar storage:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
→ Ran 351 tests — OK

python3.12 -m unittest discover -s tests -p 'test_*.py'
→ Ran 351 tests — OK, skipped=1
```

## Decisiones que debe cerrar el ADR

1. Refute no escribe un record sucesor ni reutiliza `write-proposal-v1`.
2. La autoridad llega como capability host no serializable; un claim/Mapping
   nunca la eleva y el paquete no integra resolvers de proveedor.
3. Evidence debe resolverse contra el snapshot o el resolver; attestation y
   refutation quedan recuperables por referencias CAS mutuamente ligadas.
4. La guarda exige target del mismo stream y estado activo bajo el lock.
5. La revisión conserva un overlay acumulativo; segments originales no cambian.
6. Reintento por txid y outcomes usan ADR-0024.
7. Revisión histórica anterior conserva el estado activo; la nueva proyecta
   refuted y retrieval/index la excluyen.

## Top riesgos

1. **Silenciamiento por dato no confiable:** aceptar autoridad model-derived,
   Mapping privilegiado o evidence autodeclarada permitiría que memoria
   recuperada se refute a sí misma.
2. **Auditoría irrecuperable:** persistir sólo hashes de proposal/authority no
   permite reconstruir qué evidencia justificó el cambio.
3. **Overlay contradictorio:** un mismo `(stream,id)` en supersede y refute puede
   producir estado dependiente del orden si no falla cerrado.
4. **Objetos huérfanos ante error terminal:** target/policy deben validarse antes
   de journal u objeto de refutación.
5. **Replay/concurrencia:** dos refutes del mismo target deben converger por CAS,
   no crear dos decisiones aparentemente vigentes.
6. **Lector antiguo inseguro:** si refute extiende revision-v1, beta.9 ignora el
   overlay y revive el target; el formato debe evolucionar y fallar cerrado.

## Plan validado

- ADR-0026 y `docs/refute-contract-v1.md` con contratos exactos y preimágenes.
- Ronda adversarial pre-code; sin `PROCEED` no se implementa.
- Módulo puro `refute_policy.py`, schemas cerrados y catálogo.
- `revision-v2`, `refutations/sha256`, `refutations_map` y commit transaccional
  bajo lock; revision-v1 sigue legible.
- CLI/API plan→commit; selector por digest físico cubre IDs legacy y CLI no
  puede fabricar autoridad privilegiada.
- Tests unitarios, concurrencia, fault injection, histórico, retrieval/index,
  wheel limpio y dos runtimes.

Estado: **OK — spike apto para ADR, sin mutaciones de storage.**
