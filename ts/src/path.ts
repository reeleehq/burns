/**
 * The render-agnostic Ken Burns motion spec: {@link BurnsPath} — a port of
 * `burns.path`.
 *
 * A `BurnsPath` is the single source of truth for *how the virtual camera moves
 * over a still image* — pure data, no image, no encoder, no frame count. Its one
 * job is {@link BurnsPath.evaluate}: a normalized clock time `t in [0, 1]` maps
 * to the {@link Rect} viewport at that instant. Easing is composed over the
 * geometry (`evaluate(t) === geometry(easing(t))`); `outputAspect` is render
 * metadata that `evaluate` never reads (the constructors do, with `imageAspect`).
 *
 * {@link BurnsPath.toDict} / {@link BurnsPath.fromDict} are the JSON wire format
 * shared with Python — identical key names and shape — so a path serialized by
 * either language rebuilds in the other. The golden vectors store every path via
 * this format.
 */

import { Rect } from './rect.js';
import {
  DFLT_EASING,
  parseEasing,
  type EasingFn,
  type EasingLike,
} from './easing.js';
import { roundTo } from './_round.js';

/** A keyframe: a normalized time in `[0, 1]` paired with the viewport there. */
export type Keyframe = readonly [number, Rect];

export const SPEC_VERSION = 1;

const VALID_STYLES = ['push', 'drift'] as const;
export type Style = (typeof VALID_STYLES)[number];

/** The JSON wire shape (mirrors Python `BurnsPath.to_dict`). */
export interface BurnsPathDict {
  version: number;
  keyframes: { t: number; rect: { x: number; y: number; w: number; h: number } }[];
  interp: string;
  easing: string | number[];
  output_aspect: number | null;
}

export interface BurnsPathOptions {
  easing?: EasingLike;
  interp?: string;
  outputAspect?: number | null;
  version?: number;
}

/** A source's shape: its `width / height`, or its `[width, height]` size. */
export type ImageAspect = number | readonly [number, number];

let warnedLegacyAspect = false;

/**
 * The `w / h` a rect needs, in image-normalised units, to show `outputAspect`
 * (port of `burns.path.window_aspect`). A rect's sides are fractions of the
 * image's own, so a 16:9 window over a 16:9 image is the square `w == h == 1`;
 * the ratio is `outputAspect / imageAspect`.
 *
 * Without `imageAspect` the source is treated as square (the original
 * behaviour; only right for a square source) and a warning is logged once.
 */
export function windowAspect(
  outputAspect: number | null,
  imageAspect: ImageAspect | null = null,
): number {
  let image: number | null = null;
  if (imageAspect !== null) {
    if (typeof imageAspect !== 'number') {
      const [w, h] = imageAspect;
      if (imageAspect.length !== 2 || !(w > 0 && h > 0) || typeof w !== 'number' || typeof h !== 'number') {
        throw new Error(
          `imageAspect size must be (width, height) with both > 0, got ${JSON.stringify(imageAspect)}`,
        );
      }
      image = w / h;
    } else {
      image = imageAspect;
    }
  }
  for (const [name, value] of [
    ['outputAspect', outputAspect],
    ['imageAspect', image],
  ] as const) {
    if (value !== null && !(value > 0 && Number.isFinite(value))) {
      throw new Error(`${name} must be a positive finite number, got ${value}`);
    }
  }
  if (outputAspect === null) return 1;
  if (image === null) {
    if (!warnedLegacyAspect) {
      warnedLegacyAspect = true;
      console.warn(
        'burns: outputAspect without imageAspect treats the source as square, so a ' +
          'non-square image is cropped at zoom 1.0 (burns#30). Pass imageAspect = ' +
          'width / height; omitting it will become an error.',
      );
    }
    return outputAspect;
  }
  return outputAspect / image;
}

export class BurnsPath {
  readonly keyframes: readonly Keyframe[];
  readonly easing: EasingLike;
  readonly interp: string;
  readonly outputAspect: number | null;
  readonly version: number;
  private readonly _ease: EasingFn;

