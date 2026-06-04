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
1. Fork the repository.
2. Create a descriptive branch: `git checkout -b feature/interactive-logs`.
3. Implement your changes. We aim for zero external dependencies, so please avoid adding third-party libraries unless absolutely necessary.
4. Verify your changes work by running the TUI locally.
5. Submit a pull request.

## Code Guidelines
- Write clean, PEP 8 compliant Python code.
- Provide docstrings and inline comments for complex TUI rendering logic.
- Ensure all subprocess calls to Docker CLI are safely validated and handle errors gracefully.
