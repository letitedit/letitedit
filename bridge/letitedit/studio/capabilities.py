"""What this letitedit can do, in the Studio contract's terms (CONTRACT.md section 6, 'capabilities').

Fast: no AI, no render. A kind is listed as available only once it runs on this install.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

import letitedit.core.paths as paths
import letitedit.studio.contract_schemas as contract
import letitedit.studio.estimates as estimates
import letitedit.studio.files as files

ROOT = Path(os.path.normpath(os.environ.get('LETITEDIT_ROOT') or paths.ROOT_TEXT))
HERE = Path(__file__).resolve().parent
AVAILABLE = {'capabilities', 'index', 'short', 'retext', 'still', 'conform', 'revise'}   # kinds that run on this install, each after its real run here
TRY_ENV = 'LETITEDIT_STUDIO_TRY_KINDS'   # tests only: kinds switched on before their real run has passed (a, b)
STILL_SIZES = [{'id': 'story_9x16', 'width': 1080, 'height': 1920}]
NOT_YET = 'Not on this install yet.'
DELIVERY_LUFS, DELIVERY_TP = -14.0, -1.0
USES_AI = set(estimates.USES_AI)
HEAVY = {'index', 'match', 'inspect', 'short', 'batch_shorts', 'still', 'revise', 'retext', 'conform', 'learn'}
TIERS = {'short': ['preview', 'final'], 'batch_shorts': ['preview', 'final']}
PROXY_MAX_BYTES = 8_000_000
RULE_KINDS = ('must', 'never', 'prefer')        # a job's rule kinds (contract 1.5 added prefer)
FREE_DISK_GB_NEEDED = 20.0


def letitedit_version():
    """The promoted build's number (app\\ai-assist-executable.txt names letitedit-YYYYMMDD.N.exe), else 'unknown'."""
    try:
        name = (ROOT / 'app' / 'ai-assist-executable.txt').read_text(encoding='utf-8-sig').strip()
        stem = Path(name).stem
        return stem.split('letitedit-', 1)[1] if 'letitedit-' in stem else stem
    except OSError:
        return 'unknown'


def tools_commit():
    """The tool code's commit when this is a git checkout, else None (an installed letitedit has no .git)."""
    if not (paths.CODE_ROOT / '.git').exists():
        return None
    try:
        out = subprocess.run(['git', '-C', str(paths.CODE_ROOT), 'rev-parse', '--short', 'HEAD'], capture_output=True,
                             text=True, timeout=5, creationflags=0x08000000 if os.name == 'nt' else 0)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def versions():
    v = {'contract': contract.CONTRACT_VERSION, 'letitedit': letitedit_version()}
    commit = tools_commit()
    if commit:
        v['tools'] = commit
    return v


def _val(fact):
    return fact.get('value') if isinstance(fact, dict) else None


def platforms_list():
    import letitedit.catalogs.platforms as platforms
    out = []
    for p in platforms.list_profiles():
        prof = platforms.load(p['id'])
        ep, video = prof.get('export_preset') or {}, prof.get('video') or {}
        fps = _val(ep.get('fps'))
        entry = {'id': p['id'], 'name': prof['name'], 'width': _val(ep.get('width')) or 1080,
                 'height': _val(ep.get('height')) or 1920, 'fps': fps if isinstance(fps, (int, float)) else 30,
                 'loudness_lufs': DELIVERY_LUFS, 'true_peak_dbtp': DELIVERY_TP,
                 'covered_areas': bool(_val(prof.get('safe_zones')))}
        cap = _val(ep.get('max_file_size_bytes')) or _val(video.get('max_file_size_bytes'))
        if isinstance(cap, (int, float)):
            entry['max_bytes'] = int(cap)
        longest = _val(video.get('max_length_s'))
        if isinstance(longest, (int, float)):
            entry['max_seconds'] = longest
        out.append(entry)
    return out


def looks_list():
    import letitedit.looks.looks as looks
    cat = looks.catalog()
    out = []
    for c in cat.get('looks') or []:
        if c.get('private'):
            continue
        kind = c.get('kind') or 'both'
        entry = {'id': c['id'], 'name': c.get('label') or c['id'], 'source': 'learned' if c.get('personal') else 'library',
                 'styles': [s for s in (c.get('fits') or [c.get('style')]) if s],
                 'formats': ['short', 'long'] if kind == 'both' else [kind],
                 'needs_footage': c.get('works_with') != 'no-footage'}
        if c.get('needs') or c.get('line'):
            entry['fits'] = c.get('needs') or c.get('line')
        if c.get('preview'):
            entry['example'] = c['preview']
        out.append(entry)
    themes = [{'id': t['id'], 'name': t.get('title') or t['id']} for t in cat.get('themes') or [] if t.get('approved')]
    return out, themes


def ai_info():
    import letitedit.app.ai_clis as ai_clis
    settings = ai_clis.chat_settings()
    available = [e for e in ('claude', 'codex') if ai_clis.find(e, settings)]
    engine = settings.get('engine') if settings.get('engine') in available else (available[0] if available else 'claude')
    model, effort = ai_clis.DEFAULT_CHOICE.get(engine, (None, None))
    if engine in ('claude', 'codex'):        # the saved choice, Auto's planning role (a saved "auto"), else the default
        picked = ai_clis.choice(engine, 'plan', settings)
        model, effort = picked['model'], picked['effort']
    default = {'engine': engine}
    if model:
        default['model'] = model
    if effort:
        default['effort'] = effort
    return {'default': default, 'available': available}


