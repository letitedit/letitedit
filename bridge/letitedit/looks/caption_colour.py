"""Whole-caption Difference/white decisions from native frames at phone size."""
from __future__ import annotations

import copy
import json
import math
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

import letitedit.pictures.caption_readability as ink_check
import letitedit.review.checks as checks
import letitedit.timeline.edit_script as edit_script
from letitedit.looks.look_check import current_project, digest, project_digest


def groups(words):
    result = []
    for index in sorted(range(len(words)), key=lambda value: words[value]['start']):
        word = words[index]
        if result and word['start'] < result[-1]['end'] - 1e-6:
            result[-1]['indices'].append(index)
            result[-1]['end'] = max(result[-1]['end'], word['end'])
        else:
            result.append({'indices': [index], 'start': word['start'], 'end': word['end']})
    return result


def select_colour(minimum, measured, floor):
    return 'difference' if measured and minimum >= floor else 'white'


def shot_policy(project):
    import letitedit.review.brief_check as brief_check
    import letitedit.looks.look_inputs as look_inputs
    import letitedit.looks.looks as looks
    chosen = look_inputs.read(project) or brief_check.load(project=project) or {}
    if not chosen.get('look'):
        return None
    recipe = Path(looks.read(chosen['look'])['recipe'])
    visual = recipe.with_name('visual.json')
    policy = json.loads(visual.read_text(encoding='utf-8-sig')).get('caption_colour_policy') if visual.exists() else None
    if policy is not None and policy != {'mode': 'shot_dependent', 'near_invisible_floor': 1.5,
                                         'majority_fraction': .5}:
        raise ValueError('Unsupported shot-dependent caption policy')
    return policy


def select_shot_colour(near_frames, frames, measured):
    return 'white' if not measured or not frames or near_frames / frames > .5 else 'difference'


def near_invisible(ratios):
    return bool(np.median(ratios) < 1.5)


def fully_on(settings, clock):
    entry = settings.get('entry', .15)
    reveal = settings.get('reveal', 'none')
    moving = (settings.get('from_scale', 1) != 1 or settings.get('from_x', 0)
              or settings.get('from_y', 0))
    entrance = entry if settings.get('fade_in', True) or moving or reveal == 'wipe' else 0
    if reveal == 'letters':
        entrance += max(0, len(settings['text']) - 1) * settings.get('stagger', .018)
    return (settings['start'] + entrance <= clock + 1e-9
            and clock < settings['end'] - settings.get('exit', .08) - 1e-9)


def flash_frames(script, fps):
    excluded = set()
    for track in script['tracks']:
        for item in track['items']:
            for effect in item.get('effects', []):
                if not isinstance(effect, dict):
                    continue
                flash = effect.get('cutaway_negative')
                if not isinstance(flash, dict) or round(flash.get('len', 0) * fps) != 2:
                    continue
                start = round(edit_script.to_seconds(item.get('at', 0)) * fps)
                if flash.get('edge') == 'out':
                    start += round(edit_script.to_seconds(item['len']) * fps) - 2
                elif flash.get('edge') != 'in':
                    continue
                excluded.update((start, start + 1))
    return excluded


def receipt_path(project):
    return Path(project).with_suffix('.caption-colour.json')


def choice_status(project, script=None):
    path = receipt_path(project)
    try:
        receipt = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {'passed': False, 'reason': 'Caption colour choice is missing or unreadable'}
    if isinstance(receipt, dict) and isinstance(receipt.get('result'), dict) and 'key' in receipt:
        receipt = receipt['result']     # a measurement an export kept here before it had its own file
    revision = project_digest(script if script is not None else current_project(project)[2])
    fresh = receipt.get('project_sha256') == revision
    passed = bool(fresh and receipt.get('passed') and receipt.get('coverage') == 'fully_on_native_frames')
    return {'passed': passed, 'fresh': fresh, 'receipt': str(path),
            'reason': '' if passed else ('Caption colour choice is stale; choose again after picture changes'
                                         if not fresh else 'Caption contrast choice has unresolved findings')}


