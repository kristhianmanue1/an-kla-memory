# ADR-0005: alineación matemática y presupuesto de contexto

## Estado

Aceptada para diseño prospectivo. No modifica las garantías ni el formato
físico de la alfa actual.

## Contexto

La memoria opera bajo capacidad finita: distintas historias pueden terminar en
la misma representación compacta. Esas colisiones importan sólo si cambian la
acción adecuada para una consulta. Por ello las métricas de recuperación son
diagnósticas; no prueban por sí solas calidad decisional.

La alfa ya mide exactamente el contenido de `an_kla_retrieve`, pero
`an_kla_get_checkpoint` devuelve un checkpoint sin presupuesto. Un cliente que
invoque ambas herramientas no tiene todavía una garantía sobre el contexto
total que recibe el modelo.

## Decisiones

1. La compatibilidad operacional no se tratará como transitiva. Futuros
   mecanismos de deduplicación o compactación no podrán fusionar registros por
   cierre transitivo de semejanza; deberán conservar conflicto, procedencia y
   revisión explícita.
2. El presupuesto objetivo cubre el contexto completo
   \(C=A(G,W,R,N)\), no sólo el resultado de recuperación \(R\). Hasta que
   exista ese ensamblador, la alfa sólo declara presupuesto del payload de
   `an_kla_retrieve`.
3. Se implementará `context-assembly/v1` como una operación de lectura que
   distribuya un presupuesto UTF-8 exacto entre estado de trabajo y registros
   recuperados, devuelva una única envolvente de datos no confiables y declare
   cualquier framing del host que permanezca sin medir.
4. Ninguna entrega afirmará mejora decisional basándose únicamente en Recall,
   Precision o diversidad de resultados. Tal afirmación exigirá pares
   comparables que midan éxito de tarea, desacuerdo de acción o una métrica de
   distorsión explícitamente definida.
5. Un perfil modular de mochila puede evaluarse después como perfil adicional,
   nunca como sustitución implícita del recuperador actual. Sólo podrá declarar
   la cota \(1/2\) si define utilidad modular no negativa, costos positivos
   certificados, orden por densidad, prefijo greedy, mejor singleton factible
   y pruebas frente a óptimos pequeños.

## Consecuencias

El siguiente cambio funcional de memoria será el ensamblador global y sus
pruebas de presupuesto. La evaluación decisional precede cualquier afirmación
de mejora de calidad; el experimento de mochila queda después de disponer de
consultas y pares suficientes.

Esta ADR reserva el número `0005`; `0004-index-reference` continúa perteneciendo
a su rama de trabajo hasta que se integre o se descarte.

## Referencias

- [ADR-0001: revisión content-addressed y CURRENT](0001-revision-commit.md)
- [ADR-0002: alcance alfa](0002-alpha-scope.md)
- [ADR-0003: compuertas MCP](0003-mcp-worktree-and-safety-gates.md)
- Antecedente: revisión de investigación conservada fuera del repositorio de
  producto; esta ADR contiene únicamente las decisiones publicables.
