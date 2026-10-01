# Release checklist

1. Review and merge the improvement PRs and confirm platform/Docker CI.
2. Inspect the published history: v1.4.0 is the latest published release;
   the next planned source release is v1.5.0.
3. Set `docktui/__init__.py` version and date the matching CHANGELOG section.
4. Run `pytest`, `ruff check .`, `ruff format --check .`, and `mypy`.
5. Run `python -m build`, `python -m twine check dist/*`, and
   `python scripts/validate_release.py --tag v1.5.0`. This installs the wheel
   outside the checkout and exercises both CLI entrypoints.
6. Review the concrete release/tag before creating it; a PR does not publish.
7. Create the matching tag and GitHub release, then confirm the single Release
   pipeline succeeds and attaches the verified wheel and sdist.
8. Enable optional PyPI publishing only after the setup in
   [publishing.md](publishing.md) is verified. Both upload jobs consume the
   same artifacts and cannot run after a version mismatch.
9. Update README wheel links and install instructions only after upload succeeds.

Dependabot #12–14 are superseded by the SHA-pinned CodeQL v4, checkout v7 and
setup-python v7 updates in the release pipeline PR; close those PRs after this
workflow's CI confirms the replacements.
