r"""Fact log: closed-set facts per stretch of a video, read by a local vision model, each with its measured accuracy;
and a segment map that turns long clips and whole shoots into a short list of stretches that share their facts.

    facts(video, ...)            -> {'file', 'duration', 'stretches': [{'from', 'to', 'facts': {...}, 'reused'?}],
                                     'model', 'settings', 'seconds', 'version'}        (cached; None if build=False)
    photo_facts(photo, ...)      -> the same with one stretch at 0-0 (a still photo)
    segment_map(paths, ...)      -> {'segments': [...], 'files': [...], 'settings': {...}, 'text_file', ...}
    stretch_lines(entry), segment_lines(seg_map), legend(), text_file(...)   text for replies and files

Facts (key: answers). Each is asked about one stretch shown as `frames` frames `width` px wide, in one prompt
(text first); 'moments' counts when seen in any frame, the others hold for most frames:
    text      every readable word or number, as written ('' when none)
    people    0 / 1 / 2 / 3+         face   yes / no (a face can be seen)     camera  yes / no (looks or talks to it)
    hands     yes / no (people seen only as hands or arms)
    shot      wide / medium / close-up / detail
    io        indoors / outdoors     light  day / night / low light
    place     PLACES                 subject  SUBJECTS
    moments   any of MOMENTS         cutoff  yes / no (main subject cut off by the edge)   blocked  yes / no (lens)
    clearest  per segment: which of up to `clear_n` of its stretches shows the subject most clearly (one frame each)
ACCURACY (factlog_accuracy.json beside this file) holds each fact's measured share right on a checked test set
(kept with the development notes, not shipped); facts under min_accuracy are kept and marked with their accuracy in every text.
Not from the vision model: motion, running/still, start/stop timing, crop fit, tilt (perception.py, sound, tracker).

How a video is split into stretches: shot_log.segments (picture cuts, max_s parts, merge of near-identical parts up
to merge_max_s). A stretch whose middle frame differs from the last asked stretch's by under reuse_below (mean
difference of 64x64 grey frames, 0-255), with no picture cut or big scene change (perception.py, when analysed)
between them, takes that stretch's facts ('reused': from-time).
Cached per file content, settings and VERSION in <cache>\shot_log\facts (the old footage log stays in
<cache>\shot_log, untouched).
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = _paths.BRIDGE
CACHE = Path(os.environ.get('LETITEDIT_CACHE', (_SAI_ROOT + '\\cache'))) / 'shot_log' / 'facts'
ACCURACY_FILE = HERE / 'factlog_accuracy.json'
VERSION = 1              # fact log entries
SEGMENT_VERSION = 2      # segment maps (2: words of long clips read over the whole clip)
VIDEO = {'.mov', '.mp4', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.mxf', '.wmv', '.3gp'}
PHOTO = {'.png', '.jpg', '.jpeg', '.heic', '.heif', '.webp', '.bmp', '.tif', '.tiff'}

PLACES = ['road', 'roadside/parking', 'inside a vehicle', 'on a roof', 'workshop/garage', 'kitchen', 'living space',
          'bathroom', 'store', 'city street', 'nature/forest', 'beach/water', 'mountains', 'campground', 'other']
SUBJECTS = ['person', 'vehicle', 'machine/part', 'tool', 'food', 'animal', 'landscape', 'building', 'object held up',
            'screen', 'text/document', 'other']
MOMENTS = ['thumbs-up', 'pointing', 'waving', 'laughing/smiling', 'holding up']
FACTS = [  # key, label in the prompt, answers (None: free text; 'multi': any of them)
    ('text', 'Text', None),
    ('people', 'People', ['0', '1', '2', '3+']),
    ('face', 'Face', ['yes', 'no']),
    ('camera', 'Camera', ['yes', 'no']),
    ('hands', 'Hands only', ['yes', 'no']),
    ('shot', 'Shot', ['wide', 'medium', 'close-up', 'detail']),
    ('io', 'Setting', ['indoors', 'outdoors']),
    ('light', 'Light', ['day', 'night', 'low light']),
    ('place', 'Place', PLACES),
    ('subject', 'Subject', SUBJECTS),
    ('moments', 'Moments', MOMENTS),
    ('cutoff', 'Cut off', ['yes', 'no']),
    ('blocked', 'Blocked', ['yes', 'no']),
]
KEYS = [k for k, _, _ in FACTS]
LABEL_KEY = {lab.lower(): k for k, lab, _ in FACTS}

PROMPT = """These {n} frames come in order from one stretch of a video. Answer about what is seen in most of the
frames (Moments: in any frame). Write 13 lines. Each line starts with its label and a colon, then your answer, picked
from the answers listed after that label.
Text: every readable word or number in the picture, copied exactly; or none
People: 0, 1, 2 or 3+ (every person with any part of the body in view counts)
Face: yes or no (a person's face is in view)
Camera: yes or no (a person's face is turned to the camera, or the person talks to it)
Hands only: yes or no (yes when the only parts of people in view are hands or arms)
Shot: wide, medium, close-up or detail
Setting: indoors or outdoors (outdoors: in the open air, also under or beside a vehicle)
Light: day, night or low light
Place: one of {places}
Subject: one of {subjects}
Moments: none, or any of thumbs-up, pointing, waving, laughing or smiling, holding something up to the camera
Cut off: yes or no (the main subject runs off the edge of the picture)
Blocked: yes or no (a hand, finger or object covers the lens)"""
PROMPT_PHOTO = PROMPT.replace('These {n} frames come in order from one stretch of a video. Answer about what is seen '
                              'in most of the\nframes (Moments: in any frame).', 'This is a still photo.')

CLEAREST_PROMPT = """Reply with one number only.
Here are {n} images, numbered 1 to {n} in order, from neighbouring stretches of the same video. Which one shows its
main subject most clearly (sharp, in view, not blocked)? Reply with the number of that image and nothing else."""

ASK_CHOICES = ' Answer with exactly one of: {choices}. Then a few words on what you see.'
ASK_FREE = ' Answer in one or two short sentences.'

DEFAULTS = {'max_s': 8.0, 'frames': 3, 'width': 448, 'merge_below': 5.0, 'merge_max_s': 30.0, 'cut_above': 0.3,
            'reuse_below': 3.0, 'max_new_tokens': 160, 'batch': 4}
SEGMENT_DEFAULTS = {
    'gap_s': 600.0,          # a gap in recording time between files longer than this starts a new segment
    'place_km': 1.0,         # files recorded this far apart (GPS) start a new segment
    'split_keys': ('people', 'camera', 'hands', 'io', 'light', 'place'),   # facts whose change splits a segment
    'smooth_n': 3,           # facts are smoothed over this many neighbouring stretches before comparing
    'min_accuracy': 0.85,    # facts measured under this don't split segments, and are marked in texts
    'topic_window_s': 90.0,  # words this long before/after a stretch boundary are compared
    'topic_min_words': 12,   # both sides need this many content words
    'topic_below': 0.05,     # word overlap (cosine of word counts) under this splits a segment
    'min_segment_s': 30.0,   # shorter segments join a neighbour (not across a recording gap or place change)
    'max_segment_s': 300.0,  # longer segments are cut into equal parts at stretch boundaries
    'hold_share': 0.6,       # a fact 'holds' over a segment when one answer covers this share of its time
    'clear_n': 4,            # stretches compared for the segment's frame (vision model 'clearest'); 0: middle one
    'first_words': 14,       # words of the segment's first speech shown
}
NONE_WORDS = {'none', 'no', 'n/a', 'na', 'nothing', '-', ''}
SYN = {'roadside or parking': 'roadside/parking', 'parking': 'roadside/parking', 'roadside': 'roadside/parking',
       'workshop or garage': 'workshop/garage', 'garage': 'workshop/garage', 'workshop': 'workshop/garage',
       'nature or forest': 'nature/forest', 'forest': 'nature/forest', 'nature': 'nature/forest',
       'beach or water': 'beach/water', 'beach': 'beach/water', 'water': 'beach/water', 'vehicle interior':
       'inside a vehicle', 'machine or part': 'machine/part', 'machine': 'machine/part', 'part': 'machine/part',
       'text or document': 'text/document', 'document': 'text/document', 'held up': 'object held up',
       'close up': 'close-up', 'closeup': 'close-up', 'extreme close-up': 'detail', 'extreme close up': 'detail',
       'three or more': '3+', '3 or more': '3+', 'more than 2': '3+', 'thumbs up': 'thumbs-up',
       'laughing or smiling': 'laughing/smiling', 'smiling': 'laughing/smiling', 'laughing': 'laughing/smiling',
       'smile': 'laughing/smiling', 'holding something up to the camera': 'holding up',
       'holding something up': 'holding up', 'daylight': 'day', 'dim': 'low light', 'dark': 'low light',
       'low-light': 'low light', 'indoor': 'indoors', 'outdoor': 'outdoors', 'inside': 'indoors',
       'outside': 'outdoors', 'one': '1', 'two': '2', 'zero': '0', 'three': '3+'}


# ------------------------------------------------------------------ accuracy

def accuracy():
    """{fact: share right (0-1)} measured on the test set (factlog_accuracy.json), {} when not measured."""
    try:
        return json.loads(ACCURACY_FILE.read_text(encoding='utf-8-sig')).get('accuracy', {})
    except (OSError, ValueError):
        return {}


def accuracy_info():
    try:
        return json.loads(ACCURACY_FILE.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def legend(min_accuracy=SEGMENT_DEFAULTS['min_accuracy']):
    """One line: each fact's measured accuracy; facts under min_accuracy are marked '~' in the lines."""
    acc = accuracy()
    if not acc:
        return 'Fact accuracy: not measured.'
    info = accuracy_info()
    pos = info.get('positives', {})
    names = [k for k in KEYS if k != 'moments'] + [f'moments:{m}' for m in MOMENTS] + ['clearest']
    bits = [f"{k.replace('moments:', '')} {math.floor(acc[k] * 100)}%" + (' (no examples seen)' if pos.get(k) == 0 else '')
            for k in names if k in acc]
    weak = [k.replace('moments:', '') for k in names if k in acc and acc[k] < min_accuracy]
    return (f"Fact accuracy (share right on {info.get('items', '?')} checked stretches, "
            f"{info.get('model', '?')}): " + ', '.join(bits) +
            (f"; under {min_accuracy:.0%}, marked ~: {', '.join(weak)}" if weak else ''))


# ------------------------------------------------------------------ asking

LINES = {   # the prompt line of each fact
    'text': 'Text: every readable word or number in the picture, copied exactly; or none',
    'people': 'People: 0, 1, 2 or 3+ (every person with any part of the body in view counts)',
    'face': "Face: yes or no (a person's face is in view)",
    'camera': "Camera: yes or no (a person's face is turned to the camera, or the person talks to it)",
    'hands': "Hands only: yes or no (yes when you see a person's hands or arms but not their head or body)",
    'shot': 'Shot: wide, medium, close-up or detail',
    'io': 'Setting: indoors or outdoors (outdoors: in the open air, also under or beside a vehicle)',
    'light': 'Light: day, night or low light',
    'place': 'Place: one of {places}',
    'subject': 'Subject: one of {subjects}',
    'moments': 'Moments: none, or any of thumbs-up, pointing, waving, laughing or smiling, holding up (an object '
               'lifted toward the camera to show it)',
    'cutoff': 'Cut off: yes or no (the main subject runs off the edge of the picture)',
    'blocked': 'Blocked: yes or no (a hand, finger or object covers the lens)',
}
GROUPS = {'one': [KEYS],
          'two': [['text', 'people', 'face', 'camera', 'hands', 'moments'],
                  ['shot', 'io', 'light', 'place', 'subject', 'cutoff', 'blocked']]}
DESIGN = 'two'
RETRY_MISSING = 3        # a reply missing this many of its facts is asked once more


def _choice_words(xs):
    return ', '.join(x.replace('/', ' or ') if x != 'inside a vehicle' else 'inside a vehicle (car, van, bus or '
                     'RV interior)' for x in xs)


def prompt_for(n, photo=False, keys=None):
    """The prompt for one stretch of n frames (or a photo) asking the facts in keys (default all, PROMPT)."""
    if keys is None or list(keys) == KEYS:
        return (PROMPT_PHOTO if photo else PROMPT).format(n=n, places=_choice_words(PLACES),
                                                          subjects=_choice_words(SUBJECTS))
    head = ('This is a still photo.' if photo else
            f'These {n} frames come in order from one stretch of a video. Answer about what is seen in most of the '
            'frames' + (' (Moments: in any frame).' if 'moments' in keys else '.'))
    body = '\n'.join(LINES[k].format(places=_choice_words(PLACES), subjects=_choice_words(SUBJECTS)) for k in keys)
    first = dict((k, lab) for k, lab, _ in FACTS)[keys[0]]
    return (f'{head} Write {len(keys)} lines. Each line starts with its label and a colon, then your answer, picked '
            f'from the answers listed after that label. Start with "{first}:".\n{body}')


def _norm(s):
    s = s.strip().strip('*').strip().lower()
    s = re.sub(r'\s*\(.*?\)\s*', ' ', s)
    return re.sub(r'\s+', ' ', s).strip(' .;,"\'')


def _pick(ans, options):
    """The option an answer names (synonyms, first match by position), or None."""
    a = _norm(ans)
    if not a:
        return None
    if a in options:
        return a
    if a in SYN and SYN[a] in options:
        return SYN[a]
    hits = []
    for o in options + list(SYN):
        val = o if o in options else SYN[o]
        if val not in options:
            continue
        m = re.search(r'(?<![\w+-])' + re.escape(o) + r'(?![\w-])', a)
        if m:
            hits.append((m.start(), -len(o), val))
    if hits:
        return sorted(hits)[0][2]
    if options == ['0', '1', '2', '3+']:
        m = re.search(r'\d+', a)
        if m:
            return '3+' if int(m.group()) >= 3 else m.group()
    return None


def _multi(ans, options):
    a = _norm(ans)
    if a in NONE_WORDS or a.startswith('none'):
        return []
    out = []
    for o in options + list(SYN):
        val = o if o in options else SYN.get(o)
        if val in options and val not in out and re.search(r'(?<![\w-])' + re.escape(o) + r'(?![\w-])', a):
            out.append(val)
    return [o for o in options if o in out]


def _echo(ans, options):
    """True when an answer repeats the list of answers instead of picking one."""
    a = _norm(ans)
    n = sum(1 for o in options if re.search(r'(?<![\w-])(' + re.escape(o) + '|' + re.escape(o.replace('/', ' or '))
                                              + r')(?![\w-])', a))
    return n >= min(3, len(options))


def parse(reply):
    """{fact: answer} from the model's 'Label: answer' lines; a fact it didn't answer (or answered by repeating the
    list) is left out. Unlabelled lines right after 'Text:' are part of the text."""
    out, last = {}, None
    for line in reply.splitlines():
        line = re.sub(r'^\s*\**label\**\s*:\s*', '', line, flags=re.I)
        m = re.match(r'\s*[-*\d.]*\s*\**([A-Za-z ]{3,12}?)\**\s*:\s*(.*)$', line)
        key = LABEL_KEY.get(m.group(1).strip().lower()) if m else None
        if not key:
            if last == 'text' and line.strip() and out.get('text') is not None:
                out['text'] = (out['text'] + ' ' + line.strip()).strip()
            elif line.strip():
                last = None
            continue
        last = key
        if key in out:
            continue
        ans = m.group(2).strip()
        options = dict((k, o) for k, _, o in FACTS)[key]
        if key == 'text':
            t = ans.strip().strip('"').strip()
            if re.match(r'^(copy |every readable)', t.lower()):
                continue                                            # the instruction repeated
            out['text'] = '' if _norm(t) in NONE_WORDS or re.match(r'^(none|no (readable )?(text|words))', _norm(t))                 else t
        elif _echo(ans, options):
            continue
        elif key == 'moments':
            out['moments'] = _multi(ans, options)
        else:
            v = _pick(ans, options)
            if v is not None:
                out[key] = v
    if out.get('text') and _norm(out['text']) in NONE_WORDS:
        out['text'] = ''
    if out.get('people') == '0' and 'hands' in out:
        out['hands'] = 'no'
    return out


LEAK = re.compile(r'(,\s*(3\+|yes|no|none|0|1|2)(?=\s*(,|$))){3,}', re.I)


def consistent(fa):
    """Answers made to agree with each other (in place): no people -> no face, camera, hands only; no face -> not
    to camera and no laughing/smiling; text cut where the model ran on into the answer words (', 1, 2, 3+, yes')."""
    if fa.get('people') == '0':
        for k in ('face', 'camera', 'hands'):
            if k in fa:
                fa[k] = 'no'
    if fa.get('face') == 'no':
        if 'camera' in fa:
            fa['camera'] = 'no'
        if fa.get('moments') and 'laughing/smiling' in fa['moments']:
            fa['moments'] = [m for m in fa['moments'] if m != 'laughing/smiling']
    t = fa.get('text')
    if t:
        m = LEAK.search(t)
        if m:
            fa['text'] = t[:m.start()].strip(' ,')
    return fa


def ask(image_lists, photo=False, max_new_tokens=DEFAULTS['max_new_tokens'], batch=DEFAULTS['batch'], model=None,
        design=None):
    """[(facts, raw reply)] for each list of frame paths (one stretch each), and the model reply dict (run_s summed).
    design: 'one' (one prompt with every fact) or 'two' (people facts, then scene facts); default DESIGN. A reply
    missing RETRY_MISSING or more of its facts is asked once more."""
    import letitedit.sound.model_tools as model_tools
    groups = GROUPS[design or DESIGN]
    if not image_lists:
        return [], {}
    items, where = [], []
    for i, ims in enumerate(image_lists):
        for g in groups:
            items.append({'images': ims, 'prompt': prompt_for(len(ims), photo, g)})
            where.append((i, g))
    rep = model_tools.describe(items, max_new_tokens=max_new_tokens, batch=batch, model=model)
    texts = list(rep['texts'])
    retry = [k for k, (t, (i, g)) in enumerate(zip(texts, where))
             if sum(1 for key in g if key not in parse(t)) >= min(RETRY_MISSING, len(g))]
    if retry:
        rep2 = model_tools.describe([items[k] for k in retry], max_new_tokens=max_new_tokens, batch=batch,
                                    model=model)
        for k, t in zip(retry, rep2['texts']):
            if len(parse(t)) > len(parse(texts[k])):
                texts[k] = t
        rep['run_s'] = (rep.get('run_s') or 0) + (rep2.get('run_s') or 0)
        rep['retried'] = len(retry)
    out = [({}, []) for _ in image_lists]
    for (i, g), t in zip(where, texts):
        got = parse(t)
        out[i][0].update({k: v for k, v in got.items() if k in g})
        out[i][1].append(t)
    for fa, _ in out:
        consistent(fa)
        if fa.get('text') and len(fa['text']) > 400:          # a run-away list: kept short
            fa['text'] = fa['text'][:400].rsplit(' ', 1)[0] + ' ...'
    return [(fa, '\n---\n'.join(raw)) for fa, raw in out], rep


def clearest(image_paths, max_new_tokens=12, model=None):
    """1-based number of the image the model picks as the clearest, or None."""
    import letitedit.sound.model_tools as model_tools
    if len(image_paths) < 2:
        return 1 if image_paths else None
    rep = model_tools.describe([{'images': list(image_paths), 'prompt': CLEAREST_PROMPT.format(n=len(image_paths))}],
                               max_new_tokens=max_new_tokens, batch=1, model=model)
    t = rep['texts'][0]
    m = re.match(r'\D{0,12}?(\d+)', t) or re.search(r'(?:image|number)\s*(\d+)', t, re.I)
    k = int(m.group(1)) if m else None
    return k if k and 1 <= k <= len(image_paths) else None


# ------------------------------------------------------------------ one video

def _key(path, settings):
    import letitedit.sound.model_tools as model_tools
    h = hashlib.sha256(json.dumps({**settings, 'v': VERSION}, sort_keys=True).encode()).hexdigest()[:10]
    return f'{model_tools._fingerprint(str(path))}-{h}'


def _settings(kw):
    s = {k: kw.get(k, DEFAULTS[k]) for k in ('max_s', 'frames', 'width', 'merge_below', 'merge_max_s', 'cut_above',
                                              'reuse_below')}
    return {k: (float(v) if isinstance(v, (int, float)) and k not in ('frames', 'width') else v) for k, v in s.items()}


def cache_file(path, **kw):
    photo = Path(path).suffix.lower() in PHOTO
    settings = {'photo': True, 'width': int(kw.get('width', DEFAULTS['width'])) * 2} if photo else _settings(kw)
    return CACHE / f'{_key(path, settings)}.json', settings


MODEL_FACTS = ('text in the picture', 'people', 'face', 'looks at the camera', 'hands', 'shot size',
               'indoors or outdoors', 'light', 'place', 'subject', 'moments', 'subject cut off', 'lens blocked')


def unavailable_note(fact):
    """The reply's note when the fact log could not be built on this PC (hardware.LocalModelUnavailable's fact)."""
    return ('\n\nFact log: not built. ' + fact + ' Missing from this reply: the fact-log facts per stretch ('
            + ', '.join(MODEL_FACTS) + ') and the segment map made from them. The rest of this reply (sound, '
            'motion, picture labels, cuts, words) is measured without that model.')


def _need_vision():
    """Before building: hardware.LocalModelUnavailable at once on a PC whose graphics card can't run the model, so
    no frames are cut for nothing."""
    import letitedit.core.hardware as hardware
    try:
        why = hardware.vision_unavailable()
    except Exception:  # noqa: BLE001 - no reading: model_tools.describe's own checks stand
        why = None
    if why:
        raise hardware.LocalModelUnavailable(why, feature='vision')


def facts(video, build=True, progress=None, model=None, **kw):
    """The fact log of one video (see the module doc); cached. kw: DEFAULTS keys. progress(done, total)."""
    import letitedit.footage.shot_log as shot_log
    video = Path(video)
    if video.suffix.lower() in PHOTO:
        return photo_facts(video, build=build, model=model, **kw)
    f, settings = cache_file(video, **kw)
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8-sig'))
    if not build:
        return None
    _need_vision()
    t0 = time.time()
    spans = shot_log.segments(video, settings['max_s'], settings['merge_below'], settings['merge_max_s'],
                              settings['cut_above'])
    tmp = Path(tempfile.mkdtemp(prefix='factlog-'))
    with ThreadPoolExecutor(4) as ex:
        imgs = list(ex.map(lambda s: shot_log._frames(video, s[0], s[1], settings['frames'], settings['width'], tmp),
                           spans))
        imgs = shot_log.checked_frames(video, spans, imgs, settings['frames'], settings['width'], tmp)
        greys = list(ex.map(lambda s: shot_log._grey(video, (s[0] + s[1]) / 2), spans)) \
            if settings['reuse_below'] is not None else [None] * len(spans)
    cuts = set()          # picture cuts and big scene changes (perception.py, when cached): no reuse across them
    try:
        import letitedit.footage.perception as pc
        if settings['reuse_below'] is not None and pc.is_cached('motion', video):
            pic = pc.picture(video)
            cuts = {float(c) for c in (pic.get('cuts') or []) + (pic.get('changes') or [])}
    except Exception:  # noqa: BLE001
        pass
    # which stretches are asked, which take the facts of the last asked one
    ask_idx, reuse_of, last = [], {}, None
    for i, ((a, b), g) in enumerate(zip(spans, greys)):
        cut_between = last is not None and any(spans[last][0] < c <= a + 1e-6 for c in cuts)
        if (last is not None and g is not None and greys[last] is not None and not cut_between and
                settings['reuse_below'] is not None and
                float(np.abs(g - greys[last]).mean()) < float(settings['reuse_below']) and imgs[i]):
            reuse_of[i] = last
        else:
            ask_idx.append(i)
            last = i
    answers, model_name, run_s = {}, None, 0.0
    step = 24
    for k in range(0, len(ask_idx), step):
        chunk = [i for i in ask_idx[k:k + step] if imgs[i]]
        got, rep = ask([imgs[i] for i in chunk], max_new_tokens=kw.get('max_new_tokens', DEFAULTS['max_new_tokens']),
                       batch=kw.get('batch', DEFAULTS['batch']), model=model)
        model_name, run_s = rep.get('model') or model_name, run_s + (rep.get('run_s') or 0)
        for i, (fa, raw) in zip(chunk, got):
            answers[i] = (fa, raw)
        if progress:
            progress(min(len(ask_idx), k + step), len(ask_idx))
    stretches = []
    for i, (a, b) in enumerate(spans):
        if i in reuse_of:
            fa, _ = answers.get(reuse_of[i], ({}, ''))
            stretches.append({'from': a, 'to': b, 'facts': dict(fa), 'reused': spans[reuse_of[i]][0]})
        else:
            fa, raw = answers.get(i, ({}, ''))
            stretches.append({'from': a, 'to': b, 'facts': fa, 'raw': raw})
    for p in tmp.glob('*'):
        p.unlink(missing_ok=True)
    tmp.rmdir()
    entry = {'file': str(video), 'kind': 'video', 'duration': round(shot_log._duration(video), 2),
             'stretches': stretches, 'asked': len(ask_idx), 'model': model_name, 'settings': settings,
             'version': VERSION, 'seconds': round(time.time() - t0, 1), 'model_s': round(run_s, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(entry, indent=1), encoding='utf-8')
    return entry


def _photo_jpg(photo, width, folder):
    import letitedit.footage.perception as pc
    im = pc.photo_image(str(photo), width=width)
    if im is None:
        return None
    out = Path(folder) / f'{Path(photo).stem}.jpg'
    im.save(out, quality=88)
    return str(out)


def photo_facts(photo, build=True, model=None, **kw):
    """The fact log of a still photo: one stretch at 0-0, read from the photo at 2 x width px."""
    photo = Path(photo)
    f, settings = cache_file(photo, **kw)
    if f.exists():
        return json.loads(f.read_text(encoding='utf-8-sig'))
    if not build:
        return None
    _need_vision()
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix='factlog-'))
    jpg = _photo_jpg(photo, settings['width'], tmp)
    if jpg:
        got, rep = ask([[jpg]], photo=True, max_new_tokens=kw.get('max_new_tokens', DEFAULTS['max_new_tokens']) + 80,
                       batch=1, model=model)
        (fa, raw), rep_model = got[0], rep.get('model')
    else:
        fa, raw, rep_model = {}, 'not readable', None
    for p in tmp.glob('*'):
        p.unlink(missing_ok=True)
    tmp.rmdir()
    entry = {'file': str(photo), 'kind': 'photo', 'duration': 0.0,
             'stretches': [{'from': 0.0, 'to': 0.0, 'facts': fa, 'raw': raw}], 'asked': 1, 'model': rep_model,
             'settings': settings, 'version': VERSION, 'seconds': round(time.time() - t0, 1)}
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(entry, indent=1), encoding='utf-8')
    return entry


