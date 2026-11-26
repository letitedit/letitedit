"""Tool calls that outlast the AI's own limit on a tool call.

Some AIs end every tool call at a fixed time (Google's connector: 3 minutes, whatever its settings say; tests/t57/GATE.md).
Each AI's number is `tool_call_limit_s` in the one AI list (ai_list.json), and whoever starts the AI passes it to this
server as LETITEDIT_CALL_LIMIT_S. With the value unset (Claude, Codex) the limit is DEFAULT_LIMIT_S: a call still
running after about 25 minutes answers "still working" too, so no single call keeps an AI waiting longer than that
(Codex ends a tool call at 60 minutes, `tool_timeout_sec`; Claude's prompt cache lasts an hour, and a step every
25 minutes keeps it).

With a limit set, the server waits ANSWER_MARGIN_S less than the limit. A call done by then answers as usual. Otherwise the
AI gets a normal result that says "still working" and an id, and the call goes on as a task of the server;
letitedit_wait(call_id) then gives the result in the same shape as the first call's, pictures included, or says "still
working" again. Calls run side by side as they do without a limit (the project's lease and the PC lock keep order).

An edit must never land twice (T63's longest calls were timeline_apply with cut-outs, 31.8 and 18.4 minutes). The same call
again, from an AI that ignored the instruction, starts nothing while the first runs, and once it has finished gets the
first's result, marked as such, until that result has been collected.

The AI's Stop can't reach work that has already answered: the work carries on, shows in letitedit_status and ends with the
server.
"""
import asyncio
import json
import os
import threading
import time

from mcp.types import CallToolResult, TextContent

LIMIT_VAR = 'LETITEDIT_CALL_LIMIT_S'
ANSWER_MARGIN_S = 30          # answer this long before the AI's limit
KEEP_S = 1800                 # a finished result waits this long for letitedit_wait
WAIT_TOOL = 'letitedit_wait'
DEFAULT_LIMIT_S = 1530        # an AI with no limit of its own: "still working" after 1500 s (25 minutes)


def limit_s(env=None):
    """The AI's limit on one tool call, in seconds, or None when this AI has none."""
    try:
        value = float((os.environ if env is None else env).get(LIMIT_VAR) or 0)
    except ValueError:
        return None
    return value if value > 0 else None


def answer_within_s(limit):
    """How long a call may run before the AI hears "still working"; never less than half its limit."""
    return max(limit - ANSWER_MARGIN_S, limit / 2)


def wait_cap(default):
    """The longest a tool that only waits should wait, so its own answer beats "still working"."""
    limit = limit_s() or DEFAULT_LIMIT_S
    return min(default, max(1.0, answer_within_s(limit) - 10))


def _text(words, error=False):
    return CallToolResult(content=[TextContent(type='text', text=words)], isError=error)


class _Call:
    __slots__ = ('id', 'tool', 'key', 'task', 'started', 'finished', 'collected')

    def __init__(self, call_id, tool, key, task):
        self.id, self.tool, self.key, self.task = call_id, tool, key, task
        self.started = time.monotonic()
        self.finished = None
        self.collected = False


class Calls:
    """The calls this server is running or has just finished. `limit` is the AI's limit in seconds."""

    def __init__(self, limit, keep_s=KEEP_S):
        self.limit = limit
        self.within = answer_within_s(limit)
        self.keep_s = keep_s
        self._lock = threading.Lock()
        self._calls = {}
        self._count = 0

    def _forget_old(self):
        now = time.monotonic()
        for call_id, call in list(self._calls.items()):
            if call.finished is not None and now - call.finished > self.keep_s:
                del self._calls[call_id]

    def _still_working(self, call):
        ago = int(time.monotonic() - call.started)
        return _text(f'Still working, nothing has failed. This call ({call.tool}, started {ago} s ago) is running in this '
                     f'server. Call {WAIT_TOOL} with call_id="{call.id}" to get its result; it answers within about '
                     f'{int(self.within)} s and says so again if the work is still running. Do not repeat the original call.')

    @staticmethod
    async def _done_within(call, seconds):
        """Whether the call is done by then. asyncio.wait leaves the task running on a timeout or if this waiter is cancelled."""
        await asyncio.wait({call.task}, timeout=seconds)
        return call.task.done()

    @staticmethod
    def _result(call):
        try:
            return call.task.result()
        except asyncio.CancelledError:
            return _text(f'{call.tool} was stopped before it finished.', error=True)
        except Exception as exc:  # noqa: BLE001 - it has to reach whoever waits on this call
            return _text(f'{call.tool} stopped with an error: {exc}', error=True)

    def _repeated(self, call):
        """The first call's result for a repeat of it: it isn't run again, and the AI is told so."""
        result = self._result(call)
        ago = int(time.monotonic() - call.started)
        note = TextContent(type='text', text=f'This call was not run again: this is the result of the same call you made {ago} s '
                                             f'ago, which answered "still working" ({call.id}).')
        return result.model_copy(update={'content': [note, *result.content]})

    async def call(self, tool, arguments, run):
        """Make a tool call. `run` is the async function that makes it and returns its CallToolResult."""
        key = tool + json.dumps(arguments, sort_keys=True, default=str)
        with self._lock:
            self._forget_old()
            # The same call again while it runs is the same call: an AI that ignored the instruction can't start two renders.
            earlier = next((c for c in self._calls.values() if c.key == key and not c.collected), None)
            if earlier is not None and not earlier.task.done():
                return self._still_working(earlier)
            if earlier is not None:
                earlier.collected = True
                return self._repeated(earlier)
            self._count += 1
            call = _Call(f'c{self._count}', tool, key, asyncio.get_running_loop().create_task(run()))
            call.task.add_done_callback(lambda _: setattr(call, 'finished', time.monotonic()))
            self._calls[call.id] = call
        if not await self._done_within(call, self.within):
            return self._still_working(call)
        with self._lock:
            self._calls.pop(call.id, None)    # answered on the spot: nobody will ask for it
        return self._result(call)

    async def wait(self, arguments):
        """letitedit_wait: the result of a call that answered "still working", or the same answer again."""
        arguments = arguments or {}
        call_id = str(arguments.get('call_id') or '').strip()
        with self._lock:
            self._forget_old()
            call = self._calls.get(call_id)
        if call is None:
            return _text(f'{WAIT_TOOL} found no call "{call_id}". Results are kept for {int(self.keep_s / 60)} minutes after '
                         'the call finishes, and until the tool server restarts, which ends a running call. Check what '
                         'it was meant to do before making it again: an edit may already be in the project '
                         '(letitedit_timeline_read shows it).', error=True)
        try:
            seconds = float(arguments.get('wait_s') or self.within)
        except (TypeError, ValueError):
            seconds = self.within
        if not await self._done_within(call, min(max(seconds, 0.0), self.within)):
            return self._still_working(call)
        call.collected = True
        return self._result(call)


_active = None


def active(default_limit=DEFAULT_LIMIT_S):
    """The Calls of this server (one for the server's life): its AI's limit, else `default_limit`; None when that is
    None too."""
    global _active
    if _active is None:
        limit = limit_s() or default_limit
        if limit is not None:
            _active = Calls(limit)
    return _active
