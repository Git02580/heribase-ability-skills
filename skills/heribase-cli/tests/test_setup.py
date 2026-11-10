"""检查实际安装布局和进程调用；所有写入限制在临时目录。"""
import importlib.util
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
        self.root = Path(temporary.name)
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


if __name__ == "__main__":
    unittest.main()
