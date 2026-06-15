# Changelog

All notable changes to DockTUI are documented here.

## [1.4.0] - 2026-06-15

### Added
- **Detachable Panes** (`P` in Logs/Details view): Pin the active view to the bottom half of the terminal while returning to the main dashboard to navigate other containers.
- **Bulk Start/Stop** (`Ctrl+S` on Containers tab): Quickly start or stop all containers currently matching the active filter.
- **Inline Exec Search**: The exec input dialog now features type-to-search auto-completion against your execution history.
- **Hotkey Overlays**: Define custom hotkeys in `config.json` (`hotkey_overlays` dict) to trigger shell commands inside the selected container with a single keypress.
- **Configurable Poll Intervals**: `refresh_worker` now uses specific intervals based on resource type (e.g., faster for containers, slower for images/volumes/networks) defined in `poll_intervals` config.
- **Extended Exports**: The `O` key export functionality is now available in the Settings, Search, Pull Progress, and Files views.
- **Config Persistence**: Dynamically added `log_highlights` and `exec_presets` are now automatically saved back to the configuration file.

### Fixed
- Fixed an issue where the input modal could freeze and trap the user if closed improperly.

## [1.3.0] - 2026-06-07

### Added
- **Interactive settings editor** (`Shift+S`): edit refresh interval, Docker timeout, theme, log tail/max, CPU alert threshold, exec history cap, exec presets, and log highlight patterns from inside the dashboard. Press `S` to save the changes back to the config file; `Esc` to discard.
- **Registry search and image pulling** (`F` on Images tab): search Docker Hub and pull images directly from the Images tab with a live pull-progress view (cancellable, streamed via the new `LineStreamer`).
- **Multi-host endpoint switcher**: register named remote endpoints in the config file (`endpoints`) and activate them with the `N` hotkey on the Contexts tab, or by selecting one from the prompt. Activation updates DockTUI's per-instance `DOCKER_HOST` without mutating the shell environment.
- **Dynamic resource limits** (`W` on Containers/Compose tabs): edit live CPU and memory allocations for a running container using a small modal that wraps `docker update`.
- **Log highlighting and regex filtering** (`H` in Logs view): toggle highlighting based on patterns configured via `log_highlights` (each entry is `{label, pattern}`) with regex support and case-insensitive matching.
- **Container cloning** (`Shift+C` on Containers/Compose tabs): open a clone dialog that pre-fills the image, name, and ports so you can spawn a copy of an existing container with `docker run`.
- **Volume file browser** (`Shift+F` on Volumes tab): drill into a volume's contents via a lightweight in-app directory explorer (entry list, `Enter` to descend, `Backspace` to ascend, `Esc` to return).

### Changed
- **Per-instance `DOCKER_HOST`**: `DockerClient` no longer mutates `os.environ["DOCKER_HOST"]` when you set the host programmatically. The legacy constructor behavior is preserved for backward compatibility, but the new `set_host()` / `host` property flow is side-effect free.
- **Refactored codebase**: split the dashboard into focused modules — `config.py`, `constants.py`, `enums.py`, `styles.py`, `screen.py`, `keymap.py`, `dialogs.py`, `log_stream.py` — to replace the legacy monolithic `tui.py`. The new layout keeps zero runtime dependencies while reducing duplication and making it easy to extend with new views.
- **`docker_client.py` helper extraction**: all subprocess calls now go through `_capture` / `_run_capture` / `_bool` helpers, removing hand-rolled parsing paths and yielding consistent return values for unit testing.
- **Python support**: dropped Python 3.7 (EOL); now supports 3.8–3.13. CI matrix updated accordingly.
- **Linting**: ruff is now part of the dev toolchain (`py -m ruff check .`) with a dedicated `lint` job in CI.

### Fixed
- Constructor copy/paste bug in the legacy `__init__` flow (container filter was being assigned twice) — resolved during the refactor.
- Stale imports and unused `Optional` / `Iterable` / `List` typing that were no longer needed in the new module layout.

## [1.2.0] - 2026-06-05

### Added
- Remote Docker daemon support via `--host`/`-H` CLI option and `DOCKER_HOST` environment variable.
- Parsing and display of active `DOCKER_HOST` configuration in the dashboard header.
- Warning alert on Contexts tab when `DOCKER_HOST` overrides context switching.
- Key binding `U` in Contexts tab to switch active Docker contexts (when `DOCKER_HOST` is not active).
- Color theme presets (Dark, Light, High-Contrast) switchable via CLI option `--theme` or hotkey `M`.
- Support for configuration files loaded from `~/.config/docktui/config.json` or `~/.docktui.json` to customize default parameters.
- Text search and filtering (`/` / `C` keys) support across all tabs (Images, Volumes, Networks, Contexts).
- High-resource warning alerts (CPU/Memory bar color changes and alarm badge indicators when usage >= 80%).
- Display of container IP addresses, gateways, and MAC addresses inside the Details view.
- Deletion of Docker networks from the Networks tab via `D` hotkey.
- Fixed keypress uppercase casing support for Unix/macOS input prompts.
- Support switching directly to the Contexts tab via numeric key `6`.
- Interactive terminal execution sessions (`docker exec -it` via temporary standard input/output restoration).
- Real-time streaming logs (`docker logs -f` using background thread stream readers).
- Extended Compose lifecycle actions (up, down, build, and up --build) directly from the Compose tab.
- Reverse-engineering generator (exporting selected container to a `docker-compose.yml` snippet).

## [1.1.0] - 2026-06-04

### Added
- Clean export of logs, inspect JSON, details, and top views to local files via `O` key.
- Aggregated project-level logs for Docker Compose groups on the Compose tab.
- Scroll-wheel mouse support for list and text view navigation.
- Beautiful boxed empty state screens with helpful CLI tips for all tabs.
- Integrated container processes view (`docker top`) via `T` key.

## [1.0.0] - 2026-06-04


### Added
- Containers dashboard with start, stop, restart, inspect, logs, exec, rename, and filtering workflows.
- Compose-aware tab that groups containers by Docker Compose project and service labels.
- Docker images tab with local image listing and deletion.
- Docker volumes and networks tabs.
- Docker system disk usage and prune view.
- Separate system, image, volume, and full prune confirmations.
- Scrollable log, inspect, and exec output views.
- Readable container details view for ports, mounts, env, labels, networks, and restart policy.
- Cross-platform unit test workflow for GitHub Actions.
- `--version`, `--refresh-interval`, and `--docker-timeout` CLI options.
- In-app help screen via `?`.
- Follow-mode logs via `F`.
- Log next-match navigation and error/warning-only filtering.
- Exec command presets and session command history.
- Container sorting and state filters.

### Changed
- Docker daemon checks are cached so the render loop stays responsive.
- Docker CLI commands now use a default timeout so slow commands do not hang forever.
- Project metadata now points to the public GitHub repository.
- README now includes a visual preview, clearer positioning, roadmap, and release links.

### Fixed
- `docker exec` command parsing now preserves quoted arguments.
- `docker system prune -f` now requires explicit `PRUNE` confirmation.
