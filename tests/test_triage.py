import io
import os
import subprocess
import sys
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from docktui import cli
from docktui.demo import DemoSource
from docktui.docker_client import DockerClient, DockerError
from docktui.report import EXIT_CRITICAL, EXIT_OK, EXIT_WARNING
from docktui.triage import (
    DockerSource,
    Evidence,
    Inventory,
    plain_line,
    plain_report,
    rank_containers,
)
from docktui.tui import ContainerDashboard
from docktui.views.triage import TriageScreen, _cells


class TestTriageReports(unittest.TestCase):
    def test_one_row_per_container_even_with_two_findings(self):
        rows = rank_containers(
            [
                {"id": "1", "name": "job", "state": "exited", "status": "Exited (143) 1 hour ago"},
                {
                    "id": "2",
                    "name": "worker",
                    "state": "restarting",
                    "status": "Restarting (1) (unhealthy)",
                },
                {
                    "id": "3",
                    "name": "export",
                    "state": "exited",
                    "status": "Exited (137) 2 minutes ago",
                },
            ]
        )
        self.assertEqual(
            [(c.name, c.level) for c in rows],
            [("worker", EXIT_CRITICAL), ("export", EXIT_WARNING), ("job", EXIT_OK)],
        )
        self.assertEqual(len(rows[0].reasons), 2)
        self.assertIn("1 critical", Inventory("default", rows).summary())

    def test_demo_does_not_load_configuration_or_call_docker(self):
        out = io.StringIO()
        with (
            patch("docktui.cli.DockerClient", side_effect=AssertionError("unexpected Docker")),
            patch("docktui.cli.load_config", side_effect=AssertionError("unexpected config")),
            redirect_stdout(out),
            self.assertRaises(SystemExit) as result,
        ):
            cli.main(["-H", "bad-endpoint", "-c", "nonexistent.json", "demo"])
        self.assertEqual(result.exception.code, 0)
        self.assertIn("2 critical  |  1 warning  |  6 containers", out.getvalue())
        self.assertNotIn("checkout-seed-1", out.getvalue())
        self.assertIn("checkout-seed-1", plain_report(DemoSource(), None, True)[0])

    def test_evidence_for_names_ids_and_unknown_container(self):
        source = DemoSource()
        output, code = plain_report(source, "checkout-api-1", False)
        self.assertEqual(code, 0)
        self.assertIn("GET /ready -> 503", output)
        self.assertIn("Schema version 18 required", output)
        self.assertEqual(output, plain_report(source, "000000000001", False)[0])
        self.assertIn(
            "Docker recorded an out-of-memory kill.",
            plain_report(source, "reports-export-1", False)[0],
        )
        self.assertIn("Restart count  7", plain_report(source, "checkout-worker-1", False)[0])
        self.assertIn("Exit code  137", plain_report(source, "reports-export-1", False)[0])
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as result:
            cli.main(["demo", "unknown", "--plain"])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("was not found on checkout-lab", err.getvalue())

    def test_missing_docker_gives_actionable_error(self):
        with (
            patch.object(DockerClient, "is_docker_installed", return_value=False),
            redirect_stderr(io.StringIO()) as err,
            self.assertRaises(SystemExit) as result,
        ):
            cli.main(["triage", "--plain"])
        self.assertEqual(result.exception.code, 1)
        self.assertIn("docktui demo", err.getvalue())

    def test_inspect_and_log_failures_preserve_other_evidence(self):
        source = DemoSource()
        with patch.object(
            source,
            "evidence",
            return_value=Evidence.from_output({"error": "removed"}, "retained line"),
        ):
            output, code = plain_report(source, "checkout-api-1", False)
        self.assertEqual(code, 1)
        self.assertIn("Inspect unavailable  removed", output)
        self.assertIn("retained line", output)
        evidence = Evidence.from_output(
            {"restart_count": "4"}, "", "logging driver does not support reading"
        )
        self.assertTrue(evidence.incomplete)
        self.assertIn("Restart count  4", evidence.inspection)
        self.assertIn("Logs unavailable", evidence.logs[0])
        self.assertNotIn("Docker recorded an out-of-memory kill.", evidence.inspection)

    def test_logs_are_bounded_and_strip_terminal_controls(self):
        lines = ["discard" + str(i) for i in range(40)] + [
            "x" * 8000,
            "\x1b[31mошибка\x1b[0m \x1b]0;bad title\x07data",
        ]
        evidence = Evidence.from_output({}, "\n".join(lines))
        self.assertEqual(len(evidence.logs), 40)
        self.assertEqual(evidence.logs[0], "discard2")
        self.assertEqual(len(evidence.logs[-2]), 4096)
        self.assertEqual(evidence.logs[-1], "ошибка data")

    def test_inventory_and_evidence_keep_connection_that_produced_the_row(self):
        calls = []

        def capture(client, cmd, **kwargs):
            env = client.command_env()
            calls.append(
                (cmd[1], env.get("DOCKER_CONTEXT"), env.get("DOCKER_HOST"), client.cancel_event)
            )
            responses = {
                "context": "east",
                "ps": "abc|worker|running|Up 2 days|example|labels||",
                "inspect": '[{"RestartCount": 4}]',
                "logs": "some logs",
            }
            return subprocess.CompletedProcess(cmd, 0, responses[cmd[1]], "")

        cancel = threading.Event()
        with patch.dict(os.environ, {}, clear=True), patch.object(DockerClient, "_run", capture):
            client = DockerClient()
            client.docker_bin = "docker"
            source = DockerSource(client)
            snapshot = source.scan(cancel)
            client.set_host("ssh://other")
            os.environ["DOCKER_CONTEXT"] = "west"
            data = source.evidence(snapshot, snapshot.cases[0], cancel)
            explicit = DockerSource(client)
            self.assertEqual(explicit.scan(cancel).connection, "ssh://other")
        self.assertEqual(snapshot.connection, "east")
        self.assertEqual([op for op, *_ in calls], ["context", "ps", "inspect", "logs", "ps"])
        self.assertEqual([context for _, context, _, _ in calls[1:4]], ["east"] * 3)
        self.assertTrue(all(event is cancel for _, _, _, event in calls))
        self.assertEqual(calls[-1][1:3], (None, "ssh://other"))
        self.assertEqual(data.logs, ["some logs"])
        self.assertIn("Restart count  4", data.inspection)

    def test_log_snapshots_include_interleaved_stderr_and_report_command_errors(self):
        client = DockerClient()
        client.docker_bin = sys.executable
        command = [
            sys.executable,
            "-u",
            "-c",
            "import sys;print('first');print('error', file=sys.stderr);print('last')",
        ]
        with patch.object(client, "logs_command", return_value=command):
            self.assertEqual(client.get_logs("a").splitlines(), ["first", "error", "last"])
            self.assertEqual(
                client.get_compose_project_logs("stack").splitlines(), ["first", "error", "last"]
            )
        command[-1] = "import sys;print('unavailable', file=sys.stderr);sys.exit(1)"
        with patch.object(client, "logs_command", return_value=command):
            with self.assertRaisesRegex(DockerError, "unavailable"):
                client.read_logs("a")
            self.assertEqual(client.get_logs("a"), "unavailable")


