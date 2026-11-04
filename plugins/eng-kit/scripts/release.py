"""eng-kit release speed: how long a change takes to reach staging and production.

Default source: the local Git history (no network, no token). Each merge into the staging branch is one change;
its lead time starts at the earliest commit it brought in and ends at the merge; it counts as released at the
first commit on the production branch's first-parent line that contains it (exact ancestry, not a time guess).
Merges whose source branch is a back-merge or release branch are left out.

Optional source "gitlab" (release.source = gitlab) uses read-only GitLab API calls with the person's own token:
  - merge requests merged into the staging branch (code ready -> on staging = MR opened -> merged),
  - merge requests merged into the production branch (a release MR carries every staging merge before it),
  - optionally deployments of an environment (merged -> deployed).
Writes a snapshot to .eng-kit/release.jsonl; the dashboard shows the latest one.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import statistics
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import engkit


def _ts(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pages(host: str, project: str, path: str, token: str, params: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for page in range(1, limit + 1):
        query = urllib.parse.urlencode({**params, "per_page": 100, "page": page})
        batch = engkit._api(host, project, f"{path}?{query}", token) or []
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


def _first_commits(root: Path, host: str, project: str, token: str, mrs: List[Dict[str, Any]]) -> Dict[str, str]:
    """First commit date per merged MR. Merged MRs never change, so answers are cached in .eng-kit/cache/
    and only new MRs are fetched, 4 at a time (GitLab rate limits are handled in engkit._api)."""
    from concurrent.futures import ThreadPoolExecutor

    cache_path = engkit.kit(root) / "cache" / "mr-first-commit.json"
    cache: Dict[str, str] = engkit._read_json(cache_path)
    todo = sorted({str(m["iid"]) for m in mrs if m.get("iid") is not None and str(m["iid"]) not in cache})

    def fetch(iid: str) -> Optional[str]:
        commits = engkit._api(host, project, f"/merge_requests/{iid}/commits?per_page=100", token) or []
        dates = sorted(c.get("authored_date") or c.get("created_at") for c in commits if (c.get("authored_date") or c.get("created_at")))
        return dates[0] if dates else None

    if todo:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for iid, first in zip(todo, pool.map(fetch, todo)):
                if first:
                    cache[iid] = first
        engkit.atomic_write(cache_path, json.dumps(cache, indent=0, sort_keys=True))
    return cache


def _stats(hours: List[float]) -> Dict[str, Optional[float]]:
    if not hours:
        return {"count": 0, "median_h": None, "p75_h": None, "p90_h": None}
    ordered = sorted(hours)

    def pct(q: float) -> float:
        idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
        return round(ordered[idx], 1)

    return {"count": len(ordered), "median_h": round(statistics.median(ordered), 1), "p75_h": pct(0.75), "p90_h": pct(0.9)}


DEFAULT_EXCLUDE = [r"^back-?merge", r"^release", r"^main$", r"^master$"]


MERGE_SUBJECT = re.compile(r"Merge (?:branch|remote-tracking branch) '([^']+)' into '?([^'\s]+)'?")
MR_REF = re.compile(r"See merge request \S*!(\d+)")
GITHUB_MERGE = re.compile(r"Merge pull request #(\d+) from [^\s/]+/(\S+)")


def _git(root: Path, *args: str) -> str:
    import subprocess

    out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return out.stdout


def _ref(root: Path, branch: str) -> Optional[str]:
    for candidate in (f"origin/{branch}", branch):
        try:
            _git(root, "rev-parse", "--verify", "--quiet", candidate)
            return candidate
        except RuntimeError:
            continue
    return None


def _is_ancestor(root: Path, commit: str, ref: str) -> bool:
    import subprocess

    return subprocess.run(["git", "merge-base", "--is-ancestor", commit, ref], cwd=root, capture_output=True, timeout=30).returncode == 0


def release_speed_git(root: Path, cfg: Dict[str, Any], days: int, staging: str, production: str, listing: bool) -> Dict[str, Any]:
    ref_s, ref_p = _ref(root, staging), _ref(root, production)
    if not ref_s:
        engkit.fail(f"no branch {staging!r} or origin/{staging} in this clone (set release.staging_branch)")
    patterns = (cfg.get("release") or {}).get("exclude_source_patterns") or DEFAULT_EXCLUDE
    since = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).timestamp())
    raw = _git(root, "log", "--first-parent", f"--since={since}", "--format=%H%x1f%P%x1f%ct%x1f%s%x1f%b%x1e", ref_s)
    entries = [e.strip("\n") for e in raw.split("\x1e") if e.strip()]
    main_line: List[tuple] = []
    if ref_p:
        for line in _git(root, "log", "--first-parent", "--reverse", f"--since={since - 90 * 86400}", "--format=%H %ct", ref_p).split("\n"):
            if line.strip():
                h, t = line.split()
                main_line.append((h, int(t)))
    excluded: List[Dict[str, Any]] = []
    rows: List[Dict[str, Any]] = []
    to_staging: List[float] = []
    to_production: List[float] = []
    waiting = 0
    uses_merges = any(len(((e.split("\x1f") + ["", ""])[1]).split()) >= 2 for e in entries)
    direct = 0
    for entry in entries:
        sha, parents, ctime, subject, body = (entry.split("\x1f") + ["", "", "", "", ""])[:5]
        parents_l = parents.split()
        if uses_merges and len(parents_l) < 2:
            direct += 1  # a merge-commit flow: changes arrive as merges; direct commits are not counted
            continue
        match = MERGE_SUBJECT.search(subject)
        gh = GITHUB_MERGE.search(subject)
        source = match.group(1) if match else (gh.group(2) if gh else ("(direct commit)" if len(parents_l) < 2 else "(merge)"))
        mr = MR_REF.search(body or "") or (gh and re.match(r"(\d+)", gh.group(1)))
        if source == production or any(re.search(p, source) for p in patterns):
            excluded.append({"iid": int(mr.group(1)) if mr else None, "source": source, "title": subject[:80]})
            continue
        merged_at = int(ctime)
        if len(parents_l) >= 2:
            # Commits the merge brought in, minus any that were already on the production branch at merge time
            # (a branch cut from main carries main-only commits; they are not this change's work).
            exclude: List[str] = []
            prod_then = None
            for commit, when in main_line:  # the production branch's first-parent line, oldest first
                if when >= merged_at or commit == sha:  # strictly before this merge (same-branch flows merge into it)
                    break
                prod_then = commit
            if prod_then:
                exclude = [f"^{prod_then}"]
            times = [int(t) for t in _git(root, "log", "--format=%at", f"{parents_l[0]}..{parents_l[1]}", *exclude).split() if t.strip()]
            start = min(times) if times else merged_at
        else:
            start = int(_git(root, "log", "-1", "--format=%at", sha).strip() or merged_at)
        hours = max(0.0, (merged_at - start) / 3600)
        to_staging.append(hours)
        released_at = None
        if main_line and _is_ancestor(root, sha, ref_p):
            lo, hi = 0, len(main_line) - 1
            while lo < hi:  # first main commit that contains the change
                mid = (lo + hi) // 2
                if _is_ancestor(root, sha, main_line[mid][0]):
                    hi = mid
                else:
                    lo = mid + 1
            if _is_ancestor(root, sha, main_line[lo][0]):
                released_at = main_line[lo][1]
        if released_at is not None:
            to_production.append(max(0.0, (released_at - start) / 3600))
        else:
            waiting += 1
        rows.append({"iid": int(mr.group(1)) if mr else None, "source": source, "title": (body.split("\n")[0] if body.strip() else subject)[:80],
                     "to_staging_h": round(hours, 1), "mr_open_h": None,
                     "to_production_h": round((released_at - start) / 3600, 1) if released_at else None, "release_iid": None})
    tip = _git(root, "log", "-1", "--format=%ci", ref_s).strip()
    snapshot = {
        "recorded_at": engkit.now_iso(), "source": "git", "refs": {"staging": ref_s, "production": ref_p, "staging_tip": tip},
        "window_days": days, "staging_branch": staging, "production_branch": production,
        "merged_to_staging": len(rows), "excluded": len(excluded), "direct_commits_skipped": direct, "exclude_source_patterns": patterns,
        "releases": sum(1 for h, t in main_line if t >= since), "start": "first_commit",
        "code_to_staging": _stats(to_staging), "mr_open_to_merge": None,
        "code_to_production": _stats(to_production), "not_released_yet": waiting, "deploy": None,
    }
    engkit.refuse_symlink(engkit.kit(root) / "release.jsonl")
    with open(engkit.kit(root) / "release.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
    if listing:
        snapshot["counted"] = rows
        snapshot["excluded_list"] = excluded
    return snapshot


def release_speed(root: Path, days: int, staging: str, production: str, environment: Optional[str], listing: bool = False) -> Dict[str, Any]:
    cfg = engkit.load_config(root)
    if (cfg.get("release") or {}).get("source", "git") == "git":
        if environment:
            print("Note: merged -> deployed needs release.source = gitlab; the local Git history has no deployments.")
        return release_speed_git(root, cfg, days, staging, production, listing)
    ci = cfg.get("ci", {})
    host = ci.get("host") or "https://gitlab.com"
    project = ci.get("project") or engkit._remote_project(root)
    if not project:
        engkit.fail("could not tell the GitLab project. Set it: config set ci.project group/name")
    token = engkit._token(root, cfg)
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    common = {"state": "merged", "updated_after": since, "order_by": "updated_at"}
    staged = list({m.get("iid", id(m)): m for m in _pages(host, project, "/merge_requests", token, {**common, "target_branch": staging}) if m.get("merged_at")}.values())
    released = sorted((m for m in _pages(host, project, "/merge_requests", token, {**common, "target_branch": production}) if m.get("merged_at")),
                      key=lambda m: m["merged_at"])
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    patterns = (cfg.get("release") or {}).get("exclude_source_patterns") or DEFAULT_EXCLUDE
    excluded: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    for m in staged:
        if _ts(m["merged_at"]) < cutoff:
            continue
        source = m.get("source_branch") or ""
        if source == production or any(re.search(p, source) for p in patterns):
            excluded.append(m)
        else:
            kept.append(m)
    staged = kept
    rows: List[Dict[str, Any]] = []
    to_staging: List[float] = []
    to_production: List[float] = []
    waiting = 0
    start_from = (cfg.get("release") or {}).get("start", "first_commit")
    first_commit = _first_commits(root, host, project, token, staged) if start_from == "first_commit" else {}
    review: List[float] = []
    for mr in staged:
        opened, merged = _ts(mr["created_at"]), _ts(mr["merged_at"])
        review.append((merged - opened).total_seconds() / 3600)
        first = first_commit.get(str(mr.get("iid")))
        if first:
            opened = min(_ts(first), opened)
        to_staging.append((merged - opened).total_seconds() / 3600)
        release = next((r for r in released if _ts(r["merged_at"]) >= merged), None)
        if release:
            to_production.append((_ts(release["merged_at"]) - opened).total_seconds() / 3600)
        else:
            waiting += 1
        rows.append({"iid": mr.get("iid"), "source": mr.get("source_branch"), "title": (mr.get("title") or "")[:80],
                     "to_staging_h": round(to_staging[-1], 1), "mr_open_h": round(review[-1], 1),
                     "to_production_h": round(to_production[-1], 1) if release else None,
                     "release_iid": release.get("iid") if release else None})
    deploy: Dict[str, Any] = {}
    if environment:
        deps = _pages(host, project, "/deployments", token, {"environment": environment, "status": "success", "updated_after": since, "order_by": "updated_at"})
        finished = sorted(_ts(d.get("finished_at") or d.get("updated_at")) for d in deps if (d.get("finished_at") or d.get("updated_at")))
        lead: List[float] = []
        for mr in staged:
            merged = _ts(mr["merged_at"])
            after = next((f for f in finished if f >= merged), None)
            if after:
                lead.append((after - merged).total_seconds() / 3600)
        weeks = max(1.0, days / 7)
        deploy = {"environment": environment, "deployments": len(finished), "per_week": round(len(finished) / weeks, 1), "merge_to_deploy": _stats(lead)}
    snapshot = {
        "recorded_at": engkit.now_iso(),
        "window_days": days,
        "staging_branch": staging,
        "production_branch": production,
        "merged_to_staging": len(staged),
        "excluded": len(excluded),
        "exclude_source_patterns": patterns,
        "releases": len([r for r in released if _ts(r["merged_at"]) >= cutoff]),
        "start": start_from,
        "code_to_staging": _stats(to_staging),
        "mr_open_to_merge": _stats(review),
        "code_to_production": _stats(to_production),
        "not_released_yet": waiting,
        "deploy": deploy or None,
    }
    engkit.refuse_symlink(engkit.kit(root) / "release.jsonl")
    with open(engkit.kit(root) / "release.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
    if listing:
        snapshot["counted"] = rows
        snapshot["excluded_list"] = [{"iid": m.get("iid"), "source": m.get("source_branch"), "title": (m.get("title") or "")[:80]} for m in excluded]
    return snapshot


def _h(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1f} h" if v < 48 else f"{v / 24:.1f} d"


def release_speed_cmd(root: Path, days: int, staging: str, production: str, environment: Optional[str], as_json: bool, listing: bool = False) -> int:
    snap = release_speed(root, days, staging, production, environment, listing)
    if as_json:
        print(json.dumps(snap, indent=2))
        return 0
    s, p, r = snap["code_to_staging"], snap["code_to_production"], snap.get("mr_open_to_merge")
    start_label = "first commit" if snap.get("start") == "first_commit" else "merge request opened"
    if snap.get("source") == "git":
        print(f"From the local Git history; latest commit on {snap['refs']['staging']}: {snap['refs']['staging_tip']} (git fetch updates it).")
    unit, into_prod = ("merges", "commits on the first-parent line of") if snap.get("source") == "git" else ("MRs", "MRs into")
    print(f"Release speed, last {days} days ({snap['merged_to_staging']} {unit} into {staging}, {snap['releases']} {into_prod} {production}; "
          f"{snap['excluded']} back-merge/release {unit} left out):")
    print(f"  Code ready ({start_label}) -> on {staging}: median {_h(s['median_h'])}, p75 {_h(s['p75_h'])}, p90 {_h(s['p90_h'])}")
    if r:
        print(f"  Merge request open -> merged:       median {_h(r['median_h'])}, p75 {_h(r['p75_h'])}, p90 {_h(r['p90_h'])}")
    print(f"  Code ready ({start_label}) -> in {production}: median {_h(p['median_h'])}, p75 {_h(p['p75_h'])}, p90 {_h(p['p90_h'])} ({snap['not_released_yet']} not released yet)")
    if listing:
        if snap.get("source") == "git":
            print("Counted (MR, source branch, hours from first commit to staging -> hours to production):")
        else:
            print("Counted (MR, source branch, hours to staging, MR open time, hours to production, release MR):")
        for r in snap["counted"]:
            mr_open = f" (MR open {r['mr_open_h']} h)" if r.get("mr_open_h") is not None else ""
            label = f"!{r['iid']}" if r.get("iid") is not None else "-"
            print(f"  {label} {r['source']}: {r['to_staging_h']} h to staging{mr_open} -> {r['to_production_h'] if r['to_production_h'] is not None else 'not released'}"
                  f"{' (!' + str(r['release_iid']) + ')' if r['release_iid'] else ''}  {r['title']}")
        print("Left out: " + (", ".join(f"{'!' + str(m['iid']) if m.get('iid') else '-'} {m['source']}" for m in snap["excluded_list"]) or "none"))
    if snap.get("deploy"):
        d = snap["deploy"]
        print(f"  Deploys to {d['environment']}: {d['deployments']} ({d['per_week']}/week); merge -> deployed median {_h(d['merge_to_deploy']['median_h'])}")
    return 0
