"""Configure, upload, or check XYMonk's macOS release secrets."""

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
    if set(values) != set(NAMES):
        raise SetupError(
            "Secret file must contain exactly the five release secret names"
        )
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
            for name in NAMES:
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


def status():
    configured = {
        entry["name"]
        for entry in json.loads(
            run(["gh", "secret", "list", "--repo", REPOSITORY, "--json", "name"])
        )
    }
    for name in NAMES:
        print(f"{name}: {'configured' if name in configured else 'missing'}")
    return set(NAMES) <= configured


def apply(values):
    validate(values)
    print(f"Set or replace these secrets in {REPOSITORY}: {', '.join(NAMES)}")
    if input(f"Type {REPOSITORY} to confirm: ").strip() != REPOSITORY:
        raise SetupError("Upload cancelled; no secrets changed")
    completed = []
    try:
        for name in NAMES:
            run(["gh", "secret", "set", name, "--repo", REPOSITORY], input=values[name])
            completed.append(name)
    except SetupError:
        raise SetupError(
            "Upload failed; already updated: " + (", ".join(completed) or "none")
        ) from None
    if not status():
        raise SetupError("Upload finished but some secret names are missing")


def configure(path):
    if (path.exists() or path.is_symlink()) and input(
        "Replace existing .env.release? Type yes: "
    ) != "yes":
        raise SetupError("Configuration cancelled")
    certificate = Path(
        input("Developer ID Application .p12 path: ").strip()
    ).expanduser()
    if not 0 < certificate.stat().st_size <= 36864:
        raise SetupError(
            "Certificate must be nonempty and fit the 48 KiB encoded limit"
        )
    values = dict(
        zip(
            NAMES,
            (
                base64.b64encode(certificate.read_bytes()).decode("ascii"),
                getpass.getpass("Certificate password: "),
                secrets.token_urlsafe(32),
                getpass.getpass("Apple ID: "),
                getpass.getpass("Apple app-specific password: "),
            ),
        )
    )
    save(path, values)
    print("Saved private .env.release; nothing uploaded. Run apply to upload.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("configure", "apply", "status"))
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parent.parent
        guard(root)
        if args.command != "status" and not sys.stdin.isatty():
            raise SetupError("configure and apply require an interactive terminal")
        path = root / ".env.release"
        if args.command == "configure":
            configure(path)
        elif args.command == "apply":
            apply(read(path))
        else:
            status()
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
