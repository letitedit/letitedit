"""Local, warm speech detection and short-note transcription for Review."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import threading
import time

import faster_whisper


class SpeechGate:
    def __init__(self):
        import numpy as np
        from faster_whisper.vad import get_vad_model

        self.np = np
        self.model = get_vad_model()
        self.history = np.zeros(0, dtype=np.float32)
        self.pending = np.zeros(0, dtype=np.float32)
        self.source = np.zeros(0, dtype=np.float32)
        self.source_position = 0.0
        self.voiced_ms = 0
        self.last_voice_ms = -1
        self.samples = 0
        self.silence_ms = 0

    def pcm(self, data, rate, channels=1, sample_format='int16'):
        np = self.np
        formats = {'int16': ('<i2', 32768.0), 'int32': ('<i4', 2147483648.0),
                   'float': ('<f4', 1.0), 'uint8': ('u1', 128.0)}
        dtype, scale = formats[sample_format]
        audio = np.frombuffer(data, dtype=dtype).astype(np.float32)
        if channels < 1 or rate < 8000 or rate > 192000 or audio.size % channels:
            raise ValueError('invalid review audio format')
        if sample_format == 'uint8':
            audio -= 128
        audio = (audio / scale).reshape(-1, channels).mean(axis=1)
        if rate == 16000:
            return self.feed(audio)
        self.source = np.concatenate((self.source, audio))
        positions = np.arange(self.source_position, max(0, self.source.size - 1), rate / 16000)
        converted = np.interp(positions, np.arange(self.source.size), self.source).astype(np.float32)
        next_position = positions[-1] + rate / 16000 if positions.size else self.source_position
        consumed = min(int(next_position), max(0, self.source.size - 1))
        self.source = self.source[consumed:]
        self.source_position = next_position - consumed
        return self.feed(converted)

    def feed(self, audio):
        np = self.np
        self.pending = np.concatenate((self.pending, np.asarray(audio, dtype=np.float32)))
        count = self.pending.size // 512 * 512
        if count:
            fresh, self.pending = self.pending[:count], self.pending[count:]
            combined = np.concatenate((self.history, fresh))
            probabilities = self.model(combined).reshape(-1)[-count // 512:]
            for probability in probabilities:
                self.samples += 512
                if probability >= .6:
                    self.silence_ms = 0
                    self.voiced_ms += 32
                    if self.voiced_ms >= 96:
                        self.last_voice_ms = self.samples // 16
                else:
                    self.silence_ms += 32
                    self.voiced_ms = 0 if self.silence_ms >= 160 else max(0, self.voiced_ms - 32)
            self.history = combined[-16384:]
        return {'voiced_ms': self.voiced_ms, 'last_voice_ms': self.last_voice_ms,
                'processed_ms': self.samples // 16}


class ReviewSpeech:
    def __init__(self):
        self.model = None
        self.model_name = None
        self.lock = threading.Lock()
        self.gate = None
        self.reference_cache = {}

    @staticmethod
    def cached_model(name):
        from faster_whisper.utils import download_model
        import letitedit.core.model_fetch as model_fetch

        model_id = 'faster-whisper-' + name.replace('.', '-')
        try:
            entry = model_fetch.entry(model_id)
            if model_fetch.status(entry)['present']:
                return str(model_fetch.file_dir(entry))
        except (KeyError, ValueError, FileNotFoundError):
            pass
        try:
            return download_model(name, local_files_only=True)
        except Exception:
            return None

    def warm(self, language='en'):
        import numpy as np

        english = language and language.lower().split('-')[0] == 'en'
        candidates = ('tiny.en', 'base.en', 'small.en', 'medium.en') if english else ('tiny', 'base', 'small', 'medium')
        with self.lock:
            if self.model is not None and (english == self.model_name.endswith('.en')):
                return {'engine': 'cpu ' + self.model_name}
            preferred = self.cached_model(candidates[0])
            first_use_error = None
            if not preferred and english:
                try:
                    import letitedit.core.first_use as first_use
                    first_use.need(models=['faster-whisper-tiny-en'], feature='Review spoken notes')
                    preferred = self.cached_model('tiny.en')
                except Exception as error:
                    first_use_error = str(error)
            for name in candidates:
                folder = preferred if name == candidates[0] else self.cached_model(name)
                if not folder:
                    continue
                model = faster_whisper.WhisperModel(folder, device='cpu', compute_type='int8', cpu_threads=4, num_workers=1)
                list(model.transcribe(np.zeros(1600, dtype=np.float32), language=language or None,
                                      beam_size=1, word_timestamps=False)[0])
                self.model, self.model_name = model, name
                return {'engine': 'cpu ' + name}
        raise RuntimeError(first_use_error or 'No local Review speech model for this language; no audio was sent anywhere.')

    def audio(self, request):
        if self.gate is None or request.get('reset'):
            self.gate = SpeechGate()
        result = self.gate.pcm(base64.b64decode(request['pcm'], validate=True), int(request['rate']),
                               int(request.get('channels', 1)), request.get('format', 'int16'))
        result['end_ms'] = request.get('end_ms', result['processed_ms'])
        return result

    def reference_words(self, project, ranges, language):
        import letitedit.timeline.edit_script as edit_script
        from letitedit.timeline.edit_sync import layout
        import letitedit.footage.speech as speech
        import letitedit.timeline.timeline_speech as timeline_speech
        import letitedit.app.voice_chat as voice_chat
        import letitedit.core.quiet_subprocess as quiet_subprocess
        import subprocess

        words = []
        script = edit_script.read(project)
        for track in script['tracks']:
            if track.get('hide') in ('audio', 'both'):
                continue
            for item, start, end in layout(track):
                item = timeline_speech.played_clip(item)
                if 'clip' not in item or timeline_speech._muted(item) or item.get('reverse'):
                    continue
                speed = float(item.get('speed', 1))
                if speed <= 0:
                    continue
                for lo, hi in ranges:
                    left, right = max(start, lo - 3), min(end, hi + 3)
                    if left >= right:
                        continue
                    source_start = float(item.get('in', 0)) + (left - start) * speed
                    source_end = float(item.get('in', 0)) + (right - start) * speed
                    cached = speech.cached_words(item['clip'], source_start, source_end)
                    if cached is not None:
                        for word in cached:
                            words.append({'w': word['w'], 's': start + (word['s'] - item.get('in', 0)) / speed,
                                          'e': start + (word['e'] - item.get('in', 0)) / speed})
                        continue
                    for bucket in range(int(source_start // 10), int(source_end // 10) + 1):
                        offset = bucket * 10
                        source = Path(item['clip'])
                        key = (str(source), source.stat().st_mtime_ns, offset, language)
                        if key not in self.reference_cache:
                            with tempfile.TemporaryDirectory(prefix='letitedit-review-reference-') as folder:
                                wav = Path(folder) / 'reference.wav'
                                decoded = subprocess.run([str(voice_chat.FFMPEG), '-v', 'error', '-threads', '4',
                                                          '-ss', str(offset), '-i', str(source), '-t', '10',
                                                          '-vn', '-ac', '1', '-ar', '16000', '-threads', '4', str(wav)],
                                                         capture_output=True, timeout=30)
                                if decoded.returncode:
                                    if b'does not contain any stream' in decoded.stderr:
                                        continue
                                    raise RuntimeError('Could not check the video sound; the spoken note is kept for retry.')
                                self.reference_cache[key] = self.transcribe(wav, language)['words']
                            if len(self.reference_cache) > 64:
                                del self.reference_cache[next(iter(self.reference_cache))]
                        for word in self.reference_cache[key]:
                            if offset + word['e'] < source_start or offset + word['s'] > source_end:
                                continue
                            words.append({'w': word['w'], 's': start + (offset + word['s'] - item.get('in', 0)) / speed,
                                          'e': start + (offset + word['e'] - item.get('in', 0)) / speed})
        return sorted({(word['w'], word['s'], word['e']): word for word in words}.values(), key=lambda word: word['s'])

    def transcribe(self, wav, language='en', video=None, ranges=None, project=None):
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        started = time.perf_counter()
        self.warm(language)
        audio = decode_audio(str(wav), sampling_rate=16000)
        spans = get_speech_timestamps(audio, VadOptions(threshold=.6, min_speech_duration_ms=250,
                                                       min_silence_duration_ms=300, speech_pad_ms=80))
        speech_seconds = sum(span['end'] - span['start'] for span in spans) / 16000
        result = {'text': '', 'words': [], 'seconds': len(audio) / 16000,
                  'speech_s': speech_seconds, 'engine': 'cpu ' + self.model_name}
        if speech_seconds >= .25:
            first, last = max(0, spans[0]['start'] - 1600), min(len(audio), spans[-1]['end'] + 1600)
            with self.lock:
                segments, info = self.model.transcribe(audio[first:last], language=language or None,
                                                      beam_size=1, best_of=1, temperature=0,
                                                      word_timestamps=True, vad_filter=False,
                                                      condition_on_previous_text=False)
                words = []
                for segment in segments:
                    if segment.no_speech_prob > .6 or segment.avg_logprob < -1:
                        continue
                    for word in segment.words or []:
                        if word.word.strip():
                            words.append({'w': word.word.strip(), 's': round(word.start + first / 16000, 3),
                                          'e': round(word.end + first / 16000, 3)})
            import letitedit.app.voice_chat as voice_chat
            result.update(words=words, text=voice_chat._join(words))
        else:
            result['skipped'] = 'no sustained speech'
        if video or project:
            import letitedit.app.live_review as live_review
            timeline = json.loads(Path(video).read_text(encoding='utf-8-sig')) if video and Path(video).is_file() else []
            if project and result['words']:
                timeline += self.reference_words(project, ranges or [], language)
            cleaned = live_review.clean(result['words'], timeline, ranges or [])
            result.update(cleaned, review_cleaned=True)
        result['transcribe_s'] = round(time.perf_counter() - started, 4)
        return result
