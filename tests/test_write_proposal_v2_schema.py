"""test_write_proposal_v2_schema.py — el lote v2 es descubrible (#176).

`write-proposal-v2` (ADR-0054) se publica como JSON Schema para que un agente
lo encuentre con `schema list` / `schema show`. Este test fija que el schema y
el validador del motor (`validate_batch_proposal`) coinciden: mismo veredicto
en todo lo que JSON Schema puede expresar, y una lista cerrada de reglas que
sólo el motor aplica (declaradas en la descripción del schema).
"""

from __future__ import annotations

import copy
import json
import unittest

from an_kla.schemas import schema_bytes, schema_names
from an_kla.write_batch import BATCH_SCHEMA, validate_batch_proposal
from an_kla.write_policy import _POLICY_CONFIGURATION, WritePolicyError

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - dependencia sólo de test
    Draft202012Validator = None

DIGEST = "sha256:" + "a" * 64


def _base() -> dict:
    return {
        "schema": BATCH_SCHEMA,
        "base_revision": DIGEST,
        "stream": "events",
        "operation": "add",
        "requested_representation": "summary",
        "records": [{"id": "e-1", "text": "uno"}, {"id": "e-2", "text": "dos"}],
        "lineage": {"derived_from_retrieval": False,
                    "refs": [{"kind": "external", "id": "github:issue/176"}]},
    }


def _supersede() -> dict:
    proposal = _base()
    proposal["operation"] = "supersede"
    proposal["supersedes"] = {"e-1": "e-old-1", "e-2": "e-old-2"}
    return proposal


def _mutate(base, path, value):
    proposal = copy.deepcopy(base())
    target = proposal
    for key in path[:-1]:
        target = target[key]
    if value is _DELETE:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return proposal


_DELETE = object()

# (nombre, propuesta, válida)
SHARED_CASES = [
    ("add mínimo", _base(), True),
    ("supersede con mapa", _supersede(), True),
    ("schema v1", _mutate(_base, ["schema"], "an-kla/write-proposal-v1"), False),
    ("sin records", _mutate(_base, ["records"], _DELETE), False),
    ("records vacío", _mutate(_base, ["records"], []), False),
    ("record sin id", _mutate(_base, ["records"], [{"text": "x"}]), False),
    ("record id vacío", _mutate(_base, ["records"], [{"id": ""}]), False),
    ("record no objeto", _mutate(_base, ["records"], ["e-1"]), False),
    ("operation refute", _mutate(_base, ["operation"], "refute"), False),
    ("stream inválido", _mutate(_base, ["stream"], "fact"), False),
    ("representación inválida", _mutate(_base, ["requested_representation"], "brief"), False),
    ("base_revision no digest", _mutate(_base, ["base_revision"], "abc"), False),
    ("clave extra", _mutate(_base, ["record"], {"id": "x"}), False),
    ("supersede sin mapa", _mutate(_supersede, ["supersedes"], _DELETE), False),
    ("supersede como cadena", _mutate(_supersede, ["supersedes"], "e-old-1"), False),
    ("supersedes con add", _mutate(_base, ["supersedes"], {"e-1": "e-old"}), False),
    ("target vacío", _mutate(_supersede, ["supersedes"], {"e-1": "", "e-2": "e-old-2"}), False),
    ("lineage sin refs", _mutate(_base, ["lineage"], {"derived_from_retrieval": False}), False),
    ("ref kind inválido", _mutate(_base, ["lineage", "refs"], [{"kind": "url", "id": "x"}]), False),
    ("ref clave extra", _mutate(_base, ["lineage", "refs"], [{"kind": "external", "id": "x", "url": "y"}]), False),
    # #176: cada record del lote, no sólo el primero, cumple la forma de v1.
    ("records[1] verified_at inválido", _mutate(_base, ["records"], [{"id": "e-1"}, {"id": "e-2", "verified_at": "nope"}]), False),
    ("records[1] subject_ref inválido", _mutate(_base, ["records"], [{"id": "e-1"}, {"id": "e-2", "subject_ref": "x"}]), False),
    ("records[1] sin id", _mutate(_base, ["records"], [{"id": "e-1"}, {"text": "x"}]), False),
]

