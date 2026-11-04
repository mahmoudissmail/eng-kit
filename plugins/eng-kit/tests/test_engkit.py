"""Tests for eng-kit. Run: python3 -m unittest discover -s plugins/eng-kit/tests -v"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
FIX = HERE / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import dashboard  # noqa: E402
import engkit  # noqa: E402


def run(*args: str, stdin: str = "") -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch("sys.stdin", io.StringIO(stdin)):
        try:
            code = engkit.main(list(args))
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, out.getvalue(), err.getvalue()


class ProjectCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="engkit-"))
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def project(self, files: dict[str, str]) -> Path:
        for name, text in files.items():
            path = self.tmp / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return self.tmp

    def init(self, files: dict[str, str] | None = None) -> Path:
        root = self.project(files or {"package.json": json.dumps({"devDependencies": {"vitest": "^2"}})})
        code, out, err = run("--project", str(root), "init")
        self.assertEqual(code, 0, err)
        return root


class ParseTests(unittest.TestCase):
    def test_phpunit_paratest_counts_and_times(self) -> None:
        s = engkit.parse_junit([FIX / "phpunit-paratest.xml"])
        self.assertEqual((s["tests"], s["failures"], s["errors"], s["skipped"]), (5, 1, 0, 1))
        self.assertFalse(s["passed"])
        self.assertEqual(s["test_seconds"], 21.3)
        self.assertEqual(s["slowest_classes"][0]["class"], "Tests\\Feature\\DeliveryRoutingPageTest")
        self.assertEqual(s["spread"], {"0-0.5s": 1, "0.5-2s": 2, "2-5s": 0, "5-10s": 1, ">10s": 1})

    def test_jest_junit_uses_classname(self) -> None:
        s = engkit.parse_junit([FIX / "jest-junit.xml"])
        self.assertEqual(s["tests"], 3)
        self.assertTrue(s["passed"])
        self.assertEqual(s["slowest_tests"][0]["test"], "cart adds an item")

    def test_pytest_errors_and_skips(self) -> None:
        s = engkit.parse_junit([FIX / "pytest.xml"])
        self.assertEqual((s["tests"], s["errors"], s["skipped"]), (4, 1, 1))
        self.assertFalse(s["passed"])

    def test_folder_of_surefire_reports_is_merged(self) -> None:
        s = engkit.parse_junit(engkit._junit_files(FIX, ["surefire"]))
        self.assertEqual((s["tests"], s["failures"]), (3, 1))
        self.assertEqual(s["slowest_classes"][0]["class"], "com.example.OrderTest")

    def test_invalid_xml_is_refused(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as f:
            f.write("<testsuite")
        with self.assertRaises(ValueError):
            engkit.parse_junit([Path(f.name)])
        os.unlink(f.name)


class DetectTests(ProjectCase):
    def test_laravel_with_paratest(self) -> None:
        root = self.project({"artisan": "", "composer.json": json.dumps({"require": {"laravel/framework": "^12"}, "require-dev": {"brianium/paratest": "^7"}})})
        d = engkit.detect(root)
        self.assertEqual(d["stack"], "laravel")
        self.assertIn("--parallel", d["test_command"])
        self.assertIn("--log-junit .eng-kit/junit.xml", d["test_command"])

    def test_laravel_without_paratest_notes_it(self) -> None:
        root = self.project({"artisan": "", "composer.json": json.dumps({"require": {"laravel/framework": "^12"}})})
        d = engkit.detect(root)
        self.assertNotIn("--parallel", d["test_command"])
        self.assertTrue(d["notes"])

    def test_vitest_jest_pytest_go_maven(self) -> None:
        cases = [
            ({"package.json": json.dumps({"devDependencies": {"vitest": "^2"}})}, "js-vitest"),
            ({"package.json": json.dumps({"devDependencies": {"jest": "^29", "jest-junit": "^16"}})}, "js-jest"),
            ({"pyproject.toml": "[tool.pytest.ini_options]\naddopts='-q'\n# pytest-xdist\n"}, "python-pytest"),
            ({"go.mod": "module x"}, "go"),
            ({"pom.xml": "<project/>"}, "java-maven"),
        ]
        for files, stack in cases:
            with self.subTest(stack=stack):
                d = tempfile.mkdtemp()
                for name, text in files.items():
                    Path(d, name).write_text(text)
                self.assertEqual(engkit.detect(Path(d))["stack"], stack)
                shutil.rmtree(d)

    def test_unknown_project(self) -> None:
        self.assertEqual(engkit.detect(self.tmp)["stack"], "unknown")


class InitTests(ProjectCase):
    def test_init_creates_files_and_hides_folder_once(self) -> None:
        root = self.init()
        self.assertTrue((root / ".eng-kit/config.json").is_file())
        self.assertTrue((root / ".eng-kit/status.md").is_file())
        exclude = (root / ".git/info/exclude").read_text()
        self.assertEqual(exclude.count("/.eng-kit/"), 1)
        run("--project", str(root), "init", "--force")
        self.assertEqual((root / ".git/info/exclude").read_text().count("/.eng-kit/"), 1)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout
        self.assertNotIn(".eng-kit", status)

    def test_config_set_and_get(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "targets.wall_minutes_high", "12")
        code, out, _ = run("--project", str(root), "config", "get", "targets.wall_minutes_high")
        self.assertEqual((code, out.strip()), (0, "12"))
        run("--project", str(root), "config", "set", "junit_paths", "a.xml, reports/")
        self.assertEqual(engkit.load_config(root)["junit_paths"], ["a.xml", "reports/"])

    def test_commands_need_init(self) -> None:
        code, _, err = run("--project", str(self.tmp), "status")
        self.assertEqual(code, 2)
        self.assertIn("init", err)


class RecordTests(ProjectCase):
    def test_first_full_run_becomes_baseline_and_change_is_computed(self) -> None:
        root = self.init()
        code, out, _ = run("--project", str(root), "record", str(FIX / "jest-junit.xml"), "--wall-minutes", "10")
        self.assertEqual(code, 0)
        self.assertIn("set as the baseline", out)
        faster = (FIX / "jest-junit.xml").read_text().replace('time="0.4"', 'time="0.3"')
        p = root / "faster.xml"
        p.write_text(faster)
        code, out, _ = run("--project", str(root), "record", str(p), "--wall-minutes", "6")
        self.assertIn("40% faster than the baseline", out)
        data = engkit.status_data(root)
        self.assertAlmostEqual(data["change"], 0.4)

    def test_runs_are_compared_only_within_their_environment(self) -> None:
        root = self.init()
        (root / "a.xml").write_text(junit_of(40, 2))
        _, out, _ = run("--project", str(root), "record", str(root / "a.xml"), "--wall-minutes", "84", "--source", "ci", "--environment", "CI shared runners")
        self.assertIn("set as the baseline", out)
        (root / "b.xml").write_text(junit_of(40, 1.9))
        _, out, _ = run("--project", str(root), "record", str(root / "b.xml"), "--wall-minutes", "36.5")
        self.assertNotIn("faster", out)
        (root / "c.xml").write_text(junit_of(40, 1.8))
        _, out, _ = run("--project", str(root), "record", str(root / "c.xml"), "--wall-minutes", "29.2")
        self.assertIn("20% faster than the baseline for Local", out)
        data = engkit.status_data(root)
        self.assertAlmostEqual(data["change"], 0.2, places=3)
        _, printed, _ = run("--project", str(root), "status")
        self.assertIn("Wall time per test: 43.80 s", printed)        # 29.2 min x 60 / 40 tests
        self.assertIn("summed over all workers: 1.80 s", printed)
        envs = {e["environment"]: e for e in data["environments"]}
        self.assertEqual(envs["CI shared runners"]["baseline_minutes"], 84.0)
        self.assertIsNone(envs["CI shared runners"]["change"])

    def test_same_report_is_not_recorded_twice(self) -> None:
        root = self.init()
        run("--project", str(root), "record", str(FIX / "jest-junit.xml"), "--wall-seconds", "60")
        _, out, _ = run("--project", str(root), "record", str(FIX / "jest-junit.xml"), "--wall-seconds", "60")
        self.assertIn("already recorded", out)
        self.assertEqual(len(engkit.read_runs(root)), 1)

    def test_small_run_is_partial_and_not_the_baseline_reference(self) -> None:
        root = self.init()
        run("--project", str(root), "record", str(FIX / "phpunit-paratest.xml"), "--wall-seconds", "60")
        small = root / "one.xml"
        small.write_text('<testsuite><testcase classname="A" name="t" time="0.1"/></testsuite>')
        run("--project", str(root), "record", str(small), "--wall-seconds", "2")
        self.assertEqual(engkit.read_runs(root)[-1]["scope"], "partial")

    def test_baseline_commands(self) -> None:
        root = self.init()
        run("--project", str(root), "record", str(FIX / "jest-junit.xml"), "--wall-seconds", "60")
        run("--project", str(root), "baseline", "clear")
        self.assertIsNone(engkit.load_config(root)["baseline_run_id"])
        run("--project", str(root), "baseline", "latest")
        self.assertIsNotNone(engkit.load_config(root)["baseline_run_id"])

    def test_export_csv(self) -> None:
        root = self.init()
        run("--project", str(root), "record", str(FIX / "jest-junit.xml"), "--wall-seconds", "60")
        _, out, _ = run("--project", str(root), "export")
        self.assertTrue(out.startswith("id,recorded_at,source"))
        self.assertEqual(len(out.strip().splitlines()), 2)


class MeasureTests(ProjectCase):
    def test_measure_runs_command_times_it_and_records(self) -> None:
        root = self.init()
        src = FIX / "jest-junit.xml"
        cmd = f"{shlex_quote(sys.executable)} -c \"import shutil,time; time.sleep(0.2); shutil.copy({str(src)!r}, '.eng-kit/junit.xml')\""
        code, out, _ = run("--project", str(root), "measure", "--command", cmd)
        self.assertEqual(code, 0, out)
        runs = engkit.read_runs(root)
        self.assertEqual(len(runs), 1)
        self.assertGreaterEqual(runs[0]["wall_seconds"], 0.2)
        self.assertEqual(runs[0]["source"], "local")

    def test_measure_without_junit_reports_it(self) -> None:
        root = self.init()
        code, out, _ = run("--project", str(root), "measure", "--command", "echo no-junit")
        self.assertEqual(code, 1)
        self.assertIn("wrote no new JUnit XML", out)


def shlex_quote(s: str) -> str:
    import shlex

    return shlex.quote(s)


class HookTests(ProjectCase):
    def payload(self, root: Path, phase: str, command: str, tid: str = "toolu_1") -> str:
        body = {"cwd": str(root), "tool_name": "Bash", "tool_use_id": tid, "tool_input": {"command": command}, "hook_event_name": phase}
        return json.dumps(body)

    def test_pre_then_post_records_one_agent_run(self) -> None:
        root = self.init()
        cmd = "npx vitest run --reporter=junit --outputFile.junit=.eng-kit/junit.xml"
        self.assertEqual(run("hook", "pre", stdin=self.payload(root, "PreToolUse", cmd))[0], 0)
        time.sleep(0.05)
        shutil.copy(FIX / "jest-junit.xml", root / ".eng-kit/junit.xml")
        self.assertEqual(run("hook", "post", stdin=self.payload(root, "PostToolUse", cmd))[0], 0)
        runs = engkit.read_runs(root)
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["source"], runs[0]["wall_source"]), ("agent", "hook"))
        run("hook", "post", stdin=self.payload(root, "PostToolUse", "ls"))
        self.assertEqual(len(engkit.read_runs(root)), 1)

    def test_hook_is_silent_outside_set_up_projects_and_on_bad_input(self) -> None:
        self.assertEqual(run("hook", "post", stdin=json.dumps({"cwd": str(self.tmp), "tool_name": "Bash", "tool_input": {"command": "pytest"}})), (0, "", ""))
        self.assertEqual(run("hook", "pre", stdin="not json")[0], 0)

    def test_non_test_commands_do_not_open_a_timer(self) -> None:
        root = self.init()
        run("hook", "pre", stdin=self.payload(root, "PreToolUse", "git status"))
        self.assertFalse((root / ".eng-kit/.pending.json").exists())

    def test_hook_script_records_through_the_real_entry_point(self) -> None:
        root = self.init()
        cmd = "python -m pytest --junitxml=.eng-kit/junit.xml"
        pre = self.payload(root, "PreToolUse", cmd, "toolu_9")
        subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "pre"], input=pre, text=True, check=True)
        time.sleep(0.05)
        shutil.copy(FIX / "pytest.xml", root / ".eng-kit/junit.xml")
        post = self.payload(root, "PostToolUse", cmd, "toolu_9")
        out = subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "post"], input=post, text=True, capture_output=True, check=True)
        self.assertEqual((out.stdout, out.stderr), ("", ""))
        self.assertEqual(len(engkit.read_runs(root)), 1)

    def test_hook_overhead_is_small(self) -> None:
        root = self.init()
        body = self.payload(root, "PostToolUse", "ls")
        started = time.perf_counter()
        for _ in range(20):
            subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "post"], input=body, text=True, capture_output=True, check=True)
        per_call = (time.perf_counter() - started) / 20
        self.assertLess(per_call, 0.5, f"hook took {per_call:.3f}s per call")


class ImportCiTests(ProjectCase):
    def test_import_reads_job_and_report_and_never_prints_the_token(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")
        job = {"duration": 5040.0, "pipeline": {"id": 77}, "runner": {"is_shared": True}, "ref": "staging", "name": "tests", "web_url": "https://gitlab.com/acme/shop/-/jobs/9", "finished_at": "2026-11-01T10:00:00Z"}
        report = {"total_count": 2, "test_suites": [{"name": "Feature", "test_cases": [
            {"classname": "Tests\\A", "name": "a", "execution_time": 3.0, "status": "success"},
            {"classname": "Tests\\B", "name": "b", "execution_time": 1.0, "status": "failed"}]}]}
        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append((req.full_url, dict(req.header_items())))
            body = job if req.full_url.endswith("/jobs/9") else report
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps(body).encode()
            resp.__enter__.return_value = resp
            return resp

        with mock.patch.dict(os.environ, {"GITLAB_TOKEN": "glpat-SECRET123"}), mock.patch("urllib.request.urlopen", fake_urlopen):
            code, out, err = run("--project", str(root), "import-ci", "https://gitlab.com/acme/shop/-/jobs/9")
        self.assertEqual(code, 0, err)
        self.assertNotIn("SECRET123", out + err)
        self.assertIn("/projects/acme%2Fshop/jobs/9", calls[0][0])
        self.assertEqual(calls[0][1].get("Private-token"), "glpat-SECRET123")
        r = engkit.read_runs(root)[0]
        self.assertEqual((r["tests"], r["failures"], r["wall_seconds"], r["environment"]), (2, 1, 5040.0, "CI shared runners"))
        self.assertNotIn("SECRET123", (root / ".eng-kit/runs.jsonl").read_text())

    def test_project_from_remote_never_includes_credentials(self) -> None:
        cases = {
            "https://oauth2:glpat-SECRET@gitlab.com/acme/order-app.git": "acme/order-app",
            "git@gitlab.com:group/sub/app.git": "group/sub/app",
            "https://gitlab.example.com/team/app": "team/app",
            "ssh://git@gitlab.com:2222/team/app.git": "team/app",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(engkit.project_from_url(url), expected)

    def test_token_from_file(self) -> None:
        root = self.init()
        (root / "secrets.env").write_text('OTHER=1\nGITLAB_TOKEN="from-file"\n')
        run("--project", str(root), "config", "set", "ci.token_file", "secrets.env")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITLAB_TOKEN", None)
            self.assertEqual(engkit._token(root, engkit.load_config(root)), "from-file")

    def test_missing_token_fails_clearly(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITLAB_TOKEN", None)
            code, _, err = run("--project", str(root), "import-ci", "9")
        self.assertEqual(code, 2)
        self.assertIn("no GitLab token", err)


class DashboardTests(ProjectCase):
    def test_dashboard_is_self_contained_and_escapes_data(self) -> None:
        root = self.init()
        evil = root / "evil.xml"
        evil.write_text('<testsuite><testcase classname="X&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" name="t" time="1"/></testsuite>')
        run("--project", str(root), "record", str(evil), "--wall-seconds", "30")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(dashboard.build_dashboard(root, open_browser=False), 0)
        html = (root / ".eng-kit/dashboard.html").read_text()
        self.assertNotIn("__ENGKIT_DATA__", html)
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertNotRegex(html, r"(src|href)=[\"']https?://")
        self.assertIn("Content-Security-Policy", html)
        data = html.split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(json.loads(data)["runs"][0]["tests"], 1)


class ScaleTests(ProjectCase):
    def test_parses_a_large_report_quickly(self) -> None:
        cases = "".join(f'<testcase classname="Tests\\\\Feature\\\\C{i % 400}" name="t{i}" time="{(i % 97) / 10}"/>' for i in range(5000))
        big = self.tmp / "big.xml"
        big.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
        started = time.perf_counter()
        s = engkit.parse_junit([big])
        self.assertEqual(s["tests"], 5000)
        self.assertLess(time.perf_counter() - started, 2.0)


if __name__ == "__main__":
    unittest.main()


LARAVEL_CI = """workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
default:
  image: $CI_IMAGE
  interruptible: true
