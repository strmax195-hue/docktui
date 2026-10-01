"""Cross-platform keyboard input and terminal restoration."""

import contextlib
import os
import signal
from collections import deque
from collections.abc import Iterator
from typing import Any, Callable, Optional

RESIZE_REQUESTED = False


def handle_resize(_signum=None, _frame=None):
    global RESIZE_REQUESTED
    RESIZE_REQUESTED = True


_ORIGINAL_RESIZE_HANDLER: Any = None


def _install_resize_handler() -> None:
    global _ORIGINAL_RESIZE_HANDLER
    if hasattr(signal, "SIGWINCH") and _ORIGINAL_RESIZE_HANDLER is None:
        _ORIGINAL_RESIZE_HANDLER = signal.signal(signal.SIGWINCH, handle_resize)


def _restore_resize_handler() -> None:
    global _ORIGINAL_RESIZE_HANDLER
    if _ORIGINAL_RESIZE_HANDLER is not None:
        signal.signal(signal.SIGWINCH, _ORIGINAL_RESIZE_HANDLER)
        _ORIGINAL_RESIZE_HANDLER = None


try:
    import msvcrt  # type: ignore[import-not-found]

    PLATFORM = "windows"

    def init_terminal() -> None:
        _install_resize_handler()
        os.system("")

    def restore_terminal() -> None:
        _restore_resize_handler()
        return None

    @contextlib.contextmanager
    def cooked_terminal() -> Iterator[None]:
        yield

    def get_key_nonblocking() -> Optional[str]:
        if msvcrt.kbhit():  # type: ignore[attr-defined]
            ch = msvcrt.getch()  # type: ignore[attr-defined]
            if ch in (b"\x00", b"\xe0"):
                ch2 = msvcrt.getch()  # type: ignore[attr-defined]
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
    import codecs
    import select
    import sys
    import termios

    PLATFORM = "unix"

    # The terminal stays in cbreak mode (no echo, no line buffering) for the
    # whole session. Toggling raw mode around every poll (the old approach)
    # used TCSAFLUSH, which silently discarded keys pressed between polls and
    # echoed escape sequences such as arrow keys onto the screen.
    _ORIGINAL_TERMIOS: Optional[list[Any]] = None
    _KEY_BUFFER: "deque[str]" = deque()
    _DECODER = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def init_terminal() -> None:
        _install_resize_handler()
        global _ORIGINAL_TERMIOS
        if not sys.stdin.isatty():
            return
        fd = sys.stdin.fileno()
        if _ORIGINAL_TERMIOS is None:
            _ORIGINAL_TERMIOS = termios.tcgetattr(fd)
        attrs = termios.tcgetattr(fd)
        # IXON off so Ctrl+S reaches the app; ICRNL off so Enter arrives as "\r".
        attrs[0] &= ~(termios.IXON | termios.ICRNL)
        attrs[3] &= ~(termios.ICANON | termios.ECHO)
        attrs[6][termios.VMIN] = 1
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

    def restore_terminal() -> None:
        _restore_resize_handler()
        global _ORIGINAL_TERMIOS
        if _ORIGINAL_TERMIOS is None:
            return
        try:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _ORIGINAL_TERMIOS)
        except (termios.error, ValueError, OSError):
            pass
        _ORIGINAL_TERMIOS = None

    def _fill_key_buffer(timeout: float) -> bool:
        """Read whatever bytes are pending on stdin into the key buffer."""
        try:
            fd = sys.stdin.fileno()
            rlist, _, _ = select.select([fd], [], [], timeout)
            if not rlist:
                return False
            data = os.read(fd, 1024)
        except (OSError, ValueError):
            return False
        if not data:
            return False
        _KEY_BUFFER.extend(_DECODER.decode(data))
        return True

    def _next_char(timeout: float = 0.05) -> Optional[str]:
        if not _KEY_BUFFER and not _fill_key_buffer(timeout):
            return None
        return _KEY_BUFFER.popleft() if _KEY_BUFFER else None

    def _read_escape_sequence() -> Optional[str]:
        """Decode the rest of an escape sequence after a leading ESC."""
        intro = _next_char()
        if intro is None:
            return "\x1b"  # a lone Esc key press
        if intro not in ("[", "O"):
            _KEY_BUFFER.appendleft(intro)  # Alt+key: report Esc, keep the key
            return "\x1b"
        final = _next_char()
        if final is None:
            return None
        if final in ("A", "B"):
            return "up" if final == "A" else "down"
        if intro == "[" and final == "M":  # X10 mouse report: 3 more bytes
            data = "".join(c for c in (_next_char(), _next_char(), _next_char()) if c)
            if len(data) == 3:
                cb = ord(data[0])
                if cb == 96:
                    return "scroll_up"
                if cb == 97:
                    return "scroll_down"
            return "mouse"
        # Swallow the remainder of any other CSI sequence (PgUp "5~", F-keys...).
        while intro == "[" and final is not None and not ("@" <= final <= "~"):
            final = _next_char()
        return None

    def get_key_nonblocking() -> Optional[str]:
        ch = _next_char()
        if ch is None:
            return None
        if ch == "\x1b":
            return _read_escape_sequence()
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("\x7f", "\b"):
            return "backspace"
        return ch

    @contextlib.contextmanager
    def cooked_terminal() -> Iterator[None]:
        """Temporarily hand the terminal back in normal (echo, line) mode."""
        was_managed = _ORIGINAL_TERMIOS is not None
        restore_terminal()
        try:
            yield
        finally:
            if was_managed:
                init_terminal()


@contextlib.contextmanager
def interrupt_handler(callback: Callable[[], None]) -> Iterator[None]:
    """Request UI shutdown without interrupting Python thread/lock internals."""
    previous = signal.signal(signal.SIGINT, lambda signum, frame: callback())
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
