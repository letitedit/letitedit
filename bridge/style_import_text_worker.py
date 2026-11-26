"""Isolated caption/typography analysis; the caller owns the PC lock and deadline."""
import json
import sys
from pathlib import Path

import quiet_subprocess


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))
    import style_import
    if request['stage'] == 'captions':
        import style_import_text
        result = style_import_text.caption_style(
            request['events'], request['info'], request['video'], request['words'], request['fps'],
            lambda times, width: style_import.frames_at(request['video'], times, width, request['info']))
    else:
        import style_import_typography
        result = style_import_typography.analyse(
            request['video'], request['events'], request['info'], request['folder'],
            fps=request['fps'], max_events=request['max_events'], budget_s=request['budget_s'])
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    main()
