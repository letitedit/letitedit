"""Model side of the fix-in-post pack: runs in C:\\LetItEdit\\envs\\models (torch) as
    python -I fix_worker.py <spec.json>
and prints JSON lines: {"progress": f, "frames": n} ... then {"result": {...}} (or {"error": "..."}).

Ops (spec['op']):
  frames  decode src (start, dur) at fps and in_w x in_h through ffmpeg, run each frame through a model, encode out.
          model: 'scunet' (denoise; strength blends model and input), 'realesrgan-x2plus' / 'realesr-general-x4v3'
          (upscale; boxes = per-frame [x, y, w, h] crop in decode pixels, each crop upscaled then resized to
          out_w x out_h), 'none' (crop/resize only). vf_post: ffmpeg filters after the model (encoder side).
  wpe     dereverberate a WAV with nara_wpe (taps, delay, iterations).
"""
from __future__ import annotations
import os as _os, sys as _sys
_sys.path.append(_os.path.dirname(_os.path.abspath(__file__)))   # started with -I, which leaves this folder off sys.path; last, so it shadows nothing
import quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))   # install root: LETITEDIT_ROOT, else the folder above bridge

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))          # -I leaves the script's folder off sys.path: fix_nets lives beside this file
MODELS = Path(os.environ.get('LETITEDIT_MODELS_HOME', (_SAI_ROOT + '\\models')))
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
WEIGHTS = {
    'scunet': MODELS / 'scunet' / 'scunet_color_real_psnr.pth',
    'realesrgan-x2plus': MODELS / 'realesrgan' / 'RealESRGAN_x2plus.pth',
    'realesr-general-x4v3': MODELS / 'realesrgan' / 'realesr-general-x4v3.pth',
}


def emit(**kw):
    sys.stdout.write(json.dumps(kw) + '\n')
    sys.stdout.flush()


def load_model(name, device, half):
    import torch
    import fix_nets as N
    if name == 'scunet':
        net = N.SCUNet(config=[4] * 7, dim=64)
        scale = 1
    elif name == 'realesrgan-x2plus':
        net = N.RRDBNet(scale=2)
        scale = 2
    elif name == 'realesr-general-x4v3':
        net = N.SRVGGNetCompact()
        scale = 4
    else:
        raise ValueError(f'unknown model {name}')
    sd = torch.load(str(WEIGHTS[name]), map_location='cpu', weights_only=True)
    sd = sd.get('params_ema', sd.get('params', sd))
    net.load_state_dict(sd, strict=True)
    net.eval().to(device)
    if half:
        net.half()
    return net, scale


def run_tiled(net, x, scale, tile, pad=16):
    """x: 1x3xHxW tensor. Runs net over tiles of `tile` px (0 = whole frame) with `pad` px overlap."""
    import torch
    if not tile or (x.shape[2] <= tile and x.shape[3] <= tile):
        return net(x)
    _, c, h, w = x.shape
    out = torch.zeros((1, c, h * scale, w * scale), dtype=x.dtype, device=x.device)
    for y0 in range(0, h, tile):
        for x0 in range(0, w, tile):
            y1, x1 = min(h, y0 + tile), min(w, x0 + tile)
            ya, xa = max(0, y0 - pad), max(0, x0 - pad)
            yb, xb = min(h, y1 + pad), min(w, x1 + pad)
            o = net(x[:, :, ya:yb, xa:xb])
            out[:, :, y0 * scale:y1 * scale, x0 * scale:x1 * scale] = \
                o[:, :, (y0 - ya) * scale:(y0 - ya + y1 - y0) * scale, (x0 - xa) * scale:(x0 - xa + x1 - x0) * scale]
    return out


