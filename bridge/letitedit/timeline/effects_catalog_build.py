"""The index built and its categories.

Part of `effects_catalog` (letitedit/timeline/effects_catalog.py), which imports every name here back,
so `effects_catalog.X` is the same object it always was.
"""
from __future__ import annotations
import json
import os
import re
import time
import uuid
from letitedit.timeline.effects_catalog_yaml import (  # noqa: E402
    CACHE, CATALOG_VERSION, FILTERS_QML, INDEX_FILE
)
from letitedit.timeline.effects_catalog_qml import (  # noqa: E402
    _UNK, _parse_meta, _ui_analysis
)
from letitedit.timeline.effects_catalog_services import (  # noqa: E402
    _PLUMBING, _is_avfilter, _keep, _load_services, _services_stamp, _stamp
)
_TIMING = re.compile(r'^avfilter\.(setpts|asetpts|fps|framerate|reverse|areverse|trim|atrim|loop|aloop|tpad|apad|'
                     r'select|aselect|atempo|asetrate|tinterlace|interlace|telecine|decimate|mpdecimate|framestep|'
                     r'minterpolate|asetnsamples|aresample|freezeframes|fieldmatch|pullup|detelecine|separatefields|'
                     r'weave|doubleweave|field|rubberband|adelay|tmedian|shuffleframes|random)$')
_ANALYSIS = re.compile(r'((?<!edge)detect|^avfilter\.(ebur128|showinfo|ashowinfo|metadata|ametadata|sidedata|asidedata|'
                       r'bbox|entropy|siti|signalstats|idet|vfrdet|scdet|astats|stats|aphasemeter|volumedetect|'
                       r'replaygain|drmeter|graphmonitor|agraphmonitor|bitplanenoise|qp|vif|identity|corr|psnr|'
                       r'ssim|msad|xpsnr|blockdetect|blurdetect)$|^(loudness_meter|audiolevel|fft)$)')
_GPU_ALT = {'movit_diffusion': 'Diffusion exists only on the GPU (Movit) path; use glow or blur_gaussian instead.'}
_NOTES = {
    'stabilize': 'analysis pass: vidstab must analyse the clip first (Shotcut: Analyze) and keep the results; '
                 'until then nothing is stabilised.',
    'bigsh0t_stabilize_360': 'analysis pass: analyses the clip into a file first (Shotcut: Analyze).',
    'tracker': 'analysis pass: OpenCV tracks the rectangle through the clip first (Shotcut: Analyze); other filters '
               '(blur, mask, size & position) then follow its results.',
    'audio_normalize_2p': 'analysis pass: measures the loudness first (Shotcut: Analyze; results); without that it does '
                          'nothing. audio_normalize_1p works in one pass.',
    'lut3d': 'a file: av.file = path to a .cube/.3dl/.dat/.m3d LUT.',
    'mask_shape': 'a file + several filters: filter.resource = image/video (or a luma wipe) used as the mask; put '
                  'mask_apply after the effects it should limit.',
    'mask_glaxnimate': 'a file + several filters: a Glaxnimate drawing (filter.resource, .rawr) drawn in Shotcut; end '
                       'with mask_apply.',
    'mask_alphaspot': 'several filters: starts a mask (mask_start running frei0r.alphaspot); effects after it are '
                      'limited to the mask once mask_apply follows them.',
    'mask_chromakey': 'several filters: starts a mask from a colour key; effects after it are limited to the mask '
                      'once mask_apply follows them.',
    'mask_apply': 'ends a mask begun by an earlier mask_* effect in the same list.',
    'gpstext': 'a file: a GPS track (.gpx/.tcx) synced to the clip.',
    'gpsgraphic': 'a file: a GPS track (.gpx/.tcx) synced to the clip.',
    'subtitle': 'needs subtitles in the project (feed).',
    'reframe': 'reframes the whole project output (e.g. 16:9 -> 9:16); not a clip effect.',
    'time_remap': 'changes timing: map = source time (seconds) keyframed over the clip; prefer the edit script\'s '
                  'own speed controls when they suffice.',
    'speed': 'changes timing: speed_map = speed factor, keyframed.',
    'speed_forward_reverse': 'changes timing: speed_map = speed factor (negative = reverse), keyframed.',
    'audio_fadein': 'the fade is keyframes on level (dB): level: {keys: [[0, -60], [1, 0]]}.',
    'audio_fadeout': 'the fade is keyframes on level (dB) at the clip\'s end: level: {keys: [[T-1, 0], [T, -60]]}.',
    'fadein_brightness': 'the fade is keyframes on level (0..1): level: {keys: [[0, 0], [1, 1]]} (alpha 1 = fade '
                         'from black, 0 = from transparent).',
    'fadeout_brightness': 'the fade is keyframes on level (0..1) at the clip\'s end.',
    'size_position': 'transition.rect = "x y w h [opacity]" in project pixels (or "x%/y%:w%xh%"), keyframable; '
                     'rotation = transition.fix_rotate_x (degrees).',
    'rotate': 'older Rotate and Scale; size_position does the same and more.',
    'dynamictext': 'text in argument (keywords like #timecode# work); geometry = "x y w h" box; size = font size '
                   'in pixels.',
    'typewriter': 'text in argument; geometry = "x y w h" box; size = font pixels.',
    'richtext': 'HTML in html; geometry = "x y w h" box.',
    'timer': 'draws a running timer; geometry = "x y w h" box.',
    'openfx.wtf.vala^NtscRs': 'not available: this melt has no OpenFX plugins loaded.',
    'vst2.1934451059': 'not available: the Valhalla Supermassive VST2 plugin is not installed.',
}


