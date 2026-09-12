# Obylon Sentinel Agent (v7 LTS)

The Obylon Sentinel Agent is a zero-trust, stealth workstation monitor designed for school-managed devices. It enforces policies, monitors hardware telemetry, and securely syncs offline evidence (screenshots, webcams) to the Supabase backend.

## Architecture

- **ObylonBroker.exe (Rust):** Runs as a SYSTEM service in Session 0. Monitors user logins and cleanly spawns the Core into the interactive session. Handles strict Windows folder ACL generation.
- **ObylonCore.exe (Rust):** The high-speed enforcer. Uses native Windows API hooks (SetWindowsHookEx) to monitor active windows, block USBs, and freeze the screen with a tactical overlay in under 0.0ms latency.
- **Obylon.py (Python / PyInstaller):** The "Brain". Handles complex Supabase cryptography, JWT rotation, SQLite offline vault queuing, and the AI Lexical Neural Engine. Connects to ObylonCore via local IPC.

## Building the Agent

You need Python 3.14 (or equivalent), PyInstaller, InnoSetup 6, and the Rust toolchain.

1. Compile the Rust binaries:
   cd rust
   cargo build --release
   cd ..
2. Build the final installer (bundles everything into obylon-setup.exe):
   python -m PyInstaller -y obylon.spec
   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" obylon-setup.iss

## Licensing

Agents activate via the obylonc.exe Go binary using the hidden --key-file flag to prevent unauthorized token exposure in Windows Task Manager.
