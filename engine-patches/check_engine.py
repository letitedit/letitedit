"""Render checks for letitedit's patched MLT modules (engine-patches\\README.md).

Runs the app's own melt.exe on small generated projects and measures the frames:

  weight      text drawn by the qtext producer (the `text` filter, Shotcut's Text clip) and by the qtext filter
              (dynamictext = Simple Text, captions burn-in): weight 700 and 800 must draw heavier than 400
  italic      the plain-italic weight letitedit writes (weight * 10 + 10, fonts.mlt_text_style): 4010 must draw like 400
  last_cue    a burned-in caption (subtitle_feed + subtitle, as the Captions panel writes them) whose cue ends on the
              video's last frame, at its end or past it must still be drawn (the stock 7.41 engine drew nothing)
  range_start a range render (Export > marker ranges, letitedit_export's chunks, check_range: melt <project> in= out=)
              draws a cue that began before the range from its first frame, and one running past it to its last
  font_dirs   melt loads the folders named by LETITEDIT_FONT_DIRS
  chain_ref   the engine itself (app\\libmlt-7.dll) frees a closed clip's normalizer links
              (mlt-chain-normalizer-ref\\check_chain_ref.py; the stock 7.41 engine keeps about 377 handles per clip)
  cache_ref   the engine frees a clip's decoder when a kept frame outlives the decoder's cache eviction
              (mlt-cache-held-item\\check_cache_ref.py; the stock 7.41 engine keeps one decoder, ~17 threads, a time)
  resample_ref the resample module (lib\\mlt\\libmltresample.dll) frees a closed resample filter, so a clip the
              loader made keeps nothing (mlt-resample-close\\check_resample_ref.py; stock 7.41 keeps 17-18 handles)

    python check_engine.py [--app C:\\LetItEdit\\app] [--out <folder for frames>] [--json]

Exit code 0 when every check passes. A full pass (no --only) records the SHA-256 of the app's lib\\mlt\\libmltqt6.dll,
lib\\mlt\\libmltplus.dll, lib\\mlt\\libmltresample.dll and libmlt-7.dll in modules\\VERIFIED.txt: deploy.ps1 (and so every editor build) and the
installer build take only engine files listed there. To verify freshly built ones, copy them into a copy of the app
and check that copy.
Renders are tiny (single frames at 640x360 or 1280x720); run it under the PC render lock like any render:
python bridge\\render_lock.py run --name engine-check -- python check_engine.py ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
FONT_LIBRARY = ROOT / 'fonts' / 'library'


def melt(app, args, env=None, timeout=120):
    """Run app\\melt.exe; returns the CompletedProcess (stdout and stderr as text)."""
    return subprocess.run([str(Path(app) / 'melt.exe'), *args], capture_output=True, text=True, timeout=timeout,
                          env=env, encoding='utf-8', errors='replace')


def lit(png, box=None):
    """Pixels brighter than mid-grey (white text on black) in the frame, or in box (x0, y0, x1, y1)."""
    with Image.open(png) as im:
        g = im.convert('L')
        if box:
            g = g.crop(box)
        return sum(1 for p in g.getdata() if p > 128)


def frame_of(app, producer_args, out_png, profile='atsc_720p_30', env=None):
    """Render one frame of a producer (args after melt's profile) to out_png; returns the png path."""
    pattern = str(out_png).replace('.png', '-%02d.png')
    r = melt(app, ['-quiet', '-profile', profile, *producer_args, '-consumer', f'avformat:{pattern}', 'vcodec=png',
                   'an=1', 'audio_off=1'], env=env)
    got = Path(pattern.replace('%02d', '01'))
    if not got.exists():
        raise RuntimeError(f'melt drew nothing for {producer_args}: {r.stderr[-400:]}')
    got.replace(out_png)
    return out_png


def text_frame(app, service, family, weight, style, out_png, env=None):
    """One 1280x720 frame of 'Weight 48' in white on black, drawn by the `text` or `dynamictext` filter."""
    return frame_of(app, ['color:0x000000ff', 'in=0', 'out=0', '-filter', service, 'argument=Weight 48',
                          f'family={family}', 'size=120', f'weight={weight}', f'style={style}',
                          'fgcolour=0xffffffff', 'olcolour=0x00000000', 'bgcolour=0x00000000', 'outline=0',
                          'geometry=0 0 1280 720 1', 'halign=center', 'valign=middle'], out_png, env=env)


def check_weight(app, out, env):
    """Weight 400 / 700 / 800 through both text paths, in Arial (static faces) and Inter (variable font)."""
    rows, ok = [], True
    for service in ('text', 'dynamictext'):
        for family in ('Arial', 'Inter'):
            px = {w: lit(text_frame(app, service, family, w, 'normal', out / f'weight-{service}-{family}-{w}.png',
                                    env)) for w in (400, 700, 800)}
            # Arial has no 800 face (800 draws its Bold); Inter is variable, so 800 is heavier than 700
            good = px[700] > px[400] * 1.15 and px[800] >= px[700] * 0.98
            ok &= good
            rows.append({'service': service, 'family': family, 'lit': px, 'pass': good})
    return {'check': 'weight', 'pass': ok, 'rows': rows,
            'note': 'lit pixels of the same words; heavier weights must light more pixels'}


def check_italic(app, out, env):
    """Plain italic as letitedit writes it (style italic, weight 4010) must draw like weight 400, not the boldest."""
    rows, ok = [], True
    for service in ('text', 'dynamictext'):
        px = {w: lit(text_frame(app, service, 'Inter', w, 'italic', out / f'italic-{service}-{w}.png', env))
              for w in (400, 4010, 7010)}
        good = abs(px[4010] - px[400]) <= px[400] * 0.03 and px[7010] > px[400] * 1.15
        ok &= good
        rows.append({'service': service, 'family': 'Inter', 'lit': px, 'pass': good})
    return {'check': 'italic', 'pass': ok, 'rows': rows,
            'note': '4010 = italic at 400 and 7010 = italic at 700 in the encoded form; 4010 must match 400'}


SRT_CUE = '{n}\n{a} --> {b}\n{text}\n\n'


def srt_time(ms):
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def caption_project(path, frames, cues):
    """A 640x360 30 fps project laid out as the Captions panel writes it: a black clip, a subtitle_feed on the main
    tractor and the burn-in subtitle filter (white Arial, centred). cues: [(start_ms, end_ms, text)]."""
    srt = ''.join(SRT_CUE.format(n=i + 1, a=srt_time(a), b=srt_time(b), text=t) for i, (a, b, t) in enumerate(cues))
    srt = srt.replace('>', '&gt;')
    path.write_text(f'''<?xml version="1.0" standalone="no"?>
<mlt LC_NUMERIC="C" version="7.41.0" producer="main_bin">
  <profile description="640x360 30 fps" width="640" height="360" progressive="1" sample_aspect_num="1"
    sample_aspect_den="1" display_aspect_num="16" display_aspect_den="9" frame_rate_num="30" frame_rate_den="1"
    colorspace="709"/>
  <producer id="black" in="0" out="{frames - 1}">
    <property name="length">{frames}</property>
    <property name="eof">pause</property>
    <property name="resource">0x000000ff</property>
    <property name="mlt_service">color</property>
  </producer>
  <playlist id="playlist0">
    <entry producer="black" in="0" out="{frames - 1}"/>
  </playlist>
  <tractor id="tractor0" in="0" out="{frames - 1}">
    <track producer="playlist0"/>
    <filter id="filter0">
      <property name="feed">Subtitle Track 1</property>
      <property name="lang">eng</property>
      <property name="mlt_service">subtitle_feed</property>
      <property name="shotcut:hidden">1</property>
      <property name="text">{srt}</property>
    </filter>
    <filter id="filter1" out="{frames - 1}">
      <property name="geometry">0 0 640 360 1</property>
      <property name="family">Arial</property>
      <property name="size">96</property>
      <property name="weight">700</property>
      <property name="style">normal</property>
      <property name="fgcolour">#ffffffff</property>
      <property name="bgcolour">#00000000</property>
      <property name="olcolour">#00000000</property>
      <property name="outline">0</property>
      <property name="halign">center</property>
      <property name="valign">middle</property>
      <property name="mlt_service">subtitle</property>
      <property name="shotcut:filter">subtitles</property>
      <property name="feed">Subtitle Track 1</property>
    </filter>
  </tractor>
</mlt>
''', encoding='utf-8')
    return path


def project_frames(app, project, out_dir, stem, env, *producer_args):
    """Every frame of a project as PNGs (out_dir/stem-NN.png, numbered from 1); returns the sorted paths.
    producer_args follow the project on melt's command line (in=N out=M renders a range, as the editor's export does)."""
    r = melt(app, ['-quiet', str(project), *producer_args, '-consumer', f'avformat:{out_dir / stem}-%02d.png',
                   'vcodec=png', 'an=1', 'audio_off=1'], env=env)
    frames = sorted(out_dir.glob(f'{stem}-*.png'))
    if not frames:
        raise RuntimeError(f'melt drew nothing for {project}: {r.stderr[-400:]}')
    return frames


def check_last_cue(app, out, env):
    """A 2 s video (frames 0-59); the last cue starts at 1.2 s and ends at the last frame's start (1.967 s), the
    video's end (2.000 s) or past it (2.5 s). Frame 50 must show it in every case, frame 59 when it runs to the end.
    A cue ending at 1.933 s (before the last frame; drawn by the stock engine too) is the control."""
    rows, ok = [], True
    for end_ms in (1933, 1967, 2000, 2500):
        proj = caption_project(out / f'last-cue-{end_ms}.mlt', 60, [(200, 800, 'FIRST'), (1200, end_ms, 'LAST')])
        frames = project_frames(app, proj, out, f'last-cue-{end_ms}', env)
        px = {f: lit(frames[f]) for f in (10, 50, 58, 59)}   # frame index in the video (frames[0] = frame 0)
        want = {10: True, 50: True, 58: end_ms >= 1967, 59: end_ms >= 2000}
        good = len(frames) == 60 and all((px[f] > 500) == want[f] for f in want)
        ok &= good
        rows.append({'cue_end_s': end_ms / 1000, 'frames': len(frames), 'lit': px,
                     'expected_drawn': want, 'pass': good})
    return {'check': 'last_cue', 'pass': ok, 'rows': rows,
            'note': 'lit pixels of the caption on video frames 10 (FIRST), 50, 58 and 59 (LAST; 59 is the last frame)'}


def check_range_start(app, out, env):
    """Export of a range of a 3 s video (frames 15-44 = 0.5-1.5 s, rendered as the editor's Export > marker range
    does: melt <project> in=15 out=44): a cue from 0.0 to 1.0 s must show from the range's first frame until 1.0 s;
    a cue from 1.2 s to 3.0 s (past the range) must show from 1.2 s to the range's last frame."""
    proj = caption_project(out / 'range.mlt', 90, [(0, 1000, 'EARLY'), (1200, 3000, 'LATE')])
    frames = project_frames(app, proj, out, 'range', env, 'in=15', 'out=44')
    # output frame k = video frame 15 + k: k 0-14 = 0.5-0.967 s (EARLY), k 15-20 none, k 21-29 = 1.2-1.467 s (LATE)
    px = {k: lit(frames[k]) for k in (0, 10, 17, 22, 29)} if len(frames) >= 30 else {}
    want = {0: True, 10: True, 17: False, 22: True, 29: True}
    good = len(frames) == 30 and all((px[k] > 500) == want[k] for k in want)
    return {'check': 'range_start', 'pass': good, 'frames': len(frames), 'lit': px, 'expected_drawn': want,
            'note': 'output frames 0 and 10 (EARLY, which began before the range), 17 (between cues), 22 and 29 '
                    '(LATE, which runs past the range)'}


def check_font_dirs(app, out, env):
    """melt -verbose reports loading the folder named by LETITEDIT_FONT_DIRS."""
    folder = FONT_LIBRARY / 'Anton'
    e = dict(env, LETITEDIT_FONT_DIRS=str(folder))
    r = melt(app, ['-verbose', '-profile', 'atsc_720p_30', 'color:0x000000ff', 'in=0', 'out=0', '-filter', 'text',
                   'argument=Fonts', 'family=Anton', '-consumer', f'avformat:{out}/fontdirs-%02d.png', 'vcodec=png',
                   'an=1', 'audio_off=1'], env=e)
    lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines() if 'fonts: loaded' in ln]
    good = any(str(folder).replace('\\', '/').lower() in ln.replace('\\', '/').lower() for ln in lines)
    return {'check': 'font_dirs', 'pass': good, 'log': lines[:3],
            'note': f'LETITEDIT_FONT_DIRS={folder}; the module must say it loaded that folder'}


