"""Every edit op letitedit_timeline_apply takes, in one place: its fields, which are needed, and what each does.

The same table checks a list of changes before anything is applied (`problems`, `check`) and is the listing that
`letitedit_guide('ops')` and `letitedit_guide('<op name>')` return (`text`), so the docs and the checks can't drift apart.
"""
from __future__ import annotations

LEVELS = 'talk | montage | quiet | swell | end, or a number of dB relative to the dialogue'

# name -> (summary, required fields, optional fields {name: what it does [default]})
OPS = {
    'insert': ('Put an item on a track.', ['track', 'item'], {
        'after': 'id of the item it goes after', 'before': 'id of the item it goes before',
        'at_start': 'true: first on the track', 'at': 'timeline time (s) on any track but the main picture track; '
        'the other items there keep their times',
        'overlap': "with at, when something already plays there: 'error' (refuse) [default] or 'next_track' (the next "
                   "track of the same kind named like it, '<track> 2', '<track> 3'..., made if needed; the result says "
                   "where it went)",
        'edge_mode': 'exact keeps numeric in/out times as given (the "clean cut:" note still names an edge the review will flag, with the nearest clean place); otherwise an edge that goes through a word, a word\'s tail or soft opening, or a sound moves to the nearest clean place (at most 0.6 s outward, 0.35 s inward, never adding or dropping another word; where the sound runs on, the quietest moment between two words), measured as the review measures it, and the reply\'s "clean cut:" note says what moved or what could not be made clean'}),
    'move': ('Move an item.', ['id'], {
        'track': 'the track it goes to [its own]', 'after': 'id', 'before': 'id', 'at_start': 'true', 'at': 'time (s)',
        'leave_gap': 'true: leave the space it came from empty', 'overlap': "as for insert ('error' | 'next_track')"}),
    'trim': ('Change where an item starts and ends in its source.', ['id'], {
        'in': 'source time (s) it starts at', 'out': 'source time (s) it ends at',
        'words': 'a phrase in the clip: cut on the gaps around it', 'near': 'with words: the source time to look near',
        'edge_mode': 'exact keeps numeric in/out times as given (the "clean cut:" note still names an edge the review will flag, with the nearest clean place); otherwise an edge that goes through a word, a word\'s tail or soft opening, or a sound moves to the nearest clean place (at most 0.6 s outward, 0.35 s inward, never adding or dropping another word; where the sound runs on, the quietest moment between two words), measured as the review measures it, and the reply\'s "clean cut:" note says what moved or what could not be made clean',
        'edge_reason': 'with edge_mode exact: why this time is kept (a frame chosen by picture, a beat, a sound left on '
                       'purpose); kept in the project journal, and the review quotes it beside a finding at that edge'}),
    'delete': ('Remove an item.', ['id'], {
        'close_gap': 'close the space [true on the main picture track, false elsewhere]'}),
    'set': ('Change any of an item\'s fields (null removes one).', ['id'], {
        '*': 'any item field: in, out, len, speed, reverse, transition, effects, graphic, ...',
        'edge_mode': 'as for trim: a clip\'s in and out get the same clean-cut rule unless exact',
        'edge_reason': 'as for trim'}),
    'effects': ('Replace an item\'s effects, or change the effects of many items in one op.', [], {
        'id': 'the item', 'ids': 'a list of items',
        'track': 'a track name (or names): every clip of a video or sound file on it',
        'effects': 'the list that replaces each item\'s effects',
        'add': 'effects added to each item\'s own: {fix: ...} entries after its other fixes, the rest at the end'}),
    'gap': ('Set the empty space next to an item; later items move with it.', ['id'], {
        'before': 'seconds before it', 'after': 'seconds after it'}),
    'add_track': ('Add a track.', ['name'], {'kind': 'video | audio [video]',
                  'after': 'insert just above this named track [at the top]',
                  'owner': 'the actor who owns the track (applies by other actors that change it are refused) [none]'}),
    'track': ('Settings of a whole track.', ['name'], {
        'gain': 'dB', 'duck': 'lower it under speech', 'hide': 'video | audio | both', 'effects': '[...] on the whole track',
        'owner': 'the actor who owns the track: applies by other actors that change it are refused; null clears it. '
                 'Only its owner changes or clears the owner of an owned track [unchanged]'}),
    'master': ('Whole-video effects and the final sound chain.', [], {
        'effects': '[{gain: dB or {keys}}, {loudness: {target, window, max_gain, min_gain, max_rate}}, '
                   '{limiter: {input_gain, limit_db, release_s}}, or any {filter, params}]; empty removes them'}),
    'aim': ('One effect on a chosen part of the video, made of a clip\'s, a track\'s or the whole video\'s effects, a mask, cut-out clips '
            'or an adjustment layer; the reply has before and after frames and how much changed where.', ['effect', 'on'], {
        'on': 'clip (one clip, whole; takes region) | all (every track, not captions) | below (an adjustment layer under `track`: '
              'any effect on the combined picture) | not_person (the footage, with a cut-out above it) | person (a cut-out, with the effect on it)',
        'effect': '{filter, params} (letitedit_effects); on: clip also takes any effect',
        'id': 'with on: clip, the item', 'track': 'with on: below, the track that stays untouched',
        'from': 'timeline seconds, with all, below, person, not_person (needed for the last two) [the start]',
        'to': 'timeline seconds, as from [the end]',
        'words': 'instead of from and to, a phrase said on the timeline: the stretch where it is said',
        'near': 'with words, the time to look near when it is said more than once [the first]',
        'pad': 'with words, seconds added at each end [0]',
        'name': 'with on: below, the block\'s name on the timeline',
        'region': 'with on: clip, a shape in the clip\'s own picture: {shape: rectangle | ellipse | triangle | diamond [rectangle], '
                  'box: [x0, y0, x1, y1] (fractions of the frame), or path: letitedit_track\'s rows [t, x0, y0, x1, y1, ...] (t in the '
                  'clip\'s source seconds), soft: edge softness 0-1 [0.1], invert: true changes everything but the shape}'}),
    'lift': ('An object comes out of the shot, holds, and goes back: letitedit_object makes the object; this puts it on a track with its '
             'moves as keys, and a still of the frame with the object filled in on a track below it for the background to go away.', [], {
        'object': 'the id from letitedit_object (needed unless id is given)', 'from': 'timeline time (s) the move out starts',
        'to': 'timeline time (s) it is back in place', 'words': 'instead of from and to: a phrase; near and pad as elsewhere', 'near': 'with words',
        'pad': 'with words', 'id': 'a piece of a lift already made: that lift again, with whatever else this op changes; the moves are rebuilt',
        'remove': 'with id: take the lift away', 'at': '[x, y] where the middle of the object sits during the hold, project pixels [middle, a little above centre]',
        'size': "the object's height during the hold, as a share of the frame's [0.62]", 'scale': 'instead of size: plate pixels to project pixels',
        'rotate': 'degrees turned during the hold (`axis_deg` from letitedit_object says how far it leans) [0]', 'arrive': 'seconds the move out takes [0.8]',
        'leave': 'seconds the move back takes [0.53]', 'background': 'fall (tips back and drops) | fade | none (no still: whatever is below shows) [fall]',
        'push': 'how much it grows during the hold, as a share [0.03]', 'track': "the object's track [Object]",
        'after': 'a new track goes just above this one [on top]'}),
    'adjust': ('An adjustment layer: a block on a track that changes everything below it in the stack and nothing above it, for as '
               'long as it lasts, with any picture effects. Burned-in captions are always above it. The reply has before and after '
               'frames and how much changed where.', [], {
        'effects': 'a list of effects (letitedit_effects), or effect for one', 'effect': 'one effect',
        'from': 'timeline seconds [the start]', 'to': 'timeline seconds [the end]',
        'words': 'instead of from and to, a phrase said on the timeline: the stretch where it is said',
        'near': 'with words, the time to look near when it is said more than once [the first]',
        'pad': 'with words, seconds added at each end [0]',
        'below': 'a video track: the block goes just under it, so that track and those above stay untouched [the top of the stack]',
        'above': 'a video track: the block goes just above it', 'name': 'its name on the timeline [Adjustment layer]', 'id': 'its id'}),
    'captions': ('A caption track.', ['track'], {
        'cues': '[{start, end, text}, ...]', 'from_speech': 'true: captions of everything said (runs after the other edits)',
        'chunk': 'sentence | short [short when animated, else sentence]', 'max_chars': 'characters per line [42]',
        'max_lines': 'lines per caption [2]', 'style': '{font, size, fill, outline (width or color), highlight, position, ...}',
        'animate': 'pop | karaoke | highlight | typewriter | bounce (word-by-word graphics on a video track)',
        'fix': '{heard: Written} spelling fixes (words or phrases; win over the style\'s)',
        'style_fix': 'false leaves out the style\'s spelling list (its captions.corrections, e.g. from My Looks), '
                     'applied to captions from speech [true]',
        'fillers': 'true keeps um/uh [false]', 'burn_in': 'true [true]',
        'align': 'given cues: each start and end set to the times of the words it shows on the timeline (cached '
                 'word times; text and grouping kept; a cue whose words are not heard near it keeps its times); '
                 'false keeps the given times [true]',
        'fit': "with settings.json self_checks on: after the apply, letitedit_caption_fit runs on the project with "
               "these arguments (its own; tracks: this op's track) and apply=true, then letitedit_caption_readability; "
               "the reply's self_check.captions holds both replies and one verdict (clear, or the problems). "
               "caption_fit's apply is an undo step of its own; it reads the saved file, so in a window whose edit "
               "isn't saved it doesn't run. {} or true for its defaults"}),
    'tighten': ('Keep a clip\'s spoken parts and cut its pauses.', ['id'], {
        'max_pause': 'longest pause kept (s)', 'pad_in': 's kept before speech', 'pad_out': 's kept after speech',
        'speed_up_over': 'pauses longer than this are sped up instead of cut (s)', 'speed_up': 'that speed'}),
    'score': ('Even out the speech clip by clip, then mix the music under it. Speech is where the words are (cached '
              'transcripts; the voice detector for files without one, with a warning); the result lists the '
              'pauses (gaps g1, g2...) the music can answer.', [], {
        'zones': f'[{{from: s, to: s, level: {LEVELS}, attack?: s, release?: s}}, ...] music levels for spans; '
                 'attack/release: that zone\'s own fall and rise [none]',
        'answer': "pauses the music comes up in instead of staying dipped (duet): [gap id 'g4' | time | the phrase the "
                  "pause follows | {gap | at | after: phrase, near?, level?, attack?, release?}] or 'auto' / {auto: "
                  "{min_pause: 2, spacing: 20, sentence: true, max_per_minute: 3}}; each rises after the last word "
                  "and is back down before the next, ramps scaled to the pause (rise <= 1/3, fall <= 1/4); pauses "
                  "under about 1 s are refused [none]",
        'end': 'seconds at the end at the "end" level [0]', 'level_voice': 'false leaves clip gains [true]',
        'levels': '{talk, montage, quiet, swell, end: dB} [talk -18, montage -6, quiet -24, swell -3, end -4]',
        'tracks': 'music tracks [tracks named Music...]', 'fade_in': 's where a song starts alone [1.5]',
        'fade_out': 's where a song ends alone [3]', 'crossfade': 's where songs meet [3]',
        'attack': 's of the dips under speech [0.3]', 'release': 's [0.9]',
        'merge_gap': 'speech gaps shorter than this stay dipped (s) [4]; answer opens chosen ones', 'dialogue_lufs': 'dialogue level [measured]',
        'voice_lufs': 'speech level target [measured]', 'target': 'speech level target',
        'under_voice_lu': 'with settings.json self_checks on: the measured distance of the music under the voice '
                          "while people talk (letitedit_check_audio's music_below_voice_while_talking_lu, stems on) "
                          'the talk level is set to reach, within 1 LU: the planned timeline is measured before the '
                          'apply and the talk level moved by the difference, up to two times; the reply\'s '
                          "self_check.score is check_audio's report on the project as written [-levels.talk: 18]",
        'measure': 'with self_checks on, false leaves the score unmeasured [true]'}),
    'level': ('Only the speech levelling of score.', [], {
        'target': 'LUFS', 'voice_lufs': 'LUFS', 'tracks': 'tracks'}),
    'split_edit': ("A J or L cut at the cut into item `id` (on a picture track): its sound starts before its picture "
                   "(lead) or the clip before it is still heard under its picture (lag). The moved sound is the same "
                   "file at the same source time on an audio track (in sync with its picture), the covered sound is "
                   "silenced (a split_mute Gain/Volume), and the two cross over at the sound cut. Every later edit "
                   "rebuilds it (trims, ripples, tighten); deleting either clip or putting something between them "
                   "removes it. Refused past the source's handles, naming the most possible.", ['id'], {
        'lead': "J cut: id's sound starts this many seconds before its picture (0 removes the split edit)",
        'lag': "L cut: the sound of the clip before id runs on this many seconds under id's picture (0 removes it)",
        'move': "'sound' (the picture cut stays; the sound reaches into the file beyond the clip's edge) [default] | "
                "'picture' (the sound cut stays; the picture cut moves later for lead, earlier for lag: the clip's "
                "own picture handle is used)",
        'fade': 'seconds the two sounds cross over at the sound cut, equal power [0.1; at least 1 frame]',
        'track': "audio track for the moved sound [J/L cuts, added at the end if missing]",
        'drop_words': "true: allowed to cover words of the other clip's sound [false: refused, naming the words and the "
                      "longest split that keeps them]"}),
    'multicam': ("A camera-switched cut of several synced angles of one talk (cameras that filmed the same moment), as one "
                 "change. The sound is the main picture track, uncut: its clips come from one angle. The switched pictures "
                 "are muted clips of the other angles at the same moment, on a video track just above it, with gaps where "
                 "the main track's own angle is the one shown. Each shot is the speaker's close-up while one person "
                 "talks, the wide for back-and-forth, talking over each other, laughter and pauses, and a cutaway (a "
                 "reaction of the listener or the wide) in a shot longer than max_shot_s; an angle is used only inside "
                 "the time it recorded (else the next one that shows them: their single, a wide, any angle showing "
                 "them). Speaker changes cut lead_s before the first word, cutaways in a pause between words. Every "
                 "angle clip carries its sync record: later edits to the main track (trim, delete, tighten, move) put "
                 "it back on the moment it shows, split where the main track was cut. Running it again over a range "
                 "replaces that range of its track. The reply lists the shots, the time per angle and any angle that "
                 "ran out.", ['angles'], {
        'angles': "[{file, at: sync seconds where the file's start sits (letitedit_sync's at) [0], speed: letitedit_sync's "
                  "speed [1], shows: [speaker names or ids seen in it] (two or more: a wide), name [the file name]}]",
        'sound': "the angle whose sound plays: 'best' (measured: the widest speech-to-noise spread with the speakers at "
                 "the most even level, no clipping) [best when the main track is laid by this op; otherwise the main "
                 "track's clips as they are]; an angle name or file re-points the main track's angle clips to it, "
                 "same moments",
        'source_from': 'sync seconds: lay the sound angle on the main track from here (replacing what is there) '
                       "[the main track as it is; an empty main track gets the sound angle from where a wide starts]",
        'source_to': 'sync seconds: ... to here [the end of the sound angle]',
        'from': 'timeline seconds: cut only from here [the start]', 'to': 'timeline seconds: ... to here [the end]',
        'speech': '[{who, from, to}] sync seconds: who talks when [the speaker words (letitedit_speakers) of '
                  'speech_from]',
        'speech_from': "an angle (name or file) whose letitedit_speakers words say who talks when [the main track's "
                       "angle that has them]",
        'track': 'the video track for the angle clips, put just above the main track if new [Angles]',
        'pins': '[{from, to, angle}] timeline seconds: these moments on this angle, whatever the rules say',
        'min_shot_s': 'shortest shot; shorter ones join a neighbour [1.5]',
        'max_shot_s': 'longest shot before a cutaway [12]',
        'lead_s': "a cut to a new speaker comes this long before their first word, inside the pause [0.15]",
        'quick_s': 'turns shorter than this, three or more in a row by two or more people: on the wide [2]',
        'reset_s': 'a pause with nobody talking at least this long: on the wide [2.5]',
        'merge_gap_s': "one speaker's words closer than this are one turn [0.8]",
        'reaction_every_s': "a long shot's cutaway is the listener's reaction when the last reaction was at least "
                            "this long before, else the wide; 0: no reactions [20]",
        'reaction_s': "a reaction cutaway's length [2]", 'wide_s': "a wide cutaway's length [4]",
        'snap_s': 'how far a cutaway moves to land in a pause between words [1.5]',
        'hide_jump_cuts': 'true: where the main track is cut inside a shot (a jump in the talk), the shot changes '
                          'angle there when both sides are at least jump_cut_min_s [true]',
        'jump_cut_min_s': 'see hide_jump_cuts [2]',
        'clear_stacks': "true: full clips of the angles on other video tracks (letitedit_sync's project stacks one "
                        "per track) are taken off, as they would cover the cut [true]"}),
    'declick': ("A one-frame audio ramp on both sides of every straight sound cut (fade_out_audio / fade_in_audio "
                "of `frames` frames), so butted clips can't click; run it once the cut is final. Leaves music "
                "tracks, gaps, transitions, split edits, muted clips and edges that already fade alone.", [], {
        'frames': 'fade length in frames, the level ramps over frames - 1 of them [2]',
        'floor_db': 'level at the edge frame; -60 is silence and opens a short hole [-24]',
        'tracks': 'only these tracks [every non-music track]', 'skip_tracks': 'tracks to leave alone [none]'}),
    'look': ('Select Look defaults; existing timeline effects stay as they are.', [], {'id': 'an offered Look id, or null for neutral defaults'}),
    'popups': ("Pop-ups triggered by spoken words: every entry of the project's Look (popups.entries), the "
               "project's own list (<project stem>.letitedit/popups.json) and `entries`, found in what is said on the "
               "finished timeline, placed on a video track with their sounds on an audio track (runs after the other "
               "edits). An entry: {words: [phrases], asset: {image | emoji | text | graphic | motion}, position, size, "
               "in, out, hold_s, sfx, max_per_video, cooldown_s, offset_s} (LOOK-SETTINGS.md). Matching ignores case, "
               "punctuation, spacing and a possessive 's ('letitedit' matches 'let it edit'). The result lists what "
               "fired where and what was not placed and why.", [], {
                   'entries': '[{words, asset, ...}] extra entries for this run [none]',
                   'look': "true: the project's Look entries; false: leave them out; or a Look id [true]",
                   'project': "true: the project's own popups.json [true]",
                   'only': '[entry ids] only these', 'start_s': 'from this timeline time [start]',
                   'end_s': 'up to this timeline time [end]',
                   'track': "video track [the Look's fx.track, 'Effects']",
                   'sfx_track': "audio track for their sounds [the Look's fx.sfx_track, 'Effect sounds']",
                   'min_gap_s': "seconds between any two pop-ups [the Look's, 1.5]",
                   'max_total': "most pop-ups in the video [the Look's, no limit]",
                   'replace': 'true: the pop-ups an earlier {op: popups} placed go first [true]',
                   'sfx': 'false: no sounds [true]',
                   'check': 'warn | strict | off: the style rules measured as for fx [warn]',
                   'platform': "covered areas checked: a platform id or 'phone' [the Look's fx.safe_zone]"}),
    'fx': ("A batch of effects at moments, planned by you or from cached words with auto: true, placed as one change: things popping up as they are "
           "mentioned, text pops, zoom punches, shakes, flashes, glitches, whooshes, sounds, count-ups, place tags, "
           "b-roll cutaways, light leaks, any graphic or motion block, transitions. Each item names a style preset "
           "(the Look's `effects`: kind, look, sound, rules) or a kind, and the moment: at (timeline s), words (a "
           "phrase said on the timeline) or id (a clip). The style's rules are measured on the result (density, "
           "duration, triggers, placement against faces, captions and the platform's covered areas, never rules) "
           "and listed; the reply has frames at every effect and each sound's peak offset from its target "
           "(125 ms either way), or an unmeasured/missing-target reason. Kinds and fields: LOOK-SETTINGS.md, 'Effects'.", [], {
               'items': 'effects [{at | words | id, preset | kind, sound_target?: {kind: in | out | cut | caption_word | story | effect, '
                        'id?, word?, index?, at: intended timeline s, offset?: seconds into effect clip}, ...}]. '
                        'Sounds retain their target record; without one, placement records its picture event or spoken story moment '
                        '[empty when auto is true]',
               'auto': 'true: candidate effects from cached words/cuts and Custom slider ceilings [false]',
               'model': 'local 3D file for automatic 3D effects; none is invented [none]',
               'sync_sounds': "true | {look?, rules?, voice_dbfs?, transitions?: cutaways | all_cuts, roles?, sounds?}: a "
                              "click on each cutaway transition (or every cut) and a key tick on each caption word, "
                              "from a Look's synced-sound rules (offset_s, peak_over_voice_db, min_gap_s, use); levels "
                              "are set against voice_dbfs, the speech RMS of the speaker clips [measured from them, "
                              "else -18.3], by the click's own 5 kHz-and-up peak where the rule has "
                              "hf_peak_over_voice_db (music cannot hide it) and its full peak; none are placed where "
                              "two would sit closer than min_gap_s; source peaks are aligned to exported picture/word arrivals "
                              "plus offset_s, with a target record and measured offset per sound",
               'lighting': "true | {face_ev?, face_gamma?, room_ev?, window?, feather?}: live lighting on every clip "
                           "of the main picture track that plays a video file (the speaker): engine filters on the clip "
                           "that the editor shows and a person can change (Mask: Simple Shape and Color Grading). A soft "
                           "oval, keyframed from face detections every 0.25 s, follows the biggest face and lifts it "
                           "(face_ev: EV of gain, 0 to 1; face_gamma: midtone lift, 1 to 1.5), and the room outside a "
                           "wider, lower oval is darkened (room_ev, 0 to -3 EV). window: [width, height] of the face "
                           "oval in face widths and heights; feather: 0.05 to 1. Defaults: face_ev 0.03, face_gamma "
                           "1.2, room_ev -1.3, window [1.7, 2.0], feather 0.8. With no settings given, the chosen Look sets them: its "
                           "lighting.json live_settings as they stand, or the face-to-room separation measured in its reference "
                           "(live.reference_stops) reached from each clip's own measured separation by room_ev (the reply "
                           "lists each clip's figures); settings given here win. Gain is one multiplier on all three "
                           "channels, so hue and colour strength hold. A clip already lit live is lit again from the "
                           "settings; a clip with no face found is left unlit and named. Keyframe times follow the clip's "
                           "in point, so run it again after the picture has been trimmed. A baked render, a cut-out or a "
                           "whole-picture setting is not offered. lighting.check_live(project) renders the "
                           "main track with and without the lighting and measures the face box (brighter or equal, hue "
                           "shift at most 3 degrees, colour strength within 15%, newly clipped skin at most 1%) and the "
                           "room's change in brightness",
               'grade': "true | {strength?, remove?}: the chosen Look's measured colour grade (its grade.json; a Look "
                        "learned before grades were kept has one worked out from its lighting.json) on every clip of "
                        "footage on any picture track, with or without a face: a LUT (3D) filter on each clip, which the "
                        "editor shows and a person can change or take off. Each clip is measured (five frames between its "
                        "in and out points) and matched to the reference samples nearest it in brightness: black level, "
                        "median and highlights through one smooth tone curve (the median moves at most 1 stop, the curve's "
                        "slope stays between 0.4 and 2), colour strength (HSV saturation, scaled 0.6 to 2.2) and the "
                        "colour lean of shadows, mid-tones and highlights (at most 0.06 per channel, no change in "
                        "brightness); skin-tone hues (the vectorscope's skin line, orange and red with it) get a quarter of the "
                        "lean and about half of the colour-strength change. The reply gives each clip's median, "
                        "highlights and saturation before and after. strength: 0 to 1 [1]; remove: true takes the "
                        "grade off. Pictures, graphics, colour clips and made clips are not graded. A Look without "
                        "measurements has no grade here: its colour is in its recipe and Theme. Run it again after "
                        "the picture has been trimmed",
               'pace': "true | {from?, to?, keep?, anchor?, beat_s?, lengths?}: the chosen Look's shot lengths cut "
                       "into the main picture track: each footage clip of the stretch takes a length of the reference's "
                       "body shots at the same place (the reference's body: its end hold and last four shots set apart; a "
                       "stretch with more clips than that part of it goes on into the reference's next shots), each "
                       "quarter of the stretch holding that quarter's lengths in a new, seeded order, so its cut times "
                       "differ from the reference's (the reply gives the share within 0.1 s of them); a stretch that "
                       "runs to the main track's last footage clip ends on the reference's last four shots and its end "
                       "hold, in order. Explicit lengths are kept in their order. from, to: timeline seconds [the footage clips, after a first clip held longer than any "
                       "body shot]; keep: ids left as they are; anchor: in (the clip keeps its start in its file) or "
                       "middle (keeps the middle of what it shows) [in]; beat_s: a beat in seconds, lengths become "
                       "whole half-beats; lengths: seconds in order instead of the Look's. A clip whose file is too short "
                       "keeps what it has and is named; items on other tracks move with their picture. The reply gives "
                       "the stretch's length before and after and, when it got shorter, about how many more shots fill "
                       "the time it had",
               'cut_flashes':"true | {len?, edges?, track?, sides?}: the picture goes negative for two frames (len, .03 to .2 s; "
                              "the engine's Invert filter on the first or last frames of the clip) at every edge where "
                              "a full-frame, opaque b-roll clip meets the speaker; the edge between two touching "
                              "cutaways, the video's start and end, and clips that are not opaque full-frame get none "
                              "(the reply lists them). edges: both (default), in or out. Planned from the b-roll clips "
                              "already on the timeline, so place the cutaways first; calling it again replaces the same "
                              "edges' flashes. sides: both (default) also inverts the speaker's picture for the same frames "
                              "right before an in-cut or right after an out-cut (a block on an adjustment track just under the "
                              "b-roll track, named \"Cut flash (speaker side)\"); cutaway flashes the b-roll's frames only. The "
                              "transition click for the same edges is sync_sounds in the same op",
               'camera_moves': "true | {look?, spread?, follow_motion?, drift_per_s?, max_scale?, push?, ease?, "
                               "moving_target?, seed?, measure?, keep_existing?}: a move on each cutaway, chosen from pan_left, pan_right, "
                               "tilt_up, tilt_down, push_in, pull_out (the camera pans right when the picture slides "
                               "left). Each clip's own image motion is measured first: a clip that moves enough gets "
                               "none; a static shot or a picture always gets a chosen move, pans and tilts included; "
                               "a clip that moves a little gets a chosen move that does not oppose it, or, with "
                               "follow_motion: true, its own direction topped up. No move repeats the one before it, "
                               "in any mode, and a move already used is less likely; the Look's measured spread and "
                               "drift speed set the choice (moving_target: a share of cutaways to move, only when "
                               "given). Calling it again chooses every cutaway's move afresh, so the sequence stays varied "
                               "after cutaways are swapped (keep_existing: true leaves clips that already have a moving "
                               "size and position alone). The reply names "
                               "each clip's own motion, its move and why. Also an item {kind: camera_move, id, move}",
               'check': 'warn (place and list broken rules) | strict (place nothing when a rule is broken) | off [warn]',
               'look': "a Look id for the presets [the project's Look]",
               'platform': "covered areas checked: a platform id or 'phone' (Shorts + TikTok + Reels) [the Look's "
                           "fx.safe_zone]",
               'track': "overlay track [the Look's fx.track, 'Effects']",
               'sfx_track': "sound track [the Look's fx.sfx_track, 'Effect sounds']",
               'broll_track': "cutaway track, made just above the main track [the Look's fx.broll_track, 'B-roll']"}),
    'hook': ("Swap the opening for a hook candidate from letitedit_hooks (one undo step): cold_open puts the moment "
             "first (a hook placed earlier is replaced; the moment also stays where it is in the cut) with its text "
             "on the 'Hook text' track; start_here starts the cut at the moment (in-cut moments only). Candidate "
             "'h0' (the current opening) takes an added hook out again.", ['candidate'], {
                 'text': "index of the candidate's text option, your own words, or null for none [none]",
                 'mode': 'cold_open | start_here [cold_open]', 'len': 'seconds of the moment kept [its length]'}),
}
COMMON = {'op', 'ripple', 'label', 'note'}          # read on any op (ripple: false keeps other tracks where they are)
ZONE_KEYS = {'from', 'to', 'level', 'attack', 'release'}
ANSWER_KEYS = {'gap', 'at', 'after', 'near', 'level', 'attack', 'release', 'auto'}
AUTO_KEYS = {'min_pause', 'spacing', 'sentence', 'max_per_minute', 'level', 'attack', 'release'}


