"""Command lines the letitedit app runs for its own buttons: one JSON object per line, then the answer.

    python app_tools.py <command> [options]

While it works a command prints {"progress": 0.4, "message": "..."} lines; it ends with {"result": {...}} (exit 0) or
{"error": "..."} (exit 1). The app runs the heavy ones under the PC render lock (render_lock.py run ...), so they take
turns with every other heavy job; the light ones (library-search, library-place, motion-blocks) run as they are.

  library-search   the asset library (assets.search) for the app's Stickers & sounds panel, with a picture for each
  library-place    one asset ready to place (assets.resolve): a PNG, a Lottie animation or a sound file
  motion-blocks    the animated title blocks (motion.blocks) and whether the engine can render on this PC
  motion-preview   stills of a block with the person's words (motion.preview)
  motion-render    the whole clip, a .mov with alpha (motion.render)
  sync             line up a shoot by its sound (shoot_sync.sync_shoot): a project, synced clips and a picture
  check            "Check my video": the review bundle without the critic (review_bundle.bundle), in plain words

LETITEDIT_QA_TOOLS_FAKE=<command,...> (test windows only, with LETITEDIT_QA set) answers those commands with a quick
stand-in after a few progress lines, so the app's journey checks run without models or long renders.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import argparse
import datetime
import json
import os
import shutil
import sys
import time
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
sys.path.insert(0, str(HERE))

APP_KINDS = ('emoji', 'sticker', 'icon', 'graphic', 'transition', 'sfx')


def say(obj):
    print(json.dumps(obj, ensure_ascii=False, default=str), flush=True)


def progress(fraction, message=''):
    say({'progress': round(max(0.0, min(1.0, float(fraction))), 3), 'message': str(message)})


def fake(command):
    """True when a test window asked for a stand-in answer for this command."""
    wanted = os.environ.get('LETITEDIT_QA_TOOLS_FAKE', '')
    return bool(os.environ.get('LETITEDIT_QA')) and command in {w.strip() for w in wanted.split(',') if w.strip()}


def fake_steps(steps, pause=None):
    pause = float(os.environ.get('LETITEDIT_QA_TOOLS_FAKE_S', '0.6')) if pause is None else pause
    for i, message in enumerate(steps):
        progress(i / len(steps), message)
        time.sleep(pause)


# ------------------------------------------------------------------ the asset library

_FLUENT_BY_GLYPH = {}


def _fluent_picture(glyph):
    """The still Fluent 3D picture of an emoji character (the picture an animated emoji shows in the list)."""
    import letitedit.catalogs.assets as assets
    if not _FLUENT_BY_GLYPH:
        for e in assets.index().entries:
            if e.get('source') == 'fluent' and e.get('glyph'):
                styles = e.get('styles') or {}
                _FLUENT_BY_GLYPH.setdefault(e['glyph'], assets.abspath(styles.get('3d') or e['file']))
    return _FLUENT_BY_GLYPH.get(glyph)


def _thumb(e):
    """A picture file the app can show for an entry (PNG, SVG or WebP), or None (the app draws its own)."""
    import letitedit.catalogs.assets as assets
    if e['kind'] in assets.SOUND:
        return None
    styles = e.get('styles') or {}
    if e.get('source') == 'fluent':
        return assets.abspath(styles.get('3d') or e['file'])
    if e.get('source') == 'tabler':
        return assets.abspath(styles.get('outline') or e['file'])
    if e.get('animated'):
        if e.get('glyph') and _fluent_picture(e['glyph']):
            return _fluent_picture(e['glyph'])
        f = Path(assets.abspath(e['file']))
        for ext in ('.webp', '.png', '.gif'):
            if f.with_suffix(ext).exists():
                return str(f.with_suffix(ext))
        return None
    f = assets.abspath(e['file'])
    return f if f and f.lower().endswith(('.png', '.jpg', '.jpeg', '.svg', '.webp')) else None


def _direct_file(e):
    """The file that can go on the timeline as it is (a drag), or None when it is drawn first (SVG icons)."""
    import letitedit.catalogs.assets as assets
    if e['kind'] in assets.SOUND or e.get('animated'):
        return assets.abspath(e['file'])
    styles = e.get('styles') or {}
    if e.get('source') == 'fluent' and styles.get('3d'):
        return assets.abspath(styles['3d'])
    f = assets.abspath(e['file'])
    return f if f and f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) else None


def row(e):
    return {'id': e['id'], 'kind': e['kind'], 'name': e.get('name'), 'glyph': e.get('glyph'),
            'group': e.get('group'),
            'animated': bool(e.get('animated')), 'duration_s': e.get('duration_s'), 'credit': e.get('credit'),
            'licence': e.get('licence'), 'source': e.get('source'), 'thumb': _thumb(e), 'file': _direct_file(e)}


def library_search(a):
    import letitedit.catalogs.assets as assets
    kinds = [k for k in (a.kinds or ','.join(APP_KINDS)).split(',') if k]
    animated = {'yes': True, 'no': False}.get(a.animated)
    # The old bundled Elements graphics and sounds remain available to existing projects and the AI's index, but
    # the beginner-facing library shows the wider open-source collection instead.
    r = assets.search(a.query or '', kinds=kinds, limit=a.limit, offset=a.offset, animated=animated,
                      exclude_sources={'elements', 'elements-sfx'}, groups=a.group,
                      popular=not bool((a.query or '').strip()))
    out = {'query': r['query'], 'total': r['total'], 'partial': r['partial'], 'by_kind': r['by_kind'],
           'results': [row(e) for e in r['results']]}
    if not r['total'] and a.query:
        out['suggestions'] = assets.suggestions(a.query, kinds=kinds)
    return out


def library_place(a):
    import letitedit.catalogs.assets as assets
    r = assets.resolve(a.id, size_px=a.px or None)
    return {'id': r['id'], 'kind': r['kind'], 'name': r.get('name'), 'file': r['file'],
            'animated': bool(r.get('animated')), 'credit': r.get('credit'), 'licence': r.get('licence'),
            'duration_s': r.get('duration_s'), 'w': r.get('w'), 'h': r.get('h')}


def library_preview(a):
    """A short, cached animated GIF for a selected Lottie or rendered-video Element."""
    import hashlib
    from pathlib import Path
    from PIL import Image
    import letitedit.catalogs.assets as assets
    e = assets.find(a.id)
    if not e.get('animated'):
        raise ValueError('This element is not animated')
    source = assets.abspath(e['file'])
    stamp = Path(source).stat().st_mtime_ns
    key = hashlib.sha1(f'{a.id}|{stamp}'.encode()).hexdigest()[:20]
    target = assets.CACHE / 'app-previews' / f'{key}.gif'
    if not target.exists():
        import letitedit.core.render_lock as render_lock
        with render_lock.slot('letitedit element preview', caller_pids=render_lock.ancestors()):
            if not target.exists():
                if Path(source).suffix.lower() in ('.mov', '.mp4', '.webm'):
                    import subprocess
                    import tempfile
                    with tempfile.TemporaryDirectory(prefix='letitedit-element-') as tmp:
                        pattern = str(Path(tmp) / '%03d.png')
                        command = [str(assets.APP / 'ffmpeg.exe'), '-v', 'error', '-y', '-i', source,
                                   '-vf', 'fps=8,scale=128:-1:flags=lanczos', '-frames:v', '16', pattern]
                        subprocess.run(command, check=True, timeout=90,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        frames = list(Path(tmp).glob('*.png'))
                        pictures = [Image.open(f).convert('RGBA') for f in frames]
                else:
                    frames = assets.lottie_frames(source, fps=8, px=128, count=16)
                    pictures = [Image.open(f).convert('RGBA') for f in frames]
                if not pictures:
                    raise RuntimeError('The element has no video frames')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix('.tmp.gif')
                pictures[0].save(temporary, save_all=True, append_images=pictures[1:], duration=125, loop=0,
                                 disposal=2, optimize=False)
                temporary.replace(target)
    return {'id': a.id, 'file': str(target)}


# ------------------------------------------------------------------ animated titles (motion clips)

def motion_blocks(a):
    import letitedit.pictures.motion as motion
    blocks = {k: {x: v[x] for x in ('title', 'about', 'duration', 'params')} for k, v in motion.blocks().items()}
    return {'engine': motion.available() or 'ready', 'blocks': blocks}


def _motion_spec(a):
    spec = json.loads(a.spec) if a.spec else {}
    if a.look and not spec.get('look'):
        spec['look'] = a.look
    return spec


def motion_preview(a):
    import letitedit.pictures.motion as motion
    progress(0.1, 'drawing the preview')
    r = motion.preview(_motion_spec(a), a.size[0], a.size[1], a.fps, count=a.count)
    return {'sheet': r['sheet'], 'times': r['times'], 'frames': r['frames'], 'missing_fonts': r.get('missing_fonts')}


def motion_render(a):
    import letitedit.pictures.motion as motion
    progress(0.02, 'getting the title ready')
    spec = _motion_spec(a)
    if fake('motion-render'):
        fake_steps(['drawing the frames', 'writing the clip'])
        out = Path(a.out_dir or os.environ.get('TEMP', '.')) / 'qa-motion.mov'
        out.parent.mkdir(parents=True, exist_ok=True)
        _ffmpeg(['-y', '-f', 'lavfi', '-i', f'color=c=0x2A8597@0.8:s={a.size[0]}x{a.size[1]}:r={a.fps}:d=2',
                 '-c:v', 'qtrle', '-pix_fmt', 'argb', str(out)])
        return {'file': str(out), 'alpha': True, 'duration': 2.0, 'cached': False, 'fake': True}
    r = motion.render(spec, a.size[0], a.size[1], a.fps, out_dir=a.out_dir,
                      progress=lambda f, m=None: progress(0.05 + 0.9 * float(f), m or 'drawing the frames'))
    return {'file': r['path'], 'alpha': r.get('alpha'), 'duration': motion.normalise(spec)['duration'],
            'cached': r.get('cached'), 'sheet': r.get('sheet'), 'missing_fonts': r.get('missing_fonts')}


def _ffmpeg(args):
    import subprocess
    exe = Path(os.environ.get('LETITEDIT_ROOT') or HERE.parent) / 'app' / 'ffmpeg.exe'
    subprocess.run([str(exe) if exe.exists() else 'ffmpeg', '-hide_banner', '-loglevel', 'error', *args], check=True,
                   capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


# ------------------------------------------------------------------ captions from the same transcript and layout as the AI

def captions_plan(a):
    """Plan captions against the open window's XML copy; never write the person's project."""
    import letitedit.timeline.edit_script as es
    import letitedit.pictures.caption_layout as caption_layout
    import letitedit.footage.speech as speech
    import letitedit.timeline.timeline_speech as timeline_speech

    project = Path(a.project)
    progress(0.03, 'reading the words in this video')
    script = es.read(project)
    # This is the same source-word cache used by letitedit_words and {op: captions, from_speech: true}.
    timeline_speech.timeline_words(script)
    progress(0.36, 'making phrases from the words')
    fixes = json.loads(a.fixes or '{}')
    track = a.track or 'Captions'
    op = {'op': 'captions', 'track': track, 'from_speech': True,
          'chunk': 'short' if script['profile']['width'] < script['profile']['height'] else 'sentence',
          'fix': fixes}
    planned, notes = es.edit(script, [op])
    if not planned.get('captions') or not next((c.get('cues') for c in planned['captions'] if c['track'] == track), []):
        raise ValueError('No spoken words were found in the video.')
    es.compile_script(planned, base=project, out=project, force=True)
    progress(0.52, 'placing captions clear of faces and screen buttons')
    # TikTok's covered area also keeps clear of Shorts'. 'phone' adds Reels' ad guidance (the bottom 35%), which on a
    # close-up leaves no room under the chin, so the captions would sit against it: the place for them is the middle
    # of the free area below the face (caption_layout 'free'), inside TikTok's and Shorts' uncovered area.
    fit = caption_layout.fit(str(project), tracks=[track], platform='tiktok' if
                             script['profile']['width'] < script['profile']['height'] else None,
                             native_mode='tracks', faces='hard', render_check_frames=True)
    if fit.get('unsupported'):
        raise ValueError('Caption placement could not run: ' + str(fit['unsupported'][:2]))
    if fit.get('changes'):
        planned, _ = es.edit(es.read(project), fit['changes'])
        es.compile_script(planned, base=project, out=project, force=True)
    final = es.read(project)
    captions = [c for c in final.get('captions', []) if c['track'] == track or c['track'].startswith(track + ' (')]
    for caption in captions:
        for cue in caption.get('cues', []):
            cue['start_ms'] = round(es.to_seconds(cue.pop('start')) * 1000)
            cue['end_ms'] = round(es.to_seconds(cue.pop('end')) * 1000)
    sources = {it['clip'] for t in script['tracks'] for it in t['items'] if it.get('clip')}
    models = set()
    for source in sources:
        try:
            f = speech._cached(speech._identity(source))
            if f:
                models.add(json.loads(f.read_text(encoding='utf-8-sig')).get('model', 'unknown'))
        except (OSError, ValueError):
            pass
    progress(0.98, 'captions ready')
    return {'captions': captions, 'models': sorted(models), 'notes': notes,
            'placement': fit.get('summary'), 'faces': fit.get('faces'),
            'render_check': fit.get('render_check'), 'preview_artifacts': fit.get('preview_artifacts'),
            'warnings': fit.get('warnings', [])}


# ------------------------------------------------------------------ line up a shoot by its sound

def sync(a):
    import letitedit.sound.shoot_sync as shoot_sync
    files = [f for f in a.files or []]
    folders = [f for f in files if Path(f).is_dir()] + ([a.folder] if a.folder else [])
    files = [f for f in files if not Path(f).is_dir()]
    if not files and not folders:
        raise ValueError('choose the folder with the footage, or the files')
    project = Path(a.project)
    project.parent.mkdir(parents=True, exist_ok=True)
    progress(0.05, 'listening to every file')
    res = shoot_sync.sync_shoot(files=files, folder=folders, project=str(project), sheet=True,
                                out_dir=str(project.parent / f'{project.stem} sync picture'))
    progress(0.95, 'writing the project')
    placed = [{'file': Path(r['file']).name, 'path': r['file'], 'at': r.get('at'), 'level': r.get('level'),
               'device': r.get('device')} for r in res.get('timeline') or []]
    missed = [{'file': Path(r.get('file', '')).name, 'why': r.get('why')} for r in res.get('not_placed') or []]
    synced = res.get('synced_clips') or []
    return {'project': str(project) if res.get('project') else None, 'placed': placed, 'not_placed': missed,
            'warnings': res.get('warnings') or [], 'notes': res.get('notes') or [],
            'synced_clips': [c.get('file') for c in synced if isinstance(c, dict)],
            'sheet': res.get('sheet'), 'frames_sheet': res.get('frames_sheet'), 'seconds': res.get('seconds')}


# ------------------------------------------------------------------ Check my video

VERDICT_WORDS = {
    'ready': 'Ready to share: the checks found nothing that needs fixing.',
    'revise': 'Worth fixing first: the checks found something to look at.',
    'blocked': 'Fix this before you share it: the checks found a serious problem.',
    'incomplete': 'The measured checks are done. Nobody has watched it for story and pacing yet.',
}


def _plain_finding(f):
    return {'at': f.get('at'), 'at_s': f.get('at_s'), 'severity': f.get('severity'), 'what': f.get('what'),
            'fix': f.get('fix'), 'from': f.get('source')}


def _num(v, nd=1):
    try:
        return f'{float(v):.{nd}f}'.rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return str(v)


def _limit(t, unit=''):
    """'>= 12' -> '12 or more', '<= 4' -> '4 s or less'."""
    t = str(t or '').strip()
    if t.startswith('>='):
        return f'{t[2:].strip()}{unit} or more'
    if t.startswith('<='):
        return f'{t[2:].strip()}{unit} or less'
    return t


def plain_check(c):
    """(what, fix) in plain words for a failed quality-gate check (skills/letitedit-gate/scripts/gate.py), or None
    for one it doesn't know (the measured line is shown then)."""
    name, v, t = c.get('check'), c.get('value'), c.get('threshold')
    at = c.get('at_s')
    when = f' (from {int(at // 60)}:{at % 60:04.1f})' if isinstance(at, (int, float)) else ''
    if name == 'loudness_lufs':
        if v is None:
            return ('The loudness could not be measured.', 'Check the video has sound, then check it again.')
        quieter = float(v) < -14.0
        return (f"It plays {'quieter' if quieter else 'louder'} than YouTube and phones expect ({_num(v)} LUFS; "
                'about -14 is right).',
                'Export again with "Set the volume for YouTube and phones" on (Export video).')
    plain = {
        'duration_vs_target': (f'It runs {_num(v)} s; the plan was {t}.',
                               'Trim it or add to it to land near the length you planned, or keep it if it works.'),
        'vertical_1080x1920': (f'The picture is {v}; Shorts, TikTok and Reels look best at 1080x1920.',
                               'Export from a 1080x1920 project (Export video keeps the project\'s size).'),
        'tiktok_just_under_60s': (f'It runs {_num(v)} s: TikTok pays creators for videos of 60 s or more.',
                                  'Make it 60 s or longer, or keep it short on purpose.'),
        'true_peak_dbtp': (f'The loudest moments may crackle on phones (peaks at {_num(v)} dBTP; keep them under -1).',
                           'Export again with "Set the volume for YouTube and phones" on: it keeps the peaks down.'),
        'cuts_per_min': (f'{_num(v)} cuts a minute: this kind of video usually changes picture more often '
                         f'({_limit(t)}).',
                         'A suggestion, not a rule: tighten slow parts or add b-roll where it drags.'),
        'longest_static_s': (f'One shot stays on screen {_num(v)} s without a change{when}; usually '
                             f'{_limit(t, " s")}.',
                             'A suggestion: trim it, or add a punch-in, a sticker or b-roll there.'),
        'visual_change_first3s': ('Nothing changes on screen in the first 3 seconds.',
                                  'Open on movement or a quick cut, so people keep watching.'),
        'frame0_not_black': ('The very first frame is black.',
                             'Start on a picture: the first frame often shows before the video plays.'),
        'silence_first3s_s': (f"It's quiet for {_num(v)} s in the first 3 seconds.",
                              'Start the talking or the sound sooner.'),
        'silent_share': (f"{_num(float(v) * 100 if isinstance(v, (int, float)) else v, 0)}% of the video is silent.",
                         'Cut the quiet parts (Remove pauses) or put music under them.'),
        'tail_silence_s': (f'It ends with {_num(v)} s of silence.', 'Trim the quiet end.'),
        'first_speech_s': (f'The first words come at {_num(v)} s.',
                           'Start talking sooner, or open on something worth watching.'),
        'expected_words_audible': (f"Only {_num(float(v) * 100 if isinstance(v, (int, float)) else v, 0)}% of the "
                                   'words you meant are clearly heard.',
                                   'Check the voice is loud enough and the music under it is low enough.'),
    }
    return plain.get(name)


