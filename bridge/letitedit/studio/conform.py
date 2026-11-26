"""Technical delivery of a finished video: no AI, cutting, cropping or reframing."""
from __future__ import annotations

import copy
import math
from pathlib import Path

import letitedit.core.media as media
import letitedit.studio.capabilities as capabilities
import letitedit.studio.delivery as delivery
import letitedit.studio.files as files
import letitedit.studio.media_privacy as privacy
import letitedit.studio.overlays as overlays
import letitedit.studio.state as state

RUN_FILE = 'conform-run.json'


def _save(ctx, run):
    files.write_json(Path(ctx.dir) / RUN_FILE, run)


def _load(ctx):
    return files.read_json(Path(ctx.dir) / RUN_FILE) or {}


def _rel(folder, path):
    return Path(path).relative_to(folder).as_posix()


def _earlier(job):
    import letitedit.studio.service as service
    folder = service.find(service.home(), job['from_job'])
    before = files.read_json(folder / 'result.json') if folder else None
    if not before or before.get('state') != 'done':
        raise state.StudioError('from_job_unusable', 'Conform needs a finished job with a main video.')
    for entry in (before.get('output') or {}).get('files') or []:
        if entry.get('status') != 'made' or not entry.get('video'):
            continue
        source = (folder / entry['video']).resolve()
        if not source.is_relative_to(folder.resolve()) or not source.is_file():
            raise state.StudioError('from_job_unusable', 'The earlier main video is missing or outside its job folder.')
        return source, folder, before
    raise state.StudioError('from_job_unusable', 'The earlier job has no made main video; a proxy is not a final.')


def _settings(job):
    inputs = job.get('inputs') or {}
    for name, default, low, high in [('fps', 30, 1, 120), ('loudness_lufs', -14, -70, -5),
                                    ('true_peak_dbtp', -1, -20, 0)]:
        value = inputs.get(name, default)
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise state.StudioError('invalid_job', f'{name} must be between {low} and {high}.')
    return inputs


def probe(ctx, job_dir, job, attempt, check=lambda: None):
    check()
    inputs = _settings(job)
    before, earlier_folder = {}, None
    if job.get('from_job'):
        source, earlier_folder, before = _earlier(job)
    else:
        source = Path(inputs.get('video') or '')
    info = delivery.probe(source)
    if not info or not info.get('width') or not info.get('duration_s') or not info.get('fps'):
        raise state.StudioError('source_unreadable', 'Conform needs a readable finished video with a duration.')
    unknown_matrix = ((info.get('matrix') or '').startswith('bt2020') and
                      info.get('transfer') not in delivery.SDR_TRANSFERS | delivery.HDR_TRANSFERS.keys())
    if delivery.hdr_of(info) == 'unknown' or unknown_matrix:
        raise state.StudioError('hdr_not_supported', 'This wide-colour video does not identify its transfer curve. '
                                'Conform needs a tagged HLG, PQ or SDR file to make SDR safely.')
    at = inputs.get('cover_at_s')
    if at is not None and (not math.isfinite(at) or not 0 <= at < info['duration_s']):
        raise state.StudioError('invalid_job', 'cover_at_s must be inside the video.')
    lufs, peak = delivery.loudness(source) if info.get('has_audio') else (None, None)
    if info.get('has_audio') and (lufs is None or (peak is None and lufs > -69.9)):
        raise state.StudioError('render_failed', 'Conform could not measure the source audio; nothing was delivered.')
    summary = {'path': str(source), 'sha256': files.sha256_file(source),
               **{key: info[key] for key in ('width', 'height', 'fps', 'bytes')}, 'hdr': delivery.hdr_of(info)}
    if lufs is not None and peak is not None:
        summary['loudness_lufs'] = lufs
    _save(ctx, {'source': summary, 'info': info, 'before': before,
                'earlier_folder': str(earlier_folder) if earlier_folder else None,
                'source_peak': peak, 'made': [], 'outs': [], 'warnings': []})


def _audio(source, folder, inputs, check):
    from letitedit.timeline.render_queue import Worker

    class Finisher(Worker):
        def __init__(self):
            self.dir = folder

        def ffmpeg(self, args):
            check()
            return delivery._run([media.ffmpeg(), '-nostdin', *args], 'conform sound')

        def measure_loudness(self, path):
            check()
            return delivery.loudness(path)

    finisher = Finisher()
    wav = folder / 'source.wav'
    finisher.ffmpeg(['-y', '-v', 'error', '-i', str(source), '-map', '0:a:0', '-vn', '-ar', '48000',
                    '-c:a', 'pcm_f32le', str(wav)])
    target, peak_max = inputs.get('loudness_lufs', -14), inputs.get('true_peak_dbtp', -1)
    ceiling, audio = peak_max - 1, folder / 'finished.m4a'
    for attempt in range(4):
        check()
        finished, report = finisher.finish_loudness(wav, target, ceiling=ceiling)
        finisher.ffmpeg(['-y', '-v', 'error', '-i', str(finished), '-c:a', 'aac', '-b:a',
                        f'{delivery.AUDIO_KBPS}k', '-ar', '48000', '-map_metadata', '-1', str(audio)])
        lufs, peak = finisher.measure_loudness(audio)
        if lufs is not None and peak is not None and abs(lufs - target) <= 0.5 and peak <= peak_max:
            return audio
        if peak is not None and peak > peak_max:
            ceiling -= peak - peak_max + 0.3
    raise state.StudioError('render_failed', 'Conform could not meet the requested loudness and true peak. '
                            'No platform files were delivered.', detail=f'LUFS={lufs}, dBTP={peak}, {report}')


