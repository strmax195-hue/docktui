"""Main DockTUI TUI.

This module is the dashboard orchestrator. It owns the input loop, the data
state, jobs, and modal input flow. Terminal input lives in `terminal`;
rendering lives in `views`, with shared helpers in `styles` and `screen`.
"""

import os
import re
import shlex
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from . import screen as _screen_module
from . import styles as _styles
from . import terminal as _terminal
from .terminal import PLATFORM, cooked_terminal, get_key_nonblocking, init_terminal, restore_terminal
from .log_format import colorize_log_line as colorize_log_line, _log_matches_filter, _log_is_error_line
from .views.dashboard import DashboardViews
from .views.logs import LogsViews
from .views.text import TextViews
from .views.dialogs import DialogsViews
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
from .jobs import JobRunner
from .keymap import Keymap, resolve_hotkey_overlay
from .log_stream import LineStreamer, StreamResult
from .screen import clear_screen, get_terminal_size, scroll_step, viewport_height_for
from .snapshot import DashboardSnapshot, collect_snapshot, sort_container_rows
from .styles import (
    BOLD as BOLD,
    CYAN as CYAN,
    GREEN as GREEN,
    MAGENTA as MAGENTA,
    RED as RED,
    RESET as RESET,
    WHITE_ON_BLUE as WHITE_ON_BLUE,
    YELLOW as YELLOW,
)

_THEMED_NAMES = (
    "RESET",
    "BOLD",
    "CYAN",
    "GREEN",
    "RED",
    "YELLOW",
    "WHITE_ON_BLUE",
    "BG_DARK_GRAY",
    "MAGENTA",
)


def apply_theme_colors(theme_name: Optional[str] = None) -> str:
    """Apply a theme and re-bind the colour names imported by this module and `screen`.

    `from .styles import RED` copies the value at import time, so without this
    re-binding theme switches (`M`, `--theme`) and `NO_COLOR` never reached the
    dashboard.
    """
    name = _styles.apply_theme_colors(theme_name)
    for namespace in (globals(), vars(_screen_module)):
        for attr in _THEMED_NAMES:
            if attr in namespace:
                namespace[attr] = getattr(_styles, attr)
    return name


