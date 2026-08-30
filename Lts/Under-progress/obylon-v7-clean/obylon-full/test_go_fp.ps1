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
