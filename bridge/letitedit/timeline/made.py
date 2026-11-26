"""Clips made from other clips, as timeline items: an ffmpeg filter graph, a reversed shot, a freeze frame, a shot
effect (vfx), a narrated line (voice).

    {ffmpeg: {inputs: [{clip, in, out, speed?}], video?: "...", audio?: "..." | true | false, alpha?: false,
              fit?: contain|cover|none}, len?}
    {clip, in, out, reverse: true}
    {freeze: {clip, at}, len}
    {vfx: {effect, source?: {clip, in, out, speed?}, params?: {...}}, len?}     (vfx_items.py; letitedit_vfx_effects)
    {voice: {text, voice?, speed?}}                                            (audio: local Kokoro TTS)

A recipe renders once into <project folder>/made (named by a hash of the recipe and the source files) and the result
is placed like any clip. The recipe is stored on the clip (letitedit_ai:made), so reading the timeline shows the recipe
and changing it re-renders. Renders use the full ffmpeg on this PC when there is one (drawtext, subtitles/ass, zoompan,
xfade...), else the editor's own.
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import hashlib
import json
import re
import os
import subprocess
from pathlib import Path

MADE_PROP = 'letitedit_ai:made'
APP_FFMPEG = Path(os.environ.get('LETITEDIT_APP', (_SAI_ROOT + '\\app'))) / 'ffmpeg.exe'
FULL_FFMPEG = Path(os.environ.get('LETITEDIT_FULL_FFMPEG', Path.home() / '.local' / 'bin' / 'ffmpeg.exe'))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
RENDER_TIMEOUT = 900
MAX_REVERSE_S = 30


# generated clips (C5): item key -> module with recipe/view/default_len/label/render_recipe
GENERATED = {'render3d': 'letitedit.pictures.render3d', 'map': 'letitedit.pictures.maps', 'motion': 'letitedit.pictures.motion'}


def _gen(kind):
    import importlib
    return importlib.import_module(GENERATED[kind])


def _generated_module(item):
    for k in GENERATED:
        if isinstance(item, dict) and k in item and isinstance(item[k], (dict, str)):
            return _gen(k)
    return None


def ffmpeg_exe():
    return FULL_FFMPEG if FULL_FFMPEG.exists() else APP_FFMPEG


def is_made(item):
    return ('ffmpeg' in item or 'freeze' in item or bool(item.get('reverse')) or 'vfx' in item or 'voice' in item
            or _generated_module(item) is not None
            or 'ass' in item)


def label_of(recipe):
    """Short display name for a made clip."""
    k = recipe.get('kind')
    if k in GENERATED:
        return _gen(k).label(recipe)
    if k in ('vfx', 'voice'):
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.label(recipe)
    if k == 'ass':
        first = next((ln.split(',', 9)[-1] for ln in recipe['script'].splitlines() if ln.startswith('Dialogue:')), '')
        return 'text: ' + re.sub(r'\{[^}]*\}', '', first).replace(r'\N', ' ')[:40]
    clip = recipe.get('clip') or (recipe.get('inputs') or [{}])[0].get('clip', '')
    return f"{ {'reverse': 'reversed'}.get(k, k)}: {os.path.basename(clip)}"


def _sec(v):
    import letitedit.timeline.edit_script as es
    return es.to_seconds(v)


def recipe_of(item):
    """The recipe for a made item (what gets rendered), normalised."""
    if 'ass' in item:
        script = item['ass']
        if isinstance(script, dict):
            script = script.get('script') or Path(script['file']).read_text(encoding='utf-8-sig')
        r = {'kind': 'ass', 'script': str(script)}
        r['len'] = _sec(item['len']) if item.get('len') is not None else ass_length(r['script'])
        return r
    if _generated_module(item) is not None:
        return _generated_module(item).recipe(item)
    if 'vfx' in item:
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.recipe(item)
    if 'voice' in item:
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.voice_recipe(item)
    if 'ffmpeg' in item:
        f = dict(item['ffmpeg'])
        inputs = f.get('inputs') or ([{'clip': f['clip'], 'in': f.get('in', 0), 'out': f.get('out')}] if f.get('clip') else [])
        if not inputs:
            raise ValueError('an ffmpeg item needs inputs: [{clip, in, out}] (or clip, in, out)')
        norm = []
        for i in inputs:
            if 'clip' not in i:
                raise ValueError(f'each ffmpeg input needs a clip: {i}')
            d = {'clip': str(i['clip']), 'in': _sec(i.get('in', 0))}
            if i.get('out') is not None:
                d['out'] = _sec(i['out'])
            if float(i.get('speed', 1.0)) != 1.0:
                d['speed'] = float(i['speed'])
            norm.append(d)
        r = {'kind': 'ffmpeg', 'inputs': norm}
        for k in ('video', 'audio', 'alpha', 'fit'):
            if k in f and f[k] is not None:
                r[k] = f[k]
        if item.get('len') is not None:
            r['len'] = _sec(item['len'])
        return r
    if 'freeze' in item:
        fz = item['freeze']
        return {'kind': 'freeze', 'clip': str(fz['clip']), 'at': _sec(fz.get('at', 0))}
    if item.get('reverse'):
        a, b = _sec(item['in']), _sec(item['out'])
        if b - a > MAX_REVERSE_S:
            raise ValueError(f"{item.get('id')}: reverse works on up to {MAX_REVERSE_S} s at a time ({b - a:.1f} s asked)")
        return {'kind': 'reverse', 'clip': str(item['clip']), 'in': a, 'out': b}
    raise ValueError('not a made item')


def view_of(recipe):
    """Script fields for a stored recipe (without id/len/effects)."""
    k = recipe.get('kind')
    if k == 'ass':
        return {'ass': recipe['script']}
    if k in GENERATED:
        return _gen(k).view(recipe)
    if k == 'vfx':
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.view(recipe)
    if k == 'voice':
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.voice_view(recipe)
    if k == 'ffmpeg':
        f = {'inputs': recipe['inputs']}
        for key in ('video', 'audio', 'alpha', 'fit'):
            if key in recipe:
                f[key] = recipe[key]
        return {'ffmpeg': f}
    if k == 'freeze':
        return {'freeze': {'clip': recipe['clip'], 'at': recipe['at']}}
    if k == 'reverse':
        return {'clip': recipe['clip'], 'in': recipe['in'], 'out': recipe['out'], 'reverse': True}
    raise ValueError(f'unknown made recipe {recipe}')


def default_len(item):
    """Seconds a made item lasts when it doesn't say."""
    if item.get('len') is not None:
        return _sec(item['len'])
    if 'ass' in item:
        a = item['ass']
        return ass_length(a.get('script', '') if isinstance(a, dict) else str(a))
    if _generated_module(item) is not None:
        return _generated_module(item).default_len(item)
    if 'vfx' in item:
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.default_len(item)
    if 'voice' in item:
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.voice_len(item)
    if 'freeze' in item:
        return 2.0
    if 'ffmpeg' in item:
        f = item['ffmpeg']
        i = (f.get('inputs') or [f])[0]
        if i.get('out') is not None:
            return (_sec(i['out']) - _sec(i.get('in', 0))) / float(i.get('speed', 1.0))
        return 5.0
    return (_sec(item['out']) - _sec(item['in']))


