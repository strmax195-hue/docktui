import unittest

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


if __name__ == "__main__":
    unittest.main()