def _targets(inputs):
    presets = {entry['id']: entry for entry in capabilities.platforms_list()}
    for raw in inputs['platforms']:
        target = raw if isinstance(raw, dict) else {'id': raw}
        preset = presets.get(target['id'])
        if not preset:
            raise state.StudioError('platform_unknown', f"Unknown platform: {target['id']}.")
        cap = target.get('max_mb', (inputs.get('max_mb') or {}).get(target['id']))
        caps = [value for value in (preset.get('max_bytes'), cap * 1_000_000 if cap else None) if value]
        yield target['id'], preset, int(min(caps)) if caps else None


def _check_delivery(path):
    delivery.check_sdr(path)
    info = delivery.probe(path) or {}
    if any(info.get(key) != 'bt709' for key in ('transfer', 'primaries', 'matrix')):
        Path(path).unlink(missing_ok=True)
        raise state.StudioError('hdr_not_delivered', 'The delivered SDR video is missing its BT.709 colour tags.')


def encode(ctx, job_dir, job, attempt, check=lambda: None):
    check()
    run, inputs = _load(ctx), _settings(job)
    source, info = Path(run['source']['path']), run['info']
    if files.sha256_file(source) != run['source']['sha256']:
        raise state.StudioError('source_unreadable', 'The source changed after conform probed it; submit a new job.')
    folder = Path(job_dir) / 'work'
    folder.mkdir(parents=True, exist_ok=True)
    accepted, made, outs = [], [], []
    for platform, preset, cap in _targets(inputs):
        width, height = preset['width'], preset['height']
        message, reason = None, None
        if abs(info['width'] / info['height'] / (width / height) - 1) > 0.005 and inputs.get('fit', 'refuse') != 'pad':
            reason = 'shape_differs'
            message = f'This video is {info["width"]}x{info["height"]}; {platform} is {width}x{height}. '
            message += 'Conform never crops; request fit: pad to keep the whole picture.'
        elif preset.get('max_seconds') and info['duration_s'] > preset['max_seconds']:
            reason = 'too_long'
            message = f'too_long_for_platform: {platform} allows {preset["max_seconds"]:g} s; '
            message += f'this video is {info["duration_s"]:g} s. Conform never trims.'
        if reason:
            made.append({'platform': platform, 'status': 'refused', 'reason': reason, 'message': message})
        else:
            accepted.append((platform, preset, cap))
    audio = None
    if accepted and info.get('has_audio') and run.get('source_peak') is not None:
        audio = _audio(source, folder, inputs, check)
    elif accepted and info.get('has_audio'):
        run['warnings'].append({'code': 'silent_audio', 'message': 'No measurable sound; silence kept.'})
    for platform, preset, cap in accepted:
        check()
        dst = Path(job_dir) / 'files' / f'{platform}.mp4'
        result = delivery.fit_under(source, dst, preset['width'], preset['height'], inputs.get('fps', 30), cap,
                                    what=f'the {platform} conform', audio_file=audio)
        if result['status'] == 'refused':
            made.append({'platform': platform, 'status': 'refused', 'reason': result['reason'], 'message': result['why']})
            continue
        privacy.ensure_clean(dst)
        _check_delivery(dst)
        if cap and dst.stat().st_size > cap:
            dst.unlink()
            made.append({'platform': platform, 'status': 'refused', 'reason': 'cannot_fit_size',
                         'message': 'The cleaned delivery exceeds the platform size cap.'})
            continue
        details = delivery.describe(dst, platform)
        if preset.get('max_seconds') and details.get('duration_s', 0) > preset['max_seconds']:
            dst.unlink()
            made.append({'platform': platform, 'status': 'refused', 'reason': 'too_long',
                         'message': 'too_long_for_platform: encoded frame or audio padding exceeds the length cap.'})
            continue
        if audio and (abs(details.get('loudness_lufs', -100) - inputs.get('loudness_lufs', -14)) > 0.5 or
                      details.get('true_peak_dbtp', 1) > inputs.get('true_peak_dbtp', -1)):
            dst.unlink()
            raise state.StudioError('render_failed', 'The delivered audio failed its loudness check.')
        made.append({'platform': platform, 'status': 'made', 'video': _rel(job_dir, dst),
                     'tonemapped': result['tonemapped']})
        outs.append(files.output_entry(job_dir, _rel(job_dir, dst), 'video', location_metadata='none', **details))
        run.update(made=made, outs=outs)
        _save(ctx, run)
    order = [target['id'] if isinstance(target, dict) else target for target in inputs['platforms']]
    made.sort(key=lambda entry: order.index(entry['platform']))
    run.update(made=made, outs=outs)
    _save(ctx, run)


