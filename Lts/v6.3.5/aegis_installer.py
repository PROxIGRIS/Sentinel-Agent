import os
import sys
import ctypes
import subprocess
import json
import urllib.request
import uuid
import socket
import platform

try:
    from supabase import create_client
    import win32crypt
except ImportError:
    sys.exit("Please install dependencies: pip install supabase pywin32")

# ==========================================
# ENTERPRISE CONFIGURATION
# ==========================================
SUPABASE_URL = "YOUR_SUPABASE_URL"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY"
PAYLOAD_URL = "YOUR_PAYLOAD_URL" # The Supabase public link to ObylonSentinel.exe

CRYPTPROTECT_LOCAL_MACHINE = 0x04

class ObylonVault:
    def __init__(self, config_file="obylon.enc"):
        self.config_dir = os.environ.get('PROGRAMDATA', 'C:\\ProgramData') + "\\Obylon"
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = os.path.join(self.config_dir, config_file)

    def _encrypt(self, data: bytes) -> bytes:
        return win32crypt.CryptProtectData(data, "ObylonSecure", None, None, None, CRYPTPROTECT_LOCAL_MACHINE)

    def provision(self, sb_url, sb_key, token, school, expiry):
        data = {"SUPABASE_URL": sb_url, "SUPABASE_KEY": sb_key, "LICENSE_TOKEN": token, "SCHOOL_NAME": school, "EXPIRES_AT": expiry}
        encrypted = self._encrypt(json.dumps(data).encode("utf-8"))
        
        if os.path.exists(self.config_file):
            subprocess.run(["attrib", "-H", "-R", self.config_file], shell=True, capture_output=True)
            
        with open(self.config_file, "wb") as f: 
            f.write(encrypted)
            
        try: ctypes.windll.kernel32.SetFileAttributesW(str(self.config_file), 2)
        except: pass

def is_admin():
    try: return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except: return False

def os_info() -> dict:
    return {"platform": platform.system(), "release": platform.release(), "host": socket.gethostname()}

def get_hw_uuid() -> str:
    path = os.path.join(os.path.expanduser("~"), ".sentinel_id")
    if os.path.exists(path):
        with open(path, "r") as f: return f.read().strip()
    new_id = str(uuid.uuid4())
    try:
        with open(path, "w") as f: f.write(new_id)
        subprocess.run(["attrib", "+H", path], shell=True, capture_output=True)
    except: pass
    return new_id

def main():
    print("===================================================")
    print("   OBYLON SENTINEL - ENTERPRISE SETUP WIZARD")
    print("===================================================")
    
    if not is_admin():
        print("[!] Administrator privileges required. Requesting elevation...")
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
        sys.exit(0)

    print("[+] Administrator Privileges Confirmed.")
    license_token = input("\nEnter School License Token (UUID): ").strip()

    print("\n[*] Validating License against Obylon Cloud...")
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        res = sb.rpc("enroll_node", {
            "p_token": license_token,
            "p_hw_uuid": get_hw_uuid(),
            "p_name": socket.gethostname(),
            "p_os_info": os_info()
        }).execute()
        
        school_name = res.data.get("school_name")
        expires_at = res.data.get("expires_at")
        print(f"[+] License Validated! Enrolled to: {school_name}")
        print(f"[+] Expiry: {expires_at}")
    except Exception as e:
        print(f"[-] FATAL: Cloud handshake failed: {e}")
        input("Press Enter to exit...")
        sys.exit(1)

    target_dir = os.environ.get('PROGRAMDATA', 'C:\\ProgramData') + "\\Obylon"
    exe_path = os.path.join(target_dir, "obylon_agent.exe")

    print("\n[*] Configuring Windows Defender Exclusions...")
    subprocess.run(f'powershell -Command "Add-MpPreference -ExclusionPath \'{target_dir}\'"', shell=True, capture_output=True)

    print("[*] Downloading Obylon Payload...")
    urllib.request.urlretrieve(PAYLOAD_URL, exe_path)

    print("[*] Provisioning Cryptographic Vault...")
    vault = ObylonVault()
    vault.provision(SUPABASE_URL, SUPABASE_KEY, license_token, school_name, expires_at)

    print("[*] Registering NT AUTHORITY\\SYSTEM Boot Service...")
    subprocess.run(f'schtasks /create /tn "ObylonSentinel" /tr "{exe_path}" /sc onstart /ru SYSTEM /rl HIGHEST /f', shell=True, capture_output=True)
    subprocess.run('schtasks /run /tn "ObylonSentinel"', shell=True, capture_output=True)

    print("\n[SUCCESS] Obylon Sentinel has been successfully installed and armed.")
    print("[SUCCESS] The agent is now running silently in the background.")
    input("Press Enter to exit...")

if __name__ == "__main__":
    main()
