# Look: Big Letters Behind You

Style: talking head, Shorts/Reels/TikTok (9:16). Flavour: the person stays full size and in front, on their real footage.
On a few key words the room behind them drops away and the word takes the top of the frame, huge, running off the edges and
passing behind their head; then the room comes back. Never shrink them into a frame or border.

## What the viewer sees
- Most of the time: the plain talking head, cut tight, a calm two-word caption low on the chest.
- 2-3 moments in a 16 s Short, each on one spoken word or name: the room falls to a dark tint of the room's own colour in about 0.1 s and the word hits
  on the spoken word with a pop (it overshoots about 16%, settles, shakes a few pixels for 0.3 s, and the room lifts for an
  instant on the beat), then keeps creeping larger while the idea is spoken. The letters go first, then the room fades back in
  about 0.3 s.
- One design with the captions: the same family (Montserrat; Black for the big letters), the same letter colour, the same
  dark outline, and the caption highlight is the letters' shade colour. The colours come from the footage (next section); the
  type never changes.

## Colour comes from the footage
Brief it the way an editor would: look at the room, not at the speaker. The letters, their shade, the room-drop colour and the caption
highlight all follow the environment's main colours and feel, so a warm brass room and a blue beach come out differently.
1. Sample the clip every second or two (the stretches that are used), leave the person out (a person matte plus a margin of about
   25 px), and cluster what is left into four or five colours with their share; read the dominant hue, how saturated it is and how
   light or dark the room is. Note the feel in a word (warm and woody, cool and airy, neon, grey).
2. Build one small palette from the dominant hue: the room-drop colour (a very dark version of it, value about 0.10, saturation
   kept near the room's own); the accent for the letters' shade, the glow and the caption highlight (the same hue, pushed to
   saturation about 0.75 and value about 0.95 so it glows against the dark room); the letters and caption fill (near-white with a
   trace of the hue); an optional lighter tint of the room's own colour for the glow on a second moment.
3. Check at phone size: letters on the room at least about 12:1, accent on the room at least about 8:1, and the caption highlight on a black
   outline at least about 8:1 (the outline carries it over the shirt or whatever is behind). Make the accent lighter or more saturated
   until these hold. The room-drop colour may shift a little between moments; the letter and accent colours do not.
4. Dull or grey environment (little saturation, or a few small coloured things): do not invent a hue from noise. Take the strongest
   small colour that is part of the place (a sign, a door, a plant), or the footage's colour cast (a cool or warm grey), and use it
   at the same strengths; if there is truly none, use a neutral near-black room with warm-white letters and one accent from
   the product's or video's own brand colour. A very bright environment (snow, sky): the room drops to a dark tint of its hue, so
   the letters stay white; never put light letters on a light room.
Every video gets its own measured palette from steps 1 to 3; do not carry over another room's colours.

## Where it sits
- The letters' tops sit at about 7.5% of the frame height (clears the TikTok and YouTube Shorts top bars at 6-7%; it does NOT
  clear Instagram Reels' top 14%: where Reels matters the Look needs footage with headroom). Letter height about 10-15% of the
  frame; a one-line word runs about the full width, a longer word or two short lines a little wider than the frame.
- Keep the word readable around the person: position letters above head height rather than hiding half of them behind the head. The letters may run under the right-hand button column by design (they are background letters; the part to read is in the middle and left).

## How the AI makes it
- A code scene (`letitedit_code_scene`, a canvas drawn from the playhead time) on its own track, plus the person cut out on a
  track above it: `behind_person=true` on `create` places it, over exactly the same seconds. The scene is transparent outside the moment, so the real
  room shows before and after. Write it fresh for the words; the parameters that mattered: the word's lines, the room colour,
  the glow colour, hit time inside the scene, width of the widest line at rest, the letters' top.
- Draw shade, outline and ink on one layer and fade the layer once: fading each drawing separately lets the shade show through
  the ink (a doubled, stair-stepped look; it is the scene's own drawing, the export's alpha path is exact).
- Timing: the scene starts about 0.06 s before the word, the hit is 0.1 s in; hold about 1.0-1.5 s, ending in a pause. A low boom
  (about -6 dB, its own track) on the hit. Letters leave 0.12 s before the room does.
- Captions keep running, low and readable; the caption word for the big word is not removed (it doubles the word).

## Which words earn it
- The one idea a listener should repeat: the name of the thing, the turn ("quit"), the instruction ("direct"). Two or three per
  16 s, real quiet between them, never two in a row. Short words fill the top best; a long word gets smaller letters or runs off
  the frame; a two-line name loses its second line behind the face ("EDIT" shows only at its sides).

## Lessons from the earlier drafts (kept)
- Words at face height are unreadable; a thin band above the cap is clear but small; huge letters centred on the face show only
  half the word. Top-anchored, wall-to-wall letters showed the most.
- `text_behind` has no grow animation and one text per item; it worked only as a small word above the cap. Its `outline: none` crash is fixed.
- A music bed about 12-14 LU under the voice; `score` with `levels: {talk: -13}`; speech in vfx items is not counted as speech.

## Must not
- Do not shrink or box the person; do not put a word on their face. Do not use it on every phrase or on filler; no more than 3
  in 16 s. Do not leave letters half-faded over the real room.

## Weak spots
- Not for Reels' top 14%. The head still hides the middle of a word ("QU . T" at the lowest part); "EDIT" is mostly behind the face.
- One clip, one speaker; hands and fast movement untried; nobody has listened to the sound.
