# Obylon Sentinel Agent (v7 LTS)

Current source build: `7.0.5-202609061200`

The Obylon Sentinel Agent is a zero-trust workstation monitoring and policy-enforcement agent designed for school-managed devices. It enforces policies, monitors hardware telemetry, and securely syncs offline evidence (screenshots, webcams) to the Supabase backend.

## Repository layout

```text
src/brain/      Python production Brain
obylonc/        Go administration CLI
rust/           Rust Broker/Core/Common
assets/         Runtime data and packaged assets
installer/      Inno Setup definition
build/          PyInstaller definition
tests/          Maintained automated and platform checks
tools/          Development, release, and Windows validation utilities
docs/           Architecture, engineering notes, migrations, and history
release/        Release metadata
```

Development and one-off repair utilities live under `tools/`; they are not production runtime components.

## Architecture

- **ObylonBroker.exe (Rust):** Runs as a SYSTEM service in Session 0. Monitors user logins and cleanly spawns the Core into the interactive session. Handles strict Windows folder ACL generation.
- **ObylonCore.exe (Rust):** The high-speed enforcer. Uses native Windows API hooks (SetWindowsHookEx) to monitor active windows, block USBs, and freeze the screen through the native enforcement path with bounded latency.
- **Obylon.py (Python / PyInstaller):** The "Brain". Handles complex Supabase cryptography, JWT rotation, SQLite offline vault queuing, and the AI Lexical Neural Engine. Connects to ObylonCore via local IPC.

## Building the Agent

You need Python 3.14 (or equivalent), PyInstaller, Inno Setup 7.1+, and the Rust toolchain.

1. Compile the Rust binaries:
   cd rust
   cargo build --release
   cd ..
2. Ensure the local build tree also contains the required `tesseract_engine\tesseract.exe` plus its `tessdata` files. The source archive intentionally does not redistribute that third-party runtime.
3. Build the final installer (the installer now collects the license key and activates the endpoint before completion):
   python -m PyInstaller -y build\obylon.spec
   "C:\Program Files (x86)\Inno Setup 7\ISCC.exe" installer\obylon-setup.iss

## Licensing
Activation is installer-integrated. Setup collects a license key and node name, then securely hands the key to `obylonc activate --key-file ... --node-name ...` before marking installation complete. The same activation command remains available for re-provisioning and recovery.

## CLI authorization model
The CLI uses explicit read/diagnose/evidence/update/policy/warden scopes. Every operational command is represented in the admin registry, and commands can be addressed through `obylonc admin <command>` or `obylonc auth <admin-command>`. These paths do not bypass server authorization; they only make the administrative boundary explicit. `doctor --fix` requires `obylon.agent.update`.


The installer provisions the supplied license before setup completes. Manual `obylonc activate` remains available for re-provisioning and recovery.

Agents activate via the obylonc.exe Go binary using the hidden --key-file flag to prevent unauthorized token exposure in Windows Task Manager.


## Ad-network reputation
The agent bundles `assets/data/obylon_ad_networks.json` and loads it locally as a deterministic, hostname-bound contextual signal for browser monetization telemetry. It performs no network lookups and never blocks solely from the reputation database. Mixed-use networks are conservatively damped.

## Adaptive Scan Pressure (7.0.2 baseline)
The scanner now has bounded NORMAL/ELEVATED/AGGRESSIVE observation states. Local ad-network reputation is contextual evidence only. A fresh reputation match can increase observation pressure and combine with lexical, DOM, tripwire, ALE, or OCR signals to shorten scan cadence and admit additional OCR/evidence sampling. It cannot directly block a site or endpoint. Pressure uses hysteresis, freshness gating, bounded intervals, and clean-tick decay to avoid flapping.
