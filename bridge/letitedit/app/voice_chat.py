"""Push-to-talk for the editor's chat panel: local speech-to-text of a short recording and a local spoken reply.

The editor records the microphone only while the talk control is held, writes the recording to a temporary WAV and
hands it to this helper (`python voice_chat.py serve`: JSON lines on stdin/stdout, kept running so the speech model
stays loaded). Nothing leaves this PC: transcription is speech.py's engine (GPU openai-whisper large-v3-turbo, else
CPU faster-whisper medium.en; or whisper.cpp in C:\\LetItEdit\\app), the reply voice is Windows' built-in speech
(System.Speech / SAPI voices installed with Windows).

Settings: the "voice" object in C:\\LetItEdit\\chat\\panel.json; every key is optional, DEFAULTS has the defaults.

Commands (one JSON object per line; every reply carries the request's "cmd" and "id"):
  {"cmd": "settings"}                       -> {"settings": merged, "defaults": DEFAULTS, "voices": [...]}
  {"cmd": "warm"}                           -> loads the speech model (GPU worker) ahead of the first transcription
  {"cmd": "transcribe", "wav": path, "delete": true}
                                            -> {"text", "engine", "seconds", "speech_s", "peak_db", "skipped"?}
  {"cmd": "speak", "text": "..."}           -> speaks in the background; a second reply {"done": true} when finished
  {"cmd": "stop_speaking"}                  -> stops the voice
  {"cmd": "quit"}
"""
from __future__ import annotations
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import array
import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

PANEL_SETTINGS = Path(os.environ.get('LETITEDIT_PANEL_SETTINGS', (_SAI_ROOT + '\\chat\\panel.json')))
FFMPEG = Path((_SAI_ROOT + '\\app\\ffmpeg.exe'))
WHISPER_CLI = Path((_SAI_ROOT + '\\app\\whisper-cli.exe'))
NO_WINDOW = 0x08000000

# Every number and choice the push-to-talk path uses. The editor reads ptt_key, max_record_s, sample_rate_hz,
# mic_device, speak_replies and enabled from the same "voice" object with these same defaults.
DEFAULTS = {
    'enabled': True,                 # show the Hold to talk button and the hold key
    'ptt_key': 'F12',                # key held to talk while the editor window is active ('' = button only); F8
                                     # is the editor's 540p preview, F12 no command's (the app checks for a clash)
    'mic_device': '',                # '' = Windows' default input; else text in the input's name
    'sample_rate_hz': 16000,         # recording rate asked of the microphone (it may give its own; converted here)
    'max_record_s': 60.0,            # recording stops by itself after this long
    'silence_threshold_db': -45.0,   # level (dBFS, 20 ms windows) above which a window counts as sound
    'min_speech_s': 0.3,             # less sound than this in a recording: nothing is transcribed or sent
    'engine': 'auto',                # auto (GPU whisper, else CPU) | gpu | cpu | whisper_cpp
    'whisper_cpp_model': '',         # ggml model file for engine whisper_cpp
    'language': 'en',
    'keep_recordings': False,        # False: the temporary WAV is deleted after transcription
    'speak_replies': 'spoken',       # spoken (reply aloud after a spoken message) | always | never
    'voice': '',                     # '' = Windows' default voice; else text in an installed voice's name
    'rate': 0,                       # SAPI rate, -10 (slow) .. 10 (fast)
    'volume': 100,                   # 0 .. 100
    'max_spoken_chars': 1200,        # longer replies are cut at a sentence end before this many characters
}


def settings(path=None):
    """DEFAULTS with the panel.json "voice" values on top."""
    merged = dict(DEFAULTS)
    p = Path(path) if path else PANEL_SETTINGS
    try:
        data = json.loads(p.read_text(encoding='utf-8-sig'))
        merged.update({k: v for k, v in (data.get('voice') or {}).items()})
    except (OSError, ValueError, AttributeError):
        pass
    return merged


# ------------------------------------------------------------------ hearing

def _to_16k(wav):
    """A 16 kHz mono 16-bit copy of any WAV the microphone gave (temporary file)."""
    fd, out = tempfile.mkstemp(suffix='.wav', prefix='ptt16k-')
    os.close(fd)
    r = subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-i', str(wav), '-ac', '1', '-ar', '16000',
                        '-c:a', 'pcm_s16le', out], capture_output=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        os.remove(out)
        raise RuntimeError('ffmpeg could not read the recording: ' + r.stderr.decode(errors='replace')[-300:])
    return out


