/**
 * Schema-first contract for the Ken Burns path-entry component.
 *
 * Three zod schemas describe the whole component surface, per the spec
 * (`misc/docs/ken_burns_path_entry_component_spec.md` §2):
 *
 * - {@link configSchema} — the host-provided configuration (image, target
 *   aspect, duration/easing editability, presets, layout).
 * - {@link valueSchema} — the emitted `BurnsPath` wire format. This is the
 *   single point of contact with any rendering backend and the one schema
 *   exported to JSON Schema (`scripts/export-json-schema.mjs`) for non-TS
 *   consumers. It is the architecture doc's wire shape — snake_case,
 *   `output_aspect: number | null`, the same shape `BurnsPath.toDict()`
 *   emits — extended with two **optional, additive** fields the UI authors:
 *   `duration_ms` and `meta`. Core fields are byte-compatible with the
 *   Python golden-vector contract; the additive fields are ignored by
 *   `evaluate` and by renderers that don't need them.
 * - {@link stateSchema} — the component's internal authoring state, the
 *   thing the pure reducer in `machine.ts` transforms.
 *
 * Only containment (`0 ≤ x, y` and `x + w ≤ 1`, `y + h ≤ 1`) is validated on
 * rects — **not** `w / h == output_aspect`. The wire format does not pin that
 * invariant (the golden vectors carry square rects with `output_aspect: null`;
 * the output aspect is applied downstream by `coverCropBox`). The path-entry
 * UI happens to lock its rects to the output pixel aspect, but the schema does
 * not require every producer to.
 */

import { z } from 'zod';

/** Floating-point slack for the containment invariant (matches `rect.ts`). */
export const EPS = 1e-6;

// --- shared atoms ----------------------------------------------------------

/** A normalized rectangle `(x, y, w, h)`, each a fraction of the image. */
export const rectSchema = z.object({
  x: z.number(),
  y: z.number(),
  w: z.number().positive(),
  h: z.number().positive(),
});
export type RectData = z.infer<typeof rectSchema>;

/** An exact aspect ratio as an integer-ish `num / den` pair. */
export const aspectRatioSchema = z.object({
  num: z.number().positive(),
  den: z.number().positive(),
});
export type AspectRatio = z.infer<typeof aspectRatioSchema>;

/**
 * A CSS-compatible easing identifier (`"linear"`, `"ease-in-out"`,
 * `"cubic-bezier(...)"`) or a 4-number control-point tuple. The cross-ecosystem
 * lingua franca (CSS, Remotion, GSAP).
 */
export const easingSchema = z.union([
  z.string(),
  z.tuple([z.number(), z.number(), z.number(), z.number()]),
]);
export type EasingId = z.infer<typeof easingSchema>;

/** True when the rect lies wholly inside the image (within {@link EPS}). */
function rectContained(r: RectData): boolean {
  return (
    r.x >= -EPS &&
    r.y >= -EPS &&
    r.x + r.w <= 1 + EPS &&
    r.y + r.h <= 1 + EPS
  );
}

// --- Value (the emitted BurnsPath wire format) -----------------------------

/** A single keyframe: a normalized time paired with the viewport rect there. */
export const keyframeSchema = z.object({
  t: z.number().min(0).max(1),
  rect: rectSchema,
});
export type KeyframeData = z.infer<typeof keyframeSchema>;

/**
 * Advisory round-trip metadata. Lets the same UI re-open an emitted spec in
 * preset mode for further editing without losing intent. Renderers ignore it.
 */
export const valueMetaSchema = z.object({
  /** The preset the user authored with (`"custom"` for free-drawn). */
  preset_id: z.string().optional(),
  /** Preset parameter values (e.g. `{ zoomFactor: 1.3 }`). */
  preset_params: z.record(z.string(), z.number()).optional(),
  /** The exact `num/den` the user entered, preserved for display + round-trip. */
  output_aspect_ratio: aspectRatioSchema.optional(),
});
export type ValueMeta = z.infer<typeof valueMetaSchema>;

/**
 * The emitted `BurnsPath` JSON — the wire format and the component's only
 * output. Core fields mirror `BurnsPath.toDict()` (Python parity); `duration_ms`
 * and `meta` are additive and optional.
 */