# ------------------------------------------------------------------ text

def _clock(s):
    s = float(s)
    return f'{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:04.1f}' if s >= 3600 else f'{int(s // 60)}:{s % 60:04.1f}'


def _mark(key, value, acc, min_accuracy):
    return f'~{value}' if key in acc and acc[key] < min_accuracy else value


def fact_text(fa, min_accuracy=SEGMENT_DEFAULTS['min_accuracy'], acc=None, skip=()):
    """'1 person, hands only, close-up, indoors, day, bathroom, machine/part; thumbs-up; text "MAX AIR"; blocked'."""
    acc = accuracy() if acc is None else acc
    m = lambda k, v: _mark(k, v, acc, min_accuracy)  # noqa: E731
    bits = []
    p = fa.get('people')
    if p is not None and 'people' not in skip:
        who = 'no people' if p == '0' else f"{p} {'person' if p == '1' else 'people'}"
        bits.append(m('people', who))
    for k, yes in (('hands', 'hands only'), ('face', 'face'), ('camera', 'to camera')):
        if fa.get(k) == 'yes' and k not in skip and not (k == 'face' and fa.get('camera') == 'yes'):
            bits.append(m(k, yes))
    for k in ('shot', 'io', 'light', 'place', 'subject'):
        if fa.get(k) and k not in skip:
            bits.append(m(k, fa[k]))
    out = ', '.join(bits)
    if fa.get('moments') and 'moments' not in skip:
        out += '; ' + ', '.join(m(f'moments:{x}', x) for x in fa['moments'])
    if fa.get('text') and 'text' not in skip:
        t = fa['text'].replace('\n', ' ')
        out += f'; {m("text", "text")} "{t[:120]}{"..." if len(t) > 120 else ""}"'
    for k, word in (('cutoff', 'subject cut off'), ('blocked', 'lens blocked')):
        if fa.get(k) == 'yes' and k not in skip:
            out += f'; {m(k, word)}'
    return out


