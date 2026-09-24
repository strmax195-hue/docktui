"""Regenerate the README screenshots from the *real* DockTUI output.

Runs DockTUI inside a pseudo-terminal, feeds its output through the `pyte`
terminal emulator, and renders the final screen as an SVG "terminal window".
Nothing is hand-drawn, so the images always match the current UI.

Usage (needs Docker, plus `pip install pyte`):

    scripts/demo/up.sh                 # start the demo Compose stacks
    python scripts/screenshots.py      # writes assets/screenshot-*.svg

`pyte` is only needed for this script; DockTUI itself stays dependency-free.
"""

import fcntl
import html
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
from pathlib import Path

import pyte

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

FONT = "ui-monospace, 'SF Mono', 'Cascadia Mono', 'JetBrains Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace"
CELL_W = 8.4
CELL_H = 18.0
FONT_SIZE = 14
PAD = 18
NBSP = "\u00a0"  # keeps runs of spaces intact in SVG text
TITLE_H = 34

# A calm dark palette (close to GitHub dark) for the 16 ANSI colours.
PALETTE = {
    "default_fg": "#c9d1d9",
    "default_bg": "#0d1117",
    "black": "#484f58",
    "red": "#ff7b72",
    "green": "#3fb950",
    "yellow": "#d29922",
    "brown": "#d29922",  # pyte's name for SGR 33 (yellow)
    "blue": "#1f6feb",
    "magenta": "#bc8cff",
    "cyan": "#39c5cf",
    "white": "#b1bac4",
    "brightblack": "#6e7681",
    "brightred": "#ffa198",
    "brightgreen": "#56d364",
    "brightyellow": "#e3b341",
    "brightblue": "#79c0ff",
    "brightmagenta": "#d2a8ff",
    "brightcyan": "#56d4dd",
    "brightwhite": "#f0f6fc",
}


def _color(name: str, default: str) -> str:
    if name == "default":
        return PALETTE[default]
    if name in PALETTE:
        return PALETTE[name]
    if len(name) == 6:
        try:
            int(name, 16)
            return f"#{name}"
        except ValueError:
            pass
    return PALETTE[default]


def run_in_terminal(argv, cols, rows, keys=(), settle=3.0, env=None):
    """Run `argv` in a PTY of `cols` x `rows`, send `keys`, return the pyte screen."""
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(ROOT)
        child_env = {**os.environ, "COLUMNS": str(cols), "LINES": str(rows), **(env or {})}
        child_env.pop("NO_COLOR", None)
        os.execvpe(argv[0], argv, child_env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                try:
                    data = os.read(fd, 65536)
                except OSError:
                    return False
                if not data:
                    return False
                stream.feed(data)
        return True

    pump(settle)
    for key, wait in keys:
        os.write(fd, key.encode())
        pump(wait)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)
    return screen


def shell_session(commands, cols, rows, prompt="admin@prod-1:~$ "):
    """Render several `docktui` CLI invocations as one shell transcript."""
    screen = pyte.Screen(cols, rows)
    stream = pyte.ByteStream(screen)
    for command in commands:
        stream.feed(f"\x1b[32m{prompt}\x1b[0mdocktui {command}\r\n".encode())
        sub = run_in_terminal(
            ["sh", "-c", f"{sys.executable} -m docktui {command}"],
            cols,
            rows,
            settle=4.0,
        )
        used = [y for y in range(rows) if _plain(sub.buffer[y], cols).strip()]
        last = used[-1] if used else -1
        lines = [_line_to_ansi(sub.buffer[y], cols) for y in range(last + 1)]
        for line in lines:
            stream.feed((line + "\r\n").encode())
        stream.feed(b"\r\n")
    stream.feed(f"\x1b[32m{prompt}\x1b[0m\x1b[7m \x1b[0m".encode())
    return screen


_SGR = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "brown": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
    "brightblack": 90,
    "brightred": 91,
    "brightgreen": 92,
    "brightyellow": 93,
    "brightblue": 94,
    "brightmagenta": 95,
    "brightcyan": 96,
    "brightwhite": 97,
}


def _plain(line, cols):
    return "".join(line[x].data for x in range(cols))


def _line_to_ansi(line, cols):
    out, last = [], None
    for x in range(cols):
        char = line[x]
        style = (char.fg, char.bold)
        if style != last:
            codes = ["0"]
            if char.bold:
                codes.append("1")
            if char.fg in _SGR:
                codes.append(str(_SGR[char.fg]))
            out.append(f"\x1b[{';'.join(codes)}m")
            last = style
        out.append(char.data)
    out.append("\x1b[0m")
    return "".join(out).rstrip()


