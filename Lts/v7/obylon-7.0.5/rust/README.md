# Obylon Rust Components

This folder contains the native Windows components of the Obylon Agent, written in Rust for absolute minimum latency and maximum system integration.

- core/: The ObylonCore.exe enforcement agent. Manages tactical screen freezes, overlay rendering, and native SetWindowsHookEx API calls.
- roker/: The ObylonBroker.exe background service. Runs as SYSTEM, spawns ObylonCore.exe into the student's interactive session, and safely enforces C:\ProgramData\Obylon file ACLs.
- common/: Shared IPC models and telemetry types.
