# MLT Qt module loads letitedit's fonts itself (A4, 2026-10-20)

**Problem.** Since a Windows restart on 12 Oct, Windows exposes only its built-in families to processes; the 316
per-user Google Fonts families letitedit installed (%LOCALAPPDATA%\Microsoft\Windows\Fonts + HKCU entries) are not
loaded, so melt's qtext text fell back to a default font.

**Fix** (`mlt-qt-fontdirs.patch`, MLT commit 63218a28 = the app's 7.41.0). `common.cpp` gets
`loadShotcutAiFontsIfNeeded()`: once per process, the first time a text service starts (qtext producer, qtext filter,
kdenlivetitle), and only when MLT itself created the QApplication (melt.exe; inside the editor the editor loads fonts),
it calls QFontDatabase::addApplicationFont for every .ttf/.otf/.ttc/.otc under the folders in `LETITEDIT_FONT_DIRS`
(';'-separated, recursive; a file name already loaded is skipped). Unset -> the per-user font folder; empty ->
nothing. Cost ~1.5 s per melt run that uses text (819 files); melt runs without text pay nothing. `-verbose` logs
"letitedit fonts: loaded N files". The tools set the variable (`bridge\font_env.py`), and so does the editor for the
exports it starts (`src\src\main.cpp`).

**Builds.**
- 2026-10-20: built in C:\ShotcutDev and deployed (with the weight fix, `libmltqt6-fontdirs-weight.dll`). That build
  reads the variable's old name, `SHOTCUT_AI_FONT_DIRS`. The 28 Oct rename changed this patch, the tools and the editor
  to `LETITEDIT_FONT_DIRS` but not the deployed DLL, so melt has since loaded the per-user folder, which holds no font
  files on this PC ("loaded 0 files"): exports drew library fonts in a fallback font while the editor showed them.
- 2026-10-30: rebuilt with the new name (`..\build_modules.sh` -> `..\modules\libmltqt6.dll`); `..\check_engine.py`
  checks that melt loads the folder named by `LETITEDIT_FONT_DIRS`.

Undo: `..\deploy.ps1 -Undo ..\backup-<date>` (the module it replaced). The stock 7.41.0 module is Shotcut 26.9.27's
`lib\mlt\libmltqt6.dll` (C:\ShotcutDev\backups\roadmap-20261019\libmltqt6.dll.before-A4).
