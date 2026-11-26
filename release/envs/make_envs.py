r"""Pinned recipes for letitedit's model environments, made from the environments on the build PC.

    python -I make_envs.py [--root C:\LetItEdit] [--only name,name] [--no-sizes]

For every environment in ENVS below: the exact package list installed now (uv pip freeze) becomes
<name>\requirements-cuda.txt (and, when the environment has a CPU form, requirements-cpu.txt: the same list with the
CUDA builds of torch / torchaudio / torchvision replaced by the plain PyPI builds, which are CPU-only on Windows).
Download sizes come from a uv lock of each list for Windows / CPython 3.12 (the wheel each package would use; sizes
the package index does not give are asked from the server with a HEAD request). The installed size of the CUDA form
is measured on this PC; the CPU form's installed size is an estimate scaled from it. Everything goes into
envs.json, which env_build.py (bridge) reads. Nothing is installed or uploaded; only the package index is read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TORCH_INDEX = 'https://download.pytorch.org/whl/{}'
TORCH_PKGS = ('torch', 'torchaudio', 'torchvision')
CPU_DISK_PER_DOWNLOAD = 4.5      # bytes on disk per byte downloaded, CPU forms (measured on models, see below)

# name: where it is on the build PC, which tiers it runs on (CUDA on gpu8/gpu4, CPU form for cpu when 'cpu' is
# listed), what it is for, and the imports that prove it works.
ENVS = {
    'models': dict(path=r'envs\models', cuda='cu128', cpu=True, tiers=['gpu8', 'gpu4', 'cpu'],
                   features=['picture search and speakers (index jobs, letitedit_search, letitedit_speakers)',
                             'sound labels (letitedit_hear)', 'music / voice separation (letitedit_separate)',
                             'archive search (letitedit_archive)', 'fix-in-post models (letitedit_fix)',
                             'footage log by a local model (shot_log, gpu8)',
                             'official BiRefNet-lite portrait cut-out on CUDA'],
                   check=['torch', 'transformers', 'open_clip', 'speechbrain', 'demucs', 'nara_wpe', 'cv2',
                          'torchvision']),
    'voice': dict(path=r'envs\voice', cuda='cu124', cpu=True, tiers=['gpu8', 'gpu4', 'cpu'],
                  features=['voice (letitedit_voice engine chatterbox)'],
                  check=['torch', 'torchaudio', 'chatterbox']),
    'voice_dots': dict(path=r'envs\voice_dots', cuda='cu128', cpu=False, tiers=['gpu8'],
                       features=['voice (letitedit_voice engine dots-tts)'], check=['torch', 'dots_tts']),
    'music_acestep': dict(path=r'envs\music_acestep', cuda='cu128', cpu=False, tiers=['gpu8'],
                          features=['music made to fit (letitedit_music_make)'],
                          check=['torch', 'torchaudio', 'diffusers', 'transformers', 'vector_quantize_pytorch']),
    'whisper_gpu': dict(path=r'%APPDATA%\uv\tools\openai-whisper', cuda='cu132', cpu=False, tiers=['gpu8', 'gpu4'],
                        features=['speech to text on the GPU (letitedit_words and every transcript; the CPU engine is '
                                  'used without it)'],
                        check=['torch', 'whisper'], optional=True),
}
WHEEL_PREF = ('cp312-cp312-win_amd64', 'cp312-abi3-win_amd64', 'abi3-win_amd64', 'py3-none-win_amd64',
              'none-win_amd64', 'py3-none-any', 'none-any')


def uv_exe(root):
    for p in (os.environ.get('SHOTCUT_AI_UV'), root / 'release' / 'installer' / 'tools' / 'uv' / 'uv.exe'):
        if p and Path(p).is_file():
            return str(p)
    return 'uv'


def freeze(uv, py):
    r = subprocess.run([uv, 'pip', 'freeze', '--python', str(py)], capture_output=True, text=True, check=True,
                       env=dict(os.environ, UV_NO_CONFIG='1'))
    return [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith('#')]


def cpu_form(lines):
    out = []
    for l in lines:
        name = re.split(r'[=<>!~ ]', l, maxsplit=1)[0].lower()
        out.append(re.sub(r'\+cu\d+$', '', l) if name in TORCH_PKGS else l)
    return out


def folder_bytes(p):
    n = 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            try:
                n += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return n


def head_size(url):
    try:
        req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'ShotcutAI-make-envs/1'})
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get('Content-Length') or 0) or None
    except Exception:  # noqa: BLE001
        return None


def pick(pkg):
    wheels = pkg.get('wheels') or []
    for pref in WHEEL_PREF:
        for w in wheels:
            name = w['url'].rsplit('/', 1)[-1].split('#')[0]
            if name.endswith('.whl') and name[:-4].endswith(pref):
                return name, w
    for w in wheels:
        name = w['url'].rsplit('/', 1)[-1]
        if 'win_amd64' in name or 'none-any' in name:
            return name, w
    if pkg.get('sdist'):
        return pkg['sdist']['url'].rsplit('/', 1)[-1], dict(pkg['sdist'], sdist=True)
    return None, None


def sizes(uv, req_lines, index, tmp):
    """{'download_bytes', 'packages': n, 'from_source': [...], 'unknown': [...], 'largest': [[name, bytes], ...]}"""
    req = Path(tmp) / 'req.txt'
    req.write_text('\n'.join(req_lines) + '\n', encoding='utf-8')
    lock = Path(tmp) / 'pylock.envs.toml'
    cmd = [uv, 'pip', 'compile', str(req), '--no-deps', '--format', 'pylock.toml', '--python-version', '3.12',
           '--python-platform', 'x86_64-pc-windows-msvc', '-o', str(lock), '--quiet']
    if index:
        cmd += ['--extra-index-url', index, '--index-strategy', 'unsafe-best-match']
    r = subprocess.run(cmd, capture_output=True, text=True, env=dict(os.environ, UV_NO_CONFIG='1'))
    if r.returncode != 0:
        raise RuntimeError('uv pip compile failed: ' + r.stderr[-1500:])
    d = tomllib.loads(lock.read_text(encoding='utf-8'))
    total, src, unknown, rows = 0, [], [], []
    for pkg in d.get('packages', []):
        name, w = pick(pkg)
        if not w:
            unknown.append(pkg['name'])
            continue
        size = w.get('size') or head_size(w['url'])
        if w.get('sdist'):
            src.append(pkg['name'])
        if not size:
            unknown.append(pkg['name'])
            continue
        total += size
        rows.append([f"{pkg['name']}=={pkg['version']}", size])
    rows.sort(key=lambda x: -x[1])
    return {'download_bytes': total, 'packages': len(d.get('packages', [])), 'from_source': src, 'unknown': unknown,
            'largest': rows[:5]}


def human(n):
    for unit, k in (('GB', 1 << 30), ('MB', 1 << 20), ('KB', 1 << 10)):
        if n >= k:
            return f'{n / k:.1f} {unit}'
    return f'{n} bytes'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=str(HERE.parents[1]))
    ap.add_argument('--only', default='')
    ap.add_argument('--no-sizes', action='store_true')
    a = ap.parse_args()
    root = Path(a.root)
    uv = uv_exe(root)
    only = [x for x in a.only.split(',') if x]
    old = {}
    if (HERE / 'envs.json').is_file():
        old = json.loads((HERE / 'envs.json').read_text(encoding='utf-8')).get('envs', {})
    out = {}
    for name, spec in ENVS.items():
        if only and name not in only:
            if name in old:
                out[name] = old[name]
            continue
        folder = Path(os.path.expandvars(spec['path']))
        if not folder.is_absolute():
            folder = root / folder
        py = folder / 'Scripts' / 'python.exe'
        if not py.is_file():
            print(f'{name}: no environment at {folder}; kept the old record' if name in old else f'{name}: missing')
            if name in old:
                out[name] = old[name]
            continue
        ver = subprocess.run([str(py), '-I', '-c', 'import sys;print(sys.version.split()[0])'], capture_output=True,
                             text=True).stdout.strip()
        lines = freeze(uv, py)
        if name == 'models':
            # The build PC's manually made models env has CPU torchvision.
            # Fresh CUDA installs need its deformable-convolution CUDA operator.
            lines = ['torchvision==0.23.0+cu128' if l == 'torchvision==0.23.0' else l for l in lines]
        d = HERE / name
        d.mkdir(exist_ok=True)
        head = (f'# Shotcut AI environment "{name}" ({{form}}): the exact packages of {spec["path"]} on the build PC, '
                f'{time.strftime("%Y-%m-%d")}.\n# Python {ver}. Installed with --no-deps by bridge\\env_build.py.\n')
        variants = {'cuda': {'file': f'{name}/requirements-cuda.txt', 'index': TORCH_INDEX.format(spec['cuda'])}}
        (d / 'requirements-cuda.txt').write_text(head.format(form='CUDA ' + spec['cuda']) + '\n'.join(lines) + '\n',
                                                 encoding='utf-8')
        if spec['cpu']:
            (d / 'requirements-cpu.txt').write_text(head.format(form='CPU') + '\n'.join(cpu_form(lines)) + '\n',
                                                    encoding='utf-8')
            variants['cpu'] = {'file': f'{name}/requirements-cpu.txt', 'index': None}
        installed = folder_bytes(folder)
        variants['cuda']['installed_bytes'] = installed
        rec = {'python': ver, 'tiers': spec['tiers'], 'features': spec['features'], 'check': spec['check'],
               'optional': bool(spec.get('optional')), 'packages': len(lines), 'variants': variants,
               'made_from': spec['path'], 'made': time.strftime('%Y-%m-%d')}
        if not a.no_sizes:
            with tempfile.TemporaryDirectory() as tmp:
                for form, v in variants.items():
                    req = lines if form == 'cuda' else cpu_form(lines)
                    s = sizes(uv, req, v['index'], tmp)
                    v.update(s)
            cu = variants['cuda']
            if 'cpu' in variants and cu.get('download_bytes'):
                # measured 2026-10-20: the models CPU form (412 MB of wheels) took 1,853 MB once built and imported
                variants['cpu']['installed_bytes_estimate'] = int(variants['cpu']['download_bytes'] * CPU_DISK_PER_DOWNLOAD)
        out[name] = rec
        print(f"{name}: Python {ver}, {len(lines)} packages, installed {human(installed)}; " +
              '; '.join(f"{f} download {human(v.get('download_bytes') or 0)}"
                        + (f" (from source: {', '.join(v['from_source'])})" if v.get('from_source') else '')
                        + (f" (size unknown: {', '.join(v['unknown'])})" if v.get('unknown') else '')
                        for f, v in variants.items()))
    doc = {'format': 'shotcut-ai-envs/1', 'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'note': ('Each environment is built on first use (or from the setup window) by bridge\\env_build.py with uv: '
                    'Python <python> from python-build-standalone into <root>\\python, a venv in <root>\\envs\\<name>, '
                    'the listed packages with --no-deps (exactly the set on the build PC). Form cuda on gpu8/gpu4 '
                    'PCs (torch from the PyTorch CUDA index), cpu where listed on other PCs.'),
           'envs': out}
    (HERE / 'envs.json').write_text(json.dumps(doc, indent=1) + '\n', encoding='utf-8')
    print('->', HERE / 'envs.json')


if __name__ == '__main__':
    sys.exit(main())
