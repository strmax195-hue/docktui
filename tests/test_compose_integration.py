"""Opt-in lifecycle tests against an isolated real Compose project."""

import os
import tempfile
import unittest
import uuid
from pathlib import Path

from docktui.docker_client import DockerClient


@unittest.skipUnless(os.environ.get("DOCKTUI_INTEGRATION") == "1", "requires real Docker")
class TestComposeIntegration(unittest.TestCase):
    def test_up_restart_build_down(self):
        client = DockerClient(timeout=30)
        project = "docktui-test-" + uuid.uuid4().hex[:12]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text('FROM busybox\nCMD ["sleep", "600"]\n')
            compose = root / "compose.yml"
            compose.write_text("services:\n  web:\n    build: .\n    command: sleep 600\n")
            try:
                for action in ("up", "restart", "build"):
                    success, message = client.run_compose_cmd(project, str(compose), action)
                    self.assertTrue(success, message)
                rows = client.list_containers()
                self.assertTrue(any(r["compose_project"] == project for r in rows))
                success, message = client.run_compose_cmd(project, str(compose), "down")
                self.assertTrue(success, message)
                self.assertFalse(
                    any(r["compose_project"] == project for r in client.list_containers())
                )
            finally:
                client.run_compose_cmd(project, str(compose), "down")
