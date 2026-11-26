"""The Codex plugin's manifest as the installer ships it: its server command is the build PC's own Python, so the
installer carries it with a neutral one instead (setup's relocate.py points it at the install's Python, env\\Scripts).

    python -I stage_plugin.py <codex\\plugins\\letitedit\\.codex-plugin\\plugin.json> <out\\stage\\codex-plugin.json>
"""
import json
import sys
from pathlib import Path


def main(source, target):
    data = json.loads(Path(source).read_text(encoding='utf-8-sig'))
    server = data['mcpServers']['letitedit']
    server['command'] = 'python.exe'
    server['args'] = ['bridge\\letitedit_mcp.py']
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main(*sys.argv[1:3])
