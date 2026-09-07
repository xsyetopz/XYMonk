"""Release metadata and native archive contracts; no signing or network access."""

import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from release import BUNDLES, archive, create_tag, release_metadata, release_version


class ReleaseTests(unittest.TestCase):
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

    def test_archives_contain_all_formats_and_license_readme_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
            for document in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
                (root / document).write_text(
                    "Release documentation and license terms.\n"
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
                ("linux", "x86_64"),
                ("linux", "aarch64"),
            ):
                with self.subTest(system=system, arch=arch):
                    result = archive(root, system, arch)
                    if system == "windows":
                        with zipfile.ZipFile(result) as packed:
                            names = packed.namelist()
                    else:
                        with tarfile.open(result) as packed:
                            names = packed.getnames()
                    contents = {name.split("/", 1)[1] for name in names if "/" in name}
                    self.assertIn("README.md", contents)
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
