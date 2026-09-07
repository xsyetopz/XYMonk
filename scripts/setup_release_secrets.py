"""Configure, upload, or check XYMonk's Apple release secrets."""

import argparse
import base64
import getpass
import json
import os
import secrets
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = "xsyetopz/XYMonk"
NAMES = (
    "DEVELOPER_ID_APPLICATION_CERT_BASE64",
    "CERTIFICATE_SECRET",
    "KEYCHAIN_SECRET",
    "NOTARIZE_APPLE_ID",
    "NOTARIZE_PASSWORD",
)
IOS_PROFILES = {
    "IOS_ADHOC_APP_PROFILE_BASE64": "Ad Hoc / main app (com.audionerdz.delaylama)",
    "IOS_ADHOC_EXTENSION_PROFILE_BASE64": "Ad Hoc / AUv3 extension (com.audionerdz.delaylama.AUExt)",
    "IOS_TESTFLIGHT_APP_PROFILE_BASE64": "TestFlight (App Store Connect) / main app (com.audionerdz.delaylama)",
    "IOS_TESTFLIGHT_EXTENSION_PROFILE_BASE64": "TestFlight (App Store Connect) / AUv3 extension (com.audionerdz.delaylama.AUExt)",
}
IOS_NAMES = ("IOS_DISTRIBUTION_CERT_BASE64", "IOS_CERTIFICATE_PASSWORD", *IOS_PROFILES)
ALL_NAMES = (*NAMES, *IOS_NAMES)


def names_for(platform):
    match platform:
        case "ios":
            return IOS_NAMES
        case _:
            return NAMES


class SetupError(Exception):
    """Safe diagnostic containing no secret values."""


def run(arguments, **kwargs):
    result = subprocess.run(
        arguments, capture_output=True, text=True, check=False, **kwargs
    )
    if result.returncode:
        raise SetupError(
            f"{arguments[0]} operation failed; check authentication and access"
        )
    return result.stdout.strip()


def guard(root):
    if Path(run(["git", "rev-parse", "--show-toplevel"], cwd=root)).resolve() != root:
        raise SetupError("Expected the XYMonk working tree")
    if run(["git", "branch", "--show-current"], cwd=root) != "main":
        raise SetupError("Release secrets may only be managed from main")
    origin = run(["git", "remote", "get-url", "origin"], cwd=root)
    actual = run(
        [
            "gh",
            "repo",
            "view",
            origin,
            "--json",
            "nameWithOwner",
            "--jq",
            ".nameWithOwner",
        ],
        cwd=root,
    )
    if actual != REPOSITORY:
        raise SetupError("Origin must resolve to xsyetopz/XYMonk")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env.release"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", ".env.release"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if tracked.returncode == 0 or ignored.returncode != 0:
        raise SetupError(".env.release must be ignored and untracked")


def validate(values):
    if not values or set(values) - set(ALL_NAMES):
        raise SetupError("Secret file contains unknown names or is empty")
    if any(
        not value or "\n" in value or "\r" in value or len(value.encode()) > 49152
        for value in values.values()
    ):
        raise SetupError(
            "Secrets must be nonempty, single-line values of at most 48 KiB"
        )


def save(path, values):
    validate(values)
    fd, temporary = tempfile.mkstemp(prefix=".env.release.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            for name in ALL_NAMES:
                if name in values:
                    output.write(f"{name}={shlex.quote(values[name])}\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read(path):
    if path.is_symlink() or not path.is_file():
        raise SetupError(".env.release must be a regular file, not a symlink")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise SetupError(".env.release permissions must be private (chmod 600)")
    values = {}
    for line in path.read_text().splitlines():
        words = shlex.split(line, comments=True)
        if not words:
            continue
        if len(words) != 1 or "=" not in words[0]:
            raise SetupError("Invalid secret file entry")
        name, value = words[0].split("=", 1)
        if name in values:
            raise SetupError("Duplicate secret file entry")
        values[name] = value
    validate(values)
    return values


def status(platform="macos"):
    names = names_for(platform)
    configured = {
        entry["name"]
        for entry in json.loads(
            run(["gh", "secret", "list", "--repo", REPOSITORY, "--json", "name"])
        )
    }
    for name in names:
        print(f"{name}: {'configured' if name in configured else 'missing'}")
    return set(names) <= configured


def apply(values, platform="macos"):
    validate(values)
    names = names_for(platform)
    missing = set(names) - set(values)
    if missing:
        raise SetupError("Missing secrets: " + ", ".join(sorted(missing)))
    print(f"Set or replace these secrets in {REPOSITORY}: {', '.join(names)}")
    if input(f"Type {REPOSITORY} to confirm: ").strip() != REPOSITORY:
        raise SetupError("Upload cancelled; no secrets changed")
    completed = []
    try:
        for name in names:
            run(["gh", "secret", "set", name, "--repo", REPOSITORY], input=values[name])
            completed.append(name)
    except SetupError:
        raise SetupError(
            "Upload failed; already updated: " + (", ".join(completed) or "none")
        ) from None
    if not status(platform):
        raise SetupError("Upload finished but some secret names are missing")


def encoded_file(prompt):
    path = Path(input(prompt).strip()).expanduser()
    if not path.is_file() or not 0 < path.stat().st_size <= 36864:
        raise SetupError("File must be nonempty and fit the 48 KiB encoded limit")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def configure(path, platform="macos"):
    values = read(path) if path.exists() or path.is_symlink() else {}
    if (path.exists() or path.is_symlink()) and input(
        f"Update {platform} entries in .env.release? Type yes: "
    ) != "yes":
        raise SetupError("Configuration cancelled")
    match platform:
        case "ios":
            values[IOS_NAMES[0]] = encoded_file("Apple Distribution .p12 path: ")
            password = getpass.getpass("Certificate password (Enter keeps existing): ")
            if password or IOS_NAMES[1] not in values:
                values[IOS_NAMES[1]] = password
            for name, label in IOS_PROFILES.items():
                values[name] = encoded_file(f"{label}\n.mobileprovision file path: ")
        case _:
            values.update(
                DEVELOPER_ID_APPLICATION_CERT_BASE64=encoded_file(
                    "Developer ID Application .p12 path: "
                ),
                CERTIFICATE_SECRET=getpass.getpass("Certificate password: "),
                KEYCHAIN_SECRET=secrets.token_urlsafe(32),
                NOTARIZE_APPLE_ID=getpass.getpass("Apple ID: "),
                NOTARIZE_PASSWORD=getpass.getpass("Apple app-specific password: "),
            )
    save(path, values)
    print("Saved private .env.release; nothing uploaded. Run apply to upload.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("configure", "apply", "status"))
    parser.add_argument("--platform", choices=("macos", "ios"), default="macos")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parent.parent
        guard(root)
        if args.command != "status" and not sys.stdin.isatty():
            raise SetupError("configure and apply require an interactive terminal")
        path = root / ".env.release"
        match args.command:
            case "configure":
                configure(path, args.platform)
            case "apply":
                apply(read(path), args.platform)
            case _:
                status(args.platform)
    except SetupError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, OSError, EOFError):
        print(
            "Unable to read inputs or execute tools; no secret values printed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
