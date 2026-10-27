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

| [`frame_count`](#burns.backends.frame_count)(duration, fps)                      | The frames a `duration`-second clip at `fps` has, for every backend.       |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`frame_exact_clip`](#burns.backends.frame_exact_clip)(make_frame, duration, fps)     | A moviepy clip with exactly `frame_count(duration, fps)` frames.           |
| [`get_backend`](#burns.backends.get_backend)([name])                             | Look up a registered backend by name.                                      |
| [`pillow_backend`](#burns.backends.pillow_backend)(img_np, img_w, img_h, path, ...) | Default backend: lazy moviepy `VideoClip` + per-frame Pillow resampling.   |
| [`register_backend`](#burns.backends.register_backend)(name, backend)                 | Register a render backend under `name` (open-closed extension point).      |
| [`write_clip`](#burns.backends.write_clip)(clip, output, \*, codec, ...)        | `clip.write_videofile(output)` with burns' encode defaults, then close it. |

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

### burns.backends.frame_count(duration, fps)

The frames a `duration`-second clip at `fps` has, for every backend.

The single definition. It rounds, as the fleet’s other assemblers do, and
never returns less than one. moviepy alone would floor (1.99 s at 30 fps is
59 frames), which is why [`pillow_backend()`](#burns.backends.pillow_backend) sizes its clip from this.

### Examples

```pycon
>>> frame_count(9.0, 30), frame_count(1.99, 30), frame_count(0.001, 30)
(270, 60, 1)
```

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### burns.backends.frame_exact_clip(make_frame, duration, fps)

A moviepy clip with exactly `frame_count(duration, fps)` frames.

Used by every moviepy-based render path, so they share one frame count.

* **Return type:**
  `VideoClip`

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

### burns.backends.write_clip(clip, output, , codec, audio_codec, \*\*write_kwargs)

`clip.write_videofile(output)` with burns’ encode defaults, then close it.

MoviePy muxes audio through a temp file it writes to the **current directory**
unless told otherwise (`<stem>TEMP_MPY_wvf_snd.<ext>`) and removes it only
after a successful encode, so a failed one left it wherever its caller ran
(reeleehq/reelee#747). Unless the caller places or keeps that file itself
(`temp_audiofile`, `temp_audiofile_path`, `remove_temp=False`), it goes in a
private directory beside `output`, removed whatever happens.

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
