"""Learn's reference measurements, with no pack writer or personal publication."""
from pathlib import Path

from letitedit.looks import style_import


def inputs(reference=None, package=None):
    package = package or {}
    if not isinstance(package, dict):
        raise ValueError('measurement options must be an object')
    videos = package.get('videos') or ([reference] if reference else [])
    if not isinstance(videos, list) or any(not isinstance(video, str) for video in videos):
        raise ValueError('videos must be local file paths')
    videos = list(videos)
    if package.get('folder'):
        found, _, _ = style_import.find_videos(package['folder'])
        videos.extend(str(video) for video in found)
    videos = list(dict.fromkeys(videos))
    if not 1 <= len(videos) <= 3:
        raise ValueError('Learn measures one to three reference videos')
    missing = [video for video in videos if not Path(video).is_file()]
    if missing:
        raise FileNotFoundError('not found: ' + ', '.join(missing))
    kind = package.get('kind')
    if kind not in (None, 'short', 'long'):
        raise ValueError('kind is short or long')
    return {'videos': videos, 'kind': kind, 'notes': package.get('notes'),
            'separate': package.get('separate', True), 'classify_sfx': package.get('classify_sfx', True),
            'refresh': package.get('refresh', False)}


def submit(reference=None, package=None):
    from letitedit.core import jobs
    specification = inputs(reference, package)
    return jobs.submit('learn_measure:job', inputs=specification,
                       label='Learn: measure reference videos', timeout_s=4 * 3600)


def job(context):
    specification = dict(context.inputs)
    return style_import.run(**specification, progress=context.progress, log=context.log, check=context.check)


def status(job_id):
    from letitedit.core import jobs
    state = jobs.status(job_id)
    if state.get('kind') != 'learn_measure:job':
        raise ValueError('job_id must name a Learn measurement job')
    return state
