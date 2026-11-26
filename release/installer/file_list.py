"""Read-only expansion of the installer's file inputs; does not stage or compile."""
import fnmatch
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def is_excluded(file, source_root, patterns):
    parts = file.relative_to(source_root).parts
    prefixes = ['/'.join(parts[:length]).lower() for length in range(1, len(parts) + 1)]
    for pattern in patterns:
        pattern = pattern.replace('\\', '/').lower()
        candidates = prefixes if pattern.startswith('/') else [part.lower() for part in parts]
        pattern = pattern.lstrip('/')
        if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
            return True
    return False


def allowed_roots():
    """The source folder, and in a git worktree also its main checkout: a worktree build reaches the git-ignored
    inputs (app, models, fonts ...) through junctions to it (tests/t369/build_root.py)."""
    roots = [ROOT]
    git = ROOT / '.git'
    if git.is_file():
        text = git.read_text(encoding='utf-8-sig').strip()
        if text.startswith('gitdir:'):
            gitdir = Path(text.split(':', 1)[1].strip())
            if gitdir.parent.name == 'worktrees' and gitdir.parent.parent.name == '.git':
                roots.append(gitdir.parent.parent.parent.resolve())
    return roots


STAGE = HERE / 'out' / 'stage'


def staged_at_build(pattern):
    """True for a file build.ps1 writes into out\\stage while staging (the install marker, the Codex plugin's
    manifest, Node): this check runs before staging, so on a fresh checkout those aren't there yet."""
    return pattern.parent == STAGE or STAGE in pattern.parents


def iss_lines(path):
    """The script's lines with each #include "file" (relative to the script) put in its place, as ISCC reads it."""
    lines = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        included = re.match(r'\s*#include\s+"([^"]+)"', line)
        lines += iss_lines(path.parent / included[1]) if included else [line]
    return lines


def collect():
    """(files the installer ships, patterns that matched nothing), as letitedit.iss names them."""
    roots = allowed_roots()
    # the promoted editor, or the staged one build.ps1 -Exe packages
    executable = os.environ.get('LETITEDIT_INSTALLER_EXE') or \
        Path((ROOT / 'app/ai-assist-executable.txt').read_text().strip()).name
    result = []
    missing = []
    for line in iss_lines(HERE / 'letitedit.iss'):
        match = re.match(r'Source: "([^"]+)"', line)
        if not match:
            continue
        source = match[1].replace('{#Src}', str(ROOT)).replace('{#Exe}', executable)
        pattern = Path(source)
        if not pattern.is_absolute():
            pattern = HERE / pattern
        excludes = re.search(r'Excludes: "([^"]+)"', line)
        excluded = excludes[1].split(',') if excludes else []
        matches = []
        if '*' in pattern.name or '?' in pattern.name:
            if 'recursesubdirs' in line:
                for directory, folders, names in os.walk(pattern.parent, followlinks=True):
                    for folder in folders:
                        link = Path(directory, folder)
                        if (link.is_junction() or link.is_symlink()) and not any(
                                link.resolve().is_relative_to(root) for root in roots[1:]):
                            raise ValueError('Installer follows a junction: ' + str(link))
                    matches.extend(Path(directory, name) for name in names if fnmatch.fnmatch(name, pattern.name))
            else:
                matches = [file for file in pattern.parent.glob(pattern.name) if file.is_file()]
        elif pattern.is_file():
            matches = [pattern]
        if not matches and not staged_at_build(pattern):
            missing.append(str(pattern))
        for file in matches:
            if is_excluded(file, pattern.parent, excluded):
                continue
            if not any(file.resolve().is_relative_to(root) for root in roots):
                raise ValueError('Installer source outside letitedit: ' + str(file))
            result.append(str(file))
    return result, missing


def main():
    result, missing = collect()
    print(json.dumps({'dry_run': True, 'files': len(result), 'missing': missing, 'sources': result}, indent=2))
    if missing:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
