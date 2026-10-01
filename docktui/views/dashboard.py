"""Dashboard view rendering."""

import time
from typing import Any

from .. import styles as palette
from ..enums import StateFilter
from ..screen import (
    clear_screen,
    draw_frame,
    draw_status_bar,
    get_terminal_size,
    list_window,
    truncate,
    wrap_hints,
)


class DashboardViews:
    def draw_main_view(self: Any) -> None:
        size = get_terminal_size()
        width = size.width

        if not getattr(self, "_split_screen_mode", False):
            clear_screen()
        if self.client.docker_host:
            parsed = self.client.parse_docker_host()
            host_display = parsed["display"] if parsed else self.client.docker_host
            context_text = (
                f" [{self.current_context} ({host_display})]"
                if self.current_context
                else f" [{host_display}]"
            )
        else:
            context_text = f" [{self.current_context}]" if self.current_context else ""
        title_text = f"DockTUI Container Dashboard{context_text}"
        draw_frame(title_text, width)

        if not self.client.is_docker_installed():
            print(f"\n{palette.RED}{palette.BOLD}Error: Docker CLI not found.{palette.RESET}")
            print("Please make sure Docker is installed and in your system PATH.")
            print("\nPress 'q' to quit.")
            return

        if not self.is_daemon_running_cached():
            print(
                f"\n{palette.YELLOW}{palette.BOLD}Warning: Cannot connect to the Docker daemon.{palette.RESET}"
            )
            print("Please make sure Docker Desktop or the docker service is running.")
            print("\nPress 'q' to quit, or 'r' to retry connection.")
            return

        if self.refresh_error:
            age = (
                f"{max(0, time.time() - self.last_refresh):.0f}s old"
                if self.last_refresh
                else "unavailable"
            )
            print(truncate(f"STALE ({age}): {self.refresh_error}", width))
        self._draw_tab_header(width)
        self._list_clipped = None
        if self.current_tab == "containers":
            self._draw_containers_tab(width)
        elif self.current_tab == "compose":
            self._draw_compose_tab(width)
        elif self.current_tab == "images":
            self._draw_images_tab(width)
        elif self.current_tab == "volumes":
            self._draw_volumes_tab(width)
        elif self.current_tab == "networks":
            self._draw_networks_tab(width)
        elif self.current_tab == "contexts":
            self._draw_contexts_tab(width)

        status = self.status_message
        if self._list_clipped:
            start, end, total = self._list_clipped
            status = f"{status}  [rows {start + 1}-{end} of {total}]"
        pinned = self._pinned_label()
        if pinned:
            status = f"{status}  [pinned: {pinned}, Shift+P to unpin]"
        draw_status_bar(status, width)
        self._draw_main_footer()

    def _draw_tab_header(self: Any, width: int) -> None:
        tab_labels = {
            "containers": "Containers",
            "compose": "Compose",
            "images": "Images",
            "volumes": "Volumes",
            "networks": "Networks",
            "contexts": "Contexts",
        }
        header_parts: list[str] = []
        for idx, tab in enumerate(self.tabs, start=1):
            label = f"{tab_labels[tab]} ({idx})"
            header_parts.append(
                f"{palette.WHITE_ON_BLUE} {label} {palette.RESET}"
                if tab == self.current_tab
                else f"[{label}]"
            )
        filter_bits: list[str] = []
        active_filter = self.filters.get(self.current_tab, "")
        if active_filter:
            filter_bits.append(f"filter: {active_filter}")
        if self.current_tab in ("containers", "compose"):
            if self.state_filter != StateFilter.ALL.value:
                filter_bits.append(f"state: {self.state_filter}")
            if self.sort_mode != "default":
                filter_bits.append(f"sort: {self.sort_mode}")
        filter_status = "    [" + " | ".join(filter_bits) + "]" if filter_bits else ""
        print("   ".join(header_parts) + filter_status)
        print("─" * (width - 1))

    def _list_window(self: Any, total: int, selected: int, reserved: int) -> tuple[int, int]:
        """Visible slice of a dashboard list; `reserved` is the non-list chrome height."""
        height = get_terminal_size().height
        if self.pinned_view is not None:
            height -= self.split_viewport_height(height) + 7
        start, end = list_window(total, selected, max(3, height - reserved))
        self._list_clipped = (start, end, total) if (start, end) != (0, total) else None
        return start, end

    @staticmethod
    def _state_cell(state: str, row_style: str = "") -> str:
        """A 10-wide container state cell, coloured unless the row is highlighted."""
        padded = f"{state:<10}"
        if row_style:
            return padded
        if state == "running":
            color = palette.GREEN
        elif state in ("exited", "dead"):
            color = palette.RED
        else:
            color = palette.YELLOW
        return f"{color}{padded}{palette.RESET}"

    def _draw_containers_tab(self: Any, width: int) -> None:
        if not self.containers:
            if self.container_filter:
                print(
                    f"\n{palette.CYAN}No containers match the active filter: '{self.container_filter}'{palette.RESET}"
                )
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("containers", width)
            return
        rem = width - 26
        name_w = max(15, int(rem * 0.30))
        image_w = max(15, int(rem * 0.30))
        status_w = max(15, rem - name_w - image_w)

        header_line = f"{palette.BOLD}{'ID':<12} {truncate('NAME', name_w)} {truncate('IMAGE', image_w)} {'STATE':<10} {truncate('STATUS', status_w)}{palette.RESET}"
        print(header_line)
        print("─" * (width - 1))
        start, end = self._list_window(len(self.containers), self.selected_index, reserved=19)
        for idx, c in list(enumerate(self.containers))[start:end]:
            style = palette.WHITE_ON_BLUE if idx == self.selected_index else ""
            state = c["state"]
            padded_state = f"{state:<10}"
            state_formatted = self._state_cell(state)
            status_cell = truncate(c["status"], status_w)
            if "(unhealthy)" in c["status"] or state == "restarting":
                status_cell = f"{palette.RED}{status_cell}{palette.RESET}"
            if idx == self.selected_index:
                state_formatted = padded_state
                status_cell = truncate(c["status"], status_w)
                name_str = f"» {c['name']}"
            else:
                name_str = f"  {c['name']}"
            line = f"{style}{c['id'][:10]:<12} {truncate(name_str, name_w)} {truncate(c['image'], image_w)} {state_formatted} {status_cell}{palette.RESET}"
            print(line)
        print("─" * (width - 1))

        sel = self.containers[self.selected_index]
        c_id = sel["id"]
        print(f"\n{palette.CYAN}{palette.BOLD}CONTAINER RESOURCE USAGE:{palette.RESET}")
        c_stats = self.stats.get(c_id) or self.stats.get(sel["name"])
        if c_stats and sel["state"] == "running":
            cpu_bar, cpu_high = self._percentage_bar(c_stats["cpu"], width=int(width * 0.2))
            mem_bar, mem_high = self._percentage_bar(c_stats["mem_perc"], width=int(width * 0.2))
            cpu_color = palette.RED if cpu_high else palette.GREEN
            mem_color = palette.RED if mem_high else palette.GREEN
            cpu_alert = f" {palette.RED}{palette.BOLD}[HIGH CPU]{palette.RESET}" if cpu_high else ""
            mem_alert = (
                f" {palette.RED}{palette.BOLD}[HIGH MEMORY]{palette.RESET}" if mem_high else ""
            )
            print(f"  CPU:  {cpu_color}{cpu_bar}{palette.RESET}{cpu_alert}")
            print(f"  MEM:  {mem_color}{mem_bar} ({c_stats['memory']}){palette.RESET}{mem_alert}")
            print(f"  NET:  {palette.GREEN}{c_stats['net']}{palette.RESET}")
        else:
            status_text = (
                "N/A (container stopped)" if sel["state"] != "running" else "Loading stats..."
            )
            print(f"  Usage statistics: {palette.YELLOW}{status_text}{palette.RESET}")

    def _draw_compose_tab(self: Any, width: int) -> None:
        if not self.compose_rows:
            self.draw_empty_state("compose", width)
            return
        service_w = max(18, int(width * 0.25))
        name_w = max(18, int(width * 0.25))
        image_w = max(20, int(width * 0.25))
        print(
            f"{palette.BOLD}{truncate('PROJECT / SERVICE', service_w)} {truncate('CONTAINER', name_w)} {'STATE':<10} {truncate('IMAGE', image_w)}{palette.RESET}"
        )
        print("─" * (width - 1))
        start, end = self._list_window(
            len(self.compose_rows), self.selected_compose_index, reserved=13
        )
        for idx, row in list(enumerate(self.compose_rows))[start:end]:
            style = palette.WHITE_ON_BLUE if idx == self.selected_compose_index else ""
            if row["type"] == "project":
                project = str(row["project"])
                count = len(row["containers"])  # type: ignore[arg-type]
                print(
                    f"{style}{palette.BOLD}{truncate(project + '  (' + str(count) + ')', service_w)} {truncate('', name_w)} {'':<10} {truncate('', image_w)}{palette.RESET}"
                )
            else:
                container = row["container"]  # type: ignore[assignment]
                service = container.get("compose_service") or "(standalone)"
                state = container.get("state", "")
                marker = "» " if idx == self.selected_compose_index else "  "
                print(
                    f"{style}{truncate(marker + service, service_w)} "
                    f"{truncate(container.get('name', ''), name_w)} "
                    f"{self._state_cell(state, style)} "
                    f"{truncate(container.get('image', ''), image_w)}{palette.RESET}"
                )

    def _draw_images_tab(self: Any, width: int) -> None:
        if not self.images:
            active_filter = self.filters.get("images")
            if active_filter:
                print(
                    f"\n{palette.CYAN}No images match the active filter: '{active_filter}'{palette.RESET}"
                )
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("images", width)
            return
        rem = width - 26
        repo_w = max(20, int(rem * 0.45))
        tag_w = max(12, int(rem * 0.25))
        size_w = max(10, rem - repo_w - tag_w)
        header_line = f"{palette.BOLD}{'IMAGE ID':<12} {truncate('REPOSITORY', repo_w)} {truncate('TAG', tag_w)} {truncate('SIZE', size_w)}{palette.RESET}"
        print(header_line)
        print("─" * (width - 1))
        start, end = self._list_window(len(self.images), self.selected_image_index, reserved=13)
        for idx, img in list(enumerate(self.images))[start:end]:
            style = palette.WHITE_ON_BLUE if idx == self.selected_image_index else ""
            repo_str = (
                f"» {img['repository']}"
                if idx == self.selected_image_index
                else f"  {img['repository']}"
            )
            line = f"{style}{img['id'][:10]:<12} {truncate(repo_str, repo_w)} {truncate(img['tag'], tag_w)} {truncate(img['size'], size_w)}{palette.RESET}"
            print(line)
        print("─" * (width - 1))

    def _draw_volumes_tab(self: Any, width: int) -> None:
        if not self.volumes:
            active_filter = self.filters.get("volumes")
            if active_filter:
                print(
                    f"\n{palette.CYAN}No volumes match the active filter: '{active_filter}'{palette.RESET}"
                )
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("volumes", width)
            return
        name_w = max(30, int(width * 0.50))
        driver_w = max(12, int(width * 0.20))
        print(
            f"{palette.BOLD}{truncate('VOLUME', name_w)} {truncate('DRIVER', driver_w)} {'SCOPE':<12}{palette.RESET}"
        )
        print("─" * (width - 1))
        start, end = self._list_window(len(self.volumes), self.selected_volume_index, reserved=13)
        for idx, volume in list(enumerate(self.volumes))[start:end]:
            style = palette.WHITE_ON_BLUE if idx == self.selected_volume_index else ""
            marker = "» " if idx == self.selected_volume_index else "  "
            print(
                f"{style}{truncate(marker + volume['name'], name_w)} {truncate(volume['driver'], driver_w)} {volume['scope']:<12}{palette.RESET}"
            )
        print("─" * (width - 1))

    def _draw_networks_tab(self: Any, width: int) -> None:
        if not self.networks:
            active_filter = self.filters.get("networks")
            if active_filter:
                print(
                    f"\n{palette.CYAN}No networks match the active filter: '{active_filter}'{palette.RESET}"
                )
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("networks", width)
            return
        name_w = max(30, int(width * 0.45))
        driver_w = max(12, int(width * 0.20))
        print(
            f"{palette.BOLD}{'ID':<12} {truncate('NETWORK', name_w)} {truncate('DRIVER', driver_w)} {'SCOPE':<12}{palette.RESET}"
        )
        print("─" * (width - 1))
        start, end = self._list_window(len(self.networks), self.selected_network_index, reserved=13)
        for idx, network in list(enumerate(self.networks))[start:end]:
            style = palette.WHITE_ON_BLUE if idx == self.selected_network_index else ""
            marker = "» " if idx == self.selected_network_index else "  "
            print(
                f"{style}{network['id'][:10]:<12} {truncate(marker + network['name'], name_w)} {truncate(network['driver'], driver_w)} {network['scope']:<12}{palette.RESET}"
            )
        print("─" * (width - 1))

    def _draw_contexts_tab(self: Any, width: int) -> None:
        if self.client.docker_host:
            print(
                f"{palette.YELLOW}{palette.BOLD}Note: DOCKER_HOST is active. Context switching is bypassed (DOCKER_HOST overrides context).{palette.RESET}"
            )
            print("─" * (width - 1))
        if not self.contexts:
            active_filter = self.filters.get("contexts")
            if active_filter:
                print(
                    f"\n{palette.CYAN}No contexts match the active filter: '{active_filter}'{palette.RESET}"
                )
                print("Press [C] to clear the filter.")
            else:
                self.draw_empty_state("contexts", width)
            return
        name_w = max(20, int(width * 0.25))
        desc_w = max(24, int(width * 0.30))
        endpoint_w = max(24, width - name_w - desc_w - 14)
        print(
            f"{palette.BOLD}{truncate('CONTEXT', name_w)} {'CUR':<5} {truncate('DESCRIPTION', desc_w)} {truncate('ENDPOINT', endpoint_w)}{palette.RESET}"
        )
        print("─" * (width - 1))
        start, end = self._list_window(len(self.contexts), self.selected_context_index, reserved=14)
        for idx, context in list(enumerate(self.contexts))[start:end]:
            style = palette.WHITE_ON_BLUE if idx == self.selected_context_index else ""
            marker = "» " if idx == self.selected_context_index else "  "
            print(
                f"{style}{truncate(marker + context['name'], name_w)} "
                f"{context['current']:<5} {truncate(context['description'], desc_w)} "
                f"{truncate(context['endpoint'], endpoint_w)}{palette.RESET}"
            )
        print("─" * (width - 1))

    def _main_footer_hints(self: Any) -> str:
        if self.current_tab == "compose":
            row = self.compose_rows[self.selected_compose_index] if self.compose_rows else None
            if row and row.get("type") == "project":
                return "[U] Up | [D] Down | [B] Build | [R] Restart | [L] Project Logs | [Tab] Switch | [?] Help | [Q] Quit"
            else:
                return "[S] Start/Stop | [R] Restart | [L] Logs | [V] Details | [I] Inspect | [E] Exec | [X] Compose | [W] Resources | [O] Sort | [Y] State | [Ctrl+S] Bulk Start/Stop | [Shift+S] Settings | [?] Help | [Q] Quit"
        elif self.current_tab == "containers":
            return "[S] Start/Stop | [R] Restart | [L] Logs | [V] Details | [I] Inspect | [E] Exec | [X] Compose | [W] Resources | [Shift+C] Clone | [O] Sort | [Y] State | [Ctrl+S] Bulk Start/Stop | [Shift+S] Settings | [?] Help | [Q] Quit"
        elif self.current_tab == "images":
            return "[D] Delete | [F] Search & Pull | [P] Disk/Prune | [Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit"
        elif self.current_tab == "volumes":
            return "[D] Delete | [Shift+F] Browse Files | [P] Disk/Prune | [Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit"
        elif self.current_tab == "networks":
            return (
                "[D] Delete | [Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit"
            )
        elif self.current_tab == "contexts":
            return "[U] Use | [N] New Endpoint | [Shift+S] Settings | [Tab] Switch | [G] Refresh | [?] Help | [Q] Quit"
        else:
            return "[Tab] Switch | [G] Refresh | [Shift+S] Settings | [?] Help | [Q] Quit"

    def _draw_main_footer(self: Any) -> None:
        width = get_terminal_size().width
        for line in wrap_hints(self._main_footer_hints(), width - 1):
            print(f"{palette.CYAN}{line}{palette.RESET}")

    def draw_empty_state(self: Any, tab_name: str, width: int) -> None:
        box_w = min(60, width - 4)
        padding = (width - box_w) // 2
        margin = " " * padding
        tips = {
            "containers": [
                "No containers found.",
                "To run a new container, try:",
                f"{palette.YELLOW}docker run -d --name test-nginx -p 8080:80 nginx{palette.RESET}",
            ],
            "compose": [
                "No Docker Compose projects found.",
                "To start a compose project, run in your project dir:",
                f"{palette.YELLOW}docker compose up -d{palette.RESET}",
            ],
            "images": [
                "No local images found.",
                "To pull a new image, try:",
                f"{palette.YELLOW}docker pull alpine:latest{palette.RESET}",
            ],
            "volumes": [
                "No volumes found.",
                "To create a volume, try:",
                f"{palette.YELLOW}docker volume create my-data{palette.RESET}",
            ],
            "networks": [
                "No networks found.",
                "To create a network, try:",
                f"{palette.YELLOW}docker network create my-net{palette.RESET}",
            ],
            "contexts": [
                "No Docker contexts found.",
                "To list contexts manually, run:",
                f"{palette.YELLOW}docker context ls{palette.RESET}",
            ],
        }
        content = tips.get(tab_name, ["Nothing to display."])
        print("\n")
        print(margin + f"{palette.CYAN}┌" + "─" * (box_w - 2) + f"┐{palette.RESET}")
        for line in content:
            from ..styles import strip_ansi

            visible_len = len(strip_ansi(line))
            pad_r = max(0, box_w - 4 - visible_len)
            print(
                margin
                + f"{palette.CYAN}│{palette.RESET}  {line}"
                + " " * pad_r
                + f" {palette.CYAN}│{palette.RESET}"
            )
        print(margin + f"{palette.CYAN}└" + "─" * (box_w - 2) + f"┘{palette.RESET}")
        print("\n")

    def _percentage_bar(self: Any, percentage_str: str, width: int = 15) -> tuple[str, bool]:
        try:
            val = float(percentage_str.replace("%", "").strip())
            val = max(0.0, min(100.0, val))
            filled_len = int(round(width * val / 100.0))
            bar = "█" * filled_len + "░" * (width - filled_len)
            is_high = val >= self.config.cpu_alert_threshold
            return f"[{bar}] {percentage_str}", is_high
        except Exception:
            return f"[░░░░░░░░░░░░░░░] {percentage_str}", False
