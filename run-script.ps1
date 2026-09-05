[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs = @()
)

# Thin wrapper: find Python, then delegate to run-script.py with all arguments.

$scriptDirectory = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

# ----- find python: prefer bundled runtime, then cheap conda path derivation -----
$pythonCmd = & {
    # 1. Bundled Python
    foreach ($candidate in @(
        (Join-Path $scriptDirectory "deps\python\python.exe"),
        (Join-Path $scriptDirectory "deps\python\bin\python")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    # 2. Derive the base environment from Get-Command conda / CONDA_EXE.
    # Typical layouts place conda under <base>/Scripts, <base>/condabin,
    # or <base>/bin, so no subprocess is needed for the common case.
    $conda = Get-Command conda -ErrorAction SilentlyContinue
    if ($conda) {
        $condaLocations = @(
            $env:CONDA_EXE
            $conda.Source
            $conda.Path
        ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique

        foreach ($condaLocation in $condaLocations) {
            if (-not (Test-Path -LiteralPath $condaLocation -PathType Leaf)) { continue }
            $condaParent = Split-Path -Parent $condaLocation
            $parentName = Split-Path -Leaf $condaParent
            if ($parentName -notin @("Scripts", "condabin", "bin")) { continue }
            $condaBase = Split-Path -Parent $condaParent
            if (-not (Test-Path -LiteralPath (Join-Path $condaBase "conda-meta") -PathType Container)) {
                continue
            }
            foreach ($candidate in @(
                (Join-Path $condaBase "python.exe"),
                (Join-Path $condaBase "bin/python")
            )) {
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
            }
        }
    }

    # 3. Check common base-environment locations without starting conda.
    $knownCandidates = @(
        "$env:USERPROFILE\miniconda3\python.exe",
        "$env:USERPROFILE\anaconda3\python.exe",
        "$env:PROGRAMDATA\miniconda3\python.exe",
        "$env:PROGRAMDATA\anaconda3\python.exe",
        "$env:HOME/miniconda3/bin/python",
        "$env:HOME/anaconda3/bin/python",
        "/opt/miniconda3/bin/python",
        "/opt/anaconda3/bin/python"
    )
    foreach ($candidate in $knownCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    # 4. Slow but authoritative fallback for non-standard Conda layouts.
    if ($conda) {
        $condaBase = & conda info --base 2>$null
        if ($condaBase) {
            foreach ($candidate in @(
                (Join-Path $condaBase.Trim() "python.exe"),
                (Join-Path $condaBase.Trim() "bin/python")
            )) {
                if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
            }
        }
    }

    # 5. Last-resort system candidates.
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
