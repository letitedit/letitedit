# GPL / LGPL corresponding source for a letitedit release (prepared locally, NOT published)

Prepared 2026-10-20 (roadmap A6b). Nothing here has been uploaded or pushed. Publishing is the owner's decision.

## What a release of the editor must include (or offer)
letitedit's editor is GPL-3.0 (Shotcut) and bundles GPL FFmpeg/x264/x265 and LGPL Qt/MLT. Anyone who receives the
binaries must get the complete corresponding source, the licence texts and the notices:

1. **The fork's source**: `out\<stamp>\letitedit-fork-src.tar.gz` (full tree) and `letitedit-fork.patch`
   (the changes against upstream mltframework/shotcut 325c2cc6422d93567d4edb57f1fee401f73beea1). Regenerate with
   `bash make-fork-source.sh` after every editor rebuild; ship only the newest `letitedit-*.exe`
   (older builds' exact source was not kept). Use `out\20261020-065759` or newer
   (`out\20261020-065725` is a broken first run, see the note inside it).
2. **The patched MLT modules and framework** (`libmltqt6.dll`, `libmltplus.dll`, `libmlt-7.dll`):
   `out\<stamp>\mlt-63218a28-letitedit-src.tar.gz` + `mlt-patches\` (upstream MLT
   63218a28d21f1e64b5b9e6671b4ff9146023282c + 0001 fonts + 0002 bold/weights + 0003 captions to the end + 0004 a
   clip's links freed with it + 0005 a kept frame's decoder freed after a cache eviction + 0006 a closed resample filter freed), built with `C:\LetItEdit\engine-patches\build_modules.sh` (the modules) and
   `engine-patches\mlt-cache-held-item\build_libmlt.sh` (the framework, 0004 and 0005), `engine-patches\mlt-resample-close\build_resample.sh` (the resample module, 0006) (engine-patches\README.md).
3. **Upstream Shotcut 26.9.27's own dependency source** (FFmpeg n9.0.2, MLT 7.41.0, frei0r, movit, OpenCV,
   rubberband, whisper.cpp, x264, x265 ...): `upstream\shotcut-src-26.9.27.txz` (312 MB, SHA-256 matches the
   release's sha256sums.txt, kept in `upstream\`).
4. **MSYS2-packaged DLLs** (Qt 6.11.2, x264, x265, SDL2, ICU, cairo ...: 168 files byte-identical to MSYS2 packages,
   see `app-binaries-manifest.tsv`): source tarballs listed in `msys2-sources.tsv` (59 packages from 55 source
   archives, ~730 MB incl. the full gcc source; all present on repo.msys2.org on 2026-10-20), downloaded with
   `python -I msys2_sources.py fetch <dir>`. Not downloaded yet (MSYS2 removes old versions over time, so fetch
   them before a release).
5. **Licence texts and notices**: C:\LetItEdit\THIRD-PARTY-NOTICES.md, app\COPYING.txt (GPL-3), plus LGPL-3.0 and
   LGPL-2.1 texts for Qt/MLT (not yet in app\; add them), the Lottie Simple License (app\share\shotcut\elements).
6. **A different name** from "Shotcut" for the program (trademark/confusion; upstream asks forks to rebrand).

Options for 3 and 4: ship the archives next to the binaries (simplest, ~1 GB), or host them on the same site as the
binaries (GPLv3 6(d)), or include the written offer below (GPLv3 6(b), valid 3 years).

## Files here
| File | What |
|---|---|
| make-fork-source.sh | builds `out\<stamp>\` (fork tree + patch, patched MLT tree, BUILD.txt, SHA256SUMS) without touching src\ |
| mlt-patches\ | 0001 fonts-from-folders, 0002 Qt 6 font weights, 0003 captions to the end, 0004 a clip's normalizer links freed with it, 0005 a kept frame's decoder freed after a cache eviction, 0006 a closed resample filter freed (the patches of engine-patches\modules) |
| BUILD.txt | how each binary was built |
| make_binary_manifest.py, app-binaries-manifest.tsv | every .exe/.dll in app\: SHA-256 and origin (fork, patched MLT, MSYS2 package+version, Shotcut 26.9.27 CI) |
| msys2_sources.py, msys2-sources.tsv | MSYS2 source archive URLs/sizes for the MSYS2 DLLs |
| upstream\ | shotcut-src-26.9.27.txz + the release's sha256sums |
| WRITTEN-OFFER.txt | written-offer text to include if the source archives are not shipped with the binaries |

## Other GPL programs letitedit uses (separate programs, not linked)
- BtbN FFmpeg 8.1 GPL with vid.stab (models\ffmpeg-vidstab): source = FFmpeg tag n8.1 + BtbN/FFmpeg-Builds
  scripts at the build's commit (the zip's name says "latest" = rolling; the exact FFmpeg commit is printed by
  `ffmpeg -version`); ship its LICENSE.txt and an offer, or have the installer download it from GitHub on first use.
- Blender 4.5.14 / 5.2 (vfx\blender): GPL-3.0-or-later; source at https://download.blender.org/source/ ; best
  downloaded by the installer, not shipped.
- espeak-ng (inside the espeakng-loader wheel) and phonemizer-fork: GPL-3.0; sources on PyPI (sdists) and
  https://github.com/espeak-ng/espeak-ng .
- PyAV wheel's bundled FFmpeg with x264/x265 (GPL): source per the PyAV wheel build (https://github.com/PyAV-Org/pyav-ffmpeg).
