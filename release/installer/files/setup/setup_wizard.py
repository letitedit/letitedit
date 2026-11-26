r"""letitedit first-run setup: a small window (or --console) in plain words.

    pythonw setup_wizard.py                 the window
    python setup_wizard.py --console        the same questions in the console
    python setup_wizard.py --answers a.json no questions: the answers file is the person's OK (used by tests)
    python setup_wizard.py --gui-selftest   builds every page, prints its text, closes (checks the window works)

Steps: 1) Claude Code / Codex found on this PC -> add letitedit's tools to each one the person ticks;
2) music, sound-effects and output folders (music measured for tempo and beats); 3) this PC's hardware tier, what
runs locally, which local models to download and which model environments (torch, voice, music) to build now
(sizes shown; the rest are downloaded / built when a feature first needs them, unless the person says ask or
never); 4) settings.json is written and the chosen work is done, with a log.
Answers file keys: claude, codex (true/false), music_folder, sfx_folder, output_folder, index_music (true/false),
models (list of model ids), envs (list of environment names), model_downloads ('auto' | 'ask' | 'never').
"""
from __future__ import annotations

import json
import sys
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import letitedit_setup as ss  # noqa: E402

DOWNLOAD_CHOICES = [('auto', 'Download it then (the size is logged)'), ('ask', 'Ask me first (show the size)'),
                    ('never', 'Never download models')]


def run_answers(a, log=print, progress=None):
    """Do what the answers say. Returns a summary dict (also written to setup\\first-run.json)."""
    if ss.BETTER_SPEECH_ENV in (a.get('envs') or []) and ss.BETTER_SPEECH_MODEL not in (a.get('models') or []):
        a = {**a, 'models': [*(a.get('models') or []), ss.BETTER_SPEECH_MODEL]}     # one choice: the environment and its model
    out = {'registered': {}, 'settings': None, 'audio': {}, 'models': {}, 'errors': []}
    for key, fn in (('claude', ss.register_claude), ('codex', ss.register_codex)):
        if a.get(key):
            try:
                r = fn()
                out['registered'][key] = r
                log(f"Added letitedit's tools to {'Claude Code' if key == 'claude' else 'Codex'} "
                    f"({r['config']}; backup {r['backup'] or 'not needed, new file'})"
                    + (f" and its {len(r['skills']['names'])} editing skills ({r['skills']['dir']})."
                       if r.get('skills') else '.'))
            except Exception as ex:  # noqa: BLE001
                out['errors'].append(f'{key}: {ex}')
                log(f'Could not add the tools to {key}: {ex}')
    vals = {k: a.get(k) or None for k in ('music_folder', 'sfx_folder', 'output_folder')}
    vals['model_downloads'] = a.get('model_downloads') or 'auto'
    if vals['output_folder']:
        Path(vals['output_folder']).mkdir(parents=True, exist_ok=True)
    out['settings'] = ss.write_settings(vals)
    log(f"Saved your choices in {out['settings']}.")
    if vals['music_folder'] or vals['sfx_folder']:
        try:
            ss.set_audio_folders(vals['music_folder'], vals['sfx_folder'])
            log('The music and sound-effects folders are set for the tools and the editor.')
        except Exception as ex:  # noqa: BLE001
            out['errors'].append(f'audio folders: {ex}')
            log(f'Could not set the audio folders: {ex}')
    for kind, on in (('music', a.get('index_music', True) and vals['music_folder']),
                     ('sfx', vals['sfx_folder'])):
        if on:
            log(f"Looking through the {'music (tempo and beats)' if kind == 'music' else 'sound effects'}...")
            try:
                r = ss.index_audio(kind, progress)
                out['audio'][kind] = r
                log(f"  {r.get('files', 0)} files" + (f", tempo measured for {r['with_tempo']}" if kind == 'music' else ''))
            except Exception as ex:  # noqa: BLE001
                out['errors'].append(f'{kind} index: {ex}')
                log(f'  could not finish: {ex}')
    if a.get('models'):
        ss.bridge()
        import model_fetch as mf
        p = mf.plan(a['models'])
        log(f"Downloading {', '.join(a['models'])}: {p['download_text']} (free: {p['disk_free_text']})...")
        try:
            r = mf.fetch(a['models'], progress)
            out['models'] = r
            log(f"  done: {', '.join(r['fetched']) or 'nothing new'}; checked by SHA-256.")
        except Exception as ex:  # noqa: BLE001
            out['errors'].append(f'models: {ex}')
            log(f'  not downloaded: {ex}')
    if a.get('envs'):
        ss.bridge()
        import env_build as eb
        out['envs'] = {}
        for name in a['envs']:
            try:
                p = eb.plan(name)
                if p['ready']:
                    log(f'The {name} environment is already here.')
                    continue
                if p['form'] is None:
                    raise eb.BuildError(p['note'])
                log('Building ' + eb.describe(p) + '...')
                r = eb.build(name, p['form'], lambda t: log('  ' + t))
                out['envs'][name] = r
                log(f"  done in {r['seconds']:.0f} s.")
            except Exception as ex:  # noqa: BLE001
                out['errors'].append(f'environment {name}: {ex}')
                log(f'  not built: {ex}')
    try:
        out['speech'] = ss.speech_outcome(a)
        if out['speech']:
            log(out['speech'])
    except Exception as ex:  # noqa: BLE001 - a line of words never fails the setup
        log(f'(Could not check the speech model: {ex})')
    (ss.APP / 'setup' / 'first-run.json').write_text(json.dumps({'answers': a, 'result': out}, indent=1, default=str),
                                                    encoding='utf-8')
    log('Finished.' if not out['errors'] else f"Finished with {len(out['errors'])} problem(s) - see above.")
    return out


