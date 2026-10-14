/**
 * Easing conformance against `an`'s shared contract (`@thorwhalen/an-contract`,
 * `easing.json`; burns#23, an ADR 0006).
 *
 * burns' named easings ARE the contract's CSS curves (`src/easing.ts` reads
 * them from the package). This test pins the other half: that burns' solver
 * evaluates them to the contract's sample values. The contract's CSS solver
 * stops at |x(s) - t| < 1e-12 while burns bisects to ~2^-60, so the two agree
 * to a few 1e-12, never exactly; `TOLERANCE` leaves room for that and nothing
 * more.
 */

import { describe, expect, it } from 'vitest';
import contract from '@thorwhalen/an-contract/easing.json';
import { CSS_BEZIERS, parseEasing } from '../src/easing';

const TOLERANCE = 1e-11;

/** The contract entries burns serves: `linear` plus every CSS cubic-bezier. */
const served = contract.entries.filter(
  (e) => e.name in CSS_BEZIERS && (e.family === 'css' || e.name === 'linear'),
);

describe('easing curves come from the an contract', () => {
  it('serves every CSS cubic-bezier curve of the contract', () => {
    for (const [name, points] of Object.entries(contract.css_hyphenated_curves)) {
      expect(CSS_BEZIERS[name]).toEqual(points);
    }
  });

  it("reads CSS 'ease' through the contract's import alias", () => {
    expect(contract.css_import_aliases.ease).toBe('cubic-bezier(0.25, 0.1, 0.25, 1)');
    expect(CSS_BEZIERS.ease).toEqual([0.25, 0.1, 0.25, 1]);
  });

  it('checks at least linear and the three CSS curves', () => {
    expect(served.map((e) => e.name).sort()).toEqual(
      ['ease-in', 'ease-in-out', 'ease-out', 'linear'],
    );
  });

  for (const entry of served) {
    it(`${entry.name} matches the contract's samples`, () => {
      const ease = parseEasing(entry.name);
      contract.sample_u.forEach((u, i) => {
        expect(Math.abs(ease(u) - entry.samples[i]!)).toBeLessThan(TOLERANCE);
      });
    });
  }
});
