# Roadmap

This roadmap focuses DockTUI on lightweight local Docker workflows while keeping the runtime dependency-free.

## Delivered

- Compose-aware grouping by project and service labels.
- Containers, images, volumes, networks, and Docker contexts tabs.
- Docker context display and switching.
- Container details view for ports, mounts, environment, labels, networks, and restart policy.
- Advanced logs with follow mode, search, next-match navigation, and error/warning-only filtering.
- Exec command presets and session command history.
- Separate system, image, volume, and full prune confirmations.
- Expanded TUI state tests for Compose grouping, sorting/filtering, exec history, empty states, and file exports.
- Non-blocking keyboard input loop with active thread refresh logic.
- Scroll-wheel mouse navigation support across TUI views.
- Clean export of logs, inspect JSON, details, and top views to files.
- Beautiful empty state screens with CLI tips for all tabs.

## Near term

- Theme presets for light, dark, and high-contrast terminals.
- Optional config file for default refresh interval, log tail, and exec presets.
- Filter and search (`/` key) support across all tabs (Images, Volumes, Networks, Contexts).
- High-resource warning alerts (visual indicators when container CPU/Memory usage is extremely high).

## Later

- Interactive terminal execution sessions (`docker exec -it` inside DockTUI by temporarily restoring standard tty input).
- Real-time streaming logs (`docker logs -f` via non-blocking stream readers).
- Extended Compose lifecycle actions (e.g. build, down, up --build directly from Compose tab).
- Container IP address and subnet display within the Details view.
- Reverse-engineering generator (exporting selected container to a `docker-compose.yml` snippet).
- Support for remote Docker daemons via SSH/TCP (proper `DOCKER_HOST` parsing).



## Feedback wanted

Open an issue if a Docker workflow feels repetitive enough that DockTUI should make it one keypress.
