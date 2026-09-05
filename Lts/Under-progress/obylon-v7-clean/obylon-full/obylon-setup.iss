; =============================================================================
; OBYLON SENTINEL
; Umbraxis
; Production installer • 5-stage branded setup
; =============================================================================

#define AppVersion "7.0.0"
#define AppName "Obylon Sentinel"
#define Publisher "Umbraxis"

[Setup]
AppId={{F9A8B7C6-D5E4-F3A2-B1C0-123456789ABC}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
AppComments=School-managed endpoint protection and telemetry
AppCopyright=Copyright (c) 2026 Umbraxis

DefaultDirName={commonpf64}\Obylon
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
ChangesEnvironment=yes

LicenseFile=C:\Sentinel-Agent\Lts\v6.3.5\License.rtf
SetupIconFile=C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\icon.ico

WizardStyle=modern
WizardResizable=no
DisableWelcomePage=yes

OutputDir=C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist
OutputBaseFilename=obylon-setup-final
UninstallDisplayIcon={app}\obylonc.exe

Compression=lzma2/fast
SolidCompression=yes
LZMAUseSeparateProcess=yes

[Dirs]
Name: "{commonappdata}\Obylon"; Permissions: system-full admins-full
Name: "{commonappdata}\Obylon\logs"; Permissions: system-full admins-full

[Files]
; ---------------------------------------------------------------------------
; Python onedir runtime: installed once, used directly on every boot.
; ---------------------------------------------------------------------------
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist\obylon\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ---------------------------------------------------------------------------
; Native components.
; ---------------------------------------------------------------------------
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\dist\obylonc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\rust\target\release\ObylonBroker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\rust\target\release\ObylonCore.exe"; DestDir: "{app}"; Flags: ignoreversion

; OCR runtime.
Source: "C:\Obylon v7\Agent\LTS update\tesseract_engine\*"; DestDir: "{app}\tesseract_engine"; Flags: ignoreversion recursesubdirs createallsubdirs

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /tn ""ObylonAgent"" /f"; Flags: runhidden; RunOnceId: "RemoveObylonTask"

[UninstallDelete]
Type: filesandordirs; Name: "{commonappdata}\Obylon"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]

const
  // Palette: restrained Obylon / editorial green.
  C_INK        = $002A2926;
  C_MUTED      = $0075726B;
  C_ACCENT     = $004B765F;
  C_ACCENT_DK  = $003C604D;
  C_PAPER      = $00F5F2EB;
  C_PANEL      = $00FBF9F5;
  C_LINE       = $00D9D4CA;
  C_WHITE      = $00FFFFFF;
  C_WARNING    = $00927B3A;
  C_ERROR      = $00A54A4A;

var
  ConfigPage: TWizardPage;
  WarmupPage: TPanel;

  LicenseEdit: TNewEdit;
  SingleModeRadio: TNewRadioButton;
  FleetModeRadio: TNewRadioButton;

  BrandTitle: TLabel;
  BrandSubtitle: TLabel;
  StageLabel: TLabel;
  StageBar: array[0..4] of TPanel;
  StageText: array[0..4] of TLabel;

  StatusTitle: TLabel;
  StatusDetail: TLabel;
  StatusPercent: TLabel;
  StatusPanel: TPanel;

  CompletionTitle: TLabel;
  CompletionDetail: TLabel;
  RestartButton: TButton;
  LaterButton: TButton;

  WarmupSucceeded: Boolean;
  LicenseActivationSucceeded: Boolean;

function NeedsAddPath(Param: string): Boolean;
var
  ExistingPath: string;
begin
  if not RegQueryStringValue(
    HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path',
    ExistingPath
  ) then
  begin
    Result := True;
    Exit;
  end;

  Result := Pos(';' + Param + ';', ';' + ExistingPath + ';') = 0;
end;

procedure StyleLabel(L: TLabel; FontSize: Integer; Bold: Boolean; Color: Integer);
begin
  L.Font.Name := 'Segoe UI';
  L.Font.Size := FontSize;
  L.Font.Color := Color;
  L.Font.Style := [];
  if Bold then
    L.Font.Style := [fsBold];
