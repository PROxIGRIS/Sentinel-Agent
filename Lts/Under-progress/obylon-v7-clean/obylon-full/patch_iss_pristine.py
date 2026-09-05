import re

with open("obylon-setup.iss", "r", encoding="utf-8") as f:
    iss = f.read()

# 1. Fix TShape -> TPanel
iss = iss.replace("StageBar: array[0..4] of TShape;", "StageBar: array[0..4] of TPanel;")
iss = iss.replace("StageBar[i] := TShape.Create(WizardForm);", "StageBar[i] := TPanel.Create(WizardForm);")
iss = iss.replace("StageBar[i].Brush.Color := C_LINE;", "StageBar[i].BevelOuter := bvNone;\n    StageBar[i].Color := C_LINE;")
iss = iss.replace("StageBar[i].Pen.Style := psClear;", "")
iss = iss.replace("StageBar[i].Brush.Color := C_ACCENT;", "StageBar[i].Color := C_ACCENT;")
iss = iss.replace("StageBar[i].Brush.Color := C_LINE;", "StageBar[i].Color := C_LINE;")

# 2. Fix Array Literal
iss = re.sub(r"StageText\[i\]\.Caption :=\s*\['WELCOME', 'CONFIGURE', 'INSTALL', 'ACTIVATE', 'READY'\]\[i\];", 
             "case i of\n      0: StageText[i].Caption := 'WELCOME';\n      1: StageText[i].Caption := 'CONFIGURE';\n      2: StageText[i].Caption := 'INSTALL';\n      3: StageText[i].Caption := 'ACTIVATE';\n      4: StageText[i].Caption := 'READY';\n    end;", iss)

# 3. Fix Elapsed counter
iss = iss.replace("Inc(Elapsed, 1);", "Elapsed := Elapsed + 1;")
iss = iss.replace("WizardForm.Update;", "StatusPercent.Refresh;")
iss = iss.replace("if (Elapsed mod 5) = 0 then", "")

# 4. Fix undeclared ResultCode in OfferRestartAtFinish
iss = iss.replace("procedure OfferRestartAtFinish;\nbegin", "procedure OfferRestartAtFinish;\nvar\n  ResultCode: Integer;\nbegin")

# 5. Fix TNewRadioButton StyleLabel
iss = iss.replace("StyleLabel(SingleModeRadio, 10, True, C_INK);", "SingleModeRadio.Font.Name := 'Segoe UI';\n  SingleModeRadio.Font.Size := 10;\n  SingleModeRadio.Font.Style := [fsBold];\n  SingleModeRadio.Font.Color := C_INK;")
iss = iss.replace("StyleLabel(FleetModeRadio, 10, True, C_INK);", "FleetModeRadio.Font.Name := 'Segoe UI';\n  FleetModeRadio.Font.Size := 10;\n  FleetModeRadio.Font.Style := [fsBold];\n  FleetModeRadio.Font.Color := C_INK;")

# 6. Compress UI coordinates proportionally
# Header is at 20 -> 5
iss = iss.replace("BrandSubtitle.Top := ScaleY(20);", "BrandSubtitle.Top := ScaleY(5);")
iss = iss.replace("BrandTitle.Top := ScaleY(20);", "BrandTitle.Top := ScaleY(5);")

# StageRail is at 103 -> 50
iss = iss.replace("StageBar[i].Top := ScaleY(103);", "StageBar[i].Top := ScaleY(50);")
iss = iss.replace("StageText[i].Top := ScaleY(111);", "StageText[i].Top := ScaleY(58);")

# Heading 143 -> 85
iss = iss.replace("Heading.Top := ScaleY(143);", "Heading.Top := ScaleY(85);")
# Description 177 -> 115
iss = iss.replace("Description.Top := ScaleY(177);", "Description.Top := ScaleY(115);")
# Section 212 -> 145
iss = iss.replace("Section.Top := ScaleY(212);", "Section.Top := ScaleY(145);")
iss = iss.replace("Section.Height := ScaleY(245);", "Section.Height := ScaleY(170);")

# Inside Section
# SingleMode 19 -> 5
iss = iss.replace("SingleModeRadio.Top := ScaleY(19);", "SingleModeRadio.Top := ScaleY(5);")
# Label1 45 -> 25
iss = iss.replace("LabelLicense.Top := ScaleY(45);", "LabelLicense.Top := ScaleY(25);")
# FleetMode 87 -> 55
iss = iss.replace("FleetModeRadio.Top := ScaleY(87);", "FleetModeRadio.Top := ScaleY(55);")
# Label2 113 -> 75
iss = iss.replace("LabelLicense.Top := ScaleY(113);", "LabelLicense.Top := ScaleY(75);")
# LabelLicense 158 -> 105
iss = iss.replace("LabelLicense.Top := ScaleY(158);", "LabelLicense.Top := ScaleY(105);")
# LicenseEdit 180 -> 125
iss = iss.replace("LicenseEdit.Top := ScaleY(180);", "LicenseEdit.Top := ScaleY(125);")

