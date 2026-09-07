"""Release metadata and native archive contracts; no signing or network access."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from release import (
    BUNDLES,
    archive,
    create_tag,
    release_metadata,
    release_version,
    require_ci,
)

FAKE_RELEASE_TOOL = r"""
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
scenario = os.environ["RELEASE_SCENARIO"]
with open("commands.jsonl", "a") as log:
    log.write(json.dumps(args) + "\n")
if args[0] == "api":
    if scenario == "lookup-failure":
        sys.exit(1)
    if scenario != "new":
        print("false" if scenario == "published" else "true")
elif args[:2] == ["release", "create"]:
    assert "--draft" in args and "--verify-tag" in args
elif args[:2] == ["release", "upload"]:
    if scenario == "upload-failure":
        sys.exit(1)
    assert set(args[3:-1]) == {str(p) for p in pathlib.Path("release").iterdir()}
    assert args[-1] == "--clobber"
elif args[:2] == ["release", "download"]:
    target = pathlib.Path(args[args.index("--dir") + 1])
    for source in pathlib.Path("release").iterdir():
        shutil.copy2(source, target / source.name)
    if scenario == "corrupt-upload":
        next(target.glob("*.ipa")).write_bytes(b"corrupted")
    if scenario == "stale-asset":
        (target / "old-package.zip").write_bytes(b"stale")
elif args[:2] == ["release", "edit"]:
    assert "--draft=false" in args
elif args[:2] == ["release", "view"]:
    print("false")
else:
    sys.exit("unexpected gh invocation")
