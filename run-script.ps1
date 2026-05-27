[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$ScriptName,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs = @()
)

# chcp 65001
# $OutputEncoding = [System.Text.UTF8Encoding]::new()
# [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$esc = "$([char]27)" # ANSI Escape Seq.
$FLYellow = "$esc[33m"
$FLGreen = "$esc[32m"
$FLCyan = "$esc[36m"
$FLRed = "$esc[31m"
$FGray = "$esc[90m"
$CRst = "$esc[0m"

$scriptDirectory = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }

function Get-RelativePythonScriptPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )

    $relativePath = $FullPath.Substring($scriptDirectory.Length).TrimStart('\', '/')
    return $relativePath.Replace('\', '/')
}

function Get-RelativeScriptPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )

    return Get-RelativePythonScriptPath -FullPath $FullPath
}

function Resolve-ScriptPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RequestedScriptName
    )

    $normalizedScriptName = $RequestedScriptName.Replace('\', '/').TrimStart('/')

    $hasPy = $normalizedScriptName.EndsWith(".py", [System.StringComparison]::OrdinalIgnoreCase)
    $hasPs1 = $normalizedScriptName.EndsWith(".ps1", [System.StringComparison]::OrdinalIgnoreCase)

    if ($hasPy -or $hasPs1) {
        $relativePath = $normalizedScriptName.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        return Join-Path -Path $scriptDirectory -ChildPath $relativePath
    }

    $relativePathBase = $normalizedScriptName.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
    $candidatePy = Join-Path -Path $scriptDirectory -ChildPath ($relativePathBase + ".py")
    if (Test-Path -LiteralPath $candidatePy -PathType Leaf) {
        return $candidatePy
    }

    $candidatePs1 = Join-Path -Path $scriptDirectory -ChildPath ($relativePathBase + ".ps1")
    if (Test-Path -LiteralPath $candidatePs1 -PathType Leaf) {
        return $candidatePs1
    }

    # Default to .py for a clearer error message, while still preferring .py when both exist.
    return $candidatePy
}

function Show-SupportedScripts {
    $selfPath = $PSCommandPath

    $scripts = Get-ChildItem -LiteralPath $scriptDirectory -File -Recurse |
        Where-Object {
            ($_.Extension -ieq ".py" -or $_.Extension -ieq ".ps1") -and
            ($_.Name -ne "__init__.py") -and
            (-not $selfPath -or $_.FullName -ne $selfPath) -and
            ($_.DirectoryName -notmatch '[\\/](linux|macos)([\\/]|$)')
        } | Sort-Object FullName

    # Separate root-level and subfolder scripts
    $rootScripts = @($scripts | Where-Object { $_.DirectoryName -eq $scriptDirectory })
    $subScripts = @($scripts | Where-Object { $_.DirectoryName -ne $scriptDirectory })

    if (-not $rootScripts -and -not $subScripts) {
        Write-Host "No Python/PowerShell scripts found in: ``$scriptDirectory``:"
        return $null
    }

    Write-Host "Supported scripts in: ``$scriptDirectory``:"
    $cnt = 0
    $allScripts = @()

    foreach ($script in $rootScripts) {
        $relativePath = Get-RelativeScriptPath -FullPath $script.FullName
        $fileName = [System.IO.Path]::GetFileName($relativePath)
        $color = if ($script.Extension -ieq ".py") { $FLCyan } else { $FLGreen }
        Write-Host ("  ${FGray}[${cnt}]${CRst}: ${color}${fileName}${CRst}")
        $allScripts += $script
        $cnt++
    }

    if ($subScripts.Count -gt 0) {
        Write-Host ""
        Write-Host "  ${FLYellow}--- Subfolders ---${CRst}"
        foreach ($script in $subScripts) {
            $relativePath = Get-RelativeScriptPath -FullPath $script.FullName
            $fileName = [System.IO.Path]::GetFileName($relativePath)
            $relativeDirectory = [System.IO.Path]::GetDirectoryName($relativePath)
            $color = if ($script.Extension -ieq ".py") { $FLCyan } else { $FLGreen }
            Write-Host ("  ${FGray}[${cnt}]${CRst}: ${FLYellow}${relativeDirectory}${CRst}/${color}${fileName}${CRst}")
            $allScripts += $script
            $cnt++
        }
    }

    return $allScripts
}

