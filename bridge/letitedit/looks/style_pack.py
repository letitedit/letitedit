"""Drawing primitives, neutral defaults, validators and read-only legacy conversion fixtures.

Active editing preferences resolve through look_library and catalog, not a mutable pack catalogue.
"""
from __future__ import annotations
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
from letitedit.looks import catalog as _catalog  # noqa: E402  (where the catalogue's items come from)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge

import copy
import json
import os
import re
from pathlib import Path

import yaml

STYLE_ROOT = Path(os.environ.get('LETITEDIT_STYLES', (_SAI_ROOT + '\\style-packs')))
FORMAT = 'letitedit-style/3'
# formats load() reads: v3 is v2 plus fields, so v2 files (and the older dev copy's name for v2) read as they are
READS = ('letitedit-style/3', 'letitedit-style/2', 'shotcut-ai-style/2')
KINDS = ('short', 'long', 'both')
CATALOG_FORMAT = 'letitedit-style-catalog/1'
APP_FILE = 'letitedit.json'          # written by the app's My style panel: a pack with it is the person's own

# The kinds of effect a style's presets (`effects`) and the {op: fx} edit place (fx.py says how each is made)
EFFECT_KINDS = ('popup', 'text_pop', 'zoom_punch', 'push_in', 'shake', 'flash', 'glitch', 'whoosh', 'transition', 'sfx',
                'count_up', 'location', 'broll', 'light_leak', 'graphic', 'motion', 'three_d', 'effect', 'camera_move', 'item')
# When a preset is used: what in the video calls for it (rules.triggers). The AI finds them; the edit records them.
TRIGGERS = ('mention', 'number', 'brand', 'place', 'list_item', 'emphasis', 'punchline', 'question', 'topic_change',
            'reveal', 'reaction', 'pause', 'cut', 'hook', 'ending')
# Where an overlay goes (rules.placement.zone): a position name, [x, y], or one of these, decided per moment
ZONES = ('opposite_face', 'above_captions')
# What an overlay keeps clear of (rules.placement.avoid)
AVOID = ('face', 'captions', 'covered')
# Rules the {op: fx} check measures (rules.never and fx.never); `first_s: s` / `last_s: s` are mappings
NEVER = ('over_face', 'over_captions', 'outside_safe_zone', 'overlapping', 'first_s', 'last_s')
# Sound-effect events a pack can map (sfx.events): the fx and popups edits look sounds up by these
SFX_EVENTS = ('cut', 'popup', 'punchline', 'transition', 'hook', 'reveal', 'zoom', 'text', 'end', 'shake', 'flash',
              'count', 'place')

DEFAULTS = {
    'format': FORMAT,
    'name': 'Neutral',
    'description': 'Core defaults: clean white captions with a dark outline, no brand.',
    'colors': {'primary': '#FFFFFF', 'secondary': '#FFD54F', 'accent': '#FF7043', 'dark': '#111111', 'light': '#FFFFFF'},
    'fonts': {'heading': {'family': 'Montserrat', 'weight': 800},
              'body': {'family': 'Inter', 'weight': 600},
              'captions': {'family': 'Inter', 'weight': 700}},
    'captions': {'font': 'captions', 'size': 54, 'fill': 'light', 'outline': {'color': 'dark', 'width': 3},
                 'shadow': None, 'background': None, 'position': 'bottom', 'margin': 0.07, 'max_chars': 42,
                 'max_lines': 2, 'case': 'as_spoken'},
    'text': {'font': 'heading', 'size': 72, 'fill': 'light', 'outline': {'color': 'dark', 'width': 4}},
    'graphics': {},
    # music levels are dB relative to the dialogue's loudness (the score measures it)
    'music': {'zones': {'talk': -18.0, 'montage': -6.0, 'quiet': -24.0, 'swell': -3.0, 'end': -4.0},
              'duck_under_speech': True, 'merge_gap': 4.0, 'attack': 0.3, 'release': 0.9, 'crossfade': 3.0,
              'fade_in': 1.5, 'fade_out': 3.0, 'dialogue_lufs': None, 'sources': [], 'notes': ''},
    # map: {name: file} (relative to the pack); events: {cut|popup|punchline|transition|...: name} (SFX_EVENTS)
    'sfx': {'gain_db': -16.0, 'map': {}, 'events': {}},
    'editing': {'max_pause': 0.75, 'pad_in': 0.12, 'pad_out': 0.3, 'blur_pad': True, 'transitions': 'cut',
                'pace': 'medium', 'intro': None, 'outro': None},
    'export': {'preset': 'high_quality_h264', 'loudness': -14.0},
    # v3: the style's colour look, as effects for the footage tracks (the main picture track and the B-roll track):
    # {op: track, name: <track>, effects: <look.effects>}; any effect letitedit_timeline_apply takes ({filter, params})
    'look': {'about': '', 'effects': []},
    'taste': '',
    # v3: what the app's style picker shows, and the style's know-how (recipe.md) and devices
    'label': None,           # the name on the style's card (falls back to `name`)
    'summary': '',           # one line under it
    'kind': 'both',          # short | long | both: which kind of video the style is for
    'tags': [],
    'preview': None,         # an image in the pack folder for the card
    'recipe': None,          # the written editing instructions (a file in the pack; recipe.md when present)
    'credits': [],           # [{file, source, licence}] for every asset the pack ships
    # named effect presets: {name: {kind, about, ...look, sfx, rules: {triggers, density, placement, duration_s,
    # never, when}}} (STYLES.md, "Effects"); the {op: fx} edit places them and checks their rules
    'effects': {},
    # the style's effect rhythm as a whole: tracks, density over all effects, platform covered areas, never rules
    'fx': {'track': 'Effects', 'sfx_track': 'Effect sounds', 'broll_track': 'B-roll',
           'density': {'per_10s': None, 'per_min': None, 'min_gap_s': None},
           'safe_zone': None, 'never': [], 'rhythm': ''},
    # pop-ups triggered by spoken words (popups.py; the {op: popups} edit): entries and how often they may fire
    'popups': {'track': None, 'sfx_track': None, 'min_gap_s': 1.5, 'max_total': None, 'entries': []},
    # the style's hook rules (hooks.py and letitedit_hooks read max_s, approaches and text)
    'hook': {'max_s': 3.0, 'approaches': [], 'text': {'max_words': 6}, 'rules': '', 'avoid': []},
    # A series' own habits (My style in letitedit; the editing skills read them): how much and what b-roll, how it is
    # shot, the music it likes and the small touches that make it the creator's own.
    'broll': {'amount': 'some', 'kinds': [], 'favorites': '', 'notes': ''},
    'shots': {'framing': 'medium', 'camera': 'handheld', 'punch_ins': 'some', 'notes': ''},
    'signature': {'touches': []},
    # Numbers measured on reference videos (a style imported from a video writes them; the AI reads them as targets)
    # and where they came from: {sources: [{path | url, title, duration_s, measured}], measured, tool, notes}
    'measured': {},
    'provenance': {},
}
DEFAULTS['music'].update({'likes': [], 'avoid': [], 'theme': None})


