# Platform profiles

One JSON file per platform, read by `bridge\platforms.py` and the MCP tool `letitedit_platforms`.
Most values were checked on 2026-10-19 (the four profiles added later, and the feed profiles' `images`, on 2026-11-19). Platforms change their specs and apps without notice; the `checked` date on
each value says when it was last read.

| File | Platform |
|---|---|
| `youtube.json` | YouTube (long-form) |
| `youtube_shorts.json` | YouTube Shorts |
| `tiktok.json` | TikTok |
| `instagram_reels.json` | Instagram Reels |
| `instagram_feed.json` | Instagram feed video (new video posts are shared as reels since July 2022) |
| `facebook_reels.json` | Facebook Reels |
| `facebook_feed.json` | Facebook feed video (every new video is shared as a reel since June 2025) |
| `x.json` | X (Twitter) video |
| `instagram_story.json` | Instagram Stories (pictures and videos up to 60 s) |
| `facebook_story.json` | Facebook Stories (pictures and videos up to 60 s) |
| `tiktok_photo.json` | TikTok photo posts (photo carousels) |

The feed profiles and the Story and photo profiles also have `images` (picture sizes, formats, and the most photos a
post takes). The profiles added on 2026-11-19 carried many `unconfirmed` values (their pages refused automated reading);
the ones Buffer's help centre gives were checked against it on 2026-11-18 and are now `posting-service`.

## Fact objects

Every value is an object:

```json
{"value": 2200, "source": "https://...", "checked": "2026-10-19", "status": "official", "note": "..."}
```

- `value`: the fact; `null` when the platform does not publish it.
- `source`: the page the value came from (https URL).
- `checked`: date the source was read (YYYY-MM-DD).
- `status`:
  - `official`: the platform's own help, creator or developer page.
  - `official-ads`: the platform's own ad specifications (ads run in the same viewer as organic posts, but the
    figure is published for ads).
  - `posting-service`: the help pages of a service that posts for you (Buffer), giving its limits for posting
    through it. Where its figure and another source differ, the stricter one is kept and the note gives both.
  - `unconfirmed`: not found on an official page; `source` is the best other source (press, third-party tools).
  - `not documented`: the platform publishes nothing on it; `value` is `null`.
- `note` (optional): context, conflicting figures, or the other sources used.
- `confidence` (safe zones only): `medium` or `low`, or `n/a` when there are no zones.

## Top-level fields

| Field | Contents |
|---|---|
| `id`, `name`, `schema` (`letitedit-platform/1`), `checked` | identity |
| `video` | aspect ratios, resolutions, frame rates, min/max length (s), max file size (bytes), container, codec, bitrates |
| `audio` | codec, sample rate, bitrate, `loudness_normalisation` (integrated LUFS where known) |
| `safe_zones` | fact whose `value` is a list of `{name, x, y, w, h}` rectangles: the areas of the frame covered by the app's buttons, captions and account row, as fractions of the frame's width and height measured from the top-left corner |
| `captions` | facts about caption and text placement (and YouTube end screens) |
| `thumbnail` | thumbnail / cover size, format and file-size facts |
| `text_limits` | title, caption, description, tag, hashtag and mention limits |
| `export_preset` | the export values `preset_for()` returns: `width`, `height`, `fps` (number or `"source"`), `container`, `vcodec`, `pix_fmt`, `video_bitrate_kbps`, `acodec`, `audio_bitrate_kbps`, `sample_rate_hz`, `loudness_lufs` (plus optional extras) |

Validation (`platforms.validate(profile)`) checks the required fields, that every value under the fact sections is a
fact object with an https source, a date and a known status, that safe-zone rectangles lie inside 0-1, and that the
export preset has every field.

## Adding or updating a platform

Write `<id>.json` with the fields above; `python -m unittest test_platforms` in `C:\LetItEdit\bridge` validates it.
