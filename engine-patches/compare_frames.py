"""Render the same frames of real projects with two app folders and compare them pixel by pixel.

Used to prove that new engine modules change only what they are meant to (engine-patches\\README.md): run it with
the app as it is (A) and a copy holding the new modules (B).

    python compare_frames.py --app-a <app folder> --app-b <app folder> --out <folder> [--samples 6]
                             [--env-a KEY=VALUE ...] [--env-b KEY=VALUE ...] project.mlt ...

For each project: `samples` frames spread over the timeline plus its last two frames, rendered by each app's melt.exe
in one run per app the way bridge\\checks.render_frames does it (a playlist of one-frame cuts of the project, so the
timeline keeps its own in and out points, as in a normal export; `melt project in=N out=N` would be a range export,
which the stock engine treats differently for captions). --env-a/--env-b set environment variables for one side
(for example SHOTCUT_AI_FONT_DIRS for the 20 Oct engine, which reads the font folders under that old name).
Writes <out>\\report.json and, for every frame that differs, <stem>-<frame>-AB.png (A | B | the differing pixels in
red). Prints one line per project. Run it under the PC render lock.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parent.parent


def project_length(path):
    """Frames in the project's main tractor (tractor0, else the last tractor): out + 1."""
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    prof = re.search(r'<profile[^>]*frame_rate_num="(\d+)"[^>]*frame_rate_den="(\d+)"', text)
    fps = int(prof.group(1)) / int(prof.group(2)) if prof else 30.0
    tractors = re.findall(r'<tractor id="([^"]+)"([^>]*)>', text)
    main = next((a for i, a in tractors if i == 'tractor0'), tractors[-1][1] if tractors else '')
    out = re.search(r'\bout="([^"]+)"', main)
    if not out:
        raise ValueError(f'{path}: no out point on the main tractor')
    v = out.group(1)
    if ':' in v:
        h, m, s = v.split(':')
        frames = round((int(h) * 3600 + int(m) * 60 + float(s)) * fps)
    else:
        frames = int(v)
    return frames + 1


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def render(app, project, frames, out_dir, stem, env=None):
    """The given frames of the project by app\\melt.exe, one run: [png per frame] (out_dir/stem-NNNN.png)."""
    text = Path(project).read_text(encoding='utf-8', errors='replace')
    profile = re.search(r'<profile\b[^>]*/>', text)
    entries = '\n'.join(f'    <entry producer="cut" in="{f}" out="{f}"/>' for f in frames)
    wrapper = out_dir / f'{stem}.frames.mlt'
    wrapper.write_text('<?xml version="1.0" encoding="utf-8"?>\n<mlt LC_NUMERIC="C">\n  '
                       + (profile.group(0) if profile else '') + '\n'
                       f'  <producer id="cut"><property name="resource">{_esc(str(Path(project).resolve()))}</property>'
                       '<property name="mlt_service">xml</property></producer>\n'
                       f'  <playlist id="sheet">\n{entries}\n  </playlist>\n</mlt>\n', encoding='utf-8')
    for old in out_dir.glob(f'{stem}-*.png'):
        old.unlink()
    r = subprocess.run([str(Path(app) / 'melt.exe'), '-quiet', str(wrapper), '-consumer',
                        f'avformat:{out_dir / stem}-%04d.png', 'vcodec=png', 'an=1', 'audio_off=1'],
                       capture_output=True, text=True, timeout=300 + 20 * len(frames), encoding='utf-8',
                       errors='replace', env=env)
    pngs = sorted(out_dir.glob(f'{stem}-*.png'))
    if len(pngs) < len(frames):
        raise RuntimeError(f'melt rendered {len(pngs)} of {len(frames)} frames of {project}: {r.stderr[-300:]}')
    return pngs[:len(frames)]


def diff(a_png, b_png, out_png):
    """(pixels that differ, largest channel difference, box); writes A | B | red mask when they differ."""
    with Image.open(a_png) as a0, Image.open(b_png) as b0:
        a, b = a0.convert('RGB'), b0.convert('RGB')
        if a.size != b.size:
            return -1, 255, None
        d = ImageChops.difference(a, b)
        box = d.getbbox()
        if not box:
            return 0, 0, None
        mask = d.convert('L').point(lambda v: 255 if v > 0 else 0)
        n = mask.histogram()[255]
        biggest = max(hi for _, hi in d.getextrema())
        sheet = Image.new('RGB', (a.width * 3, a.height))
        sheet.paste(a, (0, 0))
        sheet.paste(b, (a.width, 0))
        red = Image.new('RGB', a.size, (255, 0, 0))
        sheet.paste(Image.composite(red, a.point(lambda v: v // 3), mask), (a.width * 2, 0))
        scale = min(1.0, 2400 / sheet.width)
        if scale < 1:
            sheet = sheet.resize((int(sheet.width * scale), int(sheet.height * scale)))
        sheet.save(out_png)
        return n, biggest, box


def _env(pairs):
    env = dict(os.environ)
    env.setdefault('LETITEDIT_FONT_DIRS', str(ROOT / 'fonts' / 'library'))
    for p in pairs or ():
        k, _, v = p.partition('=')
        env[k] = v
    return env


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--app-a', required=True)
    ap.add_argument('--app-b', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--samples', type=int, default=6)
    ap.add_argument('--env-a', action='append', default=[])
    ap.add_argument('--env-b', action='append', default=[])
    ap.add_argument('projects', nargs='+')
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    env_a, env_b = _env(a.env_a), _env(a.env_b)
    report = []
    for proj in a.projects:
        stem = re.sub(r'[^\w.-]+', '_', Path(proj).stem)
        try:
            n = project_length(proj)
            frames = sorted({int(n * (i + 0.5) / a.samples) for i in range(a.samples)} | {n - 2, n - 1})
            pa = render(a.app_a, proj, frames, out, f'{stem}-A', env_a)
            pb = render(a.app_b, proj, frames, out, f'{stem}-B', env_b)
        except Exception as ex:  # noqa: BLE001
            report.append({'project': proj, 'error': str(ex)})
            print(f'ERROR {proj}: {ex}')
            continue
        rows = []
        for f, fa, fb in zip(frames, pa, pb):
            px, biggest, box = diff(fa, fb, out / f'{stem}-{f}-AB.png')
            rows.append({'frame': f, 'differing_pixels': px, 'max_diff': biggest, 'box': box,
                         'a': str(fa), 'b': str(fb)})
        same = [r['frame'] for r in rows if r['differing_pixels'] == 0]
        changed = [r for r in rows if r['differing_pixels']]
        report.append({'project': proj, 'frames_total': n, 'compared': rows})
        print(f"{Path(proj).name}: {len(same)}/{len(rows)} frames identical"
              + ''.join(f"; frame {r['frame']}: {r['differing_pixels']} px differ (max {r['max_diff']}, box {r['box']})"
                        for r in changed))
    (out / 'report.json').write_text(json.dumps(report, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
