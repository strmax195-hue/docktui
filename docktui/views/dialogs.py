"""Dialogs view rendering."""

from typing import Any

from .. import styles as palette
from ..screen import (
    clear_screen,
    draw_frame,
    get_terminal_size,
    list_window,
    navigation_index,
    pad_to_viewport,
    slice_viewport,
    truncate,
)

# Show the shortcuts for the current screen first, followed by the complete guide.
_HELP_TOPICS = {
    "Dashboard": (
        "Tab / 1–6       Switch resource tabs",
        "↑ / ↓ / wheel   Move the selection",
        "PgUp / PgDn     Move one page • Home / End jumps to either end",
        "/ / c           Set or clear the tab filter",
        "g / m           Refresh data / change color theme",
        "Shift+S         Open settings",
        "? / q           Show keyboard help / quit the dashboard",
    ),
    "Containers and Compose": (
        "l / v / i       Open logs, details or inspect JSON",
        "t / e / x       Show processes, run a command or generate Compose YAML",
        "s / r           Start or stop / restart the selected container or project",
        "o / y           Cycle sort order / state filter",
        "n / Shift+C     Rename / clone a container",
        "w / p           Edit CPU and memory limits / show Docker disk usage",
        "Ctrl+S          Start or stop the filtered set after confirmation",
        "Ctrl+letter     Run a configured container command",
        "u / d / b       Bring a Compose project up, down or build it",
        "Shift+P         Unpin the open pane",
    ),
    "Logs": (
        "f / Space       Toggle follow / pause",
        "/ / n / c       Search, jump to the next match or clear filters",
        "e / h           Toggle errors and warnings / configured highlights",
        "w / t           Set a time window / toggle timestamps",
        "+ / - / g       Change the tail limit / reload logs",
        "p / o           Pin this view / export the buffer",
        "Esc / l         Return to the dashboard",
    ),
    "Container details and output": (
        "↑ / ↓ / wheel   Scroll through the output",
        "e / p           In Details, toggle events / pin the pane",
        "o               Export details, inspect, processes or Compose YAML",
        "r / e           In Exec, run again / choose a different command",
        "Esc             Return to the dashboard",
    ),
    "Images and registry": (
        "f / Enter       Search Docker Hub / pull the highlighted result",
        "d / p           Delete a local image / show Docker disk usage",
        "o               Export search results or pull output",
        "Esc             Leave search or cancel an active pull",
    ),
    "Volumes and networks": (
        "Shift+F         Browse files in the selected volume",
        "Enter           Open the selected directory",
        "Backspace       Go up one directory",
        "o               Export the directory listing",
        "d               Delete the selected volume or network",
    ),
    "Contexts": (
        "Enter / u       Connect to the selected context or named endpoint",
        "n               Add and connect to a named endpoint",
    ),
    "Settings and cleanup": (
        "Enter           Edit the highlighted setting",
        "s / o           Save settings / export displayed settings",
        "x / i / v / a   Prune system, images, volumes or system with volumes",
        "Esc             Return to the dashboard",
    ),
}

_HELP_CONTEXT = {
    "containers": "Containers and Compose",
    "compose": "Containers and Compose",
    "images": "Images and registry",
    "search": "Images and registry",
    "pull_progress": "Images and registry",
    "volumes": "Volumes and networks",
    "networks": "Volumes and networks",
    "files": "Volumes and networks",
    "contexts": "Contexts",
    "logs": "Logs",
    "settings": "Settings and cleanup",
    "system": "Settings and cleanup",
}


