# letitedit Studio jobs: the contract (version 1.6, 20 Nov 2026)

letitedit's front door for making things from a written spec. A caller (letitedit Channel, a script, any program)
writes a `job.json` into a folder; letitedit does the work on this PC with the person's own AI and writes back where it
is (`status.json`, `events.jsonl`) and what it made (`result.json` and the files). The caller never imports
letitedit's code and letitedit never needs the caller's.

This document states what each file holds and what each job kind does. The JSON Schemas in `schemas/` are the exact
shapes; `examples/<kind>/` has a filled example of every kind. Where this text and a schema disagree, the schema wins and
the text is a bug.

**What runs.** On a real letitedit: the job folders, `validate`, `submit`, `status`, `cancel`, `retry`, `run`, the inbox
and the kinds `capabilities`, `index` and `short` (preview and final). The reference fake answers every kind (section 3, "Testing against the fake"). Each other
kind is switched on in its own part: `capabilities` lists a kind as `available` once it runs on that install, and until
then a job of that kind is refused `kind_not_installed`.

## 1. Files and where they are

| File | Who writes it | When |
|---|---|---|
| `job.json` | the caller | once, before submitting; letitedit never changes it |
| `status.json` | letitedit | rewritten whole at every change, at least every 10 s while running |
| `events.jsonl` | letitedit | appended, one JSON object a line |
| `result.json` | letitedit | once, when the job ends (done, failed or cancelled) |
| `cancel` | the caller (or the `cancel` command) | an empty file; its presence asks for a cancel |
| everything else | letitedit | the outputs, in sub-folders named in `result.json` |

- **The job folder is `output_dir`.** The caller makes it, writes `job.json` in it and submits it. When `output_dir`
  is left out, the folder holding `job.json` is the job folder (CLI), or letitedit's Studio folder plus the job id
  (inbox).
- **Channel's default** is `%LOCALAPPDATA%\letitedit Channel\channels\<id>\studio\<job_id>\`. Any absolute path works:
  another drive, spaces, any Unicode, longer than 260 characters.
- **Refused output folders** (error `output_dir_refused`, retry `after_change`): inside any folder the job reads
  from (a source folder, or the folder of any file the job names: footage, photos, references, music, at any depth of
  `inputs`), inside letitedit's install, a folder letitedit can't write in, or a folder holding files that aren't this
  job's own. **What counts as this job's own:** an existing job folder is accepted when it holds nothing but
  `job.json`, a `cancel` file (the job then ends cancelled at once, section 3) and the caller's own files whose names
  start with `x_`, or when it is already this letitedit's folder
  for the same job id (the same job sent again, or sent again fixed after a refusal). A `status.json` naming the same
  job id is not enough on its own. Before letitedit writes anything for a job it takes the job folder for itself,
  atomically, with a `.studio-side` file naming its owner (the side, the Studio folder and the job id); a folder taken
  by another owner (the reference fake, another Studio folder, another job) is refused, and nothing is written there.
  A job folder is written under its own lock from that claim through acceptance, and the claim is checked again right
  before `job.json` is written, so a refused submission never changes another job's files.
- **letitedit writes only** into the job folder, its own caches, and (for `learn`) the person's My Looks. It never
  writes into a footage folder and never touches the person's open letitedit window.
- **Paths:** in `job.json` and in source fields, absolute Windows paths as the caller wrote them. In `result.json`
  and `status.json`, every made file is a path relative to the job folder with forward slashes (`files/tiktok.mp4`).
- **Times:** ISO 8601 with the UTC offset (`2026-11-20T01:40:00-08:00`). Durations and positions are seconds
  (numbers).
- **Text files are UTF-8** without a byte-order mark (a reader should still accept one).
- **No location in any file letitedit makes.** Finals, stills, motion stills, conform files, proxies, posters, covers
  and evidence frames carry no GPS, no `location.ISO6709`, no `©xyz` and no EXIF or XMP location, even when the footage
  has them (phones write them). letitedit removes **all** metadata from every file it delivers, whether or not a
  location was seen (pictures keep only what draws them, and a picture with a colour profile is converted to sRGB and
  delivered without one; video and sound keep only their picture and sound streams, with every sample description's
  inner boxes, compressor name and handler names checked or blanked, and the picture stream's SEI messages, the
  free-form data an H.264 or HEVC stream can carry beside its pictures, taken out without re-encoding), and then checks
  the written file with a separate check that fails closed: a file with any metadata, colour profile or SEI message
  left, a picture that doesn't decode in full, a video whose first frame (or, for sound only, whose first moment of
  sound) doesn't decode, a file it can't read through, or a kind of file it can't check is not delivered (the job
  fails, error `location_not_removed`). Video is delivered only as H.264 or HEVC, the codecs whose in-stream data
  letitedit removes and reads; the inside of a sound stream is not read, and a video is not decoded past its first
  frame.
  Every delivered file in `outputs` says `location_metadata: "none"`, meaning: none in any of the places above. (`index` records a file's `place` as data in the library, which is the caller's own; it
  is never written into a made file.)
- **Every made file in `outputs` carries its size and SHA-256**, so a half-copied or stale file can't pass for a
  finished one.

## 2. Versions

- Every file carries `contract_version`, `"MAJOR.MINOR"`. This is `1.6`: letitedit writes `1.6` and still accepts
  `1.0`, `1.1`, `1.2`, `1.3`, `1.4` and `1.5` jobs (they simply don't use the later fields).
- **A job's `contract_version` is what it can read.** A value a later minor added to a fixed list (so far: 1.6's font
  licence ids) is sent only to a job whose `contract_version` is that minor or later; an earlier job gets what its
  version knows (for a licence id, `unknown` with the licence named in `note`). A caller asks for 1.6's values by
  writing `"contract_version": "1.6"` in `job.json`.
- **Within a major version, changes only add:** new optional fields, new kinds, new error codes, new values in lists
  this document calls open. A reader **ignores fields it doesn't know** and treats an unknown value in an open list as
  "other". Required fields are never removed or renamed and a field's meaning never changes inside a major.
- **The open lists** (the schemas give each as a plain string, with the known values listed): stages; error codes;
  event `type` (events.jsonl); `waiting_on.what` (status.json); asset `kind` (`provenance.assets`); output `role`
  (`outputs`); warning `code` (`warnings`, with `input_ignored` new in 1.1); and the conditions in an overlay item's
  `if`. A condition letitedit doesn't know is not met (the item
  isn't applied, and `why` says so).
- **Fixed lists** (states, rule kinds, rule statuses, `hook_kind`, `editable`, `retry`) grow only in a new minor, and the change
  log below names each new value.
- **letitedit accepts** a job of its own major at any minor. Fields from a newer minor that it doesn't know are kept,
  ignored, and named in `status.json` `warnings` (code `field_ignored`). A job of another major is refused
  (`unsupported_version`, retry `no`). `capabilities` lists the majors it accepts.
- **Top-level fields of job.json starting with `x_`** are the caller's own (notes, a test fake's steering). letitedit
  keeps and ignores them without a warning, and never adds an `x_` field itself.
- **A new major** is for a change that would break a reader. letitedit then accepts the previous major for at least
  one more release, and writes each job's files in the major the job asked for.
