import unittest
from unittest.mock import patch, mock_open

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
        from unittest.mock import mock_open
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


if __name__ == "__main__":
    from unittest.mock import patch, mock_open
    unittest.main()

