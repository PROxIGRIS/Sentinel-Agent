# Release workflow

From the repository root:

```powershell
python -m pytest tests/python -q
python -m PyInstaller -y build\obylon.spec
& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' installer\obylon-setup.iss
```

For endpoint certification, run `tools/validation/validate_windows.ps1` as Administrator on the built Windows machine and retain the generated report.
