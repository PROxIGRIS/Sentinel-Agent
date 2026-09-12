# =============================================================================
# Comprehensive fix for all Obylon runtime errors
# =============================================================================
#
# Issues diagnosed from C:\ProgramData\Obylon\logs\obylon.log:
#
# 1. OCR job failed: tesseract path resolves to _MEI temp dir
#    Root cause: _get_tesseract_path() checks sys._MEIPASS first (onefile
#    extraction dir), but in --onedir mode tesseract is next to the exe,
#    not inside _internal/. Fix: check sys.executable dir first.
#
# 2. "Auth session missing" / HTTP 401 on license heartbeat:
#    Root cause: ACCESS_TOKEN global is initialized to None at line 170.
#    It's only set if vault.get("ACCESS_TOKEN") returns truthy. But the
#    boot-time sb.auth.refresh_session() at line 7203 can fail silently,
#    leaving the global ACCESS_TOKEN = None. Then the license_heartbeat_loop
#    sends "Bearer None" which the Edge Function rejects as 401.
#    Fix: After building the sb client, always re-read ACCESS_TOKEN from
#    the vault (which was set during activation), and if sb.auth.refresh
#    succeeds, update it.
#
# 3. offline-{UUID} leaking to Postgres:
#    Root cause: resolve_offline_wid() is only called in remote_config_loop
#    and scan_loop but NOT in heartbeat_loop or action_loop.
#    Fix: Add resolve_offline_wid() call to heartbeat_loop and action_loop.
#
# 4. Boot-time license check 401:
#    Root cause: Same as #2 — vault.get('ACCESS_TOKEN') can be a stale
#    JWT. The boot code at line 7246 uses vault.get('ACCESS_TOKEN') directly
#    instead of the refreshed ACCESS_TOKEN global.
#    Fix: Use the refreshed ACCESS_TOKEN global instead of vault.get().
#
# =============================================================================

import re

