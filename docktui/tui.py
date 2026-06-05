import os
import sys
import time
import signal
import threading
from pathlib import Path
from typing import Callable, List, Dict, Optional
from .docker_client import DockerClient

# ANSI colors for styling
if os.environ.get("NO_COLOR"):
    RESET = ""
    BOLD = ""
    CYAN = ""
    GREEN = ""
    RED = ""
    YELLOW = ""
    WHITE_ON_BLUE = ""
    BG_DARK_GRAY = ""
else:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    WHITE_ON_BLUE = "\033[37;44m"
    BG_DARK_GRAY = "\033[90m"

RESIZE_REQUESTED = False

def handle_resize(_signum=None, _frame=None):
    global RESIZE_REQUESTED
    RESIZE_REQUESTED = True

if hasattr(signal, "SIGWINCH"):
    try:
        signal.signal(signal.SIGWINCH, handle_resize)
    except Exception:
        pass

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
            if ch in (b'\r', b'\n'):
                return "enter"
            if ch in (b'\x08', b'\x7f'):
                return "backspace"
            if ch == b'\x1b':
                return "\x1b"
            try:
                return ch.decode('utf-8')
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
                        if ch2 == '[M':
                            mouse_data = sys.stdin.read(3)
                            if len(mouse_data) == 3:
                                cb = ord(mouse_data[0])
                                if cb == 96:
                                    return "scroll_up"
                                if cb == 97:
                                    return "scroll_down"
                            return "mouse"
                    return "\x1b"
                if ch in ("\r", "\n"):
                    return "enter"
                if ch in ("\x7f", "\b"):
                    return "backspace"
                return ch.lower()
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


