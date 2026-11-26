import json
import os
import re
import subprocess
import sys
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess

# A line that starts with "Blocked:", also written in bold or as a list item ("**Blocked:** ...", "- Blocked: ...")
_STATED = re.compile(r'(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*|__)?Blocked(?:\*\*|__)?:(?:\*\*|__)?\s*(.*)$')
# What a status line says when nothing blocks ("Blocked: none")
_NO_REASON = re.compile(r'(?:none|no|nothing|n/?a|not blocked|-+|—)\W*$', re.I)


def plain_blocker(answer):
    """Return the first `Blocked:` line with a reason, or an empty string. "Blocked: none" has no reason."""
    for line in answer.splitlines():
        line = line.strip()
        stated = _STATED.match(line)
        if stated:
            reason = stated.group(1).strip().strip('*_').strip()
            if reason and not _NO_REASON.match(reason):
                return line
    return ''


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
def pending_exports(folder):
    jobs = Path(os.environ.get('LETITEDIT_CACHE', str(_paths.CODE_ROOT / 'cache'))) / 'exports'
    latest = {}
    for spec_path in jobs.glob('*/spec.json'):
        try:
            spec = json.loads(spec_path.read_text(encoding='utf-8-sig'))
            output = Path(spec.get('output', '')).resolve()
            if not output.is_relative_to(folder.resolve()):
                continue
            status = json.loads((spec_path.parent / 'status.json').read_text(encoding='utf-8-sig'))
            created = spec_path.stat().st_mtime_ns
            if output not in latest or created > latest[output][0]:
                latest[output] = (created, status.get('state'))
        except (OSError, ValueError):
            continue
    return {output for output, (_, state) in latest.items() if state != 'done'}


