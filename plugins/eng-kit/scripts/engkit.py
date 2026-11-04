#!/usr/bin/env python3
"""eng-kit: local, per-project test-speed tracking for Claude Code.

Standard library only (Python 3.9+). Every file this tool writes lives in the
project's `.eng-kit/` folder, which `init` hides from Git through
`.git/info/exclude` (local to the clone, never committed).

Commands:
  detect                       Print the detected stack and test command.
  init [--force]               Create .eng-kit/ with config.json and status.md.
  config get|set KEY [VALUE]   Read or change a config value (dotted keys).
  record PATH... [options]     Record a run from JUnit XML file(s) or folder(s).
  measure [--command CMD]      Run the test command, time it, record the run.
  import-ci REF                Record a GitLab CI job (id or URL) using your token.
  status [--json]              Latest full run against the baseline.
  baseline [RUN_ID|latest|clear]
  dashboard [--no-open] [--out PATH]
  hook pre|post                Hook logic (Claude Code calls scripts/hook.py, which delegates here).
  export [--format csv|json]
  analyze [--json]             Ranked optimization plan from the runs and project files (.eng-kit/plan.md).
  plan show | plan set ITEM STATE [--run ID] [--note T]
  release-speed [--days N] [--staging B] [--production B] [--environment E] [--json]
  report [--anonymous] [--out PATH]   Shareable markdown report (.eng-kit/report.md).
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "1.0.1"
KIT_DIR = ".eng-kit"
SCHEMA = 1
TOP = 15
BUCKETS = [0.5, 2.0, 5.0, 10.0]
FULL_RUN_RATIO = 0.8  # a run with fewer tests than 80% of the baseline counts as partial
TEST_COMMAND_RE = re.compile(
    r"(artisan\s+test|phpunit|\bpest\b|paratest|vitest|\bjest\b|pytest|go\s+test|gotestsum|"
    r"\bmvn\b.*\btest\b|gradlew?\b.*\btest\b|dotnet\s+test|\brspec\b|cargo\s+test)"
)


# --------------------------------------------------------------------------- paths


def project_root(start: Optional[str] = None) -> Path:
    """The Git top level if there is one, else the start folder."""
    base = Path(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=base, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return base


def kit(root: Path) -> Path:
    return root / KIT_DIR


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def locked(path: Path):
    """Advisory lock on POSIX; a no-op elsewhere."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        yield handle


