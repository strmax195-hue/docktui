"""Tunable defaults for DockTUI behaviour.

All user-facing knobs (those that an in-app config editor should expose)
are grouped here so that `Config` validation, `cli.py` argparse defaults
and the TUI share a single source of truth.
"""

from typing import Tuple

#: Available color theme presets (used by `argparse` choices and theme cycle order).
AVAILABLE_THEMES: Tuple[str, ...] = ("dark", "light", "high_contrast")

#: Ordered list of top-level tabs shown in the dashboard.
AVAILABLE_TABS: Tuple[str, ...] = (
    "containers",
    "compose",
    "images",
    "volumes",
    "networks",
    "contexts",
)

#: Default theme used when no value is provided in the config file or CLI args.
DEFAULT_THEME: str = "dark"

#: Default refresh interval (seconds) for the dashboard data refresh worker.
DEFAULT_REFRESH_INTERVAL: float = 2.0
DEFAULT_REFRESH_INTERVAL_IMAGES: float = 4.0
DEFAULT_REFRESH_INTERVAL_VOLUMES: float = 10.0
DEFAULT_REFRESH_INTERVAL_NETWORKS: float = 10.0

#: Default timeout (seconds) applied to every `docker` CLI invocation.
DEFAULT_DOCKER_TIMEOUT: float = 10.0

#: Default number of log lines fetched on first log view open / refresh.
DEFAULT_LOG_TAIL_LIMIT: int = 40

#: Step used when the user increases/decreases the log tail limit with `+` / `-`.
DEFAULT_LOG_TAIL_STEP: int = 10

#: Hard upper bound for the log tail limit. The user cannot exceed this via `+`.
DEFAULT_LOG_MAX: int = 500

#: Hard lower bound for the log tail limit. The user cannot go below this via `-`.
DEFAULT_LOG_MIN: int = 10

#: CPU/memory usage (percent) at or above which the bar is rendered in red.
DEFAULT_CPU_ALERT_THRESHOLD: float = 80.0

#: Number of recent exec commands kept in the in-app history.
DEFAULT_EXEC_HISTORY_CAP: int = 10

#: Default delta when scrolling long text views with arrow keys.
DEFAULT_SCROLL_DELTA: int = 1

#: Default delta when scrolling long text views with the mouse wheel.
DEFAULT_SCROLL_DELTA_WHEEL: int = 3

#: Default exec command presets shown in the exec picker.
DEFAULT_EXEC_PRESETS: Tuple[str, ...] = (
    "sh",
    "bash",
    "env",
    "ls -la",
    "cat /etc/os-release",
)

#: Lower bound (seconds) applied to the user-supplied refresh interval.
MIN_REFRESH_INTERVAL: float = 0.5

#: Lower bound (seconds) applied to the user-supplied docker timeout.
MIN_DOCKER_TIMEOUT: float = 1.0

#: Minimum terminal width assumed when the real terminal size cannot be queried.
MIN_TERMINAL_WIDTH: int = 80

#: Minimum terminal height assumed when the real terminal size cannot be queried.
MIN_TERMINAL_HEIGHT: int = 24

#: Number of lines reserved for the title, status and footer bars in views.
VIEWPORT_OVERHEAD: int = 6