# what the review didn't do, in plain words (review_bundle's coverage names)
NOT_DONE_WORDS = {'listening': 'how the mix sounds (listen to it)', 'brief': 'your notes for this video (no brief)',
                  'transcript': 'the words said', 'timing': 'the rhythm', 'project checks': 'the project file',
                  'technical measurements': 'the measurements', 'pictures': 'the pictures',
                  'credits': 'credit lines'}


def check(a):
    video = Path(a.video)
    if not video.is_file():
        raise FileNotFoundError(f'there is no video at {video}')
    out = Path(a.out) if a.out else video.parent / f'{video.stem} review'
    if fake('check'):
        fake_steps(['looking at the whole video', 'listening to it', 'measuring the sound', 'writing the review'])
        out.mkdir(parents=True, exist_ok=True)
        report = out / 'review.md'
        report.write_text(f'# Review of {video.name}\n\n**Verdict: incomplete** (a stand-in review for a test '
                          'window).\n', encoding='utf-8')
        return {'verdict': 'incomplete', 'words': VERDICT_WORDS['incomplete'],
                'counts': {'critical': 0, 'major': 0, 'minor': 1},
                'findings': [{'at': '0:01.0', 'at_s': 1.0, 'severity': 'minor', 'what': 'a stand-in finding',
                              'fix': 'nothing to do', 'from': 'gate'}],
                'not_done': ['editorial review'], 'credits': [], 'report': str(report), 'folder': str(out),
                'fake': True}
    import letitedit.review.review_bundle as review_bundle
    progress(0.03, 'looking at the whole video and listening to it (about a minute)')
    r = review_bundle.bundle(str(video), kind=a.kind, project=a.project or None, out=str(out))
    progress(0.98, 'writing it up')
    not_done = [NOT_DONE_WORDS.get(c['check'], c['check']) if c['check'] != 'editorial review' else c['check']
                for c in r.get('coverage') or [] if c.get('state') not in ('done', 'off', 'not needed')]
    # the gate's measurements as sentences (checks.json beside the review), the rest as the review says them
    failed = {}
    try:
        for c in json.loads((out / 'checks.json').read_text(encoding='utf-8-sig')).get('checks') or []:
            if c.get('state') == 'fail':
                failed[c.get('check')] = c
    except (OSError, ValueError):
        pass
    findings = []
    for f in r.get('findings') or []:
        row = _plain_finding(f)
        name = str(f.get('what') or '').split(' = ')[0].strip()
        words = plain_check(failed[name]) if f.get('source') == 'gate' and name in failed else None
        if words:
            row.update(what=words[0], fix=words[1], measured=f.get('what'))
        findings.append(row)
    return {'verdict': r['verdict'], 'words': VERDICT_WORDS.get(r['verdict'], r['verdict']), 'counts': r['counts'],
            'findings': findings, 'not_done': not_done,
            'credits': r.get('credits') or [], 'report': r.get('report'), 'folder': str(out),
            'kind': r.get('kind'), 'duration_s': r.get('duration_s'), 'seconds': r.get('seconds')}