  constructor(keyframes: readonly Keyframe[], options: BurnsPathOptions = {}) {
    const {
      easing = DFLT_EASING,
      interp = 'linear',
      outputAspect = null,
      version = SPEC_VERSION,
    } = options;

    const kfs: Keyframe[] = keyframes.map(([t, r]) => [Number(t), r]);
    if (kfs.length === 0) {
      throw new Error('BurnsPath: keyframes must be non-empty');
    }
    const times = kfs.map(([t]) => t);
    for (let i = 1; i < times.length; i++) {
      if (times[i]! <= times[i - 1]!) {
        throw new Error(
          `BurnsPath: keyframe times must strictly increase, got ${JSON.stringify(times)}`,
        );
      }
    }
    if (times[0]! < 0 || times[times.length - 1]! > 1) {
      throw new Error(
        `BurnsPath: keyframe times must lie in [0, 1], got ${JSON.stringify(times)}`,
      );
    }
    if (interp !== 'linear') {
      throw new Error(
        `BurnsPath: only interp='linear' is implemented, got ${JSON.stringify(interp)}`,
      );
    }

    this.keyframes = kfs;
    this.easing = easing;
    this.interp = interp;
    this.outputAspect = outputAspect;
    this.version = version;
    this._ease = parseEasing(easing);
  }

  /** Number of keyframe waypoints (`2` for the canonical Start/End). */
  get durationKeyframes(): number {
    return this.keyframes.length;
  }

  /**
   * The viewport {@link Rect} at normalized clock time `t in [0, 1]`.
   *
   * Applies easing to the clock, then linearly interpolates geometry at the
   * eased progress. Pure and deterministic. `t` outside `[0, 1]` clamps to the
   * nearest end.
   */
  evaluate(t: number): Rect {
    const u = this._ease(t);
    const kfs = this.keyframes;
    if (u <= kfs[0]![0]) return kfs[0]![1];
    if (u >= kfs[kfs.length - 1]![0]) return kfs[kfs.length - 1]![1];
    for (let i = 0; i < kfs.length - 1; i++) {
      const [t0, r0] = kfs[i]!;
      const [t1, r1] = kfs[i + 1]!;
      if (t0 <= u && u <= t1) {
        const local = t1 > t0 ? (u - t0) / (t1 - t0) : 0;
        return r0.lerp(r1, local);
      }
    }
    return kfs[kfs.length - 1]![1];
  }

  /** Swap start and end (mirror keyframe times about `0.5`, re-sort). */
  reversed(): BurnsPath {
    const flipped = this.keyframes
      .map(([t, r]) => [1 - t, r] as Keyframe)
      .sort((a, b) => a[0] - b[0]);
    return new BurnsPath(flipped, {
      easing: this.easing,
      interp: this.interp,
      outputAspect: this.outputAspect,
      version: this.version,
    });
  }

  /** Serialize to the versioned JSON wire format (the cross-language SSOT). */
  toDict(): BurnsPathDict {
    if (typeof this.easing === 'function') {
      throw new Error(
        'BurnsPath.toDict: a callable easing is not serializable; use a CSS ' +
          'easing string/tuple for paths that cross the wire.',
      );
    }
    const easing = Array.isArray(this.easing)
      ? [...this.easing]
      : (this.easing as string);
    return {
      version: this.version,
      keyframes: this.keyframes.map(([t, r]) => ({
        t,
        rect: { x: r.x, y: r.y, w: r.w, h: r.h },
      })),
      interp: this.interp,
      easing,
      output_aspect: this.outputAspect,
    };
  }

  /** Rebuild a {@link BurnsPath} from {@link toDict} output (or Python's). */
  static fromDict(d: BurnsPathDict): BurnsPath {
    const keyframes: Keyframe[] = d.keyframes.map((kf) => [
      kf.t,
      new Rect(kf.rect.x, kf.rect.y, kf.rect.w, kf.rect.h),
    ]);
    const easing = (d.easing ?? DFLT_EASING) as EasingLike;
    return new BurnsPath(keyframes, {
      easing: Array.isArray(easing)
        ? (easing as unknown as readonly [number, number, number, number])
        : easing,
      interp: d.interp ?? 'linear',
      outputAspect: d.output_aspect ?? null,
      version: d.version ?? SPEC_VERSION,
    });
  }

