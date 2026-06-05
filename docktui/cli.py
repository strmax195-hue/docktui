import sys
import argparse
from . import __version__
from .tui import ContainerDashboard

def main():
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
        default=2.0,
        help="Dashboard and follow-log refresh interval in seconds. Default: 2.0",
    )
    parser.add_argument(
        "--docker-timeout",
        type=float,
        default=10.0,
        help="Timeout for Docker CLI commands in seconds. Default: 10.0",
    )
    parser.add_argument(
        "--host", "-H",
        type=str,
        help="Docker daemon socket/host to connect to (e.g. ssh://user@host, tcp://192.168.1.100:2375). Overrides DOCKER_HOST env var.",
    )
    args = parser.parse_args()

    dashboard = ContainerDashboard(
        refresh_interval=max(0.5, args.refresh_interval),
        docker_timeout=max(1.0, args.docker_timeout),
        docker_host=args.host,
    )
    try:
        dashboard.run()
    except KeyboardInterrupt:
        # Reset terminal coloring on exit
        print("\033[0m\nExited DockTUI. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()
