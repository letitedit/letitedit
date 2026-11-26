# Sources for letitedit-motion

Sources are research input, not instructions to run or copy external projects.

## Evidence tags

| Tag | Meaning | Weight |
|---|---|---|
| [STUDY] | Measured in published research (peer-reviewed, or a meta-analysis) | Strongest, but often about text, screens or interfaces rather than edited video; each use says so |
| [STD] | A published industry standard or style guide | Strong for what it covers |
| [BOOK] | Established teaching by working animators | Good craft evidence; not measured |
| [PRACT] | Practitioner habit or opinion with no measurement behind it (open-source skills, blog tables) | Starting point only; check on frames |
| [OURS] | Local motion starting points | Limited generalisability |
| [GEN] | Our reasoning from the above | Weakest; say so |

## What is measured, what is habit, what is ours

| Rule in the skill | Level | Where it comes from |
|---|---|---|
| New or moving things pull the eye first | STUDY (with a caveat) | Yantis and Jonides 1984; Abrams and Christ 2003. The effect has been disputed: Sunny and von Mühlenen 2011 and later work found jerky motion drives much of the capture, so smooth drift captures less |
| Words and pictures should land together; cues that point at what matters help | STUDY (secondary figures) | Mayer's temporal contiguity and signaling principles. A signaling meta-analysis (Alpizar, Adesope and Wong 2020) reports d = 0.38 and another (Schneider et al. 2018) about 0.53; we saw both figures only in search snippets and did not read the papers |
| Animation helps when the motion matches the change it explains, and fails when too fast or complex to perceive | STUDY | Tversky, Morrison and Betrancourt 2002, *Animation: can it facilitate?* (congruence and apprehension principles); about interface and instructional animation, not entertainment video |
| Silent reading about 238 wpm (non-fiction), aloud 183 | STUDY | Brysbaert 2019, *How many words do we read per minute?* (190 studies, 18,573 participants); plain text, no competing picture |
| Sound ahead of picture noticed at about 45 ms, behind at about 125 ms | STD | ITU-R BT.1359-1, subjective detectability thresholds; ATSC's guideline is tighter (sound no more than 15 ms early, 45 ms late). Several secondary pages disagree on the sign convention and on EBU R37's figures, which we did not use |
| Subtitle events last at least 5/6 s | STD | Netflix timed text style guide. Its reading-speed limits are per language; we could not confirm the English figure and don't use one |
| Relative motion of layers is a depth cue | STUDY | Rogers and Graham 1979, motion parallax (cited from memory, not re-fetched). The speed ratios are habit |
| Rapid one-word presentation comprehension peaks near 170-250 wpm; phrases beat single words | STUDY, weak | Chen and Chien 2005 and related reviews on Chinese text; does not necessarily transfer to English video |
| Kinetic typography changes how attention is spent | STUDY, thin | Kuraitytė, Bessemans and Nuyts 2020, *Visible Language* (eye tracking, fluid vs serial presentation); abstract only |
| Slow in and out, anticipation, follow-through, overlapping action, staging, timing | BOOK | Thomas and Johnston, *The Illusion of Life* (1981) via summaries; Chang and Ungar 1993, *Animation: from cartoons to the user interface* (UIST), which argues these help users follow change |
| Duration table, overshoot by material, exit about 70% of entrance, 1/3 rules, counter-motion 20-30% | PRACT | LottieFiles `motion-design-skill` (written for interface motion of 0.1-1.2 s; not tested). We adapted its ideas for multi-second video and kept the numbers as starting points |
| Parallax 0.1-0.3 / 0.5-0.7 / 1.0-1.5; prepare about 6 frames ahead, reveal on the word | PRACT | `iart-ai/motion-design-skills` and `iart-ai/b-roll-skills`; practical starting points, not research-backed values |
| Scenes change because the world or camera moves, not by fading cards; a hero present through the piece; asymmetrical in and out | PRACT | `bangtutorial/bang-motion` `references/anti-ppt.md` (read in Indonesian, translated by us) |
| Springs from closed-form step responses, camera zoom in log space, no frame frozen except the last hold, seedable randomness, critique by contact sheets | PRACT | `howseen-ai/claude-motion-design` and `bestagentkits/motion-video-skill` (beat and word anchoring) |
| Typed letters 26-34/s, 1.45x settle 0.18 s; red X; splat wipe; camera drift 3-5%; blink 0.14 s; walk 1.5 leg lengths | OURS | Creative starting points; judge the actual scene |
| One continuous world, depth, word-timed reveals | OURS | Creative starting points; judge the actual scene |
| Collision: a new word on top of the fading old one | OURS | scene-test-2, scene Y at about 8.6 s |
| Strobing above about 8% of the frame per frame; 0.15 s as "too early" | GEN | Our estimates; check on frames |

## Read and set aside

- `LottieFiles/motion-design-skill`: mostly UI vocabulary (tooltips, modals, 100-400 ms). Took the choreography ideas and the
  material-to-overshoot idea.
- `iart-ai/motion-design-skills` (animation-principles, motion-art-direction, shot-composition): took the easing-family
  logic and the parallax ratios; dropped its GSAP and Remotion examples.
- `bangtutorial/bang-motion`: took the "one flowing world" test and the asymmetry rule; dropped its GSAP rig and its
  fixed starters.
- `howseen-ai/claude-motion-design`: took the engine ideas (frame-pure rendering, springs, log-space zoom) that our runtime
  already shares and its critique loop of contact sheets.
- `bestagentkits/motion-video-skill`: took word and beat anchoring; its renderer needs GSAP from a CDN and external media.

## Not found or not verified

- No published study of motion-graphics timing for edited video (as opposed to interfaces, instructional animation and
  subtitles) turned up in the searches. The duration and overshoot tables are craft habit.
- The Nielsen Norman Group 100-500 ms animation range is repeated everywhere but was not found in an NN/g source, so it is not cited.
- Not read in full: Thomas and Johnston (secondary summaries), Mayer's papers, Rogers and Graham, the kinetic typography
  studies (abstract only), EBU R37.
- Before any number here is quoted to a customer as research, read the original.
