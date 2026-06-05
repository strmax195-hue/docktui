import sys
import os
import json
import argparse
from pathlib import Path
from . import __version__
from .tui import ContainerDashboard

def load_config() -> dict:
    """Loads configuration options from ~/.config/docktui/config.json or ~/.docktui.json."""
    config_path = Path.home() / ".config" / "docktui" / "config.json"
    if not config_path.is_file():
        config_path = Path.home() / ".docktui.json"
    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def main():
    config = load_config()

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
        default=config.get("refresh_interval", 2.0),
        help="Dashboard and follow-log refresh interval in seconds. Default: 2.0",
    )
    parser.add_argument(
        "--docker-timeout",
        type=float,
        default=config.get("docker_timeout", 10.0),
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
        choices=["dark", "light", "high-contrast"],
        default=config.get("theme", "dark"),
        help="Color theme preset (dark, light, high-contrast). Default: dark",
    )
    args = parser.parse_args()

    dashboard = ContainerDashboard(
        refresh_interval=max(0.5, args.refresh_interval),
        docker_timeout=max(1.0, args.docker_timeout),
        docker_host=args.host,
        theme=args.theme,
        exec_presets=config.get("exec_presets"),
        log_tail_limit=config.get("log_tail_limit"),
    )
    try:
        dashboard.run()
    except KeyboardInterrupt:
        # Reset terminal coloring on exit
        print("\033[0m\nExited DockTUI. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()
