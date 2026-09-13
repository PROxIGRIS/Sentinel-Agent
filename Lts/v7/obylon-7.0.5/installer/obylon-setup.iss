; =============================================================================
; OBYLON SENTINEL
; Umbraxis
; Production installer - compact, aligned, DPI-aware, resizable.
; =============================================================================

#define AppVersion "7.0.6"
#define AppName "Obylon Sentinel"
#define Publisher "Umbraxis"

[Setup]
ArchitecturesAllowed=x64compatible
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
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes

; Paths are relative to this .iss file so the installer is portable across
; build machines instead of depending on one developer's C:\Sentinel-Agent path.
LicenseFile=..\docs\License.rtf
SetupIconFile=..\assets\icon.ico

WizardStyle=modern
WizardResizable=yes
WizardSizePercent=110
DisableWelcomePage=no

OutputDir=dist
OutputBaseFilename=obylon-setup-7.0.6
UninstallDisplayIcon={app}\obylonc.exe

Compression=lzma2/fast
SolidCompression=yes
LZMAUseSeparateProcess=yes

[Dirs]
Name: "{commonappdata}\Obylon"; Permissions: system-full admins-full
Name: "{commonappdata}\Obylon\logs"; Permissions: system-full admins-full

[Files]
; ---------------------------------------------------------------------------
; Python onedir runtime. The spec places obylon_ad_networks.json beside the
; executable, so the local ad-network reputation DB is installed with it.
; ---------------------------------------------------------------------------
Source: "..\dist\obylon\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Native components.
Source: "..\dist\obylonc.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\rust\target\release\ObylonBroker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\rust\target\release\ObylonCore.exe"; DestDir: "{app}"; Flags: ignoreversion

; OCR runtime.
Source: "..\tesseract_engine\*"; DestDir: "{app}\tesseract_engine"; Flags: ignoreversion recursesubdirs createallsubdirs

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

var
  DownloadPage: TDownloadWizardPage;

function VCInstalled(Is64Bit: Boolean): Boolean;
var
  Key: String;
  Bld: Cardinal;
begin
  if Is64Bit then
  begin
    // Check 64-bit registry view first (which is the default in 64-bit install mode)
    Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
    if RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld) then
    begin
      Result := True;
      Exit;
    end;
    // Fallback to check WOW6432Node just in case
    Key := 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
    Result := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);
  end
  else
  begin
    // 32-bit runtime is generally under WOW6432Node on 64-bit systems
    Key := 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x86';
    if RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld) then
    begin
      Result := True;
      Exit;
    end;
    // Fallback to native (if it ever changes)
    Key := 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86';
    Result := RegQueryDWordValue(HKEY_LOCAL_MACHINE, Key, 'Bld', Bld);
  end;
end;

function VCFilesPresent(Is64Bit: Boolean): Boolean;
begin
  if Is64Bit then
    Result := FileExists(ExpandConstant('{sys}\VCRUNTIME140.dll')) and
              FileExists(ExpandConstant('{sys}\VCRUNTIME140_1.dll')) and
              FileExists(ExpandConstant('{sys}\MSVCP140.dll'))
  else
    Result := FileExists(ExpandConstant('{syswow64}\VCRUNTIME140.dll')) and
              FileExists(ExpandConstant('{syswow64}\VCRUNTIME140_1.dll')) and
              FileExists(ExpandConstant('{syswow64}\MSVCP140.dll'));
end;

function VCReady(Is64Bit: Boolean): Boolean;
begin
  // Registry presence alone is not enough. A broken/partial redistributable
  // can leave the registry entry behind while the loader DLL is absent.
  Result := VCInstalled(Is64Bit) and VCFilesPresent(Is64Bit);
end;

function HostToolExists(const ToolName: string): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\where.exe'), ToolName, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function ValidateInstalledPayload: Boolean;
var
  Missing: string;
