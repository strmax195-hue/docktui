"""Log severity and optional pattern highlighting."""

import re
from typing import Optional

from . import styles as palette

ERROR_KEYWORDS = ("error", "warn", "exception")


def _log_matches_filter(line: str, needle: str) -> bool:
    if not needle:
        return True
    return needle.lower() in line.lower()


def _log_is_error_line(line: str) -> bool:
    lowered = line.lower()
    return any(keyword in lowered for keyword in ERROR_KEYWORDS)


_LOG_ERROR_RE = re.compile(
    r"\b(?:ERROR|FATAL|CRITICAL|PANIC|EMERG|ALERT)\b|level=(?:error|fatal|crit)|\bTraceback\b"
)
_LOG_WARN_RE = re.compile(r"\b(?:WARN|WARNING)\b|level=warn")


def colorize_log_line(line: str, highlight: Optional[re.Pattern] = None) -> str:
    """Colour a log line by severity and wrap `highlight` matches in bold magenta."""
    if _LOG_ERROR_RE.search(line):
        base = palette.RED
    elif _LOG_WARN_RE.search(line):
        base = palette.YELLOW
    else:
        base = ""
    text = line
    if highlight is not None:
        text = highlight.sub(lambda m: f"{palette.MAGENTA}{palette.BOLD}{m.group(0)}{palette.RESET}{base}", text)
    if base or text != line:
        return f"{base}{text}{palette.RESET}"
    return text


# ---------------------------------------------------------------------------
# Main dashboard
# ---------------------------------------------------------------------------


