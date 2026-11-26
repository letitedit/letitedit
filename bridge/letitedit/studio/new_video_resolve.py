"""New video's choices resolved without the dialog (T319's H1): the typed request a Studio job (or a session runner)
makes, the same one the person's New video dialog writes when Go is pressed.

    resolve(choices, catalog=None) -> the typed request (letitedit.app.new_video_request), checked
    choices_of(job, sources, ...)  -> the choices a Studio Short job makes in the dialog today (short.start_new_video)

The rules are the dialog's own (src/letitedit/newvideo: catalog.cpp loadLooks and mergePersonalLooks, lookstep.cpp
tabLooks, pickLooks, filmedStyle, tabStyleFor and chooseTab, stylestep.cpp routeFits and kindFits, themestep.cpp
themeFits, ownTheme, settleTheme and themeChoice), over the same catalogue (letitedit.looks.looks.catalog(), what the
dialog reads from `looks.py --list-json`). A choice the dialog wouldn't offer, or one this resolver can't make without a
person (a Look's boxes, a Look's format-fit check not supplied, a Custom Look), is refused with RequestError, never
replaced by another Look, Theme or music choice.

`choices`:
    kind, length ('<n> seconds' or ''), about, custom, turbo
    folder, files, no_footage, references
    look       'auto' (Let the AI pick, the default), 'freestyle' or a Look id
    theme      'freestyle' (the default), 'pick', 'none' or a Theme id; theme_chosen: the person chose it
    detected   what_was_filmed.detect()'s answer for the clips ({'style', 'angles', ...}) or None (not looked)
    tab        a Style id the person pressed, or None (the tab follows the clips)
    captions, music, music_file, song, fit ({'verdict', 'line', 'look_only'} from look_place's fit check), inputs
    save_folder
"""
import os
import re

from letitedit.app import new_video_request as nvr

RequestError = nvr.RequestError


def _styles(cat):
    """loadLooks: the Styles with their Looks (defaults as the dialog reads them), then the person's own merged in."""
    modern = cat.get('layout_version') == 2
    review = bool(cat.get('review_enabled'))
    styles = []
    for s in cat.get('styles') or []:
        style = {'id': s.get('id') or '', 'label': s.get('label') or s.get('id') or '', 'cut': bool(s.get('cut')),
                 'footage': s.get('footage') or 'yes', 'hidden': bool(s.get('hidden')), 'looks': []}
        for one in s.get('looks') or []:
            look = {'id': one.get('id') or '', 'label': one.get('label') or one.get('id') or '',
                    'themes': one.get('themes') or 'none', 'cut': bool(one.get('cut')),
                    'works_with': one.get('works_with') or 'footage', 'kind': one.get('kind') or 'both',
                    'personal': bool(one.get('personal')), 'based_on': one.get('based_on') or '',
                    'fits': list(one.get('fits') or []), 'place': one.get('place') or '',
                    'asks': [a for a in one.get('asks') or [] if a.get('id')]}
            if look['id']:
                style['looks'].append(look)
        if style['id'] and (modern or style['looks']):
            styles.append(style)
    _merge_personal(styles, review)
    return styles, modern, review


def _merge_personal(styles, review):
    """mergePersonalLooks."""
    mine = next((i for i, s in enumerate(styles) if s['id'] == 'personal-looks'), None)
    if mine is None:
        return
    looks = styles.pop(mine)['looks']
    for look in looks:
        routes = []
        if look['works_with'] != 'no-footage':
            routes.append(False)
        if look['works_with'] in ('no-footage', 'both'):
            routes.append(True)
        for no_footage in routes:
            def offered(s):
                return not s['hidden'] and (not s['cut'] or review) and (s['footage'] == 'no') == no_footage
            target = None
            if look['based_on']:
                target = next((s for s in styles if any(l['id'] == look['based_on'] for l in s['looks'])
                               and (s['footage'] == 'no') == no_footage), None)
            for kind in look['fits']:
                if target is None:
                    target = next((s for s in styles if s['id'] == kind and offered(s)), None)
            if target is None:
                target = next((s for s in styles if (offered(s) if no_footage else s['id'] == 'talking-head')), None)
            if target is not None:
                target['looks'].append(dict(look, personal=True))