def _keywords(text):
    if not isinstance(text, str):
        return []
    words = []
    for w in re.split(r'[\s,]+', text.lower()):
        w = w.strip('#:;()"\'')
        if w and w not in ('yuv', 'rgba', 'rgb', '10bit', 'gpu') and w not in words:
            words.append(w)
    return words


def _kind_of_service(sid, meta):
    tags = [t.lower() for t in (meta or {}).get('tags') or []]
    if sid.startswith(('ladspa.', 'sox', 'lv2.', 'vst2.')):
        return 'audio'
    if 'audio' in tags and 'video' not in tags:
        return 'audio'
    return 'video'


def _first_sentence(s, limit=140):
    if not s:
        return ''
    s = s.strip()
    m = re.match(r'(.+?[.!?])(\s|$)', s)
    s = (m.group(1) if m else s).rstrip('.')
    return s if len(s) <= limit else s[:limit - 1].rstrip() + '...'


def _norm_range(lo, hi):
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and not isinstance(lo, bool) and lo > hi:
        return hi, lo
    return lo, hi


def _sub_meta(service, prop, defaults, services):
    """MLT metadata of one property, following affine's transition.* and mask_start's filter.* indirection."""
    meta = services.get(service) or {}
    if prop.startswith('transition.') and service == 'affine':
        meta, prop = services.get('@transition.affine') or {}, prop[len('transition.'):]
    elif prop.startswith('filter.') and service == 'mask_start':
        meta, prop = services.get(str(defaults.get('filter') or '')) or {}, prop[len('filter.'):]
    for p in meta.get('params') or []:
        if p['name'] == prop:
            return p
    return None


_INTERNAL = re.compile(r'^(shotcut[:_]|_|\.|mlt_|disable$|in$|out$|results$|analyze|version$|threads$|filter$|'
                       r'filter\.threads$|ui\.|'
                       r'background$|transition\.threads$|transition\.(fix_shear|fix_rotate_y|geometry$)|.*\[)')


_ENGINE_SKIP = {'position', 'av.threads', 'threads', 'argument', 'producer', 'resource'}


def _letitedit_entries(services, available):
    entries = []
    for folder in sorted(p for p in FILTERS_QML.iterdir() if p.is_dir()):
        if folder.name.startswith('ai_'):
            continue
        metas = []
        for path in sorted(folder.glob('meta*.qml')):
            try:
                m = _parse_meta(path)
            except Exception:  # noqa: BLE001 - a broken meta file is skipped, not fatal
                continue
            svc = m.get('mlt_service')
            if not isinstance(svc, str) or svc.startswith('movit.') or m.get('needsGPU') is True \
                    or path.stem == 'meta_movit':
                continue
            metas.append((path, m))
        if not metas:
            continue
        primary = next((i for i, pm in enumerate(metas) if _visible(pm[1])), 0)
        for i, (path, m) in enumerate(metas):
            if i == primary or len(metas) == 1:
                name = folder.name
            else:
                suffix = path.stem[len('meta_'):] if path.stem.startswith('meta_') else \
                    m['mlt_service'].split('.')[-1]
                name = f'{folder.name}_{re.sub(r"[^a-z0-9]+", "_", suffix.lower()).strip("_")}'
            entries.append(_letitedit_entry(folder, name, path, m, services, available))
    # visible first, so Shotcut-name lookups and edit_effects' service->name map prefer them
    entries.sort(key=lambda e: (e['hidden'], not e['available'], e['name']))
    return entries


