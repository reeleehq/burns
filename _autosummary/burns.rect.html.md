# burns.rect

The Ken Burns viewport rectangle — the render-agnostic geometric atom.

A [`Rect`](#burns.rect.Rect) is a normalized region of interest (ROI) over a source image:
`(x, y, w, h)` with **top-left origin, y-down**, every component a fraction
of the image in `[0, 1]`. This is the convention shared by `videopython`’s
`BoundingBox`, CSS `transform-origin` semantics, and FFmpeg’s coordinate
origin — adopting it (rather than the older center+magnification spec) is what
lets one spec drive a Python renderer, a future JS/TS renderer, and a CSS
preview without each reinventing the pixel mapping.

Zoom is expressed as **window-fraction** (the visible window is a fraction of
the image) rather than magnification; the magnification a backend like FFmpeg
`zoompan` wants is the derived read-only [`Rect.zoom`](#burns.rect.Rect.zoom).

The rect is pure data: no I/O, no image needed to construct or interpolate one.
Only `to_pixels()` takes image dimensions, because that is the single point
where normalized geometry meets a concrete raster.

### Classes

| [`Rect`](#burns.rect.Rect)(x, y, w, h)   | A normalized `(x, y, w, h)` viewport over a source image.   |
|---------------------------------------------------------------------|-------------------------------------------------------------|

### *class* burns.rect.Rect(x, y, w, h)

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
  [`Rect`](#burns.rect.Rect)

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
  [`Rect`](#burns.rect.Rect)

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
  [`Rect`](#burns.rect.Rect)

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