# Reglas que JSON Schema no expresa; el schema las declara en su descripción.
ENGINE_ONLY_CASES = [
    ("ids duplicados", _mutate(_base, ["records"], [{"id": "e-1"}, {"id": "e-1"}])),
    ("claves de supersedes ≠ ids", _mutate(_supersede, ["supersedes"], {"e-1": "e-old-1", "e-9": "e-old-2"})),
    ("supersede intra-lote", _mutate(_supersede, ["supersedes"], {"e-1": "e-2", "e-2": "e-old-2"})),
    ("auto-supersede", _mutate(_supersede, ["supersedes"], {"e-1": "e-1", "e-2": "e-old-2"})),
    ("targets duplicados", _mutate(_supersede, ["supersedes"], {"e-1": "e-old", "e-2": "e-old"})),
    ("records[1] status no escalar", _mutate(_base, ["records"], [{"id": "e-1"}, {"id": "e-2", "status": 7}])),
    ("records[1] nu no escalar", _mutate(_base, ["records"], [{"id": "e-1"}, {"id": "e-2", "nu": [1, 2]}])),
    ("records[1] fecha imposible", _mutate(_base, ["records"], [{"id": "e-1"}, {"id": "e-2", "verified_at": "2026-02-30T00:00:00Z"}])),
    ("valor no finito", _mutate(_base, ["records"], [{"id": "e-1", "x": float("nan")}])),
    ("digest con salto final", _mutate(_base, ["base_revision"], DIGEST + "\n")),
]

# Heredado de v1: el schema es más estricto que el motor con `text`.
SCHEMA_ONLY_CASES = [
    ("text vacío", _mutate(_base, ["records"], [{"id": "e-1", "text": ""}])),
    ("text no cadena", _mutate(_base, ["records"], [{"id": "e-1", "text": 5}])),
]


def _engine_accepts(proposal: dict) -> bool:
    try:
        validate_batch_proposal(proposal)
    except WritePolicyError:
        return False
    return True


@unittest.skipIf(Draft202012Validator is None, "jsonschema no instalado")
class WriteProposalV2SchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(schema_bytes("write-proposal-v2"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def test_listed_and_identified(self) -> None:
        self.assertIn("write-proposal-v2", schema_names())
        self.assertEqual(self.schema["properties"]["schema"]["const"], BATCH_SCHEMA)

    def test_batch_limit_matches_the_policy(self) -> None:
        self.assertEqual(self.schema["properties"]["records"]["maxItems"],
                         _POLICY_CONFIGURATION["max_batch_records"])

    def test_schema_and_engine_agree(self) -> None:
        for name, proposal, valid in SHARED_CASES:
            with self.subTest(case=name):
                self.assertEqual(self.validator.is_valid(proposal), valid, name)
                self.assertEqual(_engine_accepts(proposal), valid, name)

    def test_engine_only_rules_are_declared(self) -> None:
        description = self.schema["description"]
        for phrase in ("unique within the batch", "supersedes keys equal to the batch ids",
                       "no self or intra-batch supersede", "unique targets",
                       "scalar status/nu", "calendar-valid verified_at",
                       "finite JSON values", "no trailing newline"):
            self.assertIn(phrase, description)
        for name, proposal in ENGINE_ONLY_CASES:
            with self.subTest(case=name):
                self.assertTrue(self.validator.is_valid(proposal), name)
                self.assertFalse(_engine_accepts(proposal), name)

    def test_schema_only_rules_are_declared(self) -> None:
        self.assertIn("text", self.schema["description"])
        for name, proposal in SCHEMA_ONLY_CASES:
            with self.subTest(case=name):
                self.assertFalse(self.validator.is_valid(proposal), name)
                self.assertTrue(_engine_accepts(proposal), name)

    def test_too_many_records_rejected_by_both(self) -> None:
        limit = _POLICY_CONFIGURATION["max_batch_records"]
        proposal = _base()
        proposal["records"] = [{"id": f"e-{i}"} for i in range(limit + 1)]
        self.assertFalse(self.validator.is_valid(proposal))
        self.assertFalse(_engine_accepts(proposal))


if __name__ == "__main__":
    unittest.main()
