"""What a New video run took from the AI: tokens and steps per stage, read from the AI's own session logs.

    python run_cost.py <folder> <since-epoch-s> [--until <epoch-s>] [--sessions id,id]   writes run-cost.json and .md
    python run_cost.py --refresh <project>.letitedit      the same measurement again, from that folder's run-cost.json

For us and for beta testers' problem reports, never shown as a bill. A run is every AI session (Claude Code or Codex)
that worked on files in `folder` after `since`: one long conversation, or one per stage. Stages come from the
project journal's `stage:<name>:done` notes, bare or with a one-line summary (letitedit-firstcut FIRST-1); what follows the last note is "finish and
review". The files go into each `<project>.letitedit` working folder in `folder` that the run wrote (else `folder`).

A step is one call to the model. Claude's log gives new input, cache writes, cache re-reads and output per step;
Codex's gives input (cached included), cached input and output per step.

Calls of the person's AI outside the run's conversation (New hook's titles) leave no session log; each is a line in
`<project>.letitedit/background-ai.jsonl` ({time, what, engine, model, usage, usd}: Claude's own token use and price
from its JSON output; Codex's plain answer has none). Those after `since` (and up to BACKGROUND_GRACE_S after `until`)
count in their stage's tokens and price, not in its steps, minutes or largest context; one without a token count is
listed as not measured.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

LAST = 'finish and review'
# API-equivalent prices in US$ per million tokens: (input, output, cache read), from Anthropic's published pricing
# (https://platform.claude.com/docs/en/about-claude/pricing, as of 12 Nov 2026). Cache writes cost 1.25x input for the
# 5-minute cache and 2x for the 1-hour one (Claude Code writes the 1-hour cache), the same page. A model is matched by
# its longest prefix here. Left out: Claude Haiku 5.5 (its price depends on each call's prompt size and its cache-read
# price isn't published per model) and Codex's GPT-6.1-Sol (above 272k tokens only its cached-input price is published,
# and a New video's conversation passes that): their runs show no US$ figure.
PRICES = {
    'claude-opus-5-5': (4.0, 20.0, 0.20),
    'claude-sonnet-5-5': (2.0, 10.0, 0.10),
    'claude-fable-5-1': (10.0, 50.0, 0.25),
    'claude-fable-5-2': (8.0, 40.0, 0.20),
}
WRITE_5M, WRITE_1H = 1.25, 2.0
MAX_LOG_BYTES = 200 * 1024 * 1024
BACKGROUND_FILE = 'background-ai.jsonl'
BACKGROUND_GRACE_S = 300      # a background call this long after `until` (the app's hook titles as a run ends) counts


def _ts(text):
    try:
        return dt.datetime.fromisoformat(str(text).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _homes():
    """The AIs' own folders: the person's, and letitedit's own AI home when one is set (LETITEDIT_AI_HOME)."""
    homes = [Path.home()]
    extra = os.environ.get('LETITEDIT_AI_HOME')
    if extra:
        homes.append(Path(extra))
    return homes


def _mentions(path, needles):
    """Whether a log names the folder (its path as written, or JSON-escaped)."""
    try:
        if path.stat().st_size > MAX_LOG_BYTES:
            return False
        text = path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return False
    low = text.lower()
    return any(n in low for n in needles)


def _needles(folder):
    raw = str(Path(folder).resolve())
    forms = {raw, raw.replace('\\', '/'), json.dumps(raw)[1:-1]}
    return [f.lower() for f in forms if f]


