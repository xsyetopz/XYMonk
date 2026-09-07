# Contributing

Use the pinned rustup toolchain and the platform prerequisites in [Build](#build). Run commands from the repository root. `just rust-build` builds a release library; `just rust-test` runs tests.

Before submitting:

```sh
cargo fmt --all -- --check
cargo test
cargo clippy --all-targets --all-features
python3 -m unittest discover -s scripts -p 'test_*.py'
```

For iOS changes, also check `aarch64-apple-ios` and `aarch64-apple-ios-sim` with `cargo check --target <target> --no-default-features --features au` on macOS with full Xcode.

Keep DSP in `src/synthesizer/`, host translation in `src/host/`, and Truce/editor integration in `src/plugin/`. Preserve parameter IDs, saved-state compatibility, and realtime safety. Add regressions near the changed behavior. See [AGENTS.md](AGENTS.md) for implementation rules.

Never commit private signing files, `.env`, `.env.release`, `target/`, or installed plug-ins. CI and release jobs run only for `xsyetopz/XYMonk` on `main`.

Use Conventional Commits: `type(scope): lowercase summary`, without a trailing period. Types: `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, `chore`. Breaking changes need `!` and a `BREAKING CHANGE:` footer explaining migration.

Keep pull requests focused. State the behavior change, affected formats/platforms, compatibility impact, and validation results, including skipped or failed checks. Include screenshots for editor changes.

## Build

Install Rust through rustup (`rust-toolchain.toml` pins the version). Build from the repository root. Prerequisites:

- **Windows:** Visual Studio Build Tools with Desktop development with C++ and the Windows SDK. Use the MSVC Rust toolchain.
- **Linux:** a C/C++ toolchain, pkg-config, ALSA and X11 development libraries. On Ubuntu:

  ```sh
  sudo apt-get install build-essential pkg-config libasound2-dev libx11-dev libx11-xcb-dev libxcb1-dev libxcursor-dev libxrandr-dev libxi-dev libgl1-mesa-dev libvulkan1
  ```

- **macOS/iOS:** Xcode Command Line Tools; full Xcode and Python 3.11+ for AUv3, iOS, and universal packaging.

Build desktop CLAP, VST3, and LV2:

```sh
cargo install cargo-truce --version 6.3.0 --locked
cargo truce build -p xymonk --clap --vst3 --lv2 --target-cpu baseline
```

Bundles go to `target/bundles/`; nothing is installed. `baseline` avoids requiring AVX2 on x86_64.

With `just` and a POSIX shell (Git Bash on Windows), `just rust-install vst3` builds and installs VST3 per-user, loading `.env` when present. Windows installs go to `%LOCALAPPDATA%\Programs\Common\VST3`; add that folder to the DAW's scan paths if needed. See [justfile](justfile) for other formats and commands.

For macOS AUv2, use `cargo truce build -p xymonk --au2 --target-cpu baseline`. For AUv3:

```sh
python3 scripts/auv3.py
python3 scripts/auv3.py --universal-package
```

The second command builds all five formats in `target/universal-bundles/` and an installer in `target/dist/`. Local builds are not notarized. Keep signing values in ignored `.env`; see [.env.example](.env.example).

For development AUv3 registration, set `AUV3_SIGNING_IDENTITY` to an Apple Development certificate, then run `just install-auv3-dev` and `just verify-auv3-registration`.

### iOS

On macOS with full Xcode, build a device/simulator development library:

```sh
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
cargo truce package --ios --xcframework -p xymonk
```

Output: `target/ios/xcframework/`, not an installable app. With a booted ARM64 simulator, `cargo truce install --ios -p xymonk` builds and installs the AUv3 container.
