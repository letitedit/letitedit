"""Look device receipts checked against the current edit and delivered bytes."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

DEVICES = ('captions', 'transitions', 'broll', 'lighting', 'sound', 'opening', 'punchins', 'sound_accents')
DEVICE_WORDS = {
    'captions': r'caption|typograph|kinetic|letter|text',
    'transitions': r'flash|negative|transition|inver',
    'broll': r'b.roll|cutaway|stock|coverage',
    'lighting': r'light|grade|teal|warm|studio',
    'sound': r'sound|music|audio|score|loudness',
    'opening': r'opening|hook|first .{0,12}second|intro',
    'punchins': r'punch|zoom|push.in|push in',
    'sound_accents': r'accent|whoosh|sfx|sound effect|sound design|transient',
    'shutter_clicks': r'shutter|click on (each|every)|transition click',
    'key_clicks': r'key (tick|click)|typewriter|keystroke|word click',
    'shot_sources': r'shot.source|base.picture|source.family|provenance',
    'stickers': r'sticker|picture.in.picture|inset|pip',
    'grade': r'grade|colou?r|lut|teal|warm|saturat|tone',
    'camera': r'camera|shot size|moving shot|static shot|pan|tilt|push.in|handheld',
}
# what a Look measured beside its recipe (Learn and Import a style save them; a library Look has only its recipe)
MEASUREMENTS = ('visual.json', 'lighting.json', 'grade.json', 'sound.json', 'sources.json', 'graphic-kit.json')
# a measured file's own identity, not a device to place
FILE_KEYS = {'format', 'version', 'reference_sha256', 'duration_s', 'limits', 'from', 'skipped_samples'}
# recipe sections about the footage, where the Look fits, its format, its limits or what it must not do: not devices
NOT_A_DEVICE = re.compile(r'#{1,6}\s*(what footage|footage|where it fits|fits|known limits|limits|weak spots|structure'
                          r'|format|must not)', re.I)


KIT_NOT_MEASURED = 'Fix protected-picture or unpinned drawing findings before measuring'
LEFT_OUT_FORMS = ('{"kind": "left_out", "because": "covered_by", "by": "<a device or source unit placed in these '
                  'decisions>"} when another placed device already carries those moments; {"kind": "left_out", '
                  '"because": "unconfirmed"} when the Look itself marks every measured event of it unconfirmed; '
                  '{"kind": "left_out", "because": "no_moment"} for an anchored overlay whose moment the new story '
                  'does not have')


def _unconfirmed(text):
    """True when the measured unit marks every event of its device unconfirmed (sound.json effects: each event's
    `confirmed` false and no confirmed count)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    events = data.get('events')
    if not isinstance(events, list) or not events:
        return False
    return (not data.get('confirmed_count')
            and all(isinstance(event, dict) and event.get('confirmed') is not True for event in events))


SOUND_DEVICES = ('sound', 'sound_accents', 'shutter_clicks', 'key_clicks')


def _is_sound(name):
    """A sound device or a unit of the Look's sound.json; everything else is picture."""
    return name in SOUND_DEVICES or str(name).startswith('sound.json:')


def left_out_problem(name, entry, requirements, decisions):
    """A device the Look measured, left out on purpose. The reason holds when the receipt or the Look shows it:
    another device placed in these same decisions carries those moments (covered_by), the Look marks every measured
    event of it unconfirmed (unconfirmed), or it is an overlay tied to a story moment (an anchor) the new story lacks
    (no_moment). A stated reason is still required in `reason`."""
    evidence = entry.get('evidence') or {}
    because = evidence.get('because')
    text = requirements.get(name, '\n'.join(requirements.values()))
    if not str(entry.get('reason', '')).strip():
        return 'left_out needs the reason in reason'
    if because == 'covered_by':
        by = str(evidence.get('by', ''))
        placed = (decisions or {}).get(by) or ((decisions or {}).get('_sources') or {}).get(by) or {}
        if not (by and by != name and placed.get('status') == 'placed' and placed.get('items')):
            return f'left_out covered_by needs "by" naming a device or source unit placed with items in these decisions (got {by!r})'
        if _is_sound(by) != _is_sound(name):
            return f'left_out covered_by needs a device of the same kind: {by} cannot carry the moments of {name}'
        return None
    if because == 'unconfirmed':
        if _unconfirmed(text):
            return None
        return 'left_out unconfirmed needs a Look unit whose measured events are all unconfirmed; this one has confirmed events'
    if because == 'no_moment':
        if '"anchor"' in text:
            return None
        return 'left_out no_moment is for an overlay the Look ties to a story moment (an anchor); this unit has none'
    return 'left_out needs because: covered_by, unconfirmed or no_moment. Forms: ' + LEFT_OUT_FORMS


# a person's own words that keep their face uncovered (or as recorded): a sentence naming their face or how they
# look, with one of these. "My Look" is letitedit's word for a Look, not their face.
FACE_WORDS = re.compile(r"\bfaces?\b|how i look", re.I)
_WHOSE = r"(?:my|the|his|her|their|our|your)(?: or (?:my|the|his|her|their|our|your))?"
# on, over or in front of a face: "on my face", "on top of his or her face", "in front of my face"
_ON_FACE = rf"\b(?:on|over|across|in front of) (?:top of )?{_WHOSE} faces?\b"
# something placed on the picture, before "on faces" with no word for whose: "no stickers on faces" (not "graininess")
_PLACED_ON_FACES = (r"\b(?:text|words?|stickers?|emojis?|captions?|graphics?|titles?|logos?|overlays?|pop-?ups?"
                    r"|labels?|arrows?|anything)\b[^.;!?]*\b(?:on|over|across|in front of) (?:top of )?faces\b")
KEEP_UNCOVERED = re.compile(
    r"uncovered|unchanged|untouched|as recorded"
    rf"|\boff (?:of )?{_WHOSE} faces?\b"
    rf"|\bleave {_WHOSE} faces? alone"
    rf"|(?:don'?t|do not|never|no|nothing|without)\b[^.;!?]*{_ON_FACE}"
    rf"|(?:don'?t|do not|never|no|nothing|without)\b[^.;!?]*{_PLACED_ON_FACES}"
    r"|(?:don'?t|do not|never|no|nothing|without)\b[^.;!?]*\b(?:cover\w*|block\w*|hid\w*)\b[^.;!?]*\bfaces?\b"
    r"|(?:don'?t|do not|never|no|nothing|without)\b[^.;!?]*\bfaces?\b[^.;!?]*\b(?:cover\w*|block\w*|hid\w*)"
    rf"|\bkeep {_WHOSE} faces? (?:clear|visible)\b"
    rf"|\bkeep\b[^.;!?]*\baway from {_WHOSE} faces?\b"
    r"|(?:don'?t|do not|never) change how i look", re.I)