def stretch_lines(entry, min_accuracy=SEGMENT_DEFAULTS['min_accuracy']):
    acc = accuracy()
    out = []
    for s in entry.get('stretches', []):
        when = 'photo' if entry.get('kind') == 'photo' else f"{_clock(s['from'])}-{_clock(s['to'])}"
        out.append(f"{when}  {fact_text(s.get('facts', {}), min_accuracy, acc)}" +
                   (f"  (same picture as {_clock(s['reused'])})" if 'reused' in s else ''))
    return out


# ------------------------------------------------------------------ segments

STOP = set('the a an and or but so to of in on at it is it\'s that this i you we he she they was were be been are '
           'for with as if just like um uh yeah okay ok oh well then there here what about all right got get go '
           'going gonna do did don\'t not no yes my your our me us them his her its have has had can could will '
           'would one up down out now see look know really kind sort thing things'.split())


def _bag(ws):
    out = {}
    for w in ws:
        t = re.sub(r"[^a-z0-9']", '', w['w'].lower())
        if len(t) > 2 and t not in STOP:
            out[t] = out.get(t, 0) + 1
    return out


def _cos(a, b):
    num = sum(v * b.get(k, 0) for k, v in a.items())
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def _km(p, q):
    la1, lo1, la2, lo2 = map(math.radians, (p['lat'], p['lon'], q['lat'], q['lon']))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _media(paths):
    import letitedit.server.core_tools as core_tools
    files, _, _ = core_tools._collect(paths)
    vids = [f for f in files if f.suffix.lower() in VIDEO]
    photos = [f for f in files if f.suffix.lower() in PHOTO]
    # a photo kept twice (IMG_1.HEIC + IMG_1.jpeg): the jpeg copy only
    stems = {}
    for p in photos:
        stems.setdefault(p.stem.lower(), []).append(p)
    photos = [sorted(v, key=lambda p: p.suffix.lower() in ('.heic', '.heif'))[0] for v in stems.values()]
    return vids, photos