.php-app:
  services:
    - name: $MYSQL_IMAGE
      alias: mysql
      command: ["--innodb-flush-log-at-trx-commit=0", "--skip-log-bin"]
tests:
  stage: tests
  extends: .php-app
  when: manual
  # tags: [project-runner]
  timeout: 120m
  script:
    - php artisan test --parallel --recreate-databases --log-junit junit.xml
  artifacts:
    when: always
    reports:
      junit: junit.xml
"""


def junit_of(n: int, seconds: float) -> str:
    cases = "".join(f'<testcase class="Tests\\\\Feature\\\\C{i % 7}Test" name="t{i}" time="{seconds}"/>' for i in range(n))
    return f"<testsuites><testsuite>{cases}</testsuite></testsuites>"


class AnalyzeTests(ProjectCase):
    def laravel(self) -> Path:
        composer = {"require": {"laravel/framework": "^12", "laravel/telescope": "^5"}, "require-dev": {"brianium/paratest": "^7"}}
        return self.init({
            "artisan": "",
            "composer.json": json.dumps(composer),
            "phpunit.xml": '<phpunit><php><env name="BCRYPT_ROUNDS" value="4"/><env name="CACHE_STORE" value="array"/></php></phpunit>',
            "tests/TestCase.php": "<?php abstract class TestCase {}",
            "tests/Feature/OrdersTest.php": "<?php class OrdersTest { protected function setUp(): void { parent::setUp(); $this->seed(RolePermissionSeeder::class); } public function test_a() {} }",
            "tests/Feature/CleanTest.php": "<?php class CleanTest { public function test_b() {} }",
            ".gitlab-ci.yml": LARAVEL_CI,
        })

    def test_laravel_project_gets_the_expected_plan(self) -> None:
        root = self.laravel()
        (root / "ci.xml").write_text(junit_of(100, 7.5))
        run("--project", str(root), "record", str(root / "ci.xml"), "--wall-minutes", "84", "--source", "ci", "--environment", "CI shared runners")
        (root / "local.xml").write_text(junit_of(100, 7.4))
        run("--project", str(root), "record", str(root / "local.xml"), "--wall-minutes", "36.5")
        code, out, err = run("--project", str(root), "analyze", "--json")
        self.assertEqual(code, 0, err)
        ids = [f["id"] for f in json.loads(out)["items"]]
        for expected in ("setup-cost", "ci-cores", "seed-once", "base-fakes", "phpunit-env", "observability-off", "cached-boot",
                         "random-order", "guard-tests", "ci-auto-cancel", "ci-manual-tests", "ci-runner"):
            self.assertIn(expected, ids)
        for absent in ("parallel", "parallel-flag", "ci-db-durability", "ci-junit", "ci-interruptible", "measure-baseline"):
            self.assertNotIn(absent, ids)
        seed = next(f for f in json.loads(out)["items"] if f["id"] == "seed-once")
        self.assertIn("1 of 2 test files", seed["evidence"][0])
        self.assertTrue((root / ".eng-kit/plan.md").read_text().startswith("# Test speed plan"))
        self.assertLess(ids.index("seed-once"), ids.index("guard-tests"))

    def test_plan_states_persist_across_reanalysis(self) -> None:
        root = self.laravel()
        (root / "ci.xml").write_text(junit_of(50, 3))
        run("--project", str(root), "record", str(root / "ci.xml"), "--wall-minutes", "20")
        run("--project", str(root), "analyze")
        rid = engkit.read_runs(root)[0]["id"]
        code, out, err = run("--project", str(root), "plan", "set", "seed-once", "verified", "--run", rid, "--note", "84 -> 40 min")
        self.assertEqual(code, 0, err)
        (root / "tests/Feature/OrdersTest.php").write_text("<?php class OrdersTest { public function test_a() {} }")
        run("--project", str(root), "analyze")
        items = {f["id"]: f for f in json.loads((root / ".eng-kit/analysis.json").read_text())["items"]}
        self.assertEqual(items["seed-once"]["state"], "verified")
        self.assertEqual(items["seed-once"]["note"], "84 -> 40 min")
        self.assertIn("verified", (root / ".eng-kit/plan.md").read_text())
        self.assertEqual(run("--project", str(root), "plan", "set", "nope", "applied")[0], 2)
        self.assertEqual(run("--project", str(root), "plan", "set", "seed-once", "done")[0], 2)

    def test_no_runs_asks_for_a_baseline(self) -> None:
        root = self.init()
        _, out, _ = run("--project", str(root), "analyze", "--json")
        self.assertEqual(json.loads(out)["items"][0]["id"], "measure-baseline")

    def test_js_and_python_projects(self) -> None:
        root = self.init({"package.json": json.dumps({"devDependencies": {"jest": "^29"}}),
                          "src/a.test.js": "beforeEach(async () => { await seedDatabase(); });\nit('x', () => {});"})
        _, out, _ = run("--project", str(root), "analyze", "--json")
        ids = [f["id"] for f in json.loads(out)["items"]]
        self.assertIn("seed-once", ids)
        self.assertIn("jest-junit", ids)
        py = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, py, True)
        (py / "pytest.ini").write_text("[pytest]\n")
        (py / "conftest.py").write_text("import pytest\n@pytest.fixture(autouse=True)\ndef data(db):\n    call_command('loaddata', 'roles')\n")
        run("--project", str(py), "init")
        _, out, _ = run("--project", str(py), "analyze", "--json")
        ids = [f["id"] for f in json.loads(out)["items"]]
        self.assertIn("parallel", ids)
        self.assertIn("seed-once", ids)


class SetupCostBasisTests(ProjectCase):
    def test_fast_parallel_suite_is_not_flagged_by_inflated_per_worker_times(self) -> None:
        root = self.init()
        (root / "fast.xml").write_text(junit_of(3000, 4.3))      # 4.3 s each when 16 workers share the CPU
        run("--project", str(root), "record", str(root / "fast.xml"), "--wall-minutes", "15.8")   # 0.32 s wall per test
        _, out, _ = run("--project", str(root), "analyze", "--json")
        self.assertNotIn("setup-cost", [f["id"] for f in json.loads(out)["items"]])

    def test_slow_suite_is_flagged_on_wall_clock(self) -> None:
        root = self.init()
        (root / "slow.xml").write_text(junit_of(3000, 3.0))
        run("--project", str(root), "record", str(root / "slow.xml"), "--wall-minutes", "84")     # 1.68 s wall per test
        _, out, _ = run("--project", str(root), "analyze", "--json")
        f = next(f for f in json.loads(out)["items"] if f["id"] == "setup-cost")
        self.assertIn("(wall clock)", f["evidence"][0])


class SeedDetectionTests(unittest.TestCase):
    def test_finds_seed_calls_anywhere_in_set_up_and_nowhere_else(self) -> None:
        import analyze

        long_setup = "<?php class A { protected function setUp(): void {\n parent::setUp();\n" + "    $x = 1; // {\n" * 200 + \
            "    $this->afterApplicationCreated(function () { $y = '}'; });\n    $this->seed(RolePermissionSeeder::class);\n} }"
        in_test_only = "<?php class B { protected function setUp(): void { parent::setUp(); }\n public function test_x() { $this->seed(S::class); } }"
        docblock = "<?php class C {\n /** @return void */\n protected function setUp(): void\n {\n  parent::setUp();\n  $this->seed(S::class);\n }\n}"
        self.assertTrue(analyze.seeds_in_setup(long_setup))
        self.assertFalse(analyze.seeds_in_setup(in_test_only))
        self.assertTrue(analyze.seeds_in_setup(docblock))


class ReleaseSpeedTests(ProjectCase):
    def test_lead_times_from_merge_requests_and_deployments(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")
        run("--project", str(root), "config", "set", "release.source", "gitlab")
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

        def at(hours_ago: float) -> str:
            return (now - __import__("datetime").timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")

        staging = [
            {"iid": 1, "created_at": at(50), "merged_at": at(48), "source_branch": "feat/a"},
            {"iid": 2, "created_at": at(30), "merged_at": at(26), "source_branch": "feat/b"},
            {"iid": 3, "created_at": at(5), "merged_at": at(4), "source_branch": "feat/c"},
            {"iid": 4, "created_at": at(19.9), "merged_at": at(19.8), "source_branch": "backmerge/main-1.55.1-into-staging"},
            {"iid": 5, "created_at": at(22), "merged_at": at(21.9), "source_branch": "release-1.58.0"},
        ]
        main = [{"created_at": at(21), "merged_at": at(20), "source_branch": "staging"}]
        deployments = [{"finished_at": at(19)}]

        commits = {1: [{"authored_date": at(60)}, {"authored_date": at(55)}]}

        def fake_urlopen(req, timeout=0):
            url = req.full_url
            if "/commits" in url:
                iid = int(url.split("/merge_requests/")[1].split("/")[0])
                body = commits.get(iid, [])
                resp = mock.MagicMock()
                resp.read.return_value = json.dumps(body).encode()
                resp.__enter__.return_value = resp
                return resp
            body = deployments if "/deployments" in url else (main if "target_branch=main" in url else staging)
            if "page=2" in url:
                body = []
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps(body).encode()
            resp.__enter__.return_value = resp
            return resp

        with mock.patch.dict(os.environ, {"GITLAB_TOKEN": "glpat-X"}), mock.patch("urllib.request.urlopen", fake_urlopen):
            code, out, err = run("--project", str(root), "release-speed", "--environment", "production", "--json")
            code2, listed, _ = run("--project", str(root), "release-speed", "--list")
        self.assertEqual((code, code2), (0, 0), err)
        snap = json.loads(out)
        self.assertEqual(snap["excluded"], 2)
        self.assertIn("!4 backmerge/main-1.55.1-into-staging", listed)
        self.assertIn("!2 feat/b: 4.0 h to staging (MR open 4.0 h)", listed)
        self.assertIn("!1 feat/a: 12.0 h to staging (MR open 2.0 h)", listed)
        self.assertEqual(snap["code_to_staging"]["count"], 3)
        self.assertEqual(snap["code_to_staging"]["median_h"], 4.0)   # MR 1 starts at its first commit (60 h ago)
        self.assertEqual(snap["mr_open_to_merge"]["median_h"], 2.0)
        self.assertEqual(snap["start"], "first_commit")
        cache = json.loads((root / ".eng-kit/cache/mr-first-commit.json").read_text())
        self.assertEqual(set(cache), {"1"})  # MRs without commits are not cached; merged MRs never change
        self.assertEqual(snap["code_to_production"]["count"], 2)
        self.assertEqual(snap["not_released_yet"], 1)
        self.assertEqual(snap["code_to_production"]["median_h"], 25.0)  # MR 1: first commit 60 h ago -> release 20 h ago = 40 h; MR 2: 30 -> 20 = 10 h
        self.assertEqual(snap["deploy"]["merge_to_deploy"]["count"], 2)
        self.assertTrue((root / ".eng-kit/release.jsonl").exists())


class ReleaseSpeedScaleTests(ProjectCase):
    def test_150_merge_requests_are_fetched_in_parallel_and_cached(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")
        run("--project", str(root), "config", "set", "release.source", "gitlab")
        import datetime as _dt

        now = _dt.datetime.now(_dt.timezone.utc)
        iso = lambda h: (now - _dt.timedelta(hours=h)).isoformat().replace("+00:00", "Z")
        mrs = [{"iid": i, "created_at": iso(10), "merged_at": iso(9), "source_branch": f"feat/{i}"} for i in range(150)]
        calls = {"commits": 0}

        def fake_urlopen(req, timeout=0):
            url = req.full_url
            if "/commits" in url:
                calls["commits"] += 1
                time.sleep(0.02)
                body = [{"authored_date": iso(12)}]
            elif "/merge_requests?" in url and url.endswith("&page=1") and "target_branch=staging" in url:
                body = mrs[:100]
            elif "/merge_requests?" in url and url.endswith("&page=2") and "target_branch=staging" in url:
                body = mrs[100:]
            else:
                body = []
            resp = mock.MagicMock()
            resp.read.return_value = json.dumps(body).encode()
            resp.__enter__.return_value = resp
            return resp

        with mock.patch.dict(os.environ, {"GITLAB_TOKEN": "glpat-X"}), mock.patch("urllib.request.urlopen", fake_urlopen):
            started = time.perf_counter()
            code, out, err = run("--project", str(root), "release-speed", "--json")
            first = time.perf_counter() - started
            run("--project", str(root), "release-speed", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["code_to_staging"]["median_h"], 3.0)
        self.assertEqual(calls["commits"], 150)        # second run used the cache
        self.assertLess(first, 3.0)                    # serial would be >= 150 x 20 ms = 3 s of sleeps alone; 4 at a time stays below


class GitReleaseSpeedTests(ProjectCase):
    def git(self, *args: str, when: int = 0) -> None:
        env = {**os.environ, "GIT_AUTHOR_DATE": f"@{when} +0000", "GIT_COMMITTER_DATE": f"@{when} +0000",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", *args], cwd=self.tmp, check=True, capture_output=True, env=env)

    def commit(self, name: str, when: int) -> None:
        (self.tmp / name).write_text(name)
        self.git("add", name, when=when)
        self.git("commit", "-q", "-m", name, when=when)

    def merge(self, branch: str, into: str, iid: int, when: int) -> None:
        self.git("checkout", "-q", into, when=when)
        self.git("merge", "--no-ff", "-q", branch, "-m", f"Merge branch '{branch}' into '{into}'\n\nTitle {branch}\n\nSee merge request acme/shop!{iid}", when=when)

    def test_lead_times_from_local_history_without_network(self) -> None:
        h = 3600
        now = int(time.time())
        t0 = now - 10 * 24 * h
        self.git("checkout", "-q", "-b", "main", when=t0)
        self.commit("base", t0)
        self.git("branch", "staging", when=t0)
        self.git("checkout", "-q", "-b", "feat/a", "staging", when=t0)
        self.commit("a1", t0 + 1 * h)
        self.commit("a2", t0 + 3 * h)
        self.merge("feat/a", "staging", 1, t0 + 5 * h)          # 4 h after the first commit
        self.git("checkout", "-q", "-b", "feat/b", "staging", when=t0 + 5 * h)
        self.commit("b1", t0 + 6 * h)
        self.merge("feat/b", "staging", 2, t0 + 8 * h)          # 2 h
        self.git("checkout", "-q", "-b", "backmerge/main-into-staging", "staging", when=t0 + 8 * h)
        self.commit("bm", t0 + 8 * h)
        self.merge("backmerge/main-into-staging", "staging", 3, t0 + 8 * h + 60)
        self.merge("staging", "main", 4, t0 + 20 * h)           # release: a -> 19 h, b -> 14 h
        self.git("checkout", "-q", "-b", "feat/c", "staging", when=t0 + 21 * h)
        self.commit("c1", t0 + 21 * h)
        self.merge("feat/c", "staging", 5, t0 + 22 * h)         # 1 h, not released
        # a branch cut from main, which carries an old main-only commit: only its own commit counts
        self.git("checkout", "-q", "main", when=t0 + 22 * h)
        self.commit("old-main-only", t0 + 22 * h + 60)
        self.git("commit", "-q", "--amend", "--no-edit", "--date", f"@{t0 - 100 * h} +0000", when=t0 + 22 * h + 60)  # authored long ago
        self.git("checkout", "-q", "-b", "feat/d", "main", when=t0 + 23 * h)
        self.commit("d1", t0 + 23 * h)
        self.merge("feat/d", "staging", 6, t0 + 24 * h)         # 1 h from d1, not 124 h from the old main commit
        self.git("checkout", "-q", "staging", when=t0 + 22 * h)
        code, out, err = run("--project", str(self.tmp), "init")
        self.assertEqual(code, 0, err)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network allowed")):
            code, out, err = run("--project", str(self.tmp), "release-speed", "--json")
            code2, listed, _ = run("--project", str(self.tmp), "release-speed", "--list")
        self.assertEqual((code, code2), (0, 0), err)
        snap = json.loads(out)
        self.assertEqual(snap["source"], "git")
        self.assertEqual(snap["merged_to_staging"], 4)
        self.assertEqual(snap["excluded"], 1)
        self.assertEqual(snap["code_to_staging"]["median_h"], 1.5)  # 4, 2, 1, 1 h (feat/d: its own commit only)
        self.assertEqual(snap["code_to_staging"]["p90_h"], 4.0)
        self.assertEqual(snap["code_to_production"]["count"], 2)
        self.assertEqual(snap["code_to_production"]["median_h"], 16.5)
        self.assertEqual(snap["not_released_yet"], 2)
        self.assertIn("!1 feat/a: 4.0 h to staging -> 19.0", listed)
        self.assertIn("!5 feat/c: 1.0 h to staging -> not released", listed)
        self.assertIn("hours from first commit to staging -> hours to production", listed)
        self.assertNotIn("MR open time", listed)
        self.assertIn("4 merges into staging", listed)
        self.assertIn("!6 feat/d: 1.0 h to staging", listed)


class GitLabErrorTests(ProjectCase):
    def test_rate_limit_is_retried_then_reported_clearly(self) -> None:
        import urllib.error

        calls = {"n": 0}

        def limited(req, timeout=0):
            calls["n"] += 1
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {"Retry-After": "0"}, None)

        with mock.patch("urllib.request.urlopen", limited), mock.patch("time.sleep"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
                engkit._api("https://gitlab.com", "a/b", "/jobs/1", "t")
        self.assertEqual(calls["n"], 5)
        self.assertIn("rate limit", err.getvalue())
        self.assertNotIn("read_api", err.getvalue())

    def test_timeout_is_retried_and_does_not_crash(self) -> None:
        def slow(req, timeout=0):
            raise TimeoutError("timed out")

        with mock.patch("urllib.request.urlopen", slow), mock.patch("time.sleep"):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
                engkit._api("https://gitlab.com", "a/b", "/jobs/1", "t")
        self.assertIn("could not reach GitLab", err.getvalue())


class DashboardSectionsTests(ProjectCase):
    def test_plan_and_release_reach_the_dashboard(self) -> None:
        root = self.init()
        (root / "r.xml").write_text(junit_of(20, 2))
        run("--project", str(root), "record", str(root / "r.xml"), "--wall-minutes", "5")
        run("--project", str(root), "analyze")
        (root / ".eng-kit/release.jsonl").write_text(json.dumps({"recorded_at": "2026-11-01T00:00:00Z", "window_days": 30, "staging_branch": "staging",
            "production_branch": "main", "merged_to_staging": 3, "releases": 1, "code_to_staging": {"count": 3, "median_h": 2.0, "p75_h": 3.0, "p90_h": 4.0},
            "code_to_production": {"count": 2, "median_h": 20.0, "p75_h": 30.0, "p90_h": 40.0}, "not_released_yet": 1, "deploy": None}) + "\n")
        with contextlib.redirect_stdout(io.StringIO()):
            dashboard.build_dashboard(root, open_browser=False)
        data = json.loads((root / ".eng-kit/dashboard.html").read_text().split('<script id="data" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertTrue(data["plan"])
        self.assertEqual(data["release"]["code_to_production"]["median_h"], 20.0)


class JunitPathInCommandTests(ProjectCase):
    def test_paths_named_in_common_test_commands(self) -> None:
        cases = {
            "php artisan test --parallel --log-junit build/junit.xml": ["build/junit.xml"],
            "vendor/bin/pest --log-junit=out.xml": ["out.xml"],
            "python -m pytest -n auto --junitxml=reports/py.xml": ["reports/py.xml"],
            "npx vitest run --reporter=junit --outputFile.junit=vt.xml": ["vt.xml"],
            "JEST_JUNIT_OUTPUT_FILE=j.xml npx jest --reporters=jest-junit": ["j.xml"],
            "gotestsum --junitfile go.xml ./...": ["go.xml"],
            "php artisan test --filter=Orders": [],
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(engkit.junit_paths_in(command), expected)

    def test_hook_records_a_run_written_to_a_path_named_in_the_command(self) -> None:
        root = self.init()
        cmd = "python -m pytest --junitxml=reports/run.xml"
        body = lambda phase: json.dumps({"cwd": str(root), "tool_name": "Bash", "tool_use_id": "toolu_7", "tool_input": {"command": cmd}, "hook_event_name": phase})
        subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "pre"], input=body("PreToolUse"), text=True, check=True)
        time.sleep(0.05)
        (root / "reports").mkdir()
        shutil.copy(FIX / "pytest.xml", root / "reports/run.xml")
        subprocess.run([sys.executable, str(SCRIPTS / "hook.py"), "post"], input=body("PostToolUse"), text=True, check=True)
        runs = engkit.read_runs(root)
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["source"], runs[0]["tests"]), ("agent", 4))


def _resp(body, raw: bool = False):
    resp = mock.MagicMock()
    resp.read.return_value = body if raw else json.dumps(body).encode()
    resp.__enter__.return_value = resp
    return resp


class GitLabLatestTests(ProjectCase):
    def test_latest_picks_the_newest_finished_tests_job(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")
        report = {"total_count": 1, "test_suites": [{"name": "s", "test_cases": [{"classname": "A", "name": "a", "execution_time": 1, "status": "success"}]}]}
        seen = []

        def fake(req, timeout=0):
            seen.append(req.full_url)
            if "/jobs?scope" in req.full_url:
                return _resp([{"id": 11, "name": "pint"}, {"id": 12, "name": "tests"}, {"id": 9, "name": "tests"}])
            if req.full_url.endswith("/jobs/12"):
                return _resp({"duration": 420.0, "pipeline": {"id": 5}, "runner": {"is_shared": False, "description": "box"}, "ref": "main", "name": "tests"})
            return _resp(report)

        with mock.patch.dict(os.environ, {"GITLAB_TOKEN": "t"}), mock.patch("urllib.request.urlopen", fake):
            code, out, err = run("--project", str(root), "import-ci", "latest")
        self.assertEqual(code, 0, err)
        self.assertTrue(any(u.endswith("/jobs/12") for u in seen))
        self.assertEqual(engkit.read_runs(root)[0]["environment"], "CI runner box")


class GitHubImportTests(ProjectCase):
    def test_imports_a_run_artifact_and_job_time_without_sending_the_token_to_storage(self) -> None:
        import urllib.error
        import zipfile as zf

        root = self.init()
        run("--project", str(root), "config", "set", "ci.provider", "github")
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")
        buf = io.BytesIO()
        with zf.ZipFile(buf, "w") as z:
            z.writestr("junit.xml", (FIX / "jest-junit.xml").read_text())
        storage_headers = {}

        def fake_urlopen(req, timeout=0):
            url = req.full_url
            if url.startswith("https://storage.example/"):
                storage_headers.update(dict(req.header_items()))
                return _resp(buf.getvalue(), raw=True)
            if url.endswith("/actions/runs/77"):
                return _resp({"id": 77, "head_branch": "main", "html_url": "https://github.com/acme/shop/actions/runs/77", "run_started_at": "2026-11-01T10:00:00Z", "updated_at": "2026-11-01T10:09:00Z"})
            if url.endswith("/actions/runs/77/artifacts"):
                return _resp({"artifacts": [{"name": "junit", "expired": False, "archive_download_url": "https://api.github.com/repos/acme/shop/actions/artifacts/5/zip"}]})
            if "/actions/runs/77/jobs" in url:
                return _resp({"jobs": [{"id": 3, "name": "tests", "started_at": "2026-11-01T10:01:00Z", "completed_at": "2026-11-01T10:08:00Z", "labels": ["self-hosted", "linux"], "runner_name": "box"}]})
            raise AssertionError(url)

        class FakeOpener:
            def open(self, req, timeout=0):
                raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://storage.example/blob?sig=x"}, None)

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_SECRET"}), mock.patch("urllib.request.urlopen", fake_urlopen), \
                mock.patch("urllib.request.build_opener", return_value=FakeOpener()):
            code, out, err = run("--project", str(root), "import-ci", "https://github.com/acme/shop/actions/runs/77")
        self.assertEqual(code, 0, err)
        r = engkit.read_runs(root)[0]
        self.assertEqual((r["tests"], r["wall_seconds"], r["environment"], r["ci"]["provider"]), (3, 420.0, "CI runner box", "github"))
        self.assertNotIn("Authorization", storage_headers)
        self.assertNotIn("SECRET", (root / ".eng-kit/runs.jsonl").read_text() + out + err)

    def test_missing_artifact_explains_what_the_workflow_needs(self) -> None:
        root = self.init()
        run("--project", str(root), "config", "set", "ci.provider", "github")
        run("--project", str(root), "config", "set", "ci.project", "acme/shop")

        def fake(req, timeout=0):
            if req.full_url.endswith("/actions/runs/8"):
                return _resp({"id": 8})
            return _resp({"artifacts": []})

        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "t"}), mock.patch("urllib.request.urlopen", fake):
            code, _, err = run("--project", str(root), "import-ci", "8")
        self.assertEqual(code, 2)
        self.assertIn("upload-artifact", err)


class GitHubMergeHistoryTests(GitReleaseSpeedTests):
    def test_github_pull_request_merges_are_counted(self) -> None:
        h = 3600
        t0 = int(time.time()) - 5 * 24 * h
        self.git("checkout", "-q", "-b", "main", when=t0)
        self.commit("base", t0)
        self.git("checkout", "-q", "-b", "feature-x", "main", when=t0)
        self.commit("x1", t0 + 1 * h)
        self.git("checkout", "-q", "main", when=t0 + 4 * h)
        self.git("merge", "--no-ff", "-q", "feature-x", "-m", "Merge pull request #7 from acme/feature-x\n\nAdd x", when=t0 + 4 * h)
        run("--project", str(self.tmp), "init")
        run("--project", str(self.tmp), "config", "set", "release.staging_branch", "main")
        _, listed, err = run("--project", str(self.tmp), "release-speed", "--list")
        self.assertIn("!7 feature-x: 3.0 h to staging", listed, err)


class ReportTests(ProjectCase):
    def test_report_and_anonymous_report(self) -> None:
        root = self.init()
        (root / "a.xml").write_text(junit_of(100, 2))
        run("--project", str(root), "record", str(root / "a.xml"), "--wall-minutes", "40", "--source", "ci", "--environment", "CI runner secret-box", "--label", "MR !12 internal")
        (root / "b.xml").write_text(junit_of(100, 1))
        run("--project", str(root), "record", str(root / "b.xml"), "--wall-minutes", "10", "--source", "ci", "--environment", "CI runner secret-box")
        code, out, _ = run("--project", str(root), "report")
        self.assertEqual(code, 0)
        self.assertIn("| CI runner secret-box | 40.0 min | 10.0 min | -75 % | 4.0× |", out)
        run("--project", str(root), "report", "--anonymous")
        anon = (root / ".eng-kit/report-anonymous.md").read_text()
        for secret in ("secret-box", "MR !12", root.name):
            self.assertNotIn(secret, anon)
        self.assertIn("CI project runner", anon)


class ProviderDetectionTests(ProjectCase):
    def test_provider_follows_the_remote_unless_set(self) -> None:
        root = self.init()
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/shop.git"], cwd=root, check=True)
        cfg = engkit.load_config(root)
        self.assertEqual(engkit.ci_provider(root, cfg), "github")
        self.assertEqual(engkit.ci_provider(root, cfg, "https://gitlab.com/a/b/-/jobs/1"), "gitlab")
        run("--project", str(root), "config", "set", "ci.provider", "gitlab")
        self.assertEqual(engkit.ci_provider(root, engkit.load_config(root)), "gitlab")
