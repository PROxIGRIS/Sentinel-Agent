# Test-Provision.ps1
$ErrorActionPreference = "Stop"

$ExePath = ".\dist\Obylon.exe"
$VaultPath = "C:\ProgramData\Obylon\obylon.enc"
$LogPath = "C:\ProgramData\Obylon\logs\nexus_sentinel.log"

$TestUrl = "https://test-ozruik.supabase.co"
$TestKey = "test_sb_publishable_dummy_key_12345"

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " OBYLON PROVISIONING DIAGNOSTIC TEST" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# 1. Check if the binary exists
if (-not (Test-Path $ExePath)) {
    Write-Host "[FATAL] Obylon.exe not found in .\dist\. Did PyInstaller finish?" -ForegroundColor Red
    exit
}

Write-Host "[*] Executing payload in background: $ExePath --provision ..." -ForegroundColor Yellow
# 2. Execute the stealth binary
& $ExePath --provision $TestUrl $TestKey

# 3. Wait for the background process to generate the vault and logs
Write-Host "[*] Waiting 2 seconds for DPAPI cryptographic lock..." -ForegroundColor DarkGray
Start-Sleep -Seconds 2

# 4. Verify the Vault
if (Test-Path $VaultPath) {
    Write-Host "[+] SUCCESS: Encrypted DPAPI Vault created at $VaultPath" -ForegroundColor Green
} else {
    Write-Host "[-] FAILED: Vault was not created." -ForegroundColor Red
}

# 5. Read the telemetry
if (Test-Path $LogPath) {
    Write-Host "[+] SUCCESS: Reading latest telemetry from SIEM log:" -ForegroundColor Green
    Write-Host "---------------------------------------------------" -ForegroundColor DarkGray
    Get-Content $LogPath -Tail 3 | ForEach-Object {
        Write-Host $_ -ForegroundColor White
    }
    Write-Host "---------------------------------------------------" -ForegroundColor DarkGray
} else {
    Write-Host "[-] FAILED: Log file does not exist. The agent crashed silently." -ForegroundColor Red
}

Write-Host "Diagnostic complete." -ForegroundColor Cyan