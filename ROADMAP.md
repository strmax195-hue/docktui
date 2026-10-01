# Roadmap

This roadmap focuses DockTUI on lightweight local Docker workflows while keeping the runtime dependency-free.

## Delivered

- Compose-aware grouping by project and service labels.
- Containers, images, volumes, networks, and Docker contexts tabs.
- Docker context display and switching (key `U`).
- Container details view for ports, mounts, environment, labels, networks, and restart policy.
- Advanced logs with follow mode, search, next-match navigation, and error/warning-only filtering.
- Exec command presets and session command history.
- Separate system, image, volume, and full prune confirmations.
- Expanded TUI state tests for Compose grouping, sorting/filtering, exec history, empty states, and file exports.
- Non-blocking keyboard input loop with active thread refresh logic.
- Scroll-wheel mouse navigation support across TUI views.
- Clean export of logs, inspect JSON, details, and top views to files.
- Beautiful empty state screens with CLI tips for all tabs.
- Support for remote Docker daemons via SSH/TCP (proper `DOCKER_HOST` parsing and display).
- Theme presets (Dark, Light, High-Contrast) for terminals (CLI `--theme` or hotkey `M`).
- Optional configuration file support (`~/.config/docktui/config.json`).
- Text search and filtering (`/` / `C` keys) across all dashboard tabs.
- High-resource warning alerts (visual alarm indicators when CPU/Memory usage >= 80%).
- Container IP address, gateway, and MAC address display in the Details view.
- Deletion of Docker networks from the Networks tab.
- Interactive terminal execution sessions (`docker exec -it` inside DockTUI).
- Real-time streaming logs (`docker logs -f` via background threads).
- Extended Compose lifecycle actions (build, down, up --build directly from Compose tab).
- Reverse-engineering generator (exporting selected container to a `docker-compose.yml` snippet).
- **Interactive Configuration Editor** (`Shift+S`): in-app settings view that edits refresh interval, log limits, theme, exec presets, log highlight patterns, and writes them back to the config file.
- **Registry Search & Image Pulling** (`F` on Images tab): Docker Hub search with live pull progress and cancellation.
- **Multi-Host Endpoint Switcher**: persistent `endpoints` list in the config file and an in-app activator (Contexts tab → `N` or a name picker) that updates DockTUI's per-instance `DOCKER_HOST` without mutating the shell environment.
- **Dynamic Resource Limits Editing** (`W` on Containers/Compose): edit live CPU and memory allocations via a small modal that wraps `docker update`.
- **Container Cloning & Duplication** (`Shift+C` on Containers/Compose): open a clone dialog pre-filled with image, name, and ports to spawn a copy of an existing container.
- **Volume Directory Explorer** (`Shift+F` on Volumes): in-app directory browser for Docker volumes.
- **Log Highlighting & Regex Filtering** (`H` in Logs view): regex-based highlight patterns configured via the config file and toggleable from the keyboard.

- Compose snippet export to file.
- Save logs/inspect/diff views via a single `O` key exposed from the Settings, Search, Pull, and Files views.
- Bulk container start/stop on the Containers tab (operate on the visible filter via `Ctrl+s`).
- Persist last-used `log_highlights` and `exec_presets` in addition to the static defaults.
- **Inline shell history search**: type-to-search through past exec commands on the Exec modal.
- **Detachable dashboard panes**: let users split the screen to keep logs open while navigating containers (`P` to pin).
- **Configurable poll interval per resource type**: slower refresh for volumes/networks, faster for containers.
- **Plugin-style hotkey overlays**: users can register custom hotkeys in the config file that run shell commands or shell scripts in the active container.

## Delivered in v1.5.0 — ops toolkit

- `docktui check`: Nagios/Icinga/cron health check with exit codes, JSON output, thresholds and required containers.
- `docktui status`: one-shot snapshot with health and resources, JSON for scripts.
- `docktui doctor`: environment diagnostics with actionable fixes.
- `docktui config init|path|show`, `--config`, `$DOCKTUI_CONFIG`, XDG support.
- Scrollable dashboard lists for large hosts; reliable keyboard input on Unix.
- Bulk start/stop, custom hotkeys and pinned panes wired up for real.

## Reliability improvements

- [x] Distinguish failed Docker collection from an empty successful result; preserve stale dashboard snapshots and return UNKNOWN for failed health checks.
- [x] Apply the selected connection to every subprocess.
- [x] Correct Compose argument ordering and validate config paths.
- [x] Bound streaming buffers and reliably finish background processes.
- [x] Keep TUI navigation responsive during slow operations.
- [x] Split terminal I/O and view rendering from the dashboard coordinator.
- [x] Save and validate configuration safely; strengthen CI.
- [x] Prepare one verified package artifact and a single opt-in release pipeline (publishing setup remains external).

The implementation plan is in [docs/superpowers/plans/2026-10-01-docktui-improvements.md](docs/superpowers/plans/2026-10-01-docktui-improvements.md).

## Next (ideas — feedback welcome)

- `docktui check --hosts prod,stage`: check several endpoints in one run.
- Prometheus text-format output for `status` (node_exporter textfile collector).
- Container events feed (`docker events`) in the dashboard: OOM kills, restarts, health changes.
- Show healthcheck log (last probe output) in the Details view.
- Log view: `--since` time windows and saving highlight presets per container.
- Publish to PyPI and Homebrew for one-command installs.

## Feedback wanted

Open an issue if a Docker workflow feels repetitive enough that DockTUI should make it one keypress — or one command in a cron job.