end;

procedure AddBrandHeader(Parent: TWinControl);
var
  Rule: TPanel;
begin
  BrandTitle := TLabel.Create(WizardForm);
  BrandTitle.Parent := Parent;
  BrandTitle.Left := ScaleX(28);
  BrandTitle.Top := ScaleY(22);
  BrandTitle.Caption := '◈  OBYLON';
  StyleLabel(BrandTitle, 14, True, C_INK);

  BrandSubtitle := TLabel.Create(WizardForm);
  BrandSubtitle.Parent := Parent;
  BrandSubtitle.Left := ScaleX(29);
  BrandSubtitle.Top := ScaleY(48);
  BrandSubtitle.Caption := 'SENTINEL  /  UMBRAXIS';
  StyleLabel(BrandSubtitle, 8, True, C_ACCENT);

  Rule := TPanel.Create(WizardForm);
  Rule.Parent := Parent;
  Rule.Left := ScaleX(28);
  Rule.Top := ScaleY(68);
  Rule.Width := Parent.Width - ScaleX(56);
  Rule.Height := ScaleY(1);
  Rule.BevelOuter := bvNone;
  Rule.Color := C_LINE;
end;

procedure BuildStageRail(Parent: TWinControl);
var
  i, x: Integer;
begin
  StageLabel := TLabel.Create(WizardForm);
  StageLabel.Parent := Parent;
  StageLabel.Left := ScaleX(28);
  StageLabel.Top := ScaleY(83);
  StageLabel.Caption := 'SETUP';
  StyleLabel(StageLabel, 8, True, C_MUTED);

  x := ScaleX(28);
  for i := 0 to 4 do
  begin
    StageBar[i] := TPanel.Create(WizardForm);
    StageBar[i].Parent := Parent;
    StageBar[i].Left := x;
    StageBar[i].Top := ScaleY(50);
    StageBar[i].Width := ScaleX(104);
    StageBar[i].Height := ScaleY(4);
    StageBar[i].BevelOuter := bvNone;
    StageBar[i].Color := C_LINE;
    

    StageText[i] := TLabel.Create(WizardForm);
    StageText[i].Parent := Parent;
    StageText[i].Left := x;
    StageText[i].Top := ScaleY(58);
    case i of
      0: StageText[i].Caption := 'WELCOME';
      1: StageText[i].Caption := 'CONFIGURE';
      2: StageText[i].Caption := 'INSTALL';
      3: StageText[i].Caption := 'ACTIVATE';
      4: StageText[i].Caption := 'READY';
    end;
    StyleLabel(StageText[i], 7, True, C_MUTED);

    x := x + ScaleX(112);
  end;
end;

procedure SetStage(Index: Integer);
var
  i: Integer;
begin
  if Index < 0 then Index := 0;
  if Index > 4 then Index := 4;

  for i := 0 to 4 do
  begin
    if i <= Index then
    begin
      StageBar[i].Color := C_ACCENT;
      StageText[i].Font.Color := C_ACCENT;
    end
    else
    begin
      StageBar[i].BevelOuter := bvNone;
    StageBar[i].Color := C_LINE;
      StageText[i].Font.Color := C_MUTED;
    end;
  end;
end;

procedure ConfigureMainPalette;
begin
  WizardForm.Color := C_PAPER;
  WizardForm.Font.Name := 'Segoe UI';
  WizardForm.Font.Size := 9;

  WizardForm.NextButton.Font.Name := 'Segoe UI';
  WizardForm.NextButton.Font.Style := [fsBold];

  WizardForm.CancelButton.Font.Name := 'Segoe UI';

  WizardForm.ProgressGauge.Height := ScaleY(5);

  WizardForm.Caption := 'Obylon Sentinel';
end;

procedure LicenseEditChange(Sender: TObject);
begin
  WizardForm.NextButton.Enabled := Trim(LicenseEdit.Text) <> '';
end;

procedure BuildConfigPage;
var
  Section: TPanel;
  Heading: TLabel;
  Description: TLabel;
  LabelLicense: TLabel;
