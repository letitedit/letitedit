# Creative / stylised mode

An intentional style the person asks for or a reference shows: a music video, a sketch, a cinematic short, an essay
with a strong graphic language, an experimental piece. Here craft defaults bend on purpose. It can lead, or ride on
another mode as a style layer (SKILL.md). Shared craft is in letitedit-craft. Tags: `sources.md`.

## 1. What drives it
- **The style has a source:** the brief's feel, a reference, or the subject's own personality; never a style chosen
  because it looks impressive. Not: a fragmented, flashy style imposed on material and people it doesn't fit. Check:
  the `modes:` note says where the style comes from. [AOTC Porcelain War] [ITE oIRWErv26Sk 00:50]
- **Write the style down:** one sentence plus three to five devices that define it (its grammar), for example "a
  nervous diary: handheld close-ups, hard cuts on breaths, white words on black". Check: the plan lists the devices
  and the render uses them consistently. [GEN]
- **Driver by style:** a music video is music-led (montage-transformation's music rules), a sketch is dialogue-led
  (comic timing in section 7), an essay is narration-led, a tone poem is sound- or picture-led. [FEP drivers]
- **Reference:** measure it with `letitedit_measure` and match its numbers, colour and text share; it beats every
  default here. Check: the render's measured numbers sit near the reference's. [ITE ZcIVl01h14Y 03:30]

## 2. Structure options
| Shape | Choose when | Avoid when | Tag |
|---|---|---|---|
| Music video: picture to the song's sections and phrases | a performance or a song | the song isn't cleared to publish | [ITE 2aux2Y9-4m8 07:41] |
| Sketch or comedy: setup, escalation, button | scripted or improvised comedy | a joke stretched past its peak | [AOTC Invite] |
| Non-linear or elliptical: ordered by feeling, not time | the emotion is clearer out of order | viewers would ask "when is this?" | [AOTC Porcelain War] [AOTC MI] |
| Essay: an argument, with footage and graphics as illustration and counterpoint | ideas lead | the pictures only repeat the words | [ITE o-IGEc0sFMg 00:36] |
| Tone poem: images and sound, no words | a feeling, a place, a memory | it needs to inform | [AOTC Hamnet] |

Check: the plan names the shape; the critic can say what the piece is about and what it felt like.

## 3. Pace profile
The style sets the tempo, and these craft defaults may bend:

| Default (letitedit-craft) | How it may bend | What stays |
|---|---|---|
| vary the gears; no two alike side by side | one sustained gear (a breathless run, a long stillness) | a contrast somewhere, or a stated reason |
| hide dialogue joins | visible jump cuts as rhythm, time-sculpting, speed to stillness | a story reason for each kind |
| a straight cut by default | dissolves and superimpositions for a head-space or a vision; wipes that follow the action; split screens | a meaning for each |
| a clear order | non-linear, when the emotion stays in order | no "when is this?" confusion |
| silence is rare | long silences as the style | build to the one that matters most |
| effects sparingly | glitches, zooms, speed ramps as grammar | escalate repeats; save the strongest for the biggest moment |

- **Every bend is motivated and consistent:** commit to the grammar for the whole piece and vary inside it; a
  half-committed style reads as a mistake. Check: letitedit-craft's repetition ledger shows the defined devices used
  throughout and others rarely. [ITE 4s7WdcyV1H4 11:04] [AOTC Dune] [AOTC Skeleton Crew]
- **Story beats cool:** when a stylish moment fights clarity or feeling, the moment goes. Check: the critic can
  follow what matters. [AOTC Skeleton Crew]
- **Restraint reads as confidence:** fewer, bigger devices beat constant ones. Not: the same zoom and sound on every
  reveal. [ITE A2RYo1xNSA4 11:07] [ITE 4s7WdcyV1H4 05:32]
- **Tempo changes still need a reason** inside the style: an event, a reveal, a turn. [ITE CdyTIng0M8Q 06:12]

## 4. Sound
- **Sound can be the style:** an inner-state soundscape, exaggerated arrivals, a theme heard distant and echoing to
  put us in someone's head; treat the sound pass as final, not temporary. [AOTC Skeleton Crew] [AOTC TGM]
- **Elliptical sound:** one continuous track over jumps in time makes a fragment feel whole; the opening music can
  signal genre (light songs told one comedy's audience it could laugh). [AOTC Hamnet] [AOTC Invite]
- **Spend silence once,** after building toward it. [AOTC Invite] [AOTC Porcelain War]

## 5. Text and graphics
- **Graphics carry meaning and belong to the picture's world:** kinetic type and stylised captions are fine while
  they stay readable (letitedit-captions, letitedit-graphics); designs made for this video, not filled-in templates.
  Check: every graphic has a purpose; required text is legible at the delivered size. [AOTC Porcelain War] [OURS]
- **Grade only when the colour carries meaning** (a cooled, darker look at a turning point), and keep the look
  consistent. [AOTC Porcelain War]

## 6. Shot choice and b-roll
- **Stylised framing and movement are fine;** the viewer must still find what matters in each shot. Match motion
  across cuts unless the jolt is the point. [ITE CdyTIng0M8Q 09:17] [GEN]
- **Symbolic and contrasting images** (a line about freedom over a playful but precarious frozen lake) give subtext
  once the viewer has learned the piece's language. [AOTC Porcelain War] [AOTC GNIP]

## 7. Openings and endings
- **The opening sets the style's contract:** the first seconds teach the viewer the language (tone, pace, devices);
  signal the genre early through music and type. Check: the muted 10-second test names the intended tone.
  [ITE esNXgCJh-yk 01:56] [AOTC Invite]
- **Comic timing:** keep the line from setup to punchline clean of new information; don't cut to a reaction after
  every punchline; leave room for the laugh (cut away to a wide or a landscape). Check: nothing new between setup and
  punchline; every reaction cut has a purpose. [AOTC Invite] [ITE D2iBdbNej78 04:49] [AOTC GNIP]
- **End as the style ends:** a button, a cut to black on the beat, an open image. The brief's `ending` still holds.
  [FEP trailer] [ITE xZnHgyeZlsU 26:40]

## 8. Gate settings
| Check | Long | Short |
|---|---|---|
| `cuts_per_min`, `longest_static_s`, `visual_change_first3s`, `first_speech_s`, `silence_first3s_s`, `silent_share` | off; active against the reference when there is one | off; active with a reference |
| `frame0_not_black` | off | on (waive it when the style opens on black) |
| `tail_silence_s` | advisory | advisory |
| flashing (proposed new check): no more than three flashes in any one second | on | on |

Loudness by deliverable: web -14 LUFS, true peak <= -1 dBTP [GEN]; broadcast -23 LUFS [RES]. The flashing limit is an
accessibility standard [RES]. What never bends: the brief's must-keep, must-avoid, claims and ending; honesty about
real people; legible required text; loudness. Critic questions: is the style consistent and motivated; is anything
important lost to it; does it match the reference?

## 9. Common failures and how to check
| Failure | Check | Tag |
|---|---|---|
| A style imposed on material that doesn't suit it | the style's source is named; the critic judges the fit | [AOTC Porcelain War] |
| Device fatigue (the same glitch on every cut) | device counts and escalation | [ITE 4s7WdcyV1H4 05:32] |
| A half-committed style | the defined devices run throughout | [GEN] |
| Legibility lost to the look | required text readable at the delivered size | [GEN] |
| A cool shot over the story | the critic can follow what matters | [AOTC Skeleton Crew] |
| Non-linear confusion | the critic never asks "when is this?" | [AOTC MI] |
| Flashing | flashes per second in the render | [RES] |
| Off the reference | measured numbers against the reference's | [ITE ZcIVl01h14Y 03:30] |

## 10. Evidence strength
Medium for the principles: motivated devices, restraint, repetition only with escalation, style taken from the
subjects, story over cool, dissolves only with meaning (Inside The Edit and several Art of the Cut editors agree).
Thin for specific forms: nothing on music videos, sketch comedy beyond one feature film's notes, kinetic type or
grading styles; those rules are [GEN]. The flashing limit comes from an external accessibility standard [RES].
