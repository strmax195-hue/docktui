# Release checklist

Status as of 2026-10-01: [PR #26](https://github.com/strmax195-hue/docktui/pull/26)
is merged into `main`, and the v1.5.0 changelog records that source date.
The v1.5.0 tag and GitHub Release artifacts are pending; v1.4.0 remains the
latest published release.

1. Review and merge the improvement PRs and confirm platform/Docker CI.
2. Inspect the published history: v1.4.0 is the latest published release;
   v1.5.0 source is available in `main` and awaits publication.
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
setup-python v7 updates in PR #26. CI confirmed the replacements, and the
superseded PRs are closed.