def _visible(meta):
    return meta.get('isHidden') is not True


def _letitedit_entry(folder, name, path, m, services, available):
    svc = m['mlt_service']
    link = m.get('type') == 'Link'
    smeta = services.get(svc) or {}
    try:
        sets, touched = _ui_analysis(folder, m.get('qml') if isinstance(m.get('qml'), str) else None)
    except Exception:  # noqa: BLE001 - leave defaults out rather than fail the index
        sets, touched = {}, []
    defaults = {k: v for k, v in sets.items() if isinstance(v, (int, float, str)) and not k.startswith('_')}
    params, seen = [], set()

    def add(prop, kp=None):
        if not isinstance(prop, str) or not prop or prop in seen:
            return
        if (kp is None and _INTERNAL.match(prop)) or prop.startswith(('shotcut:', '_shotcut')):
            return
        seen.add(prop)
        mp = _sub_meta(svc, prop, defaults, services) or {}
        kp = kp or {}
        lo, hi = kp.get('minimum'), kp.get('maximum')
        lo, hi = _norm_range(mp.get('min') if lo is None or lo is _UNK else lo,
                             mp.get('max') if hi is None or hi is _UNK else hi)
        typ = 'color' if kp.get('isColor') else 'rect' if kp.get('isRectangle') else mp.get('type')
        if typ in (None, 'string') and _isnum(lo) and _isnum(hi) and kp:
            typ = 'float'       # a Shotcut slider over an expression-capable FFmpeg option
        dflt = defaults.get(prop, mp.get('default'))
        if typ is None:
            typ = 'string' if isinstance(dflt, str) else 'float'
        notes = []
        kmin, kmax = kp.get('minimum'), kp.get('maximum')
        if _isnum(kmin) and _isnum(kmax) and kmin > kmax:
            notes.append(f"Shotcut's slider shows it reversed (its 100% = {_fmt_num(kmax)})")
        ganged = kp.get('gangedProperties')
        if isinstance(ganged, list) and ganged:
            notes.append(f'Shotcut sets {", ".join(map(str, ganged))} to the same value')
        if isinstance(kp.get('units'), str) and kp['units'].strip():
            notes.append(f'units: {kp["units"].strip()}')
        if mp.get('description'):
            notes.append(mp['description'])
        desc = '; '.join(notes) or None
        item = {'name': prop, 'title': kp.get('name') if isinstance(kp.get('name'), str) else mp.get('title'),
                'type': typ, 'min': lo if lo is not _UNK else None, 'max': hi if hi is not _UNK else None,
                'default': dflt if isinstance(dflt, (int, float, str)) else None,
                'keyframes': True if kp else bool(mp.get('keyframes')), 'description': desc,
                'values': mp.get('values')}
        params.append({k: v for k, v in item.items() if k == 'keyframes' or _keep(v)})

    for kp in m.get('parameters') or []:
        if isinstance(kp, dict):
            add(kp.get('property'), kp)
    for prop in list(defaults) + touched:
        add(prop)
    # the engine's other properties work too (e.g. vignette's x/y): listed after Shotcut's own, marked engine
    if svc not in ('mask_start', 'affine'):
        shown = len(params)
        for mp in smeta.get('params') or []:
            if mp['name'] not in seen and mp['name'] not in _ENGINE_SKIP and not _INTERNAL.match(mp['name']):
                add(mp['name'])
        for p in params[shown:]:
            p['engine'] = True
    # keyframable parameters Shotcut didn't set get the engine default, so the compiler always has a value
    for p in params:
        if p['keyframes'] and not p.get('engine') and p['name'] not in defaults \
                and isinstance(p.get('default'), (int, float)) and not isinstance(p.get('default'), bool):
            defaults[p['name']] = p['default']
    title = m.get('name') if isinstance(m.get('name'), str) else name
    kw = m.get('keywords') if isinstance(m.get('keywords'), str) else ''
    hint = kw.split(' #')[0]
    flags = [f for f in ('isClipOnly', 'isTrackOnly', 'isOutputOnly') if m.get(f) is True]
    needs = []
    if name in _NOTES or folder.name in _NOTES:
        needs.append(_NOTES.get(name) or _NOTES[folder.name])
    if link:
        needs.append('a link: it goes in the clip\'s chain, not its filter list (the compiler handles that).')
    if 'isTrackOnly' in flags:
        needs.append('track-only in Shotcut: meant for a whole track, not a single clip.')
    if 'isOutputOnly' in flags and folder.name not in ('reframe',):
        needs.append('output-only in Shotcut: meant for the whole project output.')
    if 'isClipOnly' in flags and folder.name.startswith('blend_mode'):
        needs.append('blends with the tracks below.')
    avail = svc in available
    if not avail and not any(s.startswith('not available') for s in needs):
        needs.append(f'not available: this melt has no {svc} service.')
    if m.get('isHidden') is True:
        needs.append('hidden in Shotcut\'s menu (an older variant); it still renders.')
    svc_desc = _first_sentence(smeta.get('description'))
    if svc_desc.lower().startswith(('ladspa plugin', 'process audio using a sox')):
        svc_desc = ''
    description = '; '.join(x for x in (hint.strip(), svc_desc) if x) or title
    return {'name': name, 'title': title, 'kind': 'audio' if m.get('isAudio') is True else 'video',
            'service': svc, 'shotcut_id': m.get('objectName') if isinstance(m.get('objectName'), str) and
            m.get('objectName') else None, 'source': 'shotcut', 'keywords': _keywords(kw),
            'description': description, 'params': params, 'needs': ' '.join(needs) or None, 'link': link,
            'defaults': defaults, 'hidden': m.get('isHidden') is True, 'available': avail,
            'meta_file': f'{folder.name}/{path.name}', 'flags': flags}


