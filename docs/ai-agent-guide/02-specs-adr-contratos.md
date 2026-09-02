# 02 — Specs, ADRs y contratos (F1)

> **Propósito:** fijar el diseño antes de construir. Entrada: la salida de F0
> (`01-analisis-y-requerimientos.md`). Salida: decisiones y contratos que el
> cascarón (F2) y la implementación (F3) deben respetar.

## 1. Qué se decide aquí y qué no

F1 decide: estructura de componentes, fronteras, formatos de datos,
interfaces, decisiones con alternativas. F1 **no** escribe implementación ni
elige detalles internos reversibles (nombres de variables, helpers
privados). Si una decisión es barata de cambiar después, no la fijes aquí.

## 2. Especificación (spec)

### 2.1 Cuándo escribirla

Siempre que el proyecto tenga más de un componente, una frontera externa o
un requisito no trivial. Para un script simple, los REQ-* de F0 con sus
criterios bastan: no dupliques.

### 2.2 Formato

```text
SPEC-<n> [cubre: REQ-<n>, REQ-<m>]
Comportamiento: <qué hace el sistema, observable desde fuera>
Entradas: <qué recibe, con formato y rango válido>
Salidas: <qué produce, con formato>
Errores: <qué falla, cómo se reporta, qué estado queda>
Casos:
  - DADO <contexto> CUANDO <acción> ENTONCES <resultado verificable>
Invariantes: <lo que debe cumplirse siempre, en todo caso>
```

Reglas:

- Toda spec cubre al menos un REQ; todo REQ imprescindible tiene spec.
- Los casos DADO/CUANDO/ENTONCES se traducirán a tests en F3. Si un caso no
  puede convertirse en test, está mal escrito.
- Los errores son parte de la spec, no un apéndice. Define qué estado queda
  tras cada fallo, aplicando el principio 5 de
  `../estandar-diseno-software-github.md` §1.

## 3. ADR — registro de decisiones

### 3.1 Cuándo crear uno

Crea un ADR cuando la decisión cumple alguna de: tiene alternativas reales
con costes distintos; es cara o imposible de revertir; introduce una
dependencia o frontera nueva; alguien preguntará "¿por qué está así?" en
seis meses. No crees ADRs para decisiones obvias o reversibles.

### 3.2 Formato

```text
ADR-<n>: <título de la decisión>
Estado: <propuesto | aceptado | rechazado | sustituido por ADR-<m>>
Contexto: <qué obliga a decidir; referencia REQ-*/SPEC-*>
Decisión: <qué se decidió, en una frase>
Alternativas descartadas:
  - <opción>: <por qué no>
Consecuencias: <qué gana y qué pierde; qué queda prohibido u obligado>
```

Reglas:

- Los ADR son inmutables: si la decisión cambia, se crea uno nuevo que
  sustituye al anterior.
- Una alternativa sin razón de descarte no cuenta; si no hay alternativas
  reales, no había decisión que registrar.
- Criterio de desempate (del estándar): más simple → más reversible → menor
  superficie de seguridad → sin dependencias nuevas.

### 3.3 Cierre de ADR

Cuando un ADR pasa a estado `aceptado` y se implementa, el cambio que
materializa la decisión **incluye la actualización del header** del ADR con
el commit o versión de implementación. Un ADR que dice "implementación no
iniciada" mientras un commit posterior ya lo aplicó es una deriva
verificable: `BLOQ`.

Checklist de cierre (obligatorio para ADRs que modifican norma o guía):

- [ ] Header actualizado a `implementado` con referencia al commit o PR;
- [ ] `docs/adr/00-INDICE.md` actualizado con fecha, origen e implementación;
- [ ] `project-manifest.yaml` revisado si el ADR resuelve un ítem de
      `pospuesto`;
- [ ] Referencias cruzadas verificadas con `grep -r` sobre el repositorio;
- [ ] Si procede de una propuesta, el material de deliberación se movió a
      `docs/history/` en el mismo cambio.

Un ADR sin cierre completo no cierra el gate de F1: la decisión existe, pero
  el rastro no.

## 4. Contratos de interfaz

### 4.1 Qué necesita contrato

Toda frontera del sistema: API, CLI, formato de archivo, esquema de datos,
evento, integración externa. Lo interno a un componente no lleva contrato
formal: eso es sobre-ingeniería.

### 4.2 Formato

```text
CONTRATO: <nombre de la interfaz> v<n>
Entrada:
  <campo>: <tipo> [<obligatorio|opcional>] [rango/formato] — <significado>
Salida:
  <campo>: <tipo> — <significado>
Errores:
  <código>: <condición que lo produce> — <estado en que queda el sistema>
Invariantes:
  - <propiedad que siempre se cumple>
Compatibilidad: <qué cambios son compatibles hacia atrás y cuáles exigen v<n+1>>
```

Reglas:

- Los contratos son cerrados: se acepta lo declarado, se rechaza lo demás.
  Nada de campos libres sin límite ni payload opacos en fronteras internas.
- Validar en la frontera, una sola vez, contra el contrato.
- Toda entrada no confiable que cruce una frontera hacia ejecución (shell,
  SQL, plantillas) se parametriza; nunca se concatena.
- Versionar desde el primer consumidor externo. Un cambio incompatible sin
  subir versión es un bug de diseño.

## 5. Modelo de estados (cuando aplique)

Si el sistema tiene ciclo de vida (tareas, órdenes, sesiones, procesos),
dibuja la máquina de estados antes de implementar:

```text
ESTADOS: <lista>
TRANSICIONES: <estado> --<evento>--> <estado>
INVARIANTES:
  - <qué transiciones son imposibles>
  - <qué produce cada timeout>  (respuesta obligatoria: un estado de fallo
    explícito, nunca éxito inferido)
```

## 6. Gate de F1

- [ ] todo REQ imprescindible cubierto por una SPEC con casos testables;
- [ ] todo componente con frontera externa tiene CONTRATO;
- [ ] decisiones con alternativas registradas en ADR;
- [ ] ninguna spec introduce requisitos que no estén en F0 (features
      fantasma: prohibidas);
- [ ] máquina de estados definida si hay ciclo de vida;
- [ ] las decisiones respetan las restricciones de F0.

Cierra con el bloque de reporte de fase de `00-INDICE.md`. No pases a F2
con un gate `PARCIAL` en un contrato: los contratos mal cerrados se pagan
multiplicados en F3.
