"""eng-kit: import a GitHub Actions run (read-only, the person's own token).

The workflow uploads its JUnit XML as an artifact (default name "junit"); eng-kit downloads that artifact,
reads every XML file in it, and takes the wall time from the job named ci.job_name (default "tests").
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import engkit


def _repo(root: Path, cfg: Dict[str, Any], ref: str) -> str:
    match = re.search(r"github\.com/([^/\s]+/[^/\s]+?)/actions/runs/", ref)
    if match:
        return match.group(1)
    repo = (cfg.get("ci") or {}).get("project") or engkit._remote_project(root)
    if not repo or repo.count("/") != 1:
        engkit.fail("could not tell the GitHub repository. Set it: config set ci.project owner/name")
    return repo


def _base(cfg: Dict[str, Any]) -> str:
    host = (cfg.get("ci") or {}).get("host") or ""
    if not host or "gitlab" in host:
        return "https://api.github.com"
    return host.rstrip("/") + ("" if host.rstrip("/").endswith("/api/v3") else "/api/v3")  # GitHub Enterprise Server


def _get(url: str, token: str, raw: bool = False) -> Any:
    import socket
    import time
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"eng-kit/{engkit.VERSION}",
    })
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (fixed GitHub API host)
                body = response.read()
                return body if raw else json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503, 504) and attempt < 4:
                wait = exc.headers.get("Retry-After") if exc.headers else None
                time.sleep(min(60.0, float(wait)) if wait and wait.isdigit() else 2 ** attempt)
                continue
            reasons = {401: "the token is missing or expired", 403: "the token lacks access (needs actions:read) or the rate limit is hit",
                       404: "the repository, run or artifact was not found (check ci.project)"}
            engkit.fail(f"GitHub answered {exc.code} for {url.split('?')[0].replace('https://api.github.com', '')}: {reasons.get(exc.code, 'unexpected answer')}.")
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            engkit.fail(f"could not reach GitHub ({getattr(exc, 'reason', exc)}).")
    return None


def _download(url: str, token: str) -> bytes:
    """Artifact zips redirect to a signed storage URL that must be fetched WITHOUT the GitHub token."""
    import urllib.error
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib hook
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"eng-kit/{engkit.VERSION}"})
    try:
        with opener.open(request, timeout=120) as response:  # noqa: S310
            return response.read()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") if exc.headers else None
        if exc.code in (301, 302, 303, 307, 308) and location:
            with urllib.request.urlopen(urllib.request.Request(location, headers={"User-Agent": f"eng-kit/{engkit.VERSION}"}), timeout=300) as response:  # noqa: S310
                return response.read()
        return _get(url, token, raw=True)


def _ts(value: Optional[str]) -> Optional[dt.datetime]:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def import_run(root: Path, cfg: Dict[str, Any], ref: str, label: str) -> int:
    ci = cfg.get("ci") or {}
    repo = _repo(root, cfg, ref)
    api = f"{_base(cfg)}/repos/{repo}"
    token = engkit._token(root, cfg, provider="github")
    artifact_name = ci.get("artifact") or "junit"
    job_name = ci.get("job_name") or "tests"

    if ref.strip().lower() == "latest":
        runs = (_get(f"{api}/actions/runs?status=completed&per_page=20", token) or {}).get("workflow_runs", [])
        run = None
        for candidate in runs:
            arts = (_get(f"{api}/actions/runs/{candidate['id']}/artifacts", token) or {}).get("artifacts", [])
            if any(a.get("name") == artifact_name and not a.get("expired") for a in arts):
                run = candidate
                break
        if not run:
            engkit.fail(f"none of the last 20 completed runs has an artifact named {artifact_name!r} (set ci.artifact).")
        run_id = str(run["id"])
    else:
        match = re.search(r"/actions/runs/(\d+)", ref) or re.fullmatch(r"\s*(\d+)\s*", ref)
        if not match:
            engkit.fail("give a GitHub Actions run id, a run URL (…/actions/runs/<id>) or 'latest'.")
        run_id = match.group(1)
        run = _get(f"{api}/actions/runs/{run_id}", token)

    artifacts = (_get(f"{api}/actions/runs/{run_id}/artifacts", token) or {}).get("artifacts", [])
    artifact = next((a for a in artifacts if a.get("name") == artifact_name and not a.get("expired")), None)
    if not artifact:
        engkit.fail(f"run {run_id} has no artifact named {artifact_name!r}. The workflow must upload the JUnit file "
                    f"(actions/upload-artifact with name: {artifact_name}).")
    data = _download(artifact["archive_download_url"], token)
    folder = engkit.kit(root) / "ci" / f"github-run-{run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.namelist():
            if member.lower().endswith(".xml") and ".." not in member and not member.startswith("/"):
                target = folder / Path(member).name
                target.write_bytes(archive.read(member))
                written.append(target)
    if not written:
        engkit.fail(f"artifact {artifact_name!r} of run {run_id} holds no XML file.")

    jobs = (_get(f"{api}/actions/runs/{run_id}/jobs?per_page=100", token) or {}).get("jobs", [])
    job = next((j for j in jobs if j.get("name") == job_name), None) or (jobs[0] if len(jobs) == 1 else None)
    wall, source_note = None, "ci-job-duration"
    if job and job.get("started_at") and job.get("completed_at"):
        wall = (_ts(job["completed_at"]) - _ts(job["started_at"])).total_seconds()
    elif run.get("run_started_at") and run.get("updated_at"):
        wall, source_note = (_ts(run["updated_at"]) - _ts(run["run_started_at"])).total_seconds(), "ci-run-duration"
    labels = [str(x).lower() for x in (job or {}).get("labels", [])]
    environment = f"CI runner {(job or {}).get('runner_name') or 'self-hosted'}" if "self-hosted" in labels else "CI GitHub-hosted runners"

    engkit.record(
        root, written, wall_seconds=wall, source="ci", environment=environment,
        label=label or f"{run.get('head_branch', '')} run {run_id}".strip(),
        command=(job or {}).get("name", ""), wall_source=source_note,
        ci={"provider": "github", "run_id": int(run_id), "job_id": (job or {}).get("id"), "url": run.get("html_url"),
            "finished_at": (job or {}).get("completed_at") or run.get("updated_at")},
    )
    return 0
