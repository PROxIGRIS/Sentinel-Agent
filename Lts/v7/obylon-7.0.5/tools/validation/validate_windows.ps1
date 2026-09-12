# Obylon Sentinel 7.0.5-LTS - Windows production validation harness
# Non-destructive by design. Requires PowerShell 5+ and should be run elevated.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$ExpectedVersion = '7.0.5-LTS'
$ExpectedBuild = '7.0.5-202609061200'
$ExpectedBroker = Join-Path ${env:ProgramFiles} 'Obylon\ObylonBroker.exe'
$ExpectedCore   = Join-Path ${env:ProgramFiles} 'Obylon\ObylonCore.exe'
$ExpectedAgent  = Join-Path ${env:ProgramFiles} 'Obylon\obylon.exe'
$ProgramData   = if ($env:PROGRAMDATA) { $env:PROGRAMDATA } else { 'C:\ProgramData' }
$ObylonDir     = Join-Path $ProgramData 'Obylon'
$LogDir        = Join-Path $ObylonDir 'logs'
$ValidationDir = Join-Path $ObylonDir 'validation'
$TaskNameCandidates = @('ObylonAgent', 'Obylon Session Broker')
$TaskName      = $null
foreach ($candidate in $TaskNameCandidates) {
    & schtasks.exe /query /tn $candidate 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $TaskName = $candidate; break }
}
if (-not $TaskName) { $TaskName = $TaskNameCandidates[0] }
$Stamp         = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force -Path $ValidationDir | Out-Null
$ReportPath    = Join-Path $ValidationDir "windows-validation-$Stamp.md"
$RawPath       = Join-Path $ValidationDir "windows-validation-$Stamp.json"

$Results = New-Object System.Collections.Generic.List[object]

function Add-Result {
    param(
        [string]$Id,
        [string]$Category,
        [ValidateSet('PASS','FAIL','WARN','NOT TESTED')][string]$Status,
        [string]$Message,
        [string]$Evidence = ''
    )
    $Results.Add([pscustomobject]@{
        Id=$Id; Category=$Category; Status=$Status; Message=$Message; Evidence=$Evidence
    }) | Out-Null
    $color = switch ($Status) {'PASS' {'Green'} 'FAIL' {'Red'} 'WARN' {'Yellow'} default {'DarkYellow'}}
    Write-Host ("[{0,-10}] {1}: {2}" -f $Status,$Id,$Message) -ForegroundColor $color
}

function Invoke-Capture {
    param([string]$Label,[scriptblock]$Script)
    try {
        $out = & $Script 2>&1 | Out-String
        $code = $LASTEXITCODE
        return [pscustomobject]@{ Output=$out.Trim(); ExitCode=$code }
    } catch {
        return [pscustomobject]@{ Output=$_.Exception.Message; ExitCode=999 }
    }
}

function Redact {
    param([string]$Text)
    if (-not $Text) { return '' }
    $t = $Text
    $patterns = @(
        '(?im)(Authorization\s*[:=]\s*Bearer\s+)[^\s]+',
        '(?im)(access[_-]?token\s*[:=]\s*)[^\s,]+',
        '(?im)(refresh[_-]?token\s*[:=]\s*)[^\s,]+',
        '(?im)(device[_-]?code\s*[:=]\s*)[^\s,]+',
        '(?im)(license[_-]?key\s*[:=]\s*)[^\s,]+',
        '(?im)(api[_-]?key\s*[:=]\s*)[^\s,]+'
    )
    foreach ($p in $patterns) { $t = [regex]::Replace($t,$p,'$1[REDACTED]') }
    return $t
}

Write-Host "`nOBYLON SENTINEL 7.0.5-LTS :: WINDOWS PRODUCTION VALIDATION`n" -ForegroundColor Cyan

