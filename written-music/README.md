# written-music: music written as a score

The tool `letitedit_music_write` (`bridge\written_music.py`) runs one file, `written-music.mjs`, on the Node letitedit already ships.
The AI writes every note as JSON; this file performs, mixes and masters it on the CPU, the same every time. No model, GPU, download,
network, shell or ffmpeg. Everything is synthesised, nothing is recorded, and nothing is owed per video.

- `written-music.mjs`: the bundle, the only file customers need. Commit it after any change here.
- `cli.ts`: its command line (a score as JSON, a JSON report), adapted from anidoodle's `tools/music.mjs`.
- `engine\`: the music engine copied from anidoodle.
- `build.mjs`: `node written-music\build.mjs` bundles it with the esbuild in `motion\engine\node_modules`. Customers never need esbuild.

**Licence.** Based on anidoodle by Alex Greenshpun, Apache-2.0: https://github.com/alexgreensh/anidoodle, commit 6ae8827. Its licence
and notice are `LICENSE-anidoodle.txt` and `NOTICE-anidoodle.txt`; a row in `THIRD-PARTY-NOTICES.md` carries them. Every copied file
says where it came from, and the changed ones say how: `engine\core.ts` keeps only the seeded random generator, `engine\music\index.ts`
drops the sound effects, `cli.ts` is new around code from `music.mjs`. Never sell or label anything under the name anidoodle.

**Left out on purpose:** the 373 MB sound pack and `soundfetch`, recorded rooms, sound effects, drawing code, Remotion, the `sh -c` call.
The sound pack's and the Van Gogh picture's lines in its notice don't apply to anything here; the notice is kept whole as Apache asks.

The skill is `skills\letitedit-sound` (section 2a and `references\written-music.md`).
