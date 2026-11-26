"""Two edit scripts compared, and the YAML form.

Part of `edit_script` (letitedit/timeline/edit_script.py), which imports every name here back,
so `edit_script.X` is the same object it always was.
"""
from __future__ import annotations
import os
import letitedit.timeline.adjust as adjust
from letitedit.timeline.edit_script_base import (  # noqa: E402
    to_seconds
)


# ---------------------------------------------------------------------------- diff

def _says(it, track_name, limit=160):
    """': "the words heard in this clip"' for a clip on a speech track whose file is transcribed, else ''."""
    from letitedit.timeline.timeline_speech import NOT_SPEECH, _muted, _voice, heard_in
    if 'clip' not in it or 'in' not in it or 'out' not in it or NOT_SPEECH.search(track_name) or _muted(it)             or it.get('reverse') or float(it.get('speed', 1.0)) > 1.5:
        return ''
    try:
        import letitedit.sound.music as music
        if music.is_sound_library_file(it['clip']):
            return ''
        import letitedit.footage.speech as speech
        a, b = to_seconds(it['in']), to_seconds(it['out'])
        ws = speech.cached_words(it['clip'], a - 2, b + 2)
        if not ws:
            return ''
        import letitedit.footage.word_reheard as word_reheard
        ws = word_reheard.overlay(it['clip'], ws, a - 2, b + 2)     # what's already been heard; nothing is heard here
        voice = _voice(it['clip'])
        heard = [w for w in ws if heard_in(w, a, b, voice)]
        text = ' '.join(w['w'].strip() for w in heard).strip()
        # the speaker is still talking where the clip ends: say what comes next in the source
        goes_on = ''
        if heard and voice and heard[-1]['w'].strip()[-1:] not in '.!?' and any(x <= b - 0.05 and y >= b + 0.15 for x, y in voice):
            nxt = [w['w'].strip() for w in ws if w['s'] >= heard[-1]['e'] - 0.01 and w not in heard][:4]
            if nxt:
                goes_on = f' (the source goes on: "{" ".join(nxt)} ...")'
    except Exception:  # noqa: BLE001 - the words are a convenience in a change note
        return ''
    if not text:
        return ': (no words)'
    return f': "{text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."}"' + goes_on


FX_LINES = 3            # more items than this with changed effects: one line naming them all


