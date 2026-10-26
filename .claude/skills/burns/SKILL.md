---
name: burns
description: Use when turning a still image (or a sequence of stills) into a pan/zoom video — the "Ken Burns effect" — OR when building a UI to author/select the motion path. Triggers on "ken burns", "pan and zoom a photo", "animate a still image", "make a slideshow with motion", "zoom into an image as video", "photo to video", any use of ken_burns_video / ken_burns_film / ken_burns_path / BurnsPath; on content-aware framing: "keep the subject/face in frame", "don't pan over the sky", content_aware_path / content_aware_path_for / salient_box; on STORING a move as data rather than geometry: "save the camera move", "the same move on a different picture", "named camera moves", MOVES / resolve_move / choose_move / move_kind, push_in / pull_out / drift_left / hold / auto; AND on the TypeScript side: "kenburnz", "ken burns path entry / selection / cropper UI", "author a BurnsPath", mountPathEntry, or work under ts/. Use BEFORE hand-rolling moviepy crop/resize-per-frame logic or a bespoke crop-rect UI.
---

# burns — Ken Burns pan/zoom video effects


> **Need images? Use `illustration`.** It is the fleet's image-retrieval package
> — one `search()` over Openverse / Wikimedia / Pexels / Pixabay, with licence
> and attribution on every hit, `dedupe()` to collapse several reproductions of
> the same subject into one, and `search("Category:…", source="wikimedia")` to
> browse a curated Commons category instead of guessing at filenames. Do not
> hand-roll an HTTP client against a stock or Commons API. Read its skill
> (`illustration/.claude/skills/illustration/SKILL.md`) before shipping any
> retrieved image — it carries the attribution obligations in full.

`burns` turns still images into cinematic pan/zoom films, driven by one
**render-agnostic motion spec** (the same path feeds the Python renderer here
and the TypeScript port `kenburnz` in `ts/`). Top-level imports:
`from burns import BurnsPath, Rect, ken_burns_path, ken_burns_video, ken_burns_film`
plus `content_aware_path, content_aware_path_for, salient_box, FacesDetector`.

Requires `ffmpeg` on PATH (moviepy encodes with it). Deps: numpy, moviepy, pillow.

> **Need text on the film — captions, a source line, a title card, credits?
> Use `tituli`.** It composites rendered text onto the *finished* Ken Burns
> video (text burned into a still would pan and zoom with the picture), and
> `salient_box` is its `avoid=` seam: `tituli.Frame.from_image(still,
> avoid=burns.salient_box)` keeps the caption off the subject. Read its skill
> before writing any `ImageDraw` overlay.

## The viewport: `Rect(x, y, w, h)`

A *rect* is a normalized window over the image: `(x, y, w, h)` all in `[0, 1]`,
**top-left origin, y-down** (the videopython / CSS / FFmpeg convention).
`Rect(0, 0, 1, 1)` is the whole image. Zoom is **window-fraction** — a smaller
`w`/`h` is more zoomed in; `Rect.zoom` is the derived `1/max(w,h)` magnification.

- `Rect.from_center_zoom(cx, cy, zoom, *, aspect=1.0)` — build from a pan center
  + zoom (the bridge from the old center+scale model). Auto-clamped inside the image.
- `Rect.clamped()` — slide a window inside the image **without resizing** it
  ("ride the wall" — avoids the breathing/stretch artefact).
- `Rect.to_pixels(img_w, img_h)` — integer crop box `(x0, y0, x1, y1)`.

## The motion spec: `BurnsPath`

Pure, time-parameterized, frame-count-free. **`path.evaluate(t) -> Rect`** for
`t ∈ [0, 1]` is the single primitive everything else builds on.

- `BurnsPath.from_start_end(start, end, *, easing="ease-in-out", output_aspect=None)`
  — the canonical two-rectangle (Start → End) case.
- `BurnsPath.push_in(zoom=1.3, *, to=(0.5,0.5), easing=..., output_aspect=None, image_aspect=None)`
  — the 90%-case one-liner.
- `BurnsPath(keyframes=((t, rect), ...), easing=..., output_aspect=...)` — N
  keyframes (a hold = two keyframes with equal rects).
- `path.reversed()` — swap Start/End (the NLE "Swap" button).
- `path.to_dict()` / `BurnsPath.from_dict(d)` — versioned JSON wire format (the
  cross-language SSOT). Callable easings aren't serializable — use CSS strings.