  /** The canonical two-rectangle Ken Burns case (Start frame -> End frame). */
  static fromStartEnd(
    start: Rect,
    end: Rect,
    {
      easing = DFLT_EASING,
      outputAspect = null,
    }: { easing?: EasingLike; outputAspect?: number | null } = {},
  ): BurnsPath {
    return new BurnsPath(
      [
        [0, start],
        [1, end],
      ],
      { easing, outputAspect },
    );
  }

  /**
   * A slow push from the full image toward `to` at `zoom` (the 90% case).
   * Pass `imageAspect` (the source's width/height) whenever `outputAspect` is set.
   */
  static pushIn({
    zoom = 1.3,
    to = [0.5, 0.5],
    easing = DFLT_EASING,
    outputAspect = null,
    imageAspect = null,
  }: {
    zoom?: number;
    to?: readonly [number, number];
    easing?: EasingLike;
    outputAspect?: number | null;
    imageAspect?: ImageAspect | null;
  } = {}): BurnsPath {
    const [cx, cy] = to;
    const aspect = windowAspect(outputAspect, imageAspect);
    const start =
      outputAspect === null
        ? new Rect(0, 0, 1, 1)
        : Rect.fromCenterZoom(0.5, 0.5, 1, { aspect });
    return BurnsPath.fromStartEnd(
      start,
      Rect.fromCenterZoom(cx, cy, zoom, { aspect }),
      { easing, outputAspect },
    );
  }
}

/**
 * A deterministic {@link BurnsPath} for the `index`-th image of a sequence.
 *
 * `style="push"` (default): one slow zoom toward an off-center focal point;
 * **odd indices push in, even indices pull out**, focal direction rotating
 * through compass octants. `style="drift"`: pure horizontal pan at a constant
 * zoom, alternating direction per index (`zoom` ignored). Per-index
 * deterministic: identical args always return an identical path. Pass
 * `imageAspect` (the source's width/height) whenever `outputAspect` is set.
 */
export function kenBurnsPath(
  index: number,
  {
    style = 'push',
    zoom = 1.1,
    pan = 0.03,
    easing = DFLT_EASING,
    outputAspect = null,
    imageAspect = null,
  }: {
    style?: Style;
    zoom?: number;
    pan?: number;
    easing?: EasingLike;
    outputAspect?: number | null;
    imageAspect?: ImageAspect | null;
  } = {},
): BurnsPath {
  if (!VALID_STYLES.includes(style)) {
    throw new Error(
      `kenBurnsPath: style must be one of ${JSON.stringify(VALID_STYLES)}, got ${JSON.stringify(style)}`,
    );
  }
  const [start, end] = endpointsForStyle(style, index, {
    zoom,
    pan,
    aspect: windowAspect(outputAspect, imageAspect),
  });
  return BurnsPath.fromStartEnd(start, end, { easing, outputAspect });
}

function endpointsForStyle(
  style: Style,
  index: number,
  { zoom, pan, aspect }: { zoom: number; pan: number; aspect: number },
): [Rect, Rect] {
  if (style === 'push') {
    // Focal direction cycles through compass octants per index.
    const angle = (index * 2 + 1) * (Math.PI / 4);
    const offCx = roundTo(0.5 + pan * Math.cos(angle), 4);
    const offCy = roundTo(0.5 + pan * Math.sin(angle), 4);
    const full = Rect.fromCenterZoom(0.5, 0.5, 1, { aspect });
    const offset = Rect.fromCenterZoom(offCx, offCy, zoom, { aspect });
    return index % 2 === 1 ? [full, offset] : [offset, full];
  }
  // style === "drift": horizontal pan at a constant zoom.
  const direction = index % 2 === 1 ? 1 : -1;
  const half = Math.min(pan, 0.45);
  const startCx = roundTo(0.5 - direction * half, 4);
  const endCx = roundTo(0.5 + direction * half, 4);
  // A window narrower than the frame already spans only `aspect` of the width.
  const driftZoom = roundTo(Math.max(1, Math.min(1, aspect) / (1 - 2 * half)) + 0.05, 4);
  return [
    Rect.fromCenterZoom(startCx, 0.5, driftZoom, { aspect }),
    Rect.fromCenterZoom(endCx, 0.5, driftZoom, { aspect }),
  ];
}
