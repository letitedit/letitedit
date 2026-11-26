letitedit 1.0.0-beta-20261126.6 is a free video editor for creators, built on Shotcut 26.9.27, with your own AI inside: Claude Code, Codex or Antigravity cuts your video on a real timeline that you can open and change, one Undo per step. This is a beta: free for everything, open source (GPL-3), no account needed.

### Download

**[letitedit-Setup-1.0.0-20261126.6.exe](https://github.com/letitedit/letitedit/releases/download/v1.0.0-beta-20261126.6/letitedit-Setup-1.0.0-20261126.6.exe)** (587 MB, 64-bit Windows)

SHA-256 `95250a32cd02621c97d703eb59119fced5a08807bba24a98a6da639df4a1ad2d` (every file's checksum is in `SHA256SUMS.txt` below)

### What you need

- A 64-bit Windows PC (tested on Windows 11 and Windows Server 2025). A graphics card helps but isn't needed.
- An internet connection while it installs: it sets up its own Python. Models download when a feature first needs one.
- Your own Claude Code, Codex or Antigravity on that PC, with your own subscription. You pay Anthropic, OpenAI or Google directly; letitedit adds no credits. letitedit is not made by or connected to Anthropic, OpenAI or Google.

### What's inside

One installer instead of a stack to gather and patch yourself: the Shotcut-based editor with MLT, FFmpeg and Qt; local speech to text (Whisper), cut-outs, object tracking, voice, music and stem-splitting models that download from their makers on first use; a motion engine, 316 font families, emoji, icons, sound effects and starter songs; and the tool server your AI uses. Every part with its licence: [What's bundled](https://github.com/letitedit/letitedit#whats-bundled) and `THIRD-PARTY-NOTICES.md`.

### Windows warns you once

The installer isn't code-signed yet, so Windows shows "Windows protected your PC". Click **More info**, then **Run anyway**.

### Source code

This release's source is the "Source code" archives below (the same as this repository at `v1.0.0-beta-20261126.6`): the tool server, skills and installer scripts at the top, the editor in `src/`. Beside them: `mlt-63218a28-src.tar.gz`, the source of MLT (letitedit's patches to it are in `release/source/mlt-patches/`); `letitedit-1.0.0-beta-20261126.6-msys2-sources.tar`, the source of the MSYS2-built libraries the installer bundles; and `shotcut-src-26.9.27.txz` (298 MB, SHA-256 `c20cef9e5e23acbbd2ba20a46e53919b923839a7f577584c0f9ec18aefa06576`), Shotcut 26.9.27's own source as Shotcut released it, the source of FFmpeg, frei0r, OpenCV and the other libraries Shotcut's build made. How each part is built: `release/source/BUILD.txt`. The written offer: `release/source/WRITTEN-OFFER.txt`.

letitedit is Copyright (C) 2026 letitedit, free software under the GNU GPL version 3 or later. Every bundled part keeps its own copyright and licence (`THIRD-PARTY-NOTICES.md`, and `src/COPYING` for the editor). Website: https://letitedit.app
