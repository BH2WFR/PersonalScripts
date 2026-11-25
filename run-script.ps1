# Locate Python once, then pass the original arguments to the launcher.
$ErrorActionPreference = 'Stop'
$scriptDirectory = $PSScriptRoot

function Get-CondaConfigHome {
    if ($env:OS -eq 'Windows_NT' -or -not $env:SUDO_UID -or $env:SUDO_UID -eq '0' -or (id -u) -ne '0') {
        return $HOME
    }
    if ($IsMacOS) {
        $record = dscacheutil -q user -a uid $env:SUDO_UID | Where-Object { $_ -like 'dir: *' }
        if ($record) { return $record.Substring(5) }
    } else {
        $record = getent passwd $env:SUDO_UID
        if ($record) { return $record.Split(':')[5] }
    }
    throw "Cannot resolve the home directory for sudo UID $env:SUDO_UID."
}

function Get-SystemPython {
    $conda = if ($env:CONDA_EXE -and (Test-Path -LiteralPath $env:CONDA_EXE -PathType Leaf)) {
        $env:CONDA_EXE
    } else {
        Get-Command conda -ErrorAction SilentlyContinue
    }
    if ($conda) {
        $configFile = Join-Path (Get-CondaConfigHome) '.config/PersonalScripts/conda-env.txt'
        $name = 'base'
        if (Test-Path -LiteralPath $configFile) {
            $value = [IO.File]::ReadAllText($configFile).Trim()
            if ($value) { $name = $value }
        }
        if ($name -match '[\\/\r\n]' -or $name.StartsWith('-')) {
            throw "Expected one Conda environment name in $configFile."
        }
        $prefix = $null
        if ($name -ceq 'base') {
            $condaPath = if ($conda -is [string]) { $conda } else { $conda.Path }
            if ($condaPath) {
                $root = Split-Path -Parent (Split-Path -Parent $condaPath)
                if ($root -and (Test-Path -LiteralPath (Join-Path $root 'conda-meta') -PathType Container)) {
                    $prefix = $root
                }
            }
            if (-not $prefix) {
                $prefix = & $conda info --base
                if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the Conda base environment.' }
            }
        } else {
            # Conda resolves custom envs_dirs. Only this fixed probe goes through conda run.
            $prefix = & $conda run --no-capture-output -n $name python -c "import os; print(os.environ['CONDA_PREFIX'])"
            if ($LASTEXITCODE -ne 0) { throw "Cannot locate Conda environment '$name' ($configFile)." }
        }
        if (-not $prefix) { throw "Cannot locate Conda environment '$name' ($configFile)." }
        $relative = if ($env:OS -eq 'Windows_NT') { 'python.exe' } else { 'bin/python' }
        $candidate = Join-Path $prefix.Trim() $relative
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        throw "No Python in Conda environment '$name' at $candidate."
    }

    foreach ($command in 'python', 'python3') {
        $python = Get-Command $command -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($python) { return $python.Source }
    }
    throw 'Cannot find bundled Python, Conda, or Python on PATH.'
}

$bundled = foreach ($relative in 'deps/python/python.exe', 'deps/python/bin/python', 'deps/python/bin/python3') {
    $candidate = Join-Path $scriptDirectory $relative
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $candidate; break }
}
$previousPythonPath = $env:PYTHONPATH
$previousHome = $env:PYTHONHOME
$previousUserSite = $env:PYTHONNOUSERSITE
$previousPath = $env:PATH
try {
    $pythonCmd = if ($bundled) {
        $env:PYTHONHOME = $null
        $env:PYTHONNOUSERSITE = '1'
        $bin = Split-Path -Parent $bundled
        $env:PATH = "$bin$([IO.Path]::PathSeparator)$previousPath"
        if ($env:OS -eq 'Windows_NT') {
            $env:PATH = "$(Join-Path $bin 'Scripts');$env:PATH"
        }
        $bundled
    } else {
        Get-SystemPython
    }
    $env:PYTHONPATH = $scriptDirectory
    & $pythonCmd (Join-Path $scriptDirectory 'run-script.py') @args
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
    if ($bundled) {
        $env:PYTHONHOME = $previousHome
        $env:PYTHONNOUSERSITE = $previousUserSite
        $env:PATH = $previousPath
    }
}
