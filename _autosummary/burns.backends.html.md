# burns.backends

Pluggable single-clip render backends — the open-closed seam.

A backend turns one `(image, BurnsPath, duration)` into one video file. They
all share the [`RenderBackend`](#burns.backends.RenderBackend) call signature and live in a name-keyed
`RENDER_BACKENDS` registry, so adding a backend (an FFmpeg `zoompan`
fast-path, a future GPU path) never edits the facade — you
[`register_backend()`](#burns.backends.register_backend) it and select it with `backend="…"`.

The default backend, `"pillow"`, drives a lazy `moviepy.VideoClip` whose
per-frame closure calls `burns._frame.sample_frame()`, so the whole clip is
never materialized in memory and the spec-to-pixel mapping stays in one place.
The multi-panel film renderer in [`burns.render`](burns.render.html.md#module-burns.render) deliberately does *not* go
through this registry — it is a single-pass encode across panels, which a
per-clip backend cannot express.

### Module Attributes

| [`DFLT_BACKEND`](#burns.backends.DFLT_BACKEND)   | Still `pillow`, deliberately.   |
|-----------------------------------------------------------------|---------------------------------|

### Functions

| [`get_backend`](#burns.backends.get_backend)([name])                             | Look up a registered backend by name.                                    |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`pillow_backend`](#burns.backends.pillow_backend)(img_np, img_w, img_h, path, ...) | Default backend: lazy moviepy `VideoClip` + per-frame Pillow resampling. |
| [`register_backend`](#burns.backends.register_backend)(name, backend)                 | Register a render backend under `name` (open-closed extension point).    |

### Classes

| [`RenderBackend`](#burns.backends.RenderBackend)(\*args, \*\*kwargs)   | Encode one image + `BurnsPath` into a video file at `output`.   |
|--------------------------------------------------------------------------------------|-----------------------------------------------------------------|

### burns.backends.DFLT_BACKEND *= 'pillow'*

Still `pillow`, deliberately. The two backends are NOT pixel-equivalent
(measured ~47 dB, dominated by resampler choice rather than by anything
either does wrong), so flipping the default would silently change the output
of every existing caller. The speed advantage that motivates the ffmpeg path
is also still unmeasured — see thorwhalen/burns#12.

### *class* burns.backends.RenderBackend(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Encode one image + `BurnsPath` into a video file at `output`.

Args mirror [`burns.ken_burns_video()`](burns.html.md#burns.ken_burns_video) after argument resolution: the
image is already a decoded `(H, W, C)` uint8 array with its pixel size,
and the output frame size `(out_w, out_h)` is already even-snapped.
Returns the written path.

### burns.backends.get_backend(name='pillow')

Look up a registered backend by name.

### Examples

```pycon
>>> get_backend() is get_backend("pillow")
True
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### burns.backends.pillow_backend(img_np, img_w, img_h, path, , duration, fps, output, out_w, out_h, codec, audio_codec, \*\*write_kwargs)

Default backend: lazy moviepy `VideoClip` + per-frame Pillow resampling.

Quality default; jitter-free (the window is computed in floating point and
rasterized once per frame, so there is no FFmpeg `zoompan` integer-rounding
stair-step).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### burns.backends.register_backend(name, backend)

Register a render backend under `name` (open-closed extension point).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
