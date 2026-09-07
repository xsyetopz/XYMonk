# Delay Lama

![Delay Lama (VST3) on FL Studio 2026](image.png)

**Delay Lama** is a monophonic vocal synthesizer rebuilt in Rust from the AudioNerdz plug-in. It shapes each note with a vowel/formant model. The monk interface follows the current voice.

Play it from a MIDI keyboard or the built-in XY pad. The pad controls pitch on the horizontal axis and vowel on the vertical axis. Four host parameters shape the sound:

- **Vowel** moves through the formant range.
- **Portamento** sets the glide time between notes.
- **Delay** controls the stereo delay mix.
- **Voice** changes the vocal character.

## Formats and platforms

| Platform | Release architectures | Formats |
| --- | --- | --- |
| Windows | x86_64 | CLAP, VST3, LV2 |
| Linux | x86_64, ARM64 | CLAP, VST3, LV2 |
| macOS | Apple Silicon + Intel, universal | CLAP, VST3, LV2, AUv2, AUv3 |

Linux builds use Ubuntu 24.04 and need X11 (or XWayland) and a Vulkan-capable graphics driver. BSD and other UNIX systems are not build targets: the current windowing dependency supports Windows, Linux, and macOS.

## Install

Extract the release archive or open the macOS DMG. Copy the format your DAW uses to its plug-in folder, then rescan:

| Platform | Plug-in folders |
| --- | --- |
| Windows | `%COMMONPROGRAMFILES%\CLAP`, `%COMMONPROGRAMFILES%\VST3`, `%APPDATA%\LV2` |
| Linux | `~/.clap`, `~/.vst3`, `~/.lv2` |
| macOS | `~/Library/Audio/Plug-Ins/{CLAP,VST3,LV2,Components}` |

For AUv3, copy `Delay Lama.app` to `/Applications` and open it once before rescanning your DAW. Windows and Linux archives are unsigned; the macOS DMG is signed and notarized by the release workflow.

## Build

Install Rust through rustup; `rust-toolchain.toml` pins Rust 1.98.0. Build from the repository root. Platform prerequisites:

- **Windows:** Visual Studio Build Tools with Desktop development with C++ and the Windows SDK. Use the MSVC Rust toolchain.
- **Linux:** a C/C++ toolchain, pkg-config, ALSA and X11 development libraries. On Ubuntu:

  ```sh
  sudo apt-get install build-essential pkg-config libasound2-dev libx11-dev libx11-xcb-dev libxcb1-dev libxcursor-dev libxrandr-dev libxi-dev libgl1-mesa-dev libvulkan1
  ```

- **macOS:** Xcode Command Line Tools; full Xcode and Python 3.11+ for AUv3 and universal packaging.

Build CLAP, VST3, and LV2 on any of these systems:

```sh
cargo install cargo-truce --version 6.3.0 --locked
cargo truce build -p xymonk --clap --vst3 --lv2 --target-cpu baseline
```

Bundles go to `target/bundles/`; nothing is installed. `cargo build --release` builds the default CLAP library without packaging. The `baseline` setting avoids requiring AVX2 on x86_64.

With [just](https://github.com/casey/just) and a POSIX shell (Git Bash on Windows), use `just rust-bundles` to build and `just rust-install` to build and install per-user. Add a format to limit either command, for example `just rust-install vst3`. Installation loads `.env` when present; restart or rescan your DAW afterward. On Windows, per-user VST3 installs go to `%LOCALAPPDATA%\Programs\Common\VST3`; add that folder to the DAW's scan paths if needed.

For Audio Units, use `cargo truce build -p xymonk --au2 --target-cpu baseline`. The AUv3 helper preserves the editor's fixed-size host integration:

```sh
python3 scripts/auv3.py
python3 scripts/auv3.py --universal-package
```

The second command builds all five formats for Apple Silicon and Intel in `target/universal-bundles/`, plus a local installer in `target/dist/`. Local builds are not notarized. Set `TRUCE_SIGNING_IDENTITY` for bundle signing and `TRUCE_INSTALLER_SIGNING_IDENTITY` to sign that installer; keep signing values in an ignored `.env` file.

For development AUv3 registration, install [just](https://github.com/casey/just), set `AUV3_SIGNING_IDENTITY` to an Apple Development certificate, and run `just install-auv3-dev` followed by `just verify-auv3-registration`. See the [justfile](justfile) for registration and removal commands.

## Releases

CI and releases run only in `xsyetopz/XYMonk` on `main`. To prepare macOS signing, install GitHub CLI, authenticate with repository-secret access, and run from `main`:

```sh
python3 scripts/setup_release_secrets.py configure
python3 scripts/setup_release_secrets.py apply
python3 scripts/setup_release_secrets.py status
```

`configure` asks for a Developer ID Application `.p12`, its password, an Apple ID, and an app-specific password. It generates a keychain password and saves all five values in ignored, private `.env.release`. `apply` requires confirmation before setting repository secrets; `status` checks names, never retrieves values. Do not share or commit this file.

Run the **Release** workflow manually from `main`, supplying an existing version tag (for example `v0.1.0`). Its version must match `Cargo.toml`, and it must point to the selected `main` commit. The workflow builds every format in the table, notarizes the macOS DMG, and creates a draft release with checksums. Tag pushes do not trigger releases.

## Test

```sh
cargo test --locked
cargo fmt --all -- --check
cargo clippy --all-targets --all-features
```

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

This software is provided free of charge and may be distributed freely, as long as all the files are distributed along with the plugin file. It may not be sold or included in any commercial package, nor used as part of any commercial promotion. Contact AudioNerdz if you wish to include it on a CD collection.
