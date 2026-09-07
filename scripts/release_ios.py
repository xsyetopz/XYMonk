"""Build a signed iOS IPA on an ephemeral, trusted GitHub runner; never upload to Apple."""

import argparse
import base64
import binascii
import hashlib
import os
import plistlib
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import tomllib
from setup_release_secrets import ALL_NAMES, REPOSITORY, SetupError, run


def decode(name, directory):
    try:
        data = base64.b64decode(os.environ[name], validate=True)
    except (KeyError, ValueError, binascii.Error):
        raise SetupError(f"Missing or invalid {name}") from None
    if not data:
        raise SetupError(f"Empty {name}")
    path = directory / name
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def profile_details(profile, bundle, distribution):
    entitlements = profile.get("Entitlements", {})
    teams = profile.get("TeamIdentifier", [])
    expires = profile.get("ExpirationDate")
    if (
        len(teams) != 1
        or not re.fullmatch(r"[A-Z0-9]{10}", teams[0])
        or entitlements.get("application-identifier") != f"{teams[0]}.{bundle}"
        or entitlements.get("com.apple.developer.team-identifier") != teams[0]
        or entitlements.get("get-task-allow") is not False
        or "iOS" not in profile.get("Platform", [])
        or profile.get("ProvisionsAllDevices")
        or not isinstance(expires, datetime)
        or expires.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)
    ):
        raise SetupError(
            "Profile must be unexpired iOS distribution for the expected team and bundle"
        )
    devices = profile.get("ProvisionedDevices", [])
    if bool(devices) != (distribution == "adhoc"):
        raise SetupError("Profile distribution type does not match the requested IPA")
    # SHA-1 is Apple's keychain identity identifier, not a security decision.
    certificates = {
        hashlib.sha1(certificate, usedforsecurity=False).hexdigest().upper()
        for certificate in profile.get("DeveloperCertificates", [])
    }
    if not certificates:
        raise SetupError("Profile contains no distribution certificates")
    return teams[0], certificates, set(devices)


def select_identity(app, extension, identities, distribution):
    app_team, app_certificates, app_devices = profile_details(
        app, "com.audionerdz.delaylama", distribution
    )
    extension_team, extension_certificates, extension_devices = profile_details(
        extension, "com.audionerdz.delaylama.AUExt", distribution
    )
    if app_team != extension_team or app_devices != extension_devices:
        raise SetupError(
            "App and extension profiles must use the same team and devices"
        )
    available = {
        match[0]
        for match in re.findall(
            r'\b([A-F0-9]{40}) "(Apple Distribution: [^"\n]+)"', identities
        )
    }
    matches = available & app_certificates & extension_certificates
    if len(matches) != 1:
        raise SetupError(
            "Expected one Apple Distribution private-key identity shared by both profiles"
        )
    return app_team, matches.pop()


def security(*arguments):
    return run(["security", *arguments])


@contextmanager
def signing_keychain(directory, certificate, password):
    keychain = str(directory / "signing.keychain-db")
    keychain_password = secrets.token_urlsafe(32)
    original = shlex.split(security("list-keychains", "-d", "user"))
    try:
        security("create-keychain", "-p", keychain_password, keychain)
        security("set-keychain-settings", "-lut", "21600", keychain)
        security("unlock-keychain", "-p", keychain_password, keychain)
        security(
            "import",
            str(certificate),
            "-P",
            password,
            "-t",
            "cert",
            "-f",
            "pkcs12",
            "-k",
            keychain,
            "-T",
            "/usr/bin/codesign",
        )
        security(
            "set-key-partition-list",
            "-S",
            "apple-tool:,apple:,codesign:",
            "-k",
            keychain_password,
            keychain,
        )
        security("list-keychains", "-d", "user", "-s", keychain, *original)
        yield security("find-identity", "-v", "-p", "codesigning", keychain)
    finally:
        # Deletion still runs if restoring the search list fails.
        try:
            security("list-keychains", "-d", "user", "-s", *original)
        finally:
            if Path(keychain).exists():
                security("delete-keychain", keychain)


def build(distribution, directory):
    certificate = decode("IOS_DISTRIBUTION_CERT_BASE64", directory)
    prefix = f"IOS_{distribution.upper()}"
    app_profile = decode(f"{prefix}_APP_PROFILE_BASE64", directory)
    extension_profile = decode(f"{prefix}_EXTENSION_PROFILE_BASE64", directory)
    password = os.environ.get("IOS_CERTIFICATE_PASSWORD")
    if not password:
        raise SetupError("Missing IOS_CERTIFICATE_PASSWORD")
    app, extension = [
        plistlib.loads(security("cms", "-D", "-i", str(path)).encode())
        for path in (app_profile, extension_profile)
    ]
    with signing_keychain(directory, certificate, password) as identities:
        team, identity = select_identity(app, extension, identities, distribution)
        environment = {
            key: value for key, value in os.environ.items() if key not in ALL_NAMES
        }
        environment.update(
            {
                "TRUCE_IOS_TEAM_ID": team,
                "TRUCE_IOS_SIGNING_IDENTITY": identity,
                "TRUCE_IOS_PROVISIONING_PROFILE": str(app_profile),
                "TRUCE_IOS_APPEX_PROVISIONING_PROFILE": str(extension_profile),
            }
        )
        subprocess.run(
            ["cargo", "truce", "package", "--ios", "-p", "xymonk"],
            env=environment,
            check=True,
        )
        # Check the exact payload staged by cargo-truce before uploading its IPA.
        payload = Path("target/ios/ipa/xymonk/Payload")
        apps = list(payload.glob("*.app"))
        if len(apps) != 1:
            raise SetupError("Expected one signed iOS app")
        run(["codesign", "--verify", "--deep", "--strict", str(apps[0])])
        version = tomllib.loads(Path("Cargo.toml").read_text())["package"]["version"]
        source = Path(f"target/dist/xymonk-{version}-ios.ipa")
        if not source.is_file() or not source.stat().st_size:
            raise SetupError("Signed IPA is missing or empty")
        output = Path("target/release-artifacts")
        output.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output / f"DelayLama-{version}-ios-{distribution}.ipa")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", choices=("adhoc", "testflight"))
    args = parser.parse_args()
    try:
        if (
            sys.platform != "darwin"
            or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or not os.environ.get("RUNNER_TEMP")
        ):
            raise SetupError(
                "iOS release signing requires this repository's main-branch macOS runner"
            )
        with tempfile.TemporaryDirectory(
            prefix="xymonk-ios-", dir=os.environ["RUNNER_TEMP"]
        ) as temporary:
            build(args.distribution, Path(temporary))
    except (SetupError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(
            str(error)
            if isinstance(error, SetupError)
            else "iOS packaging failed; no signing values printed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