**Easing is composed over geometry**: `evaluate(t) == geometry(easing(t))`.
Easing is a CSS timing function — `"linear"`, `"ease"`, `"ease-in"`,
`"ease-out"`, `"ease-in-out"` (default — the cinematic norm), a
`"cubic-bezier(x1,y1,x2,y2)"` string, a 4-tuple, or any callable `[0,1]→[0,1]`.

**`output_aspect`** is the AR the render should fill, *independent of the source
image* — set it to `16/9` to make a widescreen clip from a portrait photo. When
it differs from the image AR the renderer center-cover-crops (no stretch). `None`
= match the image (the legacy behavior). **When you set `output_aspect` on `push_in` / `ken_burns_path`, also pass `image_aspect` (source width/height)**: rect sides are image fractions, so without it the source is assumed square and a 16:9 still loses ~44% of its height at zoom 1.0.

## `ken_burns_path(index, *, style="push", zoom=1.10, pan=0.03, easing="ease-in-out", output_aspect=None, image_aspect=None)`

Build a cohesive, **deterministic** `BurnsPath` for the `index`-th image of a
sequence — no hand-authored rectangles. Same args → same path. **Duration is
NOT part of the path** (it's a render-time arg).

- `index` (1-based): **odd indices push in, even pull out**; focal direction
  rotates per index → sequence rhythm without changing direction within a shot.
- `style="push"` (default): zoom-led toward an off-center focal point.
- `style="drift"`: pure horizontal pan, alternating direction per index (`zoom`
  ignored — drift derives its own from `pan`).

## Content-aware paths — when the motion must respect the picture

Use these INSTEAD of `ken_burns_path` when the framing must follow what's *in*
the image: keep a subject or faces in frame, don't drift over empty sky. Same
duration-free `BurnsPath` out, same render call. Boxes everywhere are normalized
`(x, y, w, h)` in `[0, 1]`, top-left origin — the `Rect` convention.

- `content_aware_path_for(image, *, subject=None, faces=(), faces_detector=None, index=0, output_aspect=None, **kwargs)`
  — the one to reach for. Reads `image` (path / PIL / ndarray), derives the
  subject via `salient_box`, takes faces from `faces` or `faces_detector(img)`,
  delegates to `content_aware_path`. `**kwargs` forward (`zoom`, `min_zoom`,
  `keep_pad`, `mode`, `easing`). `subject` is a **named** parameter, not one of
  those: it replaces the saliency estimate (which is then not computed at all),
  and passing it through `**kwargs` used to raise `TypeError: got multiple
  values` from inside `content_aware_path`.
- `content_aware_path(img_w, img_h, *, subject=None, faces=(), index=0, output_aspect=None, zoom=1.3, min_zoom=1.05, keep_pad=0.18, mode="auto", easing="ease-in-out")`
  — the pure-geometry core: touches no pixels, deterministic. Use it when the
  boxes come from elsewhere (a UI, a DB, an upstream vision pipeline).
- `salient_box(image, *, downscale=320, threshold_pct=72.0, trim_pct=4.0, pad=0.05, min_size=0.35) -> Box`
  — gradient-magnitude estimate of the busy/detailed region; flat sky/wall/water
  falls away. Falls back to a centered `(0.15, 0.15, 0.7, 0.7)` box when the
  image is too uniform to decide.

**No extra install for this feature, and no bundled face model.** `salient_box`
uses only numpy + Pillow (already required). Detection is *injected*:
`FacesDetector = Callable[[Any], Sequence[Box]]` — OpenCV, ONNX, a vision model,
or hand-authored boxes. The detector is always called with a `PIL.Image`
(`content_aware_path_for` opens/converts the input first), whatever type you
passed as `image`. Omit it and you get saliency-only motion: no error, no
warning, just a less specific keep-region.

```python
from burns import content_aware_path_for, ken_burns_video

ken_burns_video("photo.jpg", content_aware_path_for("photo.jpg", index=1), duration=5.0)
```

Gotchas:

- **`zoom` is a request, not a guarantee** — it's capped so the padded
  keep-region stays framed. A subject filling the frame therefore yields a
  near-static move; the fix is a tighter keep-region, not a bigger `zoom`.
- The `min_zoom + 0.02` floor **wins over** that cap, so a huge keep-region gets
  slightly cropped rather than producing zero motion.
- `index` defaults to **0** here (even → pull out); `ken_burns_path`'s `index`
  is required and 1-based. Same parity rule, different default.
- Explicit `faces=[...]` short-circuits `faces_detector` — the detector runs
  only when `faces` is empty. Faces beat `subject`; the keep-region is the
  **union** of all face boxes.

## Storing a move — `MOVES` + `resolve_move` (reach for this before persisting a path)

**Never persist a `BurnsPath` as a panel's camera setting.** It is *resolved
geometry* — rectangles measured against one picture's pixels — so it pins the
move to that picture. Store the **authored intent** and resolve it at render
time; replacing the still must re-frame.

```python
from burns import MOVES, resolve_move, choose_move, move_kind

MOVES  # ('push_in','pull_out','drift_left','drift_right','drift_up','drift_down','hold','auto')

path = resolve_move("push_in", image=still, aspect=16 / 9, zoom=1.18, seed=4021)
```

`resolve_move(move, *, image, aspect, zoom=1.18, focus=None, seed=0, easing="ease-in-out", on_aspect_mismatch="raise") -> BurnsPath`

- **`move` is two front doors on one path**: a name from `MOVES`, *or* an
  explicit `BurnsPath` / its `to_dict()` payload. So a panel carrying an
  optional hand-corrected override makes the same single call —
  `resolve_move(panel.path or panel.move, ...)` — and the choice is made once,
  here, not once per consumer.
- **`image` is read every time.** Framing depends on what is in the picture.
  Do **not** cache the returned path against the intent; that is the whole
  point of the split.
- **`aspect`** is the delivered `width / height` (`= output_aspect`). Required,
  not defaulted — a cut has a delivery size, and quietly framing for the
  image's aspect instead is a cover-crop nobody asked for. `None` explicitly
  means "match the image".
- **`focus`** overrides the saliency box: a `Rect`, a normalized `(x,y,w,h)`
  tuple, a mapping with those keys, or any object with `.x/.y/.w/.h` (so a
  pydantic body is a focus box without importing burns). When given,
  `salient_box` is **not called**. **It is normalized against the `image`
  argument, not against the original still** — if you pre-composite stills onto
  a delivery-sized canvas (a blurred fill, a letterbox), a focus box a user drew
  on the source still is in the wrong space and will frame the wrong thing.
  Convert it, or pass the pre-composite image.
- **`seed` is not a position, and does exactly one job**: which concrete move
  `"auto"` becomes. Mint it once per panel and store it. It deliberately does
  **not** perturb a named move — a decision a seed can nudge is not a decision.

Why `seed` exists: deriving motion from a panel's ordinal (`style = STYLES[i%2]`,
`zoom = 1.14 + 0.02*(i%4)`, `content_aware_path_for(index=i)`) means reordering
one panel changes the camera on **every** panel after it, and "keep this move,
change this picture" is unexpressible. `resolve_move` is a pure function of its
arguments and never of a position.

