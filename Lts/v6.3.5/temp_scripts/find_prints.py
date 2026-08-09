import re

def find_prints():
    with open(r"C:\Sentinel-Agent\Lts\v6.3.5\sentinel_agent.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    for i, line in enumerate(lines):
        if "print(" in line:
            print(f"{i+1}: {line.strip()}")

if __name__ == "__main__":
    find_prints()