def _raw_entries(services_data, taken):
    filters, links = services_data['filters'], services_data['links']
    meta_all = services_data['meta']
    out = []
    for sid in filters + [x for x in links if x not in filters]:
        if sid in taken or sid.startswith('movit.') or sid in _PLUMBING or _HARDWARE.search(sid):
            continue
        meta = meta_all.get(sid) or {}
        source = 'ffmpeg' if _is_avfilter(sid) else 'mlt'
        title = meta.get('title') or sid
        desc = meta.get('description') or ''
        if sid.startswith('ladspa.'):
            desc = f'LADSPA audio plugin: {title}'
        elif sid.startswith('sox.'):
            desc = f'SoX "{sid[4:]}" audio effect; the whole SoX argument list goes in effect'
        elif _is_avfilter(sid):
            title = f'{sid[9:]} (FFmpeg)'
        needs = []
        if _TIMING.match(sid):
            needs.append('changes timing or frame count; MLT filters must keep one frame in, one out, so it may '
                         'not act as in ffmpeg.')
        if _ANALYSIS.search(sid):
            needs.append('analysis only: it measures and changes nothing you can see or hear.')
        if sid in ('vidstab', 'deshake', 'opencv.tracker'):
            needs.append('analysis pass first (see the Shotcut filters stabilize / tracker).')
        link = sid in links and sid not in filters
        if link:
            needs.append('a link: it goes in the clip\'s chain, not its filter list (the compiler handles that).')
        out.append({'name': sid, 'title': title, 'kind': _kind_of_service(sid, meta), 'service': sid,
                    'shotcut_id': None, 'source': source, 'keywords': [], 'description': _first_sentence(desc, 200),
                    'params': [dict(p, keyframes=False) if p['name'] in ('av.threads', 'position') else p
                               for p in meta.get('params') or []],
                    'needs': ' '.join(needs) or None, 'link': link,
                    'defaults': {}, 'hidden': False, 'available': True, 'flags': []})
    return out


# ------------------------------------------------------------------------------- categories

