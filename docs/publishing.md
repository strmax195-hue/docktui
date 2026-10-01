# Package publishing

Install the published v1.4.0 wheel from GitHub Releases or use the GitHub
checkout instructions in README. The source targets v1.5.0; it is not released
yet. Do not recommend `pipx install docktui` until the PyPI project and publisher
are verified. PyPI availability and account ownership could not be checked in
this execution environment.

## One tested artifact

`.github/workflows/release.yml` runs tests, lint and type checks, builds once,
checks the distributions with Twine, validates source/wheel/tag versions and
installs the actual wheel in a clean venv outside the checkout. Both GitHub
assets and PyPI consume the same retained artifacts. A mismatched release tag
blocks both. Pull requests validate builds without publishing.

`publish.yml` is a disabled legacy entrypoint and never publishes.

## Trusted Publishing setup

1. Verify the PyPI project name and maintainer ownership (or create a pending publisher).
2. Configure owner `strmax195-hue`, repository `docktui`, workflow `release.yml`, environment `pypi`.
3. Create the GitHub `pypi` environment and configure its reviewers if needed.
4. Set repository variable `ENABLE_PYPI_PUBLISH=true` only after setup is verified.
5. Publish an approved release with matching tag/version and inspect both upload jobs.

PyPI publishing is opt-in and otherwise skipped; GitHub assets still attach
when validation passes. Homebrew remains a separate step after a stable PyPI
release. Actions are pinned to reviewed commit SHAs and updated by Dependabot.