class _Dialog:
    """The few dialog rules the request depends on, over one catalogue and one set of choices."""

    def __init__(self, cat, kind, no_footage):
        self.styles, self.modern, self.review = _styles(cat)
        self.themes = list(cat.get('themes') or [])
        self.kind = kind
        self.no_footage = no_footage
        self.look = 'auto'
        self.tab = 'all'
        self.detected = ''
        self.style = 'none'

    def style_of(self, sid):
        return next((s for s in self.styles if s['id'] == sid), None)

    def kind_fits(self, look_kind):
        return not look_kind or look_kind == 'both' or self.kind in ('both', 'custom') or look_kind == self.kind

    def route_fits(self, look):
        return look['works_with'] == 'both' or look['works_with'] == ('no-footage' if self.no_footage else 'footage')

    def tab_looks(self, tab):
        out, seen = [], set()
        for personal in (False, True):
            for style in self.styles:
                if (style['footage'] == 'no') != self.no_footage or style['hidden'] or (style['cut'] and not self.review):
                    continue
                for look in style['looks']:
                    if (look['personal'] != personal or look['id'] in seen or (look['cut'] and not self.review)
                            or not self.route_fits(look) or not self.kind_fits(look['kind'])):
                        continue
                    if tab != 'all' and style['id'] != tab and tab not in look['fits']:
                        continue
                    seen.add(look['id'])
                    out.append((style, look))
        return out

    def pick_looks(self):
        return self.tab_looks(self.tab) or self.tab_looks('all')

    def tab_styles(self):
        out = []
        for style in self.styles:
            if (style['footage'] == 'no') != self.no_footage or style['hidden'] or (style['cut'] and not self.review):
                continue
            if not self.tab_looks(style['id']) and style['id'] not in (self.detected, self.tab):
                continue
            out.append(style)
        return out

    def filmed_style(self):
        kind = self.tab if self.tab != 'all' else self.detected
        return kind if self.style_of(kind) and kind != 'all' else ''

    def tab_style_for(self):
        filmed = self.filmed_style()
        if filmed:
            return filmed
        looks = self.tab_looks('all')
        if looks:
            return looks[0][0]['id']
        styles = self.tab_styles()
        return styles[0]['id'] if styles else 'none'

    def chosen_card(self):
        style = self.style_of(self.style)
        return next((l for l in style['looks'] if l['id'] == self.look), None) if style else None

    def own_theme(self, look):
        if not look or not look['personal']:
            return {}
        return next((t for t in self.themes if t.get('personal') and not t.get('cut')
                     and look['id'] in (t.get('looks') or [])), {})

    def theme_fits(self, theme, style, look):
        if not style or style['cut'] or theme.get('cut'):
            return False
        if look is None:
            if self.look == 'freestyle':
                styles = theme.get('styles') or []
                return (not theme.get('personal') and theme.get('kind') in ('kit', 'film')
                        and not (theme.get('looks') or []) and (not styles or style['id'] in styles))
            if self.look == 'auto' and any(not l['cut'] and self.theme_fits(theme, s, l) for s, l in self.pick_looks()):
                return True
            return any(not choice['cut'] and self.theme_fits(theme, style, choice) for choice in style['looks'])
        if theme.get('personal'):
            return look['id'] in (theme.get('looks') or [])
        kind = theme.get('kind')
        if not ((look['themes'] == 'kits' and kind == 'kit') or (look['themes'] == 'film' and kind == 'film')):
            return False

        def matches(ids, ident):
            return not ids or ident in ids or (ident == 'idea' and 'made-with-code' in ids)
        return matches(theme.get('styles') or [], style['id']) and matches(theme.get('looks') or [], look['id'])

    def theme_choice(self, mode):
        look = self.chosen_card()
        own = self.own_theme(look)
        own_id = own.get('id') or ''
        entry = lambda t: {key: str(t.get(key) or '') for key in ('id', 'title', 'recipe', 'recipe_shared')}  # noqa: E731
        shown, chosen = [], []
        if mode == 'pick':
            style = self.style_of(self.style) or self.style_of(self.tab_style_for())
            shown = [entry(t) for t in self.themes if self.theme_fits(t, style, look) and t.get('id') != own_id]
        elif mode not in ('none', 'freestyle'):
            chosen = [entry(t) for t in self.themes if t.get('id') == mode]
        return {'mode': mode, 'own': {'id': own_id, 'recipe': str(own.get('recipe') or '')} if own_id else None,
                'shown': shown, 'chosen': chosen}


