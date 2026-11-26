"""Does an engine (libmlt-7.dll) free a clip's decoder when a frame outlives a cache eviction? (mlt-cache-held-item)

    python check_cache_ref.py [--dll <libmlt-7.dll>] [--app C:\\LetItEdit\\app] [--media <video>] [--json]

In a child process with only that engine loaded (the modules from <app>\\lib\\mlt), with the avformat cache at 4
decoders, it repeats five times: a clip draws a frame that is kept (as the player keeps the frame it shows), six other
clips open and close (so the clip's decoder is pushed out of the cache, as the bridge's snapshot or a timeline rebuild
does), the clip draws again (a new decoder), then the clip closes and the kept frame is released. It counts the
process's threads at the start and the end. The same run without the eviction is the comparison.

Exit code 0 when the threads come back (within 2); 1 when they don't (the stock 7.41.0 engine keeps one decoder per
cycle: about 17 threads for an H.264 clip); 2 when the probe can't run. No renders; about 5 seconds. When --media is
missing, the 3-second test clip of check_chain_ref.py is made. check_engine.py runs this check as `cache_ref`.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOLERANCE = 2   # threads over the whole run


def probe(dll, app, media, variant, cycles):
    """runs in the child: threads at the start and after each cycle"""
    os.add_dll_directory(str(app))
    ctypes.windll.kernel32.SetDllDirectoryW(str(app))
    mlt = ctypes.CDLL(str(dll))   # loaded first, so the modules link to this one
    k32 = ctypes.WinDLL('kernel32')
    V = ctypes.c_void_p
    for name, res, args in [('mlt_factory_init', V, [ctypes.c_char_p]), ('mlt_profile_init', V, [ctypes.c_char_p]),
                            ('mlt_factory_producer', V, [V, ctypes.c_char_p, V]),
                            ('mlt_service_get_frame', ctypes.c_int, [V, ctypes.POINTER(V), ctypes.c_int]),
                            ('mlt_frame_get_image', ctypes.c_int,
                             [V, ctypes.POINTER(V), ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                              ctypes.POINTER(ctypes.c_int), ctypes.c_int]),
                            ('mlt_frame_close', None, [V]), ('mlt_producer_close', None, [V]),
                            ('mlt_producer_seek', ctypes.c_int, [V, ctypes.c_int]),
                            ('mlt_service_cache_set_size', None, [V, ctypes.c_char_p, ctypes.c_int])]:
        f = getattr(mlt, name)
        f.restype, f.argtypes = res, args

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ThreadID', wt.DWORD),
                    ('th32OwnerProcessID', wt.DWORD), ('tpBasePri', wt.LONG), ('tpDeltaPri', wt.LONG),
                    ('dwFlags', wt.DWORD)]

    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE

    def threads():
        snap = k32.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        e = THREADENTRY32()
        e.dwSize = ctypes.sizeof(e)
        n, ok = 0, k32.Thread32First(snap, ctypes.byref(e))
        while ok:
            n += e.th32OwnerProcessID == os.getpid()
            ok = k32.Thread32Next(snap, ctypes.byref(e))
        k32.CloseHandle(snap)
        return n

    def frame_at(producer, position):
        mlt.mlt_producer_seek(producer, position)
        frame, img = V(), V()
        fmt, w, h = ctypes.c_int(1), ctypes.c_int(320), ctypes.c_int(180)
        mlt.mlt_service_get_frame(producer, ctypes.byref(frame), 0)
        mlt.mlt_frame_get_image(frame, ctypes.byref(img), ctypes.byref(fmt), ctypes.byref(w), ctypes.byref(h), 0)
        return frame, bool(img.value)

    mlt.mlt_factory_init(os.environ['MLT_REPOSITORY'].encode())
    profile = mlt.mlt_profile_init(None)
    mlt.mlt_service_cache_set_size(None, b'producer_avformat', 4)
    counts, drawn = [threads()], True
    for _ in range(cycles):
        clip = mlt.mlt_factory_producer(profile, b'avformat-novalidate', str(media).encode())
        if not clip:
            raise SystemExit(f'the engine could not open {media}')
        shown, ok1 = frame_at(clip, 30)
        if variant == 'evict':
            for other in [mlt.mlt_factory_producer(profile, b'avformat-novalidate', str(media).encode())
                          for _ in range(6)]:
                mlt.mlt_producer_close(other)
        again, ok2 = frame_at(clip, 0)
        drawn = drawn and ok1 and ok2
        mlt.mlt_frame_close(again)
        mlt.mlt_producer_close(clip)
        mlt.mlt_frame_close(shown)
        counts.append(threads())
    return {'variant': variant, 'threads': counts, 'drawn': drawn}


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
    out['kept'] = out['threads'][-1] - out['threads'][0]
    return out


def _make_clip(app, folder):
    path = Path(__file__).resolve().parent.parent / 'mlt-chain-normalizer-ref' / 'check_chain_ref.py'
    spec = importlib.util.spec_from_file_location('check_chain_ref', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.make_clip(app, folder)


def check(dll, app, media=None, workdir=None):
    """The whole check: {'dll', 'threads_kept_evicted', 'threads_kept_plain', 'drawn', 'pass', 'media'}.
    Raises when the probe can't run."""
    media = Path(media) if media else None
    if (not media or not media.exists()) and not workdir:
        with tempfile.TemporaryDirectory(prefix='cache-ref-') as tmp:
            return check(dll, app, None, tmp)
    if not media or not media.exists():
        media = _make_clip(app, workdir)
    plain = measure(dll, app, media, 'plain')
    evict = measure(dll, app, media, 'evict')
    ok = evict['drawn'] and plain['drawn'] and evict['kept'] <= TOLERANCE and plain['kept'] <= TOLERANCE
    return {'dll': str(dll), 'threads_kept_evicted': evict['kept'], 'threads_kept_plain': plain['kept'],
            'drawn': evict['drawn'] and plain['drawn'], 'pass': ok, 'media': str(media)}


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
        print(f"{dll}: after 5 cycles of a kept frame outliving a cache eviction the engine kept "
              f"{result['threads_kept_evicted']} threads ({result['threads_kept_plain']} without the eviction), "
              f"every frame drawn: {result['drawn']}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