def describe_registration(info, key):
    if key == 'claude':
        what = f"one entry named \"letitedit\" in {info['config']}"
    else:
        what = f"a local plugin source and the letitedit plugin (turned on) in {info['config']}"
    state = info.get('registered')
    return (what + (f' (already there: {state})' if state else '') + ', and the editing skills in its skills folder. '
            'A backup copy of the file is kept.')


# ------------------------------------------------------------------ console

def ask(q, default=''):
    r = input(f'{q}' + (f' [{default}]' if default else '') + ': ').strip()
    return r or default


def yes(q, default=False):
    r = ask(q + ' (yes/no)', 'yes' if default else 'no').lower()
    return r in ('y', 'yes')


def console():
    print('letitedit setup\n')
    a = {}
    det = {'claude': ss.detect_claude(), 'codex': ss.detect_codex()}
    for key, info in det.items():
        if info['found']:
            print(f"{info['name']} is on this PC.")
            print('  Adding the tools writes ' + describe_registration(info, key))
            a[key] = yes(f"  Add letitedit's tools to {info['name']}?")
        else:
            print(f"{info['name']} was not found on this PC (you can run this setup again after installing it).")
    print()
    a['music_folder'] = ask('Your music folder (leave empty to skip)')
    a['sfx_folder'] = ask('Your sound-effects folder (leave empty to skip)')
    a['output_folder'] = ask('Where finished videos go', str(ss.home() / 'Videos' / 'letitedit'))
    a['index_music'] = bool(a['music_folder']) and yes('Measure the tempo and beats of your music now?', True)
    print('\nChecking this PC...')
    hw = ss.hardware()
    print('\n'.join('  ' + l for l in hw['lines'][:8]))
    if hw.get('speech_note'):
        print('\n' + hw['speech_note'])
    if hw.get('slow_note'):
        print('\n' + hw['slow_note'])
    models, mf = ss.models_for(hw['tier'])
    models = [s for s in models if s['id'] != ss.BETTER_SPEECH_MODEL]
    print(f"\nLocal models that suit this PC (tier {hw['tier']}):")
    for i, s in enumerate(models, 1):
        print(f"  {i:2}. {s['title']} - {s['size_text']} - {'; '.join(s['features'] or [])}"
              + (' (on this PC)' if s['present'] else ''))
    pick = ask('Numbers to download now, e.g. 1,3 (empty = none; the rest come when a feature needs them)')
    a['models'] = [models[int(x) - 1]['id'] for x in pick.replace(' ', '').split(',') if x.isdigit()
                   and 0 < int(x) <= len(models)]
    envs = ss.envs_for(hw['tier'])
    print(f"\nModel environments (Python + torch etc.) for this PC; each is built when a feature first needs it:")
    for i, p in enumerate(envs, 1):
        print(f"  {i:2}. {p['name']} ({p['form']}) - {p['download_text']} download, about {p['installed_text']} on "
              f"disk - {'; '.join(p['features'])}" + (' (built)' if p['ready'] else ''))
    better = next((i for i, p in enumerate(envs, 1) if p['name'] == ss.BETTER_SPEECH_ENV), None) if hw.get('better_speech') else None
    if better:
        print(f"\nBetter speech model (number {better}): any language, on your graphics card, {ss.better_speech_size()[1]} to download now, with its model. "
              "Without it, speech on this PC understands English only.")
    pick = ask('Numbers to build now, e.g. 1 (none = no)', str(better) if better else '')
    a['envs'] = [envs[int(x) - 1]['name'] for x in pick.replace(' ', '').split(',') if x.isdigit()
                 and 0 < int(x) <= len(envs)]
    print('When a feature first needs a model or environment that is not here: ' +
          ' / '.join(f'{k} = {t}' for k, t in DOWNLOAD_CHOICES))
    a['model_downloads'] = ask('Choose', 'auto')
    print()
    run_answers(a)