def _when(path):
    """(recording start as a datetime or None, duration s)."""
    import letitedit.server.core_tools as core_tools
    if Path(path).suffix.lower() in PHOTO:
        import letitedit.footage.perception as pc
        info = pc.photo(path)
        from datetime import datetime, timezone
        t = info.get('taken')
        try:
            return (datetime.fromisoformat(t.replace(' ', 'T')).replace(tzinfo=timezone.utc) if t else None), 0.0
        except ValueError:
            return None, 0.0
    info = core_tools.probe(Path(path))
    return core_tools.rec_start(info), float(info.get('duration') or 0)


def _order(files):
    """Files in recording order (start time; files without one by name, after the others)."""
    whens = {f: _when(f) for f in files}

    def key(f):
        st = whens[f][0]
        return (0, st.replace(tzinfo=None).isoformat() if st else '', f.name.lower()) if st else (1, '', f.name.lower())
    return sorted(files, key=key), whens


def _mode(values, own=None):
    """The most common value (ties: own, if it is among them, else the first seen)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return own
    return max(set(vals), key=lambda v: (vals.count(v), v == own, -vals.index(v)))


def _segment_breaks(entries, files, n, split_keys, st, units, whens):
    # hard breaks between files: recording gaps, GPS place changes
    import letitedit.footage.geo as geo
    gps = {}
    for f in files:
        try:
            gps[f] = geo.coords(f)
        except Exception:  # noqa: BLE001
            gps[f] = None
    hard = [None] * n          # reason a new segment starts at unit i
    soft = [None] * n
    prev_file = None
    words = {}
    for i, u in enumerate(units):
        f = u['file']
        if i == 0:
            prev_file = f
            continue
        if f != prev_file:
            a_st, a_d = whens[prev_file]
            b_st, _ = whens[f]
            if a_st and b_st:
                gap = (b_st - a_st).total_seconds() - a_d
                if gap > st['gap_s']:
                    hard[i] = f'{gap / 60:.0f} min gap in recording'
            if not hard[i] and gps.get(prev_file) and gps.get(f):
                d = _km(gps[prev_file], gps[f])
                if d > st['place_km']:
                    hard[i] = f'GPS {d:.1f} km away'
            prev_file = f
        if u['sig'] != units[i - 1]['sig']:
            changed = [k for k, x, y in zip(split_keys, units[i - 1]['sig'], u['sig']) if x != y]
            soft[i] = 'facts change: ' + ', '.join(changed)
    # transcript topic changes (inside one file, at stretch boundaries)
    import letitedit.footage.speech as speech
    for f in files:
        if f.suffix.lower() in VIDEO:
            try:
                words[f] = speech.cached_words(str(f), 0.0, entries[f]['duration'] + 1.0) or []
            except Exception:  # noqa: BLE001
                words[f] = []
    for i in range(1, n):
        u, p = units[i], units[i - 1]
        if u['file'] != p['file'] or hard[i] or soft[i]:
            continue
        ws = words.get(u['file']) or []
        t = u['from']
        before = _bag([w for w in ws if t - st['topic_window_s'] <= w['s'] < t])
        after = _bag([w for w in ws if t <= w['s'] < t + st['topic_window_s']])
        if (sum(before.values()) >= st['topic_min_words'] and sum(after.values()) >= st['topic_min_words'] and
                _cos(before, after) < st['topic_below']):
            soft[i] = 'talk changes subject'
    return hard, soft, words


def _segment_runs(hard, n, soft, st, units):
    # first cut: a segment per run between breaks
    segs, cur = [], [0]
    for i in range(1, n):
        if hard[i] or soft[i]:
            segs.append({'units': cur, 'why': hard[cur[0]] or soft[cur[0]], 'hard': bool(hard[cur[0]])})
            cur = []
        cur.append(i)
    segs.append({'units': cur, 'why': hard[cur[0]] or soft[cur[0]], 'hard': bool(hard[cur[0]])})

    def dur(seg):
        return sum(max(0.0, units[j]['to'] - units[j]['from']) for j in seg['units'])

    def sim(x, y):
        a, b = units[x['units'][-1]]['sig'], units[y['units'][0]]['sig']
        return sum(1 for p, q in zip(a, b) if p == q)
    # join short segments to a neighbour (never across a hard break)
    changed = True
    while changed and len(segs) > 1:
        changed = False
        for k, sg in enumerate(segs):
            if dur(sg) >= st['min_segment_s']:
                continue
            left = segs[k - 1] if k > 0 and not sg['hard'] else None
            right = segs[k + 1] if k + 1 < len(segs) and not segs[k + 1]['hard'] else None
            if not left and not right:
                continue
            if left and (not right or sim(left, sg) >= sim(sg, right)):
                left['units'] += sg['units']
            else:
                right['units'] = sg['units'] + right['units']
                right['why'], right['hard'] = sg['why'], sg['hard']
            segs.pop(k)
            changed = True
            break
    # cut long segments into equal parts
    out = []
    for sg in segs:
        d = dur(sg)
        parts = max(1, int(math.ceil(d / st['max_segment_s']))) if st['max_segment_s'] else 1
        if parts == 1:
            out.append(sg)
            continue
        target, first, cur, run = d / parts, True, [], 0.0
        for j in sg['units']:
            if cur and run >= target - 1e-6:
                out.append({'units': cur, 'why': sg['why'] if first else f'part of a {d / 60:.0f} min stretch with the '
                            'same facts', 'hard': sg['hard'] if first else False})
                first, cur, run = False, [], 0.0
            cur.append(j)
            run += units[j]['to'] - units[j]['from']
        if cur:
            out.append({'units': cur, 'why': sg['why'] if first else f'part of a {d / 60:.0f} min stretch with the '
                        'same facts', 'hard': sg['hard'] if first else False})
    segs = out
    return segs


def _describe_segments(clear_jobs, result, segs, st, units, words):
    for k, sg in enumerate(segs):
        us = [units[j] for j in sg['units']]
        total = sum(max(0.0, u['to'] - u['from']) for u in us) or 1.0
        weight = [max(0.0, u['to'] - u['from']) or (total / len(us)) for u in us]
        hold = {}
        for fk in KEYS:
            if fk in ('text', 'moments'):
                continue
            share = {}
            for u, w in zip(us, weight):
                v = u['facts'].get(fk)
                if v is not None:
                    share[v] = share.get(v, 0.0) + w
            if not share:
                continue
            tot = sum(weight)
            best = sorted(share.items(), key=lambda x: -x[1])
            if best[0][1] / tot >= st['hold_share']:
                hold[fk] = best[0][0]
            else:
                hold[fk] = '/'.join(v for v, _ in best[:2])
        moments = []
        for u in us:
            for mo in u['facts'].get('moments') or []:
                moments.append({'moment': mo, 'file': str(u['file']), 'at': round((u['from'] + u['to']) / 2, 1)})
        texts = []
        for u in us:
            t = (u['facts'].get('text') or '').strip()
            if t and t.lower() not in [x.lower() for x in texts]:
                texts.append(t)
        fs = list(dict.fromkeys(u['file'] for u in us))
        said = []
        for f in fs:
            lo = min(u['from'] for u in us if u['file'] == f)
            hi = max(u['to'] for u in us if u['file'] == f)
            said += [w for w in (words.get(f) or []) if lo <= w['s'] < hi]
            if len(said) >= st['first_words']:
                break
        first = ' '.join(w['w'].strip() for w in said[:st['first_words']])
        # candidate stretches for the frame: not blocked, spread over the segment
        cands = [u for u in us if u['facts'].get('blocked') != 'yes'] or us
        if st['clear_n'] and len(cands) > st['clear_n']:
            idx = [round(i * (len(cands) - 1) / (st['clear_n'] - 1)) for i in range(st['clear_n'])]
            cands = [cands[i] for i in dict.fromkeys(idx)]
        elif not st['clear_n']:
            cands = [cands[len(cands) // 2]]
        seg = {'n': k + 1, 'files': [str(f) for f in fs], 'start': {'file': str(us[0]['file']), 't': us[0]['from']},
               'end': {'file': str(us[-1]['file']), 't': us[-1]['to']}, 'seconds': round(total if total > 1 else 0, 1),
               'stretches': len(us), 'why': sg['why'] or 'start', 'facts': hold, 'moments': moments[:12],
               'text': texts[:4], 'first_words': first, 'photos': sum(1 for u in us if u['photo'])}
        result.append(seg)
        clear_jobs.append((seg, cands))


def _segment_frames(clear_jobs, folder, model, tmp, use_model):
    # representative frames
    import letitedit.footage.shot_log as shot_log
    for seg, cands in clear_jobs:
        jpgs = []
        for c in cands:
            if c['photo']:
                jpgs.append(_photo_jpg(c['file'], 448, tmp))
            else:
                t = (c['from'] + c['to']) / 2
                sub = tmp / f"{seg['n']}-{len(jpgs)}"
                sub.mkdir()
                got = shot_log._frames(c['file'], t - 0.01, t + 0.01, 1, 448, sub)
                jpgs.append(got[0] if got else None)
        pairs = [(c, j) for c, j in zip(cands, jpgs) if j]
        if not pairs:
            continue
        pick = 1
        if len(pairs) > 1 and not use_model:
            pick = (len(pairs) + 1) // 2
        elif len(pairs) > 1:
            try:
                pick = clearest([j for _, j in pairs], model=model) or (len(pairs) + 1) // 2
                seg['clearest_of'] = len(pairs)
            except Exception as e:  # noqa: BLE001 - the frame is extra
                seg['clearest_error'] = f'{type(e).__name__}: {e}'[:120]
                pick = (len(pairs) + 1) // 2
        c, j = pairs[pick - 1]
        out_jpg = folder / f"seg{seg['n']:03d}.jpg"
        os.replace(j, out_jpg)
        seg['frame'] = str(out_jpg)
        seg['frame_at'] = {'file': str(c['file']), 't': round((c['from'] + c['to']) / 2, 2)}


def segment_map(paths, build=True, progress=None, model=None, facts_kw=None, use_model=True, cached_only=False,
                **kw):
    """The segment map of one clip, a folder or a list of files (in recording order). kw: SEGMENT_DEFAULTS keys.
    build=False uses cached fact logs only (videos without one are listed under 'missing'). use_model=False picks
    each segment's frame without the vision model (the middle candidate) and never waits for the GPU.
    cached_only=True returns None unless this map is cached. Cached."""
    st = {**SEGMENT_DEFAULTS, **{k: v for k, v in kw.items() if k in SEGMENT_DEFAULTS}}
    st['split_keys'] = list(st['split_keys'])
    facts_kw = dict(facts_kw or {})
    vids, photos = _media(paths)
    files, whens = _order(vids + photos)
    if not files:
        return {'segments': [], 'files': [], 'settings': st, 'missing': []}
    import letitedit.sound.model_tools as model_tools
    if use_model:                            # no graphics card for the model: each segment's middle frame
        import letitedit.core.hardware as hardware
        with contextlib.suppress(Exception):
            use_model = hardware.vision_unavailable() is None
    key = hashlib.sha256(json.dumps({'f': [model_tools._fingerprint(str(f)) for f in files], 's': st,
                                     'fk': _settings(facts_kw), 'v': VERSION, 'sv': SEGMENT_VERSION,
                                     'm': bool(use_model)},
                                    sort_keys=True).encode()).hexdigest()[:16]
    folder = CACHE / 'segments' / key
    jf = folder / 'segments.json'
    if jf.exists():
        return json.loads(jf.read_text(encoding='utf-8-sig'))
    if cached_only:
        return None
    t0 = time.time()
    import letitedit.core.hardware as hardware
    entries, missing, unavailable = {}, [], None
    for i, f in enumerate(files):
        try:
            e = facts(f, build=build, model=model, **facts_kw)
        except hardware.LocalModelUnavailable as ex:     # no graphics card for the model: the logs already made
            unavailable, build = ex.fact, False
            e = facts(f, build=False, model=model, **facts_kw)
        if e is None:
            missing.append(str(f))
        else:
            entries[f] = e
        if progress:
            progress(i + 1, len(files), f)
    files = [f for f in files if f in entries]
    acc = accuracy()
    split_keys = [k for k in st['split_keys'] if acc.get(k, 1.0) >= st['min_accuracy']]

    # units: every stretch of every file, in order
    units = []
    for f in files:
        e = entries[f]
        for s in e['stretches']:
            units.append({'file': f, 'from': s['from'], 'to': s['to'], 'facts': s.get('facts', {}),
                          'photo': e.get('kind') == 'photo'})
    # smoothed facts for splitting
    n = len(units)
    if not n:
        out = {'segments': [], 'files': [], 'missing': missing, 'settings': st, 'split_keys': split_keys,
               'stretch_count': 0, 'footage_s': 0.0, 'version': VERSION, 'frames_by_model': bool(use_model)}
        if unavailable:
            out['unavailable'] = unavailable
        return out
    half = max(0, int(st['smooth_n']) // 2)
    for i, u in enumerate(units):
        nb = [units[j] for j in range(max(0, i - half), min(n, i + half + 1)) if units[j]['file'] == u['file']
              or not u['photo']]
        u['sig'] = tuple(_mode([x['facts'].get(k) for x in nb], u['facts'].get(k)) for k in split_keys)

    hard, soft, words = _segment_breaks(entries, files, n, split_keys, st, units, whens)
    segs = _segment_runs(hard, n, soft, st, units)

    # describe each segment
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    clear_jobs = []
    tmp = Path(tempfile.mkdtemp(prefix='factseg-'))
    _describe_segments(clear_jobs, result, segs, st, units, words)
    _segment_frames(clear_jobs, folder, model, tmp, use_model)
    for p in sorted(tmp.rglob('*'), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink(missing_ok=True)
    tmp.rmdir()
    res = {'segments': result, 'files': [str(f) for f in files], 'missing': missing, 'settings': st,
           'frames_by_model': bool(use_model),
           'split_keys': split_keys, 'facts_settings': _settings(facts_kw), 'stretch_count': n,
           'footage_s': round(sum(entries[f]['duration'] for f in files), 1), 'version': VERSION,
           'seconds': round(time.time() - t0, 1), 'folder': str(folder)}
    res['text_file'] = text_file(res, entries, folder / 'factlog.txt')
    if unavailable:                          # not kept: a PC that can build the missing logs makes the whole map
        res['unavailable'] = unavailable
        return res
    jf.write_text(json.dumps(res, indent=1), encoding='utf-8')
    return res


def _where(seg, many):
    s, e = seg['start'], seg['end']
    if not many or s['file'] == e['file']:
        name = Path(s['file']).name + ' ' if many else ''
        if Path(s['file']).suffix.lower() in PHOTO and s['file'] == e['file']:
            return f"{name}photo".strip()
        return f"{name}{_clock(s['t'])}-{_clock(e['t'])}"
    return f"{Path(s['file']).name} {_clock(s['t'])} - {Path(e['file']).name} {_clock(e['t'])}"


def segment_lines(seg_map, min_accuracy=None, frames=True, words=True, moments=True):
    """One line per segment: 'S03 IMG_0500 12:30.0-17:30.0 (5:00, 38 stretches) outdoors, night, ... | moments ...
    | text "..." | says "..." | frame seg003.jpg'."""
    acc = accuracy()
    mina = seg_map['settings']['min_accuracy'] if min_accuracy is None else min_accuracy
    many = len(seg_map['files']) > 1
    out = []
    for s in seg_map['segments']:
        nf = len(s['files'])
        bits = [f"S{s['n']:02d} {_where(s, many)}"]
        meta = [f"{_clock(s['seconds'])}"] if s['seconds'] else []
        if nf > 1:
            meta.append(f"{nf} files")
        if s.get('photos'):
            meta.append(f"{s['photos']} photo{'s' if s['photos'] > 1 else ''}")
        meta.append(f"{s['stretches']} stretch{'es' if s['stretches'] > 1 else ''}")
        line = bits[0] + f" ({', '.join(meta)}) " + fact_text({k: v for k, v in s['facts'].items()}, mina, acc)
        if moments and s.get('moments'):
            mm = {}
            for m in s['moments']:
                mm.setdefault(m['moment'], []).append((Path(m['file']).stem if many else '', m['at']))
            line += ' | ' + '; '.join(_mark(f'moments:{k}', k, acc, mina) + ' ' + ', '.join(
                (f'{f} ' if f else '') + _clock(t) for f, t in v[:3]) for k, v in mm.items())
        if s.get('text'):
            line += ' | ' + _mark('text', 'text', acc, mina) + ' ' + ' / '.join(f'"{t[:60]}"' for t in s['text'][:3])
        if words and s.get('first_words'):
            line += f' | says "{s["first_words"]}..."'
        if frames and s.get('frame'):
            line += f" | {Path(s['frame']).name}"
        out.append(line)
    return out


