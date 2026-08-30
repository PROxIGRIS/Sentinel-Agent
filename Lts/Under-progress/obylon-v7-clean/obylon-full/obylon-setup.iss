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
OutputBaseFilename=obylon-setup-final-ssot
;SetupIconFile=C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
UninstallDisplayIcon={app}\obylonc.exe

[Dirs]
Name: "{commonappdata}\Obylon"; Permissions: system-full admins-full

[Files]
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist\obylon.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist\obylonc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\rust\target\release\ObylonBroker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\rust\target\release\ObylonCore.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Obylon v7\Agent\LTS update\tesseract_engine\*"; DestDir: "{app}\tesseract_engine"; Flags: ignoreversion recursesubdirs createallsubdirs

[Run]
Filename: "{app}\obylonc.exe"; Parameters: "boot enable"; Flags: runhidden

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
  LicenseKey, DeployMode, SeedPath, TempKeyFile: string;
begin
  if CurStep = ssPostInstall then
  begin
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

