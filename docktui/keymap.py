"""Cross-platform keyboard input + keymap dispatch.

The legacy TUI had an inline if/elif ladder with hundreds of branches in
`ContainerDashboard.run`. The `Keymap` dataclass here gives views and
key-handlers a structured, testable way to declare their key bindings.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

KeyHandler = Callable[[str], None]


@dataclass
class KeyBinding:
    """A single key binding scoped to a particular view mode."""

    view: str
    key: str
    handler: KeyHandler
    description: str = ""


@dataclass
class Keymap:
    """Registry of (view, key) -> handler mappings."""

    bindings: list[KeyBinding] = field(default_factory=list)

    def register(self, view: str, key: str, handler: KeyHandler, description: str = "") -> None:
        self.bindings.append(
            KeyBinding(view=view, key=key, handler=handler, description=description)
        )

    def register_global(self, key: str, handler: KeyHandler, description: str = "") -> None:
        self.register(view="*", key=key, handler=handler, description=description)

    def dispatch(self, view: str, key: str) -> bool:
        """Invoke the most specific matching handler. Returns True if handled."""
        # Try exact view first, then global ("*") fallback.
        for candidate_view in (view, "*"):
            for binding in self.bindings:
                if binding.view == candidate_view and _key_matches(binding.key, key):
                    binding.handler(key)
                    return True
        return False

    def descriptions_for_view(self, view: str) -> list[tuple[str, str]]:
        """Return [(key, description), ...] for help screens and footers."""
        seen: dict[str, str] = {}
        for binding in self.bindings:
            if binding.view in (view, "*") and binding.description:
                if binding.key not in seen or binding.view != "*":
                    seen[binding.key] = binding.description
        return list(seen.items())


def _key_matches(spec: str, key: str) -> bool:
    """Match a single key or a `|`-separated list of aliases."""
    if spec == key:
        return True
    return key in [alias.strip() for alias in spec.split("|") if alias.strip()]


#: Control keys that DockTUI or the terminal already use and cannot be overlaid:
#: Ctrl+C (SIGINT), Ctrl+H (backspace), Ctrl+I (Tab), Ctrl+J/M (Enter),
#: Ctrl+S (bulk start/stop), Ctrl+Z (suspend), Ctrl+\\ (SIGQUIT).
RESERVED_CTRL_KEYS = frozenset("chijmsz\\")


def parse_hotkey(spec: str) -> str:
    """Translate a config hotkey like ``"ctrl+l"`` into the key string the TUI sees.

    Returns ``""`` for specs that are unsupported or reserved.
    """
    text = spec.strip().lower().replace(" ", "")
    for prefix in ("ctrl+", "ctrl-", "c-", "^"):
        if text.startswith(prefix):
            letter = text[len(prefix) :]
            if len(letter) == 1 and "a" <= letter <= "z" and letter not in RESERVED_CTRL_KEYS:
                return chr(ord(letter) - ord("a") + 1)
            return ""
    return ""


def resolve_hotkey_overlay(overlays: dict[str, str], key: str) -> Optional[str]:
    """Return the command bound to `key` in the user's ``hotkey_overlays``, if any."""
    if not key or len(key) != 1 or ord(key) >= 32:
        return None
    for spec, command in (overlays or {}).items():
        if command and parse_hotkey(spec) == key:
            return command
    return None