_CAT_OVERRIDES = {
    'opacity': 'colour & light', 'fadein_brightness': 'colour & light', 'fadeout_brightness': 'colour & light',
    'video_autofade': 'colour & light', 'invert': 'colour & light', 'sepia': 'colour & light',
    'threshold': 'stylize', 'posterize': 'stylize', 'gradientmap': 'colour & light', 'chromahold': 'colour & light',
    'pillar_echo': 'blur & sharpen', 'spot_remover': 'blur & sharpen', 'deband': 'blur & sharpen',
    'dither': 'stylize', 'noise_fast': 'stylize', 'noise_keyframes': 'stylize', 'nosync': 'distort & transform',
    'shake': 'time & motion', 'trails': 'time & motion', 'nervous': 'time & motion', 'choppy': 'time & motion',
    'strobe': 'time & motion', 'tracker': 'time & motion', 'stabilize': 'time & motion', 'speed': 'time & motion',
    'speed_forward_reverse': 'time & motion', 'time_remap': 'time & motion', 'bigsh0t_stabilize_360': 'time & motion',
    'alpha_adjust': 'keying & masks', 'alpha_view': 'keying & masks', 'unpremultiply': 'keying & masks',
    'blend_mode': 'keying & masks', 'blend_mode_qtblend': 'keying & masks', 'mask': 'keying & masks',
    'crop': 'distort & transform', 'crop_circle': 'distort & transform', 'crop_rectangle': 'distort & transform',
    'reframe': 'distort & transform', 'rotate': 'distort & transform', 'size_position': 'distort & transform',
    'dropshadow': 'stylize', 'outline': 'stylize', 'gradient': 'stylize', 'grid': 'stylize', 'glow': 'stylize',
    'vignette': 'stylize', 'oldfilm': 'stylize', 'lines': 'stylize', 'dust': 'stylize', 'grain': 'stylize',
    'tcolor': 'stylize', 'halftone': 'stylize', 'mosaic': 'stylize', 'glitch': 'stylize', 'sketch': 'stylize',
    'scanlines': 'stylize', 'rgbsplit0r': 'stylize', 'openfx.wtf.vala^NtscRs': 'stylize', 'lightshow': 'other',
    'dance': 'other', 'spectrum': 'other', 'waveform': 'other', 'audiolevelgraph': 'other', 'timer': 'other',
    'dynamictext': 'other', 'richtext': 'other', 'typewriter': 'other', 'subtitle': 'other', 'gpstext': 'other',
    'gpsgraphic': 'other', 'hqdn3d': 'blur & sharpen', 'fspp': 'blur & sharpen', 'vaguedenoiser': 'blur & sharpen',
    'smartblur': 'blur & sharpen', 'levels': 'colour & light', 'white': 'colour & light', 'lut3d': 'colour & light',
    'color': 'colour & light', 'color_frei0r_coloradj': 'colour & light', 'contrast': 'colour & light',
    'brightness': 'colour & light', 'saturation': 'colour & light', 'vibrance': 'colour & light',
    'hslprimaries': 'colour & light', 'hslrange': 'colour & light', 'hue_lightness_saturation': 'colour & light',
    'keyspillm0pup': 'keying & masks', 'spillsuppress': 'keying & masks', 'bluescreen0r': 'keying & masks',
    'select0r': 'keying & masks', 'flip': 'distort & transform', 'mirror': 'distort & transform',
    'reflect': 'distort & transform', 'corners': 'distort & transform', 'audio_autofade': 'audio levels & dynamics',
    'audio_seam': 'audio cleanup', 'audio_invert': 'audio space/effects', 'audio_mute': 'audio levels & dynamics',
    'audio_balance': 'audio space/effects', 'audio_pan': 'audio space/effects', 'audio_mono': 'audio space/effects',
    'audio_channelcopy': 'audio space/effects', 'audio_swapchannels': 'audio space/effects',
    'audio_matrix_ms': 'audio space/effects', 'audio_basstreble': 'audio EQ & filters',
    'audio_eq3band': 'audio EQ & filters', 'audio_eqparametric': 'audio EQ & filters',
    'audio_eq15band': 'audio EQ & filters', 'audio_noisegate': 'audio cleanup', 'audio_expander': 'audio levels & dynamics',
    'ambisonic_decoder': 'audio space/effects', 'ambisonic_encoder': 'audio space/effects',
    'vst2.1934451059': 'audio space/effects', 'avfilter.afftdn': 'audio cleanup', 'avfilter.adeclip': 'audio cleanup',
    'cairoblend_mode': 'keying & masks', 'qtblend_mode': 'keying & masks', 'timeremap': 'time & motion',
    'frei0r.gateweave': 'stylize', 'avfilter.eq': 'colour & light', 'avfilter.colorbalance': 'colour & light', 'avfilter.curves': 'colour & light',
}
_HARDWARE = re.compile(r'_(qsv|amf|d3d11|d3d12|cuda|vaapi|vulkan|opencl|npp|videotoolbox|cuvid)$|^avfilter\.(vpp|sr)_')
_VIDEO_RULES = [
    ('other', r'(scope|waveform|audiowave|spectrum|\bhistogram\b|\bgraph|drawgraph|monitor|pr0be|pr0file|measure|'
              r'\btext\b|qtext|watermark|subtitle|timer|deinterlac|yadif|bwdif|w3fdif|\bweave|doubleweave|\bfield|\bil\b|estdif|mcdeint|nnedi|'
              r'kerndeint|telecid|timeout|\bphase\b|sidedata|\bcue\b|realtime|latency|fsync|ccrepack|addroi|find_rect)'),
    ('keying & masks', r'\b(key|keying|chroma ?key|colorkey|chromakey|lumakey|mask|alpha|spill|bluescreen|despill|'
                       r'matte|premultipl|transparen|blend)'),
    ('time & motion', r'\b(speed|time ?remap|stabili|track|deshake|vidstab|shake|trail|tmix|freeze|strobe|choppy|'
                      r'reverse|interpolat|motion|echo|lagfun|frame ?rate|tblend|random|delay|nervous|'
                      r'photosensitiv|flicker|baltan|loop|shuffleframes|tlut2|tmidequalizer)|grab'),
    ('blur & sharpen', r'\b(blur|sharp|denois|noise reduc|reduce noise|unsharp|deband|hqdn3d|fspp|nlmeans|bilateral|'
                       r'median|smooth|soften|deblock|dctdnoiz|atadenoise|owdenoise|cas\b|convolution|pp7|spp|uspp|'
                       r'delogo|obscure|removegrain|denoise)'),
    ('distort & transform', r'\b(size|position|rotat|scale|crop|flip|mirror|reflect|lens|fisheye|distort|wave|warp|'
                            r'perspective|corner|zoom|transform|360|equirect|stereo|elastic|vertigo|pad|transpose|'
                            r'swirl|displace|kaleid|tile|untile|shear|geq|remap|v360|hflip|vflip|defish|c0rners|'
                            r'letterb|border|fillborders|scroll|swaprect|zenith|flippo|squiggl|nosync|broken tv)'),
    ('colour & light', r'\b(colou?r|grad(e|ing)|hue|saturat|bright|contrast|level|curve|white ?bal|lut|sepia|tint|'
                       r'vibran|gamma|exposure|lift|tone|temperat|invert|negat|grey|gray|opacity|fade|eq\b|hsl|'
                       r'chroma|luma|monochrome|balance|normaliz|histeq|colorspace|selectivecolor|black/white|bw0r|'
                       r'luminance|extracts (red|green|blue)|ndvi|pseudocolor|swapuv|shuffleplanes|sigmoid|rgblut|'
                       r'amplify|limiter|equaliz)'),
    ('stylize', r'\b(glow|vignette|grain|film|dust|scratch|lines|glitch|halftone|mosaic|pixel|posteri|sketch|cartoon|'
                r'emboss|edge|outline|shadow|dither|noise|scan|shift|ntsc|vhs|old|threshold|gradient|grid|burn|'
                r'charcoal|art|paint|light|sobel|prewitt|roberts|bloom|cairo|draw|softglow|roxx|videowall|dilat|'
                r'erosion|deflate|inflate|kirsch|scharr|water)'),
]
_AUDIO_RULES = [
    ('audio cleanup', r'\b(noise|denois|declick|declip|hum|rnnoise|afftdn|anlmdn|deess|de-ess|silence|dc ?shift|'
                      r'click|hiss|seam|clean|repair|restor|adenorm|arnndn|afwtdn|deesser|dc offset|dialog)'),
    ('audio levels & dynamics', r'\b(gain|volume|compress|limit|expand|gate|normali|loud|fade|mute|dynamic|agc|level|'
                                r'dynaudnorm|sc[1-4]|se4|amplif|drc|clip|softclip|ducking|sidechain|automatic|'
                                r'compand|mcompand|norm\b|vol\b|contrast|maximi)'),
    ('audio EQ & filters', r'\b(eq|equali|band|pass|notch|bass|treble|shelf|filter|lowpass|highpass|tone|crossover|'
                           r'biquad|allpass|emphasis|riaa|sinc|fir|iir|frequency|lowshelf|highshelf|deemph|'
                           r'asubboost|asubcut|asupercut|atilt|sub ?boost|sub ?cut)'),
    ('audio space/effects', r'(reverb|verb\b|\becho|delay|chorus|flang|phas|pitch|stereo|\bpan\b|panner|balance|'
                            r'channel|mono\b|swap|ambisonic|haas|tremolo|vibrato|distort|crush|width|surround|'
                            r'mid-?side|matrix|invert|speed|tempo|overdrive|exciter|room|hall|spatial|ring mod|'
                            r'modulat|octave|harmon|pulsat|decorrel|satur|valve|diode|shaper|decimat|alias|'
                            r'wavewrap|transient|vinyl|gsm|karaoke|vocoder|earwax|remix|divider|comb)'),
]


