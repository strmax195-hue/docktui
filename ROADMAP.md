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

- (All near-term items have been delivered!)

## Later

- (All planned later-stage items have been delivered!)

## Feedback wanted

Open an issue if a Docker workflow feels repetitive enough that DockTUI should make it one keypress.