export const valueSchema = z
  .object({
    version: z.literal(1),
    keyframes: z.array(keyframeSchema).min(1),
    interp: z.literal('linear'),
    easing: easingSchema,
    output_aspect: z.number().positive().nullable(),
    duration_ms: z.number().positive().optional(),
    meta: valueMetaSchema.optional(),
  })
  .superRefine((val, ctx) => {
    const { keyframes } = val;
    for (let i = 1; i < keyframes.length; i++) {
      if (keyframes[i]!.t <= keyframes[i - 1]!.t) {
        ctx.addIssue({
          code: 'custom',
          message: 'keyframe times must strictly increase',
          path: ['keyframes', i, 't'],
        });
      }
    }
    keyframes.forEach((kf, i) => {
      if (!rectContained(kf.rect)) {
        ctx.addIssue({
          code: 'custom',
          message: `keyframe ${i} rect violates containment (0 ≤ x,y; x+w ≤ 1; y+h ≤ 1)`,
          path: ['keyframes', i, 'rect'],
        });
      }
    });
  });
export type Value = z.infer<typeof valueSchema>;

// --- Config (host-provided) ------------------------------------------------

/** The image to author over. Pixel dims are the SSOT for aspect + readouts. */
export const imageConfigSchema = z.object({
  src: z.string(),
  width: z.number().positive(),
  height: z.number().positive(),
});
export type ImageConfig = z.infer<typeof imageConfigSchema>;

/**
 * The output video's aspect ratio.
 * - `{ num, den, locked }` — explicit; `locked: true` hides the AR editor.
 * - `"match-image"` — set from the image's pixel dimensions on mount.
 * - omitted — the user picks.
 */
export const targetAspectConfigSchema = z.union([
  z.object({
    num: z.number().positive(),
    den: z.number().positive(),
    locked: z.boolean(),
  }),
  z.literal('match-image'),
]);
export type TargetAspectConfig = z.infer<typeof targetAspectConfigSchema>;

export const durationConfigSchema = z.object({
  defaultMs: z.number().positive(),
  minMs: z.number().positive().optional(),
  maxMs: z.number().positive().optional(),
  editable: z.boolean(),
});
export type DurationConfig = z.infer<typeof durationConfigSchema>;

export const easingConfigSchema = z.object({
  default: easingSchema,
  editable: z.boolean(),
  options: z.array(easingSchema).optional(),
});
export type EasingConfig = z.infer<typeof easingConfigSchema>;

export const dualViewSchema = z.enum(['side-by-side', 'overlay', 'tabbed']);
export type DualView = z.infer<typeof dualViewSchema>;

/**
 * The host-facing contract. Stable across renderer changes. `presets` is
 * validated loosely here (`"default"` or a list of preset ids); full
 * {@link Preset} objects with `derive` functions are passed programmatically
 * and resolved by the machine (see `presets.ts`).
 */
export const configSchema = z.object({
  image: imageConfigSchema,
  targetAspect: targetAspectConfigSchema.optional(),
  duration: durationConfigSchema.optional(),
  easing: easingConfigSchema.optional(),
  presets: z.union([z.literal('default'), z.array(z.string())]).optional(),
  allowCustom: z.boolean().optional(),
  dualView: dualViewSchema.optional(),
  i18n: z.record(z.string(), z.string()).optional(),
  theme: z.unknown().optional(),
});
export type ConfigInput = z.infer<typeof configSchema>;

// --- State (internal authoring state) --------------------------------------

/**
 * The component's internal authoring state — the value the pure reducer
 * transforms. Holds raw authoring inputs only; the derived `(start, end)`
 * rects and the emitted {@link Value} are computed by selectors, never stored.
 */
export const stateSchema = z.object({
  image: imageConfigSchema,
  /** The resolved output aspect ratio (always concrete once the state exists). */
  outputAspect: aspectRatioSchema,
  /** Whether the AR control is offered (false ⇒ locked / hidden). */
  aspectEditable: z.boolean(),
  /** Active preset id; `"custom"` for free-drawn start/end. */
  presetId: z.string(),
  /** Current preset parameter values. */
  presetParams: z.record(z.string(), z.number()),
  /**
   * User-drawn rects. Length matches the active preset's arity:
   * 0 ⇒ empty, 1 ⇒ `[userRect]`, 2 (custom) ⇒ `[startRect, endRect]`.
   */
  rects: z.array(rectSchema),
  durationMs: z.number().positive(),
  durationEditable: z.boolean(),
  easing: easingSchema,
  easingEditable: z.boolean(),
  /** Whether Start and End are swapped on emit (the Reverse/Swap toggle). */
  reversed: z.boolean(),
});
export type State = z.infer<typeof stateSchema>;
