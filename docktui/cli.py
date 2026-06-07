"""Command-line entry point for DockTUI."""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from . import __version__
from .config import Config
from .constants import (
    AVAILABLE_THEMES,
    DEFAULT_DOCKER_TIMEOUT,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_THEME,
)
from .tui import ContainerDashboard


def _candidate_config_paths() -> List[Path]:
    return [
        Path.home() / ".config" / "docktui" / "config.json",
        Path.home() / ".docktui.json",
    ]


def load_config() -> Dict[str, Any]:
    """Load configuration from the first existing candidate path.

    Returns an empty dict if no file is present or the file is unreadable.
    """
    for path in _candidate_config_paths():
        if path.is_file():
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                return {}
    return {}


def _build_config_from_args(args: argparse.Namespace, file_config: Dict[str, Any]) -> Config:
    config = Config.from_dict(file_config)
    # CLI flags override config file values.
    config.refresh_interval = max(0.5, args.refresh_interval or config.refresh_interval)
    config.docker_timeout = max(1.0, args.docker_timeout or config.docker_timeout)
    if args.theme:
        # CLI uses the legacy "high-contrast" spelling; Config uses the underscored one.
        from .styles import _LEGACY_THEME_ALIASES
        config.theme = _LEGACY_THEME_ALIASES.get(args.theme, args.theme)
    config.validate()
    return config


def main() -> None:
    file_config = load_config()
    parser = argparse.ArgumentParser(
        description="DockTUI: A lightweight, zero-dependency TUI dashboard for managing Docker containers."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"DockTUI {__version__}",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=file_config.get("refresh_interval", DEFAULT_REFRESH_INTERVAL),
        help="Dashboard and follow-log refresh interval in seconds. Default: 2.0",
    )
    parser.add_argument(
        "--docker-timeout",
        type=float,
        default=file_config.get("docker_timeout", DEFAULT_DOCKER_TIMEOUT),
        help="Timeout for Docker CLI commands in seconds. Default: 10.0",
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        help="Docker daemon socket/host to connect to (e.g. ssh://user@host, tcp://192.168.1.100:2375). Overrides DOCKER_HOST env var.",
    )
    parser.add_argument(
        "--theme",
        type=str,
        choices=AVAILABLE_THEMES + ("high-contrast",),
        default=file_config.get("theme", DEFAULT_THEME),
        help="Color theme preset (dark, light, high-contrast). Default: dark",
    )
    args = parser.parse_args()

    config = _build_config_from_args(args, file_config)

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


if __name__ == "__main__":
    main()