def _answer_problems(spec):
    if spec is None:
        return []
    items = spec if isinstance(spec, list) else [spec]
    out = []
    for n, a in enumerate(items, 1):
        if a == 'auto' or isinstance(a, (str, int, float)) and not isinstance(a, bool):
            continue
        if not isinstance(a, dict):
            out.append(f"answer[{n}] is a pause id ('g4'), a time, a phrase, 'auto' or a dict; got {a!r}")
            continue
        extra = [k for k in a if k not in ANSWER_KEYS]
        if extra:
            out.append(f"answer[{n}]: unknown {', '.join(extra)} (an answer takes {', '.join(sorted(ANSWER_KEYS))})")
        if 'auto' in a and a['auto'] not in (True,) and not isinstance(a['auto'], dict):
            out.append(f"answer[{n}]: auto is true or {{{', '.join(sorted(AUTO_KEYS))}}}")
        if isinstance(a.get('auto'), dict):
            bad = [k for k in a['auto'] if k not in AUTO_KEYS]
            if bad:
                out.append(f"answer[{n}].auto: unknown {', '.join(bad)} (it takes {', '.join(sorted(AUTO_KEYS))})")
        if 'auto' not in a and not any(a.get(k) is not None for k in ('gap', 'at', 'after')):
            out.append(f'answer[{n}] {a!r}: needs gap, at or after (which pause)')
    return out