begin
  ConfigPage := CreateCustomPage(
    wpWelcome,
    'Configure',
    'Set the deployment mode and license before installation.'
  );

  ConfigPage.Surface.Color := C_PAPER;
  AddBrandHeader(ConfigPage.Surface);
  BuildStageRail(ConfigPage.Surface);
  SetStage(1);

  Heading := TLabel.Create(WizardForm);
  Heading.Parent := ConfigPage.Surface;
  Heading.Left := ScaleX(28);
  Heading.Top := ScaleY(85);
  Heading.Caption := 'Deploy Sentinel';
  StyleLabel(Heading, 22, True, C_INK);

  Description := TLabel.Create(WizardForm);
  Description.Parent := ConfigPage.Surface;
  Description.Left := ScaleX(29);
  Description.Top := ScaleY(115);
  Description.Width := ScaleX(485);
  Description.Caption :=
    'Configure this installation before Obylon is placed on the workstation.';
  StyleLabel(Description, 9, False, C_MUTED);

  Section := TPanel.Create(WizardForm);
  Section.Parent := ConfigPage.Surface;
  Section.Left := ScaleX(28);
  Section.Top := ScaleY(145);
  Section.Width := ScaleX(520);
  Section.Height := ScaleY(170);
  Section.BevelOuter := bvNone;
  Section.Color := C_PANEL;

  SingleModeRadio := TNewRadioButton.Create(WizardForm);
  SingleModeRadio.Parent := Section;
  SingleModeRadio.Left := ScaleX(20);
  SingleModeRadio.Top := ScaleY(5);
  SingleModeRadio.Width := ScaleX(470);
  SingleModeRadio.Caption := 'Single workstation';
  SingleModeRadio.Checked := True;
  SingleModeRadio.Font.Name := 'Segoe UI';
  SingleModeRadio.Font.Size := 10;
  SingleModeRadio.Font.Style := [fsBold];
  SingleModeRadio.Font.Color := C_INK;

  LabelLicense := TLabel.Create(WizardForm);
  LabelLicense.Parent := Section;
  LabelLicense.Left := ScaleX(40);
  LabelLicense.Top := ScaleY(25);
  LabelLicense.Caption :=
    'Activate this machine immediately after installation.';
  StyleLabel(LabelLicense, 8, False, C_MUTED);

  FleetModeRadio := TNewRadioButton.Create(WizardForm);
  FleetModeRadio.Parent := Section;
  FleetModeRadio.Left := ScaleX(20);
  FleetModeRadio.Top := ScaleY(55);
  FleetModeRadio.Width := ScaleX(470);
  FleetModeRadio.Caption := 'Master image / fleet deployment';
  FleetModeRadio.Checked := False;
  FleetModeRadio.Font.Name := 'Segoe UI';
  FleetModeRadio.Font.Size := 10;
  FleetModeRadio.Font.Style := [fsBold];
  FleetModeRadio.Font.Color := C_INK;

  LabelLicense := TLabel.Create(WizardForm);
  LabelLicense.Parent := Section;
  LabelLicense.Left := ScaleX(40);
  LabelLicense.Top := ScaleY(75);
  LabelLicense.Caption :=
    'Seed the installation for later endpoint provisioning.';
  StyleLabel(LabelLicense, 8, False, C_MUTED);

  LabelLicense := TLabel.Create(WizardForm);
  LabelLicense.Parent := Section;
  LabelLicense.Left := ScaleX(20);
  LabelLicense.Top := ScaleY(105);
  LabelLicense.Caption := 'Enterprise license key';
  StyleLabel(LabelLicense, 8, True, C_INK);

  LicenseEdit := TNewEdit.Create(WizardForm);
  LicenseEdit.Parent := Section;
  LicenseEdit.Left := ScaleX(20);
  LicenseEdit.Top := ScaleY(125);
  LicenseEdit.Width := ScaleX(470);
  LicenseEdit.Height := ScaleY(28);
  LicenseEdit.Font.Name := 'Consolas';
  LicenseEdit.Font.Size := 9;
  LicenseEdit.OnChange := @LicenseEditChange;

  WizardForm.NextButton.Enabled := False;
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
  else if FleetModeRadio.Checked then
    Result := 'FLEET'
  else
    Result := 'SINGLE';