# a must_avoid entry is already a wish against something: one naming a cover, or something on or over a face, is enough
AVOID_COVER = re.compile(rf"\b(?:cover\w*|block\w*|hid\w*)\b|{_ON_FACE}|{_PLACED_ON_FACES}", re.I)
# the brief's fields that hold the person's own wishes (the router's brief.json): not the AI's own choices
PERSON_FIELDS = ('request', 'must_avoid', 'must_keep', 'required_lines', 'protected', 'tone', 'desired_response',
                 'ending', 'narration')


def face_words(brief):
    """The first sentence of the person's own wishes in the brief (PERSON_FIELDS) that keeps their face uncovered:
    "don't cover my face", "keep graphics off my face", "no text on my face", "leave my face alone", "keep my face
    clear", "face unchanged / untouched / as recorded", "don't change how I look"; a must_avoid entry naming the face
    and a cover ("stickers over my face"). None when there is none."""
    for value in ((brief or {}).get('must_avoid') or []):
        text = value if isinstance(value, str) else (value.get('line') or value.get('text') or '') \
            if isinstance(value, dict) else ''
        for sentence in re.split(r'(?<=[.;!?])\s+|\n', str(text)):
            if FACE_WORDS.search(sentence) and AVOID_COVER.search(sentence):
                return sentence.strip()
    texts = []

    def walk(value):
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
    for field in PERSON_FIELDS:
        walk((brief or {}).get(field))
    for text in texts:
        for sentence in re.split(r'(?<=[.;!?])\s+|\n', text):
            if FACE_WORDS.search(sentence) and KEEP_UNCOVERED.search(sentence):
                return sentence.strip()
    return None


def kit_facts(kit_result, brief):
    """The kit check's facts as the Look check's rows: its face cover (face_cover: frames, seconds, first frame, the
    pieces on screen then) and the speaker's picture (picture: an inset, a see-through or graded picture) are notes,
    never faults; a face cover becomes a picture finding when the person's own words for this video keep their face
    uncovered (face_words)."""
    rows = []
    cover = (kit_result or {}).get('face_cover') or {}
    if cover.get('frames'):
        notes = ' '.join((kit_result or {}).get('notes') or [])
        said = face_words(brief)
        if said:
            rows.append({'severity': 'major', 'kind': 'picture', 'device': 'graphic_kit', 'face_cover': cover,
                         'problem': f"The kit's ink covers the face on {cover['frames']} frame(s) ({cover['seconds']:g} s) "
                                    f"from frame {cover['first_frame']}, and the person asked: \"{said}\". " + notes})
        else:
            rows.append({'severity': 'note', 'kind': 'note', 'device': 'graphic_kit', 'face_cover': cover,
                         'problem': notes or f"The kit's ink falls inside a detected face box on {cover['frames']} "
                                             f"frame(s) ({cover['seconds']:g} s) from frame {cover['first_frame']}."})
    for fact in (kit_result or {}).get('picture') or []:
        rows.append({'severity': 'note', 'kind': 'note', 'device': 'graphic_kit', 'item': fact.get('item'),
                     'problem': fact.get('what', '')})
    return rows


def decline_problem(name, entry, requirements, brief, decisions=None):
    evidence = entry.get('evidence') or {}
    basis = evidence.get('kind')
    device = name if name in DEVICE_WORDS else evidence.get('device')
    if name.startswith('grade.json:') and device != 'grade':
        return ("the grade is the Look's colour and goes on footage with or without a face; a lighting or face "
                "refusal does not decline it")
    if device in DEVICE_WORDS and name not in DEVICE_WORDS:
        if not re.search(DEVICE_WORDS[device], '\n'.join(requirements.values()), re.I):
            return 'source-unit refusal must concern a device actually present in that unit'
    if basis == 'left_out':
        return left_out_problem(name, entry, requirements, decisions)
    if basis == 'unmeasured':
        pattern = DEVICE_WORDS.get(name, '|'.join(DEVICE_WORDS.values()))
        text = requirements.get(name, '\n'.join(requirements.values()))
        return ('the Look measured this device, so unmeasured does not fit: place it, or leave it out with evidence '
                + LEFT_OUT_FORMS) if re.search(pattern, text, re.I) else None
    if basis == 'tool_refusal':
        path = Path(str(evidence.get('path', '')))
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
            if evidence.get('sha256') != digest(path) or evidence.get('device') != (device or name):
                return 'tool refusal needs matching device and evidence file digest'
            refused = (payload.get('safe') is False or payload.get('refused') is True
                       or bool(payload.get('error')) or payload.get('status') in ('refused', 'failed', 'blocked'))
            if refused and evidence.get('tool') and evidence.get('attempt'):
                return None
        except (OSError, ValueError, TypeError):
            pass
        return 'tool refusal needs an actual failed tool result, tool, attempt, device and file digest'
    if basis == 'person_rule':
        quote = evidence.get('quote', '')
        rules = json.dumps(brief, ensure_ascii=False)
        prohibitions = {
            'transitions': r'no (flashes|flash|transitions)|never flash|no flashing',
            'lighting': r'no (lighting|grading|colour grading|color grading)|do not (grade|relight)',
            'grade': r'no (grading|colou?r grading|grade|colou?r change)|do not (grade|change the colou?rs?)'
                     r'|keep (the )?(original|natural) colou?rs?',
            'punchins': r'no (zoom|punch)|never zoom|no reframing|do not (zoom|crop)',
            'sound_accents': r'no (sound effects|accents|sfx)|voice only|speech only',
            'shutter_clicks': r'no (sound effects|clicks|sfx)|voice only|speech only',
            'key_clicks': r'no (sound effects|clicks|ticks|sfx)|voice only|speech only',
            'sound': r'no (music|sound)|voice only|speech only',
            'opening': r'no (hook|opening)|keep the original opening',
            'broll': r'no (b.roll|cutaway)|talking.head only',
            'captions': r'no (captions|text)|do not (caption|add text)',
            'stickers': r'no (stickers|insets|picture.in.picture)|do not add stickers',
            'camera': r'no (camera )?(moves|movement|motion)|keep (it|the camera|the shots?) (still|static|steady)'
                      r'|tripod only|locked.off',
        }
        if quote and quote in rules and re.search(prohibitions.get(device, r'(?!)'), quote, re.I) and evidence.get('conflict'):
            return None
        return 'person rule must quote an actual explicit device prohibition in the brief and name the conflict; face protection or a warm/studio mismatch is not a blanket prohibition'
    return ('weak decline: give evidence kind tool_refusal, person_rule, unmeasured (only when the Look has no '
            'measurement of it) or left_out: ' + LEFT_OUT_FORMS)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def receipt_path(project):
    return Path(str(project) + '.look-check.json')


