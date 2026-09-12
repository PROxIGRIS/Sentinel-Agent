python -m PyInstaller -y obylon.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" obylon-setup.iss
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

git add .
git commit -m "fix(agent): dynamically recover from offline UUID block by resolving UUID when network returns"
git push
