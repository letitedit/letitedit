"""One typed New video request (T319's H1): what the person chose in New video, resolved, as data.

The editor's New video dialog builds the request's text in C++ (src/letitedit/newvideo/request.cpp: firstCutRequest,
appendLookRequest, themeRequest, inputsRequestText). This module holds the same request as typed fields and renders
exactly that text from them, so a caller without the dialog (a Studio job, a session runner) makes the same request
the person's New video makes, and a route predicate (music, captions, the Look, footage or none) reads a field instead
of matching words in free text.

    normalize(data)        -> the typed request (a dict), checked; RequestError on anything malformed
    render(data)           -> the request text, byte for byte what the dialog sends for the same choices
    facts(data)            -> the route facts: kind, short, look and its kind, captions, music, footage, theme ...
    facts_from_text(text)  -> the same facts read from a request's text (a request made before the typed record)
    write(folder, data, text=None)   keeps the record beside the video as new-video-request.json (its text and hash)
    read(folder)           -> the kept record, or None
    parity(record)         -> {'ok', 'first_difference'}: does render() give the text the editor sent?

The record holds resolved choices, not the dialog's widgets: the Looks "Let the AI pick" chooses from, the Themes
shown, the fit check's verdict and the Look's boxes are written as they were when Go was pressed. Resolving them
without the dialog is the Studio's part (letitedit.studio.new_video_resolve), over the same catalogue.

The switch: settings.json `typed_new_video_request` (default true; LETITEDIT_TYPED_NEW_VIDEO_REQUEST, 1 or 0, wins).
On, the editor writes the record beside each New video's folder and the Studio keeps it with its job. Off, nothing
here is used: the request is made and sent exactly as before.
"""
import copy
import hashlib
import json
import os
import re
from pathlib import Path

FORMAT = 'letitedit-new-video-request/1'
FILE = 'new-video-request.json'
SETTING = 'typed_new_video_request'
ENV = 'LETITEDIT_TYPED_NEW_VIDEO_REQUEST'

KINDS = ('short', 'long', 'custom', 'both')
# the special Look values of a Style with Looks (the router's `look` field)
LOOK_CHOICES = ('auto', 'freestyle')
# what each box role of a Look means to the AI (NewVideoDialog::roleMeaning)
ROLE_MEANINGS = {
    'show': 'these may appear on screen in the video',
    'style': 'look at these for the feel the person wants; they must never appear in the video',
    'voiceover': "the person's own voice: use it as the narration",
    'product': 'what the video is selling or showing',
    'person': 'who the video is about or for',
    'about': "what the video is about, in the person's words",
}
# fields kept with a record that are not part of the request itself
META = ('origin', 'text', 'text_sha256', 'written', 'summary')

_DEFAULTS = {
    'format': FORMAT, 'kind': 'short', 'custom': '', 'length': '', 'about': '', 'turbo': False, 'no_footage': False,
    'footage': {'folder': '', 'files': []},
    'look': {'has_looks': False, 'style': 'none', 'style_label': '', 'mine': False, 'id': '', 'label': '',
             'style_kind_label': '', 'files': [], 'waiting_for_learn': False},
    'inputs': None, 'modern': True, 'filmed_style': None, 'multicam': False, 'auto_shown': [], 'look_line': False,
    'fit': None, 'faces': None, 'theme': {'mode': 'none', 'own': None, 'shown': [], 'chosen': []}, 'references': [],
    'captions': 'auto', 'music': 'auto', 'music_file': '', 'song': '', 'save_folder': '',
}


class RequestError(ValueError):
    """A typed request that can't be made into the person's request: say what is wrong, never guess."""


