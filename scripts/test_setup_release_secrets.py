"""Secret handling contracts; all hosted writes are mocked."""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import setup_release_secrets as setup


class SecretTests(unittest.TestCase):
    def mock_upload(self, confirmation=setup.REPOSITORY):
        self.enterContext(patch("builtins.input", return_value=confirmation))
        self.enterContext(patch.object(setup, "status", return_value=True))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        return self.enterContext(patch.object(setup, "run"))

    def test_ios_configuration_preserves_macos_and_existing_password(self):
        values = {name: "mac-secret" for name in setup.NAMES}
        values["IOS_CERTIFICATE_PASSWORD"] = "existing-ios-password"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.release"
            setup.save(path, values)
            with (
                patch("builtins.input", return_value="yes"),
                patch.object(
                    setup,
                    "encoded_file",
                    side_effect=[
                        "certificate",
                        "adhoc-app",
                        "adhoc-extension",
                        "testflight-app",
                        "testflight-extension",
                    ],
                ) as files,
                patch.object(setup.getpass, "getpass", return_value=""),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                setup.configure(path, "ios")
            configured = setup.read(path)
            for name, value in values.items():
                self.assertEqual(configured[name], value)
            self.assertTrue(set(setup.IOS_NAMES) <= configured.keys())
            expected_profiles = (
                (
                    "IOS_ADHOC_APP_PROFILE_BASE64",
                    "Ad Hoc",
                    "main app",
                    "com.audionerdz.delaylama",
                    "adhoc-app",
                ),
                (
                    "IOS_ADHOC_EXTENSION_PROFILE_BASE64",
                    "Ad Hoc",
                    "AUv3 extension",
                    "com.audionerdz.delaylama.AUExt",
                    "adhoc-extension",
                ),
                (
                    "IOS_TESTFLIGHT_APP_PROFILE_BASE64",
                    "TestFlight (App Store Connect)",
                    "main app",
                    "com.audionerdz.delaylama",
                    "testflight-app",
                ),
                (
                    "IOS_TESTFLIGHT_EXTENSION_PROFILE_BASE64",
                    "TestFlight (App Store Connect)",
                    "AUv3 extension",
                    "com.audionerdz.delaylama.AUExt",
                    "testflight-extension",
                ),
            )
            for call, (name, distribution, target, bundle, value) in zip(
                files.call_args_list[1:], expected_profiles, strict=True
            ):
                self.assertEqual(
                    call.args[0],
                    f"{distribution} / {target} ({bundle})\n.mobileprovision file path: ",
                )
                self.assertEqual(configured[name], value)
            with (
                patch("builtins.input", return_value="yes"),
                patch.object(setup, "encoded_file", return_value="bmV3IGNlcnQ="),
                patch.object(setup.getpass, "getpass", return_value="new-mac-secret"),
                patch.object(
                    setup.secrets, "token_urlsafe", return_value="new-mac-secret"
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                setup.configure(path)
            updated = setup.read(path)
            self.assertEqual(updated[setup.NAMES[0]], "bmV3IGNlcnQ=")
            self.assertTrue(
                all(updated[name] == "new-mac-secret" for name in setup.NAMES[1:])
            )
            for name in setup.IOS_NAMES:
                self.assertEqual(updated[name], configured[name])

    def test_partial_ios_entries_do_not_break_macos_or_allow_incomplete_upload(self):
        values = {name: "mac-secret" for name in setup.NAMES}
        values["IOS_CERTIFICATE_PASSWORD"] = "ios-secret"
        run = self.mock_upload()
        setup.apply(values)
        self.assertEqual(run.call_count, len(setup.NAMES))
        run.reset_mock()
        with self.assertRaises(setup.SetupError):
            setup.apply(values, "ios")
        run.assert_not_called()

    def test_ios_upload_only_sends_ios_names_and_example_documents_them(self):
        values = {name: "private-value" for name in setup.ALL_NAMES}
        example = Path(__file__).resolve().parent.parent / ".env.example"
        for name in setup.ALL_NAMES:
            self.assertIn(f"{name}=", example.read_text())
        run = self.mock_upload()
        setup.apply(values, "ios")
        self.assertEqual(run.call_count, len(setup.IOS_NAMES))
        self.assertEqual(
            [call.args[0][3] for call in run.call_args_list], list(setup.IOS_NAMES)
        )

    def test_private_round_trip_without_shell_evaluation(self):
        values = {name: "literal ' $(false) # secret" for name in setup.NAMES}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.release"
            setup.save(path, values)
            self.assertEqual(setup.read(path), values)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                path.chmod(0o644)
                with self.assertRaises(setup.SetupError):
                    setup.read(path)
                path.chmod(0o600)
            path.write_text(path.read_text() + "UNKNOWN=bad\n")
            with self.assertRaises(setup.SetupError):
                setup.read(path)

    def test_apply_requires_confirmation_and_uses_stdin_fixed_repository(self):
        values = {name: "private-value" for name in setup.NAMES}
        run = self.mock_upload("no")
        with self.assertRaises(setup.SetupError):
            setup.apply(values)
        run.assert_not_called()
        run = self.mock_upload()
        setup.apply(values)
        self.assertEqual(run.call_count, 5)
        for call, name in zip(run.call_args_list, setup.NAMES):
            self.assertEqual(
                call.args[0],
                ["gh", "secret", "set", name, "--repo", setup.REPOSITORY],
            )
            self.assertEqual(call.kwargs, {"input": "private-value"})

    def test_guard_rejects_other_branch_and_repository(self):
        root = Path("/fixture")
        for results in (
            (str(root), "topic"),
            (str(root), "main", "origin", "other/repo"),
        ):
            with (
                patch.object(setup, "run", side_effect=results),
                self.assertRaises(setup.SetupError),
            ):
                setup.guard(root)

    def test_partial_upload_reports_names_not_values(self):
        values = {name: "private-value" for name in setup.NAMES}
        with (
            patch("builtins.input", return_value=setup.REPOSITORY),
            patch.object(setup, "run", side_effect=["", setup.SetupError("failed")]),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(setup.SetupError) as raised,
        ):
            setup.apply(values)
        self.assertIn(setup.NAMES[0], str(raised.exception))
        self.assertNotIn("private-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
