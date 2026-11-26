"""Append Claude Code hook events to the current letitedit terminal session.

Claude runs this through a project-local --settings file. It never changes the
person's own Claude settings or writes to stdout (which is a hook protocol).
"""
import json
import os
import sys


def main():
    if len(sys.argv) != 3:
        return
    try:
        event = json.load(sys.stdin)
        record = {
            "type": sys.argv[2],
            "session_id": event.get("session_id", ""),
            "tool_name": event.get("tool_name", ""),
            "stop_hook_active": event.get("stop_hook_active", False),
        }
        # What the AI left running when its turn ended (Claude Code's Stop hook says, on versions that have this field).
        tasks = event.get("background_tasks")
        if isinstance(tasks, list):
            record["background_tasks"] = [
                {key: task.get(key, "") for key in ("id", "type", "status", "server")}
                for task in tasks if isinstance(task, dict)]
        with open(sys.argv[1], "a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, ValueError, TypeError):
        pass  # A failed progress hook must never prevent a Claude tool call.


if __name__ == "__main__":
    main()