class Kit(dict):
    """A resolved style pack (DEFAULTS merged with the pack). `root` is the pack folder (None for the defaults)."""
    root: Path | None = None
    source: str = 'defaults'

    # ------------------------------------------------------------- lookups
    def color(self, value, default='#FFFFFF'):
        """'#RRGGBB' / '#RRGGBBAA' / (r, g, b[, a]) 0-255 / a colour name from the kit -> '#RRGGBBAA' (CSS order)."""
        if value is None:
            value = default
        if isinstance(value, (tuple, list)) and len(value) in (3, 4) and all(
                isinstance(x, (int, float)) and 0 <= x <= 255 for x in value):
            value = '#' + ''.join(f'{int(round(x)):02X}' for x in value)
        seen = 0
        while isinstance(value, str) and not value.startswith('#') and value in self['colors'] and seen < 5:
            value, seen = self['colors'][value], seen + 1
        v = str(value).strip()
        if not re.fullmatch(r'#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?', v):
            raise ValueError(f'Not a colour: {value!r} (use #RRGGBB, #RRGGBBAA, (r, g, b[, a]) or one of {sorted(self["colors"])})')
        return (v + 'FF' if len(v) == 7 else v).upper()

    def mlt_color(self, value, default='#FFFFFF'):
        """The same colour in MLT's '#AARRGGBB' order."""
        c = self.color(value, default)
        return '#' + c[7:9] + c[1:7]

    def rgba(self, value, default='#FFFFFF'):
        c = self.color(value, default)
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5, 7))

    def font(self, ref, default='body'):
        """{'family', 'weight', 'italic'} for a font name from the kit, an inline dict, or a family string."""
        if ref is None:
            ref = default
        if isinstance(ref, str) and ref in self['fonts']:
            ref = self['fonts'][ref]
        if isinstance(ref, str):
            ref = {'family': ref}
        fam, w, it = ref.get('family', 'Inter'), ref.get('weight'), ref.get('italic')
        try:   # 'Barlow Condensed ExtraBold', 'Inter:600' as well as plain family names
            import letitedit.catalogs.fonts as fonts
            fam, pw, pit = fonts.parse_name(fam)
            w = w if w is not None else pw
            it = it if it is not None else pit
        except Exception:  # noqa: BLE001 - font index unavailable: use the name as given
            pass
        return {'family': fam, 'weight': int(w if w is not None else 400), 'italic': bool(it)}

    def path(self, rel):
        """Absolute path for a file the kit refers to (relative to the pack folder)."""
        if not rel:
            return None
        if str(rel) in getattr(self, 'references', {}):
            return self.references[str(rel)]
        p = Path(rel)
        if not p.is_absolute() and self.root is not None:
            p = self.root / p
        return str(p)

    # ------------------------------------------------------------- Shotcut filter properties
    def caption_props(self, width=1920, height=1080, overrides=None):
        """Properties for a Shotcut caption burn-in (MLT `subtitle`) filter in this style."""
        c = _merge(self['captions'], overrides or {})
        return self._text_props(c, width, height, default_font='captions', caption=True)

    def text_props(self, width=1920, height=1080, overrides=None):
        """Properties for a Shotcut Simple Text (dynamictext) filter in this style."""
        c = _merge(self['text'], overrides or {})
        return self._text_props(c, width, height, default_font='heading', caption=False)

    def _text_props(self, c, width, height, default_font, caption):
        import letitedit.catalogs.fonts as fonts
        scale = height / 1080.0
        f = self.font(c.get('font'), default_font)
        face = fonts.mlt_text_style(f['family'], f['weight'], f['italic'])
        size = round(float(c.get('size', 54)) * scale)
        outline = c.get('outline') or {}
        props = {'family': face['family'], 'style': face['style'], 'weight': face['weight'], 'size': size,
                 'fgcolour': self.mlt_color(c.get('fill'), '#FFFFFF'),
                 'olcolour': self.mlt_color(outline.get('color'), '#000000') if outline else '#00000000',
                 'outline': round(float(outline.get('width', 0)) * scale) if outline else 0,
                 'bgcolour': self.mlt_color(c.get('background')) if c.get('background') else '#00000000',
                 'pad': round(float(c.get('pad', 0)) * scale), 'opacity': 1.0, 'shotcut:usePointSize': 0}
        # A place set on a tall frame does not suit a wide one (and back): `shape` says which it was made for.
        shape = c.get('shape')
        fits = shape not in ('tall', 'wide') or shape == ('tall' if width < height else 'wide')
        if c.get('geometry') and fits:
            props['geometry'] = c['geometry']
            props['halign'] = c.get('halign', 'center')
            props['valign'] = c.get('valign', 'bottom' if caption else 'middle')
        else:
            pos = c.get('position', 'bottom' if caption else 'middle')
            margin = float(c.get('margin', 0.07))
            lines = int(c.get('max_lines', 2 if caption else 3))
            box_h = round(size * 1.35 * lines + 2 * props['outline'] + props['pad'] * 2)
            x, w = round(width * 0.07), round(width * 0.86)
            y = {'top': round(height * margin), 'middle': round((height - box_h) / 2)}.get(
                pos, round(height * (1 - margin) - box_h))
            props['geometry'] = f'{x} {y} {w} {box_h} 1'
            props['halign'] = c.get('halign', 'center')
            props['valign'] = {'top': 'top', 'middle': 'middle'}.get(pos, 'bottom')
        return props

    def describe(self):
        """Compact YAML of the resolved kit, for reading."""
        return yaml.safe_dump(dict(self), sort_keys=False, allow_unicode=True, width=110)

    # ------------------------------------------------------------- v3: picker card and know-how
    def label(self):
        return self.get('label') or self.get('name') or (self.root.name if self.root is not None else 'Neutral')

    def recipe_path(self):
        """The pack's recipe.md (or the file `recipe` names), or None."""
        if self.root is None:
            return None
        rel = self.get('recipe') or ('recipe.md' if (self.root / 'recipe.md').exists() else None)
        if not rel:
            return None
        p = Path(self.path(rel))
        return str(p) if p.exists() else None

    def recipe_text(self):
        """The style's written editing instructions ('' when the pack has none)."""
        p = self.recipe_path()
        return Path(p).read_text(encoding='utf-8') if p else ''

    def preview_path(self):
        p = self.get('preview')
        if not p or self.root is None:
            return None
        p = Path(self.path(p))
        return str(p) if p.exists() else None

    def sfx_file(self, ref):
        """A sound by name from sfx.map, by event from sfx.events, or a file path -> absolute path (None if none). A
        name the pack doesn't ship ('whoosh', 'sfx:cheer') is looked up in the asset library when it is installed."""
        if not ref:
            return None
        sfx = self.get('sfx') or {}
        ref = (sfx.get('events') or {}).get(ref, ref)
        if not ref:
            return None
        ref = (sfx.get('map') or {}).get(ref, ref)
        p = self.path(ref)
        if p and os.path.isfile(p):
            return p
        lib = _library()
        if lib is not None and callable(getattr(lib, 'sfx_file', None)) and not os.path.splitext(str(ref))[1]:
            try:
                got = lib.sfx_file(str(ref))
                return got if got and os.path.isfile(got) else None
            except Exception:  # noqa: BLE001 - not a sound the library has
                return None
        return None

    def mine(self):
        """True for a pack the person saved in the app's My style panel (it has letitedit.json)."""
        return self.root is not None and (self.root / APP_FILE).exists()


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ------------------------------------------------------------------ loading

def _pack_file(pack):
    """style.yaml / vNNN.json for a name or path, or None for the defaults."""
    if pack in (None, '', 'neutral', 'Neutral', 'default'):
        return None
    p = Path(str(pack))
    if not p.is_absolute():
        p = STYLE_ROOT / p
    if p.is_dir():
        if (p / 'style.yaml').exists():
            return p / 'style.yaml'
        versions = sorted(p.glob('v[0-9][0-9][0-9].json'))
        if versions:
            return versions[-1]
        raise FileNotFoundError(f'No style.yaml or vNNN.json in {p}')
    if p.exists():
        return p
    raise FileNotFoundError(f'Style pack {pack!r} not found (looked for {p}). Packs: {", ".join(list_packs())}')


def load(pack=None):
    """Resolve Look settings; legacy pack loading remains until the consumer switch completes."""
    if pack in (None, '', 'neutral', 'Neutral', 'default'):
        from letitedit.looks import look_library
        return look_library.kit()
    if isinstance(pack, str) and not any(char in pack for char in '/\\:'):
        from letitedit.looks import look_library
        try:
            return look_library.kit(pack)
        except FileNotFoundError:
            pass
    f = _pack_file(pack)
    kit = Kit(copy.deepcopy(DEFAULTS))
    if f is None:
        return kit
    if f.suffix.lower() == '.json':
        with open(f, encoding='utf-8-sig') as fh:
            data = from_v1(json.load(fh))
    else:
        with open(f, encoding='utf-8-sig') as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            raise ValueError(f'{f}: a style.yaml is a mapping of fields; got {type(data).__name__}')
        if data.get('format', FORMAT) not in READS:
            raise ValueError(f'{f}: unknown style format {data.get("format")!r} (this version reads {", ".join(READS)})')
    kit = Kit(_merge(DEFAULTS, data))
    kit['format'] = data.get('format', FORMAT)
    kit.root = f.parent
    kit.source = str(f)
    return kit


