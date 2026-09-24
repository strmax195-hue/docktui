import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from docktui import doctor


def _client(installed=True, outputs=None):
    client = MagicMock()
    client.docker_bin = "/usr/bin/docker" if installed else None
    client.is_docker_installed.return_value = installed
    client.docker_host = None
    client.get_current_context.return_value = "default"
    outputs = outputs or {}

    def run_capture(cmd, action=""):
        key = " ".join(cmd[1:])
        return outputs.get(key, (False, "error"))

    client._run_capture.side_effect = run_capture
    return client


class TestDoctor(unittest.TestCase):
    def test_missing_docker_cli_fails(self):
        result = doctor.check_docker_cli(_client(installed=False))
        self.assertEqual(result.status, doctor.FAIL)
        self.assertIn("get-docker", result.hint)

    def test_daemon_ok(self):
        client = _client(outputs={"version --format {{.Server.Version}}": (True, "27.1.0\n")})
        result = doctor.check_daemon(client)
        self.assertEqual(result.status, doctor.OK)
        self.assertIn("27.1.0", result.detail)

    def test_daemon_permission_denied_hints_docker_group(self):
        client = _client(
            outputs={
                "version --format {{.Server.Version}}": (
                    False,
                    "permission denied while trying to connect to the Docker daemon socket",
                )
            }
        )
        result = doctor.check_daemon(client)
        self.assertEqual(result.status, doctor.FAIL)
        self.assertIn("usermod", result.hint)

    def test_insecure_tcp_endpoint_warns(self):
        client = _client()
        client.docker_host = "tcp://10.0.0.5:2375"
        self.assertEqual(doctor.check_endpoint(client).status, doctor.WARN)

    def test_invalid_config_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken", encoding="utf-8")
            result = doctor.check_config(path)
            self.assertEqual(result.status, doctor.FAIL)
            self.assertIn("invalid JSON", result.detail)
            path.write_text('{"theme": "light"}', encoding="utf-8")
            self.assertEqual(doctor.check_config(path).status, doctor.OK)

    def test_format_results_summarizes(self):
        results = [
            doctor.CheckResult(doctor.OK, "Python", "3.12"),
            doctor.CheckResult(doctor.FAIL, "Docker daemon", "down", "start it"),
        ]
        text = doctor.format_results(results)
        self.assertIn("[FAIL] Docker daemon", text)
        self.assertIn("-> start it", text)
        self.assertIn("1 problem(s) found", text)


if __name__ == "__main__":
    unittest.main()
