# Optional PyPI publishing

DockTUI is currently documented as installable from GitHub:

```bash
pip install git+https://github.com/strmax195-hue/docktui.git
```

PyPI publishing is optional. Use this guide only if you decide to make `pip install docktui` available later. The package has no runtime dependencies; the optional `dev` extra only installs build and upload tools.

## Trusted Publishing option

The repository release workflow currently builds package artifacts only. To publish to PyPI through Trusted Publishing later, add the official `pypa/gh-action-pypi-publish` step back to `.github/workflows/release.yml`.

One-time PyPI setup:

1. Open your PyPI project settings.
2. Add a trusted publisher for `strmax195-hue/docktui`.
3. Use workflow name `Release`.
4. Use environment `pypi`.

After that, a GitHub Release can publish the same version to PyPI without storing an API token in GitHub secrets, once the publish step is restored in the release workflow.

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
