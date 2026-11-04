"""Builds .eng-kit/dashboard.html: one self-contained page, no network, light and dark."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

import engkit


def _payload(root: Path) -> Dict[str, Any]:
    cfg = engkit.load_config(root)
    runs = engkit.read_runs(root)
    base_id = cfg.get("baseline_run_id")
    latest_full = next((r for r in reversed(runs) if r.get("scope") == "full" and r.get("passed")), None)
    latest_base = engkit.env_baseline(root, latest_full.get("environment")) if latest_full else None
    keep_detail = {base_id, latest_full["id"] if latest_full else None, latest_base["id"] if latest_base else None}
    slim = []
    for run in runs:
        item = {k: v for k, v in run.items() if k != "class_seconds" or run.get("id") in keep_detail}
        if run.get("id") not in keep_detail:
            item.pop("slowest_tests", None)
        slim.append(item)
    status_md = ""
    status_file = engkit.kit(root) / "status.md"
    if status_file.exists():
        status_md = status_file.read_text(encoding="utf-8")[:20000]
    analysis = engkit._read_json(engkit.kit(root) / "analysis.json")
    plan = [
        {k: f.get(k) for k in ("id", "title", "gain", "area", "state", "expected", "note", "run_id")}
        for f in analysis.get("items", [])
    ]
    release = None
    release_file = engkit.kit(root) / "release.jsonl"
    if release_file.exists():
        lines = [l for l in release_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lines:
            try:
                release = json.loads(lines[-1])
            except ValueError:
                release = None
    return {
        "plan": plan,
        "plan_generated_at": analysis.get("generated_at"),
        "release": release,
        "project": root.name,
        "generated_at": engkit.now_iso(),
        "version": engkit.VERSION,
        "config": {k: cfg.get(k) for k in ("stack", "test_command", "environment", "baseline_run_id", "targets")},
        "runs": slim,
        "status_md": status_md,
    }


def _open(path: Path) -> str:
    target = str(path)
    try:
        release = platform.release().lower()
        if "microsoft" in release or "wsl" in release:
            if shutil.which("wslview"):
                subprocess.Popen(["wslview", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "opened with wslview"
            if shutil.which("explorer.exe") and shutil.which("wslpath"):
                win = subprocess.run(["wslpath", "-w", target], capture_output=True, text=True, timeout=5).stdout.strip()
                subprocess.Popen(["explorer.exe", win], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "opened with explorer.exe"
        if platform.system() == "Darwin" and shutil.which("open"):
            subprocess.Popen(["open", target])
            return "opened with open"
        if platform.system() == "Linux" and shutil.which("xdg-open") and os.environ.get("DISPLAY"):
            subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "opened with xdg-open"
        if webbrowser.open(path.as_uri()):
            return "opened in the default browser"
    except (OSError, subprocess.SubprocessError):
        pass
    return "not opened automatically; open the file in a browser"


def build_dashboard(root: Path, open_browser: bool = True, out: Optional[str] = None) -> int:
    data = _payload(root)
    template = (Path(__file__).resolve().parent / "dashboard_template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = template.replace("__ENGKIT_DATA__", blob)
    target = Path(out) if out else engkit.kit(root) / "dashboard.html"
    engkit.atomic_write(target, html)
    how = _open(target) if open_browser else "not opened (--no-open)"
    print(f"Dashboard: {target} ({len(data['runs'])} runs; {how})")
    return 0
