# New video catalog

The catalog lives in three UTF-8 JSON files under `looks/`. Paths in entries are
relative to `looks/`. IDs are stable lowercase hyphenated strings. Unknown fields
are preserved. Entries are objects, and IDs are unique within each file.

## Styles: `styles.json`

The document is an array of `{id, title, blurb, order, approved, review}` objects.
`title` and `blurb` are the visible name and description; `order` is a number
(ascending). Initial IDs are `talking-head` and `idea` (Made from an idea).
`kind` optionally limits video length to `short`, `long`, or `both` (default).
`footage` optionally declares `yes`, `no`, or `optional`; otherwise it is derived
from the Style's Looks. `filter_label` is an optional short label. `hidden: true`
keeps a Style out of New video's Style tabs. `filmed` says in plain words what
footage the Style is for.

A footage Style means what was filmed, and New video works it out from the chosen
clips (`bridge/what_was_filmed.py`): `talking-head` (one person talking to the
camera), `conversation` (two or more people talking), `activity` (action or
activity, little talk to the camera) and `screen` (a screen recording). The answer
is one of these IDs, or `all` when the clips don't say clearly. The catalog lists,
for each Style, the IDs of every offered Look that fits it as `fitting`.

New video shows Styles as tabs at the top of its Look step (there is no Style
step): All, and each Style of the route that has a fitting Look, plus the one the
clips look like. The tab the clips look like is chosen; the person may choose
another. A tab lists the Looks that fit it; each row ends with Freestyle and Edit
with the AI myself (opens the editor with the clips and the chat; no AI run).

## Looks: `manifest.json`

The existing object and `format: "letitedit-looks/1"` remain. Its `looks` array
contains Look objects. Existing `picker`, legacy `styles`, and `folders` remain
readable. A Look has:

- `id`, `style` (a Style ID), `label` (or `title`), and `line` (or `blurb`).
- `fits`: optional array of the Style IDs the Look suits, its main one first. When
  `fits` is missing, or leaves out `style`, `style` is read as the first fit, so
  older entries, saved projects and personal Looks keep working. Catalog cards
  carry `fits`, and `style` is the first fit. A Style's `looks` keeps the Looks
  whose first fit it is.
- `recipe`: Markdown file; optional `recipe_shared`, `poster`, and `preview` files.
- `themes`: `kits`, `film`, or `none`. Omitted means `none` for old entries.
- `approved`, optional `review`, and optional `cut` (see Review below).
- `preview_long` and `poster_long` (optional): a 16:9 preview and poster for a Look that suits YouTube videos
  (`kind` `long` or `both`); New video shows them when Format is YouTube video, `preview` / `poster` otherwise.
- Existing optional fields retain their meaning: `folder`, `needs`, `works_with`
  (`footage`, `no-footage`, `both`), `asks`, `pace`, `was`, and other recipe metadata.

`made-with-code` is the legacy alias of Style `idea`; existing saved projects and
Look IDs continue to resolve. The eight kit Looks remain readable by their old
IDs but move out of the card grid via `theme_only: true`. The single `drawn-video`
Look belongs to `idea` and has `themes: "kits"`. Talking-head Looks that support a
drawn backdrop may also use `themes: "kits"`. Film treatments use `themes: "film"`.
Each Look remains one card; theme variants do not duplicate it.

## Themes: `themes.json`

The document is an array of `{id, kind, title, folder, poster, recipe, approved,
review}` objects. `kind` is `kit` or `film`; `folder` is a visible group label
(for example `Paper & craft` or `Lighting`). `poster` is an optional relative
image path; `recipe` is a relative Markdown path. Optional `blurb` describes the
theme; `order` sorts within a group. Optional `recipe_shared` appends shared
recipe text. Optional `styles` limits the theme to those Style IDs; optional
`looks` limits it to those Look IDs. Without these restrictions, `kind` and the
Look's `themes` select applicability. Legacy Style aliases work here too.

Kit IDs: `flat-vector`, `toy-theatre`, `crayon`, `rubber-hose`,
`pencil-watercolor`, `oil-on-canvas`, `pixel-art`, `archival-scrapbook`.
Film themes use their own unique IDs. Two built-in choices are not entries:
`freestyle` (Freestyle, the default: no set Theme; the AI treats it its own way or
not at all; sent as `Theme: Freestyle (freestyle)`) and `pick` (Let the AI pick: one of
the Themes shown for the Look; sent as `Theme: pick` with each shown Theme's title, ID
and recipe). A saved `auto` from before the split loads as `freestyle`. `none` keeps a
learned Look's own theme file (its default).

## Review

All three entry types support `approved` (boolean), `review: "new"`, and `cut`
(boolean, default false). Normal customer catalogs show approved, uncut entries
only. The local `appdata/looks-review.json` contains `{"enabled": true}`
to show pending entries marked New and cut entries with Restore controls. This
file is not shipped or enabled by default. Test installs may supply their own
root and review setting.

Keep sets `approved: true`, removes `review`, and clears `cut`. Cut sets
`cut: true` without deleting assets or changing approval. Restore clears `cut`,
returning an entry to its prior approval/review state. Review writes reread the
file, change only the named entry, and atomically replace that file. Other
entries and unknown fields are retained. A cut Style hides its Looks in normal
mode; a cut Theme does not remove its Look.

## Requests and compatibility

Default choices add no request lines and preserve the existing request. Explicit
choices add one plain line each: `Style:` (the chosen tab, when it is a Style), `Look:`, `Theme:`, `Captions & pace:`,
`Music:`. Look `auto` is Let the AI pick (one of the Looks shown, listed in a
`Let the AI pick chooses one of the Looks I was shown:` line). Look
`freestyle` is Freestyle: no set Look; the AI edits the footage its own way. It is
sent as the brief's `look: freestyle` line plus `Look: Freestyle (freestyle)`, and
a chosen Theme still applies. Existing lowercase request fields stay compatible. Theme lines name the
ID and recipe path. Music values: `library` (song library), `own` (own song file),
`ai` (AI-generated music on this PC), `written` (written music), `backdrop`
(background music), `trending` (phone-app sound, excluded from export), `none`.
Music `auto` is Let the AI decide and keeps today's behavior. File-based choices
carry a separate `Music file:` line. No microphone is recorded.

Catalog readers accept a missing `styles.json` or `themes.json`, using legacy
manifest data and no themes respectively. Adding entries requires no editor
build. Writers reread the three files immediately before each change and merge
by ID; replacing a whole stale catalog would lose other authors' entries.
