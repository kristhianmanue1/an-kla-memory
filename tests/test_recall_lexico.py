"""``an_kla/lexico_es.py`` (ADR-0064, ``an-kla/lexico-es-v1``): plegado, corte, raíz e interrogativos."""

from __future__ import annotations

import unittest
from pathlib import Path

from an_kla.lexico_es import ANALYZER, INTERROGATIVES, cut, fold, query_terms, record_terms, reduce_term

SAMPLE = Path(__file__).resolve().parent / "fixtures" / "snowball-es" / "muestra.tsv"


def _has_accent(word: str) -> bool:
    return fold(word) != word.casefold()


class FoldAndCutTests(unittest.TestCase):
    def test_fold_drops_diacritics_and_casefolds(self) -> None:
        self.assertEqual(fold("Facturación"), "facturacion")
        self.assertEqual(fold("ÑANDÚ"), "nandu")
        self.assertEqual(fold("Straße"), "strasse")

    def test_cut_splits_identifiers_on_underscore_and_signs(self) -> None:
        self.assertEqual(cut("NOMBRE_CONFIG"), ["nombre", "config"])
        self.assertEqual(cut("a-b.c/d, e"), ["a", "b", "c", "d", "e"])
        self.assertEqual(cut("v2.1_beta"), ["v2", "1", "beta"])
        self.assertEqual(cut("¿¡!?"), [])

    def test_analyzer_name_is_versioned(self) -> None:
        self.assertEqual(ANALYZER, "an-kla/lexico-es-v1")


class StemmerTests(unittest.TestCase):
    def test_number_and_verb_inflection_meet(self) -> None:
        for left, right in (("puertos", "puerto"), ("lanzo", "lanza"), ("modelo", "modelos"),
                            ("facturación", "facturacion"), ("configuración", "configuracion")):
            self.assertEqual(reduce_term(fold(left)), reduce_term(fold(right)), (left, right))

    def test_unstressed_nouns_are_not_over_reduced(self) -> None:
        # Plegados chocarían con sufijos verbales de la referencia (cambio 2 del ADR).
        self.assertEqual(reduce_term("criterio"), "criteri")
        self.assertEqual(reduce_term("historia"), "histori")
        self.assertEqual(reduce_term("crisis"), "crisis")
        self.assertEqual(reduce_term("taxi"), "taxi")

    def test_enclitics_outside_rv_are_not_cut(self) -> None:
        # `dar`/`ver` no empiezan en RV: el pronombre no se corta; sólo cae la vocal final.
        self.assertEqual(reduce_term("darme"), "darm")
        self.assertEqual(reduce_term("verlo"), "verl")
        self.assertEqual(reduce_term("hablarle"), "habl")  # `hablar` sí empieza en RV: se corta

    def test_only_alphabetic_terms_of_three_letters_or_more_are_reduced(self) -> None:
        for token in ("ab", "a", "12", "v2", "a1b2", "2024", "x9z"):
            self.assertEqual(reduce_term(token), token)
        self.assertEqual(record_terms("NOMBRE_CONFIG"), ["nombr", "config"])

    def test_agrees_with_the_snowball_reference_on_the_fixed_sample(self) -> None:
        rows = [line.split("\t") for line in SAMPLE.read_text(encoding="utf-8").splitlines()]
        self.assertGreaterEqual(len(rows), 700)
        plain = discrepancies = 0
        for word, reference in rows:
            got = reduce_term(fold(word))
            if got == fold(reference):
                continue
            discrepancies += 1
            # Toda discrepancia es una palabra con tilde (cambio 2); ninguna sin tilde.
            self.assertTrue(_has_accent(word), f"{word}: {got} != {fold(reference)}")
        for word, reference in rows:
            if not _has_accent(word):
                plain += 1
                self.assertEqual(reduce_term(fold(word)), fold(reference), word)
        self.assertGreater(plain, 500)
        self.assertLess(discrepancies, len(rows) * 0.1)


class QueryTermsTests(unittest.TestCase):
    def test_interrogatives_are_dropped_folded_and_only_from_the_query(self) -> None:
        tokens, terms = query_terms("¿Qué puertos usa? ¿Cómo y dónde? What, WHO, how")
        self.assertEqual(terms, ["puert", "usa", "y"])
        self.assertIn("que", tokens)
        # Un registro conserva sus interrogativos: sólo la consulta los pierde.
        self.assertIn("que", record_terms("lo que pasa"))
        self.assertTrue({"quien", "cuantas", "adonde", "whom", "why", "which"} <= INTERROGATIVES)

    def test_terms_are_deduplicated_keeping_order(self) -> None:
        self.assertEqual(query_terms("puertos puerto Puerto")[1], ["puert"])
        self.assertEqual(query_terms("kiwi pelo kiwi sol")[1], [reduce_term(w) for w in ("kiwi", "pelo", "sol")])

    def test_no_tokens_after_the_cut(self) -> None:
        self.assertEqual(query_terms("¿?!"), ([], []))


if __name__ == "__main__":
    unittest.main()
