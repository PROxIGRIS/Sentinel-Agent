import os
import re

fp = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\installer\obylon-setup.iss'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

# Reliable replacement
pattern = r'(if CurPageID = wpWelcome then\s*begin\s*)NeedsVC64 := not VCReady\(True\);\s*NeedsVC32 := not VCReady\(False\);'

replacement = r'''\1
      if IsWin64 then
      begin
        NeedsVC64 := not VCReady(True);
        NeedsVC32 := False;
      end
      else
      begin
        NeedsVC64 := False;
        NeedsVC32 := not VCReady(False);
      end;'''

new_content = re.sub(pattern, replacement, content)

if new_content == content:
    print("WARNING: Replacement failed!")
else:
    print("SUCCESS: File updated.")
    with open(fp, 'w', encoding='utf-8') as f:
        f.write(new_content)
