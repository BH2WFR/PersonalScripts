param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$esc = [char]27
$FLYellow = "$esc[33m"
$FLBlue = "$esc[34m"
$FLCyan = "$esc[36m"
$FLGreen = "$esc[32m"
$CRst = "$esc[0m"



Write-Host ("${FLYellow}Command line arguments:${CRst}")

$scriptPath = $MyInvocation.MyCommand.Path
Write-Host ("  PATH: ${FLGreen}$scriptPath${CRst}")

for ($i = 0; $i -lt $Args.Count; $i++) {
    Write-Host ("  argv[${FLYellow}$i${CRst}]: ${FLCyan}$($Args[$i])${CRst}")
}