def list_packs():
    """Names of the packs under style-packs (v2/v3 folders and v1 folders)."""
    return _catalog.style_packs(STYLE_ROOT)


def _legacy_visible_packs():
    """Packs offered for new videos; a hidden private pack's older pins still resolve through load()."""
    from letitedit.looks import look_settings
    hidden = look_settings.hidden_packs()
    return [name for name in list_packs() if name not in hidden]


def _version(kit):
    if kit.source.endswith('.json'):
        return 'v1'
    return 'v' + str(kit.get('format', FORMAT)).rsplit('/', 1)[-1]


def summary():
    """[{name, format, display_name, description, label, summary, kind, tags}] for every pack."""
    out = []
    for name in _legacy_visible_packs():
        try:
            k = load(name)
            out.append({'name': name, 'format': _version(k), 'display_name': k.get('name'),
                        'description': k.get('description', ''), 'label': k.label(), 'summary': k.get('summary') or '',
                        'kind': k.get('kind') or 'both', 'tags': list(k.get('tags') or [])})
        except Exception as e:  # noqa: BLE001
            out.append({'name': name, 'error': str(e)})
    return out


# ------------------------------------------------------------------ the picker's list

def _legacy_card(name, kit=None):
    """One pack as the app's style picker shows it (the contract in STYLES.md, "Style picker")."""
    try:
        k = kit or load(name)
    except Exception as e:  # noqa: BLE001 - a broken pack is listed with its error, never hidden
        return {'name': name, 'label': name, 'summary': '', 'kind': 'both', 'tags': [], 'preview': None,
                'format': None, 'mine': False, 'error': str(e)}
    kind = k.get('kind') or 'both'
    entries = (k.get('popups') or {}).get('entries') or []
    own_description = k.get('description') if k.get('description') != DEFAULTS['description'] else ''
    return {'name': name, 'label': k.label(), 'summary': k.get('summary') or own_description or '',
            'kind': kind if kind in KINDS else 'both', 'tags': [str(t) for t in (k.get('tags') or [])],
            'preview': k.preview_path(), 'format': _version(k), 'mine': k.mine(),
            'recipe': bool(k.recipe_path()), 'effects': len(k.get('effects') or {}), 'popups': len(entries)}


def _legacy_catalog(kind=None):
    """The style picker's list: every pack as a card, grouped by the kind of video it is for. A 'both' pack is in both
    groups; `kind` ('short' | 'long') keeps one group. Besides the packs there are two choices: 'none' ("Let the AI
    decide", the default: no style, the AI edits freely with its skills) and 'auto' ("Pick a style for me": the AI
    picks one of the listed packs; not shown by the app for now)."""
    if kind is not None and kind not in ('short', 'long'):
        raise ValueError("kind is 'short' or 'long'")
    cards = [_legacy_card(n) for n in _legacy_visible_packs()]
    groups = {}
    for g in ('short', 'long'):
        if kind in (None, g):
            groups[g] = [c for c in cards if c['kind'] in (g, 'both') and not c.get('error')]
    return {'format': CATALOG_FORMAT, 'root': str(STYLE_ROOT), 'default': 'none', 'choices': CHOICES,
            'groups': groups, 'packs': cards}


# The two choices that are not packs (the brief's `style` field takes the value)
CHOICES = [{'value': 'none', 'label': 'Let the AI decide', 'default': True, 'show': True,
            'about': 'No style: the AI edits freely with its own editing skills and neutral defaults.'},
           {'value': 'auto', 'label': 'Pick a style for me', 'default': False, 'show': False,
            'about': 'The AI picks one of the styles listed here for this video and says which.'}]


# ------------------------------------------------------------------ My style: the fields the app's panel shows

# key (dotted path in style.yaml), label, type (choice | text | list | number | bool), choices, help
MY_STYLE_FIELDS = [
    {'key': 'label', 'label': 'Name of your style', 'type': 'text', 'group': 'About'},
    {'key': 'summary', 'label': 'Describe it in one line', 'type': 'text', 'group': 'About'},
    {'key': 'kind', 'label': 'Mostly for', 'type': 'choice', 'choices': ['short', 'long', 'both'], 'group': 'About',
     'choice_labels': ['Shorts', 'Long videos', 'Both']},
    {'key': 'editing.pace', 'label': 'Pace', 'type': 'choice', 'choices': ['slow', 'medium', 'fast'],
     'group': 'Pacing'},
    {'key': 'editing.max_pause', 'label': 'Longest pause kept (seconds)', 'type': 'number', 'min': 0.1, 'max': 2.0,
     'group': 'Pacing'},
    {'key': 'broll.amount', 'label': 'How much b-roll', 'type': 'choice', 'choices': ['none', 'some', 'lots'],
     'group': 'B-roll'},
    {'key': 'broll.kinds', 'label': 'Kinds of b-roll you use', 'type': 'list', 'group': 'B-roll',
     'help': 'e.g. close-ups of hands, drone shots, the dog'},
    {'key': 'broll.favorites', 'label': 'Favourite shots to reuse', 'type': 'text', 'group': 'B-roll'},
    {'key': 'broll.notes', 'label': 'Anything else about b-roll', 'type': 'text', 'group': 'B-roll'},
    {'key': 'shots.framing', 'label': 'Usual framing', 'type': 'choice', 'choices': ['close', 'medium', 'wide'],
     'group': 'Shots'},
    {'key': 'shots.camera', 'label': 'Camera', 'type': 'choice', 'choices': ['handheld', 'tripod', 'both'],
     'group': 'Shots'},
    {'key': 'shots.punch_ins', 'label': 'Punch-ins (zooming in on a word)', 'type': 'choice',
     'choices': ['none', 'some', 'lots'], 'group': 'Shots'},
    {'key': 'shots.notes', 'label': 'Anything else about shots', 'type': 'text', 'group': 'Shots'},
    {'key': 'music.likes', 'label': 'Music you like', 'type': 'list', 'group': 'Music'},
    {'key': 'music.avoid', 'label': 'Music to avoid', 'type': 'list', 'group': 'Music'},
    {'key': 'music.theme', 'label': 'Your theme song (a file)', 'type': 'file', 'group': 'Music'},
    {'key': 'signature.touches', 'label': 'Your signature touches', 'type': 'list', 'group': 'Signature',
     'help': 'How you open and sign off, catchphrases, recurring segments, things you never do'},
    {'key': 'taste', 'label': 'Anything else the AI should know', 'type': 'text', 'group': 'Signature'},
    {'key': 'popups.entries', 'label': 'When I say ..., show ...', 'type': 'popups', 'group': 'Pop-ups',
     'help': 'Your own pictures only, e.g. your logo when you say your channel name: {words: [...], asset: {image: '
             'file}, position}'},
]


def get_path(data, key, default=None):
    cur = data
    for part in key.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def nested(key, value):
    """'broll.amount', 'lots' -> {'broll': {'amount': 'lots'}} (the shape _legacy_update() takes)."""
    out = value
    for part in reversed(key.split('.')):
        out = {part: out}
    return out


def _legacy_read(pack):
    """A pack as the app reads it: the resolved values (defaults filled in), the card, its folder and recipe, and the
    My style panel's fields with their current values."""
    k = load(pack)
    return {'pack': pack, 'folder': str(k.root) if k.root is not None else None, 'source': k.source,
            'card': _legacy_card(pack, k) if pack else None, 'recipe': k.recipe_path(), 'mine': k.mine(),
            'fields': [dict(f, value=get_path(k, f['key'])) for f in MY_STYLE_FIELDS], 'style': dict(k)}


