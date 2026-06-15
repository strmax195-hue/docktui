"""Main DockTUI TUI.

This module is the dashboard orchestrator. It owns the input loop, the data
shaping, the help screen, and the modal input flow. Drawing helpers live in
`styles` and `screen`; cross-platform key capture lives at the bottom of this
file; everything else is delegated to small methods that views call.
"""
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import Config
from .constants import (
    AVAILABLE_TABS,
    DEFAULT_DOCKER_TIMEOUT,
    DEFAULT_EXEC_PRESETS,
    DEFAULT_LOG_TAIL_LIMIT,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_THEME,
)
from .dialogs import DialogResult, apply_dialog_key
from .docker_client import DockerClient
from .enums import ComposeAction, StateFilter, ThemeName, ViewMode
from .keymap import Keymap
from .log_stream import LineStreamer
from .screen import (
    clear_screen,
    draw_frame,
    draw_status_bar,
    get_terminal_size,
    pad_to_viewport,
    scroll_step,
    slice_viewport,
    truncate,
    viewport_height_for,
)
from .styles import (
    BOLD,
    CYAN,
    GREEN,
    RED,
    RESET,
    WHITE_ON_BLUE,
    YELLOW,
    apply_theme_colors,
)

# ---------------------------------------------------------------------------
# Cross-platform keyboard input
# ---------------------------------------------------------------------------

RESIZE_REQUESTED = False


def handle_resize(_signum=None, _frame=None):
    global RESIZE_REQUESTED
    RESIZE_REQUESTED = True


if hasattr(signal, "SIGWINCH"):
    try:
        signal.signal(signal.SIGWINCH, handle_resize)
    except Exception:
        pass


try:
    import msvcrt  # type: ignore[import-not-found]
    PLATFORM = "windows"

    def init_terminal() -> None:
        os.system("")

    def get_key_nonblocking() -> Optional[str]:
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()
                if ch2 == b"H":
                    return "up"
                if ch2 == b"P":
                    return "down"
            if ch in (b"\r", b"\n"):
                return "enter"
            if ch in (b"\x08", b"\x7f"):
                return "backspace"
            if ch == b"\x1b":
                return "\x1b"
            try:
                return ch.decode("utf-8")
            except UnicodeDecodeError:
                return None
        return None

except ImportError:  # Unix / macOS
    import select
    import sys
    import termios
    import tty

    PLATFORM = "unix"

    def init_terminal() -> None:
        return None

    def get_key_nonblocking() -> Optional[str]:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
            if rlist:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    rlist2, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if rlist2:
                        ch2 = sys.stdin.read(2)
                        if ch2 == "[A":
                            return "up"
                        if ch2 == "[B":
                            return "down"
                        if ch2 == "[M":
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
                return ch
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ERROR_KEYWORDS = ("error", "warn", "exception")