end;

function RunHiddenCommand(
  Filename: string;
  Parameters: string;
  var ResultCode: Integer
): Boolean;
begin
  Result := Exec(
    Filename,
    Parameters,
    '',
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  );
end;

procedure PrepareWarmupPage;
var
  Heading: TLabel;
begin
  if Assigned(WarmupPage) then
    Exit;

  WarmupPage := TPanel.Create(WizardForm);
  WarmupPage.Parent := WizardForm.InnerNotebook;
  WarmupPage.Align := alClient;
  WarmupPage.BevelOuter := bvNone;
  WarmupPage.Color := C_PAPER;

  Heading := TLabel.Create(WizardForm);
  Heading.Parent := WarmupPage;
  Heading.Left := ScaleX(28);
  Heading.Top := ScaleY(25);
  Heading.Caption := 'Preparing the installation';
  StyleLabel(Heading, 18, True, C_INK);

  StatusTitle := TLabel.Create(WizardForm);
  StatusTitle.Parent := WarmupPage;
  StatusTitle.Left := ScaleX(29);
  StatusTitle.Top := ScaleY(73);
  StatusTitle.Caption := 'Preparing runtime…';
  StyleLabel(StatusTitle, 10, True, C_INK);

  StatusDetail := TLabel.Create(WizardForm);
  StatusDetail.Parent := WarmupPage;
  StatusDetail.Left := ScaleX(29);
  StatusDetail.Top := ScaleY(99);
  StatusDetail.Width := ScaleX(480);
  StatusDetail.Caption := 'Initializing first-start components.';
  StyleLabel(StatusDetail, 8, False, C_MUTED);

  StatusPanel := TPanel.Create(WizardForm);
  StatusPanel.Parent := WarmupPage;
  StatusPanel.Left := ScaleX(28);
  StatusPanel.Top := ScaleY(142);
  StatusPanel.Width := ScaleX(520);
  StatusPanel.Height := ScaleY(70);
  StatusPanel.BevelOuter := bvNone;
  StatusPanel.Color := C_PANEL;

  StatusPercent := TLabel.Create(WizardForm);
  StatusPercent.Parent := StatusPanel;
  StatusPercent.Left := ScaleX(20);
  StatusPercent.Top := ScaleY(18);
  StatusPercent.Caption := 'Running…';
  StyleLabel(StatusPercent, 10, True, C_ACCENT);
end;

function WarmupPythonRuntime: Boolean;
var
  WarmupExe: string;
  LockFile: string;
  ResultCode: Integer;
  Elapsed: Integer;
  MaxWait: Integer;
begin
  Result := False;

  PrepareWarmupPage;
  WarmupPage.Show;
  WizardForm.CancelButton.Enabled := False;
  SetStage(2);

  WarmupExe := ExpandConstant('{app}\obylon.exe');
  LockFile := ExpandConstant('{app}\warmup.lock');

  DeleteFile(LockFile);

  if not FileExists(WarmupExe) then
  begin
    StatusTitle.Caption := 'Runtime missing';
    StatusDetail.Caption := 'The installed Python runtime could not be found.';
    StatusPercent.Caption := 'FAILED';
    StatusPercent.Font.Color := C_ERROR;
    WarmupPage.Hide;
    WizardForm.CancelButton.Enabled := True;
    Exit;
  end;

  StatusDetail.Caption :=
    'Preparing installed runtime for fast startup. This is a one-time setup step.';
  StatusPercent.Caption := 'Starting…';
  StatusPercent.Refresh;

  if not Exec(
    WarmupExe,
    '--warmup',
    ExpandConstant('{app}'),
    SW_HIDE,
    ewNoWait,
    ResultCode
  ) then
  begin
    StatusTitle.Caption := 'Preparation could not start';
    StatusDetail.Caption := 'The runtime warmup process failed to launch.';
    StatusPercent.Caption := 'FAILED';
    StatusPercent.Font.Color := C_ERROR;
    WarmupPage.Hide;
    WizardForm.CancelButton.Enabled := True;
    Exit;
  end;

  MaxWait := 300;
  Elapsed := 0;

  while not FileExists(LockFile) do
  begin
    if Elapsed >= MaxWait then
      Break;

    Sleep(500);
    Elapsed := Elapsed + 1;

    StatusPercent.Caption :=
      Format('Preparing… %d / %d s', [Elapsed, MaxWait]);

    
      StatusPercent.Refresh;
  end;

  if FileExists(LockFile) then
  begin
    StatusTitle.Caption := 'Runtime prepared';
    StatusDetail.Caption :=
      'First-start preparation completed successfully.';
    StatusPercent.Caption := 'READY';
    StatusPercent.Font.Color := C_ACCENT;
    WarmupSucceeded := True;
    Result := True;
  end
  else
  begin
    StatusTitle.Caption := 'Preparation timed out';
    StatusDetail.Caption :=
      'Installation will continue, but additional first-start work may occur after reboot.';
    StatusPercent.Caption := 'DEGRADED';
    StatusPercent.Font.Color := C_WARNING;
    WarmupSucceeded := False;
  end;

  Sleep(650);
  WarmupPage.Hide;
  WizardForm.CancelButton.Enabled := True;
