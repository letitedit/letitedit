"""Explicit per-call editor routing and crash-recoverable AI ownership (local PC only)."""
from letitedit.core import paths as _paths  # noqa: E402  (the install folder and bridge\, wherever this file is)
_SAI_ROOT = __import__('os').path.normpath(__import__('os').environ.get('LETITEDIT_ROOT') or _paths.ROOT_TEXT)   # install root: LETITEDIT_ROOT, else the folder above bridge
import letitedit.core.quiet_subprocess as quiet_subprocess  # noqa: F401  (T52: no console windows, so nothing takes the keyboard focus)
import contextlib
import contextvars
import ctypes
from ctypes import wintypes
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import time
import uuid

ROOT = Path((_SAI_ROOT + '\\instances'))
_instance = contextvars.ContextVar('letitedit_instance', default=os.environ.get('LETITEDIT_INSTANCE', 'main'))
TOKEN = os.environ.get('LETITEDIT_OWNER') or uuid.uuid4().hex
# The person's own edit made with the letitedit window's controls (the Opening panel's New hook runs hooks.py apply
# --from-app, which checks that the window started it): not an AI session, so it neither checks nor takes the
# instance's or the project's AI ownership. AI sessions never set it.
_app_edit = contextvars.ContextVar('letitedit_app_edit', default=False)
# Reads never claim the instance, so a watcher (a progress script, another session) can't lock out the AI that is
# working in it.
READ_METHODS = {'ping', 'state', 'live_context', 'command_help', 'list_actions', 'list_filters', 'get_filter_params', 'project_xml', 'snapshot',
                'editor_state', 'chat_state', 'grab_window', 'hook_state', 'review_state',
                'chat_review',   # the critic, under the session that owns the window: it shows a review and changes no project
                'load_fonts'}    # a font fetched on demand, loaded for the preview (google_fonts.py): no project change


def validate(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,59}', value):
        raise ValueError('Instance ID must be 1-60 lowercase letters, digits, hyphens or underscores')
    if value.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('Reserved Windows instance ID')
    return value


def current(): return validate(_instance.get())


@contextlib.contextmanager
def scope(instance_id):
    token = _instance.set(validate(instance_id))
    try: yield
    finally: _instance.reset(token)


@contextlib.contextmanager
def app_edit():
    """Bridge writes inside run as the person's own edit through the app (see _app_edit): no AI ownership claimed."""
    token = _app_edit.set(True)
    try: yield
    finally: _app_edit.reset(token)


def in_app_edit(): return _app_edit.get()


def pipe_name(instance_id=None):
    value = validate(instance_id or current())
    return 'letitedit-bridge' if value == 'main' else 'letitedit-' + value


def process_stamp(pid):
    """Creation time avoids treating a recycled Windows PID as the old owner."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,int(pid))
    if not handle:return None
    try:
        code=wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value!=259:return None
        values=[wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in values]):return None
        return str((values[0].dwHighDateTime<<32)|values[0].dwLowDateTime)
    finally:kernel.CloseHandle(handle)


def read(path):
    """An instance file's contents. A missing file reads as {}, and so does one left empty, cut short or filled with
    zero bytes (24 Nov: the PC's crash zeroed an owner.json), so a broken file never stops the AI from working."""
    try:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}
    except ValueError:   # json.JSONDecodeError (empty, cut short, zero bytes) and UnicodeDecodeError (garbage bytes)
        return {}
    return data if isinstance(data,dict) else {}


def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,indent=2),encoding='utf-8');os.replace(temp,path)


@contextlib.contextmanager
def guard():
    import msvcrt
    ROOT.mkdir(parents=True,exist_ok=True)
    with (ROOT/'ownership.lock').open('a+b') as f:
        if f.tell()==0:f.write(b'0');f.flush()
        until=time.monotonic()+5
        while True:
            try:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>until:raise RuntimeError('Instance ownership registry busy; retry')
                time.sleep(.03)
        try:yield
        finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)


def living(data):
    return {pid:stamp for pid,stamp in data.get('processes',{}).items() if process_stamp(pid)==stamp}


def _claim_instance(pid=None):
    file=ROOT/current()/'owner.json';data=read(file);live=living(data)
    if live and data.get('token')!=TOKEN:
        raise RuntimeError(f"letitedit window '{current()}' belongs to another active AI session. Use another window or wait for its explicit handoff.")
    if data.get('token')!=TOKEN:live={}
    child_pid=pid
    pid=pid or os.getpid();stamp=process_stamp(pid)
    if not stamp:
        if child_pid is not None:return # A very short job may already have finished.
        raise RuntimeError('Cannot register instance owner process')
    live[str(pid)]=stamp
    write(file,{'instance_id':current(),'token':TOKEN,'processes':live})


