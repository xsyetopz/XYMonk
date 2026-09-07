"""Validate release tags and archive the native CLAP, VST3 and LV2 bundles."""

from __future__ import annotations

import argparse
import json
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
    """Require a SemVer tag to match the version shipped in Cargo."""
    version = tag.removeprefix("v")
    if not VERSION.fullmatch(version) or version != package_version:
        raise ValueError("release tag must match Cargo.toml (optional v prefix)")
    return version


def release_metadata(root: Path, environment: dict[str, str]) -> dict[str, str]:
    """Validate the requested version and bind the run to its main commit."""
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
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != environment.get("GITHUB_SHA"):
        raise ValueError("checkout must match the selected main commit")
    return {"tag": tag, "version": version, "prerelease": str("-" in version).lower()}


def require_ci(root: Path, environment: dict[str, str]) -> None:
    """Fail closed unless the newest CI run for this exact main commit passed."""
    release_metadata(root, environment)
    commit = environment["GITHUB_SHA"]
    result = subprocess.run(
        [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--paginate",
            "--slurp",
            f"repos/xsyetopz/XYMonk/actions/workflows/ci.yml/runs?head_sha={commit}&branch=main&per_page=100",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    runs = [run for page in json.loads(result.stdout) for run in page["workflow_runs"]]
    if not runs:
        raise ValueError(
            f"No CI run for {commit}; run CI successfully before releasing"
        )
    latest = max(runs, key=lambda run: run["run_number"])
    if (
        latest["head_sha"] != commit
        or latest["head_branch"] != "main"
        or latest["event"] not in ("push", "workflow_dispatch")
        or latest["status"] != "completed"
        or latest["conclusion"] != "success"
    ):
        raise ValueError(
            f"CI must pass for {commit} before releasing: {latest['html_url']} "
            f"({latest['status']}/{latest['conclusion']})"
        )
    print(f"CI passed for {commit}: {latest['html_url']}")


def create_tag(root: Path, environment: dict[str, str]) -> None:
    """Create a missing tag; never move or delete an existing reference."""
    metadata = release_metadata(root, environment)
    ref = f"refs/tags/{metadata['tag']}"
    commit = environment["GITHUB_SHA"]

    def remote_commit():
        output = subprocess.run(
            [
                "git",
                "ls-remote",
                "https://github.com/xsyetopz/XYMonk.git",
                ref,
                f"{ref}^{{}}",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        refs = {}
        for line in output.splitlines():
            sha, name = line.split()
            refs[name] = sha
        # Annotated tags resolve through their peeled commit; lightweight tags
        # point directly at the commit.
        return refs.get(f"{ref}^{{}}", refs.get(ref))

    existing = remote_commit()
    if existing is None:
        subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                "github.com",
                "--method",
                "POST",
                "/repos/xsyetopz/XYMonk/git/refs",
                "-f",
                f"ref={ref}",
                "-f",
                f"sha={commit}",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        existing = remote_commit()
    if existing != commit:
        raise ValueError(
            f"tag {metadata['tag']} does not point to selected main commit {commit}; refusing to overwrite it"
        )
    print(f"Tag {metadata['tag']} verified at {commit}")


def archive(root: Path, system: str, arch: str) -> Path:
    """Copy only the expected bundles and documentation into one archive."""
    if (system, arch) not in {
        ("windows", "x86_64"),
        ("windows", "aarch64"),
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
        shutil.copy2(root / "docs/install" / f"{system}.txt", staging / "INSTALL.txt")
        # Keep all accompanying documents, including redistribution terms,
        # together so the plug-ins and quick-start remain easy to find.
        documentation = staging / "Documentation"
        documentation.mkdir()
        for document in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
            shutil.copy2(root / document, documentation / document)
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
    subcommands.add_parser("create-tag")
    subcommands.add_parser("require-ci")
    pack = subcommands.add_parser("archive")
    pack.add_argument("--system", choices=("windows", "linux"), required=True)
    pack.add_argument("--arch", choices=("x86_64", "aarch64"), required=True)
    args = parser.parse_args()
    root = Path.cwd()
    match args.command:
        case "metadata":
            metadata = release_metadata(root, dict(os.environ))
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.writelines(f"{key}={value}\n" for key, value in metadata.items())
        case "create-tag":
            create_tag(root, dict(os.environ))
        case "require-ci":
            require_ci(root, dict(os.environ))
        case _:
            print(archive(root, args.system, args.arch))


if __name__ == "__main__":
    main()