def _log_matches_filter(line: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.lower() in line.lower()


def _log_is_error_line(line: str) -> bool:
    lowered = line.lower()
    return any(keyword in lowered for keyword in ERROR_KEYWORDS)


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------


class ContainerDashboard:
    """The main TUI rendering and interaction loop."""

    def __init__(
        self,
        refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
        docker_timeout: float = DEFAULT_DOCKER_TIMEOUT,
        docker_host: Optional[str] = None,
        theme: Optional[str] = None,
        exec_presets: Optional[List[str]] = None,
        log_tail_limit: Optional[int] = None,
        config: Optional[Config] = None,
    ):
        # ---------------------------------------------------------------- data
        self.config: Config = config or Config(
            refresh_interval=refresh_interval,
            docker_timeout=docker_timeout,
            theme=theme or DEFAULT_THEME,
            log_tail_limit=log_tail_limit or DEFAULT_LOG_TAIL_LIMIT,
            exec_presets=list(exec_presets) if exec_presets else list(DEFAULT_EXEC_PRESETS),
        )
        self.config.validate()
        self.client = DockerClient(timeout=self.config.docker_timeout, host=docker_host)
        self.theme = self.config.theme
        apply_theme_colors(self.theme)

        # ---------------------------------------------------------------- state
        self.tabs: List[str] = list(AVAILABLE_TABS)
        self.filters: Dict[str, str] = {tab: "" for tab in self.tabs}
        self.containers: List[Dict[str, str]] = []
        self.stats: Dict[str, Dict[str, str]] = {}
        self.images: List[Dict[str, str]] = []
        self.volumes: List[Dict[str, str]] = []
        self.networks: List[Dict[str, str]] = []
        self.contexts: List[Dict[str, str]] = []
        self.compose_rows: List[Dict[str, Any]] = []
        self.active_container: Optional[Dict[str, str]] = None
        self.active_project: Optional[str] = None
        self.active_endpoint: Optional[str] = None
        self.endpoints: List[Dict[str, str]] = list(self.config.endpoints)

        self.selected_index = 0
        self.selected_image_index = 0
        self.selected_volume_index = 0
        self.selected_network_index = 0
        self.selected_compose_index = 0
        self.selected_context_index = 0
        self.current_tab = self.tabs[0]
        self.view_mode = ViewMode.MAIN
        self.previous_view_mode = ViewMode.MAIN
        self.status_message = "Welcome to DockTUI! Use Tab or 1/2 keys to switch tabs."
        self.status_time = time.time()
        self.last_refresh = 0.0
        self.refresh_interval = self.config.refresh_interval
        self.state_filter = StateFilter.ALL.value
        self.sort_mode = "default"

        # ---------------------------------------------------------------- logs
        self.log_filter = ""
        self.log_search = ""
        self.log_match_index = 0
        self.log_errors_only = False
        self.log_tail_limit = self.config.log_tail_limit
        self.log_lines: List[str] = []
        self.log_scroll_index = 0
        self.log_follow = False
        self.last_log_refresh = 0.0
        self.log_highlight_patterns: List[Tuple[str, str]] = []  # (label, color)
        self.log_highlight_regex: Optional[re.Pattern] = None

        # ---------------------------------------------------------------- exec
        self.exec_output_lines: List[str] = []
        self.exec_scroll_index = 0
        self.exec_command_text = ""
        self.exec_history: List[str] = []

        # ---------------------------------------------------------------- other
        self.system_info_text = ""
        self.current_context = ""
        self.daemon_running = False
        self.last_daemon_check = 0.0
        self.daemon_check_interval = 3.0
        self.compose_snippet_lines: List[str] = []
        self.compose_snippet_scroll_index = 0
        self.inspect_lines: List[str] = []
        self.inspect_scroll_index = 0
        self.details_lines: List[str] = []
        self.details_scroll_index = 0
        self.top_lines: List[str] = []
        self.top_scroll_index = 0
        self.settings_options: List[Dict[str, Any]] = []
        self.settings_index = 0
        self.pull_lines: List[str] = []
        self.pull_scroll_index = 0
        self.pull_image_name = ""
        self.search_results: List[Dict[str, str]] = []
        self.search_index = 0
        self.file_entries: List[Dict[str, str]] = []
        self.file_path = "/"
        self.file_volume_name = ""
        self.file_index = 0

        # ---------------------------------------------------------------- threading
        self.data_lock = threading.Lock()
        self.refresh_requested = threading.Event()
        self.stop_refresh = threading.Event()
        self.refresh_thread: Optional[threading.Thread] = None
        self.refresh_in_progress = False
        self.log_stream_process: Optional[subprocess.Popen] = None
        self.log_stream_threads: List[threading.Thread] = []
        self.log_streamer: Optional[LineStreamer] = None
        self.pull_streamer: Optional[LineStreamer] = None

        # ---------------------------------------------------------------- modal
        self.input_dialog = DialogResult()
        self.need_redraw = True
        self.pinned_view = None
        self.pinned_target = None
        self._quit_requested = False
        self._viewport_h = 0

        # ---------------------------------------------------------------- keymap
        self.keymap = Keymap()
        self._register_bindings()

    # ------------------------------------------------------------- properties

    @property
    def container_filter(self) -> str:
        return self.filters.get("containers") or ""

    @container_filter.setter
    def container_filter(self, val: str) -> None:
        self.filters["containers"] = val
        self.filters["compose"] = val

    @property
    def exec_presets(self) -> List[str]:
        return list(self.config.exec_presets)

    # ------------------------------------------------------------- keymap

    def _register_bindings(self) -> None:
        km = self.keymap
        # Global
        km.register_global("?", self.open_help, "Open help")
        km.register_global("q", lambda _k: self._request_quit(), "Quit")
        km.register_global("\x1b", lambda _k: self._request_quit(), "Quit")
        km.register_global("m", self.cycle_theme, "Cycle theme")
        km.register_global("g", self._force_refresh, "Refresh data")
        km.register_global("tab", lambda _k: self.cycle_tab(1), "Next tab")
        km.register_global("/", self._start_filter_prompt, "Filter tab")
        km.register_global("c", self._clear_filter, "Clear filter")
        km.register_global("\t", lambda _k: self.cycle_tab(1), "Next tab")  # tab already above
        # Help / back navigation is per-view (see _handle_key).

    # ------------------------------------------------------------- status

    def set_status(self, msg: str) -> None:
        self.status_message = msg
        self.status_time = time.time()
        self.need_redraw = True

    def request_refresh(self) -> None:
        self.refresh_requested.set()

    def _request_quit(self) -> None:
        self._quit_requested = True

    def _force_refresh(self, _key: str) -> None:
        self.set_status("Refreshing data...")
        self.refresh_data()

    # ------------------------------------------------------------- refresh worker

    def start_refresh_worker(self) -> None:
        if self.refresh_thread and self.refresh_thread.is_alive():
            return
        self.stop_refresh.clear()
        self.refresh_thread = threading.Thread(target=self.refresh_worker, daemon=True)
        self.refresh_thread.start()

    def stop_refresh_worker(self) -> None:
        self.stop_refresh.set()
        self.refresh_requested.set()
        if self.refresh_thread:
            self.refresh_thread.join(timeout=1.0)

    def refresh_worker(self) -> None:
        while not self.stop_refresh.is_set():
            interval = self.refresh_interval
            if self.current_tab == "images":
                interval = self.config.refresh_interval_images
            elif self.current_tab == "volumes":
                interval = self.config.refresh_interval_volumes
            elif self.current_tab == "networks":
                interval = self.config.refresh_interval_networks

            self.refresh_requested.wait(timeout=interval)
            self.refresh_requested.clear()
            if self.stop_refresh.is_set():
                break
            try:
                self.refresh_data()
            except Exception:
                pass

    def is_daemon_running_cached(self, force: bool = False) -> bool:
        now = time.time()
        if force or now - self.last_daemon_check >= self.daemon_check_interval:
            self.daemon_running = self.client.is_daemon_running()
            self.last_daemon_check = now
        return self.daemon_running

    # ------------------------------------------------------------- input dialog

    def start_input(
        self,
        prompt: str,
        callback: Callable[[str], None],
        cancel_callback: Optional[Callable[[], None]] = None,
        initial: str = "",
    ) -> None:
        self.previous_view_mode = self.view_mode
        self.view_mode = ViewMode.INPUT
        self.input_dialog = DialogResult(
            prompt=prompt,
            buffer=initial,
            submit=callback,
            cancel=cancel_callback,
        )
        self.need_redraw = True

    def cancel_input(self) -> None:
        dialog = self.input_dialog
        if dialog.cancel is not None:
            dialog.cancel()
        self.input_dialog = DialogResult()
        self.view_mode = self.previous_view_mode
        self.need_redraw = True

    def submit_input(self) -> None:
        dialog = self.input_dialog
        value = dialog.buffer.strip()
        callback = dialog.submit
        self.input_dialog = DialogResult()
        self.view_mode = self.previous_view_mode
        self.need_redraw = True
        if callback is not None:
            callback(value)

    def handle_input_key(self, key: str) -> None:
        # submit/cancel must reset view_mode and clear the dialog; the generic
        # `apply_dialog_key` only fires the callback and leaves the modal alive,
        # which would leave the user stuck in the input view.
        if key == "enter":
            self.submit_input()
            return
        if key in ("\x1b", "q"):
            self.cancel_input()
            return
        if apply_dialog_key(self.input_dialog, key):
            self.need_redraw = True

    # ------------------------------------------------------------- prompt

    def prompt_user(self, prompt_text: str) -> str:
        """Blocking prompt used for legacy y/n confirmations."""
        print(f"\r\033[K{YELLOW}{BOLD}{prompt_text}{RESET}", end="", flush=True)
        try:
            if PLATFORM == "windows":
                while msvcrt.kbhit():
                    msvcrt.getch()
            return input().strip()
        except Exception:
            return ""

    # ------------------------------------------------------------- export

    def _export_lines_to_file(self, lines: List[str], type_name: str, filepath: str) -> None:
        if not filepath:
            self.set_status("Export canceled: empty path.")
            return
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            self.set_status(f"{type_name} successfully exported to {filepath}")
        except Exception as e:
            self.set_status(f"Failed to export {type_name.lower()}: {e}")

    def export_logs_to_file(self, filepath: str) -> None:
        self._export_lines_to_file(self.log_lines, "Logs", filepath)

    def export_inspect_to_file(self, filepath: str) -> None:
        self._export_lines_to_file(self.inspect_lines, "Inspect JSON", filepath)

    def export_details_to_file(self, filepath: str) -> None:
        self._export_lines_to_file(self.details_lines, "Details", filepath)

    def export_top_to_file(self, filepath: str) -> None:
        self._export_lines_to_file(self.top_lines, "Processes", filepath)

    def export_compose_snippet_to_file(self, filepath: str) -> None:
        self._export_lines_to_file(self.compose_snippet_lines, "Compose Snippet", filepath)

    def export_settings_to_file(self, filepath: str) -> None:
        lines = [f"{opt['label']}: {opt['display']()}" for opt in self.settings_options]
        self._export_lines_to_file(lines, "Settings", filepath)

    def export_search_to_file(self, filepath: str) -> None:
        lines = [str(r) for r in self.search_results]
        self._export_lines_to_file(lines, "Search Results", filepath)

    def export_pull_progress_to_file(self, filepath: str) -> None:
        self._export_lines_to_file(self.pull_lines, "Pull Progress", filepath)

    def export_files_to_file(self, filepath: str) -> None:
        lines = [f"{e['name']} ({e['type']}) - {e['size']}" for e in self.file_entries]
        self._export_lines_to_file(lines, "Files", filepath)


    # ------------------------------------------------------------- data shaping

    def cycle_tab(self, offset: int = 1) -> None:
        idx = self.tabs.index(self.current_tab)
        self.current_tab = self.tabs[(idx + offset) % len(self.tabs)]
        self.set_status(f"Switched tab to {self.current_tab}.")
        self.request_refresh()

    def cycle_theme(self, _key: str) -> None:
        order = [ThemeName.DARK.value, ThemeName.LIGHT.value, ThemeName.HIGH_CONTRAST.value]
        current_idx = order.index(self.theme) if self.theme in order else 0
        self.theme = order[(current_idx + 1) % len(order)]
        self.config.theme = self.theme
        apply_theme_colors(self.theme)
        self.set_status(f"Switched theme to {self.theme}.")
        self.need_redraw = True

    def current_selected_container(self) -> Optional[Dict[str, str]]:
        if self.current_tab == "containers" and self.containers:
            return self.containers[self.selected_index]
        if self.current_tab == "compose" and self.compose_rows:
            row = self.compose_rows[self.selected_compose_index]
            if row.get("type") == "container":
                return row.get("container")  # type: ignore[return-value]
        return None

    def sort_containers(self, containers: List[Dict[str, str]]) -> List[Dict[str, str]]:
        if self.state_filter != StateFilter.ALL.value:
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
        return sorted(containers, key=lambda c: (c.get("state") != "running", c.get("name", "")))

    def build_compose_rows(self) -> None:
        groups: Dict[str, List[Dict[str, str]]] = {}
        loose: List[Dict[str, str]] = []
        for container in self.containers:
            project = container.get("compose_project")
            if project:
                groups.setdefault(project, []).append(container)
            else:
                loose.append(container)

        rows: List[Dict[str, Any]] = []
        for project in sorted(groups):
            project_containers = sorted(
                groups[project], key=lambda c: (c.get("compose_service", ""), c.get("name", ""))
            )
            working_dir = ""
            config_file = ""
            for container in project_containers:
                labels = container.get("labels") or {}
                if "com.docker.compose.project.working_dir" in labels:
                    working_dir = labels["com.docker.compose.project.working_dir"]
                if "com.docker.compose.project.config_files" in labels:
                    config_file = labels["com.docker.compose.project.config_files"]
            rows.append({
                "type": "project",
                "project": project,
                "containers": project_containers,
                "working_dir": working_dir,
                "config_file": config_file,
            })
            for container in project_containers:
                rows.append({"type": "container", "project": project, "container": container})
        if loose:
            rows.append({"type": "project", "project": "(standalone)", "containers": loose})
            for container in sorted(loose, key=lambda c: c.get("name", "")):
                rows.append({"type": "container", "project": "(standalone)", "container": container})
        self.compose_rows = rows
        if self.selected_compose_index >= len(self.compose_rows):
            self.selected_compose_index = max(0, len(self.compose_rows) - 1)

    # ------------------------------------------------------------- logs / streaming

    def load_log_lines(self, container_id: Optional[str], viewport_height: int, follow: bool = False) -> None:
        if container_id is None and self.active_project:
            raw_logs = self.client.get_compose_project_logs(self.active_project, tail=self.log_tail_limit)
        else:
            raw_logs = self.client.get_logs(container_id, tail=self.log_tail_limit)
        log_lines = raw_logs.split("\n")
        if self.log_errors_only:
            log_lines = [line for line in log_lines if _log_is_error_line(line)]
            if not log_lines:
                log_lines = [f"{YELLOW}(No error/warning lines in current log window){RESET}"]
        if self.log_filter:
            self.log_lines = [line for line in log_lines if _log_matches_filter(line, self.log_filter)]
            if not self.log_lines:
                self.log_lines = [f"{YELLOW}(No logs match filter '{self.log_filter}'){RESET}"]
        else:
            self.log_lines = log_lines
        if follow or self.log_scroll_index >= max(0, len(self.log_lines) - viewport_height - 1):
            self.log_scroll_index = max(0, len(self.log_lines) - viewport_height)
        self.last_log_refresh = time.time()

    def is_log_streaming(self) -> bool:
        return self.log_streamer is not None and self.log_streamer.is_running()

    def start_log_stream(self, container_id: Optional[str], project_name: Optional[str]) -> None:
        if self.is_log_streaming():
            return
        self.stop_log_stream()

        cmd: List[str] = []
        if self.client.docker_bin:
            cmd.append(self.client.docker_bin)
        if container_id is None and project_name:
            cmd += ["compose", "-p", project_name, "logs", "-f", f"--tail={self.log_tail_limit}"]
        else:
            cmd += ["logs", "-f", f"--tail={self.log_tail_limit}", container_id]

        streamer = LineStreamer(cmd, on_line=self._on_log_line)
        error = streamer.start()
        if error is not None:
            self.set_status(error)
            return
        self.log_streamer = streamer

    def _on_log_line(self, line: str) -> None:
        if self.log_errors_only and not _log_is_error_line(line):
            return
        if self.log_filter and not _log_matches_filter(line, self.log_filter):
            return
        with self.data_lock:
            self.log_lines.append(line)
            if len(self.log_lines) > self.log_tail_limit:
                self.log_lines.pop(0)
            try:
                viewport_h = viewport_height_for(get_terminal_size().height)
            except Exception:
                viewport_h = 18
            self.log_scroll_index = max(0, len(self.log_lines) - viewport_h)
        self.need_redraw = True

    def stop_log_stream(self) -> None:
        if self.log_streamer is not None:
            self.log_streamer.stop()
            self.log_streamer = None

    def jump_to_next_log_match(self, viewport_height: int) -> None:
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

    # ------------------------------------------------------------- top / details / inspect

    def build_details_lines(self, container_id: str) -> List[str]:
        details = self.client.get_container_details(container_id)
        if "error" in details:
            return details["error"].split("\n")
        lines: List[str] = [
            f"Name: {details.get('name', '')}",
            f"ID: {details.get('id', '')}",
            f"Image: {details.get('image', '')}",
            f"Status: {details.get('status', '')}",
            f"Running: {details.get('running', '')}",
            f"Created: {details.get('created', '')}",
            f"Restart policy: {details.get('restart_policy', '') or '(none)'}",
            f"CPU limit: {details.get('cpus') or '(unlimited)'}",
            f"Memory limit: {(details.get('memory_mb') or '(unlimited)') + (' MB' if details.get('memory_mb') else '')}",
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
        lines.append("IP Details:")
        lines.extend(f"  {line}" for line in details.get("ip_details", "").split("\n"))
        lines.append("")
        lines.append("Environment:")
        lines.extend(f"  {line}" for line in details.get("env", "").split("\n"))
        lines.append("")
        lines.append("Labels:")
        lines.extend(f"  {line}" for line in details.get("labels", "").split("\n"))
        return lines

    # ------------------------------------------------------------- exec

    def prompt_exec_command(self, container_name: str) -> str:
        print(f"\r\033[K{YELLOW}{BOLD}Command inside {container_name}:{RESET}", flush=True)
        options = list(self.config.exec_presets)
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

    def record_exec_command(self, command: str) -> None:
        if command in self.exec_history:
            self.exec_history.remove(command)
        self.exec_history.insert(0, command)
        self.exec_history = self.exec_history[: self.config.exec_history_cap]

    def start_exec_input(self, container: Dict[str, str]) -> None:
        prompt = f"Command inside {container['name']} (type to search history, or custom): "

        def submit(value: str) -> None:
            command = value
            matches = [cmd for cmd in self.exec_history if value.lower() in cmd.lower()]
            if matches and value == matches[0][:len(value)]:
                command = matches[0]
            if not command:
                self.set_status("Command canceled.")
                return
            self.active_container = container
            self.exec_command_text = command
            self.record_exec_command(command)
            self.config.save()
            self.set_status(f"Running command: {command}...")
            output = self.client.exec_command(container["id"], command)
            self.exec_output_lines = output.split("\\n")
            self.exec_scroll_index = 0
            self.view_mode = ViewMode.EXEC

        self.start_input(prompt, submit)

    # ------------------------------------------------------------- refresh data

    def refresh_data(self) -> None:
        self.refresh_in_progress = True
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
        elif self.current_tab == "images":
            images = self.client.list_images()
            filter_val = (self.filters.get("images") or "").lower()
            if filter_val:
                images = [img for img in images if filter_val in img["repository"].lower()
                          or filter_val in img["tag"].lower() or filter_val in img["id"].lower()]
            with self.data_lock:
                self.current_context = current_context
                self.images = images
                if self.selected_image_index >= len(self.images):
                    self.selected_image_index = max(0, len(self.images) - 1)
        elif self.current_tab == "volumes":
            volumes = self.client.list_volumes()
            filter_val = (self.filters.get("volumes") or "").lower()
            if filter_val:
                volumes = [v for v in volumes if filter_val in v["name"].lower() or filter_val in v["driver"].lower()]
            with self.data_lock:
                self.current_context = current_context
                self.volumes = volumes
                if self.selected_volume_index >= len(self.volumes):
                    self.selected_volume_index = max(0, len(self.volumes) - 1)
        elif self.current_tab == "networks":
            networks = self.client.list_networks()
            filter_val = (self.filters.get("networks") or "").lower()
            if filter_val:
                networks = [n for n in networks if filter_val in n["name"].lower() or filter_val in n["driver"].lower() or filter_val in n["id"].lower()]
            with self.data_lock:
                self.current_context = current_context
                self.networks = networks
                if self.selected_network_index >= len(self.networks):
                    self.selected_network_index = max(0, len(self.networks) - 1)
        elif self.current_tab == "contexts":
            contexts = self.client.list_contexts()
            filter_val = (self.filters.get("contexts") or "").lower()
            if filter_val:
                contexts = [ctx for ctx in contexts if filter_val in ctx["name"].lower()
                            or filter_val in ctx["endpoint"].lower() or filter_val in ctx["description"].lower()]
            with self.data_lock:
                self.current_context = current_context
                self.contexts = contexts
                if self.selected_context_index >= len(self.contexts):
                    self.selected_context_index = max(0, len(self.contexts) - 1)
        with self.data_lock:
            self.last_refresh = time.time()
            self.refresh_in_progress = False
            self.need_redraw = True

    # ------------------------------------------------------------- main view

    def draw_main_view(self) -> None:
        size = get_terminal_size()
        width = size.width

        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        if self.client.docker_host:
            parsed = self.client.parse_docker_host()
            host_display = parsed["display"] if parsed else self.client.docker_host
            context_text = f" [{self.current_context} ({host_display})]" if self.current_context else f" [{host_display}]"
        else:
            context_text = f" [{self.current_context}]" if self.current_context else ""
        title_text = f"DockTUI Container Dashboard{context_text}"
        draw_frame(title_text, width)

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

        self._draw_tab_header(width)
        if self.current_tab == "containers":
            self._draw_containers_tab(width)
        elif self.current_tab == "compose":
            self._draw_compose_tab(width)
        elif self.current_tab == "images":
            self._draw_images_tab(width)
        elif self.current_tab == "volumes":
            self._draw_volumes_tab(width)
        elif self.current_tab == "networks":
            self._draw_networks_tab(width)
        elif self.current_tab == "contexts":
            self._draw_contexts_tab(width)

        draw_status_bar(self.status_message, width)
        self._draw_main_footer()

    def _draw_tab_header(self, width: int) -> None:
        tab_labels = {
            "containers": "Containers",
            "compose": "Compose",
            "images": "Images",
            "volumes": "Volumes",
            "networks": "Networks",
            "contexts": "Contexts",
        }
        header_parts: List[str] = []
        for idx, tab in enumerate(self.tabs, start=1):
            label = f"{tab_labels[tab]} ({idx})"
            header_parts.append(f"{WHITE_ON_BLUE} {label} {RESET}" if tab == self.current_tab else f"[{label}]")
        filter_bits: List[str] = []
        active_filter = self.filters.get(self.current_tab, "")
        if active_filter:
            filter_bits.append(f"filter: {active_filter}")
        if self.current_tab in ("containers", "compose"):
            if self.state_filter != StateFilter.ALL.value:
                filter_bits.append(f"state: {self.state_filter}")
            if self.sort_mode != "default":
                filter_bits.append(f"sort: {self.sort_mode}")
        filter_status = "    [" + " | ".join(filter_bits) + "]" if filter_bits else ""
        print("   ".join(header_parts) + filter_status)
        print("─" * (width - 1))

    def _draw_containers_tab(self, width: int) -> None:
        if not self.containers:
            if self.container_filter:
                print(f"\n{CYAN}No containers match the active filter: '{self.container_filter}'{RESET}")
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("containers", width)
            return
        rem = width - 26
        name_w = max(15, int(rem * 0.30))
        image_w = max(15, int(rem * 0.30))
        status_w = max(15, rem - name_w - image_w)

        header_line = f"{BOLD}{'ID':<12} {truncate('NAME', name_w)} {truncate('IMAGE', image_w)} {'STATE':<10} {truncate('STATUS', status_w)}{RESET}"
        print(header_line)
        print("─" * (width - 1))
        for idx, c in enumerate(self.containers):
            style = WHITE_ON_BLUE if idx == self.selected_index else ""
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

        sel = self.containers[self.selected_index]
        c_id = sel["id"]
        print(f"\n{CYAN}{BOLD}CONTAINER RESOURCE USAGE:{RESET}")
        c_stats = self.stats.get(c_id) or self.stats.get(sel["name"])
        if c_stats and sel["state"] == "running":
            cpu_bar, cpu_high = self._percentage_bar(c_stats['cpu'], width=int(width * 0.2))
            mem_bar, mem_high = self._percentage_bar(c_stats['mem_perc'], width=int(width * 0.2))
            cpu_color = RED if cpu_high else GREEN
            mem_color = RED if mem_high else GREEN
            cpu_alert = f" {RED}{BOLD}[HIGH CPU]{RESET}" if cpu_high else ""
            mem_alert = f" {RED}{BOLD}[HIGH MEMORY]{RESET}" if mem_high else ""
            print(f"  CPU:  {cpu_color}{cpu_bar}{RESET}{cpu_alert}")
            print(f"  MEM:  {mem_color}{mem_bar} ({c_stats['memory']}){RESET}{mem_alert}")
            print(f"  NET:  {GREEN}{c_stats['net']}{RESET}")
        else:
            status_text = "N/A (container stopped)" if sel["state"] != "running" else "Loading stats..."
            print(f"  Usage statistics: {YELLOW}{status_text}{RESET}")

    def _draw_compose_tab(self, width: int) -> None:
        if not self.compose_rows:
            self.draw_empty_state("compose", width)
            return
        service_w = max(18, int(width * 0.25))
        name_w = max(18, int(width * 0.25))
        image_w = max(20, int(width * 0.25))
        print(f"{BOLD}{truncate('PROJECT / SERVICE', service_w)} {truncate('CONTAINER', name_w)} {'STATE':<10} {truncate('IMAGE', image_w)}{RESET}")
        print("─" * (width - 1))
        for idx, row in enumerate(self.compose_rows):
            style = WHITE_ON_BLUE if idx == self.selected_compose_index else ""
            if row["type"] == "project":
                project = str(row["project"])
                count = len(row["containers"])  # type: ignore[arg-type]
                print(f"{style}{BOLD}{truncate(project + '  (' + str(count) + ')', service_w)} {truncate('', name_w)} {'':<10} {truncate('', image_w)}{RESET}")
            else:
                container = row["container"]  # type: ignore[assignment]
                service = container.get("compose_service") or "(standalone)"
                state = container.get("state", "")
                marker = "» " if idx == self.selected_compose_index else "  "
                print(
                    f"{style}{truncate(marker + service, service_w)} "
                    f"{truncate(container.get('name', ''), name_w)} "
                    f"{state:<10} {truncate(container.get('image', ''), image_w)}{RESET}"
                )

    def _draw_images_tab(self, width: int) -> None:
        if not self.images:
            active_filter = self.filters.get("images")
            if active_filter:
                print(f"\n{CYAN}No images match the active filter: '{active_filter}'{RESET}")
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("images", width)
            return
        rem = width - 26
        repo_w = max(20, int(rem * 0.45))
        tag_w = max(12, int(rem * 0.25))
        size_w = max(10, rem - repo_w - tag_w)
        header_line = f"{BOLD}{'IMAGE ID':<12} {truncate('REPOSITORY', repo_w)} {truncate('TAG', tag_w)} {truncate('SIZE', size_w)}{RESET}"
        print(header_line)
        print("─" * (width - 1))
        for idx, img in enumerate(self.images):
            style = WHITE_ON_BLUE if idx == self.selected_image_index else ""
            repo_str = f"» {img['repository']}" if idx == self.selected_image_index else f"  {img['repository']}"
            line = f"{style}{img['id'][:10]:<12} {truncate(repo_str, repo_w)} {truncate(img['tag'], tag_w)} {truncate(img['size'], size_w)}{RESET}"
            print(line)
        print("─" * (width - 1))

    def _draw_volumes_tab(self, width: int) -> None:
        if not self.volumes:
            active_filter = self.filters.get("volumes")
            if active_filter:
                print(f"\n{CYAN}No volumes match the active filter: '{active_filter}'{RESET}")
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("volumes", width)
            return
        name_w = max(30, int(width * 0.50))
        driver_w = max(12, int(width * 0.20))
        print(f"{BOLD}{truncate('VOLUME', name_w)} {truncate('DRIVER', driver_w)} {'SCOPE':<12}{RESET}")
        print("─" * (width - 1))
        for idx, volume in enumerate(self.volumes):
            style = WHITE_ON_BLUE if idx == self.selected_volume_index else ""
            marker = "» " if idx == self.selected_volume_index else "  "
            print(f"{style}{truncate(marker + volume['name'], name_w)} {truncate(volume['driver'], driver_w)} {volume['scope']:<12}{RESET}")
        print("─" * (width - 1))

    def _draw_networks_tab(self, width: int) -> None:
        if not self.networks:
            active_filter = self.filters.get("networks")
            if active_filter:
                print(f"\n{CYAN}No networks match the active filter: '{active_filter}'{RESET}")
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("networks", width)
            return
        name_w = max(30, int(width * 0.45))
        driver_w = max(12, int(width * 0.20))
        print(f"{BOLD}{'ID':<12} {truncate('NETWORK', name_w)} {truncate('DRIVER', driver_w)} {'SCOPE':<12}{RESET}")
        print("─" * (width - 1))
        for idx, network in enumerate(self.networks):
            style = WHITE_ON_BLUE if idx == self.selected_network_index else ""
            marker = "» " if idx == self.selected_network_index else "  "
            print(f"{style}{network['id'][:10]:<12} {truncate(marker + network['name'], name_w)} {truncate(network['driver'], driver_w)} {network['scope']:<12}{RESET}")
        print("─" * (width - 1))

    def _draw_contexts_tab(self, width: int) -> None:
        if self.client.docker_host:
            print(f"{YELLOW}{BOLD}Note: DOCKER_HOST is active. Context switching is bypassed (DOCKER_HOST overrides context).{RESET}")
            print("─" * (width - 1))
        if not self.contexts:
            active_filter = self.filters.get("contexts")
            if active_filter:
                print(f"\n{CYAN}No contexts match the active filter: '{active_filter}'{RESET}")
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("contexts", width)
            return
        name_w = max(20, int(width * 0.25))
        desc_w = max(24, int(width * 0.30))
        endpoint_w = max(24, width - name_w - desc_w - 14)
        print(f"{BOLD}{truncate('CONTEXT', name_w)} {'CUR':<5} {truncate('DESCRIPTION', desc_w)} {truncate('ENDPOINT', endpoint_w)}{RESET}")
        print("─" * (width - 1))
        for idx, context in enumerate(self.contexts):
            style = WHITE_ON_BLUE if idx == self.selected_context_index else ""
            marker = "» " if idx == self.selected_context_index else "  "
            print(
                f"{style}{truncate(marker + context['name'], name_w)} "
                f"{context['current']:<5} {truncate(context['description'], desc_w)} "
                f"{truncate(context['endpoint'], endpoint_w)}{RESET}"
            )
        print("─" * (width - 1))

    def _draw_main_footer(self) -> None:
        if self.current_tab == "compose":
            row = self.compose_rows[self.selected_compose_index] if self.compose_rows else None
            if row and row.get("type") == "project":
                print(f"{CYAN}[U] Up | [D] Down | [B] Build | [R] Restart | [L] Project Logs | [Tab] Switch | [?] Help | [Q] Quit{RESET}")
            else:
                print(f"{CYAN}[S] Start/Stop | [R] Restart | [L] Logs | [V] Details | [I] Inspect | [E] Exec | [X] Compose | [W] Resources | [O] Sort | [Y] State | [Shift+F] Files | [Shift+S] Settings | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "containers":
            print(f"{CYAN}[S] Start/Stop | [R] Restart | [L] Logs | [V] Details | [I] Inspect | [E] Exec | [X] Compose | [W] Resources | [C] Clone | [O] Sort | [Y] State | [Shift+S] Settings | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "images":
            print(f"{CYAN}[D] Delete | [F] Search & Pull | [P] Disk/Prune | [Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "volumes":
            print(f"{CYAN}[D] Delete | [F] Browse Files | [P] Disk/Prune | [Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "networks":
            print(f"{CYAN}[D] Delete | [Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit{RESET}")
        elif self.current_tab == "contexts":
            print(f"{CYAN}[U] Use | [N] New Endpoint | [Shift+S] Settings | [Tab] Switch | [G] Refresh | [?] Help | [Q] Quit{RESET}")
        else:
            print(f"{CYAN}[Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit{RESET}")

    # ------------------------------------------------------------- empty state

    def draw_empty_state(self, tab_name: str, width: int) -> None:
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
            ],
        }
        content = tips.get(tab_name, ["Nothing to display."])
        print("\n")
        print(margin + f"{CYAN}┌" + "─" * (box_w - 2) + f"┐{RESET}")
        for line in content:
            from .styles import strip_ansi
            visible_len = len(strip_ansi(line))
            pad_r = max(0, box_w - 4 - visible_len)
            print(margin + f"{CYAN}│{RESET}  {line}" + " " * pad_r + f" {CYAN}│{RESET}")
        print(margin + f"{CYAN}└" + "─" * (box_w - 2) + f"┘{RESET}")
        print("\n")

    # ------------------------------------------------------------- logs view

    def draw_logs_view(self) -> None:
        if self.active_project:
            log_title = f"PROJECT LOGS: {self.active_project}"
            target_id: Optional[str] = None
        else:
            sel = self.active_container or (self.containers[self.selected_index] if self.containers else None)
            if not sel:
                self.view_mode = ViewMode.MAIN
                return
            log_title = f"LOGS: {sel['name']}"
            target_id = sel["id"]

        size = get_terminal_size()
        width, height = size.width, size.height
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        viewport_height = self.get_viewport_height(height)

        if not self.log_lines:
            self.load_log_lines(target_id, viewport_height, follow=self.log_follow)
            if self.log_follow:
                self.start_log_stream(target_id, self.active_project)
        elif self.log_follow and not self.is_log_streaming():
            self.start_log_stream(target_id, self.active_project)
        elif not self.log_follow and self.is_log_streaming():
            self.stop_log_stream()

        filter_status = f" [FILTER: {self.log_filter}]" if self.log_filter else ""
        search_status = f" [SEARCH: {self.log_search}]" if self.log_search else ""
        error_status = " [ERRORS]" if self.log_errors_only else ""
        limit_status = f" [LIMIT: {self.log_tail_limit} lines]"
        follow_status = " [FOLLOW]" if self.log_follow else ""
        title_text = f"{log_title}{filter_status}{search_status}{error_status}{limit_status}{follow_status} (Line {self.log_scroll_index + 1} of {len(self.log_lines)})"
        draw_frame(title_text, width)

        visible, start, end = slice_viewport(self.log_lines, self.log_scroll_index, viewport_height)
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), viewport_height)
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[Up/Down] Scroll | [F] Follow | [Space] Pause | [/] Search | [N] Next | [E] Errors | [H] Highlights | [O] Export | [+/-] Limit | [Esc/L] Back{RESET}")

    # ------------------------------------------------------------- inspect / details / top

    def _draw_scrollable_text_view(
        self,
        title: str,
        lines: List[str],
        scroll_index_attr: str,
        back_keys: str,
    ) -> None:
        if not lines:
            self.view_mode = ViewMode.MAIN
            return
        size = get_terminal_size()
        width, height = size.width, size.height
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        scroll_index = getattr(self, scroll_index_attr)
        title_text = f"{title} (Line {scroll_index + 1} of {len(lines)})"
        draw_frame(title_text, width)
        viewport_height = self.get_viewport_height(height)
        visible, _, _ = slice_viewport(lines, scroll_index, viewport_height)
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), viewport_height)
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[Up/Down] Scroll | [O] Export | [Esc/{back_keys}] Back{RESET}")

    def draw_inspect_view(self) -> None:
        if not self.containers:
            self.view_mode = ViewMode.MAIN
            return
        self._draw_scrollable_text_view(
            f"INSPECT: {(self.active_container or self.containers[self.selected_index])['name']}",
            self.inspect_lines,
            "inspect_scroll_index",
            "I",
        )

    def draw_details_view(self) -> None:
        self._draw_scrollable_text_view(
            "CONTAINER DETAILS",
            self.details_lines,
            "details_scroll_index",
            "V",
        )

    def draw_top_view(self) -> None:
        self._draw_scrollable_text_view(
            "CONTAINER PROCESSES",
            self.top_lines,
            "top_scroll_index",
            "T",
        )

    def draw_compose_snippet_view(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            self.view_mode = ViewMode.MAIN
            return
        if not self.compose_snippet_lines:
            self.compose_snippet_lines = self.client.generate_compose_snippet(sel["id"]).split("\n")
            self.compose_snippet_scroll_index = 0
        self._draw_scrollable_text_view(
            f"GENERATE COMPOSE SNIPPET: {sel['name']}",
            self.compose_snippet_lines,
            "compose_snippet_scroll_index",
            "X",
        )

    def draw_exec_view(self) -> None:
        if not self.containers:
            self.view_mode = ViewMode.MAIN
            return
        sel = self.active_container or self.containers[self.selected_index]
        size = get_terminal_size()
        width, height = size.width, size.height
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        title_text = f"EXEC OUT: {sel['name']} > {self.exec_command_text[:30]} (Line {self.exec_scroll_index + 1} of {len(self.exec_output_lines)})"
        draw_frame(title_text, width)
        viewport_height = self.get_viewport_height(height)
        visible, _, _ = slice_viewport(self.exec_output_lines, self.exec_scroll_index, viewport_height)
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), viewport_height)
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[Up/Down] Scroll | [R] Run command again | [E] Run different command | [Esc] Back{RESET}")

    def draw_system_view(self) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("DOCKER SYSTEM DISK USAGE & CLEANUP", width)
        if not self.system_info_text:
            self.system_info_text = self.client.get_disk_usage()
        print(self.system_info_text)
        print(f"\n{YELLOW}Preview:{RESET} Docker does not provide a dry-run for prune; review the disk usage above before confirming.")
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[X] System prune | [I] Image prune | [V] Volume prune | [A] System prune + volumes | [Esc/P] Back{RESET}")

    def draw_input_view(self) -> None:
        previous = self.previous_view_mode
        self._dispatch_view(previous)
        print(f"\\n{YELLOW}{BOLD}{self.input_dialog.prompt}{RESET}{self.input_dialog.buffer}", end="", flush=True)
        if "type to search history" in self.input_dialog.prompt:
            matches = [cmd for cmd in self.exec_history if self.input_dialog.buffer.lower() in cmd.lower()]
            if matches:
                print(f"\\n{CYAN}Matches: {', '.join(matches[:5])}{RESET}", end="", flush=True)

    def draw_help_view(self) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("DockTUI Help", width)
        print(f"{BOLD}Global{RESET}")
        print("  Tab / 1-6    Switch tabs")
        print("  Up / Down    Move selection or scroll / Mouse scroll support")
        print("  G            Refresh current data")
        print("  M            Cycle theme color presets (Dark, Light, High-Contrast)")
        print("  Shift+S      Open the Settings editor")
        print("  ?            Open or close this help screen")
        print("  Q / Esc      Quit or return to the previous screen")
        print(f"\n{BOLD}Containers / Compose{RESET}")
        print("  S            Start or stop the selected container / project")
        print("  R            Restart the selected container / project")
        print("  L            Open container or project logs")
        print("  I            Inspect container JSON")
        print("  E            Execute a command (interactively or in background)")
        print("  V            Open readable container details")
        print("  T            View container processes (docker top)")
        print("  X            Generate a docker-compose.yml snippet")
        print("  C (Shift)    Clone the selected container")
        print("  W            Edit live CPU / memory limits (docker update)")
        print("  Shift+F      Browse volume files (on the Volumes tab)")
        print("  O / Y        Cycle sorting and state filters")
        print("  / / C        Apply or clear the tab filter")
        print("  U / D / B    Compose up / down / build on the Compose tab")
        print("  U            Use the selected Docker context")
        print("  N            Create a new endpoint on the Contexts tab")
        print(f"\n{BOLD}Images and cleanup{RESET}")
        print("  D            Delete the selected image / volume / network")
        print("  F            Search & pull a Docker Hub image (on the Images tab)")
        print("  P            Open Docker disk usage and prune view")
        print("  X / I / V / A    Run system, image, volume, or full prune")
        print(f"\n{BOLD}Logs{RESET}")
        print("  F            Toggle follow mode")
        print("  Space        Pause follow mode")
        print("  N            Jump to next search match")
        print("  E            Toggle error/warning-only lines")
        print("  H            Toggle log highlighting / regex")
        print("  + / -        Increase or decrease log tail limit")
        print("  / / C        Apply or clear log filter")
        print("  O            Export logs to a local file")
        print("  G            Refresh logs now")
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[? / Esc / Q] Return to previous screen{RESET}")

    def draw_settings_view(self) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("DOCKTUI SETTINGS", width)
        print(f"{BOLD}Edit the active configuration. Press Enter to edit the highlighted entry.{RESET}")
        print("─" * (width - 1))
        if not self.settings_options:
            self._build_settings_options()
        for idx, option in enumerate(self.settings_options):
            marker = "» " if idx == self.settings_index else "  "
            style = WHITE_ON_BLUE if idx == self.settings_index else ""
            label = option["label"]
            value = option["display"]()
            print(f"{style}{marker}{label:<28} {value}{RESET}")
        print("─" * (width - 1))
        print(f"\n{CYAN}[Up/Down] Move | [Enter] Edit | [S] Save & Apply | [Esc] Back{RESET}")

    def draw_search_view(self) -> None:
        """Show a simple registry search results picker."""
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("REGISTRY SEARCH", width)
        if not self.search_results:
            print(f"{YELLOW}No search results. Use the dialog to enter a query.{RESET}")
        else:
            for idx, result in enumerate(self.search_results):
                marker = "» " if idx == self.search_index else "  "
                style = WHITE_ON_BLUE if idx == self.search_index else ""
                print(f"{style}{marker}{result['name']:<40} {truncate(result.get('description', ''), width - 50)}{RESET}")
        print("─" * (width - 1))
        print(f"\n{CYAN}[Up/Down] Move | [Enter] Pull | [Esc] Back{RESET}")

    def draw_pull_progress_view(self) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        title = f"PULLING: {self.pull_image_name}"
        draw_frame(title, width)
        visible, _, _ = slice_viewport(self.pull_lines, self.pull_scroll_index, max(1, size.height - 6))
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), max(1, size.height - 6))
        print("\n" + "═" * (width - 1))
        print(f"{CYAN}[Esc] Cancel & back{RESET}")

    def draw_files_view(self) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        title = f"VOLUME FILES: {self.file_volume_name}  [{self.file_path}]"
        draw_frame(title, width)
        if not self.file_entries:
            print(f"{YELLOW}(empty volume or unreadable){RESET}")
        else:
            for idx, entry in enumerate(self.file_entries):
                marker = "» " if idx == self.file_index else "  "
                style = WHITE_ON_BLUE if idx == self.file_index else ""
                kind = "DIR" if entry.get("mode", "").startswith("d") else "FILE"
                print(f"{style}{marker}{kind:<5} {entry.get('name', '')}{RESET}")
        print("─" * (width - 1))
        print(f"\n{CYAN}[Up/Down] Move | [Enter] Open directory | [Backspace] Up | [Esc] Back{RESET}")

    # ------------------------------------------------------------- settings

    def _build_settings_options(self) -> None:
        def float_str(value: float) -> str:
            return f"{value:g}"

        self.settings_options = [
            {
                "label": "Refresh interval (s)",
                "key": "refresh_interval",
                "kind": "float",
                "display": lambda: float_str(self.config.refresh_interval),
            },
            {
                "label": "Docker timeout (s)",
                "key": "docker_timeout",
                "kind": "float",
                "display": lambda: float_str(self.config.docker_timeout),
            },
            {
                "label": "Theme",
                "key": "theme",
                "kind": "enum:dark,light,high_contrast",
                "display": lambda: self.config.theme,
            },
            {
                "label": "Log tail limit",
                "key": "log_tail_limit",
                "kind": "int",
                "display": lambda: str(self.config.log_tail_limit),
            },
            {
                "label": "Log tail step",
                "key": "log_tail_step",
                "kind": "int",
                "display": lambda: str(self.config.log_tail_step),
            },
            {
                "label": "CPU alert threshold (%)",
                "key": "cpu_alert_threshold",
                "kind": "float",
                "display": lambda: float_str(self.config.cpu_alert_threshold),
            },
            {
                "label": "Exec history cap",
                "key": "exec_history_cap",
                "kind": "int",
                "display": lambda: str(self.config.exec_history_cap),
            },
            {
                "label": "Exec presets",
                "key": "exec_presets",
                "kind": "list",
                "display": lambda: ", ".join(self.config.exec_presets) or "(none)",
            },
            {
                "label": "Log highlights",
                "key": "log_highlights",
                "kind": "list",
                "display": lambda: ", ".join(h.get("label", "?") for h in self.config.log_highlights) or "(none)",
            },
        ]

    def _start_settings_edit(self) -> None:
        if not self.settings_options:
            self._build_settings_options()
        option = self.settings_options[self.settings_index]
        key = option["key"]
        kind = option["kind"]
        if kind == "list":
            current = "\n".join(
                item.get("value", "") if isinstance(item, dict) else str(item)
                for item in (self.config.exec_presets if key == "exec_presets" else self.config.log_highlights)
            )
        else:
            current = str(getattr(self.config, key))

        def submit(value: str) -> None:
            try:
                if kind == "float":
                    setattr(self.config, key, float(value))
                elif kind == "int":
                    setattr(self.config, key, int(value))
                elif kind.startswith("enum:"):
                    setattr(self.config, key, value.strip())
                elif kind == "list":
                    if key == "exec_presets":
                        self.config.exec_presets = [line.strip() for line in value.splitlines() if line.strip()]
                    elif key == "log_highlights":
                        self.config.log_highlights = []
                        for line in value.splitlines():
                            if not line.strip():
                                continue
                            label, pattern = (line.split("=", 1) + [""])[:2]
                            self.config.log_highlights.append({
                                "label": label.strip(),
                                "pattern": pattern.strip(),
                            })
                        self.config.save()
            except ValueError as e:
                self.set_status(f"Invalid value: {e}")
                return
            self.config.validate()
            self._apply_runtime_config()
            self.set_status(f"Updated {key}.")

        self.start_input(f"New value for {option['label']} [{kind}]: ", submit, initial=current)

    def _apply_runtime_config(self) -> None:
        """Sync runtime fields with the (possibly edited) config."""
        self.refresh_interval = self.config.refresh_interval
        self.client.timeout = self.config.docker_timeout
        self.log_tail_limit = max(self.config.log_min, min(self.config.log_tail_limit, self.config.log_max))
        self.theme = self.config.theme
        apply_theme_colors(self.theme)

    def save_settings(self) -> None:
        try:
            path = self.config.save()
            self.set_status(f"Configuration saved to {path}.")
        except Exception as e:
            self.set_status(f"Save failed: {e}")

    # ------------------------------------------------------------- search & pull

    def start_registry_search(self) -> None:
        def submit(query: str) -> None:
            if not query:
                return
            results = self.client.search_images(query)
            self.search_results = results
            self.search_index = 0
            self.view_mode = ViewMode.SEARCH

        self.start_input("Search Docker Hub: ", submit)

    def _pull_selected_image(self) -> None:
        if not self.search_results:
            return
        entry = self.search_results[self.search_index]
        repo = entry["name"]
        self.pull_image_name = repo
        self.pull_lines = []
        self.pull_scroll_index = 0
        self.view_mode = ViewMode.PULL_PROGRESS

        def on_line(line: str) -> None:
            self.pull_lines.append(line)
            self.need_redraw = True

        def on_stop() -> None:
            self.set_status(f"Pull of {repo} finished.")
            self.refresh_data()

        streamer = LineStreamer(
            self.client.pull_image_args(repo),
            on_line=on_line,
            on_stop=on_stop,
        )
        err = streamer.start()
        if err is not None:
            self.pull_lines.append(err)
            self.set_status(err)
            return
        self.pull_streamer = streamer

    def cancel_pull(self) -> None:
        if self.pull_streamer is not None:
            self.pull_streamer.stop()
            self.pull_streamer = None
        self.set_status("Pull canceled.")
        self.view_mode = ViewMode.MAIN

    # ------------------------------------------------------------- volume files

    def open_volume_files(self) -> None:
        if not self.volumes:
            self.set_status("No volumes to browse.")
            return
        volume = self.volumes[self.selected_volume_index]
        self.file_volume_name = volume["name"]
        self.file_path = "/"
        self._load_file_entries()
        self.view_mode = ViewMode.FILES

    def _load_file_entries(self) -> None:
        self.file_entries = self.client.list_volume_contents(self.file_volume_name, path=self.file_path)
        # Filter the current-directory markers.
        self.file_entries = [e for e in self.file_entries if e.get("name") not in (".", "..")]
        self.file_index = 0

    def _file_open(self) -> None:
        if not self.file_entries:
            return
        entry = self.file_entries[self.file_index]
        if entry.get("mode", "").startswith("d"):
            self.file_path = (self.file_path.rstrip("/") + "/" + entry["name"]) or "/"
            self._load_file_entries()
        else:
            self.set_status(f"Selected file: {entry['name']} (read-only browsing).")

    def _file_up(self) -> None:
        if self.file_path in ("", "/"):
            return
        parts = self.file_path.rstrip("/").split("/")
        parts = parts[:-1]
        self.file_path = "/".join(parts) or "/"
        self._load_file_entries()

    # ------------------------------------------------------------- resource limits

    def start_resource_edit(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        details = self.client.get_container_details(sel["id"])
        current_cpus = details.get("cpus") or ""
        current_mem = details.get("memory_mb") or ""

        def submit(value: str) -> None:
            cpus = None
            memory = None
            for line in value.splitlines():
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip().lower()
                v = v.strip()
                if not v:
                    continue
                try:
                    if k in ("cpus", "cpu"):
                        cpus = float(v)
                    elif k in ("memory", "memory_mb", "mem"):
                        memory = int(float(v) * (1024 * 1024))
                except ValueError:
                    self.set_status(f"Invalid number: {v}")
                    return
            success, msg = self.client.update_container_resources(sel["id"], cpus=cpus, memory_bytes=memory)
            self.set_status(msg if success else f"Update failed: {msg}")

        initial = f"cpus={current_cpus}\nmemory_mb={current_mem}"
        self.start_input(
            "Set cpus and memory_mb (one per line):",
            submit,
            initial=initial,
        )

    # ------------------------------------------------------------- container clone

    def start_container_clone(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        details = self.client.get_container_details(sel["id"])

        def submit(value: str) -> None:
            new_name = value.strip() or f"{sel['name']}-copy"
            ports = details.get("ports", "")
            port_bindings = [line.split(" -> ")[0] for line in ports.splitlines() if "->" in line]
            success, msg = self.client.clone_container(
                source_id=sel["id"],
                new_name=new_name,
                image=details.get("image", ""),
                port_bindings=port_bindings or None,
            )
            self.set_status(msg if success else f"Clone failed: {msg}")
            self.refresh_data()

        self.start_input(f"New name for clone of {sel['name']}: ", submit, initial=f"{sel['name']}-copy")

    # ------------------------------------------------------------- endpoints

    def new_endpoint_prompt(self) -> None:
        def submit(value: str) -> None:
            parts = [p.strip() for p in value.split("|")]
            if len(parts) < 2:
                self.set_status("Format: <name>|<host>|[description]")
                return
            name, host = parts[0], parts[1]
            description = parts[2] if len(parts) > 2 else ""
            self.endpoints.append({"name": name, "host": host, "description": description})
            self.config.endpoints = list(self.endpoints)
            self.set_status(f"Added endpoint {name} -> {host}.")
            try:
                self.config.save()
            except Exception:
                pass

        self.start_input("New endpoint: name|host|description (description optional): ", submit)

    def use_selected_context(self) -> None:
        if self.client.docker_host:
            self.set_status("Cannot switch context: DOCKER_HOST is active and overrides context.")
            return
        if self.current_tab == "contexts" and self.contexts:
            sel_ctx = self.contexts[self.selected_context_index]
            self.set_status(f"Switching Docker context to {sel_ctx['name']}...")
            success, msg = self.client.use_context(sel_ctx["name"])
            self.set_status(msg)
            self.refresh_data()
            return
        if self.endpoints:
            entry = self.endpoints[self.selected_endpoint_index] if hasattr(self, "selected_endpoint_index") else self.endpoints[0]
            self._activate_endpoint(entry)

    def _activate_endpoint(self, endpoint: Dict[str, str]) -> None:
        host = endpoint.get("host")
        if not host:
            self.set_status("Endpoint has no host.")
            return
        self.client.set_host(host)
        self.active_endpoint = endpoint.get("name")
        self.config.active_endpoint = self.active_endpoint
        self.set_status(f"Switched to endpoint {endpoint.get('name', '?')} ({host}).")
        self.refresh_data()

    # ------------------------------------------------------------- modal helpers

    def _start_filter_prompt(self, _key: str) -> None:
        prompts = {
            "containers": "Filter containers (name/image): ",
            "compose": "Filter compose (project/service): ",
            "images": "Filter images (repo/tag/id): ",
            "volumes": "Filter volumes (name/driver): ",
            "networks": "Filter networks (name/driver): ",
            "contexts": "Filter contexts (name/endpoint): ",
        }
        prompt = prompts.get(self.current_tab, "Filter: ")

        def submit(value: str) -> None:
            self.filters[self.current_tab] = value
            for attr in (
                "selected_index",
                "selected_compose_index",
                "selected_image_index",
                "selected_volume_index",
                "selected_network_index",
                "selected_context_index",
            ):
                setattr(self, attr, 0)
            self.set_status(f"Filter set to: '{value}'")
            self.refresh_data()

        self.start_input(prompt, submit, initial=self.filters.get(self.current_tab, ""))

    def _clear_filter(self, _key: str) -> None:
        self.filters[self.current_tab] = ""
        for attr in (
            "selected_index",
            "selected_compose_index",
            "selected_image_index",
            "selected_volume_index",
            "selected_network_index",
            "selected_context_index",
        ):
            setattr(self, attr, 0)
        self.set_status(f"Cleared {self.current_tab} filter.")
        self.refresh_data()

    def open_help(self) -> None:
        if self.view_mode != ViewMode.HELP:
            self.previous_view_mode = self.view_mode
        self.view_mode = ViewMode.HELP
        self.need_redraw = True

    def close_help(self) -> None:
        self.view_mode = self.previous_view_mode or ViewMode.MAIN
        self.need_redraw = True

    # ------------------------------------------------------------- compose actions

    def _run_compose_action(self, action: str) -> None:
        if not self.compose_rows:
            return
        row = self.compose_rows[self.selected_compose_index]
        if not row or row.get("type") != "project":
            return
        project = row.get("project", "")
        config_file = row.get("config_file", "")
        if action == ComposeAction.UP.value and not self.compose_rows:
            return
        success, msg = self.client.run_compose_cmd(project, config_file, action)
        self.set_status(msg if success else f"Compose {action} failed: {msg}")
        self.refresh_data()

    # ------------------------------------------------------------- mouse / drawing helpers

    def enable_mouse_tracking(self) -> None:
        print("\033[?1000h", end="", flush=True)

    def disable_mouse_tracking(self) -> None:
        print("\033[?1000l", end="", flush=True)

    def _percentage_bar(self, percentage_str: str, width: int = 15) -> Tuple[str, bool]:
        try:
            val = float(percentage_str.replace("%", "").strip())
            val = max(0.0, min(100.0, val))
            filled_len = int(round(width * val / 100.0))
            bar = "█" * filled_len + "░" * (width - filled_len)
            is_high = val >= self.config.cpu_alert_threshold
            return f"[{bar}] {percentage_str}", is_high
        except Exception:
            return f"[░░░░░░░░░░░░░░░] {percentage_str}", False

    # ------------------------------------------------------------- view dispatch

    def get_viewport_height(self, height: int) -> int:
        h = viewport_height_for(height)
        if getattr(self, "_split_screen_mode", False):
            return max(5, (h // 2) - 1)
        return h

    def _dispatch_view(self, view: ViewMode) -> None:
        if view == ViewMode.MAIN:
            self.draw_main_view()
        elif view == ViewMode.LOGS:
            self.draw_logs_view()
        elif view == ViewMode.INSPECT:
            self.draw_inspect_view()
        elif view == ViewMode.DETAILS:
            self.draw_details_view()
        elif view == ViewMode.TOP:
            self.draw_top_view()
        elif view == ViewMode.SYSTEM:
            self.draw_system_view()
        elif view == ViewMode.EXEC:
            self.draw_exec_view()
        elif view == ViewMode.INPUT:
            self.draw_input_view()
        elif view == ViewMode.HELP:
            self.draw_help_view()
        elif view == ViewMode.COMPOSE_SNIPPET:
            self.draw_compose_snippet_view()
        elif view == ViewMode.SETTINGS:
            self.draw_settings_view()
        elif view == ViewMode.SEARCH:
            self.draw_search_view()
        elif view == ViewMode.PULL_PROGRESS:
            self.draw_pull_progress_view()
        elif view == ViewMode.FILES:
            self.draw_files_view()

    def draw_current(self) -> None:
        if self.pinned_view and self.view_mode == ViewMode.MAIN:
            self._split_screen_mode = True
            try:
                self.draw_main_view()
                size = get_terminal_size()
                print("═" * (size.width - 1))
                orig_view_mode = self.view_mode
                orig_active = self.active_container
                self.view_mode = self.pinned_view
                self.active_container = self.pinned_target
                self._dispatch_view(self.pinned_view)
                self.view_mode = orig_view_mode
                self.active_container = orig_active
            finally:
                self._split_screen_mode = False
        else:
            self._split_screen_mode = False
            self._dispatch_view(self.view_mode)

    # ------------------------------------------------------------- interactive exec

    def run_interactive_exec(self, container_id: str, container_name: str, command: str) -> None:
        self.stop_refresh_worker()
        print("\033[H\033[2J", end="", flush=True)
        print(f"=== Starting interactive exec session in container '{container_name}' ===")
        print(f"Command: {command}")
        print("Type 'exit' to end session and return to DockTUI.\n")
        try:
            cmd_parts = shlex.split(command)
        except ValueError as e:
            print(f"Error parsing command: {e}")
            self.start_refresh_worker()
            self.prompt_user("Press Enter to continue...")
            return
        if not self.client.docker_bin:
            self.start_refresh_worker()
            self.prompt_user("Press Enter to continue...")
            return
        cmd = [self.client.docker_bin, "exec", "-it", container_id] + cmd_parts
        try:
            subprocess.run(cmd)
        except Exception as e:
            print(f"Error running interactive session: {e}")
            self.prompt_user("Press Enter to continue...")
        self.start_refresh_worker()
        self.request_refresh()
        self.need_redraw = True

    # ------------------------------------------------------------- key handling

    def _handle_key_main(self, key: str) -> bool:
        # Numeric tab switching.
        if key in ("1", "2", "3", "4", "5", "6"):
            self.current_tab = self.tabs[int(key) - 1]
            self.set_status(f"Switched tab to {self.current_tab}.")
            self.refresh_data()
            return True
        if key in ("up", "scroll_up"):
            self._move_selection(-1)
            return True
        if key in ("down", "scroll_down"):
            self._move_selection(1)
            return True
        if key == "o" and self.current_tab in ("containers", "compose"):
            self._cycle_sort_mode()
            return True
        if key == "y" and self.current_tab in ("containers", "compose"):
            self._cycle_state_filter()
            return True
        if key == "n" and self.current_tab in ("containers", "compose"):
            sel = self.current_selected_container()
            if sel:
                self._rename_container(sel)
            return True
        if key == "p" and self.current_tab in ("containers", "compose", "images", "volumes"):
            self.system_info_text = ""
            self.view_mode = ViewMode.SYSTEM
            return True
        if key == "l" and self.current_tab in ("containers", "compose"):
            self._open_logs_view()
            return True
        if key == "v" and self.current_tab in ("containers", "compose"):
            self._open_details_view()
            return True
        if key == "i" and self.current_tab in ("containers", "compose"):
            self._open_inspect_view()
            return True
        if key == "t" and self.current_tab in ("containers", "compose"):
            self._open_top_view()
            return True
        if key == "e" and self.current_tab in ("containers", "compose"):
            self._open_exec_view()
            return True
        if key == "x" and self.current_tab in ("containers", "compose"):
            self._open_compose_snippet()
            return True
        if key == "w" and self.current_tab in ("containers", "compose"):
            self.start_resource_edit()
            return True
        if key == "C" and self.current_tab in ("containers", "compose"):
            self.start_container_clone()
            return True
        if key == "f" and self.current_tab == "images":
            self.start_registry_search()
            return True
        if key == "F" and self.current_tab == "volumes":
            self.open_volume_files()
            return True
        if key == "S":
            self.view_mode = ViewMode.SETTINGS
            return True
        if key == "r" and self.current_tab in ("containers", "compose"):
            self._restart_or_reconnect()
            return True
        if key == "s" and self.current_tab in ("containers", "compose"):
            self._start_or_stop_selected()
            return True
        # Compose tab extras
        if key in ("u", "d", "b") and self.current_tab == "compose":
            return self._handle_compose_action_key(key)
        if key == "u" and self.current_tab == "contexts":
            self.use_selected_context()
            return True
        if key == "n" and self.current_tab == "contexts":
            self.new_endpoint_prompt()
            return True
        if key == "d" and self.current_tab in ("images", "volumes", "networks"):
            self._delete_current()
            return True
        return False

    def _handle_key_logs(self, key: str) -> bool:
        delta = scroll_step(key, 3, 1)
        if key in ("up", "scroll_up"):
            self.log_follow = False
            self.log_scroll_index = max(0, self.log_scroll_index - delta)
            return True
        if key in ("down", "scroll_down"):
            self.log_follow = False
            self.log_scroll_index = max(0, min(self.log_scroll_index + delta, len(self.log_lines) - 1))
            return True
        if key == "g":
            self.stop_log_stream()
            self.log_lines = []
            self.last_log_refresh = 0.0
            self.set_status("Logs refreshed.")
            return True
        if key == " ":
            self.log_follow = False
            self.set_status("Log follow paused.")
            return True
        if key == "f":
            self.log_follow = not self.log_follow
            self.stop_log_stream()
            self.log_lines = []
            self.set_status(f"Log follow mode {'enabled' if self.log_follow else 'disabled'}.")
            return True
        if key == "/":
            self._start_log_search()
            return True
        if key == "n":
            self.jump_to_next_log_match(viewport_height_for(get_terminal_size().height))
            return True
        if key == "e":
            self.log_errors_only = not self.log_errors_only
            self.stop_log_stream()
            self.log_lines = []
            self.set_status(f"Error-only logs {'enabled' if self.log_errors_only else 'disabled'}.")
            return True
        if key == "c":
            self.stop_log_stream()
            self.log_filter = ""
            self.log_search = ""
            self.log_errors_only = False
            self.log_lines = []
            self.set_status("Cleared log filter.")
            return True
        if key in ("+", "="):
            self.log_tail_limit = min(self.config.log_max, self.log_tail_limit + self.config.log_tail_step)
            self.stop_log_stream()
            self.log_lines = []
            self.set_status(f"Increased log limit to {self.log_tail_limit} lines.")
            return True
        if key == "-":
            self.log_tail_limit = max(self.config.log_min, self.log_tail_limit - self.config.log_tail_step)
            self.stop_log_stream()
            self.log_lines = []
            self.set_status(f"Decreased log limit to {self.log_tail_limit} lines.")
            return True
        if key == "h":
            self._toggle_log_highlights()
            return True
        if key == "o":
            self.log_follow = False
            self.start_input("Export logs to path: ", self.export_logs_to_file)
            return True
        if key in ("q", "l", "\x1b"):
            self.view_mode = ViewMode.MAIN
            return True
        return False

    def _handle_key_inspect(self, key: str) -> bool:
        return self._handle_scroll_key(
            key,
            "inspect_scroll_index",
            "inspect_lines",
            "Export inspect JSON to path: ",
            self.export_inspect_to_file,
            back_keys="i",
        )

    def _handle_key_details(self, key: str) -> bool:
        return self._handle_scroll_key(
            key,
            "details_scroll_index",
            "details_lines",
            "Export details to path: ",
            self.export_details_to_file,
            back_keys="v",
        )

    def _handle_key_top(self, key: str) -> bool:
        return self._handle_scroll_key(
            key,
            "top_scroll_index",
            "top_lines",
            "Export processes to path: ",
            self.export_top_to_file,
            back_keys="t",
        )

    def _handle_key_compose_snippet(self, key: str) -> bool:
        return self._handle_scroll_key(
            key,
            "compose_snippet_scroll_index",
            "compose_snippet_lines",
            "Export compose snippet to path: ",
            self.export_compose_snippet_to_file,
            back_keys="x",
        )

    def _handle_key_exec(self, key: str) -> bool:
        if self._handle_scroll_key(key, "exec_scroll_index", "exec_output_lines", "", lambda _v: None, back_keys=""):
            return True
        if key == "r":
            sel = self.active_container or self.current_selected_container()
            if sel:
                self.set_status(f"Running command: {self.exec_command_text}...")
                output = self.client.exec_command(sel["id"], self.exec_command_text)
                self.exec_output_lines = output.split("\n")
                self.exec_scroll_index = 0
            return True
        if key == "e":
            sel = self.active_container or self.current_selected_container()
            if sel:
                command = self.prompt_exec_command(sel["name"])
                if command:
                    self.exec_command_text = command
                    self.record_exec_command(command)
                    self.set_status(f"Running command: {command}...")
                    output = self.client.exec_command(sel["id"], command)
                    self.exec_output_lines = output.split("\n")
                    self.exec_scroll_index = 0
            return True
        if key in ("q", "\x1b"):
            self.view_mode = ViewMode.MAIN
            return True
        return False

    def _handle_key_system(self, key: str) -> bool:
        if key in ("x", "i", "v", "a"):
            prune_name = {"x": "PRUNE", "i": "IMAGES", "v": "VOLUMES", "a": "ALL"}[key]
            if self.prompt_user(f"Type {prune_name} to confirm prune: ") != prune_name:
                self.set_status("Prune canceled.")
                return True
            self.set_status(f"Running Docker prune ({prune_name})...")
            self.draw_system_view()
            if key == "i":
                out = self.client.prune_images()
            elif key == "v":
                out = self.client.prune_volumes()
            else:
                out = self.client.prune_system(include_volumes=(key == "a"))
            print("\n" + "─" * 40)
            print(out)
            print("─" * 40)
            self.prompt_user("Prune complete. Press ENTER to continue.")
            self.system_info_text = ""
            self.refresh_data()
            return True
        if key in ("p", "\x1b"):
            self.view_mode = ViewMode.MAIN
            return True
        return False

    def _handle_key_settings(self, key: str) -> bool:
        if key in ("up", "scroll_up"):
            self.settings_index = max(0, self.settings_index - 1)
            return True
        if key in ("down", "scroll_down"):
            self.settings_index = min(max(0, len(self.settings_options) - 1), self.settings_index + 1)
            return True
        if key == "enter":
            self._start_settings_edit()
            return True
        if key == "s":
            self.save_settings()
            return True
        if key in ("\x1b", "q"):
            self.view_mode = ViewMode.MAIN
            return True
        return False

    def _handle_key_search(self, key: str) -> bool:
        if not self.search_results:
            if key in ("\x1b", "q"):
                self.view_mode = ViewMode.IMAGES if self.current_tab == "images" else ViewMode.MAIN
            return True
        if key in ("up", "scroll_up"):
            self.search_index = max(0, self.search_index - 1)
            return True
        if key in ("down", "scroll_down"):
            self.search_index = min(len(self.search_results) - 1, self.search_index + 1)
            return True
        if key == "enter":
            self._pull_selected_image()
            return True
        if key in ("\x1b", "q"):
            self.view_mode = ViewMode.IMAGES if self.current_tab == "images" else ViewMode.MAIN
            return True
        return False

    def _handle_key_pull(self, key: str) -> bool:
        if key in ("\x1b", "q"):
            self.cancel_pull()
            return True
        return True

    def _handle_key_files(self, key: str) -> bool:
        if not self.file_entries:
            if key in ("\x1b", "q", "backspace"):
                self.view_mode = ViewMode.MAIN
            return True
        if key in ("up", "scroll_up"):
            self.file_index = max(0, self.file_index - 1)
            return True
        if key in ("down", "scroll_down"):
            self.file_index = min(len(self.file_entries) - 1, self.file_index + 1)
            return True
        if key == "enter":
            self._file_open()
            return True
        if key == "backspace":
            self._file_up()
            return True
        if key in ("\x1b", "q"):
            self.view_mode = ViewMode.MAIN
            return True
        return False

    def _handle_key_help(self, key: str) -> bool:
        if key in ("?", "q", "\x1b"):
            self.close_help()
            return True
        return False

    # ------------------------------------------------------------- key helpers

    def _handle_scroll_key(
        self,
        key: str,
        attr: str,
        lines_attr: str,
        export_prompt: str,
        export_callback: Callable[[str], None],
        back_keys: str,
    ) -> bool:
        delta = scroll_step(key, 3, 1)
        if key in ("up", "scroll_up"):
            setattr(self, attr, max(0, getattr(self, attr) - delta))
            return True
        if key in ("down", "scroll_down"):
            current = getattr(self, attr)
            total = len(getattr(self, lines_attr))
            setattr(self, attr, max(0, min(current + delta, total - 1)))
            return True
        if key == "o" and export_prompt:
            self.start_input(export_prompt, export_callback)
            return True
        back_set = set(back_keys.split("|")) if back_keys else set()
        if key in back_set or key == "\x1b":
            self.view_mode = ViewMode.MAIN
            return True
        if key == "?":
            self.open_help()
            return True
        return False

    def _move_selection(self, delta: int) -> None:
        attrs = {
            "containers": ("selected_index", self.containers),
            "compose": ("selected_compose_index", self.compose_rows),
            "images": ("selected_image_index", self.images),
            "volumes": ("selected_volume_index", self.volumes),
            "networks": ("selected_network_index", self.networks),
            "contexts": ("selected_context_index", self.contexts),
        }
        attr, items = attrs.get(self.current_tab, ("selected_index", self.containers))
        if not items:
            return
        current = getattr(self, attr)
        new = max(0, min(len(items) - 1, current + delta))
        setattr(self, attr, new)

    def _cycle_sort_mode(self) -> None:
        modes = ["default", "name", "image", "state"]
        self.sort_mode = modes[(modes.index(self.sort_mode) + 1) % len(modes)]
        self.set_status(f"Sort mode: {self.sort_mode}.")
        self.refresh_data()

    def _cycle_state_filter(self) -> None:
        modes = [StateFilter.ALL.value, StateFilter.RUNNING.value, StateFilter.EXITED.value, StateFilter.CREATED.value]
        self.state_filter = modes[(modes.index(self.state_filter) + 1) % len(modes)]
        self.set_status(f"State filter: {self.state_filter}.")
        self.refresh_data()

    def _rename_container(self, sel: Dict[str, str]) -> None:
        new_name = self.prompt_user(f"New name for container {sel['name']}: ")
        if not new_name:
            return
        self.set_status(f"Renaming container {sel['name']} to {new_name}...")
        success, msg = self.client.rename_container(sel["id"], new_name)
        self.set_status(msg if success else f"Rename failed: {msg}")
        self.refresh_data()

    def _open_logs_view(self) -> None:
        if self.current_tab == "compose" and self.compose_rows and self.compose_rows[self.selected_compose_index].get("type") == "project":
            row = self.compose_rows[self.selected_compose_index]
            self.active_project = row["project"]
            self.active_container = None
        else:
            sel = self.current_selected_container()
            if not sel:
                return
            self.active_container = sel
            self.active_project = None
        for attr in ("log_filter", "log_search", "log_lines"):
            setattr(self, attr, "" if attr != "log_lines" else [])
        self.log_errors_only = False
        self.log_follow = False
        self.last_log_refresh = 0.0
        self.view_mode = ViewMode.LOGS

    def _open_details_view(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        self.active_container = sel
        self.set_status(f"Loading details for {sel['name']}...")
        self.details_lines = self.build_details_lines(sel["id"])
        self.details_scroll_index = 0
        self.view_mode = ViewMode.DETAILS

    def _open_inspect_view(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        self.active_container = sel
        self.set_status(f"Inspecting container {sel['name']}...")
        inspect_data = self.client.inspect_container(sel["id"])
        self.inspect_lines = inspect_data.split("\n")
        self.inspect_scroll_index = 0
        self.view_mode = ViewMode.INSPECT

    def _open_top_view(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        if sel["state"] != "running":
            self.set_status(f"Error: Container {sel['name']} is not running.")
            return
        self.active_container = sel
        self.set_status(f"Loading processes for {sel['name']}...")
        self.top_lines = self.client.top_container(sel["id"]).split("\n")
        self.top_scroll_index = 0
        self.view_mode = ViewMode.TOP

    def _open_exec_view(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        if sel["state"] != "running":
            self.set_status(f"Error: Container {sel['name']} is not running.")
            return
        self.active_container = sel
        command = self.prompt_exec_command(sel["name"])
        if not command:
            return
        self.exec_command_text = command
        self.record_exec_command(command)
        default_interactive = "y" if command.strip() in ("sh", "bash", "ash", "zsh") else "n"
        choice = self.prompt_user(f"Run command interactively? (y/n) [Default: {default_interactive}]: ").lower().strip()
        if not choice:
            choice = default_interactive
        if choice in ("y", "yes"):
            self.run_interactive_exec(sel["id"], sel["name"], command)
        else:
            self.set_status(f"Running command: {command}...")
            output = self.client.exec_command(sel["id"], command)
            self.exec_output_lines = output.split("\n")
            self.exec_scroll_index = 0
            self.view_mode = ViewMode.EXEC

    def _open_compose_snippet(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        self.set_status(f"Generating Compose snippet for {sel['name']}...")
        self.compose_snippet_lines = []
        self.view_mode = ViewMode.COMPOSE_SNIPPET

    def _restart_or_reconnect(self) -> None:
        if not self.is_daemon_running_cached(force=True):
            self.set_status("Reconnecting to Docker daemon...")
            self.refresh_data()
            return
        if not self.containers:
            self.set_status("Connected to Docker daemon. Refreshing data...")
            self.refresh_data()
            return
        if self.current_tab == "compose" and self.compose_rows and self.compose_rows[self.selected_compose_index].get("type") == "project":
            row = self.compose_rows[self.selected_compose_index]
            for container in row["containers"]:  # type: ignore[index]
                self.client.restart_container(container["id"])
            self.set_status(f"Restarted project {row['project']}.")
            self.refresh_data()
            return
        sel = self.current_selected_container()
        if not sel:
            return
        self.set_status(f"Restarting container: {sel['name']}...")
        if self.client.restart_container(sel["id"]):
            self.set_status(f"Successfully restarted container {sel['name']}.")
        else:
            self.set_status(f"Failed to restart container {sel['name']}.")
        self.refresh_data()

    def _start_or_stop_selected(self) -> None:
        if self.current_tab == "compose" and self.compose_rows and self.compose_rows[self.selected_compose_index].get("type") == "project":
            row = self.compose_rows[self.selected_compose_index]
            containers = row["containers"]  # type: ignore[index]
            any_running = any(c["state"] == "running" for c in containers)
            for container in containers:
                if any_running and container["state"] == "running":
                    self.client.stop_container(container["id"])
                elif not any_running:
                    self.client.start_container(container["id"])
            self.set_status(f"{'Stopped' if any_running else 'Started'} project {row['project']}.")
            self.refresh_data()
            return
        sel = self.current_selected_container()
        if not sel:
            return
        if sel["state"] == "running":
            self.set_status(f"Stopping container: {sel['name']}...")
            ok = self.client.stop_container(sel["id"])
            self.set_status(f"{'Stopped' if ok else 'Failed to stop'} container {sel['name']}.")
        else:
            self.set_status(f"Starting container: {sel['name']}...")
            ok = self.client.start_container(sel["id"])
            self.set_status(f"{'Started' if ok else 'Failed to start'} container {sel['name']}.")
        self.refresh_data()

    def _delete_current(self) -> None:
        if self.current_tab == "images" and self.images:
            sel_img = self.images[self.selected_image_index]
            if self.prompt_user(f"Delete image {sel_img['repository']}:{sel_img['tag']}? (y/n): ").lower() in ("y", "yes"):
                self.set_status(f"Deleting image {sel_img['id'][:10]}...")
                success, msg = self.client.remove_image(sel_img["id"])
                if not success:
                    print("\n" + "─" * 40)
                    print(f"{RED}Error: {msg}{RESET}")
                    print("─" * 40)
                    self.prompt_user("Press ENTER to continue.")
                else:
                    self.set_status("Successfully deleted image.")
                self.refresh_data()
        elif self.current_tab == "volumes" and self.volumes:
            volume = self.volumes[self.selected_volume_index]
            if self.prompt_user(f"Delete volume {volume['name']}? (y/n): ").lower() in ("y", "yes"):
                success, msg = self.client.remove_volume(volume["name"])
                self.set_status(msg if success else f"Volume delete failed: {msg}")
                self.refresh_data()
        elif self.current_tab == "networks" and self.networks:
            network = self.networks[self.selected_network_index]
            if self.prompt_user(f"Delete network {network['name']} ({network['driver']})? (y/n): ").lower() in ("y", "yes"):
                success, msg = self.client.remove_network(network["name"])
                self.set_status(msg if success else f"Network delete failed: {msg}")
                self.refresh_data()

    def _handle_compose_action_key(self, key: str) -> bool:
        if not self.compose_rows or self.compose_rows[self.selected_compose_index].get("type") != "project":
            return False
        row = self.compose_rows[self.selected_compose_index]
        if key == "u":
            confirm = self.prompt_user(f"Run up with --build on project '{row['project']}'? (y/n/c): ").lower().strip()
            if confirm in ("y", "yes"):
                self.set_status(f"Starting compose project '{row['project']}' with --build...")
                success, msg = self.client.run_compose_cmd(row["project"], row.get("config_file", ""), ComposeAction.UP_BUILD.value)
                self.set_status(msg if success else f"Compose up failed: {msg}")
            elif confirm in ("n", "no"):
                self.set_status(f"Starting compose project '{row['project']}'...")
                success, msg = self.client.run_compose_cmd(row["project"], row.get("config_file", ""), ComposeAction.UP.value)
                self.set_status(msg if success else f"Compose up failed: {msg}")
            else:
                self.set_status("Compose up canceled.")
            self.refresh_data()
            return True
        if key == "d":
            if self.prompt_user(f"Down compose project '{row['project']}'? (y/n): ").lower() in ("y", "yes"):
                self.set_status(f"Downing compose project '{row['project']}'...")
                success, msg = self.client.run_compose_cmd(row["project"], row.get("config_file", ""), ComposeAction.DOWN.value)
                self.set_status(msg if success else f"Compose down failed: {msg}")
                self.refresh_data()
            return True
        if key == "b":
            if self.prompt_user(f"Build compose project '{row['project']}'? (y/n): ").lower() in ("y", "yes"):
                self.set_status(f"Building compose project '{row['project']}'...")
                success, msg = self.client.run_compose_cmd(row["project"], row.get("config_file", ""), ComposeAction.BUILD.value)
                self.set_status(msg if success else f"Compose build failed: {msg}")
                self.refresh_data()
            return True
        return False

    # ------------------------------------------------------------- log search

    def _start_log_search(self) -> None:
        query = self.prompt_user("Enter search term: ")
        self.stop_log_stream()
        self.log_search = query
        self.log_filter = query
        self.log_match_index = -1
        self.log_lines = []

    def _toggle_log_highlights(self) -> None:
        if not self.config.log_highlights:
            self.set_status("No log highlights configured. Open Settings (Shift+S) to add some.")
            return
        if self.log_highlight_regex is not None:
            self.log_highlight_regex = None
            self.set_status("Log highlights disabled.")
            return
        patterns = []
        for entry in self.config.log_highlights:
            pattern = entry.get("pattern", "")
            if not pattern:
                continue
            try:
                patterns.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                continue
        if not patterns:
            self.set_status("No valid highlight patterns.")
            return
        self.log_highlight_regex = re.compile("|".join(f"(?:{p.pattern})" for p in patterns))
        self.set_status(f"Highlighting {len(patterns)} pattern(s) in logs.")

    # ------------------------------------------------------------- main loop

    def run(self) -> None:
        global RESIZE_REQUESTED
        self._quit_requested = False
        init_terminal()
        self.enable_mouse_tracking()
        self.start_refresh_worker()
        self.request_refresh()

        # Per-view key dispatcher table.
        view_handlers = {
            ViewMode.MAIN: self._handle_key_main,
            ViewMode.LOGS: self._handle_key_logs,
            ViewMode.INSPECT: self._handle_key_inspect,
            ViewMode.DETAILS: self._handle_key_details,
            ViewMode.TOP: self._handle_key_top,
            ViewMode.SYSTEM: self._handle_key_system,
            ViewMode.EXEC: self._handle_key_exec,
            ViewMode.HELP: self._handle_key_help,
            ViewMode.COMPOSE_SNIPPET: self._handle_key_compose_snippet,
            ViewMode.SETTINGS: self._handle_key_settings,
            ViewMode.SEARCH: self._handle_key_search,
            ViewMode.PULL_PROGRESS: self._handle_key_pull,
            ViewMode.FILES: self._handle_key_files,
        }

        try:
            while not self._quit_requested:
                size = get_terminal_size()
                self._viewport_h = viewport_height_for(size.height)

                if self.need_redraw:
                    self.need_redraw = False
                    self._dispatch_view(self.view_mode)

                if self.view_mode == ViewMode.MAIN and (time.time() - self.last_refresh > self.refresh_interval):
                    self.request_refresh()
                if self.view_mode != ViewMode.LOGS and self.is_log_streaming():
                    self.stop_log_stream()
                if RESIZE_REQUESTED:
                    RESIZE_REQUESTED = False
                    self.request_refresh()
                    self.need_redraw = True
                if self.status_message != "Use Tab to switch tabs. Up/Down to navigate." and (time.time() - self.status_time > 4):
                    self.status_message = "Use Tab to switch tabs. Up/Down to navigate."
                    self.need_redraw = True

                key = get_key_nonblocking()
                if not key:
                    time.sleep(0.04)
                    continue
                self.need_redraw = True
                if self.view_mode == ViewMode.INPUT:
                    self.handle_input_key(key)
                    time.sleep(0.08)
                    continue
                if key == "mouse":
                    self.set_status("Mouse click detected. Scroll to navigate list/logs.")
                    time.sleep(0.08)
                    continue

                # Try view-specific handler first.
                handler = view_handlers.get(self.view_mode)
                if handler is not None and handler(key):
                    time.sleep(0.04)
                    continue
                # Fall back to the global keymap.
                lowered = key.lower() if len(key) == 1 else key
                if self.keymap.dispatch(self.view_mode.value, lowered):
                    continue
                time.sleep(0.04)
        finally:
            self.stop_log_stream()
            self.stop_refresh_worker()
            self.disable_mouse_tracking()
            print(RESET)
