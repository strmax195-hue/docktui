# Changelog

All notable changes to DockTUI are documented here.

## [1.0.0] - 2026-06-04

### Added
- Containers dashboard with start, stop, restart, inspect, logs, exec, rename, and filtering workflows.
- Docker images tab with local image listing and deletion.
- Docker system disk usage and prune view.
- Scrollable log, inspect, and exec output views.
- Cross-platform unit test workflow for GitHub Actions.

### Changed
- Docker daemon checks are cached so the render loop stays responsive.
- Project metadata now points to the public GitHub repository.
- README now includes a visual preview, clearer positioning, roadmap, and release links.

### Fixed
- `docker exec` command parsing now preserves quoted arguments.
- `docker system prune -f` now requires explicit `PRUNE` confirmation.
