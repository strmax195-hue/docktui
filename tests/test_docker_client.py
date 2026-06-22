import json
import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from docktui.docker_client import DockerClient


class TestDockerClient(unittest.TestCase):
    def setUp(self):
        self.client = DockerClient()

    @patch("shutil.which")
    def test_is_docker_installed(self, mock_which):
        mock_which.return_value = "/usr/bin/docker"
        client = DockerClient()
        self.assertTrue(client.is_docker_installed())

        mock_which.return_value = None
        client_none = DockerClient()
        self.assertFalse(client_none.is_docker_installed())

    @patch("subprocess.run")
    def test_is_daemon_running(self, mock_run):
        # Setup docker_bin mock
        self.client.docker_bin = "docker"

        # Test success
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(self.client.is_daemon_running())

        # Test failure
        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(self.client.is_daemon_running())

        self.assertEqual(mock_run.call_args.kwargs["timeout"], self.client.timeout)

    @patch("subprocess.run")
    def test_list_containers(self, mock_run):
        self.client.docker_bin = "docker"

        # Mock output of 'docker ps -a --format ...'
        mock_stdout = (
            "c123|web-app|running|Up 2 hours|nginx:alpine|"
            "com.docker.compose.project=myapp,com.docker.compose.service=web|8080->80|2026-01-01\n"
            "d456|db-dev|exited|Exited (0) 5m ago|postgres:15||5432->5432|2026-01-01\n"
        )
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

        containers = self.client.list_containers()
        self.assertEqual(len(containers), 2)

        self.assertEqual(containers[0]["id"], "c123")
        self.assertEqual(containers[0]["name"], "web-app")
        self.assertEqual(containers[0]["state"], "running")
        self.assertEqual(containers[0]["status"], "Up 2 hours")
        self.assertEqual(containers[0]["image"], "nginx:alpine")
        self.assertEqual(containers[0]["compose_project"], "myapp")
        self.assertEqual(containers[0]["compose_service"], "web")
        self.assertEqual(containers[0]["ports"], "8080->80")

        self.assertEqual(containers[1]["id"], "d456")
        self.assertEqual(containers[1]["name"], "db-dev")
        self.assertEqual(containers[1]["state"], "exited")

    @patch("subprocess.run")
    def test_get_container_stats(self, mock_run):
        self.client.docker_bin = "docker"

        # Mock output of 'docker stats --no-stream ...' (now 5 columns with MemPerc)
        mock_stdout = "c123|1.25%|25.4MiB / 7.84GiB|0.32%|1.2kB / 0B\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

        stats = self.client.get_container_stats()
        self.assertIn("c123", stats)
        self.assertEqual(stats["c123"]["cpu"], "1.25%")
        self.assertEqual(stats["c123"]["memory"], "25.4MiB / 7.84GiB")
        self.assertEqual(stats["c123"]["mem_perc"], "0.32%")
        self.assertEqual(stats["c123"]["net"], "1.2kB / 0B")

    @patch("subprocess.run")
    def test_inspect_container(self, mock_run):
        self.client.docker_bin = "docker"

        mock_stdout = '[{"Id": "c123", "Name": "/web-app"}]'
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

        inspect_data = self.client.inspect_container("c123")
        self.assertEqual(inspect_data, mock_stdout)

    @patch("subprocess.run")
    def test_get_disk_usage(self, mock_run):
        self.client.docker_bin = "docker"
        mock_stdout = "TYPE            TOTAL           ACTIVE          SIZE            RECLAIMABLE\nImages          10              2               1.5GB           1.2GB (80%)"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

        disk_usage = self.client.get_disk_usage()
        self.assertEqual(disk_usage, mock_stdout)

    @patch("subprocess.run")
    def test_prune_system(self, mock_run):
        self.client.docker_bin = "docker"
        mock_stdout = "Total reclaimed space: 500MB"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

        prune_res = self.client.prune_system()
        self.assertEqual(prune_res, mock_stdout)

        self.client.prune_system(include_volumes=True)
        self.assertIn("--volumes", mock_run.call_args.args[0])

    @patch("subprocess.run")
    def test_pause_and_unpause_container(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0)

        self.assertTrue(self.client.pause_container("c123"))
        self.assertIn("pause", mock_run.call_args.args[0])
        self.assertTrue(self.client.unpause_container("c123"))
        self.assertIn("unpause", mock_run.call_args.args[0])

    @patch("subprocess.run")
    def test_top_container(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(
            returncode=0, stdout="PID USER TIME COMMAND\n1 root 0:00 app\n"
        )

        output = self.client.top_container("c123")

        self.assertIn("COMMAND", output)

    @patch("subprocess.run")
    def test_list_contexts_and_current_context(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="default|*|Current DOCKER_HOST based configuration|unix:///var/run/docker.sock\nremote|||ssh://host\n",
        )

        contexts = self.client.list_contexts()

        self.assertEqual(contexts[0]["name"], "default")
        self.assertEqual(contexts[0]["current"], "*")

        mock_run.return_value = MagicMock(returncode=0, stdout="default\n")
        self.assertEqual(self.client.get_current_context(), "default")

    @patch("subprocess.run")
    def test_use_context(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="default\n")

        success, msg = self.client.use_context("default")

        self.assertTrue(success)
        self.assertIn("default", msg)

    @patch("subprocess.run")
    def test_list_images(self, mock_run):
        self.client.docker_bin = "docker"
        mock_stdout = "sha256:123|nginx|latest|142MB\nsha256:456|postgres|15|379MB\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)

        images = self.client.list_images()
        self.assertEqual(len(images), 2)
        self.assertEqual(images[0]["id"], "sha256:123")
        self.assertEqual(images[0]["repository"], "nginx")
        self.assertEqual(images[0]["tag"], "latest")
        self.assertEqual(images[0]["size"], "142MB")

    @patch("subprocess.run")
    def test_list_volumes(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="app_data|local|local\n")

        volumes = self.client.list_volumes()

        self.assertEqual(volumes[0]["name"], "app_data")
        self.assertEqual(volumes[0]["driver"], "local")

    @patch("subprocess.run")
    def test_list_networks(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="abc123|bridge|bridge|local\n")

        networks = self.client.list_networks()

        self.assertEqual(networks[0]["name"], "bridge")
        self.assertEqual(networks[0]["driver"], "bridge")

    @patch("subprocess.run")
    def test_remove_image(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        success, msg = self.client.remove_image("sha256:123")
        self.assertTrue(success)
        self.assertIn("Successfully removed image", msg)

    @patch("subprocess.run")
    def test_rename_container(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        success, msg = self.client.rename_container("c123", "new-web-app")
        self.assertTrue(success)
        self.assertIn("Successfully renamed container", msg)

        # Test failure case
        mock_run.return_value = MagicMock(returncode=1, stderr="Error: name already in use")
        success, msg = self.client.rename_container("c123", "new-web-app")
        self.assertFalse(success)
        self.assertIn("Error: name already in use", msg)

    @patch("subprocess.run")
    def test_exec_command(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="bin\nboot\ndev\netc\n")

        output = self.client.exec_command("c123", "ls /")
        self.assertIn("bin", output)
        self.assertIn("boot", output)

    @patch("subprocess.run")
    def test_exec_command_preserves_quoted_arguments(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="hello world\n")

        output = self.client.exec_command("c123", 'sh -c "echo hello world"')

        self.assertIn("hello world", output)
        self.assertEqual(
            mock_run.call_args.args[0], ["docker", "exec", "c123", "sh", "-c", "echo hello world"]
        )

    def test_exec_command_rejects_invalid_quoting(self):
        self.client.docker_bin = "docker"

        output = self.client.exec_command("c123", 'sh -c "echo')

        self.assertIn("Invalid command", output)

    @patch("subprocess.run")
    def test_get_container_details(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="""[{
                "Id": "c1234567890abcdef",
                "Name": "/web",
                "Created": "2026-01-01T00:00:00Z",
                "Config": {
                    "Image": "nginx:alpine",
                    "Env": ["APP_ENV=dev"],
                    "Labels": {"com.docker.compose.project": "myapp"}
                },
                "State": {"Status": "running", "Running": true},
                "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
                "NetworkSettings": {
                    "Ports": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
                    "Networks": {
                        "myapp_default": {
                            "IPAddress": "172.18.0.2",
                            "Gateway": "172.18.0.1",
                            "MacAddress": "02:42:ac:12:00:02"
                        }
                    }
                },
                "Mounts": [{"Source": "/host", "Destination": "/app", "Mode": "rw"}]
            }]""",
        )

        details = self.client.get_container_details("c123")

        self.assertEqual(details["name"], "web")
        self.assertEqual(details["image"], "nginx:alpine")
        self.assertIn("8080", details["ports"])
        self.assertIn("myapp_default", details["networks"])
        self.assertIn("172.18.0.2", details["ip_details"])
        self.assertIn("Gateway: 172.18.0.1", details["ip_details"])
        self.assertIn("MAC: 02:42:ac:12:00:02", details["ip_details"])

    @patch("subprocess.run")
    def test_get_logs_reports_timeout(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["docker", "logs"], timeout=10)

        output = self.client.get_logs("c123")

        self.assertIn("Timed out reading logs", output)

    @patch("subprocess.run")
    def test_get_compose_project_logs_success(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="compose-logs-output\n")

        output = self.client.get_compose_project_logs("myproject", tail=50)

        self.assertEqual(output, "compose-logs-output\n")
        self.assertEqual(
            mock_run.call_args.args[0],
            ["docker", "compose", "-p", "myproject", "logs", "--tail=50"],
        )

    @patch("subprocess.run")
    def test_get_compose_project_logs_timeout(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["docker", "compose"], timeout=10)

        output = self.client.get_compose_project_logs("myproject")

        self.assertIn("Timed out reading Compose logs", output)

    def test_docker_host_properties_and_parsing(self):
        # Backup original DOCKER_HOST
        orig_env = os.environ.get("DOCKER_HOST")
        try:
            # Test constructor sets env
            client = DockerClient(host="ssh://testuser@192.168.1.50:2222")
            self.assertEqual(client.docker_host, "ssh://testuser@192.168.1.50:2222")
            self.assertEqual(os.environ.get("DOCKER_HOST"), "ssh://testuser@192.168.1.50:2222")

            # Test parsing SSH with port
            parsed = client.parse_docker_host()
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["protocol"], "ssh")
            self.assertEqual(parsed["user"], "testuser")
            self.assertEqual(parsed["host"], "192.168.1.50")
            self.assertEqual(parsed["port"], "2222")
            self.assertEqual(parsed["display"], "ssh://testuser@192.168.1.50:2222")

            # Test parsing SSH without port
            client.host = None
            os.environ["DOCKER_HOST"] = "ssh://anotheruser@remotehost"
            parsed = client.parse_docker_host()
            self.assertEqual(parsed["protocol"], "ssh")
            self.assertEqual(parsed["user"], "anotheruser")
            self.assertEqual(parsed["host"], "remotehost")
            self.assertEqual(parsed["port"], "")
            self.assertEqual(parsed["display"], "ssh://anotheruser@remotehost")

            # Test parsing TCP
            os.environ["DOCKER_HOST"] = "tcp://1.2.3.4:2376"
            parsed = client.parse_docker_host()
            self.assertEqual(parsed["protocol"], "tcp")
            self.assertEqual(parsed["user"], "")
            self.assertEqual(parsed["host"], "1.2.3.4")
            self.assertEqual(parsed["port"], "2376")
            self.assertEqual(parsed["display"], "tcp://1.2.3.4:2376")

            # Test parsing unix socket
            os.environ["DOCKER_HOST"] = "unix:///var/run/docker.sock"
            parsed = client.parse_docker_host()
            self.assertEqual(parsed["protocol"], "unix")
            self.assertEqual(parsed["host"], "/var/run/docker.sock")
            self.assertEqual(parsed["display"], "unix:///var/run/docker.sock")

            # Test parsing default TCP without protocol scheme
            os.environ["DOCKER_HOST"] = "localhost:2375"
            parsed = client.parse_docker_host()
            self.assertEqual(parsed["protocol"], "tcp")
            self.assertEqual(parsed["host"], "localhost")
            self.assertEqual(parsed["port"], "2375")
            self.assertEqual(parsed["display"], "tcp://localhost:2375")

            # Test parsing IPv6
            os.environ["DOCKER_HOST"] = "tcp://[::1]:2376"
            parsed = client.parse_docker_host()
            self.assertEqual(parsed["protocol"], "tcp")
            self.assertEqual(parsed["host"], "[::1]")
            self.assertEqual(parsed["port"], "2376")
            self.assertEqual(parsed["display"], "tcp://[::1]:2376")

            # Test parsing None/Empty
            os.environ.pop("DOCKER_HOST", None)
            self.assertIsNone(client.parse_docker_host())

        finally:
            # Restore environment
            if orig_env is not None:
                os.environ["DOCKER_HOST"] = orig_env
            else:
                os.environ.pop("DOCKER_HOST", None)

    def test_set_host_does_not_mutate_env(self):
        orig = os.environ.get("DOCKER_HOST")
        try:
            os.environ.pop("DOCKER_HOST", None)
            client = DockerClient()
            client.set_host("ssh://new@host")
            self.assertEqual(client.docker_host, "ssh://new@host")
            # The process env is NOT mutated by set_host.
            self.assertIsNone(os.environ.get("DOCKER_HOST"))
            # And the legacy constructor with a host DOES mutate env.
            DockerClient(host="ssh://legacy@host")
            self.assertEqual(os.environ.get("DOCKER_HOST"), "ssh://legacy@host")
        finally:
            if orig is not None:
                os.environ["DOCKER_HOST"] = orig
            else:
                os.environ.pop("DOCKER_HOST", None)

    @patch("subprocess.run")
    def test_search_images(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(
            returncode=0, stdout="nginx|Web server|15000|[OK]|\nalpine|Small Linux|8000||\n"
        )
        results = self.client.search_images("nginx")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["name"], "nginx")
        self.assertEqual(results[0]["stars"], "15000")
        self.assertEqual(results[0]["official"], "[OK]")

    @patch("subprocess.run")
    def test_search_images_empty_query(self, mock_run):
        self.client.docker_bin = "docker"
        results = self.client.search_images("  ")
        self.assertEqual(results, [])
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_update_container_resources(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        success, msg = self.client.update_container_resources(
            "c123", cpus=1.5, memory_bytes=512 * 1024 * 1024
        )
        self.assertTrue(success)
        cmd = mock_run.call_args.args[0]
        self.assertIn("--cpus=1.5", cmd)
        self.assertIn("--memory=536870912", cmd)
        self.assertIn("c123", cmd)

    @patch("subprocess.run")
    def test_update_container_resources_no_changes(self, mock_run):
        self.client.docker_bin = "docker"
        success, msg = self.client.update_container_resources("c123")
        self.assertFalse(success)
        self.assertIn("No resource changes", msg)
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_clone_container(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")
        success, msg = self.client.clone_container(
            source_id="src", new_name="newcopy", image="nginx:latest", port_bindings=["8080:80"]
        )
        self.assertTrue(success)
        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[0:4], ["docker", "run", "-d", "--name"])
        self.assertIn("newcopy", cmd)
        self.assertIn("nginx:latest", cmd)
        self.assertIn("8080:80", cmd)

    def test_clone_container_rejects_empty_name(self):
        self.client.docker_bin = "docker"
        success, msg = self.client.clone_container("src", "  ", "nginx")
        self.assertFalse(success)
        self.assertIn("name is required", msg)

    def test_clone_container_requires_docker(self):
        self.client.docker_bin = None
        success, msg = self.client.clone_container("src", "x", "nginx")
        self.assertFalse(success)
        self.assertIn("not installed", msg)

    def test_pull_image_args(self):
        self.client.docker_bin = "docker"
        self.assertEqual(self.client.pull_image_args("alpine"), ["docker", "pull", "alpine"])

    def test_pull_image_args_no_docker(self):
        self.client.docker_bin = None
        self.assertEqual(self.client.pull_image_args("alpine"), [])

    @patch("subprocess.run")
    def test_volume_inspect(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "Name": "myvol",
                        "Driver": "local",
                        "Mountpoint": "/var/lib/docker/volumes/myvol/_data",
                        "Scope": "local",
                    }
                ]
            ),
        )
        info = self.client.inspect_volume("myvol")
        self.assertEqual(info["name"], "myvol")
        self.assertEqual(info["driver"], "local")
        self.assertIn("/var/lib/docker/volumes/myvol", info["mountpoint"])

    @patch("subprocess.run")
    def test_volume_contents(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=(
                "total 12\n"
                "drwxr-xr-x 3 root root 4096 Jan  1 00:00 .\n"
                "drwxr-xr-x 1 root root 4096 Jan  1 00:00 ..\n"
                "-rw-r--r-- 1 root root  100 Jan  1 00:00 hello.txt\n"
                "drwxr-xr-x 2 root root 4096 Jan  1 00:00 sub\n"
            ),
        )
        entries = self.client.list_volume_contents("myvol", path="/")
        names = [e["name"] for e in entries]
        self.assertIn("hello.txt", names)
        self.assertIn("sub", names)
        # Subdirectory entry should be marked as a directory.
        sub = next(e for e in entries if e["name"] == "sub")
        self.assertTrue(sub["mode"].startswith("d"))

    @patch("subprocess.run")
    def test_remove_network(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        success, msg = self.client.remove_network("my-net")
        self.assertTrue(success)
        self.assertIn("Successfully removed network my-net", msg)

        # Test failure case
        mock_run.return_value = MagicMock(returncode=1, stderr="Error: network in use")
        success, msg = self.client.remove_network("my-net")
        self.assertFalse(success)
        self.assertIn("Error: network in use", msg)

    @patch("subprocess.run")
    def test_run_compose_cmd(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="Started compose")

        success, msg = self.client.run_compose_cmd("myproject", "docker-compose.yml", "up")
        self.assertTrue(success)
        self.assertIn("Started compose", msg)
        mock_run.assert_called_with(
            ["docker", "-f", "docker-compose.yml", "compose", "up", "-d"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
        )

        success, msg = self.client.run_compose_cmd("myproject", "", "down")
        self.assertTrue(success)
        mock_run.assert_called_with(
            ["docker", "-p", "myproject", "compose", "down"],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
        )

    @patch("docktui.docker_client.DockerClient.inspect_container")
    def test_generate_compose_snippet(self, mock_inspect):
        self.client.docker_bin = "docker"
        inspect_data = [
            {
                "Name": "/test-container",
                "Config": {
                    "Image": "nginx:alpine",
                    "Env": ["PATH=/usr/local/sbin", "MY_VAR=hello"],
                    "RestartPolicy": {"Name": "unless-stopped"},
                    "Labels": {"my.label": "value", "com.docker.compose.project": "ignored"},
                },
                "HostConfig": {
                    "RestartPolicy": {"Name": "unless-stopped"},
                    "PortBindings": {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]},
                    "Binds": ["/host/path:/container/path:ro"],
                },
                "NetworkSettings": {"Networks": {"my-network": {}}},
            }
        ]
        mock_inspect.return_value = json.dumps(inspect_data)

        snippet = self.client.generate_compose_snippet("container-id")

        self.assertIn("version: '3.8'", snippet)
        self.assertIn("services:", snippet)
        self.assertIn("test_container:", snippet)
        self.assertIn("image: nginx:alpine", snippet)
        self.assertIn("container_name: test-container", snippet)
        self.assertIn("restart: unless-stopped", snippet)
        self.assertIn("ports:", snippet)
        self.assertIn('- "8080:80/tcp"', snippet)
        self.assertIn("volumes:", snippet)
        self.assertIn("- /host/path:/container/path:ro", snippet)
        self.assertIn("environment:", snippet)
        self.assertIn("- MY_VAR=hello", snippet)
        self.assertNotIn("- PATH=", snippet)
        self.assertIn("networks:", snippet)
        self.assertIn("- my-network", snippet)
        self.assertIn("labels:", snippet)
        self.assertIn('- "my.label=value"', snippet)
        self.assertNotIn("com.docker.compose", snippet)


if __name__ == "__main__":
    unittest.main()
