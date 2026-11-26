# Engine patches: letitedit's changes to the MLT engine

The editor and its exports (`app\melt.exe`) run the MLT 7.41.0 engine that ships with Shotcut 26.9.27
(`app\libmlt-7.dll` and the modules in `app\lib\mlt`). Two modules are rebuilt here with letitedit's patches, from
MLT commit `63218a28d21f1e64b5b9e6671b4ff9146023282c` (the source of the app's 7.41.0; its module metadata in
`app\share\mlt\plus` and `qt6` is byte-identical to that commit's):

| Module | Patch | What it changes |
|---|---|---|
| `libmltqt6.dll` (text, images) | `mlt-qtext-fontdirs` | melt loads the fonts in the folders named by `LETITEDIT_FONT_DIRS` (letitedit's font library), whatever Windows loaded at sign-in |
| | `mlt-qtext-weight` | the qtext producer (Text clips, the `text` filter) draws the weight asked: 700 is bold (stock 7.41 divided it by 10 under Qt 6); the qtext filter (Simple Text, the captions burn-in, timer, GPS text) reads the weight form letitedit writes for plain italics (w * 10 + 10) instead of Qt clamping it to the heaviest face |
| `libmltplus.dll` (captions and more) | `mlt-subtitle-feed-range` | a caption whose cue runs to the video's last frame or past it, or began before an exported range's start, is drawn (stock 7.41 drew nothing for that cue's whole length) |
| `libmlt-7.dll` (the engine itself, in `app\`) | `mlt-chain-normalizer-ref` | a closed clip's 10 normalizer links are freed with it (stock 7.41 kept them: about 377 Windows handles and their scalers and resamplers per clip, for the rest of the process) |
| | `mlt-cache-held-item` | a clip's decoder is freed when a frame kept on screen outlives that decoder's push out of the decoder cache (stock 7.41 kept the whole decoder, about 17 threads and its hardware device, every time; in the editor, every close after the bridge's snapshot) |

Each patch folder has a README (the problem, the cause, the fix, the measurements). `release\source\mlt-patches\`
holds the same five patches (0001-0005) for the GPL/LGPL source bundle. `libmlt-7.dll` is built alone, with both of
its patches, by `mlt-cache-held-item\build_libmlt.sh`; `deploy.ps1`, `VERIFIED.txt` and `check_engine.py` cover it like
the modules.

## Files
- `build_modules.sh`: checks out the MLT commit (`mlt-build\mlt`, a scratch checkout), applies the three patches and
  builds both modules (MSYS2 MINGW64, 4 threads) into `modules\` with `SHA256SUMS.txt`. The qt module links FFTW and
  libexif statically and the plus module links `libfftw3-3.dll`, as the shipped ones do: both import exactly the DLLs
  the app already has. `STOCK=1` builds them without the patches (for comparisons).
- `modules\`: the built modules (the DLLs are not in git; `SHA256SUMS.txt` and `VERIFIED.txt` are). The installer
  ships these.
- `modules\VERIFIED.txt`: the SHA-256 of module files that passed every check in `check_engine.py`, written by the
  check itself after a full pass. Nothing deploys or ships a module file that is not listed there.
- `deploy.ps1`: copies the modules into `app\lib\mlt` and `libmlt-7.dll` into `app`, only the files that differ, only when they match `SHA256SUMS.txt` and are listed in
  `VERIFIED.txt` (exit 3 otherwise). Windows locks a loaded DLL and every open letitedit window and running export
  has these loaded, so it changes nothing while any process has them open (it names the processes; exit 2); it keeps
  the replaced files in `backup-<date>\`, then runs `check_engine.py` on the app under the render lock and puts the
  backup back if a check fails. `-Undo <backup folder>` puts a backup back.
- `check_engine.py`: render checks on an app folder (weights 400/700/800 on both text paths, the italic form, a
  caption ending on, at or past the last frame, a range render, `LETITEDIT_FONT_DIRS`) and `chain_ref` (the engine
  frees a closed clip's normalizer links, `mlt-chain-normalizer-ref\check_chain_ref.py`) and `cache_ref` (it frees a
  kept frame's decoder after a cache eviction, `mlt-cache-held-item\check_cache_ref.py`). A full pass records all
  three files in `modules\VERIFIED.txt`. The fast suite's `test_engine_patches` runs `chain_ref` and `cache_ref` on
  the installed app, so a promotion check fails on an engine without the patches.
- `compare_frames.py`: renders the same frames of real projects with two app folders the way a normal export
  draws them and lists every pixel that differs (with A | B | difference sheets).
- `mlt-build\` (not in git): the MLT checkout and the build folders.

## Rebuild, verify, deploy

    python C:\LetItEdit\bridge\render_lock.py run --name engine-modules -- C:\msys64\usr\bin\bash.exe -lc /c/LetItEdit/engine-patches/build_modules.sh
    rem copy modules\libmltqt6.dll and libmltplus.dll into a COPY of app\ (its lib\mlt), then check that copy:
    python C:\LetItEdit\bridge\render_lock.py run --name engine-check -- python C:\LetItEdit\engine-patches\check_engine.py --app <the copy>
    powershell -NoProfile -ExecutionPolicy Bypass -File C:\LetItEdit\engine-patches\deploy.ps1

A rebuild gives new SHA-256 values (the files carry a build time stamp), so a rebuilt module deploys or ships only
after its own full check pass. The MLT checkout comes from `git clone https://github.com/mltframework/mlt.git` +
`git checkout 63218a28...` (the one in `mlt-build\mlt` was copied from the 20 Oct build's checkout).

## Who picks them up
- The editor build (`build.ps1`) ends with `deploy.ps1 -IfFree`: verified modules are swapped in when nothing has
  them loaded; when they are not built, not verified, already in place or in use, it prints a note and carries on.
- The installer (`release\installer\letitedit.iss`) ships `modules\libmltqt6.dll` and `libmltplus.dll` in place of
  the app folder's; `release\installer\build.ps1` stops when either is missing, differs from `SHA256SUMS.txt` or is
  not in `VERIFIED.txt`.
- The GPL/LGPL source bundle (`release\source\make-fork-source.sh`) packs the MLT tree with the four patches.
- `libmlt-7.dll`: the editor build's `deploy.ps1 -IfFree` swaps it in like the modules once it is in `modules\`.
  The installer doesn't take it from `modules\` yet: it ships whatever `app\libmlt-7.dll` is (the patched one once
  deployed on this PC).

## Results (2026-10-30)
All five checks pass on a copy of the app with the new modules; on the stock 7.41 modules and on the 20 Oct build
they fail (numbers in each patch's README). On real projects, rendered the way a normal export draws them with both
engines loading the same fonts, 82 of 84 sampled frames of 12 projects are pixel-identical; the 2 that differ are
the last caption that runs to the video's end, now drawn. The editor's own preview engine, in a test window per app
copy, draws that caption too. With today's (20 Oct) engine as it runs, without the font library, the AI's Inter
captions came out in a fallback font. The bridge's `test_font_env` engine test fails on today's engine and passes
on the new one.

## Licence
MLT's framework and the plus module are LGPL-2.1-or-later; the qt module as built (GPL3=ON, like Shotcut's) is
GPL-3.0. Whoever gets the modules must be able to get their source: upstream MLT at the commit above plus these
patches (release\source makes the bundle). See THIRD-PARTY-NOTICES.md and LICENSES-REVIEW.md.

## History
- 2026-10-20: the fonts and weight patches were deployed together (`libmltqt6-fontdirs-weight.dll`, the owner's OK,
  ROADMAP-PROGRAM.md 07:35Z). That build reads the old variable name `SHOTCUT_AI_FONT_DIRS`; after the 28 Oct rename
  the tools set `LETITEDIT_FONT_DIRS`, so melt fell back to the per-user font folder, which holds no fonts: exports
  drew library fonts (Anton, Inter, Montserrat...) in a fallback font while the editor's preview showed them right.
- 2026-10-30: both modules rebuilt from the commit with all three patches (fonts under the new name, weights incl.
  the italic form in the qtext filter, captions to the end) and verified on a copy of the app. Not deployed on this
  PC yet: the owner's letitedit window had the engine loaded; `deploy.ps1` (or the next editor build with no letitedit
  window open) swaps them in.
