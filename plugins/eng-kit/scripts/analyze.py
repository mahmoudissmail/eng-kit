"""eng-kit analyzer: measurements + project signals -> a ranked, evidence-based optimization plan.

Read-only. It inspects the latest recorded runs and a few project files (test code, test config, CI
config), and writes `.eng-kit/analysis.json` and `.eng-kit/plan.md`. Each finding names its evidence,
the change, the expected gain, the risk and how to verify it. Item states are kept across re-runs.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import engkit

GAIN_ORDER = {"high": 0, "medium": 1, "low": 2, "guard": 3}
STATES = ("open", "applied", "verified", "skipped")
MAX_FILES = 4000


def _text(path: Path, limit: int = 400_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except OSError:
        return ""


def _files(root: Path, folders: Iterable[str], patterns: Iterable[str]) -> List[Path]:
    out: List[Path] = []
    for folder in folders:
        base = root / folder
        if not base.is_dir():
            continue
        for pattern in patterns:
            for p in base.rglob(pattern):
                if "node_modules" in p.parts or "vendor" in p.parts:
                    continue
                out.append(p)
                if len(out) >= MAX_FILES:
                    return out
    return out


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


class Finding(dict):
    pass


def finding(fid: str, gain: str, title: str, evidence: List[str], change: str, expected: str, risk: str, verify: str, area: str) -> Finding:
    return Finding(id=fid, gain=gain, area=area, title=title, evidence=evidence, change=change, expected=expected, risk=risk, verify=verify)


# --------------------------------------------------------------------------- checks from measurements


def check_runs(cfg: Dict[str, Any], runs: List[Dict[str, Any]]) -> List[Finding]:
    out: List[Finding] = []
    full = [r for r in runs if r.get("scope") == "full" and r.get("passed")]
    if not full:
        out.append(finding(
            "measure-baseline", "high", "Record a full, passed run first",
            ["No full passed run is recorded, so no change can be measured."],
            "Run /eng-kit:import-ci <job> for the CI gate and/or /eng-kit:measure locally.",
            "Makes every later change measurable.", "None.", "/eng-kit:status shows a baseline.", "measure"))
        return out
    latest = full[-1]
    # Wall clock per test when known: parallel workers sharing the CPU inflate each test's own measured time,
    # so the summed figure alone would keep flagging a suite that is already fast.
    wall_per_test = (latest["wall_seconds"] / latest["tests"]) if latest.get("wall_seconds") and latest.get("tests") else None
    per_test = wall_per_test if wall_per_test is not None else (latest.get("seconds_per_test") or 0)
    basis = "wall clock" if wall_per_test is not None else "summed test time"
    if per_test >= 1.0:
        out.append(finding(
            "setup-cost", "high", "Tests spend most of their time in setup",
            [f"{per_test:.2f} s per test ({basis}) over {latest['tests']:,} tests (run {latest['id']}).",
             "Above ~1 s per test usually means repeated setup (seeding, app boot, real I/O), not assertions."],
            "Move shared reference data to once per database/worker; create only the rows each test reads; fake network, clock and sleeps.",
            "Often 40-80% less time per test (published cases: -73%, -87%).",
            "Low if each test still creates what it reads; tests that relied on seeded data need their own setup.",
            "Re-run the full suite; compare seconds per test and wall time against the baseline.", "setup"))
    spread = latest.get("spread") or {}
    total = sum(spread.values()) or 1
    slow = spread.get("5-10s", 0) + spread.get(">10s", 0)
    if slow / total >= 0.2:
        out.append(finding(
            "slow-share", "medium", "A large share of tests take over 5 s",
            [f"{slow:,} of {total:,} tests ({slow / total:.0%}) took over 5 s in run {latest['id']}."],
            "Start with the slowest classes on the dashboard: check what their setUp does and what each test boots.",
            "Proportional to the share fixed.", "Low.", "Spread moves left on the dashboard.", "setup"))
    classes = latest.get("slowest_classes") or []
    test_seconds = latest.get("test_seconds") or 0
    if classes and test_seconds:
        top = classes[:10]
        share = sum(c["seconds"] for c in top) / test_seconds
        if share >= 0.25:
            out.append(finding(
                "hot-classes", "medium", "Ten classes hold a large part of the test time",
                [f"Top 10 classes = {share:.0%} of summed test time; slowest: {top[0]['class']} ({top[0]['seconds']:.0f} s, {top[0]['seconds_per_test']:.1f} s/test)."],
                "Fix setup in these classes first; split very large classes so parallel workers balance.",
                "Up to the share they hold.", "Low.", "Their seconds drop in 'Slowest classes — latest against baseline'.", "setup"))
    envs: Dict[str, Dict[str, Any]] = {}
    for r in full:
        if r.get("wall_seconds"):
            envs[r["environment"]] = r
    ci = [r for e, r in envs.items() if e.startswith("CI")]
    local = [r for e, r in envs.items() if not e.startswith("CI")]
    if ci and local:
        c, l = ci[-1], local[-1]
        if c["wall_seconds"] > 1.5 * l["wall_seconds"]:
            out.append(finding(
                "ci-cores", "high", "CI is much slower than a local run of the same suite",
                [f"{c['environment']}: {c['wall_seconds'] / 60:.1f} min vs {l['environment']}: {l['wall_seconds'] / 60:.1f} min ({c['wall_seconds'] / l['wall_seconds']:.1f}x)."],
                "Run the test job on a runner with more cores (self-hosted or larger runner) and set the worker count to its cores.",
                f"Up to {1 - l['wall_seconds'] / c['wall_seconds']:.0%} on hardware alone (measured gap).",
                "Runner availability; keep a fallback job on the old runner.",
                "Import the next CI run; compare with the baseline.", "ci"))
    return out


# --------------------------------------------------------------------------- checks from project files


SETUP_START = re.compile(r"function\s+setUp\s*\([^)]*\)[^{;]*\{")


def _php_method_body(code: str, open_brace: int) -> str:
    """Text between a method's braces, counting nested braces and skipping strings and comments."""
    depth, i, n = 0, open_brace, len(code)
    while i < n:
        ch = code[i]
        if ch in "'\"":
            quote, i = ch, i + 1
            while i < n and code[i] != quote:
                i += 2 if code[i] == "\\" else 1
        elif code.startswith("//", i) or ch == "#":
            i = code.find("\n", i)
            i = n if i < 0 else i
        elif code.startswith("/*", i):
            i = code.find("*/", i + 2)
            i = n if i < 0 else i + 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return code[open_brace + 1 : i]
        i += 1
    return code[open_brace + 1 :]


