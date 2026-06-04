# Publishing to PyPI

DockTUI is prepared for PyPI publishing. The package has no runtime dependencies; the optional `dev` extra only installs build and upload tools.

## Recommended: trusted publishing

The repository includes `.github/workflows/release.yml`. When you publish a GitHub Release, the workflow builds the package and can publish it to PyPI through Trusted Publishing.

One-time PyPI setup:

1. Open your PyPI project settings.
2. Add a trusted publisher for `strmax195-hue/docktui`.
3. Use workflow name `Release`.
4. Use environment `pypi`.

After that, publishing a GitHub Release can publish the same version to PyPI without storing an API token in GitHub secrets.

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
