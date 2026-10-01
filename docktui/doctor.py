"""``docktui doctor``: diagnose the local environment before opening the dashboard.

Each check returns a `CheckResult`; the command prints them and exits non-zero
when any check fails, so it can also be used in provisioning scripts.
"""

import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import __version__
from .config import Config
from .docker_client import DockerClient

OK = "ok"
WARN = "warn"
FAIL = "fail"

_LABELS = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}
_COLORS = {OK: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m"}


@dataclass
class CheckResult:
    status: str
    title: str
    detail: str = ""
    hint: str = ""


def _docker_output(client: DockerClient, args: list[str]) -> Optional[str]:
    """Run ``docker <args>`` and return stripped stdout, or ``None`` on failure."""
    if not client.is_docker_installed():
        return None
    ok, text = client._run_capture([str(client.docker_bin), *args], action=" ".join(args))
    return text.strip() if ok else None


def check_python() -> CheckResult:
    version = platform.python_version()
    return CheckResult(OK, "Python", f"{version} ({platform.system()} {platform.machine()})")


def check_docker_cli(client: DockerClient) -> CheckResult:
    if not client.is_docker_installed():
        return CheckResult(
            FAIL,
            "Docker CLI",
            "`docker` not found in PATH",
            "Install Docker Engine / Docker Desktop: https://docs.docker.com/get-docker/",
        )
    version = _docker_output(client, ["version", "--format", "{{.Client.Version}}"])
    if not version:
        # `docker version` exits non-zero when the daemon is down; `--version` never does.
        version = _docker_output(client, ["--version"])
    return CheckResult(OK, "Docker CLI", f"{version or 'unknown version'} at {client.docker_bin}")


def check_daemon(client: DockerClient) -> CheckResult:
    if not client.is_docker_installed():
        return CheckResult(FAIL, "Docker daemon", "skipped: Docker CLI missing")
    ok, text = client._run_capture(
        [str(client.docker_bin), "version", "--format", "{{.Server.Version}}"],
        action="contacting the Docker daemon",
    )
    if ok and text.strip():
        return CheckResult(OK, "Docker daemon", f"reachable, server {text.strip()}")
    message = (text or "").strip().splitlines()
    detail = message[-1] if message else "not reachable"
    hint = "Start Docker Desktop or run `sudo systemctl start docker`."
    if "permission denied" in (text or "").lower():
        hint = (
            "Add your user to the `docker` group: `sudo usermod -aG docker $USER`, then re-login."
        )
    return CheckResult(FAIL, "Docker daemon", detail, hint)


def check_endpoint(client: DockerClient) -> CheckResult:
    host = client.docker_host
    if host:
        if host.startswith("ssh://") and not shutil.which("ssh"):
            return CheckResult(
                FAIL, "Endpoint", f"DOCKER_HOST={host}", "`ssh` client not found in PATH."
            )
        if host.startswith("tcp://") and ":2375" in host:
            return CheckResult(
                WARN,
                "Endpoint",
                f"DOCKER_HOST={host}",
                "Port 2375 is unencrypted and unauthenticated; prefer ssh:// or TLS (2376).",
            )
        return CheckResult(OK, "Endpoint", f"DOCKER_HOST={host}")
    context = client.get_current_context() if client.is_docker_installed() else ""
    return CheckResult(OK, "Endpoint", f"context `{context or 'default'}`")


def check_socket_permissions() -> Optional[CheckResult]:
    if os.name != "posix" or os.environ.get("DOCKER_HOST"):
        return None
    sock = Path("/var/run/docker.sock")
    if not sock.exists():
        return None
    if os.access(sock, os.R_OK | os.W_OK):
        return CheckResult(OK, "Socket access", str(sock))
    return CheckResult(
        FAIL,
        "Socket access",
        f"no read/write access to {sock}",
        "Add your user to the `docker` group: `sudo usermod -aG docker $USER`, then re-login.",
    )


def check_compose(client: DockerClient) -> CheckResult:
    version = _docker_output(client, ["compose", "version", "--short"])
    if version:
        return CheckResult(OK, "Docker Compose", f"plugin {version}")
    if shutil.which("docker-compose"):
        return CheckResult(OK, "Docker Compose", "standalone docker-compose")
    return CheckResult(
        WARN,
        "Docker Compose",
        "not found",
        "Compose lifecycle actions (up/down/build) will be unavailable.",
    )


def check_config(path: Optional[Path]) -> CheckResult:
    target = path or Config.find_existing_path()
    if target is None:
        return CheckResult(
            OK, "Config file", "none (defaults); create one with `docktui config init`"
        )
    if not target.is_file():
        return CheckResult(FAIL, "Config file", f"{target} does not exist")
    error = Config.validate_file(target)
    if error:
        return CheckResult(FAIL, "Config file", f"{target}: {error}", "Fix the JSON syntax and reported setting values.")
    return CheckResult(OK, "Config file", str(target))


def check_terminal() -> CheckResult:
    if not sys.stdout.isatty():
        return CheckResult(
            WARN, "Terminal", "stdout is not a TTY", "The dashboard needs a terminal."
        )
    size = shutil.get_terminal_size((80, 24))
    if size.columns < 80 or size.lines < 24:
        return CheckResult(
            WARN,
            "Terminal",
            f"{size.columns}x{size.lines}",
            "Resize to at least 80x24 for the best layout.",
        )
    color = "disabled (NO_COLOR)" if os.environ.get("NO_COLOR") else "enabled"
    return CheckResult(OK, "Terminal", f"{size.columns}x{size.lines}, colors {color}")


def run_checks(client: DockerClient, config_path: Optional[Path] = None) -> list[CheckResult]:
    checks: list[Callable[[], Optional[CheckResult]]] = [
        check_python,
        lambda: check_docker_cli(client),
        lambda: check_daemon(client),
        lambda: check_endpoint(client),
        check_socket_permissions,
        lambda: check_compose(client),
        lambda: check_config(config_path),
        check_terminal,
    ]
    results = []
    for check in checks:
        result = check()
        if result is not None:
            results.append(result)
    return results


def format_results(results: list[CheckResult], color: bool = False) -> str:
    lines = [f"DockTUI {__version__} doctor", ""]
    width = max(len(r.title) for r in results) if results else 0
    for r in results:
        label = _LABELS[r.status]
        if color:
            label = f"{_COLORS[r.status]}{label}\033[0m"
        lines.append(f"{label} {r.title.ljust(width)}  {r.detail}")
        if r.hint and r.status != OK:
            lines.append(f"       {' ' * width}  -> {r.hint}")
    failed = sum(1 for r in results if r.status == FAIL)
    warned = sum(1 for r in results if r.status == WARN)
    lines.append("")
    if failed:
        lines.append(f"{failed} problem(s) found, {warned} warning(s).")
    elif warned:
        lines.append(f"Ready, with {warned} warning(s). Run `docktui` to open the dashboard.")
    else:
        lines.append("All checks passed. Run `docktui` to open the dashboard.")
    return "\n".join(lines)