def seeds_in_setup(code: str) -> bool:
    """True when a setUp() method body calls ->seed( (directly or inside a closure it defines)."""
    for match in SETUP_START.finditer(code):
        if "->seed(" in _php_method_body(code, match.end() - 1):
            return True
    return False
JS_SEED_IN_EACH = re.compile(r"beforeEach\s*\((?:(?!\bit\(|\btest\().){0,800}?\b(seed|migrate|truncate)\w*\s*\(", re.S)
PY_FUNC_FIXTURE_LOAD = re.compile(r"@pytest\.fixture(?:\(\s*(?:autouse\s*=\s*True)?\s*\))?\s*\n\s*def\s+\w+\([^)]*\):(?:(?!\ndef\s).){0,600}?(loaddata|call_command\(\s*['\"]loaddata|seed|bulk_create)", re.S)


def check_laravel(root: Path, cfg: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    composer = engkit._read_json(root / "composer.json")
    deps = {**(composer.get("require") or {}), **(composer.get("require-dev") or {})}
    tests = _files(root, ["tests"], ["*Test.php"])
    seeding = [p for p in tests if seeds_in_setup(_text(p))]
    if seeding:
        sample = ", ".join(_rel(root, p) for p in seeding[:3])
        out.append(finding(
            "seed-once", "high", "Reference data is seeded in setUp() of every test",
            [f"{len(seeding)} of {len(tests)} test files call ->seed(...) inside setUp(), e.g. {sample}."],
            "Seed reference data once per test database ($seed/$seeder, #[Seed], or ParallelTesting::setUpTestDatabase) and clear caches that hold it per test (spatie: forgetCachedPermissions()). Remove the per-test seed calls.",
            "Often the largest single gain in Laravel suites (40-80% per test).",
            "Tests that change the seeded data must still run in a transaction (RefreshDatabase); tests asserting counts of seeded rows need review.",
            "Full suite: seconds per test and wall time against the baseline; a guard test then forbids per-test seeding.", "setup"))
    if "brianium/paratest" not in deps:
        out.append(finding(
            "parallel", "high", "The suite runs in one process",
            ["brianium/paratest is not in composer.json."],
            "composer require --dev brianium/paratest, then php artisan test --parallel (one database per process).",
            "Close to the number of cores, minus setup and DB contention.",
            "Exposes order-dependent tests; fix them (see parallel-safety).",
            "Full run in parallel; record it.", "parallel"))
    elif "--parallel" not in (cfg.get("test_command") or "") and not _ci_text(root).count("--parallel"):
        out.append(finding(
            "parallel-flag", "high", "ParaTest is installed but the suite is not run with --parallel",
            ["Neither the eng-kit test command nor the CI file uses --parallel."],
            "Use php artisan test --parallel locally and in CI.", "Close to the number of cores.",
            "Exposes order-dependent tests.", "Record a parallel run.", "parallel"))
    base = _text(root / "tests" / "TestCase.php")
    missing = [name for name, needle in (("Http::preventStrayRequests()", "preventStrayRequests"), ("Sleep::fake()", "Sleep::fake")) if needle not in base]
    if missing:
        out.append(finding(
            "base-fakes", "medium", "The base TestCase does not block real network calls or sleeps",
            [f"tests/TestCase.php has no {' or '.join(missing)}."],
            "Add Http::preventStrayRequests() and Sleep::fake() in the base TestCase setUp (opt out per test where real behaviour is under test).",
            "Removes slow outliers (real HTTP, retries with sleep) and makes missing fakes fail loudly.",
            "Tests that relied on a real call fail and need an Http::fake for that endpoint.",
            "Slowest tests list loses its network-bound outliers.", "setup"))
    phpunit = _text(root / "phpunit.xml") or _text(root / "phpunit.xml.dist")
    env_missing = [k for k, pat in (
        ("BCRYPT_ROUNDS=4", r'BCRYPT_ROUNDS"\s+value="4"'),
        ("CACHE_STORE/CACHE_DRIVER=array", r'CACHE_(STORE|DRIVER)"\s+value="array"'),
        ("SESSION_DRIVER=array", r'SESSION_DRIVER"\s+value="array"'),
        ("QUEUE_CONNECTION=sync", r'QUEUE_CONNECTION"\s+value="sync"'),
        ("MAIL_MAILER=array", r'MAIL_MAILER"\s+value="array"'),
    ) if phpunit and not re.search(pat, phpunit)]
    if env_missing:
        out.append(finding(
            "phpunit-env", "medium", "phpunit.xml misses fast test settings",
            [f"Not set: {', '.join(env_missing)}."],
            "Add them under <php><env …/> in phpunit.xml.", "Small to medium; hashing and real drivers add up per test.",
            "Low.", "Seconds per test after the change.", "runtime"))
    obs = [name for name, needle in (("Telescope", "laravel/telescope"), ("Pulse", "laravel/pulse"), ("Nightwatch", "laravel/nightwatch")) if needle in deps]
    obs_off = [name for name in obs if re.search(rf'{name.upper()}_ENABLED"\s+value="false"', phpunit)]
    if obs and set(obs) - set(obs_off):
        out.append(finding(
            "observability-off", "medium", "Observability tools may run during tests",
            [f"Installed: {', '.join(obs)}; not switched off in phpunit.xml: {', '.join(sorted(set(obs) - set(obs_off)))}."],
            "Set <NAME>_ENABLED=false in phpunit.xml.", "Small to medium.", "Low.", "Seconds per test.", "runtime"))
    if not re.search(r"WithCachedRoutes|WithCachedConfig", base):
        out.append(finding(
            "cached-boot", "low", "The app boots routes and config from scratch in every test",
            ["tests/TestCase.php does not use WithCachedRoutes / WithCachedConfig (Laravel 12.38+)."],
            "Add the traits to the base TestCase if the Laravel version has them; check they work with --parallel.",
            "-10 to -30% in route-heavy apps (one published case: 7:52 -> 4:28).",
            "Reported to break under --parallel in some versions: run the parallel suite before keeping it.",
            "Full parallel run against the baseline.", "runtime"))
    migrations = list((root / "database" / "migrations").glob("*.php")) if (root / "database" / "migrations").is_dir() else []
    schema_dir = root / "database" / "schema"
    has_dump = schema_dir.is_dir() and any(schema_dir.glob("*.sql"))
    if len(migrations) >= 80 and not has_dump:
        out.append(finding(
            "schema-dump", "low", "Each test database is built by running every migration",
            [f"{len(migrations)} migrations; no database/schema/*.sql dump."],
            "php artisan schema:dump (optionally --prune) for the test connection, committed.",
            "Faster first migration per parallel database and per CI job.",
            "The dump must be refreshed when migrations change; dump for the connection tests use.",
            "Time to first test in the CI log.", "database"))
    if shutil.which("php"):
        try:
            mods = subprocess.run(["php", "-m"], capture_output=True, text=True, timeout=10).stdout.lower()
            if "xdebug" in mods:
                out.append(finding(
                    "xdebug", "medium", "Xdebug is loaded for local PHP",
                    ["php -m lists xdebug on this machine."],
                    "Run tests with XDEBUG_MODE=off (or without the extension); use PCOV only for coverage runs.",
                    "Often -20 to -50% when Xdebug is active.", "None for normal runs.", "Measure the same suite before/after.", "runtime"))
        except (OSError, subprocess.SubprocessError):
            pass
    if not re.search(r'executionOrder="random"', phpunit) and "order-by=random" not in _ci_text(root):
        out.append(finding(
            "random-order", "guard", "No random-order run catches order-dependent tests",
            ["Neither phpunit.xml nor CI runs tests in random order."],
            "Add a scheduled (nightly) CI job: --order-by=random --random-order-seed=$CI_PIPELINE_ID; print the seed.",
            "Keeps parallel runs stable as the suite grows.", "None (does not block merges).",
            "The nightly job runs green or names the seed that fails.", "guard"))
    if seeding or not _has_guard(root):
        out.append(finding(
            "guard-tests", "guard", "No guard keeps the speed rules from slipping back",
            ["No test checks for per-test seeding or slow new tests."],
            "Add a guard test that fails when a test seeds reference data in setUp, and a CI step that reports tests over the speed budget.",
            "Protects every gain above.", "None.", "The guard fails on a deliberately bad test, then passes.", "guard"))
    return out


def check_js(root: Path, cfg: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    pkg = engkit._read_json(root / "package.json")
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    tests = [p for p in _files(root, ["src", "test", "tests", "__tests__", "app", "packages"], ["*.test.*", "*.spec.*"])]
    seeding = [p for p in tests if JS_SEED_IN_EACH.search(_text(p))]
    if seeding:
        out.append(finding(
            "seed-once", "high", "Data is seeded or migrated in beforeEach",
            [f"{len(seeding)} test files seed/migrate/truncate in beforeEach, e.g. {_rel(root, seeding[0])}."],
            "Seed shared data once (globalSetup / beforeAll per worker), wrap each test in a transaction or clean only its own rows.",
            "Often 40-80% per test.", "Tests that mutate shared rows need their own data.", "Seconds per test vs baseline.", "setup"))
    if "jest" in deps and "jest-junit" not in deps:
        out.append(finding(
            "jest-junit", "high", "Jest cannot write JUnit XML yet",
            ["jest-junit is not a dev dependency."], "npm i -D jest-junit (needed to measure).",
            "Makes runs measurable.", "None.", "/eng-kit:measure records a run.", "measure"))
    if "msw" not in deps and "nock" not in deps:
        out.append(finding(
            "network-fakes", "low", "No HTTP mocking library found",
            ["Neither msw nor nock is a dependency."],
            "Mock HTTP and fail on unhandled requests (msw onUnhandledRequest: 'error').",
            "Removes slow, flaky real calls.", "Tests relying on real calls need mocks.", "Slowest tests list.", "setup"))
    return out


def check_python(root: Path, cfg: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    text = " ".join(_text(root / n) for n in ("pyproject.toml", "setup.cfg", "requirements.txt", "requirements-dev.txt", "pytest.ini", "tox.ini"))
    if "pytest-xdist" not in text and "-n " not in (cfg.get("test_command") or ""):
        out.append(finding(
            "parallel", "high", "pytest runs in one process",
            ["pytest-xdist is not listed."], "Add pytest-xdist and run pytest -n auto (one database per worker via worker_id).",
            "Close to the number of cores.", "Exposes order-dependent tests.", "Record a parallel run.", "parallel"))
    conftests = _files(root, ["."], ["conftest.py"])
    loaders = [p for p in conftests if PY_FUNC_FIXTURE_LOAD.search(_text(p))]
    if loaders:
        out.append(finding(
            "seed-once", "high", "Function-scoped fixtures load data for every test",
            [f"{len(loaders)} conftest.py files load data in function-scoped fixtures, e.g. {_rel(root, loaders[0])}."],
            "Load read-only reference data in a session-scoped fixture; keep per-test data minimal.",
            "Often 40-80% per test.", "Tests mutating shared data need their own.", "Seconds per test vs baseline.", "setup"))
    if "django" in text and "--reuse-db" not in text:
        out.append(finding(
            "reuse-db", "low", "Django test database is rebuilt every local run",
            ["pytest-django without --reuse-db in the config."], "Use --reuse-db locally (keep --create-db in CI).",
            "Faster local start.", "Remember --create-db after migration changes.", "Local start time.", "database"))
    return out


# --------------------------------------------------------------------------- CI checks


def _ci_text(root: Path) -> str:
    parts = [_text(root / ".gitlab-ci.yml")]
    gh = root / ".github" / "workflows"
    if gh.is_dir():
        parts += [_text(p) for p in sorted(gh.glob("*.y*ml"))]
    return "\n".join(parts)


def _has_guard(root: Path) -> bool:
    for p in _files(root, ["tests", "test", "__tests__"], ["*uard*", "*Speed*", "*speed*"]):
        if re.search(r"seed|slow|budget", _text(p), re.I):
            return True
    return False


def check_ci(root: Path, cfg: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    gl = _text(root / ".gitlab-ci.yml")
    gh = "\n".join(_text(p) for p in sorted((root / ".github" / "workflows").glob("*.y*ml"))) if (root / ".github" / "workflows").is_dir() else ""
    if gl:
        if "auto_cancel" not in gl:
            out.append(finding(
                "ci-auto-cancel", "low", "Superseded pipelines keep running",
                [".gitlab-ci.yml has no workflow:auto_cancel:on_new_commit."],
                "workflow: auto_cancel: on_new_commit: interruptible (with interruptible: true on test jobs).",
                "Frees the runner for the newest push; saves CI minutes.", "Keep deploy jobs non-interruptible.",
                "A second push cancels the first pipeline's test job.", "ci"))
        if "interruptible" not in gl:
            out.append(finding(
                "ci-interruptible", "low", "Jobs are not interruptible",
                ["No interruptible: true in .gitlab-ci.yml."], "default: interruptible: true (not on deploy jobs).",
                "As above.", "Low.", "As above.", "ci"))
        if re.search(r"(?m)^\s*-\s*name:\s*\$?\w*mysql|image:\s*mysql|mysql:", gl, re.I) and not re.search(r"flush[-_]log[-_]at[-_]trx[-_]commit", gl):
            out.append(finding(
                "ci-db-durability", "medium", "The CI test database writes like production",
                ["MySQL service without innodb_flush_log_at_trx_commit=0 / binlog off."],
                "Service command: --innodb-flush-log-at-trx-commit=0 --skip-log-bin --innodb-doublewrite=0 (throwaway data only).",
                "-5 to -35% depending on disk.", "None for throwaway test data.", "Next CI run vs baseline.", "database"))
        if re.search(r"tests?:\s*\n(?:.*\n){0,15}?\s*when:\s*manual", gl):
            out.append(finding(
                "ci-manual-tests", "medium", "The full test job is manual",
                ["The tests job has when: manual, so someone must start it on every MR."],
                "Once the job is fast (or runs on your own runner), make it automatic for merge requests.",
                "Removes waiting time before the job even starts.", "Uses CI capacity on every push (use auto-cancel).",
                "Pipelines start tests without a click.", "ci"))
        if not re.search(r"(?m)^\s*tags:", gl):
            out.append(finding(
                "ci-runner", "medium", "Tests run on GitLab's shared runners",
                ["No active tags: on the test job; shared runners have 2 vCPU on the free tier, so --parallel gains little."],
                "Register a project runner with more cores (Docker executor, services_tmpfs for the database) and tag the test job.",
                "Measured on a Laravel suite: 84 -> 36.5 min on 16 cores before any other change.",
                "Runner must be online; keep a manual fallback job on shared runners.", "Import the next CI run.", "ci"))
        if "reports:" not in gl or "junit" not in gl:
            out.append(finding(
                "ci-junit", "high", "CI does not publish a JUnit report",
                ["No artifacts:reports:junit in .gitlab-ci.yml."], "Add --log-junit/--junitxml and artifacts: reports: junit: <file>.",
                "Makes CI runs importable (/eng-kit:import-ci) and shows failures in the MR.", "None.", "import-ci works.", "measure"))
    if gh:
        if "cancel-in-progress" not in gh:
            out.append(finding(
                "ci-concurrency", "low", "Superseded GitHub runs keep running",
                ["No concurrency: cancel-in-progress in .github/workflows."],
                "concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }",
                "Frees runners; saves minutes.", "Not for deploy workflows.", "A second push cancels the first run.", "ci"))
        if "actions/cache" not in gh and "cache:" not in gh:
            out.append(finding(
                "ci-cache", "low", "Dependencies are installed from scratch on every run",
                ["No actions/cache or setup-* cache in workflows."], "Cache composer/npm/pip keyed on the lock file.",
                "1-3 min per run.", "Low.", "Install step time.", "ci"))
    return out


# --------------------------------------------------------------------------- plan


def analyze(root: Path) -> Dict[str, Any]:
    cfg = engkit.load_config(root)
    runs = engkit.read_runs(root)
    stack = cfg.get("stack") or "unknown"
    findings: List[Finding] = check_runs(cfg, runs)
    if stack in ("laravel", "php-pest", "php-phpunit"):
        findings += check_laravel(root, cfg)
    elif stack.startswith("js-"):
        findings += check_js(root, cfg)
    elif stack == "python-pytest":
        findings += check_python(root, cfg)
    findings += check_ci(root, cfg)
    seen, unique = set(), []
    for f in findings:
        if f["id"] not in seen:
            seen.add(f["id"])
            unique.append(f)
    previous = engkit._read_json(engkit.kit(root) / "analysis.json").get("items", [])
    state = {p["id"]: {k: p.get(k) for k in ("state", "run_id", "note", "updated_at")} for p in previous}
    for f in unique:
        f.update({k: v for k, v in (state.get(f["id"]) or {}).items() if v is not None})
        f.setdefault("state", "open")
    for old in previous:  # keep finished items that no longer show up, so the history stays
        if old["id"] not in seen and old.get("state") in ("applied", "verified", "skipped"):
            unique.append(Finding(old))
    unique.sort(key=lambda f: (f.get("state") in ("verified", "skipped"), GAIN_ORDER.get(f["gain"], 9)))
    latest = next((r for r in reversed(runs) if r.get("scope") == "full" and r.get("passed")), None)
    return {"generated_at": engkit.now_iso(), "stack": stack, "latest_run": latest["id"] if latest else None, "items": unique}


def write_plan(root: Path, data: Dict[str, Any]) -> Path:
    data["items"].sort(key=lambda f: (f.get("state") in ("verified", "skipped"), GAIN_ORDER.get(f.get("gain"), 9)))
    engkit.atomic_write(engkit.kit(root) / "analysis.json", json.dumps(data, indent=2) + "\n")
    lines = [f"# Test speed plan — {root.name}", "", f"Generated {data['generated_at']} from run {data['latest_run'] or '(none)'} · stack {data['stack']}.",
             "One change per merge request, each measured against the baseline. Never make a test faster by checking less.", ""]
    for i, f in enumerate(data["items"], 1):
        lines += [f"## {i}. [{f['state']}] {f['title']} ({f['gain']} gain · {f['area']}) — `{f['id']}`", ""]
        lines += [f"- **Evidence:** {' '.join(f['evidence'])}", f"- **Change:** {f['change']}", f"- **Expected:** {f['expected']}",
                  f"- **Risk:** {f['risk']}", f"- **Verify:** {f['verify']}"]
        if f.get("run_id") or f.get("note"):
            lines.append(f"- **Result:** {f.get('note') or ''} {('(run ' + f['run_id'] + ')') if f.get('run_id') else ''}".rstrip())
        lines.append("")
    path = engkit.kit(root) / "plan.md"
    engkit.atomic_write(path, "\n".join(lines))
    return path


def analyze_cmd(root: Path, as_json: bool) -> int:
    data = analyze(root)
    path = write_plan(root, data)
    if as_json:
        print(json.dumps(data, indent=2))
        return 0
    open_items = [f for f in data["items"] if f["state"] == "open"]
    print(f"Plan: {path} ({len(data['items'])} items, {len(open_items)} open)")
    for f in open_items[:12]:
        print(f"  [{f['gain']:<6}] {f['id']:<20} {f['title']}")
    return 0


def plan_set_cmd(root: Path, item: str, state: str, run_id: Optional[str], note: str) -> int:
    if state not in STATES:
        engkit.fail(f"state must be one of {', '.join(STATES)}")
    path = engkit.kit(root) / "analysis.json"
    data = engkit._read_json(path)
    match = next((f for f in data.get("items", []) if f["id"] == item), None)
    if not match:
        engkit.fail(f"no plan item {item!r}. Run: analyze")
    if run_id and not any(r.get("id") == run_id for r in engkit.read_runs(root)):
        engkit.fail(f"no run {run_id!r}")
    match.update({"state": state, "updated_at": engkit.now_iso()})
    if run_id:
        match["run_id"] = run_id
    if note:
        match["note"] = note
    write_plan(root, data)
    print(f"{item}: {state}" + (f" (run {run_id})" if run_id else ""))
    return 0
