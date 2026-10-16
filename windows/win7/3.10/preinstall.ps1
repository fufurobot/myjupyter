# preinstall.ps1 - Windows 7 (win7) preinstall for myjupyter.
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

$Distro        = 'win7'
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
    # Build chmlib directly from source with the system C compiler.
    #
    # WHY NOT CMAKE:
    #   The canonical repository (jedwing/CHMLib) has NO CMakeLists.txt - it
    #   uses autotools (configure.in / Makefile.am), which is not viable on a
    #   Windows runner. Its `src/` directory is nevertheless self-contained:
    #   chm_lib.c, chm_lib.h, lzx.c, lzx.h. Compiling those four files with
    #   cl.exe (or cc) is all that chmlib needs.
    #
    # WHY NOT THE VCPKG PORT:
    #   ports/chmlib/portfile.cmake downloads
    #   http://www.jedrea.com/chmlib/chmlib-0.40.zip, which returns 404, so
    #   `vcpkg install chmlib` can never succeed.
    $work = Join-Path $env:TEMP ('chmlib-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    try {
        $zip = Join-Path $work 'chmlib.zip'
        $url = 'https://codeload.github.com/jedwing/CHMLib/zip/refs/heads/master'
        Write-Log "downloading chmlib sources from $url"
        try {
            Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
        } catch {
            Write-Warn "source download failed: $_"
            return $false
        }
        Expand-Archive -Path $zip -DestinationPath $work -Force

        # Locate the sources wherever the archive rooted them.
        $hdr = Get-ChildItem -Path $work -Recurse -Filter 'chm_lib.h' -ErrorAction SilentlyContinue |
               Select-Object -First 1
        if (-not $hdr) { Write-Warn "no chm_lib.h in the downloaded archive"; return $false }
        $srcDir = Split-Path $hdr.FullName -Parent

        $prefix = Join-Path $work 'install'
        $inc    = Join-Path $prefix 'include'
        $libDir = Join-Path $prefix 'lib'
        New-Item -ItemType Directory -Force -Path $inc, $libDir | Out-Null
        Copy-Item $hdr.FullName (Join-Path $inc 'chm_lib.h') -Force

        # A bare PowerShell session has no MSVC on PATH: cl.exe/lib.exe live
        # behind vcvarsall.bat. Locate Visual Studio and import that
        # environment before compiling.
        if (-not (Test-Command 'cl.exe')) {
            $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
            if (Test-Path $vswhere) {
                $vsPath = & $vswhere -latest -products * `
                          -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
                          -property installationPath 2>$null
                if ($vsPath) {
                    $vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'
                    if (Test-Path $vcvars) {
                        Write-Log "importing MSVC environment from $vcvars"
                        # Run cmd.exe once and capture the resulting env vars.
                        $envDump = & cmd.exe /c "`"$vcvars`" >nul 2>&1 && set"
                        foreach ($line in $envDump) {
                            if ($line -match '^([^=]+)=(.*)$') {
                                Set-Item -Path ("env:" + $matches[1]) -Value $matches[2] -ErrorAction SilentlyContinue
                            }
                        }
                    }
                }
            }
        }

        if (-not (Test-Command 'cl.exe')) {
            $fallbacks = @('clang.exe', 'gcc.exe')
            $cc = $fallbacks | Where-Object { Test-Command $_ } | Select-Object -First 1
            if (-not $cc) {
                Write-Warn 'no C compiler found (cl.exe/clang/gcc); cannot build chmlib'
                Write-Warn 'install "Visual Studio Build Tools" with the C++ workload, then re-run'
                return $false
            }
            Write-Log "cl.exe unavailable; using $cc instead"
        }

        $objs = @()
        foreach ($c in @('chm_lib.c', 'lzx.c')) {
            $srcFile = Join-Path $srcDir $c
            if (-not (Test-Path $srcFile)) { Write-Warn "missing source file $c"; return $false }
            $obj = Join-Path $work ([IO.Path]::GetFileNameWithoutExtension($c) + '.obj')
            Write-Log "compiling $c"
            # /c compile only, /O2 optimise, /DCHM_STATIC for the static build.
            # Capture compiler output: without it a failure is a bare exit
            # code and cannot be diagnosed from CI (learned the hard way).
            # /DWIN32 IS REQUIRED. chm_lib.c and chm_lib.h test `#ifdef WIN32`,
            # but MSVC predefines only `_WIN32`. Without this define the code
            # takes the Linux branch and does `#include <unistd.h>`, which does
            # not exist on MSVC, so cl.exe exits 2.
            $compileOut = & cl.exe /nologo /c /O2 /W3 `
                /DWIN32 /D_WINDOWS /DCHM_STATIC /D_CRT_SECURE_NO_WARNINGS /D_CRT_NONSTDC_NO_DEPRECATE `
                "/I$srcDir" "/Fo$obj" $srcFile *>&1
            $compileOut | Out-File -FilePath (Join-Path $work 'cl.log') -Append -Encoding utf8
            if ($LASTEXITCODE -ne 0) {
                Write-Warn "cl.exe failed on $c (exit $LASTEXITCODE); output:"
                $compileOut | Select-Object -Last 15 | ForEach-Object { Write-Warn "  $_" }
                return $false
            }
            $objs += $obj
        }

        $lib = Join-Path $libDir 'chm.lib'
        Write-Log 'archiving chm.lib'
        $libOut = & lib.exe /nologo "/OUT:$lib" @objs *>&1
        $libOut | Out-File -FilePath (Join-Path $work 'cl.log') -Append -Encoding utf8
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $lib)) {
            Write-Warn "lib.exe failed to produce chm.lib (exit $LASTEXITCODE); output:"
            $libOut | Select-Object -Last 15 | ForEach-Object { Write-Warn "  $_" }
            return $false
        }

        $env:CHMLIB_PREFIX = $prefix
        $env:INCLUDE       = "$inc;$env:INCLUDE"
        $env:LIB           = "$libDir;$env:LIB"
        $env:CFLAGS        = "$env:CFLAGS /I$inc"
        $env:LDFLAGS       = "$env:LDFLAGS /LIBPATH:$libDir"
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
