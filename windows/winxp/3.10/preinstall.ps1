# preinstall.ps1 - Windows XP era (winxp) preinstall for myjupyter.
#
# Windows counterpart of preinstall.sh. The bash script is kept for parity and
# for Git Bash users, but native PowerShell is the reliable path on Windows.
#
# WHY chmlib IS NEEDED
#   pychm ships no wheels, so pip always compiles chm/_chmlib.c, which does
#   #include <chm_lib.h> and links against the native chmlib. Without it:
#       fatal error: chm_lib.h: No such file or directory
[CmdletBinding()]
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Distro        = 'winxp'
$PythonVersion = '3.10'

function Write-Log  { param([string]$m) Write-Host "[preinstall:$Distro] $m" -ForegroundColor Cyan }
function Write-Warn { param([string]$m) Write-Host "[preinstall:$Distro] $m" -ForegroundColor Yellow }
function Write-Err  { param([string]$m) Write-Host "[preinstall:$Distro] $m" -ForegroundColor Red }

function Test-Command { param([string]$Name) [bool](Get-Command $Name -ErrorAction SilentlyContinue) }

function Test-Libchm {
    # Look for chm_lib.h outside the default include path as well.
    $candidates = @()
    if ($env:CHMLIB_PREFIX) { $candidates += (Join-Path $env:CHMLIB_PREFIX 'include\chm_lib.h') }
    $candidates += @(
        'C:\Program Files\chmlib\include\chm_lib.h',
        'C:\vcpkg\installed\x64-windows\include\chm_lib.h',
        'C:\msys64\ucrt64\include\chm_lib.h',
        'C:\msys64\mingw64\include\chm_lib.h'
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $true } }
    return $false
}

function Install-Libchm {
    if (Test-Command 'vcpkg') {
        Write-Log 'installing chmlib via vcpkg'
        vcpkg install chmlib
        # Export the triplet paths so pip's compile step can find them.
        $env:CFLAGS  = "$env:CFLAGS /IC:\vcpkg\installed\x64-windows\include"
        $env:LDFLAGS = "$env:LDFLAGS /LIBPATH:C:\vcpkg\installed\x64-windows\lib"
        return
    }
    if (Test-Command 'choco') {
        Write-Log 'installing chmlib via Chocolatey'
        choco install -y chmlib
        return
    }
    if (Test-Command 'pacman') {          # MSYS2
        Write-Log 'installing chmlib via MSYS2 pacman'
        pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-chmlib
        return
    }
    Write-Err 'no vcpkg, choco, or MSYS2 pacman found to provide chmlib.'
    Write-Err 'pychm will fail to build. Install one of them, then re-run.'
    exit 1
}

# --- 1. Python toolchain ---------------------------------------------------
if (-not (Test-Command 'uv')) {
    Write-Log 'installing uv (official astral.sh installer)'
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Err "uv install failed: $_"
        exit 1
    }
}

# --- 2. Native chmlib (the pychm build fix) --------------------------------
if (Test-Libchm) {
    Write-Log 'native chmlib already present'
} else {
    Write-Log 'native chmlib missing (this is the pychm build failure); installing'
    Install-Libchm
}

if (-not (Test-Libchm)) {
    Write-Warn 'chm_lib.h still not found after install.'
    Write-Warn 'set CHMLIB_PREFIX to the chmlib root and re-run, e.g.:'
    Write-Warn '  $env:CHMLIB_PREFIX = "C:\vcpkg\installed\x64-windows"'
} else {
    Write-Log 'chmlib OK; pychm will compile'
}

# --- 3. Node (for configurable-http-proxy used by jupyterhub) --------------
if (-not (Test-Command 'node')) {
    if (Test-Command 'winget') {
        Write-Log 'installing Node.js LTS via winget'
        winget install --id OpenJS.NodeJS.LTS --silent --accept-package-agreements --accept-source-agreements
    } else {
        Write-Warn 'node not found and winget unavailable; install Node.js manually'
    }
}

Write-Log "preinstall complete for $Distro (python $PythonVersion)"