class ContainerDashboard:
    """The main TUI rendering and interaction loop."""

    def __init__(self, refresh_interval: float = 2.0, docker_timeout: float = 10.0, docker_host: Optional[str] = None):
        self.client = DockerClient(timeout=docker_timeout, host=docker_host)
        self.refresh_interval = refresh_interval
        self.containers: List[Dict[str, str]] = []
        self.stats: Dict[str, Dict[str, str]] = {}
        self.images: List[Dict[str, str]] = []
        self.volumes: List[Dict[str, str]] = []
        self.networks: List[Dict[str, str]] = []
        self.contexts: List[Dict[str, str]] = []
        self.compose_rows: List[Dict[str, object]] = []
        self.active_container: Optional[Dict[str, str]] = None
        self.selected_index = 0
        self.selected_image_index = 0
        self.selected_volume_index = 0
        self.selected_network_index = 0
        self.selected_compose_index = 0
        self.selected_context_index = 0
        self.tabs = ["containers", "compose", "images", "volumes", "networks", "contexts"]
        self.current_tab = "containers"
        self.view_mode = "main"  # 'main', 'logs', 'inspect', 'details', 'top', 'system', 'exec', 'input', or 'help'
        self.previous_view_mode = "main"
        self.status_message = "Welcome to DockTUI! Use Tab or 1/2 keys to switch tabs."
        self.status_time = time.time()
        self.last_refresh = 0.0
        self.log_filter = ""
        self.log_search = ""
        self.log_match_index = 0
        self.log_errors_only = False
        self.container_filter = ""
        self.state_filter = "all"
        self.sort_mode = "default"
        self.inspect_lines: List[str] = []
        self.inspect_scroll_index = 0
        self.details_lines: List[str] = []
        self.details_scroll_index = 0
        self.top_lines: List[str] = []
        self.top_scroll_index = 0
        self.log_tail_limit = 40
        self.log_lines: List[str] = []
        self.log_scroll_index = 0
        self.log_follow = False
        self.last_log_refresh = 0.0
        self.exec_output_lines: List[str] = []
        self.exec_scroll_index = 0
        self.exec_command_text = ""
        self.exec_history: List[str] = []
        self.exec_presets = ["sh", "bash", "env", "ls -la", "cat /etc/os-release"]
        self.system_info_text = ""
        self.current_context = ""
        self.active_project: Optional[str] = None
        self.daemon_running = False
        self.last_daemon_check = 0.0
        self.daemon_check_interval = 3.0
        self.data_lock = threading.Lock()
        self.refresh_requested = threading.Event()
        self.stop_refresh = threading.Event()
        self.refresh_thread: Optional[threading.Thread] = None
        self.refresh_in_progress = False
        self.input_prompt = ""
        self.input_buffer = ""
        self.input_callback: Optional[Callable[[str], None]] = None
        self.input_cancel_callback: Optional[Callable[[], None]] = None
        self.need_redraw = True

    def export_logs_to_file(self, filepath: str):
        self._export_lines_to_file(self.log_lines, "Logs", filepath)

    def export_inspect_to_file(self, filepath: str):
        self._export_lines_to_file(self.inspect_lines, "Inspect JSON", filepath)

    def export_details_to_file(self, filepath: str):
        self._export_lines_to_file(self.details_lines, "Details", filepath)

    def export_top_to_file(self, filepath: str):
        self._export_lines_to_file(self.top_lines, "Processes", filepath)

    def _export_lines_to_file(self, lines: List[str], type_name: str, filepath: str):
        if not filepath:
            self.set_status("Export canceled: empty path.")
            return
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self.set_status(f"{type_name} successfully exported to {filepath}")
        except Exception as e:
            self.set_status(f"Failed to export {type_name.lower()}: {str(e)}")

    def draw_empty_state(self, tab_name: str, width: int):
        """Draws a beautiful boxed empty state with tips for the current tab."""
        box_w = min(60, width - 4)
        padding = (width - box_w) // 2
        margin = " " * padding

        tips = {
            "containers": [
                "No containers found.",
                "To run a new container, try:",
                f"{YELLOW}docker run -d --name test-nginx -p 8080:80 nginx{RESET}",
            ],
            "compose": [
                "No Docker Compose projects found.",
                "To start a compose project, run in your project dir:",
                f"{YELLOW}docker compose up -d{RESET}",
            ],
            "images": [
                "No local images found.",
                "To pull a new image, try:",
                f"{YELLOW}docker pull alpine:latest{RESET}",
            ],
            "volumes": [
                "No volumes found.",
                "To create a volume, try:",
                f"{YELLOW}docker volume create my-data{RESET}",
            ],
            "networks": [
                "No networks found.",
                "To create a network, try:",
                f"{YELLOW}docker network create my-net{RESET}",
            ],
            "contexts": [
                "No Docker contexts found.",
                "To list contexts manually, run:",
                f"{YELLOW}docker context ls{RESET}",
            ]
        }

        content = tips.get(tab_name, ["Nothing to display."])
        
        print("\n")
        print(margin + f"{CYAN}┌" + "─" * (box_w - 2) + f"┐{RESET}")
        for line in content:
            # Strip ANSI escape codes when calculating length for padding
            visible_len = len(line.replace(YELLOW, "").replace(RESET, "").replace(CYAN, ""))
            pad_r = box_w - 4 - visible_len
            print(margin + f"{CYAN}│{RESET}  {line}" + " " * pad_r + f" {CYAN}│{RESET}")
        print(margin + f"{CYAN}└" + "─" * (box_w - 2) + f"┘{RESET}")
        print("\n")

    def set_status(self, msg: str):
        self.status_message = msg
        self.status_time = time.time()
        self.need_redraw = True

    def request_refresh(self):
        self.refresh_requested.set()

    def start_refresh_worker(self):
        if self.refresh_thread and self.refresh_thread.is_alive():
            return
        self.stop_refresh.clear()
        self.refresh_thread = threading.Thread(target=self.refresh_worker, daemon=True)
        self.refresh_thread.start()

    def stop_refresh_worker(self):
        self.stop_refresh.set()
        self.refresh_requested.set()
        if self.refresh_thread:
            self.refresh_thread.join(timeout=1.0)

    def refresh_worker(self):
        while not self.stop_refresh.is_set():
            self.refresh_requested.wait(timeout=self.refresh_interval)
            self.refresh_requested.clear()
            if self.stop_refresh.is_set():
                break
            self.refresh_data()

    def start_input(
        self,
        prompt: str,
        callback: Callable[[str], None],
        cancel_callback: Optional[Callable[[], None]] = None,
        initial: str = "",
    ):
        self.previous_view_mode = self.view_mode
        self.view_mode = "input"
        self.input_prompt = prompt
        self.input_buffer = initial
        self.input_callback = callback
        self.input_cancel_callback = cancel_callback
        self.need_redraw = True

    def cancel_input(self):
        if self.input_cancel_callback:
            self.input_cancel_callback()
        self.input_prompt = ""
        self.input_buffer = ""
        self.input_callback = None
        self.input_cancel_callback = None
        self.view_mode = self.previous_view_mode or "main"
        self.need_redraw = True

    def submit_input(self):
        value = self.input_buffer.strip()
        callback = self.input_callback
        self.input_prompt = ""
        self.input_buffer = ""
        self.input_callback = None
        self.input_cancel_callback = None
        self.view_mode = self.previous_view_mode or "main"
        self.need_redraw = True
        if callback:
            callback(value)

    def handle_input_key(self, key: str):
        if key == "enter":
            self.submit_input()
        elif key in ("\x1b", "q"):
            self.cancel_input()
        elif key == "backspace":
            self.input_buffer = self.input_buffer[:-1]
        elif len(key) == 1 and key.isprintable():
            self.input_buffer += key

    def is_daemon_running_cached(self, force: bool = False) -> bool:
        """Caches Docker daemon checks so the render loop stays responsive."""
        now = time.time()
        if force or now - self.last_daemon_check >= self.daemon_check_interval:
            self.daemon_running = self.client.is_daemon_running()
            self.last_daemon_check = now
        return self.daemon_running

    def open_help(self):
        """Opens help and remembers the current screen."""
        if self.view_mode != "help":
            self.previous_view_mode = self.view_mode
        self.view_mode = "help"
        self.need_redraw = True

    def close_help(self):
        """Returns from help to the screen that opened it."""
        self.view_mode = self.previous_view_mode or "main"
        self.need_redraw = True

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

    def truncate(self, text: str, length: int) -> str:
        if len(text) > length:
            return text[:max(0, length - 3)] + "..."
        return text.ljust(length)

    def cycle_tab(self, offset: int = 1):
        idx = self.tabs.index(self.current_tab)
        self.current_tab = self.tabs[(idx + offset) % len(self.tabs)]
        self.set_status(f"Switched tab to {self.current_tab}.")
        self.request_refresh()

    def current_selected_container(self) -> Optional[Dict[str, str]]:
        if self.current_tab == "containers" and self.containers:
            return self.containers[self.selected_index]
        if self.current_tab == "compose" and self.compose_rows:
            row = self.compose_rows[self.selected_compose_index]
            if row.get("type") == "container":
                return row.get("container")  # type: ignore[return-value]
        return None

    def sort_containers(self, containers: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if self.state_filter != "all":
            containers = [c for c in containers if c.get("state") == self.state_filter]
        if self.container_filter:
            needle = self.container_filter.lower()
            containers = [
                c for c in containers
                if needle in c.get("name", "").lower()
                or needle in c.get("image", "").lower()
                or needle in c.get("compose_project", "").lower()
                or needle in c.get("compose_service", "").lower()
            ]
        if self.sort_mode == "name":
            return sorted(containers, key=lambda c: c.get("name", ""))
        if self.sort_mode == "image":
            return sorted(containers, key=lambda c: c.get("image", ""))
        if self.sort_mode == "state":
            return sorted(containers, key=lambda c: (c.get("state") != "running", c.get("name", "")))
        return sorted(containers, key=lambda c: (c.get("state") != "running", c.get("name", "")))

    def build_compose_rows(self):
        groups: Dict[str, List[Dict[str, str]]] = {}
        loose = []
        for container in self.containers:
            project = container.get("compose_project")
            if project:
                groups.setdefault(project, []).append(container)
            else:
                loose.append(container)

        rows: List[Dict[str, object]] = []
        for project in sorted(groups):
            project_containers = sorted(groups[project], key=lambda c: (c.get("compose_service", ""), c.get("name", "")))
            rows.append({"type": "project", "project": project, "containers": project_containers})
            for container in project_containers:
                rows.append({"type": "container", "project": project, "container": container})
        if loose:
            rows.append({"type": "project", "project": "(standalone)", "containers": loose})
            for container in sorted(loose, key=lambda c: c.get("name", "")):
                rows.append({"type": "container", "project": "(standalone)", "container": container})
        self.compose_rows = rows
        if self.selected_compose_index >= len(self.compose_rows):
            self.selected_compose_index = max(0, len(self.compose_rows) - 1)

    def load_log_lines(self, container_id: Optional[str], viewport_height: int, follow: bool = False):
        """Loads logs and keeps the viewport pinned to the bottom in follow mode."""
        if container_id is None and self.active_project:
            raw_logs = self.client.get_compose_project_logs(self.active_project, tail=self.log_tail_limit)
        else:
            raw_logs = self.client.get_logs(container_id, tail=self.log_tail_limit)
        log_lines = raw_logs.split("\n")
        if self.log_errors_only:
            log_lines = [
                line for line in log_lines
                if "error" in line.lower() or "warn" in line.lower() or "exception" in line.lower()
            ]
            if not log_lines:
                log_lines = [f"{YELLOW}(No error/warning lines in current log window){RESET}"]
        if self.log_filter:
            self.log_lines = [line for line in log_lines if self.log_filter.lower() in line.lower()]
            if not self.log_lines:
                self.log_lines = [f"{YELLOW}(No logs match filter '{self.log_filter}'){RESET}"]
        else:
            self.log_lines = log_lines
        if follow or self.log_scroll_index >= max(0, len(self.log_lines) - viewport_height - 1):
            self.log_scroll_index = max(0, len(self.log_lines) - viewport_height)
        self.last_log_refresh = time.time()

    def jump_to_next_log_match(self, viewport_height: int):
        """Moves the log viewport to the next search match."""
        query = self.log_search or self.log_filter
        if not query or not self.log_lines:
            self.set_status("Set a log search first with '/'.")
            return
        matches = [idx for idx, line in enumerate(self.log_lines) if query.lower() in line.lower()]
        if not matches:
            self.set_status(f"No log matches for '{query}'.")
            return
        self.log_match_index = (self.log_match_index + 1) % len(matches)
        self.log_scroll_index = max(0, min(matches[self.log_match_index], len(self.log_lines) - viewport_height))
        self.log_follow = False
        self.set_status(f"Log match {self.log_match_index + 1}/{len(matches)}.")

    def build_details_lines(self, container_id: str) -> List[str]:
        details = self.client.get_container_details(container_id)
        if "error" in details:
            return details["error"].split("\n")
        lines = [
            f"Name: {details.get('name', '')}",
            f"ID: {details.get('id', '')}",
            f"Image: {details.get('image', '')}",
            f"Status: {details.get('status', '')}",
            f"Running: {details.get('running', '')}",
            f"Created: {details.get('created', '')}",
            f"Restart policy: {details.get('restart_policy', '') or '(none)'}",
            "",
            "Ports:",
        ]
        lines.extend(f"  {line}" for line in details.get("ports", "").split("\n"))
        lines.append("")
        lines.append("Mounts:")
        lines.extend(f"  {line}" for line in details.get("mounts", "").split("\n"))
        lines.append("")
        lines.append("Networks:")
        lines.append(f"  {details.get('networks', '')}")
        lines.append("")
        lines.append("Environment:")
        lines.extend(f"  {line}" for line in details.get("env", "").split("\n"))
        lines.append("")
        lines.append("Labels:")
        lines.extend(f"  {line}" for line in details.get("labels", "").split("\n"))
        return lines

    def prompt_exec_command(self, container_name: str) -> str:
        """Prompts for an exec preset, recent command, or custom command."""
        print(f"\r\033[K{YELLOW}{BOLD}Command inside {container_name}:{RESET}", flush=True)
        options = list(self.exec_presets)
        for command in self.exec_history[:3]:
            if command not in options:
                options.append(command)
        for idx, command in enumerate(options, start=1):
            print(f"  {idx}. {command}")
        print("  C. custom command")
        choice = self.prompt_user("Choose preset number or C: ")
        if choice.lower() == "c":
            return self.prompt_user("Custom command: ")
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(options):
                return options[index]
        return choice

    def record_exec_command(self, command: str):
        if command in self.exec_history:
            self.exec_history.remove(command)
        self.exec_history.insert(0, command)
        self.exec_history = self.exec_history[:10]

    def start_exec_input(self, container: Dict[str, str]):
        presets = ", ".join(f"{idx + 1}={cmd}" for idx, cmd in enumerate(self.exec_presets))
        prompt = f"Command inside {container['name']} ({presets}, or custom): "

        def submit(value: str):
            command = value
            if value.isdigit():
                index = int(value) - 1
                if 0 <= index < len(self.exec_presets):
                    command = self.exec_presets[index]
            if not command:
                self.set_status("Command canceled.")
                return
            self.active_container = container
            self.exec_command_text = command
            self.record_exec_command(command)
            self.set_status(f"Running command: {command}...")
            output = self.client.exec_command(container["id"], command)
            self.exec_output_lines = output.split("\n")
            self.exec_scroll_index = 0
            self.view_mode = "exec"

        self.start_input(prompt, submit)

    def save_lines_to_file(self, lines: List[str], default_name: str):
        def submit(value: str):
            filename = value or default_name
            path = Path(filename)
            if not path.is_absolute():
                path = Path.cwd() / path
            try:
                path.write_text("\n".join(lines), encoding="utf-8")
                self.set_status(f"Saved output to {path}.")
            except Exception as e:
                self.set_status(f"Save failed: {e}")

        self.start_input(f"Output file [{default_name}]: ", submit, initial=default_name)

    def refresh_data(self):
        """Fetches fresh docker data based on active tab."""
        self.refresh_in_progress = True
        current_tab = self.current_tab
        current_context = self.client.get_current_context()
        if self.current_tab in ("containers", "compose"):
            containers = self.sort_containers(self.client.list_containers())
            stats = self.client.get_container_stats() if containers else {}
            with self.data_lock:
                self.current_context = current_context
                self.containers = containers
                self.stats = stats
                self.build_compose_rows()
                if self.containers:
                    if self.selected_index >= len(self.containers):
                        self.selected_index = max(0, len(self.containers) - 1)
                else:
                    self.selected_index = 0
                    self.selected_compose_index = 0
        elif current_tab == "images":
            images = self.client.list_images()
            with self.data_lock:
                self.current_context = current_context
                self.images = images
                if self.selected_image_index >= len(self.images):
                    self.selected_image_index = max(0, len(self.images) - 1)
        elif current_tab == "volumes":
            volumes = self.client.list_volumes()
            with self.data_lock:
                self.current_context = current_context
                self.volumes = volumes
                if self.selected_volume_index >= len(self.volumes):
                    self.selected_volume_index = max(0, len(self.volumes) - 1)
        elif current_tab == "networks":
            networks = self.client.list_networks()
            with self.data_lock:
                self.current_context = current_context
                self.networks = networks
                if self.selected_network_index >= len(self.networks):
                    self.selected_network_index = max(0, len(self.networks) - 1)
        elif current_tab == "contexts":
            contexts = self.client.list_contexts()
            with self.data_lock:
                self.current_context = current_context
                self.contexts = contexts
                if self.selected_context_index >= len(self.contexts):
                    self.selected_context_index = max(0, len(self.contexts) - 1)
        with self.data_lock:
            self.last_refresh = time.time()
            self.refresh_in_progress = False
            self.need_redraw = True

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
        if self.client.docker_host:
            parsed = self.client.parse_docker_host()
            host_display = parsed["display"] if parsed else self.client.docker_host
            context_text = f" [{self.current_context} ({host_display})]" if self.current_context else f" [{host_display}]"
        else:
            context_text = f" [{self.current_context}]" if self.current_context else ""
        title_text = f"DockTUI Container Dashboard{context_text}"
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

        if not self.is_daemon_running_cached():
            print(f"\n{YELLOW}{BOLD}Warning: Cannot connect to the Docker daemon.{RESET}")
            print("Please make sure Docker Desktop or the docker service is running.")
            print("\nPress 'q' to quit, or 'r' to retry connection.")
            return

        tab_labels = {
            "containers": "Containers",
            "compose": "Compose",
            "images": "Images",
            "volumes": "Volumes",
            "networks": "Networks",
            "contexts": "Contexts",
        }
        header_parts = []
        for idx, tab in enumerate(self.tabs, start=1):
            label = f"{tab_labels[tab]} ({idx})"
            header_parts.append(f"{WHITE_ON_BLUE} {label} {RESET}" if tab == self.current_tab else f"[{label}]")
        filter_bits = []
        if self.container_filter:
            filter_bits.append(f"filter: {self.container_filter}")
        if self.state_filter != "all":
            filter_bits.append(f"state: {self.state_filter}")
        if self.sort_mode != "default":
            filter_bits.append(f"sort: {self.sort_mode}")
        filter_status = "    [" + " | ".join(filter_bits) + "]" if filter_bits else ""
        print("   ".join(header_parts) + filter_status)
        print("─" * (width - 1))

        # Render corresponding Tab Grid
        if self.current_tab == "containers":
            if not self.containers:
                if self.container_filter:
                    print(f"\n{CYAN}No containers match the active filter: '{self.container_filter}'{RESET}")
                    print("Press [C] to clear the filter.")
                else:
                    self.draw_empty_state("containers", width)
            else:
                # Calculate column widths dynamically based on terminal width
                rem = width - 26
                name_w = max(15, int(rem * 0.30))
                image_w = max(15, int(rem * 0.30))
                status_w = max(15, rem - name_w - image_w)

                # Table headers
                header_line = f"{BOLD}{'ID':<12} {self.truncate('NAME', name_w)} {self.truncate('IMAGE', image_w)} {'STATE':<10} {self.truncate('STATUS', status_w)}{RESET}"
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

                    line = f"{style}{c['id'][:10]:<12} {self.truncate(name_str, name_w)} {self.truncate(c['image'], image_w)} {state_formatted:<10} {self.truncate(c['status'], status_w)}{RESET}"
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

        elif self.current_tab == "compose":
            if not self.compose_rows:
                self.draw_empty_state("compose", width)
            else:
                service_w = max(18, int(width * 0.25))
                name_w = max(18, int(width * 0.25))
                image_w = max(20, int(width * 0.25))
                print(f"{BOLD}{self.truncate('PROJECT / SERVICE', service_w)} {self.truncate('CONTAINER', name_w)} {'STATE':<10} {self.truncate('IMAGE', image_w)}{RESET}")
                print("─" * (width - 1))
                for idx, row in enumerate(self.compose_rows):
                    style = WHITE_ON_BLUE if idx == self.selected_compose_index else ""
                    if row["type"] == "project":
                        project = str(row["project"])
                        count = len(row["containers"])  # type: ignore[arg-type]
                        print(f"{style}{BOLD}{self.truncate(project + '  (' + str(count) + ')', service_w)} {self.truncate('', name_w)} {'':<10} {self.truncate('', image_w)}{RESET}")
                    else:
                        container = row["container"]  # type: ignore[assignment]
                        service = container.get("compose_service") or "(standalone)"
                        state = container.get("state", "")
                        marker = "» " if idx == self.selected_compose_index else "  "
                        print(
                            f"{style}{self.truncate(marker + service, service_w)} "
                            f"{self.truncate(container.get('name', ''), name_w)} "
                            f"{state:<10} {self.truncate(container.get('image', ''), image_w)}{RESET}"
                        )

        elif self.current_tab == "images":
            if not self.images:
                self.draw_empty_state("images", width)
            else:
                # Calculate column widths dynamically based on terminal width
                rem = width - 26
                repo_w = max(20, int(rem * 0.45))
                tag_w = max(12, int(rem * 0.25))
                size_w = max(10, rem - repo_w - tag_w)

                # Table headers
                header_line = f"{BOLD}{'IMAGE ID':<12} {self.truncate('REPOSITORY', repo_w)} {self.truncate('TAG', tag_w)} {self.truncate('SIZE', size_w)}{RESET}"
                print(header_line)
                print("─" * (width - 1))

                # Render list of images
                for idx, img in enumerate(self.images):
                    style = WHITE_ON_BLUE if idx == self.selected_image_index else ""

                    if idx == self.selected_image_index:
                        repo_str = f"» {img['repository']}"
                    else:
                        repo_str = f"  {img['repository']}"

                    line = f"{style}{img['id'][:10]:<12} {self.truncate(repo_str, repo_w)} {self.truncate(img['tag'], tag_w)} {self.truncate(img['size'], size_w)}{RESET}"
                    print(line)
                print("─" * (width - 1))

        elif self.current_tab == "volumes":
            if not self.volumes:
                self.draw_empty_state("volumes", width)
            else:
                name_w = max(30, int(width * 0.50))
                driver_w = max(12, int(width * 0.20))
                print(f"{BOLD}{self.truncate('VOLUME', name_w)} {self.truncate('DRIVER', driver_w)} {'SCOPE':<12}{RESET}")
                print("─" * (width - 1))
                for idx, volume in enumerate(self.volumes):
                    style = WHITE_ON_BLUE if idx == self.selected_volume_index else ""
                    marker = "» " if idx == self.selected_volume_index else "  "
                    print(f"{style}{self.truncate(marker + volume['name'], name_w)} {self.truncate(volume['driver'], driver_w)} {volume['scope']:<12}{RESET}")
                print("─" * (width - 1))

        elif self.current_tab == "networks":
            if not self.networks:
                self.draw_empty_state("networks", width)
            else:
                id_w = 12
                name_w = max(30, int(width * 0.45))
                driver_w = max(12, int(width * 0.20))
                print(f"{BOLD}{'ID':<12} {self.truncate('NETWORK', name_w)} {self.truncate('DRIVER', driver_w)} {'SCOPE':<12}{RESET}")
                print("─" * (width - 1))
                for idx, network in enumerate(self.networks):
                    style = WHITE_ON_BLUE if idx == self.selected_network_index else ""
                    marker = "» " if idx == self.selected_network_index else "  "
                    print(f"{style}{network['id'][:10]:<12} {self.truncate(marker + network['name'], name_w)} {self.truncate(network['driver'], driver_w)} {network['scope']:<12}{RESET}")
                print("─" * (width - 1))

        elif self.current_tab == "contexts":
            if self.client.docker_host:
                print(f"{YELLOW}{BOLD}Note: DOCKER_HOST is active. Context switching is bypassed (DOCKER_HOST overrides context).{RESET}")
                print("─" * (width - 1))
            if not self.contexts:
                self.draw_empty_state("contexts", width)
            else:
                name_w = max(20, int(width * 0.25))
                desc_w = max(24, int(width * 0.30))
                endpoint_w = max(24, width - name_w - desc_w - 14)
                print(f"{BOLD}{self.truncate('CONTEXT', name_w)} {'CUR':<5} {self.truncate('DESCRIPTION', desc_w)} {self.truncate('ENDPOINT', endpoint_w)}{RESET}")
                print("─" * (width - 1))
                for idx, context in enumerate(self.contexts):
                    style = WHITE_ON_BLUE if idx == self.selected_context_index else ""
                    marker = "» " if idx == self.selected_context_index else "  "
                    print(
                        f"{style}{self.truncate(marker + context['name'], name_w)} "
                        f"{context['current']:<5} {self.truncate(context['description'], desc_w)} "
                        f"{self.truncate(context['endpoint'], endpoint_w)}{RESET}"
                    )
                print("─" * (width - 1))

        # Render status line at bottom
        print("\n" + "═" * (width - 1))
        # Clear status message if old
        if time.time() - self.status_time > 4:
            self.status_message = "Use Tab to switch tabs. Up/Down to navigate."
        print(f"{BOLD}Status:{RESET} {self.status_message}")
        print("═" * (width - 1))

        # Action instructions depending on the active tab
        if self.current_tab in ("containers", "compose"):
            print(f"{CYAN}[S] Start/Stop | [R] Restart | [L] Logs | [V] Details | [I] Inspect | [E] Exec | [O] Sort | [Y] State | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "images":
            print(f"{CYAN}[D] Delete Image | [P] Disk/Prune | [Tab] Switch | [G] Refresh | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "volumes":
            print(f"{CYAN}[D] Delete Volume | [P] Disk/Prune | [Tab] Switch | [G] Refresh | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "contexts":
            print(f"{CYAN}[U] Use Context | [Tab] Switch | [G] Refresh | [?] Help | [Q] Quit{RESET}")
        else:
            print(f"{CYAN}[Tab] Switch | [G] Refresh | [?] Help | [Q] Quit{RESET}")

    def draw_logs_view(self):
        """Renders the fullscreen log viewer screen."""
        if self.active_project:
            log_title = f"PROJECT LOGS: {self.active_project}"
            target_id = None
        else:
            sel = self.active_container or (self.containers[self.selected_index] if self.containers else None)
            if not sel:
                self.view_mode = "main"
                return
            log_title = f"LOGS: {sel['name']}"
            target_id = sel["id"]

        print("\033[2J\033[H", end="")

        # Pull logs if not loaded
        viewport_height = height - 6
        if not self.log_lines:
            self.load_log_lines(target_id, viewport_height, follow=True)
        elif self.log_follow and time.time() - self.last_log_refresh >= self.refresh_interval:
            self.load_log_lines(target_id, viewport_height, follow=True)

        filter_status = f" [FILTER: {self.log_filter}]" if self.log_filter else ""
        search_status = f" [SEARCH: {self.log_search}]" if self.log_search else ""
        error_status = " [ERRORS]" if self.log_errors_only else ""
        limit_status = f" [LIMIT: {self.log_tail_limit} lines]"
        follow_status = " [FOLLOW]" if self.log_follow else ""
        title_text = f"{log_title}{filter_status}{search_status}{error_status}{limit_status}{follow_status} (Line {self.log_scroll_index + 1} of {len(self.log_lines)})"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"

        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")

        end_idx = min(len(self.log_lines), self.log_scroll_index + viewport_height)
        for i in range(self.log_scroll_index, end_idx):
            print(self.log_lines[i][:width-1])

        # Pad with empty lines if viewport not full
        for _ in range(viewport_height - (end_idx - self.log_scroll_index)):
            print("")

        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[↑/↓] Scroll | [F] Follow | [Space] Pause | [/] Search | [N] Next | [E] Errors | [O] Export | [+/-] Limit | [?] Help | [Esc/L] Back{RESET}")

    def draw_help_view(self):
        """Renders a compact keyboard help screen."""
        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
        except Exception:
            width = 80

        print("\033[2J\033[H", end="")
        title_text = "DockTUI Help"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"

        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}\n")
        print(f"{BOLD}Global{RESET}")
        print("  Tab / 1-5    Switch tabs")
        print("  Up / Down    Move selection or scroll / Mouse scroll support")
        print("  G            Refresh current data")
        print("  ?            Open or close this help screen")
        print("  Q / Esc      Quit or return to the previous screen\n")
        print(f"{BOLD}Containers{RESET}")
        print("  S            Start or stop selected container / project")
        print("  R            Restart selected container / project")
        print("  L            Open logs (or Compose project logs)")
        print("  I            Inspect container JSON")
        print("  E            Execute command in running container")
        print("  N            Rename selected container")
        print("  V            Open readable container details")
        print("  T            View container processes (docker top)")
        print("  O / Y        Cycle sorting and state filters")
        print("  / / C        Apply or clear container filter\n")
        print(f"{BOLD}Logs{RESET}")
        print("  F            Toggle follow mode")
        print("  Space        Pause follow mode")
        print("  N            Jump to next search match")
        print("  E            Toggle error/warning-only lines")
        print("  + / -        Increase or decrease log tail limit")
        print("  / / C        Apply or clear log filter")
        print("  O            Export logs to a local file")
        print("  G            Refresh logs now\n")
        print(f"{BOLD}Images and cleanup{RESET}")
        print("  D            Delete selected image")
        print("  D            Delete selected volume on the Volumes tab")
        print("  P            Open Docker disk usage")
        print("  X / I / V / A Run system, image, volume, or full prune")
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[? / Esc / Q] Return to previous screen{RESET}")

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

        sel = self.active_container or self.containers[self.selected_index]
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
        print(f"{CYAN}[↑/↓] Scroll | [O] Export | [Esc] or [I] Return to dashboard{RESET}")

    def draw_details_view(self):
        """Renders a human-friendly container details screen."""
        if not self.details_lines:
            self.view_mode = "main"
            return

        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
            height = max(24, terminal_size.lines)
        except Exception:
            width = 80
            height = 24

        print("\033[2J\033[H", end="")
        title_text = f"CONTAINER DETAILS (Line {self.details_scroll_index + 1} of {len(self.details_lines)})"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"
        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")

        viewport_height = height - 6
        end_idx = min(len(self.details_lines), self.details_scroll_index + viewport_height)
        for i in range(self.details_scroll_index, end_idx):
            print(self.details_lines[i][:width-1])
        for _ in range(viewport_height - (end_idx - self.details_scroll_index)):
            print("")

        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[↑/↓] Scroll | [O] Export | [Esc/V] Return to dashboard{RESET}")

    def draw_top_view(self):
        """Renders docker top output for the active container."""
        if not self.top_lines:
            self.view_mode = "main"
            return
        try:
            terminal_size = os.get_terminal_size()
            width = max(80, terminal_size.columns)
            height = max(24, terminal_size.lines)
        except Exception:
            width = 80
            height = 24

        print("\033[2J\033[H", end="")
        title_text = f"CONTAINER PROCESSES (Line {self.top_scroll_index + 1} of {len(self.top_lines)})"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"
        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")

        viewport_height = height - 6
        end_idx = min(len(self.top_lines), self.top_scroll_index + viewport_height)
        for i in range(self.top_scroll_index, end_idx):
            print(self.top_lines[i][:width-1])
        for _ in range(viewport_height - (end_idx - self.top_scroll_index)):
            print("")
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[↑/↓] Scroll | [O] Export | [Esc/T] Return to dashboard{RESET}")

    def draw_input_view(self):
        """Renders the previous screen with a non-blocking input prompt."""
        previous = self.previous_view_mode
        if previous == "logs":
            self.draw_logs_view()
        elif previous == "inspect":
            self.draw_inspect_view()
        elif previous == "details":
            self.draw_details_view()
        elif previous == "top":
            self.draw_top_view()
        elif previous == "system":
            self.draw_system_view()
        elif previous == "exec":
            self.draw_exec_view()
        else:
            self.draw_main_view()
        print(f"\n{YELLOW}{BOLD}{self.input_prompt}{RESET}{self.input_buffer}", end="", flush=True)

    def enable_mouse_tracking(self):
        print("\033[?1000h", end="", flush=True)

    def disable_mouse_tracking(self):
        print("\033[?1000l", end="", flush=True)

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
        print(f"\n{YELLOW}Preview:{RESET} Docker does not provide a dry-run for prune; review the disk usage above before confirming.")
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[X] System prune | [I] Image prune | [V] Volume prune | [A] System prune + volumes | [Esc/P] Back{RESET}")

    def draw_exec_view(self):
        """Renders the scrollable command execution output screen."""
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

        sel = self.active_container or self.containers[self.selected_index]
        print("\033[2J\033[H", end="")

        title_text = f"EXEC OUT: {sel['name']} > {self.exec_command_text[:30]} (Line {self.exec_scroll_index + 1} of {len(self.exec_output_lines)})"
        padding = (width - 2 - len(title_text)) // 2
        title_line = "║" + " " * padding + title_text + " " * (width - 2 - len(title_text) - padding) + "║"

        print(f"{CYAN}{BOLD}╔" + "═" * (width - 2) + f"╗{RESET}")
        print(f"{CYAN}{BOLD}{title_line}{RESET}")
        print(f"{CYAN}{BOLD}╚" + "═" * (width - 2) + f"╝{RESET}")

        # Viewport size (lines available for content)
        viewport_height = height - 6
        end_idx = min(len(self.exec_output_lines), self.exec_scroll_index + viewport_height)

        for i in range(self.exec_scroll_index, end_idx):
            print(self.exec_output_lines[i][:width-1])

        # Pad with empty lines if not full
        for _ in range(viewport_height - (end_idx - self.exec_scroll_index)):
            print("")

        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[↑/↓] Scroll | [R] Run command again | [E] Run different command | [Esc] Return to dashboard{RESET}")

    def run(self):
        """The main dashboard control loop."""
        global RESIZE_REQUESTED
        init_terminal()
        self.enable_mouse_tracking()
        self.start_refresh_worker()
        self.request_refresh()

        running = True
        try:
            while running:
                # Query terminal height
                try:
                    viewport_h = max(24, os.get_terminal_size().lines) - 6
                except Exception:
                    viewport_h = 18

                # Render corresponding view if needed
                if self.need_redraw:
                    self.need_redraw = False
                    if self.view_mode == "main":
                        self.draw_main_view()
                    elif self.view_mode == "logs":
                        self.draw_logs_view()
                    elif self.view_mode == "inspect":
                        self.draw_inspect_view()
                    elif self.view_mode == "details":
                        self.draw_details_view()
                    elif self.view_mode == "top":
                        self.draw_top_view()
                    elif self.view_mode == "system":
                        self.draw_system_view()
                    elif self.view_mode == "exec":
                        self.draw_exec_view()
                    elif self.view_mode == "input":
                        self.draw_input_view()
                    elif self.view_mode == "help":
                        self.draw_help_view()

                # Auto-refresh main dashboard every 2 seconds
                if self.view_mode == "main" and (time.time() - self.last_refresh > self.refresh_interval):
                    self.request_refresh()
                # Auto-refresh logs in follow mode every 2 seconds
                if self.view_mode == "logs" and self.log_follow and (time.time() - self.last_log_refresh > self.refresh_interval):
                    self.need_redraw = True
                if RESIZE_REQUESTED:
                    RESIZE_REQUESTED = False
                    self.request_refresh()
                    self.need_redraw = True
                if self.status_message != "Use Tab to switch tabs. Up/Down to navigate." and (time.time() - self.status_time > 4):
                    self.status_message = "Use Tab to switch tabs. Up/Down to navigate."
                    self.need_redraw = True

                # Check for keyboard input
                key = get_key_nonblocking()
                if key:
                    self.need_redraw = True
                    if self.view_mode == "input":
                        self.handle_input_key(key)
                        time.sleep(0.08)
                        continue
                    if key == "mouse":
                        self.set_status("Mouse click detected. Scroll to navigate list/logs.")
                        time.sleep(0.08)
                        continue
                    key = key.lower() if len(key) == 1 else key
                    if self.view_mode == "logs":
                        if key in ("up", "scroll_up"):
                            self.log_follow = False
                            delta = 3 if key == "scroll_up" else 1
                            self.log_scroll_index = max(0, self.log_scroll_index - delta)
                        elif key in ("down", "scroll_down"):
                            self.log_follow = False
                            delta = 3 if key == "scroll_down" else 1
                            self.log_scroll_index = max(0, min(self.log_scroll_index + delta, len(self.log_lines) - viewport_h))
                        elif key == "g":
                            self.log_lines = []
                            self.last_log_refresh = 0.0
                            self.set_status("Logs refreshed.")
                        elif key == " ":
                            self.log_follow = False
                            self.set_status("Log follow paused.")
                        elif key == "f":
                            self.log_follow = not self.log_follow
                            self.log_lines = []
                            mode = "enabled" if self.log_follow else "disabled"
                            self.set_status(f"Log follow mode {mode}.")
                        elif key == "/":
                            query = self.prompt_user("Enter search term: ")
                            self.log_search = query
                            self.log_filter = query
                            self.log_match_index = -1
                            self.log_lines = []
                        elif key == "n":
                            self.jump_to_next_log_match(viewport_h)
                        elif key == "e":
                            self.log_errors_only = not self.log_errors_only
                            self.log_lines = []
                            mode = "enabled" if self.log_errors_only else "disabled"
                            self.set_status(f"Error-only logs {mode}.")
                        elif key == "c":
                            self.log_filter = ""
                            self.log_search = ""
                            self.log_errors_only = False
                            self.log_lines = []
                            self.set_status("Cleared log filter.")
                        elif key in ("+", "="):
                            self.log_tail_limit = min(500, self.log_tail_limit + 10)
                            self.log_lines = []
                            self.set_status(f"Increased log limit to {self.log_tail_limit} lines.")
                        elif key == "-":
                            self.log_tail_limit = max(10, self.log_tail_limit - 10)
                            self.log_lines = []
                            self.set_status(f"Decreased log limit to {self.log_tail_limit} lines.")
                        elif key == "?":
                            self.open_help()
                        elif key == "o":
                            self.log_follow = False
                            self.start_input("Export logs to path: ", self.export_logs_to_file)
                        elif key in ("q", "l", "\x1b"):
                            self.view_mode = "main"
                    elif self.view_mode == "help":
                        if key in ("?", "q", "\x1b"):
                            self.close_help()
                    elif self.view_mode == "inspect":
                        if key in ("up", "scroll_up"):
                            delta = 3 if key == "scroll_up" else 1
                            self.inspect_scroll_index = max(0, self.inspect_scroll_index - delta)
                        elif key in ("down", "scroll_down"):
                            delta = 3 if key == "scroll_down" else 1
                            self.inspect_scroll_index = max(0, min(self.inspect_scroll_index + delta, len(self.inspect_lines) - viewport_h))
                        elif key == "o":
                            self.start_input("Export inspect JSON to path: ", self.export_inspect_to_file)
                        elif key in ("i", "\x1b"):  # 'i' or 'Esc'
                            self.view_mode = "main"
                        elif key == "?":
                            self.open_help()
                    elif self.view_mode == "system":
                        if key in ("x", "i", "v", "a"):
                            prune_name = {
                                "x": "PRUNE",
                                "i": "IMAGES",
                                "v": "VOLUMES",
                                "a": "ALL",
                            }[key]
                            prompt = f"Type {prune_name} to confirm prune: "
                            confirm = self.prompt_user(prompt)
                            if confirm != prune_name:
                                self.set_status("Prune canceled.")
                                continue
                            self.set_status(f"Running Docker prune ({prune_name})...")
                            self.draw_system_view()
                            if key == "i":
                                prune_out = self.client.prune_images()
                            elif key == "v":
                                prune_out = self.client.prune_volumes()
                            else:
                                prune_out = self.client.prune_system(include_volumes=(key == "a"))
                            print("\n" + "─" * 40)
                            print(prune_out)
                            print("─" * 40)
                            self.prompt_user("Prune complete. Press ENTER to continue.")
                            self.system_info_text = ""
                            self.refresh_data()
                        elif key in ("p", "\x1b"):
                            self.view_mode = "main"
                        elif key == "?":
                            self.open_help()
                    elif self.view_mode == "details":
                        if key in ("up", "scroll_up"):
                            delta = 3 if key == "scroll_up" else 1
                            self.details_scroll_index = max(0, self.details_scroll_index - delta)
                        elif key in ("down", "scroll_down"):
                            delta = 3 if key == "scroll_down" else 1
                            self.details_scroll_index = max(0, min(self.details_scroll_index + delta, len(self.details_lines) - viewport_h))
                        elif key == "o":
                            self.start_input("Export details to path: ", self.export_details_to_file)
                        elif key in ("v", "\x1b"):
                            self.view_mode = "main"
                        elif key == "?":
                            self.open_help()
                    elif self.view_mode == "top":
                        if key in ("up", "scroll_up"):
                            delta = 3 if key == "scroll_up" else 1
                            self.top_scroll_index = max(0, self.top_scroll_index - delta)
                        elif key in ("down", "scroll_down"):
                            delta = 3 if key == "scroll_down" else 1
                            self.top_scroll_index = max(0, min(self.top_scroll_index + delta, len(self.top_lines) - viewport_h))
                        elif key == "o":
                            self.start_input("Export processes to path: ", self.export_top_to_file)
                        elif key in ("t", "q", "\x1b"):
                            self.view_mode = "main"
                        elif key == "?":
                            self.open_help()
                    elif self.view_mode == "exec":
                        if key in ("up", "scroll_up"):
                            delta = 3 if key == "scroll_up" else 1
                            self.exec_scroll_index = max(0, self.exec_scroll_index - delta)
                        elif key in ("down", "scroll_down"):
                            delta = 3 if key == "scroll_down" else 1
                            self.exec_scroll_index = max(0, min(self.exec_scroll_index + delta, len(self.exec_output_lines) - viewport_h))
                        elif key == "r":
                            sel = self.active_container or self.current_selected_container()
                            if sel:
                                self.set_status(f"Running command: {self.exec_command_text}...")
                                self.draw_exec_view()
                                output = self.client.exec_command(sel["id"], self.exec_command_text)
                                self.exec_output_lines = output.split("\n")
                                self.exec_scroll_index = 0
                        elif key == "e":
                            sel = self.active_container or self.current_selected_container()
                            if sel:
                                command = self.prompt_exec_command(sel["name"])
                                if command:
                                    self.exec_command_text = command
                                    self.record_exec_command(command)
                                    self.set_status(f"Running command: {command}...")
                                    self.draw_exec_view()
                                    output = self.client.exec_command(sel["id"], command)
                                    self.exec_output_lines = output.split("\n")
                                    self.exec_scroll_index = 0
                        elif key in ("q", "\x1b"):
                            self.view_mode = "main"
                        elif key == "?":
                            self.open_help()
                    else:
                        # Dashboard controls (main view)
                        if key == "q":
                            running = False
                        elif key == "\t":
                            self.cycle_tab()
                        elif key in ("1", "2", "3", "4", "5"):
                            self.current_tab = self.tabs[int(key) - 1]
                            self.set_status(f"Switched tab to {self.current_tab}.")
                            self.refresh_data()
                        elif key == "\x1b":
                            running = False
                        elif key in ("up", "scroll_up"):
                            if self.current_tab == "containers":
                                if self.selected_index > 0:
                                    self.selected_index -= 1
                            elif self.current_tab == "compose":
                                if self.selected_compose_index > 0:
                                    self.selected_compose_index -= 1
                            elif self.current_tab == "volumes":
                                if self.selected_volume_index > 0:
                                    self.selected_volume_index -= 1
                            elif self.current_tab == "networks":
                                if self.selected_network_index > 0:
                                    self.selected_network_index -= 1
                            elif self.current_tab == "contexts":
                                if self.selected_context_index > 0:
                                    self.selected_context_index -= 1
                            else:
                                if self.selected_image_index > 0:
                                    self.selected_image_index -= 1
                        elif key in ("down", "scroll_down"):
                            if self.current_tab == "containers":
                                if self.selected_index < len(self.containers) - 1:
                                    self.selected_index += 1
                            elif self.current_tab == "compose":
                                if self.selected_compose_index < len(self.compose_rows) - 1:
                                    self.selected_compose_index += 1
                            elif self.current_tab == "volumes":
                                if self.selected_volume_index < len(self.volumes) - 1:
                                    self.selected_volume_index += 1
                            elif self.current_tab == "networks":
                                if self.selected_network_index < len(self.networks) - 1:
                                    self.selected_network_index += 1
                            elif self.current_tab == "contexts":
                                if self.selected_context_index < len(self.contexts) - 1:
                                    self.selected_context_index += 1
                            else:
                                if self.selected_image_index < len(self.images) - 1:
                                    self.selected_image_index += 1
                        elif key == "g":
                            self.set_status("Refreshing data...")
                            self.refresh_data()
                        elif key == "?":
                            self.open_help()
                        elif key == "/":
                            query = self.prompt_user("Filter containers (name/image): ")
                            self.container_filter = query
                            self.selected_index = 0
                            self.selected_compose_index = 0
                            self.set_status(f"Filter set to: '{query}'")
                            self.refresh_data()
                        elif key == "c":
                            self.container_filter = ""
                            self.selected_index = 0
                            self.selected_compose_index = 0
                            self.set_status("Cleared container filter.")
                            self.refresh_data()
                        elif key == "o":
                            modes = ["default", "name", "image", "state"]
                            self.sort_mode = modes[(modes.index(self.sort_mode) + 1) % len(modes)]
                            self.set_status(f"Sort mode: {self.sort_mode}.")
                            self.refresh_data()
                        elif key == "y":
                            modes = ["all", "running", "exited", "created"]
                            self.state_filter = modes[(modes.index(self.state_filter) + 1) % len(modes)]
                            self.set_status(f"State filter: {self.state_filter}.")
                            self.refresh_data()
                        elif key == "p":
                            self.system_info_text = ""  # Reset system stats on enter
                            self.view_mode = "system"
                        elif key == "l" and self.current_tab in ("containers", "compose"):
                            if self.current_tab == "compose" and self.compose_rows and self.compose_rows[self.selected_compose_index].get("type") == "project":
                                row = self.compose_rows[self.selected_compose_index]
                                self.active_project = row["project"]
                                self.active_container = None
                                self.log_filter = ""
                                self.log_search = ""
                                self.log_errors_only = False
                                self.log_lines = []
                                self.log_follow = False
                                self.last_log_refresh = 0.0
                                self.view_mode = "logs"
                            else:
                                sel = self.current_selected_container()
                                if sel:
                                    self.active_container = sel
                                    self.active_project = None
                                    self.log_filter = ""  # Reset log filter on enter
                                    self.log_search = ""
                                    self.log_errors_only = False
                                    self.log_lines = []   # Force reload logs
                                    self.log_follow = False
                                    self.last_log_refresh = 0.0
                                    self.view_mode = "logs"
                        elif key == "v" and self.current_tab in ("containers", "compose"):
                            sel = self.current_selected_container()
                            if sel:
                                self.active_container = sel
                                self.set_status(f"Loading details for {sel['name']}...")
                                self.draw_main_view()
                                self.details_lines = self.build_details_lines(sel["id"])
                                self.details_scroll_index = 0
                                self.view_mode = "details"
                        elif key == "i" and self.current_tab in ("containers", "compose"):
                            sel = self.current_selected_container()
                            if sel:
                                self.active_container = sel
                                self.set_status(f"Inspecting container {sel['name']}...")
                                self.draw_main_view()
                                inspect_data = self.client.inspect_container(sel["id"])
                                self.inspect_lines = inspect_data.split("\n")
                                self.inspect_scroll_index = 0
                                self.view_mode = "inspect"
                        elif key == "t" and self.current_tab in ("containers", "compose"):
                            sel = self.current_selected_container()
                            if sel:
                                if sel["state"] != "running":
                                    self.set_status(f"Error: Container {sel['name']} is not running.")
                                else:
                                    self.active_container = sel
                                    self.set_status(f"Loading processes for {sel['name']}...")
                                    self.draw_main_view()
                                    top_data = self.client.top_container(sel["id"])
                                    self.top_lines = top_data.split("\n")
                                    self.top_scroll_index = 0
                                    self.view_mode = "top"
                        elif key == "e" and self.current_tab in ("containers", "compose"):
                            sel = self.current_selected_container()
                            if sel:
                                if sel["state"] != "running":
                                    self.set_status(f"Error: Container {sel['name']} is not running.")
                                else:
                                    self.active_container = sel
                                    command = self.prompt_exec_command(sel["name"])
                                    if command:
                                        self.exec_command_text = command
                                        self.record_exec_command(command)
                                        self.set_status(f"Running command: {command}...")
                                        self.draw_main_view()
                                        output = self.client.exec_command(sel["id"], command)
                                        self.exec_output_lines = output.split("\n")
                                        self.exec_scroll_index = 0
                                        self.view_mode = "exec"
                        elif key == "n" and self.current_tab == "containers":
                            if self.containers:
                                sel = self.containers[self.selected_index]
                                new_name = self.prompt_user(f"New name for container {sel['name']}: ")
                                if new_name:
                                    self.set_status(f"Renaming container {sel['name']} to {new_name}...")
                                    self.draw_main_view()
                                    success, msg = self.client.rename_container(sel["id"], new_name)
                                    if success:
                                        self.set_status(f"Successfully renamed to {new_name}.")
                                    else:
                                        self.set_status(f"Rename failed: {msg}")
                                    self.refresh_data()
                        elif key == "r" and self.current_tab in ("containers", "compose"):
                            # Attempt to reconnect daemon or restart container
                            if not self.is_daemon_running_cached(force=True):
                                self.set_status("Reconnecting to Docker daemon...")
                                self.refresh_data()
                            elif not self.containers:
                                self.set_status("Connected to Docker daemon. Refreshing data...")
                                self.refresh_data()
                            elif self.current_tab == "compose" and self.compose_rows and self.compose_rows[self.selected_compose_index].get("type") == "project":
                                row = self.compose_rows[self.selected_compose_index]
                                for container in row["containers"]:  # type: ignore[index]
                                    self.client.restart_container(container["id"])
                                self.set_status(f"Restarted project {row['project']}.")
                                self.refresh_data()
                            else:
                                sel = self.current_selected_container()
                                if not sel:
                                    continue
                                self.set_status(f"Restarting container: {sel['name']}...")
                                self.draw_main_view()
                                if self.client.restart_container(sel["id"]):
                                    self.set_status(f"Successfully restarted container {sel['name']}.")
                                else:
                                    self.set_status(f"Failed to restart container {sel['name']}.")
                                self.refresh_data()
                        elif key == "s" and self.current_tab in ("containers", "compose"):
                            if self.current_tab == "compose" and self.compose_rows and self.compose_rows[self.selected_compose_index].get("type") == "project":
                                row = self.compose_rows[self.selected_compose_index]
                                containers = row["containers"]  # type: ignore[index]
                                any_running = any(c["state"] == "running" for c in containers)
                                for container in containers:
                                    if any_running and container["state"] == "running":
                                        self.client.stop_container(container["id"])
                                    elif not any_running:
                                        self.client.start_container(container["id"])
                                action = "Stopped" if any_running else "Started"
                                self.set_status(f"{action} project {row['project']}.")
                                self.refresh_data()
                            else:
                                sel = self.current_selected_container()
                                if not sel:
                                    continue
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
                        elif key == "d" and self.current_tab == "volumes":
                            if self.volumes:
                                volume = self.volumes[self.selected_volume_index]
                                confirm = self.prompt_user(f"Delete volume {volume['name']}? (y/n): ")
                                if confirm.lower() in ("y", "yes"):
                                    success, msg = self.client.remove_volume(volume["name"])
                                    self.set_status(msg if success else f"Volume delete failed: {msg}")
                                    self.refresh_data()
                                else:
                                    self.set_status("Volume deletion canceled.")
                        elif key == "u" and self.current_tab == "contexts":
                            if self.client.docker_host:
                                self.set_status("Cannot switch context: DOCKER_HOST is active and overrides context.")
                            elif self.contexts:
                                sel_ctx = self.contexts[self.selected_context_index]
                                self.set_status(f"Switching Docker context to {sel_ctx['name']}...")
                                self.draw_main_view()
                                success, msg = self.client.use_context(sel_ctx["name"])
                                self.set_status(msg)
                                self.refresh_data()

                    # Small sleep to prevent high CPU usage
                    time.sleep(0.08)
        finally:
            self.stop_refresh_worker()
            self.disable_mouse_tracking()
            print(RESET)