def enabled():
    """Whether this install keeps the typed request (the switch above; on by default)."""
    forced = os.environ.get(ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


# ------------------------------------------------------------------ checking

def _str(value, where):
    if not isinstance(value, str):
        raise RequestError(f'{where} must be text, not {type(value).__name__}.')
    return value


def _bool(value, where):
    if not isinstance(value, bool):
        raise RequestError(f'{where} must be true or false.')
    return value


def _strs(value, where):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RequestError(f'{where} must be a list of text.')
    return list(value)


def _object(value, where, keys):
    if not isinstance(value, dict):
        raise RequestError(f'{where} must be an object.')
    unknown = sorted(set(value) - set(keys))
    if unknown:
        raise RequestError(f'{where} has fields this request does not know: {", ".join(unknown)}.')
    return value


def _theme_entry(value, where):
    entry = _object(value, where, ('id', 'title', 'recipe', 'recipe_shared'))
    out = {key: _str(entry.get(key, ''), f'{where}.{key}') for key in ('id', 'title', 'recipe', 'recipe_shared')}
    if not out['id']:
        raise RequestError(f'{where} needs its id.')
    return out


def normalize(data):
    """The typed request with every field present and checked. Unknown fields, wrong types and choices that can't
    have come from New video are refused (RequestError), never dropped or guessed."""
    if not isinstance(data, dict):
        raise RequestError('A New video request is an object.')
    data = {key: value for key, value in data.items() if key not in META}
    _object(data, 'the request', _DEFAULTS)
    if data.get('format', FORMAT) != FORMAT:
        raise RequestError(f'This is not a {FORMAT} record (format {data.get("format")!r}).')
    out = copy.deepcopy(_DEFAULTS)
    for key in ('kind', 'custom', 'length', 'about', 'captions', 'music', 'music_file', 'song', 'save_folder'):
        if key in data:
            out[key] = _str(data[key], key)
    for key in ('turbo', 'no_footage', 'modern', 'multicam', 'look_line'):
        if key in data:
            out[key] = _bool(data[key], key)
    for key in ('auto_shown', 'references'):
        if key in data:
            out[key] = _strs(data[key], key)
    if out['kind'] not in KINDS:
        raise RequestError(f'kind must be one of {", ".join(KINDS)}, not {out["kind"]!r}.')
    if out['kind'] == 'custom' and not out['custom'].strip():
        raise RequestError('A custom video needs its description (custom).')
    if out['length'] and not re.fullmatch(r'\d+ seconds', out['length']):
        raise RequestError(f'length is "<n> seconds" or empty (the AI chooses), not {out["length"]!r}.')
    for key in ('captions', 'music'):
        if not out[key].strip():
            raise RequestError(f'{key} is "auto" or a choice, not empty.')
    footage = _object(data.get('footage', {}), 'footage', ('folder', 'files'))
    out['footage'] = {'folder': _str(footage.get('folder', ''), 'footage.folder'),
                      'files': _strs(footage.get('files', []), 'footage.files')}
    look = _object(data.get('look', {}), 'look', _DEFAULTS['look'])
    for key, default in _DEFAULTS['look'].items():
        if key in look:
            out['look'][key] = (_bool if isinstance(default, bool) else _strs if isinstance(default, list)
                                else _str)(look[key], f'look.{key}')
    if out['look']['has_looks']:
        if not out['look']['id']:
            raise RequestError('A Style with Looks sends its Look (look.id: a Look id, auto or freestyle).')
    elif out['look']['id']:
        raise RequestError('look.id is only for a Style with Looks (look.has_looks).')
    if not out['look']['style']:
        raise RequestError('look.style is a Look id or "none".')
    if not out['no_footage'] and not out['footage']['folder'] and not out['footage']['files']:
        raise RequestError('A video from footage names its folder or files (footage).')
    if out['no_footage'] and out['footage']['files']:
        raise RequestError('A video with no footage lists no footage files.')
    if data.get('filmed_style') is not None:
        filmed = _object(data['filmed_style'], 'filmed_style', ('id', 'label'))
        out['filmed_style'] = {'id': _str(filmed.get('id', ''), 'filmed_style.id'),
                               'label': _str(filmed.get('label', ''), 'filmed_style.label')}
        if not out['filmed_style']['id']:
            raise RequestError('filmed_style needs its id.')
    if data.get('fit') is not None:
        fit = _object(data['fit'], 'fit', ('verdict', 'line', 'look_only'))
        out['fit'] = {'verdict': _str(fit.get('verdict', ''), 'fit.verdict'), 'line': _str(fit.get('line', ''), 'fit.line'),
                      'look_only': _bool(fit.get('look_only', False), 'fit.look_only')}
        if not out['fit']['verdict']:
            raise RequestError('fit needs its verdict.')
    if data.get('faces') is not None:
        faces = _object(data['faces'], 'faces', ('with_face', 'frames', 'person_looks'))
        try:
            with_face, frames = int(faces.get('with_face', 0)), int(faces.get('frames', 0))
        except (TypeError, ValueError):
            raise RequestError('faces.with_face and faces.frames are counts of frames.') from None
        if frames <= 0 or not 0 <= with_face <= frames:
            raise RequestError('faces counts the frames looked at (frames > 0) and those with a face in them.')
        out['faces'] = {'with_face': with_face, 'frames': frames,
                        'person_looks': _strs(faces.get('person_looks', []), 'faces.person_looks')}
    theme = _object(data.get('theme', {}), 'theme', ('mode', 'own', 'shown', 'chosen'))
    out['theme']['mode'] = _str(theme.get('mode', 'none'), 'theme.mode')
    if theme.get('own') is not None:
        own = _object(theme['own'], 'theme.own', ('id', 'recipe'))
        out['theme']['own'] = {'id': _str(own.get('id', ''), 'theme.own.id'),
                               'recipe': _str(own.get('recipe', ''), 'theme.own.recipe')}
        if not out['theme']['own']['id']:
            out['theme']['own'] = None
    for key in ('shown', 'chosen'):
        items = theme.get(key, [])
        if not isinstance(items, list):
            raise RequestError(f'theme.{key} must be a list.')
        out['theme'][key] = [_theme_entry(item, f'theme.{key}[{i}]') for i, item in enumerate(items)]
    if any(item['id'] != out['theme']['mode'] for item in out['theme']['chosen']):
        raise RequestError('theme.chosen lists only the chosen Theme (theme.mode).')
    if data.get('inputs') is not None:
        out['inputs'] = _inputs(data['inputs'])
    return out


def _inputs(value):
    inputs = _object(value, 'inputs', ('record_path', 'boxes', 'meanings'))
    out = {'record_path': _str(inputs.get('record_path', ''), 'inputs.record_path'), 'boxes': [], 'meanings': None}
    if not out['record_path']:
        raise RequestError("inputs needs the record it was kept in (record_path).")
    boxes = inputs.get('boxes', [])
    if not isinstance(boxes, list):
        raise RequestError('inputs.boxes must be a list.')
    for i, box in enumerate(boxes):
        where = f'inputs.boxes[{i}]'
        box = _object(box, where, ('id', 'kind', 'role', 'label', 'text', 'files', 'instead'))
        one = {key: _str(box.get(key, ''), f'{where}.{key}') for key in ('id', 'kind', 'role', 'label', 'instead')}
        if one['kind'] == 'text':
            one['text'] = _str(box.get('text', ''), f'{where}.text')
        else:
            one['files'] = _strs(box.get('files', []), f'{where}.files')
        out['boxes'].append(one)
    if inputs.get('meanings') is not None:
        meanings = inputs['meanings']
        if not isinstance(meanings, list) or any(not isinstance(pair, list) or len(pair) != 2 or
                                                 any(not isinstance(item, str) for item in pair) for pair in meanings):
            raise RequestError('inputs.meanings is a list of [role, meaning] pairs.')
        out['meanings'] = [list(pair) for pair in meanings]
    return out


# ------------------------------------------------------------------ the text (request.cpp, word for word)

def _native(path):
    return path.replace('/', '\\')


def _what(r):
    duration = 'the length the AI chooses' if not r['length'] else f'about {r["length"]}'
    kind = r['kind']
    if kind == 'short':
        return f'a vertical short of {duration} (1080x1920, for TikTok, Shorts and Reels)'
    if kind == 'long':
        return f'a YouTube video of {duration} (1920x1080)'
    if kind == 'custom':
        return f'what I describe here: "{r["custom"].strip()}" ({duration}; choose the shape that suits it)'
    return f'both: a vertical short (1080x1920) and a YouTube video (1920x1080), each {duration}'


def _inputs_text(inputs):
    """NewVideoDialog::inputsRequestText."""
    path = _native(inputs['record_path'])
    t = (f'What the person gave this Look up front (kept in {path}). Once the project exists, keep it beside the video '
         f'with letitedit_looks(action: "inputs", project: <the project .mlt>, inputs: "{path}"); in later rounds read it '
         'back with letitedit_looks(action: "inputs", project: ..., inputs: "read"):\n')
    empties, roles = [], []
    for box in inputs['boxes']:
        role = box['role']
        if role not in roles:
            roles.append(role)
        given = box['text'] if box['kind'] == 'text' else '; '.join(box['files'])
        t += f'- {role} ("{box["label"]}"): {given or "not given"}\n'
        if not given:
            empties.append(f'{role}: {box["instead"]}' if box['instead'] else f'{role}: not given, so work without it')
    meanings = inputs['meanings']
    if meanings is None:
        meanings = [[role, ROLE_MEANINGS[role]] for role in roles if ROLE_MEANINGS.get(role)]
    if meanings:
        t += 'Roles: ' + '; '.join(f'{role} = {meaning}' for role, meaning in meanings) + '.\n'
    if empties:
        t += 'Left empty: ' + '; '.join(empties) + '.\n'
    t += ('Nothing more will be asked of the person after they press Go: do not ask them anything about these, or for '
          'approval of a script, a beat table or an asset; decide for yourself. The files are theirs and are only read, '
          'never changed or moved. If you leave a "show" file out of the video, record why with '
          'letitedit_looks(action: "inputs", project: ..., unused: {<file path>: <reason>}).\n')
    return t


_REPLACES = ("A Theme you choose replaces the Look's own surface (grade, lighting mood, texture, palette and drawn "
             "elements) completely; the Look keeps its structure and timing.")


def _theme_text(theme):
    """NewVideoDialog::themeRequest, from the Theme choice as resolved."""
    own = theme['own'] or {}
    own_id = own.get('id', '')
    keep = (f'\nTheme: none chosen. Keep this Look as learned; its own theme file ({own.get("recipe", "")}) is part of '
            'the Look.\n') if own_id else ''
    mode = theme['mode']
    if mode == 'none':
        return keep
    if mode == 'pick' and theme['shown']:
        shown = []
        for one in theme['shown']:
            line = f'{one["title"]} ({one["id"]}), recipe: {one["recipe"]}'
            if one['recipe_shared']:
                line += f', shared: {one["recipe_shared"]}'
            shown.append(line)
        return ('\nTheme: pick. Choose one of the Themes I was shown for this Look, read its recipe, and tell me which '
                f'you chose and why before you start: {"; ".join(shown)}.{(" " + _REPLACES) if own_id else ""}\n')
    if mode in ('freestyle', 'pick'):
        if not own_id:
            return ('\nTheme: Freestyle (freestyle). No set Theme: decide how the video is drawn or filmed your own way; '
                    'using no Theme is fine.\n')
        return (f'\nTheme: Freestyle (freestyle). This Look has its own colours and lighting (its theme file '
                f'{own.get("recipe", "")} is part of the Look); keep them unless another treatment clearly suits this '
                f'video better. {_REPLACES}\n')
    text = ''
    for one in theme['chosen']:
        text += f'\nTheme: {one["title"]} ({mode}); recipe: {one["recipe"]}'
        if one['recipe_shared']:
            text += f'; shared: {one["recipe_shared"]}'
        text += '\n'
    if not text:
        return keep
    if own_id:
        text += ("\nThis Theme replaces the Look's own surface (grade, lighting mood, texture, palette and drawn "
                 "elements) completely: don't read or use the Look's own theme file. The Look keeps its structure and "
                 "timing.\n")
    return text


def _first_cut(r):
    """firstCutRequest."""
    look = r['look']
    what = _what(r)
    files = [] if r['no_footage'] else r['footage']['files']
    source = (f'these files: {"; ".join(files)}' if files else f'the folder {_native(r["footage"]["folder"])}')
    about = r['about'].strip()
    look_id = look['id'] if look['has_looks'] else ''
    style = 'none' if look['has_looks'] else look['style']
    inputs = _inputs_text(r['inputs']) if r['inputs'] else ''
    length_line = 'Length: Let the AI choose.\n' if not r['length'] else f'Length: {r["length"]}.\n'
    if r['turbo']:
        if r['no_footage']:
            quick = ('Make a first cut with no footage in Turbo mode: this Look draws everything itself. Read only the '
                     '`letitedit-turbo` skill and the chosen Look\'s own recipe: they take the place of the `letitedit` '
                     f'router, `letitedit-firstcut` and every stage skill.\n\nWhat to make: {what}.\n')
        else:
            quick = (f'Make a first cut from {source} in Turbo mode. Read only the `letitedit-turbo` skill (and the '
                     'chosen Look\'s own recipe, if it isn\'t Clean): they take the place of the `letitedit` router, '
                     f'`letitedit-firstcut` and every stage skill.\n\nWhat to make: {what}.\n')
        quick += length_line
        if look_id:
            quick += f'look: {look_id}\n'
        elif not style or style == 'none':
            quick += 'look: none\n'
        else:
            quick += f'look: {style}\n'
        if about:
            quick += f"What it's about, and what must stay in or stay out: {about}\n"
        quick += ("turbo: on\n(I turned on Turbo, which sacrifices quality for speed on this first run through only. "
                  "I'm putting speed over quality: keep every scene, card, effect and graphic very simple and brief, "
                  "draw each once, check nothing twice, and finish. It never changes your AI, model or effort. Tell me at "
                  "the end that Turbo was on and what it skipped. Notes I send afterwards are handled as normal.)\n")
        if inputs:
            quick += '\n' + inputs
        quick += ('\nWhen the first cut is done, open it for me and tell me in two lines what you made and what Turbo '
                  'skipped. Do not call it ready without a ready review verdict.')
        return quick
    if r['no_footage']:
        text = ('Make a first cut with no footage: this Look draws everything itself (use the letitedit skills: the '
                f'`letitedit` router and `letitedit-firstcut`).\n\nWhat to make: {what}.\n')
    else:
        text = (f'Make a first cut from {source} (use the letitedit skills: the `letitedit` router and '
                f'`letitedit-firstcut`).\n\nWhat to make: {what}.\n')
    text += length_line
    if look_id:
        text += f'look: {look_id}\n'
        if look_id == 'auto':
            text += (f'(I chose the Style "{look["style_kind_label"]}" and "Let the AI pick" for its Look: choose one of '
                     'its Looks for this footage with letitedit_looks(action: "list"), from each one\'s "needs" line, '
                     'and tell me which you chose and why before you start.)\n')
        elif look_id == 'freestyle':
            text += ('(I chose Freestyle: no set Look. Work out the kind of video from the footage and edit it the way '
                     "that suits the clips, as the `letitedit` router's `look` field says for freestyle: there is no "
                     'Look recipe to read, and `look` stays out of brief.json.)\n')
        else:
            text += (f'(I chose the Style "{look["style_kind_label"]}" and its Look "{look["label"] or look_id}". A Look '
                     'is a recipe to work from, not a template: read it in full with letitedit_looks(action: "get", '
                     f"id: {look_id}), as the `letitedit` router's `look` field says, and keep the brief's look: "
                     f'{look_id} so the review judges the video against it.)\n')
    elif not style or style == 'none':
        text += 'look: none\n(I chose "Let the AI decide": neutral defaults and your editing skills.)\n'
    else:
        text += (f'look: {style}\n(I chose the Look "{look["style_label"] or style}"'
                 f'{", my personal Look" if look["mine"] else ""}: select it with {{op: look, id: {style}}}; '
                 f'letitedit_looks(action: "get", id: {style}) reads its recipe and settings.)\n')
    if about:
        text += f"What it's about, and what must stay in or stay out: {about}\n"
    if inputs:
        text += '\n' + inputs
    text += ('\nWhen the cut is done, open it for me. State the review verdict and link its plain review line; only call '
             'the video ready when the review verdict is ready. Tell me the story in two lines and put a one-line "why" '
             'marker on every clip. Put the strongest opening first. I try other openings with the app\'s New hook '
             'button (hook candidates from letitedit_hooks, kept beside the project), so don\'t make copies of the '
             'project for other openings: if you have better opening ideas than its candidates, add them as hook '
             "candidates. I'll tell you what to change.")
    return text


def _look_request(r):
    """appendLookRequest, from what it resolved."""
    look = r['look']
    text = ''
    for path in dict.fromkeys(path for path in look['files'] if path):
        text += f'\nLook file: {path}\n'
    if not r['modern']:
        return text
    if r['filmed_style']:
        text += f'\nStyle: {r["filmed_style"]["label"]} ({r["filmed_style"]["id"]})\n'
    if r['multicam'] and not r['no_footage']:
        text += ('\nThe clips look like several cameras filming one conversation (one shows both people, the others '
                 'one face each): sync them by their sound (letitedit_sync), find who talks when (letitedit_speakers), '
                 "then cut between the cameras on who talks ({op: multicam}), as letitedit-firstcut's FIRST-1m says.\n")
    if r['auto_shown']:
        text += f'\nLet the AI pick chooses one of the Looks I was shown: {", ".join(r["auto_shown"])}\n'
    if r['look_line']:
        text += f'\nLook: {look["label"]} ({look["id"]})\n'
    if r['faces'] and r['faces']['person_looks']:
        f = r['faces']
        text += (f"\nFaces in the clips (measured): a face in {f['with_face']} of the {f['frames']} frames looked at. "
                 f"Built around a person on camera (each one's footage need): {', '.join(f['person_looks'])}.\n")
    if r['fit']:
        text += (f"\nFormat fit (letitedit's fit check of these clips against the Look's format): {r['fit']['verdict']}. "
                 f'{r["fit"]["line"]}\n')
        if r['fit']['verdict'] == 'no' and r['fit']['look_only']:
            text += ("\nLook use: look only. These clips don't fit this Look's format, and I chose to make it with only "
                     "the look: keep its captions, graphics, colour and pace, and cut the clips the way they suit "
                     '(format.fit look-only).\n')
    text += _theme_text(r['theme'])
    text += f'\nFormat: {"YouTube video" if r["kind"] == "long" else "Short"}\n'
    if r['no_footage'] and r['references']:
        text += ('\nReferences I added (characters, a logo, photos or a script to use in the video; read them, never '
                 f'change or move them): {"; ".join(r["references"])}\n')
    if r['captions'] != 'auto':
        text += f'\nCaptions & pace: {r["captions"]}\n'
    if r['music'] != 'auto':
        text += f'\nMusic: {r["music"]}\n'
    if r['music_file'] and r['music'] in ('own', 'trending'):
        text += f'Music file: {r["music_file"]}\n'
    return text


def render(data):
    """The request's text: what NewVideoDialog::send() sends for these choices, before the chat adds anything."""
    r = normalize(data)
    text = _first_cut(r) + _look_request(r)
    song = r['song'].strip().replace('"', '')
    if song:
        text += (f'\nsong: {song}\nCut the video to this song. I add it in the phone app when I post, so the file I '
                 'upload has none of it (the `song` field of the `letitedit` router, letitedit-sound section 13). You '
                 'pick the part; nothing more will be asked.\n')
    if r['save_folder']:
        text += (f'\nSave video in: {r["save_folder"].replace(chr(92), "/")}\nKeep the project, exports and AI working '
                 'files in this folder. Reference the footage where it is; never copy or move it.\n')
    return text


# ------------------------------------------------------------------ route facts

def _facts(kind, look_id, style, no_footage, turbo, captions, music, song, theme, multicam, references, inputs, fit,
           look_files, save_folder):
    from letitedit.app import phases
    choice = (look_id if look_id in LOOK_CHOICES else 'pending' if look_id == '@@LOOK_ID@@'
              else 'named' if look_id else 'none' if style in ('', 'none') else 'named')
    selected = look_id if look_id else (style if style not in ('', 'none') else 'none')
    captions_l = (captions or 'auto').strip().lower()
    music_l = (music or 'auto').strip().lower()
    return {
        'kind': kind,
        'short': kind in ('short', 'both') if kind != 'custom' else None,
        'long': kind in ('long', 'both') if kind != 'custom' else None,
        'no_footage': no_footage,
        'turbo': turbo,
        'look': selected,
        'look_choice': choice,
        'look_files': look_files,
        'captions': captions_l,
        'wants_captions': captions_l not in phases.NO_CAPTIONS + ('auto',),
        'music': music_l,
        'wants_music': music_l.split()[0] in phases.MUSIC_IN_EXPORT if music_l else False,
        'song': bool(song),
        'theme': theme,
        'multicam': multicam,
        'references': references,
        'inputs': inputs,
        'fit': fit,
        'save_folder': save_folder,
    }


def _effective_theme(theme):
    """The Theme the request's text gives: Let the AI pick with nothing to pick from is Freestyle, and a named Theme
    no longer in the catalogue is none (the Look as it is)."""
    mode = theme['mode']
    if mode == 'pick' and not theme['shown']:
        return 'freestyle'
    if mode not in ('none', 'pick', 'freestyle') and not theme['chosen']:
        return 'none'
    return mode


def facts(data):
    """What a route needs to know, from the typed request (stage_start's and phases' predicates read these)."""
    r = normalize(data)
    look = r['look']
    return _facts(r['kind'], look['id'] if look['has_looks'] else '', look['style'], r['no_footage'], r['turbo'],
                  r['captions'] if r['modern'] else 'auto', r['music'] if r['modern'] else 'auto',
                  r['song'].strip().replace('"', ''), _effective_theme(r['theme']) if r['modern'] else None,
                  r['multicam'] and r['modern'] and not r['no_footage'],
                  len(r['references']) if r['modern'] and r['no_footage'] else 0, r['inputs'] is not None,
                  (r['fit']['verdict'] if r['fit'] else None) if r['modern'] else None,
                  list(dict.fromkeys(p for p in look['files'] if p)),
                  r['save_folder'].replace('\\', '/') or None)


def _line(text, name):
    match = re.search(r'^' + re.escape(name) + r':[ \t]*(.*)$', text, re.M)
    return match.group(1).strip() if match else None


def facts_from_text(text):
    """The same facts from a request's text (one made before the typed record, or by an older editor)."""
    text = text or ''
    what = _line(text, 'What to make') or ''
    kind = ('both' if what.startswith('both:') else 'custom' if what.startswith('what I describe here')
            else 'long' if what.startswith('a YouTube video') else 'short')
    look = (_line(text, 'look') or '').strip()
    no_footage = text.startswith('Make a first cut with no footage')
    style_line = re.search(r'^\(I chose the Style "', text, re.M) is not None or look in LOOK_CHOICES or \
        look == '@@LOOK_ID@@'
    look_id = look if style_line else ''
    style = '' if style_line else look
    theme_line = _line(text, 'Theme') or ''
    theme = (None if not theme_line else 'none' if theme_line.startswith('none chosen') else
             'pick' if theme_line.startswith('pick.') else
             (re.search(r'\(([^()]+)\)', theme_line) or [None, theme_line])[1])
    if not theme_line and re.search(r'^Format: ', text, re.M):
        theme = 'none'
    fit = re.search(r"^Format fit \(letitedit's fit check[^)]*\): ([^.\n]+)\.", text, re.M)
    references = _line(text, 'References I added (characters, a logo, photos or a script to use in the video; read '
                             'them, never change or move them)')
    save = _line(text, 'Save video in')
    return _facts(kind, look_id, style, no_footage, bool(re.search(r'^turbo: on$', text, re.M)),
                  _line(text, 'Captions & pace') or 'auto', _line(text, 'Music') or 'auto', _line(text, 'song') or '',
                  theme, 'several cameras filming one conversation' in text,
                  len(references.split('; ')) if references else 0,
                  'What the person gave this Look up front' in text, fit.group(1) if fit else None,
                  list(dict.fromkeys(re.findall(r'^Look file: (.+)$', text, re.M))), save)


# ------------------------------------------------------------------ the kept record

def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def parity(record):
    """Whether the record's fields render the text it says was sent: {'ok', 'first_difference' (offset or None),
    'sent', 'rendered'} (the last two only when they differ, 200 characters around the difference)."""
    sent = record.get('text')
    if not isinstance(sent, str):
        raise RequestError('This record keeps no sent text to compare.')
    made = render(record)
    if made == sent:
        return {'ok': True, 'first_difference': None}
    at = next((i for i, (a, b) in enumerate(zip(made, sent)) if a != b), min(len(made), len(sent)))
    return {'ok': False, 'first_difference': at, 'sent': sent[max(0, at - 80):at + 120],
            'rendered': made[max(0, at - 80):at + 120]}


def write(folder, data, text=None, origin='bridge'):
    """Keep the typed request beside the video (folder/new-video-request.json). `text` is what was sent (render()'s
    text when not given). Returns the path."""
    record = normalize(data)
    sent = render(record) if text is None else text
    record.update(origin=origin, text=sent, text_sha256=_sha(sent))
    path = Path(folder) / FILE
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, path)
    return path


def read(folder):
    """The record kept in folder (or the record file itself), as written, or None when there is none. A record that
    doesn't check out raises RequestError."""
    path = Path(folder)
    path = path / FILE if path.is_dir() else path
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding='utf-8-sig'))
    except ValueError as error:
        raise RequestError(f'{path} is not readable JSON: {error}') from error
    normalize(record)
    return record
