"""Regressions at the keyboard, asynchronous refresh and Docker action boundaries."""

import io
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from docktui.config import Config
from docktui.enums import ViewMode
from docktui.screen import TerminalSize
from docktui.snapshot import DashboardSnapshot
from docktui.tui import ContainerDashboard


class TestDashboardWorkflows(unittest.TestCase):
    def setUp(self):
        self.dashboard = ContainerDashboard()
        self.addCleanup(self.dashboard.jobs.shutdown)

    def test_compose_refresh_preserves_service_and_project_action_targets(self):
        d = self.dashboard
        d.current_tab = "compose"

        def service(name):
            return {"id": name, "name": name, "state": "running", "compose_project": "shop"}

        web, worker = service("web"), service("worker")
        d._apply_snapshot(DashboardSnapshot("compose", "default", [worker, web]))
        d.selected_compose_index = 2
        d._apply_snapshot(DashboardSnapshot("compose", "default", [service("api"), web, worker]))
        with patch.object(d, "_action") as action:
            d._handle_key_main("r")
            action.assert_called_once_with("restart_container", "worker")

        d._apply_snapshot(DashboardSnapshot("compose", "default", [web]))
        self.assertEqual(d.current_selected_container()["id"], "web")
        d.selected_compose_index = 0
        d._apply_snapshot(DashboardSnapshot("compose", "default", [web, worker]))
        with patch.object(d, "_action") as action:
            d._handle_key_main("r")
            action.assert_called_once_with("bulk_container_action", "restart", ["web", "worker"])

    def test_action_waits_for_new_filter_results(self):
        d = self.dashboard
        d._apply_snapshot(
            DashboardSnapshot(
                "containers", "default", [{"id": "a", "name": "alpha", "state": "running"}]
            )
        )
        d.filters["containers"] = "bravo"
        with patch.object(d, "_action") as action:
            d._handle_key_main("s")
            action.assert_not_called()
            d._apply_snapshot(
                DashboardSnapshot(
                    "containers", "default", [{"id": "b", "name": "bravo", "state": "running"}]
                )
            )
            d._handle_key_main("s")
            action.assert_called_once_with("stop_container", "b")

    def test_tabs_keep_independent_selections_and_image_tags(self):
        d = self.dashboard
        rows = [{"id": c, "name": c, "compose_project": "shop"} for c in ("a", "b", "c")]
        d._apply_snapshot(DashboardSnapshot("containers", "local", rows))
        d.selected_index = 2
        d.selected_compose_index = 2  # b in the Compose tab
        d.current_tab = "compose"
        d._apply_snapshot(DashboardSnapshot("compose", "local", list(reversed(rows))))
        self.assertEqual(d.current_selected_container()["id"], "b")
        self.assertEqual(d.containers[d.selected_index]["id"], "c")
        d.current_tab = "images"
        tags = [{"id": "shared", "repository": "app", "tag": tag} for tag in ("one", "two")]
        d._apply_snapshot(DashboardSnapshot("images", "local", tags))
        d.selected_image_index = 1
        d._apply_snapshot(DashboardSnapshot("images", "local", list(reversed(tags))))
        self.assertEqual(d.images[d.selected_image_index]["tag"], "two")

    def test_help_opens_on_the_current_view_and_returns_there(self):
        d = self.dashboard
        d.view_mode = ViewMode.LOGS
        self.assertTrue(d.keymap.dispatch("logs", "?"))
        with patch("docktui.views.dialogs.get_terminal_size", return_value=TerminalSize(80, 24)):
            output = io.StringIO()
            with redirect_stdout(output):
                d.draw_help_view()
            self.assertIn("Set a time window", output.getvalue())
            self.assertLessEqual(len(output.getvalue().splitlines()), 24)
            d._handle_key_help("page_down")
            self.assertGreater(d.help_scroll_index, 0)
            d._handle_key_help("home")
            self.assertEqual(d.help_scroll_index, 0)
        d._handle_key_help("\x1b")
        self.assertEqual(d.view_mode, ViewMode.LOGS)

    def test_typed_text_and_esc_do_not_invoke_shortcuts(self):
        d = self.dashboard
        answers = []
        d.start_input("Filter", answers.append)
        for ch in "queue?":
            d.handle_input_key(ch)
        d.handle_input_key("enter")
        self.assertEqual(answers, ["queue?"])
        d.start_input("Filter", answers.append)
        d.handle_input_key("q")
        d.handle_input_key("\x1b")
        self.assertEqual(answers, ["queue?"])
        self.assertFalse(d._quit_requested)

    def test_default_exec_presets_and_explicit_empty_list(self):
        self.assertEqual(Config.from_dict({}).exec_presets, Config().exec_presets)
        self.assertEqual(Config.from_dict({"exec_presets": []}).exec_presets, [])

    def test_multiline_editor_preserves_existing_highlights_until_valid_and_saved(self):
        d = self.dashboard
        d.config.log_highlights = [{"label": "errors", "pattern": "panic|fatal"}]
        d.view_mode = ViewMode.SETTINGS
        d._build_settings_options()
        d.settings_index = next(
            i for i, opt in enumerate(d.settings_options) if opt["key"] == "log_highlights"
        )
        with patch.object(d.config, "save") as save:
            d._handle_key_settings("enter")
            self.assertEqual(d.input_dialog.buffer, "errors=panic|fatal")
            for ch in "\x0equeue=timeout":
                d.handle_input_key(ch)
            d.handle_input_key("enter")
            self.assertEqual(d.config.log_highlights[-1], {"label": "queue", "pattern": "timeout"})
            d._handle_key_settings("enter")
            for ch in "\x15invalid=[":
                d.handle_input_key(ch)
            d.handle_input_key("enter")
            self.assertEqual(len(d.config.log_highlights), 2)
            self.assertIn("failed", d.status_message)
            save.assert_not_called()
            d._handle_key_settings("s")
            save.assert_called_once()

    def test_slow_search_cannot_pull_previous_results_or_reopen_after_back(self):
        d = self.dashboard
        d.current_tab = "images"
        d._running = True
        d.search_results = [{"name": "old"}]
        release = threading.Event()
        with patch.object(
            d.client, "search_images", side_effect=lambda _: release.wait(1) and [{"name": "new"}]
        ):
            d.start_registry_search()
            d.input_dialog.buffer = "new"
            d.submit_input()
            self.assertEqual(d.search_results, [])
            with patch.object(d.client, "pull_image_args") as pull:
                d._handle_key_search("enter")
                pull.assert_not_called()
            d._handle_key_search("\x1b")
            release.set()
            self.assertTrue(d.jobs.wait_idle(2))
            d._drain_ui()
        self.assertEqual(
            (d.view_mode, d.current_tab, d.search_results), (ViewMode.MAIN, "images", [])
        )

    def test_empty_volume_directory_backspace_and_export(self):
        d = self.dashboard
        d.volumes = [{"name": "data"}]
        directory = {"name": "queue", "mode": "drwxr-xr-x", "size": "4096"}
        with patch.object(
            d.client, "list_volume_contents", side_effect=[[directory], [], [directory]]
        ):
            d.open_volume_files()
            d._handle_key_files("enter")
            self.assertEqual(d.file_path, "/queue")
            self.assertIn("empty", d.file_message)
            d._handle_key_files("backspace")
            self.assertEqual((d.view_mode, d.file_path), (ViewMode.FILES, "/"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.txt"
            d._handle_key_files("o")
            d.input_dialog.buffer = str(path)
            d.submit_input()
            self.assertEqual(path.read_text(), "drwxr-xr-x        4096  queue")
            self.assertEqual(d.view_mode, ViewMode.FILES)

    def test_pull_output_follows_and_preserves_completion_on_exit(self):
        d = self.dashboard
        d.search_results = [{"name": "sample"}]
        d._running = True
        command = [sys.executable, "-c", "for i in range(45): print(f'layer {i}')"]
        with patch.object(d.client, "pull_image_args", return_value=command):
            d._pull_selected_image()
        stream = d.pull_streamer
        self.addCleanup(stream.stop)
        for thread in stream._threads:
            thread.join(3)
        d._drain_ui()
        self.assertEqual(stream.result.returncode, 0)
        with patch("docktui.views.dialogs.get_terminal_size", return_value=TerminalSize(80, 24)):
            out = io.StringIO()
            with redirect_stdout(out):
                d.draw_pull_progress_view()
            self.assertIn("layer 44", out.getvalue())
            self.assertNotIn("layer 0\n", out.getvalue())
            self.assertIn("finished", out.getvalue())
        d._handle_key_pull("home")
        self.assertFalse(d.pull_follow)
        d._handle_key_pull("end")
        self.assertTrue(d.pull_follow)
        d._handle_key_pull("\x1b")
        self.assertIn("finished", d.status_message)

    def test_saved_endpoint_is_selectable_alongside_context_of_same_name(self):
        with patch.dict(os.environ, {}, clear=True):
            config = Config(
                endpoints=[
                    {"name": "prod", "host": "ssh://prod"},
                    {"name": "other", "host": "ssh://other"},
                ]
            )
            d = ContainerDashboard(config=config)
            self.addCleanup(d.jobs.shutdown)
            d.current_tab = "contexts"
            contexts = [
                {
                    "name": "prod",
                    "current": "*",
                    "description": "",
                    "endpoint": "unix:///docker.sock",
                }
            ]
            d._apply_snapshot(DashboardSnapshot("contexts", "default", contexts))
            self.assertFalse(d.daemon_running)  # Listing contexts does not contact the daemon.
            d.selected_context_index = 1
            d._apply_snapshot(DashboardSnapshot("contexts", "default", contexts))
            with patch.object(d, "refresh_data"):
                d._handle_key_main("enter")
                self.assertEqual(d.client.command_env()["DOCKER_HOST"], "ssh://prod")
                d.filters["contexts"] = "other"
                d.selected_context_index = 0
                d._handle_key_main("u")
                self.assertEqual(d.client.command_env()["DOCKER_HOST"], "ssh://other")
            self.assertNotIn("DOCKER_HOST", os.environ)

    def test_background_poll_does_not_consume_escape(self):
        d = self.dashboard
        release = threading.Event()
        try:
            d.jobs.submit("refresh", 0, lambda _: release.wait(2), lambda _: None)
            self.assertFalse(d.jobs.cancel_foreground())
            d.jobs.submit("action", 0, lambda _: release.wait(2), lambda _: None)
            self.assertTrue(d.jobs.cancel_foreground())
            self.assertFalse(d.jobs.cancel_foreground())
        finally:
            release.set()
            self.assertTrue(d.jobs.wait_idle(3))