def _lines(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        yield from fh


def _asked_about(path, engine, needles):
    """(whether a request in this session - a user message, not a tool's reply - names the folder, the session's
    working folder)."""
    cwd, asked = '', False
    for line in _lines(path):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        texts = []
        if engine == 'claude':
            cwd = cwd or o.get('cwd') or ''
            m = o.get('message') or {}
            if o.get('type') == 'user' and m.get('role') == 'user':
                c = m.get('content')
                texts = [c] if isinstance(c, str) else [b.get('text', '') for b in c or []
                                                         if isinstance(b, dict) and b.get('type') == 'text']
        else:
            p = o.get('payload') or {}
            if o.get('type') == 'session_meta':
                cwd = p.get('cwd') or cwd
            if o.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
                texts = [b.get('text', '') for b in p.get('content') or [] if isinstance(b, dict)]
        if not asked and any(n in str(t).lower() for t in texts for n in needles):
            asked = True
        if asked and cwd:
            break
    return asked, cwd


def _in_repo(cwd):
    """Agents working on letitedit itself run in its install folder; the app never starts a run's AI there."""
    try:
        from letitedit.core import paths
        root = paths.CODE_ROOT.resolve()
    except Exception:  # noqa: BLE001 - run on its own: the install folder is three levels above bridge/letitedit/app
        root = Path(__file__).resolve().parents[3]
    if not cwd:
        return False
    try:
        return Path(cwd).resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def find_logs(folder, since, homes=None, sessions=None):
    """[(engine, path)] of the run's sessions written after `since`: the ones named in `sessions` (session ids), else
    every session whose own request names `folder` and that did not run inside the letitedit install folder."""
    needles = _needles(folder)
    found = []
    for home in homes or _homes():
        for engine, pattern in (('claude', '.claude/projects/*/*.jsonl'), ('codex', '.codex/sessions/*/*/*/*.jsonl')):
            for path in home.glob(pattern):
                try:
                    if path.stat().st_mtime < since or path.stat().st_size > MAX_LOG_BYTES:
                        continue
                except OSError:
                    continue
                if sessions is not None:
                    if any(str(sid) and str(sid) in path.name for sid in sessions):
                        found.append((engine, path))
                    continue
                if not _mentions(path, needles):
                    continue
                asked, cwd = _asked_about(path, engine, needles)
                if asked and not _in_repo(cwd):
                    found.append((engine, path))
    return found


def _cwd_of(path, engine, lines=80):
    """The folder a session ran in, from its first records (None when they don't say)."""
    for n, line in enumerate(_lines(path)):
        if n >= lines:
            break
        try:
            o = json.loads(line)
        except ValueError:
            continue
        cwd = o.get('cwd') if engine == 'claude' else (o.get('payload') or {}).get('cwd')
        if cwd:
            return cwd
    return None


def sessions_under(root, since, homes=None):
    """The ids of the sessions written after `since` that ran in `root` or a folder below it: a run whose AI starts in
    a folder of its own (a Studio job's window) names its sessions exactly, whatever folder its videos are in."""
    try:
        root = Path(root).resolve()
    except OSError:
        return []
    ids = []
    for home in homes or _homes():
        for engine, pattern in (('claude', '.claude/projects/*/*.jsonl'), ('codex', '.codex/sessions/*/*/*/*.jsonl')):
            for path in home.glob(pattern):
                try:
                    if path.stat().st_mtime < since or path.stat().st_size > MAX_LOG_BYTES:
                        continue
                    cwd = _cwd_of(path, engine)
                    if cwd and Path(cwd).resolve().is_relative_to(root):
                        ids.append(path.stem)
                except (OSError, ValueError):
                    continue
    return ids


def claude_steps(path, since=0, until=None):
    """[{t, new, write, read, out, model}] per model call (a call's last usage record wins)."""
    calls = {}
    for line in _lines(path):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get('type') != 'assistant':
            continue
        m = o.get('message') or {}
        u = m.get('usage')
        t = _ts(o.get('timestamp'))
        if not u or t is None or t < since or (until and t > until):
            continue
        row = {'t': t, 'new': int(u.get('input_tokens') or 0), 'write': int(u.get('cache_creation_input_tokens') or 0),
               'read': int(u.get('cache_read_input_tokens') or 0), 'out': int(u.get('output_tokens') or 0),
               'model': m.get('model') or ''}
        row['write_1h'] = min(row['write'], int((u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0))
        key = m.get('id') or (path.name, len(calls))
        total = row['new'] + row['write'] + row['read'] + row['out']
        if key not in calls or total >= sum(calls[key][k] for k in ('new', 'write', 'read', 'out')):
            calls[key] = row
    return sorted(calls.values(), key=lambda r: r['t'])


def codex_steps(path, since=0, until=None):
    """[{t, new, write, read, out, model}] per model call, from Codex's token_count records."""
    rows, model = [], ''
    for line in _lines(path):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        p = o.get('payload') or {}
        if o.get('type') == 'turn_context' and p.get('model'):
            model = p['model']
        if o.get('type') != 'event_msg' or p.get('type') != 'token_count':
            continue
        last = (p.get('info') or {}).get('last_token_usage') or {}
        t = _ts(o.get('timestamp'))
        if t is None or t < since or (until and t > until) or not last.get('input_tokens'):
            continue
        cached = int(last.get('cached_input_tokens') or 0)
        rows.append({'t': t, 'new': int(last.get('input_tokens') or 0) - cached,
                     'write': int(last.get('cache_write_input_tokens') or 0), 'read': cached,
                     'out': int(last.get('output_tokens') or 0), 'model': model})
    return rows


def _done_stage(line):
    """The stage a done mark names, in either form the journal holds: `stage:<name>:done`, or the same followed by its
    one-line summary (`stage:<name>:done — <summary>`, as project_journal.stage_name accepts); else None."""
    line = str(line or '').strip()
    try:
        import letitedit.timeline.project_journal as project_journal
        name = project_journal.stage_name(line)
    except ImportError:         # run on its own (python run_cost.py ...): the bridge is not on the path
        name = None
    if name:
        return name
    match = re.fullmatch(r'stage:([^:\s]+):done(?:[ \t]+—[ \t]+\S.*)?', line)
    return match.group(1) if match else None


def stage_marks(folder, since=0):
    """[(time, stage)] from every project journal in `folder`: when each stage's done note was written (the note's
    first line, in either form: see _done_stage)."""
    marks = []
    for journal in Path(folder).glob('*.letitedit/journal.jsonl'):
        try:
            lines = journal.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            text = str(o.get('text') or '')
            t = _ts(o.get('time'))
            if o.get('kind') == 'note' and text.startswith('stage:') and t is not None and t >= since:
                name = _done_stage(text.split('\n', 1)[0])
                if name:
                    marks.append((t, name))
    marks.sort()
    seen, out = set(), []
    for t, name in marks:           # a stage done twice (redone): it ends at its last note
        if name in seen:
            out = [(tt, n) for tt, n in out if n != name]
        seen.add(name)
        out.append((t, name))
    return sorted(out)


def background_calls(folder, since=0, until=None):
    """(steps, not_measured): the background calls recorded in `folder`'s project working folders (BACKGROUND_FILE)
    between since and until + BACKGROUND_GRACE_S, as steps marked background; the calls without a token count."""
    steps, unmeasured = [], []
    for path in Path(folder).glob(f'*.letitedit/{BACKGROUND_FILE}'):
        try:
            lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = _ts(o.get('time')) if isinstance(o, dict) else None
            if t is None or t < since or (until and t > until + BACKGROUND_GRACE_S):
                continue
            u = o.get('usage') if isinstance(o.get('usage'), dict) else None
            if not u:
                unmeasured.append({'t': t, 'what': o.get('what'), 'engine': o.get('engine')})
                continue
            write = int(u.get('cache_creation_input_tokens') or 0)
            row = {'t': t, 'new': int(u.get('input_tokens') or 0), 'write': write,
                   'read': int(u.get('cache_read_input_tokens') or 0), 'out': int(u.get('output_tokens') or 0),
                   'model': str(o.get('model') or ''), 'background': True, 'what': o.get('what'),
                   'write_1h': min(write, int((u.get('cache_creation') or {}).get('ephemeral_1h_input_tokens') or 0))}
            if isinstance(o.get('usd'), (int, float)):
                row['usd'] = float(o['usd'])
            steps.append(row)
    return steps, unmeasured


def _price(row):
    """A step's API-equivalent price in US$ (a background call's own figure when it gave one), or None for a model
    not in PRICES."""
    if isinstance(row.get('usd'), (int, float)):
        return row['usd']
    model = str(row.get('model') or '')
    known = [prefix for prefix in PRICES if model.startswith(prefix)]
    if not known:
        return None
    inp, outp, read = PRICES[max(known, key=len)]
    hour = row.get('write_1h', 0)
    writes = (row['write'] - hour) * WRITE_5M + hour * WRITE_1H
    return (row['new'] * inp + writes * inp + row['read'] * read + row['out'] * outp) / 1e6


def summarise(steps, marks):
    """Rows per stage: {stage, steps, new, write, read, out, total, minutes, max_context, usd?}."""
    steps = sorted(steps, key=lambda r: r['t'])
    bounds = []
    start = next((r['t'] for r in steps if not r.get('background')), steps[0]['t'] if steps else 0)
    for t, name in marks:
        bounds.append((name, start, t))
        start = t
    bounds.append((LAST, start, float('inf')))
    rows = []
    for name, a, b in bounds:
        part = [r for r in steps if a <= r['t'] < b]
        if not part and name == LAST:
            continue
        own = [r for r in part if not r.get('background')]     # the conversation's own steps
        row = {'stage': name, 'steps': len(own)}
        if len(own) < len(part):
            row['background'] = len(part) - len(own)
        for k in ('new', 'write', 'read', 'out'):
            row[k] = sum(r[k] for r in part)
        row['total'] = row['new'] + row['write'] + row['read'] + row['out']
        row['max_context'] = max((r['new'] + r['write'] + r['read'] for r in own), default=0)
        row['minutes'] = round(((own[-1]['t'] - own[0]['t']) / 60) if own else 0, 1)
        prices = [_price(r) for r in part]
        if part and all(p is not None for p in prices):
            row['usd'] = round(sum(prices), 4)
        rows.append(row)
    return rows


def measure(folder, since, until=None, homes=None, sessions=None):
    logs = find_logs(folder, since, homes, sessions)
    steps = []
    for engine, path in logs:
        try:
            steps += (claude_steps if engine == 'claude' else codex_steps)(path, since, until)
        except OSError:
            continue
    background, unmeasured = background_calls(folder, since, until)
    rows = summarise(steps + background, stage_marks(folder, since))
    total = {k: sum(r[k] for r in rows) for k in ('steps', 'new', 'write', 'read', 'out', 'total')}
    if rows and all('usd' in r for r in rows):
        total['usd'] = round(sum(r['usd'] for r in rows), 2)
    result = {'format': 'letitedit-run-cost/1', 'folder': str(folder), 'since': since, 'until': until,
              'sessions': [{'engine': e, 'log': str(p)} for e, p in logs],
              'models': sorted({r['model'] for r in steps if r.get('model')}), 'stages': rows, 'total': total}
    if background or unmeasured:
        result['background'] = {'measured': [{'what': r['what'], 'tokens': r['new'] + r['write'] + r['read'] + r['out'],
                                              **({'usd': round(r['usd'], 4)} if 'usd' in r else {})} for r in background],
                                'not_measured': [{'what': r['what'], 'engine': r['engine']} for r in unmeasured]}
    return result


def as_markdown(result):
    k = lambda n: f'{n / 1000:,.0f}k'  # noqa: E731
    lines = ['# What this video took from the AI', '',
             f"{len(result['sessions'])} session(s), models: {', '.join(result['models']) or 'unknown'}. "
             'A step is one call to the model; re-read is the conversation read again from the cache.', '',
             '| stage | steps | minutes | new | cache written | re-read | output | total | largest context |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in result['stages'] + [{'stage': 'total', 'minutes': '', 'max_context': 0, **result['total']}]:
        lines.append(f"| {r['stage']} | {r['steps']} | {r.get('minutes', '')} | {k(r['new'])} | {k(r['write'])} | "
                     f"{k(r['read'])} | {k(r['out'])} | {k(r['total'])} | {k(r['max_context']) if r['max_context'] else ''} |")
    bg = result.get('background') or {}
    if bg.get('measured'):
        names = sorted({str(b['what']) for b in bg['measured']})
        lines += ['', f"Also {len(bg['measured'])} call(s) of the AI outside the conversation ({', '.join(names)}): "
                  f"{k(sum(b['tokens'] for b in bg['measured']))} tokens, counted in their stage's tokens above, not in "
                  'its steps.']
    if bg.get('not_measured'):
        names = sorted({f"{b['what']}, {b['engine']}" for b in bg['not_measured']})
        lines += ['', f"Not measured: {len(bg['not_measured'])} call(s) outside the conversation ({'; '.join(names)}): "
                  'the AI gave no token count.']
    if 'usd' in result['total']:
        lines += ['', f"At API prices this would be about ${result['total']['usd']:.2f} (a subscription is not billed this way)."]
    return '\n'.join(lines) + '\n'


def refresh(work, homes=None):
    """The measurement in `work`'s run-cost.json made again with the same folder, times and sessions (a background call
    recorded after it was written)."""
    saved = json.loads((Path(work) / 'run-cost.json').read_text(encoding='utf-8-sig'))
    ids = [Path(s['log']).stem for s in saved.get('sessions') or [] if s.get('log')]
    return write(saved['folder'], float(saved['since']), saved.get('until'), homes, ids or None)


def write(folder, since, until=None, homes=None, sessions=None):
    """Measure the run and write run-cost.json and run-cost.md where its projects' working files are."""
    result = measure(folder, since, until, homes, sessions)
    root = Path(folder)
    targets = [d for d in root.glob('*.letitedit') if d.is_dir() and d.stat().st_mtime >= since] or [root]
    for d in targets:
        try:
            (d / 'run-cost.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
            (d / 'run-cost.md').write_text(as_markdown(result), encoding='utf-8')
        except OSError:
            continue
    return result, targets


def start_detached(folder, since, sessions=None):
    """Write the cost line in its own process, so whoever asks never waits for it."""
    import subprocess
    try:
        import letitedit.core.render_lock as render_lock
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
        extra = ['--sessions', ','.join(map(str, sessions))] if sessions else []
        render_lock.start_independent([sys.executable, str(Path(__file__).resolve()), str(folder), str(float(since)),
                                       *extra], creationflags=flags)
        return True
    except OSError:
        return False


if __name__ == '__main__':
    args = sys.argv[1:]
    if args[:1] == ['--refresh']:
        res, where = refresh(args[1])
        print(json.dumps({'written': [str(w) for w in where], 'total': res['total'], 'sessions': len(res['sessions'])}))
        raise SystemExit(0)
    until = sessions = None
    if '--until' in args:
        i = args.index('--until')
        until = float(args[i + 1])
        del args[i:i + 2]
    if '--sessions' in args:
        i = args.index('--sessions')
        sessions = [x for x in args[i + 1].split(',') if x]
        del args[i:i + 2]
    res, where = write(args[0], float(args[1]), until, sessions=sessions)
    print(json.dumps({'written': [str(w) for w in where], 'total': res['total'], 'sessions': len(res['sessions'])}))
