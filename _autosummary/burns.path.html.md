# burns.path

The render-agnostic Ken Burns motion spec: [`BurnsPath`](#burns.path.BurnsPath).

A [`BurnsPath`](#burns.path.BurnsPath) is the single source of truth for \*how the virtual camera
moves over a still image\* — pure data, no image, no encoder, no frame count.
Its one job is [`BurnsPath.evaluate()`](#burns.path.BurnsPath.evaluate): given a normalized clock time
`t in [0, 1]` it returns the [`Rect`](burns.rect.html.md#burns.rect.Rect) viewport at that
instant. That pure `t -> Rect` primitive is what makes the motion unit-
testable without rendering, serializable across the wire as JSON, and
re-implementable identically in JS/TS for an in-browser preview.

The model mirrors the professional NLE consensus and Remotion’s
`interpolate`:

- **Keyframes** are `(t, Rect)` waypoints with `t in [0, 1]`. Two keyframes
  is the canonical Start/End Ken Burns case; N keyframes is the strict
  generalization (a hold is two keyframes with equal rects; a single keyframe is
  also valid and means a static framing).
- **Easing** (a CSS timing function) is composed *over* the geometry —
  `evaluate(t) == geometry(easing(t))` — keeping motion *shape* orthogonal to
  motion *speed*. Default `"ease-in-out"` (the cinematic norm).
- **output_aspect** is metadata: the aspect ratio the render should fill. When
  it differs from the source image’s AR the renderer cover-crops; when `None`
  the output AR equals the image’s. It never affects `evaluate()`.

[`ken_burns_path()`](#burns.path.ken_burns_path) is a convenience generator: it maps a small intent
vocabulary (a sequence index, a style, a zoom, a pan) to a cohesive, fully
deterministic [`BurnsPath`](#burns.path.BurnsPath), so callers animating a sequence of images get
non-repetitive motion without hand-authoring rectangles.

### Functions

| [`ken_burns_path`](#burns.path.ken_burns_path)(index, \*[, style, zoom, pan, ...])   | A deterministic [`BurnsPath`](#burns.path.BurnsPath) for the `index`-th image of a sequence.   |
|-------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|

### Classes

| [`BurnsPath`](#burns.path.BurnsPath)(keyframes[, easing, interp, ...])   | A time-parameterized pan/zoom motion over a still image.   |
|------------------------------------------------------------------------------------------------|------------------------------------------------------------|

### *class* burns.path.BurnsPath(keyframes, easing='ease-in-out', interp='linear', output_aspect=None, version=1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A time-parameterized pan/zoom motion over a still image.

Construct it directly from keyframes, or via [`from_start_end()`](#burns.path.BurnsPath.from_start_end) /
[`push_in()`](#burns.path.BurnsPath.push_in) for the common cases, or via [`ken_burns_path()`](#burns.path.ken_burns_path) for
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

The viewport `Rect` at normalized clock time `t in [0, 1]`.

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

Rebuild a [`BurnsPath`](#burns.path.BurnsPath) from [`to_dict()`](#burns.path.BurnsPath.to_dict) output.

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> BurnsPath.from_dict(p.to_dict()) == p
True
```

* **Return type:**
  [`BurnsPath`](#burns.path.BurnsPath)

#### *classmethod* from_start_end(start, end, , easing='ease-in-out', output_aspect=None)

The canonical two-rectangle Ken Burns case (Start frame -> End frame).

### Examples

```pycon
>>> BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
...
BurnsPath(keyframes=((0.0, Rect(...)), (1.0, Rect(...))), ...)
```

* **Return type:**
  [`BurnsPath`](#burns.path.BurnsPath)

#### *classmethod* push_in(zoom=1.3, , to=(0.5, 0.5), easing='ease-in-out', output_aspect=None)

The 90%-case constructor: a slow push from the full image toward
`to` at `zoom`.

### Examples

```pycon
>>> round(BurnsPath.push_in().evaluate(1.0).zoom, 4)
1.3
```

* **Return type:**
  [`BurnsPath`](#burns.path.BurnsPath)

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
  [`BurnsPath`](#burns.path.BurnsPath)

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

### burns.path.ken_burns_path(index, , style='push', zoom=1.1, pan=0.03, easing='ease-in-out', output_aspect=None)

A deterministic [`BurnsPath`](#burns.path.BurnsPath) for the `index`-th image of a sequence.

Maps intent to geometry so a sequence of images gets cohesive, non-repetitive
motion without hand-authoring rectangles. Per-index deterministic: identical
args always return an identical path. Duration is *not* part of the path — it
is a render-time parameter (pass it to [`burns.ken_burns_video()`](burns.html.md#burns.ken_burns_video) /
[`burns.ken_burns_film()`](burns.html.md#burns.ken_burns_film)).

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
* **Return type:**
  [`BurnsPath`](#burns.path.BurnsPath)
* **Returns:**
  A [`BurnsPath`](#burns.path.BurnsPath) (two keyframes — Start and End).

### Examples

```pycon
>>> ken_burns_path(1).evaluate(0.0)  # odd: push in, starts full
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> ken_burns_path(2).evaluate(1.0)  # even: pull out, ends full
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> ken_burns_path(3) == ken_burns_path(3)  # deterministic
True
```