Gotchas:

- **A drift's name is the direction the CAMERA travels** — `drift_right` ends
  with the window further right, so the picture slides *left* across the frame.
  The opposite reading is the one people reach for first.
- A drift's travel is capped at `DRIFT_SPAN` (a tenth) of the frame, so a
  vertical and a horizontal drift read at the same speed on a picture whose two
  axes leave very different amounts of room. Its zoom is *raised* if the
  requested one leaves no room to travel (`DRIFT_MIN_ROOM`) — a drift that
  silently becomes a hold is the failure that floor prevents.
- `hold` honours `zoom`: it is a *static framing*, not necessarily the whole
  picture. Pass `zoom=1.0` for the untouched frame.
- An explicit path override is returned **as authored**. If its `output_aspect`
  contradicts `aspect`, `resolve_move` **raises** (`MoveError`) rather than
  cover-cropping a hand-drawn framing without saying so. This is not academic:
  a panel carries *one* path and a project can have several cuts at different
  aspects, so a move hand-corrected on the 16:9 cut hits it in the vertical cut.
  `on_aspect_mismatch="refit"` rebuilds each keyframe at the new aspect,
  **keeping the author's centre and zoom at every instant** and changing only
  the window shape — that is the option to reach for when rendering a second
  delivery of the same project.
