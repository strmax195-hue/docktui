"""Collect immutable-by-convention dashboard data without mutating UI state."""

from dataclasses import dataclass, field
from typing import Any

from .docker_client import DockerClient


@dataclass
class DashboardSnapshot:
    tab: str
    context: str
    items: list[dict[str, Any]]
    stats: dict[str, dict[str, str]] = field(default_factory=dict)


def sort_container_rows(rows: list[dict], needle: str, state: str, sort: str) -> list[dict]:
    if state != "all":
        rows = [row for row in rows if row.get("state") == state]
    if needle:
        rows = [row for row in rows if any(
            needle.lower() in str(row.get(key, "")).lower()
            for key in ("name", "image", "compose_project", "compose_service")
        )]
    if sort in ("name", "image", "state"):
        return sorted(rows, key=lambda row: (row.get(sort, ""), row.get("name", "")))
    return sorted(rows, key=lambda row: (row.get("state") != "running", row.get("name", "")))


def collect_snapshot(
    client: DockerClient, tab: str, needle: str, state: str, sort: str,
) -> DashboardSnapshot:
    context = client.get_current_context()
    if tab in ("containers", "compose"):
        rows = sort_container_rows(client.list_containers(), needle, state, sort)
        stats = client.get_container_stats() if rows else {}
        return DashboardSnapshot(tab, context, rows, stats)
    methods = {"images": "list_images", "volumes": "list_volumes", "networks": "list_networks", "contexts": "list_contexts"}
    fields = {"images": ("repository", "tag", "id"), "volumes": ("name", "driver"), "networks": ("name", "driver", "id"), "contexts": ("name", "description", "endpoint")}
    rows = getattr(client, methods[tab])()
    if needle:
        rows = [row for row in rows if any(needle.lower() in str(row.get(key, "")).lower() for key in fields[tab])]
    return DashboardSnapshot(tab, context, rows)
