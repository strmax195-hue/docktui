# Roadmap

This roadmap focuses DockTUI on lightweight local Docker workflows while keeping the runtime dependency-free.

## Near term

- Docker Compose grouping by project and service labels.
- Safer image cleanup flow with dangling-only and selected-image prune modes.
- Saved exec command presets such as `sh`, `bash`, `env`, and `ls -la`.
- Better empty states when Docker is installed but no containers or images exist.

## Later

- Theme presets for light, dark, and high-contrast terminals.
- Container detail sidebar with ports, mounts, labels, and restart policy.
- Optional export of inspect/log output to a local file.
- Keyboard help overlay.
- Wider test coverage for TUI state transitions.

## Feedback wanted

Open an issue if a Docker workflow feels repetitive enough that DockTUI should make it one keypress.