# ------------------------------------------------------------------ the command line

def image_status(a):
    import letitedit.pictures.image_gen as image_gen
    return image_gen.status()


COMMANDS = {'image-status': image_status, 'library-search': library_search, 'library-place': library_place, 'library-preview': library_preview,
            'captions-plan': captions_plan,
            'motion-blocks': motion_blocks,
            'motion-preview': motion_preview, 'motion-render': motion_render, 'sync': sync, 'check': check}


def parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('library-search')
    p.add_argument('--query', default='')
    p.add_argument('--kinds', default='')
    p.add_argument('--limit', type=int, default=60)
    p.add_argument('--offset', type=int, default=0)
    p.add_argument('--animated', choices=('', 'yes', 'no'), default='', help='yes: moving ones only')
    p.add_argument('--group', default='', help='comma-separated asset groups')
    p = sub.add_parser('library-place')
    p.add_argument('--id', required=True)
    p.add_argument('--px', type=int, default=0)
    p = sub.add_parser('library-preview')
    p.add_argument('--id', required=True)
    p = sub.add_parser('captions-plan')
    p.add_argument('--project', required=True, help='temporary XML copy of the open timeline')
    p.add_argument('--track', default='Captions')
    p.add_argument('--fixes', default='{}', help='the person\'s heard-to-written word list as JSON')
    sub.add_parser('motion-blocks')
    sub.add_parser('image-status')
    for name in ('motion-preview', 'motion-render'):
        p = sub.add_parser(name)
        p.add_argument('--spec', required=True, help='{block, params, duration} as JSON')
        p.add_argument('--size', type=int, nargs=2, default=[1920, 1080])
        p.add_argument('--fps', type=float, default=30.0)
        p.add_argument('--look', default='')
        p.add_argument('--count', type=int, default=4)
        p.add_argument('--out-dir', default='')
    p = sub.add_parser('sync')
    p.add_argument('files', nargs='*')
    p.add_argument('--folder', default='')
    p.add_argument('--project', required=True)
    p = sub.add_parser('check')
    p.add_argument('--video', required=True)
    p.add_argument('--project', default='')
    p.add_argument('--out', default='')
    p.add_argument('--kind', choices=('short', 'long'), default=None)
    return ap


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # the app reads UTF-8 whatever the code page
    a = parser().parse_args(argv)
    try:
        result = COMMANDS[a.command](a)
    except Exception as e:  # noqa: BLE001 - every failure goes back to the app in words
        say({'error': f'{e}' if isinstance(e, (ValueError, FileNotFoundError, LookupError, RuntimeError))
             else f'{type(e).__name__}: {e}'})
        return 1
    say({'result': result})
    return 0


if __name__ == '__main__':
    sys.exit(main())