# the tool's reply (short_reply): a Look file up to this many characters is in it; a longer one is named by its path
REPLY_FILE_CHARS = 8000
# and each source unit's text is cut to this many characters (its key, which decisions._sources needs, is whole)
REPLY_UNIT_CHARS = 300
FULL_RESULT = 'look-check-full.json'


def full_result_path(project):
    """The whole of the last Look check of this project (short_reply writes it): its own folder's look-check-full.json."""
    import letitedit.timeline.project_journal as project_journal
    return project_journal.folder(project) / FULL_RESULT


def short_reply(result, project, given=False):
    """The result as letitedit_look_check replies with it: everything but the Look files' full text. Files up to
    REPLY_FILE_CHARS stay in requirements; a longer one is in requirements_in_files with its length and path; each
    source unit keeps its key and its first REPLY_UNIT_CHARS characters; decisions just given (given) are not sent
    back, the receipt holding them is named instead. The whole result is written to full_result_path(project) and
    named in the reply as full_result. A result without the Look files, or one that can't be written there, is the
    reply as it is."""
    if 'requirements' not in result and 'source_units' not in result:
        return result
    try:
        if not Path(project).is_file():         # an old episode folder: the project file it reads as
            import letitedit.timeline.edit_script as edit_script
            project = edit_script.read(project)['project']
        path = full_result_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
        temporary.replace(path)
    except (OSError, TypeError, ValueError, KeyError):
        return result
    files = {Path(name).name: name for name in result.get('source_files', [])}
    texts = result.get('requirements') or {}
    reply = {key: value for key, value in result.items() if key not in ('requirements', 'source_units')}
    reply['requirements'] = {name: text for name, text in texts.items() if len(text) <= REPLY_FILE_CHARS}
    longer = {name: {'characters': len(text), 'path': files.get(name)} for name, text in texts.items()
              if len(text) > REPLY_FILE_CHARS}
    if longer:
        reply['requirements_in_files'] = longer
    reply['source_units'] = {key: text if len(str(text)) <= REPLY_UNIT_CHARS
                             else f'{str(text)[:REPLY_UNIT_CHARS]} ... ({len(str(text))} characters in all)'
                             for key, text in (result.get('source_units') or {}).items()}
    if given and 'decisions' in result:
        reply['decisions'] = f'as given, kept in {receipt_path(project)}'
    reply['full_result'] = str(path)
    return reply


def items_digest(items, ids):
    """What draws a device on the timeline: a digest of its placed items as they are now, or None when it has none
    or one of them is gone."""
    ids = list(ids) if isinstance(ids, (list, tuple)) else []
    rows = [items[identity] for identity in ids if identity in items]
    if not rows or len(rows) != len(ids):
        return None
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def stamp_exports(decisions, video_hash, revision, items):
    """Decisions given with the export they were observed on: each device's observation of these bytes keeps the
    edit it was made on and what drew the device then (its items' digest), so a later render of the same items
    (the full-size final of a reviewed preview) reads it."""
    out = {}
    for name, entry in (decisions or {}).items():
        export = entry.get('export') if isinstance(entry, dict) else None
        if (name != '_sources' and isinstance(export, dict) and export.get('sha256') == video_hash
                and str(export.get('observation', '')).strip()):
            entry = {**entry, 'export': {**export, 'project_sha256': revision,
                                         'items_sha256': items_digest(items, entry.get('items'))}}
        out[name] = entry
    return out


def measured_here(name, entry, video_hash):
    """The check's own observation of a device on these bytes, when it measured it there: the camera language, the
    sound's opening, the captions' contrast. None for a device it does not measure."""
    if name == 'camera' and isinstance(entry.get('camera'), dict):
        cut = entry['camera'].get('cut') or {}
        return (f"camera language measured on these bytes by the Look check: {cut.get('shots')} shots, "
                f"{(cut.get('moving_share') or 0):.0%} moving")
    if name == 'sound' and isinstance(entry.get('opening'), dict):
        return (f"sound measured on these bytes by the Look check: at its main level from "
                f"{entry['opening'].get('cut_full_s')} s")
    if name == 'captions' and (entry.get('contrast') or {}).get('video_sha256') == video_hash:
        return 'caption contrast measured on these bytes'
    return None


