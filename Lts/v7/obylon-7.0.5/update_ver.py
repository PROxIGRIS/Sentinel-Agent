import os
import glob

base = r"C:\Sentinel-Agent\Lts\v7\obylon-7.0.5"
files = [
    r"metadata.json",
    r"installer\obylon-setup.iss",
    r"release\metadata.json",
    r"obylonc\cmd\root.go",
    r"src\brain\Obylon.py",
    r"tools\release\pack_release.py",
    r"obylonc\internal\authz\client.go",
    r"tools\dev\patch_broker.rs"
]

for f in files:
    path = os.path.join(base, f)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Replace 7.0.5 with 7.0.6
        content = content.replace('7.0.5', '7.0.6')
        
        # Clean up installer UI "without try hard"
        if f.endswith('obylon-setup.iss'):
            # Remove custom coloring for a standard native look
            content = content.replace("WizardForm.Color := C_PAPER;", "// WizardForm.Color := clWindow;")
            content = content.replace("WizardForm.Font.Size := 9;", "// WizardForm.Font.Size := 9;")
            content = content.replace("OutputBaseFilename=obylon-setup-7.0.6-fixed", "OutputBaseFilename=obylon-setup-7.0.6")
            
        with open(path, 'w', encoding='utf-8') as file:
            file.write(content)

print("Versions updated to 7.0.6.")