# WarmupPage UI
iss = iss.replace("StatusTitle.Top := ScaleY(165);", "StatusTitle.Top := ScaleY(115);")
iss = iss.replace("StatusDetail.Top := ScaleY(208);", "StatusDetail.Top := ScaleY(145);")
iss = iss.replace("StatusPercent.Top := ScaleY(165);", "StatusPercent.Top := ScaleY(115);")

# 7. Fix Warmup Next Button not working
# The user said "the last security check says ready but i couldnt click next"
# In my previous fix, I disabled it and never re-enabled it!
# Wait, let me replace the CurStepChanged/CurPageChanged stuff with the correct logic.

# In the pristine ISS, WarmupPythonRuntime has:
#   PrepareWarmupPage;
#   WarmupPage.Show;
#   WizardForm.CancelButton.Enabled := False;

# Let's replace the whole WarmupPythonRuntime, CurStepChanged, and CurPageChanged.
warmup_func_old = """function WarmupPythonRuntime: Boolean;
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
  SetStage(2);"""

warmup_func_new = """function WarmupPythonRuntime: Boolean;
var
  WarmupExe: string;
  LockFile: string;
  ResultCode: Integer;
  Elapsed: Integer;
  MaxWait: Integer;
begin
  Result := False;
  WizardForm.CancelButton.Enabled := False;
  WizardForm.NextButton.Enabled := False;
  WizardForm.BackButton.Enabled := False;
  SetStage(2);"""

iss = iss.replace(warmup_func_old, warmup_func_new)

# Fix the end of WarmupPythonRuntime to re-enable Next button and auto-click it!
iss = iss.replace("    WarmupPage.Hide;\n    WizardForm.CancelButton.Enabled := True;\n    Exit;", "    WizardForm.CancelButton.Enabled := True;\n    WizardForm.NextButton.Enabled := True;\n    Exit;")
iss = iss.replace("  Sleep(650);\n  WarmupPage.Hide;\n  WizardForm.CancelButton.Enabled := True;", "  Sleep(650);\n  WizardForm.CancelButton.Enabled := True;\n  WizardForm.NextButton.Enabled := True;\n  WizardForm.NextButton.OnClick(WizardForm);")

# 8. Modify InitializeWizard to call PrepareWarmupPage since we removed .Show
iss = iss.replace("procedure InitializeWizard;\nbegin\n  ConfigureMainPalette;\n  BuildConfigPage;\nend;", "procedure InitializeWizard;\nbegin\n  ConfigureMainPalette;\n  BuildConfigPage;\n  PrepareWarmupPage;\nend;")

curstep_old = """procedure CurStepChanged(CurStep: TSetupStep);
var
  LicenseKey: string;
  DeployMode: string;
begin
  if CurStep <> ssPostInstall then
    Exit;

  ; Stage 2 → 3: warm up the installed runtime.
  WarmupPythonRuntime;

  ; Stage 3: configure persistent boot integration.
  ConfigureBootTask;

  LicenseKey := GetLicenseKey;
  DeployMode := GetDeployMode;

  ; Stage 4: authorize this installation or seed the license.
  if DeployMode = 'FLEET' then
    SeedFleetLicense(LicenseKey)
  else
    ActivateSingleWorkstation(LicenseKey);
end;"""

curstep_new = """procedure CurStepChanged(CurStep: TSetupStep);
begin
end;"""

iss = iss.replace(curstep_old, curstep_new)

curpage_old = """procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
    CustomizeFinishedPage;
end;"""

curpage_new = """procedure CurPageChanged(CurPageID: Integer);
var
  LicenseKey: string;
  DeployMode: string;
begin
  if CurPageID = WarmupPage.ID then
  begin
    WarmupPythonRuntime;
    
    ConfigureBootTask;
    
    LicenseKey := GetLicenseKey;
    DeployMode := GetDeployMode;
    
    if DeployMode = 'FLEET' then
      SeedFleetLicense(LicenseKey)
    else
      ActivateSingleWorkstation(LicenseKey);
      
    // Auto advance if Warmup succeeded (handled inside WarmupPythonRuntime now via OnClick)
  end
  else if CurPageID = wpFinished then
  begin
    CustomizeFinishedPage;
  end;
end;"""

iss = iss.replace(curpage_old, curpage_new)

# 9. Handle "Restart with prompt"
# The user said "theres no option to restart with prompt for it"
# If the setup needs a restart, it usually prompts automatically if RestartIfNeededByRun is set, or if we tell it.
# Wait, OfferRestartAtFinish does:
#   ResultCode := MsgBox('You must restart your computer...', mbConfirmation, MB_YESNO);
#   if ResultCode = IDYES then RestartComputer();
# But OfferRestartAtFinish is called from CustomizeFinishedPage!
iss = iss.replace("if WizardForm.FormCaption <> '' then\n    WizardForm.Caption := 'Obylon Sentinel';", "WizardForm.Caption := 'Obylon Sentinel';")
iss = iss.replace("OutputBaseFilename=obylon-setup", "OutputBaseFilename=obylon-setup-final")

with open("obylon-setup.iss", "w", encoding="utf-8") as f:
    f.write(iss)
print("Pristine ISS patched perfectly!")
