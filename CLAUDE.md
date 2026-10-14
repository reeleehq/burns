# burns: notes for agents working in this repo

`burns` turns a still image (or a sequence of stills) into a Ken Burns pan/zoom film. A render-agnostic motion spec (a normalised crop rectangle moving along a path, plus named camera moves) drives two renderers: Python here (`burns/`, with a `pillow` and an `ffmpeg` backend) and TypeScript in `ts/` (`kenburnz`). Start with `README.md` and the skill in `.claude/skills/burns/SKILL.md`.

## Part of the `an` framework

burns is part of the `an` structured-animation framework (https://github.com/thorwhalen/an) and stays its own package. The direction and the open question on where the shared vocabulary lives are in https://github.com/thorwhalen/an/issues/257; the easing curves are the CSS entries of `an`'s easing contract (#23: the TypeScript port reads them from the npm package `@thorwhalen/an-contract`, and both languages' tests assert the contract's sample values), and this repo's open issue is #24 (a state-driven Engine for `an` shots, and shared camera moves). In short:

- A camera move is a move of a view through a parameter space. burns realises it as a **crop over pixels**: `push_in` shrinks the crop, so resolution is lost. `an`'s stage engine instead re-renders the scene into the rectangle (a zoom with no resolution loss), and `previz` (https://github.com/thorwhalen/previz, TypeScript) moves an n-dimensional parameter vector (an orbit camera, a chart's axis domain). Same names, same meaning, per-engine lowering.
- burns' eight camera moves are meant to become entries in `an`'s vocabulary, next to `an`'s nine, in one table. Until that table exists, a change to a move's name or magnitude here should be checked against `an`'s moves (`push_in` exists in both, with different magnitudes today).
- burns is to register as a state-driven Engine for `an` shots (state = a crop rectangle over a still or a video); the adapter lives here and registers itself, `an`'s core never imports burns.
- Python and JavaScript bridge: `jy` (https://github.com/i2mint/jy, JavaScript called from Python); the JavaScript-to-Python direction is still to be named.
- Design background: `misc/docs/core_from_three_genres.md` in the `an` repo (§2.6, camera).

## Repo rules

- Never hard-wrap Markdown prose: one line per paragraph or list item.
- No absolute local paths, hostnames or secrets in any committed file.
