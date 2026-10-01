"""Non-interactive reporting: ``docktui status`` and ``docktui check``.

Everything here is a pure function over the dictionaries returned by
`DockerClient.list_containers()` / `DockerClient.get_container_stats()`, so the
logic can be unit-tested without a Docker daemon and reused by scripts, cron
jobs, and monitoring systems (Nagios / Icinga / Zabbix / Sensu exit codes).
"""

import fnmatch
import json
import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Optional

#: Nagios-compatible plugin exit codes.
EXIT_OK = 0
EXIT_WARNING = 1
EXIT_CRITICAL = 2
EXIT_UNKNOWN = 3

LEVEL_NAMES = {
    EXIT_OK: "OK",
    EXIT_WARNING: "WARNING",
    EXIT_CRITICAL: "CRITICAL",
    EXIT_UNKNOWN: "UNKNOWN",
}

#: Exit codes that mean "stopped on purpose" (clean exit or SIGTERM from `docker stop`).
CLEAN_EXIT_CODES = (0, 143)

#: SIGKILL: either the OOM killer or `docker stop` hitting its grace timeout.
SIGKILL_EXIT_CODE = 137

_EXIT_RE = re.compile(r"^(?:Exited|Restarting)\s*\((-?\d+)\)")
_HEALTH_RE = re.compile(r"\((healthy|unhealthy|health: starting)\)")


def container_health(status: str) -> str:
    """Return ``healthy``, ``unhealthy``, ``starting`` or ``""`` from a `docker ps` status."""
    match = _HEALTH_RE.search(status or "")
    if not match:
        return ""
    value = match.group(1)
    return "starting" if value == "health: starting" else value


def container_exit_code(status: str) -> Optional[int]:
    """Return the exit code embedded in ``Exited (N) ...`` / ``Restarting (N) ...``."""
    match = _EXIT_RE.match((status or "").strip())
    return int(match.group(1)) if match else None


def parse_percent(value: Any) -> Optional[float]:
    """Parse ``"12.5%"`` into ``12.5``; return ``None`` for blanks or ``--``."""
    if value is None:
        return None
    text = str(value).strip().rstrip("%").strip()
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def matches_any(name: str, patterns: Sequence[str]) -> bool:
    """Shell-style glob match of a container name against any pattern."""
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


