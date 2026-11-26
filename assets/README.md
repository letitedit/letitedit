# letitedit asset library

The pictures and sounds letitedit's effects place: emoji, icons, stickers, graphics, transitions, sound effects and
music, in one searchable index with each file's licence. Code: `bridge\assets.py` (index, search, resolve, previews),
`bridge\assets_tools.py` (the `letitedit_assets` tool), `bridge\graphics_templates\asset_sticker.py` (animations on
screen). How styles name assets and how the AI finds them: `STYLES.md` section 7.

The manifests (`manifest\*.json`), licence texts (`licences\`), sound library's README and licence log, and
letitedit's Elements presets in `src\elements` are in git; the other media is made again by the scripts in
`tools\assets` (below). `cache\assets` holds the index cache,
pictures drawn from SVGs, animation frames and preview sheets (safe to delete).

## What is here

The editorial collection's 17 processed WAVs are tracked in git (unlike the larger regenerated collections).
Its individual CC0 declarations, source hashes and authors are in licences/editorial-sfx-sources.json;
the manifest also records output hashes, processing and audibility screens. Two flash cues are AI-generated.
Reproduce with: python tools/assets/editorial_sfx.py fetch, then
python bridge/render_lock.py run --name editorial-sfx -- python tools/assets/editorial_sfx.py prepare.

| Source (manifest) | Folder | Kind | Count | Licence | Ships | Credit in videos |
|---|---|---|---|---|---|---|
| BigSoundBank / SFXMint (editorial-sfx) | sfx/editorial | sfx | 17 | CC0-1.0 | yes | no |
| Microsoft Fluent Emoji (`fluent-emoji`) | `emoji\fluent\{3d,color,flat}` | emoji (still) | 1,595 | MIT | yes | no |
| Tabler Icons 3.50 (`tabler-icons`) | `icons\tabler\{outline,filled}` | icon | 5,203 | MIT | yes | no |
| Noto Emoji Animation, in Shotcut's Elements (`noto-emoji-animation`) | `app\share\shotcut\elements\emojis` | emoji (animated) | 1,196 | CC BY 4.0 | yes (app\) | **yes** |
| Shotcut Elements Lottie (`elements-lottie`) | `app\share\shotcut\elements\{graphics,text,transitions}` | sticker, graphic, transition | 25 | Lottie Simple License | yes (app\) | no |
| letitedit vector presets (`letitedit-creative`) | `src\elements` and `app\share\shotcut\elements` | transition, overlay, motion graphic | 12 | CC0 (ours) | yes | no |
| letitedit title cards (`letitedit-title-cards`) | the same Elements folders | graphic | 3 | Lottie Simple License (adapted bundled compositions) | yes | no |
| CC0 sound library (`sfx-library`) | `sfx\library` (copied from the local sound collection; `_Licenses\license_log.csv`) | sfx | 565 | CC0 / public domain | yes | no |
| Kenney audio packs (`kenney-sfx`) | `sfx\kenney\{sci-fi-sounds,digital-audio,ui-audio}` | sfx | 151 | CC0 | yes | no |
| letitedit synthesised (`synth-sfx`) | `sfx\synth` | sfx | 28 | CC0 (ours) | yes | no |
| Elements panel sounds (`elements-sounds`) | `app\share\shotcut\elements\sounds` (FLAC copies, listed on their source entries) | sfx | 57 | CC0 | yes (app\) | no |
| CC0 music library (from `music-library\library.csv`) | `music-library` | music | 807 | CC0 / Public Domain Mark | no (5 GB) | no |

Sizes on disk: Fluent 94 MB (3D 51, Color 38, Flat 5), Tabler 15 MB, sound library 36 MB, Kenney 9 MB, synthesised
6 MB, Elements sounds 17 MB.

Credit line for the Noto animated emoji (CC BY 4.0), in the description or credits of a video that shows one:
"Animated emoji: Noto Emoji Animation by Google, licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)".
`assets.credits(files)` lists the lines a video owes. Shotcut ships these files with the Noto Emoji font's OFL text;
Google's Noto Emoji Animation site gives CC BY 4.0 for the animations.

## Licence checks (2026-10-29)

- Fluent Emoji: `LICENSE` in github.com/microsoft/fluentui-emoji (MIT, Copyright (c) Microsoft Corporation); GitHub's
  licence API: MIT. Partial clone of commit 1ffb34c7; default skin tone only.
- Tabler Icons: `LICENSE` in the npm package @tabler/icons 3.50.0 and the repository (MIT, Pawel Kuna); GitHub API: MIT.
- Noto Emoji Animation: the FAQ on https://googlefonts.github.io/noto-emoji-animation/ ("Animated Noto Emoji is licensed
  under CC BY 4.0").
- Lottie elements: the Lottie Simple License text Shotcut ships (commercial use, no attribution needed, same terms when
  passed on, no compiling a competing collection).
- CC0 sound library: its `license_log.csv` names every file's source page and licence (Kenney.nl CC0, Freesound CC0
  only, Wikimedia Commons public domain / CC0).
- Kenney: each pack's kenney.nl page ("License: Creative Commons CC0") and Kenney's OpenGameArt uploads (author Kenney,
  CC0, "Credit ... is not mandatory"); archives' sha256 in `cache\downloads\kenney\<pack>\source.json`.
Never downloaded: anything attribution-required, share-alike (e.g. OpenMoji), non-commercial or "no AI"; Pixabay and
Mixkit (their terms ban scripted downloads).

## Making it again

```
python tools\assets\copy_sfx_library.py          copy the local CC0 sounds from Drive (read only there)
git clone --filter=blob:none --no-checkout --depth 1 https://github.com/microsoft/fluentui-emoji.git
    cache\downloads\fluentui-emoji-src\repo, then a non-cone sparse checkout of /LICENSE, /assets/*/metadata.json,
    /assets/*/{3D,Color,Flat}/*, /assets/*/Default/{3D,Color,Flat}/*
npm tarball @tabler/icons 3.50.0 unpacked into cache\downloads\tabler-icons-src\package
python tools\assets\build_assets.py fluent tabler library elements
python tools\assets\download_kenney.py           Kenney packs (one archive each from OpenGameArt)
python tools\assets\synth_sfx.py                 letitedit's own sounds (deterministic)
python tools\assets\elements_sounds.py make      the Elements panel's FLACs + credits (src\elements\sounds and app\)
python tools\assets\elements_sounds.py manifest
python tools\assets\creative_elements.py      source assets, app copies and manifests (original Lottie shapes and three adapted title cards)
python bridge\render_lock.py run --name creative-element-previews -- python tools\assets\creative_elements.py --previews
C:\LetItEdit\envs\models\Scripts\python.exe -I tools\assets\clap_check.py assets\manifest\synth-sfx.json
python tools\assets\render_check.py              every kind placed on a vertical project, checked with the export engine
python tools\run_tests.py files test_assets
```
