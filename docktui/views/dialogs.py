"""Dialogs view rendering."""

from typing import Any
from .. import styles as palette
from ..screen import clear_screen
from ..screen import draw_frame
from ..screen import get_terminal_size
from ..screen import pad_to_viewport
from ..screen import slice_viewport
from ..screen import truncate


class DialogsViews:
    def draw_input_view(self: Any) -> None:
        previous = self.previous_view_mode
        self._dispatch_view(previous)
        print(
            f"\n{palette.YELLOW}{palette.BOLD}{self.input_dialog.prompt}{palette.RESET}{self.input_dialog.buffer}",
            end="",
            flush=True,
        )
        if "type to search history" in self.input_dialog.prompt:
            matches = [
                cmd for cmd in self.exec_history if self.input_dialog.buffer.lower() in cmd.lower()
            ]
            if matches:
                print(f"\n{palette.CYAN}Matches: {', '.join(matches[:5])}{palette.RESET}", end="", flush=True)

    def draw_help_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("DockTUI Help", width)
        print(f"{palette.BOLD}Global{palette.RESET}")
        print("  Tab / 1-6    Switch tabs")
        print("  Up / Down    Move selection or scroll / Mouse scroll support")
        print("  G            Refresh current data")
        print("  M            Cycle theme color presets (Dark, Light, High-Contrast)")
        print("  Shift+S      Open the Settings editor")
        print("  ?            Open or close this help screen")
        print("  Q / Esc      Quit or return to the previous screen")
        print(f"\n{palette.BOLD}Containers / Compose{palette.RESET}")
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
        print("  Ctrl+S       Bulk start/stop every container matching the filter")
        print("  Ctrl+<key>   Run a custom `hotkey_overlays` command from your config")
        print("  Shift+P      Unpin the pinned logs/details pane")
        print("  O / Y        Cycle sorting and state filters")
        print("  / / C        Apply or clear the tab filter")
        print("  U / D / B    Compose up / down / build on the Compose tab")
        print("  U            Use the selected Docker context")
        print("  N            Create a new endpoint on the Contexts tab")
        print(f"\n{palette.BOLD}Images and cleanup{palette.RESET}")
        print("  D            Delete the selected image / volume / network")
        print("  F            Search & pull a Docker Hub image (on the Images tab)")
        print("  P            Open Docker disk usage and prune view")
        print("  X / I / V / A    Run system, image, volume, or full prune")
        print(f"\n{palette.BOLD}Logs{palette.RESET}")
        print("  F            Toggle follow mode")
        print("  Space        Pause follow mode")
        print("  N            Jump to next search match")
        print("  E            Toggle error/warning-only lines")
        print("  H            Toggle log highlighting / regex")
        print("  + / -        Increase or decrease log tail limit")
        print("  / / C        Apply or clear log filter")
        print("  P            Pin logs (or details) under the dashboard")
        print("  O            Export logs to a local file")
        print("  G            Refresh logs now")
        print("\n" + "═" * (width - 1))
        print(f"{palette.CYAN}[? / Esc / Q] Return to previous screen{palette.RESET}")

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
        print(f"\n{palette.CYAN}[Up/Down] Move | [Enter] Edit | [S] Save & Apply | [Esc] Back{palette.RESET}")

    def draw_search_view(self: Any) -> None:
        """Show a simple registry search results picker."""
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("REGISTRY SEARCH", width)
        if not self.search_results:
            print(f"{palette.YELLOW}No search results. Use the dialog to enter a query.{palette.RESET}")
        else:
            for idx, result in enumerate(self.search_results):
                marker = "» " if idx == self.search_index else "  "
                style = palette.WHITE_ON_BLUE if idx == self.search_index else ""
                print(
                    f"{style}{marker}{result['name']:<40} {truncate(result.get('description', ''), width - 50)}{palette.RESET}"
                )
        print("─" * (width - 1))
        print(f"\n{palette.CYAN}[Up/Down] Move | [Enter] Pull | [Esc] Back{palette.RESET}")

    def draw_pull_progress_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        title = f"PULLING: {self.pull_image_name}"
        draw_frame(title, width)
        visible, _, _ = slice_viewport(
            self.pull_lines, self.pull_scroll_index, max(1, size.height - 6)
        )
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), max(1, size.height - 6))
        print("\n" + "═" * (width - 1))
        print(f"{palette.CYAN}[Esc] Cancel & back{palette.RESET}")

    def draw_files_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        title = f"VOLUME FILES: {self.file_volume_name}  [{self.file_path}]"
        draw_frame(title, width)
        if not self.file_entries:
            print(f"{palette.YELLOW}(empty volume or unreadable){palette.RESET}")
        else:
            for idx, entry in enumerate(self.file_entries):
                marker = "» " if idx == self.file_index else "  "
                style = palette.WHITE_ON_BLUE if idx == self.file_index else ""
                kind = "DIR" if entry.get("mode", "").startswith("d") else "FILE"
                print(f"{style}{marker}{kind:<5} {entry.get('name', '')}{palette.RESET}")
        print("─" * (width - 1))
        print(
            f"\n{palette.CYAN}[Up/Down] Move | [Enter] Open directory | [Backspace] Up | [Esc] Back{palette.RESET}"
        )