def select_containers(
    containers: list[dict[str, Any]],
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Filter containers by name globs (and Compose project name for ``include``)."""
    selected = []
    for c in containers:
        name = str(c.get("name", ""))
        project = str(c.get("compose_project", ""))
        if include and not (
            matches_any(name, include) or (project and matches_any(project, include))
        ):
            continue
        if exclude and (matches_any(name, exclude) or (project and matches_any(project, exclude))):
            continue
        selected.append(c)
    return selected


def build_rows(
    containers: list[dict[str, Any]],
    stats: Optional[dict[str, dict[str, str]]] = None,
) -> list[dict[str, Any]]:
    """Merge `docker ps` and `docker stats` output into flat, JSON-friendly rows."""
    stats = stats or {}
    rows: list[dict[str, Any]] = []
    for c in containers:
        cid = str(c.get("id", ""))
        name = str(c.get("name", ""))
        st = stats.get(cid) or stats.get(cid[:12]) or stats.get(name) or {}
        status = str(c.get("status", ""))
        rows.append(
            {
                "id": cid[:12],
                "name": name,
                "state": str(c.get("state", "")),
                "status": status,
                "health": container_health(status),
                "exit_code": container_exit_code(status),
                "image": str(c.get("image", "")),
                "compose_project": str(c.get("compose_project", "")),
                "compose_service": str(c.get("compose_service", "")),
                "ports": str(c.get("ports", "")),
                "cpu_percent": parse_percent(st.get("cpu")),
                "mem_percent": parse_percent(st.get("mem_perc")),
                "mem_usage": st.get("memory", ""),
            }
        )
    rows.sort(key=lambda r: (r["compose_project"], r["name"]))
    return rows


@dataclass
class Finding:
    level: int
    container: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["level"] = LEVEL_NAMES[self.level]
        return data


def evaluate(
    rows: list[dict[str, Any]],
    cpu_warn: Optional[float] = None,
    mem_warn: Optional[float] = None,
    require_running: Sequence[str] = (),
) -> list[Finding]:
    """Turn container rows into a list of health findings.

    * CRITICAL: unhealthy healthcheck, restart loop, dead container, crash
      (non-zero exit code other than SIGTERM), or a required container that is
      missing / not running.
    * WARNING: SIGKILL exit (possible OOM), CPU or memory at/above threshold.
    """
    findings: list[Finding] = []
    for row in rows:
        name = row["name"]
        state = row["state"]
        health = row["health"]
        code = row["exit_code"]
        if health == "unhealthy":
            findings.append(Finding(EXIT_CRITICAL, name, "healthcheck reports unhealthy"))
        if state == "restarting":
            findings.append(Finding(EXIT_CRITICAL, name, f"restart loop (last exit code {code})"))
        elif state == "dead":
            findings.append(Finding(EXIT_CRITICAL, name, "container is dead"))
        elif state == "exited" and code is not None and code not in CLEAN_EXIT_CODES:
            if code == SIGKILL_EXIT_CODE:
                findings.append(
                    Finding(EXIT_WARNING, name, "killed with SIGKILL (137): OOM or stop timeout")
                )
            else:
                findings.append(Finding(EXIT_CRITICAL, name, f"exited with code {code}"))
        cpu = row.get("cpu_percent")
        if cpu_warn is not None and cpu is not None and cpu >= cpu_warn:
            findings.append(Finding(EXIT_WARNING, name, f"CPU {cpu:.1f}% >= {cpu_warn:g}%"))
        mem = row.get("mem_percent")
        if mem_warn is not None and mem is not None and mem >= mem_warn:
            findings.append(Finding(EXIT_WARNING, name, f"memory {mem:.1f}% >= {mem_warn:g}%"))

    for pattern in require_running:
        matched = [r for r in rows if fnmatch.fnmatchcase(r["name"], pattern)]
        if not matched:
            findings.append(Finding(EXIT_CRITICAL, pattern, "required container not found"))
        elif not any(r["state"] == "running" for r in matched):
            findings.append(Finding(EXIT_CRITICAL, pattern, "required container is not running"))
    return findings


def overall_level(findings: list[Finding]) -> int:
    return aggregate_levels([f.level for f in findings])


def summarize(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "containers": len(rows),
        "running": sum(1 for r in rows if r["state"] == "running"),
        "exited": sum(1 for r in rows if r["state"] == "exited"),
        "restarting": sum(1 for r in rows if r["state"] == "restarting"),
        "unhealthy": sum(1 for r in rows if r["health"] == "unhealthy"),
    }


def format_check(findings: list[Finding], rows: list[dict[str, Any]]) -> str:
    """Render a Nagios-style plugin output: status line + perfdata, then details."""
    level = overall_level(findings)
    summary = summarize(rows)
    crit = sum(1 for f in findings if f.level == EXIT_CRITICAL)
    warn = sum(1 for f in findings if f.level == EXIT_WARNING)
    if findings:
        headline = f"{crit} critical, {warn} warning"
    else:
        headline = f"{summary['running']}/{summary['containers']} containers running, all healthy"
    perfdata = " ".join(f"{k}={v}" for k, v in summary.items())
    lines = [f"DOCKTUI {LEVEL_NAMES[level]} - {headline} | {perfdata}"]
    for f in sorted(findings, key=lambda f: (-f.level, f.container)):
        lines.append(f"[{LEVEL_NAMES[f.level]}] {f.container}: {f.message}")
    return "\n".join(lines)


def check_json(findings: list[Finding], rows: list[dict[str, Any]]) -> str:
    level = overall_level(findings)
    payload = {
        "status": LEVEL_NAMES[level],
        "exit_code": level,
        "summary": summarize(rows),
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(payload, indent=2)


def _fmt_pct(value: Optional[float]) -> str:
    return "-" if value is None else f"{value:.1f}%"


def _truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)] + "…"


def format_table(
    rows: list[dict[str, Any]], color: bool = False, width: Optional[int] = None
) -> str:
    """Render rows as a compact, `docker ps`-like table.

    With `width` (the terminal width), the trailing STATUS column is shortened
    so rows never wrap.
    """
    if not rows:
        return "No containers found."
    headers: tuple[str, ...] = (
        "NAME",
        "STATE",
        "HEALTH",
        "CPU",
        "MEM",
        "PROJECT",
        "IMAGE",
        "STATUS",
    )
    table: list[tuple[str, ...]] = []
    for r in rows:
        table.append(
            (
                _truncate(r["name"], 32),
                r["state"],
                r["health"] or "-",
                _fmt_pct(r["cpu_percent"]),
                _fmt_pct(r["mem_percent"]),
                _truncate(r["compose_project"] or "-", 20),
                _truncate(r["image"], 36),
                r["status"],
            )
        )
    widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(headers)]
    if width:
        room = width - (sum(widths[:-1]) + 2 * (len(headers) - 1))
        status_w = max(len(headers[-1]), room)
        table = [row[:-1] + (_truncate(row[-1], status_w),) for row in table]
        widths[-1] = min(widths[-1], status_w)

    def paint(cell: str, i: int, raw: tuple[str, ...]) -> str:
        padded = cell.ljust(widths[i]) if i < len(headers) - 1 else cell
        if not color or i not in (1, 2):
            return padded
        value = raw[i]
        if value in ("running", "healthy"):
            return f"\033[32m{padded}\033[0m"
        if value in ("exited", "dead", "unhealthy", "restarting"):
            return f"\033[31m{padded}\033[0m"
        if value in ("paused", "starting", "created"):
            return f"\033[33m{padded}\033[0m"
        return padded

    lines = [
        "  ".join(h.ljust(widths[i]) if i < len(headers) - 1 else h for i, h in enumerate(headers))
    ]
    for row in table:
        lines.append("  ".join(paint(cell, i, row) for i, cell in enumerate(row)))
    summary = summarize(rows)
    lines.append("")
    lines.append(
        f"{summary['containers']} containers: {summary['running']} running, "
        f"{summary['exited']} exited, {summary['restarting']} restarting, "
        f"{summary['unhealthy']} unhealthy"
    )
    return "\n".join(lines)


def aggregate_levels(levels: Sequence[int]) -> int:
    """CRITICAL takes priority, then UNKNOWN, WARNING and OK."""
    priority = {EXIT_OK: 0, EXIT_WARNING: 1, EXIT_UNKNOWN: 2, EXIT_CRITICAL: 3}
    return max(levels, key=lambda level: priority[level], default=EXIT_OK)
