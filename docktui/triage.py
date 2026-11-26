"""Read-only container triage shared by the dashboard and plain-text reports."""

import re
import threading
from dataclasses import dataclass
from typing import Optional, Protocol

from .docker_client import DockerClient, DockerError
from .report import EXIT_CRITICAL, EXIT_OK, EXIT_WARNING, LEVEL_NAMES, Finding, build_rows, evaluate

# Preserve line boundaries separately. Styling and other terminal controls from
# a container must never change the triage screen or an exported report.
_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def plain_line(value: str) -> str:
    return "".join(c for c in _ESCAPE.sub("", value).expandtabs(4) if c.isprintable())


@dataclass(frozen=True)
class Case:
    id: str
    name: str
    image: str
    project: str
    service: str
    state: str
    status: str
    level: int
    reasons: tuple[str, ...]

    @property
    def reason(self) -> str:
        return " / ".join(self.reasons) or self.status or self.state


@dataclass
class Inventory:
    connection: str
    cases: list[Case]
    context: str = ""

    def summary(self) -> str:
        critical = sum(c.level == EXIT_CRITICAL for c in self.cases)
        warning = sum(c.level == EXIT_WARNING for c in self.cases)
        return f"{critical} critical  |  {warning} warning  |  {len(self.cases)} containers"


def rank_containers(containers: list[dict]) -> list[Case]:
    rows = build_rows(containers)
    by_name: dict[str, list[Finding]] = {}
    for finding in evaluate(rows):
        by_name.setdefault(finding.container, []).append(finding)
    cases = []
    for row in rows:
        findings = by_name.get(row["name"], [])
        cases.append(
            Case(
                row["id"],
                row["name"],
                row["image"],
                row["compose_project"],
                row["compose_service"],
                row["state"],
                row["status"],
                max((f.level for f in findings), default=EXIT_OK),
                tuple(f.message for f in findings),
            )
        )
    return sorted(cases, key=lambda c: (-c.level, c.name))


@dataclass
class Evidence:
    inspection: list[str]
    logs: list[str]
    incomplete: bool

    @classmethod
    def from_output(cls, details: dict[str, str], output: str, log_error: str = "") -> "Evidence":
        inspection = []
        if "error" in details:
            inspection.append("Inspect unavailable  " + plain_line(details["error"]))
        else:
            state = details.get("status", "")
            if state:
                inspection.append(f"Current state  {state}")
            if state in ("restarting", "exited", "dead") and details.get("exit_code"):
                inspection.append(f"Exit code  {details['exit_code']}")
            if details.get("state_error"):
                inspection.append("Runtime error  " + plain_line(details["state_error"]))
            health = details.get("health", "(none)")
            if health != "(none)":
                inspection.append(f"Health  {health}")
                code = details.get("health_exit_code", "(none)")
                if code != "(none)":
                    inspection.append(f"Last probe  exit {code}  {details.get('health_time', '')}")
                probe = details.get("health_output", "(none)")
                if probe != "(none)":
                    inspection.extend(plain_line(line) for line in probe[:4096].splitlines())
            else:
                inspection.append("No healthcheck recorded.")
            if details.get("oom_killed") == "true":
                inspection.append("Docker recorded an out-of-memory kill.")
            if details.get("restart_count"):
                inspection.append(f"Restart count  {details['restart_count']}")
        logs = [plain_line(line[:4096]) for line in output.splitlines()[-40:]]
        if log_error:
            logs = ["Logs unavailable  " + plain_line(log_error)]
        return cls(
            inspection, logs or ["No recent log lines."], "error" in details or bool(log_error)
        )


class Source(Protocol):
    name: str

    def scan(self, cancel: threading.Event) -> Inventory: ...

    def evidence(self, inventory: Inventory, case: Case, cancel: threading.Event) -> Evidence: ...


class DockerSource:
    name = "Docker"

    def __init__(self, client: DockerClient, context: Optional[str] = None):
        self.client = client.snapshot(context)

    def scan(self, cancel: threading.Event) -> Inventory:
        client = self.client.snapshot()
        client.cancel_event = cancel
        if not client.is_docker_installed():
            raise DockerError("Docker CLI not found. Run 'docktui doctor' or try 'docktui demo'.")
        context = client.command_env().get("DOCKER_CONTEXT", "")
        if not client.docker_host and not context:
            context = client.get_current_context()
            if not context:
                raise DockerError("Cannot determine the Docker context. Run 'docktui doctor'.")
            client = client.snapshot(context)
        return Inventory(
            client.docker_host or context, rank_containers(client.list_containers()), context
        )

    def evidence(self, inventory: Inventory, case: Case, cancel: threading.Event) -> Evidence:
        # Freeze the connection which produced this row, including the implicit Docker context.
        client = self.client.snapshot(inventory.context)
        client.cancel_event = cancel
        details = client.get_container_details(case.id)
        if cancel.is_set():
            raise DockerError("Canceled.")
        try:
            output = client.read_logs(case.id, tail=40)
        except DockerError as exc:
            return Evidence.from_output(details, "", str(exc))
        return Evidence.from_output(details, output)


def case_lines(case: Case) -> list[str]:
    lines = [f"{LEVEL_NAMES[case.level]}  {case.name}", f"Last listed  {case.status or case.state}"]
    if case.project:
        lines.append(f"Compose  {case.project} / {case.service or '-'}")
    lines.append(f"Image  {case.image}    ID  {case.id}")
    lines.extend(case.reasons)
    return lines


def evidence_lines(case: Case, evidence: Evidence) -> list[str]:
    return [
        *case_lines(case),
        "",
        "Inspection",
        *evidence.inspection,
        "",
        "Recent logs",
        *evidence.logs,
    ]


def plain_report(source: Source, target: Optional[str], show_all: bool) -> tuple[str, int]:
    cancel = threading.Event()
    snapshot = source.scan(cancel)
    title = f"DockTUI triage | {source.name} | {snapshot.connection}"
    if target:
        case = next((c for c in snapshot.cases if c.name == target or c.id == target), None)
        if case is None:
            raise DockerError(f"Container '{target}' was not found on {snapshot.connection}.")
        evidence = source.evidence(snapshot, case, cancel)
        lines = [title, "", *evidence_lines(case, evidence)]
        return "\n".join(map(plain_line, lines)), int(evidence.incomplete)
    rows = [c for c in snapshot.cases if show_all or c.level != EXIT_OK]
    lines = [title, snapshot.summary(), ""]
    lines.extend(f"{LEVEL_NAMES[c.level]:8}  {c.name}  {c.reason}" for c in rows)
    if not rows:
        lines.append(
            "No health or exit problems reported." if snapshot.cases else "No containers found."
        )
    return "\n".join(map(plain_line, lines)), 0
