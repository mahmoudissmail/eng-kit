#!/usr/bin/env python3
"""Claude Code hook entry point for eng-kit.

Kept tiny on purpose: it runs before and after every Bash call, so in a project without
.eng-kit/config.json it exits after a few file checks. Real work is delegated to engkit.py.
It never blocks Claude: it always exits 0 and prints nothing.
"""
import json
import os
import sys


def _fresh_junit(folder: str) -> bool:
    """Cheap check: is any configured JUnit file newer than the last one seen? Folders are left to engkit."""
    try:
        with open(os.path.join(folder, ".eng-kit", "config.json"), encoding="utf-8") as handle:
            paths = json.load(handle).get("junit_paths") or []
        try:
            with open(os.path.join(folder, ".eng-kit", ".seen.json"), encoding="utf-8") as handle:
                seen = json.load(handle)
        except (OSError, ValueError):
            seen = {}
        try:
            with open(os.path.join(folder, ".eng-kit", ".pending.json"), encoding="utf-8") as handle:
                for entry in json.load(handle).values():
                    paths = list(paths) + [p for p in entry.get("junit") or [] if p not in paths]
        except (OSError, ValueError, AttributeError):
            pass
        for raw in paths:
            path = raw if os.path.isabs(raw) else os.path.join(folder, raw)
            if os.path.isdir(path):
                return True
            if os.path.isfile(path) and os.path.getmtime(path) > seen.get(os.path.realpath(path), 0):
                return True
    except (OSError, ValueError, AttributeError):
        return True
    return False


def main() -> int:
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if phase not in ("pre", "post") or payload.get("tool_name") not in (None, "Bash"):
        return 0
    start = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    if not start:
        return 0
    folder = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(folder, ".eng-kit", "config.json")):
            break
        parent = os.path.dirname(folder)
        if parent == folder:
            return 0
        folder = parent
    if phase == "pre":
        command = str((payload.get("tool_input") or {}).get("command") or "")
        if not any(word in command for word in ("test", "phpunit", "pest", "jest", "vitest", "pytest", "rspec", "gotestsum")):
            return 0
    if phase == "post" and not _fresh_junit(folder):
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import engkit  # noqa: E402

    return engkit.hook_cmd(phase, payload)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # never break the session
        sys.exit(0)
