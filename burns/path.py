"""The render-agnostic Ken Burns motion spec: :class:`BurnsPath`.

A :class:`BurnsPath` is the single source of truth for *how the virtual camera
moves over a still image* — pure data, no image, no encoder, no frame count.
Its one job is :meth:`BurnsPath.evaluate`: given a normalized clock time
``t in [0, 1]`` it returns the :class:`~burns.rect.Rect` viewport at that
instant. That pure ``t -> Rect`` primitive is what makes the motion unit-
testable without rendering, serializable across the wire as JSON, and
re-implementable identically in JS/TS for an in-browser preview.

The model mirrors the professional NLE consensus and Remotion's
``interpolate``:

- **Keyframes** are ``(t, Rect)`` waypoints with ``t in [0, 1]``. Two keyframes
  is the canonical Start/End Ken Burns case; N keyframes is the strict
  generalization (a hold is two keyframes with equal rects; a single keyframe is
  also valid and means a static framing).
- **Easing** (a CSS timing function) is composed *over* the geometry —
  ``evaluate(t) == geometry(easing(t))`` — keeping motion *shape* orthogonal to
  motion *speed*. Default ``"ease-in-out"`` (the cinematic norm).
- **output_aspect** is metadata: the aspect ratio the render should fill. When
  it differs from the source image's AR the renderer cover-crops; when ``None``
  the output AR equals the image's. It never affects :meth:`evaluate`.

:func:`ken_burns_path` is a convenience generator: it maps a small intent
vocabulary (a sequence index, a style, a zoom, a pan) to a cohesive, fully
deterministic :class:`BurnsPath`, so callers animating a sequence of images get
non-repetitive motion without hand-authoring rectangles.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence, Union

from burns.easing import DFLT_EASING, EasingLike, parse_easing
from burns.rect import Rect

# A keyframe: a normalized time in [0, 1] paired with the viewport at that time.
Keyframe = tuple[float, Rect]

SPEC_VERSION = 1

_VALID_STYLES = ("push", "drift")


@dataclass(frozen=True)
class BurnsPath:
    """A time-parameterized pan/zoom motion over a still image.

    Construct it directly from keyframes, or via :meth:`from_start_end` /
    :meth:`push_in` for the common cases, or via :func:`ken_burns_path` for
    deterministic per-index motion across a sequence.

    Args:
        keyframes: a sequence of ``(t, Rect)`` waypoints, ``t in [0, 1]``,
            strictly increasing in ``t``. Must have at least one entry; the
            first ``t`` should be ``0.0`` and the last ``1.0`` for the whole
            clock to be covered (out-of-range ``t`` clamps to the ends).
        easing: a CSS timing-function spec (name / ``cubic-bezier(...)`` /
            4-tuple) or a callable ``[0,1] -> [0,1]``. Default ``"ease-in-out"``.
        interp: geometry interpolation between keyframes. Only ``"linear"`` is
            implemented; the field exists so the spec can carry richer schemes
            (``"catmull-rom"``, ``"bezier"``) without a format change.
        output_aspect: the aspect ratio (``width / height``) the render should
            fill. ``None`` means "match the source image".
        version: spec schema version (for forward-compatible serialization).

    Examples:
        >>> p = BurnsPath.from_start_end(
        ...     Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.5, 1.3)
        ... )
        >>> p.evaluate(0.0)
        Rect(x=0.0, y=0.0, w=1.0, h=1.0)
        >>> round(p.evaluate(1.0).zoom, 4)
        1.3
        >>> p.duration_keyframes  # number of waypoints
        2
    """

    keyframes: tuple[Keyframe, ...]
    easing: EasingLike = DFLT_EASING
    interp: str = "linear"
    output_aspect: Union[float, None] = None
    version: int = SPEC_VERSION
    _ease: Callable[[float], float] = field(
        default=None,
        init=False,
        repr=False,
        compare=False,  # type: ignore[assignment]
    )

    def __post_init__(self) -> None:
        kfs = tuple((float(t), r) for t, r in self.keyframes)
        if not kfs:
            raise ValueError("BurnsPath: keyframes must be non-empty")
        times = [t for t, _ in kfs]
        if any(b <= a for a, b in zip(times, times[1:])):
            raise ValueError(
                f"BurnsPath: keyframe times must strictly increase, got {times}"
            )
        if times[0] < 0.0 or times[-1] > 1.0:
            raise ValueError(
                f"BurnsPath: keyframe times must lie in [0, 1], got {times}"
            )
        if self.interp != "linear":
            raise ValueError(
                f"BurnsPath: only interp='linear' is implemented, got {self.interp!r}"
            )
        object.__setattr__(self, "keyframes", kfs)
        object.__setattr__(self, "_ease", parse_easing(self.easing))

    @property
    def duration_keyframes(self) -> int:
        """Number of keyframe waypoints (``2`` for the canonical Start/End)."""
        return len(self.keyframes)

    def evaluate(self, t: float) -> Rect:
        """The viewport :class:`Rect` at normalized clock time ``t in [0, 1]``.

        Applies easing to the clock, then linearly interpolates the geometry at
        the eased progress. Pure and deterministic: no image, no I/O, no frame
        count. ``t`` outside ``[0, 1]`` clamps to the nearest end.

        Examples:
            >>> p = BurnsPath.from_start_end(
            ...     Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing="linear"
            ... )
            >>> p.evaluate(0.5)
            Rect(x=0.0, y=0.0, w=0.75, h=0.75)
        """
        u = self._ease(t)
        kfs = self.keyframes
        if u <= kfs[0][0]:
            return kfs[0][1]
        if u >= kfs[-1][0]:
            return kfs[-1][1]
        for (t0, r0), (t1, r1) in zip(kfs, kfs[1:]):
            if t0 <= u <= t1:
                local = (u - t0) / (t1 - t0) if t1 > t0 else 0.0
                return r0.lerp(r1, local)
        return kfs[-1][1]  # pragma: no cover — covered by the u >= end branch

    def reversed(self) -> "BurnsPath":
        """Swap start and end (the NLE "Swap Start and End Areas" button).

        Mirrors every keyframe's time about ``0.5`` and re-sorts, so the motion
        plays back-to-front. Easing/interp/output_aspect are preserved.

        Examples:
            >>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
            >>> p.reversed().evaluate(0.0)
            Rect(x=0.0, y=0.0, w=0.5, h=0.5)
        """
        flipped = tuple(sorted((1.0 - t, r) for t, r in self.keyframes))
        return BurnsPath(
            keyframes=flipped,
            easing=self.easing,
            interp=self.interp,
            output_aspect=self.output_aspect,
            version=self.version,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the versioned JSON wire format (the cross-language SSOT).

        Easing is stored as the original CSS string / 4-tuple. A callable easing
        cannot be serialized and raises — use a CSS spec for paths that travel.

        Examples:
            >>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
            >>> d = p.to_dict()
            >>> d["version"], d["easing"], len(d["keyframes"])
            (1, 'ease-in-out', 2)
        """
        if callable(self.easing):
            raise ValueError(
                "BurnsPath.to_dict: a callable easing is not serializable; "
                "use a CSS easing string/tuple for paths that cross the wire."
            )
        easing = self.easing
        if isinstance(easing, Sequence) and not isinstance(easing, str):
            easing = list(easing)
        return {
            "version": self.version,
            "keyframes": [
                {"t": t, "rect": {"x": r.x, "y": r.y, "w": r.w, "h": r.h}}
                for t, r in self.keyframes
            ],
            "interp": self.interp,
            "easing": easing,
            "output_aspect": self.output_aspect,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BurnsPath":
        """Rebuild a :class:`BurnsPath` from :meth:`to_dict` output.

        Examples:
            >>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
            >>> BurnsPath.from_dict(p.to_dict()) == p
            True
        """
        keyframes = tuple(
            (
                kf["t"],
                Rect(
                    kf["rect"]["x"], kf["rect"]["y"], kf["rect"]["w"], kf["rect"]["h"]
                ),
            )
            for kf in d["keyframes"]
        )
        easing = d.get("easing", DFLT_EASING)
        if isinstance(easing, list):
            easing = tuple(easing)
        return cls(
            keyframes=keyframes,
            easing=easing,
            interp=d.get("interp", "linear"),
            output_aspect=d.get("output_aspect"),
            version=d.get("version", SPEC_VERSION),
        )

    @classmethod
    def from_start_end(
        cls,
        start: Rect,
        end: Rect,
        *,
        easing: EasingLike = DFLT_EASING,
        output_aspect: Union[float, None] = None,
    ) -> "BurnsPath":
        """The canonical two-rectangle Ken Burns case (Start frame -> End frame).

        Examples:
            >>> BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
            ... # doctest: +ELLIPSIS
            BurnsPath(keyframes=((0.0, Rect(...)), (1.0, Rect(...))), ...)
        """
        return cls(
            keyframes=((0.0, start), (1.0, end)),
            easing=easing,
            output_aspect=output_aspect,
        )

    @classmethod
    def push_in(
        cls,
        zoom: float = 1.3,
        *,
        to: tuple[float, float] = (0.5, 0.5),
        easing: EasingLike = DFLT_EASING,
        output_aspect: Union[float, None] = None,
    ) -> "BurnsPath":
        """The 90%-case constructor: a slow push from the full image toward
        ``to`` at ``zoom``.

        Examples:
            >>> round(BurnsPath.push_in().evaluate(1.0).zoom, 4)
            1.3
        """
        cx, cy = to
        aspect = output_aspect if output_aspect is not None else 1.0
        return cls.from_start_end(
            Rect(0.0, 0.0, 1.0, 1.0)
            if output_aspect is None
            else Rect.from_center_zoom(0.5, 0.5, 1.0, aspect=aspect),
            Rect.from_center_zoom(cx, cy, zoom, aspect=aspect),
            easing=easing,
            output_aspect=output_aspect,
        )


# A single panel of a multi-image film: the still to animate, the motion path
# over it, and how long (seconds) it occupies the film. Audio is supplied
# separately as one combined track for the whole film (renderer stays pure
# visual), so it is not part of a panel.
PanelInput = tuple[Union[str, Path, Any], BurnsPath, float]


def ken_burns_path(
    index: int,
    *,
    style: str = "push",
    zoom: float = 1.10,
    pan: float = 0.03,
    easing: EasingLike = DFLT_EASING,
    output_aspect: Union[float, None] = None,
) -> BurnsPath:
    """A deterministic :class:`BurnsPath` for the ``index``-th image of a sequence.

    Maps intent to geometry so a sequence of images gets cohesive, non-repetitive
    motion without hand-authoring rectangles. Per-index deterministic: identical
    args always return an identical path. Duration is *not* part of the path — it
    is a render-time parameter (pass it to :func:`burns.ken_burns_video` /
    :func:`burns.ken_burns_film`).

    Two styles:

    - ``style="push"`` (default) — the "cinematic push": one slow zoom toward an
      off-center focal point. **Odd indices push in, even indices pull out**, so a
      sequence has visual rhythm without changing direction *within* a shot. The
      focal direction rotates through compass octants per index.
    - ``style="drift"`` — pure horizontal pan at a constant zoom, alternating
      direction per index (odd drifts right, even left). ``zoom`` is ignored;
      drift derives its own zoom from ``pan`` so the slide is visible.

    Args:
        index: the image's 1-based position in the sequence.
        style: ``"push"`` (default) or ``"drift"``.
        zoom: the zoomed-end magnification (> 1.0) for ``"push"``.
        pan: focal-point offset (``"push"``) or total horizontal travel
            (``"drift"``), in ``[0, 1]`` image units.
        easing: CSS timing function or callable. Default ``"ease-in-out"`` — the
            cinematic slow-in/slow-out. Pass ``"linear"`` for constant velocity.
        output_aspect: aspect ratio the render should fill (``None`` = match image).

    Returns:
        A :class:`BurnsPath` (two keyframes — Start and End).

    Examples:
        >>> ken_burns_path(1).evaluate(0.0)  # odd: push in, starts full
        Rect(x=0.0, y=0.0, w=1.0, h=1.0)
        >>> ken_burns_path(2).evaluate(1.0)  # even: pull out, ends full
        Rect(x=0.0, y=0.0, w=1.0, h=1.0)
        >>> ken_burns_path(3) == ken_burns_path(3)  # deterministic
        True
    """
    if style not in _VALID_STYLES:
        raise ValueError(
            f"ken_burns_path: style must be one of {_VALID_STYLES}, got {style!r}"
        )
    start, end = _endpoints_for_style(
        style, index, zoom=zoom, pan=pan, output_aspect=output_aspect
    )
    return BurnsPath.from_start_end(
        start, end, easing=easing, output_aspect=output_aspect
    )


def _endpoints_for_style(
    style: str,
    index: int,
    *,
    zoom: float,
    pan: float,
    output_aspect: Union[float, None],
) -> tuple[Rect, Rect]:
    """The ``(start_rect, end_rect)`` for one image under one style."""
    aspect = output_aspect if output_aspect is not None else 1.0
    if style == "push":
        # Focal direction cycles through compass octants per index.
        angle = (index * 2 + 1) * (math.pi / 4)
        off_cx = round(0.5 + pan * math.cos(angle), 4)
        off_cy = round(0.5 + pan * math.sin(angle), 4)
        full = Rect.from_center_zoom(0.5, 0.5, 1.0, aspect=aspect)
        offset = Rect.from_center_zoom(off_cx, off_cy, zoom, aspect=aspect)
        if index % 2 == 1:
            return full, offset  # push in
        return offset, full  # pull out

    # style == "drift": horizontal pan at a constant zoom.
    direction = 1 if index % 2 == 1 else -1
    half = min(pan, 0.45)  # pan must stay < 0.5
    start_cx = round(0.5 - direction * half, 4)
    end_cx = round(0.5 + direction * half, 4)
    # Smallest zoom whose window can reach 0.5 ± half, plus headroom so the
    # slide reads as motion rather than riding the edges.
    drift_zoom = round(1.0 / (1.0 - 2.0 * half) + 0.05, 4)
    return (
        Rect.from_center_zoom(start_cx, 0.5, drift_zoom, aspect=aspect),
        Rect.from_center_zoom(end_cx, 0.5, drift_zoom, aspect=aspect),
    )