- The schemas' `$id`s carry the major (`https://letitedit.app/studio/1/...`). They are identifiers; the files ship in
  the installer at `bridge\letitedit\studio\contract\`.

## 3. Submitting, running, cancelling

**Entry points** (all three do the same thing):

```
<cli> validate     <job folder | job.json>   checks job.json, runs nothing; prints the problems as JSON
<cli> submit       <job folder | job.json>   validates, queues, returns at once (prints status.json)
<cli> run          <job folder | job.json>   submit, then wait until it ends (prints result.json)
<cli> status       <job folder | job id>     prints status.json
<cli> cancel       <job folder | job id>     asks for a cancel
<cli> retry        <job folder | job id>     queues a failed or cancelled job again, same folder
<cli> capabilities                           prints capabilities' output at once (no job folder)
```

- `<cli>` is the command line in `capabilities.entry_points.cli`: letitedit's own Python and its entry file,
  `"<install>\env\Scripts\python.exe" "<install>\bridge\letitedit_studio.py"`. The installer also writes it to the
  registry value `HKCU\Software\letitedit\Studio\cli`, so a separate program can find letitedit. Each command
  prints one JSON document. The same calls are Python functions in `letitedit.studio.service` (`submit(path)`,
  `status(ref)` and so on, with letitedit's `bridge` folder on the path). They are not tools of the editing AI: its
  tool set stays as it is.
- **The reference fake** answers the same commands without making anything: see "Testing against the fake" at the
  end of this section.
- **Every entry point starts the Studio worker when it isn't running**, `status` and `validate` included, whether or
  not letitedit is open. A caller that checks `status` now and then (Channel does every 2 minutes while it has jobs
  out) keeps its jobs moving and brings them back after a Windows restart. Nothing starts at Windows sign-in.
- **The inbox:** a caller may instead drop `<job_id>.json` (a whole `job.json`) into the folder
  `capabilities.entry_points.inbox`. letitedit first claims it (under the Studio folder's lock, so it is taken once even
  when several entry points read the inbox at once), checks it whole, and only then writes it into its job folder and
  renames it to `<job_id>.json.taken`. Two inbox files naming the same job folder are taken one after the other: the
  second finds the first's `job.json` there and is refused (`job_id_conflict`) without changing it. A refused one is renamed `.refused`, with `<job_id>.refused.json` beside it holding the
  problems, and nothing is written anywhere else. A claim left by a process that died is put back and taken again.
  **Taking back an inbox job:** until letitedit has claimed `<job_id>.json` (it is still in the inbox under that
  name), the caller may simply delete its own file. Once it is claimed, or to be safe either way, use the `cancel`
  command with the job id: an inbox job not claimed yet is then taken and ends at once as `cancelled`, never run.
- **Exit codes:** `0` done (or, for `submit`, queued); `1` failed; `2` invalid job; `3` cancelled; `4` letitedit
  couldn't start, or a job folder stayed locked by another letitedit process for a minute (problem code `busy`:
  nothing was written; call again).
- **Sending is safe to repeat.** letitedit records a job before it writes anything into the job folder; if its process
  stops part way through `submit`, the next call of any entry point finishes the job's sending (or, when `job.json`
  changed in between, fails it with `job_id_conflict`). Sending the same job again never queues it twice.
- **The job that runs is the job.json that was accepted.** A `job.json` changed after `submit` is not run, resumed or
  retried: the job fails (or `retry` refuses) with `job_id_conflict`. A changed job needs a new job id.

**`validate`** checks without running: the schema, the contract version, the job id, the output folder (writable,
not refused), every source path exists and is readable, every Look, platform, layout and caption style exists on this
install, a `from_job` is finished and of a kind this job can continue, the AI named is installed. It returns
`{"valid": bool, "problems": [{"field", "code", "message"}], "warnings": [...]}`.

**Idempotent by job id.** Submitting a job id again with the same `job.json` (compared after parsing, so spacing
doesn't matter) returns the existing job's status and starts nothing. The same id with a different `job.json` is
refused (`job_id_conflict`). A job id is never reused for another job.

**States** (`status.json` `state`):

```
queued -> running -> done
                  -> failed
                  -> cancelled
