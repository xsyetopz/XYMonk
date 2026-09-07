# Contributing to Delay Lama

Install:

- [rustup](https://rustup.rs/) with the toolchain declared in `rust-toolchain.toml`
- [just](https://github.com/casey/just)
- full Xcode only when working on AUv3 or universal macOS packaging

Clone the repository, create a focused branch, and run commands from the repository root.

## Build and test

Run the Rust test suite:

```sh
just rust-test
```

Build the release package:

```sh
just rust-build
```

Before submitting a Rust change, run:

```sh
cargo fmt --all -- --check
cargo test
cargo clippy --all-targets --all-features
```

CI runs tests and release builds on Linux, macOS, and Windows, only on `main` in `xsyetopz/XYMonk`. Cross-platform plug-in builds and release signing are documented in `README.md`.

## Repository boundaries

- Put shared synthesis behavior in `src/synthesizer/`.
- Put format-independent host state and translation in `src/host/`.
- Keep Truce and editor integration in `src/plugin/`.
- Add regression coverage in the nearest unit-test module or the matching file under `tests/`.
- Do not commit `.env`, `target/`, installed plug-ins, or other generated build output.
- Preserve parameter IDs and saved-state compatibility unless the change explicitly introduces a migration.

More detailed implementation rules and test ownership are in `AGENTS.md`.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>[optional scope]: <imperative summary>
```

Use a lowercase summary with no trailing period. Accepted types are:

| Type | Use |
| --- | --- |
| `feat` | User-visible feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Behavior-preserving code change |
| `test` | Test-only change |
| `build` | Build, dependency, signing, or packaging change |
| `ci` | Continuous-integration change |
| `chore` | Repository maintenance |

Examples:

```text
fix(editor): play idle animation frames
docs: document AUv3 development installation
build: add universal macOS packaging
```

For a breaking change, add `!` after the type or scope and include a `BREAKING CHANGE:` footer describing the impact and migration.

## Pull requests

Keep one logical change per pull request. Include:

- the problem and the resulting behavior
- affected plug-in formats and platforms
- tests and builds run, with failures or skipped checks called out
- screenshots for visible editor changes
- compatibility or state-migration impact

Do not mix unrelated formatting, cleanup, or generated output into the change.
