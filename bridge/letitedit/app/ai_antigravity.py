"""Google's Antigravity connector: what differs from any other connector AI. See tests/t57/GATE.md for what was measured.

Only Google's standalone connector, only in conversations on screen: no `agy`, no `yolo`, no hidden runs. letitedit names itself,
never reads the connector's token file and never calls Google's services itself. It signs in once in a private profile, so
nothing under the person's ~/.gemini changes. Quota shows up only when a turn says so.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)

import letitedit.app.acp_client as acp_client

# The pin. A new connector is a new letitedit release: this code, not a file read at run time, says what may run.
VERSION = '1.4.5'
URL = f'https://dl.google.com/agy-extensions/releases/windows/agy-acp-server-{VERSION}-windows-x86_64.zip'
SHA256 = 'd24f4c73c9f96d4f44384e281c855a56c72d8eaa9c5b0fad7ccb1635c6b63f50'
SIZE = 100423655
MEMBERS = {'agy_acp_server.exe': 55839864, 'localharness_external.exe': 147843736}
SIGNER = 'Google LLC'
NEEDS_FREE_BYTES = SIZE + sum(MEMBERS.values()) + 1024 ** 3 + 256 * 1024 ** 2     # each start also unpacks about 1 GB
INSTALLED_NOTE = '.installed.json'

STRIP = re.compile(r'(API_KEY|^GEMINI|^GOOGLE_|^GCP|^CLOUDSDK|^BROWSER$|^ANTHROPIC|^OPENAI)', re.I)
# Tools that write outside the conversation or never report back (T3 Code's issues; audits/antigravity-connector-2026-11-03.md).
DISABLED_TOOLS = ['run_workflow', 'invoke_subagent']
PICTURE_MODEL = 'flash-image'
LEARN_MORE = 'https://support.google.com/accounts?p=al_alert'

# Real words: "You have exhausted your capacity on this model. Your quota will reset after 167h54m59s." (pictures),
# "Error 429, Message: Individual quota reached. ... Resets in 165h1m8s." and the agent's "Usage Limit Reached" (chat).
QUOTA = re.compile(r'exhausted your capacity|RESOURCE_EXHAUSTED|QUOTA_EXHAUSTED|Individual quota reached|Usage Limit Reached|\b429\b', re.I)
RESET_AFTER = re.compile(r'(?:reset after|resets in) ([0-9hms.]+)', re.I)
SIGNED_OUT = re.compile(r'not (signed|logged) in|authentication (required|failed)|please (log|sign) in', re.I)
VERIFY_URL = re.compile(r'Verification URL:\s*(https://\S+)')
TIMED_OUT = re.compile(r'Timed out waiting for the authentication', re.I)


def _when(text):
    found = RESET_AFTER.search(text or '')
    if not found:
        return ''
    hours = re.match(r'(\d+)h', found.group(1))
    if hours and int(hours.group(1)) >= 48:
        return f' Google says it comes back in about {round(int(hours.group(1)) / 24)} days.'
    return f' Google says it comes back after {found.group(1).split(".")[0]}.'


from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
class Antigravity(acp_client.Adapter):
    def env(self, base, profile, temp):
        out = {k: v for k, v in base.items() if not STRIP.search(k)}
        out.update({'GEMINI_HOME': str(profile), 'AGY_ACP_FORCE_FILE_STORAGE': '1', 'TEMP': str(temp), 'TMP': str(temp), 'PYTHONUNBUFFERED': '1'})
        return out

    def validate_initialize(self, reply):
        info = reply.get('agentInfo') or {}
        if info.get('name') != 'antigravity-acp':
            return f"This isn't Google's connector: it calls itself {info.get('name')!r}."
        if info.get('version') != VERSION:
            return f"This connector is version {info.get('version')}, and letitedit expects {VERSION}."
        return None

    def session_meta(self, rules, disabled=DISABLED_TOOLS):
        return {'antigravity': {'disabledTools': list(disabled), 'systemPrompt': {'append': rules}}}

    def install_skills(self, profile):
        """The letitedit skills, in the private profile only."""
        target = Path(profile) / 'config' / 'skills'
        here = _paths.CODE_ROOT / 'skills'
        if not here.is_dir():
            return None
        sys.path.insert(0, str(here))
        try:
            import install as skills_install
            skills_install.install([target])
        except (ImportError, OSError):
            return None
        return target

    def tool_name(self, update):
        found = re.match(r'Run (\w+)\?', str(update.get('title') or ''))
        if found:
            return found.group(1)
        raw = update.get('rawInput') if isinstance(update.get('rawInput'), dict) else {}
        if 'ImageName' in raw and 'Prompt' in raw:
            return 'generate_image'
        return super().tool_name(update)

    def image_limit(self, text, stderr):
        """The picture allowance can run out while chat goes on: the connector's log names the picture model, and the agent's
        words quote the limit. T57: 7 pictures, then about a week, on a free account."""
        if QUOTA.search(stderr or '') and PICTURE_MODEL in (stderr or ''):
            source = stderr
        elif QUOTA.search(text or '') and re.search(r'image|picture|generate_image', text or '', re.I):
            source = text
        else:
            return None
        return f'Google says this account has run out of Antigravity pictures for now.{_when(source)}'

    def turn_failure(self, text, stop_reason, stderr):
        """A limit arrives as a normal finished turn. The typed sign is stop reason `refusal`; else the log or the agent's last words.
        A picture limit isn't a failed turn: image_limit reports that one."""
        said = f'{text or ""}\n{stderr or ""}'
        pictures_only = PICTURE_MODEL in (stderr or '') or (QUOTA.search(text or '') and re.search(r'image|picture|generate_image', text or '', re.I))
        if stop_reason == 'refusal' or (QUOTA.search(said) and not pictures_only):
            return {'kind': 'limit', 'words': f'Google says this account has reached its Antigravity limit for now.{_when(said)} '
                                              'Your work so far is safe in the project. Try again later, or pick another AI.'}
        if SIGNED_OUT.search(text or '') and not (text or '').strip()[200:]:
            return {'kind': 'signin', 'words': "Antigravity isn't signed in any more. Use Connect Your AI to sign in again."}
        return None

    def signin_waiting_words(self):
        return "Your browser is opening Google's sign-in page. Finish there and come back. The page waits 5 minutes."

    def signin_refused(self, error):
        message = str(error.get('message') or error)
        data = error.get('data') if isinstance(error.get('data'), dict) else {}
        said = f"{message} {data.get('message') or ''}"
        if TIMED_OUT.search(said):
            return {'state': 'timeout', 'message': "Google's sign-in page timed out after 5 minutes. Nothing went wrong: press Sign in to try again."}
        link = VERIFY_URL.search(said)
        if link or 'Verify your account' in said:
            words = said.split(' Verification URL:')[0].strip()
            words = re.sub(r'^Onboarding failed:\s*(User is ineligible for free-tier\.\s*Reason:\s*)?', '', words).rstrip('. ')
            return {'state': 'verify', 'google_said': words + '.', 'url': link.group(1) if link else None, 'learn_more': LEARN_MORE,
                    'message': ('Google needs to check this account before it can use Antigravity. You are not signed in yet, and '
                                "nothing is broken. Finish Google's check, then press Sign in again.")}
        return {'state': 'failed', 'message': f"Google didn't accept this sign-in: {message[:300]}"}

    # --- the download
    def install(self, home, say, url=None):
        """Downloads the pinned connector from Google's address, checks it, proves it by starting it, and only then puts it in place."""
        home = Path(home)
        target = home / 'connector'
        note = target / INSTALLED_NOTE
        if note.is_file() and (target / 'agy_acp_server.exe').is_file():
            try:
                if json.loads(note.read_text(encoding='utf-8-sig')).get('version') == VERSION:
                    say(state='installed', message='Antigravity is already set up.', version=VERSION)
                    return target
            except ValueError:
                pass
        home.mkdir(parents=True, exist_ok=True)
        import letitedit.core.cache_budget as cache_budget
        cache_budget.need_room(home, NEEDS_FREE_BYTES, 'set up Antigravity', progress=lambda message: say(state='waiting_space', message=message))
        working = home / 'download'
        shutil.rmtree(working, ignore_errors=True)
        working.mkdir(parents=True)
        archive = working / 'connector.zip'
        say(state='downloading', message="Downloading Google's connector (100 MB).", percent=0)
        url = url or os.environ.get('LETITEDIT_ANTIGRAVITY_URL') or URL
        _download(url, archive, say)
        got = _sha256(archive)
        if archive.stat().st_size != SIZE or got != SHA256:
            shutil.rmtree(working, ignore_errors=True)
            raise ValueError("The download didn't match what letitedit expects, so it wasn't used. Try again.")
        say(state='checking', message='Checking it came from Google.')
        unpacked = working / 'unpacked'
        _unpack(archive, unpacked)
        _check_signatures(unpacked)
        problem = _start_check(self, unpacked, working)
        if problem:
            shutil.rmtree(working, ignore_errors=True)
            raise ValueError(problem)
        (unpacked / INSTALLED_NOTE).write_text(json.dumps({'version': VERSION, 'sha256': SHA256}), encoding='utf-8')
        old = home / 'connector.old'
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            os.replace(target, old)
        os.replace(unpacked, target)
        shutil.rmtree(old, ignore_errors=True)
        shutil.rmtree(working, ignore_errors=True)
        say(state='installed', message='Antigravity is set up. Next, sign in with your Google account.', version=VERSION)
        return target