# ------------------------------------------------------------------ v1 packs

def _css(mlt_colour, default=None):
    """MLT '#AARRGGBB' -> CSS '#RRGGBB' (or '#RRGGBBAA' when not opaque)."""
    if not mlt_colour or not str(mlt_colour).startswith('#'):
        return default
    v = str(mlt_colour)
    if len(v) == 9:
        a, rgb = v[1:3], v[3:9]
        return ('#' + rgb + ('' if a.lower() == 'ff' else a)).upper()
    return v.upper()


def from_v1(v1):
    """Translate a v1 pack (the JSON the episode pipeline pins) into v2 style data."""
    cap = v1.get('captions') or {}
    title = v1.get('title') or {}
    shadow = v1.get('caption_shadow') or None
    music = v1.get('music') or {}
    sfx = v1.get('sfx') or {}
    assets = v1.get('assets') or {}
    colors = {}
    if cap.get('fgcolour'):
        colors['primary'] = colors['light'] = _css(cap['fgcolour'])
    if cap.get('olcolour'):
        colors['dark'] = _css(cap['olcolour'])
    if shadow and shadow.get('color'):
        colors['accent'] = _css(shadow['color'])
    fonts = {}
    if cap.get('family'):
        fonts['captions'] = {'family': cap['family'], 'weight': int(float(cap.get('weight', 400)))}
        fonts['body'] = dict(fonts['captions'])
    if title.get('family'):
        fonts['heading'] = {'family': title['family'], 'weight': int(float(title.get('weight', 700)))}
    captions = {'font': 'captions'}
    for k_v1, k_v2 in (('size', 'size'),):
        if cap.get(k_v1) is not None:
            captions[k_v2] = float(cap[k_v1])
    if cap.get('fgcolour'):
        captions['fill'] = 'primary'
    if cap.get('olcolour') or cap.get('outline'):
        captions['outline'] = {'color': 'dark' if cap.get('olcolour') else '#000000', 'width': float(cap.get('outline', 3))}
    if cap.get('geometry'):
        captions.update(geometry=cap['geometry'], halign=cap.get('halign', 'center'), valign=cap.get('valign', 'bottom'))
    if shadow:
        captions['shadow'] = {'color': 'accent', 'x': shadow.get('x', 3), 'y': shadow.get('y', 4)}
    text = {'font': 'heading'}
    if title.get('size'):
        text['size'] = float(title['size'])
    if title.get('fgcolour'):
        text['fill'] = _css(title['fgcolour'])
    if title.get('olcolour') or title.get('outline'):
        text['outline'] = {'color': _css(title.get('olcolour'), '#000000'), 'width': float(title.get('outline', 4))}
    if title.get('geometry'):
        text.update(geometry=title['geometry'], halign=title.get('halign', 'center'), valign=title.get('valign', 'middle'))
    sfx_map = {k: a['path'] for k, a in assets.items() if str(a.get('path', '')).lower().endswith(('.wav', '.mp3', '.ogg'))
               and k not in ('brand-theme',)}
    editing = {'transitions': (v1.get('transitions') or {}).get('mode', 'cut'),
               'blur_pad': any((f.get('id') == 'blur_pad') for f in v1.get('clip_filters') or [])}
    intro = (v1.get('intro') or {}).get('asset')
    if intro and intro in assets:
        editing['intro'] = assets[intro]['path']
    taste = '\n'.join(x for x in (
        (v1.get('pacing') or {}).get('notes'), (v1.get('transitions') or {}).get('notes'), music.get('coverage'),
        music.get('selection'), sfx.get('notes'), v1.get('conversation_notes')) if x)
    data = {'format': FORMAT, 'name': v1.get('display_name') or v1.get('name', 'v1 pack'),
            'description': f"Converted from v1 pack {v1.get('name')} v{v1.get('version')}", 'colors': colors,
            'fonts': fonts, 'captions': captions, 'text': text,
            'music': {k: v for k, v in {'crossfade': music.get('crossfade_seconds'), 'notes': music.get('level_note'),
                                        'theme': (assets.get('brand-theme') or {}).get('path')}.items() if v is not None},
            'sfx': {'gain_db': float(sfx.get('gain_db', -16)), 'map': sfx_map}, 'editing': editing,
            'export': {k: v for k, v in {'preset': (v1.get('export') or {}).get('preset'),
                                         'loudness': v1.get('audio_target_lufs')}.items() if v is not None},
            'taste': taste}
    return data


def _legacy_migrate(v1_pack, name=None):
    """Write a v1 pack out as an editable folder (style-packs/<name>/style.yaml, the current format). Never overwrites
    an existing pack."""
    f = _pack_file(v1_pack)
    if f is None or f.suffix.lower() != '.json':
        raise ValueError('_legacy_migrate() takes a v1 pack (folder with vNNN.json or the json file)')
    with open(f, encoding='utf-8-sig') as fh:
        data = from_v1(json.load(fh))
    name = name or f'{f.parent.name}-v2'
    dest = STYLE_ROOT / name
    if dest.exists():
        raise FileExistsError(f'{dest} already exists')
    for sub in ('brand', 'graphics', 'sfx', 'samples'):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    with open(dest / 'style.yaml', 'w', encoding='utf-8') as fh:
        fh.write(f'# Style pack, converted from {f}\n# Taste, not law: every value is a default that edits can override.\n')
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=110)
    return str(dest / 'style.yaml')


# ------------------------------------------------------------------ My style: changes merged into a pack

LOCK_TIMEOUT_S = 15.0


class _PackLock:
    """A cross-process lock beside a pack's style.yaml (style.yaml.lock, created exclusively), so the app's My style
    panel and the AI's _legacy_update() never interleave a read and a write. A lock older than 60 s is a crashed writer's."""

    def __init__(self, folder):
        self.path = Path(folder) / 'style.yaml.lock'

    def __enter__(self):
        import time
        end = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f'pid {os.getpid()}'.encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 60:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() > end:
                    raise TimeoutError(f'{self.path} is held by another writer; try again')
                time.sleep(0.05)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


def _legacy_update(pack, changes):
    """Write changes (nested like style.yaml) into a pack's style.yaml, keeping everything else; makes the pack when it
    is new. Dicts merge key by key; lists and other values are replaced (null is written as null: 'none', e.g. no
    caption outline). The file is replaced in one step under a lock, so a reader never sees half a file and two
    writers (the app's My style panel and the AI) never lose each other's changes. Returns the file."""
    if not isinstance(changes, dict):
        raise ValueError('update takes a mapping of fields, nested like style.yaml')
    if pack in (None, '', 'neutral', 'Neutral', 'default'):
        raise ValueError('update needs a pack name (the neutral defaults are not a file)')
    folder = Path(str(pack))
    if not folder.is_absolute():
        folder = STYLE_ROOT / folder
    if folder.suffix.lower() in ('.yaml', '.yml'):
        folder = folder.parent
    f = folder / 'style.yaml'
    folder.mkdir(parents=True, exist_ok=True)
    with _PackLock(folder):
        data = {}
        if f.exists():
            with open(f, encoding='utf-8') as fh:
                data = yaml.safe_load(fh) or {}
            if data.get('format', FORMAT) not in READS:
                raise ValueError(f'{f}: unknown style format {data.get("format")!r}')
        data = _merge(data, {k: v for k, v in changes.items() if k != 'format'})
        data['format'] = FORMAT      # what it holds now may use v3 fields; every reader here takes v2 and v3
        data.setdefault('name', folder.name)
        tmp = f.with_name(f'style.yaml.{os.getpid()}.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write('# letitedit style (My style). Taste, not law: edits can override any of it.\n')
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=110)
        os.replace(tmp, f)
    return str(f)


# ------------------------------------------------------------------ checks: what the tools can really do