def screen_to_svg(screen, title, trim=True):
    rows = list(range(screen.lines))
    if trim:
        while (
            rows
            and not "".join(screen.buffer[rows[-1]][x].data for x in range(screen.columns)).strip()
        ):
            rows.pop()
    cols = screen.columns
    width = int(cols * CELL_W + PAD * 2)
    height = int(len(rows) * CELL_H + PAD * 2 + TITLE_H)
    bg = PALETTE["default_bg"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
        f"<title>{html.escape(title)}</title>",
        f'<rect width="{width}" height="{height}" rx="10" fill="{bg}"/>',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="10" fill="none" stroke="#30363d"/>',
        f'<path d="M0 {TITLE_H}H{width}" stroke="#30363d"/>',
        '<circle cx="20" cy="17" r="6" fill="#ff5f56"/>',
        '<circle cx="40" cy="17" r="6" fill="#ffbd2e"/>',
        '<circle cx="60" cy="17" r="6" fill="#27c93f"/>',
        f'<text x="{width / 2}" y="22" text-anchor="middle" font-family="{FONT}" '
        f'font-size="13" fill="#8b949e">{html.escape(title)}</text>',
        f'<g font-family="{FONT}" font-size="{FONT_SIZE}" style="white-space:pre">',
    ]
    for row_index, y in enumerate(rows):
        line = screen.buffer[y]
        top = TITLE_H + PAD + row_index * CELL_H
        baseline = top + CELL_H * 0.75
        x = 0
        while x < cols:
            char = line[x]
            fg, bgc = char.fg, char.bg
            if char.reverse:
                fg, bgc = (
                    (bgc if bgc != "default" else "default_bg_as_fg"),
                    (fg if fg != "default" else "white"),
                )
            run_start = x
            text = []
            while x < cols:
                c = line[x]
                same = (c.fg, c.bg, c.bold, c.reverse) == (
                    char.fg,
                    char.bg,
                    char.bold,
                    char.reverse,
                )
                if not same:
                    break
                text.append(c.data or " ")
                x += 1
            left = PAD + run_start * CELL_W
            run_w = (x - run_start) * CELL_W
            if bgc != "default":
                parts.append(
                    f'<rect x="{left:.1f}" y="{top:.1f}" width="{run_w:.1f}" height="{CELL_H}" '
                    f'fill="{_color(bgc, "default_bg")}"/>'
                )
            content = "".join(text)
            if content.strip():
                stripped = content.rstrip()
                if fg == "default_bg_as_fg":
                    fill = PALETTE["default_bg"]
                else:
                    fill = _color(fg, "default_fg")
                weight = ' font-weight="bold"' if char.bold else ""
                parts.append(
                    f'<text x="{left:.1f}" y="{baseline:.1f}" fill="{fill}"{weight} '
                    f'textLength="{len(stripped) * CELL_W:.1f}" lengthAdjust="spacingAndGlyphs">'
                    f"{html.escape(stripped).replace(' ', NBSP)}</text>"
                )
    parts.append("</g></svg>")
    return "\n".join(parts) + "\n"


DOWN = "\x1b[B"


def main():
    py = sys.executable
    ASSETS.mkdir(exist_ok=True)
    shots = {
        "screenshot-dashboard.svg": (
            "docktui — containers with pinned live logs",
            lambda: run_in_terminal(
                [py, "-m", "docktui"],
                118,
                50,
                # Select shop-web-1, open its logs, pin them under the list.
                keys=[(DOWN, 0.4)] * 5 + [("l", 2.0), ("p", 5.0)],
                settle=3.5,
            ),
        ),
        "screenshot-compose.svg": (
            "docktui — Compose projects",
            lambda: run_in_terminal(
                [py, "-m", "docktui"], 118, 26, keys=[("2", 2.0), (DOWN, 1.5)], settle=3.5
            ),
        ),
        "screenshot-cli.svg": (
            "docktui status / check — for scripts, cron and monitoring",
            lambda: shell_session(["status", "check --cpu-warn 90 --require 'shop-db-*'"], 118, 34),
        ),
        "screenshot-doctor.svg": (
            "docktui doctor",
            lambda: shell_session(["doctor"], 118, 24),
        ),
    }
    only = set(sys.argv[1:])
    for filename, (title, make) in shots.items():
        if only and filename not in only:
            continue
        screen = make()
        (ASSETS / filename).write_text(screen_to_svg(screen, title), encoding="utf-8")
        print(f"wrote assets/{filename}")


if __name__ == "__main__":
    main()
