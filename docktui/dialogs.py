"""Modal dialog helpers used by views that need single-line or multi-line text entry.

The legacy dashboard had a single text-input flow embedded in `start_input`.
This module exposes a typed `DialogResult` and a small `TextInputDialog` value
object that views can use without duplicating the prompt / submit / cancel
plumbing.
"""
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class DialogResult:
    """Snapshot of the active dialog state, used by the view layer."""

    prompt: str = ""
    buffer: str = ""
    submit: Optional[Callable[[str], None]] = None
    cancel: Optional[Callable[[], None]] = None


@dataclass
class PickerOption:
    label: str
    value: object
    description: str = ""


def apply_dialog_key(result: DialogResult, key: str) -> bool:
    """Apply a single key press to an active dialog. Returns True if handled."""
    if result is None or not result.prompt:
        return False
    if key == "enter":
        if result.submit is not None:
            result.submit(result.buffer.strip())
        return True
    if key in ("\x1b", "q"):
        if result.cancel is not None:
            result.cancel()
        return True
    if key == "backspace":
        result.buffer = result.buffer[:-1]
        return True
    if len(key) == 1 and key.isprintable():
        result.buffer += key
        return True
    return False