# 01 Environment
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($admin) { Add-Result 'ENV-001' 'Environment' 'PASS' 'PowerShell is elevated.' } else { Add-Result 'ENV-001' 'Environment' 'WARN' 'Not elevated. Some checks may be incomplete.' }
Add-Result 'ENV-002' 'Environment' 'PASS' "Windows $([Environment]::OSVersion.VersionString), PowerShell $($PSVersionTable.PSVersion)" \
  "Computer=$env:COMPUTERNAME; User=$env:USERNAME"

# 02 Expected payload files
foreach ($p in @($ExpectedBroker,$ExpectedCore,$ExpectedAgent)) {
    if (Test-Path $p -PathType Leaf) {
        $fi = Get-Item $p
        $ver = $fi.VersionInfo.FileVersion
        $hash = (Get-FileHash $p -Algorithm SHA256).Hash
        Add-Result ('BIN-' + [IO.Path]::GetFileNameWithoutExtension($p)) 'Binaries' 'PASS' "Present: $p" "FileVersion=$ver; Length=$($fi.Length); SHA256=$hash"
    } else {
        Add-Result ('BIN-' + [IO.Path]::GetFileNameWithoutExtension($p)) 'Binaries' 'FAIL' "Missing expected binary: $p"
    }
}

# 03 Installed version through CLI
$cli = Join-Path ${env:ProgramFiles} 'Obylon\obylonc.exe'
if (Test-Path $cli) {
    $r = Invoke-Capture 'version' { & $cli version }
    $txt = Redact $r.Output
    if ($r.ExitCode -eq 0 -and $txt -match [regex]::Escape($ExpectedVersion) -and $txt -match [regex]::Escape($ExpectedBuild)) {
        Add-Result 'CLI-001' 'CLI' 'PASS' 'Installed agent reports expected version/build.' $txt
    } else {
        Add-Result 'CLI-001' 'CLI' 'FAIL' 'Version/build mismatch or version command failed.' "Exit=$($r.ExitCode)`n$txt"
    }
} else { Add-Result 'CLI-001' 'CLI' 'NOT TESTED' 'Agent executable unavailable, so version command could not run.' }

# 04 CLI smoke commands, non-destructive
$cliCommands = @(
    @{Id='CLI-002'; Name='--help'; Args=@('--help')},
    @{Id='CLI-003'; Name='status'; Args=@('status')},
    @{Id='CLI-004'; Name='diagnose'; Args=@('diagnose')},
    @{Id='CLI-005'; Name='doctor'; Args=@('doctor')},
    @{Id='CLI-006'; Name='boot status'; Args=@('boot','status')},
    @{Id='CLI-007'; Name='login status'; Args=@('login','status')}
    # @{Id='CLI-008'; Name='logs'; Args=@('logs','-n','30')}
)
foreach ($c in $cliCommands) {
    if (-not (Test-Path $cli)) { Add-Result $c.Id 'CLI' 'NOT TESTED' "$($c.Name) skipped: binary missing."; continue }
    $r = Invoke-Capture $c.Name { & $cli @($c.Args) }
    $txt = Redact $r.Output
    if ($r.ExitCode -eq 0) {
        Add-Result $c.Id 'CLI' 'PASS' "$($c.Name) exited 0." $txt
    } elseif ($c.Name -eq 'login status' -and $txt -match '(?i)not logged in|session expired') {
        Add-Result $c.Id 'CLI' 'PASS' 'login status returned an expected unauthenticated state.' $txt
    } else {
        Add-Result $c.Id 'CLI' 'FAIL' "$($c.Name) exited $($r.ExitCode)." $txt
    }
}