$showList = [string]::IsNullOrWhiteSpace($ScriptName) -or $ScriptName -eq "--list" -or $RemainingArgs -contains "--list"
if ($showList) {
    $allScripts = Show-SupportedScripts
    if (-not $allScripts) { exit 0 }

    if ($ScriptName -eq "--list" -or $RemainingArgs -contains "--list") {
        exit 0
    }

    Write-Host ""
    $choice = Read-Host -Prompt "${FLYellow}Enter number to execute (or Enter to exit)${CRst}"
    if ([string]::IsNullOrWhiteSpace($choice)) {
        exit 0
    }
    $idx = [int]$choice
    if ($idx -lt 0 -or $idx -ge $allScripts.Count) {
        Write-Error "Invalid selection: $idx"
        exit 1
    }
    $ScriptName = $allScripts[$idx].FullName
    $RemainingArgs = @()
}


$scriptPath = if (Test-Path -LiteralPath $ScriptName -PathType Leaf) { $ScriptName } else { Resolve-ScriptPath -RequestedScriptName $ScriptName }
if ($PSCommandPath -and ($scriptPath -eq $PSCommandPath)) {
    Write-Error "Refusing to run itself: ``$scriptPath``"
    exit 1
}

if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    $normalizedScriptName = $ScriptName.Replace('\\', '/').TrimStart('/')
    $hasPy = $normalizedScriptName.EndsWith(".py", [System.StringComparison]::OrdinalIgnoreCase)
    $hasPs1 = $normalizedScriptName.EndsWith(".ps1", [System.StringComparison]::OrdinalIgnoreCase)

    if (-not $hasPy -and -not $hasPs1) {
        $relativePathBase = $normalizedScriptName.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $candidatePy = Join-Path -Path $scriptDirectory -ChildPath ($relativePathBase + ".py")
        $candidatePs1 = Join-Path -Path $scriptDirectory -ChildPath ($relativePathBase + ".ps1")
        Write-Error "Cannot find script: ``$candidatePy`` (preferred) or ``$candidatePs1``"
    } else {
        Write-Error "Cannot find script: ``$scriptPath``"
    }
    exit 1
}

Write-Host ("${FLYellow}Resolved script path:${CRst} ${FLGreen}$scriptPath${CRst}`n")
$ext = [System.IO.Path]::GetExtension($scriptPath)
if ($ext -ieq ".py") {
    $env:PYTHONPATH = $scriptDirectory
    $pythonCmd = & {
        if (Get-Command python -ErrorAction SilentlyContinue) { return (Get-Command python).Source }
        if (Get-Command python3 -ErrorAction SilentlyContinue) { return (Get-Command python3).Source }
        return $null
    }
    if (-not $pythonCmd) {
        Write-Error "Cannot find python/python3"
        exit 1
    }
    Write-Host ("${FLYellow}Resolved Python path:${CRst} ${FLGreen}$pythonCmd${CRst}`n")
    & python $scriptPath @RemainingArgs
    exit $LASTEXITCODE
}

if ($ext -ieq ".ps1") {
    $psExe = (Get-Command -Name "pwsh" -ErrorAction SilentlyContinue).Source
    if (-not $psExe) {
        $psExe = (Get-Command -Name "powershell" -ErrorAction SilentlyContinue).Source
    }
    if (-not $psExe) {
        Write-Error "Cannot find PowerShell executable (pwsh/powershell)"
        exit 1
    }

    & $psExe -NoProfile -ExecutionPolicy Bypass -File $scriptPath @RemainingArgs
    exit $LASTEXITCODE
}

Write-Error "Unsupported script type: ``$ext``"
exit 1
