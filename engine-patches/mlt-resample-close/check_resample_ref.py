"""Does an app's resample module (lib\\mlt\\libmltresample.dll) free a closed resample filter? (mlt-resample-close)

    python check_resample_ref.py [--app C:\\LetItEdit\\app] [--json]

In a child process with the app's engine and modules, it attaches a `resample` filter (the audio sample-rate
normalizer every clip the loader makes gets) to a colour producer and closes both, eight times, and counts the
process's handles after each close. The same with a `channelcopy` filter (another plain audio filter) is the
comparison, and so is a clip made through the loader (`loader` producer `color:black`), the way the XML loader makes
every clip.

Exit code 0 when a closed resample filter and a loader-made clip keep no more handles than the comparison (within 2
per cycle); 1 when they keep more (the stock 7.41.0 module keeps 17 per filter, so about 18 per clip loaded); 2 when
the probe can't run. No renders, no media; about 3 seconds. check_engine.py runs this check as `resample_ref`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOLERANCE = 2   # handles per cycle


def probe(app, variant, cycles):
    """runs in the child: handles after each close"""
    os.add_dll_directory(str(app))
    ctypes.windll.kernel32.SetDllDirectoryW(str(app))
    mlt = ctypes.CDLL(str(app / 'libmlt-7.dll'))
    k32 = ctypes.WinDLL('kernel32')
    V = ctypes.c_void_p
    for name, res, args in [('mlt_factory_init', V, [ctypes.c_char_p]), ('mlt_profile_init', V, [ctypes.c_char_p]),
                            ('mlt_factory_producer', V, [V, ctypes.c_char_p, ctypes.c_char_p]),
                            ('mlt_factory_filter', V, [V, ctypes.c_char_p, ctypes.c_char_p]),
                            ('mlt_producer_attach', ctypes.c_int, [V, V]), ('mlt_filter_close', None, [V]),
                            ('mlt_producer_close', None, [V])]:
        f = getattr(mlt, name)
        f.restype, f.argtypes = res, args

    def handles():
        n = ctypes.c_ulong()
        k32.GetProcessHandleCount(ctypes.c_void_p(-1), ctypes.byref(n))
        return n.value

    mlt.mlt_factory_init(os.environ['MLT_REPOSITORY'].encode())
    profile = mlt.mlt_profile_init(None)
    counts = []
    for _ in range(cycles):
        if variant == 'loader':
            producer = mlt.mlt_factory_producer(profile, None, b'color:black')
        else:
            producer = mlt.mlt_factory_producer(profile, b'color', b'black')
            f = mlt.mlt_factory_filter(profile, variant.encode(), None)
            if not f:
                raise SystemExit(f'the engine has no {variant} filter')
            mlt.mlt_producer_attach(producer, f)
            mlt.mlt_filter_close(f)
        if not producer:
            raise SystemExit('the engine could not make a colour producer')
        mlt.mlt_producer_close(producer)
        counts.append(handles())
    return {'variant': variant, 'after_close': counts}


def measure(app, variant, cycles=8):
    env = dict(os.environ, MLT_REPOSITORY=str(app / 'lib' / 'mlt'), MLT_DATA=str(app / 'share' / 'mlt'),
               MLT_PROFILES_PATH=str(app / 'share' / 'mlt' / 'profiles'),
               PATH=str(app) + os.pathsep + os.environ.get('PATH', ''))
    r = subprocess.run([sys.executable, __file__, '--child', variant, '--app', str(app), '--cycles', str(cycles)],
                       env=env, capture_output=True, text=True, timeout=120, creationflags=0x08000000)
    line = [x for x in r.stdout.splitlines() if x.startswith('{')]
    if r.returncode or not line:
        raise RuntimeError(f'probe failed ({r.returncode}): {r.stdout[-300:]} {r.stderr[-300:]}')
    out = json.loads(line[-1])
    c = out['after_close']
    out['kept_per_cycle'] = (c[-1] - c[1]) / max(1, len(c) - 2)   # the first cycle loads the module's own caches
    return out


def check(app):
    """The whole check: {'module', 'kept_resample', 'kept_loader_clip', 'kept_comparison', 'pass'}. Raises when the
    probe can't run."""
    app = Path(app)
    plain = measure(app, 'channelcopy')
    res = measure(app, 'resample')
    loader = measure(app, 'loader')
    base = plain['kept_per_cycle']
    ok = res['kept_per_cycle'] - base <= TOLERANCE and loader['kept_per_cycle'] - base <= TOLERANCE
    return {'module': str(app / 'lib' / 'mlt' / 'libmltresample.dll'), 'kept_resample': res['kept_per_cycle'],
            'kept_loader_clip': loader['kept_per_cycle'], 'kept_comparison': base, 'pass': ok}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--app', default=str(ROOT / 'app'))
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--child')
    ap.add_argument('--cycles', type=int, default=8)
    a = ap.parse_args(argv)
    app = Path(a.app)
    if a.child:
        print(json.dumps(probe(app, a.child, a.cycles)), flush=True)
        return 0
    try:
        result = check(app)
    except Exception as e:  # noqa: BLE001
        print('could not run:', e)
        return 2
    ok = result['pass']
    if a.json:
        print(json.dumps(result))
    else:
        print(f"{result['module']}: a closed resample filter keeps {result['kept_resample']:.0f} handles, a clip the "
              f"loader made {result['kept_loader_clip']:.0f}, a closed channelcopy filter "
              f"{result['kept_comparison']:.0f}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