def colour_script(script, decisions):
    import letitedit.pictures.motion as motion
    result = ink_check.without_generated_blend(script)
    tracks = []
    for track in result['tracks']:
        if any(ink_check.edge_item(item) for item in track['items']):
            raise ValueError('Remove old dark-edge companions and restore the intended caption motion first')
        output = []
        white_items = []
        for item in track['items']:
            if not ink_check.caption_item(item):
                output.append(item)
                continue
            params = motion.normalise(item['motion'])['params']
            clean_params(params)
            rows = decisions[item['id']]
            expected = groups(params['words'])
            if [row['indices'] for row in rows] != [group['indices'] for group in expected]:
                raise ValueError('Colour decisions do not cover the current caption groups exactly')
            if any(row['colour'] not in ('difference', 'white') for row in rows):
                raise ValueError('Each caption needs a difference or white decision')
            for mode in ('difference', 'white'):
                indices = {index for row in rows if row['colour'] == mode for index in row['indices']}
                if not indices:
                    continue
                selected = copy.deepcopy(item)
                both = {row['colour'] for row in rows} == {'difference', 'white'}
                selected['id'] = item['id'] + '-' + mode if both else item['id']
                selected['motion']['params'] = copy.deepcopy(params)
                selected_params = selected['motion']['params']
                selected_params['blend'] = 'normal' if mode == 'white' else mode
                selected_params['words'] = [word for index, word in enumerate(params['words']) if index in indices]
                selected_params['phrases'] = []
                (white_items if both and mode == 'white' else output).append(selected)
        track['items'] = output
        tracks.append(track)
        if white_items:
            companion = copy.deepcopy(track)
            companion['name'] += ' white captions'
            companion['items'] = white_items
            tracks.append(companion)
    result['tracks'] = tracks
    return result


def clean_params(params):
    if params.get('blend', 'normal') not in ('normal', 'difference'):
        raise ValueError('Only Difference and normal white compositing are verified')
    if params.get('readability'):
        raise ValueError('Restore lettering without edge aids before selecting caption colour; old aids change motion')
    settings = [params, *params.get('roles', {}).values(), *params['words']]
    for value in settings:
        if value.get('box') or value.get('outline', 0) or value.get('shadow') not in (None, False, 'none'):
            raise ValueError('Inverted-then-white captions have no added box, edge or shadow')
        if value.get('fill', '#ffffff').lower() not in ('#fff', '#ffffff', 'white'):
            raise ValueError('Colour selection needs white source glyphs')
        if value.get('runs'):
            raise ValueError('Run-specific colours are not yet measured')


def _background(path, names, output, frames, height, profile):
    import letitedit.pictures.code_scenes as code_scenes
    import letitedit.core.render_lock as render_lock
    import letitedit.timeline.timeline_model as timeline_model
    with render_lock.slot('caption underlying picture preparation', timeout_s=3600):
        prepared = code_scenes.looks_path(path, span=(0, frames - 1), work=output.parent, native=True)
    notes = output.parent / 'scenes.json'
    if notes.exists():
        import json
        if any(note.get('not_drawn') for note in json.loads(notes.read_text(encoding='utf-8-sig'))):
            raise ValueError('Underlying-picture code scene could not be drawn')
    root = ET.parse(prepared).getroot()
    root.set('root', str(Path(path).parent))
    playlists = {element.get('id') for element in root.findall('playlist')
                 if timeline_model.props(element).get('shotcut:name') in names}
    main = next(element for element in reversed(root.findall('tractor'))
                if timeline_model.props(element).get('shotcut') == '1')
    hidden = set()
    for index, track in enumerate(main.findall('track')):
        if track.get('producer') in playlists:
            track.set('hide', 'both')
            hidden.add(str(index))
    for transition in main.findall('transition'):
        if timeline_model.props(transition).get('b_track') in hidden:
            main.remove(transition)
    xml = output.with_suffix('.mlt')
    ET.ElementTree(root).write(xml, encoding='utf-8', xml_declaration=True)
    command = ['in=0', f'out={frames - 1}', 'vcodec=libx264', 'crf=12', 'preset=fast', 'an=1', 'width=360',
               f'height={height}', f'frame_rate_num={profile["frame_rate_num"]}',
               f'frame_rate_den={profile["frame_rate_den"]}', 'sample_aspect_num=1', 'sample_aspect_den=1',
               'progressive=1', 'display_aspect_num=360', f'display_aspect_den={height}']

    def render():
        with render_lock.slot('caption colour background', timeout_s=3600):
            checks._run([checks.MELT, '-quiet', xml, 'in=0', f'out={frames - 1}', '-consumer',
                         f'avformat:{output}', 'vcodec=libx264', 'crf=12', 'preset=fast', 'an=1',
                         'threads=4', 'real_time=-4', 'width=360', f'height={height}',
                         f'frame_rate_num={profile["frame_rate_num"]}',
                         f'frame_rate_den={profile["frame_rate_den"]}',
                         'sample_aspect_num=1', 'sample_aspect_den=1', 'progressive=1',
                         'display_aspect_num=360', f'display_aspect_den={height}',
                         'terminate_on_pause=1'], timeout=600)
    fps = profile['frame_rate_num'] / profile['frame_rate_den']
    # the picture under the captions, drawn once for each picture: a change to the captions or the sound only, a
    # second check of the same edit, the export's pre-check and a delivered-file check reuse it (picture_key)
    key, reused = ink_check.render_or_reuse(xml, output, frames, fps, command, render)
    capture = cv2.VideoCapture(str(output))
    try:
        if (not capture.isOpened() or int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != frames
                or abs(capture.get(cv2.CAP_PROP_FPS) - fps) > .001):
            raise ValueError('Underlying-picture render is incomplete')
    finally:
        capture.release()
    if not reused:
        ink_check.keep_picture(key, output)
    return key, reused


