"""Command-line entry point for DockTUI.

``docktui`` with no sub-command opens the interactive dashboard. The
sub-commands are non-interactive and script-friendly:

* ``docktui status``  – one-shot container table (or ``--json``)
* ``docktui check``   – health check with Nagios-compatible exit codes
* ``docktui doctor``  – diagnose Docker / config / terminal problems
* ``docktui config``  – show, locate, or initialise the config file
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .config import Config
from .constants import AVAILABLE_THEMES
from .docker_client import DockerClient, DockerError
from .tui import ContainerDashboard


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    """Load the raw config dict from `path` or the first existing candidate path.

    Returns an empty dict if no file is present or the file is unreadable.
    """
    target = path or Config.find_existing_path()
    if target is None:
        return {}
    return Config.read_raw(target)


def _use_color(stream: Any = None) -> bool:
    stream = stream or sys.stdout
    return bool(getattr(stream, "isatty", lambda: False)()) and not os.environ.get("NO_COLOR")


def _add_connection_args(parser: argparse.ArgumentParser, suppress: bool = False) -> None:
    """Options shared by the dashboard and every sub-command.

    Sub-parsers use ``SUPPRESS`` defaults so they don't clobber values given
    before the sub-command (``docktui -H ssh://x status``).
    """
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument(
        "--host",
        "-H",
        type=str,
        default=default,
        help="Docker daemon to connect to (e.g. ssh://user@host, tcp://10.0.0.5:2376). "
        "Overrides DOCKER_HOST.",
    )
    parser.add_argument(
        "--docker-timeout",
        type=float,
        default=default,
        metavar="SECONDS",
        help="Timeout for Docker CLI commands. Default: 10",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=default,
        metavar="PATH",
        help="Config file to use (default: $DOCKTUI_CONFIG, "
        "$XDG_CONFIG_HOME/docktui/config.json, ~/.config/docktui/config.json, ~/.docktui.json).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docktui",
        description="DockTUI: a lightweight, zero-dependency terminal dashboard for Docker.",
        epilog="Run `docktui <command> --help` for command options. "
        "Docs: https://github.com/strmax195-hue/docktui",
    )
    parser.add_argument("--version", "-V", action="version", version=f"DockTUI {__version__}")
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Dashboard and follow-log refresh interval. Default: 2",
    )
    parser.add_argument(
        "--theme",
        type=str,
        choices=AVAILABLE_THEMES + ("high-contrast",),
        default=None,
        help="Color theme preset. Default: dark",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors (same as setting NO_COLOR=1).",
    )
    _add_connection_args(parser)

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_status = sub.add_parser(
        "status",
        aliases=["ps"],
        help="Print a one-shot snapshot of containers and exit.",
        description="Print containers with state, health, CPU and memory, then exit.",
    )
    _add_connection_args(p_status, suppress=True)
    _add_filter_args(p_status)
    output = p_status.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Emit JSON for scripting.")
    output.add_argument(
        "--prometheus", action="store_true", help="Emit Prometheus textfile metrics."
    )
    p_status.add_argument(
        "--metrics-limit",
        type=_positive_int,
        default=1000,
        help="Maximum per-container metric labels (1..10000).",
    )
    p_status.add_argument(
        "--no-stats", action="store_true", help="Skip `docker stats` (faster on busy hosts)."
    )

    p_check = sub.add_parser(
        "check",
        help="Health check with Nagios-compatible exit codes (0 OK, 1 WARN, 2 CRIT, 3 UNKNOWN).",
        description="Report unhealthy, crashed, restarting or overloaded containers. "
        "Suitable for cron, CI and Nagios/Icinga/Zabbix.",
    )
    _add_connection_args(p_check, suppress=True)
    _add_filter_args(p_check)
    p_check.add_argument(
        "--cpu-warn",
        type=_nonnegative_float,
        default=None,
        metavar="PCT",
        help="Warn when a container's CPU usage is at or above PCT.",
    )
    p_check.add_argument(
        "--mem-warn",
        type=_nonnegative_float,
        default=None,
        metavar="PCT",
        help="Warn when a container's memory usage is at or above PCT.",
    )
    p_check.add_argument(
        "--require",
        "-r",
        action="append",
        default=[],
        metavar="GLOB",
        help="Critical if no running container matches GLOB (repeatable).",
    )
    p_check.add_argument("--hosts", help="Comma-separated configured endpoint names (up to 64).")
    p_check.add_argument(
        "--workers", type=_positive_int, default=4, help="Concurrent host checks, capped at 16."
    )
    p_check.add_argument(
        "--host-timeout",
        type=_positive_seconds,
        default=None,
        help="Total seconds per endpoint, including all commands.",
    )
    p_check.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    p_check.add_argument(
        "--quiet", "-q", action="store_true", help="Print nothing; only set the exit code."
    )

    p_doctor = sub.add_parser(
        "doctor", help="Diagnose Docker, permissions, config and terminal setup."
    )
    _add_connection_args(p_doctor, suppress=True)

    p_config = sub.add_parser("config", help="Show, locate or create the config file.")
    _add_connection_args(p_config, suppress=True)
    p_config.add_argument(
        "action",
        choices=("show", "path", "init"),
        nargs="?",
        default="show",
        help="show: print effective config as JSON (default); path: print the file location; "
        "init: write a config file with all defaults.",
    )
    p_config.add_argument(
        "--force", action="store_true", help="With `init`, overwrite an existing file."
    )
    return parser


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--filter",
        "-f",
        action="append",
        default=[],
        metavar="GLOB",
        help="Only include containers (or Compose projects) matching GLOB (repeatable).",
    )
    parser.add_argument(
        "--exclude",
        "-x",
        action="append",
        default=[],
        metavar="GLOB",
        help="Skip containers (or Compose projects) matching GLOB (repeatable).",
    )


def _build_config_from_args(
    args: argparse.Namespace, file_config: dict[str, Any], path: Optional[Path] = None
) -> Config:
    config = Config.from_dict(file_config)
    config._path = path
    # CLI flags override config file values.
    refresh = getattr(args, "refresh_interval", None)
    timeout = getattr(args, "docker_timeout", None)
    config.refresh_interval = max(0.5, refresh or config.refresh_interval)
    config.docker_timeout = max(1.0, timeout or config.docker_timeout)
    theme = getattr(args, "theme", None)
    if theme:
        # CLI uses the legacy "high-contrast" spelling; Config uses the underscored one.
        from .styles import _LEGACY_THEME_ALIASES

        config.theme = _LEGACY_THEME_ALIASES.get(theme, theme)
    config.validate()
    return config


# --------------------------------------------------------------------- commands


def _collect_rows(client: DockerClient, args: argparse.Namespace, with_stats: bool) -> list[dict]:
    from .report import build_rows, select_containers

    containers = select_containers(client.list_containers(), args.filter, args.exclude)
    stats = client.get_container_stats() if with_stats and containers else {}
    rows = build_rows(containers, stats)
    for row in rows:
        if row["state"] != "running":
            continue
        for option, field in (("cpu_warn", "cpu_percent"), ("mem_warn", "mem_percent")):
            if getattr(args, option, None) is not None and row[field] is None:
                raise DockerError(f"Missing {field} for {row['name']}")
    return rows


def cmd_status(args: argparse.Namespace, config: Config) -> int:
    from .report import format_table

    client = DockerClient(timeout=config.docker_timeout, host=args.host)
    try:
        if not client.is_docker_installed():
            raise DockerError("Docker CLI not found in PATH. Run `docktui doctor`.")
        if not client.is_daemon_running():
            raise DockerError("cannot reach the Docker daemon. Run `docktui doctor`.")
        rows = _collect_rows(client, args, with_stats=not args.no_stats)
    except (DockerError, subprocess.SubprocessError, OSError) as exc:
        if args.prometheus:
            from .prometheus import format_metrics

            print(
                format_metrics([], endpoint=_metrics_endpoint(args, config), success=False), end=""
            )
        elif args.json:
            print(json.dumps({"status": "UNKNOWN", "exit_code": 1, "error": str(exc)}))
        else:
            print(f"docktui: {exc}", file=sys.stderr)
        return 1
    if args.prometheus:
        from .prometheus import format_metrics

        print(
            format_metrics(
                rows, endpoint=_metrics_endpoint(args, config), limit=args.metrics_limit
            ),
            end="",
        )
        return 0
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        width = shutil.get_terminal_size((0, 0)).columns if sys.stdout.isatty() else 0
        print(format_table(rows, color=_use_color(), width=width or None))
    return 0


def cmd_check(args: argparse.Namespace, config: Config) -> int:
    from .report import EXIT_UNKNOWN, check_json, evaluate, format_check, overall_level

    if args.hosts:
        return cmd_check_hosts(args, config)
    client = DockerClient(timeout=config.docker_timeout, host=args.host)
    if not client.is_docker_installed() or not client.is_daemon_running():
        if not args.quiet:
            reason = (
                "Docker CLI not found"
                if not client.is_docker_installed()
                else "cannot reach the Docker daemon"
            )
            if args.json:
                print(json.dumps({"status": "UNKNOWN", "exit_code": EXIT_UNKNOWN, "error": reason}))
            else:
                print(f"DOCKTUI UNKNOWN - {reason}")
        return EXIT_UNKNOWN
    needs_stats = args.cpu_warn is not None or args.mem_warn is not None
    try:
        rows = _collect_rows(client, args, with_stats=needs_stats)
    except (DockerError, subprocess.SubprocessError, OSError) as exc:
        if not args.quiet:
            if args.json:
                print(
                    json.dumps({"status": "UNKNOWN", "exit_code": EXIT_UNKNOWN, "error": str(exc)})
                )
            else:
                print(f"DOCKTUI UNKNOWN - {exc}")
        return EXIT_UNKNOWN
    findings = evaluate(
        rows, cpu_warn=args.cpu_warn, mem_warn=args.mem_warn, require_running=args.require
    )
    if not args.quiet:
        print(check_json(findings, rows) if args.json else format_check(findings, rows))
    return overall_level(findings)


def cmd_doctor(args: argparse.Namespace, config: Config) -> int:
    from .doctor import FAIL, format_results, run_checks

    client = DockerClient(timeout=config.docker_timeout, host=args.host)
    results = run_checks(client, args.config)
    print(format_results(results, color=_use_color()))
    return 1 if any(r.status == FAIL for r in results) else 0


def cmd_config(args: argparse.Namespace, config: Config) -> int:
    if args.action == "path":
        print(config.path)
        return 0
    if args.action == "init":
        target = config.path
        if target.exists() and not args.force:
            print(f"docktui: {target} already exists (use --force to overwrite).", file=sys.stderr)
            return 1
        try:
            Config().save(target)
        except (OSError, ValueError) as exc:
            print(f"docktui: config save failed: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote default config to {target}")
        return 0
    print(json.dumps(config.to_dict(), indent=2, sort_keys=True))
    return 0


COMMANDS = {
    "status": cmd_status,
    "ps": cmd_status,
    "check": cmd_check,
    "doctor": cmd_doctor,
    "config": cmd_config,
}


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    for name in ("host", "docker_timeout", "config"):
        if not hasattr(args, name):
            setattr(args, name, None)
    if args.no_color:
        os.environ["NO_COLOR"] = "1"

    config_path = args.config.expanduser() if args.config else None
    if config_path is not None and not config_path.is_file() and args.command != "config":
        parser.error(f"config file not found: {config_path}")
    file_config = load_config(config_path)
    config = _build_config_from_args(args, file_config, config_path or Config.find_existing_path())

    if getattr(args, "hosts", None):
        if args.host:
            parser.error("--hosts cannot be combined with --host")
        if not any(name.strip() for name in args.hosts.split(",")):
            parser.error("--hosts requires at least one endpoint name")
        if len(args.hosts.split(",")) > 64:
            parser.error("--hosts is limited to 64 endpoint names")
    try:
        if not getattr(args, "hosts", None):
            args.host = config.resolve_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))

    handler = COMMANDS.get(args.command or "")
    if handler is not None:
        sys.exit(handler(args, config))

    # Pass through legacy kwargs (kept for backward compatibility with any
    # downstream callers constructing `ContainerDashboard` directly).
    dashboard = ContainerDashboard(
        refresh_interval=config.refresh_interval,
        docker_timeout=config.docker_timeout,
        docker_host=args.host,
        theme=config.theme,
        exec_presets=list(config.exec_presets) if config.exec_presets else None,
        log_tail_limit=config.log_tail_limit,
        config=config,
    )
    try:
        dashboard.run()
    except KeyboardInterrupt:
        # Reset terminal coloring on exit
        print("\033[0m\nExited DockTUI. Goodbye!")
        sys.exit(0)


def _metrics_endpoint(args: argparse.Namespace, config: Config) -> str:
    if args.host:
        for endpoint in config.endpoints:
            if endpoint["host"] == args.host:
                return endpoint["name"]
        return "host_" + hashlib.sha256(args.host.encode()).hexdigest()[:12]
    return os.environ.get("DOCKER_CONTEXT", "local")


def _nonnegative_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return number


def _positive_int(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 10000:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 10000")
    return number


def _positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 3600:
        raise argparse.ArgumentTypeError("must be finite and between 0 and 3600 seconds")
    return number


def cmd_check_hosts(args: argparse.Namespace, config: Config) -> int:
    from .multihost import check_hosts
    from .report import LEVEL_NAMES, aggregate_levels, check_json, evaluate

    targets = {e["name"]: e["host"] for e in config.endpoints}
    names = list(dict.fromkeys(name.strip() for name in args.hosts.split(",") if name.strip()))
    environment = dict(os.environ)

    def check(name: str, host: str, deadline: float) -> dict:
        if not host:
            raise DockerError(f"Unknown endpoint: {name}")
        client = DockerClient(timeout=config.docker_timeout, host=host)
        client._environment = dict(environment)
        client.cancel_event = threading.Event()
        client.deadline = deadline
        rows = _collect_rows(
            client, args, with_stats=args.cpu_warn is not None or args.mem_warn is not None
        )
        findings = evaluate(
            rows, cpu_warn=args.cpu_warn, mem_warn=args.mem_warn, require_running=args.require
        )
        return {**json.loads(check_json(findings, rows)), "rows": rows}

    results = check_hosts(
        [(name, targets.get(name, "")) for name in names],
        check,
        workers=args.workers,
        timeout=args.host_timeout or config.docker_timeout,
    )
    level = aggregate_levels([r["exit_code"] for r in results])
    if not args.quiet:
        if args.json:
            print(
                json.dumps(
                    {"status": LEVEL_NAMES[level], "exit_code": level, "hosts": results}, indent=2
                )
            )
        else:
            print(f"DOCKTUI {LEVEL_NAMES[level]} - {len(results)} endpoints")
            for result in results:
                print(f"[{result['status']}] {result['endpoint']}: {result.get('error', '')}")
                for finding in result.get("findings", []):
                    print(f"  [{finding['level']}] {finding['container']}: {finding['message']}")
    return level


if __name__ == "__main__":
    main()
