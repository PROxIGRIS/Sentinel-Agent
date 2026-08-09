import sentinel_agent
import sys

def test_usb():
    print("Testing USB function:")
    # We aren't on a USB so it should be false, but let's test the call doesn't crash
    # and maybe test mocking.
    res = sentinel_agent.is_running_from_usb("cmd.exe")
    print(f"is_running_from_usb('cmd.exe'): {res}")

if __name__ == "__main__":
    test_usb()