def _decoder(path, height, first, count, fps, alpha=False, exact=False):
    """ffmpeg giving frames first .. first + count - 1 of `path` at 360 px, counted in frames, not seconds. It seeks
    to half a frame before `first`, so a file whose clock rounds a frame's time (an MKV's milliseconds) and one that
    keeps it exactly (an MP4) give the same frame; a seek to the rounded time itself skipped a frame of the MP4.
    exact=True decodes from the start and picks the frames by number (slower; it never seeks)."""
    seek = [] if exact or first <= 0 else ['-ss', f'{(first - .5) / fps:.6f}']
    picture = f'scale=360:{height}:flags=area'
    if exact:
        picture = f'select=between(n\\,{first}\\,{first + count - 1}),' + picture
    command = [str(checks.FFMPEG), '-hide_banner', '-loglevel', 'error', '-threads', '2', *seek, '-i', str(path),
               '-an', '-vf', picture, '-fps_mode', 'passthrough', '-frames:v', str(count), '-threads', '2',
               '-pix_fmt', 'rgba' if alpha else 'rgb24', '-f', 'rawvideo', '-']
    errors = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
    except BaseException:
        errors.close()
        raise
    process.caption_errors = errors
    return process


def _frame(process, height, channels):
    """The decoder's next frame, or None when it has no more (its error text is then in _error_text)."""
    size = 360 * height * channels
    data = bytearray()
    while len(data) < size:
        block = process.stdout.read(size - len(data))
        if not block:
            return None
        data.extend(block)
    return np.frombuffer(data, np.uint8).reshape(height, 360, channels)


def _error_text(process):
    try:
        process.caption_errors.seek(0)
        return process.caption_errors.read().decode('utf-8', errors='replace')[-2000:]
    except (OSError, ValueError):
        return ''


class _Frames:
    """Frames first .. first + count - 1 of one file, in order. A frame the seeking decoder doesn't give is decoded
    again by number from the start of the file; one neither gives is None: unavailable, never measured or passed."""

    def __init__(self, path, height, first, count, fps, alpha=False):
        self.path, self.height, self.fps, self.alpha = path, height, fps, alpha
        self.first, self.count, self.given, self.exact = first, count, 0, False
        self.channels = 4 if alpha else 3
        self.problems = []
        self.process = _decoder(path, height, first, count, fps, alpha)

    def next(self):
        frame = _frame(self.process, self.height, self.channels) if self.given < self.count else None
        if frame is None and not self.exact and self.given < self.count:
            self.problems.append(_error_text(self.process).strip() or f'the decoder stopped at frame {self.first + self.given}')
            _close(self.process)
            self.exact = True
            self.process = _decoder(self.path, self.height, self.first + self.given, self.count - self.given,
                                    self.fps, self.alpha, exact=True)
            frame = _frame(self.process, self.height, self.channels)
        self.given += 1
        return frame

    def close(self):
        _close(self.process)


def _close(process):
    if process.poll() is None:
        process.terminate()
    process.stdout.close()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    process.caption_errors.close()


