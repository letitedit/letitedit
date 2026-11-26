"""Start the letitedit tool server with a given Python through a real MCP stdio client and call a few read-only tools.

    <any python with mcp> check_server.py <python.exe of the env to test> [project.mlt]

Checks: the server starts, lists its tools, letitedit_guide answers (index + one topic), letitedit_timeline_read reads a
project (read-only; without one given, a new empty project in a temporary folder, removed afterwards). A venv made by
build-bridge-clean.ps1 does not see the global site-packages.
"""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PY = sys.argv[1]
PROJECT = sys.argv[2] if len(sys.argv) > 2 else None    # none given: a new empty project in a temporary folder
SERVER = StdioServerParameters(command=PY, args=[r'C:\LetItEdit\bridge\letitedit_mcp.py'])
ok = []


def text_of(r):
    return ''.join(getattr(c, 'text', '') for c in r.content)


def check(name, cond, detail=''):
    ok.append(bool(cond))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f' -- {detail}' if detail else ''))


async def main():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            check('server starts and lists tools', len(tools) >= 40, f'{len(tools)} tools')
            g = await s.call_tool('letitedit_guide', {})
            check('letitedit_guide index', not g.is_error and len(text_of(g)) > 2000, f'{len(text_of(g))} chars')
            g2 = await s.call_tool('letitedit_guide', {'topic': 'letitedit_footage'})
            check('letitedit_guide(topic=letitedit_footage)', not g2.is_error and 'footage' in text_of(g2).lower(),
                  f'{len(text_of(g2))} chars')
            project = PROJECT
            if project is None and 'letitedit_project_new' in tools:
                project = str(Path(tempfile.mkdtemp(prefix='letitedit-check-')) / 'check.mlt')
                n = await s.call_tool('letitedit_project_new', {'path': project, 'width': 640, 'height': 360, 'fps': 30})
                check('letitedit_project_new (a temporary project)', not n.is_error, text_of(n)[:160].replace('\n', ' '))
            if project and 'letitedit_timeline_read' in tools:
                props = tools['letitedit_timeline_read'].input_schema.get('properties', {})
                key = 'project' if 'project' in props else next(iter(props))
                t = await s.call_tool('letitedit_timeline_read', {key: project})
                check('letitedit_timeline_read', not t.is_error, text_of(t)[:160].replace('\n', ' '))
            if project and PROJECT is None:
                shutil.rmtree(Path(project).parent, ignore_errors=True)


asyncio.run(main())
print(f'{sum(ok)}/{len(ok)} passed with {PY}')
sys.exit(0 if all(ok) else 1)
