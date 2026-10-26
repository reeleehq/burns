# burns.content

Content-aware Ken Burns: choose crop windows that keep the subject (and any
detected faces) framed, and avoid drifting over empty regions like sky.

Two layers, usable together or apart:

* [`salient_box()`](#burns.content.salient_box) — a **zero-dependency** (numpy + Pillow, already required)
  estimate of the busy / high-detail region of an image, so motion follows the
  subject instead of blank sky or plain ground. Good default when you have no
  detector.
* [`content_aware_path()`](#burns.content.content_aware_path) — the **pure geometry**: given the image size and a
  *keep-region* (the union of face boxes if any, else a subject box), build a
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath) whose start/end windows keep that region fully
  > framed while zooming toward or away from it. This is the reusable, testable
  > core; it touches no pixels.

Detection is **injected**, not built in: faces come from a caller-supplied
`faces_detector` (an LLM, an ONNX/cv2 model, or manual boxes), so this module
stays dependency-light and deterministic. Boxes everywhere are normalized
`(x, y, w, h)` in `[0, 1]` with a top-left origin — the same convention as
[`Rect`](burns.rect.html.md#burns.rect.Rect).

The geometry [`content_aware_path()`](#burns.content.content_aware_path) is built from is exported rather than
inlined — [`axis_maxima()`](#burns.content.axis_maxima), [`keep_window()`](#burns.content.keep_window), [`fit_zoom()`](#burns.content.fit_zoom) and
[`pad_box()`](#burns.content.pad_box). [`burns.moves`](burns.moves.html.md#module-burns.moves) builds its static and drift moves out of the
same four, so “a window of this zoom, at this output aspect, centred here” has
one implementation rather than one per move.

### Module Attributes

| [`FacesDetector`](#burns.content.FacesDetector)   | given an image, return normalized face boxes (empty if none).                                       |
|------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| [`DFLT_KEEP_BOX`](#burns.content.DFLT_KEEP_BOX)   | Where the keep-region defaults to when nothing is known about the picture: a generous centered box. |
| [`DFLT_KEEP_PAD`](#burns.content.DFLT_KEEP_PAD)   | Fractional breathing room around the keep-region.                                                   |

### Functions

| [`as_pil`](#burns.content.as_pil)(image)                                      | Open / convert `image` (path, `PIL.Image`, or ndarray) to a PIL image.                                                                                                                                                                                           |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`axis_maxima`](#burns.content.axis_maxima)(img_w, img_h[, output_aspect])         | The largest `(w, h)` window, in image units, matching `output_aspect`.                                                                                                                                                                                           |
| [`content_aware_path`](#burns.content.content_aware_path)(img_w, img_h, \*[, ...])        | A `BurnsPath` that keeps the subject/faces framed while zooming toward or away from them — the content-aware counterpart of [`ken_burns_path()`](burns.path.html.md#burns.path.ken_burns_path).                                         |
| [`content_aware_path_for`](#burns.content.content_aware_path_for)(image, \*[, subject, ...])  | Convenience: derive the subject (via [`salient_box()`](#burns.content.salient_box)) and faces (from `faces` or `faces_detector(image)`) straight from `image`, then call [`content_aware_path()`](#burns.content.content_aware_path). |
| [`fit_zoom`](#burns.content.fit_zoom)(img_w, img_h, \*, keep[, output_aspect])  | The largest zoom at which `keep` still fits inside the window.                                                                                                                                                                                                   |
| [`keep_window`](#burns.content.keep_window)(img_w, img_h, \*, center, zoom[, ...]) | The window of `zoom`, at `output_aspect`, centred on `center`.                                                                                                                                                                                                   |
| [`pad_box`](#burns.content.pad_box)(box[, pad])                                | Grow `box` by `pad` of its own size on every side, clipped to the image.                                                                                                                                                                                         |
| [`salient_box`](#burns.content.salient_box)(image, \*[, downscale, ...])           | Estimate the salient (high-detail) region of `image` as a normalized box.                                                                                                                                                                                        |

### burns.content.DFLT_KEEP_BOX *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]* *= (0.15, 0.15, 0.7, 0.7)*

Where the keep-region defaults to when nothing is known about the picture:
a generous centered box. Not the full frame — that would give the framing
nothing to hold on to and every zoom would be capped to a standstill.

### burns.content.DFLT_KEEP_PAD *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.18*

Fractional breathing room around the keep-region. Framing a subject with its
own bounding box hard against the window edge reads as a crop, not a frame.

### burns.content.FacesDetector

given an image, return normalized face boxes (empty if none).

* **Type:**
  A detector

alias of `Callable`[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]]

### burns.content.as_pil(image)

Open / convert `image` (path, `PIL.Image`, or ndarray) to a PIL image.

The single entry point for “the caller gave me *some* kind of image”. Used
by every function here that needs pixels or a size, so a new accepted input
type is added in one place — and so a path is opened once per call rather
than once per function that wants it.

### burns.content.axis_maxima(img_w, img_h, output_aspect=None)

The largest `(w, h)` window, in image units, matching `output_aspect`.

At zoom `1.0` this is the window the render fills; one of the two is
always `1.0` (the axis that limits) and the other is what the output
aspect leaves of the opposite one. `output_aspect=None` means “match the
image”, so both are `1.0`.

### Examples

```pycon
>>> axis_maxima(1600, 900)                    # aspect follows the image
(1.0, 1.0)
>>> [round(v, 4) for v in axis_maxima(1600, 1200, 16 / 9)]  # 4:3 -> 16:9
[1.0, 0.75]
>>> [round(v, 4) for v in axis_maxima(1080, 1920, 16 / 9)]  # portrait
[1.0, 0.3164]
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### burns.content.content_aware_path(img_w, img_h, , subject=None, faces=(), index=0, output_aspect=None, zoom=1.3, min_zoom=1.05, keep_pad=0.18, mode='auto', easing='ease-in-out')

A `BurnsPath` that keeps the subject/faces framed while zooming
toward or away from them — the content-aware counterpart of
[`ken_burns_path()`](burns.path.html.md#burns.path.ken_burns_path).

The *keep-region* is the union of `faces` if any, else `subject` (else a
centered default). Both start and end crop windows are built to contain that
region fully, centered on it; the end zoom is capped so the region never
leaves the frame. Windows carry the output pixel-aspect so the render’s
cover-crop is a no-op and what you frame is what shows.

* **Parameters:**
  * **img_w** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – source image pixel size (the subject box lives in this space).
  * **img_h** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – source image pixel size (the subject box lives in this space).
  * **subject** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – normalized `(x,y,w,h)` of the main subject (e.g. from
    [`salient_box()`](#burns.content.salient_box)). Optional.
  * **faces** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – normalized face boxes; when present they are the keep-region and
    take priority over `subject`.
  * **index** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – sequence position; in `mode="auto"` odd indices push in, even
    pull out, giving a sequence rhythm (mirrors `ken_burns_path`).
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the render’s `width/height`; defaults to the image’s.
  * **zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – target end magnification (capped to keep the region framed).
  * **min_zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – floor magnification for the non-zoomed end.
  * **keep_pad** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – fractional padding around the keep-region.
  * **mode** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `"auto"` (alternate by index) · `"in"` (always toward) ·
    `"out"` (always away).
* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> p = content_aware_path(1600, 900, subject=(0.6, 0.55, 0.2, 0.25), index=1)
>>> r0, r1 = p.evaluate(0.0), p.evaluate(1.0)
>>> r1.zoom >= r0.zoom            # index 1 -> push in
True
>>> content_aware_path(100, 100, subject=(0,0,1,1)) == content_aware_path(100, 100, subject=(0,0,1,1))
True
```

### burns.content.content_aware_path_for(image, , subject=None, faces=(), faces_detector=None, index=0, output_aspect=None, \*\*kwargs)

Convenience: derive the subject (via [`salient_box()`](#burns.content.salient_box)) and faces (from
`faces` or `faces_detector(image)`) straight from `image`, then call
[`content_aware_path()`](#burns.content.content_aware_path). `image` may be a path, PIL image, or ndarray.

Keeps burns dependency-light: pass an LLM/cv2/manual `faces_detector` when
you want face-aware framing; omit it for saliency-only (sky-avoiding) motion.

`subject` is an explicit keep-region that **replaces** the saliency
estimate — for a caller who already knows what the picture is about (a
hand-drawn crop, an upstream detector, a stored authoring decision). It is a
named parameter rather than one more key in `**kwargs` because those are
forwarded to [`content_aware_path()`](#burns.content.content_aware_path), which already takes `subject` —
so passing it that way raised `TypeError: got multiple values` two frames
down. When given, [`salient_box()`](#burns.content.salient_box) is **not called**: the override is
total, and computing an estimate only to discard it is how a partial
override quietly lets saliency back in.

### Examples

```pycon
>>> import numpy as np
>>> a = np.zeros((600, 800, 3), dtype='uint8'); a[80:200, 60:200] = 220
>>> p = content_aware_path_for(a, subject=(0.7, 0.7, 0.2, 0.2), index=1)
>>> r = p.evaluate(1.0)                     # framed on the override,
>>> r.x + r.w / 2 > 0.5 and r.y + r.h / 2 > 0.5   # not the bright corner
True
```

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### burns.content.fit_zoom(img_w, img_h, , keep, output_aspect=None)

The largest zoom at which `keep` still fits inside the window.

`keep` is taken as given — pad it with [`pad_box()`](#burns.content.pad_box) first if you want
the subject framed rather than touching the edges.

### Examples

```pycon
>>> round(fit_zoom(1000, 1000, keep=(0.25, 0.25, 0.5, 0.5)), 4)
2.0
>>> round(fit_zoom(1000, 1000, keep=(0.0, 0.0, 1.0, 1.0)), 4)  # fills it
1.0
```

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### burns.content.keep_window(img_w, img_h, , center, zoom, output_aspect=None)

The window of `zoom`, at `output_aspect`, centred on `center`.

Clamped inside the image by sliding, never by resizing (see
[`clamped()`](burns.rect.html.md#burns.rect.Rect.clamped)) — shrinking would change the window’s
aspect and make the rendered frame breathe.

### Examples

```pycon
>>> keep_window(1000, 1000, center=(0.5, 0.5), zoom=2.0)
Rect(x=0.25, y=0.25, w=0.5, h=0.5)
>>> keep_window(1000, 1000, center=(0.95, 0.5), zoom=2.0)  # rides the wall
Rect(x=0.5, y=0.25, w=0.5, h=0.5)
```

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

### burns.content.pad_box(box, pad=0.18)

Grow `box` by `pad` of its own size on every side, clipped to the image.

### Examples

```pycon
>>> [round(v, 4) for v in pad_box((0.4, 0.4, 0.2, 0.2), 0.25)]
[0.35, 0.35, 0.3, 0.3]
>>> pad_box((0.0, 0.0, 1.0, 1.0), 0.5)  # already the whole image
(0.0, 0.0, 1.0, 1.0)
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### burns.content.salient_box(image, , downscale=320, threshold_pct=72.0, trim_pct=4.0, pad=0.05, min_size=0.35)

Estimate the salient (high-detail) region of `image` as a normalized box.

Uses gradient magnitude: flat regions (sky, walls, water) have low gradient
and fall away, so the bounding box of the high-gradient pixels tracks the
subject. Robust to outliers via percentile trimming. Falls back to a
centered box when the image is too uniform to decide.

### Examples

```pycon
>>> import numpy as np
>>> a = np.zeros((100, 100), dtype='uint8'); a[60:90, 40:70] = 255
>>> x, y, w, h = salient_box(a, min_size=0.0, pad=0.0)
>>> 0.3 < x < 0.45 and 0.55 < y < 0.65   # box around the bright square
True
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]