def fail(message: str, code: int = 2) -> None:
    print(f"eng-kit: {message}", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------- detection


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _deps(pkg: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in keys:
        value = pkg.get(key)
        if isinstance(value, dict):
            out.update(value)
    return out


def detect(root: Path) -> Dict[str, Any]:
    """Best guess of the stack and the command that runs the full suite with JUnit output."""
    junit = f"{KIT_DIR}/junit.xml"
    composer = _read_json(root / "composer.json")
    php_deps = _deps(composer, "require", "require-dev")
    pkg = _read_json(root / "package.json")
    js_deps = _deps(pkg, "dependencies", "devDependencies")
    notes: List[str] = []

    if (root / "artisan").is_file() and "laravel/framework" in php_deps:
        parallel = "brianium/paratest" in php_deps
        cmd = f"php artisan test {'--parallel ' if parallel else ''}--log-junit {junit}"
        if not parallel:
            notes.append("brianium/paratest is not installed, so the suite runs in one process.")
        return {"stack": "laravel", "test_command": cmd, "junit_paths": [junit], "notes": notes}
    if (root / "vendor/bin/pest").exists() or "pestphp/pest" in php_deps:
        return {"stack": "php-pest", "test_command": f"vendor/bin/pest --log-junit {junit}", "junit_paths": [junit], "notes": notes}
    if composer and ("phpunit/phpunit" in php_deps or (root / "phpunit.xml").exists() or (root / "phpunit.xml.dist").exists()):
        return {"stack": "php-phpunit", "test_command": f"vendor/bin/phpunit --log-junit {junit}", "junit_paths": [junit], "notes": notes}
    if "vitest" in js_deps:
        cmd = f"npx vitest run --reporter=default --reporter=junit --outputFile.junit={junit}"
        return {"stack": "js-vitest", "test_command": cmd, "junit_paths": [junit], "notes": notes}
    if "jest" in js_deps:
        if "jest-junit" not in js_deps:
            notes.append("Add jest-junit as a dev dependency so Jest can write JUnit XML.")
        cmd = f"JEST_JUNIT_OUTPUT_FILE={junit} npx jest --ci --reporters=default --reporters=jest-junit"
        return {"stack": "js-jest", "test_command": cmd, "junit_paths": [junit], "notes": notes}
    py_markers = ["pytest.ini", "conftest.py", "pyproject.toml", "setup.cfg", "tox.ini", "requirements-dev.txt", "requirements.txt"]
    py_text = " ".join(
        (root / name).read_text(encoding="utf-8", errors="ignore") for name in py_markers if (root / name).is_file()
    )
    if "pytest" in py_text or (root / "conftest.py").is_file() or (root / "pytest.ini").is_file():
        xdist = "pytest-xdist" in py_text
        cmd = f"python -m pytest {'-n auto ' if xdist else ''}--junitxml={junit}"
        return {"stack": "python-pytest", "test_command": cmd, "junit_paths": [junit], "notes": notes}
    if (root / "go.mod").is_file():
        notes.append("Needs gotestsum (go install gotest.tools/gotestsum@latest) for JUnit output.")
        return {"stack": "go", "test_command": f"gotestsum --junitfile {junit} ./...", "junit_paths": [junit], "notes": notes}
    if (root / "pom.xml").is_file():
        return {"stack": "java-maven", "test_command": "mvn -q test", "junit_paths": ["target/surefire-reports"], "notes": notes}
    if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
        runner = "./gradlew" if (root / "gradlew").exists() else "gradle"
        return {"stack": "java-gradle", "test_command": f"{runner} test", "junit_paths": ["build/test-results/test"], "notes": notes}
    if any(root.glob("*.sln")) or any(root.glob("*.csproj")):
        notes.append("Needs the JunitXml.TestLogger package for JUnit output.")
        cmd = f'dotnet test --logger "junit;LogFilePath={junit}"'
        return {"stack": "dotnet", "test_command": cmd, "junit_paths": [junit], "notes": notes}
    if (root / "Gemfile").is_file():
        notes.append("Needs rspec_junit_formatter for JUnit output.")
        cmd = f"bundle exec rspec --format progress --format RspecJunitFormatter --out {junit}"
        return {"stack": "ruby-rspec", "test_command": cmd, "junit_paths": [junit], "notes": notes}
    return {"stack": "unknown", "test_command": "", "junit_paths": [junit], "notes": ["Set the test command: config set test_command '<command>'."]}


# --------------------------------------------------------------------------- config


def default_config(root: Path) -> Dict[str, Any]:
    import platform

    found = detect(root)
    cores = os.cpu_count() or 1
    return {
        "schema": SCHEMA,
        "created_at": now_iso(),
        "stack": found["stack"],
        "test_command": found["test_command"],
        "junit_paths": found["junit_paths"],
        "environment": f"Local {platform.system().lower()} {cores}-core",
        "baseline_run_id": None,
        "targets": {"wall_minutes_low": None, "wall_minutes_high": None},
        "hook": {"enabled": True},
        "release": {"staging_branch": "staging", "production_branch": "main", "environment": None, "window_days": 30,
                    "exclude_source_patterns": ["^back-?merge", "^release", "^main$", "^master$"],
                    "start": "first_commit", "source": "git"},
        "ci": {
            "provider": "gitlab",
            "job_name": "tests",
            "artifact": "junit",
            "host": "https://gitlab.com",
            "project": None,
            "token_env": "GITLAB_TOKEN",
            "token_file": None,
            "token_key": "GITLAB_TOKEN",
        },
    }


DEFAULT_TRUSTED_HOSTS = ("gitlab.com", "github.com", "api.github.com")


def trusted_hosts() -> List[str]:
    """Hosts a token may be sent to: the public GitLab and GitHub, plus hosts the person lists themself in
    ENGKIT_TRUSTED_HOSTS (comma-separated) or ~/.config/eng-kit/trusted-hosts (one per line). Never project config."""
    hosts = list(DEFAULT_TRUSTED_HOSTS)
    hosts += [h.strip().lower() for h in os.environ.get("ENGKIT_TRUSTED_HOSTS", "").split(",") if h.strip()]
    user_file = Path(os.path.expanduser("~/.config/eng-kit/trusted-hosts"))
    with contextlib.suppress(OSError):
        hosts += [l.strip().lower() for l in user_file.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    return hosts


def check_host(url: str) -> None:
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in trusted_hosts():
        fail(f"refusing to send a token to {parsed.scheme}://{host}: it is not a trusted host. If you trust it, add "
             f"'{host}' to ~/.config/eng-kit/trusted-hosts (a project's own config cannot add hosts).")


def refuse_symlink(path: Path) -> None:
    """eng-kit appends to files in .eng-kit/; a symlink there could redirect those writes, so it is refused."""
    if path.is_symlink() or path.parent.is_symlink():
        fail(f"{path} is a symbolic link; eng-kit does not write through links. Remove it and run init again.")


def _tracked_in_git(root: Path, rel: str) -> bool:
    try:
        return subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=root, capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def load_config(root: Path) -> Dict[str, Any]:
    path = kit(root) / "config.json"
    if kit(root).is_symlink() or path.is_symlink():
        fail(f"{kit(root)} or its config is a symbolic link; eng-kit only uses a real local folder. Remove it and run init.")
    if not path.is_file():
        fail("this project is not set up yet. Run: init")
    if _tracked_in_git(root, f"{KIT_DIR}/config.json"):
        fail(f"{KIT_DIR}/config.json is committed to this repository. eng-kit only trusts local data it created itself: "
             f"remove {KIT_DIR}/ from the repository (git rm -r --cached {KIT_DIR}) and run init.")
    cfg = _read_json(path)
    if cfg.get("schema") != SCHEMA:
        fail(f"{path} has schema {cfg.get('schema')!r}; this version reads schema {SCHEMA}.")
    return cfg


def save_config(root: Path, cfg: Dict[str, Any]) -> None:
    atomic_write(kit(root) / "config.json", json.dumps(cfg, indent=2) + "\n")


def _coerce(value: str) -> Any:
    if value in ("null", "none", ""):
        return None
    if value in ("true", "false"):
        return value == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def config_cmd(root: Path, action: str, key: str, value: Optional[str]) -> int:
    cfg = load_config(root)
    parts = key.split(".")
    node: Any = cfg
    for part in parts[:-1]:
        node = node.setdefault(part, {}) if action == "set" else (node or {}).get(part)
    if action == "get":
        print(json.dumps((node or {}).get(parts[-1]) if isinstance(node, dict) else None))
        return 0
    if value is None:
        fail("config set needs a value")
    if key == "junit_paths":
        node[parts[-1]] = [p.strip() for p in str(value).split(",") if p.strip()]
    elif key == "ci.provider":
        if value not in ("gitlab", "github"):
            fail("ci.provider must be gitlab or github")
        node["provider"] = value
        node["provider_set"] = True
    elif key in ("test_command", "environment", "ci.project", "ci.host", "ci.token_env", "ci.token_file", "ci.token_key",
                 "ci.job_name", "ci.artifact", "ci.github_token_env", "ci.github_token_file", "ci.github_token_key",
                 "release.staging_branch", "release.production_branch", "release.environment", "release.start", "release.source"):
        node[parts[-1]] = value
    else:
        node[parts[-1]] = _coerce(value)
    save_config(root, cfg)
    print(f"{key} = {json.dumps(node[parts[-1]])}")
    return 0


# --------------------------------------------------------------------------- init


STATUS_TEMPLATE = """# Test speed — status

Local notes for this project (not committed). The dashboard reads this file.

## Now
- Baseline: not set yet (first full run becomes the baseline).

## Next
1. Record a full run: /eng-kit:measure or /eng-kit:import-ci <job>.
2. Open the dashboard: /eng-kit:dashboard.

## Decisions
| Date | Decision |
|---|---|

## Log
- {date}: eng-kit set up ({stack}).
"""


def ensure_excluded(root: Path) -> str:
    git_dir = root / ".git"
    if git_dir.is_file():  # worktree: ".git" is a file pointing at the real git dir
        try:
            out = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True, timeout=5)
            git_dir = (root / out.stdout.strip()).resolve()
        except (OSError, subprocess.SubprocessError):
            return "skipped (could not find the Git folder)"
    if not git_dir.is_dir():
        return "skipped (not a Git repository)"
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if any(line.strip() in (f"{KIT_DIR}/", f"/{KIT_DIR}/", KIT_DIR) for line in current.splitlines()):
        return "already hidden from Git"
    with open(exclude, "a", encoding="utf-8") as handle:
        if current and not current.endswith("\n"):
            handle.write("\n")
        handle.write(f"# eng-kit local data\n/{KIT_DIR}/\n")
    return "hidden from Git (.git/info/exclude)"


def init_cmd(root: Path, force: bool) -> int:
    folder = kit(root)
    cfg_path = folder / "config.json"
    if cfg_path.exists() and not force:
        cfg = load_config(root)
        print(f"Already set up: {cfg_path}")
        print(f"Stack: {cfg['stack']} | Test command: {cfg['test_command'] or '(not set)'}")
        print(f"Git: {ensure_excluded(root)}")
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    cfg = default_config(root)
    save_config(root, cfg)
    status = folder / "status.md"
    if not status.exists():
        atomic_write(status, STATUS_TEMPLATE.format(date=dt.date.today().isoformat(), stack=cfg["stack"]))
    (folder / "runs.jsonl").touch()
    found = detect(root)
    print(f"Set up {folder}")
    print(f"Stack: {cfg['stack']}")
    print(f"Test command: {cfg['test_command'] or '(not set)'}")
    print(f"JUnit from: {', '.join(cfg['junit_paths'])}")
    print(f"Git: {ensure_excluded(root)}")
    for note in found["notes"]:
        print(f"Note: {note}")
    return 0


# --------------------------------------------------------------------------- JUnit parsing


def _junit_files(root: Path, paths: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        p = Path(raw)
        p = p if p.is_absolute() else root / p
        if p.is_dir():
            files.extend(sorted(x for x in p.rglob("*.xml") if x.is_file()))
        elif p.is_file():
            files.append(p)
    return files


def _num(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return 0.0


def _bucket_labels() -> List[str]:
    labels, low = [], 0.0
    for high in BUCKETS:
        labels.append(f"{low:g}-{high:g}s")
        low = high
    labels.append(f">{low:g}s")
    return labels


def _bucket(seconds: float) -> str:
    low = 0.0
    for high in BUCKETS:
        if seconds < high:
            return f"{low:g}-{high:g}s"
        low = high
    return f">{low:g}s"


def parse_junit(files: List[Path]) -> Dict[str, Any]:
    import xml.etree.ElementTree as ET

    if not files:
        raise ValueError("no JUnit XML files found")
    classes: Dict[str, Dict[str, float]] = {}
    tests: List[Tuple[str, str, float]] = []
    failures = errors = skipped = 0
    spread = {label: 0 for label in _bucket_labels()}
    digest = hashlib.sha256()
    for path in files:
        data = path.read_bytes()
        digest.update(data)
        try:
            tree = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ValueError(f"{path} is not valid XML ({exc})") from exc
        for case in tree.iter("testcase"):
            cls = case.get("class") or case.get("classname") or case.get("file") or "unknown"
            name = case.get("name") or ""
            seconds = _num(case.get("time"))
            failures += len(case.findall("failure"))
            errors += len(case.findall("error"))
            skipped += len(case.findall("skipped"))
            entry = classes.setdefault(cls, {"tests": 0, "seconds": 0.0})
            entry["tests"] += 1
            entry["seconds"] += seconds
            tests.append((cls, name, seconds))
            spread[_bucket(seconds)] += 1
    count = len(tests)
    total = sum(t[2] for t in tests)
    class_rows = sorted(
        (
            {"class": c, "tests": int(v["tests"]), "seconds": round(v["seconds"], 2), "seconds_per_test": round(v["seconds"] / max(1, v["tests"]), 3)}
            for c, v in classes.items()
        ),
        key=lambda r: r["seconds"],
        reverse=True,
    )
    test_rows = sorted(({"class": c, "test": n, "seconds": round(s, 3)} for c, n, s in tests), key=lambda r: r["seconds"], reverse=True)
    return {
        "tests": count,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": count > 0 and failures == 0 and errors == 0,
        "test_seconds": round(total, 2),
        "seconds_per_test": round(total / count, 3) if count else 0.0,
        "spread": spread,
        "slowest_classes": class_rows[:TOP],
        "slowest_tests": test_rows[:TOP],
        "class_seconds": {r["class"]: r["seconds"] for r in class_rows[:200]},
        "junit_sha256": digest.hexdigest(),
    }


# --------------------------------------------------------------------------- runs


def runs_path(root: Path) -> Path:
    return kit(root) / "runs.jsonl"


def read_runs(root: Path) -> List[Dict[str, Any]]:
    path = runs_path(root)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            with contextlib.suppress(ValueError):
                out.append(json.loads(line))
    return out


def git_info(root: Path) -> Dict[str, Optional[str]]:
    def run(*args: str) -> Optional[str]:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=5)
            return out.stdout.strip() or None if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    return {"branch": run("rev-parse", "--abbrev-ref", "HEAD"), "commit": run("rev-parse", "--short", "HEAD")}


def classify(cfg: Dict[str, Any], runs: List[Dict[str, Any]], tests: int) -> str:
    base = next((r for r in runs if r.get("id") == cfg.get("baseline_run_id")), None)
    reference = base["tests"] if base else max((r.get("tests", 0) for r in runs if r.get("scope") == "full"), default=0)
    if reference and tests < FULL_RUN_RATIO * reference:
        return "partial"
    return "full"


def record(
    root: Path,
    files: List[Path],
    *,
    wall_seconds: Optional[float],
    source: str,
    environment: Optional[str] = None,
    label: str = "",
    command: str = "",
    wall_source: str = "measured",
    ci: Optional[Dict[str, Any]] = None,
    quiet: bool = False,
) -> Optional[Dict[str, Any]]:
    cfg = load_config(root)
    summary = parse_junit(files)
    with locked(kit(root) / ".lock"):
        runs = read_runs(root)
        if any(r.get("junit_sha256") == summary["junit_sha256"] for r in runs):
            if not quiet:
                print("This JUnit report is already recorded; nothing added.")
            return None
        run_id = f"r{len(runs) + 1:04d}-{summary['junit_sha256'][:6]}"
        entry = {
            "id": run_id,
            "recorded_at": now_iso(),
            "source": source,
            "environment": environment or cfg.get("environment"),
            "label": label,
            "command": command,
            "wall_seconds": round(wall_seconds, 1) if wall_seconds is not None else None,
            "wall_source": wall_source if wall_seconds is not None else "unknown",
            "scope": classify(cfg, runs, summary["tests"]),
            "git": git_info(root),
            "ci": ci or None,
            **summary,
        }
        refuse_symlink(runs_path(root))
        with open(runs_path(root), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
        if not cfg.get("baseline_run_id") and entry["scope"] == "full" and entry["passed"] and entry["wall_seconds"]:
            cfg["baseline_run_id"] = run_id
            save_config(root, cfg)
            entry["became_baseline"] = True
    if not quiet:
        print(describe(entry, env_baseline(root, entry["environment"])))
    return entry


def baseline_for(root: Path) -> Optional[Dict[str, Any]]:
    cfg = load_config(root)
    return next((r for r in read_runs(root) if r.get("id") == cfg.get("baseline_run_id")), None)


def fmt_minutes(seconds: Optional[float]) -> str:
    if seconds is None:
        return "n/a"
    return f"{seconds:.1f} s" if seconds < 60 else f"{seconds / 60:.1f} min"


def env_baseline(root: Path, environment: Optional[str]) -> Optional[Dict[str, Any]]:
    """Like-with-like: the configured baseline if it ran in this environment, else the first full passed run there."""
    base = baseline_for(root)
    if base and base.get("environment") == environment:
        return base
    return next(
        (r for r in read_runs(root) if r.get("environment") == environment and r.get("scope") == "full" and r.get("passed") and r.get("wall_seconds")),
        None,
    )


def change(run: Dict[str, Any], base: Optional[Dict[str, Any]]) -> Optional[float]:
    if not base or base.get("id") == run.get("id") or not run.get("wall_seconds") or not base.get("wall_seconds"):
        return None
    if base.get("environment") != run.get("environment"):
        return None
    return 1 - run["wall_seconds"] / base["wall_seconds"]


def describe(run: Dict[str, Any], base: Optional[Dict[str, Any]]) -> str:
    result = "passed" if run["passed"] else f"not passed ({run['failures']} failures, {run['errors']} errors)"
    line = f"Recorded {run['id']}: {run['tests']} tests, {result}, {fmt_minutes(run.get('wall_seconds'))} on {run['environment']} [{run['scope']}]"
    delta = change(run, base)
    if run.get("became_baseline"):
        line += " — set as the baseline"
    elif delta is not None:
        line += f" — {abs(delta) * 100:.0f}% {'faster' if delta >= 0 else 'slower'} than the baseline for {run['environment']} ({base['id']})"
    return line


# --------------------------------------------------------------------------- measure


def measure_cmd(root: Path, command: Optional[str], label: str) -> int:
    cfg = load_config(root)
    cmd = command or cfg.get("test_command")
    if not cmd:
        fail("no test command. Set one: config set test_command '<command>'")
    files_before = {p: p.stat().st_mtime for p in _junit_files(root, cfg["junit_paths"])}
    log = kit(root) / "last-run.log"
    print(f"Running: {cmd}\nOutput: {log}", flush=True)
    start = time.monotonic()
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.run(cmd, shell=True, cwd=root, stdout=out, stderr=subprocess.STDOUT)
    wall = time.monotonic() - start
    files = [p for p in _junit_files(root, cfg["junit_paths"]) if files_before.get(p) != p.stat().st_mtime]
    if not files:
        print(f"The command finished in {wall / 60:.1f} min (exit {proc.returncode}) but wrote no new JUnit XML to {cfg['junit_paths']}.")
        print(f"Last lines of the output:\n{_tail(log)}")
        return proc.returncode or 1
    record(root, files, wall_seconds=wall, source="local", label=label, command=cmd)
    if proc.returncode != 0:
        print(f"The test command exited with {proc.returncode}. Output: {log}")
    return proc.returncode


def _tail(path: Path, lines: int = 20) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="ignore").splitlines()[-lines:])
    except OSError:
        return ""


# --------------------------------------------------------------------------- GitLab import


def _token(root: Path, cfg: Dict[str, Any], provider: str = "gitlab") -> str:
    """The token, read at call time: an environment variable, else a KEY=value line in a file. Never stored."""
    ci = cfg.get("ci", {})
    if provider == "github":
        env_name = ci.get("github_token_env") or "GITHUB_TOKEN"
        token_file, key = ci.get("github_token_file"), ci.get("github_token_key") or env_name
    else:
        env_name = ci.get("token_env") or "GITLAB_TOKEN"
        token_file, key = ci.get("token_file"), ci.get("token_key") or env_name
    if os.environ.get(env_name):
        return os.environ[env_name].strip()
    if token_file:
        path = Path(os.path.expanduser(token_file))
        path = path if path.is_absolute() else root / path
        with contextlib.suppress(OSError):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    where = "ci.github_token_file" if provider == "github" else "ci.token_file"
    fail(f"no {'GitHub' if provider == 'github' else 'GitLab'} token. Export {env_name}, or set {where} to a file that holds {key}=…")
    return ""


def _remote_project(root: Path) -> Optional[str]:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return project_from_url(url)


def project_from_url(url: str) -> Optional[str]:
    """group/name from an https or ssh remote; ignores any user:token@ part so a token never leaks into it."""
    url = url.strip()
    if not url:
        return None
    if "://" in url:
        import urllib.parse

        path = urllib.parse.urlparse(url).path
    else:  # scp-like: git@host:group/name.git
        path = url.split(":", 1)[1] if ":" in url else ""
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path or None


def _api(host: str, project: str, path: str, token: str) -> Any:
    import socket
    import urllib.error
    import urllib.parse
    import urllib.request

    url = f"{host.rstrip('/')}/api/v4/projects/{urllib.parse.quote(project, safe='')}{path}"
    check_host(url)
    request = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token, "User-Agent": f"eng-kit/{VERSION}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 (https host from config)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 502, 503, 504) and attempt < 4:
                wait = exc.headers.get("Retry-After") if exc.headers else None
                time.sleep(min(60.0, float(wait)) if wait and wait.isdigit() else 2 ** attempt)
                continue
            reasons = {401: "the token is missing or expired", 403: "the token lacks the read_api scope or access to the project",
                       404: "the project path or id is wrong (config set ci.project group/name)", 429: "GitLab's rate limit; try again in a few minutes"}
            fail(f"GitLab answered {exc.code} for {path.split('?')[0]}: {reasons.get(exc.code, 'unexpected answer')}.")
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            if attempt < 4:
                time.sleep(2 ** attempt)
                continue
            fail(f"could not reach GitLab ({getattr(exc, 'reason', exc)}).")
    return None


def _report_to_junit(report: Dict[str, Any]) -> bytes:
    import xml.etree.ElementTree as ET

    root = ET.Element("testsuites")
    for suite in report.get("test_suites", []):
        node = ET.SubElement(root, "testsuite", name=str(suite.get("name", "")))
        for case in suite.get("test_cases", []):
            tc = ET.SubElement(
                node,
                "testcase",
                classname=str(case.get("classname") or suite.get("name") or "unknown"),
                name=str(case.get("name", "")),
                time=str(case.get("execution_time") or 0),
            )
            status = case.get("status")
            if status == "failed":
                ET.SubElement(tc, "failure")
            elif status == "error":
                ET.SubElement(tc, "error")
            elif status == "skipped":
                ET.SubElement(tc, "skipped")
    return ET.tostring(root, encoding="utf-8")


def ci_provider(root: Path, cfg: Dict[str, Any], ref: str = "") -> str:
    """gitlab or github: from a github.com URL in ref, else ci.provider when set explicitly, else the origin remote."""
    if "github.com" in ref:
        return "github"
    if "/-/jobs/" in ref:
        return "gitlab"
    provider = (cfg.get("ci") or {}).get("provider")
    if provider in ("gitlab", "github") and (cfg.get("ci") or {}).get("provider_set"):
        return provider
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        url = ""
    if "github.com" in url:
        return "github"
    return provider or "gitlab"


def import_ci_cmd(root: Path, ref: str, label: str) -> int:
    cfg = load_config(root)
    if ci_provider(root, cfg, ref) == "github":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import github  # noqa: E402

        return github.import_run(root, cfg, ref, label)
    ci = cfg.get("ci", {})
    host = ci.get("host") or "https://gitlab.com"
    project = ci.get("project") or _remote_project(root)
    if not project:
        fail("could not tell the GitLab project. Set it: config set ci.project group/name")
    url_project = re.search(r"https?://[^/]+/(.+?)/-/jobs/", ref)
    if url_project:
        project = url_project.group(1)
    token = _token(root, cfg)
    if ref.strip().lower() == "latest":
        name = ci.get("job_name") or "tests"
        jobs = _api(host, project, "/jobs?scope[]=success&scope[]=failed&per_page=50", token) or []
        job_found = next((j for j in jobs if j.get("name") == name), None)
        if not job_found:
            fail(f"no finished job named {name!r} among the last 50 jobs (set ci.job_name if your test job has another name).")
        ref = str(job_found["id"])
    match = re.search(r"/-/jobs/(\d+)", ref) or re.fullmatch(r"\s*(\d+)\s*", ref)
    if not match:
        fail("give a GitLab job id, a job URL (…/-/jobs/<id>) or 'latest'.")
    job_id = match.group(1)
    job = _api(host, project, f"/jobs/{job_id}", token)
    pipeline_id = (job.get("pipeline") or {}).get("id")
    if not pipeline_id:
        fail(f"job {job_id} has no pipeline.")
    report = _api(host, project, f"/pipelines/{pipeline_id}/test_report", token)
    if not report or not report.get("total_count"):
        fail(f"pipeline {pipeline_id} has no test report. The job must publish artifacts:reports:junit.")
    folder = kit(root) / "ci"
    folder.mkdir(parents=True, exist_ok=True)
    xml_path = folder / f"pipeline-{pipeline_id}.xml"
    xml_path.write_bytes(_report_to_junit(report))
    runner = job.get("runner") or {}
    environment = "CI shared runners" if runner.get("is_shared") else f"CI runner {runner.get('description') or 'project'}".strip()
    record(
        root,
        [xml_path],
        wall_seconds=job.get("duration"),
        source="ci",
        environment=environment,
        label=label or f"{job.get('ref', '')} job {job_id}".strip(),
        command=job.get("name", ""),
        wall_source="ci-job-duration",
        ci={"provider": "gitlab", "job_id": int(job_id), "pipeline_id": pipeline_id, "url": job.get("web_url"), "finished_at": job.get("finished_at")},
    )
    return 0


# --------------------------------------------------------------------------- status, baseline, export


def status_data(root: Path) -> Dict[str, Any]:
    cfg = load_config(root)
    runs = read_runs(root)
    full = [r for r in runs if r.get("scope") == "full" and r.get("passed") and r.get("wall_seconds")]
    base = baseline_for(root)
    latest = full[-1] if full else None
    latest_base = env_baseline(root, latest.get("environment")) if latest else None
    per_env = {}
    for r in full:
        per_env[r["environment"]] = r
    environments = []
    for env, last in per_env.items():
        b = env_baseline(root, env)
        environments.append({"environment": env, "baseline_minutes": round(b["wall_seconds"] / 60, 1) if b else None,
                             "latest_minutes": round(last["wall_seconds"] / 60, 1), "change": change(last, b), "latest_run": last["id"],
                             "baseline_seconds": b["wall_seconds"] if b else None, "latest_seconds": last["wall_seconds"]})
    return {
        "project": root.name,
        "stack": cfg.get("stack"),
        "runs": len(runs),
        "full_runs": len(full),
        "baseline": base,
        "latest": latest,
        "latest_baseline": latest_base,
        "change": change(latest, latest_base) if latest else None,
        "environments": environments,
        "targets": cfg.get("targets"),
    }


def status_cmd(root: Path, as_json: bool) -> int:
    data = status_data(root)
    if as_json:
        print(json.dumps(data, indent=2, default=str))
        return 0
    base, latest = data["baseline"], data["latest"]
    print(f"{data['project']} ({data['stack']}): {data['runs']} runs recorded, {data['full_runs']} full and passed")
    print(f"Baseline: {fmt_minutes(base['wall_seconds']) if base else 'not set'}" + (f" on {base['environment']} ({base['id']})" if base else ""))
    if latest:
        delta = data["change"]
        tail = "" if delta is None else f" — {abs(delta) * 100:.0f}% {'faster' if delta >= 0 else 'slower'} than its environment's baseline"
        print(f"Latest:   {fmt_minutes(latest['wall_seconds'])} on {latest['environment']} ({latest['id']}, {latest['tests']} tests){tail}")
        for e in data["environments"]:
            delta_e = e["change"]
            note = "" if delta_e is None else f", {abs(delta_e) * 100:.0f}% {'faster' if delta_e >= 0 else 'slower'}"
            print(f"  {e['environment']}: latest {fmt_minutes(e['latest_seconds'])}, baseline {fmt_minutes(e['baseline_seconds'])}{note}")
        wall_per_test = latest["wall_seconds"] / latest["tests"] if latest.get("tests") else None
        print(f"Wall time per test: {wall_per_test:.2f} s | test time per test, summed over all workers: {latest['seconds_per_test']:.2f} s"
              if wall_per_test is not None else f"Test time per test, summed over all workers: {latest['seconds_per_test']:.2f} s")
        print(f"Slowest class: {latest['slowest_classes'][0]['class'] if latest['slowest_classes'] else 'n/a'}")
    else:
        print("Latest:   no full passed run yet")
    return 0


def baseline_cmd(root: Path, ref: Optional[str]) -> int:
    cfg = load_config(root)
    runs = read_runs(root)
    if ref is None:
        base = baseline_for(root)
        print(base["id"] if base else "not set")
        return 0
    if ref == "clear":
        cfg["baseline_run_id"] = None
    else:
        candidates = [r for r in runs if r.get("scope") == "full" and r.get("passed")]
        run = candidates[-1] if ref == "latest" and candidates else next((r for r in runs if r.get("id") == ref), None)
        if not run:
            fail(f"no run {ref!r}. See: status --json or export")
        cfg["baseline_run_id"] = run["id"]
    save_config(root, cfg)
    print(f"baseline = {cfg['baseline_run_id']}")
    return 0


def export_cmd(root: Path, fmt: str) -> int:
    runs = read_runs(root)
    if fmt == "json":
        print(json.dumps(runs, indent=2))
        return 0
    import csv

    cols = ["id", "recorded_at", "source", "environment", "label", "scope", "tests", "failures", "errors", "skipped", "passed", "wall_seconds", "seconds_per_test"]
    writer = csv.DictWriter(sys.stdout, fieldnames=cols + ["branch", "commit"], extrasaction="ignore")
    writer.writeheader()
    for run in runs:
        writer.writerow({**run, "branch": (run.get("git") or {}).get("branch"), "commit": (run.get("git") or {}).get("commit")})
    return 0


# --------------------------------------------------------------------------- hook


JUNIT_IN_COMMAND = re.compile(
    r"(?:--log-junit[ =]|--junitxml[ =]|--junit-xml[ =]|--outputFile\.junit[ =]|--junitfile[ =]|JEST_JUNIT_OUTPUT_FILE=)([^\s;&|]+)"
)


def junit_paths_in(command: str) -> List[str]:
    """JUnit files a test command says it will write (PHPUnit/Pest/ParaTest, pytest, Vitest, gotestsum, jest-junit)."""
    return [m.strip("'\"") for m in JUNIT_IN_COMMAND.findall(command)][:5]


def hook_cmd(phase: str, payload: Optional[Dict[str, Any]] = None) -> int:
    """Never blocks Claude: any problem is logged to .eng-kit/hook-errors.log and the hook exits 0."""
    if payload is None:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            return 0
    root_hint = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    if not root_hint or payload.get("tool_name") not in (None, "Bash"):
        return 0
    start = Path(root_hint)
    folder = None
    for candidate in [start, *start.parents]:
        if (candidate / KIT_DIR / "config.json").is_file():
            if not (candidate / KIT_DIR).is_symlink():
                folder = candidate
            break
        if (candidate / ".git").exists():
            break  # stop at the repository root
    if folder is None:
        return 0
    try:
        cfg = load_config(folder)
        if not (cfg.get("hook") or {}).get("enabled", True):
            return 0
        pending_path = kit(folder) / ".pending.json"
        pending = _read_json(pending_path)
        command = str((payload.get("tool_input") or {}).get("command") or "")
        if phase == "pre":
            if TEST_COMMAND_RE.search(command):
                pending = {k: v for k, v in pending.items() if time.time() - v.get("start", 0) < 6 * 3600}
                key = payload.get("tool_use_id") or hashlib.sha1(command.encode()).hexdigest()[:12]
                pending[key] = {"start": time.time(), "command": command[:500], "junit": junit_paths_in(command)}
                atomic_write(pending_path, json.dumps(pending))
            return 0
        seen_path = kit(folder) / ".seen.json"
        seen = _read_json(seen_path)
        watched = list(cfg.get("junit_paths") or [])
        for entry in pending.values():
            watched += [p for p in entry.get("junit") or [] if p not in watched]
        files = _junit_files(folder, watched)
        fresh = [p for p in files if p.stat().st_mtime > seen.get(str(p.resolve()), 0)]
        if not fresh:
            return 0
        newest = max(p.stat().st_mtime for p in fresh)
        starts = [(v["start"], k, v) for k, v in pending.items() if v.get("start", 0) <= newest]
        if not starts:
            for p in fresh:
                seen[str(p.resolve())] = p.stat().st_mtime
            atomic_write(seen_path, json.dumps(seen))
            return 0
        start_at, key, info = max(starts)
        same_call = key == payload.get("tool_use_id")
        wall = (time.time() if same_call else newest) - start_at
        try:
            record(folder, fresh, wall_seconds=wall, source="agent", command=info.get("command", ""), wall_source="hook" if same_call else "hook-estimate", label="recorded by hook", quiet=True)
        finally:
            for p in fresh:
                seen[str(p.resolve())] = p.stat().st_mtime
            atomic_write(seen_path, json.dumps(seen))
            pending.pop(key, None)
            atomic_write(pending_path, json.dumps(pending))
    except SystemExit:
        return 0
    except Exception as exc:  # pragma: no cover - defensive: a hook must never break the session
        with contextlib.suppress(OSError):
            if not (kit(folder) / "hook-errors.log").is_symlink():
              with open(kit(folder) / "hook-errors.log", "a", encoding="utf-8") as log:
                log.write(f"{now_iso()} {phase}: {type(exc).__name__}: {exc}\n")
    return 0


# --------------------------------------------------------------------------- main


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="engkit", description="Local test-speed tracking per project.")
    parser.add_argument("--project", help="project folder (default: the Git top level of the current folder)")
    parser.add_argument("--version", action="version", version=f"eng-kit {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("detect")
    p = sub.add_parser("init")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("config")
    p.add_argument("action", choices=["get", "set"])
    p.add_argument("key")
    p.add_argument("value", nargs="?")
    p = sub.add_parser("record")
    p.add_argument("paths", nargs="+")
    p.add_argument("--wall-seconds", type=float)
    p.add_argument("--wall-minutes", type=float)
    p.add_argument("--source", default="local", choices=["local", "ci", "agent"])
    p.add_argument("--environment")
    p.add_argument("--label", default="")
    p = sub.add_parser("measure")
    p.add_argument("--command")
    p.add_argument("--label", default="")
    p = sub.add_parser("import-ci")
    p.add_argument("ref")
    p.add_argument("--label", default="")
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("baseline")
    p.add_argument("ref", nargs="?")
    p = sub.add_parser("dashboard")
    p.add_argument("--no-open", action="store_true")
    p.add_argument("--out")
    p = sub.add_parser("export")
    p.add_argument("--format", default="csv", choices=["csv", "json"])
    p = sub.add_parser("analyze")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("plan")
    p.add_argument("action", choices=["set", "show"])
    p.add_argument("item", nargs="?")
    p.add_argument("state", nargs="?")
    p.add_argument("--run")
    p.add_argument("--note", default="")
    p = sub.add_parser("release-speed")
    p.add_argument("--days", type=int)
    p.add_argument("--staging")
    p.add_argument("--production")
    p.add_argument("--environment")
    p.add_argument("--json", action="store_true")
    p.add_argument("--list", action="store_true", help="print every merge request counted and left out")
    p = sub.add_parser("report")
    p.add_argument("--anonymous", action="store_true", help="leave out project, labels, commits and runner names")
    p.add_argument("--out")
    p = sub.add_parser("hook")
    p.add_argument("phase", choices=["pre", "post"])
    args = parser.parse_args(argv)

    if args.cmd == "hook":
        return hook_cmd(args.phase)
    root = project_root(args.project)
    if args.cmd == "detect":
        print(json.dumps(detect(root), indent=2))
        return 0
    if args.cmd == "init":
        return init_cmd(root, args.force)
    if args.cmd == "config":
        return config_cmd(root, args.action, args.key, args.value)
    if args.cmd == "record":
        files = _junit_files(root, args.paths)
        if not files:
            fail(f"no JUnit XML found at {args.paths}")
        wall = args.wall_seconds if args.wall_seconds is not None else (args.wall_minutes * 60 if args.wall_minutes is not None else None)
        try:
            record(root, files, wall_seconds=wall, source=args.source, environment=args.environment, label=args.label)
        except ValueError as exc:
            fail(str(exc))
        return 0
    if args.cmd == "measure":
        return measure_cmd(root, args.command, args.label)
    if args.cmd == "import-ci":
        return import_ci_cmd(root, args.ref, args.label)
    if args.cmd == "status":
        return status_cmd(root, args.json)
    if args.cmd == "baseline":
        return baseline_cmd(root, args.ref)
    if args.cmd == "export":
        return export_cmd(root, args.format)
    if args.cmd in ("analyze", "plan", "release-speed", "report"):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    if args.cmd == "report":
        import report

        return report.report_cmd(root, args.anonymous, args.out)
    if args.cmd == "analyze":
        import analyze

        return analyze.analyze_cmd(root, args.json)
    if args.cmd == "plan":
        import analyze

        if args.action == "show":
            path = kit(root) / "plan.md"
            print(path.read_text(encoding="utf-8") if path.exists() else "No plan yet. Run: analyze")
            return 0
        if not args.item or not args.state:
            fail("usage: plan set <item> <open|applied|verified|skipped> [--run RUN_ID] [--note TEXT]")
        return analyze.plan_set_cmd(root, args.item, args.state, args.run, args.note)
    if args.cmd == "release-speed":
        import release

        rc = (load_config(root).get("release") or {})
        return release.release_speed_cmd(
            root,
            args.days or rc.get("window_days") or 30,
            args.staging or rc.get("staging_branch") or "staging",
            args.production or rc.get("production_branch") or "main",
            args.environment or rc.get("environment"),
            args.json,
            args.list,
        )
    if args.cmd == "dashboard":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from dashboard import build_dashboard  # noqa: E402

        return build_dashboard(root, open_browser=not args.no_open, out=args.out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
