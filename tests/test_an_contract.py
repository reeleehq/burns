"""Easing conformance against ``an``'s shared easing contract (burns#23).

``an`` publishes every named easing, with sample values, as
``an/data/timing/easing.json`` (on npm as ``@thorwhalen/an-contract``, an ADR
0006). burns' named easings are its CSS curves: the TypeScript port reads them
from the npm package, and this test pins the Python table and solver to the
same file.

burns does not depend on ``an``, so the file is found where it already is: the
``an`` package if it is installed, else the npm package under ``ts/`` once
``pnpm install`` has run there; the test skips when neither is present. The
cross-language golden vectors (``test_golden.py``) tie the Python to the
TypeScript, which asserts the contract in every CI run.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from burns.easing import CSS_BEZIERS, parse_easing

# The contract's CSS solver stops at |x(s) - t| < 1e-12; burns bisects to
# ~2^-60, so the two agree to a few 1e-12, never exactly.
TOLERANCE = 1e-11

_NPM_CONTRACT = (
    Path(__file__).parent.parent
    / "ts"
    / "node_modules"
    / "@thorwhalen"
    / "an-contract"
    / "easing.json"
)


def _contract_path():
    """The first easing contract file found, or ``None``."""
    spec = importlib.util.find_spec("an")  # locates, does not import, ``an``
    if spec is not None and spec.submodule_search_locations:
        for root in spec.submodule_search_locations:
            candidate = Path(root) / "data" / "timing" / "easing.json"
            if candidate.is_file():
                return candidate
    return _NPM_CONTRACT if _NPM_CONTRACT.is_file() else None


@pytest.fixture(scope="module")
def contract():
    path = _contract_path()
    if path is None:
        pytest.skip("an's easing contract is not installed (an, or ts/node_modules)")
    return json.loads(path.read_text())


def test_table_is_the_contracts_css_curves(contract):
    for name, points in contract["css_hyphenated_curves"].items():
        assert CSS_BEZIERS[name] == tuple(points), name
    for name, spec in contract["css_import_aliases"].items():
        assert parse_easing(spec)(0.3) == parse_easing(name)(0.3), name


def test_easings_match_the_contracts_samples(contract):
    served = [
        e
        for e in contract["entries"]
        if e["name"] in CSS_BEZIERS and (e["family"] == "css" or e["name"] == "linear")
    ]
    assert sorted(e["name"] for e in served) == [
        "ease-in",
        "ease-in-out",
        "ease-out",
        "linear",
    ]
    for entry in served:
        ease = parse_easing(entry["name"])
        for u, expected in zip(contract["sample_u"], entry["samples"]):
            assert abs(ease(u) - expected) < TOLERANCE, (entry["name"], u)