def claim_instance(pid=None):
    if _app_edit.get():return
    with guard():_claim_instance(pid)


def project_key(path):
    path=Path(path).resolve()
    # All revisions of one managed cut share ownership; independent cuts have their own episode.json.
    for candidate in (path if path.is_dir() else path.parent, *path.parents):
        if (candidate/'episode.json').is_file():return str(candidate).casefold()
        # layout v2: the user-facing episode folder keeps episode.json in its system folder
        system=candidate/"9 System (AI working files - don't edit)"
        if (system/'episode.json').is_file():return str(system).casefold()
    return str(path).casefold()


def claim_project(path):
    if _app_edit.get():return
    key=project_key(path);file=ROOT/'projects'/(hashlib.sha256(key.encode()).hexdigest()+'.json')
    with guard():
        _claim_instance();data=read(file)
        if data and (data['instance_id']!=current() or data['token']!=TOKEN):
            owner=read(ROOT/data['instance_id']/'owner.json')
            if owner.get('token')==data['token'] and living(owner):
                raise RuntimeError(f"Project is owned by letitedit window '{data['instance_id']}'. Use a separate cut/copy or hand off that instance; no changes made.")
        write(file,{'path':key,'instance_id':current(),'token':TOKEN})


def release():
    with guard():
        file=ROOT/current()/'owner.json';data=read(file);live=living(data)
        if live and data.get('token')!=TOKEN:raise RuntimeError('Cannot release another active AI session')
        others=set(live)-{str(os.getpid())}
        if others:raise RuntimeError('Background jobs still own this instance; wait for them before handing off')
        write(file,{'instance_id':current(),'processes':{}})
    return {'instance_id':current(),'released':True,'window_closed':False}


def worker_env():
    return {**os.environ,'LETITEDIT_INSTANCE':current(),'LETITEDIT_OWNER':TOKEN}


def window_row(bridge):
    """{'pid', 'project', 'modified'} of the window on this bridge, from its ping. An editor whose ping doesn't say them
    (before T366) is asked for its full state, which on a heavy project holds its window 0.3-1.3 s (the revision
    writes out the whole project), every window at each listing."""
    reply=bridge.call('ping')
    if isinstance(reply,dict) and 'project' in reply:
        return {'pid':reply.get('pid'),'project':reply.get('project'),'modified':reply.get('modified')}
    state=bridge.call('state')
    return {'pid':state.get('instance',{}).get('pid'),'project':state.get('project'),'modified':state.get('modified')}


def list_instances():
    from letitedit.app.letitedit_client import ShotcutBridge
    ids={'main'}
    if ROOT.exists():ids.update(p.parent.name for p in ROOT.glob('*/editor.json'))
    result=[]
    for value in sorted(ids):
        try:
            with scope(value),ShotcutBridge(timeout=2) as bridge:row=window_row(bridge)
        except Exception:
            continue
        owner=read(ROOT/value/'owner.json');live=living(owner)
        result.append({'instance_id':value,'pid':row['pid'],
                       'project':row['project'],'modified':row['modified'],
                       'ownership':'this_session' if live and owner.get('token')==TOKEN else 'other_session' if live else 'available'})
    return result


def scoped_tool(fn):
    """Expose explicit instance_id on every tool, safe even if an MCP host shares one server."""
    signature=inspect.signature(fn)
    @functools.wraps(fn)
    def wrapped(*args,instance_id='main',**kwargs):
        with scope(instance_id):
            bound=signature.bind(*args,**kwargs)
            # Managed episode tools serialize edits by cut for the entire AI session.
            # Pure inspections remain accessible to a second conversation.
            reads={'letitedit_episode_job','letitedit_episode_media','letitedit_search_scenes','letitedit_scene_candidates',
                   'letitedit_version_request_status','letitedit_list_cuts','letitedit_compare_cuts','letitedit_episode_preflight',
                   'letitedit_scan_episode_sources','letitedit_source_frame','letitedit_episode_status','letitedit_create_cut'}
            project=bound.arguments.get('project_folder')
            try:
                if project and fn.__name__ not in reads:claim_project(project)
                result=fn(*args,**kwargs)
                if fn.__name__=='letitedit_create_cut':claim_project(result['project'])
                return result
            except (RuntimeError, ValueError, OSError) as exc:
                from mcp.server.mcpserver.exceptions import ToolError
                raise ToolError(str(exc)) from exc
    wrapped.__signature__=signature.replace(parameters=[*signature.parameters.values(),
        inspect.Parameter('instance_id',inspect.Parameter.KEYWORD_ONLY,default='main',annotation=str)])
    wrapped.__annotations__={**getattr(fn,'__annotations__',{}),'instance_id':str}
    wrapped.__doc__=(fn.__doc__ or '')+'\nPass your conversation\'s instance_id on every call. Never switch a global active editor.'
    return wrapped
