"""Private reference/result evidence; measured deltas are not editorial scores."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess
import letitedit.looks.broll_evidence as broll_evidence

PARTS = {
    'cutting': ('pacing', ('cuts_per_min', 'shot_len_p25_s', 'shot_len_median_s', 'shot_len_p75_s',
                            'jump_cut_share', 'transition_kinds')),
    'captions': ('captions', ('captions', 'caption_fonts', 'caption_font_weight', 'caption_words',
                              'caption_lines', 'caption_case', 'caption_zone', 'caption_y', 'caption_line_h',
                              'caption_width', 'caption_fill', 'caption_outline', 'caption_outline_px',
                              'caption_plate', 'caption_highlight', 'caption_entry', 'caption_entry_ms')),
    'zooms': ('zooms', ('punches_per_min', 'punch_scale', 'push_ins_per_min')),
    'stickers': ('overlays', ('overlays_per_min', 'overlay_zone', 'overlay_size', 'overlay_len_s',
                              'overlay_entry', 'text_pops_per_min')),
    'colour': ('look', ('brightness', 'contrast', 'saturation', 'warmth', 'grain', 'vignette')),
    'music': ('sound.music', ('tempo_bpm', 'music_share', 'beat_quality', 'cuts_on_beat',
                              'music_under_voice_db', 'ducking_db')),
    'loudness': ('sound.loudness', ('loudness_lufs',)),
    'sound_effects': ('sound.sfx', ('sfx_per_min', 'sfx_kinds', 'sfx_at_cuts', 'sfx_at_overlays')),
    'b_roll': ('pacing', ('cutaway_share', 'talking_head')),
    'opening': ('hook', ('hook_talks_at_once', 'hook_text_at_once', 'hook_moves', 'hook_sfx')),
    'ending': ('ending', ('ending_cta', 'ending_loops')),
}


def _get(report, path):
    value = report
    for key in path.split('.'):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _present(report, path):
    value = _get(report, path)
    return value is not None and not (isinstance(value, dict) and (not value or value.get('error')))


FACT_SOURCES = {
    'jump_cut_share': 'pacing.cut_kinds', 'transition_kinds': 'pacing.transitions',
    'push_ins_per_min': 'pacing.push_ins', 'captions': 'captions.present',
    'caption_fonts': 'captions.font_guess', 'caption_highlight': 'captions.highlight.present',
    'overlays_per_min': 'overlays.events', 'text_pops_per_min': 'overlays.events',
    'sfx_kinds': 'sound.sfx.kinds', 'hook_moves': 'hook.cuts',
    'hook_sfx': 'hook.sfx', 'ending_cta': 'ending.call_to_action',
}


def compare(reference, result):
    from letitedit.looks.style_import_write import facts
    reference_facts, result_facts = facts(reference), facts(result)
    parts = {}
    for part, (source, keys) in PARTS.items():
        metrics = {}
        for key in keys:
            evidence_source = FACT_SOURCES.get(key, source)
            before = reference_facts.get(key) if _present(reference, evidence_source) else None
            after = result_facts.get(key) if _present(result, evidence_source) else None
            numeric = all(type(value) in (int, float) and math.isfinite(value) for value in (before, after))
            metrics[key] = {'reference': before, 'result': after,
                            'delta': round(after - before, 4) if numeric else None,
                            'status': 'measured' if before is not None and after is not None else 'unmeasured'}
        parts[part] = {'metrics': metrics, 'critic_score': None,
                       'note': 'Detector estimates, not a visual or listening verdict.'}
    energy = [_get(report, 'sound.music.energy') for report in (reference, result)]
    available = [value if isinstance(value, dict) and value.get('available') is not False else None
                 for value in energy]
    parts['music']['energy_curve'] = {
        'reference': available[0], 'result': available[1],
        'status': 'measured' if all(value is not None for value in available) else 'unmeasured',
        'note': 'Separated-stem RMS only, not musical semantics. Listen for rises, drops and resolves.',
    }
    parts['music']['whole_mix_energy'] = {
        'reference': _get(reference, 'sound.mix_energy'),
        'result': _get(result, 'sound.mix_energy'),
        'note': 'Whole soundtrack includes speech and effects; never evidence of music-only energy.',
    }
    import letitedit.looks.typography_match as typography_match
    parts['captions']['typography'] = typography_match.pairs(reference, result)
    parts['b_roll'] = broll_evidence.compare(reference, result)
    return parts


def _run(arguments, timeout=300):
    try:
        return subprocess.run([str(item) for item in arguments], capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout, check=True)
    except subprocess.CalledProcessError as error:
        raise ValueError(f'comparison command failed ({error.returncode}): {error.stderr[-4000:]}') from error
    except subprocess.TimeoutExpired as error:
        raise ValueError(f'comparison command exceeded {timeout} seconds') from error


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
def render_pair(reference, result, out):
    import letitedit.core.render_lock as render_lock
    from PIL import Image, ImageDraw
    app = _paths.CODE_ROOT / 'app'
    paths = [Path(report['file']).resolve(strict=True) for report in (reference, result)]
    info = []
    for path in paths:
        info.append(json.loads(_run([app / 'ffprobe.exe', '-v', 'error', '-show_streams',
                                     '-show_format', '-of', 'json', path]).stdout))
    durations = [float(item['format']['duration']) for item in info]
    duration = max(durations)
    filters = []
    for index in range(2):
        filters.append(f'[{index}:v]setpts=PTS-STARTPTS,fps=30,scale=480:640:force_original_aspect_ratio=decrease,'
                       f'pad=480:640:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=add:stop_duration={duration},'
                       f'trim=duration={duration}[v{index}]')
        if any(stream['codec_type'] == 'audio' for stream in info[index]['streams']):
            filters.append(f'[{index}:a:0]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=mono,'
                           f'apad,atrim=duration={duration}[a{index}]')
        else:
            filters.append(f'anullsrc=r=48000:cl=mono,atrim=duration={duration}[a{index}]')
    labels = out / 'comparison-labels.png'
    with Image.new('RGB', (960, 28), 'black') as image:
        draw = ImageDraw.Draw(image)
        draw.text((12, 7), 'REFERENCE - left audio', fill='white')
        draw.text((492, 7), 'RESULT - right audio', fill='white')
        image.save(labels)
    filters.extend(('[v0][v1]hstack=inputs=2[pair]', '[pair][2:v]overlay=0:0:shortest=1[video]',
                    '[a0][a1]join=inputs=2:channel_layout=stereo[audio]'))
    video = out / 'side-by-side-private.mp4'
    frames = out / 'frames-1fps'
    frames.mkdir(exist_ok=True)
    with render_lock.slot('learned-Look private comparison', timeout_s=3600):
        _run([app / 'ffmpeg.exe', '-y', '-v', 'error', '-threads', '4', '-filter_complex_threads', '1',
              '-i', paths[0], '-i', paths[1], '-loop', '1', '-i', labels,
              '-filter_complex', ';'.join(filters), '-map', '[video]',
              '-map', '[audio]', '-t', str(duration), '-c:v', 'libx264', '-threads', '4',
              '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-movflags', '+faststart', video])
        _run([app / 'ffmpeg.exe', '-y', '-v', 'error', '-threads', '4', '-i', video,
              '-vf', r'select=not(mod(n\,30)),scale=640:-2', '-fps_mode', 'vfr',
              '-threads', '4', frames / '%05d.jpg'])
    images = [frames / f'{index + 1:05d}.jpg' for index in range(math.ceil(duration))]
    images = [image for image in images if image.is_file()]
    pages = []
    for offset in range(0, len(images), 6):
        with Image.open(images[offset]) as first:
            height = first.height + 26
        page = Image.new('RGB', (1280, height * 3), '#151515')
        draw = ImageDraw.Draw(page)
        for index, image in enumerate(images[offset:offset + 6]):
            left, top = index % 2 * 640, index // 2 * height
            with Image.open(image) as tile:
                page.paste(tile, (left, top + 26))
            draw.text((left + 8, top + 6), f'{offset + index}s - reference left / result right', fill='white')
        target = out / f'1fps-page-{offset // 6 + 1:02d}.jpg'
        page.save(target)
        page.close()
        pages.append(str(target))
    return {'video': str(video), 'pages': pages, 'durations_s': durations,
            'audio': 'Reference in LEFT headphone; result in RIGHT. Listen separately to the originals.',
            'timing': 'Same elapsed second, not event-aligned. The shorter picture becomes black after its end.',
            'privacy': 'Internal reference analysis only. Never publish or commit this video or its pages.'}


def bundle(reference, result, out, render=False, scores=None):
    if not all(isinstance(value, str) and value for value in (reference, result, out)):
        raise ValueError('match requires reference/result importer report paths and out folder')
    reports = [json.loads(Path(path).read_text(encoding='utf-8-sig')) for path in (reference, result)]
    if not all(isinstance(report, dict) and isinstance(report.get('file'), str) and report['file']
               and type(report.get('duration_s')) in (int, float)
               and math.isfinite(report['duration_s']) and report['duration_s'] > 0
               for report in reports):
        raise ValueError('both inputs must be importer reports with file and duration_s')
    directory = Path(out)
    for report in reports:
        broll_evidence.measure(report, verify_media=True)
    directory.mkdir(parents=True, exist_ok=True)
    fingerprints = [hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (reference, result)]
    evidence = {'format': 'letitedit-look-match/1', 'report_sha256': fingerprints,
                'reference': str(Path(reference).resolve()), 'result': str(Path(result).resolve()),
                'parts': compare(*reports), 'critic': None, 'verdict': 'incomplete'}
    if scores is not None:
        if not isinstance(scores, dict):
            raise ValueError('critic scores must be an object')
        if scores.get('report_sha256') != fingerprints:
            raise ValueError('critic scores must name this exact pair of report_sha256 hashes')
        if not all(isinstance(scores.get(key), str) and scores[key].strip()
                   for key in ('engine', 'model', 'effort')):
            raise ValueError('critic needs engine, model and effort')
        if not isinstance(scores.get('parts'), dict) or set(scores['parts']) != set(PARTS):
            raise ValueError('critic must assess every part, using null for unassessed scores')
        for part, assessment in scores['parts'].items():
            if not isinstance(assessment, dict):
                raise ValueError(f'{part}: assessment must be an object')
            score = assessment.get('score')
            if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 10):
                raise ValueError(f'{part}: score must be 0-10 or null')
            if not isinstance(assessment.get('evidence'), str) or not assessment['evidence'].strip():
                raise ValueError(f'{part}: timestamped evidence or unassessed reason required')
            if (not isinstance(assessment.get('limitations'), list)
                    or not all(isinstance(item, str) for item in assessment['limitations'])):
                raise ValueError(f'{part}: limitations list required')
            evidence['parts'][part]['critic_score'] = score
            if part == 'captions':
                import letitedit.looks.typography_match as typography_match
                evidence['parts'][part]['typography']['subparts'] = typography_match.validate_scores(assessment)
        evidence['critic'] = scores
        evidence['verdict'] = 'assessed' if all(item['score'] is not None for item in scores['parts'].values()) else 'incomplete'
    previous = directory / 'match.json'
    if previous.is_file():
        stored = json.loads(previous.read_text(encoding='utf-8-sig'))
        if stored.get('report_sha256') == fingerprints and stored.get('comparison'):
            evidence['comparison'] = stored['comparison']
    if render:
        evidence['comparison'] = render_pair(*reports, directory)
    import letitedit.looks.typography_match as typography_match
    text_evidence = typography_match.sheets(*reports, directory)
    if scores is not None:
        typography_match.validate_evidence(scores['parts']['captions'], text_evidence)
    text_evidence['subparts'] = evidence['parts']['captions']['typography']['subparts']
    evidence['parts']['captions']['typography'] = text_evidence
    (directory / 'match.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding='utf-8')
    prompt = ('Independently compare the reference and result. Does this look and feel like the reference, part by part?\n'
              'Read match.json and every ordered 1fps page; inspect denser frames at caption/zoom/cut boundaries.\n'
              'Listen separately to the two originals; stereo comparison is reference left / result right.\n'
              'Score each part 0-10 with reference/result timecodes, evidence, what did not carry over and why.\n'
              'Return null when a part cannot be assessed; detector agreement alone earns no score.\n'
              'For captions inspect every role/phase text-private page and its dense source crops, not just 1fps.\n'
              'Compare emphasis with emphasis and linking with linking. Check full frames for position/overlap.\n'
              'Captions must include text_parts:{fonts,sizes,layout,colour,movement}, each {score,evidence,limitations}.\n'
              'The caption total must not exceed its weakest text sub-score; any unknown prevents a total.\n'
              'A similar blue or a simple uniform pop is not a match for a multi-role kinetic type system.\n'
              'Judge the editing grammar, not whether the two videos have the same people or subject.\n'
              'For b-roll use the export-bound semantic shot log, not face absence. Judge the line job, '
              'rhythm and visual richness separately from coverage share; made/stock shots are illustrations, '
              'not evidence that an event happened. Missing shot logs mean unassessed coverage.\n'
              'Parts: ' + ', '.join(PARTS) + '. Record engine/model/effort and report_sha256 from match.json.\n'
              'Output JSON: {report_sha256,engine,model,effort,parts:{part:{score,evidence,limitations:[text]}}}.\n'
              'Private analysis only. Do not copy source assets or publish/commit the comparison.\n')
    (directory / 'critic-brief.txt').write_text(prompt, encoding='utf-8')
    return {'match': str(directory / 'match.json'), 'critic_brief': str(directory / 'critic-brief.txt'),
            'verdict': evidence['verdict'], 'comparison': evidence.get('comparison')}
