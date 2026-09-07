"""iOS signing boundaries, using synthetic profiles and mocked Apple tools."""

import base64
import contextlib
import hashlib
import os
import plistlib
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from unittest.mock import patch

import release_ios as ios

CERTIFICATE = b"synthetic certificate, not a credential"
IDENTITY = hashlib.sha1(CERTIFICATE, usedforsecurity=False).hexdigest().upper()


def profile(bundle, distribution="adhoc"):
    value = {
        "Entitlements": {
            "application-identifier": f"TESTTEAM01.{bundle}",
            "com.apple.developer.team-identifier": "TESTTEAM01",
            "get-task-allow": False,
        },
        "TeamIdentifier": ["TESTTEAM01"],
        "Platform": ["iOS"],
        "ExpirationDate": (datetime.now(timezone.utc) + timedelta(days=30)).replace(
            tzinfo=None
        ),
        "DeveloperCertificates": [CERTIFICATE],
    }
    match distribution:
        case "adhoc":
            value["ProvisionedDevices"] = ["fixture-device"]
    return value


def signing_values(distribution):
    values = {
        "IOS_DISTRIBUTION_CERT_BASE64": base64.b64encode(CERTIFICATE).decode(),
        "IOS_CERTIFICATE_PASSWORD": "fixture-password",
    }
    for role, suffix in (("APP", ""), ("EXTENSION", ".AUExt")):
        data = profile(f"com.audionerdz.delaylama{suffix}", distribution)
        values[f"IOS_{distribution.upper()}_{role}_PROFILE_BASE64"] = base64.b64encode(
            plistlib.dumps(data)
        ).decode()
    return values


def fake_security(command, *, log, fail_import=False, fail_restore=False):
    log.append(command.copy())
    match command[1]:
        case "cms":
            return Path(command[-1]).read_text()
        case "list-keychains":
            if "-s" not in command:
                return '"/fixture/login.keychain-db"'
            if fail_restore and command[4:] == ["-s", "/fixture/login.keychain-db"]:
                raise ios.SetupError("restore failed")
        case "create-keychain":
            Path(command[-1]).touch()
        case "import" if fail_import:
            raise ios.SetupError("import failed")
        case "find-identity":
            return f'1) {IDENTITY} "Apple Distribution: Fixture (TESTTEAM01)"'
        case "delete-keychain":
            Path(command[-1]).unlink()
    return ""


class IosSigningTests(unittest.TestCase):
    def test_package_uses_selected_profiles_scrubs_secrets_and_cleans_up(self):
        for distribution in ("adhoc", "testflight"):
            for fail_build in (False, True):
                prefix = f"IOS_{distribution.upper()}"
                commands = []
                with (
                    self.subTest(distribution=distribution, fail_build=fail_build),
                    tempfile.TemporaryDirectory() as temporary,
                    contextlib.chdir(temporary),
                    patch.dict(os.environ, signing_values(distribution)),
                    patch.object(
                        ios, "run", side_effect=partial(fake_security, log=commands)
                    ),
                    patch.object(ios.subprocess, "run") as cargo,
                ):
                    root = Path(temporary)
                    signing = root / "signing"
                    signing.mkdir()
                    Path("Cargo.toml").write_text('[package]\nversion = "0.1.0"\n')
                    Path("target/ios/ipa/xymonk/Payload/Delay Lama.app").mkdir(
                        parents=True
                    )
                    Path("target/dist").mkdir(parents=True)
                    Path("target/dist/xymonk-0.1.0-ios.ipa").write_bytes(b"fixture IPA")
                    if fail_build:
                        cargo.side_effect = subprocess.CalledProcessError(1, "cargo")
                        with self.assertRaises(subprocess.CalledProcessError):
                            ios.build(distribution, signing)
                    else:
                        ios.build(distribution, signing)
                    environment = cargo.call_args.kwargs["env"]
                    self.assertFalse(set(ios.ALL_NAMES) & environment.keys())
                    self.assertEqual(
                        environment["TRUCE_IOS_SIGNING_IDENTITY"], IDENTITY
                    )
                    self.assertEqual(
                        environment["TRUCE_IOS_PROVISIONING_PROFILE"],
                        str(signing / f"{prefix}_APP_PROFILE_BASE64"),
                    )
                    self.assertEqual(
                        cargo.call_args.args[0],
                        ["cargo", "truce", "package", "--ios", "-p", "xymonk"],
                    )
                    output = Path(
                        f"target/release-artifacts/DelayLama-0.1.0-ios-{distribution}.ipa"
                    )
                    self.assertEqual(output.exists(), not fail_build)
                    self.assertFalse((signing / "signing.keychain-db").exists())
                    self.assertEqual(commands[-1][1], "delete-keychain")

    def test_identity_must_match_both_profiles_and_include_private_key(self):
        app = profile("com.audionerdz.delaylama")
        extension = profile("com.audionerdz.delaylama.AUExt")
        identities = f'1) {IDENTITY} "Apple Distribution: Fixture (TESTTEAM01)"'
        self.assertEqual(
            ios.select_identity(app, extension, identities, "adhoc"),
            ("TESTTEAM01", IDENTITY),
        )
        for identity in (
            "",
            identities.replace("Apple Distribution", "Developer ID Application"),
        ):
            with self.assertRaises(ios.SetupError):
                ios.select_identity(app, extension, identity, "adhoc")
        extension["DeveloperCertificates"] = [b"different certificate"]
        with self.assertRaises(ios.SetupError):
            ios.select_identity(app, extension, identities, "adhoc")

    def test_profiles_reject_wrong_bundle_type_expiry_and_device_set(self):
        original = profile("com.audionerdz.delaylama")
        changes = (
            {"ExpirationDate": datetime(2000, 1, 1, tzinfo=timezone.utc)},
            {"ProvisionedDevices": []},
            {"ProvisionsAllDevices": True},
            {"Platform": ["OSX"]},
            {"Entitlements": {**original["Entitlements"], "get-task-allow": True}},
            {
                "Entitlements": {
                    **original["Entitlements"],
                    "application-identifier": "TESTTEAM01.*",
                }
            },
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ios.SetupError):
                ios.profile_details(
                    {**original, **change}, "com.audionerdz.delaylama", "adhoc"
                )
        testflight = profile("com.audionerdz.delaylama", "testflight")
        ios.profile_details(testflight, "com.audionerdz.delaylama", "testflight")
        extension = profile("com.audionerdz.delaylama.AUExt")
        extension["ProvisionedDevices"] = ["different-device"]
        with self.assertRaises(ios.SetupError):
            ios.select_identity(original, extension, "", "adhoc")

    def test_signing_failure_restores_search_list_and_deletes_keychain(self):
        for fail_restore in (False, True):
            commands = []
            with (
                tempfile.TemporaryDirectory() as temporary,
                patch.dict(os.environ, signing_values("adhoc")),
                patch.object(
                    ios,
                    "run",
                    side_effect=partial(
                        fake_security,
                        log=commands,
                        fail_import=True,
                        fail_restore=fail_restore,
                    ),
                ),
                self.assertRaises(ios.SetupError),
            ):
                ios.build("adhoc", Path(temporary))
            self.assertEqual(
                commands[-2],
                [
                    "security",
                    "list-keychains",
                    "-d",
                    "user",
                    "-s",
                    "/fixture/login.keychain-db",
                ],
            )
            self.assertEqual(commands[-1][1], "delete-keychain")


if __name__ == "__main__":
    unittest.main()