def _result(captions, script, video, decoded, floor, policy, unavailable=(), problems=()):
    result = {'passed': all(row['passed'] for rows in captions.values() for row in rows) and not unavailable,
              'project_sha256': project_digest(script), 'video_sha256': digest(video) if video else None,
              'coverage': 'fully_on_native_frames', 'width': 360, 'frames_decoded': decoded, 'floor': floor,
              'captions': captions, 'white_captions': sum(row['colour'] == 'white' for rows in captions.values() for row in rows),
              'method': 'Native alpha glyph cores and final underlying picture at 360px, large-text 3:1. Every fully-on word frame is measured; entrance, exit and exact two-frame cutaway negatives are excluded. Actual delivered ink is checked separately. No box, edge or shadow; white may still fail on a light picture.'}
    if policy:
        result['policy'] = policy
        result['minor_findings'] = [{'severity': 'minor', 'item': identity, 'text': row['text'],
                                     'problem': 'caption nearly invisible for most fully-on frames'}
                                    for identity, rows in captions.items() for row in rows if row['minor_finding']]
        result['method'] = ('Every fully-on native frame at 360px; median glyph-core contrast defines near-invisibility below 1.5:1. '
                            'A cue turns white only when inverted ink is near-invisible on more than half these frames. '
                            'Brief dips are allowed; sustained near-invisibility is minor. Missing ink evidence or wrong stored colour fails. '
                            'Entrance/exit and exact two-frame negatives excluded. No shape or motion change; no box, edge or shadow.')
    result['unavailable_frames'] = len(unavailable)
    if unavailable:
        result['unavailable'] = list(unavailable)[:40]
        result['decode_problems'] = sorted({str(text)[:400] for text in problems})[:4]
        result['reason'] = (f'{len(unavailable)} fully-on frames could not be decoded, even frame by frame from the start '
                            'of the file: they are unavailable, not measured and not passed; every other frame was measured')
    return result


def _measurement_key(picture, script, tracks, flashes, policy, floor, video, timeline, height):
    """What a colour measurement reads, as one key: the picture under the captions (its kept render's key), the caption
    tracks, each caption's glyph render (its file's size and date), the cutaway flashes left out, the Look's policy,
    the floor and the delivered file (its path, size and date). None when a part can't be read: then it measures."""
    import letitedit.pictures.motion as motion
    if not picture:
        return None
    try:
        assets = []
        for track in tracks:
            for item in track['items']:
                if 'id' in item:
                    asset = motion.render(motion.normalise(item['motion']), script['profile']['width'],
                                          script['profile']['height'], timeline.fps, sheet_count=0)['path']
                    assets.append([item['id'], str(asset), ink_check._resource_stamp(asset)])
        delivered = None
        if video:
            stat = Path(video).stat()
            delivered = [str(Path(video).resolve()), stat.st_size, stat.st_mtime_ns]
    except Exception:  # noqa: BLE001 - nothing to key on: measured afresh, as before
        return None
    return ink_check.measurement_key({'kind': 'caption colour', 'picture': picture, 'captions': tracks,
                                      'assets': assets, 'flashes': sorted(flashes), 'policy': policy, 'floor': floor,
                                      'video': delivered, 'frames': timeline.frames, 'fps': timeline.fps,
                                      'height': height, 'profile': script['profile']})


