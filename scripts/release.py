"""Validate release tags and archive the native CLAP, VST3 and LV2 bundles."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import tomllib

BUNDLES = ("Delay Lama.clap", "Delay Lama.vst3", "delay-lama.lv2")
VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?"
)


def release_version(tag: str, package_version: str) -> str:
    """Require an existing SemVer tag to match the version shipped in Cargo."""
    version = tag.removeprefix("v")
    if not VERSION.fullmatch(version) or version != package_version:
        raise ValueError("release tag must match Cargo.toml (optional v prefix)")
    return version


def release_metadata(root: Path, environment: dict[str, str]) -> dict[str, str]:
    """Bind a main-only release run to one existing tag and exact commit."""
    if (
        environment.get("GITHUB_REPOSITORY") != "xsyetopz/XYMonk"
        or environment.get("GITHUB_REF") != "refs/heads/main"
        or environment.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
    ):
        raise ValueError("release must run manually on xsyetopz/XYMonk main")
    tag = environment.get("RELEASE_TAG", "")
    version = release_version(
        tag, tomllib.loads((root / "Cargo.toml").read_text())["package"]["version"]
    )
    commits = []
    for ref in ("HEAD", f"refs/tags/{tag}^{{commit}}"):
        commits.append(
            subprocess.run(
                ["git", "rev-parse", "--verify", ref],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    if commits[0] != commits[1] or commits[0] != environment.get("GITHUB_SHA"):
        raise ValueError("release tag must point to the selected main commit")
    return {"tag": tag, "version": version, "prerelease": str("-" in version).lower()}


def archive(root: Path, system: str, arch: str) -> Path:
    """Copy only the expected bundles and documentation into one archive."""
    if (system, arch) not in {
        ("windows", "x86_64"),
        ("linux", "x86_64"),
        ("linux", "aarch64"),
    }:
        raise ValueError("unsupported release platform/architecture")
    version = tomllib.loads((root / "Cargo.toml").read_text())["package"]["version"]
    release_version(version, version)
    source = root / "target/bundles"
    for name in BUNDLES:
        bundle = source / name
        if not bundle.exists() or (bundle.is_dir() and not any(bundle.rglob("*"))):
            raise ValueError(f"missing or empty release bundle: {name}")
        if bundle.is_file() and bundle.stat().st_size == 0:
            raise ValueError(f"empty release bundle: {name}")
    output = root / "target/release-artifacts"
    output.mkdir(parents=True, exist_ok=True)
    name = f"DelayLama-{version}-{system}-{arch}"
    with tempfile.TemporaryDirectory(prefix="xymonk-release-") as temporary:
        staging = Path(temporary) / name
        staging.mkdir()
        for bundle_name in BUNDLES:
            bundle = source / bundle_name
            if bundle.is_dir():
                shutil.copytree(bundle, staging / bundle_name, symlinks=True)
            else:
                shutil.copy2(bundle, staging / bundle_name)
        # README contains the original redistribution/license terms.
        for document in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
            shutil.copy2(root / document, staging / document)
        result = shutil.make_archive(
            str(output / name),
            "zip" if system == "windows" else "gztar",
            root_dir=temporary,
            base_dir=name,
        )
    return Path(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("metadata")
    pack = subcommands.add_parser("archive")
    pack.add_argument("--system", choices=("windows", "linux"), required=True)
    pack.add_argument("--arch", choices=("x86_64", "aarch64"), required=True)
    args = parser.parse_args()
    root = Path.cwd()
    if args.command == "metadata":
        metadata = release_metadata(root, dict(os.environ))
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            output.writelines(f"{key}={value}\n" for key, value in metadata.items())
    else:
        print(archive(root, args.system, args.arch))


if __name__ == "__main__":
    main()
