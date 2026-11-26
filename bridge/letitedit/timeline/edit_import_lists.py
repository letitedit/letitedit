"""Edit lists: a JSON or Python list of segments (or tracks of them), or a .py file that assigns one.

Part of `edit_import` (letitedit/timeline/edit_import.py), which imports every name here back,
so `edit_import.X` is the same object it always was.
"""
from __future__ import annotations
import ast
import copy
import json
import os
import re
import sys
from pathlib import Path
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
HERE = _paths.BRIDGE
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import letitedit.timeline.edit_script as es  # noqa: E402
import letitedit.timeline.made as made  # noqa: E402
from letitedit.timeline.edit_import_common import (  # noqa: E402
    _db, _ext, _find_media, _item_tlen, _kind_of_file, _r, _text_item, _time, item_len
)
from letitedit.timeline.edit_import_scripts import (  # noqa: E402
    _parse_py
)


# ============================================================================ list form

_EDIT_NAMES = ('EDIT', 'EDL', 'SEGMENTS', 'CUTS', 'CLIPS', 'TIMELINE', 'TRACKS', 'SHOTS', 'EDITS', 'PLAYLIST', 'ITEMS')


def _py_literal(text):
    """The edit list a .py file assigns at module level (ast.literal_eval of the assigned literal), or None."""
    try:
        tree = _parse_py(text)
    except SyntaxError:
        return None
    found = []
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name) and isinstance(value, (ast.List, ast.Dict, ast.Tuple)):
                try:
                    found.append((t.id, ast.literal_eval(value)))
                except (ValueError, SyntaxError, TypeError):
                    pass
    if not found:
        return None
    named = [v for k, v in found if k.upper() in _EDIT_NAMES]
    if named:
        return named[-1]
    segs = [v for k, v in found if _looks_like_segments(v)]
    return (segs or [max(found, key=lambda kv: len(kv[1]))[1]])[-1]


def _looks_like_segments(obj):
    if isinstance(obj, dict):
        return any(isinstance(v, list) for v in obj.values())
    if not isinstance(obj, (list, tuple)) or not obj:
        return False
    return all(isinstance(x, (dict, list, tuple, str)) for x in obj)


KEY_ALIASES = {
    'clip': ('clip', 'file', 'src', 'path', 'source', 'media', 'filename', 'video', 'input', 'asset', 'footage', 'url',
             'sourcefile', 'mediafile', 'filepath', 'audio', 'image', 'picture', 'music', 'sound', 'sfx'),
    'in': ('in', 'start', 'ss', 'from', 'sourcein', 'srcin', 'inpoint', 'begin', 'trimstart', 'startsec', 'starts',
           'startseconds', 'ins', 'insec', 'starttime', 'sourcestart', 'srcstart', 'clipin', 'mediain'),
    'out': ('out', 'end', 'to', 'sourceout', 'srcout', 'outpoint', 'stop', 'trimend', 'endsec', 'ends', 'endseconds',
            'outs', 'outsec', 'endtime', 'sourceend', 'srcend', 'clipout', 'mediaout'),
    'dur': ('dur', 'duration', 'len', 'length', 'durationsec', 'durs', 'seconds', 'durationseconds'),
    'track': ('track', 'layer', 'lane', 'trackname'),
    'at': ('at', 'time', 'position', 'pos', 'timelinestart', 'recordin', 'recin', 'offset', 'placeat', 'startat',
           'timelinein', 'tlstart', 'atsec', 'timelineposition', 'when'),
    'text': ('text', 'caption', 'title', 'subtitle', 'overlaytext', 'captiontext', 'lowerthird'),
    'gain': ('gain', 'volume', 'vol', 'db', 'level', 'gaindb', 'volumedb'),
    'speed': ('speed', 'rate', 'playbackrate', 'playbackspeed'),
    'effects': ('effects', 'filter', 'filters', 'vf', 'fx', 'effect'),
    'name': ('name', 'label', 'note', 'notes', 'comment', 'description', 'desc', 'purpose', 'beat', 'role'),
    'transition': ('transition', 'dissolve', 'crossfade', 'xfade'),
}
NATIVE_KEYS = {'id', 'clip', 'in', 'out', 'at', 'len', 'speed', 'effects', 'transition', 'name', 'gap', 'color', 'ffmpeg',
               'ass', 'graphic', 'freeze', 'vfx', 'voice', 'reverse', 'skip', 'words', 'near'}