with open("Obylon.py", "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# ─────────────────────────────────────────────────────────────────────
# FIX 1: _get_tesseract_path() — check exe dir before _MEIPASS
# ─────────────────────────────────────────────────────────────────────
old_tess = '''def _get_tesseract_path():
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller temp extraction dir
        base_dir = sys._MEIPASS
    elif getattr(sys, 'frozen', False):
        # Compiled exe directory
        base_dir = os.path.dirname(sys.executable)
    else:
        # Script directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    tessdata_dir = os.path.join(base_dir, "tesseract_engine", "tessdata")
    os.environ["TESSDATA_PREFIX"] = tessdata_dir
    return os.path.join(base_dir, "tesseract_engine", "tesseract.exe")'''

new_tess = '''def _get_tesseract_path():
    # In --onedir mode, tesseract is installed next to the exe by the ISS
    # installer, NOT inside _internal/. We must check the exe directory
    # first, then fall back to _MEIPASS for development builds.
    if getattr(sys, 'frozen', False):
        # Frozen exe — always resolve relative to the user-facing binary
        base_dir = os.path.dirname(sys.executable)
    elif hasattr(sys, '_MEIPASS'):
        # PyInstaller temp extraction dir (--onefile dev builds)
        base_dir = sys._MEIPASS
    else:
        # Script directory (unpackaged dev)
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    tessdata_dir = os.path.join(base_dir, "tesseract_engine", "tessdata")
    os.environ["TESSDATA_PREFIX"] = tessdata_dir
    return os.path.join(base_dir, "tesseract_engine", "tesseract.exe")'''

if old_tess in content:
    content = content.replace(old_tess, new_tess)
    changes += 1
    print(f"[FIX 1] ✓ _get_tesseract_path(): prioritize sys.executable over _MEIPASS")
else:
    old_tess_crlf = old_tess.replace("\n", "\r\n")
    new_tess_crlf = new_tess.replace("\n", "\r\n")
    if old_tess_crlf in content:
        content = content.replace(old_tess_crlf, new_tess_crlf)
        changes += 1
        print(f"[FIX 1] ✓ _get_tesseract_path(): prioritize sys.executable over _MEIPASS (CRLF)")
    else:
        print(f"[FIX 1] ✗ old_tess not found — may already be fixed")

# ─────────────────────────────────────────────────────────────────────
# FIX 2: Load ACCESS_TOKEN from vault BEFORE building sb client
# ─────────────────────────────────────────────────────────────────────
old_token_load = '''        # 3. Ignite the Supabase Engine FIRST to refresh tokens
        try:
            if not SUPABASE_URL or not SUPABASE_KEY:
                raise ValueError("Credentials missing")
            sb = _build_supabase_client()
            
            # Actively refresh token at boot to prevent stale 401s!
            try:
                session = sb.auth.refresh_session()
            except Exception:
                session = sb.auth.get_session()
                
            if session and session.access_token != vault.get("ACCESS_TOKEN"):
                vault._data["ACCESS_TOKEN"] = session.access_token
                vault._data["REFRESH_TOKEN"] = session.refresh_token
                vault._save()
        except Exception as e:
            logger.warning(f"Supabase offline mode. linkage failed: {e}", component="boot")
            sb = None'''

new_token_load = '''        # 3. Ignite the Supabase Engine FIRST to refresh tokens
        # Load tokens from vault into globals BEFORE building the client,
        # so _build_supabase_client() can set_session with them and so
        # the license heartbeat has a valid Bearer token from the start.
        ACCESS_TOKEN = vault.get("ACCESS_TOKEN")
        REFRESH_TOKEN = vault.get("REFRESH_TOKEN")
        try:
            if not SUPABASE_URL or not SUPABASE_KEY:
                raise ValueError("Credentials missing")
            sb = _build_supabase_client()
            
            # Actively refresh token at boot to prevent stale 401s!
            try:
                session = sb.auth.refresh_session()
            except Exception:
                session = sb.auth.get_session()
                
            if session and session.access_token:
                ACCESS_TOKEN = session.access_token
                REFRESH_TOKEN = session.refresh_token
                vault._data["ACCESS_TOKEN"] = ACCESS_TOKEN
                vault._data["REFRESH_TOKEN"] = REFRESH_TOKEN
                vault._save()
                logger.info("Session tokens refreshed at boot", component="boot")
        except Exception as e:
            logger.warning(f"Supabase offline mode. linkage failed: {e}", component="boot")
            sb = None'''

if old_token_load in content:
    content = content.replace(old_token_load, new_token_load)
    changes += 1
    print(f"[FIX 2] ✓ ACCESS_TOKEN loaded from vault before sb client build")
else:
    old_token_load_crlf = old_token_load.replace("\n", "\r\n")
    new_token_load_crlf = new_token_load.replace("\n", "\r\n")
    if old_token_load_crlf in content:
        content = content.replace(old_token_load_crlf, new_token_load_crlf)
        changes += 1
        print(f"[FIX 2] ✓ ACCESS_TOKEN loaded from vault before sb client build (CRLF)")
    else:
        print(f"[FIX 2] ✗ old_token_load not found — may already be fixed")

# ─────────────────────────────────────────────────────────────────────
# FIX 3: Boot-time license check uses refreshed ACCESS_TOKEN global
# ─────────────────────────────────────────────────────────────────────
old_boot_token = '''                headers={"Authorization": f"Bearer {vault.get('ACCESS_TOKEN')}", "Content-Type": "application/json"}'''
new_boot_token = '''                headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}'''

if old_boot_token in content:
    content = content.replace(old_boot_token, new_boot_token)
    changes += 1
    print(f"[FIX 3] ✓ Boot-time license check uses refreshed ACCESS_TOKEN global")
else:
    old_boot_token_crlf = old_boot_token.replace("\n", "\r\n")
    new_boot_token_crlf = new_boot_token.replace("\n", "\r\n")
    if old_boot_token_crlf in content:
        content = content.replace(old_boot_token_crlf, new_boot_token_crlf)
        changes += 1
        print(f"[FIX 3] ✓ Boot-time license check uses refreshed ACCESS_TOKEN global (CRLF)")
    else:
        print(f"[FIX 3] ✗ Boot-time token reference not found")

# ─────────────────────────────────────────────────────────────────────
# FIX 4: Add resolve_offline_wid to heartbeat_loop
# ─────────────────────────────────────────────────────────────────────
old_hb = '''def heartbeat_loop(workstation_id: str) -> None:
    _name_current_thread("heartbeat")
    while True:
        try:
            if sb is not None:'''

new_hb = '''def heartbeat_loop(workstation_id: str) -> None:
    _name_current_thread("heartbeat")
    while True:
        workstation_id = resolve_offline_wid(workstation_id)
        try:
            if sb is not None:'''

if old_hb in content:
    content = content.replace(old_hb, new_hb)
    changes += 1
    print(f"[FIX 4] ✓ resolve_offline_wid added to heartbeat_loop")
else:
    old_hb_crlf = old_hb.replace("\n", "\r\n")
    new_hb_crlf = new_hb.replace("\n", "\r\n")
    if old_hb_crlf in content:
        content = content.replace(old_hb_crlf, new_hb_crlf)
        changes += 1
        print(f"[FIX 4] ✓ resolve_offline_wid added to heartbeat_loop (CRLF)")
    else:
        print(f"[FIX 4] ✗ heartbeat_loop pattern not found — may already be fixed")

# ─────────────────────────────────────────────────────────────────────
# FIX 5: Add resolve_offline_wid to action_loop
# ─────────────────────────────────────────────────────────────────────
old_al = '''def action_loop(workstation_id: str) -> None:
    _name_current_thread("actions")
    while True:
        try:
            if sb is not None:'''

new_al = '''def action_loop(workstation_id: str) -> None:
    _name_current_thread("actions")
    while True:
        workstation_id = resolve_offline_wid(workstation_id)
        try:
            if sb is not None:'''

if old_al in content:
    content = content.replace(old_al, new_al)
    changes += 1
    print(f"[FIX 5] ✓ resolve_offline_wid added to action_loop")
else:
    old_al_crlf = old_al.replace("\n", "\r\n")
    new_al_crlf = new_al.replace("\n", "\r\n")
    if old_al_crlf in content:
        content = content.replace(old_al_crlf, new_al_crlf)
        changes += 1
        print(f"[FIX 5] ✓ resolve_offline_wid added to action_loop (CRLF)")
    else:
        print(f"[FIX 5] ✗ action_loop pattern not found — may already be fixed")

# ─────────────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────────────
with open("Obylon.py", "w", encoding="utf-8") as f:
    f.write(content)

print(f"\n{'='*50}")
print(f"Total fixes applied: {changes}")
print(f"{'='*50}")