class TestTriageScreen(unittest.TestCase):
    def screen(self, source):
        screen = TriageScreen(source, interval=1000)
        self.addCleanup(screen.close)
        return screen

    def load_screen(self, screen):
        screen.tick()
        self.assertTrue(screen.jobs.wait_idle(3))
        screen.tick()

    def test_reorder_stale_empty_and_recovery(self):
        source = DemoSource()
        initial = source.scan(threading.Event())
        reduced = Inventory(initial.connection, initial.cases[1:])
        with patch.object(
            source,
            "scan",
            side_effect=[
                initial,
                reduced,
                DockerError("daemon offline"),
                Inventory(initial.connection, []),
            ],
        ):
            screen = self.screen(source)
            self.load_screen(screen)
            screen.key("down")
            screen.key("r")
            self.load_screen(screen)
            self.assertEqual(screen.rows[screen.index].name, "checkout-worker-1")
            screen.key("r")
            self.load_screen(screen)
            rendered = "\n".join(screen.render(80, 24))
            self.assertIn("Stale inventory  daemon offline", rendered)
            self.assertIn("checkout-worker-1", rendered)
            screen.key("r")
            self.load_screen(screen)
            self.assertIn("No containers found", "\n".join(screen.render(80, 24)))
            self.assertFalse(screen.error)

    def test_a_slow_old_response_cannot_replace_new_selection(self):
        source = DemoSource()
        block = threading.Event()
        started = threading.Event()
        original = source.evidence

        def read(inventory, case, cancel):
            if case.name == "checkout-api-1":
                started.set()
                block.wait(3)
            return original(inventory, case, cancel)

        with patch.object(source, "evidence", side_effect=read):
            screen = self.screen(source)
            self.load_screen(screen)
            screen.key("enter")
            self.assertTrue(started.wait(2))
            screen.key("\x1b")
            screen.key("down")
            screen.key("enter")
            block.set()
            self.load_screen(screen)
            report = "\n".join(screen.render(80, 24))
            self.assertIn("QUEUE_URL", report)
            self.assertNotIn("Schema version", report)

    def test_sizing_navigation_and_disconnected_first_scan(self):
        source = DemoSource()
        screen = self.screen(source)
        with patch.object(source, "scan", side_effect=DockerError("permission denied")):
            self.load_screen(screen)
        self.assertIn("Collection failed", "\n".join(screen.render(80, 24)))
        self.assertNotIn("No health or exit problems", "\n".join(screen.render(80, 24)))
        screen.key("r")
        self.load_screen(screen)
        screen.key("a")
        screen.key("end")
        self.assertEqual(screen.rows[screen.index].name, "checkout-seed-1")
        screen.key("home")
        screen.key("enter")
        self.load_screen(screen)
        screen.detail.logs.append("界" * 100)
        for cols, rows in [(80, 24), (36, 10), (2, 3)]:
            for key in ("home", "page_down", "end", "page_up", "?"):
                screen.key(key)
                frame = screen.render(cols, rows)
                self.assertLessEqual(len(frame), rows)
                self.assertTrue(
                    all(sum(_cells(c) for c in plain_line(line)) < cols for line in frame)
                )
            screen.key("?")
        self.assertTrue(screen.key("\x1b"))
        self.assertFalse(screen.key("q"))

    def test_dashboard_round_trip_preserves_tab_and_selection(self):
        dashboard = ContainerDashboard()
        self.addCleanup(dashboard.jobs.shutdown)
        self.addCleanup(dashboard._close_triage)
        dashboard.current_tab = "compose"
        dashboard.selected_compose_index = 7
        with patch("docktui.tui.DockerSource", return_value=DemoSource()):
            dashboard._handle_key_main("!")
        self.load_screen(dashboard.triage_screen)
        self.assertEqual(dashboard.view_mode, "triage")
        dashboard._handle_key_triage("enter")
        dashboard._handle_key_triage("\x1b")
        self.assertEqual(dashboard.view_mode, "triage")
        dashboard._handle_key_triage("\x1b")
        self.assertIsNone(dashboard.triage_screen)
        self.assertEqual(
            (dashboard.view_mode, dashboard.current_tab, dashboard.selected_compose_index),
            ("main", "compose", 7),
        )