def check_chain_ref(app, out, env):
    """The engine (app\\libmlt-7.dll) frees a closed clip's normalizer links (mlt-chain-normalizer-ref)."""
    import importlib.util
    path = Path(__file__).resolve().parent / 'mlt-chain-normalizer-ref' / 'check_chain_ref.py'
    spec = importlib.util.spec_from_file_location('check_chain_ref', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.check(Path(app) / 'libmlt-7.dll', Path(app), workdir=out)
    return {'check': 'chain_ref', 'pass': r['pass'],
            'rows': {k: r[k] for k in ('links', 'kept_per_clip_normalized', 'kept_per_clip_bare')},
            'note': 'handles a closed clip keeps with its normalizer links and without; the stock 7.41 engine keeps '
                    'about 377 with them (engine-patches\\mlt-chain-normalizer-ref)'}


def check_cache_ref(app, out, env):
    """The engine (app\\libmlt-7.dll) frees a clip's decoder when a kept frame outlives its cache eviction
    (mlt-cache-held-item)."""
    import importlib.util
    path = Path(__file__).resolve().parent / 'mlt-cache-held-item' / 'check_cache_ref.py'
    spec = importlib.util.spec_from_file_location('check_cache_ref', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.check(Path(app) / 'libmlt-7.dll', Path(app), workdir=out)
    return {'check': 'cache_ref', 'pass': r['pass'],
            'rows': {k: r[k] for k in ('threads_kept_evicted', 'threads_kept_plain', 'drawn')},
            'note': "threads kept after five cycles of a kept frame outliving its decoder's cache eviction; the stock "
                    '7.41 engine keeps one decoder a cycle (engine-patches\\mlt-cache-held-item)'}


def check_resample_ref(app, out, env):
    """The resample module (app\\lib\\mlt\\libmltresample.dll) frees a closed resample filter (mlt-resample-close)."""
    import importlib.util
    path = Path(__file__).resolve().parent / 'mlt-resample-close' / 'check_resample_ref.py'
    spec = importlib.util.spec_from_file_location('check_resample_ref', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.check(Path(app))
    return {'check': 'resample_ref', 'pass': r['pass'],
            'rows': {k: r[k] for k in ('kept_resample', 'kept_loader_clip', 'kept_comparison')},
            'note': 'handles a closed resample filter and a closed clip the loader made keep, against a closed '
                    'channelcopy filter; the stock 7.41 module keeps 17 and 18 (engine-patches\\mlt-resample-close)'}


CHECKS = {'weight': check_weight, 'italic': check_italic, 'last_cue': check_last_cue,
          'range_start': check_range_start, 'font_dirs': check_font_dirs, 'chain_ref': check_chain_ref,
          'cache_ref': check_cache_ref, 'resample_ref': check_resample_ref}


VERIFIED = Path(__file__).resolve().parent / 'modules' / 'VERIFIED.txt'
MODULES = ('libmltqt6.dll', 'libmltplus.dll', 'libmltresample.dll')   # in app\\lib\\mlt
FRAMEWORK = ('libmlt-7.dll',)                    # in app itself


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def record_verified(app, out):
    """After a full pass: add the checked app's engine files (the three modules and libmlt-7.dll, SHA-256) to
    modules\\VERIFIED.txt, the list deploy.ps1 and the installer build accept them from. Returns the lines added."""
    files = [Path(app) / 'lib' / 'mlt' / n for n in MODULES] + [Path(app) / n for n in FRAMEWORK]
    known = VERIFIED.read_text(encoding='utf-8').splitlines() if VERIFIED.exists() else []
    have = {ln.split()[0] + ' ' + ln.split()[1] for ln in known if ln and not ln.startswith('#')}
    new = []
    for f in files:
        line = f'{sha256(f)} *{f.name}'
        if line not in have:
            new.append(line)
    if new:
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        VERIFIED.parent.mkdir(parents=True, exist_ok=True)
        with open(VERIFIED, 'a', encoding='utf-8', newline='\n') as f:
            if not known:
                f.write('# Engine files that passed every check in check_engine.py (weight, italic, last_cue,\n'
                        '# range_start, font_dirs, chain_ref, cache_ref, resample_ref). deploy.ps1 and release\\installer\\build.ps1 take only these.\n')
            f.write(f'# {stamp}: all checks passed on {Path(app).resolve()} (frames: {out})\n')
            f.write(''.join(ln + '\n' for ln in new))
    return new


def run(app, out=None, only=None):
    """Run the checks against an app folder; returns {'app', 'pass', 'checks': [...], 'verified': [...]}. A full
    pass (no `only`) records the app's modules in modules\\VERIFIED.txt."""
    out = Path(out or tempfile.mkdtemp(prefix='engine-check-'))
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault('LETITEDIT_FONT_DIRS', str(FONT_LIBRARY))
    results = []
    for name, fn in CHECKS.items():
        if only and name not in only:
            continue
        try:
            results.append(fn(app, out, env))
        except Exception as ex:  # noqa: BLE001
            results.append({'check': name, 'pass': False, 'error': str(ex)})
    ok = bool(results) and all(r['pass'] for r in results)
    verified = record_verified(app, out) if ok and not only else []
    return {'app': str(app), 'frames': str(out), 'pass': ok, 'checks': results, 'verified': verified}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--app', default=str(ROOT / 'app'))
    ap.add_argument('--out', help='folder for the frames (default: a new temporary folder)')
    ap.add_argument('--only', nargs='*', choices=sorted(CHECKS))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    res = run(a.app, a.out, a.only)
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(f"{'PASS' if res['pass'] else 'FAIL'}  {res['app']}  (frames: {res['frames']})")
        for c in res['checks']:
            detail = c.get('error') or json.dumps(c.get('rows') or {k: c[k] for k in ('lit', 'log') if k in c})
            print(f"  {'pass' if c['pass'] else 'FAIL'}  {c['check']:12s} {detail}")
        for line in res['verified']:
            print(f'  recorded in {VERIFIED.name}: {line}')
    return 0 if res['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
