# ADR-0051: rediseñar `relocate attach` con un testigo del checkout anterior que no dependa de su ruta

- **Estado:** Propuesta
- **Implementación:** No iniciada. El comando quedó fuera de la CLI de
  beta.30 (ADR-0048 Enmienda 9); `an_kla/relocate_attach.py` y sus tests
  siguen en el repo, sin superficie pública.
- **Fecha:** 2026-10-13
- **Decide sobre:** cómo sabe `attach` que el checkout al que estaba ligada
  una bóveda externa ya no la usa, antes de ligarla a otra raíz.

## Contexto

`attach` (ADR-0048 Enmienda 5) liga una bóveda externa creada para otra
raíz de proyecto al checkout actual. Por bytes, una bóveda movida y una
copia son indistinguibles, así que la única defensa contra dos bóvedas
vivas para el mismo proyecto es un testigo: algo que diga si el checkout
anterior sigue vivo con su puntero.

La ronda adversarial de release beta.30 (Muse CLI) encontró un HIGH nuevo
en `attach` en cada una de sus tres rondas:

- **H-02 (ronda 1):** el replay aceptaba un CURRENT falso.
- **N-01 (ronda 2):** `attach` de una copia con el checkout anterior vivo
  dejaba dos bóvedas aceptando escrituras.
- **R3-01 (ronda 3):** la corrección de N-01 mira el checkout anterior sólo
  en su ruta registrada. Basta un `mv` del checkout anterior para que el
  testigo desaparezca y se repita N-01.

Por la regla de corte del maintainer (2026-10-13), beta.30 sale sin el
comando y el rediseño se decide aquí.

## Decisión

Pendiente. Opciones a evaluar, sin preferencia todavía:

1. **Testigo en la bóveda:** `attach` exige que la bóveda registre que su
   checkout anterior la liberó (por ejemplo, un receipt de liberación que
   escribe el checkout viejo o `relocate back`). Sin liberación, falla.
2. **Arrendamiento con caducidad:** cada escritura renueva un arrendamiento
   en la bóveda ligado a la raíz. `attach` sólo procede si el arrendamiento
   venció. Exige reloj y define una ventana de riesgo.
3. **Declaración explícita del operador:** `attach --i-own-the-only-copy`,
   con la copia viva como límite declarado. Es la opción más débil.

## Por qué no seguir parcheando

Tres rondas encontraron tres variantes del mismo hueco: el testigo depende
de rutas, y las rutas cambian con operaciones ordinarias. Otro parche sobre
la ruta registrada tendría el mismo defecto.

## Consecuencias

- Positivas: beta.30 no expone un comando que puede bifurcar la custodia.
- Negativas: un checkout recreado en otra ruta no puede recuperar su bóveda
  externa sin `init` sobre la misma raíz ligada (Enmienda 5 §4) o sin este
  rediseño.

## Test de regresión

`tests/test_custody_release_round_b30.py` (N-01..N-03) y
`tests/test_relocate_attach.py` cubren la API actual;
`test_cli_does_not_expose_attach` fija que la CLI no la expone.

## Referencias

ADR-0048 Enmiendas 5, 7, 8 y 9; `docs/releases/v0.1.0-beta.30-adversarial.md`
§Ronda 3.