_ALIAS = {a: k for k, al in KEY_ALIASES.items() for a in al}
AUDIO_TRACK = re.compile(r'^(a\s*\d*|audio.*|music.*|sfx.*|sound.*|vo|voice.*|narration.*|bed.*|score.*)$', re.I)
TEXT_TRACK = re.compile(r'^(text.*|title.*|caption.*|subtitle.*|subs?|lower.?third.*|words?)$', re.I)
MAIN_TRACK = re.compile(r'^(v1?|video\s*1?|main|picture|a-?roll|primary|track\s*1|1)$', re.I)


def _norm_key(k):
    return re.sub(r'[^a-z0-9]', '', str(k).lower())


def _key_map(seg):
    """{original key: field} for one segment dict."""
    out = {}
    for k in seg:
        if k in NATIVE_KEYS:
            out[k] = 'dur' if k == 'len' else k
            continue
        n = _norm_key(k)
        f = _ALIAS.get(n) or _ALIAS.get(re.sub(r'(sec|secs|seconds|s|ms)$', '', n))
        if f:
            out[k] = f
    fields = list(out.values())
    if fields.count('in') > 1:      # 'start' next to 'in': start is the timeline time
        for k, f in list(out.items()):
            if f == 'in' and _norm_key(k) in ('start', 'starttime', 'startsec', 'starts', 'begin') and any(
                    v == 'in' and kk != k for kk, v in out.items()):
                out[k] = 'at'
    if list(out.values()).count('out') > 1:
        for k, f in list(out.items()):
            if f == 'out' and _norm_key(k) in ('end', 'endtime', 'stop') and any(v == 'out' and kk != k for kk, v in out.items()):
                out[k] = '_end'
    if list(out.values()).count('clip') > 1:     # prefer the key that names a file
        firsts = [k for k, f in out.items() if f == 'clip']
        keep = next((k for k in firsts if isinstance(seg[k], str) and _ext(seg[k])), firsts[0])
        for k in firsts:
            if k != keep:
                out[k] = 'name' if isinstance(seg[k], str) else None
    return {k: f for k, f in out.items() if f}


