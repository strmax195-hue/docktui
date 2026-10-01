"""Validate built metadata and smoke-test the actual wheel in an isolated venv."""

import argparse
import email
import re
import subprocess
import tempfile
import venv
import zipfile
from pathlib import Path
from typing import Optional


def verify_version(wheel: Path, source_version: str, tag: Optional[str] = None) -> None:
    with zipfile.ZipFile(wheel) as archive:
        metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
        package = email.message_from_bytes(archive.read(metadata))
    if package["Name"] != "docktui" or package["Version"] != source_version:
        raise ValueError("Built wheel metadata does not match source version")
    if tag is not None and tag != f"v{source_version}":
        raise ValueError(f"Tag {tag} does not match v{source_version}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag")
    args = parser.parse_args()
    wheels = list(Path("dist").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected exactly one wheel")
    match = re.search(r'__version__ = "([^"]+)"', Path("docktui/__init__.py").read_text())
    if match is None:
        raise ValueError("Source version missing")
    version = match.group(1)
    verify_version(wheels[0], version, args.tag)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv" / "bin" / "python"
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheels[0].resolve()),
            ],
            check=True,
        )
        for arguments in (["--version"], ["--help"], ["config", "show"]):
            subprocess.run(
                [str(root / "venv" / "bin" / "docktui"), *arguments], cwd=root, check=True
            )
            # cwd is outside the checkout: this tests installed package files.
            subprocess.run([str(python), "-I", "-m", "docktui", *arguments], cwd=root, check=True)
        output = subprocess.check_output(
            [str(python), "-I", "-m", "docktui", "--version"], cwd=root, text=True
        )
        if version not in output:
            raise ValueError("Installed wheel version differs")


if __name__ == "__main__":
    main()
