# letitedit's copyright holder: every place it appears

The copyright holder and publisher is **letitedit** (24 Nov 2026). To change it (to "letitedit LLC", say), change the
installer's `#define Holder`, then every other row below to the same name, in one pass.
`bridge/tests/repo/test_holder.py` reads this table and checks that each place says what the installer's define says,
so a missed spot fails the fast suite. `{holder}` stands for the name.

## Where it appears

| Where | The text | What uses it |
|---|---|---|
| `release/installer/letitedit.iss` | `#define Holder "{holder}"` | **The one value.** The installer's AppPublisher, AppCopyright, VersionInfoCompany and VersionInfoCopyright, and the source release's `SOURCES.txt` (`release/source/make_release_sources.py` reads it) and the public Release's text (`release/public-repo/notes.md`, filled by `release/source/make_public_repo.py`) |
| `src/CMakeLists.txt` | `set(LETITEDIT_HOLDER "{holder}")` | The editor repo: the program's CompanyName and LegalCopyright (`packaging/windows/shotcut.rc.in`), from the next editor build |
| `src/src/**` | `Copyright (c) 2026 {holder}` | The editor repo: letitedit's 40 source headers (37 in `src/`, 3 in `tests/`). They can't share a constant: one search-and-replace changes them all (upstream's "Meltytech, LLC" lines stay) |
| `README.md` | `letitedit is Copyright (C) 2026 {holder}, free software` | The tools repo's Licence section |
| `release/installer/files/README-LETITEDIT.txt` | `is Copyright (C) 2026 {holder}, free software` | The README the installer ships |
| `THIRD-PARTY-NOTICES.md` | `Meltytech, LLC and contributors; changes: {holder}` | The Shotcut row of the notices (shipped) |
| `release/source/WRITTEN-OFFER.txt` | `are offered, {holder} (teamletitedit@gmail.com) will give` | The written offer for the source |
| `C:/letitedit-site/public/privacy.html` | `<p>{holder}, an independent project.` | The site's privacy page, section 7 (repo `letitedit-site`; checked only where that checkout exists). The home page's "letitedit is an independent project" names the product: reword it by hand if wanted |

## Not the holder (nothing to change for it)

- `LICENSE` in both repos and `COPYING` in the editor: the GPL-3 text itself; it names no holder.
- The source snapshot's git author, `letitedit <teamletitedit@gmail.com>` (`tools/release/make_source_snapshot.py`,
  `release/source/make_release_sources.py`): an author name, changed only if he wants.
- "letitedit" as the product's name everywhere else (the program, the installer's AppName, the site).
