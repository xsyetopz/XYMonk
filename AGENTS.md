# AGENTS.md

These instructions apply repository-wide; direct user instructions and nearer nested `AGENTS.md` files take precedence. `CLAUDE.md` and `GEMINI.md` must remain symlinks to this file.

## Commands

- Use Rust `1.98.0`, run commands from the repository root, and keep signing values only in ignored `.env` files.
- Before completing Rust changes, run `cargo fmt --all -- --check`, `cargo test`, and `cargo clippy --all-targets --all-features`.
- Use `just rust-build` for a release build and `just rust-bundles` for macOS CLAP, VST3, and AUv2 bundles; the latter builds but does not install them.
- Follow `README.md` and `justfile` for AUv3 installation and registration, then verify installed artifacts before reporting success.

## Project rules

- Keep DSP in `src/synthesizer/`, host translation in `src/host/`, and Truce/editor integration in `src/plugin/`.
- Preserve parameter IDs in `src/plugin/parameter.rs`, the `DLM1` state layout, sample-offset events, and MIDI/pad ownership unless explicitly changing compatibility.
- Do not allocate, block, access files, or acquire contended locks in the audio render path; keep editor/audio communication bounded and nonblocking.
- Follow `rustfmt.toml`, `Cargo.toml` lints, and `clippy.toml`; keep unsafe code narrow, justified, and covered by required safety comments.
- Update the nearest tests for behavior changes and `tests/assets.rs` for artwork contract changes; never edit or commit generated files under `target/`.
- Follow `CONTRIBUTING.md` for documentation, Conventional Commits, and pull requests; preserve unrelated working-tree changes.
