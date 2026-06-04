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
        self.images: List[Dict[str, str]] = []
        self.selected_index = 0
        self.selected_image_index = 0
        self.current_tab = "containers"  # "containers" or "images"
        self.view_mode = "main"  # 'main', 'logs', 'inspect', or 'system'
        self.status_message = "Welcome to DockTUI! Use Tab or 1/2 keys to switch tabs."
        self.status_time = time.time()
        self.last_refresh = 0.0
        self.log_filter = ""
        self.inspect_lines: List[str] = []
        self.inspect_scroll_index = 0
        self.log_tail_limit = 40
        self.system_info_text = ""

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
        """Fetches fresh docker data based on active tab."""
        if self.current_tab == "containers":
            self.containers = self.client.list_containers()
            if self.containers:
                self.stats = self.client.get_container_stats()
                if self.selected_index >= len(self.containers):
                    self.selected_index = max(0, len(self.containers) - 1)
            else:
                self.stats = {}
                self.selected_index = 0
        elif self.current_tab == "images":
            self.images = self.client.list_images()
            if self.images:
                if self.selected_image_index >= len(self.images):
                    self.selected_image_index = max(0, len(self.images) - 1)
            else:
                self.selected_image_index = 0
        self.last_refresh = time.time()

    def draw_main_view(self):
        """Renders the main table dashboard view."""
        # Query screen size dynamically
        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
        except Exception:
            width = 80

        # Clear screen
        print("\033[2J\033[H", end="")

        # Title block
        title_text = "DockTUI Container Dashboard"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"
        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")
        
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

        # Render Tab Headers
        if self.current_tab == "containers":
            print(f" {WHITE_ON_BLUE} 📦 Containers (1) {RESET}   [💾 Images (2)]")
        else:
            print(f" [📦 Containers (1)]   {WHITE_ON_BLUE} 💾 Images (2) {RESET}")
        print("─" * (width - 1))

        def truncate(text: str, length: int) -> str:
            if len(text) > length:
                return text[:length-3] + "..."
            return text.ljust(length)

        # Render corresponding Tab Grid
        if self.current_tab == "containers":
            if not self.containers:
                print(f"\n{CYAN}No Docker containers found on this system.{RESET}")
                print("Create some containers using 'docker run' to see them here.")
            else:
                # Calculate column widths dynamically based on terminal width
                rem = width - 26
                name_w = max(15, int(rem * 0.30))
                image_w = max(15, int(rem * 0.30))
                status_w = max(15, rem - name_w - image_w)

                # Table headers
                header_line = f"{BOLD}{'ID':<12} {truncate('NAME', name_w)} {truncate('IMAGE', image_w)} {'STATE':<10} {truncate('STATUS', status_w)}{RESET}"
                print(header_line)
                print("─" * (width - 1))

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
                        state_formatted = state
                        name_str = f"» {c['name']}"
                    else:
                        name_str = f"  {c['name']}"

                    line = f"{style}{c['id'][:10]:<12} {truncate(name_str, name_w)} {truncate(c['image'], image_w)} {state_formatted:<10} {truncate(c['status'], status_w)}{RESET}"
                    print(line)

                print("─" * (width - 1))

                # Render Stats section for selected container
                sel = self.containers[self.selected_index]
                c_id = sel["id"]
                print(f"\n{CYAN}{BOLD}CONTAINER RESOURCE USAGE:{RESET}")
                
                c_stats = self.stats.get(c_id) or self.stats.get(sel["name"])
                if c_stats and sel["state"] == "running":
                    cpu_bar = self.get_percentage_bar(c_stats['cpu'], width=int(width*0.2))
                    mem_bar = self.get_percentage_bar(c_stats['mem_perc'], width=int(width*0.2))
                    print(f"  CPU:  {GREEN}{cpu_bar}{RESET}")
                    print(f"  MEM:  {GREEN}{mem_bar} ({c_stats['memory']}){RESET}")
                    print(f"  NET:  {GREEN}{c_stats['net']}{RESET}")
                else:
                    status_text = "N/A (container stopped)" if sel["state"] != "running" else "Loading stats..."
                    print(f"  Usage statistics: {YELLOW}{status_text}{RESET}")

        elif self.current_tab == "images":
            if not self.images:
                print(f"\n{CYAN}No local Docker images found on this system.{RESET}")
                print("Run 'docker pull' to fetch images.")
            else:
                # Calculate column widths dynamically based on terminal width
                rem = width - 26
                repo_w = max(20, int(rem * 0.45))
                tag_w = max(12, int(rem * 0.25))
                size_w = max(10, rem - repo_w - tag_w)

                # Table headers
                header_line = f"{BOLD}{'IMAGE ID':<12} {truncate('REPOSITORY', repo_w)} {truncate('TAG', tag_w)} {truncate('SIZE', size_w)}{RESET}"
                print(header_line)
                print("─" * (width - 1))

                # Render list of images
                for idx, img in enumerate(self.images):
                    style = WHITE_ON_BLUE if idx == self.selected_image_index else ""
                    
                    if idx == self.selected_image_index:
                        repo_str = f"» {img['repository']}"
                    else:
                        repo_str = f"  {img['repository']}"

                    line = f"{style}{img['id'][:10]:<12} {truncate(repo_str, repo_w)} {truncate(img['tag'], tag_w)} {truncate(img['size'], size_w)}{RESET}"
                    print(line)
                print("─" * (width - 1))

        # Render status line at bottom
        print("\n" + "═" * (width - 1))
        # Clear status message if old
        if time.time() - self.status_time > 4:
            self.status_message = "Use Tab to switch tabs. Up/Down to navigate."
        print(f"{BOLD}Status:{RESET} {self.status_message}")
        print("═" * (width - 1))
        
        # Action instructions depending on the active tab
        if self.current_tab == "containers":
            print(f"{CYAN}[S] Start/Stop | [R] Restart | [L] Logs | [I] Inspect | [P] Disk/Prune | [Tab] Tab | [G] Refresh | [Q] Quit{RESET}")
        else:
            print(f"{CYAN}[D] Delete Image | [P] Disk/Prune | [Tab] Switch Tab | [G] Refresh | [Q] Quit{RESET}")

    def draw_logs_view(self):
        """Renders the fullscreen log viewer screen."""
        if not self.containers:
            self.view_mode = "main"
            return

        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
            height = max(24, terminal_size.lines)
        except Exception:
            width = 80
            height = 24

        sel = self.containers[self.selected_index]
        print("\033[2J\033[H", end="")
        
        filter_status = f" [FILTER: {self.log_filter}]" if self.log_filter else ""
        limit_status = f" [LIMIT: {self.log_tail_limit} lines]"
        title_text = f"LOGS: {sel['name']}{filter_status}{limit_status}"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"
        
        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")
        
        # Pull enough logs to satisfy our limit + filtering
        raw_logs = self.client.get_logs(sel["id"], tail=self.log_tail_limit + 100)
        log_lines = raw_logs.strip().split("\n")
        
        # Filter lines if keyword is active
        if self.log_filter:
            filtered_lines = [line for line in log_lines if self.log_filter.lower() in line.lower()]
            if not filtered_lines:
                filtered_lines = [f"{YELLOW}(No logs match filter '{self.log_filter}'){RESET}"]
            # Show up to viewport height - 6 lines
            viewport_lines = filtered_lines[-(height - 6):]
        else:
            viewport_lines = log_lines[-(height - 6):]

        display_logs = "\n".join(line[:width-1] for line in viewport_lines)
        print(display_logs)
        
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[/] Filter | [C] Clear Filter | [+/-] Limit logs | [G] Refresh | [Esc/Other] Back{RESET}")

    def draw_inspect_view(self):
        """Renders the scrollable inspect JSON screen."""
        if not self.containers:
            self.view_mode = "main"
            return

        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
            height = max(24, terminal_size.lines)
        except Exception:
            width = 80
            height = 24

        sel = self.containers[self.selected_index]
        print("\033[2J\033[H", end="")
        
        title_text = f"INSPECT: {sel['name']} (Line {self.inspect_scroll_index + 1} of {len(self.inspect_lines)})"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"
        
        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")

        # Viewport size (lines available for content)
        viewport_height = height - 6
        end_idx = min(len(self.inspect_lines), self.inspect_scroll_index + viewport_height)
        
        for i in range(self.inspect_scroll_index, end_idx):
            print(self.inspect_lines[i][:width-1]) # Trim line width to match viewport width
            
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[↑/↓] Scroll | [Esc] or [I] Return to dashboard{RESET}")

    def draw_system_view(self):
        """Renders the Docker system disk usage and prune view."""
        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
        except Exception:
            width = 80

        print("\033[2J\033[H", end="")
        
        title_text = "DOCKER SYSTEM DISK USAGE & CLEANUP"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"
        
        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")

        if not self.system_info_text:
            self.system_info_text = self.client.get_disk_usage()

        print(self.system_info_text)
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[X] Run Prune (clean unused containers/images) | [Esc/P] Return to dashboard{RESET}")

    def run(self):
        """The main dashboard control loop."""
        init_terminal()
        self.refresh_data()
        
        running = True
        while running:
            # Query terminal height
            try:
                viewport_h = max(24, os.get_terminal_size().lines) - 6
            except Exception:
                viewport_h = 18

            # Render corresponding view
            if self.view_mode == "main":
                self.draw_main_view()
            elif self.view_mode == "logs":
                self.draw_logs_view()
            elif self.view_mode == "inspect":
                self.draw_inspect_view()
            elif self.view_mode == "system":
                self.draw_system_view()

            # Auto-refresh main dashboard every 2 seconds
            if self.view_mode == "main" and (time.time() - self.last_refresh > 2.0):
                self.refresh_data()

            # Check for keyboard input
            key = get_key_nonblocking()
            if key:
                if self.view_mode == "logs":
                    if key == "g":
                        # Refresh logs is handled by loop redrawing
                        pass
                    elif key == "/":
                        query = self.prompt_user("Enter search term: ")
                        self.log_filter = query
                    elif key == "c":
                        self.log_filter = ""
                        self.set_status("Cleared log filter.")
                    elif key in ("+", "="):
                        self.log_tail_limit = min(500, self.log_tail_limit + 10)
                        self.set_status(f"Increased log limit to {self.log_tail_limit} lines.")
                    elif key == "-":
                        self.log_tail_limit = max(10, self.log_tail_limit - 10)
                        self.set_status(f"Decreased log limit to {self.log_tail_limit} lines.")
                    elif key in ("q", "l", "\x1b"):
                        self.view_mode = "main"
                elif self.view_mode == "inspect":
                    if key == "up":
                        if self.inspect_scroll_index > 0:
                            self.inspect_scroll_index -= 1
                    elif key == "down":
                        # Allow scrolling if there are more lines than the viewport
                        if self.inspect_scroll_index < len(self.inspect_lines) - viewport_h:
                            self.inspect_scroll_index += 1
                    elif key in ("i", "\x1b"):  # 'i' or 'Esc'
                        self.view_mode = "main"
                elif self.view_mode == "system":
                    if key == "x":
                        self.set_status("Running docker system prune -f...")
                        self.draw_system_view()
                        prune_out = self.client.prune_system()
                        # Output results
                        print("\n" + "─" * 40)
                        print(prune_out)
                        print("─" * 40)
                        self.prompt_user("Prune complete. Press ENTER to continue.")
                        self.system_info_text = ""  # Force refresh df
                        self.refresh_data()
                    elif key in ("p", "\x1b"):
                        self.view_mode = "main"
                else:
                    # Dashboard controls (main view)
                    if key == "q":
                        running = False
                    elif key in ("\t", "1", "2"):
                        if key == "\t":
                            self.current_tab = "images" if self.current_tab == "containers" else "containers"
                        elif key == "1":
                            self.current_tab = "containers"
                        elif key == "2":
                            self.current_tab = "images"
                        self.set_status(f"Switched tab to {self.current_tab}.")
                        self.refresh_data()
                    elif key == "up":
                        if self.current_tab == "containers":
                            if self.selected_index > 0:
                                self.selected_index -= 1
                        else:
                            if self.selected_image_index > 0:
                                self.selected_image_index -= 1
                    elif key == "down":
                        if self.current_tab == "containers":
                            if self.selected_index < len(self.containers) - 1:
                                self.selected_index += 1
                        else:
                            if self.selected_image_index < len(self.images) - 1:
                                self.selected_image_index += 1
                    elif key == "g":
                        self.set_status("Refreshing data...")
                        self.refresh_data()
                    elif key == "p":
                        self.system_info_text = ""  # Reset system stats on enter
                        self.view_mode = "system"
                    elif key == "l" and self.current_tab == "containers":
                        if self.containers:
                            self.log_filter = ""  # Reset log filter on enter
                            self.view_mode = "logs"
                    elif key == "i" and self.current_tab == "containers":
                        if self.containers:
                            sel = self.containers[self.selected_index]
                            self.set_status(f"Inspecting container {sel['name']}...")
                            self.draw_main_view()
                            inspect_data = self.client.inspect_container(sel["id"])
                            self.inspect_lines = inspect_data.split("\n")
                            self.inspect_scroll_index = 0
                            self.view_mode = "inspect"
                    elif key == "r" and self.current_tab == "containers":
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
                    elif key == "s" and self.current_tab == "containers":
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
                    elif key == "d" and self.current_tab == "images":
                        if self.images:
                            sel_img = self.images[self.selected_image_index]
                            confirm = self.prompt_user(f"Delete image {sel_img['repository']}:{sel_img['tag']}? (y/n): ")
                            if confirm.lower() in ("y", "yes"):
                                self.set_status(f"Deleting image {sel_img['id'][:10]}...")
                                self.draw_main_view()
                                success, msg = self.client.remove_image(sel_img["id"])
                                if success:
                                    self.set_status(f"Successfully deleted image.")
                                else:
                                    # Output clean error dump
                                    print("\n" + "─" * 40)
                                    print(f"{RED}Error: {msg}{RESET}")
                                    print("─" * 40)
                                    self.prompt_user("Press ENTER to continue.")
                                self.refresh_data()
                            else:
                                self.set_status("Deletion canceled.")

            # Small sleep to prevent high CPU usage
            time.sleep(0.08)
        
        # Clean shutdown and reset colors
        print(RESET)
