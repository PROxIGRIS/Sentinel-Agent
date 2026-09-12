import re

iss_path = r'C:\Sentinel-Agent\Lts\v7\obylon-7.0.5\installer\obylon-setup.iss'
with open(iss_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add ArchitecturesAllowed=x64compatible in [Setup]
if 'ArchitecturesAllowed' not in content:
    content = content.replace('[Setup]\n', '[Setup]\nArchitecturesAllowed=x64compatible\n')

# 2. Add DownloadPage var and VCInstalled function
new_funcs = """
var
  DownloadPage: TDownloadWizardPage;

function VCInstalled(Is64Bit: Boolean): Boolean;
var
  Key: String;
  Bld: Cardinal;
begin
  if Is64Bit then
    Key := 'SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64'
  else
    Key := 'SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x86';
  
  Result := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);
end;

"""
content = content.replace('[Code]\n', '[Code]\n' + new_funcs)

# 3. Add to InitializeWizard
init_wiz = """procedure InitializeWizard;
begin
  ConfigureMainPalette;
  // BuildConfigPage;
  BuildLicensePage;
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;"""

content = re.sub(r'procedure InitializeWizard;\s*begin\s*ConfigureMainPalette;\s*// BuildConfigPage;\s*BuildLicensePage;\s*end;', init_wiz, content)

# 4. Replace NextButtonClick
old_next = """function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (Assigned(LicensePage)) and (CurPageID = LicensePage.ID) then
  begin
    if Trim(LicensePage.Values[0]) = '' then
    begin
      MsgBox('A license key is required because setup provisions the endpoint before completion.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(LicensePage.Values[1]) = '' then
    begin
      MsgBox('A node name is required so the workstation is registered with a stable inventory name.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;"""

new_next = """function NextButtonClick(CurPageID: Integer): Boolean;
var
  NeedsVC64, NeedsVC32: Boolean;
  ResultCode: Integer;
begin
  Result := True;
  
  if CurPageID = wpWelcome then
  begin
    NeedsVC64 := not VCInstalled(True);
    NeedsVC32 := not VCInstalled(False);
    
    if NeedsVC64 or NeedsVC32 then
    begin
      if MsgBox('Obylon requires the Microsoft Visual C++ Redistributable 2015-2022 to function properly.'#13#10#13#10 +
                'It appears to be missing on your system.'#13#10#13#10 +
                'Would you like to automatically download and install it now? (Recommended)', mbConfirmation, MB_YESNO) = IDNO then
      begin
        MsgBox('Installation cannot continue without the required dependencies. Obylon Broker and Core will crash on launch if the Visual C++ runtime is missing.', mbCriticalError, MB_OK);
        Result := False;
        Exit;
      end;
      
      DownloadPage.Clear;
      if NeedsVC64 then
        DownloadPage.Add('https://aka.ms/vs/17/release/vc_redist.x64.exe', 'vc_redist.x64.exe', '');
      if NeedsVC32 then
        DownloadPage.Add('https://aka.ms/vs/17/release/vc_redist.x86.exe', 'vc_redist.x86.exe', '');
        
      DownloadPage.Show;
      try
        try
          DownloadPage.Download;
        except
          MsgBox('Failed to download the dependencies. Please check your internet connection.', mbCriticalError, MB_OK);
          Result := False;
          Exit;
        end;
      finally
        DownloadPage.Hide;
      end;
      
      if NeedsVC64 then
      begin
        if not Exec(ExpandConstant('{tmp}\\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          MsgBox('Failed to install the 64-bit Visual C++ runtime.', mbError, MB_OK);
          Result := False;
          Exit;
        end;
      end;
      
      if NeedsVC32 then
      begin
        if not Exec(ExpandConstant('{tmp}\\vc_redist.x86.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          MsgBox('Failed to install the 32-bit Visual C++ runtime.', mbError, MB_OK);
          Result := False;
          Exit;
        end;
      end;
      
      if (NeedsVC64 and not VCInstalled(True)) or (NeedsVC32 and not VCInstalled(False)) then
      begin
        MsgBox('The dependency installation did not complete successfully. Setup will abort.', mbError, MB_OK);
        Result := False;
        Exit;
      end;
    end;
  end;

  if (Assigned(LicensePage)) and (CurPageID = LicensePage.ID) then
  begin
    if Trim(LicensePage.Values[0]) = '' then
    begin
      MsgBox('A license key is required because setup provisions the endpoint before completion.', mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if Trim(LicensePage.Values[1]) = '' then
    begin
      MsgBox('A node name is required so the workstation is registered with a stable inventory name.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;"""

content = content.replace(old_next, new_next)

with open(iss_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patched.")
