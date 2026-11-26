"""letitedit Studio's command line: jobs from a written spec (job.json), for other programs (T258).

    python letitedit_studio.py validate|submit|run|status|cancel|retry <job folder | job.json | job id>
    python letitedit_studio.py capabilities
    python letitedit_studio.py watch [--idle-s S]

With LETITEDIT_STUDIO_FAKE=1 in the environment every command goes to the reference fake instead
(letitedit/studio/fake.py, its Studio folder LETITEDIT_STUDIO_FAKE_HOME): placeholder results, marked fake, for a
caller's integration tests.

The contract: bridge/letitedit/studio/contract/CONTRACT.md. The code: bridge/letitedit/studio/.
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

FAKE_ENV = 'LETITEDIT_STUDIO_FAKE'


def _fake_wanted():
    return os.environ.get(FAKE_ENV, '').strip().lower() in ('1', 'true', 'yes')


if __name__ == '__main__':
    if _fake_wanted():
        from letitedit.studio import fake
        sys.exit(fake.main(sys.argv[1:], entry=os.path.abspath(__file__)))
    import letitedit.core.quiet_subprocess  # noqa: F401  (T52: no console windows)
    from letitedit.studio.cli import main
    sys.exit(main())
