import os

fp = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\installer\obylon-setup.iss'
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

# Only require the architecture-appropriate VC runtime
old_checks = '''    if CurPageID = wpWelcome then
    begin
      NeedsVC64 := not VCReady(True);
      NeedsVC32 := not VCReady(False);'''

new_checks = '''    if CurPageID = wpWelcome then
    begin
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

content = content.replace(old_checks, new_checks)

with open(fp, 'w', encoding='utf-8') as f:
    f.write(content)
