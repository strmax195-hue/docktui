"""Logs view rendering."""

from typing import Any, Optional

from .. import styles as palette
from ..enums import ViewMode
from ..log_format import colorize_log_line
from ..screen import clear_screen, draw_frame, get_terminal_size, pad_to_viewport, slice_viewport


class LogsViews:
    def draw_logs_view(self: Any) -> None:
        if self.active_project:
            log_title = f"PROJECT LOGS: {self.active_project}"
            target_id: Optional[str] = None
        else:
            sel = self.active_container or (
                self.containers[self.selected_index] if self.containers else None
            )
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
            print(colorize_log_line(line[: width - 1], self.log_highlight_regex))
        pad_to_viewport(len(visible), viewport_height)
        if getattr(self, "_split_screen_mode", False):
            return  # pinned pane: the dashboard footer already shows the keys
        print("\n" + "═" * (width - 1))
        print(
            f"{palette.CYAN}[Up/Down] Scroll | [F] Follow | [Space] Pause | [/] Search | [N] Next | [E] Errors | [H] Highlights | [O] Export | [+/-] Limit | [Esc/L] Back{palette.RESET}"
        )
