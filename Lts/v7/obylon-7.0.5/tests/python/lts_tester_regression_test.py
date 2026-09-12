from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRAIN = (ROOT / "src" / "brain" / "Obylon.py").read_text(encoding="utf-8")
COMMON = (ROOT / "rust" / "common" / "src" / "lib.rs").read_text(encoding="utf-8")
CORE = (ROOT / "rust" / "core" / "src" / "main.rs").read_text(encoding="utf-8")


def test_boot_identity_is_async_and_fail_closed_on_mismatch():
    assert "def _identity_verification_loop()" in BRAIN
    assert "threading.Thread(target=_identity_verification_loop" in BRAIN
    assert "Hardware identity verification pending; background probe unavailable" in BRAIN
    assert "Hardware identity mismatch detected after background verification; stopping Brain." in BRAIN
    assert "os._exit(78)" in BRAIN
    # The normal boot path must not wait on the helper. The bounded helper
    # remains only for exceptional provisioning/legacy paths.
    standard = BRAIN[BRAIN.index('if __name__ == "__main__":'): ]
    assert "threading.Thread(target=_identity_verification_loop" in standard
    assert standard.index("threading.Thread(target=_identity_verification_loop") < standard.index("main()")


def test_remote_shutdown_is_immediate_and_core_backed():
    assert 'resp = _core_ipc_call({"cmd": "shutdown"}, timeout=1.5)' in BRAIN
    assert 'subprocess.Popen(\n                ["shutdown.exe", "/s", "/f", "/t", "0"]' in BRAIN
    assert "time.sleep(TERMINATE_GRACE_SEC)" not in BRAIN
    assert 'logger.info("Immediate shutdown accepted by ObylonCore"' in BRAIN
    assert 'dispatched = bool(controlled_shutdown(workstation_id, action_id))' in BRAIN
    assert 'dispatched = bool(controlled_shutdown(workstation_id, action["id"]))' in BRAIN


def test_shutdown_has_a_dedicated_ipc_schema_and_handler():
    assert "Shutdown," in COMMON
    assert 'r#"{\"cmd\":\"shutdown\"}"#' in COMMON
    assert "Ok(IpcRequest::Shutdown)" in CORE
    assert 'Command::new("shutdown.exe")' in CORE


def test_core_ipc_auth_is_constant_time_exact_pid():
    assert "fn is_authorized_brain_pid(client_pid: u32, expected_pid: u32) -> bool" in CORE
    assert "is_process_descendant_of" not in CORE
    assert "is_authorized_brain_pid(client_pid, expected_pid)" in CORE


def test_detection_scan_cadence_is_still_one_second():
    assert "SCAN_INTERVAL = 1" in BRAIN
    assert "time.sleep(10)" in BRAIN  # only the remote-config loop was relaxed


def test_boot_critical_path_does_not_block_on_session_restore_or_license_check():
    standard = BRAIN[BRAIN.index('if __name__ == "__main__":'): ]
    assert "threading.Thread(target=_session_bootstrap_loop" in standard
    assert "threading.Thread(target=_boot_license_watch" in standard
    assert standard.index("threading.Thread(target=_session_bootstrap_loop") < standard.index("main()")
    assert standard.index("threading.Thread(target=_boot_license_watch") < standard.index("main()")
    # No direct session initialization call should sit on the startup path.
    assert "session_manager.initialize_from_vault()" not in standard