def project_digest(script):
    content = {key: script[key] for key in ('profile', 'tracks')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def relevant_share(script, identities):
    import letitedit.timeline.edit_script as edit_script
    spans = sorted((edit_script.to_seconds(item['at']), edit_script.to_seconds(item['at']) + item['len'])
                   for track in script['tracks'] for item in track['items'] if item.get('id') in identities)
    end = max((edit_script.to_seconds(item['at']) + item['len'] for track in script['tracks']
               for item in track['items'] if 'id' in item), default=0)
    seconds = 0.
    cursor = 0.
    for start, stop in spans:
        seconds += max(0, stop - max(cursor, start))
        cursor = max(cursor, stop)
    return {'seconds': seconds, 'duration': end, 'share': seconds / end if end else 0.}


CAPTION_COVERAGE = ('every_native_frame', 'fully_on_native_frames')


def caption_measurement(project, supplied, revision):
    """The caption contrast measurement for this edit: the one in the decision when it is for this edit, else the
    caption tools' own results kept beside the project (the colour choice's receipt, and the export's kept
    measurements), so a receipt never has to copy a measurement the tools already hold."""
    if isinstance(supplied, dict) and supplied.get('project_sha256') == revision:
        return supplied
    base = Path(project)
    for suffix in ('.caption-colour.json', '.caption-colour-check.json', '.caption-readability.json'):
        try:
            saved = json.loads(base.with_suffix(suffix).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if isinstance(saved, dict) and isinstance(saved.get('result'), dict) and 'key' in saved:
            saved = saved['result']
        if (isinstance(saved, dict) and saved.get('project_sha256') == revision
                and saved.get('coverage') in CAPTION_COVERAGE):
            return {**saved, 'read_from': str(base.with_suffix(suffix))}
    return supplied if isinstance(supplied, dict) else {}


def caption_failures(measured):
    """The captions under the floor, by their words, for the message."""
    failing = []
    for identity, rows in (measured.get('captions') or {}).items():
        if isinstance(rows, list):
            failing += [f"\"{row.get('text', '')}\" ({row.get('colour', '')}, {identity})"
                        for row in rows if isinstance(row, dict) and not row.get('passed')]
        elif isinstance(rows, dict):
            failing += [f"\"{word.get('text', '')}\" ({identity})" for word in (rows.get('words') or {}).values()
                        if isinstance(word, dict) and word.get('below_floor_frames')]
    return (f"{len(failing)} caption(s): " + '; '.join(failing[:8])) if failing else 'see the caption measurement'


def broll_measured_none(requirements):
    """True when the Look's visual.json measured every reference and found no cutaways (b-roll share or seconds 0)."""
    try:
        references = json.loads(requirements.get('visual.json', 'null'))['references']
    except (TypeError, ValueError, KeyError):
        return False
    if not references:
        return False
    for reference in references:
        semantic = (reference or {}).get('semantic') or {}
        if not (semantic.get('broll_share') == 0 or semantic.get('broll_seconds') == 0):
            return False
    return True


def current_project(project):
    import letitedit.server.timeline_tools as timeline_tools
    import letitedit.timeline.edit_script as edit_script
    script = edit_script.read(project)
    identity = Path(script['project'])
    live = timeline_tools._live_state(identity)
    # a window that only shows the saved project reads it back with the editor's own defaults filled in (filter
    # parameters, its blend), which changes the digest without changing the edit: read the window only when it
    # holds unsaved changes, so a measurement taken on the saved project still counts while the project is open
    live = live if live and live.get('modified') else None
    source = Path(timeline_tools.live_edit_snapshot(live)) if live else identity
    return identity, source, edit_script.read(source) if live else script


def source_units(requirements):
    units = {}
    for name, text in requirements.items():
        if name.endswith('.md'):
            sections = re.split(r'(?m)(?=^#{1,6} )', text)
            for index, section in enumerate(section for section in sections if section.strip()):
                units[f'{name}:{index}'] = section.strip()
        else:
            data = json.loads(text)
            entries = data.items() if isinstance(data, dict) else enumerate(data if isinstance(data, list) else [data])
            for key, value in entries:
                units[f'{name}:{key}'] = json.dumps(value, ensure_ascii=False)
    return units


def device_units(units):
    """The source units that hold a device to place or decline: every one except a recipe section about the footage,
    the fit, the format, the limits or the must-nots, a bare title, and a measured file's identity (its format, digest,
    length and limits). A section is never judged by its words: shot choice or framing names no device word."""
    out = {}
    for key, text in units.items():
        name, _, part = key.rpartition(':')
        if name.endswith('.md'):
            if NOT_A_DEVICE.match(text) or (text.startswith('#') and not text.partition('\n')[2].strip()):
                continue
        elif part in FILE_KEYS:
            continue
        out[key] = text
    return out


def _write_cutaway_notes(project, script, ids, feelings):
    """The project's notes: each cutaway's line, its feeling and why the shot fits (cutaway-notes.md beside the project)."""
    try:
        import letitedit.timeline.project_journal as project_journal
        import letitedit.looks.cutaway_slots as cutaway_slots
        from letitedit.timeline.timeline_speech import timeline_words
        words = timeline_words(script, cached_only=True)
        spans = {identity: (s, e) for identity, s, e in cutaway_slots.existing(script)}
        rows = ['# Cutaways: line, feeling, why the shot fits', '']
        for identity in sorted(ids, key=lambda i: spans.get(i, (0, 0))[0]):
            s, e = spans.get(identity, (0, 0))
            line = cutaway_slots._said(words, s, e)
            note = feelings.get(identity) or {}
            rows.append(f"- {s:.1f}-{e:.1f} s `{identity}` \"{line}\": **{note.get('feeling', '')}** - {note.get('why', '')}")
        folder = project_journal.folder(project)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'cutaway-notes.md').write_text(chr(10).join(rows) + chr(10), encoding='utf-8')
    except Exception:  # noqa: BLE001 - notes are a record; the receipt stands without them
        pass


def format_findings(recipe, project):
    """A learned Look's format (place.json beside its recipe) against the first cut's story plan: each section built
    from this footage or left out with a reason (look_place.plan_check). No story plan yet: nothing to check here."""
    place_path = Path(recipe).with_name('place.json')
    if not place_path.is_file():
        return []
    import letitedit.looks.look_place as look_place
    import letitedit.review.review_bundle as review_bundle
    plan_path = review_bundle.story_plan_path(project=str(project))
    if plan_path is None:
        return []
    try:
        problems = look_place.plan_check(json.loads(place_path.read_text(encoding='utf-8-sig')),
                                         json.loads(Path(plan_path).read_text(encoding='utf-8-sig')))
    except (OSError, ValueError) as error:
        problems = [f'format plan unreadable: {error}']
    return [{'severity': 'major', 'device': 'format', 'problem': problem} for problem in problems]


def _check_broll(name, status, entry, ids, script, requirements, video, problems, timeline, project):
    """Check relevant cutaway coverage, rhythm, motion and per-line feelings."""
    if name == 'broll' and status == 'placed':
        relevant = dict(entry.get('relevance') or {})
        for identity, note in (entry.get('feelings') or {}).items():
            if isinstance(note, dict) and not str(relevant.get(identity, '')).strip() and str(note.get('why', '')).strip():
                relevant[identity] = f"{note.get('feeling', '')}: {note['why']}"
        lacking = [identity for identity in ids if not str(relevant.get(identity, '')).strip()]
        if lacking:
            problems.append('each shot needs its line and what it shows (relevance: {id: "..."}, or feelings: '
                            '{id: {feeling, why}}); off-topic footage does not count; missing for ' + ', '.join(lacking[:8]))
        coverage = relevant_share(script, ids)
        entry = {**entry, 'timeline_coverage': coverage}
        from letitedit.looks.cutaway_rhythm import check as check_rhythm
        rhythm, rhythm_problems = check_rhythm(script, ids, entry, requirements, coverage['duration'])
        entry['cutaway_rhythm'] = rhythm
        timeline.extend(rhythm_problems)
        from letitedit.looks.cutaway_motion import check as check_motion
        movement, movement_problems = check_motion(entry, requirements, video)
        entry['cutaway_motion'] = movement
        timeline.extend(movement_problems)
        target = entry.get('share_target')
        if 'share_target' not in entry or (target is not None and (type(target) not in (int, float) or not 0 <= target <= 1)):
            problems.append('share_target needs the Look minimum as a fraction, or explicit null when unmeasured')
        elif target is not None and coverage['share'] + 1e-6 < target:
            short = target * coverage['duration'] - coverage['seconds']
            timeline.append(f"declared relevant shots cover {coverage['share']:.1%} ({coverage['seconds']:.1f} of "
                            f"{coverage['duration']:.1f} s), under the Look's {target:.1%}: about {short:.1f} s more cutaway")
    if name == 'broll' and status == 'placed' and re.search(r'feeling of (the|each|every) line', json.dumps(requirements), re.I):
        feelings = entry.get('feelings') or {}
        lacking = [identity for identity in ids if not (isinstance(feelings.get(identity), dict)
                   and str(feelings[identity].get('feeling', '')).strip() and str(feelings[identity].get('why', '')).strip())]
        if lacking:
            problems.append("each cutaway needs the feeling of its line and why the shot carries it (feelings: {id: {feeling, why}}); "
                            f"missing for {', '.join(lacking[:8])}")
        elif ids:
            _write_cutaway_notes(project, script, ids, feelings)
    return entry


def _check_caption_contrast(name, status, kit_result, project, entry, revision, findings, look_measured, timeline, problems, requirements, script, video, video_hash):
    """Check caption measurements and colour choice for this project and export."""
    if name == 'captions' and status == 'placed' and kit_result is None:
        measured = caption_measurement(project, entry.get('contrast') or {}, revision)
        entry = {**entry, 'contrast': measured}
        for finding in measured.get('minor_findings', []):
            findings.append({'severity': 'minor', 'device': name, 'problem': finding['problem'],
                             'text': finding.get('text')})
        if (measured.get('project_sha256') != revision
                or measured.get('coverage') not in ('every_native_frame', 'fully_on_native_frames')):
            (timeline if look_measured else problems).append('whole-time 360px ink contrast not measured on this edit: run letitedit_caption_readability '
                            '(inverted_then_white=true, apply=true for an inverted-then-white Look) after the last '
                            'picture change; this check reads its result itself')
        elif not measured.get('passed'):
            (timeline if look_measured else problems).append('caption contrast measured on this edit and below the floor: '
                                                             + caption_failures(measured))
        policy = json.dumps(requirements).lower()
        if 'inverted-then-white' in policy or 'inverted_then_white' in policy:
            import letitedit.looks.caption_colour as caption_colour
            choice = caption_colour.choice_status(project, script)
            if not choice['passed']:
                timeline.append(choice['reason'])
        if video and measured.get('video_sha256') != video_hash:
            problems.append('caption contrast has not been measured on these delivered bytes')
    return entry


def camera_references(requirements):
    """The Look's measured camera language: each reference's visual.json camera block that holds shots."""
    try:
        references = json.loads(requirements.get('visual.json', 'null'))['references']
    except (TypeError, ValueError, KeyError):
        return []
    return [ref['camera'] for ref in references or [] if isinstance(ref, dict) and isinstance(ref.get('camera'), dict)
            and ref['camera'].get('shots')]


def reference_shots(requirements):
    """The Look's reference shots by reference index ({index: [(start_s, end_s)]}), as its visual.json's camera
    measured them: the index is the reference's place in the list, as grade.json's samples name it."""
    try:
        references = json.loads(requirements.get('visual.json', 'null'))['references']
    except (TypeError, ValueError, KeyError):
        return {}
    out = {}
    for index, ref in enumerate(references or []):
        shots = ((ref or {}).get('camera') or {}).get('shots') if isinstance(ref, dict) else None
        spans = [(float(s['start_s']), float(s['end_s'])) for s in shots or []
                 if isinstance(s, dict) and s.get('start_s') is not None and s.get('end_s') is not None]
        if spans:
            out[index] = spans
    return out


def footage_folders(brief):
    """The footage folders a brief names (a file stands for its folder)."""
    named = (brief or {}).get('footage') or []
    named = [named] if isinstance(named, str) else named
    out = []
    for place in named:
        if isinstance(place, str) and place.strip():
            path = Path(place)
            out.append(str(path if path.is_dir() else path.parent))
    return out


def _check_camera(entry, references, video, script, timeline, problems, folders=()):
    """The Look's camera language on the delivered export, whatever the receipt says: the moving share and shot
    sizes against the reference's, the stretches outside them with the footage's unused fuller shots, and the
    ending."""
    if not video:
        problems.append('the camera language is measured on the export: call letitedit_look_check with video '
                        '(the review bundle does)')
        return entry
    import letitedit.looks.camera_language as camera_language
    try:
        measured = camera_language.measure(video)
    except Exception as error:  # noqa: BLE001 - an unreadable export is reported, not a crash of the whole check
        timeline.append(f'camera language not measured on this export: {type(error).__name__}: {error}'[:300])
        return entry
    summary, found = camera_language.check(references, measured, script, folders)
    timeline.extend(found)
    entry = {**entry, 'camera': summary}
    # the pace section by section, from the same shots: its own finding (pace_problems, taken out by the caller)
    import letitedit.looks.pace as pace
    try:
        pace_summary, pace_found = pace.check(references, measured, script)
    except Exception as error:  # noqa: BLE001 - the camera language stands without the pace
        pace_summary, pace_found = {'not_measured': f'{type(error).__name__}: {error}'[:300]}, []
    if pace_summary:
        entry['pace'] = pace_summary
    if pace_found:
        entry['pace_problems'] = pace_found
    return entry


TURNED_DOWN_DB = -15.0       # a clip's own sound this far down is background (a crowd, an announcer), not talk


def _opening_talk(script, seconds):
    """Seconds of speech the timeline plays in its first seconds (cached words only), on clips not turned down to
    background; 0 without a timeline or cached words."""
    if not script or not seconds:
        return 0.0
    try:
        from letitedit.timeline.timeline_speech import timeline_words
        words = timeline_words(script, 0, seconds, cached_only=True)
    except Exception:  # noqa: BLE001 - without words, the cut's opening is judged on its sound alone
        return 0.0
    gains = {}
    for track in script.get('tracks') or []:
        for item in track.get('items') or []:
            gains[item.get('id')] = sum(float(effect['gain']) for effect in item.get('effects') or []
                                        if isinstance(effect, dict) and isinstance(effect.get('gain'), (int, float)))
    return round(sum(max(0.0, min(seconds, w['t1']) - max(0.0, w['t0'])) for w in words
                     if gains.get(w.get('id'), 0.0) > TURNED_DOWN_DB), 3)


def _check_sound_opening(entry, sound_text, video, timeline, script=None):
    """How fast the export's sound reaches its main level, against the opening of the Look's measured music: later,
    or (with nobody talking in either opening) well before a reference that opens quiet."""
    import letitedit.looks.sound_opening as sound_opening
    try:
        ref = sound_opening.reference(json.loads(sound_text))
        if not ref:
            return entry
        talk = _opening_talk(script, ref['full_s']) if ref.get('full_s') else 0.0
        summary, found = sound_opening.check(ref, sound_opening.measure(video), talk_s=talk)
    except Exception as error:  # noqa: BLE001 - an export without readable sound is noted, not a fault in the video
        return {**entry, 'opening_not_measured': f'{type(error).__name__}: {error}'[:300]}
    timeline.extend(found)
    return {**entry, 'opening': summary} if summary else entry


def reference_mix(requirements):
    """What the Look's reference shots show (shot_mix.from_camera on its visual.json camera shots, every reference's
    rows together); None when the reference's shots carry no vision facts (a Look learned before they were kept)."""
    try:
        references = json.loads(requirements.get('visual.json', 'null'))['references']
    except (TypeError, ValueError, KeyError):
        return None
    import letitedit.looks.shot_mix as shot_mix
    rows = []
    for ref in references or []:
        found = shot_mix.from_camera(((ref or {}).get('camera') or {}).get('shots') if isinstance(ref, dict) else None)
        rows += found or []
    return rows or None


def _shot_mix(video, script, ref_rows):
    """(summary, problems) of the export's mix of what its shots show against the reference's, with the footage's
    unused stretches of a kind it lacks (the fact log, nothing measured there)."""
    import letitedit.looks.camera_language as camera_language
    import letitedit.looks.shot_mix as shot_mix
    shots = camera_language.measure(video).get('shots')
    rows = shot_mix.from_camera(shots) or shot_mix.measure(video, shots)
    return shot_mix.check(ref_rows, rows, camera_language.footage_log(script))


def whole_video(recipe, look, video, script, graded_look, ref_shots=None, ref_mix=None):
    """The measured Look against the whole export, whatever the receipts say: one grade across its footage shots
    against the reference's (grade_match), and its sound's shape (opening, level through the body, ending, rate of
    sharp hits) against the reference's (sound_shape). ref_shots (reference_shots) lets the grade's evenness from one
    shot to the next be read against the reference's own shots. Near repeats (one file shown again within
    shot_mix.REPEAT_S) are named whatever the reference. ref_mix (reference_mix) adds what the shots show (people up
    close, people wider, details, transport, places) against the reference's mix, with unused footage of a kind the cut
    lacks. The opening title is measured against the recipe's title rule (title_measure) when the recipe has one.
    Returns ({'grade_likeness', 'sound_shape', 'shot_mix', 'near_repeats', 'title'}, findings)."""
    out, findings = {}, []
    try:
        import letitedit.looks.shot_mix as shot_mix
        runs = shot_mix.near_repeats(script)
        if runs:
            out['near_repeats'] = runs
            findings.append({'severity': 'major', 'kind': 'picture', 'device': 'shot_mix',
                             'problem': 'Look shot choice: ' + shot_mix.repeats_text(runs)})
    except Exception as error:  # noqa: BLE001 - noted, not a crash
        out['near_repeats'] = {'not_measured': f'{type(error).__name__}: {error}'[:300]}
    if ref_mix:
        try:
            summary, problems = _shot_mix(video, script, ref_mix)
            out['shot_mix'] = summary
            if problems:
                findings.append({'severity': 'major', 'kind': 'picture', 'device': 'shot_mix',
                                 'problem': "Look shot mix (what the shots show, against the reference's): "
                                            + '; '.join(problems)
                                            + ''.join('; ' + limit for limit in summary.get('footage_limits') or [])})
        except Exception as error:  # noqa: BLE001 - a mix that can't be read is noted, not a crash
            out['shot_mix'] = {'not_measured': f'{type(error).__name__}: {error}'[:300]}
    if graded_look:
        try:
            import letitedit.looks.camera_language as camera_language
            import letitedit.looks.grade as grade
            import letitedit.looks.grade_match as grade_match
            reference = grade_match.reference(grade.look_grade(look=look).get('grade'), ref_shots)
            shots = grade_match.shot_rows(video, camera_language.measure(video).get('shots'), script)
            summary, problems = grade_match.check(reference, shots, grade.last_reach(script or {}))
            out['grade_likeness'] = summary
            if problems:
                findings.append({'severity': 'major', 'kind': 'picture', 'device': 'grade_likeness',
                                 'problem': "Look grade likeness (one grade across the footage, against the "
                                            "reference's): " + '; '.join(problems)})
        except Exception as error:  # noqa: BLE001 - an export that can't be read for colour is noted, not a crash
            out['grade_likeness'] = {'not_measured': f'{type(error).__name__}: {error}'[:300]}
    try:
        import letitedit.looks.title_measure as title_measure
        text = Path(recipe).read_text(encoding='utf-8-sig') if recipe and Path(recipe).is_file() else ''
        summary, problems = title_measure.check_export(text, video, script)
        if summary:
            out['title'] = summary
        if problems:
            findings.append({'severity': 'major', 'kind': 'picture', 'device': 'title',
                             'problem': "Look title (measured on the export, against the recipe's title rule): "
                                        + '; '.join(problems)})
    except Exception as error:  # noqa: BLE001 - a title that can't be read is noted, not a crash
        out['title'] = {'not_measured': f'{type(error).__name__}: {error}'[:300]}
    try:
        import letitedit.looks.sound_shape as sound_shape
        reference = sound_shape.look_shape(recipe)
        if reference:
            summary, problems = sound_shape.check(reference, sound_shape.measure(video))
            out['sound_shape'] = summary
            if problems:
                findings.append({'severity': 'major', 'kind': 'sound', 'device': 'sound_shape',
                                 'problem': "Look sound shape (the reference's, measured on the whole mix): "
                                            + '; '.join(problems)})
    except Exception as error:  # noqa: BLE001 - an export without readable sound is noted, not a crash
        out['sound_shape'] = {'not_measured': f'{type(error).__name__}: {error}'[:300]}
    return out, findings


def _check_devices(synced_devices, source_profile, graded_look, supplied, fresh, items, requirements, brief, script, project, video, grade, kit_result, revision, findings, look_measured, video_hash, devices, camera_refs=()):
    """Check each declared device against its receipt and current timeline evidence."""
    for name in (DEVICES + synced_devices + (('shot_sources', 'stickers') if source_profile else ())
                 + (('grade',) if graded_look else ()) + (('camera',) if camera_refs else ())):
        entry = supplied.get(name, {})
        status = entry.get('status')
        reason = str(entry.get('reason', '')).strip()
        ids = entry.get('items', [])
        problems = []           # the receipt: what a measured Look's devices need written down
        timeline = []           # what the timeline itself shows behind a placed device, for any Look
        if not fresh:
            problems.append('receipt predates the current edit or Look: call letitedit_look_check with decisions again '
                            'after the last picture change (the last ones are in this receipt: decisions)')
        inventory_unassessed = (name == 'stickers' and source_profile is not None
                                and not any(event['kind'] in ('sticker', 'pip') and event['status'] == 'reviewed'
                                            for source in source_profile['references'] for event in source['overlays'])
                                and any(source['overlay_coverage'][kind] != 'complete'
                                        for source in source_profile['references'] for kind in ('sticker', 'pip')))
        measured_absence = (name == 'stickers' and source_profile is not None
                            and all(source['overlay_coverage'][kind] == 'complete'
                                    for source in source_profile['references'] for kind in ('sticker', 'pip'))
                            and not any(event['kind'] in ('sticker', 'pip') for source in source_profile['references']
                                        for event in source['overlays'])
                            and entry.get('evidence', {}).get('kind') == 'measured_absence')
        if (inventory_unassessed and status == 'declined'
                and (entry.get('evidence') or {}).get('kind') in ('unmeasured', 'unassessed', None)):
            status = 'unassessed'    # the Look's sticker inventory is incomplete: "not measured" is the honest receipt
        if (status not in ('placed', 'declined') and not (status == 'unassessed' and inventory_unassessed)) or not reason:
            problems.append('needs placed or declined with an evidence-based reason, including absent measurements')
        if name == 'shot_sources':
            import letitedit.looks.style_import_sources as style_import_sources
            declared = entry.get('sources')
            if isinstance(declared, list) and all(isinstance(row, dict) and row.get('id') for row in declared):
                entry = {**entry, 'sources': {row['id']: {k: v for k, v in row.items() if k != 'id'} for row in declared}}
            if not ids and isinstance(entry.get('sources'), dict):
                ids = list(entry['sources'])
            problems.extend(style_import_sources.check(source_profile, entry, script, brief, supplied))
            if status != 'placed':
                problems.append('base-picture provenance cannot be declined')
        if name == 'stickers' and status == 'declined' and inventory_unassessed:
            problems.append('the sticker inventory of this Look is incomplete, so it is unassessed, not a measured absence: '
                            'write {"status": "unassessed", "reason": "..."}')
        if name == 'stickers' and status == 'unassessed' and not inventory_unassessed:
            problems.append('unassessed is for a Look whose sticker inventory is incomplete; this one is complete: '
                            'place its stickers, or decline them with evidence')
        if status == 'placed' and (not ids or any(identity not in items for identity in ids)):
            problems.append('placed device needs current timeline item IDs')
        if name == 'broll' and status == 'declined' and broll_measured_none(requirements):
            measured_absence = True     # the Look measured its references and found no cutaways: nothing to place
        if status == 'declined' and not measured_absence:
            problem = decline_problem(name, entry, requirements, brief, supplied)
            if problem:
                problems.append(problem)
        entry = _check_broll(name, status, entry, ids, script, requirements, video, problems, timeline, project)

        if name == 'transitions' and status == 'placed' and re.search(r'negative|inver', json.dumps(requirements), re.I):
            import letitedit.looks.cut_flashes as cut_flashes
            lacking = cut_flashes.missing(script)
            if lacking:
                timeline.append(f"{len(lacking)} cutaway edge(s) that are cuts with the speaker carry no inverted flash "
                                "(fx cut_flashes places them): " + ', '.join(f"{m['id']} {m['edge']} {m['at']:g}s" for m in lacking[:8]))
        if name == 'grade' and status != 'placed' and problems:
            problems.append("the grade is the Look's colour, for every clip of footage with or without a face: "
                            "{op: fx, grade: true} puts it on")
            ungraded = grade.ungraded_footage(script)
            if ungraded:
                timeline.append(f"the Look's grade is not on {len(ungraded)} clip(s) of footage ({', '.join(ungraded[:8])})")
        if name == 'grade' and status == 'placed':
            ungraded = grade.ungraded_footage(script)
            if ungraded:
                timeline.append("the Look's grade covers every clip of footage: "
                                f"{len(ungraded)} clip(s) have none ({', '.join(ungraded[:8])})")
        if name == 'camera':
            entry = _check_camera(entry, camera_refs, video, script, timeline, problems, footage_folders(brief))
            pace_found = entry.pop('pace_problems', None)
            if pace_found:
                findings.append({'severity': 'major', 'kind': 'picture', 'device': 'pace',
                                 'problem': 'Look pace: ' + '; '.join(pace_found)})
        if name == 'sound' and video and status != 'declined' and 'sound.json' in requirements:
            entry = _check_sound_opening(entry, requirements['sound.json'], video, timeline, script)
        if name == 'lighting' and status == 'placed':
            import letitedit.looks.lighting as lighting
            unlit = lighting.uncovered_speaker_clips(script)
            if unlit:
                timeline.append('lighting covers every speaker clip, and one test clip is not the delivery: '
                                f"{len(unlit)} main-track clip(s) have none ({', '.join(unlit[:8])})")
        entry = _check_caption_contrast(name, status, kit_result, project, entry, revision, findings, look_measured, timeline, problems, requirements, script, video, video_hash)

        if video and status == 'placed':
            evidence = entry.get('export') if isinstance(entry.get('export'), dict) else {}
            observed = bool(str(evidence.get('observation', '')).strip())
            own = measured_here(name, entry, video_hash)
            if observed and evidence.get('sha256') == video_hash:
                pass
            elif observed and evidence.get('items_sha256') and evidence['items_sha256'] == items_digest(items, ids):
                # observed on another render of the same items (the reviewed preview of this final): it stands
                entry = {**entry, 'export_carried': {'from_sha256': evidence.get('sha256'),
                                                     'why': 'the items that draw it are unchanged since that export'}}
            elif own:
                entry = {**entry, 'export': {'sha256': video_hash, 'observation': own, 'by': 'look_check'}}
            else:
                problems.append('this export needs a device observation tied to its bytes')
        receipt_rows = problems if look_measured else []
        devices.append({'device': name, **entry, 'problems': receipt_rows + timeline,
                        'picture_problems': timeline, 'receipt_problems': receipt_rows})
        if timeline:
            findings.append({'severity': 'major', 'kind': 'picture', 'device': name,
                             'problem': f'Look {name}: ' + '; '.join(timeline)})
        if receipt_rows:
            findings.append({'severity': 'receipt', 'kind': 'receipt', 'device': name,
                             'problem': f'Look {name} receipt: ' + '; '.join(receipt_rows)})


def check(project, look=None, decisions=None, video=None):
    import letitedit.timeline.edit_script as edit_script
    import letitedit.looks.looks as looks
    project, _, script = current_project(project)
    stored = receipt_path(project)
    previous = json.loads(stored.read_text(encoding='utf-8-sig')) if stored.exists() else {}
    import letitedit.looks.look_inputs as look_inputs
    import letitedit.review.brief_check as brief_check
    brief = brief_check.load(project=project) or {}
    chosen = look_inputs.read(project) or {}
    look = look or chosen.get('look') or brief.get('look') or previous.get('look')
    if not look or str(look).strip().lower() in ('none', 'auto', 'freestyle'):
        # Freestyle and no Look have no recipe to check against
        return {'applicable': False, 'reason': 'No Look selected', 'findings': [], 'passed': True}
    card = looks.read(look)
    recipe = Path(card['recipe'])
    sources = [recipe] + [recipe.with_name(name) for name in ('visual.json', 'lighting.json', 'grade.json', 'sound.json',
                                                              'sources.json', 'graphic-kit.json')
                          if recipe.with_name(name).exists()]
    source_hashes = {path.name: digest(path) for path in sources}
    requirements = {path.name: path.read_text(encoding='utf-8-sig') for path in sources}
    # a Look with measurements keeps a receipt per device; a library Look's recipe is written guidance, so it has
    # none to keep, and only what the timeline itself shows is checked
    look_measured = any(path.name in MEASUREMENTS for path in sources)
    inventory = device_units(source_units({name: text for name, text in requirements.items()
                                           if name != 'graphic-kit.json'})) if look_measured else {}
    kit_result = None
    if 'graphic-kit.json' in requirements:
        import letitedit.looks.graphic_kit as graphic_kit
        try:
            kit_result = graphic_kit.check(recipe.with_name('graphic-kit.json'), project, video)
        except Exception as error:
            kit_result = {'passed': False, 'findings': [{'problem': f'Kit evidence unavailable: {error}'}]}
    revision = project_digest(script)
    video_hash = digest(video) if video else None
    items = {item['id']: item for track in script['tracks'] for item in track['items'] if 'id' in item}
    supplied = decisions if decisions is not None else previous.get('decisions', {})
    if decisions is not None and video:
        supplied = stamp_exports(supplied, video_hash, revision, items)
    fresh = decisions is not None or (previous.get('project_sha256') == revision
                                      and previous.get('sources') == source_hashes)
    devices = []
    findings = []
    if kit_result is not None:
        findings.extend({'severity': 'receipt' if str(finding.get('problem', '')).startswith(KIT_NOT_MEASURED) else 'major',
                         'kind': 'note' if str(finding.get('problem', '')).startswith(KIT_NOT_MEASURED) else 'picture',
                         'device': 'graphic_kit', **finding}
                        for finding in kit_result['findings'])
        findings.extend(kit_facts(kit_result, brief))
    findings.extend(format_findings(recipe, project))
    accounted = supplied.get('_sources', {})
    for key in inventory:
        entry = accounted.get(key, {})
        if (not fresh or entry.get('status') not in ('placed', 'declined') or not str(entry.get('reason', '')).strip()
                or (entry.get('status') == 'placed' and (not entry.get('items')
                    or any(identity not in items for identity in entry['items'])))):
            findings.append({'severity': 'receipt', 'kind': 'receipt', 'device': key,
                             'problem': f'Look source unit {key}: account for every measured device with placed/declined, reason and current placed item IDs'})
        elif entry.get('status') == 'declined':
            problem = decline_problem(key, entry, {key: inventory[key]}, brief, supplied)
            if problem:
                findings.append({'severity': 'receipt', 'kind': 'receipt', 'device': key,
                                 'problem': f'Look source unit {key}: {problem}'})
    source_profile = json.loads(requirements['sources.json']) if 'sources.json' in requirements else None
    synced = {}
    if 'sound.json' in requirements:
        synced = json.loads(requirements['sound.json']).get('synced') or {}
    synced_devices = tuple(name for name, key in (('shutter_clicks', 'transition_click'), ('key_clicks', 'word_click'))
                           if isinstance(synced.get(key), dict) and synced[key].get('use') is not False)
    # the Look's colour: its grade.json, or one worked out from the lighting.json of a Look saved before grades
    import letitedit.looks.grade as grade
    graded_look = look_measured and bool(grade.look_grade(look=look))
    # the Look's camera language: the mix of moving and static shots and of shot sizes measured on its references
    camera_refs = camera_references(requirements) if look_measured else []
    _check_devices(synced_devices, source_profile, graded_look, supplied, fresh, items, requirements, brief, script, project, video, grade, kit_result, revision, findings, look_measured, video_hash, devices, camera_refs)
    whole = {}
    if look_measured and video:
        whole, found = whole_video(recipe, look, video, script, graded_look, reference_shots(requirements),
                                   reference_mix(requirements))
        findings.extend(found)
    pace_targets = None
    if camera_refs:
        import letitedit.looks.pace as pace
        try:
            pace_targets = pace.targets(camera_refs)
        except Exception:  # noqa: BLE001 - the targets are advice; the check stands without them
            pace_targets = None

    slots = None
    try:
        import letitedit.looks.cutaway_slots as cutaway_slots
        slots = cutaway_slots.plan(script, look)
        findings.extend({'severity': 'major', 'kind': 'picture', 'device': 'broll', 'problem': text}
                        for text in slots.get('findings', []))
    except Exception as error:  # noqa: BLE001 - the slot report is advice; the receipt stands without it
        slots = {'error': str(error)}
    forms = None
    if look_measured:
        forms = {'declined': 'evidence kind tool_refusal, person_rule, unmeasured (only when the Look has no '
                             'measurement of the device) or left_out: ' + LEFT_OUT_FORMS,
                 'captions': "contrast may be left out: the caption tools' own measurement of this edit, kept beside "
                             'the project, is read here',
                 'broll': 'relevance: {id: "the line and what the shot shows"}, or feelings: {id: {feeling, why}}'}
        if camera_refs:
            forms['camera'] = ('placed with items: the footage clips chosen for the camera language; with video, the '
                               'export is measured against the reference mix whatever the receipt says')
        if source_profile:
            import letitedit.looks.style_import_sources as style_import_sources
            forms['shot_sources'] = ('sources: {id: {role: base|overlay, kind, evidence}} or a list of {id, role, kind, '
                                     'evidence}; base kinds this Look permits: '
                                     + ', '.join(style_import_sources.permitted_labels(source_profile))
                                     + '; overlay events with no decision of their own are covered by their device '
                                       '(captions, sound effects, stickers)')
            incomplete = any(source['overlay_coverage'][kind] != 'complete'
                             for source in source_profile['references'] for kind in ('sticker', 'pip'))
            forms['stickers'] = ('{"status": "unassessed", "reason": "..."}: this Look’s '
                                 'sticker inventory is incomplete' if incomplete else
                                 'placed, or declined with evidence {"kind": "measured_absence"} when the Look has none')
    result = {'applicable': True, 'look': look, 'measured': look_measured, 'receipt_forms': forms,
              'receipts': ('needed: every device and every source unit, placed or declined' if look_measured else
                           'not needed: this Look has no measurements beside its recipe (a library Look), so its recipe '
                           'is written guidance; decisions are optional, and a device placed is still checked on the timeline'),
              'graphic_kit': kit_result, 'cutaway_slots': slots, 'sources': source_hashes,
              **({'pace_targets': pace_targets} if pace_targets else {}), **whole,
              'project_sha256': revision, 'decisions': supplied, 'devices': devices,
              'findings': findings,
              # faults in the video (picture, sound, the Look's measured devices on the timeline) decide passing; the
              # receipt rows are the record of the AI's decisions, kept apart so they never read as a fault in the video
              'passed': not any(finding.get('severity') in ('critical', 'major') for finding in findings),
              'receipt_complete': not any(finding.get('kind') == 'receipt' for finding in findings),
              'source_files': [str(path) for path in sources], 'requirements': requirements, 'source_units': inventory,
              'verification': 'Kit families use native rendered every-frame ink/face measurements when present. Other device observations and relevance are reviewer declarations; identity receipts alone are not vision verdicts.'}
    if decisions is not None:
        temporary = stored.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2), encoding='utf-8')
        temporary.replace(stored)
    return result
