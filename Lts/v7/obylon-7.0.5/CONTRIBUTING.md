# Contributing to Obylon

## Repository layout

- `src/brain/` — production Python Brain and its supporting modules.
- `obylonc/` — production Go administration/authentication CLI.
- `rust/` — production Rust Broker/Core/Common components.
- `assets/` — runtime data and packaged assets.
- `installer/` — Inno Setup installer definition.
- `build/` — PyInstaller build definition.
- `tests/` — maintained automated tests and platform checks.
- `tools/` — developer, release, and validation utilities. These are not runtime components.
- `docs/` — architecture, engineering history, migrations, and operational notes.
- `release/` — release metadata.

## Production source rule

Code under `src/brain/`, `obylonc/`, and `rust/` is production source. Do not add one-off repair scripts, experiments, trace injectors, or diagnostic utilities beside production code. Put them under `tools/dev/` and document anything that must be run as part of a release process.

## Tests

Python tests live in `tests/python/`. Go tests that belong to the CLI stay with the Go package under `obylonc/`. Standalone cross-check programs live under `tests/go/` and are not part of the shipped executable.