# what an effect preset needs, by kind (the look; placement and timing come from the edit or the rules)
KIND_NEEDS = {'sfx': ['sfx'], 'graphic': ['template'], 'motion': ['block'], 'effect': ['effect'],
              'item': ['item', 'track']}
RULE_KEYS = ('triggers', 'density', 'placement', 'duration_s', 'never', 'when')
DENSITY_KEYS = ('per_10s', 'per_min', 'min_gap_s')


def _num_ok(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def never_problems(never, where):
    out = []
    if never is None:
        return out
    if not isinstance(never, list):
        return [f'{where}: never is a list like [over_face, over_captions, {{first_s: 1}}]']
    for r in never:
        if isinstance(r, str):
            if r not in NEVER or r in ('first_s', 'last_s'):
                out.append(f"{where}: never {r!r}: one of {', '.join(n for n in NEVER if n not in ('first_s', 'last_s'))}, "
                           f"or {{first_s: s}} / {{last_s: s}} (plain-words rules go in `when`)")
        elif isinstance(r, dict) and len(r) == 1 and next(iter(r)) in ('first_s', 'last_s') and _num_ok(next(iter(r.values()))):
            continue
        else:
            out.append(f'{where}: never {r!r} is not a rule the check measures')
    return out


def density_problems(d, where):
    if d is None:
        return []
    if not isinstance(d, dict):
        return [f'{where}: density is {{per_10s, per_min, min_gap_s}}']
    out = [f"{where}: density.{k}: one of {', '.join(DENSITY_KEYS)}" for k in d if k not in DENSITY_KEYS]
    out += [f'{where}: density.{k} is a number 0 or more; got {v!r}' for k, v in d.items()
            if k in DENSITY_KEYS and v is not None and not _num_ok(v)]
    return out


def rules_problems(rules, where):
    """Problems with a preset's usage rules (when and where it is used)."""
    if rules is None:
        return []
    if not isinstance(rules, dict):
        return [f'{where}: rules is a mapping {{triggers, density, placement, duration_s, never, when}}']
    out = [f"{where}: rules.{k}: one of {', '.join(RULE_KEYS)}" for k in rules if k not in RULE_KEYS]
    trig = rules.get('triggers')
    if trig is not None:
        if not isinstance(trig, list):
            out.append(f'{where}: rules.triggers is a list of {", ".join(TRIGGERS)}')
        else:
            out += [f"{where}: trigger {t!r}: one of {', '.join(TRIGGERS)}" for t in trig if t not in TRIGGERS]
    out += density_problems(rules.get('density'), f'{where}: rules')
    pl = rules.get('placement')
    if pl is not None:
        if not isinstance(pl, dict):
            out.append(f'{where}: rules.placement is {{zone, avoid}}')
        else:
            z = pl.get('zone')
            if z is not None and z not in ZONES:
                try:
                    position_xy(z)
                except ValueError as e:
                    out.append(f'{where}: rules.placement.zone: {e}; or one of {", ".join(ZONES)}')
            av = pl.get('avoid')
            if av is not None and (not isinstance(av, list) or any(a not in AVOID for a in av)):
                out.append(f"{where}: rules.placement.avoid is a list of {', '.join(AVOID)}; got {av!r}")
    du = rules.get('duration_s')
    if du is not None and not (_num_ok(du) or (isinstance(du, list) and len(du) == 2 and all(_num_ok(x) for x in du)
                                                and du[0] <= du[1])):
        out.append(f'{where}: rules.duration_s is seconds or [min, max]; got {du!r}')
    out += never_problems(rules.get('never'), f'{where}: rules')
    if rules.get('when') is not None and not isinstance(rules['when'], str):
        out.append(f'{where}: rules.when is plain words')
    return out


def _effect_problems(kit, name, preset, deep=True):
    """Problems with one named effect preset: its kind, the fields that kind needs, its rules, and (deep) whether the
    edit tools take what it names (effects, templates, blocks, sounds, files)."""
    where = f'effects.{name}'
    if not isinstance(preset, dict):
        return [f'{where}: a preset is a mapping like {{kind: zoom_punch, scale: 1.15, rules: {{...}}}}; got {preset!r}']
    kind = preset.get('kind')
    if kind not in EFFECT_KINDS:
        return [f"{where}: kind is one of {', '.join(EFFECT_KINDS)}; got {kind!r}"]
    out = [f'{where}: {kind} needs {k}' for k in KIND_NEEDS.get(kind, []) if preset.get(k) in (None, '', {})]
    out += rules_problems(preset.get('rules'), where)
    if not deep or out:
        return out
    try:
        if kind == 'popup' and preset.get('asset') is not None:    # no asset: the moment gives it
            out += [f'{where}: {p}' for p in popup_problems(kit, preset, need_words=False)]
        elif kind == 'effect':
            import letitedit.timeline.edit_script as es
            es.build_filter(preset['effect'], 30.0, 30, 1080, 1920, kit=kit)
        elif kind == 'item':
            out += [f'{where}: {p}' for p in item_problems(kit, preset['item'])]
        elif kind == 'graphic':
            out += [f'{where}: {p}' for p in item_problems(kit, {'graphic': {'template': preset['template']}})]
        elif kind in ('motion', 'count_up', 'location'):
            block = preset.get('block') or {'count_up': 'count_up', 'location': 'location'}.get(kind)
            out += [f'{where}: {p}' for p in item_problems(kit, {'motion': {'block': block}})]
        elif kind in ('transition', 'whoosh') and preset.get('transition') is not None:
            import letitedit.timeline.edit_script as es
            es.transition_spec(preset['transition'])
    except Exception as e:  # noqa: BLE001
        out.append(f'{where}: the edit tools do not take it: {e}')
    if preset.get('sfx') and not kit.sfx_file(preset['sfx']):
        out.append(f"{where}: sfx {preset['sfx']!r} is not a sound in sfx.map / sfx.events or a file")
    return out


def item_problems(kit, item):
    """Problems with a timeline item a preset or pop-up places (graphic, motion, vfx, clip, ffmpeg, ass, color)."""
    if not isinstance(item, dict):
        return [f'an item is a mapping like {{graphic: {{template, params}}, len: 2}}; got {item!r}']
    if 'graphic' in item:
        g = item['graphic'] or {}
        try:
            import letitedit.pictures.graphics as graphics
            if g.get('template') != 'custom' and g.get('template') not in graphics.templates(kit):
                return [f"graphic template {g.get('template')!r} does not exist"]
        except ImportError:
            pass
        return []
    if 'motion' in item:
        m = item['motion']
        block = m if isinstance(m, str) else (m or {}).get('block')
        try:
            import letitedit.pictures.motion as motion
            # motion clips not installed here (no blocks folder): optional, drawn as graphics (motion.render_fallback)
            if block != 'custom' and motion.BLOCKS.is_dir() and block not in motion.blocks():
                return [f'motion block {block!r} does not exist (blocks: {", ".join(sorted(motion.blocks()))})']
        except ImportError:
            pass
        return []
    if 'vfx' in item:
        try:
            import letitedit.pictures.vfx_items as vfx_items
            eff = (item['vfx'] or {}).get('effect')
            if eff not in vfx_items.EFFECTS:
                return [f'vfx effect {eff!r} does not exist (letitedit_vfx_effects lists them)']
        except ImportError:
            pass
        return []
    if 'clip' in item:
        p = kit.path(item['clip'])
        return [] if p and os.path.exists(p) else [f"clip {item['clip']!r} not found"]
    if any(k in item for k in ('ffmpeg', 'ass', 'color', 'freeze', 'voice', 'map', 'render3d')):
        return []
    return [f'not an item the timeline takes: {sorted(item)}']


POSITIONS = ('center', 'top', 'bottom', 'left', 'right', 'upper_left', 'upper_right', 'lower_left', 'lower_right')
ANIMS_IN = ('pop', 'fade', 'slide_up', 'slide_down', 'slide_left', 'slide_right', 'drop', 'spin', 'none')
ANIMS_OUT = ('pop', 'shrink', 'fade', 'slide_up', 'slide_down', 'slide_left', 'slide_right', 'spin', 'none')
ASSET_KINDS = ('image', 'emoji', 'text', 'graphic', 'motion')
# A library reference names an asset instead of giving it: '<kind>:<name or tag>' ('emoji:fire', 'icon:wrench').
# The effects asset library (bridge/assets.py, assets.resolve(ref)) answers them once it is installed; until then
# 'emoji:<name>' is drawn from the emoji font by its short name (EMOJI below, then the character's Unicode name).
ASSET_REF = re.compile(r'^\s*([a-z][a-z_-]*)\s*:\s*(\S.*?)\s*$', re.I)
RASTER = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp')
EMOJI = {   # common short names (Unicode CLDR, the names emoji sets use) and a few tags -> the character
    'fire': '\U0001F525', 'hot': '\U0001F525', 'money bag': '\U0001F4B0', 'money': '\U0001F4B0',
    'dollar banknote': '\U0001F4B5', 'money with wings': '\U0001F4B8', 'coin': '\U0001FA99',
    'light bulb': '\U0001F4A1', 'idea': '\U0001F4A1', 'check mark button': '\u2705', 'check': '\u2705',
    'done': '\u2705', 'cross mark': '\u274C', 'no': '\u274C', 'warning': '\u26A0\uFE0F',
    'exploding head': '\U0001F92F', 'mind blown': '\U0001F92F', 'red heart': '\u2764\uFE0F', 'heart': '\u2764\uFE0F',
    'wrench': '\U0001F527', 'hammer': '\U0001F528', 'hammer and wrench': '\U0001F6E0\uFE0F',
    'tools': '\U0001F6E0\uFE0F', 'nut and bolt': '\U0001F529', 'screw': '\U0001F529', 'bolt': '\U0001F529',
    'gear': '\u2699\uFE0F', 'high voltage': '\u26A1', 'electricity': '\u26A1', 'lightning': '\u26A1',
    'electric plug': '\U0001F50C', 'battery': '\U0001F50B', 'dashing away': '\U0001F4A8', 'air': '\U0001F4A8',
    'wind face': '\U0001F32C\uFE0F', 'wind': '\U0001F32C\uFE0F', 'cyclone': '\U0001F300', 'fan': '\U0001F300',
    'snowflake': '\u2744\uFE0F', 'cold': '\u2744\uFE0F', 'thermometer': '\U0001F321\uFE0F',
    'droplet': '\U0001F4A7', 'water': '\U0001F4A7', 'bus': '\U0001F68C', 'car': '\U0001F697', 'dog': '\U0001F415',
    'house': '\U0001F3E0', 'tent': '\u26FA', 'alarm clock': '\u23F0', 'clock': '\u23F0',
    'stopwatch': '\u23F1\uFE0F', 'hourglass': '\u231B', 'calendar': '\U0001F4C5',
    'face with tears of joy': '\U0001F602', 'laugh': '\U0001F602', 'face screaming in fear': '\U0001F631',
    'shocked': '\U0001F631', 'astonished face': '\U0001F632', 'thinking face': '\U0001F914',
    'thinking': '\U0001F914', 'eyes': '\U0001F440', 'look': '\U0001F440', 'party popper': '\U0001F389',
    'party': '\U0001F389', 'thumbs up': '\U0001F44D', 'clapping hands': '\U0001F44F', 'hundred points': '\U0001F4AF',
    '100': '\U0001F4AF', 'rocket': '\U0001F680', 'star': '\u2B50', 'sparkles': '\u2728', 'collision': '\U0001F4A5',
    'boom': '\U0001F4A5', 'bomb': '\U0001F4A3', 'skull': '\U0001F480', 'trophy': '\U0001F3C6', 'crown': '\U0001F451',
    'brain': '\U0001F9E0', 'camera': '\U0001F4F7', 'movie camera': '\U0001F3A5', 'mobile phone': '\U0001F4F1',
    'phone': '\U0001F4F1', 'laptop': '\U0001F4BB', 'package': '\U0001F4E6', 'shopping cart': '\U0001F6D2',
    'round pushpin': '\U0001F4CD', 'location': '\U0001F4CD', 'world map': '\U0001F5FA\uFE0F',
    'map': '\U0001F5FA\uFE0F', 'compass': '\U0001F9ED', 'magnifying glass tilted left': '\U0001F50D',
    'search': '\U0001F50D', 'red question mark': '\u2753', 'question': '\u2753', 'red exclamation mark': '\u2757',
    'exclamation': '\u2757', 'speaker high volume': '\U0001F50A', 'loud': '\U0001F50A',
    'muted speaker': '\U0001F507', 'ear': '\U0001F442', 'musical note': '\U0001F3B5', 'key': '\U0001F511',
    'locked': '\U0001F512', 'gem stone': '\U0001F48E', 'chart increasing': '\U0001F4C8',
    'chart decreasing': '\U0001F4C9', 'memo': '\U0001F4DD', 'books': '\U0001F4DA', 'hot beverage': '\u2615',
    'coffee': '\u2615', 'pizza': '\U0001F355', 'sun': '\u2600\uFE0F', 'mountain': '\u26F0\uFE0F',
    'water wave': '\U0001F30A', 'wave': '\U0001F30A', 'sleeping face': '\U0001F634', 'sleep': '\U0001F634',
    'zany face': '\U0001F92A', 'face with rolling eyes': '\U0001F644', 'pleading face': '\U0001F97A',
    'sweat droplets': '\U0001F4A6', 'flexed biceps': '\U0001F4AA', 'muscle': '\U0001F4AA',
    'stop sign': '\U0001F6D1', 'construction': '\U0001F6A7', 'toolbox': '\U0001F9F0', 'magnet': '\U0001F9F2',
    'test tube': '\U0001F9EA', 'scissors': '\u2702\uFE0F', 'screwdriver': '\U0001FA9B',
    'counterclockwise arrows button': '\U0001F504', 'arrows': '\U0001F504', 'recycle': '\u267B\uFE0F',
    'ladder': '\U0001FA9C', 'thumbs down': '\U0001F44E', 'face with open mouth': '\U0001F62E',
    'grimacing face': '\U0001F62C', 'oops': '\U0001F62C', 'person shrugging': '\U0001F937', 'shrug': '\U0001F937',
    'new button': '\U0001F195', 'new': '\U0001F195', 'free button': '\U0001F193', 'free': '\U0001F193',
    'link': '\U0001F517', 'puzzle piece': '\U0001F9E9', 'broom': '\U0001F9F9',
}


def _emoji_char(name):
    key = re.sub(r'[\s_-]+', ' ', str(name).strip().lower())
    if key in EMOJI:
        return EMOJI[key]
    if any(ord(c) > 0x2100 for c in key):        # the character itself
        return str(name).strip()
    try:
        import unicodedata
        return unicodedata.lookup(key.upper())
    except KeyError:
        return None


def _library():
    try:
        import letitedit.catalogs.assets as assets           # the effects asset library (another task); optional until it is installed
    except ImportError:
        return None
    return assets if callable(getattr(assets, 'resolve', None)) else None


def resolve_asset(ref, kit=None):
    """A sticker's asset as the drawing tools take it. A mapping ({image | emoji | text | graphic | motion}) comes back
    as it is. A library reference '<kind>:<name or tag>' ('emoji:fire', 'emoji:check mark button', 'icon:wrench') is
    looked up in the asset library when it is installed (a picture file it returns becomes {image: file}, a character
    {emoji: char}); until then, and for anything the library has no picture of, 'emoji:<name>' is drawn from the
    emoji font by its short name. Raises ValueError when nothing answers it."""
    if isinstance(ref, dict):
        return ref
    m = ASSET_REF.match(ref) if isinstance(ref, str) else None
    if not m:
        raise ValueError(f"asset {ref!r}: a mapping like {{emoji: ...}} / {{image: file}}, or a library reference "
                         f"like 'emoji:fire'")
    kind, name = m.group(1).lower(), m.group(2)
    lib = _library()
    if lib is not None and callable(getattr(lib, 'popup_asset', None)):
        try:                    # the library's own answer: {image: png} or an animation's {graphic: asset_sticker}
            got = lib.popup_asset(ref)
        except Exception:  # noqa: BLE001 - not in the library (or a sound): the fallbacks below may still answer
            got = None
        if isinstance(got, dict) and got.get('graphic'):
            return got
        if isinstance(got, dict) and got.get('image') and os.path.isfile(str(got['image'])):
            return {'image': str(got['image'])}
    if lib is not None:
        try:
            got = lib.resolve(ref)
        except Exception:  # noqa: BLE001 - not in the library: the fallbacks below may still answer
            got = None
        if isinstance(got, (tuple, list)) and got:
            got = got[0]
        if isinstance(got, dict):
            ch = got.get('char') or got.get('emoji')
            if ch:
                return {'emoji': str(ch)}
            got = got.get('file') or got.get('path')
        if got and str(got).lower().endswith(RASTER) and os.path.isfile(str(got)):
            return {'image': str(got)}
    if kind == 'emoji':
        ch = _emoji_char(name)
        if ch:
            return {'emoji': ch}
    raise ValueError(f"asset {ref!r}: not found" + ('' if lib is not None else
                     ' (the asset library is not installed yet; emoji:<short name> works without it)'))


def position_xy(pos):
    """A pop-up position -> (x, y) centre as fractions of the frame: a name from POSITIONS (or with '-' for '_') or
    [x, y]."""
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        return float(pos[0]), float(pos[1])
    name = str(pos or 'upper_right').strip().lower().replace('-', '_').replace(' ', '_')
    table = {'center': (0.5, 0.42), 'middle': (0.5, 0.42), 'top': (0.5, 0.2), 'bottom': (0.5, 0.66),
             'left': (0.27, 0.42), 'right': (0.73, 0.42), 'upper_left': (0.27, 0.22), 'upper_right': (0.73, 0.22),
             'top_left': (0.27, 0.22), 'top_right': (0.73, 0.22), 'lower_left': (0.27, 0.62),
             'lower_right': (0.73, 0.62), 'bottom_left': (0.27, 0.62), 'bottom_right': (0.73, 0.62)}
    if name not in table:
        raise ValueError(f'position {pos!r}: one of {", ".join(POSITIONS)} or [x, y] (fractions of the frame)')
    return table[name]


def popup_problems(kit, entry, need_words=True):
    """Problems with one pop-up entry (pack, project or inline)."""
    out = []
    if not isinstance(entry, dict):
        return [f'a pop-up is a mapping like {{words: [...], asset: {{image: file}}}}; got {entry!r}']
    if need_words:
        words = entry.get('words')
        if isinstance(words, str):
            words = [words]
        if not words or not all(isinstance(w, str) and w.strip() for w in words):
            out.append('words: one or more phrases that trigger it')
    asset = entry.get('asset')
    if isinstance(asset, str):
        try:
            asset = resolve_asset(asset, kit)
        except ValueError as e:
            return out + [str(e)]
    if not isinstance(asset, dict) or len([k for k in ASSET_KINDS if k in asset]) != 1:
        out.append(f"asset: exactly one of {', '.join(ASSET_KINDS)} (e.g. {{image: assets/logo.png}}); got {asset!r}")
    else:
        kind = next(k for k in ASSET_KINDS if k in asset)
        if kind == 'image':
            p = kit.path(asset['image'])
            if not p or not os.path.isfile(p):
                out.append(f"asset image {asset['image']!r} not found")
        elif kind in ('emoji', 'text') and not str(asset[kind] or '').strip():
            out.append(f'asset {kind} is empty')
        elif kind in ('graphic', 'motion'):
            out += item_problems(kit, {kind: asset[kind]})
    try:
        position_xy(entry.get('position'))
    except ValueError as e:
        out.append(str(e))
    for k, allowed in (('in', ANIMS_IN), ('out', ANIMS_OUT)):
        if entry.get(k) is not None and entry[k] not in allowed:
            out.append(f"{k}: one of {', '.join(allowed)}; got {entry[k]!r}")
    for k in ('size', 'hold_s', 'in_s', 'out_s', 'cooldown_s'):
        v = entry.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0):
            out.append(f'{k}: a number 0 or more; got {v!r}')
    if entry.get('max_per_video') is not None and (not isinstance(entry['max_per_video'], int)
                                                  or entry['max_per_video'] < 1):
        out.append(f"max_per_video: a whole number 1 or more; got {entry['max_per_video']!r}")
    if entry.get('sfx') and not kit.sfx_file(entry['sfx']):
        out.append(f"sfx {entry['sfx']!r} is not a sound in sfx.map / sfx.events or a file")
    return out


