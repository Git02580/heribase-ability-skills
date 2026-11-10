"""工作台通过 Node 启动随附 CLI，Windows 不依赖 Unix shebang。"""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "heribase-workspace/scripts"))
import workspace_executor


class CliLaunchTests(unittest.TestCase):
    def test_bundled_javascript_runs_through_node_with_isolated_home(self):
        with patch.object(workspace_executor.shutil, "which", return_value="/node path/node"), patch.object(
            workspace_executor.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b'{"ok":true}', b""),
        ) as run:
            result = workspace_executor.cli_runner(Path("/test user"))(["status"])
        self.assertEqual(result, b'{"ok":true}')
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "/node path/node")
        self.assertEqual(Path(argv[1]).parts[-3:], ("heribase-cli", "bin", "heribase"))
        self.assertEqual(argv[2:], ["status", "--json"])
        self.assertEqual(run.call_args.kwargs["env"]["USERPROFILE"], str(Path("/test user")))


if __name__ == "__main__":
    unittest.main()