def resolve(choices, catalog=None):
    """The typed request for these New video choices, as the dialog would resolve them."""
    if catalog is None:
        from letitedit.looks import looks as looks_catalog
        catalog = looks_catalog.catalog()
    c = dict(choices)
    kind = c.get('kind', 'short')
    dialog = _Dialog(catalog, kind, bool(c.get('no_footage')))
    if not dialog.modern:
        raise RequestError('This catalogue is not the current New video layout (layout_version 2).')
    detected = c.get('detected') or {}
    dialog.detected = detected.get('style') if dialog.style_of(detected.get('style') or '') else 'all'
    look = c.get('look') or 'auto'
    if look in ('custom', 'pending-learn', 'none'):
        raise RequestError(f'"{look}" needs the New video dialog; resolve() makes a request for a Look id, auto or '
                           'freestyle.')
    dialog.look = look
    tab = c.get('tab')
    if tab:
        dialog.tab = tab if dialog.style_of(tab) else 'all'
    elif look in nvr.LOOK_CHOICES or any(l['id'] == look for _, l in dialog.tab_looks(dialog.detected)):
        dialog.tab = dialog.detected if dialog.style_of(dialog.detected) else 'all'
    if look in nvr.LOOK_CHOICES:
        dialog.style = dialog.tab_style_for()
    else:
        found = next(((s, l) for s, l in dialog.tab_looks(dialog.tab) if l['id'] == look), None)
        if found is None:
            found = next(((s, l) for s, l in dialog.tab_looks('all') if l['id'] == look), None)
            if found is not None:
                dialog.tab = 'all'
        if found is None:
            raise RequestError(f'The Look "{look}" is not offered for this video on this letitedit (its route, its '
                               'format or the catalogue).')
        dialog.style = found[0]['id']
    styles = dialog.style_of(dialog.style)
    if styles is None:
        raise RequestError('No Style with Looks is offered for this video, so New video has nothing to send.')
    card = dialog.chosen_card()
    label = ('Let the AI pick' if look == 'auto' else 'Freestyle' if look == 'freestyle'
             else card['label'] if card else 'Let the AI pick')
    filmed = dialog.style_of(dialog.filmed_style())
    no_footage = dialog.no_footage or bool(card and card['works_with'] == 'no-footage')
    if card and card['asks'] and c.get('inputs') is None:
        raise RequestError(f'The Look "{look}" asks the person for things up front (its boxes); give them as '
                           '`inputs`, or choose another Look.')
    fit = c.get('fit')
    if card and card['place'] and not no_footage and fit is None:
        raise RequestError(f'The Look "{look}" is a format: its fit check of these clips (look_place fit) must be '
                           'run and given as `fit`.')
    if not (card and card['place'] and not no_footage):
        fit = None
    mode = c.get('theme') or 'freestyle'
    if not c.get('theme_chosen') and not c.get('theme') and dialog.own_theme(card):
        mode = 'none'                                     # settleTheme: a learned Look keeps its own Theme
    if mode not in ('none', 'pick', 'freestyle'):
        style = dialog.style_of(dialog.style)
        theme = next((t for t in dialog.themes if t.get('id') == mode), None)
        if theme is None or not dialog.theme_fits(theme, style, card):
            raise RequestError(f'The Theme "{mode}" is not offered for this Look.')
    music, music_file, song = c.get('music') or 'auto', c.get('music_file') or '', (c.get('song') or '').strip()
    if music == 'auto' and song:                          # loadLooks: a song in the old box is a trending song now
        music, music_file, song = 'trending', song.replace('"', ''), ''
    faces = face_fact(detected, dialog, card, look) if face_fit_on() and not no_footage else None
    typed = {
        'kind': kind, 'custom': c.get('custom') or '', 'length': c.get('length') or '', 'about': c.get('about') or '',
        'turbo': bool(c.get('turbo')), 'no_footage': no_footage,
        'footage': {'folder': c.get('folder') or '', 'files': [] if no_footage else list(c.get('files') or [])},
        'look': {'has_looks': True, 'style': 'none', 'style_label': '', 'mine': False, 'id': look, 'label': label,
                 'style_kind_label': filmed['label'] if filmed else 'All', 'files': [], 'waiting_for_learn': False},
        'inputs': c.get('inputs'), 'modern': True,
        'filmed_style': {'id': filmed['id'], 'label': filmed['label']} if filmed else None,
        'multicam': not no_footage and bool(detected.get('angles')),
        'auto_shown': [l['id'] for _, l in dialog.pick_looks()] if look == 'auto' else [],
        'look_line': look != 'auto',
        'fit': fit,
        'faces': faces,
        'theme': dialog.theme_choice(mode),
        'references': list(c.get('references') or []) if no_footage else [],
        'captions': c.get('captions') or 'auto', 'music': music, 'music_file': music_file, 'song': song,
        'save_folder': (c.get('save_folder') or '').replace('\\', '/'),
    }
    return nvr.normalize(typed)


