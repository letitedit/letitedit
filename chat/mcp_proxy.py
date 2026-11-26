"""Transparent stdio bridge that records letitedit tool names for the AI panel.

The actual tool server remains the same process and protocol. The record is
only progress metadata; no tool arguments, media or results are saved here.
It also says when a call comes back, so the panel knows whether a turn that ended
left a tool running, on any version of the AI program. When the AI program goes
away (Stop, a finished New video) the server and whatever it started go too.
"""
import json
import subprocess
import sys
import threading

LOG_LOCK = threading.Lock()


def record(events, entry):
    try:
        with LOG_LOCK, open(events, "a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # progress only: never in the way of a tool call


def stop_tree(child):
    """The server has not gone by itself: a tool is still working in it. Stop it and the programs it started."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        child.kill()


def main():
    if len(sys.argv) != 3:
        return 2
    server, events = sys.argv[1:]
    child = subprocess.Popen([sys.executable, server], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=sys.stderr.buffer, bufsize=0)
    calls = set()  # ids of the calls that went out and have not come back

    def copy_out():
        for line in child.stdout:
            try:
                call = json.loads(line).get("id") if calls else None
                if call is not None and call in calls:
                    calls.discard(call)
                    # before the answer reaches the AI: a turn ending on this answer finds the call already gone
                    record(events, {"type": "tool_end", "call": str(call)})
            except (ValueError, TypeError, AttributeError):
                pass
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()

    thread = threading.Thread(target=copy_out, daemon=True)
    thread.start()
    try:
        for line in sys.stdin.buffer:
            try:
                message = json.loads(line)
                if message.get("method") == "tools/call":
                    name = message.get("params", {}).get("name", "")
                    calls.add(message.get("id"))
                    record(events, {"type": "tool", "tool_name": name, "call": str(message.get("id"))})
                elif message.get("method") == "notifications/cancelled":
                    call = message.get("params", {}).get("requestId")
                    if call in calls:
                        calls.discard(call)
                        record(events, {"type": "tool_end", "call": str(call)})
            except (ValueError, TypeError, AttributeError):
                pass
            child.stdin.write(line)
            child.stdin.flush()
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stop_tree(child)
            child.wait(timeout=5)
        thread.join(timeout=1)
    return child.returncode


if __name__ == "__main__":
    sys.exit(main())
