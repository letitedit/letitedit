// letitedit: the small part of shared.ts the geometry hands re-export, so a hand's import line stays short.
export { Hand, register, smoothStep } from "./shared";
export const clamp01 = (v: number) => (v <= 0 ? 0 : v >= 1 ? 1 : v);
