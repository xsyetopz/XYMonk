#!/usr/bin/env python3
"""Build Delay Lama AUv3 with fixed-size macOS host negotiation.

cargo-truce 6.3.0 advertises every host view configuration and makes the
controller view width/height sizable even when the Rust editor opts out of
resizing. Logic consequently expands the fixed 360x510 editor to its entire
2000x1752 plug-in pane. This bounded source patch is restored after the build.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

import tomllib

TEMPLATE_RELATIVE = Path("cargo-truce-6.3.0/templates/au3/AudioUnitFactory.swift")
OLD_CONFIG = """override func supportedViewConfigurations(
        _ availableViewConfigurations: [AUAudioUnitViewConfiguration]
    ) -> IndexSet {
        IndexSet(integersIn: availableViewConfigurations.indices)
    }"""
NEW_CONFIG = """override func supportedViewConfigurations(
        _ availableViewConfigurations: [AUAudioUnitViewConfiguration]
    ) -> IndexSet {
        // This editor has one intrinsic size, not a host-selectable layout.
        // Returning any proposed configuration opts Logic into its resizable
        // plug-in pane, whose outer window remains larger than the editor.
        IndexSet()
    }"""
OLD_SELECT = (
    "override func select(_ viewConfiguration: AUAudioUnitViewConfiguration) {}"
)
NEW_SELECT = """override func select(_ viewConfiguration: AUAudioUnitViewConfiguration) {
        // No host configuration is supported for this fixed-size editor.
    }"""
OLD_MASK = "v.autoresizingMask = [.width, .height]"
NEW_MASK = "v.autoresizingMask = [] // fixed-size Delay Lama editor"


OLD_WILL_APPEAR = r"""override func viewWillAppear() {
        super.viewWillAppear()
        logger.info("viewWillAppear: view.frame=\(self.view.frame.width)x\(self.view.frame.height)")
        setupGUIIfReady()
    }"""
NEW_WILL_APPEAR = r"""override func viewWillAppear() {
        super.viewWillAppear()
        let fixedEditorSize = NSSize(width: 360.0, height: 510.0)
        preferredContentSize = fixedEditorSize
        view.setFrameSize(fixedEditorSize)
        logger.info("viewWillAppear fixed: \(self.view.frame.width)x\(self.view.frame.height)")
        setupGUIIfReady()
    }"""

OLD_USER_PRESET_RECALL = """            } else {
                // User preset: replay the host-stored document state.
                guard let state = try? presetState(for: preset) else { return }
                fullStateForDocument = state
                _currentPreset = preset
            }"""
NEW_USER_PRESET_RECALL = """            } else {
                // Logic can assign a negative-numbered user preset before it
                // has written a backing document. Asking AudioToolbox for
                // that absent file raises an Objective-C exception, which
                // cannot be caught by Swift's `try?`. The host restores the
                // document state separately, so retain the preset reference
                // and let fullStateForDocument handle the actual restore.
                _currentPreset = preset
            }"""


def find_template() -> Path:
    cargo_home = Path.home() / ".cargo" / "registry" / "src"
    matches = list(cargo_home.glob(f"*/{TEMPLATE_RELATIVE}"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one cargo-truce 6.3.0 AUv3 template, found {matches}"
        )
    return matches[0]


def patched(source: str) -> str:
    if (
        source.count(OLD_CONFIG) != 1
        or source.count(OLD_SELECT) != 1
        or source.count(OLD_MASK) != 1
        or source.count(OLD_WILL_APPEAR) != 1
        or source.count(OLD_USER_PRESET_RECALL) != 1
    ):
        raise RuntimeError(
            "cargo-truce AUv3 template no longer matches the verified 6.3.0 source"
        )
    return (
        source.replace(OLD_CONFIG, NEW_CONFIG)
        .replace(OLD_SELECT, NEW_SELECT)
        .replace(OLD_MASK, NEW_MASK)
        .replace(OLD_WILL_APPEAR, NEW_WILL_APPEAR)
        .replace(OLD_USER_PRESET_RECALL, NEW_USER_PRESET_RECALL)
    )


def prepare_patched_tool() -> Path:
    template = find_template()
    patched_tool = Path("/tmp/xymonk-cargo-truce-fixed-auv3")
    shutil.rmtree(patched_tool, ignore_errors=True)
    shutil.copytree(template.parent.parent.parent, patched_tool)
    copied_template = patched_tool / "templates/au3/AudioUnitFactory.swift"
    copied_template.write_text(patched(copied_template.read_text()))
    return patched_tool


def rustup_environment() -> dict[str, str]:
    toolchain = tomllib.loads(Path("rust-toolchain.toml").read_text())["toolchain"][
        "channel"
    ]
    subprocess.run(
        [
            "rustup",
            "target",
            "add",
            "--toolchain",
            toolchain,
            "aarch64-apple-darwin",
            "x86_64-apple-darwin",
        ],
        check=True,
    )
    cargo = subprocess.run(
        ["rustup", "which", "--toolchain", toolchain, "cargo"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    environment = os.environ.copy()
    environment["PATH"] = f"{Path(cargo).parent}:{environment['PATH']}"
    return environment


def copy_universal_bundles() -> None:
    staging = Path("target/package/macos/plugin/delaylama")
    output = Path("target/universal-bundles")
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    for name in [
        "Delay Lama.clap",
        "Delay Lama.vst3",
        "Delay Lama.component",
        "Delay Lama.app",
        "delay-lama.lv2",
    ]:
        shutil.copytree(staging / name, output / name, symlinks=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universal-package", action="store_true")
    arguments = parser.parse_args()
    patched_tool = prepare_patched_tool()
    environment = rustup_environment()

    # AudioUnitFactory.swift is embedded into cargo-truce at compile time.
    # Compile and run the isolated patched tool rather than changing the
    # registry source or invoking an installed binary with its old template.
    command = [
        "cargo",
        "run",
        "--release",
        "--locked",
        "--manifest-path",
        str(patched_tool / "Cargo.toml"),
        "--",
    ]
    if arguments.universal_package:
        command.extend(
            [
                "package",
                "-p",
                "xymonk",
                "--formats",
                "clap,vst3,lv2,au2,au3",
                "--universal",
                "--no-notarize",
                "--target-cpu",
                "baseline",
                "--user",
            ]
        )
    else:
        shutil.rmtree(Path("target/tmp/au-v3"), ignore_errors=True)
        command.extend(["build", "--au3", "-p", "xymonk"])
    subprocess.run(command, check=True, env=environment)
    if arguments.universal_package:
        copy_universal_bundles()


if __name__ == "__main__":
    main()
