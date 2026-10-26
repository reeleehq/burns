# burns

burns — Ken Burns pan/zoom video effects.

Turn a still image (or a sequence of stills) into a cinematic pan/zoom film,
driven by one **render-agnostic motion spec** so the same path feeds the Python
renderer here and the in-browser TypeScript port (`kenburnz`, in `ts/`).

The core abstraction is a pure, time-parameterized spec:

- [`Rect`](#burns.Rect) — a normalized `(x, y, w, h)` viewport over the image
  (top-left origin, window-fraction zoom).
- [`BurnsPath`](#burns.BurnsPath) — keyframes + easing, with `evaluate(t) -> Rect` (pure,
  deterministic, frame-count-free) and JSON `to_dict` / `from_dict`.
- [`ken_burns_path()`](#burns.ken_burns_path) — build a cohesive, deterministic path per sequence
  index from a little intent (style / zoom / pan / easing).
- [`content_aware_path_for()`](#burns.content_aware_path_for) — the content-aware counterpart: keep the
  subject (via [`salient_box()`](#burns.salient_box)) and any injected face boxes framed.
- `MOVES` + [`resolve_move()`](#burns.resolve_move) — the named-move vocabulary, for callers
  that want to *store* a camera move as an authored intent and resolve it
  against whatever still is in the slot at render time. A caller that caches
  the render puts `RESOLVER_IMPL_VERSION` in its key, since the pixels an
  unchanged intent becomes are decided here.

Two renderers consume a path plus a render-time `duration`:

- [`ken_burns_video()`](#burns.ken_burns_video) — one image -> one mp4 (pluggable backend).
- [`ken_burns_film()`](#burns.ken_burns_film) — a sequence of `(image, path, duration)` panels ->
  one continuous mp4 (single encode pass, no seams), with optional audio.

Quickstart:

```pycon
>>> from burns import ken_burns_video, ken_burns_path
>>> ken_burns_video("photo.jpg")  # 2s push-in
>>> ken_burns_video(  # path per sequence index
...     "photo.jpg", ken_burns_path(1, style="push"), duration=5.0
... )
```

### Functions

| [`ken_burns_path`](#burns.ken_burns_path)(index, \*[, style, zoom, pan, ...])   | A deterministic [`BurnsPath`](#burns.BurnsPath) for the `index`-th image of a sequence.                                                                                                                                                      |
|-------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`content_aware_path`](#burns.content_aware_path)(img_w, img_h, \*[, ...])          | A [`BurnsPath`](#burns.BurnsPath) that keeps the subject/faces framed while zooming toward or away from them — the content-aware counterpart of [`ken_burns_path()`](burns.path.html.md#burns.path.ken_burns_path). |
| [`content_aware_path_for`](#burns.content_aware_path_for)(image, \*[, subject, ...])    | Convenience: derive the subject (via [`salient_box()`](#burns.salient_box)) and faces (from `faces` or `faces_detector(image)`) straight from `image`, then call [`content_aware_path()`](#burns.content_aware_path).        |
| [`salient_box`](#burns.salient_box)(image, \*[, downscale, ...])             | Estimate the salient (high-detail) region of `image` as a normalized box.                                                                                                                                                                                               |
| [`choose_move`](#burns.choose_move)(seed)                                    | Which concrete move `"auto"` resolves to for `seed`.                                                                                                                                                                                                                    |
| [`move_kind`](#burns.move_kind)(move)                                      | How `move` is grouped: `"zoom"`, `"drift"`, `"static"`, `"select"`.                                                                                                                                                                                                     |
| [`resolve_move`](#burns.resolve_move)(move, \*, image, aspect[, zoom, ...])   | Resolve an authored camera intent against `image` into a path.                                                                                                                                                                                                          |
| [`ken_burns_video`](#burns.ken_burns_video)(image[, path, duration, ...])        | Render one image into a pan/zoom video from a [`BurnsPath`](#burns.BurnsPath).                                                                                                                                                               |
| [`ken_burns_film`](#burns.ken_burns_film)(panels, \*, saveas[, fps, ...])       | Render an N-panel Ken Burns film in a single pass.                                                                                                                                                                                                                      |
| [`parse_easing`](#burns.parse_easing)([spec])                                 | Resolve an easing spec to a callable `f: [0, 1] -> [0, 1]`.                                                                                                                                                                                                             |
| [`cubic_bezier`](#burns.cubic_bezier)(x1, y1, x2, y2)                         | A CSS-style cubic-bezier easing `f: [0, 1] -> [0, 1]`.                                                                                                                                                                                                                  |
| [`register_backend`](#burns.register_backend)(name, backend)                      | Register a render backend under `name` (open-closed extension point).                                                                                                                                                                                                   |
| [`get_backend`](#burns.get_backend)([name])                                  | Look up a registered backend by name.                                                                                                                                                                                                                                   |

### Classes

| [`Rect`](#burns.Rect)(x, y, w, h)                            | A normalized `(x, y, w, h)` viewport over a source image.                                                    |
|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`BurnsPath`](#burns.BurnsPath)(keyframes[, easing, interp, ...]) | A time-parameterized pan/zoom motion over a still image.                                                     |
| [`RenderBackend`](#burns.RenderBackend)(\*args, \*\*kwargs)           | Encode one image + [`BurnsPath`](#burns.BurnsPath) into a video file at `output`. |

### Exceptions

| [`MoveError`](#burns.MoveError)   | A move that cannot be resolved into a path.   |
|--------------------------------------------------------------|-----------------------------------------------|

### *class* burns.BurnsPath(keyframes, easing='ease-in-out', interp='linear', output_aspect=None, version=1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A time-parameterized pan/zoom motion over a still image.

Construct it directly from keyframes, or via [`from_start_end()`](#burns.BurnsPath.from_start_end) /
[`push_in()`](#burns.BurnsPath.push_in) for the common cases, or via [`ken_burns_path()`](#burns.ken_burns_path) for
deterministic per-index motion across a sequence.

* **Parameters:**
  * **keyframes** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`Rect`](burns.rect.html.md#burns.rect.Rect)], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – a sequence of `(t, Rect)` waypoints, `t in [0, 1]`,
    strictly increasing in `t`. Must have at least one entry; the
    first `t` should be `0.0` and the last `1.0` for the whole
    clock to be covered (out-of-range `t` clamps to the ends).
  * **easing** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – a CSS timing-function spec (name / `cubic-bezier(...)` /
    4-tuple) or a callable `[0,1] -> [0,1]`. Default `"ease-in-out"`.
  * **interp** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – geometry interpolation between keyframes. Only `"linear"` is
    implemented; the field exists so the spec can carry richer schemes
    (`"catmull-rom"`, `"bezier"`) without a format change.
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the aspect ratio (`width / height`) the render should
    fill. `None` means “match the source image”.
  * **version** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – spec schema version (for forward-compatible serialization).

### Examples

```pycon
>>> p = BurnsPath.from_start_end(
...     Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.5, 1.3)
... )
>>> p.evaluate(0.0)
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> round(p.evaluate(1.0).zoom, 4)
1.3
>>> p.duration_keyframes  # number of waypoints
2
```

#### *property* duration_keyframes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Number of keyframe waypoints (`2` for the canonical Start/End).

#### evaluate(t)

The viewport [`Rect`](#burns.Rect) at normalized clock time `t in [0, 1]`.

Applies easing to the clock, then linearly interpolates the geometry at
the eased progress. Pure and deterministic: no image, no I/O, no frame
count. `t` outside `[0, 1]` clamps to the nearest end.

### Examples

```pycon
>>> p = BurnsPath.from_start_end(
...     Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing="linear"
... )
>>> p.evaluate(0.5)
Rect(x=0.0, y=0.0, w=0.75, h=0.75)
```

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

#### *classmethod* from_dict(d)

Rebuild a [`BurnsPath`](#burns.BurnsPath) from [`to_dict()`](#burns.BurnsPath.to_dict) output.

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> BurnsPath.from_dict(p.to_dict()) == p
True
```

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

#### *classmethod* from_start_end(start, end, , easing='ease-in-out', output_aspect=None)

The canonical two-rectangle Ken Burns case (Start frame -> End frame).

### Examples

```pycon
>>> BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
...
BurnsPath(keyframes=((0.0, Rect(...)), (1.0, Rect(...))), ...)
```

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

#### *classmethod* push_in(zoom=1.3, , to=(0.5, 0.5), easing='ease-in-out', output_aspect=None, image_aspect=None)

The 90%-case constructor: a slow push from the full image toward
`to` at `zoom`.

* **Parameters:**
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the delivery’s `width / height` (see [`BurnsPath`](#burns.BurnsPath)).
  * **image_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the source’s `width / height`. \*\*Pass it whenever
    `output_aspect` is set\*\*; without it the source is treated as
    square, and on any other shape the zoom-1.0 window already
    crops the image (a 16:9 source loses ~44% of its height).
* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> round(BurnsPath.push_in().evaluate(1.0).zoom, 4)
1.3
>>> BurnsPath.push_in(output_aspect=16 / 9, image_aspect=16 / 9).evaluate(0.0)
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
```

#### reversed()

Swap start and end (the NLE “Swap Start and End Areas” button).

Mirrors every keyframe’s time about `0.5` and re-sorts, so the motion
plays back-to-front. Easing/interp/output_aspect are preserved.

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> p.reversed().evaluate(0.0)
Rect(x=0.0, y=0.0, w=0.5, h=0.5)
```

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

#### to_dict()

Serialize to the versioned JSON wire format (the cross-language SSOT).

Easing is stored as the original CSS string / 4-tuple. A callable easing
cannot be serialized and raises — use a CSS spec for paths that travel.

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> d = p.to_dict()
>>> d["version"], d["easing"], len(d["keyframes"])
(1, 'ease-in-out', 2)
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### *exception* burns.MoveError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A move that cannot be resolved into a path.

A plain [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError) subclass, so a consumer that already catches
`ValueError` around its authoring layer keeps working, and so nothing
downstream needs to import [`burns.moves`](burns.moves.html.md#module-burns.moves) to handle it.

### *class* burns.Rect(x, y, w, h)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A normalized `(x, y, w, h)` viewport over a source image.

All four components are fractions of the image in `[0, 1]` with a
top-left origin. `(x, y)` is the top-left corner of the window; `w` and
`h` are its width and height. `Rect(0, 0, 1, 1)` is the whole image.

### Examples

```pycon
>>> full = Rect(0.0, 0.0, 1.0, 1.0)
>>> full.center
(0.5, 0.5)
>>> full.zoom
1.0
>>> Rect.from_center_zoom(0.5, 0.5, 2.0)
Rect(x=0.25, y=0.25, w=0.5, h=0.5)
```

#### *property* aspect *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Aspect ratio of the window *in normalized image units* (`w / h`).

Note this is not the rendered-pixel aspect ratio unless the image is
square — the pixel AR is `(w * img_w) / (h * img_h)`. The render path
reconciles the window with the desired output AR via a cover-crop.

#### *property* center *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]*

The window’s center `(cx, cy)` in `[0, 1]` image units.

#### clamped()

Slide the window inside the image **without resizing it**.

Clamps the top-left corner so the window “rides the wall” at an edge
rather than shrinking — shrinking the box would change its aspect ratio
and make the rendered frame breathe/stretch. Windows larger than the
image in a dimension are centered in that dimension.

### Examples

```pycon
>>> Rect(0.8, 0.0, 0.5, 0.5).clamped()
Rect(x=0.5, y=0.0, w=0.5, h=0.5)
>>> Rect(-0.2, 0.3, 0.4, 0.4).clamped()
Rect(x=0.0, y=0.3, w=0.4, h=0.4)
```

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

#### *classmethod* from_center_zoom(cx, cy, zoom=1.0, , aspect=1.0)

Build a rect from a pan center, a zoom, and a window aspect ratio.

This is the bridge from the older center+magnification mental model to
the `(x, y, w, h)` representation. `zoom` is window-fraction
magnification (`1.0` = full image, `> 1.0` = zoomed in). `aspect`
is the window’s normalized `w / h`; the default `1.0` yields an
isotropic window (`w == h`) whose rendered AR equals the source
image’s — reproducing the legacy behavior exactly. The result is
clamped to stay inside the image.

### Examples

```pycon
>>> Rect.from_center_zoom(0.5, 0.5, 1.0)
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> Rect.from_center_zoom(0.75, 0.5, 2.0)  # off-center zoom-in
Rect(x=0.5, y=0.25, w=0.5, h=0.5)
```

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

#### is_contained()

True when the window lies wholly inside the image.

### Examples

```pycon
>>> Rect(0.1, 0.1, 0.5, 0.5).is_contained()
True
>>> Rect(0.8, 0.0, 0.5, 0.5).is_contained()
False
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### lerp(other, t)

Linearly interpolate toward `other` by `t` in `[0, 1]`.

### Examples

```pycon
>>> Rect(0, 0, 1, 1).lerp(Rect(0.25, 0.25, 0.5, 0.5), 0.5)
Rect(x=0.125, y=0.125, w=0.75, h=0.75)
```

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

#### to_pixels(img_w, img_h)

Map the (clamped) window to an integer pixel box `(x0, y0, x1, y1)`.

Clamps first so the box is always inside the raster, then rounds (not
truncates) for symmetric integer conversion. The returned box is a
half-open crop region suitable for `ndarray[y0:y1, x0:x1]`.

### Examples

```pycon
>>> Rect(0.0, 0.0, 1.0, 1.0).to_pixels(100, 80)
(0, 0, 100, 80)
>>> Rect.from_center_zoom(0.5, 0.5, 2.0).to_pixels(100, 80)
(25, 20, 75, 60)
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

#### *property* zoom *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Magnification implied by the window, `1 / max(w, h)`.

`1.0` = the full image; `> 1.0` = zoomed in. This is the derived
value an FFmpeg `zoompan` backend consumes; the window-fraction
`(w, h)` is the authoritative, user-facing representation.

### *class* burns.RenderBackend(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Encode one image + [`BurnsPath`](#burns.BurnsPath) into a video file at `output`.

Args mirror [`burns.ken_burns_video()`](#burns.ken_burns_video) after argument resolution: the
image is already a decoded `(H, W, C)` uint8 array with its pixel size,
and the output frame size `(out_w, out_h)` is already even-snapped.
Returns the written path.

### burns.choose_move(seed)

Which concrete move `"auto"` resolves to for `seed`.

Public because “auto” is a decision a person may want to *see* (a UI
showing `auto → drift_left`) and to *pin* (liking what auto chose and
storing that name instead, so it survives a change to the weights).

A pure function of `seed` alone — not of the image, and not of any
position in a sequence. That is what makes a panel’s move survive both a
reorder and a swapped still.

### Examples

```pycon
>>> choose_move(7) == choose_move(7)
True
>>> choose_move(7) in MOVES and choose_move(7) != 'auto'
True
>>> len({choose_move(s) for s in range(60)}) > 1   # not one move forever
True
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### burns.content_aware_path(img_w, img_h, , subject=None, faces=(), index=0, output_aspect=None, zoom=1.3, min_zoom=1.05, keep_pad=0.18, mode='auto', easing='ease-in-out')

A [`BurnsPath`](#burns.BurnsPath) that keeps the subject/faces framed while zooming
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
    [`salient_box()`](#burns.salient_box)). Optional.
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

### burns.content_aware_path_for(image, , subject=None, faces=(), faces_detector=None, index=0, output_aspect=None, \*\*kwargs)

Convenience: derive the subject (via [`salient_box()`](#burns.salient_box)) and faces (from
`faces` or `faces_detector(image)`) straight from `image`, then call
[`content_aware_path()`](#burns.content_aware_path). `image` may be a path, PIL image, or ndarray.

Keeps burns dependency-light: pass an LLM/cv2/manual `faces_detector` when
you want face-aware framing; omit it for saliency-only (sky-avoiding) motion.

`subject` is an explicit keep-region that **replaces** the saliency
estimate — for a caller who already knows what the picture is about (a
hand-drawn crop, an upstream detector, a stored authoring decision). It is a
named parameter rather than one more key in `**kwargs` because those are
forwarded to [`content_aware_path()`](#burns.content_aware_path), which already takes `subject` —
so passing it that way raised `TypeError: got multiple values` two frames
down. When given, [`salient_box()`](#burns.salient_box) is **not called**: the override is
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

### burns.cubic_bezier(x1, y1, x2, y2)

A CSS-style cubic-bezier easing `f: [0, 1] -> [0, 1]`.

The curve runs from `(0, 0)` to `(1, 1)` with control points
`(x1, y1)` and `(x2, y2)`. Evaluation inverts `x(t)` for the curve
parameter (bisection — robust for any monotone-x curve) then returns
`y(t)`.

### Examples

```pycon
>>> linear = cubic_bezier(0.0, 0.0, 1.0, 1.0)
>>> round(linear(0.5), 6)
0.5
>>> round(cubic_bezier(0.42, 0.0, 0.58, 1.0)(0.5), 6)  # ease-in-out
0.5
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### burns.get_backend(name='pillow')

Look up a registered backend by name.

### Examples

```pycon
>>> get_backend() is get_backend("pillow")
True
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### burns.ken_burns_film(panels, , saveas, fps=30, audio_path=None, codec='libx264', audio_codec='aac', \*\*write_kwargs)

Render an N-panel Ken Burns film in a single pass.

Each panel is an `(image, path, duration_s)` triple
(`burns.PanelInput`): `image` is a path / `PIL.Image` /
`np.ndarray`, `path` a [`BurnsPath`](#burns.BurnsPath), `duration_s` how long the
panel occupies the film. Panels play back-to-back; the camera cuts at panel
boundaries but motion never pauses on a static frame within a panel.

A single `VideoClip` (rather than per-panel render + concatenate) avoids
the concat re-encode seam and per-panel tail freeze, and keeps frame
generation lazy via one global `make_frame(t)` closure.

* **Parameters:**
  * **panels** – iterable of `(image, path, duration_s)` triples.
  * **saveas** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – output mp4 path (required — a film has no single source image).
  * **fps** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – frame rate.
  * **audio_path** – optional pre-built track (already matching the film
    duration); muxed in when supplied. Per-panel audio assembly is the
    caller’s job — the renderer stays pure visual.
  * **codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **audio_codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **\*\*write_kwargs** – forwarded to `write_videofile`.
* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
* **Returns:**
  The written mp4 [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path).

### burns.ken_burns_path(index, , style='push', zoom=1.1, pan=0.03, easing='ease-in-out', output_aspect=None, image_aspect=None)

A deterministic [`BurnsPath`](#burns.BurnsPath) for the `index`-th image of a sequence.

Maps intent to geometry so a sequence of images gets cohesive, non-repetitive
motion without hand-authoring rectangles. Per-index deterministic: identical
args always return an identical path. Duration is *not* part of the path — it
is a render-time parameter (pass it to [`burns.ken_burns_video()`](#burns.ken_burns_video) /
[`burns.ken_burns_film()`](#burns.ken_burns_film)).

Two styles:

- `style="push"` (default) — the “cinematic push”: one slow zoom toward an
  off-center focal point. **Odd indices push in, even indices pull out**, so a
  sequence has visual rhythm without changing direction *within* a shot. The
  focal direction rotates through compass octants per index.
- `style="drift"` — pure horizontal pan at a constant zoom, alternating
  direction per index (odd drifts right, even left). `zoom` is ignored;
  drift derives its own zoom from `pan` so the slide is visible.

* **Parameters:**
  * **index** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – the image’s 1-based position in the sequence.
  * **style** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `"push"` (default) or `"drift"`.
  * **zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – the zoomed-end magnification (> 1.0) for `"push"`.
  * **pan** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – focal-point offset (`"push"`) or total horizontal travel
    (`"drift"`), in `[0, 1]` image units.
  * **easing** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – CSS timing function or callable. Default `"ease-in-out"` — the
    cinematic slow-in/slow-out. Pass `"linear"` for constant velocity.
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – aspect ratio the render should fill (`None` = match image).
  * **image_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the source’s `width / height`. Pass it whenever
    `output_aspect` is set (see [`BurnsPath.push_in()`](#burns.BurnsPath.push_in)); without it
    the source is treated as square.
* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)
* **Returns:**
  A [`BurnsPath`](#burns.BurnsPath) (two keyframes — Start and End).

### Examples

```pycon
>>> ken_burns_path(1).evaluate(0.0)  # odd: push in, starts full
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> ken_burns_path(2).evaluate(1.0)  # even: pull out, ends full
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> ken_burns_path(3) == ken_burns_path(3)  # deterministic
True
```

### burns.ken_burns_video(image, path=BurnsPath(keyframes=((0.0, Rect(x=0.0, y=0.0, w=1.0, h=1.0)), (1.0, Rect(x=0.11538461538461542, y=0.11538461538461542, w=0.7692307692307692, h=0.7692307692307692))), easing='ease-in-out', interp='linear', output_aspect=None, version=1), , duration=2.0, fps=30, saveas=None, output_size=None, backend='pillow', codec='libx264', audio_codec='aac', \*\*write_kwargs)

Render one image into a pan/zoom video from a [`BurnsPath`](#burns.BurnsPath).

* **Parameters:**
  * **image** – path / `PIL.Image` / `np.ndarray`.
  * **path** ([`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)) – the motion spec. Default is a 2-second standard push-in.
  * **duration** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – clip length in seconds (the path’s clock is normalized, so
    duration is supplied here, not baked into the path).
  * **fps** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – frames per second.
  * **saveas** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – output path. Default: the source image’s name with
    `_kenburns` appended (auto-uniquified so an existing file is not
    overwritten). Required-ish when `image` has no source path —
    falls back to a temp file.
  * **output_size** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – explicit `(width, height)` (even-snapped). If omitted and
    `path.output_aspect` is set, the size is derived from it; otherwise
    the source image’s size is used.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – registered render backend name (default `"pillow"`).
  * **codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **audio_codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **\*\*write_kwargs** – forwarded to `write_videofile`.
* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
* **Returns:**
  The output [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path).

### Examples

```pycon
>>> ken_burns_video("photo.jpg")  # 2s push-in
>>> from burns import ken_burns_path
>>> ken_burns_video(
...     "photo.jpg", ken_burns_path(1), duration=5.0, saveas="out.mp4"
... )
```

### burns.move_kind(move)

How `move` is grouped: `"zoom"`, `"drift"`, `"static"`, `"select"`.

For a UI that wants a compass of directions separately from the rest, read
off the same table [`resolve_move()`](#burns.resolve_move) dispatches on.

### Examples

```pycon
>>> move_kind("drift_left"), move_kind("hold"), move_kind("auto")
('drift', 'static', 'select')
>>> sorted(m for m in MOVES if move_kind(m) == 'drift')
['drift_down', 'drift_left', 'drift_right', 'drift_up']
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### burns.parse_easing(spec='ease-in-out')

Resolve an easing spec to a callable `f: [0, 1] -> [0, 1]`.

Accepts:

> - a CSS name (`"linear"`, `"ease"`, `"ease-in"`, `"ease-out"`,
>   `"ease-in-out"`);
> - a CSS `"cubic-bezier(x1, y1, x2, y2)"` string;
> - a 4-element sequence `(x1, y1, x2, y2)`;
> - any callable, returned unchanged.

### Examples

```pycon
>>> parse_easing("linear")(0.3)
0.3
>>> round(parse_easing("cubic-bezier(0,0,1,1)")(0.7), 6)
0.7
>>> parse_easing(lambda t: t * t)(0.5)
0.25
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### burns.register_backend(name, backend)

Register a render backend under `name` (open-closed extension point).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### burns.resolve_move(move, , image, aspect, zoom=1.18, focus=None, seed=0, easing='ease-in-out', on_aspect_mismatch='raise', content_box=None)

Resolve an authored camera intent against `image` into a path.

* **Parameters:**
  * **move** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – a name from `MOVES`, or an explicit
    [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath) / its `to_dict()` payload. The two
    are the two front doors on this one path: a stored panel that
    carries both a named move and a hand-corrected override passes the
    override here and the choice is made in one place.
  * **image** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – the still the move is framed against — a path, `PIL.Image` or
    ndarray. **Required, and read every time**: the framing depends on
    what is in the picture, so swapping the still must re-frame. Do not
    cache the returned path against the intent.
  * **aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the delivered `width / height`. `None` means “match the
    image”. Required rather than defaulted, because a cut has a
    delivery size and quietly framing for the image’s aspect instead is
    a cover-crop nobody asked for.
  * **zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – 

    the end magnification. A pure function of the arguments — never
    jittered by `seed` or by a position — but \*\*bounded at both
    ends\*\*, so the number you pass is a request:
    * capped so the padded keep-region stays framed. A `focus`
      filling the frame therefore yields a nearly static move; the fix
      is a tighter `focus`, not a bigger `zoom`. A keep-region
      that *saliency* found covering `DIFFUSE_KEEP_AREA` or more
      of the picture is only a centre hint and does not cap: on a
      detailed photograph it covers nearly everything, and capping on
      it made every zoom render the same ~1.07.
    * floored. `push_in` / `pull_out` inherit
      `content_aware_path`’s `min_zoom + 0.02` (about 1.07), so a
      barely-there 1.02 push renders as 1.07; `hold` has no such floor
      and honours 1.02 exactly. A drift is floored to whatever leaves
      `DRIFT_MIN_ROOM` of travel.
  * **focus** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – an explicit keep-region overriding the saliency estimate. A
    [`Rect`](burns.rect.html.md#burns.rect.Rect), a normalized `(x, y, w, h)` tuple, or
    any object with `.x/.y/.w/.h`. When given,
    [`salient_box()`](burns.content.html.md#burns.content.salient_box) is not called at all.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – chooses which move `"auto"` becomes, and nothing else. Mint it
    once per panel and store it; never derive it from a position, which
    is the defect this parameter exists to remove.
  * **easing** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – CSS timing function or callable. A callable is fine here but
    cannot be serialized — see [`BurnsPath.to_dict()`](#burns.BurnsPath.to_dict). Applies to a
    named move; an explicit path carries its own.
  * **content_box** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – the part of `image` that is picture, as a normalized
    `(x, y, w, h)` (same forms as `focus`). Saliency runs inside it,
    so the blurred fill or bars a caller composited around a still do
    not read as subject. Ignored when `focus` is given.
  * **on_aspect_mismatch** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – what to do when an explicit path was authored for a
    different `output_aspect` than the one being rendered.
    `"raise"` (default) refuses, because honouring the stored
    rectangles at another shape cover-crops a framing somebody chose by
    hand. `"refit"` rebuilds each keyframe at the new aspect,
    **keeping what the author actually chose** — where the camera looks
    at each instant, and how far in it is — and changing only the window
    shape. A cut in a second aspect is a real workflow (a vertical
    edit of a landscape film), and a panel carries *one* path, not one
    per delivery, so “author a second path” is not a remedy a caller
    can take; `"refit"` is.
* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)
* **Returns:**
  A [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath). Duration is not part of it; pass that
  to the renderer.
* **Raises:**
  [**MoveError**](#burns.MoveError) – an unknown move name, a malformed `focus`, a non-positive
      `zoom` or `aspect`, or — under the default
      `on_aspect_mismatch="raise"` — an explicit path whose
      `output_aspect` contradicts `aspect`.

#### NOTE
`image` is opened for every *named* move. For an explicit path it is
read only when refitting, since resolved geometry needs no picture.

### Examples

```pycon
>>> import numpy as np
>>> img = np.zeros((600, 800, 3), dtype='uint8'); img[300:460, 500:700] = 230
```

A named move is a decision, so the seed does not touch it:

```pycon
>>> resolve_move("push_in", image=img, aspect=16 / 9, seed=1) == \
...     resolve_move("push_in", image=img, aspect=16 / 9, seed=999)
True
```

`"auto"` is where the seed does its one job:

```pycon
>>> a = resolve_move("auto", image=img, aspect=16 / 9, seed=3)
>>> a == resolve_move("auto", image=img, aspect=16 / 9, seed=3)
True
```

A drift travels — and `drift_right` ends further right:

```pycon
>>> d = resolve_move("drift_right", image=img, aspect=16 / 9)
>>> d.evaluate(1.0).x > d.evaluate(0.0).x
True
```

An explicit path is the other front door, returned as authored:

```pycon
>>> from burns import BurnsPath, Rect
>>> hand = BurnsPath.from_start_end(
...     Rect(0, 0, 1, 1), Rect(0.1, 0.1, 0.6, 0.6), output_aspect=16 / 9
... )
>>> resolve_move(hand.to_dict(), image=img, aspect=16 / 9) == hand
True
```

Rendering it at another delivery refuses by default, and `"refit"`
keeps the authored look while changing the window shape:

```pycon
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
```

### burns.salient_box(image, , downscale=320, threshold_pct=72.0, trim_pct=4.0, pad=0.05, min_size=0.35)

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

### Modules

| [`backends`](burns.backends.html.md#module-burns.backends)   | Pluggable single-clip render backends — the open-closed seam.                                                                                       |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`content`](burns.content.html.md#module-burns.content)     | Content-aware Ken Burns: choose crop windows that keep the subject (and any detected faces) framed, and avoid drifting over empty regions like sky. |
| [`easing`](burns.easing.html.md#module-burns.easing)       | Timing functions (easing) for Ken Burns motion.                                                                                                     |
| [`moves`](burns.moves.html.md#module-burns.moves)         | The named camera moves, and the one resolver that expands one into a path.                                                                          |
| [`path`](burns.path.html.md#module-burns.path)           | The render-agnostic Ken Burns motion spec: [`BurnsPath`](#burns.BurnsPath).                                              |
| [`rect`](burns.rect.html.md#module-burns.rect)           | The Ken Burns viewport rectangle — the render-agnostic geometric atom.                                                                              |
| [`render`](burns.render.html.md#module-burns.render)       | Ken Burns **renderers** — turn still images into pan/zoom video.                                                                                    |
