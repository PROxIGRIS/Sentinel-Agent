import re

iss_path = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\installer\obylon-setup.iss'
with open(iss_path, 'r', encoding='utf-8') as f:
    content = f.read()

new_vcinstalled = """function VCInstalled(Is64Bit: Boolean): Boolean;
var
  Key: String;
  Bld: Cardinal;
begin
  if Is64Bit then
  begin
    // Check 64-bit registry view first (which is the default in 64-bit install mode)
    Key := 'SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64';
    if RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld) then
    begin
      Result := True;
      Exit;
    end;
    // Fallback to check WOW6432Node just in case
    Key := 'SOFTWARE\\WOW6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64';
    Result := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);
  end
  else
  begin
    // 32-bit runtime is generally under WOW6432Node on 64-bit systems
    Key := 'SOFTWARE\\WOW6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x86';
    if RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld) then
    begin
      Result := True;
      Exit;
    end;
    // Fallback to native (if it ever changes)
    Key := 'SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x86';
    Result := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);
  end;
end;"""

old_vcinstalled = re.search(r'function VCInstalled\(Is64Bit: Boolean\): Boolean;.*?end;', content, re.DOTALL).group(0)
content = content.replace(old_vcinstalled, new_vcinstalled)

with open(iss_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patched.")
