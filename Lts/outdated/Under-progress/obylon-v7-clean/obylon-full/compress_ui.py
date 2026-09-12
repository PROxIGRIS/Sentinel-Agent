import re

with open("obylon-setup.iss", "r", encoding="utf-8") as f:
    iss = f.read()

# ConfigPage adjustments
# Old Header is at 20, StageRail at 103, Heading at 143, Desc at 177, Section at 212
# Let's shift everything up!
iss = iss.replace("StageBar[i].Top := ScaleY(103);", "StageBar[i].Top := ScaleY(73);")
iss = iss.replace("StageText[i].Top := ScaleY(111);", "StageText[i].Top := ScaleY(81);")
iss = iss.replace("Heading.Top := ScaleY(143);", "Heading.Top := ScaleY(110);")
iss = iss.replace("Description.Top := ScaleY(177);", "Description.Top := ScaleY(140);")
iss = iss.replace("Section.Top := ScaleY(212);", "Section.Top := ScaleY(170);")

# Inside Section, things are:
# SingleMode=19, Label1=45, FleetMode=87, Label2=113, LabelLicense=158, Edit=180
# If Section starts at 170, the Edit will end up at 170+180 = 350. We need to squash Section too!
iss = iss.replace("SingleModeRadio.Top := ScaleY(19);", "SingleModeRadio.Top := ScaleY(5);")
iss = iss.replace("LabelLicense.Top := ScaleY(45);", "LabelLicense.Top := ScaleY(25);")
iss = iss.replace("FleetModeRadio.Top := ScaleY(87);", "FleetModeRadio.Top := ScaleY(50);")
iss = iss.replace("LabelLicense.Top := ScaleY(113);", "LabelLicense.Top := ScaleY(70);")
iss = iss.replace("LabelLicense.Top := ScaleY(158);", "LabelLicense.Top := ScaleY(105);")
iss = iss.replace("LicenseEdit.Top := ScaleY(180);", "LicenseEdit.Top := ScaleY(125);")
iss = iss.replace("Section.Height := ScaleY(245);", "Section.Height := ScaleY(160);")

# WarmupPage adjustments (if any are out of bounds)
iss = iss.replace("StatusTitle.Top := ScaleY(165);", "StatusTitle.Top := ScaleY(115);")
iss = iss.replace("StatusDetail.Top := ScaleY(208);", "StatusDetail.Top := ScaleY(145);")
iss = iss.replace("StatusPercent.Top := ScaleY(165);", "StatusPercent.Top := ScaleY(115);")

with open("obylon-setup.iss", "w", encoding="utf-8") as f:
    f.write(iss)
print("UI coordinates compressed")
