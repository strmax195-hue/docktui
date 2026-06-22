"""ANSI color/style helpers and theme presets.

This module owns every color code used by the TUI. `apply_theme_colors` mutates
the module-level globals below, and the rest of the application reads them.
"""

import os
from typing import Optional

from .constants import DEFAULT_THEME
from .enums import ThemeName

# Module-level globals, repopulated by `apply_theme_colors`.
RESET = ""
BOLD = ""
CYAN = ""
GREEN = ""
RED = ""
YELLOW = ""
WHITE_ON_BLUE = ""
BG_DARK_GRAY = ""
MAGENTA = ""

# Backwards-compatible alias for callers that still pass the old "high-contrast" form.
_LEGACY_THEME_ALIASES = {
    "high-contrast": ThemeName.HIGH_CONTRAST.value,
    "high_contrast": ThemeName.HIGH_CONTRAST.value,
    "dark": ThemeName.DARK.value,
    "light": ThemeName.LIGHT.value,
}


def _normalize_theme(theme_name: Optional[str]) -> str:
    if not theme_name:
        return DEFAULT_THEME
    candidate = _LEGACY_THEME_ALIASES.get(theme_name, theme_name)
    if candidate not in (
        ThemeName.DARK.value,
        ThemeName.LIGHT.value,
        ThemeName.HIGH_CONTRAST.value,
    ):
        return DEFAULT_THEME
    return candidate


def apply_theme_colors(theme_name: Optional[str] = None) -> str:
    """Populate module-level ANSI color globals for the given theme.

    Returns the normalized theme name actually applied, so callers can record it.
    """
    global RESET, BOLD, CYAN, GREEN, RED, YELLOW, WHITE_ON_BLUE, BG_DARK_GRAY, MAGENTA

    name = _normalize_theme(theme_name)

    if os.environ.get("NO_COLOR"):
        RESET = ""
        BOLD = ""
        CYAN = ""
        GREEN = ""
        RED = ""
        YELLOW = ""
        WHITE_ON_BLUE = ""
        BG_DARK_GRAY = ""
        MAGENTA = ""
        return name

    if name == ThemeName.HIGH_CONTRAST.value:
        RESET = "\033[0m"
        BOLD = "\033[1m"
        CYAN = "\033[96m"
        GREEN = "\033[92m"
        RED = "\033[91m"
        YELLOW = "\033[93m"
        MAGENTA = "\033[95m"
        WHITE_ON_BLUE = "\033[7m"  # reverse video
        BG_DARK_GRAY = ""
    elif name == ThemeName.LIGHT.value:
        RESET = "\033[0m"
        BOLD = "\033[1m"
        CYAN = "\033[34m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        YELLOW = "\033[33m"
        MAGENTA = "\033[35m"
        WHITE_ON_BLUE = "\033[30;47m"
        BG_DARK_GRAY = "\033[37m"
    else:  # dark (default)
        RESET = "\033[0m"
        BOLD = "\033[1m"
        CYAN = "\033[36m"
        GREEN = "\033[32m"
        RED = "\033[31m"
        YELLOW = "\033[33m"
        MAGENTA = "\033[35m"
        WHITE_ON_BLUE = "\033[37;44m"
        BG_DARK_GRAY = "\033[90m"
    return name


def visible_length(text: str) -> int:
    """Return the printed length of `text` ignoring ANSI escape sequences."""
    import re

    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from `text`."""
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)


# Initialize default colors at import time.
apply_theme_colors(DEFAULT_THEME)
