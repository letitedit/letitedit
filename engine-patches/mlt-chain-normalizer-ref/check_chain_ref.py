"""Does an engine (libmlt-7.dll) free a clip's normalizer links when the clip closes? (mlt-chain-normalizer-ref)

    python check_chain_ref.py [--dll <libmlt-7.dll>] [--app C:\\LetItEdit\\app] [--media <video>] [--json]

In a child process with only that engine loaded (the modules from <app>\\lib\\mlt), it makes a clip the way Shotcut
and the XML loader do (a chain with its source and the normalizer links), draws three frames, closes it, five times,
and counts the process's handles after each close. A chain without links is measured the same way for comparison.
Every MLT property owns a Windows event, so a link that outlives its chain shows as about 40 handles.

Exit code 0 when a closed clip with normalizers keeps no more handles than one without (within 3 per clip);
1 when it keeps more (the stock 7.41.0 engine keeps about 377 per clip); 2 when the probe can't run.
No renders; about 5 seconds. When --media is missing (a PC without test-footage), a 3-second test clip with sound is
made with the app's own ffmpeg.exe in a temporary folder (make_clip). check_engine.py runs this check as `chain_ref`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOLERANCE = 3   # handles per clip per cycle


def probe(dll, app, media, variant, cycles):
    """runs in the child: handles after each close"""
    os.add_dll_directory(str(app))
    ctypes.windll.kernel32.SetDllDirectoryW(str(app))
    mlt = ctypes.CDLL(str(dll))   # loaded first, so the modules link to this one
    k32 = ctypes.WinDLL('kernel32')
    V = ctypes.c_void_p
    for name, res, args in [('mlt_factory_init', V, [ctypes.c_char_p]), ('mlt_profile_init', V, [ctypes.c_char_p]),
                            ('mlt_factory_producer', V, [V, ctypes.c_char_p, V]),
                            ('mlt_chain_init', V, [V]), ('mlt_chain_set_source', None, [V, V]),
                            ('mlt_chain_attach_normalizers', None, [V]), ('mlt_chain_link_count', ctypes.c_int, [V]),
                            ('mlt_chain_close', None, [V]), ('mlt_producer_close', None, [V]),
                            ('mlt_service_get_frame', ctypes.c_int, [V, ctypes.POINTER(V), ctypes.c_int]),
                            ('mlt_frame_get_image', ctypes.c_int,
                             [V, ctypes.POINTER(V), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_int), ctypes.c_int]),
                            ('mlt_frame_close', None, [V]), ('mlt_producer_seek', ctypes.c_int, [V, ctypes.c_int])]:
        f = getattr(mlt, name)
        f.restype, f.argtypes = res, args

    def handles():
        n = ctypes.c_ulong()
        k32.GetProcessHandleCount(ctypes.c_void_p(-1), ctypes.byref(n))
        return n.value

    mlt.mlt_factory_init(os.environ['MLT_REPOSITORY'].encode())
    profile = mlt.mlt_profile_init(None)
    counts, links = [], 0
    for _ in range(cycles):
        src = mlt.mlt_factory_producer(profile, b'avformat-novalidate', str(media).encode())
        if not src:
            raise SystemExit(f'the engine could not open {media}')
        chain = mlt.mlt_chain_init(profile)
        mlt.mlt_chain_set_source(chain, src)
        mlt.mlt_producer_close(src)
        if variant == 'normalized':
            mlt.mlt_chain_attach_normalizers(chain)
        links = mlt.mlt_chain_link_count(chain)
        for i in range(3):
            mlt.mlt_producer_seek(chain, 30 + i * 10)
            frame, img = V(), V()
            fmt, w, h = ctypes.c_int(1), ctypes.c_int(320), ctypes.c_int(180)
            mlt.mlt_service_get_frame(chain, ctypes.byref(frame), 0)
            mlt.mlt_frame_get_image(frame, ctypes.byref(img), ctypes.byref(fmt), ctypes.byref(w), ctypes.byref(h), 0)
            mlt.mlt_frame_close(frame)
        mlt.mlt_chain_close(chain)
        counts.append(handles())
    return {'variant': variant, 'links': links, 'after_close': counts}


def make_clip(app, folder):
    """A 3-second 640x360 30 fps test clip with a tone (H.264 + AAC), made by the app's ffmpeg.exe; returns its path."""
    out = Path(folder) / 'chain-ref-clip.mp4'
    if not out.exists():
        r = subprocess.run([str(Path(app) / 'ffmpeg.exe'), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=size=640x360:rate=30:duration=3', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=48000:duration=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-shortest', str(out)], capture_output=True, text=True, timeout=120,
                           creationflags=0x08000000)
        if r.returncode or not out.exists():
            raise RuntimeError(f'could not make a test clip with {Path(app) / 'ffmpeg.exe'}: {r.stderr[-300:]}')
    return out