class _ListReader:
    def __init__(self, data, path, base_dir, media_dir, fps, notes):
        self.data, self.path, self.notes = data, path, notes
        self.dirs = [d for d in (*(media_dir or []), base_dir, Path.cwd()) if d]
        self.fps = fps or 30.0
        self.mapping, self.unread, self.unresolved = {}, set(), []
        self.tuple_note = False

    def media(self, name):
        got = _find_media(name, self.dirs)
        if got is None and name not in self.unresolved:
            self.unresolved.append(name)
        return got

    def read(self):
        data = self.data
        if isinstance(data, str):
            data = self._parse(data)
        tracks = self._tracks(data)
        nums = [seg.get(k) for _, _, segs, _ in tracks for seg in segs if isinstance(seg, dict)
                for k, f in _key_map(seg).items() if f == 'track' and isinstance(seg.get(k), int)]
        self.zero_based = bool(nums) and min(nums) == 0
        model = {'tracks': [], 'notes': self.notes, 'made': []}
        main = self._pick_main(tracks)
        out_tracks = {}
        order = []

        def track(name, kind):
            if name not in out_tracks:
                out_tracks[name] = {'name': name, 'kind': kind, 'items': [], 'pos': 0.0}
                order.append(name)
            return out_tracks[name]

        track('V1', 'video')['main'] = True
        main_pos = main_last = 0.0
        for tname, tkind, segs, tgain in tracks:
            is_main = tname is main
            for seg in segs:
                it, extra = self._item(seg)
                if it is None:
                    continue
                ttrack = extra.get('track')
                if isinstance(ttrack, (int, float)) and not isinstance(ttrack, bool):
                    n = int(ttrack) + (1 if self.zero_based else 0)
                    ttrack = None if n <= 1 and _kind_of_file(it.get('clip', '')) != 'audio' else n
                if ttrack is None and not is_main and tname is not None:
                    ttrack = tname
                if 'gap' in it:
                    g = es.to_seconds(it['gap'])
                    if ttrack is None or MAIN_TRACK.match(str(ttrack)):
                        out_tracks['V1']['items'].append({'gap': _r(g)})
                        main_pos += g
                    else:
                        tk = tkind or ('audio' if AUDIO_TRACK.match(str(ttrack)) else 'video')
                        t = track(str(ttrack), tk)
                        t['pos'] += g
                    continue
                kind = self._kind_for(it, ttrack, tkind)
                text = extra.get('text')
                at = extra.get('at')
                if kind == 'text' or ('ass' in it and ttrack is None):
                    name = ttrack if isinstance(ttrack, str) and not MAIN_TRACK.match(str(ttrack)) else 'Text'
                    t = track(name, 'video')
                    start = at if at is not None else (main_last if is_main or tname is None else t['pos'])
                    it['at'] = _r(start)
                    t['items'].append(it)
                    t['pos'] = start + item_len(it)
                    continue
                if kind == 'audio':
                    name = ttrack if isinstance(ttrack, str) else ('A1' if ttrack is None else f'A{max(1, ttrack)}')
                    t = track(name, 'audio')
                    start = at if at is not None else t['pos']
                    it['at'] = _r(start)
                    t['items'].append(it)
                    t['pos'] = start + item_len(it)
                    continue
                # video / picture
                on_main = (ttrack is None and (is_main or tname is None)) or (ttrack is not None and MAIN_TRACK.match(str(ttrack)))
                if on_main:
                    t = out_tracks['V1']
                    expect = main_pos - (_item_tlen(it) if t['items'] and 'gap' not in t['items'][-1] else 0.0)
                    if at is not None and at > expect + 1e-3:
                        t['items'].append({'gap': _r(at - expect)})
                        main_pos = at + (main_pos - expect)
                        it.pop('transition', None)
                    elif at is not None and at < expect - 1e-3:
                        self.notes.append(f"{self._label(it)}: at {at:g} s overlaps the clip before it on the main track; "
                                          'placed on V2 at that time')
                        on_main = False
                        ttrack = 'V2'
                    if on_main:
                        main_last = main_pos
                        t['items'].append(it)
                        L = item_len(it)
                        if text:
                            tt = track('Text', 'video')
                            tx = _text_item(text, L)
                            tx['at'] = _r(main_pos)
                            tt['items'].append(tx)
                        main_pos += L - _item_tlen(it)
                        continue
                name = ttrack if isinstance(ttrack, str) else f'V{ttrack}'
                t = track(name, 'video')
                start = at if at is not None else t['pos']
                it['at'] = _r(start)
                t['items'].append(it)
                t['pos'] = start + item_len(it)
                if text:
                    tt = track('Text', 'video')
                    tx = _text_item(text, item_len(it))
                    tx['at'] = _r(start)
                    tt['items'].append(tx)
            if tgain is not None and tname is not None:
                key = 'V1' if is_main else tname
                if key in out_tracks:
                    out_tracks[key]['gain'] = tgain
        # text tracks above pictures, audio last
        vids = [n for n in order if out_tracks[n]['kind'] == 'video' and not TEXT_TRACK.match(n)]
        texts = [n for n in order if out_tracks[n]['kind'] == 'video' and TEXT_TRACK.match(n)]
        auds = [n for n in order if out_tracks[n]['kind'] == 'audio']
        for n in vids + texts + auds:
            t = out_tracks[n]
            t.pop('pos', None)
            model['tracks'].append(t)
        if self.mapping:
            model['notes'].insert(0, 'keys read: ' + ', '.join(f'{k} -> {v}' for k, v in sorted(self.mapping.items())))
        if self.tuple_note:
            model['notes'].insert(0, 'tuples read as (clip, in, out, labels): the string naming a file is the clip, the '
                                     'first two numbers in and out, other strings labels (the clip name)')
        if self.unread:
            model['notes'].append('keys not read: ' + ', '.join(sorted(self.unread)))
        if self.unresolved:
            model['notes'].append('no file found for: ' + ', '.join(map(str, self.unresolved[:20])) +
                                  ' (each is a black placeholder; media_dir= says where to look)')
        return model

    def _label(self, it):
        return it.get('name') or os.path.basename(str(it.get('clip', ''))) or 'an item'

    def _parse(self, text):
        s = text.lstrip()
        try:
            return json.loads(s)
        except ValueError:
            pass
        try:
            return ast.literal_eval(s)
        except (ValueError, SyntaxError):
            pass
        lit = _py_literal(text)
        if lit is None:
            raise ValueError('no edit list found: give a JSON or Python literal list of segments, or a .py file that '
                             'assigns one (EDIT = [...])')
        self.notes.append('read the list a .py file assigns (ast.literal_eval, not run)')
        return lit

    def _tracks(self, data):
        """[(track name or None, kind or None, segments, gain)]"""
        if isinstance(data, dict):
            if isinstance(data.get('tracks'), list):
                out = []
                for t in data['tracks']:
                    if isinstance(t, dict):
                        segs = t.get('items') or t.get('clips') or t.get('segments') or t.get('children') or []
                        out.append((t.get('name') or t.get('track'), t.get('kind'), segs, t.get('gain')))
                    elif isinstance(t, list):
                        out.append((None, None, t, None))
                return out
            if isinstance(data.get('tracks'), dict):
                return [(k, None, v, None) for k, v in data['tracks'].items() if isinstance(v, list)]
            for k in data:
                if _norm_key(k) in ('edit', 'segments', 'clips', 'cuts', 'timeline', 'items', 'shots', 'events',
                                    'playlist', 'edl', 'sequence'):
                    return self._tracks(data[k])
            lists = [(k, v) for k, v in data.items() if isinstance(v, list)]
            if lists:
                return [(k, None, v, None) for k, v in lists]
            return [(None, None, [data], None)]
        if isinstance(data, (list, tuple)):
            if data and all(isinstance(x, dict) and isinstance(x.get('items'), list) for x in data):
                return self._tracks({'tracks': list(data)})
            return [(None, None, list(data), None)]
        raise ValueError(f'an edit list is a list of segments (or tracks of them), not {type(data).__name__}')

    def _pick_main(self, tracks):
        named = [t for t in tracks if t[0] is not None]
        for t in named:
            if MAIN_TRACK.match(str(t[0])) and (t[1] in (None, 'video')):
                return t[0]
        for t in named:
            if t[1] in (None, 'video') and not AUDIO_TRACK.match(str(t[0])) and not TEXT_TRACK.match(str(t[0])):
                return t[0]
        return None

    def _kind_for(self, it, ttrack, tkind):
        if 'ass' in it:
            return 'text'
        if tkind == 'audio' or (isinstance(ttrack, str) and AUDIO_TRACK.match(ttrack) and not MAIN_TRACK.match(ttrack)):
            return 'audio'
        if isinstance(ttrack, str) and TEXT_TRACK.match(ttrack):
            return 'text' if 'clip' not in it else 'video'
        if 'clip' in it and _kind_of_file(it['clip']) == 'audio':
            return 'audio'
        return 'video'

    def _item(self, seg):
        """(edit-script item, {track, at, text}) for one segment."""
        if isinstance(seg, str):
            seg = (seg,)
        if isinstance(seg, (list, tuple)):
            return self._tuple(seg)
        if not isinstance(seg, dict):
            self.notes.append(f'skipped a segment that is not a dict, tuple or file name: {seg!r}'[:200])
            return None, {}
        if 'gap' in seg and len(seg) == 1:
            return {'gap': _time(seg['gap'], self.fps)}, {}
        km = _key_map(seg)
        for k, f in km.items():
            if k != f and not (k in NATIVE_KEYS):
                self.mapping[k] = f
        for k in seg:
            if k not in km:
                self.unread.add(str(k))
        get = {f: seg[k] for k, f in km.items()}
        it, extra = {}, {}
        for k in ('ffmpeg', 'ass', 'graphic', 'freeze', 'vfx', 'voice', 'color', 'reverse', 'skip', 'words', 'near'):
            if k in seg:
                it[k] = copy.deepcopy(seg[k])
        if 'id' in seg and isinstance(seg['id'], str):
            it['id'] = seg['id']
        elif 'id' in seg:
            self.unread.add('id (not text)')
        clip = get.get('clip')
        if clip is not None and not made.is_made(it):
            found = self.media(clip)
            if found is None:
                it = {'color': '#ff000000'}
                extra['missing'] = clip
                it['name'] = f'missing: {os.path.basename(str(clip))}'
            else:
                it['clip'] = found
        a = _time(get['in'], self.fps) if get.get('in') is not None else None
        b = _time(get['out'], self.fps) if get.get('out') is not None else None
        d = _time(get['dur'], self.fps) if get.get('dur') is not None else None
        if a is not None and b is not None and b <= a:
            self.notes.append(f'{os.path.basename(str(clip))}: out {b:g} is not after in {a:g}; read out as a length')
            b = a + b
        if 'clip' in it:
            if a is not None:
                it['in'] = _r(a)
            if b is not None:
                it['out'] = _r(b)
            elif d is not None:
                it.setdefault('in', 0.0)
                if _kind_of_file(it['clip']) == 'image':
                    it['out'] = _r(it['in'] + d)
                else:
                    sp = float(get.get('speed') or 1.0)
                    it['out'] = _r(it['in'] + d * sp)
            elif _kind_of_file(it['clip']) == 'image':
                it.setdefault('in', 0.0)
        elif 'color' in it or made.is_made(it) or 'graphic' in it:
            if d is not None:
                it['len'] = _r(d)
            elif a is not None and b is not None and 'color' in it:
                it['len'] = _r(b - a)
            elif seg.get('len') is not None:
                it['len'] = _r(_time(seg['len'], self.fps))
        if get.get('speed') not in (None, 1, 1.0) and 'clip' in it:
            it['speed'] = float(get['speed'])
        if get.get('name') is not None:
            it['name'] = str(get['name']) if not isinstance(get['name'], (list, tuple)) else ' / '.join(map(str, get['name']))
        effects = get.get('effects')
        if effects is not None:
            if isinstance(effects, str):
                effects = [{'ffmpeg': effects}]
            elif isinstance(effects, dict):
                effects = [effects]
            it['effects'] = list(effects)
        g = get.get('gain')
        if g is not None:
            gk = next(k for k, f in km.items() if f == 'gain')
            if isinstance(g, str) and g.strip().lower().endswith('db'):
                dbv = float(g.strip()[:-2])
            elif _norm_key(gk) in ('volume', 'vol', 'level') and isinstance(g, (int, float)) and 0 <= g <= 4:
                dbv = _db(g) if g > 0 else -96.0
                self.mapping[f'{gk} (factor {g:g})'] = f'gain {dbv:g} dB'
            else:
                dbv = float(g)
            it.setdefault('effects', []).append({'gain': _r(dbv, 3)} if dbv > -96 else 'mute')
        tr = get.get('transition')
        if tr is not None and tr is not False:
            it['transition'] = tr if isinstance(tr, (dict, int, float)) else _time(tr, self.fps)
        if get.get('track') is not None:
            extra['track'] = get['track']
        if get.get('at') is not None:
            extra['at'] = _time(get['at'], self.fps)
        if get.get('text') is not None:
            if not it or ('clip' not in it and 'color' not in it and not made.is_made(it)):
                L = d if d is not None else ((b - a) if a is not None and b is not None else None)
                tx = _text_item(get['text'], L if L else made.ass_length(''))
                if L is None:
                    self.notes.append(f"text {str(get['text'])[:30]!r} has no length; it lasts "
                                      f"{made.ass_length('')} s (the .ass default)")
                for k in ('id',):
                    if k in it:
                        tx[k] = it[k]
                if a is not None and get.get('at') is None and b is not None:
                    extra['at'] = a
                return tx, extra
            extra['text'] = get['text']
        if not it or ('clip' not in it and 'color' not in it and not made.is_made(it) and 'graphic' not in it):
            if 'missing' not in extra:
                self.notes.append(f'skipped a segment with no clip: {seg!r}'[:200])
            return None, {}
        return it, extra

    def _tuple(self, seg):
        self.tuple_note = True
        clip, nums, labels = None, [], []
        for x in seg:
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                nums.append(float(x))
            elif isinstance(x, str):
                if clip is None and (self.media(x) if (_ext(x) or os.sep in x or '/' in x) else _find_media(x, self.dirs)):
                    clip = self.media(x)
                elif clip is None and re.fullmatch(r'[\d:.;]+', x.strip()) and ':' in x:
                    nums.append(_time(x, self.fps))
                else:
                    labels.append(x)
            elif isinstance(x, dict):
                labels.append(json.dumps(x))
        if clip is None:
            self.notes.append(f'no file in segment {seg!r}'[:200])
            if labels and _ext(labels[0]):
                self.unresolved.append(labels[0])
                it = {'color': '#ff000000', 'len': _r(nums[1] - nums[0]) if len(nums) >= 2 else 5.0,
                      'name': f'missing: {os.path.basename(labels[0])}'}
                return it, {}
            return None, {}
        it = {'clip': clip}
        if nums:
            it['in'] = _r(nums[0])
        if len(nums) >= 2:
            it['out'] = _r(nums[1] if nums[1] > nums[0] else nums[0] + nums[1])
        elif _kind_of_file(clip) == 'image':
            it.setdefault('in', 0.0)
        if len(nums) > 2:
            self.notes.append(f'{os.path.basename(clip)}: numbers after in/out not read: {nums[2:]}')
        if labels:
            it['name'] = ' / '.join(labels)
        return it, {}