# 05 Scheduled task definition
try {
    $taskXml = & schtasks.exe /query /tn $TaskName /xml 2>&1 | Out-String
    $taskText = $taskXml.Trim()
    if ($LASTEXITCODE -ne 0) {
        Add-Result 'BOOT-001' 'Boot' 'FAIL' 'Scheduled task query failed.' (Redact $taskText)
    } else {
        [xml]$xml = $taskText
        $ns = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
        $ns.AddNamespace('t','http://schemas.microsoft.com/windows/2004/02/mit/task')
        $boot = $xml.Task.Triggers.BootTrigger
        $principal = $xml.Task.Principals.Principal
        $action = $xml.Task.Actions.Exec.Command
        $runLevel = $principal.RunLevel
        $userId = $principal.UserId
        $enabled = $boot.Enabled
        $actionLeaf = Split-Path $action -Leaf
        $checks = @(
            ($enabled -eq 'true'),
            ($userId -eq 'S-1-5-18'),
            ($runLevel -eq 'HighestAvailable'),
            ($actionLeaf -ieq 'ObylonBroker.exe'),
            ($action -ieq $ExpectedBroker)
        )
        if ($checks -notcontains $false) {
            Add-Result 'BOOT-001' 'Boot' 'PASS' 'Scheduled task definition matches the expected System/Broker boot configuration.' "UserId=$userId; RunLevel=$runLevel; BootEnabled=$enabled; Command=$action"
        } else {
            Add-Result 'BOOT-001' 'Boot' 'FAIL' 'Scheduled task exists but does not match the expected production definition.' "UserId=$userId; RunLevel=$runLevel; BootEnabled=$enabled; Command=$action"
        }
    }
} catch { Add-Result 'BOOT-001' 'Boot' 'FAIL' "Could not validate scheduled task XML: $($_.Exception.Message)" }

# 06 Process state
$names = @('ObylonBroker','ObylonCore','obylon')
$procs = @{}
foreach ($n in $names) {
    $p = Get-Process -Name $n -ErrorAction SilentlyContinue
    if ($p) {
        $procs[$n] = $p
        Add-Result ('PROC-' + $n) 'Runtime' 'PASS' "$n is running." (($p | ForEach-Object { "PID=$($_.Id); WS_MB=$([math]::Round($_.WorkingSet64/1MB,1))" }) -join '; ')
    } else {
        Add-Result ('PROC-' + $n) 'Runtime' 'FAIL' "$n is not running."
    }
}

# 07 Log freshness and error scan
$logs = @('broker.log','core.log','obylon.log')
foreach ($ln in $logs) {
    $path = Join-Path $LogDir $ln
    if (-not (Test-Path $path -PathType Leaf)) {
        Add-Result ('LOG-' + $ln) 'Logs' 'WARN' "Log file missing: $path"
        continue
    }
    $fi = Get-Item $path
    $age = (Get-Date) - $fi.LastWriteTime
    $tail = Get-Content $path -Tail 400 -ErrorAction SilentlyContinue
    $joined = ($tail -join "`n")
    $errors = @($tail | Select-String -Pattern '(?i)\b(error|exception|traceback|panic|fatal)\b')
    if ($errors.Count -eq 0) {
        Add-Result ('LOG-' + $ln) 'Logs' 'PASS' "$ln is readable with no obvious error/fatal/exception markers in the last 400 lines." "LastWrite=$($fi.LastWriteTime.ToString('o')); AgeMinutes=$([math]::Round($age.TotalMinutes,1)); Size=$($fi.Length)"
    } else {
        $sample = ($errors | Select-Object -Last 20 | ForEach-Object { $_.Line }) -join "`n"
        Add-Result ('LOG-' + $ln) 'Logs' 'FAIL' "$ln contains $($errors.Count) error-like line(s) in the last 400 lines." (Redact $sample)
    }
}

