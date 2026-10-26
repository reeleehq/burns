"""Content-aware Ken Burns: choose crop windows that keep the subject (and any
detected faces) framed, and avoid drifting over empty regions like sky.

Two layers, usable together or apart:

* :func:`salient_box` — a **zero-dependency** (numpy + Pillow, already required)
  estimate of the busy / high-detail region of an image, so motion follows the
  subject instead of blank sky or plain ground. Good default when you have no
  detector.
* :func:`content_aware_path` — the **pure geometry**: given the image size and a
  *keep-region* (the union of face boxes if any, else a subject box), build a
  :class:`~burns.path.BurnsPath` whose start/end windows keep that region fully
  framed while zooming toward or away from it. This is the reusable, testable
  core; it touches no pixels.

Detection is **injected**, not built in: faces come from a caller-supplied
``faces_detector`` (an LLM, an ONNX/cv2 model, or manual boxes), so this module
stays dependency-light and deterministic. Boxes everywhere are normalized
``(x, y, w, h)`` in ``[0, 1]`` with a top-left origin — the same convention as
:class:`~burns.rect.Rect`.

The geometry :func:`content_aware_path` is built from is exported rather than
inlined — :func:`axis_maxima`, :func:`keep_window`, :func:`fit_zoom` and
:func:`pad_box`. :mod:`burns.moves` builds its static and drift moves out of the
same four, so "a window of this zoom, at this output aspect, centred here" has
one implementation rather than one per move.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, Sequence, Union

from burns.easing import DFLT_EASING, EasingLike
from burns.path import BurnsPath, window_aspect
from burns.rect import Rect

Box = tuple[float, float, float, float]
#: A detector: given an image, return normalized face boxes (empty if none).
FacesDetector = Callable[[Any], Sequence[Box]]


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _union(boxes: Iterable[Box]) -> Box:
    boxes = list(boxes)
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


#: Where the keep-region defaults to when nothing is known about the picture:
#: a generous centered box. Not the full frame — that would give the framing
#: nothing to hold on to and every zoom would be capped to a standstill.
DFLT_KEEP_BOX: Box = (0.15, 0.15, 0.7, 0.7)

#: Fractional breathing room around the keep-region. Framing a subject with its
#: own bounding box hard against the window edge reads as a crop, not a frame.
DFLT_KEEP_PAD: float = 0.18


def as_pil(image: Any):
    """Open / convert ``image`` (path, ``PIL.Image``, or ndarray) to a PIL image.

    The single entry point for "the caller gave me *some* kind of image". Used
    by every function here that needs pixels or a size, so a new accepted input
    type is added in one place — and so a path is opened once per call rather
    than once per function that wants it.
    """
    from PIL import Image as PIL_Image
    import numpy as np

    if isinstance(image, np.ndarray):
        return PIL_Image.fromarray(image)
    if isinstance(image, PIL_Image.Image):
        return image
    return PIL_Image.open(image)


def pad_box(box: Box, pad: float = DFLT_KEEP_PAD) -> Box:
    """Grow ``box`` by ``pad`` of its own size on every side, clipped to the image.

    Examples:
        >>> [round(v, 4) for v in pad_box((0.4, 0.4, 0.2, 0.2), 0.25)]
        [0.35, 0.35, 0.3, 0.3]
        >>> pad_box((0.0, 0.0, 1.0, 1.0), 0.5)  # already the whole image
        (0.0, 0.0, 1.0, 1.0)
    """
    x, y, w, h = box
    x = _clamp(x - w * pad)
    y = _clamp(y - h * pad)
    return (x, y, min(1 - x, w * (1 + 2 * pad)), min(1 - y, h * (1 + 2 * pad)))


def axis_maxima(
    img_w: int, img_h: int, output_aspect: Union[float, None] = None
) -> tuple[float, float]:
    """The largest ``(w, h)`` window, in image units, matching ``output_aspect``.

    At zoom ``1.0`` this is the window the render fills; one of the two is
    always ``1.0`` (the axis that limits) and the other is what the output
    aspect leaves of the opposite one. ``output_aspect=None`` means "match the
    image", so both are ``1.0``.

    Examples:
        >>> axis_maxima(1600, 900)                    # aspect follows the image
        (1.0, 1.0)
        >>> [round(v, 4) for v in axis_maxima(1600, 1200, 16 / 9)]  # 4:3 -> 16:9
        [1.0, 0.75]
        >>> [round(v, 4) for v in axis_maxima(1080, 1920, 16 / 9)]  # portrait
        [1.0, 0.3164]
    """
    if not output_aspect:
        return (1.0, 1.0)
    a = window_aspect(float(output_aspect), (img_w, img_h))
    return (a, 1.0) if a < 1.0 else (1.0, 1.0 / a)


def keep_window(
    img_w: int,
    img_h: int,
    *,
    center: tuple[float, float],
    zoom: float,
    output_aspect: Union[float, None] = None,
) -> Rect:
    """The window of ``zoom``, at ``output_aspect``, centred on ``center``.

    Clamped inside the image by sliding, never by resizing (see
    :meth:`~burns.rect.Rect.clamped`) — shrinking would change the window's
    aspect and make the rendered frame breathe.

    Examples:
        >>> keep_window(1000, 1000, center=(0.5, 0.5), zoom=2.0)
        Rect(x=0.25, y=0.25, w=0.5, h=0.5)
        >>> keep_window(1000, 1000, center=(0.95, 0.5), zoom=2.0)  # rides the wall
        Rect(x=0.5, y=0.25, w=0.5, h=0.5)
    """
    wmax, hmax = axis_maxima(img_w, img_h, output_aspect)
    w = min(wmax / zoom, 1.0)
    h = min(hmax / zoom, 1.0)
    cx, cy = center
    return Rect(cx - w / 2, cy - h / 2, w, h).clamped()


def fit_zoom(
    img_w: int,
    img_h: int,
    *,
    keep: Box,
    output_aspect: Union[float, None] = None,
) -> float:
    """The largest zoom at which ``keep`` still fits inside the window.

    ``keep`` is taken as given — pad it with :func:`pad_box` first if you want
    the subject framed rather than touching the edges.

    Examples:
        >>> round(fit_zoom(1000, 1000, keep=(0.25, 0.25, 0.5, 0.5)), 4)
        2.0
        >>> round(fit_zoom(1000, 1000, keep=(0.0, 0.0, 1.0, 1.0)), 4)  # fills it
        1.0
    """
    wmax, hmax = axis_maxima(img_w, img_h, output_aspect)
    _, _, kw, kh = keep
    return min(wmax / max(kw, 1e-3), hmax / max(kh, 1e-3))


def _gray_array(image: Any, downscale: int):
    """Return a small 2-D float grayscale array from a path / PIL image / ndarray."""
    import numpy as np
    from PIL import Image as PIL_Image

    img = as_pil(image).convert("L")
    w, h = img.size
    scale = downscale / max(w, h)
    if scale < 1.0:
        img = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), PIL_Image.BILINEAR
        )
    return np.asarray(img, dtype="float32")


def salient_box(
    image: Any,
    *,
    downscale: int = 320,
    threshold_pct: float = 72.0,
    trim_pct: float = 4.0,
    pad: float = 0.05,
    min_size: float = 0.35,
) -> Box:
    """Estimate the salient (high-detail) region of ``image`` as a normalized box.

    Uses gradient magnitude: flat regions (sky, walls, water) have low gradient
    and fall away, so the bounding box of the high-gradient pixels tracks the
    subject. Robust to outliers via percentile trimming. Falls back to a
    centered box when the image is too uniform to decide.

    Examples:
        >>> import numpy as np
        >>> a = np.zeros((100, 100), dtype='uint8'); a[60:90, 40:70] = 255
        >>> x, y, w, h = salient_box(a, min_size=0.0, pad=0.0)
        >>> 0.3 < x < 0.45 and 0.55 < y < 0.65   # box around the bright square
        True
    """
    import numpy as np

    a = _gray_array(image, downscale)
    if a.ndim != 2 or min(a.shape) < 4:
        return DFLT_KEEP_BOX
    e = np.zeros_like(a)
    e[:, :-1] += np.abs(np.diff(a, axis=1))
    e[:-1, :] += np.abs(np.diff(a, axis=0))
    thr = np.percentile(e, threshold_pct)
    ys, xs = np.where(e >= max(thr, 1e-6))
    H, W = a.shape
    if xs.size < 8:
        return DFLT_KEEP_BOX
    x0, x1 = np.percentile(xs, [trim_pct, 100 - trim_pct])
    y0, y1 = np.percentile(ys, [trim_pct, 100 - trim_pct])
    bx, by = x0 / W, y0 / H
    bw, bh = max((x1 - x0) / W, 1e-3), max((y1 - y0) / H, 1e-3)
    # pad
    bx = _clamp(bx - bw * pad)
    by = _clamp(by - bh * pad)
    bw = min(1 - bx, bw * (1 + 2 * pad))
    bh = min(1 - by, bh * (1 + 2 * pad))
    # enforce a minimum footprint (keep it centered on the salient centroid)
    cx, cy = bx + bw / 2, by + bh / 2
    bw = max(bw, min_size)
    bh = max(bh, min_size)
    bx = _clamp(cx - bw / 2, 0, 1 - bw)
    by = _clamp(cy - bh / 2, 0, 1 - bh)
    return (float(bx), float(by), float(bw), float(bh))


def content_aware_path(
    img_w: int,
    img_h: int,
    *,
    subject: Optional[Box] = None,
    faces: Sequence[Box] = (),
    index: int = 0,
    output_aspect: Union[float, None] = None,
    zoom: float = 1.3,
    min_zoom: float = 1.05,
    keep_pad: float = DFLT_KEEP_PAD,
    mode: str = "auto",
    easing: EasingLike = DFLT_EASING,
) -> BurnsPath:
    """A :class:`BurnsPath` that keeps the subject/faces framed while zooming
    toward or away from them — the content-aware counterpart of
    :func:`~burns.path.ken_burns_path`.

    The *keep-region* is the union of ``faces`` if any, else ``subject`` (else a
    centered default). Both start and end crop windows are built to contain that
    region fully, centered on it; the end zoom is capped so the region never
    leaves the frame. Windows carry the output pixel-aspect so the render's
    cover-crop is a no-op and what you frame is what shows.

    Args:
        img_w, img_h: source image pixel size (the subject box lives in this space).
        subject: normalized ``(x,y,w,h)`` of the main subject (e.g. from
            :func:`salient_box`). Optional.
        faces: normalized face boxes; when present they are the keep-region and
            take priority over ``subject``.
        index: sequence position; in ``mode="auto"`` odd indices push in, even
            pull out, giving a sequence rhythm (mirrors ``ken_burns_path``).
        output_aspect: the render's ``width/height``; defaults to the image's.
        zoom: target end magnification (capped to keep the region framed).
        min_zoom: floor magnification for the non-zoomed end.
        keep_pad: fractional padding around the keep-region.
        mode: ``"auto"`` (alternate by index) · ``"in"`` (always toward) ·
            ``"out"`` (always away).

    Examples:
        >>> p = content_aware_path(1600, 900, subject=(0.6, 0.55, 0.2, 0.25), index=1)
        >>> r0, r1 = p.evaluate(0.0), p.evaluate(1.0)
        >>> r1.zoom >= r0.zoom            # index 1 -> push in
        True
        >>> content_aware_path(100, 100, subject=(0,0,1,1)) == content_aware_path(100, 100, subject=(0,0,1,1))
        True
    """
    faces = list(faces or [])
    keep = pad_box(
        _union(faces) if faces else (subject if subject else DFLT_KEEP_BOX), keep_pad
    )
    kx, ky, kw, kh = keep
    cx, cy = kx + kw / 2, ky + kh / 2

    def window(z: float) -> Rect:
        return keep_window(
            img_w, img_h, center=(cx, cy), zoom=z, output_aspect=output_aspect
        )

    # largest zoom at which the whole keep-region still fits the window
    z_fit = fit_zoom(img_w, img_h, keep=keep, output_aspect=output_aspect)
    z_in = max(min_zoom + 0.02, min(zoom, z_fit * 0.98))
    z_in = max(z_in, 1.0)
    z_out = max(1.0, min(z_in - 0.12, z_fit * 0.98))
    if z_out >= z_in:  # keep-region too large to zoom — gentle move
        z_out = max(1.0, z_in - 0.06)

    if mode == "in":
        push = True
    elif mode == "out":
        push = False
    else:
        push = index % 2 == 1
    start, end = (
        (window(z_out), window(z_in)) if push else (window(z_in), window(z_out))
    )
    return BurnsPath.from_start_end(
        start, end, easing=easing, output_aspect=output_aspect
    )


def content_aware_path_for(
    image: Any,
    *,
    subject: Optional[Box] = None,
    faces: Sequence[Box] = (),
    faces_detector: Optional[FacesDetector] = None,
    index: int = 0,
    output_aspect: Union[float, None] = None,
    **kwargs: Any,
) -> BurnsPath:
    """Convenience: derive the subject (via :func:`salient_box`) and faces (from
    ``faces`` or ``faces_detector(image)``) straight from ``image``, then call
    :func:`content_aware_path`. ``image`` may be a path, PIL image, or ndarray.

    Keeps burns dependency-light: pass an LLM/cv2/manual ``faces_detector`` when
    you want face-aware framing; omit it for saliency-only (sky-avoiding) motion.

    ``subject`` is an explicit keep-region that **replaces** the saliency
    estimate — for a caller who already knows what the picture is about (a
    hand-drawn crop, an upstream detector, a stored authoring decision). It is a
    named parameter rather than one more key in ``**kwargs`` because those are
    forwarded to :func:`content_aware_path`, which already takes ``subject`` —
    so passing it that way raised ``TypeError: got multiple values`` two frames
    down. When given, :func:`salient_box` is **not called**: the override is
    total, and computing an estimate only to discard it is how a partial
    override quietly lets saliency back in.

    Examples:
        >>> import numpy as np
        >>> a = np.zeros((600, 800, 3), dtype='uint8'); a[80:200, 60:200] = 220
        >>> p = content_aware_path_for(a, subject=(0.7, 0.7, 0.2, 0.2), index=1)
        >>> r = p.evaluate(1.0)                     # framed on the override,
        >>> r.x + r.w / 2 > 0.5 and r.y + r.h / 2 > 0.5   # not the bright corner
        True
    """
    img = as_pil(image)
    iw, ih = img.size
    detected = list(faces) or (list(faces_detector(img)) if faces_detector else [])
    return content_aware_path(
        iw,
        ih,
        subject=subject if subject is not None else salient_box(img),
        faces=detected,
        index=index,
        output_aspect=output_aspect,
        **kwargs,
    )
