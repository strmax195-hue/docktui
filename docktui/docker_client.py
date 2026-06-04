import subprocess
import shutil
from typing import Dict, List, Optional

class DockerClient:
    """Interacts with the local Docker daemon via the Docker CLI command line."""

    def __init__(self):
        self.docker_bin = shutil.which("docker")

    def is_docker_installed(self) -> bool:
        """Checks if Docker CLI is installed and available in system PATH."""
        return self.docker_bin is not None

    def is_daemon_running(self) -> bool:
        """Checks if the Docker daemon is running by querying 'docker info'."""
        if not self.is_docker_installed():
            return False
        try:
            res = subprocess.run(
                [self.docker_bin, "info"],
                capture_output=True,
                text=True,
                check=False
            )
            return res.returncode == 0
        except Exception:
            return False

    def list_containers(self) -> List[Dict[str, str]]:
        """
        Retrieves a list of all containers (active and inactive) via 'docker ps -a'.
        Returns a list of dicts with keys: id, name, state, status, image.
        """
        if not self.is_docker_installed():
            return []

        cmd = [
            self.docker_bin, "ps", "-a",
            "--format", "{{.ID}}|{{.Names}}|{{.State}}|{{.Status}}|{{.Image}}"
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            containers = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 5:
                    containers.append({
                        "id": parts[0],
                        "name": parts[1],
                        "state": parts[2],
                        "status": parts[3],
                        "image": parts[4]
                    })
            return containers
        except subprocess.CalledProcessError:
            return []

    def get_container_stats(self) -> Dict[str, Dict[str, str]]:
        """
        Retrieves CPU, Memory, and Network IO usage stats for running containers.
        Returns a dictionary mapping container name/ID to its statistics.
        """
        if not self.is_docker_installed():
            return {}

        cmd = [
            self.docker_bin, "stats", "--no-stream",
            "--format", "{{.Container}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}"
        ]

        stats_dict = {}
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 5:
                    container_id = parts[0]
                    stats_dict[container_id] = {
                        "cpu": parts[1],
                        "memory": parts[2],
                        "mem_perc": parts[3],
                        "net": parts[4]
                    }
            return stats_dict
        except subprocess.CalledProcessError:
            return {}

    def start_container(self, container_id: str) -> bool:
        """Starts a stopped container."""
        if not self.is_docker_installed():
            return False
        try:
            res = subprocess.run([self.docker_bin, "start", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except subprocess.CalledProcessError:
            return False

    def stop_container(self, container_id: str) -> bool:
        """Stops a running container."""
        if not self.is_docker_installed():
            return False
        try:
            res = subprocess.run([self.docker_bin, "stop", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except subprocess.CalledProcessError:
            return False

    def restart_container(self, container_id: str) -> bool:
        """Restarts a container."""
        if not self.is_docker_installed():
            return False
        try:
            res = subprocess.run([self.docker_bin, "restart", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except subprocess.CalledProcessError:
            return False

    def get_logs(self, container_id: str, tail: int = 40) -> str:
        """Fetches the last N log lines of a container."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = subprocess.run(
                [self.docker_bin, "logs", f"--tail={tail}", container_id],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace"
            )
            return res.stdout or res.stderr or "(no logs available)"
        except Exception as e:
            return f"Error reading logs: {str(e)}"

    def inspect_container(self, container_id: str) -> str:
        """Fetches detailed inspection JSON for a container."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = subprocess.run(
                [self.docker_bin, "inspect", container_id],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "No inspect data."
        except Exception as e:
            return f"Error inspecting container: {str(e)}"
