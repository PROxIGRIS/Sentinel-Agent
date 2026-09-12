import re

target_file = r"C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full\obylonc\internal\platform\windows.go"

with open(target_file, "r") as f:
    content = f.read()

old_script = """const fingerprintScript = `
$ErrorActionPreference = 'SilentlyContinue'
function Emit($v) {
  if ([string]::IsNullOrWhiteSpace($v)) { Write-Output "unknown" } else { Write-Output $v.Trim() }
}
try { $u = (Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID } catch { $u = $null }
Emit $u
try { $d = (Get-CimInstance -ClassName Win32_DiskDrive | Select-Object -First 1).SerialNumber } catch { $d = $null }
Emit $d
try {
  $m = (Get-CimInstance -ClassName Win32_NetworkAdapter -Filter "PhysicalAdapter=True" |
        Where-Object { $_.MACAddress } | Select-Object -First 1).MACAddress
} catch { $m = $null }
Emit $m
`"""

new_script = """const fingerprintScript = `
$ErrorActionPreference = 'SilentlyContinue'
function Emit($v) {
  if ([string]::IsNullOrWhiteSpace($v)) { Write-Output "unknown" } else { Write-Output $v.Trim() }
}
try { $u = (Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID } catch { $u = $null }
Emit $u
try { $d = (Get-CimInstance -ClassName Win32_DiskDrive | Where-Object { $_.MediaType -eq 'Fixed hard disk media' } | Sort-Object Index | Select-Object -First 1).SerialNumber } catch { $d = $null }
Emit $d
try {
  $m = (Get-CimInstance -ClassName Win32_NetworkAdapter -Filter "PhysicalAdapter=True" |
        Where-Object { $_.PNPDeviceID -match '^(PCI|SD)' } | 
        Sort-Object { [int]$_.DeviceID } | 
        Select-Object -First 1).MACAddress
} catch { $m = $null }
Emit $m
`"""

if old_script in content:
    content = content.replace(old_script, new_script)
    with open(target_file, "w") as f:
        f.write(content)
    print("Patched successfully")
else:
    print("Old script not found")
