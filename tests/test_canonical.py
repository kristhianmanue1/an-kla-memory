from __future__ import annotations

import unittest

from an_kla.canonical import canonical_json, exact_sized_payload


class ExactSizedPayloadTests(unittest.TestCase):
    def test_decimal_boundaries_converge_without_padding_or_oscillation(self) -> None:
        for padding in (0, 1, 8, 9, 10, 88, 89, 90, 98, 99, 100, 988, 989, 990):
            with self.subTest(padding=padding):
                payload, measured = exact_sized_payload(
                    lambda used, padding=padding: {
                        "padding": "x" * padding,
                        "used_bytes": used,
                    }
                )
                self.assertEqual(payload["used_bytes"], measured)
                self.assertEqual(len(canonical_json(payload)), measured)