def diff(a, b):
    """Plain-language changes from script a to script b."""
    out = []
    def index(s):
        d = {}
        for t in s['tracks']:
            for it in t['items']:
                if 'id' in it:
                    d[it['id']] = (t['name'], it)
        return d
    ia, ib = index(a), index(b)
    def label(it):
        if it.get('adjust'):
            return it.get('name') or adjust.DEFAULT_NAME
        if 'scene' in it:
            return it.get('name') or f"code scene {it['scene'].get('id')}"
        if 'graphic' in it:
            p = it['graphic'].get('params') or {}
            return f"{it['graphic']['template']} '{p.get('title') or p.get('text') or p.get('value') or ''}'"
        if 'ffmpeg' in it:
            return 'ffmpeg: ' + os.path.basename((it['ffmpeg'].get('inputs') or [{}])[0].get('clip', ''))
        if 'freeze' in it:
            return f"freeze of {os.path.basename(it['freeze'].get('clip', ''))} at {it['freeze'].get('at')}"
        if 'vfx' in it:
            return f"vfx {it['vfx'].get('effect')}"
        if 'ass' in it:
            return 'text layer (.ass)'
        if 'voice' in it:
            return f"voice '{str(it['voice'].get('text', ''))[:30]}'"
        return it.get('name') or os.path.basename(it.get('clip', '')) or it.get('color') or it.get('id')
    for iid, (tn, it) in ia.items():
        if iid not in ib:
            out.append(f'deleted {iid} ({label(it)}) from {tn} at {it.get("at")}')
    fx_changed = []         # (place in out, 'id (label)'): many become one line
    for iid, (tn, it) in ib.items():
        if iid not in ia:
            out.append(f'added {iid} ({label(it)}) on {tn} at {it.get("at")} for {it.get("len")} s' + _says(it, tn))
            continue
        ta, old = ia[iid]
        if ta != tn:
            out.append(f'moved {iid} ({label(it)}) from {ta} to {tn}')
        if old.get('clip') != it.get('clip'):
            out.append(f'{iid}: source changed to {label(it)}')
        if old.get('scene') != it.get('scene'):
            out.append(f'{iid} ({label(it)}): code scene revision changed to {it.get("scene", {}).get("revision")}')
        trimmed = False
        for k in ('in', 'out'):
            if k in old and k in it and abs(to_seconds(old[k]) - to_seconds(it[k])) > 0.02:
                d = to_seconds(it[k]) - to_seconds(old[k])
                out.append(f'{iid} ({label(it)}): {"start" if k == "in" else "end"} trimmed {"later" if d > 0 else "earlier"} by {abs(d):.2f} s')
                trimmed = True
        if trimmed and _says(it, tn):
            out.append(f'{iid} now says' + _says(it, tn))
        if not trimmed and 'len' in old and 'len' in it and abs(to_seconds(old['len']) - to_seconds(it['len'])) > 0.02:
            out.append(f'{iid} ({label(it)}): length {to_seconds(old["len"]):g} -> {to_seconds(it["len"]):g} s')
        if abs(float(old.get('speed', 1)) - float(it.get('speed', 1))) > 1e-6:
            out.append(f'{iid}: speed {old.get("speed", 1)}x -> {it.get("speed", 1)}x')
        if old.get('effects') != it.get('effects'):
            fx_changed.append((len(out), f'{iid} ({label(it)})'))
            out.append(f'{iid} ({label(it)}): effects changed')
        for key in ('ffmpeg', 'freeze', 'graphic', 'reverse', 'vfx', 'voice', 'ass'):
            if old.get(key) != it.get(key):
                out.append(f'{iid} ({label(it)}): {key} recipe changed, re-rendered')
        if old.get('transition') != it.get('transition'):
            tr = it.get('transition')
            out.append(f"{iid} ({label(it)}): " + (f"{tr.get('type', 'dissolve')} transition in, {tr.get('len')} s"
                                                    if isinstance(tr, dict) else 'no transition in'))
        if old.get('at') != it.get('at') and ta == tn:
            out.append(f'{iid} ({label(it)}): now at {it.get("at")} (was {old.get("at")})')
    if len(fx_changed) > FX_LINES:
        first = fx_changed[0][0]
        drop = {n for n, _ in fx_changed}
        out[:] = [line for n, line in enumerate(out) if n not in drop or n == first]
        out[first] = f'effects changed on {len(fx_changed)} items: ' + ', '.join(w for _, w in fx_changed)
    ca = {c['track']: c['cues'] for c in a.get('captions', [])}
    cb = {c['track']: c['cues'] for c in b.get('captions', [])}
    for name in set(ca) | set(cb):
        if ca.get(name) != cb.get(name):
            out.append(f'captions "{name}": {len(ca.get(name, []))} -> {len(cb.get(name, []))} cues (text or timing changed)')
    sa = {c['track']: c.get('style') or {} for c in a.get('captions', [])}
    sb = {c['track']: c.get('style') or {} for c in b.get('captions', [])}
    for name in set(sa) & set(sb):
        changed = [f'{k} {sa[name].get(k)} -> {sb[name].get(k)}' for k in sorted(set(sa[name]) | set(sb[name]))
                   if str(sa[name].get(k)) != str(sb[name].get(k))]
        if changed:
            out.append(f'caption style "{name}": ' + ', '.join(changed))
    ta = {t['name']: t for t in a.get('tracks', [])}
    for t in b.get('tracks', []):
        o = ta.get(t['name'])
        if o is None:
            out.append(f"added track {t['name']} ({t.get('kind', 'video')})")
            continue
        for key, what in (('gain', 'volume'), ('duck', 'auto-duck'), ('effects', 'effects'), ('hide', 'hidden')):
            if o.get(key) != t.get(key):
                old_v, new_v = o.get(key), t.get(key)
                if key == 'gain' and not isinstance(old_v, dict) and not isinstance(new_v, dict):
                    out.append(f"track {t['name']}: volume {old_v if old_v is not None else 0} dB -> "
                               f"{new_v if new_v is not None else 0} dB")
                else:
                    out.append(f"track {t['name']}: {what} changed")
    for name in set(ta) - {t['name'] for t in b.get('tracks', [])}:
        out.append(f'removed track {name}')
    if a.get('master') != b.get('master'):
        out.append('master (whole-video) effects changed')
    if (a.get('look') or None) != (b.get('look') or None):
        out.append(f"Look: {a.get('look') or 'neutral'} -> {b.get('look') or 'neutral'}")
    if (a.get('hook') or None) != (b.get('hook') or None):
        out.append(f"opening: {(a.get('hook') or 'h0').split('|')[0]} -> {(b.get('hook') or 'h0').split('|')[0]}")
    if a.get('length') != b.get('length'):
        out.append(f'length {a.get("length")} -> {b.get("length")}')
    moves = [x for x in out if 'now at' in x]
    if len(moves) > 12:
        out = [x for x in out if 'now at' not in x] + [f'{len(moves)} clips shifted in time']
    return out


# ---------------------------------------------------------------------------- yaml

def to_yaml(script):
    import yaml

    class Dumper(yaml.SafeDumper):
        pass

    def flow_dict(dumper, data):
        flow = len(data) <= 3 and all(not isinstance(v, (dict, list)) for v in data.values())
        return dumper.represent_mapping('tag:yaml.org,2002:map', data, flow_style=flow)

    Dumper.add_representer(dict, flow_dict)
    import letitedit.timeline.stack as stack
    head = ('# letitedit edit script of this timeline. Items are in order; positions (at) and lengths (len) are for\n'
            '# reading. Edit with letitedit_timeline_apply: changes (ops by id), or the whole script sent back as script_yaml.\n')
    return head + stack.comment(script) + yaml.dump(script, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=140)


def from_yaml(text):
    import yaml
    script = yaml.safe_load(text)
    for t in (script or {}).get('tracks') or []:
        for it in t.get('items') or []:
            it.pop('said', None)          # shown by reads, not part of the timeline
            it.pop('recorded', None)
    return script
