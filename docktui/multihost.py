"""Independent endpoint checks with bounded concurrency and total host deadlines."""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


def check_hosts(endpoints: list[tuple[str, str]], check: Callable,
                workers: int = 4, timeout: float = 10) -> list[dict]:
    def execute(endpoint: tuple[str, str]) -> dict:
        name, host = endpoint
        started = time.monotonic()
        try:
            result = check(name, host, started + timeout)
            return {**result, 'endpoint': name, 'duration_seconds': time.monotonic() - started}
        except Exception as exc:
            return {'endpoint': name, 'status': 'UNKNOWN', 'exit_code': 3,
                    'error': str(exc), 'rows': [], 'duration_seconds': time.monotonic() - started}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 16)), thread_name_prefix='docktui-check') as executor:
        return list(executor.map(execute, endpoints))