def measure(project, video=None, apply=False, floor=3.):
    import letitedit.core.cache_budget as cache_budget
    import letitedit.looks.kinetic_type as kinetic_type
    import letitedit.pictures.motion as motion
    import letitedit.core.render_lock as render_lock
    import letitedit.server.timeline_tools as timeline_tools
    import yaml
    if apply and video:
        raise ValueError('A delivered-video check cannot also change caption colour')
    cache_budget.need_room(checks.CACHE, 2 * 1024 ** 3, 'caption colour measurement', cache=checks.CACHE)
    _, path, script = current_project(project)
    policy = shot_policy(project)
    timeline, path = checks.resolve(path)
    tracks = [track for track in script['tracks'] if any(ink_check.caption_item(item) for item in track['items'])]
    if not tracks or any(any('id' in item and not ink_check.caption_item(item) for item in track['items']) for track in tracks):
        raise ValueError('Colour selection needs dedicated kinetic_type tracks')
    if any(ink_check.edge_item(item) for track in script['tracks'] for item in track['items']):
        raise ValueError('Old edge companions are not part of inverted-then-white captions')
    if any(track.get('effects') for track in tracks):
        raise ValueError('Caption track effects need an independently transformed mask')
    height = round(script['profile']['height'] * 360 / script['profile']['width'] / 2) * 2
    if video:
        capture = cv2.VideoCapture(str(video))
        try:
            if abs(capture.get(cv2.CAP_PROP_FPS) - timeline.fps) > .001 or int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) != timeline.frames:
                raise ValueError('Delivered frame count/rate differs from the current timeline')
        finally:
            capture.release()
    captions = {}
    decoded = 0
    unavailable = []        # fully-on frames no decoder gave: never measured, never a pass
    problems = []
    flashes = flash_frames(script, timeline.fps)
    checks.CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='caption-colour-', dir=checks.CACHE) as folder:
        background = Path(folder) / 'background.mkv'
        under, _ = _background(path, {track['name'] for track in tracks}, background, timeline.frames, height,
                               timeline.profile)
        memory = _measurement_key(under, script, tracks, flashes, policy, floor, video, timeline, height)
        kept = ink_check.kept_measurement(memory) if memory else None
        for track in ([] if kept else tracks):
            for item in track['items']:
                if 'id' not in item:
                    continue
                if 'motion' not in item:
                    raise ValueError('Only kinetic_type colour selection is verified')
                spec = motion.normalise(item['motion'])
                params = spec['params']
                clean_params(params)
                if any(effect.get('filter') != 'cairoblend_mode' for effect in item.get('effects', [])):
                    raise ValueError('Additional caption effects need a native transformed glyph mask')
                rows = groups(params['words'])
                if not rows:
                    raise ValueError('No timed caption words to measure')
                for row in rows:
                    row.update(text=' '.join(params['words'][index]['text'] for index in row['indices']),
                               frames=0, minimum_difference=21., minimum_white=21.,
                               actual_minimum=21., unmeasured_frames=0, excluded_entrance_exit=0,
                               excluded_flash_frames=0, fully_on_frames=0, near_difference_frames=0,
                               near_white_frames=0, near_actual_frames=0, colourful_frames=0,
                               unavailable_frames=0, measured_words={index: 0 for index in row['indices']})
                bounds = []
                word_settings = []
                for word in params['words']:
                    settings = dict(x=.5, y=.5, size=.05, font=params['font'], align='center')
                    settings.update(params.get('roles', {}).get(word.get('role'), {}))
                    settings.update(word)
                    word_settings.append(settings)
                    if settings['align'] != 'center':
                        raise ValueError('Non-centred word bounds are unverified')
                    bounds.append(kinetic_type.envelope(settings, script['profile']['width'], script['profile']['height']))
                asset = motion.render(spec, script['profile']['width'], script['profile']['height'],
                                      timeline.fps, sheet_count=0)['path']
                at = edit_script.to_seconds(item['at'])
                skip = edit_script.to_seconds(item.get('skip', 0))
                count = round(item['len'] * timeline.fps)
                first = round(at * timeline.fps)
                streams = []
                try:
                    with render_lock.slot('caption colour native-frame scan', timeout_s=3600):
                        streams.append(_Frames(background, height, first, count, timeline.fps))
                        streams.append(_Frames(asset, height, round(skip * timeline.fps), count, timeline.fps, True))
                        if video:
                            streams.append(_Frames(video, height, first, count, timeline.fps))
                        for frame_index in range(count):
                            frames = [stream.next() for stream in streams]
                            clock = frame_index / timeline.fps + skip + params.get('offset', 0)
                            active = [row for row in rows if row['start'] <= clock < row['end']]
                            if first + frame_index in flashes:
                                for row in active:
                                    row['excluded_flash_frames'] += 1
                                decoded += 1
                                continue
                            if not active:
                                decoded += 1
                                continue
                            if any(frame is None for frame in frames):
                                for row in active:
                                    row['unavailable_frames'] += 1
                                missing = next(index for index, frame in enumerate(frames) if frame is None)
                                unavailable.append({'item': item['id'], 'frame': first + frame_index,
                                                    'at_s': round((first + frame_index) / timeline.fps, 3),
                                                    'file': str([background, asset, video][missing])})
                                continue
                            picture = frames[0]
                            alpha = frames[1][..., 3].astype(np.float32) / 255
                            actual = frames[2] if video else None
                            picture_luma = ink_check.luminance(picture[..., ::-1])
                            inverted_luma = ink_check.luminance((255 - picture)[..., ::-1])
                            for row in active:
                                row['frames'] += 1
                                glyphs = np.zeros(alpha.shape, bool)
                                for index in row['indices']:
                                    word = params['words'][index]
                                    if not word['start'] <= clock < word['end']:
                                        continue
                                    if not fully_on(word_settings[index], clock):
                                        row['excluded_entrance_exit'] += 1
                                        continue
                                    left, top, right, bottom = bounds[index]
                                    region = np.zeros(alpha.shape, bool)
                                    region[max(0, int(top * height)):min(height, math.ceil(bottom * height)),
                                           max(0, int(left * 360)):min(360, math.ceil(right * 360))] = True
                                    peak = float(alpha[region].max()) if region.any() else 0.
                                    core = region & (alpha >= max(.05, peak * .9))
                                    if not core.any():
                                        row['unmeasured_frames'] += 1
                                        continue
                                    row['measured_words'][index] += 1
                                    glyphs |= core
                                    row['minimum_difference'] = min(row['minimum_difference'], float(ink_check.ratios(inverted_luma[core], picture_luma[core]).min()))
                                    row['minimum_white'] = min(row['minimum_white'], float(ink_check.ratios(1., picture_luma[core]).min()))
                                    if actual is not None:
                                        contrast = ink_check.ratios(ink_check.luminance(actual[..., ::-1])[core], picture_luma[core])
                                        row['actual_minimum'] = min(row['actual_minimum'], float(contrast.min()))
                                if glyphs.any():
                                    row['fully_on_frames'] += 1
                                    row['near_difference_frames'] += int(near_invisible(ink_check.ratios(inverted_luma[glyphs], picture_luma[glyphs])))
                                    row['near_white_frames'] += int(near_invisible(ink_check.ratios(1., picture_luma[glyphs])))
                                    row['colourful_frames'] += int(np.mean(np.ptp(picture[glyphs].astype(float), axis=1) > 35) >= .2)
                                    if actual is not None:
                                        row['near_actual_frames'] += int(near_invisible(ink_check.ratios(ink_check.luminance(actual[..., ::-1])[glyphs], picture_luma[glyphs])))
                            decoded += 1
                finally:
                    for stream in streams:
                        problems.extend(stream.problems)
                        stream.close()
                for row in rows:
                    measured = bool(row['frames'] and row['fully_on_frames'] and not row['unmeasured_frames'] and
                                    all(row['measured_words'].values()))
                    row['colour'] = select_colour(row['minimum_difference'], measured, floor)
                    if policy:
                        row['colour'] = select_shot_colour(row['near_difference_frames'], row['fully_on_frames'], measured)
                    row['minimum'] = row['minimum_white' if row['colour'] == 'white' else 'minimum_difference']
                    row['passed'] = bool(measured and row['minimum'] >= floor)
                    if policy:
                        row['passed'] = measured
                    row['actual_minimum'] = row['actual_minimum'] if video else None
                    row['stored_colour'] = 'white' if params.get('blend') == 'normal' else params.get('blend')
                    if video and row['stored_colour'] != row['colour']:
                        row['passed'] = False
                    if video and not policy and row['actual_minimum'] < floor:
                        row['passed'] = False
                    if row['unavailable_frames']:
                        row['passed'] = False       # a frame no decoder gave is unavailable, never a pass
                    near_count = row['near_actual_frames'] if video else row['near_white_frames' if row['colour'] == 'white' else 'near_difference_frames']
                    row['near_invisible_share'] = near_count / row['fully_on_frames'] if row['fully_on_frames'] else None
                    row['minor_finding'] = bool(policy and measured and row['near_invisible_share'] > .5)
                captions[item['id']] = rows
    if kept:
        result = {**kept, 'project_sha256': project_digest(script), 'video_sha256': digest(video) if video else None,
                  'reused': "the same picture, captions and file were measured before: these are that measurement's "
                            'numbers'}
        captions = result['captions']
    else:
        result = _result(captions, script, video, decoded, floor, policy, unavailable, problems)
        if memory and not unavailable:
            ink_check.keep_measurement(memory, result)
    if apply:
        changed = colour_script(script, captions)
        result['changed'] = timeline_tools.apply_project(project, script_yaml=yaml.safe_dump(changed, sort_keys=False),
                                                        label='Whole-caption inverted or white lettering')[0]
        result['project_sha256'] = project_digest(current_project(project)[2])
        receipt = receipt_path(project)
        temporary = receipt.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
        temporary.replace(receipt)
    return result
