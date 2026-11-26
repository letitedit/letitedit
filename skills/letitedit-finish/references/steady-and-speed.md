# Steadying a shot and changing its speed (letitedit-finish FINISH-1a and FINISH-1b)

Read in full before steadying a shot (`letitedit_fix` shake) or setting a clip's `speed`, ramp or slow motion.

**FINISH-1a Steady a shot only when shake is the problem.** Do: read `shake_px` in the clip's
`letitedit_fix` shake result (`measures.before`, px on a 480-wide frame; it also gives `motion_px`, the after-value and
a before/after sheet). Steady a shot that should look locked-off and shakes about 2 px or more; keep the default
vid.stab engine and `smoothing` 15; then require the after-value to be under half the before-value and look at the
sheet's 1:1 frames. Increasing smoothing can increase crop without improving steadiness;
large foreground motion can mislead the tracker. The crop is the static zoom that hides the borders (`optzoom` 1; 0 leaves
black edges, `crop: keep` keeps the borders); the subject and captions must stay inside it. The default `sharpen` makes the
sharpness number rise even on a soft result: judge by the frames. When: handheld b-roll meant to be steady, a walking
shot that wobbles. Not: tripod or already-steady talking heads, a pan or a deliberate handheld feel, shots where
something big moves in the frame. Check: the after-value, the sheet, and `letitedit_check_frames` of the real cut; revert
(`action: revert`) when it isn't clearly better. The first use downloads the vid.stab engine (184 MB): ask the person
first on a new PC. [OURS]

**FINISH-1b Speed changes: pitch, sound and slow motion.** Do: set `speed` on the clip (`{clip, in, out, speed}`; the
timeline length changes: 1x 0:00-0:04, 0.5x 4 s of source -> 8 s, 2x 8 s -> 4 s, 4x 8 s -> 2 s, as measured; read the
reply's length). The clip's own sound changes pitch with `speed` and keeps no compensation [OURS]. On a sped-up or slowed clip either
mute it (`mute`) and put music or an effect under it, or, when the speech must stay, make the clip as an ffmpeg item
(`{ffmpeg: {video: "setpts=0.5*PTS", audio: "atempo=2", inputs: [{clip, in, out}]}, len}`; listen for pitch artifacts); keep speech between 0.5x and 2x, and never speed speech
past what can be understood. Slow motion: a clip's `speed` below 1 repeats frames; at 0.25x of 30 fps there are only 7.5 fps of real motion. Source shot at 60 fps holds up to 0.5x. Frame
interpolation (`minterpolate` with `mi_mode=mci` in an ffmpeg item, before `setpts`) can make new intermediate frames but is expensive and can tear motion; inspect it rather than promising smooth slow motion. A ramp: `speed` is one number per clip, so cutting a clip into pieces of 1x, 1.5x, 2x
gives steps (each cut shows). A smooth ramp from 1x to Sx over D seconds of source is a video-only ffmpeg item
`setpts='log(1+K*PTS*TB)/K/TB'` with K = (S-1)/D, lasting ln(S)/K seconds (S 4, D 3: about 1.386 s); give it `mute` and put sound under it. After a speed change re-check captions and
sound timing (`letitedit_check_frames`, `letitedit_check_audio`); captions made before it are not re-timed by the speed
(do not assume retiming). When: a time-lapse stretch, a punchline beat, a quick montage cut. Not: speech the viewer must follow, a
change with no job. Check: the project's new length, the pitch (a person will hear a chipmunk at once), frames in motion.
[OURS]
