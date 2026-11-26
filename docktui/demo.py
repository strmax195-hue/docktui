"""Bundled offline Docker data for the same triage screen used on live hosts."""

import threading

from .triage import Case, Evidence, Inventory, rank_containers

# Name, image, state, Docker ps status, Compose project, service.
_CONTAINERS = (
    (
        "checkout-api-1",
        "checkout/api:2.8",
        "running",
        "Up 8 minutes (unhealthy)",
        "checkout",
        "api",
    ),
    (
        "checkout-worker-1",
        "checkout/worker:2.8",
        "restarting",
        "Restarting (1) 8 seconds ago",
        "checkout",
        "worker",
    ),
    (
        "reports-export-1",
        "reports/export:1.4",
        "exited",
        "Exited (137) 3 minutes ago",
        "reports",
        "export",
    ),
    ("checkout-db-1", "postgres:16", "running", "Up 2 days (healthy)", "checkout", "db"),
    ("checkout-cache-1", "redis:7", "running", "Up 2 days", "checkout", "cache"),
    ("checkout-seed-1", "checkout/seed:2.8", "exited", "Exited (0) 1 hour ago", "checkout", "seed"),
)

# Entirely local examples. No Docker client, configuration or subprocess is used.
_LOGS = {
    "checkout-api-1": (
        "09:41:03 INFO  Serving HTTP on port 8080\n"
        "09:41:04 INFO  Connected to checkout-db\n"
        "09:41:05 ERROR Schema version 18 required, found 17\n"
        "09:41:10 WARN  GET /ready returned 503"
    ),
    "checkout-worker-1": "09:40:52 INFO  Starting worker\n09:40:52 ERROR Required setting QUEUE_URL is missing",
    "reports-export-1": "09:38:20 INFO  Export started\n09:38:51 WARN  Memory usage reached 498 MiB of 512 MiB",
    "checkout-db-1": "09:10:02 INFO  Database ready to accept connections",
    "checkout-cache-1": "09:10:01 INFO  Ready to accept connections",
    "checkout-seed-1": "08:40:00 INFO  Seed data loaded; exiting successfully",
}


class DemoSource:
    name = "Offline demo"

    def scan(self, cancel: threading.Event) -> Inventory:
        rows = [
            dict(
                id=f"{i:012x}",
                name=name,
                image=image,
                state=state,
                status=status,
                compose_project=project,
                compose_service=service,
            )
            for i, (name, image, state, status, project, service) in enumerate(_CONTAINERS, 1)
        ]
        return Inventory("checkout-lab", rank_containers(rows))

    def evidence(self, inventory: Inventory, case: Case, cancel: threading.Event) -> Evidence:
        details = {"status": case.state, "restart_count": "0"}
        if case.name == "checkout-api-1":
            details.update(
                health="unhealthy",
                health_exit_code="1",
                health_time="09:41:10 UTC",
                health_output="GET /ready -> 503  database schema is behind",
            )
        elif case.name == "checkout-worker-1":
            details.update(restart_count="7", exit_code="1")
        elif case.name == "reports-export-1":
            details.update(oom_killed="true", exit_code="137")
        elif case.name == "checkout-seed-1":
            details["exit_code"] = "0"
        elif case.name == "checkout-db-1":
            details.update(
                health="healthy",
                health_exit_code="0",
                health_time="09:41:10 UTC",
                health_output="accepting connections",
            )
        return Evidence.from_output(details, _LOGS[case.name])
