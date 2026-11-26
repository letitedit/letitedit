// letitedit's command line for music written as a score (bundled into written-music.mjs by build.mjs).
// Adapted from anidoodle's engine/tools/music.mjs (https://github.com/alexgreensh/anidoodle, commit 6ae8827),
// Copyright 2026 Alex Greenshpun, Apache-2.0: see LICENSE-anidoodle.txt. Changed for letitedit, 4 Nov 2026: a score is plain
// JSON (no TypeScript and no esbuild at run time); the report is JSON; no sound pack, no recorded rooms, no shell, no ffmpeg,
// no network; the master gets a fade on what rings after the last note; per-bar levels, the lead's times and a fingerprint
// of each part's notes are added to the report.
//
//   node written-music.mjs vocab [style]
//   node written-music.mjs craft <score.json>
//   node written-music.mjs report <score.json> [--seconds N] [--payoff S] [--fit] [--end-fade S] [--threads N] [--out out.wav]
//
// Writes one JSON object to stdout (vocab: text). A score that can't be read or composed: {"error": "..."}, exit code 2.
import { Worker, isMainThread, parentPort, workerData } from "node:worker_threads";
import { writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { availableParallelism } from "node:os";
import { fileURLToPath } from "node:url";
import * as M from "./engine/music/index";

const SR = 48000, STEM_SR = 24000;
const round = (x: number, d = 2) => (Number.isFinite(x) ? +x.toFixed(d) : null);
let THREADS = Math.max(1, Math.min(4, availableParallelism() - 1));

// ---------------------------------------------------------------- voices in parallel (as tools/music.mjs: the audio is bit-identical to a serial render)
const workerMain = () => {
  parentPort!.on("message", ({ id, job, task }: any) => {
    if (job) { const o: any = (M as any).runVoiceJob(job); parentPort!.postMessage({ id, o }, [...new Set([o.L.buffer, o.R.buffer, o.halo && o.halo.buffer].filter(Boolean))] as any); return; }
    const opts = { ...task.opts, cache: new Map(task.voices) };
    parentPort!.postMessage({ id, out: task.kind === "band" ? (M as any).roleBandDb(task.piece, task.sr, opts, task.spans) : (M as any).measureStems(task.piece, task.sr, opts) });
  });
  parentPort!.postMessage({ ready: true });
};
const pool = (msgs: any[], threads: number): Promise<Map<string, any>> => {
  const queue = msgs.slice(), out = new Map<string, any>();
  return Promise.all(Array.from({ length: Math.min(threads, msgs.length) }, () => new Promise<void>((ok, fail) => {
    const w = new Worker(fileURLToPath(import.meta.url), { workerData: { letiteditVoices: true } });
    const next = () => { const x = queue.shift(); if (!x) { w.terminate(); ok(); return; } w.postMessage(x); };
    w.on("message", (m: any) => { if (!m.ready) out.set(m.id, m); next(); });
    w.on("error", (e) => { queue.length = 0; w.terminate(); fail(e); });
  }))).then(() => out);
};
const prewarm = async (cache: Map<string, any>, jobs: any[]) => {
  const A: any = M, todo = new Map<string, any>();
  for (const j of jobs) { const k = A.voiceJobKey(j); if (!cache.has(k) && !todo.has(k)) todo.set(k, j); }
  if (Math.min(todo.size, THREADS) < 2) return;
  const queue = [...todo].sort((a, b) => b[1].n * b[1].keys.length - a[1].n * a[1].keys.length);
  for (const [id, m] of await pool(queue.map(([id, job]) => ({ id, job })), THREADS)) cache.set(id, m.o);
};
const checkPlan = (piece: any, tempo: number, seconds?: number) => {
  const A: any = M, perf = A.perform(piece, tempo ?? piece.plan.tempo, { expressive: true });
  const n = seconds ? Math.round(seconds * SR) : Math.ceil((perf.lastOnset + piece.tail) * SR);
  return { p: piece, o: { seconds, tempo }, mask: A.maskingPlan(piece, { seconds: n / SR, tempo, perf }) };
};
const checkJobs = (piece: any, tempo: number, seconds?: number) => {
  const A: any = M, { p, o, mask } = checkPlan(piece, tempo, seconds);
  return [...A.voiceJobs(p, SR, o), ...(mask ? mask.roles.flatMap((r: any) => A.voiceJobs(p, SR, mask.opts(r))) : []), ...A.voiceJobs(piece, STEM_SR, { tempo, seconds })];
};
const plain = (p: any) => { const { refit, shortForm, sec, ...rest } = p; void refit; void shortForm; void sec; return rest; };
const startGuards = (cache: Map<string, any>, piece: any, tempo: number, seconds?: number): Promise<any> => {
  if (THREADS < 2) return Promise.resolve({});
  const A: any = M, { p, mask } = checkPlan(piece, tempo, seconds), voices = (jobs: any[]) => jobs.map((j) => { const k = A.voiceJobKey(j); return [k, cache.get(k)]; }).filter(([, v]) => v);
  const msgs: any[] = [];
  if (mask) for (const r of mask.roles) { const { cache: _c, perf, ...opts } = mask.opts(r); void _c; msgs.push({ id: `band:${r}`, task: { kind: "band", piece: plain(p), sr: SR, spans: mask.spans, opts: { ...opts, perf: plain(perf) }, voices: voices(A.voiceJobs(p, SR, mask.opts(r))) } }); }
  msgs.push({ id: "stems", task: { kind: "stems", piece: plain(piece), sr: STEM_SR, opts: { tempo, seconds }, voices: voices(A.voiceJobs(piece, STEM_SR, { tempo, seconds })) } });
  return pool(msgs, THREADS).then((out) => ({ bands: mask ? Object.fromEntries(mask.roles.map((r: any) => [r, out.get(`band:${r}`).out])) : undefined, stems: out.get("stems")?.out }));
};

// ---------------------------------------------------------------- reading a score
const readScore = (file: string) => {
  let m: any;
  try { m = JSON.parse(readFileSync(file, "utf8")); } catch (e) { throw new Error(`the score is not valid JSON: ${(e as Error).message}`); }
  if (!m || typeof m !== "object" || Array.isArray(m) || !m.sections || !m.chords) throw new Error("a score is one object with at least style, title, seed, mood, bpm, key, mode, chords and sections");
  if (!(M as any).VOCAB[m.style]) throw new Error(`no style "${m.style}" (have: ${Object.keys((M as any).VOCAB).join(", ")})`);
  if (m.legacy) throw new Error("legacy is for shipped scores only");
  return m;
};

// ---------------------------------------------------------------- what the report adds
const wavFloat = (path: string, L: Float32Array, R: Float32Array) => {
  const n = L.length, data = Buffer.alloc(n * 8), h = Buffer.alloc(58);
  for (let i = 0; i < n; i++) { data.writeFloatLE(L[i], i * 8); data.writeFloatLE(R[i], i * 8 + 4); }
  h.write("RIFF", 0); h.writeUInt32LE(50 + data.length, 4); h.write("WAVE", 8);
  h.write("fmt ", 12); h.writeUInt32LE(18, 16); h.writeUInt16LE(3, 20); h.writeUInt16LE(2, 22); h.writeUInt32LE(SR, 24); h.writeUInt32LE(SR * 8, 28); h.writeUInt16LE(8, 32); h.writeUInt16LE(32, 34); h.writeUInt16LE(0, 36);
  h.write("fact", 38); h.writeUInt32LE(4, 42); h.writeUInt32LE(n, 46); h.write("data", 50); h.writeUInt32LE(data.length, 54);
  writeFileSync(path, Buffer.concat([h, data]));
};
const rmsDb = (L: Float32Array, R: Float32Array, a: number, b: number) => {
  let e = 0; const i0 = Math.max(0, Math.round(a * SR)), i1 = Math.min(L.length, Math.round(b * SR));
  for (let i = i0; i < i1; i++) { const m = 0.5 * (L[i] + R[i]); e += m * m; }
  return i1 > i0 ? 10 * Math.log10(e / (i1 - i0) + 1e-12) : -120;
};
/** RBJ band-pass as a high-pass and a low-pass in a row, on the mid: how much of the music sits where speech sits. */
const speechBandDb = (L: Float32Array, R: Float32Array) => {
  const biquad = (x: Float64Array, f: number, high: boolean) => {
    const w = (2 * Math.PI * f) / SR, c = Math.cos(w), a = Math.sin(w) / Math.SQRT2, a0 = 1 + a;
    const b0 = (high ? (1 + c) / 2 : (1 - c) / 2) / a0, b1 = (high ? -(1 + c) : 1 - c) / a0, b2 = b0, a1 = (-2 * c) / a0, a2 = (1 - a) / a0;
    let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
    for (let i = 0; i < x.length; i++) { const v = x[i], y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2; x2 = x1; x1 = v; y2 = y1; y1 = y; x[i] = y; }
  };
  const x = new Float64Array(L.length); let all = 0, band = 0;
  for (let i = 0; i < x.length; i++) { x[i] = 0.5 * (L[i] + R[i]); all += x[i] * x[i]; }
  biquad(x, 300, true); biquad(x, 3400, false);
  for (let i = 0; i < x.length; i++) band += x[i] * x[i];
  return 10 * Math.log10((band + 1e-12) / (all + 1e-12));
};
/** A fade on what rings after the last note (never on a note's start): the piece decays instead of stopping dead. */
const endFade = (L: Float32Array, R: Float32Array, lastOnsetS: number, fadeS: number) => {
  const n = L.length, room = n - Math.ceil((lastOnsetS + 0.1) * SR), f = Math.min(room, Math.round(fadeS * SR));
  if (f <= 0) return 0;
  for (let i = 0; i < f; i++) { const g = 0.5 - 0.5 * Math.cos((Math.PI * i) / f), k = n - 1 - i; L[k] *= g; R[k] *= g; }
  return f / SR;
};
const partsPrint = (piece: any) => Object.fromEntries(piece.parts.map((p: any) => [p.id, { notes: p.notes.length, hash: createHash("sha256").update(JSON.stringify(p.notes.map((n: any) => [n.t, n.d, n.p, n.v]))).digest("hex").slice(0, 12) }]));
const craftOut = (r: any) => ({ scores: r.scores, findings: r.findings.map((f: any) => ({ level: f.level, area: f.area, msg: f.msg, fix: f.fix })), tension_by_bar: r.tension.bars.map((x: number) => round(x)), tension_peak_at: round(r.tension.peakAt) });

// ---------------------------------------------------------------- commands
const report = async (file: string, o: { seconds?: number; payoff?: number; fit: boolean; endFadeS: number; out?: string }) => {
  const A: any = M;
  let piece = A.composePiece(readScore(file)), tempo = piece.plan.tempo;
  const seconds = o.seconds;
  if (o.fit) { if (!seconds) throw new Error("fit needs a length"); const f = A.fitScore(piece, seconds); piece = f.piece; tempo = f.tempo; }
  const t0 = Date.now(), cache = new Map<string, any>();
  await prewarm(cache, checkJobs(piece, tempo, seconds));
  const pending = startGuards(cache, piece, tempo, seconds);
  const r = A.renderPiece(piece, SR, { seconds, tempo, cache, stems: true }), g = await pending;
  const problems: string[] = A.planProblems(piece), warnings: string[] = piece.warnings ?? [];
  const lu = A.loudness([r.L, r.R], SR).integrated, tp = A.truePeak([r.L, r.R]).dbtp, target = r.masterMode === "dense" ? -14 : r.masterMode === "gentle" ? -16 : NaN;
  const master: any = { mode: r.masterMode, lufs: round(lu, 1), target, true_peak: round(tp) };
  if (lu < target - 0.5) { const pk = A.peakReport(r, SR); master.short_of_target = { db: round(target - lu, 1), bar: pk.bar, beat: pk.beat, at_s: round(pk.sec), parts: pk.parts.map((x: any) => x.id) }; }
  const guards = A.guardReport(r, SR, r.L.length / SR, { cache, bands: g.bands });
  const stems = g.stems ?? A.measureStems(piece, STEM_SR, { tempo, seconds, cache });
  const calibrated = A.VOCAB[piece.plan.style]?.calibrated !== false;
  const craft = A.craftReport(piece, { centroidHz: A.centroid([r.L, r.R], SR).mean });
  const arc = A.arcReport([r.L, r.R], SR, { payoffS: o.payoff });
  const fam = [file], nov = A.novelty(piece, A.DEMOS, fam), q = nov.rows.find((x: any) => x.quotedShapes || x.reusedFragments);

  // bars as the performance plays them, each one's level, and the sections
  const bpb = A.beatsPerBar(piece.plan.meter), dur = r.L.length / SR, sec = (b: number) => r.perf.sec(b);
  const lastOnset = r.perf.lastOnset, noteEnd = Math.max(...r.perf.parts.flatMap((p: any) => p.keys.map((k: any) => k.off ?? k.t)));
  const fadeS = endFade(r.L, r.R, lastOnset, o.endFadeS);
  const arrangement: any[] = piece.arrangement ?? [], total = arrangement.length ? Math.max(...arrangement.map((x) => x.from + x.bars)) : Math.ceil(lastOnset / (bpb * 60 / tempo));
  const bars = Array.from({ length: total }, (_, i) => { const a = sec(i * bpb), b = i + 1 < total ? sec((i + 1) * bpb) : Math.min(dur, a + bpb * 60 / tempo); return { bar: i + 1, at_s: round(a), db: round(rmsDb(r.L, r.R, a, b), 1), section: arrangement.find((x) => i >= x.from && i < x.from + x.bars)?.id ?? null }; }).filter((b) => (b.at_s as number) < dur);
  const dbs = bars.map((b) => b.db as number).sort((a, b) => a - b), median = dbs.length ? dbs[Math.floor(dbs.length / 2)] : 0;
  let lift: any = null;
  if (o.payoff !== undefined) { const near = o.payoff + 30 / tempo /* half a beat: a payoff just before a bar line belongs to that bar */, at = bars.findIndex((b, i) => (b.at_s as number) <= near && (i + 1 === bars.length || (bars[i + 1].at_s as number) > near)); if (at >= 0) { const before = bars.slice(Math.max(0, at - 2), at).map((b) => b.db as number); lift = { bar: bars[at].bar, db: bars[at].db, over_two_bars_before_db: before.length ? round((bars[at].db as number) - before.reduce((x, y) => x + y, 0) / before.length, 1) : null }; } }
  const firstBar = bars[0] ? round((bars[0].db as number) - median, 1) : null;
  const lead = r.perf.parts.filter((p: any) => piece.parts.find((x: any) => x.id === p.id)?.role === "melody").flatMap((p: any) => p.keys.map((k: any) => [round(k.t, 3), round(k.off ?? k.t, 3)]));
  const fails: string[] = [];
  if (problems.length) fails.push("key");
  if (!guards.ghost.pass) fails.push("ghost");
  if (!guards.reverb.pass) fails.push("reverb");
  if (guards.masking && !guards.masking.pass) fails.push("masking");
  if (!stems.pass && calibrated) fails.push("stems");
  if (craft.findings.some((f: any) => f.level === "error")) fails.push("craft");
  if (!nov.pass) fails.push("novelty");
  if (o.out) wavFloat(o.out, r.L, r.R);
  return {
    pass: fails.length === 0, failed: fails, tempo: round(tempo), duration_s: round(dur, 3), seconds_given: seconds ?? null, render_s: round((Date.now() - t0) / 1000, 1),
    problems, warnings, master,
    guards: { ghost: { pass: guards.ghost.pass, formless_windows: guards.ghost.failures, windows: guards.ghost.windows }, reverb: { pass: guards.reverb.pass, worst_db: round(guards.reverb.worstDb, 1) }, masking: guards.masking ? { pass: guards.masking.pass, lead_clear_share: round(guards.masking.shareOfBarsClear), worst_db: round(guards.masking.worstMarginDb, 1), lead_headroom_db: A.LEAD_HEADROOM_DB } : null },
    stems: { pass: stems.pass, advisory: !calibrated, tolerance_db: stems.tolDb, rows: stems.rows.map((x: any) => ({ id: x.id, db: round(x.rmsDb, 1), target: x.targetDb === null ? null : round(x.targetDb, 1), off: x.offDb === null ? null : round(x.offDb, 1), ok: x.ok })) },
    craft: craftOut(craft),
    arc: { usual_lufs: round(arc.medianLu, 1), loudest_lufs: round(arc.peakLu, 1), loudest_at_s: round(arc.peakS, 1), range_lu: round(arc.lra, 1), opens_under_lu: round(arc.introUnderBody, 1), ends_under_peak_lu: round(arc.endUnderPeak, 1), findings: arc.findings },
    novelty: { pass: nov.pass, threshold: nov.threshold, closest: nov.rows[0] ? { name: nov.rows[0].name, score: round(nov.rows[0].score, 3) } : null, quotes: q ? q.name : null },
    bars, first_bar_vs_median_db: firstBar, lift,
    end: { last_note_s: round(lastOnset, 2), last_note_off_s: round(noteEnd, 2), fade_s: round(fadeS), notes_past_end: r.perf.parts.reduce((c: number, p: any) => c + p.keys.filter((k: any) => k.t >= dur).length, 0), silent_after_s: round(Math.max(0, dur - (noteEnd + piece.tail)), 2) },
    sound: { centroid_hz: Math.round(A.centroid([r.L, r.R], SR).mean), speech_band_db: round(speechBandDb(r.L, r.R), 1) },
    lead_notes: lead, parts: partsPrint(piece),
  };
};

const printVocab = (id?: string) => {
  const A: any = M;
  if (!id) {
    for (const v of Object.values<any>(A.VOCAB)) console.log(`${v.id.padEnd(15)} ${v.name}: ${v.atmosphere}\n${"".padEnd(16)}grooves: ${v.grooves.join(", ") || "none (no drums)"} | moods: ${v.moods.join(", ")} | ${v.tempo.join("-")} bpm ${v.meters.join(" ")}`);
    console.log("\ngroove families:"); for (const [k, d] of Object.entries(A.GROOVE_FAMILIES)) console.log(`  ${k.padEnd(10)} ${d}`);
    console.log("\nsection kinds:"); for (const [k, d] of Object.entries<any>(A.KINDS)) console.log(`  ${k.padEnd(10)} ${d.what}`);
    return;
  }
  const v = A.VOCAB[id]; if (!v) throw new Error(`no style "${id}" (have: ${Object.keys(A.VOCAB).join(", ")})`);
  console.log(`${v.name} (${v.id}): ${v.atmosphere}\ntempo ${v.tempo.join("-")} bpm, meters ${v.meters.join(" ")}, swing ${v.swing.join("-")}, moods ${v.moods.join(", ")}`);
  const tgt = (slot: string) => (v.stemTargets[slot] === undefined ? "-" : +(v.stemTargets[slot] + (A.VOCAB_TARGET_FIX[v.id]?.[slot] ?? 0)).toFixed(1));
  console.log("palette (slot: instrument, stem target dB). Every voice, alternate or your own, is calibrated to its slot's target:\n  levels.<slot> and your own voice's gainDb are dB offsets from there (0 = at the target)");
  for (const [slot, x] of Object.entries<any>(v.palette)) console.log(`  ${slot.padEnd(8)} ${x.inst.padEnd(10)} ${String(tgt(slot)).padStart(6)} dB${Object.keys(v.alternates[slot] ?? {}).length ? `   alternates: ${Object.entries<any>(v.alternates[slot]).map(([n, a]) => `${n} (${a.inst})`).join(", ")}` : ""}`);
  for (const [slot, alts] of Object.entries<any>(v.alternates)) if (!v.palette[slot]) console.log(`  ${slot.padEnd(8)} (no default) alternates: ${Object.entries<any>(alts).map(([n, a]) => `${n} (${a.inst})`).join(", ")}`);
  console.log(`stem targets ${v.calibrated ? "calibrated on a listened score" : "are starting numbers (uncalibrated: flags are advisory)"}`);
  console.log(`grooves: ${v.grooves.map((g: string) => `${g} (${A.GROOVE_FAMILIES[g]})`).join("\n         ") || "none"}`);
  for (const [k, x] of Object.entries<any>(v.harmony)) console.log(`harmony.${k}: ${Array.isArray(x) ? x.join(", ") : x}`);
  for (const [k, x] of Object.entries<any>(v.melody)) console.log(`melody.${k}: ${x}`);
  for (const [k, x] of Object.entries<any>(v.arrangement)) console.log(`arrangement.${k}: ${x}`);
  console.log(`mix: ${A.describeMix(v.id)}`);
  console.log(`avoid: ${v.avoid}`);
};

const main = async () => {
  const [cmd, ...args] = process.argv.slice(2);
  const val = (k: string) => { const i = args.indexOf(k); return i >= 0 ? Number(args[i + 1]) : undefined; }, str = (k: string) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
  const threads = val("--threads"); if (threads) THREADS = threads;
  if (cmd === "vocab") { printVocab(args[0]); return; }
  if (cmd === "craft") { const piece = (M as any).composePiece(readScore(args[0])); console.log(JSON.stringify({ ...craftOut((M as any).craftReport(piece)), parts: partsPrint(piece) })); return; }
  if (cmd === "report") { console.log(JSON.stringify(await report(args[0], { seconds: val("--seconds"), payoff: val("--payoff"), fit: args.includes("--fit"), endFadeS: val("--end-fade") ?? 1, out: str("--out") }))); return; }
  throw new Error("commands: vocab [style] | craft <score.json> | report <score.json> [...]");
};

if (isMainThread) main().catch((e) => { console.log(JSON.stringify({ error: (e as Error).message })); process.exit(2); });
else if (workerData?.letiteditVoices) workerMain();
