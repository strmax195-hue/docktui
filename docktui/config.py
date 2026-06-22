"""Persistent configuration loaded from disk and editable in-app.

`Config` is a small stdlib-only dataclass that knows how to load itself from
`~/.config/docktui/config.json` (or `~/.docktui.json`), validate the loaded
values, and write itself back. It is the single source of truth for tunable
runtime options and the in-app configuration editor (`Phase 2A`) saves through
this object.
"""

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from .constants import (
    AVAILABLE_THEMES,
    DEFAULT_CPU_ALERT_THRESHOLD,
    DEFAULT_DOCKER_TIMEOUT,
    DEFAULT_EXEC_HISTORY_CAP,
    DEFAULT_EXEC_PRESETS,
    DEFAULT_LOG_MAX,
    DEFAULT_LOG_MIN,
    DEFAULT_LOG_TAIL_LIMIT,
    DEFAULT_LOG_TAIL_STEP,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL_IMAGES,
    DEFAULT_REFRESH_INTERVAL_NETWORKS,
    DEFAULT_REFRESH_INTERVAL_VOLUMES,
    DEFAULT_SCROLL_DELTA,
    DEFAULT_THEME,
)


@dataclass
class Config:
    refresh_interval: float = DEFAULT_REFRESH_INTERVAL
    refresh_interval_images: float = DEFAULT_REFRESH_INTERVAL_IMAGES
    refresh_interval_volumes: float = DEFAULT_REFRESH_INTERVAL_VOLUMES
    refresh_interval_networks: float = DEFAULT_REFRESH_INTERVAL_NETWORKS
    docker_timeout: float = DEFAULT_DOCKER_TIMEOUT
    theme: str = DEFAULT_THEME
    log_tail_limit: int = DEFAULT_LOG_TAIL_LIMIT
    log_tail_step: int = DEFAULT_LOG_TAIL_STEP
    log_max: int = DEFAULT_LOG_MAX
    log_min: int = DEFAULT_LOG_MIN
    cpu_alert_threshold: float = DEFAULT_CPU_ALERT_THRESHOLD
    exec_history_cap: int = DEFAULT_EXEC_HISTORY_CAP
    scroll_delta: int = DEFAULT_SCROLL_DELTA
    exec_presets: List[str] = None  # type: ignore[assignment]
    log_highlights: List[Dict[str, str]] = None  # type: ignore[assignment]
    endpoints: List[Dict[str, str]] = None  # type: ignore[assignment]
    hotkey_overlays: Dict[str, str] = None  # type: ignore[assignment]
    active_endpoint: Optional[str] = None

    _CANDIDATE_PATHS: ClassVar[tuple] = (
        Path.home() / ".config" / "docktui" / "config.json",
        Path.home() / ".docktui.json",
    )

    def __post_init__(self) -> None:
        if self.exec_presets is None:
            self.exec_presets = list(DEFAULT_EXEC_PRESETS)
        if self.log_highlights is None:
            self.log_highlights = []
        if self.endpoints is None:
            self.endpoints = []
        if self.hotkey_overlays is None:
            self.hotkey_overlays = {}

    # ------------------------------------------------------------------ load/save

    @classmethod
    def default_config_path(cls) -> Path:
        """Return the path where `save()` will write."""
        return cls._CANDIDATE_PATHS[0]

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Load configuration from `path` (or the first existing candidate)."""
        target = path
        if target is None:
            for candidate in cls._CANDIDATE_PATHS:
                if candidate.is_file():
                    target = candidate
                    break
        if target is None or not target.is_file():
            return cls()
        try:
            with open(target, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls.from_dict(raw)

    def save(self, path: Optional[Path] = None) -> Path:
        """Persist the configuration to `path` (default: standard config location)."""
        target = path or self.default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
        return target

    # ------------------------------------------------------------------ dict

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Config":
        known = {f.name for f in fields(cls) if not f.name.startswith("_")}
        clean: Dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        # Coerce list fields to the right type to be tolerant of malformed input.
        for key in ("exec_presets", "log_highlights", "endpoints"):
            value = clean.get(key)
            if value is None:
                clean[key] = []
            elif isinstance(value, str):
                clean[key] = [value] if value else []
            elif isinstance(value, list):
                clean[key] = list(value)
            else:
                clean[key] = []
        # Coerce dict fields
        if not isinstance(clean.get("hotkey_overlays"), dict):
            clean["hotkey_overlays"] = {}
        # Normalize theme to a known preset.
        if clean.get("theme") not in AVAILABLE_THEMES:
            clean["theme"] = DEFAULT_THEME
        return cls(**clean)

    # ------------------------------------------------------------------ validation

    def validate(self) -> None:
        """Clamp the config to safe ranges in-place."""
        if self.refresh_interval < 0.5:
            self.refresh_interval = DEFAULT_REFRESH_INTERVAL
        if self.refresh_interval_images < 0.5:
            self.refresh_interval_images = DEFAULT_REFRESH_INTERVAL_IMAGES
        if self.refresh_interval_volumes < 0.5:
            self.refresh_interval_volumes = DEFAULT_REFRESH_INTERVAL_VOLUMES
        if self.refresh_interval_networks < 0.5:
            self.refresh_interval_networks = DEFAULT_REFRESH_INTERVAL_NETWORKS
        if self.docker_timeout < 1.0:
            self.docker_timeout = DEFAULT_DOCKER_TIMEOUT
        if self.log_tail_limit < self.log_min:
            self.log_tail_limit = self.log_min
        if self.log_tail_limit > self.log_max:
            self.log_tail_limit = self.log_max
        if self.cpu_alert_threshold < 0.0 or self.cpu_alert_threshold > 100.0:
            self.cpu_alert_threshold = DEFAULT_CPU_ALERT_THRESHOLD
        if self.exec_history_cap < 0:
            self.exec_history_cap = DEFAULT_EXEC_HISTORY_CAP
        if self.scroll_delta < 1:
            self.scroll_delta = DEFAULT_SCROLL_DELTA
        if self.theme not in AVAILABLE_THEMES:
            self.theme = DEFAULT_THEME
        self.exec_presets = [str(p) for p in (self.exec_presets or []) if str(p).strip()]
        self.log_highlights = [h for h in (self.log_highlights or []) if isinstance(h, dict)]
        self.endpoints = [e for e in (self.endpoints or []) if isinstance(e, dict)]
        self.hotkey_overlays = {str(k): str(v) for k, v in (self.hotkey_overlays or {}).items()}
