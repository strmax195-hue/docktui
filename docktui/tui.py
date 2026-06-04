import os
import sys
import time
from typing import List, Dict, Optional
from .docker_client import DockerClient

# ANSI colors for styling
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
WHITE_ON_BLUE = "\033[37;44m"
BG_DARK_GRAY = "\033[90m"

# Cross-platform keyboard input handler
try:
    import msvcrt
    PLATFORM = "windows"
    def init_terminal():
        # Windows ANSI support enable
        os.system("")
    def get_key_nonblocking() -> Optional[str]:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b'\x00', b'\xe0'):  # Arrow keys prefix
                ch2 = msvcrt.getch()
                if ch2 == b'H': return "up"
                if ch2 == b'P': return "down"
            try:
                return ch.decode('utf-8').lower()
            except UnicodeDecodeError:
                return None
        return None
except ImportError:
    # Unix (Linux / macOS) keyboard handler
    import select
    import termios
    import tty
    PLATFORM = "unix"
    
    def init_terminal():
        pass

    def get_key_nonblocking() -> Optional[str]:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == '\x1b':  # Escape sequences (like arrow keys)
                    rlist2, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if rlist2:
                        ch2 = sys.stdin.read(2)
                        if ch2 == '[A': return "up"
                        if ch2 == '[B': return "down"
                return ch.lower()
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class ContainerDashboard:
    """The main TUI rendering and interaction loop."""

    def __init__(self):
        self.client = DockerClient()
        self.containers: List[Dict[str, str]] = []
        self.stats: Dict[str, Dict[str, str]] = {}
        self.selected_index = 0
        self.view_mode = "main"  # 'main', 'logs', or 'inspect'
        self.status_message = "Welcome to DockTUI! Use arrow keys to navigate."
        self.status_time = time.time()
        self.last_refresh = 0.0
        self.log_filter = ""
        self.inspect_lines: List[str] = []
        self.inspect_scroll_index = 0

    def set_status(self, msg: str):
        self.status_message = msg
        self.status_time = time.time()

    def prompt_user(self, prompt_text: str) -> str:
        """Prompts the user for text input in a clean way."""
        print(f"\r\033[K{YELLOW}{BOLD}{prompt_text}{RESET}", end="", flush=True)
        try:
            # Flush key buffer to prevent old keys from entering input
            if PLATFORM == "windows":
                while msvcrt.kbhit():
                    msvcrt.getch()
            return input().strip()
        except Exception:
            return ""

    def get_percentage_bar(self, percentage_str: str, width: int = 15) -> str:
        """Generates a beautiful block progress bar for resource usage."""
        try:
            val = float(percentage_str.replace('%', '').strip())
            val = max(0.0, min(100.0, val))
            filled_len = int(round(width * val / 100.0))
            bar = "█" * filled_len + "░" * (width - filled_len)
            return f"[{bar}] {percentage_str}"
        except Exception:
            # Fallback if loading or N/A
            return f"[░░░░░░░░░░░░░░░] {percentage_str}"

    def refresh_data(self):
        """Fetches fresh container info and stats from the client."""
        self.containers = self.client.list_containers()
        if self.containers:
            self.stats = self.client.get_container_stats()
            # Ensure selected index stays in bounds
            if self.selected_index >= len(self.containers):
                self.selected_index = max(0, len(self.containers) - 1)
        else:
            self.stats = {}
            self.selected_index = 0
        self.last_refresh = time.time()

    def draw_main_view(self):
        """Renders the main table dashboard view."""
        # Clear screen
        print("\033[2J\033[H", end="")

        # Title block
        print(f"{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════╗{RESET}")
        print(f"{CYAN}{BOLD}║                     DockTUI Container Dashboard              ║{RESET}")
        print(f"{CYAN}{BOLD}╚══════════════════════════════════════════════════════════════╝{RESET}")
        
        # Check if Docker is available
        if not self.client.is_docker_installed():
            print(f"\n{RED}{BOLD}Error: Docker CLI not found.{RESET}")
            print("Please make sure Docker is installed and in your system PATH.")
            print("\nPress 'q' to quit.")
            return

        if not self.client.is_daemon_running():
            print(f"\n{YELLOW}{BOLD}Warning: Cannot connect to the Docker daemon.{RESET}")
            print("Please make sure Docker Desktop or the docker service is running.")
            print("\nPress 'q' to quit, or 'r' to retry connection.")
            return

        if not self.containers:
            print(f"\n{CYAN}No Docker containers found on this system.{RESET}")
            print("Create some containers using 'docker run' to see them here.")
            print("\nPress 'q' to quit. Auto-refreshing...")
            return

        # Table headers
        print(f"{BOLD}{'ID':<12} {'NAME':<20} {'IMAGE':<18} {'STATE':<10} {'STATUS':<15}{RESET}")
        print("─" * 78)

        # Render list of containers
        for idx, c in enumerate(self.containers):
            # Highlight selected row
            style = WHITE_ON_BLUE if idx == self.selected_index else ""
            
            # Format state color
            state = c["state"]
            if state == "running":
                state_formatted = f"{GREEN}running{RESET}"
            elif state in ("exited", "dead"):
                state_formatted = f"{RED}{state}{RESET}"
            else:
                state_formatted = f"{YELLOW}{state}{RESET}"

            if idx == self.selected_index:
                # Remove formatting on selected row to keep background color consistent
                state_formatted = state
                name_str = f"» {c['name'][:18]}"
            else:
                name_str = f"  {c['name'][:18]}"

            line = f"{style}{c['id'][:10]:<12} {name_str:<20} {c['image'][:18]:<18} {state_formatted:<10} {c['status'][:15]:<15}{RESET}"
            print(line)

        print("─" * 78)

        # Render Stats section for selected container
        if self.containers:
            sel = self.containers[self.selected_index]
            c_id = sel["id"]
            print(f"\n{CYAN}{BOLD}CONTAINER RESOURCE USAGE:{RESET}")
            
            c_stats = self.stats.get(c_id) or self.stats.get(sel["name"])
            if c_stats and sel["state"] == "running":
                cpu_bar = self.get_percentage_bar(c_stats['cpu'])
                mem_bar = self.get_percentage_bar(c_stats['mem_perc'])
                print(f"  CPU:  {GREEN}{cpu_bar}{RESET}")
                print(f"  MEM:  {GREEN}{mem_bar} ({c_stats['memory']}){RESET}")
                print(f"  NET:  {GREEN}{c_stats['net']}{RESET}")
            else:
                status_text = "N/A (container stopped)" if sel["state"] != "running" else "Loading stats..."
                print(f"  Usage statistics: {YELLOW}{status_text}{RESET}")

        # Render status line at bottom
        print("\n" + "═" * 78)
        # Clear status message if old
        if time.time() - self.status_time > 4:
            self.status_message = "Use Arrow keys to select. Auto-refreshing every 2s."
        print(f"{BOLD}Status:{RESET} {self.status_message}")
        print("═" * 78)
        
        # Action instructions
        print(f"{CYAN}[S] Start/Stop | [R] Restart | [L] Logs | [I] Inspect | [G] Refresh | [Q] Quit{RESET}")

    def draw_logs_view(self):
        """Renders the fullscreen log viewer screen."""
        if not self.containers:
            self.view_mode = "main"
            return

        sel = self.containers[self.selected_index]
        print("\033[2J\033[H", end="")
        print(f"{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════╗{RESET}")
        filter_status = f" [FILTER: {self.log_filter}]" if self.log_filter else ""
        title_text = f"LOGS: {sel['name']}{filter_status}"
        print(f"{CYAN}{BOLD}║ {title_text:<58} ║{RESET}")
        print(f"{CYAN}{BOLD}╚══════════════════════════════════════════════════════════════╝{RESET}")
        
        raw_logs = self.client.get_logs(sel["id"], tail=150)
        log_lines = raw_logs.strip().split("\n")
        
        # Filter lines if keyword is active
        if self.log_filter:
            filtered_lines = [line for line in log_lines if self.log_filter.lower() in line.lower()]
            if not filtered_lines:
                filtered_lines = [f"{YELLOW}(No logs match filter '{self.log_filter}'){RESET}"]
            display_logs = "\n".join(filtered_lines[-30:])
        else:
            display_logs = "\n".join(log_lines[-30:])

        print(display_logs)
        print("\n" + "═" * 78)
        print(f"{CYAN}[/] Filter logs | [C] Clear filter | [G] Refresh | [Any other key] Back to dashboard{RESET}")

    def draw_inspect_view(self):
        """Renders the scrollable inspect JSON screen."""
        if not self.containers:
            self.view_mode = "main"
            return

        sel = self.containers[self.selected_index]
        print("\033[2J\033[H", end="")
        print(f"{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════╗{RESET}")
        title_text = f"INSPECT: {sel['name']} (Line {self.inspect_scroll_index + 1} of {len(self.inspect_lines)})"
        print(f"{CYAN}{BOLD}║ {title_text:<58} ║{RESET}")
        print(f"{CYAN}{BOLD}╚══════════════════════════════════════════════════════════════╝{RESET}")

        # Viewport size (e.g. 24 lines)
        viewport_height = 24
        end_idx = min(len(self.inspect_lines), self.inspect_scroll_index + viewport_height)
        
        for i in range(self.inspect_scroll_index, end_idx):
            print(self.inspect_lines[i][:78]) # Trim line width to match box width
            
        print("\n" + "═" * 78)
        print(f"{CYAN}[↑/↓] Scroll | [Esc] or [I] Return to dashboard{RESET}")

    def run(self):
        """The main dashboard control loop."""
        init_terminal()
        self.refresh_data()
        
        running = True
        while running:
            # Render corresponding view
            if self.view_mode == "main":
                self.draw_main_view()
            elif self.view_mode == "logs":
                self.draw_logs_view()
            elif self.view_mode == "inspect":
                self.draw_inspect_view()

            # Auto-refresh main dashboard every 2 seconds
            if self.view_mode == "main" and (time.time() - self.last_refresh > 2.0):
                self.refresh_data()

            # Check for keyboard input
            key = get_key_nonblocking()
            if key:
                if self.view_mode == "logs":
                    if key == "g":
                        # Refresh logs
                        pass
                    elif key == "/":
                        query = self.prompt_user("Enter search term: ")
                        self.log_filter = query
                    elif key == "c":
                        self.log_filter = ""
                        self.set_status("Cleared log filter.")
                    else:
                        self.view_mode = "main"
                elif self.view_mode == "inspect":
                    if key == "up":
                        if self.inspect_scroll_index > 0:
                            self.inspect_scroll_index -= 1
                    elif key == "down":
                        # Allow scrolling if there are more lines than the viewport
                        if self.inspect_scroll_index < len(self.inspect_lines) - 24:
                            self.inspect_scroll_index += 1
                    elif key in ("i", "\x1b"):  # 'i' or 'Esc'
                        self.view_mode = "main"
                else:
                    # Dashboard controls (main view)
                    if key == "q":
                        running = False
                    elif key == "up":
                        if self.selected_index > 0:
                            self.selected_index -= 1
                    elif key == "down":
                        if self.selected_index < len(self.containers) - 1:
                            self.selected_index += 1
                    elif key == "g":
                        self.set_status("Refreshing data...")
                        self.refresh_data()
                    elif key == "l":
                        if self.containers:
                            self.log_filter = ""  # Reset log filter on enter
                            self.view_mode = "logs"
                    elif key == "i":
                        if self.containers:
                            sel = self.containers[self.selected_index]
                            self.set_status(f"Inspecting container {sel['name']}...")
                            self.draw_main_view()
                            inspect_data = self.client.inspect_container(sel["id"])
                            self.inspect_lines = inspect_data.split("\n")
                            self.inspect_scroll_index = 0
                            self.view_mode = "inspect"
                    elif key == "r":
                        # Attempt to reconnect daemon or restart container
                        if not self.client.is_daemon_running():
                            self.set_status("Reconnecting to Docker daemon...")
                            self.refresh_data()
                        elif self.containers:
                            sel = self.containers[self.selected_index]
                            self.set_status(f"Restarting container: {sel['name']}...")
                            self.draw_main_view()
                            if self.client.restart_container(sel["id"]):
                                self.set_status(f"Successfully restarted container {sel['name']}.")
                            else:
                                self.set_status(f"Failed to restart container {sel['name']}.")
                            self.refresh_data()
                    elif key == "s":
                        if self.containers:
                            sel = self.containers[self.selected_index]
                            if sel["state"] == "running":
                                self.set_status(f"Stopping container: {sel['name']}...")
                                self.draw_main_view()
                                if self.client.stop_container(sel["id"]):
                                    self.set_status(f"Stopped container {sel['name']}.")
                                else:
                                    self.set_status(f"Failed to stop container {sel['name']}.")
                            else:
                                self.set_status(f"Starting container: {sel['name']}...")
                                self.draw_main_view()
                                if self.client.start_container(sel["id"]):
                                    self.set_status(f"Started container {sel['name']}.")
                                else:
                                    self.set_status(f"Failed to start container {sel['name']}.")
                            self.refresh_data()

            # Small sleep to prevent high CPU usage
            time.sleep(0.08)
        
        # Clean shutdown and reset colors
        print(RESET)
