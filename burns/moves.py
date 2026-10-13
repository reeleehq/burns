"""The named camera moves, and the one resolver that expands one into a path.

A :class:`~burns.path.BurnsPath` is *resolved geometry*: rectangles measured
against one picture's pixels. That makes it the wrong thing to store when the
picture can change. What an editor wants to keep is the **authored intent** —
"push in on this, gently" — and have the rectangles computed against whatever
image is in the slot at render time. Replace the still and the move re-frames;
keep the still and the move is exactly what it was.

So this module is the vocabulary (:data:`MOVES`) plus the one function that
turns an intent into geometry (:func:`resolve_move`).

**One code path, two front doors.** ``resolve_move`` takes a *name* or an
explicit ``BurnsPath`` (or its ``to_dict()`` payload), so a caller that stores
both a named move and an optional hand-corrected path override makes one call
and the choice between them is made here — once — rather than once per consumer.
This is ``an.ir.camera.camera_keys``' arrangement: one table, not two tables
reconciled by a test.

**``seed`` replaces the ordinal, and does one job.** The motion in a sequence
used to be derived from each panel's *position* — style by ``i % 2``, zoom by
``i % 4``, push-or-pull by the parity of ``i``. Reordering one panel therefore
changed the camera on every panel after it, and "keep this move, change this
picture" was unexpressible. ``resolve_move`` is a pure function of its
arguments and never of a position; a caller mints a ``seed`` once, stores it
beside the move, and the move survives every reorder.

The seed's *only* job is choosing which concrete move ``"auto"`` becomes
(:func:`choose_move`). It deliberately does **not** perturb a named move's zoom
or framing: a named move is a decision, and a decision a seed can still nudge
is not one. Variety across a sequence comes from ``"auto"`` and from the
pictures themselves — the content-aware framing differs per image already.

    >>> import numpy as np
    >>> img = np.zeros((600, 800, 3), dtype='uint8'); img[380:520, 120:300] = 210
    >>> path = resolve_move("push_in", image=img, aspect=16 / 9, seed=41)
    >>> path.evaluate(1.0).zoom >= path.evaluate(0.0).zoom
    True
    >>> resolve_move("hold", image=img, aspect=16 / 9).evaluate(0.0) == \\
    ...     resolve_move("hold", image=img, aspect=16 / 9).evaluate(1.0)
    True
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Union

from burns.content import (
    Box,
    DFLT_KEEP_PAD,
    as_pil,
    axis_maxima,
    content_aware_path,
    fit_zoom,
    keep_window,
    pad_box,
    salient_box,
)
from burns.easing import DFLT_EASING, EasingLike
from burns.path import BurnsPath
from burns.rect import Rect

__all__ = [
    "MOVES",
    "AUTO_WEIGHTS",
    "RESOLVER_IMPL_VERSION",
    "DFLT_ZOOM",
    "DIFFUSE_KEEP_AREA",
    "DRIFT_TRAVEL",
    "DRIFT_SPAN",
    "DRIFT_MIN_ROOM",
    "MoveError",
    "choose_move",
    "move_kind",
    "resolve_move",
]

#: The identity of the resolver's *geometry*, for a caller's cache key.
#:
#: A stored panel is an intent, so the pixels it becomes depend on constants
#: that live here — :data:`DFLT_ZOOM`, :data:`DRIFT_TRAVEL`, :data:`DRIFT_SPAN`,
#: :data:`DRIFT_MIN_ROOM`, :data:`AUTO_WEIGHTS` and the order
#: :func:`choose_move` draws from. Retune any of them and an **unchanged** panel
#: renders differently.
#:
#: A consumer that caches a render keyed on the panel alone would therefore
#: serve the old frames forever, or silently produce a cut that disagrees with
#: its siblings. Put this in the key. It is ``nw.Transform.impl_version``'s
#: contract — *a lock, not a receipt*: bump it whenever the geometry changes for
#: an unchanged input, and leave it alone for a docstring or a new move name.
#:
#: Deliberately **not** the package version: a burns release that touches only
#: the renderer must not invalidate anybody's cut, and
#: ``importlib.metadata.version("burns")`` is unreliable here besides.
RESOLVER_IMPL_VERSION: int = 2
# 2: a diffuse saliency keep-region is a centre hint, not a cap, and saliency
#    can be confined to a ``content_box`` (thorwhalen/burns#21).

#: The area (share of the picture) around which a saliency keep-region that
#: reaches the borders stops being a subject and becomes a centre hint.
#: On a detailed photograph gradient saliency marks nearly everything, and
#: treating that as a subject capped every requested zoom at ~1.0, so
#: ``push_in`` rendered its ~1.07 floor whatever was asked (burns#21, measured
#: on 10 of 10 archive photos). Such a region is replaced by the largest keep-
#: region that still honours the requested zoom, centred where saliency
#: points. An explicit ``focus`` is never treated this way: it is a decision.
#: It is the centre of a ramp (:data:`DIFFUSE_KEEP_RAMP`) and applies only to a
#: box touching :data:`DIFFUSE_MIN_EDGES` borders; the default centred box
#: (:data:`~burns.content.DFLT_KEEP_BOX`) touches none, so a uniform picture
#: keeps its old framing.
DIFFUSE_KEEP_AREA: float = 0.5
#: The width of the area ramp around :data:`DIFFUSE_KEEP_AREA` over which a box
#: turns from subject into centre hint (0.45 → 0.55), so framing never flips.
DIFFUSE_KEEP_RAMP: float = 0.1
#: A diffuse box reaches the borders: texture everywhere touches at least this
#: many of the four image edges, a large subject on a flat field does not.
DIFFUSE_MIN_EDGES: int = 3
#: A box edge within ``_EDGE_NEAR`` of the border fully touches it, one beyond
#: ``_EDGE_FAR`` does not, linearly between — a ramp, not a threshold, so a 2 %
#: change in content cannot flip the framing. Saliency trims 4 % percentiles
#: and pads 5 %, so texture-everywhere sits 3–7 % in on real photographs.
_EDGE_NEAR: float = 0.04
_EDGE_FAR: float = 0.12
#: Smallest ``content_box`` side, in pixels, saliency can run on.
_MIN_CONTENT_PX: int = 4
#: ``salient_box``'s default ``downscale`` (long side, px), which the guard
#: above has to anticipate.
_SALIENCY_DOWNSCALE: int = 320
#: How far under the requested zoom's window a centre-hint keep-region is
#: sized, so the ``0.98`` framing margins downstream never bind on it.
_HINT_MARGIN: float = 0.96

#: Default end magnification. Enough that a slow push reads as movement on a
#: 1080p frame, little enough that a found still is not visibly softened by the
#: upscale.
#:
#: A **drift** may render slightly above it: reaching :data:`DRIFT_SPAN` needs
#: :data:`DRIFT_MIN_ROOM` of travel room, which at this zoom is marginally more
#: than the window leaves, so the floor raises it to ~1.2. That is the floor
#: working, not a jitter — it is a pure function of the arguments.
DFLT_ZOOM: float = 1.18

#: How much of the available travel a drift uses, as a fraction of the room the
#: window leaves inside the image. Less than ``1.0`` on purpose: a drift that
#: runs wall to wall starts and ends against an edge, which reads as the frame
#: hitting a stop rather than as a camera continuing past the cut.
DRIFT_TRAVEL: float = 0.5

#: A ceiling on that travel, as a fraction of the **window** rather than of the
#: image — how far the camera crosses its own frame.
#:
#: Without it a drift's speed is whatever room the picture happened to leave,
#: which is not the same on both axes: on a 4:3 still delivered at 16:9 there is
#: twice as much vertical room as horizontal, so ``drift_up`` travelled ~29 % of
#: the frame where ``drift_left`` travelled ~9 % — the same named gesture at
#: three times the speed, decided by the aspect of the picture. ``an``'s camera
#: hit the same asymmetry from the other direction and answered it the same way,
#: with one fraction of the frame per axis (``an.ir.camera.PAN_FRACTION``).
#:
#: A tenth is calibrated against what the room-limited horizontal case already
#: produces at :data:`DFLT_ZOOM`, and against ``ken_burns_path(style="drift")``'s
#: ~7 %: legible at 1080p over a normal panel, and not a whip.
DRIFT_SPAN: float = 0.10

#: The least travel room a drift will accept, in image units. When the
#: requested ``zoom`` leaves less, the zoom is *raised* until it does — the same
#: way ``content_aware_path``'s ``min_zoom`` floor wins over its framing cap.
#: A drift with no room is a hold, and silently returning one is the failure
#: this floor exists to prevent.
#:
#: **It is derived, not chosen**, and the derivation is the point. Travel is
#: ``min(room * DRIFT_TRAVEL, size * DRIFT_SPAN)`` with ``size == 1 - room``, so
#: the span can only ever bind when
#: ``room >= DRIFT_SPAN / (DRIFT_TRAVEL + DRIFT_SPAN)`` — one sixth, at the
#: values above. Set below that and the two constants can *never* both bind:
#: the floor silently wins everywhere, every room-limited drift crosses
#: ``DRIFT_TRAVEL * DRIFT_MIN_ROOM / (1 - DRIFT_MIN_ROOM)`` of its frame, and
#: :data:`DRIFT_SPAN`'s promise that the two axes read at the same speed holds
#: only on pictures with room to spare. At ``0.08`` it measured 2.3x apart on a
#: portrait still delivered at 16:9 — the exact asymmetry DRIFT_SPAN exists to
#: remove. ``tests/test_moves.py`` pins the relationship, so changing either
#: constant without the other fails.
DRIFT_MIN_ROOM: float = DRIFT_SPAN / (DRIFT_TRAVEL + DRIFT_SPAN)

#: Slack when comparing a stored path's ``output_aspect`` against the render's.
#: **Relative**, not absolute: an absolute tolerance on a ratio is four times
#: stricter for 2.39:1 scope than for a 9:16 vertical, which is not a judgement
#: anybody made. It exists only to absorb float noise between two spellings of
#: the same shape (``1920 / 1080`` against ``16 / 9``), never to let a genuinely
#: different delivery through.
_ASPECT_REL_TOL: float = 1e-9


class MoveError(ValueError):
    """A move that cannot be resolved into a path.

    A plain :class:`ValueError` subclass, so a consumer that already catches
    ``ValueError`` around its authoring layer keeps working, and so nothing
    downstream needs to import :mod:`burns.moves` to handle it.
    """


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Frame:
    """Everything a move builder needs: the picture, the intent, the delivery."""

    img_w: int
    img_h: int
    keep: Box  # the UNPADDED keep-region; each builder pads as it needs
    zoom: float
    aspect: Union[float, None]
    easing: EasingLike

    @property
    def padded(self) -> Box:
        return pad_box(self.keep, DFLT_KEEP_PAD)

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.padded
        return (x + w / 2, y + h / 2)

    def capped_zoom(self) -> float:
        """``zoom``, capped so the padded keep-region still fits the window."""
        cap = fit_zoom(
            self.img_w, self.img_h, keep=self.padded, output_aspect=self.aspect
        )
        return max(1.0, min(self.zoom, cap * 0.98))


@dataclass(frozen=True)
class _MoveSpec:
    """One row of the vocabulary: how a name is grouped, and how it is built."""

    kind: str  # "zoom" | "drift" | "static" | "select"
    build: Union[Callable[[_Frame], BurnsPath], None]


def _zoom_move(mode: str) -> Callable[[_Frame], BurnsPath]:
    """A zoom-led move: two windows on the same centre, differing in zoom."""

    def build(f: _Frame) -> BurnsPath:
        return content_aware_path(
            f.img_w,
            f.img_h,
            subject=f.keep,
            output_aspect=f.aspect,
            zoom=f.zoom,
            keep_pad=DFLT_KEEP_PAD,
            mode=mode,
            easing=f.easing,
        )

    return build


def _static(f: _Frame) -> BurnsPath:
    """A hold: two keyframes with equal rects.

    Two rather than one because that is what the spec calls a hold. (A
    one-keyframe path is also valid, in Python, TypeScript and on the wire; the
    built-in moves still emit the canonical two so a hold reads like any other
    Start/End path to a UI that edits it.)

    ``zoom`` is honoured: a hold is a *static framing*, not necessarily the
    whole picture. Pass ``zoom=1.0`` for the untouched frame.
    """
    window = keep_window(
        f.img_w,
        f.img_h,
        center=f.center,
        zoom=f.capped_zoom(),
        output_aspect=f.aspect,
    )
    return BurnsPath(
        keyframes=((0.0, window), (1.0, window)),
        easing=f.easing,
        output_aspect=f.aspect,
    )


def _drift(axis: str, sign: float) -> Callable[[_Frame], BurnsPath]:
    """A pan-led move: one window translated along ``axis``.

    **The name is the direction the CAMERA travels**, which is the direction the
    *content* appears to travel the other way — ``drift_right`` ends with the
    window further right, so the picture slides left across the frame. This is
    the convention ``ken_burns_path(style="drift")`` and ``an``'s ``pan_left``
    already use; the opposite reading is the one people reach for first, which
    is why it is written down rather than inferred.

    The travel is centred on the keep-region, so the subject is mid-frame at the
    midpoint of the move rather than arriving or departing; the cross axis stays
    locked to the keep-region, so a horizontal drift cannot slide off a face.
    """

    def build(f: _Frame) -> BurnsPath:
        zoom = max(f.capped_zoom(), _zoom_for_room(f, axis))
        window = keep_window(
            f.img_w, f.img_h, center=f.center, zoom=zoom, output_aspect=f.aspect
        )
        size = window.w if axis == "x" else window.h
        base = (f.center[0] if axis == "x" else f.center[1]) - size / 2
        lo, hi = 0.0, max(0.0, 1.0 - size)
        # Up to half the room, but never more than DRIFT_SPAN of the frame, so
        # a vertical and a horizontal drift read at the same speed on a picture
        # whose two axes leave very different amounts of room.
        half = min((hi - lo) * DRIFT_TRAVEL, size * DRIFT_SPAN) / 2.0
        # Slide the whole travel interval inside the image rather than clamping
        # each end: clamping ends independently collapses the travel to zero
        # whenever the keep-region sits near an edge, which is a silent hold.
        a, b = base - half, base + half
        if a < lo:
            a, b = lo, lo + 2 * half
        elif b > hi:
            a, b = hi - 2 * half, hi
        first, last = (a, b) if sign > 0 else (b, a)
        if axis == "x":
            start = Rect(first, window.y, window.w, window.h)
            end = Rect(last, window.y, window.w, window.h)
        else:
            start = Rect(window.x, first, window.w, window.h)
            end = Rect(window.x, last, window.w, window.h)
        return BurnsPath.from_start_end(
            start.clamped(), end.clamped(), easing=f.easing, output_aspect=f.aspect
        )

    return build


def _zoom_for_room(f: _Frame, axis: str) -> float:
    """The zoom at which the window leaves :data:`DRIFT_MIN_ROOM` to travel.

    The window is ``min(m / z, 1)`` of the image on ``axis``, so the room is
    ``1 - m / z`` and the zoom that buys ``r`` of room is ``m / (1 - r)``.
    """
    wmax, hmax = axis_maxima(f.img_w, f.img_h, f.aspect)
    m = wmax if axis == "x" else hmax
    return m / (1.0 - DRIFT_MIN_ROOM)


#: The vocabulary, as ONE table. ``MOVES`` and :func:`move_kind` are read off
#: it, so a UI that groups the directional moves separately from the static and
#: automatic ones does not maintain a second list that can disagree with this
#: one about what a valid move is.
#:
#: ``"auto"`` carries no builder: it is a *selector* over the others, resolved
#: to a concrete name by :func:`choose_move` before any geometry is built.
_MOVES: dict[str, _MoveSpec] = {
    "push_in": _MoveSpec("zoom", _zoom_move("in")),
    "pull_out": _MoveSpec("zoom", _zoom_move("out")),
    "drift_left": _MoveSpec("drift", _drift("x", -1.0)),
    "drift_right": _MoveSpec("drift", _drift("x", +1.0)),
    "drift_up": _MoveSpec("drift", _drift("y", -1.0)),
    "drift_down": _MoveSpec("drift", _drift("y", +1.0)),
    "hold": _MoveSpec("static", _static),
    "auto": _MoveSpec("select", None),
}

#: Every name a stored ``move`` field may hold — one vocabulary, because it is
#: one field. ``"hold"`` and ``"auto"`` sit beside the directional moves for
#: that reason: splitting them into separate constants would make a consumer
#: union two tuples to validate one field. They differ in *kind*, not in
#: membership, and :func:`move_kind` is where that difference is read.
#:
#: **burns owns this vocabulary.** A consumer that needs to validate its own
#: stored field before a render (rather than discovering a typo five minutes
#: in) will mirror it; that mirror must be pinned equal to this tuple by a test
#: that *fails* when burns is absent rather than skipping, or the two drift
#: silently. burns is deliberately strict about the spelling — no case folding
#: and no whitespace stripping — so a mirror written as a plain membership test
#: agrees with it exactly.
MOVES: tuple[str, ...] = tuple(_MOVES)

#: How often ``"auto"`` picks each move, as integer weights. Pushes and pulls
#: dominate because a commentary film is mostly faces and documents, where a
#: drift wanders off the thing being talked about; the drifts are there so a
#: long sequence does not read as one move repeated.
#: Read-only on purpose. The pool :func:`choose_move` draws from is built once
#: at import, so assigning into a plain dict here would change the documented
#: weights and change nothing about the moves — a silent no-op in a name that
#: is in ``__all__``. Retuning these is a burns change that bumps
#: :data:`RESOLVER_IMPL_VERSION`, not something a consumer does at runtime.
AUTO_WEIGHTS: Mapping[str, int] = MappingProxyType(
    {
        "push_in": 3,
        "pull_out": 3,
        "drift_left": 1,
        "drift_right": 1,
        "drift_up": 1,
        "drift_down": 1,
    }
)

_AUTO_POOL: tuple[str, ...] = tuple(
    name for name, weight in AUTO_WEIGHTS.items() for _ in range(weight)
)


def move_kind(move: str) -> str:
    """How ``move`` is grouped: ``"zoom"``, ``"drift"``, ``"static"``, ``"select"``.

    For a UI that wants a compass of directions separately from the rest, read
    off the same table :func:`resolve_move` dispatches on.

    Examples:
        >>> move_kind("drift_left"), move_kind("hold"), move_kind("auto")
        ('drift', 'static', 'select')
        >>> sorted(m for m in MOVES if move_kind(m) == 'drift')
        ['drift_down', 'drift_left', 'drift_right', 'drift_up']
    """
    spec = _MOVES.get(move)
    if spec is None:
        raise MoveError(_unknown_move_message(move))
    return spec.kind


# --------------------------------------------------------------------------
# The seed
# --------------------------------------------------------------------------


def _mix(seed: int) -> int:
    """A stable 64-bit scramble of ``seed`` (splitmix64's finalizer).

    Python's ``hash()`` cannot be the basis of a *persisted* choice: it is
    salted for strings and unspecified for large integers, so the move a stored
    seed resolves to could differ between processes. This is arithmetic, so it
    does not.

    Examples:
        >>> _mix(0) == _mix(0)
        True
        >>> _mix(0) != _mix(1)
        True
    """
    mask = 0xFFFFFFFFFFFFFFFF
    x = (int(seed) + 0x9E3779B97F4A7C15) & mask
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & mask
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & mask
    return x ^ (x >> 31)


def choose_move(seed: int) -> str:
    """Which concrete move ``"auto"`` resolves to for ``seed``.

    Public because "auto" is a decision a person may want to *see* (a UI
    showing ``auto → drift_left``) and to *pin* (liking what auto chose and
    storing that name instead, so it survives a change to the weights).

    A pure function of ``seed`` alone — not of the image, and not of any
    position in a sequence. That is what makes a panel's move survive both a
    reorder and a swapped still.

    Examples:
        >>> choose_move(7) == choose_move(7)
        True
        >>> choose_move(7) in MOVES and choose_move(7) != 'auto'
        True
        >>> len({choose_move(s) for s in range(60)}) > 1   # not one move forever
        True
    """
    return _AUTO_POOL[_mix(seed) % len(_AUTO_POOL)]


# --------------------------------------------------------------------------
# The resolver
# --------------------------------------------------------------------------

#: What ``move`` accepts: a name, a built path, or a ``to_dict()`` payload.
MoveLike = Union[str, BurnsPath, Mapping[str, Any]]

#: What ``focus`` accepts: a :class:`~burns.rect.Rect`, a 4-tuple, or anything
#: with ``.x/.y/.w/.h``. burns does not define a competing rectangle type and
#: does not require consumers to import its own — a pydantic model with those
#: four fields is a focus box.
FocusLike = Any


def resolve_move(
    move: MoveLike,
    *,
    image: Any,
    aspect: Union[float, None],
    zoom: float = DFLT_ZOOM,
    focus: FocusLike = None,
    seed: int = 0,
    easing: EasingLike = DFLT_EASING,
    on_aspect_mismatch: str = "raise",
    content_box: FocusLike = None,
) -> BurnsPath:
    """Resolve an authored camera intent against ``image`` into a path.

    Args:
        move: a name from :data:`MOVES`, or an explicit
            :class:`~burns.path.BurnsPath` / its ``to_dict()`` payload. The two
            are the two front doors on this one path: a stored panel that
            carries both a named move and a hand-corrected override passes the
            override here and the choice is made in one place.
        image: the still the move is framed against — a path, ``PIL.Image`` or
            ndarray. **Required, and read every time**: the framing depends on
            what is in the picture, so swapping the still must re-frame. Do not
            cache the returned path against the intent.
        aspect: the delivered ``width / height``. ``None`` means "match the
            image". Required rather than defaulted, because a cut has a
            delivery size and quietly framing for the image's aspect instead is
            a cover-crop nobody asked for.
        zoom: the end magnification. A pure function of the arguments — never
            jittered by ``seed`` or by a position — but **bounded at both
            ends**, so the number you pass is a request:

            * capped so the padded keep-region stays framed. A ``focus``
              filling the frame therefore yields a nearly static move; the fix
              is a tighter ``focus``, not a bigger ``zoom``. A keep-region
              that *saliency* found covering :data:`DIFFUSE_KEEP_AREA` or more
              of the picture is only a centre hint and does not cap: on a
              detailed photograph it covers nearly everything, and capping on
              it made every zoom render the same ~1.07.
            * floored. ``push_in`` / ``pull_out`` inherit
              ``content_aware_path``'s ``min_zoom + 0.02`` (about 1.07), so a
              barely-there 1.02 push renders as 1.07; ``hold`` has no such floor
              and honours 1.02 exactly. A drift is floored to whatever leaves
              :data:`DRIFT_MIN_ROOM` of travel.
        focus: an explicit keep-region overriding the saliency estimate. A
            :class:`~burns.rect.Rect`, a normalized ``(x, y, w, h)`` tuple, or
            any object with ``.x/.y/.w/.h``. When given,
            :func:`~burns.content.salient_box` is not called at all.
        seed: chooses which move ``"auto"`` becomes, and nothing else. Mint it
            once per panel and store it; never derive it from a position, which
            is the defect this parameter exists to remove.
        easing: CSS timing function or callable. A callable is fine here but
            cannot be serialized — see :meth:`BurnsPath.to_dict`. Applies to a
            named move; an explicit path carries its own.
        content_box: the part of ``image`` that is picture, as a normalized
            ``(x, y, w, h)`` (same forms as ``focus``). Saliency runs inside it,
            so the blurred fill or bars a caller composited around a still do
            not read as subject. Ignored when ``focus`` is given.
        on_aspect_mismatch: what to do when an explicit path was authored for a
            different ``output_aspect`` than the one being rendered.
            ``"raise"`` (default) refuses, because honouring the stored
            rectangles at another shape cover-crops a framing somebody chose by
            hand. ``"refit"`` rebuilds each keyframe at the new aspect,
            **keeping what the author actually chose** — where the camera looks
            at each instant, and how far in it is — and changing only the window
            shape. A cut in a second aspect is a real workflow (a vertical
            edit of a landscape film), and a panel carries *one* path, not one
            per delivery, so "author a second path" is not a remedy a caller
            can take; ``"refit"`` is.

    Returns:
        A :class:`~burns.path.BurnsPath`. Duration is not part of it; pass that
        to the renderer.

    Raises:
        MoveError: an unknown move name, a malformed ``focus``, a non-positive
            ``zoom`` or ``aspect``, or — under the default
            ``on_aspect_mismatch="raise"`` — an explicit path whose
            ``output_aspect`` contradicts ``aspect``.

    Note:
        ``image`` is opened for every *named* move. For an explicit path it is
        read only when refitting, since resolved geometry needs no picture.

    Examples:
        >>> import numpy as np
        >>> img = np.zeros((600, 800, 3), dtype='uint8'); img[300:460, 500:700] = 230

        A named move is a decision, so the seed does not touch it:

        >>> resolve_move("push_in", image=img, aspect=16 / 9, seed=1) == \\
        ...     resolve_move("push_in", image=img, aspect=16 / 9, seed=999)
        True

        ``"auto"`` is where the seed does its one job:

        >>> a = resolve_move("auto", image=img, aspect=16 / 9, seed=3)
        >>> a == resolve_move("auto", image=img, aspect=16 / 9, seed=3)
        True

        A drift travels — and ``drift_right`` ends further right:

        >>> d = resolve_move("drift_right", image=img, aspect=16 / 9)
        >>> d.evaluate(1.0).x > d.evaluate(0.0).x
        True

        An explicit path is the other front door, returned as authored:

        >>> from burns import BurnsPath, Rect
        >>> hand = BurnsPath.from_start_end(
        ...     Rect(0, 0, 1, 1), Rect(0.1, 0.1, 0.6, 0.6), output_aspect=16 / 9
        ... )
        >>> resolve_move(hand.to_dict(), image=img, aspect=16 / 9) == hand
        True

        Rendering it at another delivery refuses by default, and ``"refit"``
        keeps the authored look while changing the window shape:

        >>> resolve_move(hand, image=img, aspect=9 / 16)
        Traceback (most recent call last):
            ...
        burns.moves.MoveError: ...
        >>> v = resolve_move(hand, image=img, aspect=9 / 16,
        ...                  on_aspect_mismatch="refit")
        >>> v.output_aspect == 9 / 16
        True
        >>> before = [round(c, 4) for c in hand.evaluate(1.0).center]
        >>> after = [round(c, 4) for c in v.evaluate(1.0).center]
        >>> before == after          # the author's framing, at the new shape
        True
    """
    aspect = _checked_aspect(aspect)
    if on_aspect_mismatch not in _ASPECT_MISMATCH_ACTIONS:
        raise MoveError(
            f"on_aspect_mismatch must be one of "
            f"{list(_ASPECT_MISMATCH_ACTIONS)}, got {on_aspect_mismatch!r}"
        )

    if isinstance(move, Mapping):
        try:
            move = BurnsPath.from_dict(dict(move))
        except (KeyError, TypeError) as e:
            raise MoveError(
                f"a mapping passed as `move` is read as a BurnsPath.to_dict() "
                f"payload and this one is not well-formed ({e!r}). A move name "
                f"goes in as a string, one of {list(MOVES)}."
            ) from e
    if isinstance(move, BurnsPath):
        return _adopt(move, aspect, image=image, on_mismatch=on_aspect_mismatch)
    if not isinstance(move, str):
        raise MoveError(_unknown_move_message(move))

    # No `.strip()`: leniency here is invisible divergence. A consumer that
    # mirrors MOVES to validate its own field (braidio's panel body does)
    # rejects " push_in " while burns would accept it, so the same stored
    # value is valid in one package and not the other.
    name = move
    spec = _MOVES.get(name)
    if spec is None:
        raise MoveError(_unknown_move_message(move))
    if spec.kind == "select":
        name = choose_move(seed)
        spec = _MOVES[name]

    img = as_pil(image)
    img_w, img_h = img.size
    zoom = _checked_zoom(zoom)
    if focus is not None:
        keep = _focus_box(focus)
    else:
        keep = _saliency_keep(
            img,
            None
            if content_box is None
            else _focus_box(content_box, what="content_box"),
            zoom=zoom,
            aspect=aspect,
        )
    return spec.build(
        _Frame(
            img_w=img_w,
            img_h=img_h,
            keep=keep,
            zoom=zoom,
            aspect=aspect,
            easing=easing,
        )
    )


def _diffuseness(box: Box) -> float:
    """How much a saliency box reads as *texture everywhere* rather than a subject, in [0, 1].

    Two signals, because area alone cannot tell a detailed photograph from one
    large subject on a flat field (a 0.69-sided block crossed a hard 0.5-area
    threshold and was suddenly cropped at 1.3x). Texture everywhere reaches the
    picture's borders: the box must reach :data:`DIFFUSE_MIN_EDGES` of them,
    each edge's reach itself ramped (``_EDGE_NEAR`` → ``_EDGE_FAR``). Then the
    area ramps the weight in over ``DIFFUSE_KEEP_AREA ± DIFFUSE_KEEP_RAMP / 2``.
    Both ramps, so no small change in the box flips the framing.

    The trade-off, stated: a large *subject* that genuinely reaches three
    borders (a figure filling the height and one side) reads as diffuse, and
    at a strong zoom (1.3) the window keeps ~0.6 of its box where it used to
    keep ~0.7–0.8. An explicit ``focus`` restores the old cap.

    >>> _diffuseness((0.0, 0.0, 1.0, 1.0))
    1.0
    >>> _diffuseness((0.15, 0.15, 0.7, 0.7))   # a big centred subject
    0.0
    >>> _diffuseness((0.0, 0.38, 1.0, 0.62))   # sky over detail: diffuse
    1.0
    """
    x, y, w, h = box

    def reach(gap: float) -> float:  # 1 at the border, 0 once clearly inside
        return min(1.0, max(0.0, (_EDGE_FAR - gap) / (_EDGE_FAR - _EDGE_NEAR)))

    touches = reach(x) + reach(y) + reach(1 - x - w) + reach(1 - y - h)
    edges = min(1.0, max(0.0, touches - (DIFFUSE_MIN_EDGES - 1)))
    lo = DIFFUSE_KEEP_AREA - DIFFUSE_KEEP_RAMP / 2
    return edges * min(1.0, max(0.0, (w * h - lo) / DIFFUSE_KEEP_RAMP))


def _saliency_keep(img, content_box, *, zoom: float, aspect) -> Box:
    """The keep-region saliency supports, in ``img``'s normalized coordinates.

    Saliency runs inside ``content_box`` (the whole image when ``None``), so a
    blurred fill or letterbox around a composited still never reads as
    subject: the seam between still and fill is a hard edge, and it widened
    every box to the full still plus both seams. A diffuse region (see
    :func:`_diffuseness`) is shrunk toward a centre hint that honours the
    requested zoom, by as much as it is diffuse.

    >>> import numpy as np
    >>> busy = (np.random.default_rng(0).random((300, 400)) * 255).astype("uint8")
    >>> x, y, w, h = _saliency_keep(as_pil(busy), None, zoom=1.3, aspect=16 / 9)
    >>> w * h < DIFFUSE_KEEP_AREA          # no longer the whole picture
    True
    """
    bx, by, bw, bh = content_box if content_box is not None else (0.0, 0.0, 1.0, 1.0)
    if content_box is not None:
        img_w, img_h = img.size
        x0, y0 = int(round(bx * img_w)), int(round(by * img_h))
        x1 = max(x0 + 1, int(round((bx + bw) * img_w)))
        y1 = max(y0 + 1, int(round((by + bh) * img_h)))
        cw, ch = x1 - x0, y1 - y0
        # salient_box downscales the long side to its `downscale` first, so the
        # short side must survive that too, or it silently returns its default
        shrunk = min(cw, ch) * min(1.0, _SALIENCY_DOWNSCALE / max(cw, ch))
        if min(cw, ch) < _MIN_CONTENT_PX or shrunk < _MIN_CONTENT_PX:
            raise MoveError(
                f"content_box {content_box} covers {cw}x{ch} px of a "
                f"{img_w}x{img_h} image; saliency needs at least "
                f"{_MIN_CONTENT_PX} px on each side after downscaling the long "
                f"side to {_SALIENCY_DOWNSCALE} px"
            )
        region = img.crop((x0, y0, x1, y1))
    else:
        region = img
    sbox = salient_box(region)
    sx, sy, sw, sh = sbox
    keep = (bx + sx * bw, by + sy * bh, sw * bw, sh * bh)
    t = _diffuseness(sbox)
    if t <= 0.0:
        return keep
    wmax, hmax = axis_maxima(*img.size, aspect)
    grow = 1 + 2 * DFLT_KEEP_PAD
    hint_w = min(keep[2], _HINT_MARGIN * wmax / zoom / grow)
    hint_h = min(keep[3], _HINT_MARGIN * hmax / zoom / grow)
    w = keep[2] + (hint_w - keep[2]) * t
    h = keep[3] + (hint_h - keep[3]) * t
    cx, cy = keep[0] + keep[2] / 2, keep[1] + keep[3] / 2
    return (cx - w / 2, cy - h / 2, w, h)


#: What ``on_aspect_mismatch`` accepts. A tuple rather than an enum because it
#: crosses the wire as a plain string from whatever surface the caller exposes.
_ASPECT_MISMATCH_ACTIONS: tuple[str, ...] = ("raise", "refit")


def _checked_aspect(aspect: Union[float, None]) -> Union[float, None]:
    """``aspect`` as a positive float, or ``None``, or a refusal.

    ``0.0`` and a negative are refused rather than passed through. Zero is
    falsy, so it would reach :func:`~burns.content.axis_maxima` and quietly mean
    "match the image" — exactly the cover-crop-nobody-asked-for this argument is
    required in order to prevent, arriving as a plausible ``width / height``
    from a body whose width was never filled in. A negative produces a
    negative-width window that still passes ``Rect.is_contained()`` and reaches
    the renderer. :meth:`Rect.from_center_zoom` already refuses a non-positive
    zoom; this is the same rule at the new front door.
    """
    if aspect is None:
        return None
    try:
        value = float(aspect)
    except (TypeError, ValueError) as e:
        raise MoveError(f"aspect must be a number or None, got {aspect!r}") from e
    if not value > 0 or value != value or value in (float("inf"), float("-inf")):
        raise MoveError(
            f"aspect must be a positive, finite width/height ratio, or None to "
            f"match the image — got {aspect!r}. A 0 here would silently mean "
            "'match the image', which is the cover-crop this argument exists to "
            "make impossible."
        )
    return value


def _checked_zoom(zoom: float) -> float:
    """``zoom`` as a positive float, or a refusal (as ``Rect.from_center_zoom``)."""
    try:
        value = float(zoom)
    except (TypeError, ValueError) as e:
        raise MoveError(f"zoom must be a number, got {zoom!r}") from e
    if not value > 0 or value != value or value == float("inf"):
        raise MoveError(
            f"zoom must be a positive, finite magnification (1.0 = the whole "
            f"frame), got {zoom!r}"
        )
    return value


def _aspects_agree(stored: float, aspect: Union[float, None]) -> bool:
    """Whether two aspect ratios are the same shape up to float noise."""
    if aspect is None:
        return False
    return math.isclose(float(stored), float(aspect), rel_tol=_ASPECT_REL_TOL)


def _adopt(
    path: BurnsPath,
    aspect: Union[float, None],
    *,
    image: Any,
    on_mismatch: str,
) -> BurnsPath:
    """An explicit path, reconciled with the delivery aspect.

    A hand-corrected path is *resolved geometry*: its rectangles were drawn for
    one output shape. Silently honouring them at another cover-crops somebody's
    authored framing, which is the shape of defect this module exists to
    remove — so that never happens. What happens instead is the caller's call.

    ``output_aspect=None`` is not a mismatch — it is a path that says "match the
    image", a deliberate authoring choice, and is preserved.
    """
    stored = path.output_aspect
    if stored is None or _aspects_agree(stored, aspect):
        return path
    if on_mismatch == "refit":
        img_w, img_h = as_pil(image).size
        return _refit(path, img_w, img_h, aspect)
    raise MoveError(
        f"this panel carries an explicit BurnsPath authored for "
        f"output_aspect={stored!r}, but the cut is being rendered at "
        f"aspect={aspect!r}. Its rectangles were drawn against the first shape, "
        "so honouring them at the second would silently crop the framing "
        "somebody chose by hand. Either render this cut at the aspect the path "
        "was authored for, pass on_aspect_mismatch='refit' to keep the authored "
        "look at the new shape, or drop the override so the named move re-frames."
    )


def _refit(
    path: BurnsPath, img_w: int, img_h: int, aspect: Union[float, None]
) -> BurnsPath:
    """Rebuild every keyframe at ``aspect``, keeping what the author chose.

    A keyframe says two things a person decided — *where the camera is looking*
    and *how far in it is* — plus one thing the delivery decided, the window's
    shape. Refitting keeps the first two and recomputes the third, so a
    landscape film's hand-corrected move survives into a vertical cut as the
    same move rather than as a refusal or a silent crop.

    It is **not** lossless and does not pretend to be: a 16:9 window refitted to
    9:16 shows less to the sides and more above and below, because that is what
    the delivery is. What it guarantees is that the centre and the zoom are the
    author's at every instant.
    """
    keyframes = tuple(
        (
            t,
            keep_window(
                img_w, img_h, center=rect.center, zoom=rect.zoom, output_aspect=aspect
            ),
        )
        for t, rect in path.keyframes
    )
    return BurnsPath(
        keyframes=keyframes,
        easing=path.easing,
        interp=path.interp,
        output_aspect=aspect,
        version=path.version,
    )


def _focus_box(focus: FocusLike, *, what: str = "focus") -> Box:
    """Normalize ``focus`` to a ``(x, y, w, h)`` box, or say why it is not one."""
    if isinstance(focus, Mapping):
        # What a stored focus looks like after a JSON round-trip, which is how
        # it reaches a consumer that persists panels rather than holds models.
        missing = [k for k in ("x", "y", "w", "h") if k not in focus]
        if missing:
            raise MoveError(
                f"a {what} mapping needs the keys x, y, w, h — missing {missing}"
            )
        box = tuple(focus[k] for k in ("x", "y", "w", "h"))
    elif all(hasattr(focus, a) for a in ("x", "y", "w", "h")):
        # Covers Rect and every structural rectangle a consumer already has —
        # burns does not make anyone import its type to say where to look.
        box = (focus.x, focus.y, focus.w, focus.h)
    else:
        try:
            box = tuple(float(v) for v in focus)
        except (TypeError, ValueError) as e:
            # ValueError as well as TypeError: a str is iterable, so `focus="nope"`
            # reached float() and escaped as a bare ValueError from a generator
            # expression, three frames from anything that named the argument.
            raise MoveError(
                f"{what} must be a Rect, a normalized (x, y, w, h) sequence of 4 "
                f"components, or an object with .x/.y/.w/.h — got "
                f"{type(focus).__name__} {focus!r}"
            ) from e
        if len(box) != 4:
            raise MoveError(
                f"{what} must have exactly 4 components (x, y, w, h), got {len(box)}"
            )
    x, y, w, h = (float(v) for v in box)
    if w <= 0 or h <= 0:
        raise MoveError(
            f"{what} must have positive width and height, got {(x, y, w, h)}"
        )
    if not (-1e-6 <= x and -1e-6 <= y and x + w <= 1 + 1e-6 and y + h <= 1 + 1e-6):
        raise MoveError(
            f"{what} must lie inside the image in normalized [0, 1] units with a "
            f"top-left origin, got {(x, y, w, h)}. A box in pixels is the usual "
            "cause — divide by the image's width and height."
        )
    return (x, y, w, h)


def _unknown_move_message(move: Any) -> str:
    return (
        f"unknown camera move {move!r}. The vocabulary is {list(MOVES)}. "
        "Pass an explicit BurnsPath (or its to_dict() payload) for a move the "
        "names do not cover."
    )
