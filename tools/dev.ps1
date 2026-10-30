# PowerShell front end for tools/dev, for contributors on Windows who are not
# in Git Bash or WSL. Same commands, same container:
#
#   .\tools\dev.ps1 sim
#   .\tools\dev.ps1 sim --only frame_crc
#   .\tools\dev.ps1 lint
#   .\tools\dev.ps1 synth
#   .\tools\dev.ps1 all
#   .\tools\dev.ps1 new fpga frame_crc
#   .\tools\dev.ps1 shell
#
# Set $env:UTOSS_PIP_TRUSTED_HOST = "pypi.org files.pythonhosted.org" first if
# you are on a network that re-signs HTTPS and the image build fails in pip.
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "all",

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Image = if ($env:UTOSS_RTL_IMAGE) { $env:UTOSS_RTL_IMAGE } else { "utoss-rtl:synth" }
$Target = if ($env:UTOSS_RTL_TARGET) { $env:UTOSS_RTL_TARGET } else { "synth" }

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Build-Image {
    Write-Host "==> building $Image (target: $Target)"
    $buildArgs = @("build", "-f", "$RepoRoot\docker\Dockerfile", "--target", $Target)
    if ($env:UTOSS_PIP_TRUSTED_HOST) {
        $buildArgs += @("--build-arg", "PIP_TRUSTED_HOST=$($env:UTOSS_PIP_TRUSTED_HOST)")
    }
    $buildArgs += @("-t", $Image, $RepoRoot)
    Invoke-Checked "docker" $buildArgs
}

# Through cmd.exe so docker's stderr never reaches PowerShell: with
# ErrorActionPreference=Stop, PowerShell 5.1 turns any native stderr line into a
# terminating error, which is how "Docker is not running" used to surface as an
# unreadable NativeCommandError about a named pipe.
function Test-Docker {
    cmd /c "docker info >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

function Test-Image {
    cmd /c "docker image inspect $Image >nul 2>&1"
    return ($LASTEXITCODE -eq 0)
}

function Invoke-InContainer {
    param([string[]]$Arguments, [switch]$Interactive)
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "docker not found. Install Docker Desktop (https://www.docker.com/products/docker-desktop/), then run this again."
        exit 1
    }
    if (-not (Test-Docker)) {
        Write-Host "Docker is installed but not running. Start Docker Desktop, wait until it says it is running, then run this again."
        exit 1
    }
    if (-not (Test-Image)) { Build-Image }
    $runArgs = @("run", "--rm")
    # Without -it, `shell` starts bash with no terminal and it exits at once.
    if ($Interactive) { $runArgs += "-it" }
    $runArgs += @("-v", "$($RepoRoot):/work", "-w", "/work", $Image) + $Arguments
    Invoke-Checked "docker" $runArgs
}

switch ($Command) {
    "build"    { Build-Image }
    "rebuild"  { docker image rm -f $Image *> $null; Build-Image }
    "sim"      { Invoke-InContainer (@("python3", "scripts/run_rtl_tests.py") + $Rest) }
    "lint"     { Invoke-InContainer (@("python3", "scripts/lint_rtl.py") + $Rest) }
    "synth"    { Invoke-InContainer (@("python3", "scripts/run_synth_check.py") + $Rest) }
    "list"     { Invoke-InContainer (@("python3", "scripts/rtl_bench.py") + $Rest) }
    "new"      { Invoke-InContainer (@("python3", "scripts/new_module.py") + $Rest) }
    "versions" { Invoke-InContainer @("utoss-versions") }
    "shell"    { Invoke-InContainer @("/bin/bash") -Interactive }
    "all" {
        Invoke-InContainer @("python3", "scripts/lint_rtl.py")
        Invoke-InContainer (@("python3", "scripts/run_rtl_tests.py") + $Rest)
        Invoke-InContainer @("python3", "scripts/run_synth_check.py")
    }
    default {
        Write-Host "unknown command: $Command"
        Write-Host "commands: build rebuild sim lint synth list new versions shell all"
        exit 2
    }
}