def _zone_problems(zones):
    if zones is None:
        return []
    if not isinstance(zones, list):
        return [f'zones is a list of {{from, to, level}}; got {type(zones).__name__}']
    out = []
    for n, z in enumerate(zones, 1):
        if isinstance(z, (list, tuple)) and len(z) in (2, 3):
            continue                                 # [from, to] or [from, to, level]
        if not isinstance(z, dict):
            out.append(f'zones[{n}] is {{from: s, to: s, level: ...}} or [from, to, level]; got {z!r}')
            continue
        miss = [k for k in ('from', 'to') if k not in z]
        extra = [k for k in z if k not in ZONE_KEYS]
        if miss or extra:
            out.append(f'zones[{n}] {z!r}: ' + '; '.join(
                ([f"needs {', '.join(miss)}"] if miss else []) + ([f"unknown {', '.join(extra)}"] if extra else []))
                + f' (a zone is {{from: s, to: s, level: {LEVELS}}})')
    return out


def problems(ops):
    """Every problem with a list of changes, as sentences naming the op, the field and what is accepted."""
    out = []
    if not isinstance(ops, list):
        return [f'changes is a list of ops; got {type(ops).__name__}']
    for n, op in enumerate(ops, 1):
        where = f'change {n}'
        if not isinstance(op, dict):
            out.append(f'{where} is {op!r}; each change is a dict like {{op: trim, id: ..., out: 12.5}}')
            continue
        name = op.get('op')
        if name not in OPS:
            out.append(f"{where}: unknown op {name!r}; ops: {', '.join(OPS)} (letitedit_guide('ops') lists their fields)")
            continue
        where = f'change {n} ({name})'
        summary, required, optional = OPS[name]
        miss = [k for k in required if op.get(k) in (None, '')]
        if miss:
            out.append(f"{where}: needs {', '.join(miss)}"
                       + (" (track: a track's name, as letitedit_timeline_read lists them)" if 'track' in miss else ''))
        if '*' not in optional:
            extra = [k for k in op if k not in COMMON and k not in required and k not in optional
                     and not str(k).startswith('_')]
            if extra:
                out.append(f"{where}: unknown field{'s' if len(extra) > 1 else ''} {', '.join(extra)}; it takes "
                           f"{', '.join(required + list(optional)) or 'no fields'}")
        if name == 'insert' and 'item' in op and not isinstance(op['item'], dict):
            out.append(f'{where}: item is a dict like {{clip: path, in: s, out: s}}; got {op["item"]!r}')
        if name in ('insert', 'move') and op.get('overlap') not in (None, 'error', 'next_track'):
            out.append(f"{where}: overlap is 'error' or 'next_track'; got {op['overlap']!r}")
        if name == 'score':
            out += [f'{where}: {p}' for p in _zone_problems(op.get('zones'))]
            out += [f'{where}: {p}' for p in _answer_problems(op.get('answer'))]
        if name == 'split_edit':
            out += [f'{where}: {p}' for p in _split_problems(op)]
        if name == 'effects':
            if not any(op.get(k) for k in ('id', 'ids', 'track')):
                out.append(f'{where}: needs id, ids or track')
            if ('effects' in op) == ('add' in op):
                out.append(f'{where}: takes effects (replaces each item\'s effects) or add (adds to them), one of the two')
        if name == 'multicam':
            if not isinstance(op.get('angles'), list) or len(op['angles']) < 2 or                     not all(isinstance(a, dict) and a.get('file') for a in op['angles']):
                out.append(f'{where}: angles is a list of two or more {{file, at, shows}}')
            if op.get('pins') is not None and not isinstance(op['pins'], list):
                out.append(f'{where}: pins is a list of {{from, to, angle}}')
            if op.get('speech') is not None and not isinstance(op['speech'], list):
                out.append(f'{where}: speech is a list of {{who, from, to}} in sync seconds')
        if name == 'fx':
            if op.get('auto') not in (None, True, False):
                out.append(f'{where}: auto is true or false')
            items = op.get('items')
            if (not isinstance(items, list) or not items) and not (op.get('auto') or op.get('sync_sounds')
                                                                   or op.get('camera_moves') or op.get('lighting')
                                                                   or op.get('grade') or op.get('cut_flashes')
                                                                   or op.get('pace')):
                out.append(f'{where}: items is a list of {{at | words | id, preset | kind, ...}}')
            elif isinstance(items, list) and items:
                for k, it in enumerate(items, 1):
                    if not isinstance(it, dict):
                        out.append(f'{where}: item {k} is a mapping like {{at: 3.2, preset: money_pop}}')
                    elif not (it.get('preset') or it.get('kind')):
                        out.append(f'{where}: item {k} needs preset (a style effect) or kind')
                    elif it.get('at') is None and not it.get('words') and not it.get('id'):
                        out.append(f'{where}: item {k} needs at (timeline s), words (a phrase said) or id (a clip)')
            if op.get('check') not in (None, 'warn', 'strict', 'off'):
                out.append(f"{where}: check is warn, strict or off; got {op['check']!r}")
        if name == 'popups' and op.get('entries') is not None and not isinstance(op['entries'], list):
            out.append(f'{where}: entries is a list of {{words, asset, ...}}')
        if name == 'hook' and not isinstance(op.get('candidate'), (str, dict)):
            out.append(f"{where}: candidate is an id from letitedit_hooks ('h3') or {{source: {{clip, in, out}}}}")
        if name == 'hook' and op.get('mode') not in (None, 'cold_open', 'start_here'):
            out.append(f"{where}: mode is cold_open or start_here; got {op['mode']!r}")
    return out


