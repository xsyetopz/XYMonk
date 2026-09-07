# Contributing

Use the pinned rustup toolchain and the platform prerequisites in [README.md](README.md). Run commands from the repository root. `just rust-build` builds a release library; `just rust-test` runs tests.

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
