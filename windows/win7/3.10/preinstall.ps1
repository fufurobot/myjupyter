# preinstall.ps1 - native prerequisites for win7 (windows), Python 3.10.
#
# Scope: ONLY the build prerequisites for the core requirement set. Anything
# that cannot be built on Windows is isolated in requirements.experimental.txt
# rather than fought here.
#
# pychm is deliberately NOT installed. PyPI has exactly one pychm wheel in its
# whole history (cp27, macOS), so every Python 3 install compiles it against
# the native chmlib - and vcpkg's chmlib port is broken upstream (its
# portfile fetches a 404 URL). Not worth it: see requirements.experimental.txt
[CmdletBinding()]
param([switch]$Force)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Distro = 'win7'

function Write-Log  { param([string]$m) Write-Host "[preinstall:$Distro] $m" -ForegroundColor Cyan }
function Write-Warn { param([string]$m) Write-Host "[preinstall:$Distro] $m" -ForegroundColor Yellow }
function Test-Command { param([string]$N) [bool](Get-Command $N -ErrorAction SilentlyContinue) }

# uv via the official installer (distro/package-manager packages lag).
if (-not (Test-Command 'uv')) {
    Write-Log 'installing uv via the official astral.sh installer'
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Write-Warn "uv install failed: $_"
    }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

# Node is only needed by jupyterhub's proxy, which is unix-only anyway; report
# it as optional rather than installing it for every Windows target.
if (-not (Test-Command 'node')) {
    Write-Warn 'node not found (optional: only needed for jupyterhub on unix)'
}

Write-Log "preinstall complete for $Distro"
