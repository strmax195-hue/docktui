import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from docktui import __version__
from docktui.cli import main


class TestCli(unittest.TestCase):
    @patch("docktui.cli.ContainerDashboard")
    @patch("sys.argv", ["docktui", "--refresh-interval", "3.5", "--docker-timeout", "12"])
    def test_cli_passes_runtime_options_to_dashboard(self, mock_dashboard):
        main()

        mock_dashboard.assert_called_once()
        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["refresh_interval"], 3.5)
        self.assertEqual(kwargs["docker_timeout"], 12.0)
        self.assertIsNone(kwargs["docker_host"])
        self.assertEqual(kwargs["theme"], "dark")
        # No config file -> no explicit exec_presets override.
        self.assertIsNone(kwargs["exec_presets"])
        # log_tail_limit comes from the Config default when no override exists.
        self.assertEqual(kwargs["log_tail_limit"], 40)
        # New: a Config object must always be passed in.
        self.assertIsNotNone(kwargs["config"])
        self.assertEqual(kwargs["config"].refresh_interval, 3.5)
        mock_dashboard.return_value.run.assert_called_once()

    @patch("sys.argv", ["docktui", "--version"])
    def test_cli_version(self):
        stdout = io.StringIO()

        with self.assertRaises(SystemExit) as cm, redirect_stdout(stdout):
            main()

        self.assertEqual(cm.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())

    @patch("docktui.cli.ContainerDashboard")
    @patch("sys.argv", ["docktui", "--refresh-interval", "0.1", "--docker-timeout", "0.1"])
    def test_cli_clamps_low_runtime_options(self, mock_dashboard):
        main()

        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["refresh_interval"], 0.5)
        self.assertEqual(kwargs["docker_timeout"], 1.0)

    @patch("docktui.cli.ContainerDashboard")
    @patch("sys.argv", ["docktui", "--host", "ssh://user@host", "--theme", "light"])
    def test_cli_passes_host_and_theme_options(self, mock_dashboard):
        main()

        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["docker_host"], "ssh://user@host")
        self.assertEqual(kwargs["theme"], "light")
        self.assertEqual(kwargs["config"].theme, "light")

    @patch("docktui.cli.ContainerDashboard")
    @patch("docktui.cli.load_config")
    @patch("sys.argv", ["docktui"])
    def test_cli_loads_config_defaults(self, mock_load_config, mock_dashboard):
        mock_load_config.return_value = {
            "refresh_interval": 4.5,
            "docker_timeout": 15.0,
            "theme": "high-contrast",
            "exec_presets": ["echo 1"],
            "log_tail_limit": 100,
        }
        main()

        kwargs = mock_dashboard.call_args.kwargs
        self.assertEqual(kwargs["config"].refresh_interval, 4.5)
        self.assertEqual(kwargs["config"].docker_timeout, 15.0)
        self.assertEqual(kwargs["config"].theme, "high_contrast")
        self.assertEqual(kwargs["config"].exec_presets, ["echo 1"])
        self.assertEqual(kwargs["config"].log_tail_limit, 100)


def _fake_client(containers, stats=None, installed=True, daemon=True):
    client = MagicMock()
    client.is_docker_installed.return_value = installed
    client.is_daemon_running.return_value = daemon
    client.list_containers.return_value = containers
    client.get_container_stats.return_value = stats or {}
    return client


def _run(argv):
    stdout = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
        with _CatchExit() as code:
            main(argv)
    return code[0], stdout.getvalue()


class _CatchExit:
    def __enter__(self):
        self.code = [None]
        return self.code

    def __exit__(self, exc_type, exc, tb):
        if exc_type is SystemExit:
            self.code[0] = exc.code
            return True
        return False


CONTAINERS = [
    {
        "id": "aaaaaaaaaaaa",
        "name": "web",
        "state": "running",
        "status": "Up 1 hour (healthy)",
        "image": "nginx",
        "compose_project": "shop",
        "compose_service": "web",
    },
    {
        "id": "bbbbbbbbbbbb",
        "name": "worker",
        "state": "exited",
        "status": "Exited (1) 5 minutes ago",
        "image": "app",
        "compose_project": "shop",
        "compose_service": "worker",
    },
]


class TestCliCommands(unittest.TestCase):
    @patch("docktui.cli.DockerClient")
    def test_status_json(self, mock_client):
        mock_client.return_value = _fake_client(CONTAINERS)
        code, out = _run(["status", "--json", "--no-stats"])
        self.assertEqual(code, 0)
        rows = json.loads(out)
        self.assertEqual([r["name"] for r in rows], ["web", "worker"])
        self.assertEqual(rows[0]["health"], "healthy")
        mock_client.return_value.get_container_stats.assert_not_called()

    @patch("docktui.cli.DockerClient")
    def test_status_reports_unreachable_daemon(self, mock_client):
        mock_client.return_value = _fake_client([], daemon=False)
        code, _ = _run(["status"])
        self.assertEqual(code, 1)

    @patch("docktui.cli.DockerClient")
    def test_check_exit_codes(self, mock_client):
        mock_client.return_value = _fake_client(CONTAINERS)
        code, out = _run(["check"])
        self.assertEqual(code, 2)
        self.assertIn("DOCKTUI CRITICAL", out)
        self.assertIn("worker: exited with code 1", out)

        code, out = _run(["check", "--exclude", "worker"])
        self.assertEqual(code, 0)
        self.assertIn("DOCKTUI OK", out)

        code, out = _run(["check", "-q"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    @patch("docktui.cli.DockerClient")
    def test_check_unknown_when_docker_missing(self, mock_client):
        mock_client.return_value = _fake_client([], installed=False)
        code, out = _run(["check", "--json"])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["status"], "UNKNOWN")

    @patch("docktui.cli.DockerClient")
    def test_host_before_subcommand_is_kept(self, mock_client):
        mock_client.return_value = _fake_client(CONTAINERS)
        _run(["-H", "ssh://admin@box", "check"])
        self.assertEqual(mock_client.call_args.kwargs["host"], "ssh://admin@box")

    def test_config_init_path_and_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "config.json"
            code, out = _run(["--config", str(target), "config", "init"])
            self.assertEqual(code, 0)
            self.assertTrue(target.is_file())
            # Refuses to overwrite without --force.
            code, _ = _run(["--config", str(target), "config", "init"])
            self.assertEqual(code, 1)
            code, out = _run(["--config", str(target), "config", "path"])
            self.assertEqual(out.strip(), str(target))
            code, out = _run(["--config", str(target), "config", "show"])
            self.assertEqual(json.loads(out)["theme"], "dark")

    def test_missing_explicit_config_is_an_error(self):
        code, _ = _run(["--config", "/nonexistent/docktui.json"])
        self.assertEqual(code, 2)

    @patch("docktui.cli.ContainerDashboard")
    def test_no_color_flag_sets_env(self, mock_dashboard):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_COLOR", None)
            main(["--no-color"])
            self.assertEqual(os.environ.get("NO_COLOR"), "1")


if __name__ == "__main__":
    unittest.main()
