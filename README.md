# DockTUI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://github.com/strmax195-hue/docktui/actions/workflows/tests.yml/badge.svg)](https://github.com/strmax195-hue/docktui/actions/workflows/tests.yml)
[![PyPI Ready](https://img.shields.io/badge/PyPI-ready-blue)](docs/publishing.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)

**DockTUI** is a fast, zero-dependency terminal dashboard for monitoring, debugging, and managing local Docker containers and images. It is written in pure Python, talks to Docker through the Docker CLI, and keeps your existing Docker permissions and context intact.

![DockTUI terminal preview](https://raw.githubusercontent.com/strmax195-hue/docktui/main/assets/demo.svg)

Use DockTUI when you want something richer than repeated `docker ps`, `docker stats`, and `docker logs`, but lighter than a web dashboard or a heavyweight TUI framework.

---

## Why DockTUI?

- **Zero runtime dependencies**: install the package and run it. No Docker SDK, no TUI framework, no daemon sidecar.
- **Docker-native behavior**: DockTUI wraps the Docker CLI, so it respects your current Docker context, permissions, and platform setup.
- **Practical workflows**: start, stop, restart, rename, inspect, tail logs, execute commands, browse images, and review disk usage from one terminal screen.
- **Safe cleanup flow**: destructive cleanup requires explicit confirmation before `docker system prune -f` runs.
- **Friendly codebase**: small pure-Python modules, unit tests with subprocess mocking, and CI on Linux, macOS, and Windows.

## Key Features

- **Zero Dependencies**: Pure Python standard library implementation, no installation of heavy third-party UI/TUI frameworks required.
- **Dual Tabbed Navigation**:
  - **📦 Containers Tab**: Real-time listing of active and inactive containers.
  - **💾 Images Tab**: Clean grid layout showing local Docker images and their size.
- **Container Grid Search & Filtering**: Press `/` in the main view to instantly filter containers by name or image. Press `C` to clear the filter.
- **Interactive Container Execution**: Execute commands inside running containers (`E` key) and scroll through the command outputs in a scrollable console viewer. Re-run commands with `R` or enter new ones with `E`.
- **Quick Rename**: Rename containers instantly (`N` key) with automatic dashboard refresh.
- **Scrollable Log View**: View and search container logs with an interactive viewport. Supports arrow-key scrolling, keyword filtering (`/`), filter clearing (`C`), and tail limit adjustment (`+`/`-`).
- **Interactive Configuration Inspect**: Browse detailed container JSON configuration (`I` key) inside a scrollable inspector viewport.
- **System Disk Usage & Pruning**: Review overall disk space consumed by images, containers, and volumes (`P` key), and trigger safe system cleanup/pruning (`X` key) with real-time feedback.
- **Modern Aesthetics**: Utilizes Unicode double-line frames, block character resource usage bars (`█`/`░`), and ANSI color coding.
- **Dynamic Layout & Resizing**: Automatically listens to terminal dimensions (`os.get_terminal_size()`) and scales column grids proportionally.

---

## DockTUI vs alternatives

| Tooling style | Best for | Tradeoff |
| --- | --- | --- |
| `docker ps`, `docker logs`, `docker stats` | Maximum control and scripting | Repetitive for day-to-day monitoring |
| Web dashboards | Rich graphical management | Heavier setup and more moving parts |
| Full-featured TUI managers | Broad Docker workflows | Often depend on larger external runtimes |
| **DockTUI** | Lightweight local monitoring and quick actions | Intentionally focused on common local Docker tasks |

## Installation

Clone the repository and install it locally using `pip`:

```bash
git clone https://github.com/strmax195-hue/docktui.git
cd docktui
pip install -e .
```

After the first PyPI release, installation will be:

```bash
pip install docktui
```

---

## Usage

Simply run:
```bash
docktui
```

### Hotkeys & Keyboard Navigation

#### Global Controls
- **`Tab` or `1` / `2`**: Switch between **Containers** and **Images** tabs.
- **`↑` / `↓` (Arrow Keys)**: Navigate list items.
- **`G`**: Force refresh data.
- **`Q`**: Exit DockTUI.

#### Containers Tab
- **`S`**: Start or Stop the selected container.
- **`R`**: Restart the selected container (or reconnect to Docker daemon if disconnected).
- **`L`**: Open fullscreen interactive **Logs View**.
- **`I`**: Open fullscreen interactive **Inspect View**.
- **`E`**: Execute a shell command inside the running container (**Exec View**).
- **`N`**: Rename the selected container.
- **`/`**: Filter the containers grid by name/image.
- **`C`**: Clear the active container filter.
- **`P`**: Open **System Disk Usage & Cleanup Dashboard**.

#### Images Tab
- **`D`**: Delete the selected image (asks for confirmation).
- **`P`**: Open **System Disk Usage & Cleanup Dashboard**.

#### In-View Navigation (Logs, Inspect, Exec, System Views)
- **`↑` / `↓` (Arrow Keys)**: Scroll content line-by-line.
- **`Esc` or View Key**: Return back to the main dashboard.
- **Logs View Features**:
  - `/`: Search/filter logs for specific terms.
  - `C`: Clear active log filter.
  - `+` / `-`: Increase/decrease log line retrieval limits.
- **Exec View Features**:
  - `R`: Re-run the current command.
  - `E`: Execute a new command.
- **System View Features**:
  - `X`: Trigger `docker system prune -f` after typing `PRUNE` to confirm cleanup of unused containers, networks, and images.

---

## Technical Architecture

DockTUI interfaces directly with the local Docker daemon by wrapping the `docker` command-line utility via subprocess execution. This guarantees that your existing Docker configurations, permissions, and security context are preserved without requiring complex SDK setups or elevated privilege daemons.

It implements a non-blocking cross-platform input capturing loop using:
- `msvcrt` on Windows.
- `select`, `termios`, and `tty` on Unix systems (Linux/macOS).

---

## Running Tests

DockTUI includes an isolated unit test suite covering client operations via subprocess mocking, meaning you can run tests without a running Docker daemon:

```bash
python -m unittest discover tests
```

On Windows, `py -m unittest discover tests` also works when the Python launcher is installed.

---

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned improvements, including follow-mode logs, Docker Compose grouping, image prune flows, command presets, and theme polish.

## Releases

Release notes live in [CHANGELOG.md](CHANGELOG.md). Maintainers can use [docs/release-checklist.md](docs/release-checklist.md) and [docs/publishing.md](docs/publishing.md) when cutting GitHub and PyPI releases.

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) to learn how to help improve DockTUI.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
