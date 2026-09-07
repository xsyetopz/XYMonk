"""Exercise the signing lifecycle with fake Apple tools, never real credentials."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FAKE_TOOL = r"""
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\n")
if name == "security":
    if args[0] == "list-keychains" and "-s" not in args:
        print('    "/tmp/original-login.keychain-db"')
    elif args[0] == "create-keychain":
        pathlib.Path(args[-1]).touch()
    elif args[0] == "delete-keychain":
        pathlib.Path(args[-1]).unlink()
    elif args[0] == "find-identity":
        print('  1) ABCDEF "Developer ID Application: Fixture (TESTTEAM01)"')
    elif args[0] == "list-keychains" and os.environ.get("FAIL_RESTORE") == "1":
        if args[-1] == "/tmp/original-login.keychain-db" and len(args) == 5:
            sys.exit(1)
elif name == "file":
    print("Mach-O universal binary" if pathlib.Path(args[-1]).name == "binary" else "data")
elif name == "codesign" and "-dv" in args:
    print("Authority=Developer ID Application: Fixture (TESTTEAM01)")
    print("TeamIdentifier=TESTTEAM01\nTimestamp=fixture\nCodeDirectory flags=0x10000(runtime)")
elif name == "hdiutil":
    pathlib.Path(args[-1]).write_bytes(b"DMG fixture")
elif name == "xcrun" and args[:2] == ["notarytool", "submit"]:
    print(json.dumps({"status": os.environ["NOTARY_STATUS"], "id": "fixture-id"}))
elif name == "xcrun" and args[:2] == ["notarytool", "log"]:
    pathlib.Path(args[-1]).write_text('{"issues": ["fixture rejection"]}')
"""


@unittest.skipUnless(os.name == "posix", "the macOS helper requires a POSIX shell")
class MacReleaseTests(unittest.TestCase):
    def test_signing_lifecycle_is_inside_out_and_notarization_fails_closed(self):
        for status in ("Accepted", "Invalid"):
            with (
                self.subTest(status=status),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                scripts = root / "scripts"
                scripts.mkdir()
                helper = scripts / "release-macos.sh"
                shutil.copy2(Path(__file__).with_name(helper.name), helper)
                tools = root / "fake-tools"
                tools.mkdir()
                for tool in (
                    "security",
                    "file",
                    "codesign",
                    "lipo",
                    "hdiutil",
                    "xcrun",
                    "spctl",
                ):
                    executable = tools / tool
                    executable.write_text(f"#!{sys.executable}\n{FAKE_TOOL}")
                    executable.chmod(0o755)
                bundles = root / "target/universal-bundles"
                for name in (
                    "Delay Lama.clap",
                    "Delay Lama.vst3",
                    "Delay Lama.component",
                    "Delay Lama.app",
                    "delay-lama.lv2",
                ):
                    directory = bundles / name
                    directory.mkdir(parents=True)
                    (directory / "binary").write_bytes(b"Mach-O fixture")
                extension = bundles / "Delay Lama.app/Contents/PlugIns/AUExt.appex"
                framework = extension / "Contents/Frameworks/Plugin.framework"
                framework.mkdir(parents=True)
                (extension / "binary").write_bytes(b"Mach-O fixture")
                (framework / "binary").write_bytes(b"Mach-O fixture")
                for name in ("README.md", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md"):
                    (root / name).write_text("## License\nFixture terms.\n")
                runner = root / "runner"
                runner.mkdir()
                log = root / "commands.jsonl"
                env = {
                    **os.environ,
                    "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
                    "RUNNER_TEMP": str(runner),
                    "GITHUB_ENV": str(root / "github-env"),
                    "RELEASE_VERSION": "0.1.0",
                    "DEVELOPER_ID_APPLICATION_CERT_BASE64": "Zml4dHVyZQ==",
                    "CERTIFICATE_SECRET": "fixture",
                    "KEYCHAIN_SECRET": "fixture",
                    "NOTARIZE_APPLE_ID": "fixture@example.invalid",
                    "NOTARIZE_PASSWORD": "fixture",
                    "NOTARY_STATUS": status,
                    "FAKE_LOG": str(log),
                }

                def invoke(command):
                    return subprocess.run(
                        ["bash", str(helper), command],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                setup = invoke("setup")
                self.assertEqual(setup.returncode, 0, setup.stderr)
                package = invoke("package")
                self.assertEqual(
                    package.returncode == 0, status == "Accepted", package.stderr
                )
                commands = [json.loads(line) for line in log.read_text().splitlines()]
                signed = [
                    command[-1]
                    for command in commands
                    if command[0] == "codesign" and "--force" in command
                ]
                app = next(path for path in signed if path.endswith("Delay Lama.app"))
                appex = next(path for path in signed if path.endswith("AUExt.appex"))
                inner = next(
                    path for path in signed if path.endswith("Plugin.framework")
                )
                self.assertLess(signed.index(inner), signed.index(appex))
                self.assertLess(signed.index(appex), signed.index(app))
                self.assertFalse(any(path.endswith(".lv2") for path in signed))
                stapled = any(
                    command[:3] == ["xcrun", "stapler", "staple"]
                    for command in commands
                )
                self.assertEqual(stapled, status == "Accepted")
                # Even a search-list restoration failure must remove private material.
                if status == "Invalid":
                    env["FAIL_RESTORE"] = "1"
                cleanup = invoke("cleanup")
                self.assertEqual(
                    cleanup.returncode == 0, status == "Accepted", cleanup.stderr
                )
                self.assertFalse((runner / "xymonk-release.keychain-db").exists())
                self.assertFalse((runner / "xymonk-release-state").exists())


if __name__ == "__main__":
    unittest.main()
