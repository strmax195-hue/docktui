import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from docktui.cli import main
from docktui.config import Config
from docktui.docker_client import DockerClient
from docktui.tui import ContainerDashboard


class TestConnectionIsolation(unittest.TestCase):
    def test_constructor_does_not_change_global_host(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "ssh://original"}):
            first = DockerClient(host="ssh://a")
            second = DockerClient(host="ssh://b")
            self.assertEqual(os.environ["DOCKER_HOST"], "ssh://original")
            self.assertEqual(first.docker_host, "ssh://a")
            self.assertEqual(second.docker_host, "ssh://b")

    def test_explicit_host_overrides_docker_context(self):
        with patch.dict(os.environ, {"DOCKER_CONTEXT": "prod"}):
            client = DockerClient(host="ssh://stage")
            self.assertNotIn("DOCKER_CONTEXT", client._env())

    def test_config_endpoint_is_used_at_startup(self):
        config = Config(endpoints=[{"name": "prod", "host": "ssh://prod"}], active_endpoint="prod")
        with patch.dict(os.environ, {}, clear=True):
            dashboard = ContainerDashboard(config=config)
        self.assertEqual(dashboard.client.docker_host, "ssh://prod")

    def test_unknown_config_endpoint_is_an_error(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("docktui.cli.load_config", return_value={"active_endpoint": "missing"}),
            redirect_stderr(io.StringIO()),
        ):
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(["check", "--quiet"])
        self.assertEqual(caught.exception.code, 2)

    def test_logs_receive_selected_host(self):
        dashboard = ContainerDashboard()
        dashboard.client.set_host("ssh://prod")
        with patch("subprocess.Popen", side_effect=OSError("not starting")) as spawn:
            dashboard.start_log_stream("c", None)
        self.assertEqual(spawn.call_args.kwargs.get("env", {}).get("DOCKER_HOST"), "ssh://prod")

    def test_interactive_exec_receives_selected_host(self):
        dashboard = ContainerDashboard()
        dashboard.client.set_host("ssh://prod")
        dashboard.client.docker_bin = "docker"
        with (
            patch.object(dashboard, "start_refresh_worker"),
            patch("subprocess.run") as run,
            redirect_stdout(io.StringIO()),
        ):
            dashboard.run_interactive_exec("c", "web", "sh")
        self.assertEqual(run.call_args.kwargs.get("env", {}).get("DOCKER_HOST"), "ssh://prod")

    def test_switch_discards_old_data_and_streams(self):
        dashboard = ContainerDashboard()
        dashboard.containers = [{"id": "old"}]
        dashboard.log_lines = ["old log"]
        with (
            patch.object(dashboard, "refresh_data"),
            patch.object(dashboard, "stop_log_stream") as stop,
        ):
            dashboard._activate_endpoint({"name": "stage", "host": "ssh://stage"})
        self.assertEqual(dashboard.containers, [])
        self.assertEqual(dashboard.log_lines, [])
        stop.assert_called_once()

