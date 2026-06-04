import subprocess
import shutil
import shlex
from typing import Dict, List, Optional, Tuple

class DockerClient:
    """Interacts with the local Docker daemon via the Docker CLI command line."""

    def __init__(self, timeout: float = 10.0):
        self.docker_bin = shutil.which("docker")
        self.timeout = timeout

    def _run(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Runs Docker CLI commands with a default timeout."""
        kwargs.setdefault("timeout", self.timeout)
        return subprocess.run(cmd, **kwargs)

    def is_docker_installed(self) -> bool:
        """Checks if Docker CLI is installed and available in system PATH."""
        return self.docker_bin is not None

    def is_daemon_running(self) -> bool:
        """Checks if the Docker daemon is running by querying 'docker info'."""
        if not self.is_docker_installed():
            return False
        try:
            res = self._run(
                [self.docker_bin, "info"],
                capture_output=True,
                text=True,
                check=False
            )
            return res.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
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
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
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
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
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
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
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
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return {}

    def start_container(self, container_id: str) -> bool:
        """Starts a stopped container."""
        if not self.is_docker_installed():
            return False
        try:
            res = self._run([self.docker_bin, "start", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def stop_container(self, container_id: str) -> bool:
        """Stops a running container."""
        if not self.is_docker_installed():
            return False
        try:
            res = self._run([self.docker_bin, "stop", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def restart_container(self, container_id: str) -> bool:
        """Restarts a container."""
        if not self.is_docker_installed():
            return False
        try:
            res = self._run([self.docker_bin, "restart", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def get_logs(self, container_id: str, tail: int = 40) -> str:
        """Fetches the last N log lines of a container."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "logs", f"--tail={tail}", container_id],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace"
            )
            return res.stdout or res.stderr or "(no logs available)"
        except subprocess.TimeoutExpired:
            return f"Timed out reading logs after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error reading logs: {str(e)}"

    def inspect_container(self, container_id: str) -> str:
        """Fetches detailed inspection JSON for a container."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "inspect", container_id],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "No inspect data."
        except subprocess.TimeoutExpired:
            return f"Timed out inspecting container after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error inspecting container: {str(e)}"

    def get_disk_usage(self) -> str:
        """Runs 'docker system df' to get disk space statistics."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "system", "df"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "No disk usage data."
        except subprocess.TimeoutExpired:
            return f"Timed out reading disk usage after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error reading disk usage: {str(e)}"

    def prune_system(self) -> str:
        """Runs 'docker system prune -f' to clean unused resources."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "system", "prune", "-f"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "Prune completed with no output."
        except subprocess.TimeoutExpired:
            return f"Timed out running prune after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error running prune command: {str(e)}"

    def list_images(self) -> List[Dict[str, str]]:
        """
        Retrieves a list of all local images via 'docker images'.
        Returns a list of dicts with keys: id, repository, tag, size.
        """
        if not self.is_docker_installed():
            return []

        cmd = [
            self.docker_bin, "images",
            "--format", "{{.ID}}|{{.Repository}}|{{.Tag}}|{{.Size}}"
        ]

        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            images = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    images.append({
                        "id": parts[0],
                        "repository": parts[1],
                        "tag": parts[2],
                        "size": parts[3]
                    })
            return images
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

    def remove_image(self, image_id: str) -> Tuple[bool, str]:
        """Removes a local Docker image."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "rmi", image_id],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            if res.returncode == 0:
                return True, f"Successfully removed image {image_id}."
            else:
                return False, res.stderr or f"Failed to remove image {image_id}."
        except subprocess.TimeoutExpired:
            return False, f"Timed out removing image after {self.timeout:g} seconds."
        except Exception as e:
            return False, f"Error removing image: {str(e)}"

    def rename_container(self, container_id: str, new_name: str) -> Tuple[bool, str]:
        """Renames an existing container."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "rename", container_id, new_name],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            if res.returncode == 0:
                return True, f"Successfully renamed container to {new_name}."
            else:
                return False, res.stderr or f"Failed to rename container to {new_name}."
        except subprocess.TimeoutExpired:
            return False, f"Timed out renaming container after {self.timeout:g} seconds."
        except Exception as e:
            return False, f"Error renaming container: {str(e)}"

    def exec_command(self, container_id: str, command: str) -> str:
        """Executes a single command inside a running container."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            cmd_parts = shlex.split(command)
        except ValueError as e:
            return f"Invalid command: {str(e)}"
        if not cmd_parts:
            return "Empty command."
        
        cmd = [self.docker_bin, "exec", container_id] + cmd_parts
        try:
            res = self._run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "(Command executed with no output)"
        except subprocess.TimeoutExpired:
            return f"Timed out executing command after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error executing command: {str(e)}"
