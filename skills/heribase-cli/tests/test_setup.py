"""检查实际安装布局和进程调用；所有写入限制在临时目录。"""
import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup.py"


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), "需要轻量的环境检查/安装脚本")
        spec = importlib.util.spec_from_file_location("heribase_setup", SCRIPT)
        self.setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.setup)
        temporary = tempfile.TemporaryDirectory(prefix="HeriBase 空格 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name in self.setup.SKILLS:
            (self.root / name).mkdir()
            (self.root / name / "SKILL.md").write_text("fixture", encoding="utf-8")
        self.cli = self.root / "heribase-cli"
        (self.cli / "bin").mkdir()
        (self.cli / "bin/heribase").write_text("console.log('fixture')", encoding="utf-8")

    def process(self, argv, **kwargs):
        if argv[-1] == "--version":
            value = "v24.15.0"
        elif "version" in argv:
            value = '{"version":"1.0.1"}'
        else:
            value = json.dumps({"python":"3.11.15", "missing":[]})
        return subprocess.CompletedProcess(argv, 0, value, "")

    def test_check_is_read_only_and_uses_node_for_bundled_cli(self):
        before = sorted(str(p) for p in self.root.rglob("*"))
        with patch.object(self.setup.shutil, "which", return_value="node"), patch.object(
            self.setup.subprocess, "run", side_effect=self.process,
        ) as run:
            result = self.setup.check_environment(self.root)
        self.assertTrue(result["ok"], result)
        self.assertEqual(sorted(str(p) for p in self.root.rglob("*")), before)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertIn(["node", str(self.cli / "bin/heribase"), "version", "--json"], calls)
        self.assertFalse(any("login" in call or "status" in call for call in calls))

    def test_missing_skills_and_old_node_are_reported(self):
        (self.root / "heribase-appraisal/SKILL.md").unlink()
        def old_node(argv, **kwargs):
            result = self.process(argv, **kwargs)
            if argv[-1] == "--version":
                result.stdout = "v20.0.0"
            return result
        with patch.object(self.setup.shutil, "which", return_value="node"), patch.object(
            self.setup.subprocess, "run", side_effect=old_node,
        ):
            result = self.setup.check_environment(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(any("heribase-appraisal" in item["detail"] for item in result["checks"] if not item["ok"]))
        self.assertTrue(any("24" in item["detail"] for item in result["checks"] if item["name"] == "node"))

    def test_missing_dependencies_are_not_installed_by_check(self):
        def missing(argv, **kwargs):
            result = self.process(argv, **kwargs)
            if "-c" in argv:
                result.stdout = '{"python":"3.11.15","missing":["Pillow","openpyxl"]}'
            return result
        with patch.object(self.setup.shutil, "which", return_value="node"), patch.object(
            self.setup.subprocess, "run", side_effect=missing,
        ) as run:
            result = self.setup.check_environment(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("--install", json.dumps(result))
        self.assertFalse(any("pip" in call.args[0] for call in run.call_args_list))

    def test_dependency_install_uses_private_venv_and_reports_failure(self):
        (self.cli / "requirements.txt").write_text("Pillow>=11.3,<13\n", encoding="utf-8")
        with patch.object(self.setup.venv, "EnvBuilder") as builder, patch.object(
            self.setup.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "private-index-token"),
        ) as run:
            with self.assertRaisesRegex(RuntimeError, "依赖安装失败") as error:
                self.setup.install_dependencies(self.cli)
        self.assertNotIn("private-index-token", str(error.exception))
        builder.return_value.create.assert_called_once_with(self.cli / ".venv")
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], str(self.setup.venv_python(self.cli)))
        self.assertIn("pip", argv)
        self.assertIn(str(self.cli / "requirements.txt"), argv)

    def test_windows_environment_path_and_launcher_preserve_spaces(self):
        self.assertEqual(self.setup.venv_python(self.cli, windows=True), self.cli / ".venv/Scripts/python.exe")
        self.setup.prepare_cli(self.cli)
        wrapper = (self.cli / "bin/heribase.cmd").read_text(encoding="utf-8")
        self.assertIn('"%~dp0heribase" %*', wrapper)
        self.assertIn("exit /b %errorlevel%", wrapper)

    def test_prepare_preserves_cli_artifact_and_permissions(self):
        bundle = self.cli / "bin/heribase"
        before = bundle.read_bytes(), bundle.stat().st_mode
        self.setup.prepare_cli(self.cli)
        self.assertEqual((bundle.read_bytes(), bundle.stat().st_mode), before)

    def initialize(self, process):
        """从带空格的安装路径运行真实入口；外部进程由各用例提供结果。"""
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(self.setup, "__file__", str(self.cli / "scripts/setup.py")), patch.object(
            self.setup.shutil, "which", return_value="node",
        ), patch.object(self.setup.subprocess, "run", side_effect=process) as run, redirect_stdout(output), redirect_stderr(errors):
            try:
                code = self.setup.main(["--init"])
            except SystemExit as exc:
                code = exc.code
        return code, json.loads(output.getvalue() or "{}"), errors.getvalue(), run

    def status_process(self, authenticated=False, api="https://api.heribase.com"):
        def process(argv, **kwargs):
            if "status" in argv:
                # 即使 CLI 将来添加字段，初始化报告也只转发所需的非敏感状态。
                value = {"api_base_url": api, "authenticated": authenticated,
                         "accountSubject": "fixture-account", "extra": "do-not-forward"}
                return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
            return self.process(argv, **kwargs)
        return process

    def test_init_without_login_succeeds_and_offers_onboarding(self):
        code, report, errors, run = self.initialize(self.status_process())
        self.assertEqual(code, 0, errors)
        self.assertTrue(report["ok"])
        self.assertEqual(report["initialization"], {
            "ok": True, "apiBaseUrl": "https://api.heribase.com", "authenticated": False,
        })
        self.assertTrue(report["onboarding"]["loginPrompt"])
        self.assertTrue(report["onboarding"]["examples"])
        self.assertNotIn("do-not-forward", json.dumps(report))
        self.assertTrue((self.cli / "bin/heribase.cmd").is_file())
        calls = [call.args[0] for call in run.call_args_list]
        self.assertIn(["node", str(self.cli / "bin/heribase"), "status", "--json"], calls)
        self.assertFalse(any("login" in call or "configure" in call or "pip" in call for call in calls))

    def test_init_preserves_existing_api_and_skips_login_prompt(self):
        code, report, errors, run = self.initialize(self.status_process(True, "https://custom.example.test"))
        self.assertEqual(code, 0, errors)
        self.assertEqual(report["initialization"]["apiBaseUrl"], "https://custom.example.test")
        self.assertTrue(report["initialization"]["authenticated"])
        self.assertIsNone(report["onboarding"]["loginPrompt"])
        self.assertFalse(any("configure" in call.args[0] or "login" in call.args[0] for call in run.call_args_list))

    def test_init_configures_existing_cli_only_when_explicitly_unconfigured(self):
        for configure_code in (0, 1):
            with self.subTest(configure_code=configure_code):
                configured = False
                def process(argv, **kwargs):
                    nonlocal configured
                    if "status" in argv and not configured:
                        return subprocess.CompletedProcess(argv, 1, "", "HeriBase CLI is not configured. Run heribase configure --api-base-url <url>.\n")
                    if "configure" in argv:
                        self.assertEqual(argv[2:], ["configure", "--api-base-url", "https://api.heribase.com"])
                        configured = configure_code == 0
                        return subprocess.CompletedProcess(argv, configure_code, "", "")
                    return self.status_process()(argv, **kwargs)
                code, report, errors, _ = self.initialize(process)
                self.assertEqual(code, configure_code, errors)
                self.assertEqual(report["ok"], configure_code == 0)
                if configure_code == 0:
                    self.assertEqual(report["initialization"]["apiBaseUrl"], "https://api.heribase.com")
                else:
                    self.assertNotIn("onboarding", report)

    def test_init_installs_missing_dependencies_then_rechecks(self):
        ready = False
        def process(argv, **kwargs):
            if "-c" in argv and not ready:
                return subprocess.CompletedProcess(argv, 0, '{"python":"3.11.15","missing":["Pillow"]}', "")
            return self.status_process()(argv, **kwargs)
        def install(cli):
            nonlocal ready
            self.assertEqual(cli, self.cli)
            ready = True
        with patch.object(self.setup, "install_dependencies", side_effect=install):
            code, report, errors, _ = self.initialize(process)
        self.assertEqual(code, 0, errors)
        self.assertTrue(report["ok"])
        self.assertTrue(ready)

    def test_init_stops_when_installation_is_incomplete(self):
        (self.root / "heribase-appraisal/SKILL.md").unlink()
        code, report, _, run = self.initialize(self.status_process())
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        self.assertNotIn("onboarding", report)
        self.assertFalse(any("status" in call.args[0] or "pip" in call.args[0] for call in run.call_args_list))

    def test_init_status_failure_or_invalid_output_cannot_report_success(self):
        cases = [(1, "", "sensitive-error"), (0, "not-json", ""),
                 (0, '{"api_base_url":"https://api.heribase.com","authenticated":"false"}', "")]
        for returncode, stdout, stderr in cases:
            with self.subTest(stdout=stdout, returncode=returncode):
                def process(argv, **kwargs):
                    if "status" in argv:
                        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)
                    return self.process(argv, **kwargs)
                code, report, errors, run = self.initialize(process)
                self.assertEqual(code, 1, errors)
                self.assertFalse(report["ok"])
                self.assertFalse(report["initialization"]["ok"])
                self.assertNotIn("onboarding", report)
                self.assertNotIn("sensitive-error", json.dumps(report) + errors)
                self.assertFalse(any("configure" in call.args[0] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
