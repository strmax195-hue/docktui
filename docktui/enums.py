"""Enum-style constants for view modes and other stringly-typed states."""

from enum import Enum


class ViewMode(str, Enum):
    """All possible dashboard views."""

    MAIN = "main"
    LOGS = "logs"
    INSPECT = "inspect"
    DETAILS = "details"
    TOP = "top"
    SYSTEM = "system"
    EXEC = "exec"
    INPUT = "input"
    HELP = "help"
    COMPOSE_SNIPPET = "compose_snippet"
    SETTINGS = "settings"
    SEARCH = "search"
    PULL_PROGRESS = "pull_progress"
    FILES = "files"


class ThemeName(str, Enum):
    DARK = "dark"
    LIGHT = "light"
    HIGH_CONTRAST = "high_contrast"


class SortMode(str, Enum):
    DEFAULT = "default"
    NAME = "name"
    IMAGE = "image"
    STATE = "state"


class StateFilter(str, Enum):
    ALL = "all"
    RUNNING = "running"
    EXITED = "exited"
    CREATED = "created"


class ComposeAction(str, Enum):
    UP = "up"
    UP_BUILD = "up-build"
    DOWN = "down"
    BUILD = "build"
    RESTART = "restart"