- **Caching a render? Put `burns.RESOLVER_IMPL_VERSION` in the cache key.** The
  pixels a stored intent becomes are decided by this module's constants
  (`DFLT_ZOOM`, `DRIFT_TRAVEL`, `DRIFT_SPAN`, `DRIFT_MIN_ROOM`,
  `AUTO_WEIGHTS`), so a key built from the panel alone serves stale frames
  forever after a retune, or renders a cut that disagrees with its siblings.
  It is `nw.Transform.impl_version`'s "a lock, not a receipt", and it is
  deliberately **not** the package version — `burns.__version__` does not exist
  and `importlib.metadata.version("burns")` is unreliable (plan §4).
- **`aspect` and `zoom` are validated.** A non-positive, NaN or infinite value
  raises rather than being passed through: `aspect=0.0` is falsy and would
  quietly mean "match the image", and a negative aspect produces a
  negative-width rect that still passes `Rect.is_contained()`.
- **The move name is matched strictly** — no whitespace stripping, no case
  folding — so a consumer mirroring `MOVES` to validate its own stored field
  agrees with burns exactly.
- `zoom` is honoured, never jittered — and still capped so the keep-region stays
  framed (a subject filling the frame yields an almost static move; the fix is a
  tighter `focus`, not a bigger `zoom`).
- `choose_move(seed)` is public so a UI can show `auto → drift_left`, and so a
  user can *pin* what auto chose by storing that name instead. `move_kind(name)`
  groups the vocabulary (`"zoom"` / `"drift"` / `"static"` / `"select"`) off the
  same table `resolve_move` dispatches on — do not keep a second list.
- `"hold"` and `"auto"` sit in `MOVES` beside the directional moves because it
  is **one field's value set**. They differ in *kind*, not in membership; read
  the difference with `move_kind`, not with a second constant.
- **burns owns the vocabulary.** If you mirror `MOVES` to validate a stored
  field before a render, pin the mirror equal to `burns.MOVES` with a test that
  *fails* when burns is absent rather than skipping — a doubly-soft
  `importorskip` + `hasattr` skip goes green in exactly the environment where
  the two have drifted.
- `"auto"` is i.i.d. per seed and knows nothing of its neighbours, so it gives
  a good global distribution but **not** sequence-level variety: expect a few
  adjacent repeats in any 24-panel track. If you need "never the same move
  twice in a row", that is the caller's to enforce when it mints the seeds.
  And note `seed=0` is the default on both sides — an import that forgets to
  mint seeds renders every `auto` panel as the same move.

## `ken_burns_video(image, path=DEFAULT_BURNS_PATH, *, duration=2.0, fps=30, saveas=None, output_size=None, backend="pillow", ...)`

Render ONE image → mp4. `image` is a path / `PIL.Image` / numpy array. `path` is
a `BurnsPath`; `duration` is seconds. Returns the output `Path` (auto-named
`{stem}_kenburns.mp4` next to the source when `saveas` is None).

```python
ken_burns_video("photo.jpg")  # 2s default push-in
ken_burns_video("photo.jpg", ken_burns_path(1), duration=5.0, saveas="out.mp4")
ken_burns_video(
    "portrait.jpg", BurnsPath.push_in(1.4, output_aspect=16 / 9, image_aspect=3 / 4), duration=6
)
```

Backends are pluggable via the `RenderBackend` registry (`register_backend`).
Two ship:

- **`"pillow"` (default)** — lazy moviepy + per-frame Pillow resampling,
  jitter-free, and the only one with no constraints on the path.
