"""Fix the warmup block in Obylon.py to exercise real dependencies."""
import re

with open("Obylon.py", "r", encoding="utf-8") as f:
    content = f.read()

old_block = '''    if len(sys.argv) > 1 and sys.argv[1] == "--warmup":
        print("Running first-start warmup...")
        try:
            _ensure_ocr_libs()
            try:
                import numpy
                import cv2
            except ImportError:
                pass
            import pynput
            import websockets
            
            import time
            import os
            import sys
            exe_dir = os.path.dirname(sys.executable)
            lock_path = os.path.join(exe_dir, "warmup.lock")
            if os.path.exists(lock_path):
                os.remove(lock_path)
            with open(lock_path, "w") as f:
                f.write(str(time.time()))
            sys.exit(0)
        except Exception as e:
            print(f"Warmup failed: {e}")
            sys.exit(1)'''

new_block = '''    if len(sys.argv) > 1 and sys.argv[1] == "--warmup":
        # ---------------------------------------------------------------
        # First-start preparation mode.
        #
        # Contract: initialize every expensive runtime component that
        # would otherwise delay the very first normal boot, then drop
        # warmup.lock ONLY after all required work succeeds.
        #
        # This must NOT start monitoring, enforcement, telemetry, or
        # any persistent background service.  It is purely a local
        # runtime initialization pass.
        # ---------------------------------------------------------------
        _warmup_ok = True
        _warmup_errors = []

        def _warmup_step(label, fn):
            nonlocal _warmup_ok
            try:
                fn()
                print(f"  [OK] {label}")
            except Exception as _e:
                _warmup_ok = False
                _warmup_errors.append(f"{label}: {_e}")
                print(f"  [FAIL] {label}: {_e}")

        print("Obylon first-start preparation")
        print("=" * 40)

        # 1. OCR stack (PIL + pytesseract + tesseract binary path)
        _warmup_step("OCR libraries (PIL + pytesseract)", _ensure_ocr_libs)

        # 2. Keyboard hook library
        _warmup_step("Input hook (pynput)", lambda: __import__("pynput"))

        # 3. WebSocket transport
        _warmup_step("WebSocket transport", lambda: __import__("websockets"))

        # 4. Crypto signing (optional — not required for warmup success)
        try:
            import nacl.signing  # noqa: F401
            print("  [OK] Crypto signing (nacl)")
        except ImportError:
            print("  [SKIP] Crypto signing (nacl) — optional")

        # 5. Process monitoring
        _warmup_step("Process monitoring (psutil)", lambda: __import__("psutil"))

        # 6. TLS certificates
        _warmup_step("TLS certificates (certifi)", lambda: __import__("certifi"))

        # 7. Win32 APIs (COM, services)
        _warmup_step("Win32 APIs", lambda: (__import__("win32event"), __import__("win32api")))

        print("=" * 40)

        exe_dir = os.path.dirname(sys.executable)
        lock_path = os.path.join(exe_dir, "warmup.lock")

        if _warmup_ok:
            # Delete any stale lock before writing a fresh one
            if os.path.exists(lock_path):
                os.remove(lock_path)
            with open(lock_path, "w") as _f:
                _f.write(str(time.time()))
            print(f"Warmup complete — lock written to {lock_path}")
            sys.exit(0)
        else:
            # Do NOT create lock on failure — installer will see timeout
            if os.path.exists(lock_path):
                os.remove(lock_path)
            print("Warmup FAILED — required components did not load:")
            for _err in _warmup_errors:
                print(f"  * {_err}")
            sys.exit(1)'''

if old_block in content:
    content = content.replace(old_block, new_block)
    with open("Obylon.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: warmup block replaced")
else:
    # Try with \r\n
    old_crlf = old_block.replace("\n", "\r\n")
    new_crlf = new_block.replace("\n", "\r\n")
    if old_crlf in content:
        content = content.replace(old_crlf, new_crlf)
        with open("Obylon.py", "w", encoding="utf-8") as f:
            f.write(content)
        print("OK: warmup block replaced (CRLF)")
    else:
        print("ERROR: old block not found")
        # Find the line for debugging
        for i, line in enumerate(content.split("\n")):
            if "--warmup" in line and "argv" in line:
                print(f"  Found --warmup reference at line {i+1}: {line.strip()}")
