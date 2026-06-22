import json
import os
import shlex
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple


def _format_timeout_message(seconds: float, action: str) -> str:
    return f"Timed out {action} after {seconds:g} seconds."


class DockerClient:
    """Interacts with the Docker daemon via the Docker CLI command line."""

    def __init__(self, timeout: float = 10.0, host: Optional[str] = None):
        self.docker_bin = shutil.which("docker")
        self.timeout = timeout
        # Per-instance DOCKER_HOST override. Used as a property so callers
        # can assign to `client.host` to clear or change it.
        self._host_override: Optional[str] = host
        # Backwards compatibility: a `host` value also pins the process env
        # so the legacy `--host` CLI flag keeps working for subprocesses
        # spawned by external tools.
        if host:
            os.environ["DOCKER_HOST"] = host

    # ------------------------------------------------------------------ host

    @property
    def host(self) -> Optional[str]:
        return self._host_override

    @host.setter
    def host(self, value: Optional[str]) -> None:
        self.set_host(value)

    @property
    def docker_host(self) -> Optional[str]:
        """Return the active DOCKER_HOST (per-instance override takes precedence)."""
        if self._host_override:
            return self._host_override
        return os.environ.get("DOCKER_HOST")

    def set_host(self, host: Optional[str]) -> None:
        """Update the per-instance DOCKER_HOST without touching the process env.

        Pass ``None`` to clear the override (the process env, if any, is used).
        """
        self._host_override = host

    def _env(self) -> Optional[Dict[str, str]]:
        if not self._host_override:
            return None
        return {**os.environ, "DOCKER_HOST": self._host_override}

    def parse_docker_host(self) -> Optional[Dict[str, str]]:
        """Parse DOCKER_HOST into protocol/user/host/port/display parts."""
        host_str = self.docker_host
        if not host_str:
            return None

        parsed: Dict[str, str] = {
            "original": host_str,
            "protocol": "",
            "host": "",
            "user": "",
            "port": "",
            "display": "",
        }

        temp = host_str.strip()
        if "://" in temp:
            proto, rest = temp.split("://", 1)
            parsed["protocol"] = proto.lower()
        else:
            if temp.startswith("/") or temp.startswith("\\\\"):
                parsed["protocol"] = "unix" if temp.startswith("/") else "npipe"
                rest = temp
            else:
                parsed["protocol"] = "tcp"
                rest = temp

        if parsed["protocol"] in ("unix", "npipe"):
            parsed["host"] = rest
            parsed["display"] = f"{parsed['protocol']}://{rest}"
        elif parsed["protocol"] in ("ssh", "tcp"):
            user = ""
            host_port = rest
            if parsed["protocol"] == "ssh" and "@" in rest:
                user, host_port = rest.rsplit("@", 1)
                parsed["user"] = user

            if host_port.startswith("["):
                if "]" in host_port:
                    parts = host_port.split("]", 1)
                    parsed["host"] = parts[0] + "]"
                    if parts[1].startswith(":"):
                        parsed["port"] = parts[1][1:]
                else:
                    parsed["host"] = host_port
            else:
                if ":" in host_port:
                    parts = host_port.rsplit(":", 1)
                    parsed["host"] = parts[0]
                    parsed["port"] = parts[1]
                else:
                    parsed["host"] = host_port

            display_parts: List[str] = []
            if parsed["user"]:
                display_parts.append(f"{parsed['user']}@")
            display_parts.append(parsed["host"])
            if parsed["port"]:
                display_parts.append(f":{parsed['port']}")
            parsed["display"] = f"{parsed['protocol']}://{''.join(display_parts)}"

        return parsed

    # ------------------------------------------------------------------ subprocess

    def _run(self, cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """Run a Docker CLI command with default timeout and per-instance env."""
        kwargs.setdefault("timeout", self.timeout)
        env = kwargs.pop("env", None) or self._env()
        if env is not None:
            kwargs["env"] = env
        return subprocess.run(cmd, **kwargs)

    def _capture(
        self,
        cmd: List[str],
        action: str = "running command",
    ) -> str:
        """Run a `docker` command and return its text output, normalised on errors."""
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            res = self._run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return _format_timeout_message(self.timeout, action)
        except Exception as e:
            return f"Error {action}: {e}"
        stdout = (res.stdout or "") if res.stdout is not None else ""
        stderr = (res.stderr or "") if res.stderr is not None else ""
        if stdout:
            return stdout
        if stderr:
            return stderr
        return ""

    def _run_capture(
        self,
        cmd: List[str],
        action: str = "running command",
    ) -> Tuple[bool, str]:
        """Run a `docker` command returning ``(success, text)``.

        The text is stdout when available, otherwise stderr. ``success`` is
        ``True`` only when the subprocess returned 0 AND produced some text,
        matching the legacy behaviour where an empty output was treated as
        a successful no-op.
        """
        if not self.is_docker_installed():
            return False, "Docker not installed."
        try:
            res = self._run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return False, _format_timeout_message(self.timeout, action)
        except Exception as e:
            return False, f"Error {action}: {e}"
        if res.returncode != 0:
            text = (res.stderr or res.stdout or "").strip()
            return False, text or f"Failed to {action}."
        stdout = (res.stdout or "") if res.stdout is not None else ""
        stderr = (res.stderr or "") if res.stderr is not None else ""
        return True, stdout or stderr or ""

    def _bool(self, cmd: List[str], action: str) -> Tuple[bool, str]:
        """Run a `docker` command returning `(True, "")` on success, `(False, msg)` otherwise."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        try:
            res = self._run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired:
            return False, _format_timeout_message(self.timeout, action)
        except Exception as e:
            return False, f"Error {action}: {e}"
        if res.returncode == 0:
            return True, ""
        stderr = res.stderr if isinstance(res.stderr, str) else ""
        stdout = res.stdout if isinstance(res.stdout, str) else ""
        text = (stderr + stdout).strip()
        return False, text or f"Failed to {action}."

    def _parse_labels(self, labels: str) -> Dict[str, str]:
        """Parse Docker's comma-separated key=value labels into a dict."""
        result: Dict[str, str] = {}
        for item in labels.split(","):
            if "=" in item:
                key, value = item.split("=", 1)
                result[key.strip()] = value.strip()
        return result

    # ------------------------------------------------------------------ basic checks

    def is_docker_installed(self) -> bool:
        return self.docker_bin is not None

    def is_daemon_running(self) -> bool:
        if not self.is_docker_installed():
            return False
        try:
            res = self._run(
                [str(self.docker_bin), "info"], capture_output=True, text=True, check=False
            )
            return res.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            return False

    # ------------------------------------------------------------------ containers

    def list_containers(self) -> List[Dict[str, str]]:
        if not self.is_docker_installed():
            return []

        cmd = [
            self.docker_bin,
            "ps",
            "-a",
            "--format",
            "{{.ID}}|{{.Names}}|{{.State}}|{{.Status}}|{{.Image}}|{{.Labels}}|{{.Ports}}|{{.CreatedAt}}",
        ]

        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")  # type: ignore
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []

        containers: List[Dict[str, str]] = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 5:
                continue
            labels = self._parse_labels(parts[5] if len(parts) > 5 else "")
            containers.append(
                {
                    "id": parts[0],
                    "name": parts[1],
                    "state": parts[2],
                    "status": parts[3],
                    "image": parts[4],
                    "labels": labels,  # type: ignore
                    "compose_project": labels.get("com.docker.compose.project", ""),
                    "compose_service": labels.get("com.docker.compose.service", ""),
                    "ports": parts[6] if len(parts) > 6 else "",
                    "created": parts[7] if len(parts) > 7 else "",
                }
            )
        return containers

    def get_container_stats(self) -> Dict[str, Dict[str, str]]:
        if not self.is_docker_installed():
            return {}

        cmd = [
            self.docker_bin,
            "stats",
            "--no-stream",
            "--format",
            "{{.Container}}|{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}|{{.NetIO}}",
        ]

        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")  # type: ignore
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return {}

        stats: Dict[str, Dict[str, str]] = {}
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 5:
                continue
            stats[parts[0]] = {
                "cpu": parts[1],
                "memory": parts[2],
                "mem_perc": parts[3],
                "net": parts[4],
            }
        return stats

    def start_container(self, container_id: str) -> bool:
        return self._bool([str(self.docker_bin), "start", container_id], f"start {container_id}")[0]

    def stop_container(self, container_id: str) -> bool:
        return self._bool([str(self.docker_bin), "stop", container_id], f"stop {container_id}")[0]

    def restart_container(self, container_id: str) -> bool:
        return self._bool(
            [str(self.docker_bin), "restart", container_id], f"restart {container_id}"
        )[0]

    def pause_container(self, container_id: str) -> bool:
        return self._bool([str(self.docker_bin), "pause", container_id], f"pause {container_id}")[0]

    def unpause_container(self, container_id: str) -> bool:
        return self._bool(
            [str(self.docker_bin), "unpause", container_id], f"unpause {container_id}"
        )[0]

    def top_container(self, container_id: str) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture(
            [str(self.docker_bin), "top", container_id], action="reading container processes"
        )
        return out or "No process data."

    def rename_container(self, container_id: str, new_name: str) -> Tuple[bool, str]:
        success, err = self._bool(
            [str(self.docker_bin), "rename", container_id, new_name],
            f"rename container to {new_name}",
        )
        if success:
            return True, f"Successfully renamed container to {new_name}."
        return False, err or f"Failed to rename container to {new_name}."

    def update_container_resources(
        self,
        container_id: str,
        cpus: Optional[float] = None,
        memory_bytes: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Apply live CPU/memory limits via `docker update`."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        if cpus is None and memory_bytes is None:
            return False, "No resource changes specified."
        cmd = [str(self.docker_bin), "update"]
        if cpus is not None:
            cmd += [f"--cpus={cpus}"]
        if memory_bytes is not None:
            cmd += [f"--memory={memory_bytes}"]
        cmd.append(container_id)
        success, err = self._bool(cmd, f"update resources for {container_id}")
        if success:
            return True, f"Successfully updated resources for {container_id}."
        return False, err or f"Failed to update resources for {container_id}."

    def clone_container(
        self,
        source_id: str,
        new_name: str,
        image: str,
        command: Optional[List[str]] = None,
        env: Optional[List[str]] = None,
        port_bindings: Optional[List[str]] = None,
        volumes: Optional[List[str]] = None,
        detach: bool = True,
    ) -> Tuple[bool, str]:
        """Spawn a new container that mirrors `source_id`'s configuration."""
        if not self.is_docker_installed():
            return False, "Docker not installed."
        if not new_name.strip():
            return False, "Container name is required."
        cmd = [str(self.docker_bin), "run"]
        if detach:
            cmd.append("-d")
        cmd += ["--name", new_name]
        for binding in port_bindings or []:
            cmd += ["-p", binding]
        for volume in volumes or []:
            cmd += ["-v", volume]
        for entry in env or []:
            cmd += ["-e", entry]
        cmd.append(image)
        if command:
            cmd += list(command)
        success, msg = self._run_capture(cmd, action=f"cloning container to {new_name}")
        if not success:
            return False, msg
        return True, msg.strip() or f"Cloned {source_id} as {new_name}."

    # ------------------------------------------------------------------ contexts

    def get_current_context(self) -> str:
        if not self.is_docker_installed():
            return ""
        try:
            res = self._run(
                [str(self.docker_bin), "context", "show"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
            )
            return (res.stdout or "").strip()
        except (subprocess.TimeoutExpired, Exception):
            return ""

    def list_contexts(self) -> List[Dict[str, str]]:
        if not self.is_docker_installed():
            return []
        cmd = [
            self.docker_bin,
            "context",
            "ls",
            "--format",
            "{{.Name}}|{{.Current}}|{{.Description}}|{{.DockerEndpoint}}",
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")  # type: ignore
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        contexts: List[Dict[str, str]] = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            contexts.append(
                {
                    "name": parts[0],
                    "current": parts[1],
                    "description": parts[2],
                    "endpoint": parts[3],
                }
            )
        return contexts

    def use_context(self, context_name: str) -> Tuple[bool, str]:
        if not self.is_docker_installed():
            return False, "Docker not installed."
        success, msg = self._run_capture(
            [str(self.docker_bin), "context", "use", context_name],
            action=f"switching Docker context to {context_name}",
        )
        if not success:
            return False, msg
        return True, f"Switched Docker context to {context_name}."

    def create_context(self, name: str, host: str, description: str = "") -> Tuple[bool, str]:
        if not self.is_docker_installed():
            return False, "Docker not installed."
        cmd = [str(self.docker_bin), "context", "create", name, "--docker", f"host={host}"]
        if description:
            cmd += ["--description", description]
        success, msg = self._run_capture(cmd, action=f"creating context {name}")
        if not success:
            return False, msg
        return True, f"Created context {name}."

    def remove_context(self, name: str) -> Tuple[bool, str]:
        if not self.is_docker_installed():
            return False, "Docker not installed."
        success, msg = self._run_capture(
            [str(self.docker_bin), "context", "rm", name],
            action=f"removing context {name}",
        )
        if not success:
            return False, msg
        return True, f"Removed context {name}."

    def inspect_context(self, name: str) -> Dict[str, str]:
        if not self.is_docker_installed():
            return {}
        try:
            res = self._run(
                [str(self.docker_bin), "context", "inspect", name],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            data = json.loads(res.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {}
        if not isinstance(data, list) or not data:
            return {}
        entry = data[0] or {}
        endpoints = entry.get("Endpoints") or {}
        docker_endpoint = endpoints.get("docker") or {}
        return {
            "name": entry.get("Name", name),
            "description": entry.get("Description", "") or "",
            "host": docker_endpoint.get("Host", "") or "",
            "skip_tls": str(docker_endpoint.get("SkipTLSVerify", False)).lower(),
        }

    # ------------------------------------------------------------------ logs / inspect

    def get_logs(self, container_id: str, tail: int = 40) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture(
            [str(self.docker_bin), "logs", f"--tail={tail}", container_id],
            action="reading logs",
        )
        return out or "(no logs available)"

    def get_compose_project_logs(self, project_name: str, tail: int = 40) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture(
            [str(self.docker_bin), "compose", "-p", project_name, "logs", f"--tail={tail}"],
            action="reading Compose logs",
        )
        return out or "(no logs available)"

    def inspect_container(self, container_id: str) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture(
            [str(self.docker_bin), "inspect", container_id],
            action="inspecting container",
        )
        return out or "No inspect data."

    # ------------------------------------------------------------------ disk / prune

    def get_disk_usage(self) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture([str(self.docker_bin), "system", "df"], action="reading disk usage")
        return out or "No disk usage data."

    def prune_system(self, include_volumes: bool = False) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        cmd = [str(self.docker_bin), "system", "prune", "-f"]
        if include_volumes:
            cmd.append("--volumes")
        out = self._capture(cmd, action="running prune")
        return out or "Prune completed with no output."

    def prune_images(self) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture([str(self.docker_bin), "image", "prune", "-f"], action="pruning images")
        return out or "Image prune completed with no output."

    def prune_volumes(self) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        out = self._capture(
            [str(self.docker_bin), "volume", "prune", "-f"], action="pruning volumes"
        )
        return out or "Volume prune completed with no output."

    # ------------------------------------------------------------------ images

    def list_images(self) -> List[Dict[str, str]]:
        if not self.is_docker_installed():
            return []
        cmd = [
            str(self.docker_bin),
            "images",
            "--format",
            "{{.ID}}|{{.Repository}}|{{.Tag}}|{{.Size}}",
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        images: List[Dict[str, str]] = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            images.append(
                {
                    "id": parts[0],
                    "repository": parts[1],
                    "tag": parts[2],
                    "size": parts[3],
                }
            )
        return images

    def remove_image(self, image_id: str) -> Tuple[bool, str]:
        success, msg = self._run_capture(
            [str(self.docker_bin), "rmi", image_id],
            action=f"removing image {image_id}",
        )
        if success:
            return True, f"Successfully removed image {image_id}."
        return False, msg or f"Failed to remove image {image_id}."

    def search_images(self, query: str, limit: int = 25) -> List[Dict[str, str]]:
        """Search Docker Hub (or the configured registry) for `query`."""
        if not self.is_docker_installed():
            return []
        query = (query or "").strip()
        if not query:
            return []
        cmd = [
            self.docker_bin,
            "search",
            "--limit",
            str(limit),
            query,
            "--format",
            "{{.Name}}|{{.Description}}|{{.StarCount}}|{{.IsOfficial}}|{{.IsAutomated}}",
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")  # type: ignore
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        results: List[Dict[str, str]] = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            results.append(
                {
                    "name": parts[0],
                    "description": parts[1],
                    "stars": parts[2] if len(parts) > 2 else "0",
                    "official": parts[3] if len(parts) > 3 else "",
                    "automated": parts[4] if len(parts) > 4 else "",
                }
            )
        return results

    def pull_image_args(self, repository: str) -> List[str]:
        """Return the command used to pull `repository` (used by `LineStreamer`)."""
        if not self.is_docker_installed():
            return []
        return [str(self.docker_bin), "pull", repository]

    def pull_image(self, repository: str, on_progress=None) -> "subprocess.Popen":
        """Start a background `docker pull` process and return the handle.

        `on_progress` is an optional callback receiving one decoded line at a time.
        """
        cmd = self.pull_image_args(repository)
        if not cmd:
            raise RuntimeError("Docker not installed.")
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self._env(),
        )

    # ------------------------------------------------------------------ volumes

    def list_volumes(self) -> List[Dict[str, str]]:
        if not self.is_docker_installed():
            return []
        cmd = [str(self.docker_bin), "volume", "ls", "--format", "{{.Name}}|{{.Driver}}|{{.Scope}}"]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        volumes: List[Dict[str, str]] = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            volumes.append(
                {
                    "name": parts[0],
                    "driver": parts[1],
                    "scope": parts[2],
                }
            )
        return volumes

    def remove_volume(self, volume_name: str) -> Tuple[bool, str]:
        success, msg = self._run_capture(
            [str(self.docker_bin), "volume", "rm", volume_name],
            action=f"removing volume {volume_name}",
        )
        if success:
            return True, f"Successfully removed volume {volume_name}."
        return False, msg or f"Failed to remove volume {volume_name}."

    def inspect_volume(self, name: str) -> Dict[str, str]:
        if not self.is_docker_installed():
            return {}
        try:
            res = self._run(
                [str(self.docker_bin), "volume", "inspect", name],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            data = json.loads(res.stdout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {}
        if not isinstance(data, list) or not data:
            return {}
        entry = data[0] or {}
        return {
            "name": entry.get("Name", name),
            "driver": entry.get("Driver", ""),
            "mountpoint": entry.get("Mountpoint", ""),
            "scope": entry.get("Scope", ""),
        }

    def list_volume_contents(self, name: str, path: str = "/") -> List[Dict[str, str]]:
        """Best-effort directory listing of a volume via `docker run --rm`.

        We use a tiny Alpine container and `ls -la` so the output is identical
        across local and remote daemons.
        """
        if not self.is_docker_installed():
            return []
        target = path if path.startswith("/") else "/" + path
        cmd = [
            self.docker_bin,
            "run",
            "--rm",
            "-v",
            f"{name}:/data:ro",
            "alpine:latest",
            "ls",
            "-la",
            f"/data{target}",
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")  # type: ignore
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        entries: List[Dict[str, str]] = []
        for line in res.stdout.splitlines():
            line = line.rstrip()
            if not line or line.startswith("total "):
                continue
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue
            entries.append(
                {
                    "mode": parts[0],
                    "links": parts[1],
                    "owner": parts[2],
                    "group": parts[3],
                    "size": parts[4],
                    "mtime": " ".join(parts[5:8]),
                    "name": parts[8],
                }
            )
        return entries

    # ------------------------------------------------------------------ networks

    def list_networks(self) -> List[Dict[str, str]]:
        if not self.is_docker_installed():
            return []
        cmd = [
            self.docker_bin,
            "network",
            "ls",
            "--format",
            "{{.ID}}|{{.Name}}|{{.Driver}}|{{.Scope}}",
        ]
        try:
            res = self._run(cmd, capture_output=True, text=True, check=True, encoding="utf-8")  # type: ignore
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return []
        networks: List[Dict[str, str]] = []
        for line in res.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 4:
                continue
            networks.append(
                {
                    "id": parts[0],
                    "name": parts[1],
                    "driver": parts[2],
                    "scope": parts[3],
                }
            )
        return networks

    def remove_network(self, network_name: str) -> Tuple[bool, str]:
        success, msg = self._run_capture(
            [str(self.docker_bin), "network", "rm", network_name],
            action=f"removing network {network_name}",
        )
        if success:
            return True, f"Successfully removed network {network_name}."
        return False, msg or f"Failed to remove network {network_name}."

    # ------------------------------------------------------------------ details

    def get_container_details(self, container_id: str) -> Dict[str, str]:
        """Return a human-friendly summary of container inspection data."""
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

        port_lines: List[str] = []
        for container_port, bindings in ports.items():
            if not bindings:
                port_lines.append(container_port)
                continue
            for binding in bindings:
                host_ip = binding.get("HostIp", "")
                host_port = binding.get("HostPort", "")
                port_lines.append(f"{host_ip}:{host_port} -> {container_port}".strip(":"))

        mount_lines: List[str] = []
        for mount in mounts:
            source = mount.get("Source") or mount.get("Name") or ""
            target = mount.get("Destination") or ""
            mode = mount.get("Mode") or mount.get("RW") or ""
            mount_lines.append(f"{source} -> {target} ({mode})")

        env = config.get("Env") or []
        labels = config.get("Labels") or {}

        ip_lines: List[str] = []
        for net_name, net_data in networks.items():
            ip = net_data.get("IPAddress", "")
            gateway = net_data.get("Gateway", "")
            mac = net_data.get("MacAddress", "")
            if ip:
                detail = f"{net_name}: {ip}"
                if gateway:
                    detail += f" (Gateway: {gateway})"
                if mac:
                    detail += f" [MAC: {mac}]"
                ip_lines.append(detail)

        # Resource limits come from HostConfig.
        nano_cpus = host_config.get("NanoCpus") or 0
        memory_bytes = host_config.get("Memory") or 0
        cpus = round(nano_cpus / 1e9, 3) if nano_cpus else None
        memory_mb = round(memory_bytes / (1024 * 1024), 1) if memory_bytes else None

        return {
            "id": (data.get("Id") or "")[:12],
            "name": (data.get("Name") or "").lstrip("/"),
            "image": config.get("Image", ""),
            "status": state.get("Status", ""),
            "running": str(state.get("Running", "")),
            "created": data.get("Created", ""),
            "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name", ""),
            "ports": "\n".join(port_lines) or "(none)",
            "mounts": "\n".join(mount_lines) or "(none)",
            "networks": ", ".join(networks.keys()) or "(none)",
            "ip_details": "\n".join(ip_lines) or "(none)",
            "env": "\n".join(env[:20]) or "(none)",
            "labels": "\n".join(f"{k}={v}" for k, v in labels.items()) or "(none)",
            "cpus": str(cpus) if cpus is not None else "",
            "memory_mb": str(memory_mb) if memory_mb is not None else "",
        }

    # ------------------------------------------------------------------ exec / compose

    def exec_command(self, container_id: str, command: str) -> str:
        if not self.is_docker_installed():
            return "Docker not installed."
        try:
            if os.name == "nt":
                command = command.replace("\\", "\\\\")
            cmd_parts = shlex.split(command, posix=True)
        except ValueError as e:
            return f"Invalid command: {e}"
        if not cmd_parts:
            return "Empty command."

        cmd = [str(self.docker_bin), "exec", container_id] + cmd_parts
        out = self._capture(cmd, action="executing command")
        return out or "(Command executed with no output)"

    def run_compose_cmd(self, project_name: str, config_file: str, action: str) -> Tuple[bool, str]:
        if not self.is_docker_installed():
            return False, "Docker not installed."

        cmd = [str(self.docker_bin)]
        if config_file:
            files = [f.strip() for f in config_file.split(",") if f.strip()]
            for f in files:
                cmd += ["-f", f]
        else:
            cmd += ["-p", project_name]

        cmd += ["compose"]
        if action == "up":
            cmd += ["up", "-d"]
        elif action == "up-build":
            cmd += ["up", "-d", "--build"]
        elif action == "down":
            cmd += ["down"]
        elif action == "build":
            cmd += ["build"]
        elif action == "restart":
            cmd += ["restart"]
        else:
            return False, f"Unknown compose action: {action}"

        success, msg = self._run_capture(cmd, action=f"running compose {action}")
        if not success:
            return False, msg
        return True, msg.strip() or f"Compose {action} succeeded."

    # ------------------------------------------------------------------ compose snippet

    def generate_compose_snippet(self, container_id: str) -> str:
        if not self.is_docker_installed():
            return "# Docker not installed."
        raw = self.inspect_container(container_id)
        try:
            data = json.loads(raw)[0]
        except Exception as e:
            return f"# Error inspecting container: {e}"

        name = (data.get("Name") or "").lstrip("/")
        config = data.get("Config") or {}
        host_config = data.get("HostConfig") or {}
        network_settings = data.get("NetworkSettings") or {}

        service_name = name.replace("-", "_").lower() or "myservice"

        lines: List[str] = [
            "version: '3.8'",
            "services:",
            f"  {service_name}:",
            f"    container_name: {name}",
        ]

        image = config.get("Image")
        if image:
            lines.append(f"    image: {image}")

        restart = host_config.get("RestartPolicy", {}).get("Name")
        if restart and restart != "no":
            lines.append(f"    restart: {restart}")

        if host_config.get("Privileged"):
            lines.append("    privileged: true")

        entrypoint = config.get("Entrypoint")
        if entrypoint:
            if isinstance(entrypoint, list):
                lines.append(f"    entrypoint: {json.dumps(entrypoint)}")
            else:
                lines.append(f"    entrypoint: {entrypoint}")

        cmd = config.get("Cmd")
        if cmd:
            if isinstance(cmd, list):
                lines.append(f"    command: {json.dumps(cmd)}")
            else:
                lines.append(f"    command: {cmd}")

        working_dir = config.get("WorkingDir")
        if working_dir:
            lines.append(f"    working_dir: {working_dir}")

        user = config.get("User")
        if user:
            lines.append(f"    user: {user}")

        hostname = config.get("Hostname")
        if hostname:
            lines.append(f"    hostname: {hostname}")

        ports = host_config.get("PortBindings") or {}
        if ports:
            lines.append("    ports:")
            for container_port, bindings in ports.items():
                if bindings:
                    for binding in bindings:
                        host_ip = binding.get("HostIp", "")
                        host_port = binding.get("HostPort", "")
                        if host_ip and host_ip != "0.0.0.0":
                            lines.append(f'      - "{host_ip}:{host_port}:{container_port}"')
                        else:
                            lines.append(f'      - "{host_port}:{container_port}"')
                else:
                    lines.append(f'      - "{container_port}"')

        binds = host_config.get("Binds") or []
        if binds:
            lines.append("    volumes:")
            for bind in binds:
                lines.append(f"      - {bind}")

        env = config.get("Env") or []
        env_lines: List[str] = []
        for entry in env:
            if "=" in entry:
                k, v = entry.split("=", 1)
                if k in ("PATH", "HOME", "HOSTNAME", "TERM"):
                    continue
                env_lines.append(f"      - {k}={v}")
        if env_lines:
            lines.append("    environment:")
            lines.extend(env_lines)

        networks = network_settings.get("Networks") or {}
        if networks and list(networks.keys()) != ["bridge"]:
            lines.append("    networks:")
            for net_name in networks.keys():
                lines.append(f"      - {net_name}")

        extra_hosts = host_config.get("ExtraHosts")
        if extra_hosts:
            lines.append("    extra_hosts:")
            for host in extra_hosts:
                lines.append(f'      - "{host}"')

        labels = config.get("Labels") or {}
        clean_labels = {k: v for k, v in labels.items() if not k.startswith("com.docker.compose.")}
        if clean_labels:
            lines.append("    labels:")
            for k, v in clean_labels.items():
                lines.append(f'      - "{k}={v}"')

        return "\n".join(lines)
