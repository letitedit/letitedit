# Personal Looks

`letitedit_learn` is the tools-only learning boundary; there is no Learn button yet.
The AI uses `skills/letitedit-learn/SKILL.md` to interpret importer reports and its own
frame observations, save a reusable recipe, and run a reference-match test.

## Storage and updates

The default is `~/Documents/letitedit/My Looks`, not the app installation. Tests may
set `LETITEDIT_MY_LOOKS` to an isolated folder. An app update does not replace it.
Each `mine-<name>` directory has an atomic `look.json` current-revision pointer and
`revisions/<uuid>/recipe.md`, optional `theme.md`, and `evidence.json`. Evidence keeps
report hashes, measured facts, original paths, AI observations and stated limitations;
no reference media is copied. Originals/reports are needed for fresh comparisons, not
for using a saved Look's recipe. This is local storage, not cloud sync or a backup.

Updates require the current `expected_revision`; a simultaneous save is rejected.
Old revisions are retained. A crash may leave `.save-lock`; inspect the owning save
before removing an abandoned lock. Never remove one to bypass an active writer.

The live catalog merges personal entries in memory only. Shipped `looks/manifest.json`,
`styles.json` and `themes.json` are untouched. Personal cards live under **Your Looks**,
are visible in both normal and owner-review mode, and are excluded from Keep/Cut review
operations. Their Theme is applicable only to that personal Look. The request carries
the exact recipe path. Existing videos keep the recipe revision in their request; a
new choice sees the current pointer. No editor rebuild is required.

## Comparison contract

`action=match` takes reference and result importer report paths, not project paths.
It writes `match.json` and a separate critic brief. `render=true` also writes a private
side-by-side MP4 and 1fps pages under the PC render lock. Both videos begin at their
own zero, without matching narrative beats. Shorter footage becomes black after its
end. Reference audio goes left, result right; the critic must listen separately too.
These media artifacts are for the person's private inspection only, never shipped,
published or committed. A full-duration comparison may contain many pages.

Missing measurements remain unknown. Deltas never generate editorial scores.
An independent critic's JSON supplies every part's score (0-10 or null), evidence,
limits and engine/model/effort, bound to the exact pair of report SHA-256 hashes.
`assessed` is not an approval or resemblance threshold; null parts stay incomplete.
The skill permits at most two evidence-led retries after the first test video.
Elapsed learning/test/check times must be recorded; an ETA needs comparable measured
runs, not a fixed speed promise.
