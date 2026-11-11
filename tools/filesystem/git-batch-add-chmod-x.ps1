$ErrorActionPreference = "Stop"
$HELP = @'
GIT EXECUTABLE PERMISSIONS

Mark Python and shell files executable in the Git index so checkouts on Unix
retain executable permissions. Commit the index changes to persist them.

Requirements:
  PowerShell, Git and a Git working tree.

Usage:
  pwsh -File git-batch-add-chmod-x.ps1 [DIRECTORY]
'@

if ($args -contains '--help' -or $args -contains '-h') {
    Write-Output $HELP
    exit 0
}

Write-Host "=========== GIT BATCH ADD CHMOD +X ===========" -ForegroundColor Yellow

#============ 路径 ===========
if ($args.Count -gt 0) {
    $TARGET = $args[0]
} else {
    $TARGET = Read-Host -Prompt "Enter path (default: .)"
    if (-not $TARGET) { $TARGET = "." }
}

$TARGET = Resolve-Path $TARGET
Write-Host "  -> target: $TARGET" -ForegroundColor Yellow

#============ git 检查 ===========
Push-Location $TARGET
try {
    git rev-parse --is-inside-work-tree 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Not inside a git repository. EXIT..." -ForegroundColor Red
        exit 1
    }

    $files = Get-ChildItem -Recurse -File | Where-Object { $_.Extension -match '^\.(py|sh)$' }
    $count = ($files | Measure-Object).Count

    if ($count -eq 0) {
        Write-Host "No .py or .sh files found. EXIT..." -ForegroundColor Yellow
        exit 0
    }

    Write-Host "  -> found $count file(s), adding +x via git update-index..." -ForegroundColor Cyan

    foreach ($f in $files) {
        $relPath = Resolve-Path -Relative $f.FullName
        Write-Host "  -> $relPath" -ForegroundColor Gray
        git update-index --chmod=+x $relPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: git update-index failed for $relPath" -ForegroundColor Red
            exit 1
        }
    }

    Write-Host "Done. $count file(s) marked +x in git index." -ForegroundColor Green
    Write-Host "Run 'git commit' to persist the changes." -ForegroundColor Yellow
} finally {
    Pop-Location
}