def make(entry, settings):
    return Antigravity(entry, settings)


def _download(url, path, say):
    done, last = 0, -10
    request = urllib.request.Request(url, headers={'User-Agent': 'letitedit'})
    with urllib.request.urlopen(request, timeout=120) as reply, open(path, 'wb') as out:
        while True:
            piece = reply.read(1024 * 1024)
            if not piece:
                return
            out.write(piece)
            done += len(piece)
            if done > SIZE * 1.05:
                raise ValueError("The download is bigger than letitedit expects, so it wasn't used.")
            percent = int(100 * done / SIZE)
            if percent >= last + 10:
                last = percent
                say(state='downloading', message="Downloading Google's connector (100 MB).", percent=min(percent, 100))


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for piece in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(piece)
    return digest.hexdigest()


def _unpack(archive, folder):
    """Only the two programs, by their own names and sizes, nothing else and nowhere else."""
    with zipfile.ZipFile(archive) as zipped:
        rows = zipped.infolist()
        if {r.filename: r.file_size for r in rows} != MEMBERS:
            raise ValueError("The download holds something letitedit doesn't expect, so it wasn't used.")
        folder.mkdir(parents=True)
        for row in rows:
            with zipped.open(row) as source, open(folder / Path(row.filename).name, 'wb') as out:
                shutil.copyfileobj(source, out)


