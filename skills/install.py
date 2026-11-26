"""Install (or refresh) the letitedit skills for the person's own AI: Claude Code (~/.claude/skills) and Codex
(~/.codex/skills), whichever are on this PC. Copies every `letitedit*` folder next to this script; run it again after
changing a skill, or after adding a second AI.

python install.py            install / refresh
python install.py --remove   take them out again

The editor's Connect Your AI runs it; the installer's setup window calls install() for the apps the person ticks.
"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def targets():
    """The CLIs' own skills folders: CLAUDE_CONFIG_DIR and CODEX_HOME when set, else ~/.claude and ~/.codex."""
    return [Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'skills',
            Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'skills']


def _present(engine, folder, chosen):
    """Install here? A folder the person named, skills already there to refresh, or that AI's program on this PC. Making
    ~/.codex for someone without Codex would later read as "Codex is on this PC"."""
    if chosen or any(folder.glob('letitedit*')):
        return True
    try:
        sys.path.insert(0, str(HERE.parent / 'bridge'))
        import ai_clis
    except ImportError:
        return True
    return ai_clis.find(engine) is not None


def installed_targets():
    """targets() without the AIs that aren't on this PC."""
    claude, codex = targets()
    return ([claude] if _present('claude', claude, os.environ.get('CLAUDE_CONFIG_DIR')) else []) + \
           ([codex] if _present('codex', codex, os.environ.get('CODEX_HOME')) else [])


def skills():
    """The skill folders shipped here (letitedit*, each with a SKILL.md)."""
    return [p for p in sorted(HERE.glob('letitedit*')) if (p / 'SKILL.md').is_file()]


def install(where=None, remove=False):
    """Copy (or with remove=True take out) every skill into each folder of `where` (default: installed_targets(), or
    with remove=True every target that exists). Returns {folder: [skill names]}."""
    done = {}
    if where is None:
        where = [t for t in targets() if t.is_dir()] if remove else installed_targets()
    for target in [Path(t) for t in where]:
        target.mkdir(parents=True, exist_ok=True)
        names = []
        for skill in skills():
            dest = target / skill.name
            if dest.exists():
                shutil.rmtree(dest)
            if not remove:
                shutil.copytree(skill, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'dev-history'))
            names.append(skill.name)
        done[str(target)] = names
    return done


def main():
    remove = '--remove' in sys.argv
    done = install(remove=remove)
    for target in done:
        print(('removed from ' if remove else 'installed in ') + target)
    if not done and not remove:
        print('neither Claude Code nor Codex is on this PC: nothing to install into yet')


if __name__ == '__main__':
    main()
