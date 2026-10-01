"""Persistent configuration loaded from disk and editable in-app.

`Config` is a small stdlib-only dataclass that knows how to load itself from
`~/.config/docktui/config.json` (or `~/.docktui.json`), validate the loaded
values, and write itself back. It is the single source of truth for tunable
runtime options and the in-app configuration editor (`Phase 2A`) saves through
this object.
"""

import json
import math
import os
import re
import tempfile
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
    log_since: str = ""
    log_until: str = ""
    log_timestamps: bool = False
    log_presets: dict[str, list[dict[str, str]]] = field(default_factory=dict)
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
        errors = Config.validation_errors(raw)
        return "; ".join(errors) if errors else None

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
        data = self.to_dict()
        errors = self.validation_errors(data)
        if errors:
            raise ValueError("; ".join(errors))
        temporary: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent, prefix=".docktui-", delete=False
            ) as fh:
                temporary = Path(fh.name)
                json.dump(data, fh, indent=2, sort_keys=True, allow_nan=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
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
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError
                    clean[key] = int(number) if ftype is int else number
                except (TypeError, ValueError, OverflowError):
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
        for key in ("log_since", "log_until"):
            if not isinstance(clean.get(key, ""), str):
                clean.pop(key, None)
        if not isinstance(clean.get("log_timestamps", False), bool):
            clean.pop("log_timestamps", None)
        if not isinstance(clean.get("log_presets", {}), dict):
            clean.pop("log_presets", None)
        config = cls(**clean)
        config.validate()
        return config

    # ------------------------------------------------------------------ validation

    def validate(self) -> None:
        """Clamp the config to safe ranges in-place."""
        defaults = Config()
        for entry in fields(self):
            if entry.type in (int, float):
                value = getattr(self, entry.name)
                try:
                    valid = not isinstance(value, bool) and math.isfinite(float(value))
                except (TypeError, ValueError, OverflowError):
                    valid = False
                if not valid:
                    setattr(self, entry.name, getattr(defaults, entry.name))
        if self.log_max < 1:
            self.log_max = DEFAULT_LOG_MAX
        if self.log_min < 1 or self.log_min > self.log_max:
            self.log_min = min(DEFAULT_LOG_MIN, self.log_max)
        if self.log_tail_step < 1:
            self.log_tail_step = DEFAULT_LOG_TAIL_STEP
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
        self.log_presets = {
            key: [h for h in highlights if self._valid_highlight(h)]
            for key, highlights in self.log_presets.items()
            if isinstance(key, str) and isinstance(highlights, list)
        }
        self.log_highlights = [h for h in (self.log_highlights or []) if self._valid_highlight(h)]
        self.endpoints = [e for e in (self.endpoints or []) if self._valid_endpoint(e)]
        unique = {e["name"]: e for e in self.endpoints}
        self.endpoints = list(unique.values())
        self.hotkey_overlays = {
            k: v
            for k, v in (self.hotkey_overlays or {}).items()
            if isinstance(k, str) and isinstance(v, str) and k and v.strip()
        }

    @staticmethod
    def _valid_endpoint(value: Any) -> bool:
        return isinstance(value, dict) and all(
            isinstance(value.get(key), str) and bool(value[key].strip()) for key in ("name", "host")
        )

    @staticmethod
    def _valid_highlight(value: Any) -> bool:
        if not isinstance(value, dict) or not isinstance(value.get("pattern"), str):
            return False
        if not isinstance(value.get("label", ""), str):
            return False
        try:
            re.compile(value["pattern"])
        except re.error:
            return False
        return True

    @classmethod
    def validation_errors(cls, raw: dict[str, Any]) -> list[str]:
        """Explain the original values, before runtime fallback or clamping."""
        errors = []
        defaults = cls()
        numeric = {f.name: f for f in fields(cls) if f.type in (int, float)}
        values = dict(raw)
        polls = raw.get("poll_intervals")
        if polls is not None:
            if not isinstance(polls, dict):
                errors.append("poll_intervals must be an object")
            else:
                for resource, key in _POLL_INTERVAL_KEYS.items():
                    if resource in polls and key not in values:
                        values[key] = polls[resource]
        for key, entry in numeric.items():
            if key not in values:
                continue
            value = values[key]
            try:
                number = float(value)
                if isinstance(value, bool) or not math.isfinite(number):
                    raise ValueError
                minimum = 0.5 if key.startswith("refresh_interval") else 1
                if key in ("cpu_alert_threshold", "exec_history_cap"):
                    minimum = 0
                if number < minimum or (entry.type is int and number != int(number)):
                    raise ValueError
                if key == "cpu_alert_threshold" and number > 100:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                errors.append(f"{key} must be finite and within its valid range")
                values[key] = getattr(defaults, key)
        lo = float(values.get("log_min", defaults.log_min))
        hi = float(values.get("log_max", defaults.log_max))
        tail = float(values.get("log_tail_limit", defaults.log_tail_limit))
        if not lo <= tail <= hi:
            errors.append("log_min <= log_tail_limit <= log_max is required")
        names = []
        endpoints = raw.get("endpoints", [])
        if not isinstance(endpoints, list) or any(not cls._valid_endpoint(e) for e in endpoints):
            errors.append("endpoints must contain non-empty string name and host")
        else:
            names = [e["name"] for e in endpoints]
            if len(names) != len(set(names)):
                errors.append("endpoints contain duplicate names")
        active = raw.get("active_endpoint")
        if active is not None and (not isinstance(active, str) or active not in names):
            errors.append("active_endpoint does not name a configured endpoint")
        highlights = raw.get("log_highlights", [])
        if not isinstance(highlights, list) or any(not cls._valid_highlight(h) for h in highlights):
            errors.append("log_highlights must contain valid regular expressions")
        overlays = raw.get("hotkey_overlays", {})
        if not isinstance(overlays, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not k or not v.strip()
            for k, v in overlays.items()
        ):
            errors.append("hotkey_overlays must map keys to non-empty command strings")
        presets = raw.get("log_presets", {})
        if not isinstance(presets, dict) or any(
            not isinstance(k, str)
            or not isinstance(v, list)
            or any(not cls._valid_highlight(h) for h in v)
            for k, v in presets.items()
        ):
            errors.append("log_presets must map target keys to valid highlight patterns")
        for key in ("log_since", "log_until"):
            if not isinstance(raw.get(key, ""), str):
                errors.append(f"{key} must be a Docker time string")
        if not isinstance(raw.get("log_timestamps", False), bool):
            errors.append("log_timestamps must be a boolean")
        return errors
