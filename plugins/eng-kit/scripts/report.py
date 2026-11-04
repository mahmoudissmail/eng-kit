"""eng-kit report: one markdown file to share — speed per environment, every run, what changed, release speed.

`--anonymous` leaves out the project name, run labels, commits and runner names, so the file can be shared outside
the team.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import engkit


def _env_alias(envs: List[str]) -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    runner_count = 0
    for env in envs:
        if env.startswith("CI runner"):
            runner_count += 1
            aliases[env] = "CI project runner" if runner_count == 1 else f"CI project runner {runner_count}"
        else:
            aliases[env] = env
    return aliases


def _scrub(text: str, aliases: Dict[str, str], project: str) -> str:
    for real, alias in aliases.items():
        if real != alias:
            name = real.replace("CI runner ", "")
            text = text.replace(real, alias).replace(name, "the project runner")
    return text.replace(project, "the project") if project else text


def _mins(seconds: Optional[float]) -> str:
    return "—" if seconds is None else (f"{seconds:.0f} s" if seconds < 60 else f"{seconds / 60:.1f} min")


def build_report(root: Path, anonymous: bool) -> str:
    cfg = engkit.load_config(root)
    runs = engkit.read_runs(root)
    envs = list(dict.fromkeys(r.get("environment") or "unknown" for r in runs))
    aliases = _env_alias(envs) if anonymous else {e: e for e in envs}
    project = root.name
    lines: List[str] = []
    title = "Test speed report" + ("" if anonymous else f" — {project}")
    lines += [f"# {title}", "", f"Generated {engkit.now_iso()} with eng-kit {engkit.VERSION} · stack {cfg.get('stack')}", ""]

    lines += ["## Speed per environment", "",
              "| Environment | Baseline | Latest | Change | Times faster | Tests | Wall time per test |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    full = [r for r in runs if r.get("scope") == "full" and r.get("passed") and r.get("wall_seconds")]
    for env in envs:
        mine = [r for r in full if r.get("environment") == env]
        if not mine:
            continue
        base = engkit.env_baseline(root, env) or mine[0]
        last = mine[-1]
        delta = engkit.change(last, base)
        times = f"{base['wall_seconds'] / last['wall_seconds']:.1f}×" if last is not base and last["wall_seconds"] else "—"
        lines.append(f"| {aliases[env]} | {_mins(base['wall_seconds'])} | {_mins(last['wall_seconds'])} | "
                     f"{'—' if delta is None else f'{-delta * 100:+.0f} %'} | {times} | "
                     f"{last['tests']:,} | {last['wall_seconds'] / last['tests']:.2f} s |")
    overall_first = full[0] if full else None
    overall_last = full[-1] if full else None
    if overall_first and overall_last and overall_first is not overall_last:
        gain = 1 - overall_last["wall_seconds"] / overall_first["wall_seconds"]
        lines += ["", f"First recorded run {_mins(overall_first['wall_seconds'])} ({aliases[overall_first['environment']]}) → "
                      f"latest {_mins(overall_last['wall_seconds'])} ({aliases[overall_last['environment']]}): "
                      f"{gain * 100:.0f} % less time across environments."]

    lines += ["", "## Every run", "",
              "| Date | Environment | Source | Scope | Tests | Failed | Time | Change |" + ("" if anonymous else " Label |"),
              "| --- | --- | --- | --- | --- | --- | --- | --- |" + ("" if anonymous else " --- |")]
    for r in runs:
        base = engkit.env_baseline(root, r.get("environment"))
        delta = engkit.change(r, base)
        cells = [r.get("recorded_at", "")[:10], aliases.get(r.get("environment"), r.get("environment")), r.get("source", ""),
                 r.get("scope", ""), f"{r.get('tests', 0):,}", str(r.get("failures", 0) + r.get("errors", 0)),
                 _mins(r.get("wall_seconds")), "baseline" if base and base.get("id") == r.get("id") else ("—" if delta is None else f"{-delta * 100:+.0f} %")]
        if not anonymous:
            cells.append(r.get("label") or "")
        lines.append("| " + " | ".join(cells) + " |")

    analysis = engkit._read_json(engkit.kit(root) / "analysis.json")
    items = analysis.get("items") or []
    if items:
        lines += ["", "## Improvements", "", "| Change | State | Result |", "| --- | --- | --- |"]
        for f in items:
            note = f.get("note") or ""
            if anonymous:
                note = _scrub(note, aliases, project)
            lines.append(f"| {f.get('title')} | {f.get('state')} | {note} |")

    release_file = engkit.kit(root) / "release.jsonl"
    if release_file.exists():
        snaps = [json.loads(l) for l in release_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        if snaps:
            s = snaps[-1]
            h = lambda v: "—" if v is None else (f"{v:.1f} h" if v < 48 else f"{v / 24:.1f} d")  # noqa: E731
            lines += ["", f"## Release speed (last {s['window_days']} days)", "", "| Step | Changes | Median | p75 | p90 |",
                      "| --- | --- | --- | --- | --- |",
                      f"| Code ready → {s['staging_branch']} | {s['code_to_staging']['count']} | {h(s['code_to_staging']['median_h'])} | {h(s['code_to_staging']['p75_h'])} | {h(s['code_to_staging']['p90_h'])} |",
                      f"| Code ready → {s['production_branch']} | {s['code_to_production']['count']} | {h(s['code_to_production']['median_h'])} | {h(s['code_to_production']['p75_h'])} | {h(s['code_to_production']['p90_h'])} |"]
    lines += ["", "Change = 1 − run ÷ the baseline of the same environment. Wall time per test = run time ÷ tests. "
                  "Runs with far fewer tests than the baseline are marked partial and not compared.", ""]
    text = "\n".join(lines)
    if anonymous:
        text = _scrub(text, aliases, project)
    return text


def report_cmd(root: Path, anonymous: bool, out: Optional[str]) -> int:
    text = build_report(root, anonymous)
    target = Path(out) if out else engkit.kit(root) / ("report-anonymous.md" if anonymous else "report.md")
    engkit.atomic_write(target, text)
    print(text)
    print(f"Saved: {target}")
    return 0
