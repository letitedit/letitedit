# letitedit's own editor code (`src/src/letitedit/`)

letitedit is Shotcut 26.9.27 plus our changes. Every C++ file letitedit added lives here, out of Shotcut's folders,
so that a Shotcut update touches as few of our lines as possible (T165, stage D of
`C:\LetItEdit\audits\refactor-2026-11-09.md`). Shotcut's own files keep only small hooks: a declaration in their
header, a call where their code needs ours, an `#include "letitedit/..."`. `src/src` is an include root, so every
include names its file from there (`#include "letitedit/chat/aichatpanel.h"`). The QML views are still in
`src/src/qml/` with Shotcut's.

| Folder | What | Entry the rest of the editor uses |
|---|---|---|
| (top) | `airoot.h` (where letitedit is installed), `letitedit.h` (letitedit's own choices: caption look, word list, pause and music settings, styles) | both |
| `chat/` | The chat panel (`aichatpanel.h` declares what other files call; `aichatpanel.cpp` the panel), the Codex app server and New video's carry-on (`aicodexserver.h`, `ainewvideocarry.h`, only included by `aichatpanel.cpp`), the terminal (`aiterminal`), Connect Your AI (`connectai`), the AI menu (`aiassistpanel.h`) | `aichatpanel.h`, `connectai.h` |
| `bridge/` | The tool bridge (`claudebridge.cpp`: the pipe, the dispatch), its test-window calls (`claudebridge_qa.cpp`) and its edits as one Undo step each (`claudebridge_edits.cpp`); `bridgehelpers.h` holds the helpers and the error type all bridge files share; `aicollaboration.h` (the Undo commands the app and the tools share); `qaoffscreen.h` (test windows made off-screen, never activated) | `claudebridge.h` |
| `newvideo/` | New video: `newvideodialog.h` declares the dialog; one file per step (`formatstep`, `contentstep`, `stylestep`, `lookstep`, `themestep`, `gostep`), the Look's input boxes (`lookinputs`), the catalogue as the steps read it (`catalog`), the older one-browser layout and the test profiles' review buttons (`lookbrowser`), presets and My style (`presets`), what is sent to the AI (`request`, with `firstCutRequest`), the cards and sliders (`widgets`), the shell and Back/Next (`newvideodialog.cpp`); `learnlooks.h` (Learn from a video) | `firstcut.h`: `showFirstCutDialog`, `firstCutRequest` |
| `home/` | The home screen (`welcomepage.h`), the grid of videos (`homevideos.h`), a new project's folder (`videoprojects.h`) | `welcomepage.h` |
| `workspace/` | The focus workspace (`focusworkspace.h`: the colour names and four functions; `focusworkspace.cpp` the layout), its inspector, media list and text panel (`focusinspector.h`, `focusmediadelegate.h`, `studiotextpanel.h`), a project's own `<name>.letitedit` folder (`leside.h`), progress on the home screen and the AI dock (`progressstate.h`, `progressview.h`); our member functions of Shotcut's MainWindow and TimelineDock (`mainwindow_letitedit.cpp`, `timelinedock_letitedit.cpp`) | `focusworkspace.h`; Shotcut's headers |
| `review/` | Review (Ctrl+Shift+R): `reviewwindow.h` declares the window and its parts; `reviewwindow.cpp` (window, keys, playing), `drawing`, `notes`, `takes` (spoken notes, transcription), `files` (saving, loading, submitting), `live` (Live Review inside the window), `send` (notes to the AI), `canvas` (canvas, scrubber, the drawing tools), `qa` (what test windows drive); `reviewmode.cpp` (entry points, banners); Live Review itself (`livereview`) | `reviewmode.h`: `ReviewMode::show`, `state`, `installQaActions`; `livereview.h` |
| `dialogs/` | The feature dialogs, one file each: Import a style, Animated title, Sync sound, Check my video, Dub; `featurehelpers.h` is what they share with `lefeatures.cpp` (the menu, state, the rest of the features); `letools.h` (the app's buttons run the tools' commands), `lejobs.h` (heavy programs take turns on the PC lock) | `lefeatures.h` |
| `panels/` | Music (`musicpicker`, `aiaudiolibrary.h`), stickers, My style, My assets, New hook (`hookpanel`), images (`imagegen`) | each panel's header |
| `player/` | Click the thing in the video (`previewobjects`), the live code-scene overlay (`livecodeoverlay`, Windows only), the phone apps' covered areas (`phonezones`) | each file's header |
| `export/` | The export checks, other sizes, shorts, chapters, pause remover; our member functions of Shotcut's EncodeDock (`encodedock_letitedit.cpp`) | each file's header; `encodedock.h` |
| `captions/` | Our member functions of Shotcut's SubtitlesDock (caption looks, words, layout: `subtitlesdock_letitedit.cpp`) | `subtitlesdock.h` |

What stays in Shotcut's files: the hooks above, `Player::addSelectionBar` (6 lines), one PlaylistDock function (it uses
`playlistdock.cpp`'s private PlaylistProxyModel), our QML in `src/src/qml/` (VuiBase.qml and others), and our small
changes inside Shotcut's own functions. `git diff v26.9.27 -- src/src` outside this folder shows them.

How the splits were made (each a move: every function body is the same text, one level less indented; scripts and
their checks in `C:\LetItEdit\tests\t165\lane2\`): `classsplit.py` moves a class's member function bodies out of the
class; `split_chatpanel.py`, `split_focusworkspace.py`, `split_newvideo.py`, `split_review.py`, `split_features.py`,
`split_bridge.py`, `split_shotcut.py` and `move_members.py` (our functions out of a Shotcut file), `split_move.py`
(the files into these folders, includes rewritten); `verify_lines.py` compares the code lines before and after.
`editor-moves.json` there lists where every file went.