def _category(e):
    if e['name'] in _CAT_OVERRIDES:
        return _CAT_OVERRIDES[e['name']]
    if e.get('needs') and 'analysis only' in e['needs']:
        return 'other'
    blob = ' '.join([e['name'].replace('_', ' ').replace('.', ' '), e['title'] or '', ' '.join(e['keywords']),
                     e['description'] or '']).lower()
    rules = _AUDIO_RULES if e['kind'] == 'audio' else _VIDEO_RULES
    name_blob = (e['name'].split('.', 1)[-1] + ' ' + (e['title'] or '')).lower()
    for cat, pat in rules:          # the name/title decide first, the description only if they say nothing
        if re.search(pat, name_blob):
            return cat
    for cat, pat in rules:
        if re.search(pat, blob):
            return cat
    return 'other'


def _build():
    t0 = time.time()
    stamp = _stamp()
    services_data = _load_services(_services_stamp())
    available = set(services_data['filters']) | set(services_data['links'])
    shotcut = _letitedit_entries(services_data['meta'], available)
    taken = {e['name'] for e in shotcut}
    entries = shotcut + _raw_entries(services_data, taken)
    for e in entries:
        e['category'] = _category(e)
    data = {'version': CATALOG_VERSION, 'stamp': stamp, 'built': time.strftime('%Y-%m-%d %H:%M:%S'),
            'build_seconds': round(time.time() - t0, 2), 'entries': entries}
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(f'.{uuid.uuid4().hex[:6]}.tmp')
    tmp.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    os.replace(tmp, INDEX_FILE)
    return data


