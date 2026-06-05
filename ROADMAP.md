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

## Near term

- **Interactive Configuration Editor**: An in-app settings view (or editor) to customize refresh intervals, log limits, and add/edit exec presets, saving them directly to `~/.config/docktui/config.json`.
- **Registry Search & Image Pulling**: Add a dialog to search for images on Docker Hub (or configured registries) and pull them directly from the Images tab.
- **Multi-Host Endpoint Switcher**: Expand the Contexts tab to define, manage, and switch between multiple remote Docker daemon connections (SSH/TCP) dynamically.

## Later

- **Dynamic Resource Limits Editing**: Support modifying container CPU and memory allocations dynamically (wrapping `docker update`) from the Details view.
- **Container Cloning & Duplication**: Easily clone an existing container's configuration to spawn a new replica with customized ports or names.
- **Volume Directory Explorer**: Browse files and directories inside local volumes and container mounts directly from a nested Files explorer.
- **Log Highlighting & Regex Filtering**: Support custom keyword highlights and regex filters inside the Log Viewer.

## Feedback wanted

Open an issue if a Docker workflow feels repetitive enough that DockTUI should make it one keypress.
