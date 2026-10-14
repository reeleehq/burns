/**
 * Timing functions (easing) for Ken Burns motion — a port of `burns.easing`.
 *
 * Easing maps clock time `t in [0, 1]` to progress `[0, 1]` and is composed
 * *over* the geometry: `evaluate(t) === geometry(easing(t))`. The public
 * currency is the **CSS timing-function string** (`"linear"`, `"ease"`,
 * `"ease-in"`, `"ease-out"`, `"ease-in-out"`, or `"cubic-bezier(x1,y1,x2,y2)"`),
 * understood verbatim by CSS, Remotion, and GSAP. The cinematic default is
 * `"ease-in-out"`.
 *
 * The named curves are not defined here: they are the CSS entries of `an`'s
 * shared easing contract (`@thorwhalen/an-contract`, `easing.json`), its
 * `css_hyphenated_curves` plus its `css_import_aliases` (CSS `ease`), bundled
 * at build time. `test/an-contract.test.ts` asserts the curves against the
 * contract's sample values.
 *
 * The cubic-bezier solver uses the **same 60-iteration bisection** as the
 * Python reference, so the eased values are reproducible to ~2^-60 and the
 * golden vectors match across languages.
 */

import {
  css_hyphenated_curves as CONTRACT_CSS_CURVES,
  css_import_aliases as CONTRACT_CSS_ALIASES,
} from '@thorwhalen/an-contract/easing.json';

export type EasingFn = (t: number) => number;
export type EasingLike =
  | string
  | EasingFn
  | readonly [number, number, number, number];

type Bezier = [number, number, number, number];

function asBezier(points: readonly number[]): Bezier {
  if (points.length !== 4) {
    throw new Error(`easing contract: expected 4 control values, got ${points}`);
  }
  return [...points] as Bezier;
}

/**
 * CSS cubic-bezier control points by name: `linear`, plus every CSS curve of
 * `an`'s easing contract (`ease-in`, `ease-out`, `ease-in-out`, and CSS `ease`
 * through the contract's import alias).
 */
export const CSS_BEZIERS: Record<string, Bezier> = {
  linear: [0, 0, 1, 1],
  ...Object.fromEntries(
    Object.entries(CONTRACT_CSS_ALIASES).map(([name, spec]) => [
      name,
      parseBezierArgs(spec),
    ]),
  ),
  ...Object.fromEntries(
    Object.entries(CONTRACT_CSS_CURVES).map(([name, points]) => [
      name,
      asBezier(points),
    ]),
  ),
};

export const DFLT_EASING = 'ease-in-out';

const BISECTION_ITERS = 60;

function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

/**
 * A CSS-style cubic-bezier easing `f: [0, 1] -> [0, 1]` from `(0,0)` to `(1,1)`
 * with control points `(x1, y1)` and `(x2, y2)`. Inverts `x(t)` by bisection,
 * then returns `y(t)`.
 */
export function cubicBezier(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): EasingFn {
  const bez = (t: number, a: number, b: number): number => {
    const u = 1 - t;
    return 3 * u * u * t * a + 3 * u * t * t * b + t * t * t;
  };

  const solveTForX = (x: number): number => {
    let lo = 0;
    let hi = 1;
    for (let i = 0; i < BISECTION_ITERS; i++) {
      const mid = (lo + hi) / 2;
      if (bez(mid, x1, x2) < x) lo = mid;
      else hi = mid;
    }
    return (lo + hi) / 2;
  };

  return (t: number): number => {
    t = clamp01(t);
    if (t === 0 || t === 1) return t;
    return bez(solveTForX(t), y1, y2);
  };
}

/**
 * Resolve an easing spec to a callable `f: [0, 1] -> [0, 1]`.
 *
 * Accepts a CSS name, a `cubic-bezier(...)` string, a 4-element tuple, or any
 * callable (returned unchanged).
 */
export function parseEasing(spec: EasingLike = DFLT_EASING): EasingFn {
  if (typeof spec === 'function') return spec;
  if (typeof spec === 'string') {
    const key = spec.trim().toLowerCase();
    if (key in CSS_BEZIERS) return cubicBezier(...CSS_BEZIERS[key]!);
    if (key.startsWith('cubic-bezier')) {
      return cubicBezier(...parseBezierArgs(spec));
    }
    throw new Error(
      `parseEasing: unknown easing ${JSON.stringify(spec)}. Use a CSS name ` +
        `(${Object.keys(CSS_BEZIERS).join(', ')}), a cubic-bezier(...) ` +
        `string, a 4-tuple, or a callable.`,
    );
  }
  if (Array.isArray(spec) && spec.length === 4) {
    return cubicBezier(...(spec.map(Number) as [number, number, number, number]));
  }
  throw new Error(
    `parseEasing: cannot interpret easing spec ${JSON.stringify(spec)}`,
  );
}

function parseBezierArgs(
  spec: string,
): [number, number, number, number] {
  const inside = spec.slice(spec.indexOf('(') + 1, spec.lastIndexOf(')'));
  const parts = inside.split(',').map((p) => p.trim());
  if (parts.length !== 4) {
    throw new Error(
      `parseEasing: cubic-bezier needs 4 values, got ${JSON.stringify(spec)}`,
    );
  }
  return parts.map(Number) as [number, number, number, number];
}