def validate(data):
    """Structural problems that make style data unusable, as sentences ([] when it is fine): the format, kind, the
    sections' shapes, every effect preset's kind and rules, pop-up entries, the fx section, measured, provenance and
    credits. Files and tools are not looked at here (check() does that on a written pack)."""
    out = []
    if not isinstance(data, dict):
        return ['style data is a mapping of fields, like style.yaml']
    if data.get('format', FORMAT) not in READS:
        out.append(f"format: {data.get('format')!r} is not one this version reads ({', '.join(READS)})")
    if data.get('kind', 'both') not in KINDS:
        out.append(f"kind: one of {', '.join(KINDS)}; got {data.get('kind')!r}")
    for k in ('label', 'summary', 'name', 'description', 'taste', 'recipe', 'preview'):
        if data.get(k) is not None and not isinstance(data[k], str):
            out.append(f'{k} is text; got {type(data[k]).__name__}')
    if data.get('tags') is not None and (not isinstance(data['tags'], list) or not all(isinstance(t, str) for t in data['tags'])):
        out.append('tags is a list of words')
    shape = [f'{k} is a mapping; got {type(data[k]).__name__}'
             for k in ('colors', 'fonts', 'captions', 'text', 'graphics', 'music', 'sfx', 'editing', 'export', 'hook', 'look',
                       'popups', 'fx', 'effects', 'measured', 'provenance', 'broll', 'shots', 'thumbnail', 'signature')
             if data.get(k) is not None and not isinstance(data[k], dict)]
    if shape:                       # the checks below read these sections as mappings
        return out + shape
    kit = Kit(_merge(DEFAULTS, data))
    for name, preset in (data.get('effects') or {}).items():
        out += _effect_problems(kit, name, preset, deep=False)
    fx = data.get('fx') or {}
    out += density_problems(fx.get('density'), 'fx')
    out += never_problems(fx.get('never'), 'fx')
    pop = data.get('popups') or {}
    if pop.get('entries') is not None and not isinstance(pop['entries'], list):
        out.append('popups.entries is a list of {words, asset, ...}')
    for i, e in enumerate(pop.get('entries') or [], 1):
        if not isinstance(e, dict) or not e.get('words') or not isinstance(e.get('asset'), (dict, str)):
            out.append(f'popups.entries[{i}]: needs words (phrases) and asset ({{image | emoji | text | graphic | motion}})')
    ev = (data.get('sfx') or {}).get('events') or {}
    out += [f"sfx.events.{k}: events are {', '.join(SFX_EVENTS)}" for k in ev if k not in SFX_EVENTS]
    cr = data.get('credits')
    if cr is not None and (not isinstance(cr, list) or not all(isinstance(c, dict) and c.get('file') for c in cr)):
        out.append('credits is a list of {file, source, licence}')
    prov = data.get('provenance') or {}
    if prov.get('sources') is not None and not isinstance(prov['sources'], list):
        out.append('provenance.sources is a list of {path | url, title, duration_s, measured}')
    look = (data.get('look') or {}).get('effects')
    if look is not None and (not isinstance(look, list) or not all(isinstance(e, (dict, str)) for e in look)):
        out.append('look.effects is a list of effects like {filter: hue_lightness_saturation, params: {av.s: 0.9}}')
    return out


