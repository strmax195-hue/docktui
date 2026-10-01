import subprocess
import unittest
from unittest.mock import patch

from docktui.config import Config
from docktui.docker_client import DockerClient
from docktui.tui import ContainerDashboard


class TestLogWindows(unittest.TestCase):
    def test_filters_and_follow_keep_received_history(self):
        dashboard = ContainerDashboard()
        dashboard._apply_log_text("hello\nERROR boom", 10, False)
        dashboard.log_errors_only = True
        dashboard._on_log_line("ordinary line")
        self.assertEqual(dashboard.visible_log_lines(), ["ERROR boom"])
        dashboard._handle_key_logs("c")
        self.assertEqual(dashboard.visible_log_lines(), ["hello", "ERROR boom", "ordinary line"])
        dashboard._handle_key_logs("f")
        self.assertEqual(len(dashboard.log_lines), 3)

    def test_search_keeps_buffer_and_empty_windows_are_not_reloaded(self):
        d = ContainerDashboard()
        d._apply_log_text("hello\nERROR boom", 10, False)
        with patch.object(d, "prompt_user", return_value="ERROR"):
            d._start_log_search()
        self.assertEqual(d.log_lines, ["hello", "ERROR boom"])
        self.assertEqual(d.visible_log_lines(), ["ERROR boom"])
        d._apply_log_text("", 10, False)
        self.assertTrue(d._logs_loaded)
        self.assertEqual(d.log_lines, [])

    def test_time_options_are_before_target_for_container_and_compose(self):
        client = DockerClient()
        client.docker_bin = "docker"
        for project in (None, "app"):
            cmd = client.logs_command(
                "id", project, since="1h", until="2026-10-01T00:00:00Z" if project is None else "", timestamps=True
            )
            self.assertIn("--since=1h", cmd)
            if project is None:
                self.assertIn("--until=2026-10-01T00:00:00Z", cmd)
            self.assertIn("--timestamps", cmd)
            if project is None:
                self.assertEqual(cmd[-1], "id")
            else:
                self.assertEqual(cmd[:5], ["docker", "compose", "-p", "app", "logs"])
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertEqual(client.get_logs("id", since="1h"), "")

    def test_service_preset_wins_and_config_roundtrip_retains_it(self):
        config = Config.from_dict(
            {"log_presets": {"service:app/web": [{"pattern": "panic", "label": "fatal"}]}}
        )
        d = ContainerDashboard(config=config)
        d.active_container = {"name": "web-1", "compose_project": "app", "compose_service": "web"}
        d._toggle_log_highlights()
        self.assertIsNotNone(d.log_highlight_regex.search("PANIC"))
        self.assertIn("log_presets", config.to_dict())
