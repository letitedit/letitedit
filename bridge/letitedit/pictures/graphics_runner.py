"""Runs one custom graphic job in its own process (started by graphics._render_sandboxed with python -I)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import letitedit.pictures.graphics as graphics  # noqa: E402

if __name__ == '__main__':
    graphics.run_job(sys.argv[1])
