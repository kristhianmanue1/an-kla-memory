# Muestra del vocabulario de referencia de Snowball para español

Prueba de `an_kla/lexico_es.py` (ADR-0064, `an-kla/lexico-es-v1`) frente a la referencia.

- **Origen:** <https://github.com/snowballstem/snowball-data>, carpeta `spanish/`:
  `voc.txt` (28.378 palabras, sha256 `8ddebc62…ea309`) y `output.txt` (su raíz de referencia, sha256
  `641e30bd…16836`), descargados de `raw.githubusercontent.com/snowballstem/snowball-data/master/spanish/`.
- **Muestra fija y declarada:** `muestra.tsv` toma una palabra de cada 40 de `voc.txt`, empezando por la primera y
  en el orden del original (710 filas), con la forma `palabra<TAB>raíz de referencia`. No se ha editado a mano.
- **Licencia:** BSD de 3 cláusulas del proyecto Snowball (`COPYING`, copia literal del de `snowball-data`).
- **Uso:** la prueba exige que toda palabra sin tilde coincida exactamente tras plegar
  (`reduce_term(fold(w)) == fold(raiz)`) y que toda discrepancia sea una palabra con tilde (cambio 2 del ADR).