def final_review(root, since):
    """The last review of this run, when one was made since `since`: a review bundle past its round limit
    (review_bundle.json says rounds.final). Its video is the one handed over; nothing restarts the run after it."""
    found = []
    for bundle in list(root.glob('* review/review_bundle.json')) + list(root.glob('*/* review/review_bundle.json')):
        try:
            if bundle.stat().st_mtime < since:
                continue
            data = json.loads(bundle.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if (data.get('rounds') or {}).get('final'):
            video = (data.get('video') or {}).get('file') if isinstance(data.get('video'), dict) else data.get('video')
            found.append((bundle.stat().st_mtime, video))
    if not found:
        return None
    return {'decision': 'finished', 'reason': 'the review rounds are used up: the last review was made',
            'video': str(max(found)[1] or '')}


def inspect(folder, since, answer, probe=None, stage_request=None, stage_state=None):
    """stage_request: the New video request, when the app runs one conversation per stage (new_video_stages.py):
    a stage handed over gives {'decision': 'next_stage', 'request': ...} for a fresh conversation."""
    blocker = plain_blocker(answer)
    if blocker:
        return {'decision': 'blocked', 'reason': blocker}
    root = Path(folder)
    if not folder or not root.is_dir():
        return {'decision': 'unfinished'}
    final = final_review(root, since)
    if final:
        return final
    import letitedit.app.new_video_stages as new_video_stages
    if stage_request is not None and new_video_stages.lean_enabled() and pending_exports(root):
        return {'decision': 'unfinished', 'reason': 'Collect pending exports before a lean stage handoff.'}
    if new_video_stages.stopped(folder, since):          # a run that stops after a stage (a Studio preview)
        if new_video_stages.lean_enabled():
            checkpoint = new_video_stages.next_session(folder, since, stage_request, live=stage_state,
                                                       checkpoint_only=True)
            if not checkpoint or checkpoint.get('decision') != 'stage_checkpoint':
                return checkpoint or {'decision': 'unfinished', 'reason': 'Repair the lean preview checkpoint.'}
        done = {'decision': 'finished', 'reason': f'stopped after the {new_video_stages.stop_after()} stage, as asked'}
        books = new_video_stages.bookkeep_stopped(folder, since, stage_request)   # T331 P8, on by default; off: {}
        if books:
            done['bookkeeping'] = books
        return done
    if stage_request is not None:
        import letitedit.app.new_video_stages as new_video_stages
        # the install's switch (settings.json new_video_stage_sessions, on by default): off, the run stays one conversation
        # phases (settings.json new_video_phases, on by default): the next phase starts when this one's outputs check out
        fresh = (new_video_stages.lean_enabled() or new_video_stages.enabled() or new_video_stages.phases_on()) and \
            new_video_stages.next_session(folder, since, stage_request, live=stage_state)
        if fresh:
            return fresh
    probe = probe or _paths.CODE_ROOT / 'app/ffprobe.exe'
    pending = pending_exports(root)
    candidates = list(root.glob('*'))[:200]
    for directory in list(candidates):
        if directory.is_dir() and not directory.name.endswith('.letitedit') and directory.name.lower() not in {'cache', 'checks', 'review', 'made', 'source-check', 'takes', 'poster-still'}:
            candidates.extend(list(directory.glob('*'))[:200])
    for path in candidates:
        if path.suffix.lower() not in {'.mp4', '.mov', '.mkv', '.webm'} or not path.is_file():
            continue
        stat = path.stat()
        if stat.st_size == 0 or stat.st_mtime < since or path.resolve() in pending:
            continue
        try:
            result = subprocess.run([str(probe), '-v', 'error', '-show_entries',
                                     'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)],
                                    capture_output=True, text=True, timeout=4)
            data = json.loads(result.stdout)
            after = path.stat()
            stable = (stat.st_size, stat.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
            if stable and result.returncode == 0 and float(data.get('format', {}).get('duration', 0)) > 0 and any(
                    stream.get('codec_type') == 'video' and stream.get('width', 0) > 0
                    for stream in data.get('streams', [])):
                return {'decision': 'finished', 'video': str(path)}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            continue
    return {'decision': 'unfinished'}


def dispatch(request):
    """Internal editor JSON protocol, not an MCP tool or tool-contract extension."""
    action = request.get('action', 'inspect')
    if action == 'stage_start':
        from letitedit.app import new_video_stages
        options = {key: request[key] for key in ('handover', 'timeline', 'look', 'skills', 'evidence', 'input_record', 'max_bytes')
                   if key in request}
        ai = request['ai']
        options['ai'] = ai['engine'] if isinstance(ai, dict) else ai
        try:
            startup = new_video_stages.start_request(request['request'], request['stage'], request['project'], **options)
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {'decision': 'unfinished', 'reason': f'Complete stage startup needs repair: {error}'}
        return dict(startup, decision='stage_ready')
    if action == 'stage_start_verify':
        from letitedit.app import stage_start
        stage_start.verify(request['startup'], request['delivered'])
        return {'decision': 'stage_verified'}
    if action in ('stage_begin', 'stage_ack'):
        from letitedit.app import new_video_stages, stage_handoff
        if not new_video_stages.lean_enabled():
            return {'decision': 'unfinished', 'reason': 'Lean stage handoffs are disabled.'}
        if action == 'stage_begin':
            config = stage_handoff.begin_run(request['project'], request['run_id'], request['request'],
                                            request['ai'], request['sources'], request['look'],
                                            request['review_limit'], request.get('skills'))
            return {'decision': 'stage_ready', 'run_id': config['run_id']}
        stage_handoff.acknowledge(Path(request['project']).with_suffix('.letitedit'), request['run_id'],
                                  request['transition_id'], request['session_id'])
        return {'decision': 'stage_started', 'transition_id': request['transition_id']}
    if action != 'inspect':
        raise ValueError('Unknown internal carry action.')
    return inspect(request['folder'], request['since'], request.get('answer', ''),
                   stage_request=request.get('request', '') if request.get('stage_sessions') else None,
                   stage_state=request.get('stage_state'))


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        if request.get('action', 'inspect') == 'inspect':
            decision = inspect(request['folder'], request['since'], request.get('answer', ''),
                               stage_request=request.get('request', '') if request.get('stage_sessions') else None,
                               stage_state=request.get('stage_state'))
        else:
            decision = dispatch(request)
        if decision.get('decision') == 'finished' and request.get('folder') and request.get('cost'):
            # the run's cost line (run_cost.py): tokens and steps per stage, written beside the project, in its own
            # process; an app that asks for it sends cost: true (and its sessions' ids)
            try:
                import letitedit.app.run_cost as run_cost
                run_cost.start_detached(request['folder'], request['since'], request.get('sessions'))
            except Exception:  # noqa: BLE001 - a measurement never changes the decision
                pass
        print(json.dumps(decision))
    except Exception as error:
        print(json.dumps({'decision': 'unknown', 'reason': str(error)}))
