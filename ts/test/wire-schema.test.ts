/**
 * The wire contract: the zod `valueSchema`, the committed JSON Schema generated
 * from it, and the Python golden vectors must all agree.
 *
 *   - every path in `tests/golden/vectors.json` (authored by Python) validates,
 *     bar the known drift tracked in burns#27;
 *   - a one-keyframe path is valid, an empty one is not (burns#19);
 *   - `ts/schemas/*.json` equals what `pnpm schema` would emit now, so editing
 *     the zod source without regenerating fails here instead of drifting.
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { z } from 'zod';

import { configSchema, valueSchema } from '../src/component/schema.js';

const here = dirname(fileURLToPath(import.meta.url));
const read = (...parts: string[]) => readFileSync(resolve(here, '..', '..', ...parts), 'utf8');
const golden = JSON.parse(read('tests', 'golden', 'vectors.json')) as {
  evaluate: { name: string; path: unknown }[];
};

describe('wire schema', () => {
  // clamp_ride_the_wall is out-of-image on purpose; zod rejects it today (burns#27).
  const KNOWN_DRIFT = new Set(['clamp_ride_the_wall']);

  it.each(
    golden.evaluate.filter((v) => !KNOWN_DRIFT.has(v.name)).map((v) => [v.name, v.path] as const),
  )(
    'accepts the Python-authored golden path %s',
    (_name, path) => {
      expect(() => valueSchema.parse(path)).not.toThrow();
    },
  );

  it('accepts a one-keyframe path and rejects an empty one', () => {
    const rect = { x: 0.1, y: 0.1, w: 0.5, h: 0.5 };
    const doc = { version: 1, interp: 'linear', easing: 'linear', output_aspect: null };
    expect(() => valueSchema.parse({ ...doc, keyframes: [{ t: 0, rect }] })).not.toThrow();
    expect(() => valueSchema.parse({ ...doc, keyframes: [] })).toThrow();
  });

  it.each([
    ['burns-path', valueSchema, 'BurnsPath (path-entry component output)'],
    ['path-entry-config', configSchema, 'Ken Burns path-entry component config'],
  ] as const)('committed %s.schema.json is up to date with the zod source', (name, schema, title) => {
    const json = z.toJSONSchema(schema, { target: 'draft-2020-12' });
    const expected = { $schema: 'https://json-schema.org/draft/2020-12/schema', title, ...json };
    expect(JSON.parse(read('ts', 'schemas', `${name}.schema.json`))).toEqual(expected);
  });
});
