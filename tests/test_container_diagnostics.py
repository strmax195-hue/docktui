import json
import unittest
from unittest.mock import patch

from docktui.docker_client import DockerClient


class TestContainerDiagnostics(unittest.TestCase):
    def test_last_probe_is_bounded_and_no_healthcheck_is_explicit(self):
        client = DockerClient()
        with patch.object(client, "inspect_container", return_value=json.dumps([{"State": {}}])):
            self.assertEqual(client.get_container_details("id")["health"], "(none)")
        health = {
            "Status": "unhealthy",
            "Log": [{"End": "now", "ExitCode": 1, "Output": "x" * 100000}],
        }
        with patch.object(
            client, "inspect_container", return_value=json.dumps([{"State": {"Health": health}}])
        ):
            details = client.get_container_details("id")
        self.assertEqual(details["health_exit_code"], "1")
        self.assertEqual(details["health_time"], "now")
        self.assertLessEqual(len(details["health_output"]), 4096)

    def test_events_are_bounded_and_reconnect_has_no_duplicates(self):
        from docktui.events import EventFeed

        feed = EventFeed(max_events=3)
        for i in range(10):
            row = {
                "timeNano": 100 + i,
                "Action": "die",
                "Actor": {"ID": "abc", "Attributes": {"exitCode": "3"}},
            }
            feed.append(json.dumps(row))
        self.assertEqual(len(feed.rows), 3)
        self.assertFalse(feed.append(json.dumps(row)))
        self.assertEqual(feed.since, "0.000000109")
        feed.disconnect(1)
        self.assertIn("disconnected", feed.status)
        self.assertFalse(feed.append("bad json"))
