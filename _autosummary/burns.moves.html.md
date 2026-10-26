# burns.moves

The named camera moves, and the one resolver that expands one into a path.

A [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath) is *resolved geometry*: rectangles measured
against one picture’s pixels. That makes it the wrong thing to store when the
picture can change. What an editor wants to keep is the **authored intent** —
“push in on this, gently” — and have the rectangles computed against whatever
image is in the slot at render time. Replace the still and the move re-frames;
keep the still and the move is exactly what it was.

So this module is the vocabulary ([`MOVES`](#burns.moves.MOVES)) plus the one function that
turns an intent into geometry ([`resolve_move()`](#burns.moves.resolve_move)).

**One code path, two front doors.** `resolve_move` takes a *name* or an
explicit `BurnsPath` (or its `to_dict()` payload), so a caller that stores
both a named move and an optional hand-corrected path override makes one call
and the choice between them is made here — once — rather than once per consumer.
This is `an.ir.camera.camera_keys`’ arrangement: one table, not two tables
reconciled by a test.

**\`\`seed\`\` replaces the ordinal, and does one job.** The motion in a sequence
used to be derived from each panel’s *position* — style by `i % 2`, zoom by
`i % 4`, push-or-pull by the parity of `i`. Reordering one panel therefore
changed the camera on every panel after it, and “keep this move, change this
picture” was unexpressible. `resolve_move` is a pure function of its
arguments and never of a position; a caller mints a `seed` once, stores it
beside the move, and the move survives every reorder.

The seed’s *only* job is choosing which concrete move `"auto"` becomes
([`choose_move()`](#burns.moves.choose_move)). It deliberately does **not** perturb a named move’s zoom
or framing: a named move is a decision, and a decision a seed can still nudge
is not one. Variety across a sequence comes from `"auto"` and from the
pictures themselves — the content-aware framing differs per image already.

```pycon
>>> import numpy as np
>>> img = np.zeros((600, 800, 3), dtype='uint8'); img[380:520, 120:300] = 210
>>> path = resolve_move("push_in", image=img, aspect=16 / 9, seed=41)
>>> path.evaluate(1.0).zoom >= path.evaluate(0.0).zoom
True
>>> resolve_move("hold", image=img, aspect=16 / 9).evaluate(0.0) == \
...     resolve_move("hold", image=img, aspect=16 / 9).evaluate(1.0)
True
```

### Module Attributes

| [`RESOLVER_IMPL_VERSION`](#burns.moves.RESOLVER_IMPL_VERSION)   | The identity of the resolver's *geometry*, for a caller's cache key.                                                                          |
|--------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| [`DIFFUSE_KEEP_AREA`](#burns.moves.DIFFUSE_KEEP_AREA)       | The area (share of the picture) around which a saliency keep-region that reaches the borders stops being a subject and becomes a centre hint. |
| [`DFLT_ZOOM`](#burns.moves.DFLT_ZOOM)               | Default end magnification.                                                                                                                    |
| [`DRIFT_TRAVEL`](#burns.moves.DRIFT_TRAVEL)            | How much of the available travel a drift uses, as a fraction of the room the window leaves inside the image.                                  |
| [`DRIFT_SPAN`](#burns.moves.DRIFT_SPAN)              | A ceiling on that travel, as a fraction of the **window** rather than of the image — how far the camera crosses its own frame.                |
| [`DRIFT_MIN_ROOM`](#burns.moves.DRIFT_MIN_ROOM)          | The least travel room a drift will accept, in image units.                                                                                    |
| [`MOVES`](#burns.moves.MOVES)                   | Every name a stored `move` field may hold — one vocabulary, because it is one field.                                                          |
| [`AUTO_WEIGHTS`](#burns.moves.AUTO_WEIGHTS)            | How often `"auto"` picks each move, as integer weights.                                                                                       |

### Functions

| [`choose_move`](#burns.moves.choose_move)(seed)                                  | Which concrete move `"auto"` resolves to for `seed`.                |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`move_kind`](#burns.moves.move_kind)(move)                                    | How `move` is grouped: `"zoom"`, `"drift"`, `"static"`, `"select"`. |
| [`resolve_move`](#burns.moves.resolve_move)(move, \*, image, aspect[, zoom, ...]) | Resolve an authored camera intent against `image` into a path.      |

### Exceptions

| [`MoveError`](#burns.moves.MoveError)   | A move that cannot be resolved into a path.   |
|--------------------------------------------------------------|-----------------------------------------------|

### burns.moves.AUTO_WEIGHTS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [int](https://docs.python.org/3/builtins/functions.html#int)]* *= mappingproxy({'push_in': 3, 'pull_out': 3, 'drift_left': 1, 'drift_right': 1, 'drift_up': 1, 'drift_down': 1})*

How often `"auto"` picks each move, as integer weights. Pushes and pulls
dominate because a commentary film is mostly faces and documents, where a
drift wanders off the thing being talked about; the drifts are there so a
long sequence does not read as one move repeated.
Read-only on purpose. The pool [`choose_move()`](#burns.moves.choose_move) draws from is built once
at import, so assigning into a plain dict here would change the documented
weights and change nothing about the moves — a silent no-op in a name that
is in `__all__`. Retuning these is a burns change that bumps
[`RESOLVER_IMPL_VERSION`](#burns.moves.RESOLVER_IMPL_VERSION), not something a consumer does at runtime.

### burns.moves.DFLT_ZOOM *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 1.18*

Default end magnification. Enough that a slow push reads as movement on a
1080p frame, little enough that a found still is not visibly softened by the
upscale.

A **drift** may render slightly above it: reaching [`DRIFT_SPAN`](#burns.moves.DRIFT_SPAN) needs
[`DRIFT_MIN_ROOM`](#burns.moves.DRIFT_MIN_ROOM) of travel room, which at this zoom is marginally more
than the window leaves, so the floor raises it to ~1.2. That is the floor
working, not a jitter — it is a pure function of the arguments.

### burns.moves.DIFFUSE_KEEP_AREA *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.5*

The area (share of the picture) around which a saliency keep-region that
reaches the borders stops being a subject and becomes a centre hint.
On a detailed photograph gradient saliency marks nearly everything, and
treating that as a subject capped every requested zoom at ~1.0, so
`push_in` rendered its ~1.07 floor whatever was asked (burns#21, measured
on 10 of 10 archive photos). Such a region is replaced by the largest keep-
region that still honours the requested zoom, centred where saliency
points. An explicit `focus` is never treated this way: it is a decision.
It is the centre of a ramp (`DIFFUSE_KEEP_RAMP`) and applies only to a
box touching `DIFFUSE_MIN_EDGES` borders; the default centred box
([`DFLT_KEEP_BOX`](burns.content.html.md#burns.content.DFLT_KEEP_BOX)) touches none, so a uniform picture
keeps its old framing.

### burns.moves.DRIFT_MIN_ROOM *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.16666666666666669*

The least travel room a drift will accept, in image units. When the
requested `zoom` leaves less, the zoom is *raised* until it does — the same
way `content_aware_path`’s `min_zoom` floor wins over its framing cap.
A drift with no room is a hold, and silently returning one is the failure
this floor exists to prevent.

**It is derived, not chosen**, and the derivation is the point. Travel is
`min(room * DRIFT_TRAVEL, size * DRIFT_SPAN)` with `size == 1 - room`, so
the span can only ever bind when
`room >= DRIFT_SPAN / (DRIFT_TRAVEL + DRIFT_SPAN)` — one sixth, at the
values above. Set below that and the two constants can *never* both bind:
the floor silently wins everywhere, every room-limited drift crosses
`DRIFT_TRAVEL * DRIFT_MIN_ROOM / (1 - DRIFT_MIN_ROOM)` of its frame, and
[`DRIFT_SPAN`](#burns.moves.DRIFT_SPAN)’s promise that the two axes read at the same speed holds
only on pictures with room to spare. At `0.08` it measured 2.3x apart on a
portrait still delivered at 16:9 — the exact asymmetry DRIFT_SPAN exists to
remove. `tests/test_moves.py` pins the relationship, so changing either
constant without the other fails.

### burns.moves.DRIFT_SPAN *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.1*

A ceiling on that travel, as a fraction of the **window** rather than of the
image — how far the camera crosses its own frame.

Without it a drift’s speed is whatever room the picture happened to leave,
which is not the same on both axes: on a 4:3 still delivered at 16:9 there is
twice as much vertical room as horizontal, so `drift_up` travelled ~29 % of
the frame where `drift_left` travelled ~9 % — the same named gesture at
three times the speed, decided by the aspect of the picture. `an`’s camera
hit the same asymmetry from the other direction and answered it the same way,
with one fraction of the frame per axis (`an.ir.camera.PAN_FRACTION`).

A tenth is calibrated against what the room-limited horizontal case already
produces at [`DFLT_ZOOM`](#burns.moves.DFLT_ZOOM), and against `ken_burns_path(style="drift")`’s
~7 %: legible at 1080p over a normal panel, and not a whip.

### burns.moves.DRIFT_TRAVEL *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.5*

How much of the available travel a drift uses, as a fraction of the room the
window leaves inside the image. Less than `1.0` on purpose: a drift that
runs wall to wall starts and ends against an edge, which reads as the frame
hitting a stop rather than as a camera continuing past the cut.

### burns.moves.MOVES *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('push_in', 'pull_out', 'drift_left', 'drift_right', 'drift_up', 'drift_down', 'hold', 'auto')*

Every name a stored `move` field may hold — one vocabulary, because it is
one field. `"hold"` and `"auto"` sit beside the directional moves for
that reason: splitting them into separate constants would make a consumer
union two tuples to validate one field. They differ in *kind*, not in
membership, and [`move_kind()`](#burns.moves.move_kind) is where that difference is read.

**burns owns this vocabulary.** A consumer that needs to validate its own
stored field before a render (rather than discovering a typo five minutes
in) will mirror it; that mirror must be pinned equal to this tuple by a test
that *fails* when burns is absent rather than skipping, or the two drift
silently. burns is deliberately strict about the spelling — no case folding
and no whitespace stripping — so a mirror written as a plain membership test
agrees with it exactly.

### *exception* burns.moves.MoveError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A move that cannot be resolved into a path.

A plain [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError) subclass, so a consumer that already catches
`ValueError` around its authoring layer keeps working, and so nothing
downstream needs to import [`burns.moves`](#module-burns.moves) to handle it.

### burns.moves.RESOLVER_IMPL_VERSION *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 2*

The identity of the resolver’s *geometry*, for a caller’s cache key.

A stored panel is an intent, so the pixels it becomes depend on constants
that live here — [`DFLT_ZOOM`](#burns.moves.DFLT_ZOOM), [`DRIFT_TRAVEL`](#burns.moves.DRIFT_TRAVEL), [`DRIFT_SPAN`](#burns.moves.DRIFT_SPAN),
[`DRIFT_MIN_ROOM`](#burns.moves.DRIFT_MIN_ROOM), [`AUTO_WEIGHTS`](#burns.moves.AUTO_WEIGHTS) and the order
[`choose_move()`](#burns.moves.choose_move) draws from. Retune any of them and an **unchanged** panel
renders differently.

A consumer that caches a render keyed on the panel alone would therefore
serve the old frames forever, or silently produce a cut that disagrees with
its siblings. Put this in the key. It is `nw.Transform.impl_version`’s
contract — *a lock, not a receipt*: bump it whenever the geometry changes for
an unchanged input, and leave it alone for a docstring or a new move name.

Deliberately **not** the package version: a burns release that touches only
the renderer must not invalidate anybody’s cut, and
`importlib.metadata.version("burns")` is unreliable here besides.

### burns.moves.choose_move(seed)

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

### burns.moves.move_kind(move)

How `move` is grouped: `"zoom"`, `"drift"`, `"static"`, `"select"`.

For a UI that wants a compass of directions separately from the rest, read
off the same table [`resolve_move()`](#burns.moves.resolve_move) dispatches on.

### Examples

```pycon
>>> move_kind("drift_left"), move_kind("hold"), move_kind("auto")
('drift', 'static', 'select')
>>> sorted(m for m in MOVES if move_kind(m) == 'drift')
['drift_down', 'drift_left', 'drift_right', 'drift_up']
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### burns.moves.resolve_move(move, , image, aspect, zoom=1.18, focus=None, seed=0, easing='ease-in-out', on_aspect_mismatch='raise', content_box=None)

Resolve an authored camera intent against `image` into a path.

* **Parameters:**
  * **move** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]) – a name from [`MOVES`](#burns.moves.MOVES), or an explicit
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
      that *saliency* found covering [`DIFFUSE_KEEP_AREA`](#burns.moves.DIFFUSE_KEEP_AREA) or more
      of the picture is only a centre hint and does not cap: on a
      detailed photograph it covers nearly everything, and capping on
      it made every zoom render the same ~1.07.
    * floored. `push_in` / `pull_out` inherit
      `content_aware_path`’s `min_zoom + 0.02` (about 1.07), so a
      barely-there 1.02 push renders as 1.07; `hold` has no such floor
      and honours 1.02 exactly. A drift is floored to whatever leaves
      [`DRIFT_MIN_ROOM`](#burns.moves.DRIFT_MIN_ROOM) of travel.
  * **focus** ([`Any`](https://docs.python.org/3/library/typing.html#typing.Any)) – an explicit keep-region overriding the saliency estimate. A
    [`Rect`](burns.rect.html.md#burns.rect.Rect), a normalized `(x, y, w, h)` tuple, or
    any object with `.x/.y/.w/.h`. When given,
    [`salient_box()`](burns.content.html.md#burns.content.salient_box) is not called at all.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – chooses which move `"auto"` becomes, and nothing else. Mint it
    once per panel and store it; never derive it from a position, which
    is the defect this parameter exists to remove.
  * **easing** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – CSS timing function or callable. A callable is fine here but
    cannot be serialized — see `BurnsPath.to_dict()`. Applies to a
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
  [**MoveError**](#burns.moves.MoveError) – an unknown move name, a malformed `focus`, a non-positive
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
