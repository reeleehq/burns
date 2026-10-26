"""Generate the golden-vector fixture — the cross-language equivalence contract.

`burns`' motion spec is pure data with a pure ``evaluate(t) -> Rect`` and a pure
spec->pixels crop (:func:`burns._frame.sample_box`). A future JS/TS port
(``kenburnz``) must reproduce both *exactly*. The contract is a committed JSON
fixture (``tests/golden/vectors.json``) that both languages assert against — per
the architecture report, the fixture is the source of truth and the code
conforms to it, not the other way round.

This script regenerates that fixture **from the current Python implementation**.
Run it whenever an intentional, reviewed change to the spec math lands::

    python -m misc.gen_golden_vectors        # from the repo root
    #  or:  python misc/gen_golden_vectors.py

``tests/test_golden.py`` then asserts the live code still reproduces every
vector, so an *unintended* change to the math fails CI instead of silently
rewriting the contract.

Two vector kinds are emitted:

1. ``evaluate`` — ``(spec, t) -> Rect{x, y, w, h}``: the pure motion math
   (easing composed over linearly-interpolated geometry).
2. ``pixel_box`` — ``(spec, image_size, output_size, t) -> [x0, y0, x1, y1]``:
   the integer crop box :func:`burns._frame.sample_box` reads from the source
   image (evaluate -> clamp -> to_pixels -> cover-crop to output AR). This is
   the highest cross-language risk, so it is pinned to the exact integer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from burns import BurnsPath, Rect, ken_burns_path
from burns._frame import sample_box
from burns.easing import CSS_BEZIERS

# Where the committed fixture lives (the SSOT the test loads).
FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent / "tests" / "golden" / "vectors.json"
)

# Equivalence tolerance for the float-valued evaluate rects. The pixel boxes are
# compared as exact integers (no eps), so they are not governed by this.
EVAL_EPS = 1e-9

# Clock times every vector is sampled at — endpoints plus the interior quarters,
# enough to catch an easing or interpolation divergence.
T_SAMPLES = (0.0, 0.25, 0.5, 0.75, 1.0)

# A 4:3 source (AR ~1.333). Even dimensions so the boxes match real renders.
IMG_W, IMG_H = 64, 48


def _named_paths() -> dict[str, BurnsPath]:
    """The labelled spec catalog driving both vector kinds.

    Covers every constructor, every CSS easing plus an explicit cubic-bezier,
    both ``ken_burns_path`` styles (odd push-in / even pull-out / drift), an
    N-keyframe path, the reversed transform, and a ride-the-wall clamp case.
    """
    paths: dict[str, BurnsPath] = {}

    # --- Constructors -----------------------------------------------------
    paths["from_start_end_linear"] = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing="linear"
    )
    paths["push_in_default"] = BurnsPath.push_in()  # zoom 1.3, ease-in-out
    paths["push_in_off_center"] = BurnsPath.push_in(
        1.5, to=(0.7, 0.35), easing="ease-out"
    )
    # An N-keyframe (3-waypoint) path: pan right, then push in. Linear easing so
    # the per-segment lerp is exercised without the bezier remap muddying it.
    paths["three_keyframe"] = BurnsPath(
        keyframes=(
            (0.0, Rect(0.0, 0.0, 0.6, 0.6)),
            (0.5, Rect(0.4, 0.0, 0.6, 0.6)),
            (1.0, Rect(0.4, 0.4, 0.5, 0.5)),
        ),
        easing="linear",
    )
    # A one-keyframe path: a static framing. Valid in Python, in the TS class and
    # on the wire (the JSON Schema allows minItems 1), so it is pinned here and
    # every golden path is validated against the schema by both suites.
    paths["single_keyframe"] = BurnsPath(
        keyframes=((0.0, Rect(0.1, 0.2, 0.6, 0.6)),),
    )
    paths["reversed"] = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing="linear"
    ).reversed()

    # --- Every CSS easing + an explicit cubic-bezier ----------------------
    # Same geometry, different timing — isolates the easing remap.
    for name in CSS_BEZIERS:  # linear, ease, ease-in, ease-out, ease-in-out
        paths[f"easing_{name}"] = BurnsPath.from_start_end(
            Rect(0, 0, 1, 1), Rect(0.25, 0.25, 0.5, 0.5), easing=name
        )
    paths["easing_cubic_bezier"] = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1),
        Rect(0.25, 0.25, 0.5, 0.5),
        easing="cubic-bezier(0.2, 0.8, 0.3, 0.9)",
    )

    # --- ken_burns_path intent vocabulary ---------------------------------
    paths["kbp_push_odd"] = ken_burns_path(1, style="push")  # push in
    paths["kbp_push_even"] = ken_burns_path(2, style="push")  # pull out
    paths["kbp_drift"] = ken_burns_path(1, style="drift")

    # --- Ride-the-wall clamp edge case ------------------------------------
    # The end window is pushed past the right edge; evaluate() returns it raw
    # (un-clamped), and the pixel box pins to_pixels()'s clamp ("ride the wall"
    # without resizing). Linear easing so t maps straight to progress.
    paths["clamp_ride_the_wall"] = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1), Rect(0.8, 0.0, 0.5, 0.5), easing="linear"
    )

    return paths


def _evaluate_vectors(paths: dict[str, BurnsPath]) -> list[dict[str, Any]]:
    """``(spec, t) -> Rect`` vectors for every named path."""
    vectors = []
    for name, path in paths.items():
        samples = []
        for t in T_SAMPLES:
            r = path.evaluate(t)
            samples.append({"t": t, "rect": {"x": r.x, "y": r.y, "w": r.w, "h": r.h}})
        vectors.append({"name": name, "path": path.to_dict(), "samples": samples})
    return vectors


#: Constructor calls, pinned with their arguments (snake_case, as in Python), so
#: a port's *constructors* are checked, not only the paths they produce. Every
#: one sets ``output_aspect`` together with ``image_aspect`` (burns#30/#34).
CONSTRUCTOR_CALLS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "push_in_16x9_on_16x9",
        "push_in",
        dict(zoom=1.2, to=(0.45, 0.5), output_aspect=16 / 9, image_aspect=16 / 9),
    ),
    (
        "push_in_16x9_on_4x3",
        "push_in",
        dict(zoom=1.3, output_aspect=16 / 9, image_aspect=4 / 3),
    ),
    (
        "push_in_9x16_on_16x9",
        "push_in",
        dict(zoom=1.4, to=(0.6, 0.4), output_aspect=9 / 16, image_aspect=16 / 9),
    ),
    (
        "kbp_push_odd_16x9_on_4x3",
        "ken_burns_path",
        dict(index=1, output_aspect=16 / 9, image_aspect=4 / 3),
    ),
    (
        "kbp_push_even_square_on_16x9",
        "ken_burns_path",
        dict(index=2, output_aspect=1.0, image_aspect=16 / 9),
    ),
    (
        "kbp_drift_16x9_on_4x3",
        "ken_burns_path",
        dict(index=1, style="drift", output_aspect=16 / 9, image_aspect=4 / 3),
    ),
    (
        "kbp_drift_9x16_on_16x9",
        "ken_burns_path",
        dict(
            index=1, style="drift", pan=0.3, output_aspect=9 / 16, image_aspect=16 / 9
        ),
    ),
)


def build_constructor_path(fn: str, args: dict[str, Any]) -> BurnsPath:
    """Call the named constructor with ``args`` (`tests/test_golden.py` keeps its own copy, as an independent check)."""
    args = dict(args)
    if fn == "push_in":
        return BurnsPath.push_in(**args)
    return ken_burns_path(args.pop("index"), **args)


def _constructor_vectors() -> list[dict[str, Any]]:
    """``(constructor, args) -> BurnsPath`` vectors."""
    return [
        {
            "name": name,
            "fn": fn,
            "args": {
                k: list(v) if isinstance(v, tuple) else v for k, v in args.items()
            },
            "path": build_constructor_path(fn, args).to_dict(),
        }
        for name, fn, args in CONSTRUCTOR_CALLS
    ]


def _pixel_box_cases(
    paths: dict[str, BurnsPath],
) -> list[tuple[str, BurnsPath, tuple[int, int]]]:
    """``(name, path, output_size)`` cases for the pixel-box vectors.

    The image is always ``(IMG_W, IMG_H)``; the interesting axis is output size:
    one matching the source AR (cover-crop is a no-op) and one square (the
    cover-crop trims the wide sides — the part most likely to diverge in JS).
    """
    out_match = (IMG_W, IMG_H)  # 4:3, same AR as the source
    out_square = (IMG_H, IMG_H)  # 1:1, forces a horizontal cover-crop
    out_wide = (IMG_H * 2, IMG_H)  # 2:1, forces a vertical cover-crop
    return [
        ("from_start_end_linear__match", paths["from_start_end_linear"], out_match),
        ("from_start_end_linear__square", paths["from_start_end_linear"], out_square),
        ("from_start_end_linear__wide", paths["from_start_end_linear"], out_wide),
        ("push_in_default__match", paths["push_in_default"], out_match),
        ("push_in_default__square", paths["push_in_default"], out_square),
        ("three_keyframe__square", paths["three_keyframe"], out_square),
        ("kbp_push_odd__match", paths["kbp_push_odd"], out_match),
        ("kbp_push_even__square", paths["kbp_push_even"], out_square),
        ("kbp_drift__match", paths["kbp_drift"], out_match),
        ("clamp_ride_the_wall__match", paths["clamp_ride_the_wall"], out_match),
        ("clamp_ride_the_wall__square", paths["clamp_ride_the_wall"], out_square),
    ]


def _pixel_box_vectors(paths: dict[str, BurnsPath]) -> list[dict[str, Any]]:
    """``(spec, image_size, output_size, t) -> integer crop box`` vectors."""
    vectors = []
    for name, path, (out_w, out_h) in _pixel_box_cases(paths):
        samples = []
        for t in T_SAMPLES:
            box = sample_box(path, t, IMG_W, IMG_H, out_w, out_h)
            samples.append({"t": t, "box": list(box)})
        vectors.append(
            {
                "name": name,
                "path": path.to_dict(),
                "image_size": [IMG_W, IMG_H],
                "output_size": [out_w, out_h],
                "samples": samples,
            }
        )
    return vectors


def build_fixture() -> dict[str, Any]:
    """The full fixture payload (the committed ``vectors.json`` contents)."""
    paths = _named_paths()
    return {
        "spec_version": BurnsPath.from_start_end(
            Rect(0, 0, 1, 1), Rect(0, 0, 1, 1)
        ).version,
        "eps": EVAL_EPS,
        "t_samples": list(T_SAMPLES),
        "evaluate": _evaluate_vectors(paths),
        "pixel_box": _pixel_box_vectors(paths),
        "constructors": _constructor_vectors(),
    }


def write_fixture(path: Path = FIXTURE_PATH) -> Path:
    """Write the fixture to ``path`` (pretty-printed, newline-terminated)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_fixture()
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


if __name__ == "__main__":
    written = write_fixture()
    payload = json.loads(written.read_text())
    print(
        f"Wrote {written} "
        f"({len(payload['evaluate'])} evaluate + "
        f"{len(payload['pixel_box'])} pixel_box vectors)."
    )
