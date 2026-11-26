"""SAM 2 Tiny for object layers, run in the models environment (the bridge has no torch).

object_sam_worker.py <spec.json>
spec: {model, raw, shape: [n, h, w, 3], chunk, jobs: [{name, key, indices, points, labels, out}]}
Each job follows one object through the listed frames of the raw file, from `key`, both ways. A session holds about 42 MB
of GPU memory per frame however its state is stored (measured, T62), so a long run goes in chunks: each chunk starts from
the last mask of the one before. Writes <out>/<name>_<index>.png (8-bit soft mask) and prints one JSON line.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import Sam2VideoModel, Sam2VideoProcessor


def run_chunk(model, proc, frames, prompt, on_mask):
    h, w = frames[0].size[1], frames[0].size[0]
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
        session = proc.init_video_session(video=frames, inference_device='cuda', inference_state_device='cpu',
                                          video_storage_device='cpu', dtype=torch.float16)
        proc.add_inputs_to_inference_session(inference_session=session, frame_idx=0, obj_ids=1, **prompt)

        def soft(masks):
            m = proc.post_process_masks([masks.cpu()], original_sizes=[[h, w]], binarize=False)[0][0, 0].float()
            if m.min() < 0 or m.max() > 1:
                m = m.sigmoid()
            return np.clip(m.numpy(), 0, 1)
        last = soft(model(inference_session=session, frame_idx=0).pred_masks)
        on_mask(0, last)
        if len(frames) > 1:
            for out in model.propagate_in_video_iterator(session, start_frame_idx=0):
                if out.frame_idx == 0:
                    continue
                last = soft(out.pred_masks)
                on_mask(out.frame_idx, last)
        del session
    return last


def main():
    spec = json.load(open(sys.argv[1], encoding='utf-8-sig'))
    n, h, w, c = spec['shape']
    raw = np.memmap(spec['raw'], dtype=np.uint8, mode='r', shape=(n, h, w, c))
    model = Sam2VideoModel.from_pretrained(spec['model'], local_files_only=True).to('cuda', dtype=torch.float16).eval()
    proc = Sam2VideoProcessor.from_pretrained(spec['model'], local_files_only=True)
    torch.cuda.reset_peak_memory_stats()
    chunk = max(4, int(spec.get('chunk') or 100))
    t0 = time.perf_counter()
    done = {}
    for job in spec['jobs']:
        out_dir = Path(job['out'])
        out_dir.mkdir(parents=True, exist_ok=True)
        indices = sorted(job['indices'])
        key = job['key']
        if key not in indices:
            indices = sorted(indices + [key])
        p = indices.index(key)
        areas = {}

        def picture(i):
            return Image.fromarray(np.asarray(raw[i])[..., ::-1])

        def follow(order):
            prompt = dict(input_points=[[job['points']]], input_labels=[[job['labels']]])
            at = 0
            while at < len(order):
                part = order[at:at + chunk]
                frames = [picture(i) for i in part]

                def keep(k, mask, part=part):
                    Image.fromarray((mask * 255).astype(np.uint8)).save(out_dir / f"{job['name']}_{part[k]:05d}.png")
                    areas[part[k]] = float((mask > .5).mean())
                last = run_chunk(model, proc, frames, prompt, keep)
                if at + chunk >= len(order):
                    break
                # the next chunk starts on this chunk's last frame, from its mask
                prompt = dict(input_masks=(last > .5))
                at += chunk - 1
        follow(indices[p:])
        if p > 0:
            follow(indices[p::-1])
        done[job['name']] = {'frames': len(areas), 'area_min': round(min(areas.values()), 5),
                             'area_max': round(max(areas.values()), 5)}
    print(json.dumps({'ok': True, 'seconds': round(time.perf_counter() - t0, 2), 'jobs': done,
                      'gpu_peak_mb': round(torch.cuda.max_memory_allocated() / 1048576)}), flush=True)


if __name__ == '__main__':
    main()
