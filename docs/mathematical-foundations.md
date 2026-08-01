# Fundamentos matemáticos de AN-KLA Memory

Este documento fija el modelo matemático público de AN-KLA Memory. Distingue entre propiedades demostradas bajo hipótesis explícitas, garantías implementadas y objetivos todavía pendientes. No convierte una aspiración de diseño en una garantía del producto.

## 1. La memoria acotada necesariamente pierde información

Sea \(\Sigma\) un alfabeto finito y sea \(B_M\) el presupuesto máximo de una representación de memoria. El conjunto de estados posibles satisface

\[
\mathcal{S}\subseteq\Sigma^{\leq B_M},
\qquad
|\mathcal{S}|\leq\sum_{i=0}^{B_M}|\Sigma|^i<\infty.
\]

Si el conjunto de historiales posibles \(\mathcal{H}\) tiene cardinalidad mayor que \(\mathcal{S}\), toda función de compresión

\[
\kappa:\mathcal{H}\rightarrow\mathcal{S}
\]

es no inyectiva. Por el principio del palomar, existen \(H_1\neq H_2\) tales que

\[
\kappa(H_1)=\kappa(H_2).
\]

Por tanto, una memoria finita no puede preservar todos los detalles de historiales arbitrariamente ricos. Este resultado no afirma que toda colisión sea dañina: una colisión importa cuando los historiales comprimidos requieren decisiones incompatibles para una consulta relevante.

## 2. Estado, recuperación y ensamblado

Modelamos el estado operativo de un agente en el instante \(t\) como

\[
X_t=(G_t,W_t,M_t,L_t),
\]

donde \(G_t\) representa objetivos, \(W_t\) el estado de trabajo, \(M_t\) la memoria persistente y \(L_t\) el registro de evidencia.

Ante una consulta \(q_t\), el contexto efectivo es

\[
C_t=A\bigl(G_t,W_t,R(q_t,M_t),N_t\bigr),
\]

donde \(R\) recupera candidatos, \(N_t\) contiene información nueva y \(A\) ensambla el contexto final. La restricción correcta es global:

\[
|C_t|\leq B.
\]

Limitar sólo la salida de \(R\) no demuestra que el contexto completo respete \(B\). La versión actual de AN-KLA aplica un presupuesto exacto en bytes UTF-8 al resultado de recuperación; todavía no ofrece una garantía global sobre \(G_t\), \(W_t\), la recuperación y \(N_t\) ensamblados conjuntamente.

## 3. Objetivo: reducir distorsión decisional

Sea \(U(a,H,q)\) la utilidad de ejecutar la acción \(a\) con historial real \(H\) ante la consulta \(q\), y sea \(\pi(S,q)\) la acción elegida usando el estado de memoria \(S\). Definimos la distorsión decisional como

\[
D(H,S;q)=\max_a U(a,H,q)-U\bigl(\pi(S,q),H,q\bigr).
\]

El objetivo de una política de memoria es minimizar, bajo presupuesto, la distorsión esperada:

\[
\min_{\kappa,R,A}\mathbb{E}_{(H,q)}
\left[D\bigl(H,\kappa(H);q\bigr)\right]
\quad\text{sujeto a}\quad |C_t|\leq B.
\]

Recall, precision y bytes recuperados son métricas diagnósticas, no sustitutos de este objetivo. Una afirmación de mejora decisional requiere evaluaciones emparejadas de la acción o tarea con y sin la memoria examinada.

## 4. Compatibilidad operacional

Para una tolerancia \(\varepsilon\), dos historiales son compatibles ante \(q\) si existe al menos una acción que es \(\varepsilon\)-óptima en ambos:

\[
H_1\sim_{q,\varepsilon}H_2
\iff
\exists a:\ U(a,H_i,q)\geq\max_{a'}U(a',H_i,q)-\varepsilon,
\quad i\in\{1,2\}.
\]

Esta relación puede no ser transitiva. De \(H_1\sim H_2\) y \(H_2\sim H_3\) no se sigue necesariamente \(H_1\sim H_3\). En consecuencia, una futura compactación no deberá fusionar hechos mediante cierre transitivo sin demostrar que conserva una acción aceptable para todo el grupo.

## 5. Teorema condicional para selección modular

Considérese un conjunto elegible \(E\), utilidad modular no negativa

\[
U(S)=\sum_{i\in S}u_i,\qquad u_i\geq0,
\]

costos certificados positivos \(c_i>0\) y presupuesto \(B\). El problema es

\[
\max_{S\subseteq E}\sum_{i\in S}u_i
\quad\text{sujeto a}\quad\sum_{i\in S}c_i\leq B.
\]

Ordene los elementos por densidad \(u_i/c_i\), con desempate determinista. Sea \(P\) el prefijo factible producido por ese orden y sea \(j^*\) el mejor singleton factible. El algoritmo que devuelve el mejor de \(P\) y \(\{j^*\}\) satisface

\[
U(\mathrm{ALG})\geq\frac{1}{2}U(\mathrm{OPT}).
\]

### Esbozo de prueba

La relajación fraccionaria se obtiene tomando el prefijo \(P\) y, como máximo, una fracción del primer elemento que ya no cabe, denotado \(j\). Por ello,

\[
U(\mathrm{OPT})\leq U(\mathrm{OPT}_{\mathrm{frac}})\leq U(P)+u_j.
\]

El elemento \(j\) debe ser un singleton factible dentro del mismo dominio; de otro modo, el último término no puede compararse con \(j^*\). Como \(u_j\leq u_{j^*}\),

\[
U(\mathrm{OPT})\leq U(P)+u_{j^*}
\leq 2\max\{U(P),u_{j^*}\}.
\]

La cota depende de todas sus hipótesis: mismo conjunto elegible para algoritmo y óptimo, utilidad modular no negativa, costos positivos que coinciden con la restricción evaluada, factibilidad del singleton y orden determinista. No demuestra calidad respecto de la distorsión decisional, no representa complementariedad ni redundancia y no aplica automáticamente a costos aproximados.

El recuperador léxico actual de AN-KLA no implementa este algoritmo ni reclama esta aproximación. El teorema delimita un perfil futuro verificable, no una garantía presente.

## 6. Bytes y tokens

Un límite exacto de bytes UTF-8 es reproducible e independiente del proveedor:

\[
\sum_{i\in R}|\operatorname{UTF8}(i)|\leq B_{\mathrm{bytes}}.
\]

Esto no equivale a una cota exacta de tokens para un tokenizador específico. Una garantía de tokens requiere integrar y fijar ese tokenizador, o usar una cota superior demostrada para el dominio correspondiente.

## 7. Estado de las garantías

| Propiedad | Estado |
|---|---|
| Revisiones inmutables y puntero `CURRENT` | Implementada |
| Escritura serializada y recuperación diagnosticable | Implementada |
| Presupuesto exacto UTF-8 en recuperación | Implementada |
| Presupuesto global del contexto ensamblado en bytes UTF-8 | Implementado en `context-assembly/v1` |
| Presupuesto global exacto en tokens | Contrato `cost-model/v1`; implementación pendiente |
| Medición emparejada de distorsión decisional | Pendiente |
| Selector modular con aproximación \(1/2\) | Teorema condicional; no implementado |
| Compactación respetando compatibilidad operacional | Invariante de diseño; compactación no implementada |

Las decisiones de adopción y alcance están registradas en [ADR-0005](architecture/0005-mathematical-alignment.md).