# ------------------------------------------------------------------ window

def gui(selftest=False):
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title('letitedit setup')
    root.geometry('760x560')
    root.minsize(640, 480)
    state = {'page': 0}
    det = {'claude': ss.detect_claude(), 'codex': ss.detect_codex()}
    v = {'claude': tk.BooleanVar(value=False), 'codex': tk.BooleanVar(value=False),
         'music_folder': tk.StringVar(), 'sfx_folder': tk.StringVar(),
         'output_folder': tk.StringVar(value=str(ss.home() / 'Videos' / 'letitedit')),
         'index_music': tk.BooleanVar(value=True), 'model_downloads': tk.StringVar(value='auto')}
    s0 = ss.read_settings()
    for k in ('music_folder', 'sfx_folder', 'output_folder', 'model_downloads'):
        if s0.get(k):
            v[k].set(s0[k])
    body = ttk.Frame(root, padding=16)
    body.pack(fill='both', expand=True)
    nav = ttk.Frame(root, padding=(16, 0, 16, 12))
    nav.pack(fill='x')
    back = ttk.Button(nav, text='Back')
    nxt = ttk.Button(nav, text='Next')
    back.pack(side='left')
    nxt.pack(side='right')
    model_vars = {}
    env_vars = {}
    hw_box = {}

    def clear():
        for w in body.winfo_children():
            w.destroy()

    def title(text, sub=None):
        ttk.Label(body, text=text, font=('Segoe UI', 14, 'bold')).pack(anchor='w')
        if sub:
            ttk.Label(body, text=sub, wraplength=700, justify='left').pack(anchor='w', pady=(4, 12))

    def page_apps():
        title('1. Your AI app', 'letitedit works through Claude Code or Codex. Tick the ones that should get '
                                "letitedit's tools. Nothing is signed in and nothing is sent anywhere; only a "
                                'settings file on this PC changes.')
        for key, info in det.items():
            f = ttk.LabelFrame(body, text=info['name'], padding=10)
            f.pack(fill='x', pady=6)
            if info['found']:
                ttk.Checkbutton(f, text=f"Add letitedit's tools to {info['name']}", variable=v[key]).pack(anchor='w')
                ttk.Label(f, text='This writes ' + describe_registration(info, key), wraplength=680,
                          justify='left', foreground='#555').pack(anchor='w', pady=(4, 0))
            else:
                v[key].set(False)
                ttk.Label(f, text=f"Not found on this PC. Install {info['name']} and run this setup again "
                                  '(Start menu: letitedit setup).', wraplength=680).pack(anchor='w')

    def folder_row(label, key, hint):
        f = ttk.Frame(body)
        f.pack(fill='x', pady=6)
        ttk.Label(f, text=label, width=22).pack(side='left')
        ttk.Entry(f, textvariable=v[key]).pack(side='left', fill='x', expand=True, padx=6)
        ttk.Button(f, text='Choose...', command=lambda: v[key].set(
            filedialog.askdirectory(title=label, initialdir=v[key].get() or str(ss.home())) or v[key].get())
        ).pack(side='left')
        ttk.Label(body, text=hint, foreground='#555').pack(anchor='w', padx=(4, 0))

    def page_folders():
        title('2. Your folders', 'letitedit only reads your music and sound effects; it never changes them. '
                                 'Leave a box empty to skip it.')
        folder_row('Music folder', 'music_folder', 'Songs the tools can pick from. Their tempo and beats are measured once.')
        folder_row('Sound-effects folder', 'sfx_folder', 'Whooshes, hits, ambience...')
        folder_row('Finished videos go to', 'output_folder', 'Exports and new projects are saved here.')
        ttk.Checkbutton(body, text='Measure the tempo and beats of the music now (about half a second per song)',
                        variable=v['index_music']).pack(anchor='w', pady=(12, 0))

    def page_pc():
        title('3. This PC', 'What your computer can run by itself. Models are downloaded from their makers '
                            'only when you choose them here or when a feature first needs one.')
        if 'hw' not in hw_box:
            try:
                hw_box['hw'] = ss.hardware()
            except Exception as ex:  # noqa: BLE001
                hw_box['hw'] = {'tier': 'cpu', 'lines': [f'Could not check the hardware: {ex}'], 'features': {}}
        hw = hw_box['hw']
        txt = tk.Text(body, height=7, wrap='word', relief='flat', background=root.cget('background'))
        txt.insert('end', '\n'.join(l for l in hw['lines'] if not l.startswith(('Settings', '  {', 'Read at'))))
        txt.configure(state='disabled')
        txt.pack(fill='x')
        if hw.get('speech_note'):
            ttk.Label(body, text=hw['speech_note'], wraplength=680, justify='left').pack(anchor='w', pady=(6, 0))
        if hw.get('slow_note'):
            ttk.Label(body, text=hw['slow_note'], wraplength=680, justify='left').pack(anchor='w', pady=(6, 0))
        fits = bool(hw.get('better_speech'))
        if fits:
            try:
                size = ss.better_speech_size()[1]
            except Exception:  # noqa: BLE001
                size = 'about 3.4 GB'
            ttk.Label(body, text=f'Better speech model, ticked below: any language, about 5 times faster, on your graphics card. {size} to download now, so '
                                 'your first video has no surprise wait. Untick it and speech on this PC understands English only.',
                      wraplength=680, justify='left').pack(anchor='w', pady=(6, 0))
        ttk.Label(body, text=f"Local models that suit this PC (tier {hw['tier']}). Tick to download now:").pack(
            anchor='w', pady=(8, 2))
        frame = ttk.Frame(body)
        frame.pack(fill='both', expand=True)
        canvas = tk.Canvas(frame, highlightthickness=0, height=150)
        sb = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        try:
            models, _ = ss.models_for(hw['tier'])
            models = [s for s in models if s['id'] != ss.BETTER_SPEECH_MODEL]    # one choice with its environment, below
        except Exception as ex:  # noqa: BLE001
            models = []
            ttk.Label(inner, text=f'No model list: {ex}').pack(anchor='w')
        total = tk.StringVar()
        try:
            envs = ss.envs_for(hw['tier'])
        except Exception as ex:  # noqa: BLE001
            envs = []
            ttk.Label(inner, text=f'No environment list: {ex}').pack(anchor='w')

        def update_total(*_):
            n = sum(s['missing_bytes'] for s in models if model_vars[s['id']].get())
            n += sum(p['download_bytes'] or 0 for p in envs if env_vars[p['name']].get() and not p['ready'])
            if env_vars.get(ss.BETTER_SPEECH_ENV) is not None and env_vars[ss.BETTER_SPEECH_ENV].get():
                try:
                    import model_fetch as mf
                    n += mf.status(ss.BETTER_SPEECH_MODEL)['missing_bytes']
                except Exception:  # noqa: BLE001
                    pass
            total.set(f'To download now: {n / 2**20:.0f} MB')
        for s in models:
            model_vars.setdefault(s['id'], tk.BooleanVar(value=False))
            label = (f"{s['title']} - {s['size_text']}" + (' (already on this PC)' if s['present'] else '') +
                     f" - {'; '.join(s['features'] or [])}")
            ttk.Checkbutton(inner, text=label, variable=model_vars[s['id']], command=update_total).pack(anchor='w')
        if envs:
            ttk.Label(inner, text='Model environments (Python + torch etc.; the models above need the one named '
                                  'in their feature):', foreground='#555').pack(anchor='w', pady=(8, 0))
        for p in envs:
            better = p['name'] == ss.BETTER_SPEECH_ENV
            env_vars.setdefault(p['name'], tk.BooleanVar(value=better and fits))
            label = (f"{p['name']} ({p['form']}) - {p['download_text']} download, about {p['installed_text']} on "
                     f"disk" + (' (already built)' if p['ready'] else '') + f" - {'; '.join(p['features'])}")
            if better:
                try:
                    label = (f"Better speech model ({p['form']}): {ss.better_speech_size()[1]} download, with its model file, about "
                             f"{((p.get('installed_bytes') or 0) + 1617941637) / 2**30:.1f} GB on disk" + (' (environment already built)' if p['ready'] else '')
                             + ' - speech on your graphics card, in any language; without it, English only')
                except Exception:  # noqa: BLE001 - the plain row still says what it is
                    label = 'Better speech model: ' + label
            ttk.Checkbutton(inner, text=label, variable=env_vars[p['name']], command=update_total).pack(anchor='w')
        update_total()
        ttk.Label(body, textvariable=total).pack(anchor='w', pady=(6, 0))
        f = ttk.Frame(body)
        f.pack(fill='x', pady=(6, 0))
        ttk.Label(f, text='When a feature first needs one that is not here:').pack(side='left')
        for val, text in DOWNLOAD_CHOICES:
            ttk.Radiobutton(f, text=text, value=val, variable=v['model_downloads']).pack(side='left', padx=4)

    def page_done():
        title('4. Setting up', 'Doing what you chose. You can close this window when it says Finished.')
        log = tk.Text(body, height=16, wrap='word')
        log.pack(fill='both', expand=True)
        bar = ttk.Progressbar(body, mode='determinate')
        bar.pack(fill='x', pady=(8, 0))

        def say(t):
            root.after(0, lambda: (log.insert('end', t + '\n'), log.see('end')))

        def prog(label, got, tot):
            if tot:
                root.after(0, lambda: bar.configure(value=100 * got / tot))
        answers = {k: (x.get()) for k, x in v.items()}
        answers['models'] = [i for i, x in model_vars.items() if x.get()]
        answers['envs'] = [i for i, x in env_vars.items() if x.get()]

        def work():
            try:
                run_answers(answers, say, prog)
            except Exception:  # noqa: BLE001
                say(traceback.format_exc())
            root.after(0, lambda: nxt.configure(text='Close', state='normal', command=root.destroy))
        nxt.configure(state='disabled')
        back.configure(state='disabled')
        if not selftest:
            threading.Thread(target=work, daemon=True).start()

    pages = [page_apps, page_folders, page_pc, page_done]

    def show(i):
        state['page'] = i
        clear()
        pages[i]()
        back.configure(state='normal' if 0 < i < 3 else 'disabled', command=lambda: show(state['page'] - 1))
        if i < 2:
            nxt.configure(text='Next', state='normal', command=lambda: show(state['page'] + 1))
        elif i == 2:
            nxt.configure(text='Set up', state='normal', command=lambda: show(3))

    show(0)
    if selftest:
        def texts(w):
            out = []
            for c in w.winfo_children():
                try:
                    t = c.cget('text')
                    if t:
                        out.append(t)
                except tk.TclError:
                    pass
                out += texts(c)
            return out
        for i in range(4):
            show(i)
            root.update()
            print(f'--- page {i + 1}')
            print('\n'.join(texts(body)))
        root.destroy()
        return
    root.mainloop()


def main(argv):
    if '--answers' in argv:
        a = json.loads(Path(argv[argv.index('--answers') + 1]).read_text(encoding='utf-8-sig'))
        r = run_answers(a)
        return 1 if r['errors'] else 0
    if '--console' in argv:
        console()
        return 0
    gui(selftest='--gui-selftest' in argv)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