def _legacy_create(name, data, recipe_md=None, assets=None, overwrite=False, root=None):
    """Write a new pack (the writer for tools that make styles, e.g. importing one from a reference video):
    style-packs/<name>/style.yaml from `data` (fields as in style.yaml; format is set to the current one),
    recipe.md from `recipe_md` (data['recipe'] then names it), and `assets` copied in: {path inside the pack (e.g.
    'assets/pop.wav'): a source file path or bytes}. Every asset the pack ships should have a credits entry.
    Validated first (validate(): nothing is written when it fails); written into a temporary folder and moved into
    place in one step, so a reader never sees half a pack. overwrite=True replaces an existing pack (the old one is
    kept as <name>.replaced-<time> until the new one is in place, then removed). Returns {'pack', 'style_yaml',
    'recipe', 'assets', 'problems'} where problems are check()'s findings on the written pack (files the tools can't
    find or take)."""
    import shutil
    import time
    if not isinstance(name, str) or not name.strip() or re.search(r'[\\/:*?"<>|]', name) or name.startswith('.'):
        raise ValueError(f'a pack name is a folder name without \\ / : * ? " < > |; got {name!r}')
    data = copy.deepcopy(data or {})
    data['format'] = FORMAT
    data.setdefault('name', name)
    if recipe_md is not None:
        data['recipe'] = data.get('recipe') or 'recipe.md'
    problems = validate(data)
    if problems:
        raise ValueError('style not written: ' + ' | '.join(problems))
    root = Path(root) if root is not None else STYLE_ROOT
    dest = root / name
    if dest.exists() and not overwrite:
        raise FileExistsError(f'{dest} already exists (overwrite=True replaces it; _legacy_update() changes fields)')
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f'.tmp-{name}-{os.getpid()}-{int(time.time() * 1000)}'
    tmp.mkdir(parents=True)
    written = []
    try:
        for rel, src in (assets or {}).items():
            rel_p = Path(str(rel))
            if rel_p.is_absolute() or '..' in rel_p.parts:
                raise ValueError(f'asset {rel!r}: a path inside the pack (assets/..., sfx/..., brand/...)')
            target = tmp / rel_p
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(src, (bytes, bytearray)):
                target.write_bytes(bytes(src))
            else:
                shutil.copy2(str(src), target)
            written.append(rel_p.as_posix())
        if recipe_md is not None:
            (tmp / data['recipe']).parent.mkdir(parents=True, exist_ok=True)
            (tmp / data['recipe']).write_text(str(recipe_md), encoding='utf-8')
        with open(tmp / 'style.yaml', 'w', encoding='utf-8') as fh:
            fh.write(f'# letitedit style: {data.get("label") or name}. Taste, not law: edits can override any of it.\n')
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=110)
        old = None
        if dest.exists():
            old = root / f'.{name}.replaced-{int(time.time())}'
            os.replace(dest, old)
        os.replace(tmp, dest)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {'pack': name, 'style_yaml': str(dest / 'style.yaml'),
            'recipe': str(dest / data['recipe']) if recipe_md is not None else None, 'assets': written,
            'problems': check(str(dest))}