# T352: a Look built around a person, offered or chosen for clips with few faces, says so as a measured fact (the AI
# still decides). A Look is built around a person when every kind of video it fits is one of these.
PERSON_KINDS = {'talking-head', 'conversation'}
# Fewer faces than this share of the frames looked at is what letitedit.app.what_was_filmed.decide reads as the camera
# on the work rather than on a person ("Talk over the work"), so it is the same share here.
FEW_FACES = 0.2
FACE_FIT_SETTING, FACE_FIT_ENV = 'look_face_fit', 'LETITEDIT_LOOK_FACE_FIT'


def face_fit_on():
    """T352's switch (settings.json look_face_fit, on by default; LETITEDIT_LOOK_FACE_FIT, 1 or 0, wins)."""
    forced = os.environ.get(FACE_FIT_ENV, '').strip().lower()
    if forced in ('1', 'true', 'on', 'yes'):
        return True
    if forced in ('0', 'false', 'off', 'no'):
        return False
    try:
        import letitedit.core.hardware as hardware
        return hardware.settings().get(FACE_FIT_SETTING) is not False
    except Exception:  # noqa: BLE001 - an unreadable setting means the default: on
        return True


def face_fact(detected, dialog, card, look):
    """{'with_face', 'frames', 'person_looks'} when the clips' frames (what_was_filmed.detect's per-frame face counts)
    show a face in fewer than FEW_FACES of them and a Look in play is built around a person (its `fits`: the Looks
    Let the AI pick offers, or the one chosen); else None."""
    clips = (detected or {}).get('clips') or []
    counts = [n for c in clips for n in (c.get('faces') or []) if isinstance(n, (int, float))]
    if not counts:
        return None
    with_face = sum(1 for n in counts if n >= 1)
    if with_face >= FEW_FACES * len(counts):
        return None
    in_play = [l for _, l in dialog.pick_looks()] if look == 'auto' else ([card] if card else [])
    person = [l['id'] for l in in_play if l.get('fits') and set(l['fits']) <= PERSON_KINDS]
    if not person:
        return None
    return {'with_face': with_face, 'frames': len(counts), 'person_looks': person}


def normalized_length(raw):
    """NewVideoDialog::normalizedLength: '1:30', '90 s', '1.5 min' ... as '<n> seconds'; '' when it can't be read."""
    raw = (raw or '').strip().lower()
    if not raw:
        return ''
    clock = re.fullmatch(r'(\d+):(\d{1,2})', raw)
    if clock:
        if int(clock.group(2)) >= 60:
            return ''
        seconds = int(clock.group(1)) * 60 + int(clock.group(2))
    else:
        units = re.fullmatch(r'(\d+(?:[.,]\d+)?)\s*(s|sec|secs|seconds?|m|min|mins|minutes?)', raw)
        if not units:
            return ''
        seconds = float(units.group(1).replace(',', '.')) * (1 if units.group(2).startswith('s') else 60)
    if seconds <= 0 or seconds > 24 * 3600:
        return ''
    return f'{_qround(seconds)} seconds'


def _qround(value):
    """qRound: halves away from zero."""
    return int(value + 0.5) if value >= 0 else int(value - 0.5)


def choices_of(job, sources, about, length, save_folder, detected=None):
    """What short.start_new_video chooses in the dialog for this job: a Short, its files (or no footage), its Look
    (Let the AI pick when the job names none), its Theme when it names one, Turbo off, its length and about."""
    inputs = job.get('inputs') or {}
    files = list(sources.get('files') or []) if sources.get('mode') == 'pieces' else []
    choices = {'kind': 'short', 'length': normalized_length(length), 'about': about, 'turbo': False,
               'no_footage': sources.get('mode') == 'none', 'folder': sources.get('folder') or '', 'files': files,
               'look': inputs.get('look_id') or 'auto', 'detected': detected, 'save_folder': save_folder}
    if inputs.get('theme_id'):
        choices.update(theme=inputs['theme_id'], theme_chosen=True)
    return choices
