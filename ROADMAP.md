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
- Initial TUI state tests for Compose grouping, sorting/filtering, and exec history.
- Basic mouse input detection and terminal mouse tracking cleanup.

## Near term

- Better empty states when Docker is installed but no containers, images, volumes, networks, or contexts exist.
- Richer Compose actions such as logs for an entire service group.
- Export logs, inspect JSON, and details output to local files.
- Broader test coverage for interactive TUI transitions and destructive-action confirmations.
- Improve mouse support beyond detection, starting with scroll-wheel navigation where terminals expose it.

## Later

- Theme presets for light, dark, and high-contrast terminals.
- Optional config file for default refresh interval, log tail, and exec presets.
- Optional project-level config for saved commands and preferred tab/sort mode.

## Feedback wanted

Open an issue if a Docker workflow feels repetitive enough that DockTUI should make it one keypress.
