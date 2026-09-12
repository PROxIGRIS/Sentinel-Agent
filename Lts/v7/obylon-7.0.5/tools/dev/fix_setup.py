import re

with open("obylon-setup.iss", "r", encoding="utf-8") as f:
    iss = f.read()

# Fix Output Base Filename & Architecture
iss = iss.replace("OutputBaseFilename=obylon-setup", "OutputBaseFilename=obylon-setup-final")
iss = iss.replace("ArchitecturesInstallIn64BitMode=x64compatible", "ArchitecturesInstallIn64BitMode=x64")

# Fix TShape to TPanel
iss = iss.replace("StageBar: array[0..4] of TShape;", "StageBar: array[0..4] of TPanel;")
iss = iss.replace("StageBar[i] := TShape.Create(WizardForm);", "StageBar[i] := TPanel.Create(WizardForm);")
iss = iss.replace("StageBar[i].Brush.Color := C_LINE;", "StageBar[i].BevelOuter := bvNone;\n    StageBar[i].Color := C_LINE;")
iss = iss.replace("StageBar[i].Pen.Style := psClear;", "")
iss = iss.replace("StageBar[i].Brush.Color := C_ACCENT;", "StageBar[i].Color := C_ACCENT;")
iss = iss.replace("StageBar[i].Brush.Color := C_LINE;", "StageBar[i].Color := C_LINE;")

# Fix Array indexing
iss = re.sub(r"StageText\[i\]\.Caption :=\s*\['WELCOME', 'CONFIGURE', 'INSTALL', 'ACTIVATE', 'READY'\]\[i\];", 
             "case i of\n      0: StageText[i].Caption := 'WELCOME';\n      1: StageText[i].Caption := 'CONFIGURE';\n      2: StageText[i].Caption := 'INSTALL';\n      3: StageText[i].Caption := 'ACTIVATE';\n      4: StageText[i].Caption := 'READY';\n    end;", iss)

# Fix ResultCode in OfferRestartAtFinish
iss = iss.replace("procedure OfferRestartAtFinish;\nbegin", "procedure OfferRestartAtFinish(Sender: TObject);\nvar\n  ResultCode: Integer;\nbegin")
# Ensure the restart button triggers it!
iss = iss.replace("RestartButton.OnClick := nil;", "RestartButton.OnClick := @OfferRestartAtFinish;")
# Fix LaterButton to just close
iss = iss.replace("LaterButton.OnClick := nil;", "LaterButton.OnClick := @WizardForm.Close;")

# Make WarmupPage a TPanel overlay over InnerNotebook so .Show and .Hide work during ssPostInstall
iss = iss.replace("WarmupPage: TInputOptionWizardPage;", "WarmupPage: TPanel;")
iss = re.sub(
    r"WarmupPage := CreateInputOptionPage\([^;]+;\s*",
    "WarmupPage := TPanel.Create(WizardForm);\n  WarmupPage.Parent := WizardForm.InnerNotebook;\n  WarmupPage.Align := alClient;\n  WarmupPage.BevelOuter := bvNone;\n  WarmupPage.Color := C_PAPER;\n  ",
    iss, flags=re.MULTILINE
)
iss = iss.replace("WarmupPage.Surface", "WarmupPage")

# Fix Elapsed counter
iss = iss.replace("Inc(Elapsed, 1);", "Elapsed := Elapsed + 1;")
iss = iss.replace("WizardForm.Update;", "StatusPercent.Refresh;")
iss = iss.replace("if (Elapsed mod 5) = 0 then", "")

# Fix TNewRadioButton StyleLabel
iss = iss.replace("StyleLabel(SingleModeRadio, 10, True, C_INK);", "SingleModeRadio.Font.Name := 'Segoe UI';\n  SingleModeRadio.Font.Size := 10;\n  SingleModeRadio.Font.Style := [fsBold];\n  SingleModeRadio.Font.Color := C_INK;")
iss = iss.replace("StyleLabel(FleetModeRadio, 10, True, C_INK);", "FleetModeRadio.Font.Name := 'Segoe UI';\n  FleetModeRadio.Font.Size := 10;\n  FleetModeRadio.Font.Style := [fsBold];\n  FleetModeRadio.Font.Color := C_INK;")

# Fix FormCaption error
iss = iss.replace("if WizardForm.FormCaption <> '' then\n    WizardForm.Caption := 'Obylon Sentinel';", "WizardForm.Caption := 'Obylon Sentinel';")

# Compress UI coordinates!
iss = iss.replace("BrandSubtitle.Top := ScaleY(20);", "BrandSubtitle.Top := ScaleY(5);")
iss = iss.replace("BrandTitle.Top := ScaleY(20);", "BrandTitle.Top := ScaleY(5);")
iss = iss.replace("StageBar[i].Top := ScaleY(103);", "StageBar[i].Top := ScaleY(50);")
iss = iss.replace("StageText[i].Top := ScaleY(111);", "StageText[i].Top := ScaleY(58);")
iss = iss.replace("Heading.Top := ScaleY(143);", "Heading.Top := ScaleY(85);")
iss = iss.replace("Description.Top := ScaleY(177);", "Description.Top := ScaleY(115);")
iss = iss.replace("Section.Top := ScaleY(212);", "Section.Top := ScaleY(145);")
iss = iss.replace("Section.Height := ScaleY(245);", "Section.Height := ScaleY(170);")
iss = iss.replace("SingleModeRadio.Top := ScaleY(19);", "SingleModeRadio.Top := ScaleY(5);")
iss = iss.replace("LabelLicense.Top := ScaleY(45);", "LabelLicense.Top := ScaleY(25);")
iss = iss.replace("FleetModeRadio.Top := ScaleY(87);", "FleetModeRadio.Top := ScaleY(55);")
iss = iss.replace("LabelLicense.Top := ScaleY(113);", "LabelLicense.Top := ScaleY(75);")
iss = iss.replace("LabelLicense.Top := ScaleY(158);", "LabelLicense.Top := ScaleY(105);")
iss = iss.replace("LicenseEdit.Top := ScaleY(180);", "LicenseEdit.Top := ScaleY(125);")

# Compress WarmupPage UI coordinates
iss = iss.replace("StatusTitle.Top := ScaleY(165);", "StatusTitle.Top := ScaleY(115);")
iss = iss.replace("StatusDetail.Top := ScaleY(208);", "StatusDetail.Top := ScaleY(145);")
iss = iss.replace("StatusPercent.Top := ScaleY(165);", "StatusPercent.Top := ScaleY(115);")

with open("obylon-setup.iss", "w", encoding="utf-8") as f:
    f.write(iss)
print("ISS patched with flawless TPanel overlay and UI compress.")
