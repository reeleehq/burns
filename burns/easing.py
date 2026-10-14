"""Timing functions (easing) for Ken Burns motion.

Easing maps normalized clock time ``t in [0, 1]`` to normalized progress
``[0, 1]``. It is composed *over* the geometry: a path's viewport at clock
time ``t`` is ``path.evaluate_geometry(easing(t))`` — the After-Effects split
of *what shape the motion traces* (the path) from *how fast it moves along it*
(the timing). Keeping them orthogonal is the single most useful design lesson
from the NLE prior art.

The public currency is the **CSS timing-function string** — ``"linear"``,
``"ease"``, ``"ease-in"``, ``"ease-out"``, ``"ease-in-out"``, or an explicit
``"cubic-bezier(x1, y1, x2, y2)"`` — because that vocabulary is understood
verbatim by CSS, Remotion's ``Easing.bezier``, and GSAP's ``CustomEase`` alike.
The cinematic default is ``"ease-in-out"`` (Final Cut Pro's Ken Burns default),
**not** linear.

:func:`parse_easing` also accepts a 4-tuple of bezier control values or any
callable ``float -> float``, so power users can inject an arbitrary curve.
"""

from __future__ import annotations

from typing import Callable, Sequence, Union

EasingLike = Union[str, Callable[[float], float], Sequence[float]]

# Canonical CSS cubic-bezier control points (verbatim from CSS Timing
# Functions Level 1). Each maps a named easing to its (x1, y1, x2, y2).
# These are the CSS entries of `an`'s shared easing contract (`easing.json`,
# on npm as `@thorwhalen/an-contract`), which the TypeScript port reads
# directly; `tests/test_an_contract.py` pins this table and its values to it.
CSS_BEZIERS: dict[str, tuple[float, float, float, float]] = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "ease": (0.25, 0.1, 0.25, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
}

DFLT_EASING = "ease-in-out"

_BISECTION_ITERS = 60  # ~2^-60 precision on the bezier x-root; plenty.


def _clamp01(t: float) -> float:
    return 0.0 if t < 0.0 else 1.0 if t > 1.0 else t


def cubic_bezier(
    x1: float, y1: float, x2: float, y2: float
) -> Callable[[float], float]:
    """A CSS-style cubic-bezier easing ``f: [0, 1] -> [0, 1]``.

    The curve runs from ``(0, 0)`` to ``(1, 1)`` with control points
    ``(x1, y1)`` and ``(x2, y2)``. Evaluation inverts ``x(t)`` for the curve
    parameter (bisection — robust for any monotone-x curve) then returns
    ``y(t)``.

    Examples:
        >>> linear = cubic_bezier(0.0, 0.0, 1.0, 1.0)
        >>> round(linear(0.5), 6)
        0.5
        >>> round(cubic_bezier(0.42, 0.0, 0.58, 1.0)(0.5), 6)  # ease-in-out
        0.5
    """

    def _bez(t: float, a: float, b: float) -> float:
        # Bezier coordinate at parameter t with endpoints 0 and 1.
        u = 1.0 - t
        return 3.0 * u * u * t * a + 3.0 * u * t * t * b + t * t * t

    def _solve_t_for_x(x: float) -> float:
        lo, hi = 0.0, 1.0
        for _ in range(_BISECTION_ITERS):
            mid = (lo + hi) / 2.0
            if _bez(mid, x1, x2) < x:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2.0

    def ease(t: float) -> float:
        t = _clamp01(t)
        if t == 0.0 or t == 1.0:
            return t
        return _bez(_solve_t_for_x(t), y1, y2)

    return ease


def parse_easing(spec: EasingLike = DFLT_EASING) -> Callable[[float], float]:
    """Resolve an easing spec to a callable ``f: [0, 1] -> [0, 1]``.

    Accepts:
        - a CSS name (``"linear"``, ``"ease"``, ``"ease-in"``, ``"ease-out"``,
          ``"ease-in-out"``);
        - a CSS ``"cubic-bezier(x1, y1, x2, y2)"`` string;
        - a 4-element sequence ``(x1, y1, x2, y2)``;
        - any callable, returned unchanged.

    Examples:
        >>> parse_easing("linear")(0.3)
        0.3
        >>> round(parse_easing("cubic-bezier(0,0,1,1)")(0.7), 6)
        0.7
        >>> parse_easing(lambda t: t * t)(0.5)
        0.25
    """
    if callable(spec):
        return spec
    if isinstance(spec, str):
        key = spec.strip().lower()
        if key in CSS_BEZIERS:
            return cubic_bezier(*CSS_BEZIERS[key])
        if key.startswith("cubic-bezier"):
            return cubic_bezier(*_parse_bezier_args(spec))
        raise ValueError(
            f"parse_easing: unknown easing {spec!r}. Use a CSS name "
            f"({', '.join(CSS_BEZIERS)}), a cubic-bezier(...) string, a "
            f"4-tuple, or a callable."
        )
    if isinstance(spec, Sequence) and len(spec) == 4:
        return cubic_bezier(*(float(v) for v in spec))
    raise ValueError(f"parse_easing: cannot interpret easing spec {spec!r}")


def _parse_bezier_args(spec: str) -> tuple[float, float, float, float]:
    """Extract the four floats from a ``cubic-bezier(x1, y1, x2, y2)`` string."""
    inside = spec[spec.index("(") + 1 : spec.rindex(")")]
    parts = [p.strip() for p in inside.split(",")]
    if len(parts) != 4:
        raise ValueError(f"parse_easing: cubic-bezier needs 4 values, got {spec!r}")
    return tuple(float(p) for p in parts)  # type: ignore[return-value]