# 08 Performance snapshot freshness
foreach ($pair in @(
    @{Name='Python Brain'; File=(Join-Path $LogDir 'perf_snapshot.json')},
    @{Name='Rust Core'; File=(Join-Path $LogDir 'core_perf_snapshot.json')}
)) {
    if (-not (Test-Path $pair.File -PathType Leaf)) {
        Add-Result ('PERF-' + ($pair.Name -replace '\s','')) 'Performance' 'WARN' "$($pair.Name) snapshot missing." $pair.File
        continue
    }
    try {
        $fi = Get-Item $pair.File
        $age = (Get-Date) - $fi.LastWriteTime
        $obj = Get-Content $pair.File -Raw | ConvertFrom-Json
        if ($age.TotalMinutes -le 10) {
            Add-Result ('PERF-' + ($pair.Name -replace '\s','')) 'Performance' 'PASS' "$($pair.Name) performance snapshot is fresh." "LastWrite=$($fi.LastWriteTime.ToString('o')); AgeMinutes=$([math]::Round($age.TotalMinutes,1))"
        } else {
            Add-Result ('PERF-' + ($pair.Name -replace '\s','')) 'Performance' 'WARN' "$($pair.Name) performance snapshot is stale." "LastWrite=$($fi.LastWriteTime.ToString('o')); AgeMinutes=$([math]::Round($age.TotalMinutes,1))"
        }
    } catch { Add-Result ('PERF-' + ($pair.Name -replace '\s','')) 'Performance' 'WARN' "$($pair.Name) snapshot exists but could not be parsed." $_.Exception.Message }
}

# 09 Vault / identity presence, no secret disclosure
$vault = Join-Path $ObylonDir 'obylon.enc'
$idfile = Join-Path $ObylonDir '.machine_id'
if (Test-Path $vault) {
    Add-Result 'SEC-001' 'Security' 'PASS' 'Protected vault file exists; content is not printed.' "Length=$((Get-Item $vault).Length); LastWrite=$((Get-Item $vault).LastWriteTime.ToString('o'))"
} else {
    Add-Result 'SEC-001' 'Security' 'FAIL' 'Protected vault file missing.'
}

$idfile = Join-Path $ObylonDir '.machine_id'
if (Test-Path $idfile) {
    Add-Result 'SEC-002' 'Security' 'PASS' 'Machine identity file exists; content is not printed.' "Length=$((Get-Item $idfile).Length); LastWrite=$((Get-Item $idfile).LastWriteTime.ToString('o'))"
} else { Add-Result 'SEC-002' 'Security' 'FAIL' 'Machine identity file is missing.' }

# 10 Capture directory hygiene
$capture = Join-Path $ObylonDir 'capture'
if (Test-Path $capture) {
    $old = @(Get-ChildItem $capture -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-1) })
    if ($old.Count -eq 0) { Add-Result 'EVID-001' 'Evidence' 'PASS' 'No capture files older than one hour.' }
    else { Add-Result 'EVID-001' 'Evidence' 'WARN' "$($old.Count) capture file(s) are older than one hour. Nothing was deleted." (($old | Select-Object -First 20 | ForEach-Object { $_.Name + ' @ ' + $_.LastWriteTime.ToString('o') }) -join "`n") }
} else { Add-Result 'EVID-001' 'Evidence' 'WARN' 'Capture directory does not exist.' }

# 11 Source/package checks if the validation package was extracted beside this script
$scriptRoot = Split-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) -Parent
$expectedSourceFiles = @('src\brain\Obylon.py','src\brain\scan_pressure.py','src\brain\recovery_engine.py','src\brain\ad_network_reputation.py','assets\data\obylon_ad_networks.json','build\obylon.spec','installer\obylon-setup.iss','obylonc\go.mod')
foreach ($rel in $expectedSourceFiles) {
    $p = Join-Path $scriptRoot $rel
    if (Test-Path $p -PathType Leaf) { Add-Result ('SRC-' + ($rel -replace '[^A-Za-z0-9]','_')) 'Package' 'PASS' "Package contains $rel." }
    else { Add-Result ('SRC-' + ($rel -replace '[^A-Za-z0-9]','_')) 'Package' 'FAIL' "Expected package file missing: $rel" }
}

