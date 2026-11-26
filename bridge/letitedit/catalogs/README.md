# letitedit\catalogs

The asset library, My assets, platforms and fonts.

- `assets`: The asset library: one searchable index of the pictures and sounds letitedit can place in a video.
- `fonts`: The font library: every family letitedit can use, by name, in captions, titles and Python graphics.
- `my_assets`: My assets: the person's own logo, intro, outro, colours, clips, sounds, pictures and fonts, in one folder that works on every video and survives a reinstall.
- `platforms`: Platform profiles: published specs for YouTube, YouTube Shorts, TikTok, Instagram Reels, Instagram feed video, Facebook Reels and Facebook feed video, read from C:\LetItEdit\platforms\<id>.json (folder overridable with the...
- `fonts_build`: Build the bundled font library from Google Fonts (all OFL / Apache / UFL licensed, free to ship and use).
- `google_fonts`: Google Fonts on demand: a searchable index of every Google Fonts family (about 1,950, each under its open licence: OFL, Apache or UFL), its measured shape, and a download of one family when it is chosen.

Each module here also answers to its old name in `bridge\` (a small alias file: one module object under both names); inside the package, import the real name. What the other jobs may use from here: `IMPORTS.md`. The whole map: `CODEMAP.md` at the top of the repository.