def _norm_key(s):
    return re.sub(r'[^a-z0-9]+', '', str(s).lower())


def _make_state(data):
    entries = data['entries']
    by_name, by_lname, by_title, by_object, by_norm = {}, {}, {}, {}, {}

    def better(a, b):   # prefer visible, available, clip-capable Shotcut entries for a shared title
        def rank(e):
            return (e['source'] != 'shotcut', e['hidden'], not e['available'],
                    'isTrackOnly' in e.get('flags', []), e['link'])
        return a if b is None or rank(a) < rank(b) else b

    for e in entries:
        by_name[e['name']] = e
        by_lname.setdefault(e['name'].lower(), e)
        if e['source'] == 'shotcut':
            t = (e['title'] or '').lower()
            by_title[t] = better(e, by_title.get(t))
            if e['shotcut_id']:
                by_object.setdefault(e['shotcut_id'], e)
                by_object.setdefault(e['shotcut_id'].lower(), e)
            by_norm[_norm_key(e['title'])] = better(e, by_norm.get(_norm_key(e['title'])))
    for e in entries:
        by_norm.setdefault(_norm_key(e['name']), e)
    return {'entries': entries, 'by_name': by_name, 'by_lname': by_lname, 'by_title': by_title,
            'by_object': by_object, 'by_norm': by_norm, 'stamp': data['stamp'], 'checked': time.time(),
            'built': data.get('built'), 'build_seconds': data.get('build_seconds')}


def _fmt_num(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return f'{v:.6g}'
    return str(v)


def _isnum(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)
