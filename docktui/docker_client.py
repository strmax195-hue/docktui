import subprocess
import shutil
import shlex
import json
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

    def _parse_labels(self, labels: str) -> Dict[str, str]:
        """Parses Docker's comma-separated key=value labels into a dictionary."""
        result = {}
        for item in labels.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                result[key.strip()] = value.strip()
        return result

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
            "--format", "{{.ID}}|{{.Names}}|{{.State}}|{{.Status}}|{{.Image}}|{{.Labels}}|{{.Ports}}|{{.CreatedAt}}"
        ]

        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            containers = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 5:
                    labels = self._parse_labels(parts[5] if len(parts) > 5 else "")
                    containers.append({
                        "id": parts[0],
                        "name": parts[1],
                        "state": parts[2],
                        "status": parts[3],
                        "image": parts[4],
                        "labels": labels,
                        "compose_project": labels.get("com.docker.compose.project", ""),
                        "compose_service": labels.get("com.docker.compose.service", ""),
                        "ports": parts[6] if len(parts) > 6 else "",
                        "created": parts[7] if len(parts) > 7 else "",
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

    def pause_container(self, container_id: str) -> bool:
        """Pauses a running container."""
        if not self.is_docker_installed():
            return False
        try:
            res = self._run([self.docker_bin, "pause", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def unpause_container(self, container_id: str) -> bool:
        """Unpauses a paused container."""
        if not self.is_docker_installed():
            return False
        try:
            res = self._run([self.docker_bin, "unpause", container_id], capture_output=True, check=True)
            return res.returncode == 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def top_container(self, container_id: str) -> str:
        """Shows processes running inside a container."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "top", container_id],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace"
            )
            return res.stdout or res.stderr or "No process data."
        except subprocess.TimeoutExpired:
            return f"Timed out reading container processes after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error reading container processes: {str(e)}"

    def get_current_context(self) -> str:
        """Returns the active Docker context name."""
        if not self.is_docker_installed():
            return ""
        try:
            res = self._run(
                [self.docker_bin, "context", "show"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return (res.stdout or "").strip()
        except (subprocess.TimeoutExpired, Exception):
            return ""

    def list_contexts(self) -> List[Dict[str, str]]:
        """Retrieves available Docker contexts."""
        if not self.is_docker_installed():
            return []
        cmd = [
            self.docker_bin, "context", "ls",
            "--format", "{{.Name}}|{{.Current}}|{{.Description}}|{{.DockerEndpoint}}"
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            contexts = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    contexts.append({
                        "name": parts[0],
                        "current": parts[1],
                        "description": parts[2],
                        "endpoint": parts[3],
                    })
            return contexts
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

    def use_context(self, context_name: str) -> Tuple[bool, str]:
        """Switches Docker context."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "context", "use", context_name],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            if res.returncode == 0:
                return True, f"Switched Docker context to {context_name}."
            return False, res.stderr or f"Failed to switch Docker context to {context_name}."
        except subprocess.TimeoutExpired:
            return False, f"Timed out switching context after {self.timeout:g} seconds."
        except Exception as e:
            return False, f"Error switching Docker context: {str(e)}"

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

    def prune_system(self, include_volumes: bool = False) -> str:
        """Runs Docker system prune to clean unused resources."""
        if not self.is_docker_installed():
            return "Docker not installed."
        cmd = [self.docker_bin, "system", "prune", "-f"]
        if include_volumes:
            cmd.append("--volumes")
        try:
            res = self._run(
                cmd,
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

    def prune_images(self) -> str:
        """Runs 'docker image prune -f' to clean dangling images."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "image", "prune", "-f"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "Image prune completed with no output."
        except subprocess.TimeoutExpired:
            return f"Timed out pruning images after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error pruning images: {str(e)}"

    def prune_volumes(self) -> str:
        """Runs 'docker volume prune -f' to clean unused volumes."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "volume", "prune", "-f"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            return res.stdout or res.stderr or "Volume prune completed with no output."
        except subprocess.TimeoutExpired:
            return f"Timed out pruning volumes after {self.timeout:g} seconds."
        except Exception as e:
            return f"Error pruning volumes: {str(e)}"

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

    def list_volumes(self) -> List[Dict[str, str]]:
        """Retrieves local Docker volumes."""
        if not self.is_docker_installed():
            return []
        cmd = [
            self.docker_bin, "volume", "ls",
            "--format", "{{.Name}}|{{.Driver}}|{{.Scope}}"
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            volumes = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 3:
                    volumes.append({
                        "name": parts[0],
                        "driver": parts[1],
                        "scope": parts[2],
                    })
            return volumes
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

    def remove_volume(self, volume_name: str) -> Tuple[bool, str]:
        """Removes a Docker volume."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        try:
            res = self._run(
                [self.docker_bin, "volume", "rm", volume_name],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8"
            )
            if res.returncode == 0:
                return True, f"Successfully removed volume {volume_name}."
            return False, res.stderr or f"Failed to remove volume {volume_name}."
        except subprocess.TimeoutExpired:
            return False, f"Timed out removing volume after {self.timeout:g} seconds."
        except Exception as e:
            return False, f"Error removing volume: {str(e)}"

    def list_networks(self) -> List[Dict[str, str]]:
        """Retrieves local Docker networks."""
        if not self.is_docker_installed():
            return []
        cmd = [
            self.docker_bin, "network", "ls",
            "--format", "{{.ID}}|{{.Name}}|{{.Driver}}|{{.Scope}}"
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
            networks = []
            for line in res.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|")
                if len(parts) >= 4:
                    networks.append({
                        "id": parts[0],
                        "name": parts[1],
                        "driver": parts[2],
                        "scope": parts[3],
                    })
            return networks
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

    def get_container_details(self, container_id: str) -> Dict[str, str]:
        """Returns a human-friendly summary of container inspection data."""
        raw = self.inspect_container(container_id)
        try:
            data = json.loads(raw)[0]
        except Exception:
            return {"error": raw}

        config = data.get("Config") or {}
        host_config = data.get("HostConfig") or {}
        network_settings = data.get("NetworkSettings") or {}
        state = data.get("State") or {}
        mounts = data.get("Mounts") or []
        networks = network_settings.get("Networks") or {}
        ports = network_settings.get("Ports") or {}

        port_lines = []
        for container_port, bindings in ports.items():
            if not bindings:
                port_lines.append(container_port)
                continue
            for binding in bindings:
                host_ip = binding.get("HostIp", "")
                host_port = binding.get("HostPort", "")
                port_lines.append(f"{host_ip}:{host_port} -> {container_port}".strip(":"))

        mount_lines = []
        for mount in mounts:
            source = mount.get("Source") or mount.get("Name") or ""
            target = mount.get("Destination") or ""
            mode = mount.get("Mode") or mount.get("RW") or ""
            mount_lines.append(f"{source} -> {target} ({mode})")

        env = config.get("Env") or []
        labels = config.get("Labels") or {}
        return {
            "id": data.get("Id", "")[:12],
            "name": (data.get("Name") or "").lstrip("/"),
            "image": config.get("Image", ""),
            "status": state.get("Status", ""),
            "running": str(state.get("Running", "")),
            "created": data.get("Created", ""),
            "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name", ""),
            "ports": "\n".join(port_lines) or "(none)",
            "mounts": "\n".join(mount_lines) or "(none)",
            "networks": ", ".join(networks.keys()) or "(none)",
            "env": "\n".join(env[:20]) or "(none)",
            "labels": "\n".join(f"{k}={v}" for k, v in labels.items()) or "(none)",
        }

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