def text_file(seg_map, entries, out):
    """The segment map, then every file's stretches with their facts, in one text file; returns its path."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    st = seg_map['settings']
    head = [f"Fact log: {len(seg_map['files'])} files, {_clock(seg_map['footage_s'])} of video, "
            f"{seg_map['stretch_count']} stretches -> {len(seg_map['segments'])} segments.",
            legend(st['min_accuracy']),
            'Segment settings: ' + ', '.join(f'{k}={v}' for k, v in st.items()) + f"; split on: {', '.join(seg_map['split_keys'])}",
            f"Frames: {seg_map.get('folder', '')}", '', 'SEGMENTS'] + segment_lines(seg_map) + ['', 'STRETCHES']
    for f in seg_map['files']:
        e = entries.get(Path(f)) or entries.get(f)
        if not e:
            continue
        head.append(f"== {Path(f).name}  ({'photo' if e.get('kind') == 'photo' else _clock(e['duration'])}, "
                    f"{len(e['stretches'])} stretches, {e.get('asked', len(e['stretches']))} asked)")
        head += stretch_lines(e, st['min_accuracy'])
        head.append('')
    out.write_text('\n'.join(head), encoding='utf-8')
    return str(out)


def compact_stretch_lines(entry, min_accuracy=SEGMENT_DEFAULTS['min_accuracy']):
    """stretch_lines with neighbouring stretches of the same facts joined: '0:00.0-2:30.0 (19 stretches) ...'."""
    acc = accuracy()
    out, run = [], None
    for s in entry.get('stretches', []):
        t = fact_text(s.get('facts', {}), min_accuracy, acc)
        if run and run[2] == t:
            run[1], run[3] = s['to'], run[3] + 1
        else:
            if run:
                out.append(run)
            run = [s['from'], s['to'], t, 1]
    if run:
        out.append(run)
    if entry.get('kind') == 'photo':
        return [f'photo  {r[2]}' for r in out]
    return [f"{_clock(a)}-{_clock(b)}" + (f' ({n} stretches)' if n > 1 else '') + f'  {t}' for a, b, t, n in out]


# ------------------------------------------------------------------ on demand

def ask_frames(path, question, start=None, end=None, times=None, choices=None, frames=6, width=448, span_s=0.0,
               max_new_tokens=80, model=None):
    """The vision model's answer to one question at each of several times of a video (or for a photo).
    times: seconds; else `frames` times spread evenly over start-end (default the whole clip). span_s > 0: each
    answer sees 3 frames over span_s seconds around its time, else the one frame. choices: answers to pick from
    (the reply's pick is in 'choice'; None when it named none of them). Returns {'answers': [{'t', 'answer',
    'choice', 'frames'}], 'sheet': jpeg bytes, 'model', 'run_s', 'prompt'}; on a PC whose graphics card can't run the
    model (hardware.vision_unavailable) every answer is None, the sheet is the frames labelled with their times, and
    'unavailable' is the plain fact."""
    import letitedit.footage.shot_log as shot_log
    import letitedit.sound.model_tools as model_tools
    path = Path(path)
    tmp = Path(tempfile.mkdtemp(prefix='askframes-'))
    photo = path.suffix.lower() in PHOTO
    if photo:
        times = [0.0]
        groups = [[_photo_jpg(path, int(width) * 2, tmp)]]
    else:
        dur = shot_log._duration(path)
        if times:
            times = [max(0.0, min(dur - 0.05, float(t))) for t in times]
        else:
            a = 0.0 if start is None else max(0.0, float(start))
            b = dur if end is None else min(dur, float(end))
            n = max(1, int(frames))
            times = [round(a + (b - a) * (i + 0.5) / n, 2) for i in range(n)]
        groups = []
        for i, t in enumerate(times):
            sub = tmp / str(i)
            sub.mkdir()
            if span_s and span_s > 0:
                groups.append(shot_log._frames(path, max(0.0, t - span_s / 2), min(dur, t + span_s / 2), 3, width,
                                               sub))
            else:
                groups.append(shot_log._frames(path, t - 0.01, t + 0.01, 1, width, sub))
    tail = ASK_CHOICES.format(choices=' / '.join(choices)) if choices else ASK_FREE
    prompt = question.strip() + tail
    items = [{'images': g, 'prompt': prompt} for g in groups if g]
    import letitedit.core.hardware as hardware
    unavailable = None
    try:
        rep = model_tools.describe(items, max_new_tokens=max_new_tokens, batch=4, model=model) if items else {'texts': []}
    except hardware.LocalModelUnavailable as e:      # no graphics card for it: the frames, unanswered, and the fact
        rep, unavailable = {'texts': [], 'model': None, 'run_s': 0.0}, e.fact
    answers, k = [], 0
    for t, g in zip(times, groups):
        if not g or unavailable:
            answers.append({'t': t, 'answer': None, 'choice': None, 'frames': len(g)})
            continue
        text = rep['texts'][k].strip()
        k += 1
        pick = _pick(text.split('\n')[0], [c.lower() for c in choices]) if choices else None
        if pick is not None:
            pick = next(c for c in choices if c.lower() == pick)
        answers.append({'t': t, 'answer': text, 'choice': pick, 'frames': len(g)})
    from PIL import Image
    import letitedit.server.core_tools as core_tools
    tiles = []
    for g in groups:
        tiles.append(Image.open(g[len(g) // 2]).convert('RGB') if g else None)
    labels = [(('photo' if photo else _clock(a['t'])) + ('' if unavailable and a['frames'] else
                                                          ': ' + (a['choice'] or (a['answer'] or 'no frame'))[:30]))
              for a in answers]
    sheet = core_tools._sheet(tiles, labels, cols=4 if len(tiles) > 2 else len(tiles) or 1, tile_w=400)
    for p in sorted(tmp.rglob('*'), reverse=True):
        p.rmdir() if p.is_dir() else p.unlink(missing_ok=True)
    tmp.rmdir()
    out = {'answers': answers, 'sheet': sheet, 'model': rep.get('model'), 'run_s': rep.get('run_s'),
           'prompt': prompt}
    if unavailable:
        out['unavailable'] = unavailable
    return out


if __name__ == '__main__':
    import sys
    m = segment_map(sys.argv[1:])
    print('\n'.join(segment_lines(m)))
    print(m['text_file'], m['seconds'])