def _check_signatures(folder):
    """Windows' own check: a valid signature, by Google."""
    if os.environ.get('LETITEDIT_ANTIGRAVITY_SKIP_SIGNATURE'):       # a test's stand-in zip only
        return
    for name in MEMBERS:
        path = str(folder / name).replace("'", "''")
        code = (f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; "
                "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)")
        run = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', code], capture_output=True, text=True, timeout=120,
                             errors='replace', stdin=subprocess.DEVNULL)
        answer = run.stdout.strip()
        if not answer.startswith('Valid|') or SIGNER not in answer:
            raise ValueError(f"{name} isn't signed by {SIGNER} as expected, so it wasn't used. ({answer[:120]})")


def _start_check(adapter, unpacked, working):
    """Starts the new program in a throwaway profile and asks what it is, before anything relies on it. No sign-in, no account."""
    home, temp, cwd = working / 'check-profile', working / 'check-temp', working / 'check-work'
    home.mkdir()
    temp.mkdir()
    env = adapter.env(dict(os.environ), home, temp)
    env['BROWSER'] = 'cmd /c exit 0'
    connector = None
    try:
        connector = acp_client.Connector(str(unpacked / 'agy_acp_server.exe'), cwd, env)
        return adapter.validate_initialize(connector.initialize())
    except (acp_client.Gone, acp_client.AcpError, TimeoutError, OSError) as exc:
        return f"Google's connector didn't start on this PC: {str(exc)[:200]}"
    finally:
        if connector:
            connector.end()
