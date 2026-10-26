/**
 * Pure, DOM-free geometry for the path-entry component.
 *
 * Everything here operates on normalized `[0, 1]` image coordinates (the
 * spec's resolution-independent space) and reuses {@link Rect} from the core
 * for clamping and interpolation. The renderer converts pointer pixels to
 * normalized coordinates and back; the core never sees a pixel or a DOM node.
 *
 * ## The aspect-ratio lock
 *
 * The user draws crop windows shaped to the **output** video's aspect ratio,
 * over an image with its own (possibly different) aspect ratio. A box that
 * *looks* like a correct output-AR window on screen has, in normalized image
 * units, `w / h = outputAspect / imageAspect` — see {@link lockRatio}. Emitting
 * rects at that ratio with `output_aspect = outputAspect` makes the downstream
 * cover-crop (`coverCropBox`) a no-op, so the rendered window is exactly the
 * one the user drew.
 */

import { Rect } from '../rect.js';
import type { AspectRatio, RectData } from './schema.js';
import { windowAspect } from '../path.js';

/** The image's pixel aspect ratio `width / height`. */
export function imageAspectOf(width: number, height: number): number {
  return width / height;
}

/** The output aspect ratio as a single number `num / den`. */
export function aspectValue(ar: AspectRatio): number {
  return ar.num / ar.den;
}

/**
 * The normalized `w / h` lock ratio for crop rects: `outputAspect / imageAspect`.
 *
 * A rect built at this ratio renders (after cover-crop) as the exact window the
 * user framed, because its *pixel* aspect equals the output aspect.
 */
export function lockRatio(outputAspect: AspectRatio, imageAspect: number): number {
  return windowAspect(aspectValue(outputAspect), imageAspect);
}

/** Reduce a `num / den` ratio to lowest terms (for display, e.g. `16:9`). */
export function simplifyRatio(num: number, den: number): AspectRatio {
  const a = Math.round(num);
  const b = Math.round(den);
  const g = gcd(Math.abs(a), Math.abs(b)) || 1;
  return { num: a / g, den: b / g };
}

function gcd(a: number, b: number): number {
  while (b) {
    [a, b] = [b, a % b];
  }
  return a;
}

/** Convert a {@link Rect} to plain {@link RectData}. */
export function toRectData(r: Rect): RectData {
  return { x: r.x, y: r.y, w: r.w, h: r.h };
}

/** Convert plain {@link RectData} to a {@link Rect}. */
export function toRect(r: RectData): Rect {
  return new Rect(r.x, r.y, r.w, r.h);
}

/**
 * The largest AR-locked rect (normalized `w / h = ratio`) that fits inside the
 * image, centered. The "fully zoomed out" cap — the user cannot zoom out past
 * this (the containment constraint, spec §4.3).
 */
export function maxContainedRect(ratio: number): Rect {
  let w: number;
  let h: number;
  if (ratio >= 1) {
    w = 1;
    h = 1 / ratio;
  } else {
    h = 1;
    w = ratio;
  }
  return new Rect((1 - w) / 2, (1 - h) / 2, w, h);
}

/**
 * An AR-locked rect scaled to `1 / zoom` of {@link maxContainedRect}, centered
 * at `(cx, cy)`, then clamped inside the image. `zoom = 1` ⇒ fully zoomed out;
 * `zoom > 1` ⇒ tighter window.
 */
export function scaledContainedRect(
  ratio: number,
  zoom: number,
  cx = 0.5,
  cy = 0.5,
): Rect {
  if (zoom <= 0) {
    throw new Error(`scaledContainedRect: zoom must be > 0, got ${zoom}`);
  }
  const full = maxContainedRect(ratio);
  const w = full.w / zoom;
  const h = full.h / zoom;
  return new Rect(cx - w / 2, cy - h / 2, w, h).clamped();
}

/**
 * Build an AR-locked rect from a freehand drag: a box with one corner at
 * `anchor` growing toward `pointer`, its size taken from the dominant drag
 * extent so the rect tracks the pointer naturally, then clamped.
 *
 * Used to *create* a rect (click-drag on empty canvas) and to *resize* one
 * (drag a corner handle, with `anchor` = the opposite corner).
 */
export function rectFromDrag(
  anchor: { x: number; y: number },
  pointer: { x: number; y: number },
  ratio: number,
): Rect {
  const dx = Math.abs(pointer.x - anchor.x);
  const dy = Math.abs(pointer.y - anchor.y);
  // Size from whichever axis the pointer pulled further (relative to the AR),
  // so a mostly-horizontal drag grows width-first and vice-versa.
  let w: number;
  let h: number;
  if (dx / ratio >= dy) {
    w = dx;
    h = w / ratio;
  } else {
    h = dy;
    w = h * ratio;
  }
  const x = pointer.x >= anchor.x ? anchor.x : anchor.x - w;
  const y = pointer.y >= anchor.y ? anchor.y : anchor.y - h;
  return new Rect(x, y, w, h).clamped();
}

/** Translate a rect by `(dx, dy)` normalized units, then clamp (pan). */
export function translateRect(r: RectData, dx: number, dy: number): Rect {
  return new Rect(r.x + dx, r.y + dy, r.w, r.h).clamped();
}

/**
 * Scale a rect about its own center by `factor` (`> 1` grows, `< 1` shrinks),
 * preserving its aspect ratio, then clamp. The handle-drag fallback and the
 * zoom slider both route through here.
 */
export function scaleRect(r: RectData, factor: number): Rect {
  if (factor <= 0) {
    throw new Error(`scaleRect: factor must be > 0, got ${factor}`);
  }
  const cx = r.x + r.w / 2;
  const cy = r.y + r.h / 2;
  const w = r.w * factor;
  const h = r.h * factor;
  return new Rect(cx - w / 2, cy - h / 2, w, h).clamped();
}

/**
 * The human-legible readout for a rect (spec §4.3): percent position and a
 * window-fraction zoom (`1 / max(w, h)`, what every NLE shows — not pixel
 * magnification).
 */
export interface RectReadout {
  xPercent: number;
  yPercent: number;
  widthPercent: number;
  heightPercent: number;
  zoom: number;
}

export function rectReadout(r: RectData): RectReadout {
  return {
    xPercent: r.x * 100,
    yPercent: r.y * 100,
    widthPercent: r.w * 100,
    heightPercent: r.h * 100,
    zoom: 1 / Math.max(r.w, r.h),
  };
}
