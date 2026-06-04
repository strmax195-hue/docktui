# Release checklist

Use this checklist when preparing a GitHub release.

1. Update `version` in `pyproject.toml`.
2. Update `CHANGELOG.md` with the release date and highlights.
3. Run tests:

   ```bash
   python -m unittest discover tests
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
8. Confirm the `Release` workflow succeeds.
9. Publish to PyPI through Trusted Publishing or upload manually with Twine.
