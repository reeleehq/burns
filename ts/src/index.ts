/**
 * kenburnz — a TypeScript port of the `burns` Ken Burns motion spec.
 *
 * The same render-agnostic spec that drives the Python renderer: a pure,
 * time-parameterized `BurnsPath.evaluate(t) -> Rect`, the cover-crop pixel
 * geometry (`sampleBox`), plus a WebCodecs exporter and a zero-cost CSS preview
 * for the browser. Conformance with Python is pinned by the shared golden
 * vectors (`tests/golden/vectors.json`).
 */

export { Rect, type PixelBox } from './rect.js';
export {
  CSS_BEZIERS,
  DFLT_EASING,
  cubicBezier,
  parseEasing,
  type EasingFn,
  type EasingLike,
} from './easing.js';
export {
  BurnsPath,
  kenBurnsPath,
  SPEC_VERSION,
  windowAspect,
  type BurnsPathDict,
  type BurnsPathOptions,
  type ImageAspect,
  type Keyframe,
  type Style,
} from './path.js';
export {
  coverCropBox,
  even,
  outputSizeFor,
  sampleBox,
} from './frame.js';
export {
  cssTransformForRect,
  cssPreviewAt,
  type CssPreview,
} from './css-preview.js';
export {
  exportWebCodecsVideo,
  isWebCodecsSupported,
  type WebCodecsExportOptions,
  type WebCodecsExportResult,
} from './render-webcodecs.js';
export {
  createWebmMuxer,
  exportWebmBlob,
  type WebmMuxer,
  type WebmExportOptions,
  type WebmExportResult,
} from './mux-webm.js';
