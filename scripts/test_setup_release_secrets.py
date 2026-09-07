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
        with (
            patch("builtins.input", return_value="no"),
            patch.object(setup, "run") as run,
        ):
            with (
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(setup.SetupError),
            ):
                setup.apply(values)
            run.assert_not_called()
        with (
            patch("builtins.input", return_value=setup.REPOSITORY),
            patch.object(setup, "run") as run,
        ):
            with (
                patch.object(setup, "status", return_value=True),
                contextlib.redirect_stdout(io.StringIO()),
            ):
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
        ):
            with self.assertRaises(setup.SetupError) as raised:
                setup.apply(values)
        self.assertIn(setup.NAMES[0], str(raised.exception))
        self.assertNotIn("private-value", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