# 12 Heuristic contradictions in recent logs
$allLogFiles = @('broker.log','core.log','obylon.log') | ForEach-Object { Join-Path $LogDir $_ } | Where-Object { Test-Path $_ }
$recent = foreach ($p in $allLogFiles) { Get-Content $p -Tail 500 -ErrorAction SilentlyContinue }
$contradict = @($recent | Select-String -Pattern '(?i)(connection restored).*(offline|failed)|(?i)(security ready).*(not ready|unverified)|(?i)(heartbeat).*(401|unauthorized)|(?i)(jwt).*(expired|refresh).*(failed)|(?i)(boot).*(failed|error)')
if ($contradict.Count -eq 0) { Add-Result 'LOG-004' 'Logs' 'PASS' 'No obvious contradiction patterns found in recent log tails.' }
else { Add-Result 'LOG-004' 'Logs' 'WARN' "$($contradict.Count) possible contradiction pattern(s) found. Manual review required." (Redact (($contradict | Select-Object -Last 30 | ForEach-Object {$_.Line}) -join "`n")) }

# 13 Report
$fail = @($Results | Where-Object Status -eq 'FAIL').Count
$warn = @($Results | Where-Object Status -eq 'WARN').Count
$nt = @($Results | Where-Object Status -eq 'NOT TESTED').Count
$pass = @($Results | Where-Object Status -eq 'PASS').Count

$verdict = if ($fail -gt 0) { 'NO-SHIP' } elseif ($nt -gt 3 -or $warn -gt 5) { 'SHIP WITH CONDITIONS' } else { 'SHIP' }

$md = @()
$md += "# Obylon Sentinel 7.0.5-LTS — Windows Validation Report"
$md += ""
$md += "Generated: $(Get-Date -Format o)"
$md += "Computer: $env:COMPUTERNAME"
$md += "User: $env:USERNAME"
$md += "Expected version: $ExpectedVersion"
$md += "Expected build: $ExpectedBuild"
$md += ""
$md += "## Verdict"
$md += "**$verdict**"
$md += ""
$md += "PASS=$pass | FAIL=$fail | WARN=$warn | NOT TESTED=$nt"
$md += ""
$md += "## Results"
$md += "| ID | Category | Status | Message | Evidence |"
$md += "|---|---|---|---|---|"
foreach ($x in $Results) {
    $msg = (Redact $x.Message) -replace '\|','\\|'
    $ev = (Redact $x.Evidence) -replace '\|','\\|'
    $ev = $ev -replace "`r?`n", '<br>'
    $md += "| $($x.Id) | $($x.Category) | $($x.Status) | $msg | $ev |"
}
$md += ""
$md += "## Required operator follow-up"
$md += "The following must be explicitly tested on the endpoint and entered into the report: fresh install, reboot, session transition, CLI authentication, license heartbeat, freeze/unfreeze, Classroom Focus, Warden enforcement, offline/reconnect, and installer visual inspection."
$md += ""
$md += "## Release rule"
$md += "Do not call the build production-ready if there is any P0/P1 defect, unexplained boot failure/delay, authentication failure, enforcement bypass, credential exposure, or untested critical lifecycle path."

$md | Set-Content -Path $ReportPath -Encoding UTF8
$Results | ConvertTo-Json -Depth 6 | Set-Content -Path $RawPath -Encoding UTF8

Write-Host "`nReport: $ReportPath" -ForegroundColor Cyan
Write-Host "Raw JSON: $RawPath" -ForegroundColor Cyan
Write-Host "VERDICT: $verdict  | PASS=$pass FAIL=$fail WARN=$warn NOT_TESTED=$nt" -ForegroundColor $(if($verdict -eq 'SHIP'){'Green'}elseif($verdict -eq 'SHIP WITH CONDITIONS'){'Yellow'}else{'Red'})

if ($fail -gt 0) { exit 2 }
if ($nt -gt 0 -or $warn -gt 0) { exit 1 }
exit 0