def _digest(recipe, width, height, fps):
    files = []
    for clip in [i['clip'] for i in recipe.get('inputs', [])] + ([recipe['clip']] if 'clip' in recipe else []):
        try:
            st = os.stat(clip)
            files.append([clip, st.st_size, int(st.st_mtime)])
        except OSError:
            raise FileNotFoundError(f'no such file: {clip}') from None
    key = json.dumps({'r': recipe, 'f': files, 'size': [width, height], 'fps': round(fps, 4), 'engine': 2}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def _fit(width, height, fps, fit, alpha):
    fmt = 'yuva444p10le' if alpha else 'yuv420p'
    if fit == 'none':
        return f'fps={fps:.6f},setsar=1,format={fmt}'
    if fit == 'cover':
        return (f'fps={fps:.6f},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},'
                f'setsar=1,format={fmt}')
    pad = '0x00000000' if alpha else 'black'
    return (f'fps={fps:.6f},scale={width}:{height}:force_original_aspect_ratio=decrease,'
            f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={pad},setsar=1,format={fmt}')


def _run(cmd, what):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=RENDER_TIMEOUT, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f'{what} failed: {r.stderr.strip()[-1500:]}')


def _has_audio(path):
    ffprobe = APP_FFMPEG.with_name('ffprobe.exe')
    r = subprocess.run([str(ffprobe), '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0',
                        str(path)], capture_output=True, text=True, creationflags=NO_WINDOW)
    return bool(r.stdout.strip())


def render(recipe, width=1920, height=1080, fps=30.0, out_dir=None):
    """Render a recipe; returns {'path', 'cached', 'alpha'}."""
    out_dir = Path(out_dir or Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'made')
    if recipe['kind'] in GENERATED:
        return _gen(recipe['kind']).render_recipe(recipe, width, height, fps, out_dir)
    if recipe['kind'] in ('vfx', 'voice'):
        import letitedit.pictures.vfx_items as vfx_items
        return vfx_items.render_recipe(recipe, width, height, fps, out_dir)
    if recipe['kind'] == 'ass':
        return render_ass(recipe, width, height, fps, out_dir)
    if recipe['kind'] == 'fx':
        return render_fx(recipe, width, height, fps, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kind = recipe['kind']
    alpha = bool(recipe.get('alpha'))
    ext = '.png' if kind in ('freeze', 'still') else ('.mov' if alpha else '.mp4')
    path = out_dir / f'{kind}-{_digest(recipe, width, height, fps)}{ext}'
    if path.exists():
        return {'path': str(path), 'cached': True, 'alpha': alpha}
    tmp = path.with_name(path.stem + '.tmp' + ext)
    ff = ffmpeg_exe()
    vcodec = (['-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le'] if alpha
              else ['-c:v', 'libx264', '-crf', '14', '-preset', 'fast', '-pix_fmt', 'yuv420p'])
    acodec = ['-c:a', 'pcm_s16le'] if alpha else ['-c:a', 'aac', '-b:a', '256k']
    try:
        if kind == 'still':      # one frame at the source's own size (a freeze frame that effects then fit)
            _run([ff, '-hide_banner', '-y', '-ss', f"{recipe['at']:.3f}", '-i', recipe['clip'], '-frames:v', '1',
                  '-update', '1', tmp], 'still frame')
        elif kind == 'freeze':
            vf = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                  f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')
            _run([ff, '-hide_banner', '-y', '-ss', f"{recipe['at']:.3f}", '-i', recipe['clip'], '-frames:v', '1', '-vf', vf,
                  '-update', '1', tmp], 'freeze frame')
        elif kind == 'reverse':
            dur = recipe['out'] - recipe['in']
            cmd = [ff, '-hide_banner', '-y', '-ss', f"{recipe['in']:.3f}", '-t', f'{dur:.3f}', '-i', recipe['clip'],
                   '-vf', 'reverse,' + _fit(width, height, fps, 'contain', False)]
            cmd += (['-af', 'areverse', *acodec] if _has_audio(recipe['clip']) else ['-an'])
            _run(cmd + [*vcodec, '-movflags', '+faststart', tmp], 'reverse')
        else:
            cmd = [ff, '-hide_banner', '-y']
            for i in recipe['inputs']:
                cmd += ['-ss', f"{i['in']:.3f}"]
                if i.get('out') is not None:
                    cmd += ['-t', f"{(i['out'] - i['in']):.3f}"]
                cmd += ['-i', i['clip']]
            fit = _fit(width, height, fps, recipe.get('fit', 'contain'), alpha)
            video = (recipe.get('video') or '').strip()
            sp = float(recipe['inputs'][0].get('speed', 1.0))
            speed_v = f'setpts=PTS/{sp:g},' if sp != 1.0 else ''
            graph = []
            if '[' in video:
                graph.append(video.rstrip(';'))
                vlabel = '[v]'
                if '[v]' not in video:
                    raise ValueError('a filter graph with [labels] must end in [v] (and [a] for its sound)')
                graph.append(f'{vlabel}{fit}[vout]')
            else:
                graph.append(f"[0:v]{speed_v}{video + ',' if video else ''}{fit}[vout]")
            audio = recipe.get('audio', True)
            maps = ['-map', '[vout]']
            if audio is not False and '[a]' in video:
                maps += ['-map', '[a]']
            elif audio is not False and _has_audio(recipe['inputs'][0]['clip']):
                chain = audio if isinstance(audio, str) else ''
                speed_a = ','.join(f'atempo={x:g}' for x in _atempo(sp)) if sp != 1.0 else ''
                parts = [x for x in (speed_a, chain) if x]
                graph.append(f"[0:a]{','.join(parts) or 'anull'}[aout]")
                maps += ['-map', '[aout]']
            cmd += ['-filter_complex', ';'.join(graph), *maps, *vcodec]
            if len(maps) > 2:
                cmd += [*acodec, '-ar', '48000']
            first = recipe['inputs'][0]
            length = recipe.get('len')
            if length is None and first.get('out') is not None:
                length = (first['out'] - first['in']) / float(first.get('speed', 1.0))
            if length is not None:
                cmd += ['-t', f"{length:.3f}"]
            _run(cmd + ['-movflags', '+faststart', tmp], 'ffmpeg item')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {'path': str(path), 'cached': False, 'alpha': alpha}


# ------------------------------------------------------------------ .ass text layers

_ASS_TIME = re.compile(r'^\s*Dialogue:\s*[^,]*,\s*(\d+):(\d+):([\d.]+)\s*,\s*(\d+):(\d+):([\d.]+)', re.M)
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter,{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{outline},0,2,60,60,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_length(script):
    """Seconds until the last Dialogue line ends (3 s if there are none)."""
    ends = [int(m.group(4)) * 3600 + int(m.group(5)) * 60 + float(m.group(6)) for m in _ASS_TIME.finditer(script)]
    return round(max(ends), 3) if ends else 3.0


def ass_document(script, width, height):
    """A full .ass document: the script as given, or Dialogue lines wrapped in a header at the project size.
    A document without PlayResX/PlayResY gets the project size (libass would otherwise assume 384x288)."""
    if '[Events]' not in script:
        return ASS_HEADER.format(w=width, h=height, size=round(height * 0.06), outline=max(2, round(height / 270)),
                                 margin=round(height * 0.08)) + script.strip() + '\n'
    if 'PlayResX' not in script:
        script = script.replace('[Script Info]', f'[Script Info]\nPlayResX: {width}\nPlayResY: {height}', 1)
    return script


def _fonts_dir():
    d = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'Windows' / 'Fonts'
    return d if d.is_dir() else None


def render_ass(recipe, width, height, fps, out_dir):
    """A transparent text layer (QuickTime Animation, alpha) drawn by libass from an .ass script."""
    import tempfile
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'ass-{_digest(recipe, width, height, fps)}.mov'
    if path.exists():
        return {'path': str(path), 'cached': True, 'alpha': True}
    ff = ffmpeg_exe()
    if ff == APP_FFMPEG:
        raise RuntimeError('.ass text layers need an ffmpeg with libass (not found at ' + str(FULL_FFMPEG) + ')')
    vf = 'subtitles=layer.ass:alpha=1'
    fonts = _fonts_dir()
    if fonts is not None:
        vf += ":fontsdir='" + str(fonts).replace('\\', '/').replace(':', '\\:') + "'"
    rate = f'{fps:.6f}'.rstrip('0').rstrip('.')
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'layer.ass').write_text(ass_document(recipe['script'], width, height), encoding='utf-8')
        tmp = Path(d) / 'layer.mov'
        r = subprocess.run([str(ff), '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            f"color=c=black@0.0:s={width}x{height}:r={rate}:d={recipe['len']:.3f},format=rgba",
                            '-vf', vf, '-c:v', 'qtrle', '-pix_fmt', 'argb', str(tmp)], cwd=d, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=RENDER_TIMEOUT, creationflags=NO_WINDOW)
        if r.returncode != 0 or not tmp.exists():
            raise RuntimeError('.ass text layer failed: ' + r.stderr.strip()[-1200:])
        os.replace(tmp, path)
    return {'path': str(path), 'cached': False, 'alpha': True}


# ------------------------------------------------------------------ ffmpeg as an effect on a clip
#
# A normal clip (or every clip on a track) can carry {ffmpeg: "<filter chain or graph>"} in its effects. The clip's
# source range (plus a handle each side) is rendered through the graph in the background, and the clip plays that
# render; trimming inside the handles needs no new render, trimming past them renders again. The source file, its in/out
# points and the graphs are stored on the clip (letitedit_ai:fx), so reading the timeline shows the clip as written.

FX_PROP = 'letitedit_ai:fx'
FX_HANDLE_S = 0.5
FX_KEYS = ('video', 'audio', 'inputs', 'fit')
IMAGE_EXT = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.heic'}
_REF = re.compile(r'\[([^\[\]]+)\]')


def is_fx(effect):
    return isinstance(effect, dict) and ('ffmpeg' in effect or 'fix' in effect)


def is_fix(effect):
    """A fix-in-post effect {fix: {kind: night|shake|punch|voice, ...settings}} (fix_post.py)."""
    return isinstance(effect, dict) and 'fix' in effect


def fx_stage(effect):
    """An ffmpeg effect normalised: {video?, audio?, inputs?, fit?}; a fix effect: {fix: {kind, ...settings}}."""
    if is_fix(effect):
        import letitedit.review.fix_post as fix_post
        return {'fix': fix_post.normalise(effect['fix'])}
    spec = effect['ffmpeg']
    if isinstance(spec, str):
        spec = {'video': spec}
    if not isinstance(spec, dict):
        raise ValueError('an ffmpeg effect is {ffmpeg: "<filter chain or graph>"} or {ffmpeg: {video, audio, inputs, fit}}')
    unknown = sorted(set(spec) - set(FX_KEYS))
    if unknown:
        raise ValueError(f'ffmpeg effect: unknown key(s) {", ".join(unknown)} (it takes {", ".join(FX_KEYS)})')
    st = {}
    if spec.get('video'):
        st['video'] = str(spec['video']).strip().rstrip(';')
    if spec.get('audio') is False:
        st['audio'] = False
    elif spec.get('audio'):
        st['audio'] = str(spec['audio']).strip().rstrip(';')
    if spec.get('inputs'):
        ins = []
        for i in spec['inputs']:
            i = {'clip': i} if isinstance(i, str) else dict(i)
            if 'clip' not in i:
                raise ValueError(f'each ffmpeg effect input needs a clip: {i}')
            d = {'clip': str(i['clip'])}
            if i.get('in'):
                d['in'] = _sec(i['in'])
            ins.append(d)
        st['inputs'] = ins
    if spec.get('fit'):
        if spec['fit'] not in ('none', 'contain', 'cover'):
            raise ValueError("ffmpeg effect fit is none (keep the graph's own size), contain or cover")
        st['fit'] = spec['fit']
    if not st.get('video') and 'audio' not in st:
        raise ValueError('an ffmpeg effect needs a video or an audio graph')
    return st


def _fx_text(text, k, cur_v, cur_a, offset, key):
    """One stage's chain/graph wired to the current picture/sound. Returns (parts, new_v, new_a)."""
    parts = []
    if '[' not in text:
        if key == 'video':
            return [f'{cur_v}{text}[s{k}v]'], f'[s{k}v]', cur_a
        if cur_a is None:
            raise ValueError('this clip has no sound for the ffmpeg audio graph')
        return [f'{cur_a}{text}[s{k}a]'], cur_v, f'[s{k}a]'
    names = _REF.findall(text)
    # [v] / [a] are the graph's outputs only when nothing else uses them; split[a][b]...[a]... is an inner label
    outs = {n for n in ('v', 'a') if names.count(n) == 1}
    uses = {'0:v': sum(n in ('0:v', '0') for n in names), '0:a': sum(n == '0:a' for n in names)}
    if uses['0:a'] and cur_a is None:
        raise ValueError('this clip has no sound, so the graph cannot use [0:a]')
    feeds = {}
    for ref, cur, split in (('0:v', cur_v, 'split'), ('0:a', cur_a, 'asplit')):
        c = uses[ref]
        if c > 1 and cur not in ('[0:v]', '[0:a]'):
            labels = [f'[s{k}{ref[-1]}in{j}]' for j in range(c)]
            parts.append(f'{cur}{split}={c}{"".join(labels)}')
            feeds[ref] = iter(labels)
        else:
            feeds[ref] = iter([cur] * max(c, 1))

    def swap(m):
        n = m.group(1)
        if n in ('0:v', '0'):
            return next(feeds['0:v'])
        if n == '0:a':
            return next(feeds['0:a'])
        g = re.fullmatch(r'(\d+)(:[va])?', n)
        if g:
            return f'[{offset + int(g.group(1)) - 1}{g.group(2) or ""}]'
        if n in outs:
            return f'[s{k}{n}]'
        return f'[s{k}_{n}]'
    parts.append(_REF.sub(swap, text))
    if key == 'video' and 'v' not in outs:
        raise ValueError('an ffmpeg graph with [labels] ends its picture in [v] (and its sound, if it makes one, in [a])')
    if key == 'audio' and 'a' not in outs:
        raise ValueError('an ffmpeg audio graph with [labels] ends in [a]')
    new_v = f'[s{k}v]' if 'v' in outs else cur_v
    new_a = f'[s{k}a]' if 'a' in outs else (None if uses['0:a'] else cur_a)
    if 'v' in outs and not uses['0:v'] and cur_v not in ('[0:v]', None):
        parts.append(f'{cur_v}nullsink')
    return parts, new_v, new_a


def render_fx(recipe, width, height, fps, out_dir):
    """Render a clip's source range through its ffmpeg effects (recipe kind 'fx')."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    picture, sound = recipe.get('picture', True), recipe.get('sound', True)
    files = dict(recipe, inputs=[i for st in recipe['stages'] for i in st.get('inputs', [])])
    ext = '.mp4' if picture else '.wav'
    path = out_dir / f'fx-{_digest(files, width, height, fps)}{ext}'
    if path.exists():
        return {'path': str(path), 'cached': True, 'alpha': False}
    sp = float(recipe.get('speed', 1.0))
    dur = (recipe['out'] - recipe['in']) / sp
    rate = f'{fps:.6f}'.rstrip('0').rstrip('.')
    image = Path(recipe['clip']).suffix.lower() in IMAGE_EXT
    cmd = [ffmpeg_exe(), '-hide_banner', '-v', 'error', '-y']
    fixes = [st['fix'] for st in recipe['stages'] if 'fix' in st]
    fixed = {}
    if fixes:   # fix-in-post repairs of the source range (cached copies; the source file is only read)
        if image:
            raise ValueError('fix effects work on video and sound clips, not still images')
        import letitedit.review.fix_post as fix_post
        fixed = fix_post.chain(recipe['clip'], recipe['in'], recipe['out'], fixes, fps / sp, width, height)
    if image:
        cmd += ['-loop', '1', '-framerate', rate, '-t', f'{dur:.4f}', '-i', recipe['clip']]
    elif fixed.get('video'):
        cmd += ['-ss', f"{fixed['offset_video']:.4f}", '-t', f"{recipe['out'] - recipe['in']:.4f}", '-i', fixed['video']]
    else:
        cmd += ['-ss', f"{recipe['in']:.4f}", '-t', f"{recipe['out'] - recipe['in']:.4f}", '-i', recipe['clip']]
    stage_inputs = [i for st in recipe['stages'] for i in st.get('inputs', [])]
    for st in recipe['stages']:
        for i in st.get('inputs', []):
            if Path(i['clip']).suffix.lower() in IMAGE_EXT:
                cmd += ['-loop', '1', '-framerate', rate, '-t', f'{dur:.4f}', '-i', i['clip']]
            else:
                cmd += ['-ss', f"{i.get('in', 0):.4f}", '-t', f'{dur:.4f}', '-i', i['clip']]
    parts = []
    v = '[0:v]' if picture else None
    a = '[0:a]' if sound and not image else None
    if fixed.get('audio') and sound:      # the voice fix's sound, as the last input
        cmd += ['-ss', f"{fixed['offset_audio']:.4f}", '-t', f"{recipe['out'] - recipe['in']:.4f}", '-i', fixed['audio']]
        a = f'[{1 + len(stage_inputs)}:a]'
    if v:   # graphs see the clip at the project frame rate (and speed)
        parts.append(f"{v}{f'setpts=PTS/{sp:g},' if sp != 1.0 else ''}fps={rate}[sv]")
        v = '[sv]'
    if sp != 1.0:
        if a:
            parts.append(f"{a}{','.join(f'atempo={x:g}' for x in _atempo(sp))}[sa]")
            a = '[sa]'
    offset, fit = 1, 'none'
    for k, st in enumerate(recipe['stages']):
        if 'fix' in st:
            continue
        fit = st.get('fit', fit)
        for key in ('video', 'audio'):
            text = st.get(key)
            if text is False:
                if a and a != '[0:a]':
                    parts.append(f'{a}anullsink')
                a = None
                continue
            if not text:
                continue
            if key == 'video' and v is None:
                raise ValueError('this file has no picture for the ffmpeg video graph')
            p, v, a = _fx_text(text, k, v, a, offset, key)
            parts += p
        offset += len(st.get('inputs', []))
    maps = []
    if v:
        even = 'scale=trunc(iw/2)*2:trunc(ih/2)*2,' if fit == 'none' else ''
        parts.append(f'{v}{even}{_fit(width, height, fps, fit, False)}[vout]')
        maps += ['-map', '[vout]', '-c:v', 'libx264', '-crf', '15', '-preset', 'veryfast', '-pix_fmt', 'yuv420p']
    if a:
        parts.append(f'{a}aresample=48000[aout]')
        maps += ['-map', '[aout]'] + (['-c:a', 'aac', '-b:a', '256k'] if picture else ['-c:a', 'pcm_s16le'])
    if not maps:
        raise ValueError('the ffmpeg effect left nothing to play (no picture and no sound)')
    tmp = path.with_name(path.stem + '.tmp' + ext)
    try:
        r = subprocess.run([str(c) for c in cmd + ['-filter_complex', ';'.join(parts), *maps, '-t', f'{dur:.4f}',
                                                    *(['-movflags', '+faststart'] if picture else []), str(tmp)]],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=RENDER_TIMEOUT,
                           creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        if r.returncode != 0 or not tmp.exists():
            raise RuntimeError('ffmpeg effect failed: ' + r.stderr.strip()[-1500:] + '\n(filter graph: ' + ';'.join(parts) + ')')
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {'path': str(path), 'cached': False, 'alpha': False}


def _atempo(speed):
    """atempo takes 0.5-2 per stage."""
    out = []
    while speed > 2.0:
        out.append(2.0)
        speed /= 2.0
    while speed < 0.5:
        out.append(0.5)
        speed /= 0.5
    out.append(speed)
    return out
