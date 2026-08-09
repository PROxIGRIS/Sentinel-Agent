import sys
from unittest.mock import MagicMock
sys.modules['supabase'] = MagicMock()
sys.modules['pynput'] = MagicMock()
sys.modules['cv2'] = MagicMock()

# Mock sys.exit to prevent the script from halting during import
original_exit = sys.exit
sys.exit = lambda *args, **kwargs: print(f"sys.exit bypassed: {args}")

try:
    import sentinel_agent
except Exception as e:
    print(f"Failed to import: {e}")

# Restore sys.exit
sys.exit = original_exit

def run_tests():
    print("--- ENGINE INTEGRITY REPORT ---")
    
    # 1. Normalizer Engine
    print("\n[1] Normalizer Engine")
    dirty = "p.o.r.n h\\/b \u200b !n"
    clean = sentinel_agent.normalize_haystack(dirty)
    print(f"  Input: {dirty}")
    print(f"  Output: {clean}")
    
    # 2. Lev Engine Fast Path
    print("\n[2] LevEngine Fast Path")
    fast_title = "pornhub.com"
    fast_proc = "chrome.exe"
    c_lev, cat, hit = sentinel_agent.LEV.evaluate_suspicion(fast_title, fast_proc)
    print(f"  Title: {fast_title} | Proc: {fast_proc}")
    print(f"  Score: {c_lev} | Category: {cat} | Hit: {hit}")
    
    # 3. Lev Engine Slow Path (Typo / Bypasses)
    print("\n[3] LevEngine Slow Path (Typo Simulation)")
    slow_title = "xnxx"
    slow_proc = "msedge.exe"
    # Wait, 'xnxx' is in INSTANT_STRIKE_LIST, it's an exact match.
    # Let's try 'rxblox' for roblox (warning/info)
    slow_title = "play robl0x online"
    c_lev, cat, hit = sentinel_agent.LEV.evaluate_suspicion(slow_title, slow_proc)
    print(f"  Title: {slow_title}")
    print(f"  Score: {c_lev} | Category: {cat} | Hit: {hit}")
    
    # 4. DOM Context Engine
    print("\n[4] DOM Context Engine")
    dom_text = "Check out this free streaming video gallery hd premium"
    is_violation, reason = sentinel_agent.classify_web_context(dom_text)
    print(f"  DOM: {dom_text}")
    print(f"  Violation: {is_violation} | Reason: {reason}")
    
    # 5. App Modifier Engine
    print("\n[5] App Modifier Engine")
    # Simulate an educational app running in temp
    proc_name = "C:\\Users\\student\\AppData\\Local\\Temp\\typing_tutor.exe"
    mod = sentinel_agent._get_app_modifier(proc_name)
    print(f"  Proc: {proc_name}")
    print(f"  Multiplier: {mod}")

    # 6. Final Arbitration Engine
    print("\n[6] Final Arbitration Engine")
    # Simulate: Lev = 0.70, DOM = 0.0, OCR = 0.85, Mod = 1.0
    final = sentinel_agent._calculate_final_arbitration(0.70, 0.0, 0.85, 1.0)
    print(f"  Inputs: Lev=0.70, DOM=0.0, OCR=0.85, Mod=1.0")
    print(f"  Final Score: {final}")

run_tests()
