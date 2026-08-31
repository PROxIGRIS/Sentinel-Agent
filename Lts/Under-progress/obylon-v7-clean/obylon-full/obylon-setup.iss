[Setup]
AppId={{f9a8b7c6-d5e4-f3a2-b1c0-123456789abc}
AppName=Obylon Sentinel Agent
AppVersion=7.0.0
AppPublisher=Umbraxis
DefaultDirName={commonpf64}\Obylon
DisableDirPage=auto
DisableProgramGroupPage=yes
LicenseFile=C:\Sentinel-Agent\Lts\v6.3.5\License.rtf
WizardStyle=modern
WizardResizable=yes
OutputDir=C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist
OutputBaseFilename=obylon-setup-final
SetupIconFile=C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\icon.ico
Compression=lzma2/fast
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
UninstallDisplayIcon={app}\obylonc.exe

[Dirs]
Name: "{commonappdata}\Obylon"; Permissions: system-full admins-full
Name: "{commonappdata}\Obylon\logs"; Permissions: system-full admins-full

[Files]
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist\obylon\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist\obylonc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\rust\target\release\ObylonBroker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\rust\target\release\ObylonCore.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Obylon v7\Agent\LTS update\tesseract_engine\*"; DestDir: "{app}\tesseract_engine"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/delete /tn ""ObylonAgent"" /f"; Flags: runhidden; RunOnceId: "RemoveObylonTask"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\Obylon"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
var
  CustomPage: TWizardPage;
  LicenseEdit: TNewEdit;
  SingleModeRadio: TNewRadioButton;
  FleetModeRadio: TNewRadioButton;

function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath)
  then begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;

procedure LicenseEditChange(Sender: TObject);
begin
  WizardForm.NextButton.Enabled := Trim(LicenseEdit.Text) <> '';
end;

procedure InitializeWizard;
var
  PageLabel: TLabel;
begin
  CustomPage := CreateCustomPage(wpSelectDir, 'License and Deployment', 'Configure license key and deployment mode.');

  SingleModeRadio := TNewRadioButton.Create(WizardForm);
  SingleModeRadio.Parent := CustomPage.Surface;
  SingleModeRadio.Top := 10;
  SingleModeRadio.Width := CustomPage.SurfaceWidth;
  SingleModeRadio.Caption := 'Single Workstation (Activate Immediately)';
  SingleModeRadio.Checked := True;

  FleetModeRadio := TNewRadioButton.Create(WizardForm);
  FleetModeRadio.Parent := CustomPage.Surface;
  FleetModeRadio.Top := SingleModeRadio.Top + SingleModeRadio.Height + 10;
  FleetModeRadio.Width := CustomPage.SurfaceWidth;
  FleetModeRadio.Caption := 'Master Image (Seed for Fleet Deployment)';

  PageLabel := TLabel.Create(WizardForm);
  PageLabel.Parent := CustomPage.Surface;
  PageLabel.Top := FleetModeRadio.Top + FleetModeRadio.Height + 20;
  PageLabel.Caption := 'Enterprise License Key:';

  LicenseEdit := TNewEdit.Create(WizardForm);
  LicenseEdit.Parent := CustomPage.Surface;
  LicenseEdit.Top := PageLabel.Top + PageLabel.Height + 5;
  LicenseEdit.Width := CustomPage.SurfaceWidth;
  LicenseEdit.OnChange := @LicenseEditChange;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = CustomPage.ID then
  begin
    WizardForm.NextButton.Enabled := Trim(LicenseEdit.Text) <> '';
  end;
end;

function GetLicenseKey: string;
begin
  if WizardSilent() then
    Result := ExpandConstant('{param:LICENSEKEY|}')
  else
    Result := Trim(LicenseEdit.Text);
end;

