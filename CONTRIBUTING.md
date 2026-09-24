# Contributing to DockTUI

First off, thank you for considering contributing to DockTUI! Your involvement helps make this a better tool for the developer community.

## How Can I Contribute?

### Reporting Bugs
If you encounter any issues:
1. Search existing issues to see if it has already been reported.
2. Open a new issue with a clear description, steps to reproduce, and details about your Docker environment.

### Feature Requests
Have an idea to make DockTUI better?
1. Open an issue describing the feature.
2. Discuss feasibility and design with the maintainers.

### Development Process
1. Fork the repository and create a descriptive branch: `git checkout -b feature/interactive-logs`.
2. Set up a development environment:

   ```bash
   python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   pre-commit install   # optional, runs ruff + mypy before each commit
   ```

3. Implement your change. DockTUI has **zero runtime dependencies** — please keep it that way (dev-only tools are fine).
4. Run the same checks as CI:

   ```bash
   pytest                                  # no Docker daemon needed; subprocess calls are mocked
   ruff check . && ruff format --check .
   mypy
   ```

5. Try it for real: `docktui doctor`, `docktui`, and `docktui check` against your local Docker.
6. Add a line to the `Unreleased` section of `CHANGELOG.md` and open a pull request.

### Where things live
- Non-interactive commands (`status`, `check`) are pure functions in `docktui/report.py` — the easiest place to start contributing, and fully unit-testable.
- Diagnostics live in `docktui/doctor.py`; every check returns a `CheckResult`.
- The dashboard is `docktui/tui.py` (one `draw_*` method and one `_handle_key_*` method per view).

## Code Guidelines
- Write clean, PEP 8 compliant Python code.
- Provide docstrings and inline comments for complex TUI rendering logic.
- Ensure all subprocess calls to Docker CLI are safely validated and handle errors gracefully.
