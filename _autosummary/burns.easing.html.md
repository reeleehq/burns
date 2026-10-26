# burns.easing

Timing functions (easing) for Ken Burns motion.

Easing maps normalized clock time `t in [0, 1]` to normalized progress
`[0, 1]`. It is composed *over* the geometry: a path’s viewport at clock
time `t` is `path.evaluate_geometry(easing(t))` — the After-Effects split
of *what shape the motion traces* (the path) from *how fast it moves along it*
(the timing). Keeping them orthogonal is the single most useful design lesson
from the NLE prior art.

The public currency is the **CSS timing-function string** — `"linear"`,
`"ease"`, `"ease-in"`, `"ease-out"`, `"ease-in-out"`, or an explicit
`"cubic-bezier(x1, y1, x2, y2)"` — because that vocabulary is understood
verbatim by CSS, Remotion’s `Easing.bezier`, and GSAP’s `CustomEase` alike.
The cinematic default is `"ease-in-out"` (Final Cut Pro’s Ken Burns default),
**not** linear.

[`parse_easing()`](#burns.easing.parse_easing) also accepts a 4-tuple of bezier control values or any
callable `float -> float`, so power users can inject an arbitrary curve.

### Functions

| [`cubic_bezier`](#burns.easing.cubic_bezier)(x1, y1, x2, y2)   | A CSS-style cubic-bezier easing `f: [0, 1] -> [0, 1]`.      |
|---------------------------------------------------------------------------------|-------------------------------------------------------------|
| [`parse_easing`](#burns.easing.parse_easing)([spec])           | Resolve an easing spec to a callable `f: [0, 1] -> [0, 1]`. |

### burns.easing.cubic_bezier(x1, y1, x2, y2)

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

### burns.easing.parse_easing(spec='ease-in-out')

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
