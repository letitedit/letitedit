"""Build the letitedit model manifest (models-manifest.json) from the SOURCE.md records.

    python -I make_manifest.py [--root C:\\LetItEdit] [--out models-manifest.json] [--check-hashes]

Every model / data download letitedit uses has a SOURCE.md next to its files (models\\*\\SOURCE.md,
models\\README.txt for whisper.cpp, vfx\\models\\SOURCE.md, maps\\naturalearth\\SOURCE.md). This script reads them:
origin URL, revision, licence, every file's size and hash. What a record does not say (which letitedit feature uses
the model, the hardware tier it suits from hardware.py, where it goes, how it is laid out on disk) comes from the
ENTRIES table below. A file whose record gives no SHA-256 (a git blob SHA-1 only, or nothing) gets the SHA-256 of
the copy on this PC, marked hash_source 'local copy' - the downloader checks every file by SHA-256 either way.

Writes the manifest and prints a check: each file's size against the copy on this PC (when present); with
--check-hashes also the SHA-256 of every local file up to 64 MB (bigger ones: size only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

HF = 'https://huggingface.co'

# id -> what the records cannot say. record: SOURCE.md path (relative to root). section: for a record with several
# repos, the '### <repo>' heading. dest: folder under the install root the files go to. layout: 'files' (as listed,
# relative to dest), 'hf-cache' (Hugging Face hub cache: dest/hub/models--org--name/snapshots/<rev>/<file> +
# refs/main), 'single' (one file listed in bullets). tiers: hardware.py tiers on which the feature runs it locally
# (gpu8 / gpu4 / cpu); env: the Python environment that runs it (None = bridge env or a program).
ENTRIES = [
    dict(id='qwen3.5-4b', record='models/hf/SOURCE.md', section='Qwen/Qwen3.5-4B', layout='hf-cache', dest='models/hf',
         title='Qwen3.5-4B vision model', features=['footage log written by a local model (shot_log)'],
         tiers=['gpu8'], env='models', note='On gpu4 and cpu PCs the footage log is written by the agent instead.'),
    dict(id='chatterbox', record='models/hf/SOURCE.md', section='ResembleAI/chatterbox', layout='hf-cache',
         dest='models/hf', title='Chatterbox voice', features=['voice (letitedit_voice, engine chatterbox, the default)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env='voice', note='GPU with ~4 GB; on the CPU it is much slower.'),
    dict(id='clip-vit-b-32', record='models/hf/SOURCE.md', section='laion/CLIP-ViT-B-32-laion2B-s34B-b79K',
         layout='hf-cache', dest='models/hf', title='CLIP ViT-B-32 picture search',
         features=['picture search in footage (index jobs, letitedit_search)'], tiers=['gpu8', 'gpu4', 'cpu'], env='models'),
    dict(id='clap-htsat-unfused', record='models/hf/SOURCE.md', section='laion/clap-htsat-unfused', layout='hf-cache',
         dest='models/hf', title='CLAP sound labels', features=['sound labels (letitedit_hear)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env='models'),
    dict(id='spkrec-ecapa-voxceleb', record='models/hf/SOURCE.md', section='speechbrain/spkrec-ecapa-voxceleb',
         layout='hf-cache', dest='models/hf', title='SpeechBrain speaker recognition',
         features=['who is speaking (letitedit_speakers)'], tiers=['gpu8', 'gpu4', 'cpu'], env='models'),
    dict(id='bge-small-en-v1.5', record='models/bge-small-en-v1.5/SOURCE.md', layout='files',
         dest='models/bge-small-en-v1.5', title='BAAI bge-small-en-v1.5 text embeddings',
         features=['archive search by meaning (letitedit_archive)'], tiers=['gpu8', 'gpu4', 'cpu'], env='models'),
    dict(id='ace-step-1.5', record='models/ace-step-1.5/SOURCE.md', layout='files', dest='models/ace-step-1.5',
         title='ACE-Step 1.5 music model', features=['music made to fit (letitedit_music_make)'], tiers=['gpu8'],
         env='music_acestep', requires=['ace-step-1.5-code']),
    dict(id='ace-step-1.5-code', record='models/ace-step-1.5-code/SOURCE.md', layout='single',
         dest='models/ace-step-1.5-code', title='ACE-Step 1.5 code', features=['music made to fit (letitedit_music_make)'],
         tiers=['gpu8'], env='music_acestep', extract=True,
         rename={'ca1e85fe9430179831e6bc6be790c332190a3866.zip': 'ACE-Step-1.5-ca1e85f.zip'}),
    dict(id='dots-tts-soar', record='models/dots-tts-soar/SOURCE.md', layout='files', dest='models/dots-tts-soar',
         title='dots.tts-soar voice', features=['voice (letitedit_voice, engine dots-tts)'], tiers=['gpu8'],
         env='voice_dots'),
    dict(id='deepfilternet', record='models/deepfilternet/SOURCE.md', layout='single', dest='models/deepfilternet',
         title='DeepFilterNet voice clean-up', features=['voice clean-up (letitedit_fix)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='ffmpeg-vidstab', record='models/ffmpeg-vidstab/SOURCE.md', layout='single', dest='models/ffmpeg-vidstab',
         title='FFmpeg 8.1 with vid.stab', features=['shake fix (letitedit_fix stabilise)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None, extract='extracted',
         # BtbN's 'latest' file is rebuilt every day: the manifest pins the dated autobuild of the same FFmpeg commit
         # (n8.1.3-18-g46d899d7a0, built 2026-10-19; size and SHA-256 from GitHub's release asset digest) and falls
         # back to 'latest', checked by size range + zip contents, when BtbN has removed the dated build.
         rename={'ffmpeg-n8.1-latest-win64-gpl-8.1.zip': 'ffmpeg-n8.1.3-18-g46d899d7a0-win64-gpl-8.1.zip'},
         file_overrides={'ffmpeg-n8.1.3-18-g46d899d7a0-win64-gpl-8.1.zip': dict(
             url='https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-19-13-06/'
                 'ffmpeg-n8.1.3-18-g46d899d7a0-win64-gpl-8.1.zip',
             bytes=193047496, sha256='5dc774c80fca5b63803ce052cbb1c7fc82aaccf3908b32e34f8842b367573c37',
             hash_source='GitHub release asset digest (autobuild-2026-10-19-13-06)',
             accept_existing=['ffmpeg-n8.1-latest-win64-gpl-8.1.zip'],
             fallback_urls=['https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/'
                            'ffmpeg-n8.1-latest-win64-gpl-8.1.zip'],
             check=dict(rule='rolling', bytes_min=150 << 20, bytes_max=260 << 20, format='zip',
                        zip_has=['*/bin/ffmpeg.exe', '*/bin/ffprobe.exe'],
                        why="BtbN rebuilds 'latest' daily and removes dated builds after some weeks"))}),
    dict(id='geonames', record='models/geo/SOURCE.md', layout='files', dest='models/geo', title='GeoNames world places',
         features=['place names from GPS (letitedit_places, footage place: line)'], tiers=['gpu8', 'gpu4', 'cpu'],
         env=None, url_base='https://download.geonames.org/export/dump/',
         # GeoNames regenerates these files every day and keeps no dated copies: the SHA-256 is of the copy on the
         # build PC; a newer file is accepted by size range + format (tab-separated rows), never by hash.
         file_overrides={
             'cities1000.zip': dict(check=dict(rule='rolling', first_url_rolling=True, bytes_min=8 << 20,
                                               bytes_max=16 << 20, format='zip', zip_has=['cities1000.txt'],
                                               tsv_member='cities1000.txt', tsv_fields=19, min_rows=200,
                                               why='GeoNames regenerates the dump daily; no dated copies')),
             'admin1CodesASCII.txt': dict(check=dict(rule='rolling', first_url_rolling=True, bytes_min=100_000,
                                                     bytes_max=300_000, format='tsv', tsv_fields=4, min_rows=200,
                                                     why='GeoNames regenerates the dump daily; no dated copies')),
             'countryInfo.txt': dict(check=dict(rule='rolling', first_url_rolling=True, bytes_min=20_000,
                                                bytes_max=60_000, format='tsv', tsv_fields=16, min_rows=200,
                                                why='GeoNames regenerates the dump daily; no dated copies'))}),
    dict(id='realesrgan', record='models/realesrgan/SOURCE.md', layout='single', dest='models/realesrgan',
         title='Real-ESRGAN upscalers', features=['sharper punch-ins (letitedit_fix)'], tiers=['gpu8', 'gpu4'],
         env='models', note='Runs on the CPU too, very slowly.'),
    dict(id='scunet', record='models/scunet/SOURCE.md', layout='single', dest='models/scunet',
         title='SCUNet denoiser', features=['night / noise fix (letitedit_fix)'], tiers=['gpu8', 'gpu4'], env='models',
         note='Needs ~3.1 GB of GPU memory; on the CPU very slow.'),
    dict(id='htdemucs', record='models/torch/SOURCE.md', files=['hub/checkpoints/955717e8-8726e21a.th'], layout='files', dest='models/torch',
         title='Demucs htdemucs stems', features=['music / voice separation (letitedit_separate)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env='models'),
    dict(id='dbs-tiger-dnr', record='models/dbs-tiger/SOURCE.md', layout='files', dest='models/dbs-tiger',
         title='DBS-TIGER-DnR film-sound separation (dialogue, music, effects)',
         features=["Learn's sound-effect devices (an importer setting, off by default)"],
         tiers=['gpu8', 'gpu4', 'cpu'], env='models', note='Only when the sound-device setting is on.'),
    dict(id='panns-cnn14-sed', record='models/panns/SOURCE.md', files=['Cnn14_DecisionLevelMax_mAP=0.385.pth'],
         layout='files', dest='models/panns', title='PANNs Cnn14 sound events (AudioSet)',
         features=["Learn's sound-effect devices (an importer setting, off by default)"],
         tiers=['gpu8', 'gpu4', 'cpu'], env='models', note='Only when the sound-device setting is on.'),
    dict(id='faster-whisper-tiny-en', record='release/installer/records/review-speech-SOURCE.md',
         section='Systran/faster-whisper-tiny.en', layout='hf-cache', dest='models/hf',
         title='Fast Review spoken notes (Whisper tiny.en, English)',
         features=['local spoken Review notes'], tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='faster-whisper-medium-en', record='models/hf/SOURCE.md', section='Systran/faster-whisper-medium.en', layout='hf-cache',
         dest='models/hf', title='Speech on the processor (faster-whisper medium.en, English only)',
         features=['what is said, on a PC with no suitable graphics card (letitedit_words, captions, first cuts)'],
         tiers=['gpu4', 'cpu'], env=None),
    dict(id='whisper-large-v3-turbo', record='release/installer/records/whisper-large-v3-turbo-SOURCE.md', files=['large-v3-turbo.pt'], layout='files',
         dest='models/whisper', title='Better speech model (Whisper large-v3-turbo, any language)',
         features=['what is said, on the graphics card (letitedit_words, captions, first cuts)'], tiers=['gpu8', 'gpu4'], env='whisper_gpu'),
    dict(id='whisper-cpp-base-en', record='models/README.txt', layout='single', dest='models',
         title='whisper.cpp base.en', features=['speech to text inside the editor and push-to-talk'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='kokoro-v1.0', record='vfx/models/SOURCE.md', files=['kokoro-v1.0.onnx', 'voices-v1.0.bin'], layout='files',
         dest='vfx/models', title='Kokoro voice (ONNX)', features=['dub voice (creator dub)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='birefnet-lite', record='vfx/models/SOURCE.md', files=['birefnet_lite.onnx'], layout='files',
         dest='vfx/models', title='BiRefNet-lite cut-outs', features=['cut-outs (callouts)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='birefnet-lite-official', record='vfx/BIREFNET-LITE-SOURCE.md', layout='files',
         dest='vfx/models/birefnet-lite-official', title='Official BiRefNet-lite portrait matte',
         features=['person cut-out (backdrop, cutout, text behind, clone, VFX analysis)'],
         tiers=['gpu8', 'gpu4'], env='models'),
    dict(id='sam2-hiera-tiny', record='vfx/SAM2-TINY-SOURCE.md', layout='files',
         dest='vfx/models/sam2-hiera-tiny', title='SAM 2 Tiny object follower',
         features=['object layers (letitedit_object)'], tiers=['gpu8', 'gpu4'], env='models'),
    dict(id='lama', record='vfx/models/SOURCE.md', files=['lama_fp32.onnx'], layout='files', dest='vfx/models',
         title='LaMa object removal', features=['object removal (tracking)'], tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='skyseg', record='vfx/models/SOURCE.md', files=['skyseg.onnx'], layout='files', dest='vfx/models',
         title='Sky segmentation', features=['sky replacement (sky)'], tiers=['gpu8', 'gpu4', 'cpu'], env=None,
         note='Origin not fully confirmed (see its SOURCE.md).'),
    dict(id='modnet', record='vfx/models/SOURCE.md', files=['modnet.onnx'], layout='files', dest='vfx/models',
         title='MODNet person matte', features=['person matte (VFX beta)'], tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='depth-anything-v2-small', record='vfx/models/SOURCE.md', files=['depth_anything_v2_small.onnx'],
         layout='files', dest='vfx/models', title='Depth Anything V2 Small', features=['depth (VFX beta)'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='opencv-zoo-faces-tracking', record='vfx/models/SOURCE.md',
         files=['yunet_2023mar.onnx', 'face_recognition_sface_2021dec.onnx', 'vittrack_2023sep.onnx'], layout='files',
         dest='vfx/models', title='OpenCV Zoo YuNet / SFace / VitTrack',
         features=['faces in frame checks (letitedit_check_frames), face matching, object tracking'],
         tiers=['gpu8', 'gpu4', 'cpu'], env=None),
    dict(id='natural-earth', record='maps/naturalearth/SOURCE.md', layout='local-listing', dest='maps/naturalearth',
         title='Natural Earth maps data', features=['maps (letitedit_map)'], tiers=['gpu8', 'gpu4', 'cpu'], env=None,
         url_base='https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/',
         url_overrides={'LICENSE.md': 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/LICENSE.md',
                        'raster_sr_lr/SR_LR.zip': 'https://naciscdn.org/naturalearth/10m/raster/SR_LR.zip'},
         extract_members={'raster_sr_lr/SR_LR.zip': 'raster_sr_lr'}),
]

SHA256 = re.compile(r'\b[0-9a-f]{64}\b', re.I)
SHA1 = re.compile(r'\b[0-9a-f]{40}\b', re.I)
URL = re.compile(r'https?://[^\s)>\]|,]+')


def sha256_file(p, block=1 << 22):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(block), b''):
            h.update(b)
    return h.hexdigest()


def sections(text):
    """[(heading, lines)] split at markdown headings (the text before the first heading has heading '')."""
    out, head, cur = [], '', []
    for line in text.splitlines():
        if line.startswith('#'):
            out.append((head, cur))
            head, cur = line.lstrip('#').strip(), []
        else:
            cur.append(line)
    out.append((head, cur))
    return out


def bullets(lines):
    """{key lower: value} from '- Key: value' lines (first wins)."""
    d = {}
    last = None
    for line in lines:
        m = re.match(r'\s*(?:-\s*)?([A-Za-z][A-Za-z ()-]{1,40}?):\s*(.+)$', line)
        if m and not line.startswith('  '):
            key = m.group(1).strip().lower()
            last = key if key not in d else None
            d.setdefault(key, m.group(2).strip())
        elif last and line.startswith('  ') and not line.strip().startswith('-') and line.strip():
            d[last] += ' ' + line.strip()   # a wrapped bullet
        else:
            last = None
    return d


def tables(lines):
    """[[{col: cell}]] markdown tables."""
    out, i = [], 0
    while i < len(lines):
        if lines[i].strip().startswith('|') and i + 1 < len(lines) and re.match(r'\s*\|[\s:|-]+\|\s*$', lines[i + 1]):
            head = [c.strip().lower() for c in lines[i].strip().strip('|').split('|')]
            rows, i = [], i + 2
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                rows.append(dict(zip(head, cells)))
                i += 1
            out.append(rows)
        else:
            i += 1
    return out


def col(row, *names):
    for k, v in row.items():
        if any(n in k for n in names):
            return v
    return None


def table_files(rows):
    files = []
    for r in rows:
        name = col(r, 'file')
        if not name:
            continue
        name = name.strip('`')
        b = col(r, 'bytes')
        nbytes = int(re.sub(r'[^\d]', '', b)) if b and re.search(r'\d', b) else None
        hash_cell = ' '.join(v for k, v in r.items() if 'sha' in k or 'hash' in k)
        f = {'path': name, 'bytes': nbytes}
        m = SHA256.search(hash_cell)
        if m:
            f['sha256'] = m.group(0).lower()
            f['hash_source'] = 'record'
        else:
            m1 = SHA1.search(hash_cell)
            if m1:
                f['git_blob_sha1'] = m1.group(0).lower()
        url = col(r, 'url', 'upstream')
        if url:
            u = URL.search(url)
            if u:
                f['url'] = u.group(0)
        rev = col(r, 'revision')
        if rev:
            f['revision'] = rev.split()[0]
        lic = col(r, 'licen')
        if lic:
            f['licence'] = lic
        files.append(f)
    return files


def bullet_downloads(lines):
    """Downloads written as a URL line followed by 'size N bytes; sha256 H' (same or next two lines)."""
    out = []
    for i, line in enumerate(lines):
        for u in URL.findall(line):
            name = u.rstrip('/').rsplit('/', 1)[-1]
            if not re.search(r'\.(pth|th|exe|zip|bin|onnx|safetensors|tar\.gz|tgz)$', name, re.I):
                continue
            window = ' '.join(lines[i:i + 3])
            mb = re.search(r'([\d,]{4,})\s*bytes', window)
            mh = SHA256.search(window)
            if mb and mh:
                out.append({'path': name, 'url': u, 'bytes': int(mb.group(1).replace(',', '')),
                            'sha256': mh.group(0).lower(), 'hash_source': 'record'})
    return out


def whisper_readme(text):
    d = {}
    for line in text.splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            d[k.strip().lower()] = v.strip()
    url = d.get('download')
    return {'origin': d.get('source'), 'licence': 'MIT (whisper.cpp / OpenAI Whisper weights)',
            'files': [{'path': url.rsplit('/', 1)[-1], 'url': url, 'bytes': int(re.sub(r'[^\d]', '', d['size'])),
                       'sha256': d['sha256'].lower(), 'hash_source': 'record'}]}


def licence_of(b):
    for k in ('licence', 'license'):
        if k in b:
            return b[k]
    return None


def build_entry(spec, root, check_hashes, report):
    rec_path = root / spec['record']
    text = rec_path.read_text(encoding='utf-8-sig')
    e = {k: spec[k] for k in ('id', 'title', 'features', 'tiers', 'env', 'dest', 'layout') if k in spec}
    for k in ('note', 'requires'):
        if k in spec:
            e[k] = spec[k]
    e['record'] = spec['record'].replace('/', '\\')
    secs = sections(text)
    doc_b = {}
    for _, lines in secs:
        for k, v in bullets(lines).items():
            doc_b.setdefault(k, v)
    if spec['record'].endswith('README.txt'):
        w = whisper_readme(text)
        e.update(origin=w['origin'], licence=w['licence'], files=w['files'])
    elif spec['layout'] == 'hf-cache':
        repo = spec['section']
        head, lines = next((h, l) for h, l in secs if h.startswith(repo + ' ') or h == repo)
        rev = re.search(r'revision\s+([0-9a-f]{40})', head).group(1)
        files = table_files(tables(lines)[0])
        lic_row = next(r for t in tables(sum((l for _, l in secs), [])) for r in t if col(r, 'repo') == repo)
        e.update(repo=repo, revision=rev, origin=f'{HF}/{repo}', licence=col(lic_row, 'licen'))
        for f in files:
            f['url'] = f'{HF}/{repo}/resolve/{rev}/{f["path"]}'
        e['files'] = files
    elif spec['layout'] == 'local-listing':
        folder = rec_path.parent
        e.update(origin=URL.search(doc_b.get('url', '')).group(0), licence=licence_of(doc_b), version=doc_b.get('version'))
        files = []
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or p.name == 'SOURCE.md':
                continue
            rel = p.relative_to(folder).as_posix()
            if any(rel.startswith(m + '/') and rel != z for z, m in spec.get('extract_members', {}).items()):
                continue  # extracted from a zip below
            url = spec.get('url_overrides', {}).get(rel) or spec['url_base'] + rel
            f = {'path': rel, 'url': url, 'bytes': p.stat().st_size, 'sha256': sha256_file(p), 'hash_source': 'local copy'}
            if rel in spec.get('extract_members', {}):
                into = spec['extract_members'][rel]
                f['extract_to'] = into
                f['members'] = [{'path': q.relative_to(folder / into).as_posix(), 'bytes': q.stat().st_size,
                                 'sha256': sha256_file(q)} for q in sorted((folder / into).rglob('*'))
                                if q.is_file() and q.name != p.name]
            files.append(f)
        e['files'] = files
    else:
        all_lines = sum((l for _, l in secs), [])
        files = []
        for t in tables(all_lines):
            files += table_files(t)
        if spec.get('files'):
            files = [f for f in files if f['path'] in spec['files']]
        if spec['layout'] == 'single' or not files:
            files = bullet_downloads(all_lines) or files
        src = doc_b.get('source') or doc_b.get('url')
        origin = URL.search(src).group(0) if src and URL.search(src) else None
        rev = doc_b.get('revision') or doc_b.get('revision (commit)')
        if rev:
            rev = rev.split()[0]
            e['revision'] = rev
        if spec.get('files'):  # vfx table: per-file origin, revision, licence
            origin = files[0].get('url')
            e['licence'] = files[0].get('licence')
            for f in files:
                u = f.get('url', '')
                if f.get('revision') and '/resolve/main/' in u:
                    f['url'] = u.replace('/resolve/main/', f'/resolve/{f["revision"]}/')
                elif f.get('revision') and 'github.com/opencv/opencv_zoo/raw/main/' in u:
                    f['url'] = u.replace('/raw/main/', f'/raw/{f["revision"]}/')
        else:
            e['licence'] = licence_of(doc_b) or next((f['licence'] for f in files if f.get('licence')), None)
        if origin is None and files:
            origin = files[0].get('url')
        e['origin'] = origin
        for f in files:
            if 'url' not in f:
                if spec.get('url_base'):
                    f['url'] = spec['url_base'] + f['path']
                elif origin and origin.startswith(HF) and rev:
                    f['url'] = f'{origin}/resolve/{rev}/{f["path"]}'
        if spec.get('extract'):
            for f in files:
                if f['path'].lower().endswith('.zip'):
                    f['extract_to'] = spec['extract'] if isinstance(spec['extract'], str) else '.'
        e['files'] = files
    seen, files = set(), []
    for f in e['files']:
        f['path'] = spec.get('rename', {}).get(f['path'], f['path'])
        if f['path'] in seen:        # a record naming the pinned download as well as the original
            continue
        seen.add(f['path'])
        f.update(spec.get('file_overrides', {}).get(f['path'], {}))
        files.append(f)
    e['files'] = files
    # local check and hashes the record lacks
    dest_local = local_dest(root, e)
    for f in e['files']:
        lp = next((dest_local / n for n in [f['path']] + f.get('accept_existing', []) if (dest_local / n).is_file()),
                  dest_local / f['path'])
        if lp.is_file() and lp.name != f['path'].rsplit('/', 1)[-1]:
            pass        # an older copy accepted under its own name (rolling file): nothing to compare
        elif lp.is_file():
            size = lp.stat().st_size
            if f.get('bytes') is None:
                f['bytes'] = size
            if size != f['bytes']:
                report.append(f"{e['id']}: {f['path']} size {size} on this PC, record says {f['bytes']}")
            if 'sha256' not in f:
                f['sha256'] = sha256_file(lp)
                f['hash_source'] = 'local copy'
            elif check_hashes and size <= 64 << 20 and sha256_file(lp) != f['sha256']:
                report.append(f"{e['id']}: {f['path']} SHA-256 differs from the record")
        elif 'sha256' not in f:
            report.append(f"{e['id']}: {f['path']} has no SHA-256 and no local copy")
        if not f.get('url'):
            report.append(f"{e['id']}: {f['path']} has no URL")
    e['size_bytes'] = sum(f.get('bytes') or 0 for f in e['files'])
    e['size_text'] = human(e['size_bytes'])
    return e


def local_dest(root, e):
    if e['layout'] == 'hf-cache':
        return root / e['dest'] / 'hub' / ('models--' + e['repo'].replace('/', '--')) / 'snapshots' / e['revision']
    return root / e['dest']


def human(n):
    for unit, k in (('GB', 1 << 30), ('MB', 1 << 20), ('KB', 1 << 10)):
        if n >= k:
            return f'{n / k:.1f} {unit}'
    return f'{n} bytes'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument('--out', default=str(Path(__file__).resolve().parent / 'models-manifest.json'))
    ap.add_argument('--check-hashes', action='store_true')
    a = ap.parse_args()
    root = Path(a.root)
    report, entries = [], []
    for spec in ENTRIES:
        try:
            entries.append(build_entry(spec, root, a.check_hashes, report))
        except Exception as ex:  # noqa: BLE001 - report and go on
            report.append(f"{spec['id']}: could not read {spec['record']}: {type(ex).__name__}: {ex}")
    manifest = {
        'format': 'letitedit-models/1',
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'generated_from': sorted({s['record'].replace('/', '\\') for s in ENTRIES}),
        'tiers': {'gpu8': 'NVIDIA GPU with 7600 MB or more', 'gpu4': 'NVIDIA GPU with 3800 MB or more',
                  'cpu': 'no NVIDIA GPU (or a smaller one)', 'source': 'bridge\\hardware.py tier()'},
        'envs_note': ('env names the Python environment that runs the model (<root>\\envs\\<env>, built on first use '
                      'by bridge\\env_build.py from setup\\envs\\envs.json). None = the bridge or a program.'),
        'models': entries,
    }
    Path(a.out).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    tot = sum(e['size_bytes'] for e in entries)
    print(f'{len(entries)} models, {sum(len(e["files"]) for e in entries)} files, {human(tot)} -> {a.out}')
    for e in entries:
        print(f"  {e['id']:<28} {e['size_text']:>9}  {','.join(e['tiers']):<14} {e.get('licence') or '?'}"[:150])
    if report:
        print('CHECK:')
        for r in report:
            print('  ' + r)
    return 1 if report else 0


if __name__ == '__main__':
    sys.exit(main())
