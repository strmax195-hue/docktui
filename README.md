# DockTUI 🐳

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.7%2B-blue.svg)](https://www.python.org/downloads/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)

**DockTUI** is a lightweight, interactive Terminal User Interface (TUI) dashboard to monitor and manage local Docker containers. Written in pure Python with **zero external dependencies**, it works out of the box on Windows, macOS, and Linux.

With DockTUI, you don't need heavy web dashboards or complex CLI command chains to manage your containers—simply launch it in your terminal, select your container, and manage it with simple hotkeys.

---

## Features

- **Zero Dependencies**: Pure Python standard library implementation, no third-party packages required.
- **Interactive TUI**: Easy-to-use terminal interface with keyboard-driven navigation (arrow keys).
- **Real-Time Monitoring**: Auto-refreshing statistics (CPU, Memory, and Network IO usage) for running containers.
- **Control Actions**: Start, stop, and restart containers instantly with single keystrokes.
- **Log Viewer**: View real-time logs directly in a dedicated screen.
- **Cross-Platform**: Designed to work seamlessly on Windows PowerShell/CMD, Linux terminals, and macOS Terminal.

---

## Installation

Clone the repository and install it locally using `pip`:

```bash
git clone https://github.com/yourusername/docktui.git
cd docktui
pip install -e .
```

---

## Usage

Simply run:
```bash
docktui
```

### Hotkeys
- **`↑` / `↓` (Arrow Keys)**: Navigate and select containers in the list.
- **`S`**: Start or Stop the selected container.
- **`R`**: Restart the selected container (or retry daemon connection if disconnected).
- **`L`**: Toggle fullscreen log view for the selected container.
- **`G`**: Force refresh data.
- **`Q`**: Exit DockTUI.

---

## Technical Details

DockTUI interfaces directly with the local Docker daemon by wrapping the `docker` command-line utility via subprocess execution. This guarantees that your existing Docker configurations, permissions, and security context are preserved without requiring complex SDK setups.

---

## Running Tests

Run the test suite containing unit tests and mocks:

```bash
python -m unittest discover tests
```

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) to learn how to help improve DockTUI.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