def check(pack=None):
    """Everything in a pack the tools can't do or can't find, as sentences ([] when all is usable): kind, recipe,
    preview, effects presets (each form tried against the edit tools), pop-ups, sounds, and files the pack uses from
    outside its own folder (not shipped with it; their licence is not the pack's to state)."""
    kit = pack if isinstance(pack, Kit) else load(pack)
    out = []
    if kit.get('kind') not in KINDS:
        out.append(f"kind: one of {', '.join(KINDS)}; got {kit.get('kind')!r}")
    fx = kit.get('fx') or {}
    out += density_problems(fx.get('density'), 'fx') + never_problems(fx.get('never'), 'fx')
    if fx.get('safe_zone') and fx['safe_zone'] != 'phone':      # phone = Shorts, TikTok and Reels together
        try:
            import letitedit.catalogs.platforms as platforms
            platforms.load(fx['safe_zone'])
        except Exception as e:  # noqa: BLE001
            out.append(f"fx.safe_zone {fx['safe_zone']!r}: not a platform letitedit_platforms knows ({e})")
    if kit.get('recipe') and not kit.recipe_path():
        out.append(f"recipe {kit['recipe']!r} not found in the pack")
    if kit.get('preview') and not kit.preview_path():
        out.append(f"preview {kit['preview']!r} not found in the pack")
    for i, eff in enumerate((kit.get('look') or {}).get('effects') or [], 1):
        try:                        # the look goes on footage tracks as track effects: each must be one the tools take
            import letitedit.timeline.edit_script as es
            es.build_filter(eff, 30.0, 30, 1080, 1920, kit=kit)
        except Exception as e:  # noqa: BLE001
            out.append(f'look.effects[{i}]: the edit tools do not take it: {e}')
    for name, preset in (kit.get('effects') or {}).items():
        out += _effect_problems(kit, name, preset)
    pop = kit.get('popups') or {}
    for i, e in enumerate(pop.get('entries') or [], 1):
        out += [f"popups.entries[{i}] ({(e or {}).get('id') or (e or {}).get('words')}): {p}"
                for p in popup_problems(kit, e)]
    sfx = kit.get('sfx') or {}
    for ev, name in (sfx.get('events') or {}).items():
        if ev not in SFX_EVENTS:
            out.append(f"sfx.events.{ev}: events are {', '.join(SFX_EVENTS)}")
        if name and not kit.sfx_file(name):
            out.append(f'sfx.events.{ev}: {name!r} is not a sound in sfx.map or a file')
    outside = []
    for name, rel in (sfx.get('map') or {}).items():
        p = kit.path(rel)
        if not p or not os.path.isfile(p):
            if not os.path.splitext(str(rel))[1] and kit.sfx_file(name):
                continue    # a sound from the asset library ('synth/whoosh-soft', 'sfx:pop'): its licence is the library's
            out.append(f'sfx.map.{name}: {rel!r} not found')
        elif kit.root is not None and not _inside(p, kit.root):
            outside.append(f'sfx.map.{name}')
    for e in pop.get('entries') or []:
        asset = (e or {}).get('asset') if isinstance(e, dict) else None
        img = asset.get('image') if isinstance(asset, dict) else None
        p = kit.path(img) if img else None
        if p and os.path.isfile(p) and kit.root is not None and not _inside(p, kit.root):
            outside.append(f"popup {(e or {}).get('id') or img}")
    if outside:
        out.append('uses files from outside the pack (not shipped with it; licence not stated by the pack): '
                   + ', '.join(outside))
    if kit.root is not None:
        credited = {str((c or {}).get('file', '')).replace('\\', '/') for c in kit.get('credits') or []}
        for sub in ('assets', 'sfx', 'brand'):
            folder = kit.root / sub
            for f in sorted(folder.rglob('*')) if folder.is_dir() else []:
                rel = f.relative_to(kit.root).as_posix()
                if f.is_file() and not f.name.startswith('.') and f.suffix.lower() not in ('.py', '.md', '.txt') \
                        and rel not in credited:
                    out.append(f'{rel}: no credits entry (file, source, licence)')
    return out


def notes(pack=None):
    """What this PC makes differently from the pack's own design (not problems): motion-clip presets are drawn as
    their nearest graphic while motion clips can't render here (motion.available())."""
    kit = pack if isinstance(pack, Kit) else load(pack)
    names = [n for n, p in (kit.get('effects') or {}).items()
             if isinstance(p, dict) and p.get('kind') in ('motion', 'count_up', 'location')]
    if not names:
        return []
    try:
        import letitedit.pictures.motion as motion
        why = motion.available()
    except ImportError as e:
        why = str(e)
    return [f"{', '.join('effects.' + n for n in names)}: drawn as graphics on this PC, motion clips can't render "
            f'here ({why})'] if why else []


def _inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False


if __name__ == '__main__':
    raise SystemExit('Style-pack commands have been removed. The local Look interface is bridge/look_library.py.')
