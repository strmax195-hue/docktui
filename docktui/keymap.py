"""Cross-platform keyboard input + keymap dispatch.

The legacy TUI had an inline if/elif ladder with hundreds of branches in
`ContainerDashboard.run`. The `Keymap` dataclass here gives views and
key-handlers a structured, testable way to declare their key bindings.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

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

    bindings: List[KeyBinding] = field(default_factory=list)

    def register(self, view: str, key: str, handler: KeyHandler, description: str = "") -> None:
        self.bindings.append(KeyBinding(view=view, key=key, handler=handler, description=description))

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

    def descriptions_for_view(self, view: str) -> List[Tuple[str, str]]:
        """Return [(key, description), ...] for help screens and footers."""
        seen: Dict[str, str] = {}
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
