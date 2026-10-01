"""Text view rendering."""

from typing import Any

from .. import styles as palette
from ..enums import ViewMode
from ..screen import clear_screen, draw_frame, get_terminal_size, pad_to_viewport, slice_viewport


class TextViews:
    def _draw_scrollable_text_view(
        self: Any,
        title: str,
        lines: list[str],
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
        print(
            f"{palette.CYAN}[Up/Down] Scroll | [O] Export | [Esc/{back_keys}] Back{palette.RESET}"
        )

    def draw_inspect_view(self: Any) -> None:
        if not self.containers:
            self.view_mode = ViewMode.MAIN
            return
        self._draw_scrollable_text_view(
            f"INSPECT: {(self.active_container or self.containers[self.selected_index])['name']}",
            self.inspect_lines,
            "inspect_scroll_index",
            "I",
        )

    def draw_details_view(self: Any) -> None:
        self._draw_scrollable_text_view(
            "CONTAINER DETAILS [E] events",
            self.details_lines + (["", *self.event_feed.lines()] if self.events_enabled else []),
            "details_scroll_index",
            "V",
        )

    def draw_top_view(self: Any) -> None:
        self._draw_scrollable_text_view(
            "CONTAINER PROCESSES",
            self.top_lines,
            "top_scroll_index",
            "T",
        )

    def draw_compose_snippet_view(self: Any) -> None:
        sel = self.current_selected_container()
        if not sel:
            self.view_mode = ViewMode.MAIN
            return
        if not self.compose_snippet_lines:
            self.compose_snippet_lines = ["Loading…"]
            self._load_output("compose_snippet_lines", "generate_compose_snippet", sel["id"])
            self.compose_snippet_scroll_index = 0
        self._draw_scrollable_text_view(
            f"GENERATE COMPOSE SNIPPET: {sel['name']}",
            self.compose_snippet_lines,
            "compose_snippet_scroll_index",
            "X",
        )

    def draw_exec_view(self: Any) -> None:
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
        visible, _, _ = slice_viewport(
            self.exec_output_lines, self.exec_scroll_index, viewport_height
        )
        for line in visible:
            print(line[: width - 1])
        pad_to_viewport(len(visible), viewport_height)
        print("\n" + "═" * (width - 1))
        print(
            f"{palette.CYAN}[Up/Down] Scroll | [R] Run command again | [E] Run different command | [Esc] Back{palette.RESET}"
        )

    def draw_system_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width
        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        draw_frame("DOCKER SYSTEM DISK USAGE & CLEANUP", width)
        if not self.system_info_text:
            self.system_info_text = "Loading…"
            self._docker_job(
                "view:disk",
                "get_disk_usage",
                (),
                lambda value: setattr(self, "system_info_text", value),
            )
        print(self.system_info_text)
        print(
            f"\n{palette.YELLOW}Preview:{palette.RESET} Docker does not provide a dry-run for prune; review the disk usage above before confirming."
        )
        print("\n" + "═" * (width - 1))
        print(
            f"{palette.CYAN}[X] System prune | [I] Image prune | [V] Volume prune | [A] System prune + volumes | [Esc/P] Back{palette.RESET}"
        )
