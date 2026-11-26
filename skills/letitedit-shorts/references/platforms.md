# Platforms, reframing and export

Read on demand from letitedit-shorts. Tags as in SKILL.md and `references/sources.md` (`[GEN]` and `[OURS]` as letitedit-craft defines them).

## Platform facts come from letitedit_platforms
`letitedit_platforms()` lists the profiles; `letitedit_platforms('tiktok')` (or `youtube_shorts`, `instagram_reels`,
`facebook_reels`) gives sizes, frame rates, length limits, covered areas with their confidence, caption facts, cover
sizes and title or caption limits, each with its source, status and the date checked. Use it instead of remembered
numbers. As read on 2026-10-27, for orientation only: YouTube Shorts run up to 3 min; Reels up to 20 min, but the
help pages say reels over 3 min are not recommended to new audiences; TikTok Creator Rewards counts videos of at
least one minute [YT]. The covered areas for Shorts and TikTok are unconfirmed third-party estimates; Reels' come
from Meta's ad specs.

## One edit per platform (Hoyos; low confidence)
| Platform | What she saw [JH 27:38-30:05] | What to change | Check |
|---|---|---|---|
| YouTube Shorts | older audience; slower, more story; her best about 34 s; under 30 s needed more than 100% retention on her channel [JH 17:38-18:43] | keep the story beats and a breath between them | the critic can retell it |
| TikTok | 10-20 s, dense with information, few jokes, made to scroll; over 30 s did poorly for her | cut to hook, mechanism and payoff; if the person earns Creator Rewards, 60 s or more on purpose | the gate's 57-60 s warning (TikTok only) |
| Reels | slightly older; muted viewing, so very visual with subtitles every second; easy to share | captions on all speech; the picture tells it muted; an ending worth sending | a fully muted watch |
| Facebook Reels | no source | treat like Reels [GEN] | as Reels |
The same idea, cut differently, did very well on one platform and poorly on another, then the reverse [JH 28:07].
The channel's own numbers, once it has them, replace this table [JH 6:29, 17:56].

## Making the versions
- From a long edit: `letitedit_versions(main, action='make', target='tiktok' | 'youtube_shorts' | 'instagram_reels' |
  'vertical', ranges=[[start, end], ...], name='tiktok')` makes `<main> - tiktok.mlt`; one version per platform,
  each with its own ranges (the TikTok one shorter). Later edits on the main come across with `action='sync'`.
- From a vertical master: versions with different ranges, or `letitedit_project_new(path, copy_of=master)`.
- Reframe settings (`reframe`): order ['given', 'track', 'action', 'centre'], fit 'fill' (crop) or 'fit' (whole
  picture), zoom 1.0, key_every_s 0.5, smooth_s 1.0, deadzone 0.03, min_score 0.3.
- **Keep an object in frame:** `focus={item_id: [x, y]}` (0-1 of the picture) or `[[t, x, y], ...]` for one that
  moves; or `letitedit_track(file, start, end, target=[x0, y0, x1, y1] or 'face')` and pass the result as `tracks`.
  Say in the plan which object it is and why (the part being fixed, the product, the face, the hand doing the step).
- When it cannot fit: fit 'fit' over a blurred fill, a split, or another shot; tell the person.
- Check: `letitedit_check_frames(version, every_s=1, platform='tiktok')` draws the covered areas; the object, the text
  and the captions stay clear of them in every frame checked.

## Export
- `letitedit_export(version, platform='tiktok')` applies the profile's bitrate cap, audio bitrate and sample rate and
  reports the platform's other published values beside the project's. Loudness defaults to -14 LUFS with a true
  peak of -1 dBTP (the web deliverable). Name each file by platform.
- `letitedit_export_job(job_id, wait_s=...)` until done, then `letitedit_review_bundle(video, project=version,
  brief=..., critic='run')` per file.
- Never upload another app's download with its watermark; export each platform's file from the project [GEN].

## What the gate checks on a short (gate.py's table; letitedit-gate owns it)
- Blocking: the 1080x1920 size; loudness for the deliverable (web -14 LUFS +-1); true peak <= -1 dBTP.
- Advisory: the mode's pace checks (a story short: >= 12 cuts a minute, longest static shot <= 4 s unless a
  `hold:` marker covers it, a picture change by 3 s, first speech by 1 s when dialogue drives, <= 0.5 s of silence
  in the first 3 s, <= 15% silence); frame 0 not black; <= 0.6 s of silence at the end; the TikTok 57-60 s warning
  on TikTok cuts only. Montage and creative shorts have no pace checks; documentary and travel shorts skip the
  opening ones.
- A brief can set its own pace numbers (`pace`: {"cuts_per_min": 20}), which then block, or switch a check on or
  off; a local `reference` video sets the cut rate (at least 0.8x its own).

## Metadata
- Title: the hook, 40-60 characters, the main keyword early [GEN]. Caption: hook + context + 3-5 hashtags [GEN].
- Disclose an AI voice or realistic AI visuals where the platform asks for it [YT].
- One call to action at most, inside the payoff; shares may matter (her hunch, no data) [JH 35:13].
- Scheduling and posting are the person's (their scheduler), not the editor's.
