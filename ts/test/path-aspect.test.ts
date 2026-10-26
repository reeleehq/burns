/** `windowAspect` — the port of `burns.path.window_aspect` (burns#30/#34). */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { BurnsPath, windowAspect } from '../src/path.js';

afterEach(() => vi.restoreAllMocks());

describe('windowAspect', () => {
  it('is the full frame when the shapes match', () => {
    expect(windowAspect(16 / 9, 16 / 9)).toBe(1);
  });

  it('is outputAspect / imageAspect', () => {
    expect(windowAspect(16 / 9, 4 / 3)).toBeCloseTo(4 / 3, 12);
  });

  it('accepts the image size, width first', () => {
    expect(windowAspect(16 / 9, [1600, 1200])).toBeCloseTo(windowAspect(16 / 9, 4 / 3), 12);
    expect(windowAspect(16 / 9, [1200, 1600])).not.toBeCloseTo(windowAspect(16 / 9, 4 / 3), 6);
  });

  it('is 1 without an outputAspect', () => {
    expect(windowAspect(null, 4 / 3)).toBe(1);
  });

  it.each([0, -1, Number.NaN, Infinity])('refuses a bad aspect %s', (bad) => {
    expect(() => windowAspect(bad, 1)).toThrow(/Aspect/);
    expect(() => windowAspect(16 / 9, bad)).toThrow(/Aspect/);
  });

  it.each([[[1600, 0]], [[-1600, -1200]], [[1, 2, 3]], [[1600]]])(
    'refuses a bad size %j',
    (bad) => {
      expect(() => windowAspect(16 / 9, bad as unknown as [number, number])).toThrow(
        /width, height/,
      );
    },
  );

  it('warns about the square-source assumption (once) when imageAspect is omitted', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    BurnsPath.pushIn({ outputAspect: 16 / 9 });
    BurnsPath.pushIn({ outputAspect: 16 / 9 });
    expect(warn.mock.calls.length).toBeLessThanOrEqual(1);
  });
});