function GetDeployMode: string;
begin
  if WizardSilent() then
    Result := ExpandConstant('{param:DEPLOYMODE|SINGLE}')
  else begin
    if FleetModeRadio.Checked then
      Result := 'FLEET'
    else
      Result := 'SINGLE';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
  var
    ResultCode: Integer;
    LicenseKey, DeployMode, SeedPath, TempKeyFile, BootLog: string;
    WarmupPage: TOutputProgressWizardPage;
    LockFile: string;
    ElapsedSecs, MaxWaitSecs, QuoteIdx: Integer;
    Quotes: array[0..5] of string;
  begin
    if CurStep = ssPostInstall then
    begin
      Quotes[0] := 'Asking Windows Defender for permission to exist...';
      Quotes[1] := 'Uploading telemetry profile for advanced cloud analysis...';
      Quotes[2] := 'Still waiting. Defender is really inspecting those 1s and 0s...';
      Quotes[3] := 'Any minute now... We promise this only happens once.';
      Quotes[4] := 'Defender is making sure we aren''t a crypto miner...';
      Quotes[5] := 'Almost there! The cloud is thinking very hard...';
      
      LockFile := ExpandConstant('{app}\warmup.lock');
      DeleteFile(LockFile);
      
      // Warm up the executable asynchronously
      Exec('cmd.exe', '/C ""' + ExpandConstant('{app}\obylon.exe') + '" --warmup"', '', SW_HIDE, ewNoWait, ResultCode);
      
      // Wait for 3 seconds to see if it finishes instantly
      Sleep(3000);
      
      if not FileExists(LockFile) then
      begin
        WarmupPage := CreateOutputProgressPage('Analyzing Security Payload', 'Windows Defender "Block at First Sight" is performing a one-time cloud analysis.');
        WarmupPage.Show;
        
        MaxWaitSecs := 300;
        ElapsedSecs := 3;
        
        while not FileExists(LockFile) do
        begin
          if ElapsedSecs >= MaxWaitSecs then break;
          
          WarmupPage.SetProgress(ElapsedSecs, MaxWaitSecs);
          QuoteIdx := (ElapsedSecs div 10) mod 6;
          WarmupPage.SetText(Quotes[QuoteIdx], 'Elapsed Time: ' + IntToStr(ElapsedSecs) + 's / Estimated Max Timeout: 300s');
          
          Sleep(1000);
          ElapsedSecs := ElapsedSecs + 1;
        end;
        
        WarmupPage.SetProgress(MaxWaitSecs, MaxWaitSecs);
        WarmupPage.SetText('Analysis Complete!', 'The executable has been successfully verified and cached.');
        Sleep(1000);
        
        WarmupPage.Hide;
        WarmupPage.Free;
      end;

      BootLog := ExpandConstant('{commonappdata}\Obylon\logs\boot_task.log');
    if not Exec('cmd.exe', '/C ""' + ExpandConstant('{app}\obylonc.exe') + '" boot enable > "' + BootLog + '" 2>&1"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Failed to execute Obylon boot-task setup.');
    if ResultCode <> 0 then
      RaiseException('Obylon boot-task setup failed. See ' + BootLog + ' for details.');

    LicenseKey := GetLicenseKey();
    DeployMode := GetDeployMode();
    
    if DeployMode = 'FLEET' then
    begin
      SeedPath := ExpandConstant('{commonappdata}\Obylon\license_seed.txt');
      SaveStringToFile(SeedPath, LicenseKey, False);
      if not WizardSilent() then
        MsgBox('Fleet seed planted. The agent will auto-provision when launched on each endpoint.', mbInformation, MB_OK);
    end
    else
    begin
      TempKeyFile := ExpandConstant('{commonappdata}\Obylon\.activate_key');
      SaveStringToFile(TempKeyFile, LicenseKey, False);
      if Exec('cmd.exe', '/C ""' + ExpandConstant('{app}\obylonc.exe') + '" activate --key-file "' + TempKeyFile + '" > "' + ExpandConstant('{commonappdata}\Obylon\logs\activate_cmd.log') + '" 2>&1"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      begin
        if ResultCode <> 0 then
        begin
          if not WizardSilent() then
            MsgBox('Failed to activate Obylon Sentinel Agent. Exit code: ' + IntToStr(ResultCode), mbError, MB_OK);
        end
        else begin
          if not WizardSilent() then
            MsgBox('Successfully activated Obylon Sentinel Agent.', mbInformation, MB_OK);
        end;
      end
      else begin
        if not WizardSilent() then
          MsgBox('Failed to execute activation command.', mbError, MB_OK);
      end;
      DeleteFile(TempKeyFile);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  OrigPath, AppDir: string;
  P: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDir := ExpandConstant('{app}');
    if RegQueryStringValue(HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path', OrigPath) then
    begin
      P := Pos(';' + AppDir, OrigPath);
      if P > 0 then
      begin
        Delete(OrigPath, P, Length(';' + AppDir));
        RegWriteExpandStringValue(HKEY_LOCAL_MACHINE,
          'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
          'Path', OrigPath);
      end
      else begin
        P := Pos(AppDir + ';', OrigPath);
        if P > 0 then
        begin
          Delete(OrigPath, P, Length(AppDir + ';'));
          RegWriteExpandStringValue(HKEY_LOCAL_MACHINE,
            'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
            'Path', OrigPath);
        end;
      end;
    end;
  end;
end;








