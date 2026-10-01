"""Regression tests for collection failures after a successful daemon probe."""
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from docktui.cli import main
from docktui.docker_client import DockerClient
from docktui.tui import ContainerDashboard


class TestCollectionErrors(unittest.TestCase):
    def test_ps_failure_is_not_an_empty_list(self):
        client = DockerClient()
        client.docker_bin = 'docker'
        error = subprocess.CalledProcessError(1, ['docker', 'ps'], stderr='permission denied')
        with patch('subprocess.run', side_effect=error), self.assertRaises(RuntimeError):
            client.list_containers()

    def test_stats_timeout_is_not_an_empty_mapping(self):
        client = DockerClient()
        client.docker_bin = 'docker'
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('docker', 10)):
            with self.assertRaises(RuntimeError):
                client.get_container_stats()

    def test_check_returns_unknown_for_failed_collection(self):
        for options in ([], ['--json'], ['--quiet']):
            with self.subTest(options=options), patch('docktui.cli.DockerClient') as factory:
                client = factory.return_value
                client.is_docker_installed.return_value = True
                client.is_daemon_running.return_value = True
                client.list_containers.side_effect = subprocess.CalledProcessError(
                    1, ['docker', 'ps'], stderr='permission denied'
                )
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaises(SystemExit) as caught:
                    main(['check', *options])
                self.assertEqual(caught.exception.code, 3)
                if '--json' in options:
                    self.assertEqual(json.loads(output.getvalue())['status'], 'UNKNOWN')
                elif '--quiet' in options:
                    self.assertEqual(output.getvalue(), '')
                else:
                    self.assertIn('UNKNOWN', output.getvalue())

    def test_successful_empty_check_is_ok(self):
        with patch('docktui.cli.DockerClient') as factory:
            factory.return_value.list_containers.return_value = []
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(['check'])
            self.assertEqual(caught.exception.code, 0)

    def test_refresh_failure_preserves_snapshot(self):
        dashboard = ContainerDashboard()
        previous = [{'id': 'a', 'name': 'web', 'state': 'running'}]
        dashboard.containers = previous
        with patch.object(dashboard.client, 'get_current_context', return_value='default'):
            with patch.object(dashboard.client, 'list_containers', side_effect=RuntimeError('timeout')):
                dashboard.refresh_data()
        self.assertEqual(dashboard.containers, previous)
        self.assertFalse(dashboard.refresh_in_progress)
        self.assertIn('timeout', dashboard.refresh_error)

    def test_required_stats_cannot_be_silently_missing(self):
        with patch('docktui.cli.DockerClient') as factory:
            client = factory.return_value
            client.list_containers.return_value = [
                {'id': 'a', 'name': 'web', 'state': 'running', 'status': 'Up'}
            ]
            client.get_container_stats.return_value = {}
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                main(['check', '--cpu-warn', '90'])
            self.assertEqual(caught.exception.code, 3)

    def test_status_json_collection_error_is_valid_json(self):
        from docktui.docker_client import DockerError
        with patch('docktui.cli.DockerClient') as factory:
            factory.return_value.list_containers.side_effect = DockerError('permission denied')
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as caught:
                main(['status', '--json'])
            self.assertEqual(caught.exception.code, 1)
            self.assertEqual(json.loads(output.getvalue())['error'], 'permission denied')
