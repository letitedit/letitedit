"""Platform profiles: published specs for YouTube, YouTube Shorts, TikTok, Instagram Reels, Instagram feed video,
Facebook Reels and Facebook feed video, read from C:\\LetItEdit\\platforms\\<id>.json (folder overridable with the
LETITEDIT_PLATFORMS environment variable).

Every value in a profile is a fact object {value, source, checked, status[, note, confidence]}; status is 'official',
'official-ads' (from the platform's own ad specs), 'posting-service' (a posting service's help pages, for posting
through that service), 'unconfirmed' (best non-official source) or 'not documented'.

    list_profiles()                      -> one summary per profile
    load(platform)                       -> the profile dict
    validate(profile)                    -> list of problems (empty when the profile is well-formed)
    preset_for(platform)                 -> export settings (size, fps, codecs, bitrates, loudness) with sources
    safe_zone_overlay(image, platform, out=None, alpha=0.38)
                                         -> path of a PNG with the covered areas drawn over the frame
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
ROOT = Path(os.environ.get('LETITEDIT_PLATFORMS', _paths.CODE_ROOT / 'platforms'))
CACHE = Path(os.environ.get('LETITEDIT_PLATFORMS_CACHE',
                            _paths.CODE_ROOT / 'cache' / 'platforms'))
SCHEMA = 'letitedit-platform/1'
STATUSES = ('official', 'official-ads', 'posting-service', 'unconfirmed', 'not documented')
REQUIRED = ('id', 'name', 'schema', 'checked', 'video', 'audio', 'safe_zones', 'captions', 'thumbnail', 'text_limits',
            'export_preset')
PRESET_FIELDS = ('width', 'height', 'fps', 'container', 'vcodec', 'pix_fmt', 'video_bitrate_kbps', 'acodec',
                 'audio_bitrate_kbps', 'sample_rate_hz', 'loudness_lufs')
ALIASES = {'yt': 'youtube', 'youtube_long': 'youtube', 'youtube_longform': 'youtube', 'shorts': 'youtube_shorts',
           'yt_shorts': 'youtube_shorts', 'tik_tok': 'tiktok', 'ig_reels': 'instagram_reels',
           'reels': 'instagram_reels', 'instagram': 'instagram_reels', 'ig_feed': 'instagram_feed',
           'fb_reels': 'facebook_reels', 'facebook': 'facebook_reels', 'fb_feed': 'facebook_feed'}


def _ids():
    return sorted(p.stem for p in ROOT.glob('*.json'))


def resolve(platform: str) -> str:
    """Profile id for a name ('YouTube Shorts', 'ig-reels', 'tiktok'...). Raises KeyError listing the ids."""
    key = re.sub(r'[^a-z0-9]+', '_', str(platform).strip().lower()).strip('_')
    key = ALIASES.get(key, key)
    if key not in _ids():
        raise KeyError(f'no platform profile {platform!r}; profiles: {", ".join(_ids())}')
    return key


def load(platform: str) -> dict:
    if str(platform).strip().lower() == 'phone':
        # A style's phone safe zone is the union of the three common vertical feeds.
        ids = ('youtube_shorts', 'tiktok', 'instagram_reels')
        profiles = [load(pid) for pid in ids]
        profile = json.loads(json.dumps(profiles[0]))
        profile['id'], profile['name'] = 'phone', 'Phone video'
        profile['checked'] = max(p['checked'] for p in profiles)
        profile['safe_zones']['value'] = [dict(z, name=f"{p['id']}: {z['name']}")
                                          for p in profiles for z in p['safe_zones']['value'] or []]
        return profile
    return json.loads((ROOT / f'{resolve(platform)}.json').read_text(encoding='utf-8-sig'))


def is_fact(node) -> bool:
    return isinstance(node, dict) and 'value' in node and 'source' in node


def iter_facts(node, path=''):
    """(dotted path, fact) for every fact object in a profile."""
    if is_fact(node):
        yield path, node
        return
    if isinstance(node, dict):
        for k, v in node.items():
            yield from iter_facts(v, f'{path}.{k}' if path else k)


def validate(profile: dict) -> list[str]:
    problems = [f'missing field {k}' for k in REQUIRED if k not in profile]
    if profile.get('schema') != SCHEMA:
        problems.append(f'schema is {profile.get("schema")!r}, expected {SCHEMA!r}')
    for k in ('video', 'audio', 'captions', 'text_limits', 'export_preset'):
        node = profile.get(k)
        if k in profile and not isinstance(node, dict):
            problems.append(f'{k} must be an object')
    for k in ('safe_zones', 'thumbnail'):
        if k in profile and not is_fact(profile[k]):
            problems.append(f'{k} must be a fact object')
    # every leaf under the fact sections must be a fact
    for k in ('video', 'audio', 'captions', 'text_limits', 'export_preset'):
        for name, v in (profile.get(k) or {}).items():
            if not is_fact(v):
                problems.append(f'{k}.{name} is not a fact object (value + source)')
    for path, fact in iter_facts(profile):
        src = fact.get('source')
        if not (isinstance(src, str) and src.startswith('https://')):
            problems.append(f'{path}: source is not an https URL')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(fact.get('checked', ''))):
            problems.append(f'{path}: checked date missing')
        if fact.get('status') not in STATUSES:
            problems.append(f'{path}: status {fact.get("status")!r} not one of {STATUSES}')
    zones = (profile.get('safe_zones') or {}).get('value')
    if zones is not None and not isinstance(zones, list):
        problems.append('safe_zones.value must be a list')
    for z in zones or []:
        try:
            x, y, w, h = (float(z[c]) for c in 'xywh')
        except (KeyError, TypeError, ValueError):
            problems.append(f'safe zone {z!r} needs numeric x, y, w, h')
            continue
        if not (0 <= x and 0 <= y and w > 0 and h > 0 and x + w <= 1.0001 and y + h <= 1.0001):
            problems.append(f'safe zone {z.get("name")!r} is outside the frame (fractions 0-1)')
    for k in PRESET_FIELDS:
        if k not in (profile.get('export_preset') or {}):
            problems.append(f'export_preset.{k} missing')
    return problems


def _val(fact):
    return fact.get('value') if is_fact(fact) else None


def summary_line(profile: dict) -> str:
    v, p = profile['video'], profile['export_preset']
    size = f"{_val(p['width'])}x{_val(p['height'])}" if _val(p['width']) else '?'
    mx = _val(v.get('max_length_s', {}))
    length = 'no max' if mx is None else (f'{mx / 60:g} min max' if mx >= 60 else f'{mx:g} s max')
    zones = profile['safe_zones']
    zone_txt = (f"{len(zones['value'])} covered areas ({zones['status']}, confidence {zones.get('confidence')})"
                if zones['value'] else 'no published covered areas')
    return f"{profile['id']}: {profile['name']} - export {size}, {length}; {zone_txt}; checked {profile['checked']}"


def list_profiles() -> list[dict]:
    out = []
    for pid in _ids():
        prof = load(pid)
        out.append({'id': pid, 'name': prof['name'], 'checked': prof['checked'], 'line': summary_line(prof)})
    return out


def preset_for(platform: str) -> dict:
    """Export settings from the profile's export_preset: plain values plus where each came from. Values the platform
    does not publish are None and listed under not_documented; non-official values are listed under unconfirmed.
    Does not touch render_queue."""
    prof = load(platform)
    ep = prof['export_preset']
    out = {'platform': prof['id'], 'name': prof['name'], 'checked': prof['checked']}
    sources, unconfirmed, missing = {}, [], []
    for k, fact in ep.items():
        out[k] = _val(fact)
        sources[k] = {'source': fact['source'], 'status': fact['status'], **({'note': fact['note']}
                                                                           if fact.get('note') else {})}
        if fact['status'] == 'unconfirmed':
            unconfirmed.append(k)
        elif fact['status'] == 'not documented':
            missing.append(k)
    out['size'] = f"{out.get('width')}x{out.get('height')}"
    out['sources'] = sources
    out['unconfirmed'] = unconfirmed
    out['not_documented'] = missing
    return out


def safe_zone_overlay(image_path, platform: str, out=None, alpha: float = 0.38, color=(255, 40, 40)) -> str:
    """Draw the profile's covered areas (fractions of width/height) over a frame and save a PNG. Returns its path.
    out: file path; default <cache>/<frame stem>.<platform>-zones.png. alpha: fill opacity 0-1. The zones are drawn
    at the image's own size; the frame's aspect ratio and the platform's are both written on the image."""
    from PIL import Image, ImageDraw, ImageFont

    prof = load(platform)
    zones = prof['safe_zones']['value'] or []
    src = Path(image_path)
    base = Image.open(src).convert('RGBA')
    W, H = base.size
    layer = Image.new('RGBA', base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fill = (*color, max(0, min(255, int(alpha * 255))))
    edge = (*color, 255)
    lw = max(2, round(min(W, H) / 300))
    try:
        font = ImageFont.truetype('arial.ttf', max(12, H // 45))
    except OSError:
        font = ImageFont.load_default()
    for z in zones:
        x0, y0 = round(z['x'] * W), round(z['y'] * H)
        x1, y1 = round((z['x'] + z['w']) * W) - 1, round((z['y'] + z['h']) * H) - 1
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W - 1, x1), min(H - 1, y1)
        d.rectangle([x0, y0, x1, y1], fill=fill, outline=edge, width=lw)
    img = Image.alpha_composite(base, layer)
    d = ImageDraw.Draw(img)
    def wrap(text, maxw):
        lines, cur = [], ''
        for word in text.split():
            t = f'{cur} {word}'.strip()
            if cur and d.textlength(t, font=font) > maxw:
                lines.append(cur)
                cur = word
            else:
                cur = t
        return '\n'.join(lines + [cur])

    for z in zones:   # labels on top of all fills
        x0, y0 = max(0, round(z['x'] * W)), max(0, round(z['y'] * H))
        zw = round(z['w'] * W) - lw * 4
        label = z['name'] if d.textlength(z['name'], font=font) <= zw else z['name'].split(':')[0]
        tx, ty = min(x0 + lw * 2, W - 10), min(y0 + lw * 2, H - 20)
        d.multiline_text((tx, ty), wrap(label, max(zw, 10)), fill=(255, 255, 255, 255), font=font, stroke_width=2,
                         stroke_fill=(0, 0, 0, 255))
    sz = prof['safe_zones']
    banner = (f"{prof['name']}: {sz['status']}, confidence {sz.get('confidence')}, checked {sz['checked']} | "
              f"frame {W}x{H} ({W / H:.3f}), export {prof['export_preset']['width']['value']}x"
              f"{prof['export_preset']['height']['value']}")
    if not zones:
        banner = f"{prof['name']}: no published covered areas | frame {W}x{H}"
    d.multiline_text((lw * 2, H // 2), wrap(banner, W - lw * 4), fill=(255, 255, 255, 255), font=font,
                     stroke_width=2, stroke_fill=(0, 0, 0, 255))
    if out is None:
        CACHE.mkdir(parents=True, exist_ok=True)
        out = CACHE / f'{src.stem}.{prof["id"]}-zones.png'
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert('RGB').save(out)
    return str(out)
