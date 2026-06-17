[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
	# Registry root where network profiles are stored.
	[string]$ProfilesKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\NetworkList\Profiles',

	# Regex used to match Android USB tethering profiles.
	# Android USB tethering creates profiles named "Network", "Network 1", "Network 2", etc.
	# Also matches localized versions: 网络, 網路, 네트워크, ネットワーク
	[string]$Match = '^(Network|网络|網路|네트워크|ネットワーク)( )?([0-9]*)$',

	# Delete without prompting.
	[switch]$Force,

	# Show help message and exit.
	[switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Help) {
	$scriptName = [System.IO.Path]::GetFileName($PSCommandPath)
	Write-Host @"

CLEAR ANDROID RNDIS NETWORK RECORDS
====================================

Usage:
  .\$scriptName [-Match <regex>] [-Force] [-Help]
  .\$scriptName -Help

Description:
  Every time you enable USB tethering on an Android phone, Windows creates
  a new network profile (e.g. "Network", "Network 1", "网络 2"). This causes
  the "Local Area Connection" name to keep incrementing ("Local Area Connection"
  → "Local Area Connection 1" → "Local Area Connection 2" ...). Over time,
  stale profiles clutter the registry. This script removes those entries.

  Requires Administrator privileges (HKLM write access).

Options:
  -ProfilesKey  Registry path to scan
                (default: HKLM:\...\NetworkList\Profiles)
  -Match        Regex to match profile names
                (default: Network/网络/網路/네트워크/ネットワーク + optional number)
  -Force        Delete without confirmation prompt
  -Help         Show this help message

Examples:
  .\$scriptName
      Scan and prompt for each matching profile.

  .\$scriptName -Force
      Scan and delete without prompting.

  .\$scriptName -Match 'Ethernet|Local Area'
      Use a custom regex to match profile names.

"@ -ForegroundColor Yellow
	exit 0
}

function Test-IsWindows {
	return [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
		[System.Runtime.InteropServices.OSPlatform]::Windows
	)
}

function Test-IsAdmin {
	$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
	$principal = [Security.Principal.WindowsPrincipal]::new($currentIdentity)
	return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Convert-RegistryBinaryFileTimeToLocalTime {
	param([object]$Value)

	if ($null -eq $Value) { return $null }
	if ($Value -is [datetime]) { return $Value }

	if ($Value -is [byte[]] -and $Value.Length -ge 8) {
		try {
			$fileTime = [BitConverter]::ToInt64($Value, 0)
			if ($fileTime -le 0) { return $null }
			return ([DateTime]::FromFileTimeUtc($fileTime)).ToLocalTime()
		} catch {
			return $null
		}
	}

	return $null
}

if (-not (Test-IsWindows)) {
	Write-Error 'This script only applies to Windows.'
}

if (-not (Test-IsAdmin)) {
	Write-Error 'Please run PowerShell as Administrator (required to delete HKLM network profiles).'
}

if (-not (Test-Path -LiteralPath $ProfilesKey)) {
	Write-Error "Registry key not found: $ProfilesKey"
}

$guidRegex = '^\{?[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}?$'

$subKeys = Get-ChildItem -LiteralPath $ProfilesKey -ErrorAction Stop |
	Where-Object { $_.PSChildName -match $guidRegex }

if (-not $subKeys -or $subKeys.Count -eq 0) {
	Write-Host "No GUID profile subkeys found under: $ProfilesKey"
	exit 0
}

$profiles = foreach ($k in $subKeys) {
	$p = $null
	try {
		$p = Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction Stop
	} catch {
		$p = $null
	}

	$profileName = if ($p) { [string]$p.ProfileName } else { '' }
	$description = if ($p) { [string]$p.Description } else { '' }

	$dateCreated = $null
	$dateLastConnected = $null
	if ($p) {
		$dateCreated = Convert-RegistryBinaryFileTimeToLocalTime $p.DateCreated
		$dateLastConnected = Convert-RegistryBinaryFileTimeToLocalTime $p.DateLastConnected
	}

	$isTarget = $false
	if ($profileName -match $Match) {
		$isTarget = $true
	}

	[pscustomobject]@{
		Guid              = $k.PSChildName
		ProfileName        = $profileName
		Description        = $description
		Category           = if ($p) { $p.Category } else { $null }
		DateCreated        = $dateCreated
		DateLastConnected  = $dateLastConnected
		IsTarget           = $isTarget
		RegistryPath       = $k.PSPath
	}
}

$targets = @($profiles | Where-Object { $_.IsTarget })

Write-Host "Registry: $ProfilesKey"
Write-Host "Match regex: $Match"

if ($targets.Count -eq 0) {
	Write-Host 'No matching profiles found.'
	exit 0
}

$targets |
	Select-Object Guid, ProfileName, Description, Category, DateCreated, DateLastConnected |
	Format-Table -AutoSize

if (-not $Force) {
	$confirm = Read-Host "Delete these $($targets.Count) profile key(s)? (y/N)"
	if ($confirm.Trim().ToLowerInvariant() -ne 'y') {
		Write-Host 'Cancelled.'
		exit 0
	}
}

$deleted = 0
$failed = 0

foreach ($t in $targets) {
	try {
		if ($PSCmdlet.ShouldProcess($t.Guid, "Remove registry key: $($t.RegistryPath)")) {
			Remove-Item -LiteralPath $t.RegistryPath -Recurse -Force -ErrorAction Stop
			$deleted += 1
			Write-Host "Removed: $($t.Guid)  $($t.ProfileName)"
		}
	} catch {
		$failed += 1
		Write-Warning "Failed to remove $($t.Guid): $($_.Exception.Message)"
	}
}

Write-Host "Done. Deleted=$deleted Failed=$failed"