def _cover_time(source, duration, folder, check):
    from PIL import Image, ImageFilter, ImageStat
    best, best_score = 0.0, -1.0
    for index in range(12):
        check()
        at = min(3.0, duration) * index / 12
        candidate = delivery.frame(source, at, folder / f'candidate-{index}.jpg', width=320)
        with Image.open(candidate) as image:
            score = ImageStat.Stat(image.convert('L').filter(ImageFilter.FIND_EDGES)).var[0]
        if score > best_score:
            best, best_score = at, score
    return best


def cover(ctx, job_dir, job, attempt, check=lambda: None):
    run = _load(ctx)
    source = next((Path(job_dir) / item['video'] for item in run['made'] if item['status'] == 'made'),
                  Path(run['source']['path']))
    at = (job.get('inputs') or {}).get('cover_at_s')
    at = at if at is not None else _cover_time(source, run['info']['duration_s'], Path(job_dir) / 'work', check)
    for item in run['made']:
        check()
        if item['status'] != 'made':
            continue
        dst = Path(job_dir) / 'files' / f'{item["platform"]}-cover.jpg'
        video = Path(job_dir) / item['video']
        delivery.frame(video, at, dst, width=(delivery.probe(video) or {})['width'])
        privacy.ensure_clean(dst)
        item['cover'] = _rel(job_dir, dst)
        run['outs'].append(files.output_entry(job_dir, item['cover'], 'cover', location_metadata='none'))
    run['cover_at_s'] = at
    _save(ctx, run)


def proxy(ctx, job_dir, job, attempt, check=lambda: None):
    from letitedit.studio.library import file_id
    check()
    run = _load(ctx)
    before = run['before']
    source = next((Path(job_dir) / item['video'] for item in run['made'] if item['status'] == 'made'),
                  Path(run['source']['path']))
    video, poster = Path(job_dir) / 'proxy/proxy.mp4', Path(job_dir) / 'proxy/poster.jpg'
    result = delivery.proxy(source, video, poster, at_s=run['cover_at_s'])
    for path in (video, poster):
        check()
        privacy.ensure_clean(path)
    _check_delivery(video)
    extra = overlays.carry_media(before)
    extra.setdefault('provenance', {'sources': [{'path': run['source']['path'],
                                               'file_id': file_id(run['source']['path']), 'in': 0,
                                               'out': run['info']['duration_s'], 'at': 0, 'role': 'main'}], 'assets': []})
    if 'rules' in before:
        extra['rules'] = copy.deepcopy(before['rules'])
        for rule in extra['rules']:
            for frame in rule.get('frames') or []:
                old = (Path(run['earlier_folder']) / frame['path']).resolve()
                if not old.is_relative_to(Path(run['earlier_folder']).resolve()) or not old.is_file():
                    raise state.StudioError('from_job_unusable', 'Earlier rule evidence is missing or outside its folder.')
                dst = Path(job_dir) / 'evidence' / f'{files.sha256_file(old)[:12]}-{old.name}'
                dst.parent.mkdir(parents=True, exist_ok=True)
                privacy.copy_clean(old, dst)
                frame['path'] = _rel(job_dir, dst)
                run['outs'].append(files.output_entry(job_dir, frame['path'], 'evidence', location_metadata='none'))
    extra['proxy'] = {'video': _rel(job_dir, video), 'poster': _rel(job_dir, poster),
                      'width': result['width'], 'height': result['height'], 'bytes': video.stat().st_size}
    run['outs'] += [files.output_entry(job_dir, _rel(job_dir, video), 'proxy', location_metadata='none',
                                      **delivery.describe(video)),
                    files.output_entry(job_dir, _rel(job_dir, poster), 'poster', location_metadata='none')]
    return {'__result__': True, 'output': {'source': run['source'], 'files': run['made']}, 'extra': extra,
            'outputs': run['outs'], 'warnings': run['warnings'],
            'cost': {'tokens': dict(input=0, cache_write=0, cache_read=0, output=0, total=0),
                     'steps': 0, 'usd_api_equivalent': 0, 'measured': True}}


STAGES = [('probe', probe), ('encode', encode), ('cover', cover), ('proxy', proxy)]
