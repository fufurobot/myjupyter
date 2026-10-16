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

function Install-LibchmFromSource {
    # Fallback that does not depend on any package manager's port being healthy.
    #
    # NOTE: the vcpkg `chmlib` port is CURRENTLY BROKEN upstream. Its
    # portfile.cmake downloads http://www.jedrea.com/chmlib/chmlib-0.40.zip,
    # which now returns 404, so `vcpkg install chmlib` can never succeed:
    #
    #     error: curl operation failed with response code 404.
    #     CMake Error at scripts/cmake/vcpkg_download_distfile.cmake:134
    #
    # Build from the maintained GitHub mirror instead. chmlib only supports
    # static linkage on Windows, hence CHM_STATIC.
    $work = Join-Path $env:TEMP ('chmlib-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    try {
        $zip = Join-Path $work 'chmlib.zip'
        # `codeload` serves a stable archive for a tagged ref, which is much
        # more durable than a personal homepage.
        $url = 'https://codeload.github.com/jedwing/chmlib/zip/refs/heads/master'
        Write-Log "downloading chmlib sources from $url"
        try {
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        } catch {
            Write-Warn "source download failed: $_"
            return $false
        }
        Expand-Archive -Path $zip -DestinationPath $work -Force
        $src = Get-ChildItem -Path $work -Directory | Select-Object -First 1
        if (-not $src) { Write-Warn 'no source directory after extract'; return $false }

        if (-not (Test-Command 'cmake')) {
            Write-Warn 'cmake not available; cannot build chmlib from source'
            Write-Warn 'install CMake (winget install Kitware.CMake) and re-run'
            return $false
        }
        $prefix = Join-Path $work 'install'
        $build  = Join-Path $work 'build'

        # Keep the tool output: piping to Out-Null hides the real error and
        # makes a failed build undiagnosable. Capture, then report on failure.
        $log = Join-Path $work 'cmake.log'
        Write-Log "configuring chmlib -> $build"
        $configure = & cmake -S $src.FullName -B $build `
              -DCMAKE_BUILD_TYPE=Release `
              -DCMAKE_INSTALL_PREFIX="$prefix" `
              -DCHM_STATIC=ON *>&1
        $configure | Out-File -FilePath $log -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "cmake configure failed (exit $LASTEXITCODE); last lines:"
            $configure | Select-Object -Last 12 | ForEach-Object { Write-Warn "  $_" }
            return $false
        }

        Write-Log 'building and installing chmlib'
        $buildOut = & cmake --build $build --config Release --target install *>&1
        $buildOut | Out-File -FilePath $log -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "cmake build failed (exit $LASTEXITCODE); last lines:"
            $buildOut | Select-Object -Last 12 | ForEach-Object { Write-Warn "  $_" }
            return $false
        }

        # CMake may place the artifacts in a config subdirectory on Windows.
        $header = Join-Path $prefix 'include\chm_lib.h'
        if (-not (Test-Path $header)) {
            $found = Get-ChildItem -Path $work -Recurse -Filter 'chm_lib.h' -ErrorAction SilentlyContinue |
                     Select-Object -First 1
            if ($found) {
                $inc = Split-Path $found.FullName -Parent
                $lib = Get-ChildItem -Path $work -Recurse -Filter 'chm.lib' -ErrorAction SilentlyContinue |
                       Select-Object -First 1
                $env:CHMLIB_PREFIX = Split-Path $inc -Parent
                $env:INCLUDE       = "$inc;$env:INCLUDE"
                $env:CFLAGS        = "$env:CFLAGS /I$inc"
                if ($lib) {
                    $env:LIB     = "$(Split-Path $lib.FullName -Parent);$env:LIB"
                    $env:LDFLAGS = "$env:LDFLAGS /LIBPATH:$(Split-Path $lib.FullName -Parent)"
                }
                Write-Log "built chmlib from source -> $inc"
                return $true
            }
            Write-Warn "source build produced no chm_lib.h; full log: $log"
            return $false
        }

        $env:CHMLIB_PREFIX = $prefix
        $env:INCLUDE       = "$prefix\include;$env:INCLUDE"
        $env:LIB           = "$prefix\lib;$env:LIB"
        $env:CFLAGS        = "$env:CFLAGS /I$prefix\include"
        $env:LDFLAGS       = "$env:LDFLAGS /LIBPATH:$prefix\lib"
        Write-Log "built chmlib from source -> $prefix"
        return $true
    } catch {
        Write-Warn "chmlib source build failed: $_"
        return $false
    }
}

function Install-Libchm {
    # Try every provider we can. Any single one may be broken (the vcpkg port
    # is, today), so never trust the first and never hard-fail the whole
    # preinstall just because an optional native library is unavailable.
    if (Test-Command 'vcpkg') {
        Write-Log 'trying chmlib via vcpkg (known to fail: upstream jedrea.com 404)'
        vcpkg install chmlib 2>&1 | Out-Null
        $root = if ($env:VCPKG_ROOT) { $env:VCPKG_ROOT } else { 'C:\vcpkg' }
        if (Test-Path "$root\installed\x64-windows\include\chm_lib.h") {
            $env:INCLUDE = "$root\installed\x64-windows\include;$env:INCLUDE"
            $env:LIB     = "$root\installed\x64-windows\lib;$env:LIB"
            $env:CFLAGS  = "$env:CFLAGS /I$root\installed\x64-windows\include"
            $env:LDFLAGS = "$env:LDFLAGS /LIBPATH:$root\installed\x64-windows\lib"
            Write-Log 'chmlib installed via vcpkg'
            return $true
        }
        Write-Warn 'vcpkg could not provide chmlib; trying other providers'
    }

    if (Test-Command 'choco') {
        Write-Log 'trying chmlib via Chocolatey'
        choco install -y chmlib 2>&1 | Out-Null
        if (Test-Libchm) { Write-Log 'chmlib installed via Chocolatey'; return $true }
        Write-Warn 'Chocolatey could not provide chmlib'
    }

    if (Test-Command 'pacman') {          # MSYS2
        Write-Log 'trying chmlib via MSYS2 pacman'
        pacman -S --needed --noconfirm mingw-w64-ucrt-x86_64-chmlib 2>&1 | Out-Null
        if (Test-Libchm) { Write-Log 'chmlib installed via MSYS2'; return $true }
        Write-Warn 'MSYS2 could not provide chmlib'
    }

    Write-Log 'falling back to building chmlib from source'
    if (Install-LibchmFromSource) { return $true }

    Write-Warn 'chmlib could not be provisioned by any provider.'
    Write-Warn 'pychm will not build here. Options:'
    Write-Warn '  1. set CHMLIB_PREFIX to an existing chmlib root and re-run'
    Write-Warn '  2. add INCLUDE/LIB for chmlib, then: pip install pychm'
    Write-Warn '  3. skip pychm on Windows; the rest of the toolchain is unaffected'
    return $false
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

# --- 1b. CMake (needed to build chmlib from source when no package provides it)
if (-not (Test-Command 'cmake')) {
    Write-Log 'cmake not found; attempting to install it for the chmlib source build'
    if (Test-Command 'winget') {
        try {
            winget install --id Kitware.CMake --silent --accept-package-agreements --accept-source-agreements | Out-Null
        } catch { Write-Warn "winget could not install CMake: $_" }
    } elseif (Test-Command 'choco') {
        try { choco install -y cmake --no-progress | Out-Null } catch { Write-Warn "choco could not install CMake: $_" }
    } else {
        Write-Warn 'no winget/choco to install CMake; the chmlib source fallback will be skipped'
    }
    # Refresh PATH so a just-installed cmake becomes visible.
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path','User')
}

# --- 2. Native chmlib (the pychm build fix) --------------------------------
if (Test-Libchm) {
    Write-Log 'native chmlib already present'
} else {
    Write-Log 'native chmlib missing (this is the pychm build failure); installing'
    if (-not (Install-Libchm)) {
        # chmlib is only needed to build ONE sdist-only package (pychm).
        # Never fail the whole environment because of it.
        Write-Warn 'continuing without chmlib; pychm will be skipped on this machine'
    }
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
