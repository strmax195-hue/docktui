# PyPI publishing

DockTUI is currently installed from GitHub:

```bash
pipx install git+https://github.com/strmax195-hue/docktui.git
```

Publishing to PyPI makes `pipx install docktui` / `pip install docktui` work. The package has no runtime dependencies; the `dev` extra only installs build, lint and test tools.

## Trusted Publishing (recommended)

`.github/workflows/publish.yml` builds the package and uploads it with `pypa/gh-action-pypi-publish` whenever a GitHub Release is published. It uses PyPI Trusted Publishing, so no API token is stored in GitHub. **Until the one-time setup below is done, that job fails on every release** (the `Release` workflow that attaches the wheel to the GitHub release is unaffected).

One-time setup:

1. Sign in to PyPI and open *Your projects → Publishing* (for a new project: "Add a new pending publisher").
2. Owner `strmax195-hue`, repository `docktui`, workflow name `publish.yml`, environment `pypi`.
3. In GitHub, create the `pypi` environment (*Settings → Environments*), optionally with required reviewers.
4. Publish the next GitHub Release; the package appears on PyPI.

After the first upload, add the PyPI badge and `pipx install docktui` back to the README.

## Manual setup

1. Create a PyPI account.
2. Create a PyPI API token.
3. Store the token locally for Twine, or paste it when prompted.

## Build

```bash
python -m pip install -e ".[dev]"
python -m build
python -m twine check dist/*
```

## Upload to TestPyPI

```bash
python -m twine upload --repository testpypi dist/*
```

## Upload to PyPI

```bash
python -m twine upload dist/*
```

After publishing, users can install DockTUI with:

```bash
pip install docktui
```
