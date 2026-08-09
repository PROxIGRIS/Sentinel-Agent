import sys
from unittest.mock import MagicMock
sys.modules['supabase'] = MagicMock()
sys.modules['pynput'] = MagicMock()
sys.modules['cv2'] = MagicMock()

original_exit = sys.exit
sys.exit = lambda *args, **kwargs: print(f"sys.exit bypassed: {args}")

try:
    import sentinel_agent
except Exception as e:
    print(f"Failed to import: {e}")

sys.exit = original_exit

def run_angel_tests():
    print("--- ANGEL ENGINE TESTS ---")
    
    # Test 1: Legitimate query (4 words radius)
    t1 = "the history of al gore"
    hit1 = "gore"
    res1 = sentinel_agent.apply_angel_engine(t1, hit1)
    print(f"Test 1 [Valid Radius]: {res1} (Expected: True)")
    
    # Test 2: Outside radius
    t2 = "the history of the very famous politician al gore"
    res2 = sentinel_agent.apply_angel_engine(t2, hit1)
    print(f"Test 2 [Outside Radius]: {res2} (Expected: False)")

    # Test 3: Keyword Stuffing
    t3 = "meaning meaning meaning meaning gore" 
    res3 = sentinel_agent.apply_angel_engine(t3, hit1)
    print(f"Test 3 [Keyword Stuffing]: {res3} (Expected: True)")

    # Test 4: Hardcore Veto
    t4 = "the meaning of pornhub"
    hit4 = "pornhub"
    res4 = sentinel_agent.apply_angel_engine(t4, hit4)
    print(f"Test 4 [Hardcore Veto]: {res4} (Expected: False)")

run_angel_tests()
