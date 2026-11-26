# Product / commercial mode

Selling or showing a product, a service or a brand: an ad or spot, a demo, a launch, a brand film, a testimonial. The
viewer should believe one thing and do one thing. Shared craft is in letitedit-craft. Tags: `sources.md`. The library
has no lesson on ads or product video, so most rules here are general practice [GEN].

## 1. What drives it
- **Music or a script usually drives; product action is the evidence.** A music-led spot builds the track first
  (montage-transformation's music rules); a voice-over spot locks the read first; a demo runs on its steps
  (tutorial-explainer). Check: the plan names the driver per section. [FEP drivers] [AOTC Porcelain War]
- **Log the product's moments:** hero shots, features in use, details, reactions and results; tag every claim spoken
  in the footage. Check: each claim in `brief.claims` maps to a source line and a proof shot. [GEN]
- **Purpose line:** "After this, the viewer believes [one thing] and [does the call to action]." One message per
  spot: a piece about several things is about none. Check: the critic restates the one message.
  [ITE FOJhAl9IyPg 09:30] [GEN]

## 2. Structure options
| Shape | Choose when | Avoid when | Tag |
|---|---|---|---|
| Problem, solution, proof, call to action | the product removes a clear pain | the pain would be invented | [GEN] |
| Demo: the product doing its job, step by step | the how is the selling point | the steps are dull without a result | [GEN] |
| Brand or mood film: feeling first, product late | premium, awareness | the viewer must learn a specific fact | [ITE art:how-to-start-a-scene] |
| Testimonial (interview-podcast's rules) | real customers on camera | scripted lines presented as real | [GEN] |
| Teaser or promo: grab, escalate, shift the music's energy, stop it for the button | launches, trailers | a calm, reassuring brand | [FEP trailer] |
| Launch or event recap (travel-event's rules) | an opening day, a cause's work | there is no event footage | [ITE WlS5f8Plyl0 19:30] |

Check: the plan names the shape and its one message.
- **Spot lengths are deliverables:** a 6 s spot holds one image, one idea and the brand; 15 s a hook, one
  demonstration and the offer; 30-60 s room for problem, proof and a breath before the offer. Check: each deliverable
  is its own cut, not a trim of the longest; per-platform edits differ where the platforms do. [GEN] [JH 27:38]
- **No invented hero's journey:** a founder's struggle only when it is real and the brief wants it. [GEN]

### Claims, proof and the call to action
- **Claims stay exact:** every product name, price, spec, offer and date is said and shown as in `brief.claims`, from
  one take, never assembled from fragments; `letitedit_find_takes` flags takes that differ in a number, a name or a
  negation, so pick the take that states the approved claim. Check: the gate's claims check passes (it is critical);
  the critic hears each claim whole. [ITE KAO0n3C0kAg 12:09] [GEN]
- **Every claim gets proof:** a shot of the product doing it, in the same beat as the line (just before or just
  after). With none in the footage, flag a pickup; never imply proof with an unrelated shot. Check: a claim-to-proof
  table in the journal; the critic confirms each pair. [ITE gwyneGrX9Jw 26:53] [GEN]
- **One call to action,** said and shown at the end (and earlier in short spots if the brief wants), on screen long
  enough to read twice (letitedit-captions has reading speeds), inside every platform's safe area. Check:
  `letitedit_check_frames` with the platform's covered areas drawn; the CTA reads at the delivered size. [GEN]
- **Legal and disclaimer text** legible and on screen long enough; never under the busiest moment. [GEN]

## 3. Pace profile
- **Match the energy to the brand's audience:** short spots often run gears 3-5; a premium or reassuring brand runs
  1-3 with restrained cutting, which reads high-end; no high-speed jump cuts or glitches for a calm brand. Check: the
  plan's gears match the brief's feel words. [ITE A2RYo1xNSA4 08:03] [ITE A2RYo1xNSA4 11:09]
- **Leave a breath before the offer:** cramming reads as insecure, and a shorter cut can feel longer. [AOTC GNIP]
- **Beauty needs progression:** hero shots as a short chain (reveal, detail, in use, result), not a string of pretty
  stills. Check: no three standalone beauty shots in a row without a change. [ITE eXUH3Z5ZntE 06:45]
  [ITE bCVeyUFGxi8 05:37]

## 4. Sound
- **Music-led spots put the track first,** arranged with `letitedit_soundtrack` so its hits land on the reveal and the
  logo while the claims sit in protected ranges. Check: the soundtrack's measure shows the hits landed and the
  protected ranges clear. [AOTC Porcelain War] [GEN]
- **Claims must be heard:** the voice above everything; no musical swell under a claim. Check: the critic hears every
  claim; `letitedit_check_audio` shows music down under speech. [GEN]
- **Accents on product actions** (a click, a pour, a snap), motivated by a change in movement speed; hard hits half a
  frame before the cut; stop the music to land the button. [FEP trailer] [AOTC Dune]

## 5. Text and graphics
- **Brand-true text:** product names as the brand writes them, prices and offers short and large, the brand's
  typeface and colours from the person's Look (`letitedit_looks(action='get', id=...)`) when one exists; designed for this video, not
  a filled-in template. Check: names and prices match `brief.claims`. [AOTC TGM] [OURS]
- **Feature callouts** that point at the product and follow it when it moves (`letitedit_annotate`); an exploded or
  x-ray view with `letitedit_3d` when a model exists (letitedit-graphics). [GEN]
- **The logo end card stays short** (a second or two), with the CTA. [GEN]

## 6. Shot choice and b-roll
- **Hero, detail, in use, benefit, context:** the product clean and well lit; textures and features close; hands and
  people using it; the result or the reaction; where it lives. Check: the product is visible in the opening and at
  the end. [GEN]
- **One look across shots:** `letitedit_match_shots` evens out exposure and white balance against a hero shot; never
  shift the product's true colour, since its colour is a claim too. Check: the product's colour in the render matches
  the source. [GEN]
- **Real reactions only:** a reaction belongs to the moment it is cut to (letitedit-craft's honesty boundary). [GEN]

## 7. Openings and endings
- **Brand-first openings are allowed:** the product, logo or price in frame one works when it is the recognisable
  draw; the first seconds carry the emotional promise, and even a business-to-business film can open on mystery.
  Check: muted, the first 2-3 s (Short) or 5 s (long) say what it is and how it feels. [JH 10:00]
  [ITE art:how-to-start-a-scene] [JH 2:34]
- **End on the call to action and the brand,** then stop; in a Short the CTA can be the last beat right after the
  payoff. Check: nothing but the CTA and brand follows the payoff. [JH 0:42] [GEN]

## 8. Gate settings
| Check | Long | Short |
|---|---|---|
| `cuts_per_min`, `longest_static_s` | advisory | advisory |
| `visual_change_first3s` | advisory | advisory |
| `first_speech_s` | off (music-led spots may have no speech) | off |
| `silence_first3s_s`, `silent_share` | advisory | advisory |
| `frame0_not_black` | advisory | on |
| `tail_silence_s` | advisory | on |

Loudness: web and social -14 LUFS, true peak <= -1 dBTP [GEN]; television -23 LUFS (EBU R128) or the broadcaster's own
spec [RES]. The brief's claims check stays critical. Critic questions: does every claim have proof on screen; is the
CTA clear and readable; does the energy fit the brand; is anything implied that isn't shown?

## 9. Common failures and how to check
| Failure | Check | Tag |
|---|---|---|
| A claim reworded, rounded or misspelled | the claims check; captions spelled as in `brief.claims` | [GEN] |
| A claim with no proof, or proof implied by an unrelated shot | the claim-to-proof table | [ITE gwyneGrX9Jw 26:53] |
| A CTA missing, unreadable or under the platform's buttons | frames with the covered areas drawn | [GEN] |
| A calm brand over-cut, or a crammed spot with no breath | gears against the feel words; the critic | [ITE A2RYo1xNSA4 08:03] [AOTC GNIP] |
| A musical swell over a claim | claims audible; music down under speech | [GEN] |
| An opening that doesn't show what it is | the muted opening test | [JH 2:34] |
| Colour jumping between shots, or the product's colour changed | the shot-match report; source against render | [GEN] |
| An invented arc, or a reaction taken from another moment | every turn and reaction maps to a real moment | [GEN] |

## 10. Evidence strength
Thin. The library has no lesson on ads, product video or brand assets. Sourced and transferable: a brand film's first
seconds carry its emotion and may open on mystery (an Inside The Edit article), frame one can show the brand, product
and price (Hoyos), cutting energy matched to the brand's audience (Inside The Edit), the teaser shape (a second-hand
Film Editing Pro trailer note), proof shots for key claims (Inside The Edit's missing-shots checklist), and commercial
cutters' urge to cram (Art of the Cut). Spot grammar, CTA placement, brand typography, honest product colour and claim
handling are [GEN]. Note that The Greatest Night in Pop's editors call fragment-splicing routine in commercials;
letitedit is stricter for claims. Uncollected candidates are listed in `sources.md`.
