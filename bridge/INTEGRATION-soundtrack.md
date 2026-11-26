# Integrating `letitedit_soundtrack` (soundtrack assembler)

New files (nothing else in the bridge was edited):

| File | What it is |
|---|---|
| `bridge/soundtrack.py` | The algorithm: song analysis, request validation, plan (runs, fixed points, beam search over bars, frame layout, gain envelope, edit ops), apply through the shared timeline apply, measurement of the rendered mix, a background-job kind. |
| `bridge/soundtrack_tools.py` | Thin MCP wrapper: `register(mcp, Image)` exposes `letitedit_soundtrack` (full contract in its docstring). |
| `bridge/tests/sound/test_soundtrack.py` | pytest suite (synthetic songs and projects; one melt round trip; one real-footage test skipped when the footage is missing). |

## 1. `letitedit_mcp.py`

Register the tool with the other `*_tools` modules, e.g. right after the review tools block (before `if __name__ == "__main__":`):

```python
# A deliberate score from one song: sections, hits on musical events, protected natural sound, the mix measured.
from soundtrack_tools import register as register_soundtrack
register_soundtrack(mcp, Image)
```

and add the name to the v2 tool set (`V2_NEW`, e.g. after `'letitedit_music_make',`):

```python
    'letitedit_soundtrack',
```

(It works on files and finds an open window by project itself, like the other v2 tools, so it belongs in `V2_NEW`, which is
also `UNSCOPED`. Not proposed for the `core` or `lean` sets.)

## 2. `letitedit_ai.py` (`_registry`)

Add the import next to the others and the module to the tuple that is registered:

```python
    import soundtrack_tools
```

```python
    for mod in (..., factlog_tools, review_tools, soundtrack_tools):
        mod.register(_Collect(), _SavedImage)
```

`sa.tool('soundtrack', project=..., song=..., ...)` then works. Optional convenience function (not added), for the module
docstring's list:

```python
def soundtrack(project, song=None, **params):
    """sa.soundtrack(project, song, sections, hits, protect, mode='plan'|'apply'|'measure'|'song', plan_id=...)"""
    import soundtrack as _st
    return _st.soundtrack(project, song, **params)
```

## 3. `tool_docs_v2.py` (`SHORT`)

```python
    'letitedit_soundtrack': "A deliberate score from one song: sections by energy, hits landed on downbeats, phrases or "
                          "drops, natural sound protected (deep duck or drop-out), no back-to-back loops; returns the "
                          "plan (edit ops, where each hit lands, joins) or applies it and measures the rendered mix.",
```

## 4. Changes described, not made

- **GUIDE.md** (Tools table): one row, e.g.
  `| letitedit_soundtrack(project, song, sections, hits, protect, start, end, repeat, max_stretch, mode, plan_id) | One
  song arranged as a score: material by section energy, hits landed exactly (by playing on, a short bar, a bounded
  speed change or a stop), protected ranges ducked deep or dropped out, repeat limits; plan first (edit ops, hit errors,
  a picture, an mp3 of the bed), then apply (refused if anything changed) and the mix measured from a melt render. |`
- **`{op: score}` and the soundtrack write the same thing** (the music clips' gain keys). Running `score` after
  `letitedit_soundtrack` replaces the soundtrack's envelope (its section levels and deep ducks are lost). Until `score` learns
  to leave such clips alone (their ids start with `st`; a `letitedit_ai:role` property would be cleaner), the guide and the
  letitedit-finish skill should say: one or the other per music track. Speech levelling (`{op: level}`) is compatible.
- **Pitch-kept speed**: `edit_script.build_producer` writes `warp_pitch=0`, so `max_stretch` (clip `speed`) moves the pitch
  (the plan reports the cents). An optional item field such as `pitch: keep` (writing `warp_pitch=1`) would let the
  stretch keep the pitch; the soundtrack would then set it. Default `max_stretch` is 0 for this reason.
- **Live windows**: applies go through `timeline_tools.apply_project`. When the project is open in Shotcut, a plan that
  has to add the Music track is a track-structure change, which `live_edit` rejects today; a saved project then falls back
  to the file apply and reload, an unsaved one is refused (the soundtrack itself refuses projects with unsaved changes,
  because the plan is made from the saved file). The native transaction in the implementation plan's FOUNDATION removes this.
- **The app's "Add music"** (musicpicker.cpp) marks its clips with `letitedit:music_volume` / `letitedit:music_duck`;
  the soundtrack replaces every clip on its track, so "Update the Music" no longer sees them. No change needed unless
  the two should cooperate.
- **Skills**: letitedit-finish (music) could point at `letitedit_soundtrack` for a deliberate score (song choice stays with
  `letitedit_library`; `mode='song'` shows the song's phrases, drops and energy to choose hit kinds and sections).
- **Background jobs**: `background=true` submits the job kind `soundtrack:job` (jobs.py resolves `module:function`
  kinds itself; nothing to register). Optional: add `soundtrack` to `LETITEDIT_JOB_KINDS`.

## 5. Caches and files

- `cache/soundtrack/songs/<content key>-b<beats per bar>-v<version>.json`: song analysis (beat grid, bars, energy,
  phrases, drops); invalidated by file content or `ANALYSIS_VERSION`.
- `cache/soundtrack/plans/<plan_id>.json`: every plan (applied by `plan_id`). A plan records the project's file hash,
  the song's size/time, the analysis versions and every footage file speech was measured on; `apply` refuses when any
  of them changed (`force=true` overrides).
- `cache/soundtrack/<plan_id>/`: `plan.png`, `music-bed.mp3` (the planned bed alone), and `measure-<time>/` with
  `music.mp3` and `mix.mp3` to listen to, `measured.png`, `measurements.json`. The 48 kHz float stems the
  measurement works on (about 23 MB a minute each) are deleted afterwards unless `measure(..., keep_audio=True)`.

## 7. Engine timing correction (worth knowing)

The render is measured against the plan piece by piece (cross-correlation of the music stem with the song). Some song
files are seeked imprecisely by the engine: the Grieg concerto MP3 in the library plays every clip 25 ms late at 30 fps
and 29-65 ms late at 29.97 fps, while ffmpeg's own seek and other MP3s with the same encoder delay are exact. When a
piece plays more than half a frame off, `apply` shifts its in/out points by whole frames with `set` ops (a second undo
step) and measures again (`options.correct_engine_offsets`, default on); measured residuals were -8 ms at 29.97 fps. A
song file replaced by a WAV/FLAC copy avoids it, but the tool never copies music, so it only reports and corrects.

## 6. Tests and acceptance runs

- `cd C:\LetItEdit\bridge && python -m pytest test_soundtrack.py -q`
- Real footage + library songs: `python C:\LetItEdit\cache\soundtrack-tests\run_cases.py all` (cases speech, protect,
  montage, long, unclear; projects in `cases\`, results in `results\<case>.json|txt`). Never opens Shotcut; the
  open-editor lookup is switched off there because those projects are never open.
