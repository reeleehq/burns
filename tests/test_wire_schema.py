"""The committed JSON Schema (``ts/schemas/burns-path.schema.json``) accepts every path Python emits.

The schema is generated from the zod source under ``ts/`` (``pnpm schema``), so it
is the cross-language wire contract. Python must never author a document the
schema rejects: every golden-vector path (including the one-keyframe case from
issue #19) is validated against the committed schema here, and the TypeScript
suite does the same through zod. Skipped when ``jsonschema`` is not installed.
"""

import json
from pathlib import Path

import pytest

from burns import BurnsPath, Rect

jsonschema = pytest.importorskip("jsonschema")

ROOT = Path(__file__).parent.parent
SCHEMA = json.loads((ROOT / "ts" / "schemas" / "burns-path.schema.json").read_text())
GOLDEN = json.loads((ROOT / "tests" / "golden" / "vectors.json").read_text())


@pytest.mark.parametrize("vector", GOLDEN["evaluate"], ids=lambda v: v["name"])
def test_every_golden_path_is_valid_on_the_wire(vector):
    jsonschema.validate(vector["path"], SCHEMA)


def test_a_one_keyframe_path_is_valid_on_the_wire():
    path = BurnsPath(keyframes=((0.0, Rect(0.1, 0.1, 0.5, 0.5)),))
    jsonschema.validate(path.to_dict(), SCHEMA)


def test_an_empty_keyframe_list_is_invalid_in_both_languages():
    doc = BurnsPath.push_in().to_dict() | {"keyframes": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)
    with pytest.raises(ValueError):
        BurnsPath.from_dict(doc)