class DialogsViews:
    def draw_input_view(self: Any) -> None:
        previous = self.previous_view_mode
        self._dispatch_view(previous)
        hints = "[Ctrl+U] Clear  [Enter] Apply  [Esc] Back"
        if self.input_dialog.multiline:
            hints = "[Ctrl+N] New line  " + hints
        print(f"\n{palette.CYAN}{hints}{palette.RESET}")
        print(
            f"{palette.YELLOW}{palette.BOLD}{self.input_dialog.prompt}{palette.RESET}{self.input_dialog.buffer}",
            end="",
            flush=True,
        )
        if "type to search history" in self.input_dialog.prompt:
            matches = [
                cmd for cmd in self.exec_history if self.input_dialog.buffer.lower() in cmd.lower()
            ]
            if matches:
                print(
                    f"\n{palette.CYAN}Matches: {', '.join(matches[:5])}{palette.RESET}",
                    end="",
                    flush=True,
                )

    def _help_lines(self: Any) -> list[str]:
        context = self.previous_view_mode.value
        if context == "main":
            context = self.current_tab
        first = _HELP_CONTEXT.get(context, "Container details and output")
        lines: list[str] = []
        for title in dict.fromkeys((first, "Dashboard", *_HELP_TOPICS)):
            if lines:
                lines.append("")
            lines.append(title)
            lines.extend(f"  {hint}" for hint in _HELP_TOPICS[title])
        return lines

    def scroll_help(self: Any, key: str) -> None:
        page = max(1, get_terminal_size().height - 6)
        last = max(0, len(self._help_lines()) - page)
        index = navigation_index(key, self.help_scroll_index, last, page)
        if index is not None:
            self.help_scroll_index = index

    def draw_help_view(self: Any) -> None:
        size = get_terminal_size()
        clear_screen()
        lines = self._help_lines()
        page = max(1, size.height - 6)
        start = self.help_scroll_index = min(self.help_scroll_index, max(0, len(lines) - page))
        end = min(len(lines), start + page)
        draw_frame(f"Keyboard help  ·  {start + 1}–{end} of {len(lines)}", size.width)
        for line in lines[start:end]:
            style = palette.BOLD if line and not line.startswith(" ") else ""
            print(f"{style}{line[: size.width - 1]}{palette.RESET}")
        print("─" * (size.width - 1))
        print(
            f"{palette.CYAN}[↑/↓] Scroll  [PgUp/PgDn] Page  [Home/End] Jump  [?/Esc] Back{palette.RESET}"
        )

    def draw_settings_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("DOCKTUI SETTINGS", width)
        print(
            f"{palette.BOLD}Edit the active configuration. Press Enter to edit the highlighted entry.{palette.RESET}"
        )
        print("─" * (width - 1))
        if not self.settings_options:
            self._build_settings_options()
        for idx, option in enumerate(self.settings_options):
            marker = "» " if idx == self.settings_index else "  "
            style = palette.WHITE_ON_BLUE if idx == self.settings_index else ""
            label = option["label"]
            value = option["display"]()
            print(f"{style}{marker}{label:<28} {value}{palette.RESET}")
        print("─" * (width - 1))
        print(
            f"\n{palette.CYAN}[Up/Down] Move | [Enter] Edit | [s] Save | [o] Export | [Esc] Back{palette.RESET}"
        )

    def draw_search_view(self: Any) -> None:
        """Show a simple registry search results picker."""
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        start, end = list_window(
            len(self.search_results), self.search_index, max(1, size.height - 7)
        )
        position = (
            f"  ·  {self.search_index + 1} of {len(self.search_results)}"
            if self.search_results
            else ""
        )
        draw_frame(f"Registry search{position}", width)
        if not self.search_results:
            print(f"{palette.YELLOW}{self.search_message}{palette.RESET}")
        else:
            name_width = min(40, width // 2)
            for idx in range(start, end):
                result = self.search_results[idx]
                marker = "» " if idx == self.search_index else "  "
                style = palette.WHITE_ON_BLUE if idx == self.search_index else ""
                print(
                    f"{style}{marker}{truncate(result['name'], name_width)} {truncate(result.get('description', ''), width - name_width - 4)}{palette.RESET}"
                )
        print("─" * (width - 1))
        print(
            f"{palette.CYAN}[↑/↓] Move  [Enter] Pull  [/] New search  [o] Export  [Esc] Back{palette.RESET}"
        )

    def draw_pull_progress_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame(f"Image pull  ·  {self.pull_image_name}", width)
        page = max(1, size.height - 7)
        last = max(0, len(self.pull_lines) - page)
        start = last if self.pull_follow else min(self.pull_scroll_index, last)
        visible, _, _ = slice_viewport(self.pull_lines, start, page)
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), page)
        print("─" * (width - 1))
        print(self.pull_status[: width - 1])
        back = "Cancel pull" if self.pull_streamer and self.pull_streamer.result is None else "Back"
        print(f"{palette.CYAN}[↑/↓] Scroll  [End] Follow  [o] Export  [Esc] {back}{palette.RESET}")

    def draw_files_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        title = f"Volume files  ·  {self.file_volume_name}  [{self.file_path}]"
        draw_frame(title, width)
        if not self.file_entries:
            print(f"{palette.YELLOW}{self.file_message}{palette.RESET}")
        else:
            start, end = list_window(
                len(self.file_entries), self.file_index, max(1, size.height - 7)
            )
            for idx in range(start, end):
                entry = self.file_entries[idx]
                marker = "» " if idx == self.file_index else "  "
                style = palette.WHITE_ON_BLUE if idx == self.file_index else ""
                kind = "DIR" if entry.get("mode", "").startswith("d") else "FILE"
                print(
                    f"{style}{marker}{kind:<5} {entry.get('name', '')[: width - 9]}{palette.RESET}"
                )
        print("─" * (width - 1))
        print(
            f"{palette.CYAN}[↑/↓] Move  [Enter] Open  [Backspace] Up  [o] Export  [Esc] Back{palette.RESET}"
        )