# ---------------------------------------------------------------------------
# Cross-platform keyboard input
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class ContainerDashboard(DashboardViews, LogsViews, TextViews, DialogsViews):
    """The main TUI rendering and interaction loop."""

    def __init__(
        self,
        refresh_interval: float = DEFAULT_REFRESH_INTERVAL,
        docker_timeout: float = DEFAULT_DOCKER_TIMEOUT,
        docker_host: Optional[str] = None,
        theme: Optional[str] = None,
        exec_presets: Optional[list[str]] = None,
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
        self.client = DockerClient(
            timeout=self.config.docker_timeout, host=self.config.resolve_host(docker_host)
        )
        self.theme = self.config.theme
        apply_theme_colors(self.theme)

        # ---------------------------------------------------------------- state
        self.tabs: list[str] = list(AVAILABLE_TABS)
        self.filters: dict[str, str] = {tab: "" for tab in self.tabs}
        self.containers: list[dict[str, str]] = []
        self.stats: dict[str, dict[str, str]] = {}
        self.images: list[dict[str, str]] = []
        self.volumes: list[dict[str, str]] = []
        self.networks: list[dict[str, str]] = []
        self.contexts: list[dict[str, str]] = []
        self.compose_rows: list[dict[str, Any]] = []
        self.active_container: Optional[dict[str, str]] = None
        self.active_project: Optional[str] = None
        self.active_endpoint: Optional[str] = (
            self.config.active_endpoint if self.client.host else None
        )
        self.endpoints: list[dict[str, str]] = list(self.config.endpoints)

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
        self.last_attempt = 0.0
        self.refresh_error = ""
        self.refresh_interval = self.config.refresh_interval
        self.state_filter = StateFilter.ALL.value
        self.sort_mode = "default"

        # ---------------------------------------------------------------- logs
        self.log_filter = ""
        self.log_search = ""
        self.log_match_index = 0
        self.log_errors_only = False
        self.log_tail_limit = self.config.log_tail_limit
        self.log_lines: list[str] = []
        self.log_scroll_index = 0
        self.log_follow = False
        self.last_log_refresh = 0.0
        self.log_highlight_patterns: list[tuple[str, str]] = []  # (label, color)
        self.log_highlight_regex: Optional[re.Pattern] = None

        # ---------------------------------------------------------------- exec
        self.exec_output_lines: list[str] = []
        self.exec_scroll_index = 0
        self.exec_command_text = ""
        self.exec_history: list[str] = []

        # ---------------------------------------------------------------- other
        self.system_info_text = ""
        self.current_context = ""
        self.daemon_running = False
        self.last_daemon_check = 0.0
        self.daemon_check_interval = 3.0
        self.compose_snippet_lines: list[str] = []
        self.compose_snippet_scroll_index = 0
        self.inspect_lines: list[str] = []
        self.inspect_scroll_index = 0
        self.details_lines: list[str] = []
        self.details_scroll_index = 0
        self.top_lines: list[str] = []
        self.top_scroll_index = 0
        self.settings_options: list[dict[str, Any]] = []
        self.settings_index = 0
        self.pull_lines: list[str] = []
        self.pull_scroll_index = 0
        self.pull_image_name = ""
        self.search_results: list[dict[str, str]] = []
        self.search_index = 0
        self.file_entries: list[dict[str, str]] = []
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
        self.log_stream_threads: list[threading.Thread] = []
        self.log_streamer: Optional[LineStreamer] = None
        self.pull_streamer: Optional[LineStreamer] = None

        # ---------------------------------------------------------------- modal
        self.input_dialog = DialogResult()
        self.need_redraw = True
        self.pinned_view: Optional[ViewMode] = None
        self.pinned_target: Optional[dict[str, str]] = None
        self.pinned_project: Optional[str] = None
        self._list_clipped: Optional[tuple[int, int, int]] = None
        self._quit_requested = False
        self._running = False
        self.jobs = JobRunner()
        self._ui_lines: deque = deque(maxlen=max(1, self.config.log_max))
        self._ui_events: deque = deque(maxlen=100)
        self._log_generation = 0
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
    def exec_presets(self) -> list[str]:
        return list(self.config.exec_presets)

    # ------------------------------------------------------------- keymap

    def _register_bindings(self) -> None:
        km = self.keymap
        # Global
        km.register_global("?", self.open_help, "Open help")  # type: ignore
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
        if self._running:
            self.request_refresh()
            return
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
        if self._running:
            return self.daemon_running
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
                while _terminal.msvcrt.kbhit():  # type: ignore[attr-defined]
                    _terminal.msvcrt.getch()  # type: ignore[attr-defined]
            with cooked_terminal():
                return input().strip()
        except Exception:
            return ""

    # ------------------------------------------------------------- export

    def _export_lines_to_file(self, lines: list[str], type_name: str, filepath: str) -> None:
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

    def current_selected_container(self) -> Optional[dict[str, str]]:
        if self.current_tab == "containers" and self.containers:
            return self.containers[self.selected_index]
        if self.current_tab == "compose" and self.compose_rows:
            row = self.compose_rows[self.selected_compose_index]
            if row.get("type") == "container":
                return row.get("container")  # type: ignore[return-value]
        return None

    def sort_containers(self, containers: list[dict[str, str]]) -> list[dict[str, str]]:
        return sort_container_rows(containers, self.container_filter, self.state_filter, self.sort_mode)

    def build_compose_rows(self) -> None:
        groups: dict[str, list[dict[str, str]]] = {}
        loose: list[dict[str, str]] = []
        for container in self.containers:
            project = container.get("compose_project")
            if project:
                groups.setdefault(project, []).append(container)
            else:
                loose.append(container)

        rows: list[dict[str, Any]] = []
        for project in sorted(groups):
            project_containers = sorted(
                groups[project], key=lambda c: (c.get("compose_service", ""), c.get("name", ""))
            )
            working_dir = ""
            config_file = ""
            for container in project_containers:
                labels = container.get("labels") or {}  # type: ignore
                if "com.docker.compose.project.working_dir" in labels:
                    working_dir = labels["com.docker.compose.project.working_dir"]  # type: ignore
                if "com.docker.compose.project.config_files" in labels:
                    config_file = labels["com.docker.compose.project.config_files"]  # type: ignore
            rows.append(
                {
                    "type": "project",
                    "project": project,
                    "containers": project_containers,
                    "working_dir": working_dir,
                    "config_file": config_file,
                }
            )
            for container in project_containers:
                rows.append({"type": "container", "project": project, "container": container})
        if loose:
            rows.append({"type": "project", "project": "(standalone)", "containers": loose})
            for container in sorted(loose, key=lambda c: c.get("name", "")):
                rows.append(
                    {"type": "container", "project": "(standalone)", "container": container}
                )
        self.compose_rows = rows
        if self.selected_compose_index >= len(self.compose_rows):
            self.selected_compose_index = max(0, len(self.compose_rows) - 1)

    # ------------------------------------------------------------- logs / streaming

    def load_log_lines(
        self, container_id: Optional[str], viewport_height: int, follow: bool = False
    ) -> None:
        if self._running:
            method = "get_compose_project_logs" if container_id is None and self.active_project else "get_logs"
            target = self.active_project if method == "get_compose_project_logs" else container_id
            token = self._log_generation
            def apply(raw):
                if token == self._log_generation:
                    self._apply_log_text(raw, viewport_height, follow)
                    self.need_redraw = True
            self._docker_job("view:logs", method, (target,), apply, tail=self.log_tail_limit)
            return
        if container_id is None and self.active_project:
            raw_logs = self.client.get_compose_project_logs(
                self.active_project, tail=self.log_tail_limit
            )
        else:
            raw_logs = self.client.get_logs(container_id, tail=self.log_tail_limit)  # type: ignore
        self._apply_log_text(raw_logs, viewport_height, follow)

    def _apply_log_text(self, raw_logs: str, viewport_height: int, follow: bool) -> None:
        log_lines = raw_logs.split("\n")
        if self.log_errors_only:
            log_lines = [line for line in log_lines if _log_is_error_line(line)]
            if not log_lines:
                log_lines = [f"{YELLOW}(No error/warning lines in current log window){RESET}"]
        if self.log_filter:
            self.log_lines = [
                line for line in log_lines if _log_matches_filter(line, self.log_filter)
            ]
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

        cmd: list[str] = []
        if self.client.docker_bin:
            cmd.append(self.client.docker_bin)
        if container_id is None and project_name:
            cmd += ["compose", "-p", project_name, "logs", "-f", f"--tail={self.log_tail_limit}"]
        else:
            cmd += ["logs", "-f", f"--tail={self.log_tail_limit}", container_id]  # type: ignore

        token = self._log_generation
        generation = self.client.connection_generation
        def on_line(line):
            self._post_ui(lambda: self._on_log_line(line) if token == self._log_generation else None, generation, line=True)
        streamer = LineStreamer(cmd, on_line=on_line, env=self.client.command_env())
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
                height = get_terminal_size().height
                viewport_h = viewport_height_for(height)
                if self.pinned_view == ViewMode.LOGS and self.view_mode != ViewMode.LOGS:
                    viewport_h = self.split_viewport_height(height)
            except Exception:
                viewport_h = 18
            self.log_scroll_index = max(0, len(self.log_lines) - viewport_h)
        self.need_redraw = True

    def stop_log_stream(self) -> None:
        self._log_generation += 1
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
        self.log_scroll_index = max(
            0, min(matches[self.log_match_index], len(self.log_lines) - viewport_height)
        )
        self.log_follow = False
        self.set_status(f"Log match {self.log_match_index + 1}/{len(matches)}.")

    # ------------------------------------------------------------- top / details / inspect

    def build_details_lines(self, container_id: str, details: Optional[dict] = None) -> list[str]:
        if details is None:
            details = self.client.get_container_details(container_id)
        if "error" in details:
            return details["error"].split("\n")
        lines: list[str] = [
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

    def start_exec_input(self, container: dict[str, str]) -> None:
        prompt = f"Command inside {container['name']} (type to search history, or custom): "

        def submit(value: str) -> None:
            command = value
            matches = [cmd for cmd in self.exec_history if value.lower() in cmd.lower()]
            if matches and value == matches[0][: len(value)]:
                command = matches[0]
            if not command:
                self.set_status("Command canceled.")
                return
            self.active_container = container
            self.exec_command_text = command
            self.record_exec_command(command)
            self.config.save()
            self.set_status(f"Running command: {command}...")
            self._load_output("exec_output_lines", "exec_command", container["id"], command)
            self.exec_scroll_index = 0
            self.view_mode = ViewMode.EXEC

        self.start_input(prompt, submit)

    # ------------------------------------------------------------- refresh data

    def _post_ui(self, callback: Callable, generation: int, line: bool = False) -> None:
        if not self._running:
            if generation == self.client.connection_generation:
                callback()
            return
        with self.data_lock:
            (self._ui_lines if line else self._ui_events).append((generation, callback))

    def _drain_ui(self) -> None:
        with self.data_lock:
            updates = list(self._ui_lines) + list(self._ui_events)
            self._ui_lines.clear()
            self._ui_events.clear()
        for generation, callback in updates:
            if generation == self.client.connection_generation:
                callback()
        self.jobs.drain(self.client.connection_generation)

    def _snapshot_request(self) -> tuple[str, str, str, str]:
        return (self.current_tab, self.filters.get(self.current_tab, ""), self.state_filter, self.sort_mode)

    def _apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        self.current_context = snapshot.context
        if snapshot.tab in ("containers", "compose"):
            selected = self.current_selected_container()
            cid = selected.get("id") if selected else None
            project = None
            if self.compose_rows and self.selected_compose_index < len(self.compose_rows):
                project = self.compose_rows[self.selected_compose_index].get("project")
            self.containers, self.stats = snapshot.items, snapshot.stats
            self.build_compose_rows()
            self.selected_index = next((i for i, row in enumerate(self.containers) if row.get("id") == cid), min(self.selected_index, max(0, len(self.containers) - 1)))
            self.selected_compose_index = next((i for i, row in enumerate(self.compose_rows) if (row.get("container") or {}).get("id") == cid and cid is not None or row.get("type") == "project" and row.get("project") == project and project is not None), 0)
        else:
            attrs = {"images": "selected_image_index", "volumes": "selected_volume_index", "networks": "selected_network_index", "contexts": "selected_context_index"}
            attr = attrs[snapshot.tab]
            old = getattr(self, snapshot.tab)
            index = getattr(self, attr)
            key = "id" if snapshot.tab in ("images", "networks") else "name"
            selected = old[index].get(key) if old and index < len(old) else None
            setattr(self, snapshot.tab, snapshot.items)
            setattr(self, attr, next((i for i, row in enumerate(snapshot.items) if row.get(key) == selected), min(index, max(0, len(snapshot.items) - 1))))
        self.daemon_running = True
        self.last_daemon_check = time.time()
        self.last_refresh = time.time()
        self.refresh_error = ""
        self.refresh_in_progress = False
        self.need_redraw = True

    def _refresh_failed(self, exc: Exception) -> None:
        self.refresh_error = str(exc)
        self.refresh_in_progress = False
        self.set_status(f"Refresh failed; keeping last snapshot: {exc}")
        self.need_redraw = True

    def _schedule_refresh(self) -> None:
        request = self._snapshot_request()
        client = self.client.snapshot(context=self.current_context or None)
        def work(cancel):
            client.cancel_event = cancel
            return collect_snapshot(client, *request)
        def apply(snapshot):
            if request == self._snapshot_request():
                self._apply_snapshot(snapshot)
            else:
                self.refresh_in_progress = False
                self.request_refresh()
        if self.jobs.submit("refresh", self.client.connection_generation, work, apply, self._refresh_failed):
            self.refresh_in_progress = True
            self.last_attempt = time.time()

    def refresh_data(self) -> None:
        if self._running:
            self.request_refresh()
            return
        self.refresh_in_progress = True
        self.last_attempt = time.time()
        generation = self.client.connection_generation
        try:
            snapshot = collect_snapshot(
                self.client.snapshot(context=self.current_context or None), *self._snapshot_request()
            )
            if generation == self.client.connection_generation:
                self._apply_snapshot(snapshot)
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            self._refresh_failed(exc)
        finally:
            self.refresh_in_progress = False

    def _docker_job(self, key: str, method: str, args: tuple, apply: Callable, **kwargs) -> None:
        client = self.client.snapshot(context=self.current_context or None)
        if not self._running:
            apply(getattr(client, method)(*args, **kwargs))
            return
        def work(cancel):
            client.cancel_event = cancel
            return getattr(client, method)(*args, **kwargs)
        if self.jobs.submit(key, self.client.connection_generation, work, apply, lambda exc: self.set_status(f"Operation failed: {exc}")):
            self.set_status("Working… Esc cancels the operation.")
        else:
            self.set_status("This operation is already running.")

    def _load_output(self, attr: str, method: str, *args, **kwargs) -> None:
        target = self.active_container
        def apply(value):
            if target is self.active_container:
                setattr(self, attr, value.split("\n") if isinstance(value, str) else value)
                self.need_redraw = True
        self._docker_job(f"view:{attr}", method, args, apply, **kwargs)

    def _action(self, method: str, *args, **kwargs) -> None:
        def apply(value):
            if isinstance(value, tuple):
                ok, message = value
                self.set_status(message or ("Operation completed." if ok else "Operation failed."))
            else:
                self.set_status(str(value) if isinstance(value, str) else ("Operation completed." if value else "Operation failed."))
            self.request_refresh()
        self._docker_job("action", method, args, apply, **kwargs)

    # ------------------------------------------------------------- main view













    # ------------------------------------------------------------- empty state


    # ------------------------------------------------------------- logs view


    # ------------------------------------------------------------- inspect / details / top














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
                "display": lambda: (
                    ", ".join(h.get("label", "?") for h in self.config.log_highlights) or "(none)"
                ),
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
                for item in (
                    self.config.exec_presets
                    if key == "exec_presets"
                    else self.config.log_highlights
                )
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
                        self.config.exec_presets = [
                            line.strip() for line in value.splitlines() if line.strip()
                        ]
                    elif key == "log_highlights":
                        self.config.log_highlights = []
                        for line in value.splitlines():
                            if not line.strip():
                                continue
                            label, pattern = (line.split("=", 1) + [""])[:2]
                            self.config.log_highlights.append(
                                {
                                    "label": label.strip(),
                                    "pattern": pattern.strip(),
                                }
                            )
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
        self.log_tail_limit = max(
            self.config.log_min, min(self.config.log_tail_limit, self.config.log_max)
        )
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
            self._load_output("search_results", "search_images", query)
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
            del self.pull_lines[:-self.config.log_max]
            self.need_redraw = True

        def on_complete(result: StreamResult) -> None:
            if result.cancelled:
                self.set_status(f"Pull of {repo} canceled.")
            elif result.returncode == 0:
                self.set_status(f"Pull of {repo} finished.")
                self.request_refresh()
            else:
                self.set_status(f"Pull of {repo} failed (exit {result.returncode}).")
            self.need_redraw = True

        generation = self.client.connection_generation
        streamer = LineStreamer(
            self.client.pull_image_args(repo),
            on_line=lambda line: self._post_ui(lambda: on_line(line), generation, line=True),
            on_complete=lambda result: self._post_ui(lambda: on_complete(result), generation),
            max_lines=self.config.log_max,
            env=self.client.command_env(),
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
        target = (self.file_volume_name, self.file_path)
        def apply(entries):
            if target == (self.file_volume_name, self.file_path):
                self.file_entries = [e for e in entries if e.get("name") not in (".", "..")]
                self.file_index = 0
                self.need_redraw = True
        self._docker_job("view:files", "list_volume_contents", (target[0],), apply, path=target[1])

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

    def start_resource_edit(self, details: Optional[dict] = None, selected: Optional[dict] = None) -> None:
        sel = selected or self.current_selected_container()
        if not sel:
            return
        if details is None:
            if self._running:
                self._docker_job("view:prepare", "get_container_details", (sel["id"],), lambda value: self.start_resource_edit(value, sel))
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
            self._action("update_container_resources",
                sel["id"], cpus=cpus, memory_bytes=memory
            )

        initial = f"cpus={current_cpus}\nmemory_mb={current_mem}"
        self.start_input(
            "Set cpus and memory_mb (one per line):",
            submit,
            initial=initial,
        )

    # ------------------------------------------------------------- container clone

    def start_container_clone(self, details: Optional[dict] = None, selected: Optional[dict] = None) -> None:
        sel = selected or self.current_selected_container()
        if not sel:
            return
        if details is None:
            if self._running:
                self._docker_job("view:prepare", "get_container_details", (sel["id"],), lambda value: self.start_container_clone(value, sel))
                return
            details = self.client.get_container_details(sel["id"])

        def submit(value: str) -> None:
            new_name = value.strip() or f"{sel['name']}-copy"
            ports = details.get("ports", "")
            port_bindings = [line.split(" -> ")[0] for line in ports.splitlines() if "->" in line]
            self._action("clone_container",
                source_id=sel["id"],
                new_name=new_name,
                image=details.get("image", ""),
                port_bindings=port_bindings or None,
            )


        self.start_input(
            f"New name for clone of {sel['name']}: ", submit, initial=f"{sel['name']}-copy"
        )

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
        if self.client.docker_host or self.client.command_env().get("DOCKER_CONTEXT"):
            self.set_status("Cannot switch context: DOCKER_HOST is active and overrides context.")
            return
        if self.current_tab == "contexts" and self.contexts:
            sel_ctx = self.contexts[self.selected_context_index]
            self.set_status(f"Switching Docker context to {sel_ctx['name']}...")
            self._action("use_context", sel_ctx["name"])
            return
        if self.endpoints:
            entry = (
                self.endpoints[self.selected_endpoint_index]
                if hasattr(self, "selected_endpoint_index")
                else self.endpoints[0]
            )
            self._activate_endpoint(entry)

    def _activate_endpoint(self, endpoint: dict[str, str]) -> None:
        host = endpoint.get("host")
        if not host:
            self.set_status("Endpoint has no host.")
            return
        self.jobs.cancel_all()
        self.refresh_in_progress = False
        self.stop_log_stream()
        if self.pull_streamer is not None:
            self.pull_streamer.stop()
            self.pull_streamer = None
        with self.data_lock:
            self.client.set_host(host)
            for name in (
                "containers",
                "images",
                "volumes",
                "networks",
                "contexts",
                "compose_rows",
                "log_lines",
                "details_lines",
                "inspect_lines",
            ):
                setattr(self, name, [])
            self.stats = {}
            self.active_container = None
            self.active_project = None
            self.pinned_view = None
            self.pinned_target = None
            self.pinned_project = None
            self.selected_index = self.selected_compose_index = 0
            self.last_refresh = 0.0
            self.daemon_running = False
            self.last_daemon_check = 0.0
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
        self._action("run_compose_cmd", project, config_file, action, working_dir=row.get("working_dir") or None)

    # ------------------------------------------------------------- mouse / drawing helpers

    def enable_mouse_tracking(self) -> None:
        print("\033[?1000h", end="", flush=True)

    def disable_mouse_tracking(self) -> None:
        print("\033[?1000l", end="", flush=True)


    # ------------------------------------------------------------- view dispatch

    @staticmethod
    def split_viewport_height(height: int) -> int:
        """Content rows of a pinned pane; the pane adds ~7 rows of chrome."""
        return max(4, height // 2 - 8)

    def get_viewport_height(self, height: int) -> int:
        if getattr(self, "_split_screen_mode", False):
            return self.split_viewport_height(height)
        return viewport_height_for(height)

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

    # ------------------------------------------------------------- pinned panes

    def pin_current_view(self) -> None:
        """Pin the logs/details view to the lower half of the dashboard."""
        if self.view_mode not in (ViewMode.LOGS, ViewMode.DETAILS):
            return
        self.pinned_view = self.view_mode
        self.pinned_target = self.active_container
        self.pinned_project = self.active_project
        if self.view_mode == ViewMode.LOGS:
            # A pinned log pane is only useful if it keeps updating.
            self.log_follow = True
        self.view_mode = ViewMode.MAIN
        self.set_status("Pinned pane to the bottom half. Shift+P to unpin.")

    def unpin_view(self) -> None:
        if self.pinned_view == ViewMode.LOGS:
            self.stop_log_stream()
        self.pinned_view = None
        self.pinned_target = None
        self.pinned_project = None

    def _pinned_label(self) -> str:
        if self.pinned_view is None:
            return ""
        kind = "logs" if self.pinned_view == ViewMode.LOGS else "details"
        target = self.pinned_project or (self.pinned_target or {}).get("name", "")
        return f"{kind} {target}".strip()

    # ------------------------------------------------------------- bulk / overlays

    def bulk_start_stop(self) -> None:
        """Start or stop every container matching the current filter (Ctrl+S)."""
        targets = list(self.containers)
        if not targets:
            self.set_status("No containers match the current filter.")
            return
        any_running = any(c.get("state") == "running" for c in targets)
        action = "stop" if any_running else "start"
        affected = [c for c in targets if (c.get("state") == "running") == any_running]
        scope = f"matching '{self.container_filter}'" if self.container_filter else "visible"
        if self.state_filter != StateFilter.ALL.value:
            scope += f", state={self.state_filter}"
        names = ", ".join(c["name"] for c in affected[:5])
        if len(affected) > 5:
            names += f", +{len(affected) - 5} more"
        answer = self.prompt_user(
            f"{action.title()} {len(affected)} {scope} container(s) [{names}]? (y/n): "
        )
        if answer.lower() not in ("y", "yes"):
            self.set_status(f"Bulk {action} canceled.")
            return
        self.set_status(f"Bulk {action}: {len(affected)} container(s)...")
        ids = tuple(c["id"] for c in affected)
        def apply(value):
            ok, msg = value
            self.set_status(f"Bulk {action} finished for {len(ids)} container(s)." if ok else f"Bulk {action} failed: {msg}")
            self.request_refresh()
        self._docker_job("action", "bulk_container_action", (action, list(ids)), apply)

    def _run_hotkey_overlay(self, key: str) -> bool:
        """Run a user-defined `hotkey_overlays` command in the selected container."""
        if self.current_tab not in ("containers", "compose"):
            return False
        command = resolve_hotkey_overlay(self.config.hotkey_overlays, key)
        if command is None:
            return False
        sel = self.current_selected_container()
        if not sel:
            self.set_status("Select a container to run the hotkey command.")
            return True
        if sel.get("state") != "running":
            self.set_status(f"Error: Container {sel['name']} is not running.")
            return True
        self.active_container = sel
        self.exec_command_text = command
        self.set_status(f"Running hotkey command: {command}...")
        self._load_output("exec_output_lines", "exec_command", sel["id"], command)
        self.exec_scroll_index = 0
        self.view_mode = ViewMode.EXEC
        return True

    def draw_current(self) -> None:
        if self.pinned_view and self.view_mode == ViewMode.MAIN:
            self._split_screen_mode = True
            try:
                clear_screen()
                self.draw_main_view()
                size = get_terminal_size()
                print("═" * (size.width - 1))
                orig_view_mode = self.view_mode
                orig_active = self.active_container
                orig_project = self.active_project
                self.view_mode = self.pinned_view
                self.active_container = self.pinned_target
                self.active_project = self.pinned_project
                try:
                    self._dispatch_view(self.pinned_view)
                finally:
                    self.view_mode = orig_view_mode
                    self.active_container = orig_active
                    self.active_project = orig_project
            finally:
                self._split_screen_mode = False
        else:
            self._split_screen_mode = False  # type: ignore
            self._dispatch_view(self.view_mode)

    # ------------------------------------------------------------- interactive exec

    def run_interactive_exec(self, container_id: str, container_name: str, command: str) -> None:
        self.stop_refresh_worker()
        print("\033[H\033[2J", end="", flush=True)
        print(f"=== Starting interactive exec session in container '{container_name}' ===")
        print(f"Command: {command}")
        print("Type 'exit' to end session and return to DockTUI.\n")
        try:
            if os.name == "nt":
                command = command.replace("\\", "\\\\")
            cmd_parts = shlex.split(command, posix=True)
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
            with cooked_terminal():
                subprocess.run(cmd, env=self.client.command_env())
        except Exception as e:
            print(f"Error running interactive session: {e}")
            self.prompt_user("Press Enter to continue...")
        self.start_refresh_worker()
        self.request_refresh()
        self.need_redraw = True

    # ------------------------------------------------------------- key handling

    def _handle_key_main(self, key: str) -> bool:
        if key == "\x13" and self.current_tab in ("containers", "compose"):
            self.bulk_start_stop()
            return True
        if key == "P" and self.pinned_view is not None:
            self.unpin_view()
            self.set_status("Unpinned pane.")
            return True
        if self._run_hotkey_overlay(key):
            return True
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
            self.log_scroll_index = max(
                0, min(self.log_scroll_index + delta, len(self.log_lines) - 1)
            )
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
            self.log_tail_limit = min(
                self.config.log_max, self.log_tail_limit + self.config.log_tail_step
            )
            self.stop_log_stream()
            self.log_lines = []
            self.set_status(f"Increased log limit to {self.log_tail_limit} lines.")
            return True
        if key == "-":
            self.log_tail_limit = max(
                self.config.log_min, self.log_tail_limit - self.config.log_tail_step
            )
            self.stop_log_stream()
            self.log_lines = []
            self.set_status(f"Decreased log limit to {self.log_tail_limit} lines.")
            return True
        if key == "h":
            self._toggle_log_highlights()
            return True
        if key == "p":
            self.pin_current_view()
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
        if key == "p":
            self.pin_current_view()
            return True
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
        if self._handle_scroll_key(
            key, "exec_scroll_index", "exec_output_lines", "", lambda _v: None, back_keys=""
        ):
            return True
        if key == "r":
            sel = self.active_container or self.current_selected_container()
            if sel:
                self.set_status(f"Running command: {self.exec_command_text}...")
                self._load_output("exec_output_lines", "exec_command", sel["id"], self.exec_command_text)
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
                    self._load_output("exec_output_lines", "exec_command", sel["id"], command)
                    self.exec_scroll_index = 0
            return True
        if key in ("q", "\x1b"):
            self.view_mode = ViewMode.MAIN
            return True
        return False

    def _handle_key_system(self, key: str) -> bool:
        if key in ("x", "i", "v", "a"):
            word = {"x": "PRUNE", "i": "IMAGES", "v": "VOLUMES", "a": "ALL"}[key]
            if self.prompt_user(f"Type {word} to confirm prune: ") != word:
                self.set_status("Prune canceled.")
                return True
            method = {"i": "prune_images", "v": "prune_volumes"}.get(key, "prune_system")
            self.system_info_text = ""
            self._action(method, **({"include_volumes": key == "a"} if method == "prune_system" else {}))
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
            self.settings_index = min(
                max(0, len(self.settings_options) - 1), self.settings_index + 1
            )
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
                self.view_mode = ViewMode.IMAGES if self.current_tab == "images" else ViewMode.MAIN  # type: ignore
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
            self.view_mode = ViewMode.IMAGES if self.current_tab == "images" else ViewMode.MAIN  # type: ignore
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
        modes = [
            StateFilter.ALL.value,
            StateFilter.RUNNING.value,
            StateFilter.EXITED.value,
            StateFilter.CREATED.value,
        ]
        self.state_filter = modes[(modes.index(self.state_filter) + 1) % len(modes)]
        self.set_status(f"State filter: {self.state_filter}.")
        self.refresh_data()

    def _rename_container(self, sel: dict[str, str]) -> None:
        new_name = self.prompt_user(f"New name for container {sel['name']}: ")
        if not new_name:
            return
        self.set_status(f"Renaming container {sel['name']} to {new_name}...")
        self._action("rename_container", sel["id"], new_name)

    def _open_logs_view(self) -> None:
        if (
            self.current_tab == "compose"
            and self.compose_rows
            and self.compose_rows[self.selected_compose_index].get("type") == "project"
        ):
            row = self.compose_rows[self.selected_compose_index]
            self.active_project = row["project"]
            self.active_container = None
        else:
            sel = self.current_selected_container()
            if not sel:
                return
            self.active_container = sel
            self.active_project = None
        if self.pinned_view == ViewMode.LOGS:
            self.unpin_view()
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
        if self.pinned_view == ViewMode.DETAILS:
            self.unpin_view()
        self.active_container = sel
        self.set_status(f"Loading details for {sel['name']}...")
        self.details_lines = ["Loading…"]
        def apply(details):
            if self.active_container is sel:
                self.details_lines = self.build_details_lines(sel["id"], details)
                self.need_redraw = True
        self._docker_job("view:details", "get_container_details", (sel["id"],), apply)
        self.details_scroll_index = 0
        self.view_mode = ViewMode.DETAILS

    def _open_inspect_view(self) -> None:
        sel = self.current_selected_container()
        if not sel:
            return
        self.active_container = sel
        self.set_status(f"Inspecting container {sel['name']}...")
        self.inspect_lines = ["Loading…"]
        self._load_output("inspect_lines", "inspect_container", sel["id"])
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
        self.top_lines = ["Loading…"]
        self._load_output("top_lines", "top_container", sel["id"])
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
        choice = (
            self.prompt_user(f"Run command interactively? (y/n) [Default: {default_interactive}]: ")
            .lower()
            .strip()
        )
        if not choice:
            choice = default_interactive
        if choice in ("y", "yes"):
            self.run_interactive_exec(sel["id"], sel["name"], command)
        else:
            self.set_status(f"Running command: {command}...")
            self._load_output("exec_output_lines", "exec_command", sel["id"], command)
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
        if not self.daemon_running:
            self.request_refresh()
            return
        if self.current_tab == "compose" and self.compose_rows:
            row = self.compose_rows[self.selected_compose_index]
            if row.get("type") == "project":
                self._action("bulk_container_action", "restart", [c["id"] for c in row["containers"]])
                return
        sel = self.current_selected_container()
        if sel:
            self._action("restart_container", sel["id"])

    def _start_or_stop_selected(self) -> None:
        if self.current_tab == "compose" and self.compose_rows:
            row = self.compose_rows[self.selected_compose_index]
            if row.get("type") == "project":
                containers = row["containers"]
                running = any(c["state"] == "running" for c in containers)
                self._action("bulk_container_action", "stop" if running else "start", [c["id"] for c in containers if not running or c["state"] == "running"])
                return
        sel = self.current_selected_container()
        if sel:
            self._action("stop_container" if sel["state"] == "running" else "start_container", sel["id"])

    def _delete_current(self) -> None:
        resources = {"images": (self.images, self.selected_image_index, "id", "remove_image"), "volumes": (self.volumes, self.selected_volume_index, "name", "remove_volume"), "networks": (self.networks, self.selected_network_index, "name", "remove_network")}
        entry = resources.get(self.current_tab)
        if not entry:
            return
        items, index, field, method = entry
        if not items:
            return
        target = items[index][field]
        if self.prompt_user(f"Delete {self.current_tab[:-1]} {target}? (y/n): ").lower() in ("y", "yes"):
            self._action(method, target)

    def _handle_compose_action_key(self, key: str) -> bool:
        if not self.compose_rows or self.compose_rows[self.selected_compose_index].get("type") != "project":
            return False
        row = self.compose_rows[self.selected_compose_index]
        action = None
        if key == "u":
            answer = self.prompt_user(f"Run up with --build on project '{row['project']}'? (y/n/c): ").lower()
            if answer in ("y", "yes"):
                action = ComposeAction.UP_BUILD.value
            elif answer in ("n", "no"):
                action = ComposeAction.UP.value
        elif key in ("d", "b"):
            action = ComposeAction.DOWN.value if key == "d" else ComposeAction.BUILD.value
            if self.prompt_user(f"{action.title()} project '{row['project']}'? (y/n): ").lower() not in ("y", "yes"):
                action = None
        else:
            return False
        if action:
            self._run_compose_action(action)
        else:
            self.set_status("Compose action canceled.")
        return True

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
        self.log_highlight_regex = re.compile(
            "|".join(f"(?:{p.pattern})" for p in patterns), re.IGNORECASE
        )
        self.set_status(f"Highlighting {len(patterns)} pattern(s) in logs.")

    # ------------------------------------------------------------- main loop

    def run(self) -> None:
        self._quit_requested = False
        self._running = True
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
                self._drain_ui()
                if self.refresh_requested.is_set():
                    self.refresh_requested.clear()
                    self._schedule_refresh()
                size = get_terminal_size()
                self._viewport_h = viewport_height_for(size.height)

                if self.need_redraw:
                    self.need_redraw = False
                    self.draw_current()

                if self.view_mode == ViewMode.MAIN and (
                    time.time() - self.last_attempt > self.refresh_interval
                ):
                    self.request_refresh()
                log_pinned = self.pinned_view == ViewMode.LOGS and self.view_mode in (
                    ViewMode.MAIN,
                    ViewMode.INPUT,
                )
                if self.view_mode != ViewMode.LOGS and not log_pinned and self.is_log_streaming():
                    self.stop_log_stream()
                if _terminal.RESIZE_REQUESTED:
                    _terminal.RESIZE_REQUESTED = False
                    self.request_refresh()
                    self.need_redraw = True
                if self.status_message != "Use Tab to switch tabs. Up/Down to navigate." and (
                    time.time() - self.status_time > 4
                ):
                    self.status_message = "Use Tab to switch tabs. Up/Down to navigate."
                    self.need_redraw = True

                key = get_key_nonblocking()
                if not key:
                    time.sleep(0.04)
                    continue
                self.need_redraw = True
                if key == "\x1b" and self.jobs.busy:
                    self.jobs.cancel_all()
                    self.refresh_in_progress = False
                    self.set_status("Operation canceled; Docker-side work may already have started.")
                    continue
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
            self._running = False
            self.jobs.shutdown()
            self.stop_log_stream()
            if self.pull_streamer is not None:
                self.pull_streamer.stop()
            self.stop_refresh_worker()
            self.disable_mouse_tracking()
            restore_terminal()
            print(RESET)
