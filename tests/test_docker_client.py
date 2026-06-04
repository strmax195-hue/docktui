import unittest
from unittest.mock import patch, MagicMock
import subprocess
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

    @patch("subprocess.run")
    def test_list_containers(self, mock_run):
        self.client.docker_bin = "docker"
        
        # Mock output of 'docker ps -a --format ...'
        mock_stdout = "c123|web-app|running|Up 2 hours|nginx:alpine\nd456|db-dev|exited|Exited (0) 5m ago|postgres:15\n"
        mock_run.return_value = MagicMock(returncode=0, stdout=mock_stdout)
        
        containers = self.client.list_containers()
        self.assertEqual(len(containers), 2)
        
        self.assertEqual(containers[0]["id"], "c123")
        self.assertEqual(containers[0]["name"], "web-app")
        self.assertEqual(containers[0]["state"], "running")
        self.assertEqual(containers[0]["status"], "Up 2 hours")
        self.assertEqual(containers[0]["image"], "nginx:alpine")

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
    def test_remove_image(self, mock_run):
        self.client.docker_bin = "docker"
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        
        success, msg = self.client.remove_image("sha256:123")
        self.assertTrue(success)
        self.assertIn("Successfully removed image", msg)

if __name__ == "__main__":
    unittest.main()