- **`"ffmpeg"`** — one process. The path is sampled and compiled to a filter
  graph by [`looks`](https://github.com/thorwhalen/looks), and burns runs the
  argv. `burns` owns the authored geometry, `looks` owns compiling it.

They are **not pixel-identical**: ~52 dB apart on a smooth image, ~34 dB on hard
edges, dominated by resampler choice rather than framing. `pillow` stays the
default so switching is a decision, not a surprise. The ffmpeg path **refuses**
— naming `backend="pillow"` — any path it cannot express (a zoom past 10x, which
`zoompan` would otherwise clamp silently), rather than rendering something else.

Two knobs it adds, both keyword-only: `samples=` (how densely the eased path is
sampled; the default is measured, not fixed) and `ffmpeg_exe=` (which binary —
the default is the GPL-configured one moviepy bundles, so a commercial shipper
may want their own).

## `ken_burns_film(panels, *, saveas, fps=30, audio_path=None, ...)`

Render a sequence of `(image, path, duration_s)` **triples** as ONE continuous
film — a single encode pass, so no concatenation seams and no per-image freeze
frames at cuts. `saveas` required. Optional `audio_path` muxes in a pre-built
track (assemble/pad it to the film duration yourself — renderer stays pure visual).

```python
panels = [
    ("a.jpg", ken_burns_path(1), 4.0),
    ("b.jpg", ken_burns_path(2), 4.0),
    ("c.jpg", ken_burns_path(3), 4.0),
]
ken_burns_film(panels, saveas="film.mp4", fps=30, audio_path="narration.mp3")
```

## TypeScript port (`kenburnz`, in `ts/`)

The same render-agnostic spec is mirrored in TypeScript under `ts/` (published
as **`kenburnz`**), pinned bit-for-bit to the Python side by the shared
golden-vector fixture (`tests/golden/vectors.json`). Same vocabulary: `Rect`,
`BurnsPath.evaluate(t)`, `sampleBox`, CSS easing strings. Plus browser-only
extras: `cssPreviewAt` (zero-cost CSS-transform preview) and a WebCodecs
exporter. **Never change `BurnsPath.toDict()` field names** — that's the
cross-language wire contract.

## Path-entry component — authoring a `BurnsPath` (headless, schema-first)

For *authoring* a path in a UI (not rendering it), `kenburnz` ships a headless,
schema-first component. Spec: `misc/docs/ken_burns_path_entry_component_spec.md`.
Two entry points:

- **`kenburnz/component`** — DOM-free core. zod schemas (`Config` / `Value` /
  `State`), pure geometry (AR-lock, containment clamp, `rectFromDrag`,
  `translateRect`, `scaleRect`, `rectReadout`), the data-driven preset catalog,
  and a **pure reducer** `reduce(state, event, catalog)` + selectors
  (`resolveStartEnd`, `editTargets`, `toValue`). Build any renderer on top.
- **`kenburnz/vanilla`** — the default vanilla DOM renderer:
  `mountPathEntry(el, config, { onChange, onSubmit }) → handle`. AR-locked crop
  rect over a dim matte, handles, rule-of-thirds, drag/pan/resize, keyboard
  nudge, duration/easing/swap/aspect controls, side-by-side / overlay / tabbed
  layouts. Theme via `--kb-*` CSS custom properties. A *replaceable example*,
  not privileged.

```ts
import { mountPathEntry } from 'kenburnz/vanilla';
const handle = mountPathEntry(el, {
  image: { src, width: 1920, height: 1080 },
  targetAspect: { num: 16, den: 9, locked: true },
}, { onSubmit: (value) => submit(value) });   // value = the BurnsPath JSON
```

**The emitted `Value`** is the wire shape `BurnsPath.toDict()` emits (snake_case,
`output_aspect: number|null`) **plus** two optional additive fields the UI
authors: `duration_ms` and `meta` (`preset_id`, `preset_params`,
`output_aspect_ratio`). Additive fields are ignored by `evaluate` and by
backends that don't need them — Python parity is preserved. A JSON Schema of
this contract is committed under `ts/schemas/burns-path.schema.json`
(regenerate with `pnpm schema`).

- The crop rect is AR-locked to the **output** aspect (not the image's): in
  normalized image units, `w/h = output_aspect / image_aspect`, so the rendered
  window (after cover-crop) is exactly what the user drew.
- Presets are **data** (`{ id, label, icon, arity, params?, derive }`) — add an
  entry, don't edit the core. Default set: zoom in/out + 4 pans + drift
  (arity 0); push-in-to / pull-out-from / enter-/exit-edge / reveal-around
  (arity 1); custom (arity 2).
- To write your own renderer: `initState` → `reduce` on `Event`s → draw
  `resolveStartEnd` / `editTargets`; `kenburnz/vanilla`'s source is the worked
  example. README "Path-entry component" section has the full guide.
- Demo: `cd ts/demo && pnpm dev` → `/path-entry.html`.

## Gotchas

- **Build films with one `ken_burns_film` call**, not by rendering per-image
  clips and concatenating — concat reintroduces the seam/freeze artefacts.
- `duration` lives on the renderer, not the path — `ken_burns_path` and
  `BurnsPath` are duration-free (the clock is normalized `[0,1]`).
- Default easing is `"ease-in-out"`, NOT linear — pass `"linear"` for constant velocity.
- Even pixel dimensions are required by libx264; the renderer snaps output dims
  to even automatically, but synthetic test images should use even width/height.
- fps below ~24 looks choppy; default 30 is smooth.
- A serializable path needs a CSS easing (string/tuple), not a Python callable.
