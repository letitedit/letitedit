"""Length-prefixed RGB/matte pipe for the official BiRefNet-lite CUDA checkpoint."""

import importlib.machinery
import os
import queue
import struct
import sys
import threading
import types
from pathlib import Path


def _read_exact(stream, size):
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            return None
        data.extend(part)
    return bytes(data)


def _reply(payload):
    sys.stdout.buffer.write(struct.pack('<I', len(payload)) + payload)
    sys.stdout.buffer.flush()


def main():
    # The author's eval path never calls laplacian; kornia is used in training.
    kornia = types.ModuleType('kornia')
    kornia.__path__ = []
    kornia.__spec__ = importlib.machinery.ModuleSpec('kornia', loader=None, is_package=True)
    filters = types.ModuleType('kornia.filters')
    filters.__spec__ = importlib.machinery.ModuleSpec('kornia.filters', loader=None)
    def training_only(*_args, **_kwargs):
        raise RuntimeError('training-only filter called in inference')
    filters.laplacian = training_only
    kornia.filters = filters
    sys.modules['kornia'] = kornia
    sys.modules['kornia.filters'] = filters

    # The build PC's existing CUDA environment has torchvision but gets timm
    # from the models environment. A fresh customer models environment has both.
    extra = os.environ.get('LETITEDIT_BIREFNET_PACKAGES')
    if extra and Path(extra).is_dir():
        sys.path.append(extra)
    import numpy as np
    import torch
    import torchvision
    from PIL import Image
    from transformers import AutoModelForImageSegmentation
    bridge = str(Path(__file__).resolve().parents[2] / 'bridge')
    if bridge not in sys.path:
        sys.path.append(bridge)
    from letitedit.core import pipe_input

    if not torch.cuda.is_available() or not torchvision.extension._has_ops():
        raise RuntimeError('CUDA torchvision operators unavailable')
    torch.set_num_threads(4)
    model = AutoModelForImageSegmentation.from_pretrained(
        sys.argv[1], trust_remote_code=True, local_files_only=True).to('cuda').eval().half()
    _reply(b'READY')
    mean, std = np.array([.485, .456, .406], np.float32), np.array([.229, .224, .225], np.float32)
    # Preparing and finishing a frame run beside the model, so the model is the only wait. Mattes come back in order.
    prepared, finished = queue.Queue(3), queue.Queue(3)

    def guarded(work):
        def run():
            try:
                work()
            except BaseException as ex:  # noqa: BLE001
                print(f'{type(ex).__name__}: {ex}', file=sys.stderr, flush=True)
                os._exit(1)
        return run

    def prepare():
        # frames are read only once they are in the pipe: a read left waiting here would hold any library the model
        # loads meanwhile, and the sender writes nothing more until that picture is answered
        input_stream = pipe_input.reader(sys.stdin.buffer, poll_s=.005)
        while header := _read_exact(input_stream, 8):
            width, height = struct.unpack('<II', header)
            if not width or not height or width > 8192 or height > 8192:
                raise ValueError('invalid frame dimensions')
            raw = _read_exact(input_stream, width * height * 3)
            if raw is None:
                break
            image = Image.fromarray(np.frombuffer(raw, np.uint8).reshape(height, width, 3), 'RGB')
            image = image.resize((1024, 1024), Image.Resampling.BILINEAR)
            x = np.asarray(image, np.float32) / 255
            x = (x - mean) / std
            prepared.put((width, height, x.transpose(2, 0, 1).copy()))
        prepared.put(None)

    def answer():
        while (item := finished.get()) is not None:
            width, height, pred = item
            matte = Image.fromarray(pred).resize((width, height), Image.Resampling.BILINEAR)
            _reply(np.asarray(matte, np.float16).tobytes())

    threading.Thread(target=guarded(prepare), daemon=True).start()
    answering = threading.Thread(target=guarded(answer), daemon=True)
    answering.start()
    while (item := prepared.get()) is not None:
        width, height, x = item
        tensor = torch.from_numpy(x).unsqueeze(0).to('cuda', dtype=torch.float16)
        with torch.inference_mode():
            pred = model(tensor)[-1].sigmoid()[0].squeeze().float().cpu().numpy()
        finished.put((width, height, pred))
    finished.put(None)
    answering.join()


if __name__ == '__main__':
    try:
        main()
    except Exception as ex:
        print(f'{type(ex).__name__}: {ex}', file=sys.stderr, flush=True)
        raise