def levels(wav16, threshold_db, window_s=0.02):
    """(seconds, seconds of windows above threshold_db, peak dBFS) of a 16-bit mono WAV."""
    with wave.open(str(wav16), 'rb') as w:
        rate, n = w.getframerate(), w.getnframes()
        data = array.array('h', w.readframes(n))
    if not data:
        return 0.0, 0.0, -120.0
    step = max(1, int(rate * window_s))
    loud = 0
    peak = 0
    for i in range(0, len(data), step):
        chunk = data[i:i + step]
        rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
        peak = max(peak, max(abs(x) for x in chunk))
        if rms > 0 and 20 * math.log10(rms / 32768.0) > threshold_db:
            loud += 1
    peak_db = 20 * math.log10(peak / 32768.0) if peak else -120.0
    return len(data) / rate, loud * step / rate, round(peak_db, 1)


def _join(words):
    text = ' '.join((w.get('w') or w.get('word') or '').strip() for w in words)
    return re.sub(r'\s+([,.!?;:])', r'\1', re.sub(r'\s+', ' ', text)).strip()


def _whisper_cpp(wav16, cfg):
    model = cfg.get('whisper_cpp_model')
    if not model or not Path(model).is_file():
        raise RuntimeError("engine whisper_cpp needs voice.whisper_cpp_model (a ggml .bin file)")
    r = subprocess.run([str(WHISPER_CLI), '-m', model, '-f', str(wav16), '-l', cfg.get('language') or 'en', '-nt',
                        '-np'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                       creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError('whisper-cli failed: ' + r.stderr[-300:])
    return re.sub(r'\s+', ' ', r.stdout).strip()


def _lock_taken_elsewhere():
    """True when another job has the PC lock, and the CPU engine is on this PC to use instead (nothing is downloaded here)."""
    try:
        import letitedit.core.render_lock as render_lock
        i = render_lock.info()
        if (not i.get('held') and not i.get('waiting')) or i.get('stale') or i.get('owner_pid') == os.getpid():
            return False
        import letitedit.footage.speech as speech
        import letitedit.footage.speech_language as speech_language
        if speech.MODEL.endswith('.en') and speech_language.may_speak_other_language():
            return False  # the CPU model understands English only: wait for the real words rather than made-up English (T101)
        from faster_whisper.utils import download_model
        download_model(speech.MODEL, local_files_only=True)
        return True
    except Exception:  # noqa: BLE001 - no CPU engine, or no lock to read: the normal way, which waits its turn
        return False


def transcribe(wav, cfg=None, delete=None, not_behind_others=False):
    """Text said in a recording, transcribed on this PC. Returns {'text', 'engine', 'seconds', 'speech_s',
    'peak_db'} plus 'skipped' when the recording held less sound than min_speech_s. not_behind_others: when another job
    has the PC lock (an export), the CPU engine writes it down now rather than the GPU model after that job: a short note
    in Live Review, while the person is watching. It uses no GPU, so the rule that no model runs during a render holds."""
    cfg = cfg or settings()
    delete = (not cfg.get('keep_recordings')) if delete is None else delete
    t0 = time.time()
    wav16 = _to_16k(wav)
    try:
        seconds, speech_s, peak_db = levels(wav16, float(cfg['silence_threshold_db']))
        out = {'seconds': round(seconds, 2), 'speech_s': round(speech_s, 2), 'peak_db': peak_db,
               'silence_threshold_db': float(cfg['silence_threshold_db']), 'min_speech_s': float(cfg['min_speech_s'])}
        if speech_s < float(cfg['min_speech_s']):
            out.update(text='', engine=None, skipped='less sound than min_speech_s above silence_threshold_db')
            return out
        engine = cfg.get('engine') or 'auto'
        text = None
        words = []
        if engine == 'whisper_cpp':
            text, used = _whisper_cpp(wav16, cfg), 'whisper_cpp'
        else:
            import letitedit.footage.speech as speech
            if engine in ('auto', 'gpu') and not_behind_others and _lock_taken_elsewhere():
                os.environ.setdefault('LETITEDIT_WHISPER_CPU_THREADS', '4')
                words = speech._transcribe_cpu(wav16)
                text, used = _join(words), 'cpu ' + speech.MODEL + ' (the PC lock was taken)'
            elif engine in ('auto', 'gpu'):
                words = speech._transcribe_gpu(wav16)
                if words is not None:
                    text, used = _join(words), 'gpu ' + speech.GPU_MODEL
                else:
                    words = []
            if text is None:
                if engine == 'gpu':
                    raise RuntimeError('no GPU speech engine on this PC (engine gpu)')
                words = speech._transcribe_cpu(wav16)
                text, used = _join(words), 'cpu ' + speech.MODEL
        # each word with its start and end in seconds from the start of the recording (Review ties each drawn mark to them)
        out.update(text=text, engine=used, transcribe_s=round(time.time() - t0, 2),
                   words=[{'w': (w.get('w') or w.get('word') or '').strip(), 's': w.get('s'), 'e': w.get('e')}
                          for w in (words or [])])
        return out
    finally:
        try:
            os.remove(wav16)
        except OSError:
            pass
        if delete:
            try:
                os.remove(wav)
            except OSError:
                pass


def warm(cfg=None):
    cfg = cfg or settings()
    if (cfg.get('engine') or 'auto') in ('auto', 'gpu'):
        import letitedit.footage.speech as speech
        # the model loads under the PC lock's model slot, with room made on the GPU first (never beside a render)
        return {'gpu': speech._ensure_gpu_worker() is not None}
    return {'gpu': False}


# ------------------------------------------------------------------ speaking

def spoken_text(text, max_chars):
    """Reply text as it is read aloud: markdown marks, code and links removed; cut at a sentence end before
    max_chars."""
    t = re.sub(r'```.*?```', ' ', text or '', flags=re.S)
    t = re.sub(r'`([^`]*)`', r'\1', t)
    t = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', t)
    t = re.sub(r'(\*{1,3})([^*\n]+)\1', r'\2', t)
    t = re.sub(r'(?<!\w)(_{1,3})([^_\n]+)\1(?!\w)', r'\2', t)
    t = re.sub(r'^\s*(#+|>|[-*]|\d+\.)\s+', '', t, flags=re.M)
    t = re.sub(r'\s+', ' ', t).strip()
    if len(t) > max_chars:
        cut = t[:max_chars + 1]
        ends = [m.end(1) for m in re.finditer(r'([.!?])(\s|$)', cut) if m.end(1) <= max_chars]
        t = cut[:ends[-1]] if ends else t[:max_chars]
    return t


def _ps_script(text, cfg, wav_out=None):
    b64 = base64.b64encode((text or '').encode('utf-8')).decode()
    voice = (cfg.get('voice') or '').replace("'", "''")
    lines = [
        'Add-Type -AssemblyName System.Speech',
        '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer',
        f"$want = '{voice}'",
        "if ($want) { $v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Name -like ('*' + $want + '*') } | Select-Object -First 1; if ($v) { $s.SelectVoice($v.VoiceInfo.Name) } }",
        f'$s.Rate = {max(-10, min(10, int(cfg.get("rate", 0))))}',
        f'$s.Volume = {max(0, min(100, int(cfg.get("volume", 100))))}',
    ]
    if wav_out:
        lines.append(f"$s.SetOutputToWaveFile('{str(wav_out).replace(chr(39), chr(39) * 2)}')")
    lines += [f"$t = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}'))",
              '$s.Speak($t)', '$s.Dispose()']
    return '\n'.join(lines)


def _powershell(script):
    enc = base64.b64encode(script.encode('utf-16-le')).decode()
    return ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', enc]


def speak(text, cfg=None, wav_out=None, wait=True):
    """Say text with a Windows voice (to the speakers, or to wav_out). Returns the process when wait=False."""
    cfg = cfg or settings()
    p = subprocess.Popen(_powershell(_ps_script(text, cfg, wav_out)), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    if wait:
        p.wait()
        return p.returncode
    return p


def voices():
    script = ('Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
              '$s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name + "|" + '
              '$_.VoiceInfo.Culture + "|" + $_.VoiceInfo.Gender }')
    r = subprocess.run(_powershell(script), capture_output=True, text=True, creationflags=NO_WINDOW)
    out = []
    for line in r.stdout.splitlines():
        parts = line.strip().split('|')
        if len(parts) == 3:
            out.append({'name': parts[0], 'culture': parts[1], 'gender': parts[2]})
    return out


# ------------------------------------------------------------------ helper process

def serve(stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    lock = threading.Lock()
    state = {'speaker': None}
    review = None
    review_jobs = None

    def send(obj):
        with lock:
            stdout.write(json.dumps(obj) + '\n')
            stdout.flush()

    def stop_speaking():
        p = state['speaker']
        if p is not None and p.poll() is None:
            p.kill()
        state['speaker'] = None

    send({'cmd': 'hello', 'ready': True, 'pid': os.getpid()})
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            send({'cmd': None, 'ok': False, 'error': 'invalid JSON'})
            continue
        cmd, rid = req.get('cmd'), req.get('id')
        cfg = settings()
        try:
            if req.get('review') or cmd == 'review_audio':
                if review is None:
                    from review_speech import ReviewSpeech
                    from concurrent.futures import ThreadPoolExecutor
                    review = ReviewSpeech()
                    review_jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix='review-words')
                if cmd == 'review_audio':
                    send({'cmd': cmd, 'id': rid, 'ok': True, **review.audio(req)})
                else:
                    def review_work(req=req, cfg=cfg, cmd=cmd, rid=rid):
                        try:
                            if cmd == 'warm':
                                result = review.warm(cfg.get('language') or '')
                            elif cmd == 'transcribe':
                                result = review.transcribe(req['wav'], cfg.get('language') or '',
                                                           req.get('video'), req.get('ranges'), req.get('project'))
                            else:
                                raise ValueError('unknown Review speech command')
                            send({'cmd': cmd, 'id': rid, 'ok': True, **result})
                        except Exception as error:
                            send({'cmd': cmd, 'id': rid, 'ok': False, 'error': str(error)})
                    review_jobs.submit(review_work)
                continue
            if cmd == 'quit':
                stop_speaking()
                send({'cmd': cmd, 'id': rid, 'ok': True})
                break
            if cmd == 'settings':
                send({'cmd': cmd, 'id': rid, 'ok': True, 'settings': cfg, 'defaults': DEFAULTS, 'voices': voices()})
            elif cmd == 'warm':
                send({'cmd': cmd, 'id': rid, 'ok': True, **warm(cfg)})
            elif cmd == 'transcribe':
                res = transcribe(req['wav'], cfg, delete=req.get('delete'), not_behind_others=bool(req.get('not_behind_others')))
                send({'cmd': cmd, 'id': rid, 'ok': True, **res})
            elif cmd == 'speak':
                stop_speaking()
                text = spoken_text(req.get('text', ''), int(cfg['max_spoken_chars']))
                if not text:
                    send({'cmd': cmd, 'id': rid, 'ok': True, 'text': '', 'done': True})
                    continue
                p = speak(text, cfg, wav_out=req.get('wav_out'), wait=False)
                state['speaker'] = p
                send({'cmd': cmd, 'id': rid, 'ok': True, 'text': text, 'started': True})

                def finished(p=p, rid=rid, text=text):
                    code = p.wait()
                    send({'cmd': 'speak', 'id': rid, 'ok': code == 0, 'text': text, 'done': True, 'exit': code})
                threading.Thread(target=finished, daemon=True).start()
            elif cmd == 'stop_speaking':
                stop_speaking()
                send({'cmd': cmd, 'id': rid, 'ok': True})
            else:
                send({'cmd': cmd, 'id': rid, 'ok': False, 'error': f'unknown cmd {cmd!r}'})
        except Exception as exc:  # noqa: BLE001 - every failure goes back to the editor as a reply
            send({'cmd': cmd, 'id': rid, 'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
    if review_jobs is not None:
        review_jobs.shutdown(wait=True)


if __name__ == '__main__':
    # the app reads every line as UTF-8, whatever the Windows code page is
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    if len(sys.argv) > 1 and sys.argv[1] == 'serve':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdin.reconfigure(encoding='utf-8')
        serve()
    elif len(sys.argv) > 2 and sys.argv[1] == 'transcribe':
        # classic Review waits on this, with Send and its next note held for the words: rough CPU words now rather than
        # the GPU model after whoever holds the PC lock (5 Nov; tests/t101/REPORT.md)
        print(json.dumps(transcribe(sys.argv[2], delete=False, not_behind_others=True), indent=1))
    elif len(sys.argv) > 2 and sys.argv[1] == 'speak':
        speak(' '.join(sys.argv[2:]))
    else:
        print(json.dumps({'settings': settings(), 'defaults': DEFAULTS}, indent=1))
