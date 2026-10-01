"""Persistent configuration loaded from disk and editable in-app.

`Config` is a small stdlib-only dataclass that knows how to load itself from
`~/.config/docktui/config.json` (or `~/.docktui.json`), validate the loaded
values, and write itself back. It is the single source of truth for tunable
runtime options and the in-app configuration editor (`Phase 2A`) saves through
this object.
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, ClassVar, Optional

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

#: Mapping of `poll_intervals` entries to the dataclass fields they set.
_POLL_INTERVAL_KEYS = {
    "containers": "refresh_interval",
    "images": "refresh_interval_images",
    "volumes": "refresh_interval_volumes",
    "networks": "refresh_interval_networks",
}


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
    exec_presets: list[str] = None  # type: ignore[assignment]
    log_highlights: list[dict[str, str]] = None  # type: ignore[assignment]
    endpoints: list[dict[str, str]] = None  # type: ignore[assignment]
    hotkey_overlays: dict[str, str] = None  # type: ignore[assignment]
    active_endpoint: Optional[str] = None
    #: File this config was loaded from; `save()` writes back to it.
    _path: Optional[Path] = field(default=None, repr=False, compare=False)

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

    def resolve_host(self, explicit: Optional[str] = None) -> Optional[str]:
        """Explicit host, Docker environment, configured endpoint, then context."""
        if explicit:
            return explicit
        if os.environ.get("DOCKER_CONTEXT") or os.environ.get("DOCKER_HOST"):
            return None
        if self.active_endpoint:
            for endpoint in self.endpoints:
                if endpoint.get("name") == self.active_endpoint and endpoint.get("host"):
                    return endpoint["host"]
            raise ValueError(f"Unknown or invalid active endpoint: {self.active_endpoint}")
        return None

    # ------------------------------------------------------------------ load/save

    @classmethod
    def candidate_paths(cls) -> tuple[Path, ...]:
        """Config locations in lookup order.

        ``$DOCKTUI_CONFIG`` wins, then ``$XDG_CONFIG_HOME/docktui/config.json``,
        then ``~/.config/docktui/config.json`` and ``~/.docktui.json``.
        """
        paths: list[Path] = []
        env_path = os.environ.get("DOCKTUI_CONFIG")
        if env_path:
            paths.append(Path(env_path).expanduser())
        xdg = os.environ.get("XDG_CONFIG_HOME")
        if xdg:
            paths.append(Path(xdg).expanduser() / "docktui" / "config.json")
        for candidate in cls._CANDIDATE_PATHS:
            if candidate not in paths:
                paths.append(candidate)
        return tuple(paths)

    @classmethod
    def default_config_path(cls) -> Path:
        """Return the path where `save()` writes when no file was loaded."""
        return cls.candidate_paths()[0]

    @classmethod
    def find_existing_path(cls) -> Optional[Path]:
        """Return the first existing config file, or ``None``."""
        for candidate in cls.candidate_paths():
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def read_raw(path: Path) -> dict[str, Any]:
        """Read a config file as a dict; ``{}`` if it is missing or malformed."""
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def validate_file(path: Path) -> Optional[str]:
        """Return a human-readable error for an unreadable config file, else ``None``."""
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except OSError as exc:
            return f"cannot read file ({exc.strerror or exc})"
        except ValueError as exc:
            return f"invalid JSON ({exc})"
        if not isinstance(raw, dict):
            return "top-level value must be a JSON object"
        return None

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Load configuration from `path` (or the first existing candidate)."""
        target = path or cls.find_existing_path()
        if target is None or not target.is_file():
            config = cls()
        else:
            config = cls.from_dict(cls.read_raw(target))
        config._path = target
        return config

    @property
    def path(self) -> Path:
        """Where this config lives on disk (or will be written)."""
        return self._path or self.default_config_path()

    def save(self, path: Optional[Path] = None) -> Path:
        """Persist the configuration to `path` (default: the file it was loaded from)."""
        target = path or self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
        self._path = target
        return target

    # ------------------------------------------------------------------ dict

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        known = {f.name: f for f in fields(cls) if not f.name.startswith("_")}
        clean: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        # `poll_intervals` is a friendlier spelling of the per-resource refresh
        # intervals; explicit `refresh_interval_*` keys take precedence.
        polls = raw.get("poll_intervals")
        if isinstance(polls, dict):
            for resource, key in _POLL_INTERVAL_KEYS.items():
                if resource in polls and key not in clean:
                    clean[key] = polls[resource]
        # Coerce numeric fields; drop values that cannot be parsed so the
        # dataclass default applies instead of crashing later comparisons.
        for key in list(clean):
            ftype = known[key].type
            if ftype in (int, float):
                value = clean[key]
                try:
                    if isinstance(value, bool):
                        raise TypeError
                    clean[key] = int(float(value)) if ftype is int else float(value)
                except (TypeError, ValueError):
                    del clean[key]
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
        # Normalize theme to a known preset (accept the "high-contrast" spelling).
        if clean.get("theme") == "high-contrast":
            clean["theme"] = "high_contrast"
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