def typical(registry_dir=None, want=None):
    """Per '<kind>' or '<kind>.<tier>', for the AI `want` (engine, model, effort; contract 1.2): this PC's median of
    its last 10 finished jobs run with that AI when it has 3 or more, else letitedit's reference numbers
    (typical.json), else the nearest figure, saying so (estimates.choose). Each figure says the AI it was measured
    with."""
    ref = files.read_json(HERE / 'typical.json', {}) or {}
    ref = {k: v for k, v in ref.items() if not k.startswith('_')}
    runs = {}
    for f in sorted(Path(registry_dir).glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True) \
            if registry_dir is not None else []:
        entry = files.read_json(f) or {}
        r = files.read_json(Path(entry.get('job_dir', '')) / 'result.json') or {}
        if r.get('state') != 'done' or not r.get('cost'):
            continue
        key = r['kind'] + (f'.{r["tier"]}' if r.get('tier') else '')
        runs.setdefault(key, {}).setdefault(estimates.key(r['cost'].get('ai')), []).append(r['cost'])
    measured = {}
    for key, by_ai in runs.items():
        for ai, costs in by_ai.items():
            costs = costs[:10]
            if len(costs) < 3:
                continue
            mins = sorted(c['wall_s'] / 60 for c in costs)
            toks = sorted((c.get('tokens') or {}).get('total', 0) for c in costs)
            fig = {'minutes': round(statistics.median(mins), 1), 'minutes_p90': round(mins[int(0.9 * (len(mins) - 1))], 1),
                   'tokens': int(statistics.median(toks)), 'tokens_p90': int(toks[int(0.9 * (len(toks) - 1))]),
                   'basis': 'measured_here', 'samples': len(costs), 'as_of': files.now_iso()[:10]}
            label = estimates.label(costs[0].get('ai'))
            if label:
                fig['ai'] = label
            measured.setdefault(key, []).append(fig)
    return estimates.choose_all(ref, want, measured)


def free_disk_gb(path):
    import shutil
    try:
        return round(shutil.disk_usage(path).free / 1e9, 1)
    except OSError:
        return None


def tried():
    return {k.strip() for k in os.environ.get(TRY_ENV, '').split(',') if k.strip()}


def kinds_info():
    out = {}
    for kind in contract.kinds():
        ok = kind in AVAILABLE or kind in tried()
        d = {'available': ok, 'uses_ai': kind in USES_AI, 'heavy': kind in HEAVY}
        if not ok:
            d['why_not'] = NOT_YET
        if kind in TIERS:
            d['tiers'] = TIERS[kind]
        out[kind] = d
    return out


def still_layouts():
    import letitedit.studio.still as still
    return list(still.drawing.LAYOUTS.values()) if 'still' in tried() else still.offered()


def build(home=None, entry_points=None, include=None, ai=None):
    """capabilities' output (contract kinds/capabilities.schema.json $defs/output). ai: the AI the caller plans to
    run its jobs with (`typical` is for it); absent, the person's own (`ai.default`)."""
    home = Path(home) if home else None
    want = set(include or ('looks', 'platforms', 'stills_layouts', 'caption_styles', 'typical', 'limits'))
    looks, themes = looks_list() if 'looks' in want else ([], [])
    who = ai_info()
    out = {'contract_version': contract.CONTRACT_VERSION, 'contract_versions_accepted': [str(contract.MAJOR)],
           'letitedit_version': letitedit_version(), 'kinds': kinds_info(), 'ai': who,
           'looks': looks, 'themes': themes,
           'platforms': platforms_list() if 'platforms' in want else [],
           'still_sizes': STILL_SIZES, 'stills_layouts': still_layouts(),
           'caption_styles': [{'id': 'look', 'name': "The Look's own captions"}, {'id': 'none', 'name': 'No captions'}],
           'rule_kinds': list(RULE_KINDS),
           'rule_checks': [{'id': 'blur_plates', 'status': 'ai_review_only', 'note': 'No licence plate detector yet.'},
                           {'id': 'house_numbers', 'status': 'ai_review_only', 'note': 'No house number detector yet.'},
                           {'id': 'kids_faces', 'status': 'ai_review_only', 'note': 'No face detector for this yet.'}],
           'priorities': ['urgent', 'normal', 'dev'],
           'limits': {'concurrent_jobs': 1, 'max_references': 3, 'max_still_motion_seconds': 60,
                      'proxy_max_bytes': PROXY_MAX_BYTES, 'free_disk_gb_needed': FREE_DISK_GB_NEEDED},
           'typical': typical(home / 'registry' if home else None, ai or who['default'])
           if 'typical' in want else {}}
    disk = free_disk_gb(home or ROOT)
    if disk is not None:
        out['limits']['free_disk_gb'] = disk
    out['entry_points'] = entry_points or {}
    return out


if __name__ == '__main__':
    print(json.dumps(build(), indent=1, ensure_ascii=False))
    sys.exit(0)