def _seconds_ok(v):
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return v == v and v >= 0
    try:
        import letitedit.timeline.edit_script as edit_script
        return edit_script.to_seconds(v) >= 0
    except (ValueError, TypeError):
        return False


def _split_problems(op):
    out = []
    given = [k for k in ('lead', 'lag') if op.get(k) is not None]
    if not given:
        out.append('needs lead (a J cut: the sound of id starts before its picture) or lag (an L cut: the sound of '
                   'the clip before id runs on under its picture), in seconds')
    elif len(given) == 2:
        out.append('give lead or lag, not both: one cut has one sound cut (lead moves it earlier, lag later)')
    for k in given:
        if not _seconds_ok(op[k]):
            out.append(f'{k} is seconds (0 or more); got {op[k]!r}')
    if op.get('move') not in (None, 'sound', 'picture'):
        out.append(f"move is 'sound' or 'picture'; got {op['move']!r}")
    if op.get('fade') is not None and not _seconds_ok(op['fade']):
        out.append(f"fade is seconds (0 or more); got {op['fade']!r}")
    if op.get('drop_words') not in (None, True, False):
        out.append(f"drop_words is true or false; got {op['drop_words']!r}")
    if op.get('track') is not None and not (isinstance(op['track'], str) and op['track'].strip()):
        out.append(f"track is an audio track's name; got {op['track']!r}")
    return out


def check(ops):
    """Raise one ValueError listing every problem, before anything is applied."""
    found = problems(ops)
    if found:
        raise ValueError('changes not applied: ' + ' | '.join(found))


def text(name=None):
    """The listing: every op (name=None) or one op, with its fields."""
    names = [name] if name else list(OPS)
    lines = [] if name else ['# Edit ops for letitedit_timeline_apply (`changes`)', '',
                             'Every op takes `ripple: false` (other tracks keep their times). Required fields first.', '']
    for k in names:
        summary, required, optional = OPS[k]
        fields = ', '.join(required + [f'{f}?' for f in optional if f != '*'] + (['...fields'] if '*' in optional else []))
        lines.append(f'- `{{op: {k}{", " + fields if fields else ""}}}`: {summary}')
        for f, what in optional.items():
            lines.append(f'    - `{f if f != "*" else "any field"}`: {what}')
    return '\n'.join(lines)
