letitedit
==========

What this is
- The editor "letitedit" (app\), a version of the free, open-source Shotcut video editor.
- letitedit's tools (bridge\): Claude Code or Codex use them to look at your footage, build and change letitedit
  projects, and export videos. The guide the AI reads is GUIDE_V2.md.
- 316 free fonts (fonts\library), platform profiles for YouTube, Shorts, TikTok, Instagram and Facebook
  (platforms\), and the Codex plugin (codex\).
- Its own copy of Python (python\ and env\), set up during the install from the internet (Python itself and the
  packages listed in setup\env\requirements-bridge*.txt). Your own Python, if you have one, is not touched.

Setup (Start menu > letitedit > letitedit setup, or setup\setup_wizard.py)
- Adds letitedit's tools to Claude Code and/or Codex when you tick them. It only writes their settings files on
  this PC (and keeps a backup copy); it never signs in for you.
- Asks for your music, sound-effects and output folders. Your music and sound effects are only read.
- Shows what your PC can run by itself and lets you download local models now. Every model comes from its maker's
  own download address (listed in models\manifest.json with its size, licence and checksum), and each file is
  checked after download. Models you don't pick are downloaded when a feature first needs one (settings.json
  "model_downloads": "auto", the default; "ask" makes the feature stop with the size and the command instead;
  "never"). What was fetched, with sizes: cache\first-use.log.
- Model environments (envs\<name>: Python + torch and the voice / music engines) are built the same way, from the
  pinned package lists in setup\envs (CUDA form on a PC with an NVIDIA GPU, CPU form elsewhere where there is one).
- Command line: env\Scripts\python.exe setup\setup_wizard.py --console
- Models from the command line: env\Scripts\python.exe bridge\model_fetch.py list | fetch <id>
- Environments: env\Scripts\python.exe bridge\env_build.py list | plan <name> | build <name>

Uninstall (Start menu > letitedit > Uninstall, or unins000.exe)
- Removes what the installer put here, its Python, the models it downloaded, and the entries it added to Claude
  Code / Codex (only if they still point here). It asks before removing working files (caches, job records,
  editor settings, settings.json). Your projects, videos, music and anything else of yours are never removed.

Licences
- letitedit (the editor, its AI tools and skills) is Copyright (C) 2026 letitedit, free software under the GNU
  GPL version 3 or later (LICENSE.txt,
  and the editor's own copy app\COPYING.txt); the editor uses Qt and MLT under the GNU
  LGPL (licences\LGPL-3.0.txt, licences\LGPL-2.1.txt). Every part, its licence and where its source is:
  THIRD-PARTY-NOTICES.md. Fonts: each font folder holds its licence (OFL, Apache or UFL).
- GeoNames place names (if you download them) need the credit "Contains data from GeoNames (www.geonames.org),
  licensed under CC BY 4.0." wherever a place name shows in a video.
