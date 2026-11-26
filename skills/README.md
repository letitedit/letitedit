# letitedit skills

Editing skills for the person's own agent (Claude Code or Codex) driving letitedit through the `letitedit` MCP tools:
from a short brief, a strong first cut of the person's own footage, then revisions from plain feedback ("less
flashy", "give the reveal more room"). The skills hold the editorial judgment; the tools measure, match, lay out and
render. Each skill's
`references/sources.md` summarizes the evidence behind its rules.

## The skills

| Folder | Job | Loaded |
|---|---|---|
| `letitedit` | Router: the brief (`mode`, `driver`, deliverables, `reference`, `feel`, `must_keep`, `must_avoid`, `claims`, `ending`, `narration`, `protected`), the next stage from the project files, which skills to load | always first |
| `letitedit-craft` | Fundamentals for every edit: spine, pacing (feeling first, gears, levers), scenes, dialogue, faces, b-roll jobs, tension, the device ledger, transitions, and the revision-levers table | every edit |
| `letitedit-modes` | One playbook per kind of video (`references/<mode>.md`): story/vlog (with the DIY and repair playbook), tutorial, interview/podcast, documentary, product, travel/event, montage/transformation (with before/after), creative | the brief's mode(s) |
| `letitedit-log` | Log by mode (text to find, picture and sound to judge), takes via `letitedit_find_takes`, requirements mapped, ranked selects -> `log.json`, `selects.json` | stage |
| `letitedit-story` | Purpose, sections with driver, gear and feel, loops, setups, revelations, opening and ending, pickups -> `story_plan.json`, `pickups.md` | stage |
| `letitedit-rough` | Built in the driver's order, rendered early, one restructure, mode-aware story QA (FM1-FM12) -> rough project, QA table in the journal | stage |
| `letitedit-fine` | Dialogue retimed line by line, joins, J/L cuts, b-roll timing and sequences, punch-ins and holds, pace against the plan's gears | stage |
| `letitedit-finish` | Shot matching, speech cleanup, then the sound, graphics and caption skills, safe zones, one export per deliverable | stage |
| `letitedit-sound` | Music, natural and protected sound, bridges, ducking, the loudness table by deliverable | when sound or music is touched |
| `letitedit-captions` | Spoken captions and on-screen words: chunking, reading speed, names and numbers, placement (`letitedit_caption_fit`) | when captions or text are added |
| `letitedit-graphics` | The explain-it-clearly pass (`letitedit_annotate`), titles and lower thirds, effects restraint | when the edit explains, labels or styles |
| `letitedit-layers` | What's in front of what, and what an effect touches: behind a person, picture-in-picture, blend modes, colour on a clip, track, stretch or whole video, regions; what the engine can't do; proving it with frames | when an edit stacks things or aims an effect |
| `letitedit-motion` | How things move: arrive/hold/leave timing in frames, easing, overshoot and springs by weight, one focal point, stagger, camera and parallax through one world, kinetic type, landing on the spoken word and sound, checks for cheap-looking motion (`letitedit_code_scene`, `letitedit_motion`) | before a code scene, motion block or animated title |
| `letitedit-shorts` | Vertical shorts: a muted visual hook and foreshadow, mechanism, payoff and end, one edit per platform | format: shorts |
| `letitedit-firstcut` | The "Make a first cut" button: the stages in order, `why:` markers, three openings, fixes in plain words | entry point |
| `letitedit-review` | The brief for the separate critic -> `review.json` | inside `letitedit_review_bundle` |
| `letitedit-gate` | `letitedit_review_bundle` on each export: one verdict -> `review_bundle.json`, `review.md` | at the end |
| `letitedit-broll` | Cutaway jobs, source selection, sequences, sound and rhythm | when choosing or placing b-roll |

## How they compose
- **Load rule:** load the router, letitedit-craft, the brief's mode playbook, the current stage skill and every
  presentation skill that stage needs (sound, captions, graphics, layers or motion), plus letitedit-shorts for a short.
- **Stages and hand-off files**, in the project folder: `brief.json` (router) -> `log.json` and `selects.json` (log)
  -> `story_plan.json` and `pickups.md` (story) -> the rough project, its render and the QA table in the journal
  (rough) -> the fine-cut project (fine) -> the mix, captions, SRT and exports (finish) -> `review_bundle.json` and
  `review.md` (gate; the critic writes `review.json`). In the app's chat, which can't write files, the same content
  goes into `letitedit_journal` notes starting `brief:`, `log:`, `selects:`, `story_plan:` and `pickups:`. Each stage
  ends with a `stage:<name>:done` note.
- **The driver routes the work:** the brief's `driver` (dialogue, narration, music, visual, sound), refined per section
  in the plan, decides what the log looks at first, how the rough is built and how the fine cut sets pace.
  Dialogue-first rules apply only when dialogue drives.
- **Requirements travel from the start:** the log maps `required_lines`, `must_keep`, `claims`, `ending`, `protected`
  and `must_avoid` to source times; the story places them; the rough checks them (FM6); the gate checks them again
  on the render.
- **review.md is the final word.** Never claim success yourself: the message to the person is the video path and
  `review.md` as written, with what failed, what was waived and what wasn't checked (code doesn't listen). The
  to-film list lives in `pickups.md`, because the gate rewrites its own files on every run.
- **Markers** carry intent on the timeline (`letitedit_bin`): `why:`, `cut:`, `beat:<id>:<label>`, `loop:open:<id>`,
  `loop:close:<id>`, `hold:<reason>`, `chapter:<name>`, `hook:<A|B|C>`, `callback:`, `waive:<check>:<reason>`.

## Rules every skill follows
- Defaults, not laws: the person's brief and reference win. Break a craft default with `waive:<check>:<reason>`;
  delivery limits and story blockers need the person's OK instead.
- Never invent structure the footage doesn't have; when something needed is missing, say so and offer a pickup or an
  honest bridge.
- Judgment in the skills, measuring and timing in the tools: no coordinate or timing maths a tool can do. Tool
  parameters come from `letitedit_guide('<tool>')`, not from memory.
- Every rule says what to do, when, when not, how to check it, and its evidence: `[ITE <id> mm:ss]` Inside The Edit
  (one documentary editor, so agreement inside ITE is one voice), `[ITE art:<slug>]` its articles, `[AOTC <film>]`
  Art of the Cut interviews (GNIP = The Greatest Night in Pop, TGM = Top Gun: Maverick, MI = Mission: Impossible),
  `[JH m:ss]` Jenny Hoyos (the one short-form source), `[FEP <note>]` Film Editing Pro notes (summaries, low weight),
  `[YT]` / `[RES]` platform docs or research, `[OURS]` local editing practice, `[GEN]` general practice, unsourced. Each
  rebuilt skill lists its documents in `references/sources.md`. Skills not yet rebuilt still use the older tags
  ([OFF] official, [RES] measured study, [EXP] practitioner, [HYP] our default).

## Install
Copy (or link) each folder into `%USERPROFILE%\.claude\skills\` for Claude Code, or into `.agents\skills\` of the
working folder (or `~/.codex/skills`) for Codex; `install.py` does both (run it again after edits). Tool names are
the `letitedit` MCP server's (`letitedit_guide` lists them); if the server is installed under another name, the router's
alias line says what to substitute.
