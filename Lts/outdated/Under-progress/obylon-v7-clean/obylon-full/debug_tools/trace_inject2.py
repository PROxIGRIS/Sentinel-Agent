import re

with open('Obylon.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace specific log lines or comments in main() with T_LOG
replacements = [
    (r'def main\(\) -> None:', r'def main() -> None:\n    T_LOG("Entering main()")'),
    (r'harden_installation\(\)', r'T_LOG("Calling harden_installation()"); harden_installation(); T_LOG("harden_installation() finished")'),
    (r'vault_loaded = vault\.load\(\)', r'T_LOG("Calling vault.load()"); vault_loaded = vault.load(); T_LOG("vault.load() finished")'),
    (r'identity_result = wait_for_identity_validation\(vault\)', r'T_LOG("Calling wait_for_identity_validation"); identity_result = wait_for_identity_validation(vault); T_LOG("wait_for_identity_validation finished")'),
    (r'sb = _build_supabase_client\(\)', r'T_LOG("Calling _build_supabase_client"); sb = _build_supabase_client(); T_LOG("_build_supabase_client finished")'),
    (r'session = sb\.auth\.refresh_session\(\)', r'T_LOG("Calling sb.auth.refresh_session"); session = sb.auth.refresh_session(); T_LOG("sb.auth.refresh_session finished")'),
    (r'session = sb\.auth\.get_session\(\)', r'T_LOG("Calling sb.auth.get_session"); session = sb.auth.get_session(); T_LOG("sb.auth.get_session finished")'),
    (r'_boot_t_bucket\.start\(\)', r'T_LOG("Starting _boot_t_bucket"); _boot_t_bucket.start()'),
    (r'_boot_t_identity\.start\(\)', r'T_LOG("Starting _boot_t_identity"); _boot_t_identity.start()'),
    (r'with urllib\.request\.urlopen\(req, context=ctx, timeout=5\) as response:', r'T_LOG("Sending boot-time license heartbeat (5s timeout)"); with urllib.request.urlopen(req, context=ctx, timeout=5) as response:\n                T_LOG("Boot-time license heartbeat returned")'),
    (r'WARDEN = WorkstationGuard\(\)', r'T_LOG("Initializing WorkstationGuard"); WARDEN = WorkstationGuard()'),
    (r'if WARDEN\.start\(\):', r'T_LOG("Calling WARDEN.start() (IPC security_ready)"); if WARDEN.start():\n                T_LOG("WARDEN.start() returned True")'),
    (r'_boot_t_bucket\.join\(timeout=30\)', r'T_LOG("Joining _boot_t_bucket"); _boot_t_bucket.join(timeout=30); T_LOG("_boot_t_bucket joined")'),
    (r'_boot_t_identity\.join\(timeout=30\)', r'T_LOG("Joining _boot_t_identity"); _boot_t_identity.join(timeout=30); T_LOG("_boot_t_identity joined")'),
    (r'threading\.Thread\(target=consume_core_events_loop', r'T_LOG("Starting consume_core_events_loop thread"); threading.Thread(target=consume_core_events_loop'),
    (r'start_usb_insertion_monitor\(\)', r'T_LOG("Calling start_usb_insertion_monitor"); start_usb_insertion_monitor(); T_LOG("start_usb_insertion_monitor finished")'),
    (r'if not _core_ipc_call\(\{"cmd": "ping"\}\)\.get\("ok"\):', r'T_LOG("Calling _core_ipc_call ping"); ping_res = _core_ipc_call({"cmd": "ping"}); T_LOG("ping returned"); if not ping_res.get("ok"):'),
    (r'BuildInfo\.print_banner\(\)', r'T_LOG("Calling BuildInfo.print_banner"); BuildInfo.print_banner()')
]

for old, new in replacements:
    content = re.sub(old, new, content)

# Also trace get_hardware_fingerprint_blocking
content = re.sub(r'def get_hardware_fingerprint_blocking\(timeout: float = FINGERPRINT_HELPER_TIMEOUT_SEC\) -> str \| None:', r'def get_hardware_fingerprint_blocking(timeout: float = FINGERPRINT_HELPER_TIMEOUT_SEC) -> str | None:\n    T_LOG(f"get_hardware_fingerprint_blocking called with timeout {timeout}")', content)

with open('Obylon.py', 'w', encoding='utf-8') as f:
    f.write(content)
