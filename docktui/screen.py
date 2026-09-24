"""Reusable UI primitives shared by every dashboard view.

The legacy TUI open-coded the title/footer frame, screen clearing, terminal size
lookup and viewport scrolling in every `draw_*` method. This module centralizes
those concerns so views can stay focused on their data.
"""

import shutil
from collections.abc import Sequence
from dataclasses import dataclass

from .constants import MIN_TERMINAL_HEIGHT, MIN_TERMINAL_WIDTH, VIEWPORT_OVERHEAD
from .styles import BOLD, CYAN, RESET


@dataclass
class TerminalSize:
    width: int
    height: int


def get_terminal_size() -> TerminalSize:
    """Return the current terminal size, falling back to safe defaults."""
    try:
        cols, rows = shutil.get_terminal_size((MIN_TERMINAL_WIDTH, MIN_TERMINAL_HEIGHT))
        return TerminalSize(
            width=max(MIN_TERMINAL_WIDTH, cols),
            height=max(MIN_TERMINAL_HEIGHT, rows),
        )
    except Exception:
        return TerminalSize(width=MIN_TERMINAL_WIDTH, height=MIN_TERMINAL_HEIGHT)


def clear_screen() -> None:
    """Move the cursor home and clear the visible terminal area."""
    print("\033[2J\033[H", end="")


def draw_frame(title: str, width: int) -> None:
    """Render a centered top frame (top border + title + bottom border)."""
    inner_w = max(0, width - 2)
    pad = max(0, (inner_w - len(title)) // 2)
    right_pad = max(0, inner_w - len(title) - pad)
    print(f"{CYAN}{BOLD}╔" + "═" * inner_w + f"╗{RESET}")
    print(f"{CYAN}{BOLD}║" + " " * pad + title + " " * right_pad + f"║{RESET}")
    print(f"{CYAN}{BOLD}╚" + "═" * inner_w + f"╝{RESET}")


def draw_status_bar(message: str, width: int) -> None:
    """Render the standard status / separator pair used at the bottom of views."""
    sep = "═" * max(1, width - 1)
    print("\n" + sep)
    print(f"{BOLD}Status:{RESET} {message}")
    print(sep)


def slice_viewport(
    lines: Sequence[str],
    scroll_index: int,
    viewport_height: int,
) -> tuple[list[str], int, int]:
    """Return the visible slice of `lines` plus the padding count for empty rows."""
    if viewport_height <= 0:
        return [], 0, 0
    total = len(lines)
    start = max(0, min(scroll_index, max(0, total - 1)))
    end = min(total, start + viewport_height)
    visible = list(lines[start:end])
    return visible, start, end


def list_window(total: int, selected: int, rows: int) -> tuple[int, int]:
    """Return ``(start, end)`` of a `rows`-tall window that keeps `selected` visible.

    The selection is kept roughly centred so long lists scroll smoothly.
    """
    if rows <= 0 or total <= rows:
        return 0, total
    start = min(max(0, selected - rows // 2), total - rows)
    return start, start + rows


def wrap_hints(text: str, width: int, sep: str = " | ") -> list[str]:
    """Wrap a ``"[K] Action | [K] Action"`` hint bar at separators, never mid-word."""
    lines: list[str] = []
    current = ""
    for item in text.split(sep):
        candidate = f"{current}{sep}{item}" if current else item
        if current and len(candidate) > width:
            lines.append(current)
            current = item
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def pad_to_viewport(visible_count: int, viewport_height: int) -> None:
    """Print empty lines so the viewport height stays constant."""
    for _ in range(max(0, viewport_height - visible_count)):
        print("")


def viewport_height_for(height: int, overhead: int = VIEWPORT_OVERHEAD) -> int:
    return max(1, height - overhead)


def truncate(text: str, length: int) -> str:
    """Truncate `text` to `length` characters, padding with spaces on the right."""
    if length <= 0:
        return ""
    if len(text) > length:
        if length <= 3:
            return text[:length]
        return text[: length - 3] + "..."
    return text.ljust(length)


def scroll_step(key: str, wheel_delta: int, arrow_delta: int) -> int:
    """Return the scroll delta for a given key (mouse wheel vs arrow key)."""
    if key in ("scroll_up", "scroll_down"):
        return wheel_delta
    return arrow_delta
