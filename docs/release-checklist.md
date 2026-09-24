# Release checklist

Use this checklist when preparing a GitHub release.

1. Update `__version__` in `docktui/__init__.py` (the only place the version lives; `pyproject.toml` reads it).
2. Update `CHANGELOG.md` with the release date and highlights.
3. Run tests:

   ```bash
   pytest
   ruff check . && ruff format --check .
   mypy
   ```

4. Build and check the package:

   ```bash
   python -m pip install -e ".[dev]"
   python -m build
   python -m twine check dist/*
   ```

5. Commit the release changes.
6. Create and push a tag:

   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

7. Create a GitHub release from the tag and paste the matching changelog section.
8. Confirm the `Release` workflow succeeds: it fails if the tag does not match `__version__`, and attaches the wheel and sdist to the GitHub release.

PyPI publishing is optional. If you decide to publish later, use `docs/publishing.md`.
