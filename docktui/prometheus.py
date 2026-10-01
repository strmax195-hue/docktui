"""Prometheus textfile exposition with bounded container label cardinality."""

import math
import hashlib
import time
from typing import Optional


def _escape(value: object) -> str:
    text = str(value)
    if len(text) > 128:
        text = text[:111] + '_' + hashlib.sha256(text.encode()).hexdigest()[:16]
    return text.replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def format_metrics(rows: list[dict], endpoint: str = 'local', success: bool = True,
                   collected_at: Optional[float] = None, limit: int = 1000) -> str:
    labels = f'endpoint="{_escape(endpoint)}"'
    definitions = {
        'collection_success': 'Whether Docker collection succeeded (1 or 0).',
        'collection_timestamp_seconds': 'Unix time of successful collection, in seconds.',
        'metrics_truncated': 'Whether per-container metrics exceeded the label limit.',
        'containers': 'Total selected containers.',
        'container_running': 'Whether the container is running (1 or 0).',
        'container_unhealthy': 'Whether the healthcheck is unhealthy (1 or 0).',
        'container_cpu_ratio': 'CPU usage divided by 100 percent; may exceed 1 on multicore hosts.',
        'container_memory_ratio': 'Memory usage divided by 100 percent.',
    }
    lines = []
    for name, help_text in definitions.items():
        lines.extend([f'# HELP docktui_{name} {help_text}', f'# TYPE docktui_{name} gauge'])
    lines.append(f'docktui_collection_success{{{labels}}} {int(success)}')
    if success:
        stamp = time.time() if collected_at is None else collected_at
        lines.extend([f'docktui_collection_timestamp_seconds{{{labels}}} {stamp:g}',
                      f'docktui_containers{{{labels}}} {len(rows)}',
                      f'docktui_metrics_truncated{{{labels}}} {int(len(rows) > limit)}'])
        for row in rows[:max(0, min(limit, 10000))]:
            target = labels + f',container="{_escape(row.get("name", ""))}"'
            lines.extend([f'docktui_container_running{{{target}}} {int(row.get("state") == "running")}',
                          f'docktui_container_unhealthy{{{target}}} {int(row.get("health") == "unhealthy")}'])
            for field, metric in (('cpu_percent', 'cpu'), ('mem_percent', 'memory')):
                value = row.get(field)
                if isinstance(value, (int, float)) and math.isfinite(value):
                    lines.append(f'docktui_container_{metric}_ratio{{{target}}} {value / 100:g}')
    return '\n'.join(lines) + '\n'
