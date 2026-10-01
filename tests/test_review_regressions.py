import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from docktui.config import Config
from docktui.docker_client import DockerClient
from docktui.enums import ViewMode
from docktui.log_stream import LineStreamer
from docktui.prometheus import format_metrics
from docktui.tui import ContainerDashboard


class TestReviewRegressions(unittest.TestCase):
    def test_global_highlights_survive_load_save(self):
        patterns = [{"label": "errors", "pattern": "error"}]
        cfg = Config.from_dict({"log_highlights": patterns})
        self.assertEqual(cfg.log_highlights, patterns)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            cfg.save(path)
            self.assertEqual(Config.load(path).log_highlights, patterns)

    def test_context_switch_invalidates_old_host_state_and_pins_every_command(self):
        with patch.dict("os.environ", {}, clear=True):
            d = ContainerDashboard()
            d.current_context = "old"
            d.current_tab = "contexts"
            d.contexts = [{"name": "new"}]
            d.active_container = {"id": "old"}
            generation = d.client.connection_generation
            with (
                patch.object(d.client, "use_context", return_value=(True, "Switched")),
                patch.object(d, "refresh_data"),
                patch.object(d, "stop_log_stream") as stop,
            ):
                d.use_selected_context()
            self.assertEqual(d.current_context, "new")
            self.assertGreater(d.client.connection_generation, generation)
            self.assertIsNone(d.active_container)
            stop.assert_called_once()
            self.assertEqual(d.client.command_env()["DOCKER_CONTEXT"], "new")
            self.assertEqual(
                d.client.snapshot(d.current_context).command_env()["DOCKER_CONTEXT"], "new"
            )

    def test_latest_view_request_replaces_slow_old_target(self):
        d = ContainerDashboard()
        d._running = True
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def details(cid):
            calls.append(cid)
            if cid == "a":
                entered.set()
                release.wait(1)
            return {"name": cid}

        d.client.get_container_details = details
        try:
            d.containers = [{"id": "a", "name": "a"}, {"id": "b", "name": "b"}]
            d._open_details_view()
            self.assertTrue(entered.wait(1))
            d.selected_index = 1
            d._open_details_view()
            release.set()
            self.assertTrue(d.jobs.wait_idle(2))
            d._drain_ui()
            self.assertEqual(calls, ["a", "b"])
            self.assertIn("Name: b", d.details_lines)
        finally:
            release.set()
            d.jobs.shutdown()

    def test_real_epoch_is_preserved_in_freshness_gauge(self):
        output = format_metrics([], collected_at=1790801234)
        line = next(
            line
            for line in output.splitlines()
            if line.startswith("docktui_collection_timestamp_seconds{")
        )
        self.assertEqual(float(line.rsplit(" ", 1)[1]), 1790801234)

    def test_stream_start_failure_completes_once_and_events_retry(self):
        completed = []
        stream = LineStreamer(["/definitely/missing/docktui"], on_complete=completed.append)
        self.assertIsNotNone(stream.start())
        stream.stop()
        self.assertEqual(len(completed), 1)
        self.assertTrue(completed[0].error)
        d = ContainerDashboard()
        d.client.docker_bin = "/definitely/missing/docktui"
        d.active_container = {"id": "a", "name": "a"}
        d.events_enabled = True
        d._start_events()
        d._drain_ui()
        self.assertIsNone(d.event_streamer)
        self.assertIn("disconnected", d.event_feed.status)

    def test_finite_window_cannot_follow_through_pin_or_direct_start(self):
        d = ContainerDashboard()
        d.view_mode = ViewMode.LOGS
        d.active_container = {"id": "a", "name": "a"}
        d.log_until = "2026-10-01T00:00:00Z"
        d.pin_current_view()
        self.assertFalse(d.log_follow)
        with patch("docktui.tui.LineStreamer") as stream:
            d.start_log_stream("a", None)
            stream.assert_not_called()

    def test_compose_until_collects_supported_container_windows(self):
        c = DockerClient()
        c.docker_bin = "docker"
        with (
            patch.object(
                c,
                "list_containers",
                return_value=[
                    {"id": "a", "name": "web", "compose_project": "app", "compose_service": "web"},
                    {"id": "b", "compose_project": "other"},
                ],
            ),
            patch.object(c, "get_logs", return_value="line") as logs,
        ):
            output = c.get_compose_project_logs("app", since="1h", until="2026-10-01T00:00:00Z")
        logs.assert_called_once_with("a", tail=40, since="1h", until="2026-10-01T00:00:00Z")
        self.assertIn("line", output)
