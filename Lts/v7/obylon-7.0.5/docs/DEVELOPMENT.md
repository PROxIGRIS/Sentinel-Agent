# Development Guide

Obylon is intentionally split into production components and tooling.

## Production path

`src/brain` contains the Python Brain. `obylonc` contains the administrative Go CLI. `rust` contains the low-level Broker/Core components. Runtime assets are under `assets/data` and packaged installer material is under `installer`.

## Build path

Use `build/obylon.spec` for the PyInstaller build and `installer/obylon-setup.iss` for the Windows installer. Release metadata is kept under `release/`.

## Tooling path

Everything under `tools/` is development/release/validation support and should not be treated as part of the runtime product.

## Change hygiene

Keep runtime code free of temporary patches and machine-specific scripts. Prefer adding a small, named module under `src/brain/` when a capability is genuinely production functionality. Prefer a test under `tests/` when the code is not itself a product feature.
