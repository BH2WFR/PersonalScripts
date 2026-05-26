[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
	# Registry root where network profiles are stored.
	[string]$ProfilesKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\NetworkList\Profiles',

	# Regex used to match Android RNDIS / USB tethering related profiles.
	[string]$Match = 'RNDIS|Android|Remote\s+NDIS|USB\s*Tether|Tether|USB\s*Ethernet',

	# Delete without prompting.
	[switch]$Force,

	# Danger: delete ALL GUID-named subkeys (ignores -Match).
	[switch]$AllGuids
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

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
	if ($AllGuids) {
		$isTarget = $true
	} else {
		if (($profileName -match $Match) -or ($description -match $Match)) {
			$isTarget = $true
		}
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
if ($AllGuids) {
	Write-Host "Mode: -AllGuids (DANGEROUS)"
} else {
	Write-Host "Match regex: $Match"
}

if ($targets.Count -eq 0) {
	Write-Host 'No matching profiles found.'
	Write-Host "Tip: run with -Match '<your regex>' or -AllGuids (dangerous)."
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
