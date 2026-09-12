Add-Type -AssemblyName System.IO.Compression.FileSystem
$sourceDir = "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-full"
$zipFile = "C:\Sentinel-Agent\Lts\Under-progress\obylon-v7-clean\obylon-source.zip"

if (Test-Path $zipFile) { Remove-Item $zipFile }

$excludeExts = @('.dll', '.pyd', '.exe', '.pyc', '.o', '.obj', '.a', '.lib', '.so', '.dylib')
$excludeDirs = @('__pycache__', 'dist', 'build', '.git', '.mypy_cache', 'target', 'node_modules', '.pytest_cache')

$zip = [System.IO.Compression.ZipFile]::Open($zipFile, [System.IO.Compression.ZipArchiveMode]::Create)

Get-ChildItem -Path $sourceDir -Recurse -File | ForEach-Object {
    $file = $_
    $skip = $false
    
    foreach ($dir in $excludeDirs) {
        if ($file.FullName -match "\\$dir\\") {
            $skip = $true
            break
        }
    }
    
    if ($file.Name -eq "go.zip") { $skip = $true }
    
    foreach ($ext in $excludeExts) {
        if ($file.Extension -eq $ext) {
            $skip = $true
            break
        }
    }
    
    if (-not $skip) {
        $relPath = $file.FullName.Substring($sourceDir.Length + 1)
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.FullName, $relPath) | Out-Null
    }
}
$zip.Dispose()