"""


class ReleaseTests(unittest.TestCase):
    def test_ci_gate_requires_latest_exact_commit_success_and_fails_closed(self):
        environment = {
            "GITHUB_REPOSITORY": "xsyetopz/XYMonk",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "RELEASE_TAG": "v0.1.0",
            "GITHUB_SHA": "selected-commit",
        }
        success = {
            "run_number": 1, "head_sha": "selected-commit", "head_branch": "main",
            "event": "push", "status": "completed", "conclusion": "success",
            "html_url": "https://github.com/xsyetopz/XYMonk/actions/runs/1",
        }
        cases = [([], False), ([success], True),
                 ([success | {"event": "workflow_dispatch"}], True)]
        for change in (
            {"conclusion": "failure"}, {"conclusion": "cancelled"},
            {"conclusion": "skipped"}, {"conclusion": "timed_out"},
            {"status": "queued", "conclusion": None},
            {"status": "in_progress", "conclusion": None},
            {"head_sha": "other-commit"}, {"head_branch": "other"},
            {"event": "pull_request"},
        ):
            # An older success must never mask a newer failure or pending run.
            cases.append(([success | change | {"run_number": 2}, success], False))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
            for runs, allowed in cases:
                with self.subTest(runs=runs), patch(
                    "release.subprocess.run",
                    side_effect=[
                        SimpleNamespace(stdout="selected-commit\n"),
                        SimpleNamespace(stdout=json.dumps([
                            {"workflow_runs": runs[:1]}, {"workflow_runs": runs[1:]}
                        ])),
                    ],
                ) as run:
                    if allowed:
                        require_ci(root, environment)
                    else:
                        with self.assertRaises(ValueError):
                            require_ci(root, environment)
                    command = run.call_args.args[0]
                    self.assertIn("--paginate", command)
                    self.assertIn("--slurp", command)
                    self.assertEqual(command[-1],
                        "repos/xsyetopz/XYMonk/actions/workflows/ci.yml/runs"
                        "?head_sha=selected-commit&branch=main&per_page=100")
            for failure in (
                subprocess.CalledProcessError(1, "gh"),
                SimpleNamespace(stdout="invalid JSON"),
            ):
                with self.subTest(failure=failure), patch(
                    "release.subprocess.run",
                    side_effect=[SimpleNamespace(stdout="selected-commit\n"), failure],
                ), self.assertRaises((subprocess.CalledProcessError, ValueError)):
                    require_ci(root, environment)

    def test_ci_gate_precedes_builds_and_tag_creation(self):
        workflow = (Path(__file__).resolve().parents[1]
                    / ".github/workflows/release.yml").read_text()
        metadata = workflow.split("  metadata:\n", 1)[1].split("  native:\n", 1)[0]
        self.assertIn("run: python3 scripts/release.py require-ci", metadata)
        self.assertIn("actions: read", metadata)
        for job, following in (("native", "macos"), ("macos", "ios"), ("ios", "release")):
            block = workflow.split(f"  {job}:\n", 1)[1].split(f"  {following}:\n", 1)[0]
            self.assertIn("needs: metadata", block)
        publish = workflow.split("  release:\n", 1)[1]
        self.assertIn("needs.metadata.result == 'success'", publish)
        self.assertIn("actions: read", publish)
        self.assertLess(publish.index("scripts/release.py require-ci"),
                        publish.index("scripts/release.py create-tag"))

    @unittest.skipUnless(os.name == "posix", "workflow uses bash")
    def test_workflow_publishes_only_after_all_release_assets_are_verified(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/release.yml"
        step = workflow.read_text().split(
            "      - name: Upload binaries and publish release\n", 1
        )[1]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        for scenario in (
            "new",
            "draft",
            "published",
            "lookup-failure",
            "upload-failure",
            "corrupt-upload",
            "stale-asset",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                release = root / "release"
                release.mkdir()
                for suffix in (
                    "windows-x86_64.zip",
                    "windows-aarch64.zip",
                    "linux-x86_64.tar.gz",
                    "linux-aarch64.tar.gz",
                    "macos-universal.dmg",
                    "ios-testflight.ipa",
                ):
                    (release / f"DelayLama-0.1.0-{suffix}").write_bytes(
                        b"binary fixture"
                    )
                sums = "".join(
                    f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                    for p in sorted(release.iterdir())
                )
                (release / "SHA256SUMS").write_text(sums)
                tools = root / "tools"
                tools.mkdir()
                gh = tools / "gh"
                gh.write_text(f"#!{sys.executable}\n{FAKE_RELEASE_TOOL}")
                gh.chmod(0o755)
                result = subprocess.run(
                    ["bash", "-e", "-o", "pipefail", "-c", script],
                    cwd=root,
                    env=os.environ
                    | {
                        # Exclude developer-installed tools (notably Homebrew
                        # sha256sum) so macOS exercises its system shasum.
                        "PATH": f"{tools}{os.pathsep}{os.defpath}",
                        "RELEASE_SCENARIO": scenario,
                        "RELEASE_TAG": "v0.1.0",
                        "PRERELEASE": "false",
                        "GH_REPO": "xsyetopz/XYMonk",
                        "GITHUB_SHA": "selected-commit",
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                commands = [
                    json.loads(line)
                    for line in (root / "commands.jsonl").read_text().splitlines()
                ]
                published = any(c[:2] == ["release", "edit"] for c in commands)
                self.assertEqual(
                    result.returncode == 0, scenario in ("new", "draft"), result.stderr
                )
                self.assertEqual(published, scenario in ("new", "draft"))
                if scenario in ("published", "lookup-failure"):
                    self.assertEqual(len(commands), 1)
                if published:
                    self.assertEqual(commands[-2][:2], ["release", "edit"])
                    self.assertEqual(commands[-1][:2], ["release", "view"])

    def test_metadata_requires_canonical_main_and_exact_checkout_not_existing_tag(self):
        environment = {
            "GITHUB_REPOSITORY": "xsyetopz/XYMonk",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "RELEASE_TAG": "v0.1.0",
            "GITHUB_SHA": "selected-commit",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
            with patch(
                "release.subprocess.run",
                return_value=SimpleNamespace(stdout="selected-commit\n"),
            ) as run:
                self.assertEqual(release_metadata(root, environment)["tag"], "v0.1.0")
                self.assertEqual(run.call_count, 1)
                self.assertEqual(
                    run.call_args.args[0], ["git", "rev-parse", "--verify", "HEAD"]
                )
            for key, value in (
                ("GITHUB_REPOSITORY", "fork/XYMonk"),
                ("GITHUB_REF", "refs/tags/v0.1.0"),
                ("GITHUB_EVENT_NAME", "push"),
            ):
                with (
                    patch("release.subprocess.run") as run,
                    self.assertRaises(ValueError),
                ):
                    release_metadata(root, environment | {key: value})
                run.assert_not_called()
            with (
                patch(
                    "release.subprocess.run",
                    return_value=SimpleNamespace(stdout="older-commit"),
                ),
                self.assertRaisesRegex(ValueError, "selected main commit"),
            ):
                release_metadata(root, environment)

    def test_tag_creation_missing_matching_conflicting_and_failed_lookup(self):
        environment = {
            "GITHUB_REPOSITORY": "xsyetopz/XYMonk",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "RELEASE_TAG": "v0.1.0",
            "GITHUB_SHA": "selected-commit",
        }
        matching = "selected-commit\trefs/tags/v0.1.0\n"
        annotated = (
            "tag-object\trefs/tags/v0.1.0\nselected-commit\trefs/tags/v0.1.0^{}\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
            for remote in (matching, annotated):
                with patch(
                    "release.subprocess.run",
                    side_effect=[
                        SimpleNamespace(stdout="selected-commit"),
                        SimpleNamespace(stdout=remote),
                    ],
                ) as run:
                    create_tag(root, environment)
                    self.assertEqual(run.call_count, 2)
                    self.assertEqual(
                        run.call_args.args[0][0:3],
                        ["git", "ls-remote", "https://github.com/xsyetopz/XYMonk.git"],
                    )
            with patch(
                "release.subprocess.run",
                side_effect=[
                    SimpleNamespace(stdout="selected-commit"),
                    SimpleNamespace(stdout=""),
                    SimpleNamespace(stdout="created"),
                    SimpleNamespace(stdout=matching),
                ],
            ) as run:
                create_tag(root, environment)
                self.assertEqual(run.call_count, 4)
                self.assertEqual(
                    run.call_args_list[2].args[0],
                    [
                        "gh",
                        "api",
                        "--hostname",
                        "github.com",
                        "--method",
                        "POST",
                        "/repos/xsyetopz/XYMonk/git/refs",
                        "-f",
                        "ref=refs/tags/v0.1.0",
                        "-f",
                        "sha=selected-commit",
                    ],
                )
            with (
                patch(
                    "release.subprocess.run",
                    side_effect=[
                        SimpleNamespace(stdout="selected-commit"),
                        SimpleNamespace(stdout="other-commit\trefs/tags/v0.1.0\n"),
                    ],
                ) as run,
                self.assertRaisesRegex(ValueError, "refusing to overwrite"),
            ):
                create_tag(root, environment)
            self.assertEqual(run.call_count, 2)
            with (
                patch(
                    "release.subprocess.run",
                    side_effect=[
                        SimpleNamespace(stdout="selected-commit"),
                        subprocess.CalledProcessError(128, "git ls-remote"),
                    ],
                ) as run,
                self.assertRaises(subprocess.CalledProcessError),
            ):
                create_tag(root, environment)
            self.assertEqual(run.call_count, 2)

    def test_tags_must_match_package_version_and_be_safe_for_filenames(self):
        for tag in ("0.1.0", "v0.1.0", "v0.1.0-rc.1"):
            version = tag.removeprefix("v")
            self.assertEqual(release_version(tag, version), version)
        for tag in ("main", "v0.2.0", "v01.1.0", "v0.1.0\n", "../0.1.0", "$(id)"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_version(tag, "0.1.0")

    def test_archives_contain_plugins_platform_guide_and_accompanying_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
            for document in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
                (root / document).write_text(
                    "Release documentation and license terms.\n"
                )
            instructions = root / "docs/install"
            instructions.mkdir(parents=True)
            for system in ("windows", "linux"):
                (instructions / f"{system}.txt").write_bytes(
                    (
                        Path(__file__).resolve().parents[1]
                        / "docs/install"
                        / f"{system}.txt"
                    ).read_bytes()
                )
            source = root / "target/bundles"
            source.mkdir(parents=True)
            (source / BUNDLES[0]).write_bytes(b"clap fixture")
            for name in BUNDLES[1:]:
                (source / name).mkdir()
                (source / name / "plugin").write_bytes(b"plugin fixture")
            (source / "unrelated-debug-output").write_bytes(b"must not ship")
            for system, arch in (
                ("windows", "x86_64"),
                ("windows", "aarch64"),
                ("linux", "x86_64"),
                ("linux", "aarch64"),
            ):
                with self.subTest(system=system, arch=arch):
                    result = archive(root, system, arch)
                    guide_path = f"DelayLama-0.1.0-{system}-{arch}/INSTALL.txt"
                    if system == "windows":
                        with zipfile.ZipFile(result) as packed:
                            names = packed.namelist()
                            guide = packed.read(guide_path)
                    else:
                        with tarfile.open(result) as packed:
                            names = packed.getnames()
                            stored = packed.extractfile(guide_path)
                            assert stored is not None, (
                                f"Not a readable file: {guide_path}"
                            )
                            with stored:
                                guide = stored.read()
                    self.assertEqual(
                        guide, (instructions / f"{system}.txt").read_bytes()
                    )
                    contents = {name.split("/", 1)[1] for name in names if "/" in name}
                    self.assertEqual(
                        {name.split("/", 1)[0] for name in contents if name},
                        {*BUNDLES, "INSTALL.txt", "Documentation"},
                    )
                    for document in (
                        "README.md",
                        "CONTRIBUTING.md",
                        "CODE_OF_CONDUCT.md",
                    ):
                        self.assertIn(f"Documentation/{document}", contents)
                    self.assertIn(BUNDLES[0], contents)
                    self.assertIn(f"{BUNDLES[1]}/plugin", contents)
                    self.assertIn(f"{BUNDLES[2]}/plugin", contents)
                    self.assertFalse(any("unrelated" in name for name in names))

    def test_missing_format_stops_packaging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                archive(root, "linux", "x86_64")
            self.assertFalse((root / "target/release-artifacts").exists())


if __name__ == "__main__":
    unittest.main()