def op_frames(spec):
    import numpy as np
    import torch
    ff = spec['ffmpeg']
    fps, iw, ih = spec['fps'], int(spec['in_w']), int(spec['in_h'])
    ow, oh = int(spec.get('out_w') or iw), int(spec.get('out_h') or ih)
    model = spec.get('model', 'none')
    device = 'cuda' if torch.cuda.is_available() and spec.get('device', 'cuda') == 'cuda' else 'cpu'
    half = bool(spec.get('half', True)) and device == 'cuda'
    t_load = time.monotonic()
    net, scale = (None, 1) if model == 'none' else load_model(model, device, half)
    load_s = time.monotonic() - t_load
    rate = f'{fps:.6f}'.rstrip('0').rstrip('.')
    pre = f'fps={rate},scale={iw}:{ih}:flags=lanczos,setsar=1' + (',' + spec['vf_pre'] if spec.get('vf_pre') else '')
    rd = subprocess.Popen([ff, '-v', 'error', '-ss', f"{spec['start']:.4f}", '-t', f"{spec['dur']:.4f}", '-i', spec['src'],
                           '-vf', pre, '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                          stdout=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    wcmd = [ff, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{ow}x{oh}', '-r', rate, '-i', '-']
    if spec.get('audio'):
        wcmd += ['-ss', f"{spec['start']:.4f}", '-t', f"{spec['dur']:.4f}", '-i', spec['src']]
    post = spec.get('vf_post') or 'null'
    wcmd += ['-vf', post, '-map', '0:v']
    if spec.get('audio'):
        wcmd += ['-map', '1:a:0?', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000']
    wcmd += ['-c:v', 'libx264', '-crf', str(spec.get('crf', 14)), '-preset', spec.get('preset', 'medium'),
             '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-t', f"{spec['dur']:.4f}", spec['out']]
    wr = subprocess.Popen(wcmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, creationflags=NO_WINDOW)
    nbytes = iw * ih * 3
    q = queue.Queue(maxsize=8)

    def reader():
        while True:
            buf = rd.stdout.read(nbytes)
            if len(buf) < nbytes:
                q.put(None)
                return
            q.put(buf)
    threading.Thread(target=reader, daemon=True).start()
    total = max(1, int(round(spec['dur'] * fps)))
    boxes = spec.get('boxes')
    strength = float(spec.get('strength', 1.0))
    tile = int(spec.get('tile', 0) or 0)
    n, t0, peak = 0, time.monotonic(), 0
    with torch.no_grad():
        while True:
            buf = q.get()
            if buf is None:
                break
            img = np.frombuffer(buf, np.uint8).reshape(ih, iw, 3)
            if boxes:
                bx = boxes[min(n, len(boxes) - 1)]
                x, y, w, h = (int(round(v)) for v in bx)
                x, y = max(0, min(iw - w, x)), max(0, min(ih - h, y))
                img = img[y:y + h, x:x + w]
            if net is not None:
                t = torch.from_numpy(np.ascontiguousarray(img)).to(device).permute(2, 0, 1)[None]
                t = (t.half() if half else t.float()) / 255.0
                o = run_tiled(net, t, scale, tile)
                if model == 'scunet' and strength != 1.0:
                    o = strength * o + (1.0 - strength) * t
                if o.shape[2] != oh or o.shape[3] != ow:
                    o = torch.nn.functional.interpolate(o.float(), size=(oh, ow), mode='bicubic', align_corners=False,
                                                        antialias=True)
                img = (o.clamp(0, 1) * 255.0 + 0.5).byte()[0].permute(1, 2, 0).cpu().numpy()
                if device == 'cuda':
                    peak = max(peak, torch.cuda.max_memory_allocated() // 2 ** 20)
            elif img.shape[0] != oh or img.shape[1] != ow:
                t = torch.from_numpy(np.ascontiguousarray(img)).permute(2, 0, 1)[None].float() / 255.0
                o = torch.nn.functional.interpolate(t, size=(oh, ow), mode='bicubic', align_corners=False, antialias=True)
                img = (o.clamp(0, 1) * 255.0 + 0.5).byte()[0].permute(1, 2, 0).numpy()
            wr.stdin.write(np.ascontiguousarray(img).tobytes())
            n += 1
            if n % 10 == 0:
                emit(progress=round(min(1.0, n / total), 4), frames=n)
    wr.stdin.close()
    rc = wr.wait()
    rd.wait()
    if rc != 0 or n == 0:
        raise RuntimeError(f'encoding failed (ffmpeg exit {rc}, {n} frames)')
    return {'frames': n, 'model': model, 'device': device, 'half': half, 'load_s': round(load_s, 2),
            'run_s': round(time.monotonic() - t0, 2), 'gpu_peak_mb': int(peak), 'scale': scale}


def op_wpe(spec):
    import numpy as np
    import soundfile as sf
    from nara_wpe.utils import istft, stft
    from nara_wpe.wpe import wpe
    t0 = time.monotonic()
    y, sr = sf.read(spec['in'], always_2d=True)
    y = y.T                                         # channels x samples
    size, shift = int(spec.get('stft_size', 512)), int(spec.get('stft_shift', 128))
    Y = stft(y, size=size, shift=shift).transpose(2, 0, 1)     # freq x channels x frames
    Z = wpe(Y, taps=int(spec.get('taps', 10)), delay=int(spec.get('delay', 3)),
            iterations=int(spec.get('iterations', 3)), statistics_mode='full').transpose(1, 2, 0)
    z = istft(Z, size=size, shift=shift)[:, :y.shape[1]]
    peak = float(np.max(np.abs(z))) or 1.0
    if peak > 0.999:
        z = z * (0.999 / peak)
    sf.write(spec['out'], z.T, sr, subtype='FLOAT')
    return {'seconds': round(y.shape[1] / sr, 3), 'run_s': round(time.monotonic() - t0, 2), 'sample_rate': sr}


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    try:
        fn = {'frames': op_frames, 'wpe': op_wpe}[spec['op']]
        emit(result=fn(spec))
    except Exception as e:  # noqa: BLE001
        import traceback
        emit(error=f'{type(e).__name__}: {e}', trace=traceback.format_exc()[-2000:])
        sys.exit(1)


if __name__ == '__main__':
    main()
