import sys
import argparse
from .tui import ContainerDashboard

def main():
    parser = argparse.ArgumentParser(
        description="DockTUI: A lightweight, zero-dependency TUI dashboard for managing Docker containers."
    )
    # Allow arguments if needed in the future
    parser.parse_args()

    dashboard = ContainerDashboard()
    try:
        dashboard.run()
    except KeyboardInterrupt:
        # Reset terminal coloring on exit
        print("\033[0m\nExited DockTUI. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()
