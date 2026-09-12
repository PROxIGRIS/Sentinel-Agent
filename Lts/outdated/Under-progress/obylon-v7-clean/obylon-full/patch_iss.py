import re

with open("obylon-setup.iss", "r", encoding="utf-8") as f:
    iss = f.read()

# 1. Modify InitializeWizard to call PrepareWarmupPage
iss = iss.replace(
    "procedure InitializeWizard;\nbegin\n  ConfigureMainPalette;\n  BuildConfigPage;\nend;",
    "procedure InitializeWizard;\nbegin\n  ConfigureMainPalette;\n  BuildConfigPage;\n  PrepareWarmupPage;\nend;"
)

# 2. Modify WarmupPythonRuntime to remove .Show, .Hide, and WizardForm.CancelButton edits
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

# Remove the WarmupPage.Hide
iss = iss.replace("    WarmupPage.Hide;\n    WizardForm.CancelButton.Enabled := True;\n    Exit;", "    WizardForm.CancelButton.Enabled := True;\n    Exit;")
iss = iss.replace("  Sleep(650);\n  WarmupPage.Hide;\n  WizardForm.CancelButton.Enabled := True;", "  Sleep(650);\n  WizardForm.CancelButton.Enabled := True;\n  WizardForm.NextButton.Enabled := True;")

# 3. Rewrite CurStepChanged / CurPageChanged
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
    
    // Continue with boot-task and activation right after warmup
    ConfigureBootTask;
    
    LicenseKey := GetLicenseKey;
    DeployMode := GetDeployMode;
    
    if DeployMode = 'FLEET' then
      SeedFleetLicense(LicenseKey)
    else
      ActivateSingleWorkstation(LicenseKey);
      
    // Auto advance to the finished page
    WizardForm.NextButton.OnClick(WizardForm);
  end
  else if CurPageID = wpFinished then
  begin
    CustomizeFinishedPage;
  end;
end;"""

iss = iss.replace(curpage_old, curpage_new)

with open("obylon-setup.iss", "w", encoding="utf-8") as f:
    f.write(iss)
print("ISS patched successfully")
