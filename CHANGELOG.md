# Changelog

All notable changes to DockTUI are documented here.

## [1.2.0] - 2026-06-05

### Added
- Remote Docker daemon support via `--host`/`-H` CLI option and `DOCKER_HOST` environment variable.
- Parsing and display of active `DOCKER_HOST` configuration in the dashboard header.
- Warning alert on Contexts tab when `DOCKER_HOST` overrides context switching.
- Key binding `U` in Contexts tab to switch active Docker contexts (when `DOCKER_HOST` is not active).

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