begin
  Missing := '';
  if not FileExists(ExpandConstant('{app}\ObylonBroker.exe')) then
    Missing := Missing + 'ObylonBroker.exe' + #13#10;
  if not FileExists(ExpandConstant('{app}\ObylonCore.exe')) then
    Missing := Missing + 'ObylonCore.exe' + #13#10;
  if not FileExists(ExpandConstant('{app}\obylon.exe')) then
    Missing := Missing + 'obylon.exe' + #13#10;
  if not FileExists(ExpandConstant('{app}\tesseract_engine\tesseract.exe')) then
    Missing := Missing + 'tesseract_engine\tesseract.exe' + #13#10;
  if not DirExists(ExpandConstant('{commonappdata}\Obylon\logs')) then
    Missing := Missing + '{commonappdata}\Obylon\logs' + #13#10;

  if Missing <> '' then
  begin
    MsgBox('Installation preflight failed. The installed payload is incomplete.'#13#10#13#10 +
           'Missing:'#13#10 + Missing + #13#10 +
           'Setup will stop before activation or boot-task registration.', mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;

  Result := True;
end;

function RunHiddenCommand(const Filename, Parameters: string; var ResultCode: Integer): Boolean;
begin
  Result := Exec(ExpandConstant('{sys}\cmd.exe'), '/c "' + Filename + ' ' + Parameters + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

const
  C_INK        = $002A2926;
  C_MUTED      = $0075726B;
  C_ACCENT     = $004B765F;
  C_PAPER      = $00F5F2EB;
  C_PANEL      = $00FBF9F5;
  C_LINE       = $00D9D4CA;
  C_WARNING    = $00927B3A;
  C_ERROR      = $00A54A4A;

var
  ConfigPage: TWizardPage;
  LicensePage: TInputQueryWizardPage;
  WarmupPage: TPanel;
  BrandTitle: TLabel;
  BrandSubtitle: TLabel;
  StageText: array[0..4] of TLabel;
  StageBar: array[0..4] of TPanel;
  StatusTitle: TLabel;
  StatusDetail: TLabel;
  StatusPercent: TLabel;
  StatusPanel: TPanel;
  CompletionTitle: TLabel;
  CompletionDetail: TLabel;
  WarmupSucceeded: Boolean;

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
  if Bold then L.Font.Style := [fsBold];
end;

procedure AddBrandHeader(Parent: TWinControl);
var
  Rule: TPanel;
begin
  BrandTitle := TLabel.Create(WizardForm);
  BrandTitle.Parent := Parent;
  BrandTitle.Left := ScaleX(28);
  BrandTitle.Top := ScaleY(16);
  BrandTitle.Caption := 'OBYLON';
  StyleLabel(BrandTitle, 14, True, C_INK);

  BrandSubtitle := TLabel.Create(WizardForm);
  BrandSubtitle.Parent := Parent;
  BrandSubtitle.Left := ScaleX(29);
  BrandSubtitle.Top := ScaleY(40);
  BrandSubtitle.Caption := 'SENTINEL  /  UMBRAXIS';
  StyleLabel(BrandSubtitle, 8, True, C_ACCENT);

  Rule := TPanel.Create(WizardForm);
  Rule.Parent := Parent;
  Rule.Left := ScaleX(28);
  Rule.Top := ScaleY(63);
  Rule.Width := Parent.Width - ScaleX(56);
  Rule.Height := ScaleY(1);
  Rule.BevelOuter := bvNone;
  Rule.Color := C_LINE;
end;

procedure BuildStageRail(Parent: TWinControl);
var
  i, x, RailWidth, SegmentWidth, Gap: Integer;
begin
  x := ScaleX(28);
  RailWidth := Parent.Width - ScaleX(56);
  Gap := ScaleX(8);
  SegmentWidth := (RailWidth - (Gap * 4)) div 5;

  for i := 0 to 4 do
  begin
    StageBar[i] := TPanel.Create(WizardForm);
    StageBar[i].Parent := Parent;
    StageBar[i].Left := x;
    StageBar[i].Top := ScaleY(78);
    StageBar[i].Width := SegmentWidth;
    StageBar[i].Height := ScaleY(4);
    StageBar[i].BevelOuter := bvNone;
    StageBar[i].Color := C_LINE;

    StageText[i] := TLabel.Create(WizardForm);
    StageText[i].Parent := Parent;
    StageText[i].Left := x;
    StageText[i].Top := ScaleY(88);
    case i of
      0: StageText[i].Caption := 'WELCOME';
      1: StageText[i].Caption := 'CONFIGURE';
      2: StageText[i].Caption := 'INSTALL';
      3: StageText[i].Caption := 'ACTIVATE';
      4: StageText[i].Caption := 'READY';
    end;
    StyleLabel(StageText[i], 7, True, C_MUTED);
    x := x + SegmentWidth + Gap;
  end;
end;

procedure SetStage(Index: Integer);
begin
end;

procedure ConfigureMainPalette;
begin
  // WizardForm.Color := clWindow;
  WizardForm.Font.Name := 'Segoe UI';
  // WizardForm.Font.Size := 9;
  WizardForm.NextButton.Font.Name := 'Segoe UI';
  WizardForm.NextButton.Font.Style := [fsBold];
  WizardForm.CancelButton.Font.Name := 'Segoe UI';
  WizardForm.ProgressGauge.Height := ScaleY(5);
  WizardForm.Caption := 'Obylon Sentinel';
end;

procedure BuildConfigPage;
var
  Section: TPanel;
  Heading: TLabel;
  Description: TLabel;
  Detail: TLabel;
begin
  ConfigPage := CreateCustomPage(
    wpWelcome,
    'Configure',
    'Review the installation plan before files are deployed.'
  );
  ConfigPage.Surface.Color := C_PAPER;

  AddBrandHeader(ConfigPage.Surface);
  BuildStageRail(ConfigPage.Surface);
  SetStage(1);

  Heading := TLabel.Create(WizardForm);
  Heading.Parent := ConfigPage.Surface;
  Heading.Left := ScaleX(28);
  Heading.Top := ScaleY(95);
  Heading.Caption := 'Deploy Sentinel';
  StyleLabel(Heading, 20, True, C_INK);

  Description := TLabel.Create(WizardForm);
  Description.Parent := ConfigPage.Surface;
  Description.Left := ScaleX(29);
  Description.Top := ScaleY(120);
  Description.Width := ConfigPage.Surface.Width - ScaleX(58);
  Description.WordWrap := True;
  Description.Caption := 'Install the runtime, native enforcement components, and boot integration.';
  StyleLabel(Description, 9, False, C_MUTED);

  Section := TPanel.Create(WizardForm);
  Section.Parent := ConfigPage.Surface;
  Section.Left := ScaleX(28);
  Section.Top := ScaleY(150);
  Section.Width := ConfigPage.Surface.Width - ScaleX(56);
  Section.Height := ScaleY(100);
  Section.BevelOuter := bvNone;
  Section.Color := C_PANEL;

  Detail := TLabel.Create(WizardForm);
  Detail.Parent := Section;
  Detail.Left := ScaleX(20);
  Detail.Top := ScaleY(20);
  Detail.Width := Section.Width - ScaleX(40);
  Detail.WordWrap := True;
  Detail.Caption :=
    'The installer will activate the supplied license before setup completes.'#13#10#13#10 +
    'The workstation name is collected during configuration and sent with the enrollment request.'#13#10#13#10 +
    'No separate post-install activation step is required when setup completes successfully.';
  StyleLabel(Detail, 9, False, C_INK);
end;


procedure BuildLicensePage;
var
  NodeName: string;
begin
  LicensePage := CreateInputQueryPage(
    wpWelcome,
      'License Configuration',
    'Provision this workstation',
    'Enter the Obylon license key that should be bound to this endpoint.'
  );
  LicensePage.Add('License key:', True);
  LicensePage.Add('Node name:', False);
  NodeName := Trim(GetEnv('COMPUTERNAME'));
  if NodeName = '' then
    NodeName := 'OBYLON-ENDPOINT';
  LicensePage.Values[1] := NodeName;
end;

function ActivateFromInstaller: Boolean;
var
  KeyFile: string;
  Params: string;
  NodeName: string;
  ResultCode: Integer;
begin
  Result := False;
  if not Assigned(LicensePage) then Exit;

  WarmupPage.Show;
  NodeName := Trim(LicensePage.Values[1]);
  if NodeName = '' then
    NodeName := 'OBYLON-ENDPOINT';

  KeyFile := ExpandConstant('{tmp}\obylon-installer-license.key');
  DeleteFile(KeyFile);
  if not SaveStringToFile(KeyFile, AnsiString(Trim(LicensePage.Values[0])), False) then
  begin
    StatusTitle.Caption := 'License staging failed';
    StatusDetail.Caption := 'The installer could not create its temporary license-key handoff.';
    StatusPercent.Caption := 'FAILED';
    StatusPercent.Font.Color := C_ERROR;
    Exit;
  end;

  StatusTitle.Caption := 'Activating license...';
  StatusDetail.Caption := 'Registering this workstation and binding the license to its hardware identity.';
  StatusPercent.Caption := 'ACTIVATING';
  StatusPercent.Font.Color := C_ACCENT;
  StatusTitle.Refresh;
  StatusDetail.Refresh;
  StatusPercent.Refresh;
  SetStage(3);

  Params := 'activate --key-file "' + KeyFile + '" --node-name "' + NodeName + '"';
  if not Exec(ExpandConstant('{app}\obylonc.exe'), Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    DeleteFile(KeyFile);
    StatusTitle.Caption := 'License activation could not start';
    StatusDetail.Caption := 'The installed CLI could not be launched. Setup will stop rather than report a partially provisioned workstation.';
    StatusPercent.Caption := 'FAILED';
    StatusPercent.Font.Color := C_ERROR;
    Exit;
  end;
  DeleteFile(KeyFile);

  if ResultCode <> 0 then
  begin
    StatusTitle.Caption := 'License activation failed';
    StatusDetail.Caption := 'The enrollment service rejected or could not complete the license transaction. Review the activation log and retry setup.';
    StatusPercent.Caption := Format('FAILED (code %d)', [ResultCode]);
    StatusPercent.Font.Color := C_ERROR;
    Exit;
  end;

  StatusTitle.Caption := 'License activated';
  StatusDetail.Caption := 'The endpoint was enrolled successfully and its node identity was persisted locally.';
  StatusPercent.Caption := 'ACTIVE';
  StatusPercent.Font.Color := C_ACCENT;
  StatusTitle.Refresh;
  StatusDetail.Refresh;
  StatusPercent.Refresh;
  WarmupPage.Hide;
  Result := True;
end;

procedure PrepareWarmupPage;
var
  Heading: TLabel;
begin
  if Assigned(WarmupPage) then Exit;

  WarmupPage := TPanel.Create(WizardForm);
  WarmupPage.Parent := WizardForm.InnerNotebook;
  WarmupPage.Align := alClient;
  WarmupPage.BevelOuter := bvNone;
  WarmupPage.Color := C_PAPER;

  Heading := TLabel.Create(WizardForm);
  Heading.Parent := WarmupPage;
  Heading.Left := ScaleX(28);
  Heading.Top := ScaleY(34);
  Heading.Caption := 'Preparing installation';
  StyleLabel(Heading, 18, True, C_INK);

  StatusTitle := TLabel.Create(WizardForm);
  StatusTitle.Parent := WarmupPage;
  StatusTitle.Left := ScaleX(29);
  StatusTitle.Top := ScaleY(83);
  StatusTitle.Caption := 'Preparing runtime...';
  StyleLabel(StatusTitle, 10, True, C_INK);

  StatusDetail := TLabel.Create(WizardForm);
  StatusDetail.Parent := WarmupPage;
  StatusDetail.Left := ScaleX(29);
  StatusDetail.Top := ScaleY(109);
  StatusDetail.Width := WarmupPage.Width - ScaleX(58);
    StatusDetail.AutoSize := False;
    StatusDetail.Height := ScaleY(60);
  StatusDetail.WordWrap := True;
  StatusDetail.Caption := 'Initializing first-start components.';
  StyleLabel(StatusDetail, 8, False, C_MUTED);

  StatusPanel := TPanel.Create(WizardForm);
  StatusPanel.Parent := WarmupPage;
  StatusPanel.Left := ScaleX(28);
  StatusPanel.Top := ScaleY(151);
  StatusPanel.Width := WarmupPage.Width - ScaleX(56);
  StatusPanel.Height := ScaleY(70);
  StatusPanel.BevelOuter := bvNone;
  StatusPanel.Color := C_PANEL;

  StatusPercent := TLabel.Create(WizardForm);
  StatusPercent.Parent := StatusPanel;
  StatusPercent.Left := ScaleX(20);
  StatusPercent.Top := ScaleY(20);
  StatusPercent.Caption := 'Starting...';
  StyleLabel(StatusPercent, 10, True, C_ACCENT);
end;

function WarmupPythonRuntime: Boolean;
var
  WarmupExe: string;
  LockFile: string;
  ResultCode: Integer;
  ElapsedMs: Integer;
  MaxWaitMs: Integer;
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

  if not Exec(WarmupExe, '--warmup', ExpandConstant('{app}'), SW_HIDE, ewNoWait, ResultCode) then
  begin
    StatusTitle.Caption := 'Preparation could not start';
    StatusDetail.Caption := 'The runtime warmup process failed to launch.';
    StatusPercent.Caption := 'FAILED';
    StatusPercent.Font.Color := C_ERROR;
    WarmupPage.Hide;
    WizardForm.CancelButton.Enabled := True;
    Exit;
  end;

  MaxWaitMs := 300000;
  ElapsedMs := 0;
  while not FileExists(LockFile) do
  begin
    if ElapsedMs >= MaxWaitMs then Break;
    Sleep(500);
    ElapsedMs := ElapsedMs + 500;
    StatusPercent.Caption := Format('Preparing... %d / %d s', [ElapsedMs div 1000, MaxWaitMs div 1000]);
    StatusPercent.Refresh;
  end;

  if FileExists(LockFile) then
  begin
    StatusTitle.Caption := 'Runtime prepared';
    StatusDetail.Caption := 'First-start preparation completed successfully.';
    StatusPercent.Caption := 'READY';
    StatusPercent.Font.Color := C_ACCENT;
    WarmupSucceeded := True;
    Result := True;
  end
  else
  begin
    StatusTitle.Caption := 'Preparation timed out';
    StatusDetail.Caption := 'Installation will continue; the first boot may perform additional initialization.';
    StatusPercent.Caption := 'DEGRADED';
    StatusPercent.Font.Color := C_WARNING;
    WarmupSucceeded := False;
    Result := True;
  end;

  Sleep(400);
  WarmupPage.Hide;
  WizardForm.CancelButton.Enabled := True;
end;

procedure ConfigureBootTask;
var
  ResultCode: Integer;
  BootLog: string;
  BrokerPath: string;
begin
  // The installer is already elevated. Do not invoke the CLI here: boot
  // management is an authenticated admin command and the installer has no
  // Umbraxis user credential yet. Register the same SYSTEM boot task directly.
  BrokerPath := ExpandConstant('{app}\ObylonBroker.exe');
  BootLog := ExpandConstant('{commonappdata}\Obylon\logs\boot_task.log');
  if not RunHiddenCommand(
    ExpandConstant('{sys}\schtasks.exe'),
    '/create /tn "ObylonAgent" /tr "\"' + BrokerPath + '\"" /sc onstart /ru SYSTEM /rl HIGHEST /f > "' + BootLog + '" 2>&1',
    ResultCode
  ) then
    RaiseException('Could not execute Windows Task Scheduler setup.');
    
  // Apply robust restart, concurrency, and battery-power settings via PowerShell
  Log('Applying advanced task settings (RestartOnFailure, Battery overrides)...');
  if not RunHiddenCommand(
    'powershell.exe',
    '-NoProfile -WindowStyle Hidden -Command "$s = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -ExecutionTimeLimit 0 -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Set-ScheduledTask -TaskName ''ObylonAgent'' -Settings $s"',
    ResultCode
  ) then
    Log('Warning: Could not configure RestartOnFailure settings via PowerShell.');
  if ResultCode <> 0 then
    RaiseException('Obylon boot-task setup failed.'#13#13 + 'See:'#13#10 + BootLog);

  Log('Starting ObylonAgent task immediately...');
  if not RunHiddenCommand(
    ExpandConstant('{sys}\schtasks.exe'),
    '/run /tn "ObylonAgent"',
    ResultCode
  ) then
    Log('Warning: Could not start ObylonAgent task immediately.');
end;

procedure CustomizeFinishedPage;
var
  L: TLabel;
begin
  SetStage(4);
  WizardForm.Caption := 'Obylon Sentinel - Ready';

  CompletionTitle := TLabel.Create(WizardForm);
  CompletionTitle.Parent := WizardForm;
  CompletionTitle.Left := WizardForm.InnerNotebook.Left + ScaleX(28);
  CompletionTitle.Top := WizardForm.InnerNotebook.Top + ScaleY(34);
  CompletionTitle.Caption := 'Installation complete';
  StyleLabel(CompletionTitle, 20, True, C_INK);

  CompletionDetail := TLabel.Create(WizardForm);
  CompletionDetail.Parent := WizardForm;
  CompletionDetail.Left := WizardForm.InnerNotebook.Left + ScaleX(29);
  CompletionDetail.Top := WizardForm.InnerNotebook.Top + ScaleY(75);
  CompletionDetail.Width := WizardForm.InnerNotebook.Width - ScaleX(58);
    CompletionDetail.AutoSize := False;
    CompletionDetail.Height := ScaleY(60);
  CompletionDetail.WordWrap := True;
  CompletionDetail.Caption := 'Obylon is installed, licensed, node-registered, and boot integration is configured.'#13#10#13#10 + 'The endpoint is ready for its first managed session.';
  StyleLabel(CompletionDetail, 9, False, C_MUTED);

  L := TLabel.Create(WizardForm);
  L.Parent := WizardForm;
  L.Left := WizardForm.InnerNotebook.Left + ScaleX(29);
  L.Top := WizardForm.InnerNotebook.Top + ScaleY(142);
  L.Caption := 'SYSTEM';
  StyleLabel(L, 7, True, C_MUTED);

  L := TLabel.Create(WizardForm);
  L.Parent := WizardForm;
  L.Left := WizardForm.InnerNotebook.Left + ScaleX(29);
  L.Top := WizardForm.InnerNotebook.Top + ScaleY(163);
  L.Caption := 'Runtime installed    Boot integration    Native core';
  StyleLabel(L, 9, False, C_ACCENT);

  if WarmupSucceeded then
  begin
    L := TLabel.Create(WizardForm);
    L.Parent := WizardForm;
    L.Left := WizardForm.InnerNotebook.Left + ScaleX(29);
    L.Top := WizardForm.InnerNotebook.Top + ScaleY(191);
    L.Caption := 'First-start runtime preparation complete';
    StyleLabel(L, 9, False, C_ACCENT);
  end;

  WizardForm.FinishedLabel.Visible := False;
  WizardForm.FinishedHeadingLabel.Visible := False;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then CustomizeFinishedPage;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then Exit;
  // Never register the scheduled task or activate the endpoint until the full
  // installed payload has been verified. This prevents a half-installed agent
  // from silently becoming a broken boot task.
  if not ValidateInstalledPayload then
    RaiseException('Obylon dependency/payload preflight failed. Setup cannot continue safely.');
  if not WarmupPythonRuntime then
    RaiseException('Obylon runtime preparation failed. Setup cannot continue safely.');
  if not ActivateFromInstaller then
    RaiseException('Obylon license activation failed. Setup stopped before reporting the endpoint as ready.');
  ConfigureBootTask;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  NeedsVC64, NeedsVC32: Boolean;
  ResultCode: Integer;
begin
  Result := True;
  
  if CurPageID = wpWelcome then
  begin
    NeedsVC64 := not VCReady(True);
    NeedsVC32 := not VCReady(False);

    if not HostToolExists('schtasks.exe') then
    begin
      MsgBox('Windows Task Scheduler tooling (schtasks.exe) is missing. Obylon cannot register its protected boot service on this Windows installation.', mbCriticalError, MB_OK);
      Result := False;
      Exit;
    end;

    if not HostToolExists('powershell.exe') then
    begin
      MsgBox('Windows PowerShell is missing. Obylon requires it for hardened Task Scheduler recovery settings.', mbCriticalError, MB_OK);
      Result := False;
      Exit;
    end;
    
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
        if not Exec(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          MsgBox('Failed to install the 64-bit Visual C++ runtime.', mbError, MB_OK);
          Result := False;
          Exit;
        end;
      end;
      
      if NeedsVC32 then
      begin
        if not Exec(ExpandConstant('{tmp}\vc_redist.x86.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
        begin
          MsgBox('Failed to install the 32-bit Visual C++ runtime.', mbError, MB_OK);
          Result := False;
          Exit;
        end;
      end;
      
      if (NeedsVC64 and not VCReady(True)) or (NeedsVC32 and not VCReady(False)) then
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
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExistingPath: string;
  AppDir: string;
  P: Integer;
begin
  if CurUninstallStep <> usPostUninstall then Exit;
  AppDir := ExpandConstant('{app}');
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', ExistingPath) then Exit;
  P := Pos(';' + AppDir, ExistingPath);
  if P > 0 then
  begin
    Delete(ExistingPath, P, Length(';' + AppDir));
    RegWriteExpandStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', ExistingPath);
    Exit;
  end;
  P := Pos(AppDir + ';', ExistingPath);
  if P > 0 then
  begin
    Delete(ExistingPath, P, Length(AppDir + ';'));
    RegWriteExpandStringValue(HKEY_LOCAL_MACHINE, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', 'Path', ExistingPath);
  end;
end;

procedure InitializeWizard;
begin
  ConfigureMainPalette;
  // BuildConfigPage;
  BuildLicensePage;
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), nil);
end;

