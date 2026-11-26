// From anidoodle (https://github.com/alexgreensh/anidoodle, commit 6ae8827), Copyright 2026 Alex Greenshpun, Apache-2.0: see written-music/LICENSE-anidoodle.txt.
// Changed for letitedit, 4 Nov 2026: anidoodle's core.ts is the drawing core; the music needs only this seeded random
// generator from it, so only this function is copied.
export const rng = (seed: number) => {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
};
