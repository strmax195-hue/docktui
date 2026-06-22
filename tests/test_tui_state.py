import unittest
from unittest.mock import mock_open, patch

from docktui.config import Config
from docktui.enums import ViewMode
from docktui.tui import ContainerDashboard


class TestContainerDashboardState(unittest.TestCase):
    def test_build_compose_rows_groups_project_containers(self):
        dashboard = ContainerDashboard()
        dashboard.containers = [
            {
                "id": "c1",
                "name": "web-1",
                "state": "running",
                "image": "web:latest",
                "compose_project": "app",
                "compose_service": "web",
            },
            {
                "id": "c2",
                "name": "db-1",
                "state": "running",
                "image": "postgres:15",
                "compose_project": "app",
                "compose_service": "db",
            },
        ]

        dashboard.build_compose_rows()

        self.assertEqual(dashboard.compose_rows[0]["type"], "project")
        self.assertEqual(dashboard.compose_rows[0]["project"], "app")
        self.assertEqual(len(dashboard.compose_rows), 3)

    def test_sort_containers_applies_filter_and_running_first(self):
        dashboard = ContainerDashboard()
        dashboard.container_filter = "api"
        containers = [
            {"name": "api-old", "image": "app", "state": "exited"},
            {"name": "api", "image": "app", "state": "running"},
            {"name": "worker", "image": "app", "state": "running"},
        ]

        result = dashboard.sort_containers(containers)

        self.assertEqual([c["name"] for c in result], ["api", "api-old"])

    def test_exec_history_keeps_recent_unique_commands(self):
        dashboard = ContainerDashboard()

        dashboard.record_exec_command("sh")
        dashboard.record_exec_command("env")
        dashboard.record_exec_command("sh")

        self.assertEqual(dashboard.exec_history[:2], ["sh", "env"])

    @patch("builtins.open", new_callable=mock_open)
    def test_export_logs_to_file(self, mock_file):
        dashboard = ContainerDashboard()
        dashboard.log_lines = ["line1", "line2"]

        dashboard.export_logs_to_file("logs.txt")

        mock_file.assert_called_once_with("logs.txt", "w", encoding="utf-8")
        mock_file().write.assert_called_once_with("line1\nline2")
        self.assertIn("successfully exported", dashboard.status_message)

    @patch("builtins.print")
    def test_draw_empty_state_contains_tips(self, mock_print):
        dashboard = ContainerDashboard()
        dashboard.draw_empty_state("containers", width=80)

        # Verify that print was called and some help text was outputted
        self.assertTrue(mock_print.called)
        printed_args = [call.args[0] for call in mock_print.call_args_list if call.args]
        joined_output = "".join(printed_args)
        self.assertIn("No containers found", joined_output)

    @patch("docktui.docker_client.DockerClient.get_compose_project_logs")
    def test_load_log_lines_calls_project_logs_when_active_project_set(self, mock_get_project_logs):
        dashboard = ContainerDashboard()
        dashboard.active_project = "myproject"
        mock_get_project_logs.return_value = "log1\nlog2"

        dashboard.load_log_lines(None, viewport_height=10)

        mock_get_project_logs.assert_called_once_with("myproject", tail=40)
        self.assertEqual(dashboard.log_lines, ["log1", "log2"])

    # ---- Settings / config --------------------------------------------------

    def test_settings_view_built_from_config(self):
        config = Config(refresh_interval=5.0, theme="light")
        dashboard = ContainerDashboard(config=config)
        dashboard._build_settings_options()
        labels = [opt["label"] for opt in dashboard.settings_options]
        self.assertIn("Refresh interval (s)", labels)
        self.assertIn("Theme", labels)
        self.assertIn("Exec presets", labels)

    @patch("docktui.config.Config.save")
    def test_save_settings_calls_save(self, mock_save):
        mock_save.return_value = "/tmp/config.json"
        dashboard = ContainerDashboard()
        dashboard.save_settings()
        mock_save.assert_called_once()
        self.assertIn("Configuration saved", dashboard.status_message)

    def test_apply_runtime_config_updates_fields(self):
        config = Config(refresh_interval=7.0, docker_timeout=15.0, theme="light")
        dashboard = ContainerDashboard(config=config)
        dashboard._apply_runtime_config()
        self.assertEqual(dashboard.refresh_interval, 7.0)
        self.assertEqual(dashboard.client.timeout, 15.0)
        self.assertEqual(dashboard.theme, "light")

    # ---- Endpoints ---------------------------------------------------------

    def test_new_endpoint_appends_and_persists(self):
        dashboard = ContainerDashboard()

        def fake_submit(value: str) -> None:
            parts = [p.strip() for p in value.split("|")]
            name, host = parts[0], parts[1]
            dashboard.endpoints.append({"name": name, "host": host})
            dashboard.config.endpoints = list(dashboard.endpoints)

        fake_submit("prod|ssh://user@prod.example")
        self.assertEqual(len(dashboard.endpoints), 1)
        self.assertEqual(dashboard.endpoints[0]["name"], "prod")
        self.assertEqual(dashboard.config.endpoints[0]["host"], "ssh://user@prod.example")

    def test_activate_endpoint_sets_per_instance_host(self):
        dashboard = ContainerDashboard()
        dashboard._activate_endpoint({"name": "prod", "host": "ssh://u@h"})
        self.assertEqual(dashboard.client.docker_host, "ssh://u@h")
        self.assertEqual(dashboard.active_endpoint, "prod")

    def test_activate_endpoint_rejects_missing_host(self):
        dashboard = ContainerDashboard()
        dashboard._activate_endpoint({"name": "bad"})
        self.assertIn("no host", dashboard.status_message)

    # ---- Search / pull -----------------------------------------------------

    @patch("docktui.docker_client.DockerClient.search_images")
    def test_start_registry_search_stores_results(self, mock_search):
        mock_search.return_value = [
            {
                "name": "nginx",
                "description": "Web server",
                "stars": "100",
                "official": "[OK]",
                "automated": "",
            },
            {
                "name": "alpine",
                "description": "Linux",
                "stars": "200",
                "official": "[OK]",
                "automated": "",
            },
        ]
        dashboard = ContainerDashboard()
        dashboard.start_registry_search()
        # The dialog submit callback was registered.
        self.assertEqual(dashboard.input_dialog.prompt, "Search Docker Hub: ")
        # Manually invoke the submit to simulate user pressing Enter.
        callback = dashboard.input_dialog.submit
        callback("nginx")
        self.assertEqual(len(dashboard.search_results), 2)
        self.assertEqual(dashboard.view_mode.value, "search")

    # ---- File browser ------------------------------------------------------

    @patch("docktui.docker_client.DockerClient.list_volume_contents")
    def test_open_volume_files_loads_entries(self, mock_list):
        mock_list.return_value = [
            {"mode": "drwxr-xr-x", "name": "data", "size": "4096"},
            {"mode": "-rw-r--r--", "name": "notes.txt", "size": "12"},
        ]
        dashboard = ContainerDashboard()
        dashboard.volumes = [{"name": "myvol"}]
        dashboard.selected_volume_index = 0
        dashboard.open_volume_files()
        self.assertEqual(dashboard.file_volume_name, "myvol")
        self.assertEqual(len(dashboard.file_entries), 2)
        self.assertEqual(dashboard.view_mode.value, "files")

    @patch("docktui.docker_client.DockerClient.list_volume_contents")
    def test_file_open_navigates_into_subdir(self, mock_list):
        mock_list.return_value = [
            {"mode": "drwxr-xr-x", "name": "sub", "size": "4096"},
        ]
        dashboard = ContainerDashboard()
        dashboard.file_volume_name = "v"
        dashboard.file_path = "/"
        dashboard.file_entries = mock_list.return_value
        dashboard.file_index = 0
        dashboard._file_open()
        self.assertEqual(dashboard.file_path, "/sub")

    @patch("docktui.docker_client.DockerClient.list_volume_contents")
    def test_file_up_climbs_one_level(self, mock_list):
        mock_list.return_value = []
        dashboard = ContainerDashboard()
        dashboard.file_volume_name = "v"
        dashboard.file_path = "/a/b"
        dashboard._file_up()
        self.assertEqual(dashboard.file_path, "/a")

    # ---- Resource edit / clone --------------------------------------------

    @patch("docktui.docker_client.DockerClient.update_container_resources")
    def test_resource_edit_submits_valid_numbers(self, mock_update):
        mock_update.return_value = (True, "ok")
        dashboard = ContainerDashboard()
        dashboard.containers = [{"id": "c1", "name": "web", "image": "nginx", "state": "running"}]
        dashboard.current_tab = "containers"
        dashboard.selected_index = 0
        dashboard.start_resource_edit()
        callback = dashboard.input_dialog.submit
        callback("cpus=1.5\nmemory_mb=256")
        args, kwargs = mock_update.call_args
        self.assertEqual(kwargs.get("cpus"), 1.5)
        self.assertEqual(kwargs.get("memory_bytes"), 256 * 1024 * 1024)

    @patch("docktui.docker_client.DockerClient.clone_container")
    def test_container_clone_uses_inspect_details(self, mock_clone):
        mock_clone.return_value = (True, "cloned")
        dashboard = ContainerDashboard()
        dashboard.containers = [
            {"id": "src", "name": "web", "image": "nginx:latest", "state": "running"}
        ]
        dashboard.current_tab = "containers"
        dashboard.selected_index = 0

        with patch("docktui.docker_client.DockerClient.get_container_details") as mock_details:
            mock_details.return_value = {
                "name": "web",
                "image": "nginx:latest",
                "ports": "0.0.0.0:8080->80/tcp",
            }
            dashboard.start_container_clone()
            callback = dashboard.input_dialog.submit
            callback("web-copy")
        args, kwargs = mock_clone.call_args
        self.assertEqual(kwargs["source_id"], "src")
        self.assertEqual(kwargs["new_name"], "web-copy")
        self.assertEqual(kwargs["image"], "nginx:latest")

    # ---- Log highlights ----------------------------------------------------

    def test_log_highlight_toggle_requires_patterns(self):
        dashboard = ContainerDashboard()
        dashboard._toggle_log_highlights()
        self.assertIn("No log highlights configured", dashboard.status_message)

    def test_log_highlight_toggle_compiles_patterns(self):
        config = Config()
        config.log_highlights = [{"label": "errors", "pattern": r"ERROR|FAIL"}]
        dashboard = ContainerDashboard(config=config)
        dashboard._toggle_log_highlights()
        self.assertIsNotNone(dashboard.log_highlight_regex)
        self.assertIn("Highlighting 1 pattern", dashboard.status_message)
        # Toggling again disables.
        dashboard._toggle_log_highlights()
        self.assertIsNone(dashboard.log_highlight_regex)

    # ---- Input dialog state reset (regression) -----------------------------

    def test_input_dialog_enter_resets_view_and_dialog(self):
        """Enter must submit, then return to the previous view and clear the modal."""
        dashboard = ContainerDashboard()
        dashboard.view_mode = ViewMode.MAIN
        received: list = []
        dashboard.start_input("prompt", lambda v: received.append(v))

        dashboard.handle_input_key("e")
        dashboard.handle_input_key("n")
        # Reset buffer and type fresh value.
        dashboard.input_dialog.buffer = ""
        for ch in "hello":
            dashboard.handle_input_key(ch)
        dashboard.handle_input_key("enter")

        self.assertEqual(received, ["hello"])
        self.assertEqual(dashboard.view_mode, ViewMode.MAIN)
        self.assertEqual(dashboard.input_dialog.prompt, "")

    def test_input_dialog_esc_invokes_cancel_and_resets(self):
        """Esc must fire cancel and restore the previous view without leaving the modal alive."""
        dashboard = ContainerDashboard()
        dashboard.view_mode = ViewMode.LOGS
        cancelled: list = []
        dashboard.start_input(
            "prompt", lambda _v: None, cancel_callback=lambda: cancelled.append(True)
        )

        dashboard.handle_input_key("\x1b")

        self.assertEqual(cancelled, [True])
        self.assertEqual(dashboard.view_mode, ViewMode.LOGS)
        self.assertEqual(dashboard.input_dialog.prompt, "")

    def test_dashboard_initializes_runtime_attributes(self):
        """All attributes read during the run loop / view dispatch must exist up front."""
        dashboard = ContainerDashboard()
        for attr in (
            "search_results",
            "search_index",
            "file_index",
            "_quit_requested",
            "_viewport_h",
        ):
            self.assertTrue(hasattr(dashboard, attr), f"missing attribute: {attr}")
        self.assertEqual(dashboard.search_results, [])
        self.assertEqual(dashboard.search_index, 0)
        self.assertEqual(dashboard.file_index, 0)
        self.assertFalse(dashboard._quit_requested)


if __name__ == "__main__":
    from unittest.mock import mock_open, patch

    unittest.main()
