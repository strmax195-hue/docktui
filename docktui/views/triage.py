"""Interactive, read-only triage workspace for real and bundled data."""

import shutil
import sys
import time
import unicodedata
from typing import Optional

from .. import styles, terminal
from ..jobs import JobRunner
from ..log_format import colorize_log_line
from ..report import EXIT_CRITICAL, EXIT_OK, LEVEL_NAMES
from ..screen import list_window, navigation_index
from ..triage import Case, Evidence, Inventory, Source, evidence_lines, plain_line


def _cells(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _wrap(line: str, width: int) -> list[str]:
    """Wrap terminal cells without breaking away a combining mark."""
    line = plain_line(line)
    if width == 1:
        line = "".join("…" if _cells(char) > 1 else char for char in line)
    parts = []
    start = used = 0
    for i, char in enumerate(line):
        cells = _cells(char)
        if used and used + cells > width:
            parts.append(line[start:i])
            start = i
            used = 0
        used += cells
    return [*parts, line[start:]]


def _clip(line: str, width: int) -> str:
    if width <= 0:
        return ""
    line = plain_line(line)
    if line.isascii():
        return line if len(line) <= width else line[: width - 1] + "…"
    used = 0
    cut = 0
    for i, char in enumerate(line):
        used += _cells(char)
        if used <= width - 1:
            cut = i + 1
        if used > width:
            return line[:cut] + "…"
    return line


def _style(text: str, color: str) -> str:
    return color + text + styles.RESET if color else text


class TriageScreen:
    def __init__(self, source: Source, interval: float, show_all: bool = False):
        self.source = source
        self.interval = interval
        self.show_all = show_all
        self.jobs = JobRunner()
        self.snapshot: Optional[Inventory] = None
        self.rows: list[Case] = []
        self.index = 0
        self.opened: Optional[tuple[Inventory, Case]] = None
        self.detail: Optional[Evidence] = None
        self.detail_error = ""
        self.error = ""
        self.scroll = 0
        self.last_scroll = 0
        self.page = 1
        self.help = False
        self.dirty = True
        self.scanning = False
        self.next_scan = 0.0

    def close(self) -> None:
        self.jobs.shutdown()

    def _filter(self, selected: Optional[str]) -> None:
        assert self.snapshot is not None
        self.rows = [c for c in self.snapshot.cases if self.show_all or c.level != EXIT_OK]
        self.index = next(
            (i for i, c in enumerate(self.rows) if c.id == selected),
            min(self.index, max(0, len(self.rows) - 1)),
        )

    def _received(self, snapshot: Inventory) -> None:
        selected = (
            self.rows[self.index].id
            if self.rows and self.snapshot and (self.snapshot.connection == snapshot.connection)
            else None
        )
        self.snapshot = snapshot
        self._filter(selected)
        self.error = ""
        self._scan_done()

    def _failed(self, exc: Exception) -> None:
        self.error = plain_line(str(exc))
        self._scan_done()

    def _scan_done(self) -> None:
        self.scanning = False
        self.next_scan = time.monotonic() + self.interval
        self.dirty = True

    def tick(self) -> bool:
        self.jobs.drain(0)
        if not self.opened and not self.scanning and time.monotonic() >= self.next_scan:
            self.scanning = self.jobs.submit(
                "scan", 0, self.source.scan, self._received, self._failed
            )
        dirty, self.dirty = self.dirty, False
        return dirty

    def _read_evidence(self) -> None:
        assert self.opened is not None
        snapshot, case = self.opened

        def received(result: Evidence) -> None:
            self.detail = result
            self.dirty = True

        def failed(exc: Exception) -> None:
            self.detail_error = plain_line(str(exc))
            self.dirty = True

        if self.jobs.submit(
            "evidence",
            0,
            lambda cancel: self.source.evidence(snapshot, case, cancel),
            received,
            failed,
        ):
            self.detail = None
            self.detail_error = ""
            self.scroll = 0
            self.dirty = True

    def key(self, key: str) -> bool:
        """Return False when the caller should leave triage."""
        self.dirty = True
        if key == "q":
            return False
        if self.help:
            if key in ("?", "\x1b"):
                self.help = False
            return True
        if key == "?":
            self.help = True
            return True
        if self.opened:
            if key in ("\x1b", "backspace"):
                self.jobs.cancel_prefix("evidence")
                self.opened = None
                self.detail = None
                self.next_scan = 0
            elif key == "r":
                self._read_evidence()
            else:
                index = navigation_index(key, self.scroll, self.last_scroll, self.page)
                if index is not None:
                    self.scroll = index
            return True
        if key == "\x1b":
            return False
        if key == "r":
            self.next_scan = 0
        elif key == "a":
            selected = self.rows[self.index].id if self.rows else None
            self.show_all = not self.show_all
            if self.snapshot:
                self._filter(selected)
        elif key == "enter" and self.snapshot and self.rows:
            self.opened = (self.snapshot, self.rows[self.index])
            self._read_evidence()
        else:
            index = navigation_index(key, self.index, len(self.rows) - 1, self.page)
            if index is not None:
                self.index = index
        return True

    def _list(self, width: int, available: int) -> list[str]:
        if self.snapshot is None:
            return [
                _clip("Reading containers…" if not self.error else "Inventory unavailable.", width)
            ]
        if not self.rows:
            if self.error:
                return [_clip("Retry with r to check this connection.", width)]
            return [
                _clip(
                    "No health or exit problems reported."
                    if self.snapshot.cases
                    else "No containers found on this connection.",
                    width,
                )
            ]
        case = self.rows[self.index]
        if available == 1:
            return [_clip(f"› {LEVEL_NAMES[case.level]}  {case.name}", width)]
        preview = []
        if available >= 8:
            preview = [
                "",
                _style(_clip(case.name, width), styles.BOLD),
                _clip(case.status, width),
                _clip(f"Image  {case.image}", width),
            ]
            if case.project and available >= 10:
                preview.append(_clip(f"Compose  {case.project} / {case.service or '-'}", width))
        self.page = max(1, available - len(preview) - 1)
        start, end = list_window(len(self.rows), self.index, self.page)
        name_width = max(8, min(max(len(c.name) for c in self.rows), width // 3))
        result = [
            _style(
                _clip(f"  {'LEVEL':8}  {'CONTAINER':<{name_width}}  FINDING / STATUS", width),
                styles.CYAN,
            )
        ]
        for i in range(start, end):
            row = self.rows[i]
            name = _clip(row.name, name_width)
            mark = "›" if i == self.index else " "
            line = _clip(
                f"{mark} {LEVEL_NAMES[row.level]:8}  {name:<{name_width}}  {row.reason}", width
            )
            color = (
                styles.RED if row.level == EXIT_CRITICAL else (styles.YELLOW if row.level else "")
            )
            result.append(_style(line, styles.WHITE_ON_BLUE if i == self.index else color))
        return result + preview

    def render(self, cols: int, height: int) -> list[str]:
        width = max(1, cols - 1)
        height = max(1, height - 1)
        snapshot = self.opened[0] if self.opened else self.snapshot
        connection = f"  /  {snapshot.connection}" if snapshot else ""
        title = f"DockTUI  /  Triage     {self.source.name}{connection}"
        header = [
            _style(_clip(title, width), styles.BOLD + styles.CYAN),
            _style("─" * width, styles.CYAN),
        ]
        if self.help:
            body = [
                "Keyboard help",
                "",
                "↑ / ↓, wheel     Move or scroll",
                "PgUp / PgDn      Move one page",
                "Home / End       Jump to either end",
                "Enter            Read the selected container's probe and logs",
                "a                Switch between incidents and all containers",
                "r                Read the current view again",
                "Esc              Go back",
                "q                Leave triage",
            ]
            footer = "? / Esc  Back"
        elif self.opened:
            case = self.opened[1]
            lines = (
                evidence_lines(case, self.detail)
                if self.detail
                else [
                    f"{LEVEL_NAMES[case.level]}  {case.name}",
                    self.detail_error or "Reading probe and logs…",
                ]
            )
            wrapped = [part for line in lines for part in _wrap(line, width)]
            self.page = max(1, height - len(header) - 2)
            self.last_scroll = max(0, len(wrapped) - self.page)
            self.scroll = min(self.scroll, self.last_scroll)
            body = [
                _style(line, styles.CYAN)
                if line in ("Inspection", "Recent logs")
                else colorize_log_line(line)
                for line in wrapped[self.scroll : self.scroll + self.page]
            ]
            footer = "Esc Back   ↑/↓ Scroll   r Refresh   q Leave"
        else:
            if self.snapshot:
                header.append(_clip(self.snapshot.summary(), width))
                label = "All containers" if self.show_all else "Needs attention"
                position = f"  {self.index + 1}/{len(self.rows)}" if self.rows else ""
                header.append(_style(_clip(label + position, width), styles.BOLD))
            if self.error:
                label = "Stale inventory" if self.snapshot else "Collection failed"
                header.append(_style(_clip(f"{label}  {self.error}", width), styles.YELLOW))
            available = max(1, height - len(header) - 2)
            body = self._list(width, available)
            toggle = "Issues" if self.show_all else "All"
            footer = f"Enter Evidence   ↑/↓ Select   a {toggle}   r Refresh   ? Keys   q Leave"
        lines = (header + [_clip(line, width) if self.help else line for line in body])[
            : max(0, height - 2)
        ]
        footer = _clip(footer, width)
        if height > 1:
            lines.append("─" * width)
        lines.append(_style(footer, styles.CYAN))
        return lines

    def draw(self) -> None:
        size = shutil.get_terminal_size((80, 24))
        frame = "\n".join(self.render(size.columns, size.lines))
        sys.stdout.write("\033[H" + frame.replace("\n", "\033[K\n") + "\033[K\033[J")
        sys.stdout.flush()


def run_screen(screen: TriageScreen) -> None:
    """Standalone terminal lifecycle. The main dashboard can also host this screen."""
    stopping = False

    def stop() -> None:
        nonlocal stopping
        stopping = True

    try:
        with terminal.interrupt_handler(stop):
            terminal.init_terminal()
            try:
                sys.stdout.write("\033[?1049h\033[?25l\033[?1000h")
                while not stopping:
                    changed = screen.tick()
                    if changed or terminal.RESIZE_REQUESTED:
                        terminal.RESIZE_REQUESTED = False
                        screen.draw()
                    key = terminal.get_key_nonblocking()
                    if key and not screen.key(key):
                        break
                    if not key:
                        time.sleep(0.04)
            finally:
                try:
                    sys.stdout.write("\033[?1000l\033[?25h\033[?1049l")
                    sys.stdout.flush()
                finally:
                    terminal.restore_terminal()
    finally:
        screen.close()
