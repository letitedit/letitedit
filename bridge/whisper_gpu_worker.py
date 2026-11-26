"""GPU transcription worker for letitedit (runs in the openai-whisper environment, not the bridge's Python).

Started by speech.py and kept alive so the model loads once. Protocol: one JSON request per stdin line
    {"id": 1, "wav": "C:/.../a.wav", "language": "en"}
and one JSON reply per stdout line
    {"id": 1, "words": [{"w": "word", "s": 0.12, "e": 0.40, "p": 0.93}, ...]}   or   {"id": 1, "error": "..."}
(p = how sure the model is of the word, 0-1)
The first line written is {"ready": true, "model": ..., "device": ...}. Exits on EOF or after IDLE seconds idle.
"""
import json
import os
import sys
import threading
import time
import wave

import numpy as np

MODEL = sys.argv[1] if len(sys.argv) > 1 else 'large-v3-turbo'
IDLE = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
ROOT = sys.argv[3] if len(sys.argv) > 3 else None     # where the model's file is (speech.py sees to it: nothing downloads here)


def load_wav(path):
    with wave.open(path, 'rb') as w:
        if w.getnchannels() != 1 or w.getframerate() != 16000 or w.getsampwidth() != 2:
            raise ValueError('expected 16 kHz mono 16-bit WAV')
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def tool_server_gone():
    """The tool server that started this worker has gone (Stop in the app): no one is waiting for the job in hand."""
    pid = int(os.environ.get('LETITEDIT_TOOL_SERVER_PID') or 0)
    if not pid or os.name != 'nt':
        return False
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
    if not handle:
        return True
    try:
        return kernel.WaitForSingleObject(handle, 0) != 0x102  # WAIT_TIMEOUT: still running
    finally:
        kernel.CloseHandle(handle)


def main():
    import torch
    import whisper
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = whisper.load_model(MODEL, device=device, download_root=ROOT)
    out = sys.stdout
    out.write(json.dumps({'ready': True, 'model': MODEL, 'device': device}) + '\n')
    out.flush()
    last = [time.time()]

    def watchdog():
        while True:
            time.sleep(15)
            if tool_server_gone() or time.time() - last[0] > IDLE:
                import os
                os._exit(0)
    threading.Thread(target=watchdog, daemon=True).start()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        last[0] = time.time()
        req = json.loads(line)
        try:
            audio = load_wav(req['wav'])
            words = []
            if audio.size:
                r = model.transcribe(audio, language=req.get('language', 'en'), word_timestamps=True,
                                     condition_on_previous_text=False, beam_size=5, fp16=(device == 'cuda'))
                for seg in r['segments']:
                    for w in seg.get('words', []):
                        text = w['word'].strip()
                        if text:
                            words.append({'w': text, 's': round(float(w['start']), 3), 'e': round(float(w['end']), 3),
                                          'p': round(float(w.get('probability', 1.0)), 2)})
            out.write(json.dumps({'id': req.get('id'), 'words': words}) + '\n')
        except Exception as e:  # noqa: BLE001
            out.write(json.dumps({'id': req.get('id'), 'error': f'{type(e).__name__}: {e}'}) + '\n')
        out.flush()
        last[0] = time.time()


if __name__ == '__main__':
    main()
