import subprocess
import unittest
from unittest.mock import patch

from docktui.docker_client import DockerClient


class TestComposeLifecycle(unittest.TestCase):
    def test_multiple_files_keep_order_and_project(self):
        client = DockerClient()
        client.docker_bin = "docker"
        with (
            patch("pathlib.Path.is_file", return_value=True),
            patch(
                "subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")
            ) as run,
        ):
            success, _ = client.run_compose_cmd("shop", "base.yml, override.yml", "up")
        self.assertTrue(success)
        self.assertEqual(
            run.call_args.args[0],
            ["docker", "compose", "-p", "shop", "-f", "base.yml", "-f", "override.yml", "up", "-d"],
        )

    def test_missing_remote_config_never_runs_another_local_stack(self):
        client = DockerClient(host="ssh://prod")
        client.docker_bin = "docker"
        with patch("subprocess.run") as run:
            success, error = client.run_compose_cmd("shop", "/does-not-exist/compose.yml", "down")
        self.assertFalse(success)
        self.assertIn("local", error.lower())
        run.assert_not_called()