def check(dll, app, media=None, workdir=None):
    """The whole check: {'dll', 'links', 'kept_per_clip_bare', 'kept_per_clip_normalized', 'pass', 'media'}.
    Raises when the probe can't run."""
    media = Path(media) if media else None
    if (not media or not media.exists()) and not workdir:
        with tempfile.TemporaryDirectory(prefix='chain-ref-') as tmp:
            return check(dll, app, None, tmp)
    if not media or not media.exists():
        media = make_clip(app, workdir)
    bare = measure(dll, app, media, 'bare')
    norm = measure(dll, app, media, 'normalized')
    extra = norm['kept_per_clip'] - bare['kept_per_clip']
    ok = norm['links'] > 0 and extra <= TOLERANCE
    return {'dll': str(dll), 'links': norm['links'], 'kept_per_clip_bare': bare['kept_per_clip'],
            'kept_per_clip_normalized': norm['kept_per_clip'], 'pass': ok, 'media': str(media)}


def measure(dll, app, media, variant, cycles=5):
    env = dict(os.environ, MLT_REPOSITORY=str(app / 'lib' / 'mlt'), MLT_DATA=str(app / 'share' / 'mlt'),
               MLT_PROFILES_PATH=str(app / 'share' / 'mlt' / 'profiles'),
               PATH=str(app) + os.pathsep + os.environ.get('PATH', ''))
    r = subprocess.run([sys.executable, __file__, '--child', variant, '--dll', str(dll), '--app', str(app),
                        '--media', str(media), '--cycles', str(cycles)], env=env, capture_output=True, text=True,
                       timeout=120, creationflags=0x08000000)
    line = [x for x in r.stdout.splitlines() if x.startswith('{')]
    if r.returncode or not line:
        raise RuntimeError(f'probe failed ({r.returncode}): {r.stdout[-300:]} {r.stderr[-300:]}')
    out = json.loads(line[-1])
    c = out['after_close']
    out['kept_per_clip'] = (c[-1] - c[1]) / max(1, len(c) - 2)   # the first cycle loads the engine's own caches
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--app', default=str(ROOT / 'app'))
    ap.add_argument('--dll', help="the libmlt-7.dll to check (default: the app's own)")
    ap.add_argument('--media', default=str(ROOT / 'test-footage' / 'quick' / 'talk-60s.mp4'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--child')
    ap.add_argument('--cycles', type=int, default=5)
    a = ap.parse_args(argv)
    app = Path(a.app)
    dll = Path(a.dll) if a.dll else app / 'libmlt-7.dll'
    if a.child:
        print(json.dumps(probe(dll, app, Path(a.media), a.child, a.cycles)), flush=True)
        return 0
    try:
        result = check(dll, app, a.media)
    except Exception as e:  # noqa: BLE001
        print('could not run:', e)
        return 2
    ok = result['pass']
    if a.json:
        print(json.dumps(result))
    else:
        print(f"{dll}: a closed clip with {result['links']} normalizer links keeps "
              f"{result['kept_per_clip_normalized']:.0f} handles, one without links "
              f"{result['kept_per_clip_bare']:.0f}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
