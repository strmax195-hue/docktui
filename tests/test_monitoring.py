import io
import json
import sys
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from docktui.cli import main


class TestMonitoring(unittest.TestCase):
    def test_prometheus_escaping_limit_units_and_failure(self):
        from docktui.prometheus import format_metrics

        rows = [
            {
                "name": 'a"\\\nb',
                "state": "running",
                "health": "healthy",
                "cpu_percent": 25,
                "mem_percent": 50,
            },
            {"name": "ignored", "state": "running", "health": ""},
        ]
        output = format_metrics(rows, endpoint="prod", collected_at=10, limit=1)
        self.assertIn(
            'docktui_container_cpu_ratio{endpoint="prod",container="a\\"\\\\\\nb"} 0.25', output
        )
        self.assertNotIn("ignored", output)
        self.assertIn('docktui_metrics_truncated{endpoint="prod"} 1', output)
        failed = format_metrics([], success=False)
        self.assertIn('docktui_collection_success{endpoint="local"} 0', failed)
        self.assertNotIn("docktui_container_running{", failed)

    def test_status_preflight_json_is_machine_readable(self):
        with patch("docktui.cli.DockerClient") as factory:
            factory.return_value.is_docker_installed.return_value = False
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(SystemExit) as caught:
                main(["status", "--json"])
            self.assertEqual(caught.exception.code, 1)
            self.assertIn("error", json.loads(out.getvalue()))

    def test_parallel_hosts_are_isolated_and_critical_wins_over_unknown(self):
        raw = {
            "endpoints": [
                {"name": "prod", "host": "ssh://prod"},
                {"name": "bad", "host": "ssh://bad"},
            ]
        }
        from docktui.docker_client import DockerError
        from docktui.report import aggregate_levels

        self.assertEqual(aggregate_levels([1, 3, 2]), 2)
        self.assertEqual(aggregate_levels([0, 1, 3]), 3)

        def containers(client):
            if client.docker_host == "ssh://bad":
                raise DockerError("unreachable")
            return [{"id": "a", "name": "web", "state": "exited", "status": "Exited (3)"}]

        out = io.StringIO()
        with (
            patch("docktui.cli.load_config", return_value=raw),
            patch("docktui.docker_client.shutil.which", return_value="docker"),
            patch("docktui.docker_client.DockerClient.list_containers", containers),
        ):
            with redirect_stdout(out), self.assertRaises(SystemExit) as caught:
                main(["check", "--hosts", "prod,bad", "--json"])
        self.assertEqual(caught.exception.code, 2)
        payload = json.loads(out.getvalue())
        self.assertEqual([h["endpoint"] for h in payload["hosts"]], ["prod", "bad"])
        self.assertIn("unreachable", payload["hosts"][1]["error"])
        self.assertEqual(payload["hosts"][0]["rows"][0]["name"], "web")

    def test_host_deadline_kills_slow_process_and_concurrency_is_bounded(self):
        from docktui.docker_client import DockerClient
        from docktui.multihost import check_hosts

        lock = threading.Lock()
        active = maximum = 0

        def check(name, host, deadline):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                client = DockerClient(host=host)
                client.cancel_event = threading.Event()
                client.deadline = deadline
                client._run(
                    [sys.executable, "-c", "import time;time.sleep(10)"], capture_output=True
                )
            finally:
                with lock:
                    active -= 1

        started = time.monotonic()
        result = check_hosts([("a", "ssh://a"), ("b", "ssh://b")], check, workers=1, timeout=0.1)
        self.assertEqual(maximum, 1)
        self.assertLess(time.monotonic() - started, 1)
        self.assertTrue(all(r["exit_code"] == 3 and r["error"] for r in result))
