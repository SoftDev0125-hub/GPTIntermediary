param(
    [string]$Version = "16.4-1",
    [string]$OutputRoot = "",
    [switch]$ForceRedownload
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[*] $Message"
}

function Resolve-ProjectRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

$projectRoot = Resolve-ProjectRoot
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $projectRoot "portable_deps"
}

$archiveDir = Join-Path $OutputRoot "archives"
$extractDir = Join-Path $OutputRoot ("postgresql-" + $Version + "-windows-x64-binaries")
$zipName = "postgresql-$Version-windows-x64-binaries.zip"
$zipPath = Join-Path $archiveDir $zipName
$downloadUrl = "https://get.enterprisedb.com/postgresql/$zipName"

New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

if ((-not (Test-Path $zipPath)) -or $ForceRedownload) {
    Write-Step "Downloading PostgreSQL binaries zip..."
    Write-Host "    URL: $downloadUrl"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
} else {
    Write-Step "Using existing archive: $zipPath"
}

if (Test-Path $extractDir) {
    Write-Step "Removing existing extracted folder..."
    Remove-Item -Recurse -Force $extractDir
}

Write-Step "Extracting archive..."
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

# The zip root may contain nested folders; locate the first directory with bin\pg_ctl.exe.
$runtimeRoot = $null
$candidates = Get-ChildItem -Path $extractDir -Directory -Recurse
foreach ($dir in $candidates) {
    $pgCtl = Join-Path $dir.FullName "bin\pg_ctl.exe"
    if (Test-Path $pgCtl) {
        $runtimeRoot = $dir.FullName
        break
    }
}

if (-not $runtimeRoot) {
    throw "Could not locate PostgreSQL runtime (bin\pg_ctl.exe) inside: $extractDir"
}

Write-Host ""
Write-Host "[OK] Portable PostgreSQL runtime is ready:"
Write-Host "    $runtimeRoot"
Write-Host ""
Write-Host "Use it for build:"
Write-Host "    `$env:POSTGRES_RUNTIME_DIR=""$runtimeRoot"""
Write-Host "    python build.py"
Write-Host ""
