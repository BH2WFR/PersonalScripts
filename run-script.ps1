[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs = @()
)

# Thin wrapper: find Python, then delegate to run-script.py with all arguments.

$scriptDirectory = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# ----- find python: prefer bundled runtime, then conda and system candidates -----
$pythonCmd = & {
    # 1. Bundled Python
    foreach ($candidate in @(
        (Join-Path $scriptDirectory "deps\python\python.exe"),
        (Join-Path $scriptDirectory "deps\python\bin\python")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    # 2. Try conda info --base (most reliable)
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        $condaBase = & conda info --base 2>$null
        if ($condaBase) {
            $candidate = Join-Path $condaBase.Trim() "python.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
    }

    # 3. Fallback: known paths
    # Windows conda paths
    $winCandidates = @(
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:PROGRAMDATA\miniconda3\python.exe",
        "$env:PROGRAMDATA\anaconda3\python.exe"
    )
    foreach ($c in $winCandidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    # Unix-style conda paths (PowerShell on macOS/Linux, or WSL interop)
    $unixCandidates = @(
        "$env:HOME/miniconda3/bin/python",
        "$env:HOME/anaconda3/bin/python",
        "/opt/miniconda3/bin/python",
        "/opt/anaconda3/bin/python"
    )
    foreach ($c in $unixCandidates) {
        if (Test-Path -LiteralPath $c -PathType Leaf) { return $c }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) { return (Get-Command python).Source }
    if (Get-Command python3 -ErrorAction SilentlyContinue) { return (Get-Command python3).Source }
    return $null
}

if (-not $pythonCmd) {
    Write-Error "Cannot find python (miniconda/anaconda/python3). Install miniconda: https://docs.conda.io/en/latest/miniconda.html"
    exit 1
}

# ----- delegate to run-script.py -----
$env:PYTHONPATH = $scriptDirectory
& $pythonCmd "$scriptDirectory\run-script.py" @RemainingArgs
exit $LASTEXITCODE