end;

procedure ConfigureBootTask;
var
  ResultCode: Integer;
  BootLog: string;
begin
  BootLog := ExpandConstant('{commonappdata}\Obylon\logs\boot_task.log');

  if not RunHiddenCommand(
    ExpandConstant('{app}\obylonc.exe'),
    'boot enable > "' + BootLog + '" 2>&1',
    ResultCode
  ) then
    RaiseException('Could not execute Obylon boot-task setup.');

  if ResultCode <> 0 then
    RaiseException(
      'Obylon boot-task setup failed.'#13#13 +
      'See:'#13#10 + BootLog
    );
end;

procedure ActivateSingleWorkstation(const LicenseKey: string);
var
  ResultCode: Integer;
  TempKeyFile: string;
  ActivateLog: string;
begin
  TempKeyFile := ExpandConstant('{commonappdata}\Obylon\.activate_key');
  ActivateLog := ExpandConstant('{commonappdata}\Obylon\logs\activate_cmd.log');

  DeleteFile(TempKeyFile);
  SaveStringToFile(TempKeyFile, LicenseKey, False);

  SetStage(3);

  try
    if not RunHiddenCommand(
      ExpandConstant('{app}\obylonc.exe'),
      'activate --key-file "' + TempKeyFile + '" > "' +
      ActivateLog + '" 2>&1',
      ResultCode
    ) then
    begin
      LicenseActivationSucceeded := False;
      if not WizardSilent() then
        MsgBox(
          'License activation could not start.'#13#13 +
          'The diagnostic log is:'#13 + ActivateLog,
          mbError,
          MB_OK
        );
      Exit;
    end;

    if ResultCode <> 0 then
    begin
      LicenseActivationSucceeded := False;
      if not WizardSilent() then
        MsgBox(
          'License activation failed.'#13#13 +
          'Exit code: ' + IntToStr(ResultCode) + #13#10 +
          'The diagnostic log is:'#13 + ActivateLog,
          mbError,
          MB_OK
        );
      Exit;
    end;

    LicenseActivationSucceeded := True;
  finally
    DeleteFile(TempKeyFile);
  end;
end;

procedure SeedFleetLicense(const LicenseKey: string);
var
  SeedPath: string;
begin
  SeedPath := ExpandConstant('{commonappdata}\Obylon\license_seed.txt');
  DeleteFile(SeedPath);
  SaveStringToFile(SeedPath, LicenseKey, False);
  LicenseActivationSucceeded := True;
end;

procedure CustomizeFinishedPage;
var
  L: TLabel;