running -> queued (resuming: true)   after its process stopped: a crash, a kill, a Windows restart
```

`done`, `failed` and `cancelled` are final, and `result.json` exists exactly when the state is final. Until then,
nothing in the folder is final, even files listed in `outputs_so_far`.

**Counts (1.2).** While a stage works through a job's files (`index`'s files, transcripts and moments), `status.json`
also has `counts`: `{stage, files_done, files_total, footage_min_done, footage_min_total}` (the files stage, which
finds the lengths, gives no minutes), written at most once a second, and `progress` moves within the stage. A caller
may show "1,240 of 5,800 clips".

**The first status.** `submit` prints the job's status right after it is queued: `queued`, or already `running` when a
free worker has started it. A caller reads either. letitedit writes `queued` first and then `running`; the fake
answers the same way. (A job cancelled at its claim, below, is `cancelled` at once.)

**Crashes and restarts.** Each kind runs in stages (section 6) and saves a checkpoint at the end of each. If
letitedit's process stops mid-stage, the job goes back to `queued` with `resuming: true` and the next attempt starts
that stage again from its beginning (an export inside it resumes from its finished chunks; an `index` stage carries
on after the last file it finished). After `max_attempts`
(default 3) it fails with `interrupted_too_often` (retry `yes`). The worker starts again when any entry point is used
(`status` included); opening letitedit doesn't start it, and nothing starts at Windows sign-in. If the worker stops
while a job's own process carries on, the next worker takes that process over and still enforces cancel and the time
limit on it; it never starts a second attempt beside it. A heartbeat older than 60 s on a `running` job means its
process has stopped; the job will resume or fail cleanly, never stay half-done.

**Cancel.** The `cancel` command, or an empty file named `cancel` in the job folder. letitedit stops at its next
check (within about 20 s), ends its own processes, writes `result.json` with state `cancelled`, the error code
`cancelled` and the files finished so far, and leaves the person's window and other jobs alone.

**Cancelled before it was taken.** A job folder whose only extra file is `cancel` when letitedit claims it (a caller
cancelling a job still in the inbox, or one sent with `submit` after a `cancel` file was written) is claimed, accepted
and ends at once as `cancelled`: `result.json` with state `cancelled`, error `cancelled` and no files. It never runs.
`submit` answers 0 and that status. The `cancel` command does the same for an inbox job letitedit hasn't claimed yet.

**Retry.** `retry` queues a failed or cancelled job again in the same folder. The old `result.json` moves to
`history/result-<attempt>.json`; finished stages are reused where their inputs haven't changed. A changed `job.json`
needs a new job id. A job cancelled at its claim is queued for the first time; that first retry is recorded before anything moves, so a stop part way is finished by the next entry point, under the same fixed queue job. Two retries of one job at once queue it once: the other answers `not_retryable` (exit 2), saying it was already queued again. A `cancel` during a first retry, or after one stopped part way, waits for it to finish and then cancels the new attempt. A retry hands the ending attempt's `cancel` file over by renaming it to `cancel.attempt-<n>` before anything else: a `cancel` written before that rename belongs to the ending attempt, and any `cancel` that exists after it belongs to the new attempt and is never removed by the retry. A cancel is the person's choice: a
caller retries a cancelled job only when the person asks (section 8).

**Reading the files safely.** `status.json` and `result.json` are written to a temporary file and then swapped in. On
Windows a reader can still meet a moment when the file is locked: read again after about 100 ms (up to 5 times).
`events.jsonl` lines are written whole; a last line that doesn't parse is being written, so skip it and read again
later. `seq` starts at 1 and rises by one across attempts, so a reader can tail it by `seq`.

### Testing against the fake

The reference fake answers every command of the real command line with placeholder files, in seconds, for every kind
and every state. A caller's integration tests use it through **the exact same command line**, switched by the
environment:

```
set LETITEDIT_STUDIO_FAKE=1
set LETITEDIT_STUDIO_FAKE_HOME=<a folder of the test's own>
<cli> submit <job folder>        (and every other command, exactly as above)
```

- **The Python:** the one in `<cli>`, letitedit's own (`<install>\env\Scripts\python.exe`), which has what the
  fake needs. The fake also runs on any Python 3.10 or later with the `jsonschema` package, as
  `"<python>" "<install>\bridge\letitedit\studio\fake.py" --home <folder> <command> ...`.
- **Where it writes:** its own Studio folder (`LETITEDIT_STUDIO_FAKE_HOME`; without it
  `%TEMP%\letitedit-studio-fake`) and the job folders it is given, nothing else. It never takes the PC lock,
  starts no AI, renders nothing and never touches the person's letitedit window, so it is safe to run while they edit.
- **A fake result can't pass for a real one.** Every `status.json` and `result.json` it writes has the warning
  `fake_studio` first in `warnings`, every `result.json` has `versions.letitedit: "fake"`, and `capabilities` says
  `fake: true` and `letitedit_version: "fake"`. Its media files are short text placeholders.
- **The two never share anything.** Each job folder the fake writes holds a `.studio-fake` file; the real letitedit
  refuses such a folder (`output_dir_refused`; `status`, `cancel` and `retry` answer `not_found`) and never runs it.
  The fake refuses a folder the real letitedit has written to in the same way. Each side takes a job folder
  atomically (`.studio-side`, naming the side, the Studio folder and the job id) before it writes anything for it, so
  the two can't both take one at the same moment, and a submission a crash interrupted is finished only when its
  folder is still that side's and that Studio folder's. A Studio folder is claimed
  as one side's the same way (`studio-home.json`); pointing the other side at it is refused.
- **Steering:** a top-level `x_test` object in job.json (letitedit itself ignores `x_` fields): `stages` (extra
  stages before the kind's own), `stage_s` (seconds each), `fail` with `fail_at` (an error code at a stage number),
  `crash_at` with `crash_attempts` or `crash_always` (the worker process dies there), and `wait`
  (`{"what": "pc_lock", "s": 2, "ahead": 1}`: a wait before the first stage), and `ai_media` (true: the result holds
  a generated picture, so an `overlay_text` item with `if: ["ai_generated_media"]` applies). Results are made from this
  contract's examples. The fake decides `overlay_text` and returns a still's revise as section 6 describes; on a real
  letitedit those land with each making kind.
- The contract's own test suite runs against either: `"<python>"
  "<install>\bridge\letitedit\studio\contract\tests\contract_tests.py" --target fake` (or `--target real`).

## 4. Priority and the PC

- **One Studio job runs at a time.** Others wait in the Studio queue, `urgent` before `normal` before `dev`. Within a
  lane a job resuming after a stop goes first (it holds finished work), then the oldest. `status.json` `queue.position` is 0 for the running job, 1 for the next, and so on.
- **The lanes:** `urgent` and `normal`, the names to write, and `dev` for test runs. `channel_urgent` and `channel`
  are accepted as the same as `urgent` and `normal`; `status.json` shows `urgent` or `normal`. The person's own work is above every lane and can't be asked for.
- **The PC lock.** Every heavy step (a render, an export, a model) takes letitedit's PC-wide lock, one at a time. Its
  line is ordered by class: the person's own work first, then `urgent`, then `normal`, then test runs. A job never
  stops a render that is already running; a long render of a lower class gives way between its pieces when a higher
  class waits. While a job waits, `status.json` has `waiting_on: {what: "pc_lock", ahead, holder}`.
- **The person working.** A Studio job that uses the AI starts no new stage while the person's own letitedit is
  running an AI edit of theirs (`waiting_on.what: "person_working"`), so the two don't share the AI plan at once. A
  stage already running carries on. Kinds without AI wait only for the PC lock.
- **AI usage limits.** When the person's AI reports its usage limit, the job waits (`waiting_on.what: "ai_limit"`,
  with `until` when the AI says) up to its time limit, then fails with `ai_limit` (retry `after`). Its error always
  carries `retry_after_s`: the seconds until the AI's own reset time when it gave one, else 3600.
- **Memory and disk.** A job waits for memory as exports do (`waiting_on.what: "memory"`). A making job is refused
  when free disk space is under `capabilities.limits.free_disk_gb_needed` (`disk_full`, retry `after_change`).

## 5. Which AI

A job uses the person's own AI subscription, through the AI they use in letitedit:
- `job.json` `ai` absent: the person's New video choice (the AI, model and effort saved in the chat's settings), else
  letitedit's default (Claude Opus 5.5 at medium, or Codex GPT-6.1-Sol at medium for someone with only Codex).
- `ai.engine` given: that AI only. If it isn't installed or signed in, the job fails with `ai_unavailable` (retry
  `after_change`); letitedit never switches to another provider by itself. `ai.model` and `ai.effort` are passed on as
  given.
- **A job's `ai` overrides the person's chat choice for that job only.** Its `engine`, `model` and `effort` are what
  the job's own window runs; an `effort` or `model` without an `engine` is for the AI the person uses. The person's own
  settings are never changed. A job without `ai` (or without one of its parts) inherits the person's chat choice.
- The review's critic follows letitedit's own rule (the editing AI first, then the other one if the person has it).
- `result.json` `cost.ai` and `review.critic` say what actually ran.

Kinds with no AI (`capabilities`, `index`, `match`, `retext`, `conform`) never start one, whatever `ai` says.

## 6. The kinds

Every kind's `inputs` are in `job.json`; its particular output is `result.json` `output`. Making kinds also return
the shared fields in section 7. Stages are an open list.

| Kind | What it does | AI | Heavy | Stages |
|---|---|---|---|---|
| `capabilities` | what this letitedit can do | no | no | `read` |
| `index` | a library of footage folders | no | yes | `files`, `transcripts`, `moments`, `photos`, `flags`, `write` |
| `match` | where a finished video's footage came from | no | yes | `fingerprint`, `search`, `write` |
| `inspect` | what is in a video made elsewhere | local models only | yes | `probe`, `transcript`, `pictures`, `sound`, `write` |
| `short` | one vertical video from an idea | yes | yes | preview: `log`, `story`, `rough`, `proxy`; final: `fine`, `finish`, `review`, `export`, `proxy` |
| `batch_shorts` | several Shorts from one log and story pass | yes | yes | `log`, `story`, then per item |
| `still` | a picture post, Story or carousel, or a motion still | yes | yes | `layout`, `draw`, `check`, `export` |
| `revise` | a made video changed from plain notes | yes | yes | `apply`, `review`, `export`, `proxy` |
| `retext` | text items changed by id, exported again | no | yes | `apply`, `export`, `proxy` |
| `hooks` | other openings for a Short | yes | light | `find`, `preview` |
| `conform` | per-platform files of a finished video, no creative change | no | yes | `probe`, `encode`, `cover`, `proxy` |
| `learn` | a Look from reference videos | yes | yes | `fetch`, `learn`, `save` |

### capabilities
No inputs (`include` narrows it). Returns: `contract_version`, `contract_versions_accepted`, `letitedit_version`,
`kinds` (each with `available`, `why_not`, `tiers`, `options`, `uses_ai`, `heavy`), `ai` (the default and the AIs
installed), `looks` (`id`, `name`, `source` library/learned/shared, `styles`, `formats`, `needs_footage`, `fits`),
`themes`, `platforms` (size, fps, size cap, length cap, loudness, whether covered areas are known), `still_sizes`,
`stills_layouts` (with their text `fields`), `caption_styles`, `rule_kinds` (1.5: the rule kinds a job's `rules` may
use, `must`, `never` and `prefer`; a reader that finds no `rule_kinds` should assume `must` and `never` only),
`rule_checks` (which rule hints have a detector yet),
`priorities`, `limits` and `typical`. Also answered at once by the CLI's `capabilities` command.

**`typical`**: for each `<kind>` or `<kind>.<tier>` (and `batch_shorts.per_short.<tier>`): median `minutes` (waits
left out), `minutes_p90`, `tokens`, `tokens_p90`, and its `basis`: `measured_here` (the median of this PC's last 10
finished jobs of that kind and tier, `samples` how many), `reference` (letitedit's own measured runs) or `estimate`
(nothing measured yet). A planner should treat `estimate` as rough.

**`typical` by AI (1.2).** Each figure says the AI it was measured with (`ai`: engine, model, effort; an estimate has
none) and `samples`. A figure measured here is the median of this PC's last 10 finished jobs of that kind and tier
run with that same engine, model and effort, once there are 3. `inputs.ai` (the AI the caller plans to use; absent,
the person's own, `ai.default`) picks the figure: `match: exact` when one was measured with it, else `match:
nearest`, the closest one (same engine, then model, then the nearest effort; measured here before letitedit's
reference before an estimate), with `match_note` saying what it stands in for. `by_ai` lists every figure of that kind and
tier measured with an AI. Kinds that run no AI have one figure and no `match`.

### index
Inputs: `folders` (read only), optional `files`, `changed_only` (default true), `since_job`, `steps` (`files`,
`transcripts`, `moments`, `photos`, `flags`, and `vision` from 1.2; absent: all but `vision`), `recursive`. It writes
a full snapshot of those folders into the job folder, and nothing into the footage folders:
- `library/files.jsonl`: per file `file_id`, `paths` (copies share one id), `kind`, `bytes`, `duration_s`,
  `recorded_at`, `camera`, `width`, `height`, `fps`, `hdr`, `talking`, `place`, `transcript` (a file in
  `transcripts/`).
- `library/moments.jsonl`: per moment `moment_id`, `file_id`, `in`, `out`, `state` (current or retired),
  `replaced_by`, `what`, `who`, `words`, `picture_quality`, `hook_value`, and `flags`: `place_revealing`,
  `licence_plate`, `faces`, `kids`, each `yes`, `no` or `unknown` with `how` and `confidence`.
- `library/photos.jsonl`: per photo `sharpness`, `faces`, `kids`, `subjects`, `place_revealing`, `licence_plate`.
- `library/changes.jsonl`: what was added, changed, removed or retired since `since_job` (the newest finished index
  job of the same folders when absent).

The output gives these paths and counts (files, analysed, skipped unchanged, unreadable, moments current and retired,
photos), the unreadable files with why, and the steps skipped with why (a flag with no detector yet is `unknown`,
and `steps_skipped` says so).

**File ids.** `file_id` is the file's content identity: its size plus a hash of its first 2 MB, as letitedit's
archive keys files. A copy or a renamed file keeps its id; an edited file gets a new one.

**Moment ids.**
- A `moment_id` is minted once, when index first finds that moment, from its `file_id`, `in` and `out`. letitedit
  keeps every id it has minted, and an id is never recomputed, reused or given to a different moment.
- **Re-indexing an unchanged file** with the same settings gives the same moments and the same ids.
- **When a re-index splits a file differently** (a new model, new settings, a longer transcript):
  - each new moment whose `in` and `out` are both within 0.5 s of an existing current moment of that file keeps that
    moment's id (its `in` and `out` are updated);
  - every other new moment gets a new id;
  - an old moment with no such match becomes `retired`, with `replaced_by` listing the new moments that overlap it and
    by how many seconds.
  - A retired moment stays in `moments.jsonl` forever, so an id in a caller's ledger always resolves.
- **A rule that keys on footage** (such as "the same footage at least 4 weeks apart") is safest on `file_id` plus time
  overlap. `replaced_by` maps an old id to the new ones for that.

**Moment fields (1.2).** Each moment may carry five more fields, for choosing shots. Each value is `{value,
confidence, how}` like the flags (`how`: `detector`, `vision_model`, `transcript` or `file_metadata`, an open list),
and every list of values below is open. A field letitedit can't tell is absent, never guessed.
- `shot`: `framing` (close-up, medium, wide, detail, screen, talking head) and `camera` (still, handheld, pan, tilt,
  moving vehicle, drone, timelapse, slow motion).
- `sound`: `speech` and `music` (yes or no); `music_source` (scene or added); `ambient` in a few words (quiet, room
  tone, steady noise, engine-like hum, music, loud room); `events`, what letitedit's sound detector heard, in its words
  (bang, click, thud, clank, repeated hits, engine-like hum, steady noise, rumble, music, beep, quiet), each with `at` or
  `from` and `to` in file seconds.
- `subjects`: the main people, animals and objects seen (person, animal, vehicle, tool, food, screen, ...).
- `setting`: `indoors_outdoors`, `place_kind` (a kind of place in plain words: kitchen, workshop/garage, road,
  beach/water ...) and `time_of_day` (day, night, dusk, dark). Never the name of a place: a file's `place` stays in
  `files.jsonl`, for the caller's privacy checks.
- `energy` (calm, steady or lively), `b_roll_fit` (yes when the moment can cover someone talking: no speech of its
  own, a usable picture, at least 1.5 s) and `best_frame_s` (the time in the file of its sharpest frame that is
  neither dark nor blown out).

What every index gives, locally and cheaply: `camera` still, handheld, pan and tilt (letitedit's motion analysis),
timelapse and slow motion (the file's frame rates and tags); `framing` close-up, medium, wide and talking head from
the size of the largest face (a face model already on the PC, never downloaded); `speech`; `music` present; `ambient`
and `events`; `energy`, `b_roll_fit` and `best_frame_s`. Best effort, from letitedit's vision pass (a local vision
model, about 6 s of graphics card time per 8 s of video): `framing` wide, detail and screen, `camera` moving vehicle,
`subjects` and `setting`. They are there when a file's vision pass is already on the PC, or when `steps` includes
`vision`; otherwise they are absent and `steps_skipped` says for how many files. Nothing tells a drone shot or
`music_source` yet, so those are absent and `steps_skipped` says so. A 1.1 reader ignores all of these fields.

**Adding the vision fields later (1.2).** Ask `index` again with the same `folders`, the files in `files`, and
`steps: ["vision"]`. `vision` brings `transcripts` and `moments` with it: a file already indexed is split into the
same moments from its cached words (or its picture's cuts) and keeps its moment ids; only the vision pass is new
work. With `changed_only` true (the default) a file whose vision pass is already done is skipped, so the same ask
sent again after a stop carries on; `changed_only: false` does every listed file again. The vision pass adds fields
to moments and never splits them.

**Big libraries.** Files are read one at a time, stage by stage: the files stage reads each file's first 2 MB and its
container's description; transcripts read each talking file's whole sound track (the voice detector, then the speech
model); moments read each video's whole picture at a small size (motion, and the cuts of a file with no talking), and
the vision pass reads the picture's cuts and then samples frames. The analyses are cached (the picture's by content,
the words by file path, size and time), so an unchanged file is not analysed twice; the cuts of a file with no
talking are read again when its moments are. A library sent in chunks (a few hundred files or a few hours each)
loses at most the file in progress to a stop.

### match
Inputs: `video` (a finished video file), optional `folders` (search only footage indexed from these), `max_candidates`
(default 3), `min_confidence` (default 0.5). Output: `verdict` (`matched`, `partial` or `unknown`), `matched_share`,
and `segments` of the video, each with `candidates` (`file_id`, `path`, `moment_ids`, `in`, `out`, `confidence`,
`method`: picture, sound, words). An empty list means unknown. Best effort, local only, against footage that index
has seen.

### inspect
Inputs: `video`, optional `checks`. Output: `duration_s`, size, `hdr`; `watermarks` and `end_cards` (other apps'), `music`
(with `looks_like_known_song` yes/no/unknown, `vocals` and `why`), `film_tv` (movie or TV clips), each a finding
(`found`, `none_found` or `could_not_check` with a reason, plus items with times and up to 3 frames); `transcript`;
`choices` (the record of section 7, as far as can be read from a finished file: `look_id` is null); and `rights`
(`risk` low/medium/high/unknown with `reasons`), and `location_metadata`: `present` or `none` for the dropped-in file,
with the kinds of location `found` (their values are never copied), or `unknown` with `why` when the file couldn't be
read through. It reads the file's metadata (EXIF, IPTC, XMP, MP4 and QuickTime boxes and tags), not the data inside its
picture or sound streams, so `none` there means none in its metadata. Everything runs on this PC with what letitedit already has.
**There is no song or film fingerprint database**, and none is planned for now, so `looks_like_known_song` is often
`unknown` and `film_tv` is `could_not_check`; both are valid answers. `none_found` means letitedit's checks saw none,
not a guarantee.

### Platforms and size caps
Every kind that delivers files (`short`, `batch_shorts`, `still`, `revise`, `retext`, `conform`) takes `platforms` as a
list whose items are a platform id from `capabilities.platforms` or `{id, max_mb}`. `max_mb` (megabytes of 1,000,000
bytes) caps each file for that platform, and **a caller's `max_mb` always wins over the preset's cap**, larger or
smaller; without it the platform preset's cap applies. letitedit lowers the bitrate to fit. A file that still can't fit
is not delivered for that platform: its entry in the output's `files` says `status: "refused"`, `reason:
"cannot_fit_size"`. The platform ids are letitedit's; callers map their own names to them. The presets are
`youtube_shorts`, `tiktok`, `instagram_reels`, `facebook_reels`, `youtube`, `x`, `instagram_story`, `facebook_story`,
`tiktok_photo`, `instagram_feed` and `facebook_feed`; `capabilities.platforms` lists every preset the install has, with
its cap (`max_bytes`, absent when the platform publishes none). The caps are the platforms' published limits for
posting, read in bytes the stricter way (300 MB is 300,000,000 bytes); where two published figures differ the smaller
is kept (section 9).

### short
Inputs:
- `tier`: `preview` or `final`.
- `idea`: `idea_id`, `title` (optional, 1.1: the working title, used in the made files' names; absent: the
  `idea_id`), `pattern`, `hook_line`, `on_screen_text`, `target_seconds`, `about` (what it's about, what must stay in
  or out), `end_with`.
- `sources`: one of
  - `{pieces: [...], strict}`: listed files with `in`/`out` and/or `moment_id`s. `strict` (default true) means only
    those ranges of the caller's footage are used.
  - `{find_in: [folders], hint, avoid_moments}`: letitedit finds the moments.
  - `{none: true}`: a Look that draws everything.
- `look_id` (or `auto`), `theme_id`, `brand_kit` (`intro`, `end_card`, `logo`, `fonts`, `colours`, `handle`),
  `rules` (below, "Rules"), `music`, `captions`, `platforms` (with size caps, above).
- `deliver`: `srt`, `cover`, `project`, `post_text`.
- `references`, and `notes_for_final` (the person's notes on a preview).
- `overlay_text` (optional, 1.1): words on the picture, below.

The two tiers:
- **preview**: New video's log, story and rough cut, rendered only as the phone proxy. No review and no platform
  files. The rough cut is as New video makes it: captions, graphics and the sound pass come at the finish, so the
  proxy shows draft captions drawn from the timeline's own words (`text_items` stay empty until the final), no
  graphics, and music only where the rough cut already has it. Its rule results are what can be said at that point
  (blurs are placed in the final, so a blur rule is `could_not_check` with that reason).
- **final** from a preview: a job with `tier: final` and `from_job` set to the preview. **What a final changes:**
  `tier`, `rules`, `platforms`, `deliver` and `notes_for_final` (often it gives just `{tier: "final"}`); everything
  else is the preview's. Music and caption changes go in `notes_for_final` as notes. A new Look, sources or idea needs a
  new preview: giving `look_id`, `sources` or `idea` is refused (`from_job_unusable`, retry `after_change`), as in 1.0.
  Any other input (a theme, brand kit, music, captions, references, `overlay_text`) is accepted and kept but not
  applied, and named in `status.json` `warnings` with the code `input_ignored`; an input this version doesn't know is
  named with `field_ignored`, as always. It copies the preview's project into its own folder (the preview stays as it
  was) and carries on from the rough cut: the log, story and selects are not done again.
- **final** without `from_job`: the whole run in one job.

Output: `files` (per platform: `status` made or refused, `video`, `srt`, `cover`, and `tonemapped` (1.2) when HDR
footage was turned into SDR for it; a refused entry has `reason` `cannot_fit_size`, `too_long_for_platform` or
`shape_differs` (1.2: a landscape platform for a vertical Short, or the other way round) and a `message`), `project` (the `.mlt`, which a person can open in letitedit;
it refers to the footage where it is), `post_text` (a suggested caption per platform, a hint only, when asked for),
`summary` (two plain lines) and `left_out`. A final's videos are 1080x1920 H.264 at 30 fps unless the platform preset
says otherwise, under its size cap, at -14 LUFS / -1 dBTP.

**HDR footage (1.2).** Every video a Studio job delivers is SDR: H.264, 8-bit 4:2:0, BT.709 primaries, transfer
and matrix, tagged so.
- **HLG** (what phones such as the iPhone record as "HDR video") is accepted. New video edits SDR working copies,
  tone-mapped and kept in the job's own folder (`work/_footage`; the footage itself is only read), and every file
  made from them says `tonemapped: true`. Provenance names the original files and their `file_id`s.
- **PQ (HDR10)**, and wide-colour footage whose transfer letitedit doesn't recognise, is refused before anything is
  made: `hdr_not_supported`, retry `after_change` (export those clips as SDR or HLG and send the job again).
- After the location stripper, every delivered video is probed again; one that isn't plain SDR is not delivered and the
  job fails with `hdr_not_delivered` (a letitedit fault). A file whose HDR signalling was stripped while its picture
  stayed HDR is never handed over.
- A final from a preview uses the preview's working copies, so it needs the preview's job folder.

### overlay_text (1.1)
Words the caller wants on the picture, on `short`, `still`, `revise` and `batch_shorts` (at the top level, and per idea
in a batch, where an idea's items are added to the top level's for that Short). A list of up to 10 items, each:
- `text`: the words.
- `platforms` (optional): only those platforms' files get it; without it, every file.
- `placement`: `safe_area` (the default: where letitedit finds room inside the platform's uncovered area), `top` or
  `bottom` (of that area), or `caption_zone` (the Look's caption zone, when it has one; else `safe_area`, said in
  `why`).
- `if` (optional): conditions, all of which must hold. An open list (section 2). Its first value:
  - `ai_generated_media`: the result's own provenance holds AI-made picture or sound. **What counts:** an entry in
    `provenance.assets` marked `ai_generated: true` whose kind is `generated_picture`, `generated_video` or
    `generated_voice` (a voice-over or a dub), or a music track whose `source` is `ai_made`. **What doesn't:** drawn
    scenes, graphics and motion clips letitedit draws from code, music written as a score (`written`), stock, the
    caller's footage, a colour grade or a blur.

letitedit places each applied item clear of faces and each platform's covered areas, the way captions are placed. The
result's `text_items` list every overlay item (ids `ovl-001` ...), each with `overlay`: `from` (the job field, such as
`inputs.overlay_text.0` or `inputs.ideas.2.overlay_text.0`), `placement`, `if`, and `files`: per made file (a
platform's video, a still's platform or size, or a preview's proxy) `applied` true or false and `why` in one plain
line. A `revise` without `overlay_text` keeps the earlier job's items; with it, its items replace them.

### Rules: must, never and prefer (1.5)

`rules` (`short`, `batch_shorts`, `still`, `revise`) is a list, each rule an `id`, a `kind`, its `text` in plain words
and an optional `check` hint (`capabilities.rule_checks`).
- `must` and `never` are requirements.
- `prefer` (1.5) ranks below every `must` and `never`. letitedit follows a prefer unless it conflicts with a `must` or
  a `never`; between two prefers that conflict, the earlier one in the job's list wins. A `short` tells the editing AI
  this in plain words, preview and final.
- Every rule, a prefer too, is checked and reported in `result.json` `rules` (section 7) with the same fields and
  statuses. A prefer that gave way to another rule is `not_applicable`, its `reason` naming that rule, with
  `gave_way_to` listing the ids of the rules it gave way to.
- **A prefer not met never moves the review's verdict on its own** (not to `revise`, `incomplete` or `blocked`): it is
  a note in `rules`, never a problem the review counts. The AI is told to keep prefers out of the brief's checked
  fields, and the review leaves out of its counts any problem its critic raises about one.
- A preview reports a prefer as it reports the others (most are `could_not_check` until the final).
- **Sending a prefer to an older install.** A 1.4 or earlier letitedit refuses a job with a `prefer` rule: the schema
  takes only `must` and `never`, so the job is refused as `invalid_job`, its problem naming the rule's field
  (`inputs.rules.<n>.kind`). Send a prefer only when `capabilities.rule_kinds` lists it.

### batch_shorts
Inputs: `tier`, `sources`, `ideas` (each with an `idea_id`; an idea may set its own `look_id`, `sources`, `title` or
`overlay_text`), `look_id`, and the shared `brand_kit`, `rules`, `music`, `captions`, `platforms`, `deliver`,
`overlay_text`; `no_shared_moments` (default true).
The footage is logged once and the stories are planned together. Then each Short is cut, finished and reviewed on its
own: each final has its own review. Each item is written under `items/<idea_id>/` with its own full short
`result.json` (job id `<batch job id>.<idea_id>`, usable as a `from_job`). The output lists the `shared` log, story
plan and their cost, and the `items` with their state. One item failing doesn't fail the others; the batch is `done`
when every item has ended, and `failed` only when the shared pass failed.

### still
Inputs: `layout` (from `capabilities.stills_layouts`), `pictures` (files, video frames at a time, or moments), `text`
(the layout's fields), `look_id`, `brand_kit`, `sizes` (`story_9x16`, `feed_4x5`, `feed_1x1`), `platforms` (whose
covered areas to keep clear and whose size caps apply: `instagram_story`, `facebook_story`, `tiktok_photo`,
`instagram_feed`, `facebook_feed`), `motion` and `motion_seconds` (3-60), `music`, `sticker_room`, `rules`, `format`
(png or jpg), `overlay_text` (1.1). Output: `sets` per size (one picture, a carousel in order, or a motion-still MP4) with the
`sticker_box` left clear when asked, `checks` (`legible_at_phone_size`, `covered_areas_clear`, `faces_clear`, notes),
`project` for a motion still, `post_text`, and per set an `alt_text` hint (a plain description of the picture). Its
shared fields include `text_items` (with their `box`) but no `choices` or `review`. A still without motion
has only a poster in `proxy`. Its `rules`: a `must` or `never` not met stops delivery (`render_failed`, retry `after_change`); one
that could not be checked is reported `could_not_check` with its reason and the still is delivered, as a Short's is. A `prefer` not met gets one redo inside the job (laid out, drawn and checked again with its reason;
the redo's AI use is in `cost`), then is reported `applied` or `not_met` with its reason, and the still is delivered;
a `prefer` that could not be checked is reported as such. A prefer never fails a still.

### revise
`from_job`: a finished short (a `preview` or a `final`), revise, retext, batch item or (1.1) still.

**A still's revise** (1.1): the notes change the still's text, layout or picture choice, and it returns a still: a
still's output (`sets`, `checks`, ...) plus `what_changed`, `changes` and `revision_of`, and a still's shared fields (no
`choices` or `review`). A still has no tier: a still's revise names none.

**A video's revise:** a revise of a preview with
`tier: preview` (the default for a preview) returns a preview again: the rough cut changed, shown only as the phone
proxy, no review and no platform files. With `tier: final` it goes on to a final, as a final from a preview does. Inputs: `notes` (each `text`, optional `at_s` pinned to a
time in the earlier video, optional `platform`) and/or `hook` (`{from_job: <hooks job>, hook_id}` puts that opening
in), `tier`, `platforms`, `rules`, `overlay_text` (1.1; absent: the earlier job's). The earlier project is copied; the notes are applied the way Review applies them.
Output: everything a short returns, plus `what_changed` (one plain line), `changes` (per note: done yes, partly or
no, and what was done) and `revision_of`.

### retext
`from_job`: a finished short, revise, retext, still or batch item. Inputs: `changes` (`id`, `text`), `platforms`.
**No AI runs.** Each change goes to the item with that `id` in the earlier job's `text_items`:
- `live` (a caption or text item on the timeline): changed in place;
- `remake` (drawn by letitedit: a code scene, a motion clip, a graphic): drawn again from the source letitedit kept,
  with the new text;
- `baked` (inside a picture letitedit can't redraw: a generated image, words in the footage): refused, reason
  `baked`.

A new text longer than its box holds (`max_chars`, or the drawn layout's measured fit) is refused for that item
(`too_long`); the other changes still apply. The video or picture is exported again under the PC lock. Output:
- **a video's retext:** everything a short returns (its `review` is `not_reviewed`: only text changed);
- **a still's or a motion still's retext (1.2):** everything a video's retext returns, so a 1.0 or 1.1 caller reads
  it as before, with values that hold for a still: `files` empty (the pictures are in `sets`), `project` (the still's
  working project), `choices` with no cuts or spoken words, and `review` `not_reviewed`. Added beside them: the still's
  own output, `sets` and `checks`, as a still's revise returns;
- either way plus `applied` (per id: `changed`, `redrawn`, `unchanged_same_text` or `refused` with a reason),
  `what_changed` and `revision_of`.

Only text changes, so **a retext's `provenance`, `ai_labels` and `music` are the earlier job's** (1.2 states it): AI-made
media in the draft stay in the result's provenance, and an overlay item with `if: ["ai_generated_media"]` (reworded by
the retext or not) is decided on them again for the retext's own files. Item ids carry over, so a retext can follow a
retext.

### hooks
`from_job` (a finished Short), or `moments` for a Short not yet made. Inputs: `count` (default 3), `avoid_moments`,
`previews` (a phone proxy of each candidate's first seconds), `kinds`. Output: `candidates`, each with `hook_id`,
`kind` (`hook_kind`), `line`, `first_3s`, `why`, `sources` and an optional `proxy`. A `revise` with `hook` puts one in.

### conform
`video` (a finished file) or `from_job` (that job's main video). Inputs: `platforms`, `max_mb` per platform, `fps`
(default 30), `loudness_lufs` (-14), `true_peak_dbtp` (-1), `cover_at_s`, `fit` (`refuse`, the default, or `pad`).
**No AI and no creative change:** H.264, the frame rate, under the size cap, the loudness, HLG or PQ tone-mapped to
SDR, and a cover frame. It never crops or reframes. A platform whose shape differs is refused for that platform
(`shape_differs`) unless `fit: pad`. It runs under the PC lock. Output: `source` (its hash, size, fps, `hdr`, loudness)
and `files` per platform (`made` with `video`, `cover`, `tonemapped`; or `refused` with a reason). Its shared fields
are `provenance` and `proxy`. AI labels, music and rules carry over from `from_job` when there is one; otherwise
they are absent.

### learn
Inputs: `references` (1-3, each a `path` or a `url`, fetched privately), `note`. It works as the app's Learn from a
video: the AI names the Look and saves it in the person's My Looks, and sharing follows their own Share learned Looks
setting. Output: `look` (`id`, `name`, `styles`, `formats`, `needs_footage`, `fits`, `card`) and `left_out`. The Look
can be used by `look_id` at once.

## 7. What every making job returns

`short`, `revise` and `retext` return all of these. `still` returns all but `choices` and `review`. `conform`
returns `provenance` and `proxy`, plus the rest carried from `from_job`. A batch returns them in each item's
`result.json`.

- **`provenance`**:
  - `sources`: every range of the caller's footage in the output, with `path`, `file_id`, `moment_ids`, `in`, `out`,
    `role` (main, broll, audio_only, still_frame, photo) and `at` (where it starts in the output). A frame used as a
    still (`still_frame`) and a photo are one frame: their `in` equals their `out`.
  - `assets`: everything else, with `kind`, `what`, `source`, `url`, `path`, `licence` and `ai_generated`, and the
    `ranges` where it is. Kinds (an open list): stock video or picture, generated picture, video or voice, library
    sound or sticker, drawn scene, graphic, motion clip, web picture, font, brand kit, reference. A library sticker or
    emoji, and an AI-made picture, that a graphic draws is listed over the graphic's range. A still lists the font its words are drawn in (`font`, 1.6: with its licence id, section 7, "Licences"); a
    video's caption and title fonts are not listed; a picture fetched from the web is `web_picture`, with `url` the page it came from.
- **`ai_labels`**:
  - `generated_picture`, `generated_voice`, `generated_music` and `altered_real_footage` (true or false);
  - `items`, each AI-made thing with its kind, whether it is `realistic` and when;
  - `platforms`: per platform, `label` `required`, `not_required` or `unknown`, with `why` and `rule_as_of` (letitedit's
    reading of that platform's labelling rule, from its platform profiles). **1.4:** an AI-made picture that a graphic
    draws counts like any other (it is an asset with `ai_generated: true` over the graphic's range, so the label reads
    `required`). When a graphic draws a picture letitedit can't trace to its maker (a picture file named in its recipe
    that is not on the PC, or drawing code that loads a picture from a path it works out when it runs), the label is
    `unknown`, never `not_required`, and `why` says which graphic and why; an AI-made picture found elsewhere still
    makes it `required`.
- **`music`**:
  - `tracks`, each with `title`, `artist`, `source` (letitedit_library, youtube_audio_library, pixabay, written,
    ai_made, person_file, in_source_footage), `licence` (`id`, `commercial_use`, `attribution_required`, `attribution_text`,
    `note`, `content_id_registered` no/yes/unknown; see "Licences" below) and `ranges`;
  - `policy_met`: yes, no, could_not_check or no_policy, against the job's `music` policy.
- **`rules`**: one entry for every rule in `job.json`, in its order:
  - `status`: `applied`, `not_applicable`, `could_not_check` or `not_met`;
  - `how`: detector, ai_review, by_construction or not_checked;
  - `reason`, one plain line, required for every status but `applied`;
  - `gave_way_to` (1.5, prefer rules only): the ids of the rules a prefer gave way to; its status is then
    `not_applicable`;
  - `ranges`, each a `start`, an `end` and a one-line `note`;
  - `frames`: up to 3 small JPGs in `evidence/` (about 360x640) for anything applied or flagged.

  Until letitedit has detectors for plates, faces and house numbers, such rules are checked by the AI's and the
  critic's review of frames (`how: ai_review`) or are `could_not_check`. `capabilities.rule_checks` says which hints
  have a detector. The person's approval stays the backstop. A prefer not met is a note here and nothing else: it never
  changes `review` (section 6, "Rules").
- **`choices`** (`short`, `revise`, `retext`; `inspect` as far as it can):
  - `look_id`, `look_name`, `theme_id`, `pattern`;
  - `hook_kind`, from the fixed list: question, bold_claim, result_first, mid_action, number_or_list,
    guess_or_challenge, before_after, story_tease, reaction, how_to, other;
  - `hook_line`, and `first_3s` (one plain line on what is seen and heard);
  - `duration_s`, `cuts_per_min`, `words_per_min`;
  - `caption_style`, `music_kind`, `music_mood`;
  - `broll_share` (the share of the running time not on the main footage);
  - `moments` (`moment_id`, `file_id`, `in`, `out`).

  `measured` names the fields measured from the exported timeline; the rest are the AI's description.
- **`text_items`**: every caption and on-screen text, each with `id`, `kind` (on_screen or caption), `start`, `end`,
  `text`, `editable` (live, remake or baked, as in retext), `max_chars` when known, `platforms` when it isn't in
  every file, and `box` when known (`x`, `y`, `w`, `h` as fractions 0-1 of the frame from the top-left, at its widest),
  so a tap on the picture can be matched to an item's id. `still` returns them too. An item made from `overlay_text`
  (1.1) also has `overlay`, saying per made file whether it was applied and why (section 6, "overlay_text").
- **`proxy`**: `video` (about 720x1280, or 1280x720 for landscape; H.264; under about 8 MB, with the bitrate lowered
  to fit) and `poster` (a JPG frame), for a phone to stream instead of the finals.
- **`review`** (`short`, `revise`; `retext` says `not_reviewed`):
  - `verdict`: ready, revise, incomplete or blocked from letitedit's review gate, or `not_reviewed` for a preview;
  - `plain`: review.md's plain section, as written;
  - `path`, the `critical`, `major` and `minor` counts, and the `critic` that ran;
  - `not_checked` (1.3): the checks the review couldn't do, each `{check, why}`, absent when it did them all. `check`
    is an open list; `speech` means the review couldn't hear the video's speech (its speech model didn't run, or it
    heard none of a video that talks, or nothing in a long stretch of its talk). Then what is said there wasn't
    judged: a spoken claim or line is never called missing for it. The verdict is never `ready` while a check is
    listed: `blocked` for a critical problem, `revise` for a major one, else `incomplete`.
- **`cost`**:
  - `wall_s`, and of it `waited_s` (the PC lock, memory, the person's own work, the AI's limit);
  - `ai`: engine, model and effort;
  - `tokens`: input, cache_write, cache_read, output and total;
  - `usd_api_equivalent`: what the tokens would cost at API prices, or null. The person pays through their own
    subscription; this is never a bill;
  - `steps`, and per-stage `stages`;
  - `measured`: false when the AI's session logs couldn't be read.
- **`versions`**: `contract`, `letitedit` (the build), `tools` (the tool code's commit), and `look` (the Look's hash)
  when a Look was used.
- **`outputs`**: every file made, with `role` (an open list: video, srt, cover, project, proxy, poster, image,
  motion_still, review, transcript, index, evidence, other), `path`, `bytes`, `sha256` and, where it applies,
  `platform`, `size`, width, height, fps, duration, codec, loudness and true peak.
- **`warnings`**: things worth knowing that didn't stop the job. Their `code` is an open list: `field_ignored` (a field
  this version doesn't know), `input_ignored` (1.1: an input the job kind accepts but doesn't apply here, such as
  `captions` on a final from a preview), `fake_studio` (made by the reference fake), and others as they are added.

### Licences (1.4)

Every asset and every song carries a `licence`: `id`, `commercial_use`, `attribution_required`, `attribution_text`
(when a credit is owed), `note` and, for a song, `content_id_registered`. The `id` is one of a **closed list**
(the schema's `enum`), so a caller can match on it; a licence letitedit can't tell is `unknown`, never a guess.
`commercial_use` is what the licence's own terms say, read from the licence text as its pack ships it, and is **not
legal advice**: `allowed`, `allowed_with_credit`, `forbidden` or `unknown`. Limits a value can't hold are in `note`.
`attribution_required` is absent for `unknown`. `attribution_text` is the credit line the video owes, the same text
`letitedit_export_job` and `letitedit_review_bundle` list for the project; it is filled whenever `attribution_required`
is true.

| `id` | `commercial_use` | credit | what it is, and where letitedit reads it |
|---|---|---|---|
| `own` | allowed | no | the person's own file: one kept in My assets (a path under that folder, or a `mine:` reference), and songs whose source is `person_file` or `in_source_footage`. The rights are theirs to state |
| `CC0-1.0` | allowed | no | library sounds, music, animations and graphics, by the asset's own manifest entry |
| `public-domain` | allowed | no | library items whose manifest says public domain |
| `MIT` | allowed | no | Fluent emoji, Tabler icons (the licence's notice stays with the files, not the video) |
| `CC-BY-4.0` | allowed_with_credit | **yes** | Noto animated emoji; a map whose place names are GeoNames: `attribution_text` is the credit |
| `lottie-simple-licence` | allowed | no | the Lottie elements and title cards (credit encouraged, not required) |
| `pixabay-content-licence` | allowed | no | stock from Pixabay, from the download's own sidecar; `note` has its limits |
| `pexels-licence` | allowed | no | stock from Pexels, the same; `note` has its limits |
| `generated` | allowed | no | an AI-made picture or video (an image service); `note` says AI labels apply |
| `made-by-letitedit` | allowed | no | drawn by letitedit's own code: scenes, motion clips, graphics, maps |
| `written-for-this-video` | allowed | no | music written as a score for this video |
| `made-on-this-pc` | allowed | no | music or a voice made by a model running on the PC |
| `OFL-1.1` | allowed | no | 1.6: a font under the SIL Open Font License 1.1 (most of the bundled library and of Google Fonts), read from the `OFL.txt` beside the font file. Its conditions bind the font files, not a picture or video drawn with them |
| `Apache-2.0` | allowed | no | 1.6: a font under the Apache License 2.0, read from the `LICENSE.txt` beside it; its notice conditions bind copies of the font files |
| `Ubuntu-font-1.0` | allowed | no | 1.6: a font under the Ubuntu Font Licence 1.0 (Ubuntu), read from the `UFL.txt` beside it; its conditions bind the font files |
| `unknown` | unknown | not known | everything else: a sound or file with no receipt, a song with no licence on record, a YouTube Audio Library track (each has its own terms), and **pictures fetched from the web** and anything made from one: their rights are not known, so the licence is `unknown` and `note` says where each came from and the licence its source stated |

The licence of a library asset is read from the library's own manifest for that file, per source or per item, never
from its folder; a file in a library folder that the manifest does not list is `unknown`. Stock and on-demand songs
are read from the sidecar written beside the download. Music is read from the library manifest or from the song
folder's own list (`library.csv`). A font is read from the licence file in its family's folder (the bundled library and
a Google Fonts family fetched on demand both keep it there; an on-demand family's own record names the file); a font
with no licence file letitedit knows there (a Windows font, say) is `unknown`.

**Font ids and the job's version (1.6).** `OFL-1.1`, `Apache-2.0` and `Ubuntu-font-1.0` are sent only to a job whose
`contract_version` is `1.6` or later. A job at `1.5` or earlier gets `unknown` for the same font, with the licence named
in `note` ("SIL Open Font License 1.1 (OFL-1.1, read from the font's own OFL.txt). Contract 1.5 has no id for it (1.6
adds OFL-1.1), so the id is unknown."), so no earlier caller meets an id its schema doesn't list. A retext answers in
its own job's version: a font the earlier result listed is read again for it.

**What a 1.3 reader sees.** Nothing breaks. 1.3's `licence.id` was any string and 1.4 only narrows what letitedit
sends, so a 1.3 reader accepts every 1.4 result and ignores `commercial_use` and `note`. Two things it will notice if
it matched on 1.3's values: `letitedit-library` is no longer sent (it is now the asset's real licence: `CC0-1.0`,
`public-domain`, `MIT`, `CC-BY-4.0` or `lottie-simple-licence`), and things drawn by letitedit's own code, which were
`generated`, are `made-by-letitedit` (`generated` now means AI-made). `attribution_required` is no longer sent as
`false` for what is unknown.

## 8. Errors

A failed or cancelled job's `result.json` has `error`:
- `code`: an open list, below;
- `message`: plain English for a person, saying what went wrong and what to do;
- `retry`:
  - `yes`: the same job again may work. For `cancelled` this means a retry can work, not that a caller should send it
    again by itself: a cancel is the person's choice, and only the person retries it;
  - `after`: wait `retry_after_s` first (always given with `after`; for `ai_limit` it is the AI's reset time when it
    gave one, else 3600);
  - `after_change`: only after the job or the PC changes, as the message says;
  - `no`: it won't work;
- `stage`, where it happened;
- `detail`: technical, for a log.

`outputs` still lists the files that were finished.

| Code | Retry | Meaning |
|---|---|---|
| `invalid_job` | after_change | job.json doesn't match the schema (validate gives the fields) |
| `unsupported_version` | no | another major version |
| `job_id_conflict` | after_change | that id was used for a different job.json |
| `output_dir_refused` | after_change | inside a source folder, the install, or a folder with other files |
| `source_missing`, `source_unreadable` | after_change | a footage file is gone, on a drive not connected, or damaged |
| `look_unknown`, `platform_unknown`, `layout_unknown` | after_change | not on this install (see capabilities) |
| `kind_not_installed` | no | this kind isn't available on this install yet |
| `from_job_unusable` | after_change | the earlier job isn't finished, isn't of a kind this one continues, or the change needs a new preview |
| `no_footage_for_idea` | after_change | the folder has nothing the idea needs |
| `location_not_removed` | no | a made file still had location metadata after stripping; it was not delivered (a letitedit fault) |
| `hdr_not_supported` | after_change | footage is PQ (HDR10) or HDR of a kind letitedit can't turn into SDR faithfully (1.2) |
| `hdr_not_delivered` | no | a made file was still HDR after tone mapping and stripping; it was not delivered (a letitedit fault, 1.2) |
| `ai_unavailable` | after_change | the AI named (or any AI) isn't installed or signed in |
| `ai_limit` | after | the AI's usage limit was reached and didn't reset within the job's time limit |
| `ai_failed` | yes | the AI stopped or answered nothing usable |
| `render_failed` | yes | a render or export failed |
| `out_of_memory` | yes | not enough memory even after waiting |
| `disk_full` | after_change | not enough free disk space |
| `timeout` | yes | the job's time limit (timeout_s) ran out |
| `interrupted_too_often` | yes | its process stopped max_attempts times |
| `cancelled` | yes | asked for (a retry only when the person asks) |
| `internal` | yes | a letitedit fault; detail says what |

Per-item refusals inside a job that succeeded (retext's `baked` and `too_long`, conform's and short's
`shape_differs`, a platform file's `cannot_fit_size` or `too_long_for_platform`) are not errors; they are in that
kind's output.

## 9. Settled

- No Studio worker at Windows sign-in: every entry point starts it (section 3).
- No song or film fingerprint database for `inspect` for now: `unknown` and `could_not_check` are the answers.
- Platform ids are letitedit's; presets for X, Stories, TikTok photo posts and feed pictures were added. Their lengths,
  file sizes, photo counts and picture formats are checked against Buffer's help centre (status `posting-service`:
  the limits for posting through Buffer); where Buffer and another source differ the stricter value is kept and the
  profile's note gives both. Values neither gives stay `unconfirmed` in the profiles.
- Size caps checked again on 19 Nov 2026 against the platforms' published limits (contract 1.1), read in bytes the
  stricter way: `instagram_reels` 300,000,000 (it was 300 x 1024²); `instagram_story` 100,000,000 (was none);
  `instagram_feed` 300,000,000 (a feed video posted through Meta's publishing API is a Reel; was 4 GiB);
  `facebook_reels` and `facebook_feed` 1,000,000,000 (Buffer's limit; Meta's ads guide gives 4 GB; was 4 GiB);
  `x` 512,000,000 (was 512 x 1024²). `facebook_story` stays 1,000,000,000. Each profile's note gives its sources.

## 10. Change log

- **1.6** (20 Nov 2026; additive, from Channel: real Story pictures' fonts, which it could never clear as `unknown`):
  - `licence.id` gains `OFL-1.1`, `Apache-2.0` and `Ubuntu-font-1.0` (section 7, "Licences"): commercial use allowed,
    no credit owed for a picture or video drawn with the font, the note saying what the licence's conditions bind.
  - They are sent only to a job whose `contract_version` is 1.6 or later (section 2); a 1.5 or earlier job gets
    `unknown` with the licence named in `note`, as before.
  - A still's `provenance.assets` lists its font (it already did in 1.5, as `unknown`); a retext's font licences
    follow the retext job's own version.
  - All of 1.6 is additive within major 1 for readers: a 1.5 job never receives a new id, so a 1.5 reader reads every
    result it asked for; `capabilities.contract_version` says `1.6`.

- **1.5** (20 Nov 2026; additive, from Channel: rules it learns from review notes):
  - A rule's `kind` gains `prefer`, below every `must` and `never` (section 6, "Rules"): followed unless it conflicts
    with a must or never, the earlier of two conflicting prefers winning. It is reported in `rules` like the others;
    one that gave way is `not_applicable` with `gave_way_to`. A prefer not met never moves the review's verdict.
  - `capabilities` gains `rule_kinds` (`must`, `never`, `prefer`). A reader that finds none should assume `must` and
    `never` only; a 1.4 install refuses a prefer as `invalid_job`.
  - All of 1.5 is additive within major 1 for readers: a 1.4 reader of a 1.5 result reads every field it knows and
    ignores `gave_way_to` and `rule_kinds`.

- **1.4** (19 Nov 2026; additive, from Channel: licences it can clear):
  - `licence.id` is one of a closed list (section 7, "Licences"), and `licence` gains `commercial_use` (`allowed`,
    `allowed_with_credit`, `forbidden`, `unknown`) and `note`. `attribution_text` is filled for every licence that
    owes a credit, with the text letitedit's own credit list gives.
  - Each asset's licence is its real one: the library's manifest per asset (CC0-1.0, public-domain, MIT, CC-BY-4.0,
    lottie-simple-licence), stock from its source (pixabay-content-licence, pexels-licence), things letitedit's code
    draws `made-by-letitedit`, AI-made pictures `generated`, music and voices made on the PC `made-on-this-pc`,
    pictures fetched from the web `unknown` with their source page. Library stickers and emoji that a graphic draws
    are listed as assets, and so are AI-made pictures a graphic draws (`generated_picture`, `generated`). A graphic
    whose pictures can't be traced makes a platform's AI label `unknown` (section 7, `ai_labels`). A file from the
    person's My assets is `own`. Fonts are not listed.
  - All of 1.4 is additive within major 1 for readers: 1.3 took any string as an id, so a 1.3 reader reads every 1.4
    result (section 7 says what it will see differently).

- **1.3** (19 Nov 2026; additive, from Channel: a review that couldn't hear the video):
  - A video's `review` gains `not_checked`, the checks letitedit's review couldn't do, each with `why` (section 7).
    `speech` is the first: when the review couldn't hear the video's speech, the verdict is never `ready`
    (`incomplete`, or `revise` and `blocked` for a major or critical problem found as well), and a spoken claim it
    couldn't hear is not a `blocked`.
  - All of 1.3 is additive within major 1: a 1.2 reader ignores `not_checked` and reads the verdict as before.

- **1.2** (19 Nov 2026; additive, from Channel: shot choice from a richer index, and the HDR rule):
  - `index` moments gain the optional fields `shot`, `sound`, `subjects`, `setting`, `energy`, `b_roll_fit` and
    `best_frame_s`, each value with `confidence` and `how`, every value list open (section 6, "Moment fields").
    `setting` never holds a place's name.
  - `index` `steps` gains `vision` (letitedit's vision pass for the fields it gives); absent `steps` means all but
    `vision`. `steps_skipped` says which fields wait for it.
  - The HDR rule (section 6, "HDR footage"): HLG is accepted and tone-mapped to SDR; PQ and unrecognised wide colour
    are refused. New error codes `hdr_not_supported` and `hdr_not_delivered`.
  - A Short's platform file gains `tonemapped`, and its refusal `reason` (a fixed list) gains `shape_differs`.
  - Stated: what a preview's proxy shows (draft captions from the timeline's words, no graphics).
  - A retext of a still or a motion still adds the still's own output (`sets`, `checks`) beside everything a retext
    returned in 1.1 (`files` empty, `project`, `choices`, `review`), so a 1.1 caller reads it as before.
  - A retext keeps the earlier job's `provenance`, `ai_labels` and `music`, so an overlay item with
    `if: ["ai_generated_media"]` (a reworded "Made with AI" line) still applies when the draft holds AI-made media.
  - `status.json` gains `counts` (files done of total and minutes of footage done of total) while an `index` stage
    works through the files, and `progress` moves within a stage (section 3, "Counts").
  - An `index` stage started again after a stop carries on after the last file it finished.
  - `steps: ["vision"]` brings `transcripts` and `moments` with it, so asking for the vision fields of files already
    indexed keeps their moment ids (section 6, "Adding the vision fields later").
  - `capabilities.typical` by AI: each figure gains `ai` (what it was measured with), `match`, `match_note` and `by_ai`; a figure
    measured here counts only jobs run with the same engine, model and effort; `inputs.ai` asks for a given AI, and
    a request with no figure of its own gets the nearest, saying so (section 6, "typical by AI"). letitedit's
    reference figures for a Short were measured at extra high effort, the person's chat setting.
  - Stated: a job's `ai` overrides the person's chat choice for that job only; a job without it inherits theirs
    (section 5).
  - All of 1.2 is additive within major 1: a 1.1 job runs as before.

- **1.1** (19 Nov 2026; additive, from Channel's first review):
  - Open lists: asset `kind`, event `type`, `waiting_on.what` and output `role` are plain strings in the schemas, with
    the known values listed, and are named in section 2 with the overlay conditions.
  - A job folder holding a `cancel` file when letitedit claims it ends at once as `cancelled` (no files, never run);
    the `cancel` command does the same for an inbox job not claimed yet; deleting one's own unclaimed inbox file is
    fine.
  - New input `overlay_text` (on `short`, `still`, `revise`, `batch_shorts` and each batch idea) with `text`,
    `platforms`, `placement` (`safe_area`, `top`, `bottom`, `caption_zone`) and `if` (open list; `ai_generated_media`);
    `text_items` gain `overlay` (`from`, `placement`, `if`, `files` with `applied` and `why`).
  - `revise` continues a `still` and returns a still; the result schema asks `choices` and `review` only of a video's
    revise.
  - An idea may carry `title`. `ai_limit` always carries `retry_after_s` (3600 when the AI gives no reset time).
  - Stated: `retry: yes` on `cancelled` is the person's call; a still frame's provenance has `in == out`; a final from a
    preview changes `tier`, `rules`, `platforms`, `deliver` and `notes_for_final` (`look_id`, `sources` and `idea`
    stay refused as in 1.0; any other input is accepted, kept and not applied, with the new warning `input_ignored`);
    a caller's `max_mb` always wins; the first status after
    `submit` is `queued` or `running`; `capabilities.platforms` lists every preset (the example and the fake too).
  - Size caps corrected (section 9). The header says what runs.

- **1.0** (19 Nov 2026, 06:30 PT; after the third independent review): a job folder's claim names its Studio folder
  and job id, and the folder is written under its own lock through acceptance (two Studio folders can't both take one);
  delivered video is H.264 or HEVC with its SEI messages taken out and checked; the decode check is stated as what it
  is (a picture in full, a video's first frame); `inspect`'s `none` covers a file's metadata.
- **1.0** (19 Nov 2026, 04:30 PT; after the second independent review): each side takes a job folder and a Studio
  folder atomically before writing; two inbox files naming one job folder can't both take it; delivered pictures are
  converted to sRGB without a colour profile and must decode; every box inside a video's sample descriptions is
  checked; a malformed field is a normal refusal.
- **1.0** (19 Nov 2026, 02:30 PT; after the first independent review): a folder lock that can't be taken fails with
  `busy` instead of writing; sending is safe to repeat; the accepted `job.json` is the one that runs; the inbox claims
  before it writes; every read path protects its folder; within a lane a resuming job goes first; all metadata is
  removed from delivered files and checked by a separate check that fails closed; `inspect`'s `location_metadata` may
  be `unknown`; what counts as a job's own folder is stated exactly.
- **1.0** (19 Nov 2026, 01:00 PT; additive): the fake behind the real command line (`LETITEDIT_STUDIO_FAKE=1`,
  "Testing against the fake"), the `fake_studio` warning and `capabilities.fake`; the command line is `<cli>` (the
  entry file `letitedit_studio.py`), and the Python functions are in `letitedit.studio.service`. The new presets'
  values checked against Buffer's help centre (section 9).
- **1.0** (19 Nov 2026, 01:25 PT; still 1.0 because nothing had shipped): Channel's review folded in, all additive.
  Platform items may be `{id, max_mb}` (size caps on every delivering kind); new presets `x`, `instagram_story`,
  `facebook_story`, `tiktok_photo` and feed picture sizes; `location_metadata: "none"` on every made media file and the
  error `location_not_removed`; `inspect`'s `location_metadata`; `text_items` get `box` and are in `still` results;
  `still` sets get `alt_text`; short `files` entries get `status` (made or refused); `revise` of a preview stated;
  `urgent` and `normal` are the lane names to write; every entry point starts the worker; no fingerprint database; the
  Python functions are `letitedit.studio`'s (not `letitedit_ai`); `x_` fields.
- **1.0** (draft, 19 Nov 2026, `215742ee`): first version. Twelve kinds; the shared fields; the lanes; validate.
