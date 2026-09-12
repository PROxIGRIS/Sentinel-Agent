# Obylon Sentinel 7.0.5-LTS Release Checklist

## Completed in this source package

- Python source compilation: PASS
- Python functional/regression tests: 32 PASS
- Go tests: PASS
- Windows-targeted Go build: PASS
- No duplicate top-level Python function definitions detected
- Active release metadata aligned to 7.0.5 / build 7.0.5-202609061200
- Workstation registration no longer uses name-only identity or random UUID insertion
- Action dispatch no longer relies on UPDATE+SELECT claim response semantics
- Rename state persists across the live process and reboot
- Machine-wide node name is persisted under ProgramData, preventing per-user profile name drift
- Verified hardware fingerprint is bound to the canonical node ID; current schemas use the existing os_info JSON fallback, while newer schemas may use a dedicated hardware_fingerprint column
- Fresh installs promote the provisional machine UUID to a deterministic hardware-bound UUID without changing existing installations
- Existing node IDs and hardware UUIDs are preserved, so the 7.0.x identity contract remains backward-compatible

## External release gates still required

- Rust `cargo check/test` on the Windows build environment
- Real Windows endpoint boot/session/reboot validation
- Live Supabase registration/duplicate-node behavior validation
- Real dashboard rename/command end-to-end validation
- Inno Setup compilation
