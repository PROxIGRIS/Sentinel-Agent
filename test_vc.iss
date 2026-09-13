[Setup]
AppName=Test
AppVersion=1.0
DefaultDirName={pf}\Test
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=test_vc
DisableWelcomePage=no

[Code]
function InitializeSetup(): Boolean;
var
  Key: String;
  Bld: Cardinal;
  has64Reg, has32Reg: Boolean;
  has64Files, has32Files: Boolean;
  ResultStr: String;
begin
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  has64Reg := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);
  
  Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86';
  has32Reg := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);

  has64Files := FileExists(ExpandConstant('{sys}\VCRUNTIME140.dll')) and FileExists(ExpandConstant('{sys}\VCRUNTIME140_1.dll'));
  has32Files := FileExists(ExpandConstant('{syswow64}\VCRUNTIME140.dll'));

  ResultStr := 'IsWin64: ' + IntToStr(Integer(IsWin64)) + #13#10 +
               'Is64BitInstallMode: ' + IntToStr(Integer(Is64BitInstallMode)) + #13#10 +
               '64Reg: ' + IntToStr(Integer(has64Reg)) + #13#10 +
               '32Reg: ' + IntToStr(Integer(has32Reg)) + #13#10 +
               '64Files: ' + IntToStr(Integer(has64Files)) + #13#10 +
               '32Files: ' + IntToStr(Integer(has32Files));
               
  SaveStringToFile(ExpandConstant('{src}\test_out.txt'), ResultStr, False);
  Result := False;
end;
