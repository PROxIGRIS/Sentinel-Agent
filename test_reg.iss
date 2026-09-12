[Setup]
AppName=Test
AppVersion=1.0
DefaultDirName={tmp}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Code]
function InitializeSetup: Boolean;
var
  Bld: Cardinal;
begin
  if RegQueryDWordValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Bld', Bld) then
    SaveStringToFile('C:\Sentinel-Agent\test_out.txt', 'HKLM x64=' + IntToStr(Bld) + ';', False);
  if RegQueryDWordValue(HKEY_LOCAL_MACHINE, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Bld', Bld) then
    SaveStringToFile('C:\Sentinel-Agent\test_out.txt', 'HKLM WOW64 x64=' + IntToStr(Bld) + ';', True);
  Result := False;
end;