begin
  SetStage(4);

  WizardForm.Caption := 'Obylon Sentinel — Ready';

  CompletionTitle := TLabel.Create(WizardForm);
  CompletionTitle.Parent := WizardForm;
  CompletionTitle.Left := ScaleX(30);
  CompletionTitle.Top := ScaleY(115);
  CompletionTitle.Caption := 'Installation complete';
  StyleLabel(CompletionTitle, 20, True, C_INK);

  CompletionDetail := TLabel.Create(WizardForm);
  CompletionDetail.Parent := WizardForm;
  CompletionDetail.Left := ScaleX(31);
  CompletionDetail.Top := ScaleY(151);
  CompletionDetail.Width := ScaleX(470);

  if LicenseActivationSucceeded then
    CompletionDetail.Caption :=
      'Obylon is installed, the boot integration is configured, and the deployment is authorized.'#13#10#13#10 +
      'Restart Windows once to complete the first normal boot.'
  else
    CompletionDetail.Caption :=
      'Obylon is installed and the boot integration is configured.'#13#10#13#10 +
      'License activation did not complete. Use obylonc status/diagnose after installation.';
  StyleLabel(CompletionDetail, 9, False, C_MUTED);

  L := TLabel.Create(WizardForm);
  L.Parent := WizardForm;
  L.Left := ScaleX(31);
  L.Top := ScaleY(225);
  L.Caption := 'SYSTEM';
  StyleLabel(L, 7, True, C_MUTED);

  L := TLabel.Create(WizardForm);
  L.Parent := WizardForm;
  L.Left := ScaleX(31);
  L.Top := ScaleY(246);
  L.Caption := '✓ Runtime installed    ✓ Boot integration    ✓ Native core';
  StyleLabel(L, 9, False, C_ACCENT);

  if WarmupSucceeded then
  begin
    L := TLabel.Create(WizardForm);
    L.Parent := WizardForm;
    L.Left := ScaleX(31);
    L.Top := ScaleY(274);
    L.Caption := '✓ First-start runtime preparation';
    StyleLabel(L, 9, False, C_ACCENT);
  end;

  WizardForm.FinishedLabel.Visible := False;
  WizardForm.FinishedHeadingLabel.Visible := False;
end;

procedure OfferRestartAtFinish(Sender: TObject);
var
  ResultCode: Integer;
begin
  WizardForm.Close;

  if not WizardSilent() then
  begin
    if MsgBox(
      'Obylon is ready.'#13#10#13#10 +
      'Restart Windows now to complete the first boot?',
      mbInformation,
      MB_YESNO
    ) = IDYES then
      Exec(
        ExpandConstant('{sys}\shutdown.exe'),
        '/r /t 0',
        '',
        SW_HIDE,
        ewNoWait,
        ResultCode
      );
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    CustomizeFinishedPage;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  LicenseKey: string;
  DeployMode: string;
begin
  if CurStep <> ssPostInstall then
    Exit;

  // Stage 2 → 3: warm up the installed runtime.
  WarmupPythonRuntime;

  // Stage 3: configure persistent boot integration.
  ConfigureBootTask;

  LicenseKey := GetLicenseKey;
  DeployMode := GetDeployMode;

  // Stage 4: authorize this installation or seed the license.
  if DeployMode = 'FLEET' then
    SeedFleetLicense(LicenseKey)
  else
    ActivateSingleWorkstation(LicenseKey);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if CurPageID = ConfigPage.ID then
  begin
    if Trim(LicenseEdit.Text) = '' then
    begin
      MsgBox(
        'Enter the deployment license key before continuing.',
        mbError,
        MB_OK
      );
      Result := False;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExistingPath: string;
  AppDir: string;
  P: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;

  AppDir := ExpandConstant('{app}');

  if not RegQueryStringValue(
    HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path',
    ExistingPath
  ) then
    Exit;

  P := Pos(';' + AppDir, ExistingPath);
  if P > 0 then
  begin
    Delete(ExistingPath, P, Length(';' + AppDir));
    RegWriteExpandStringValue(
      HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path',
      ExistingPath
    );
    Exit;
  end;

  P := Pos(AppDir + ';', ExistingPath);
  if P > 0 then
  begin
    Delete(ExistingPath, P, Length(AppDir + ';'));
    RegWriteExpandStringValue(
      HKEY_LOCAL_MACHINE,
      'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
      'Path',
      ExistingPath
    );
  end;
end;

procedure InitializeWizard;
begin
  ConfigureMainPalette;
  BuildConfigPage;
end;
