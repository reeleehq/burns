"""Golden-vector conformance test — the cross-language equivalence contract.

``tests/golden/vectors.json`` pins, from the Python implementation, the two
things a second-language renderer (the future ``kenburnz`` TS/npm port) must
reproduce exactly:

1. ``evaluate``  — ``(spec, t) -> Rect{x, y, w, h}``, the pure motion math.
2. ``pixel_box`` — ``(spec, image_size, output_size, t) -> [x0, y0, x1, y1]``,
   the integer crop box :func:`burns._frame.sample_box` reads (the highest
   cross-language risk: evaluate -> clamp -> to_pixels -> cover-crop).

The fixture is the source of truth; this test asserts the **live** code still
matches it. Regenerate it deliberately with ``python misc/gen_golden_vectors.py``
when (and only when) an intended change to the spec math lands — an *unintended*
change makes this test fail instead of silently rewriting the contract.

Rects compare within the fixture's ``eps``; pixel boxes compare as exact ints.
"""

import json
from pathlib import Path

import pytest

from burns import BurnsPath
from burns._frame import sample_box

FIXTURE_PATH = Path(__file__).parent / "golden" / "vectors.json"


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE_PATH.read_text())


def test_fixture_is_present_and_populated(fixture):
    # A truncated or empty fixture must fail loudly rather than vacuously pass.
    assert fixture["evaluate"], "no evaluate vectors in fixture"
    assert fixture["pixel_box"], "no pixel_box vectors in fixture"


def test_fixture_covers_the_required_surface(fixture):
    """Guard the coverage the issue mandates, so a future trim can't quietly
    drop a constructor, an easing, or the aspect-mismatch / clamp cases."""
    eval_names = {v["name"] for v in fixture["evaluate"]}
    # Constructors + transforms + N-keyframe.
    assert {
        "from_start_end_linear",
        "push_in_default",
        "three_keyframe",
        "reversed",
    } <= eval_names
    # Every CSS easing plus an explicit cubic-bezier.
    assert {
        "easing_linear",
        "easing_ease",
        "easing_ease-in",
        "easing_ease-out",
        "easing_ease-in-out",
        "easing_cubic_bezier",
    } <= eval_names
    # ken_burns_path push (odd/even) and drift.
    assert {"kbp_push_odd", "kbp_push_even", "kbp_drift"} <= eval_names
    # Clamp / ride-the-wall.
    assert "clamp_ride_the_wall" in eval_names

    box_names = {v["name"] for v in fixture["pixel_box"]}
    # output_aspect == image AR (match) AND != image AR (square/wide cover-crop).
    assert any(n.endswith("__match") for n in box_names)
    assert any(n.endswith("__square") for n in box_names)
    assert any(n.endswith("__wide") for n in box_names)
    # The clamp case carried through the pixel mapping.
    assert any(n.startswith("clamp_ride_the_wall") for n in box_names)


def _eval_ids(fixture):
    return [v["name"] for v in fixture["evaluate"]]


def _box_ids(fixture):
    return [v["name"] for v in fixture["pixel_box"]]


def test_evaluate_vectors_reproduce(fixture):
    """Every ``(spec, t) -> Rect`` vector matches live ``BurnsPath.evaluate``."""
    eps = fixture["eps"]
    for vec in fixture["evaluate"]:
        path = BurnsPath.from_dict(vec["path"])
        for sample in vec["samples"]:
            r = path.evaluate(sample["t"])
            expected = sample["rect"]
            for comp in ("x", "y", "w", "h"):
                got = getattr(r, comp)
                assert got == pytest.approx(expected[comp], abs=eps), (
                    f"{vec['name']} @ t={sample['t']}: "
                    f"rect.{comp} {got} != {expected[comp]}"
                )


def test_pixel_box_vectors_reproduce(fixture):
    """Every ``(spec, image, output, t) -> box`` vector matches live ``sample_box``.

    Exact integers — the crop box is what both renderers physically read, so any
    off-by-one here is a real cross-language divergence, not float slack.
    """
    for vec in fixture["pixel_box"]:
        path = BurnsPath.from_dict(vec["path"])
        img_w, img_h = vec["image_size"]
        out_w, out_h = vec["output_size"]
        for sample in vec["samples"]:
            box = sample_box(path, sample["t"], img_w, img_h, out_w, out_h)
            assert list(box) == sample["box"], (
                f"{vec['name']} @ t={sample['t']}: {list(box)} != {sample['box']}"
            )


def test_path_roundtrips_through_dict(fixture):
    """The fixture stores each path as ``to_dict``; that must rebuild an equal
    path (the wire format is itself part of the contract)."""
    for vec in fixture["evaluate"]:
        path = BurnsPath.from_dict(vec["path"])
        assert BurnsPath.from_dict(path.to_dict()) == path


def test_constructor_vectors_reproduce(fixture):
    """The constructors (not only the paths) are part of the contract (burns#34)."""
    from burns import ken_burns_path

    assert fixture["constructors"], "no constructor vectors in fixture"
    for vec in fixture["constructors"]:
        args = {
            k: tuple(v) if isinstance(v, list) else v for k, v in vec["args"].items()
        }
        if vec["fn"] == "push_in":
            path = BurnsPath.push_in(**args)
        else:
            path = ken_burns_path(args.pop("index"), **args)
        assert path.to_dict() == vec["path"], vec["name"]
