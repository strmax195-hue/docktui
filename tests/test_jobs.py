import threading
import time
import unittest


class TestJobs(unittest.TestCase):
    def test_slow_job_does_not_block_submit_and_navigation(self):
        from docktui.jobs import JobRunner

        runner = JobRunner()
        release = threading.Event()
        received = []
        started = time.monotonic()
        self.assertTrue(runner.submit("slow", 0, lambda cancel: release.wait(2), received.append))
        self.assertLess(time.monotonic() - started, 0.15)
        self.assertFalse(runner.submit("slow", 0, lambda cancel: None, received.append))
        self.assertEqual(received, [])
        release.set()
        self.assertTrue(runner.wait_idle(2))
        runner.drain(0)
        self.assertEqual(received, [True])
        runner.shutdown()

    def test_cancelled_and_old_generation_results_are_discarded(self):
        from docktui.jobs import JobRunner

        runner = JobRunner()
        received = []
        runner.submit("old", 1, lambda cancel: "old", received.append)
        self.assertTrue(runner.wait_idle(2))
        runner.drain(2)
        self.assertEqual(received, [])
        runner.submit("cancel", 2, lambda cancel: cancel.wait(2), received.append)
        runner.cancel_all()
        self.assertTrue(runner.wait_idle(2))
        runner.drain(2)
        self.assertEqual(received, [])
        runner.shutdown()

    def test_selection_follows_container_identity(self):
        from unittest.mock import patch

        from docktui.tui import ContainerDashboard

        dashboard = ContainerDashboard()
        dashboard.containers = [{"id": "b", "name": "beta", "state": "running"}]
        with (
            patch.object(dashboard.client, "get_current_context", return_value="default"),
            patch.object(
                dashboard.client,
                "list_containers",
                return_value=[
                    {"id": "a", "name": "alpha", "state": "running"},
                    {"id": "b", "name": "beta", "state": "running"},
                ],
            ),
            patch.object(dashboard.client, "get_container_stats", return_value={}),
        ):
            dashboard.refresh_data()
        self.assertEqual(dashboard.current_selected_container()["id"], "b")

    def test_hotkey_exec_keeps_keyboard_responsive(self):
        from unittest.mock import patch

        from docktui.config import Config
        from docktui.tui import ContainerDashboard

        dashboard = ContainerDashboard(config=Config(hotkey_overlays={"ctrl+l": "slow"}))
        dashboard._running = True
        dashboard.containers = [
            {"id": "a", "name": "alpha", "state": "running"},
            {"id": "b", "name": "beta", "state": "running"},
        ]
        release = threading.Event()

        def slow(*args):
            release.wait(2)
            return "finished"

        try:
            with patch.object(dashboard.client, "exec_command", side_effect=slow):
                start = time.monotonic()
                dashboard._handle_key_main("\x0c")
                dashboard._handle_key_main("down")
                self.assertLess(time.monotonic() - start, 0.15)
                self.assertEqual(dashboard.selected_index, 1)
                release.set()
                self.assertTrue(dashboard.jobs.wait_idle(2))
                dashboard._drain_ui()
                self.assertEqual(dashboard.exec_output_lines, ["finished"])
        finally:
            release.set()
            dashboard.jobs.shutdown()

    def test_cancel_stops_a_real_slow_subprocess(self):
        import sys

        from docktui.jobs import run_cancellable

        cancel = threading.Event()
        timer = threading.Timer(0.1, cancel.set)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaises(RuntimeError):
                run_cancellable(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    cancel,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            self.assertLess(time.monotonic() - started, 1)
        finally:
            timer.cancel()

    def test_navigation_with_large_hosts_and_real_ten_second_command(self):
        import sys
        from unittest.mock import patch
        from docktui.config import Config
        from docktui.docker_client import DockerClient
        from docktui.jobs import run_cancellable
        from docktui.tui import ContainerDashboard

        def slow(client, *args):
            return run_cancellable([sys.executable, '-c', 'import time;time.sleep(10)'], client.cancel_event, capture_output=True, timeout=15).stdout

        for size in (100, 1000):
            with self.subTest(containers=size):
                d = ContainerDashboard(config=Config(hotkey_overlays={"ctrl+l":"slow"}))
                d.containers = [{"id":str(i), "name":f"c{i}", "state":"running"} for i in range(size)]
                d._running = True
                try:
                    with patch.object(DockerClient, 'exec_command', slow):
                        started = time.monotonic()
                        d._handle_key_main('\x0c')
                        d._handle_key_main('down')
                        self.assertLess(time.monotonic()-started, .15)
                        self.assertEqual(d.selected_index, 1)
                        d.jobs.cancel_all()
                        self.assertTrue(d.jobs.wait_idle(2))
                finally:
                    d.jobs.shutdown()
