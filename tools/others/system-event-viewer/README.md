# System Event Viewer implementation

Run `../system-event-viewer.py`; this directory is a private package loaded as
`personal_system_event_viewer`. The launcher and compiler exclude its individual
modules. `compile-script.py` stages this alias for Nuitka and PyInstaller.

## Module ownership

| Module | Responsibility |
| --- | --- |
| `models.py` | Events, source status, time ranges and platform capabilities |
| `common.py` | Cancellable commands, bounded source collection and SSH messages |
| `windows.py` | Provider-qualified Windows Event Log queries and decoding |
| `windows_activity.py` | Native activity event IDs, query selectors and category mapping |
| `windows_smb.py` | SMB failures, share authorization outcomes and network authentication |
| `macos.py` | Power/session logs and bounded DiagnosticReports scans |
| `macos_activity.py` | Source-qualified unified-log activity patterns and predicates |
| `linux.py` | systemd journal collection and decoding |
| `history.py` | Query dispatch, time bounds, deduplication and CSV/JSON exports |
| `ui.py` | Lazy Qt loading, query worker, table, filters and XML tree |
| `app.py` | Desktop/platform checks and application startup |

The entry owns CLI help. Preserve the `PersonalScripts/PowerEvents` QSettings
identity, the `powerEventsWindow` application property and existing export fields
when refactoring. These retain display preferences and integration compatibility.
`PowerEvent` remains the internal event model name.

Available event filters default on except Application crash, Application
unresponsive, the nine activity categories below and Windows SMB/network
authentication. Saved selections take
precedence. All selects supported categories; None clears them; Reset restores
defaults without changing dates or querying again. Filter columns adapt to window
width. All categories are collected during a query so filtering remains immediate.
F5 triggers Query / Refresh throughout the window; it is ignored while a query
is running and does not repeat when held down.
Combined controls cover Startup / Shutdown, Sleep / Wake (including Modern
Standby entry/exit), Logon / Logoff, Lock / Unlock, all RDP connection/reconnection/disconnection
events, and SSH connection/disconnection. Rows and exports retain their original
event types. When restoring older settings, a merged checkbox is enabled if any
of its supported member types was enabled. Hibernate, Background wake and power
session transitions remain separate.
Filters are ordered by power, sessions/authentication, network/devices/maintenance,
then failures/diagnostics; their ordering is independent of persisted event names.

## Source coverage

- Windows: System power/boot records, Security lock/unlock and interactive
  logon/logoff (types 2/10/11/12), separate type-3 network authentication,
  SMB/share auditing, TerminalServices RDP, OpenSSH server channels,
  Application Error/Hang, WER, bugchecks, WHEA and Diagnostics-Performance.
  Modern Standby 506/507 and power-session transition 566 remain separate from
  traditional sleep/wake. Sleep/DRIPS metrics and native reasons are retained.
- Windows blocked device ejections: System / Microsoft-Windows-Kernel-PnP / 225.
  The shared `utils.windows_events` decoder also serves `device-ejection-history`.
  Details preserve the blocking process path, historical PID, device instance and
  optional vetoing devices. This includes USB and other PnP devices; no matches
  do not prove safe removal. Devices and running processes are never altered.
- macOS: `pmset`, explicit `loginwindow` lock notifications, `last` boot/shutdown,
  current `kern.boottime`, incoming sshd unified logs, user/system
  `Library/Logs/DiagnosticReports` and their `Retired` directories. Text/IPS
  reports distinguish crashes, hangs, panics and other diagnostics. Spin samples
  alone are not hangs. Missing timestamps use explicitly labelled file times.
- Linux: systemd kernel/logind/sleep/shutdown and sshd journal records, coredump
  reports, explicit service watchdog timeouts and kernel/systemd errors. Lock
  history requires explicit logind transitions; arbitrary desktop hangs are not
  detected. Non-systemd logging and file-only SSH logs are not collected.

## Optional activity categories

These nine categories default off on every platform. Coverage is limited to
retained native messages; no extra auditing, daemon, device polling or continuous
resource recording is installed. Native details remain available in each row.

| Category | Windows | Linux | macOS |
| --- | --- | --- | --- |
| Battery / power source | Kernel-Power 105/521/524 source/count/trigger reports | UPower and explicit kernel battery/AC messages | Explicit powerd battery/source messages |
| Time changes | Kernel-General 1/22, Security 4616, Time-Service | systemd clock changes, timesyncd/chronyd/ntpd | timed clock adjustment/synchronization messages |
| Authentication | Security 4625 (excluding type 3)/4740/4767 and OpenSSH failures | SSH failures and PAM authentication failures in sshd/sudo/su/login journal records | SSH failures and explicit authd/opendirectoryd/loginwindow/PAM failures |
| Updates | WindowsUpdateClient installation/removal/restart records | Journal messages from PackageKit, apt/dnf, unattended-upgrade and fwupd | softwareupdated/softwareupdate/installd/osinstallersetupd messages |
| Resource exhaustion | Resource-Exhaustion-Detector 2004 | Kernel OOM kills and systemd-oomd | Explicit memorystatus/jetsam/memory-pressure/swap failures |
| Services | Service Control Manager state/install/start/failure events | Explicit systemd unit start/stop/failure/restart messages | Explicit launchd exits, spawn failures and throttling |
| Disk / filesystem | disk errors/retries/removal; NTFS health/corruption/flush reports | Explicit kernel filesystem/I/O faults and systemd mount failures | Explicit kernel/APFS/HFS/I/O and mount failures |
| Device changes | Kernel-PnP Configuration 400/410/411/420 | Kernel USB enumeration/disconnection | Explicit USB/disk/device messages from kernel/diskarbitrationd/bluetoothd |
| Network connections | NetworkProfile and WLAN connect/disconnect/failure | NetworkManager, networkd, wpa_supplicant and kernel link states | Explicit airportd/wifid/configd/VPN-service link/connection messages |

Device configuration/start/deletion is not proof of a physical insertion/removal.
Battery reports are not a continuous charge history. Update attempts are not
assumed successful. NTFS volume-health records may describe a healthy volume.
Windows type-3 authentication appears in its own optional category; interactive
logon/logoff filtering remains separate. Distribution/version-specific wording,
privacy redaction and absent services can leave gaps. Package-manager log files
and macOS installation-history databases are not collected.

Windows mappings follow provider manifests and Microsoft's
[audit event reference](https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/plan/Appendix-L--Events-to-Monitor).
Linux source selection follows native
[journal fields](https://www.freedesktop.org/software/systemd/man/257/systemd.journal-fields.html).
macOS activity recognition uses source-qualified message patterns, not a stable
cross-version event-ID contract.

## Windows SMB and network authentication

Both filters default off and are disabled on Linux/macOS; Samba and macOS SMB
server logs are not collected by these filters.

- **Network authentication**: Security 4624/4625 with LogonType 3. These identify
  successful/failed network authentication, not necessarily SMB. Success is
  queried separately from desktop sessions so its source limit cannot crowd out
  the interactive query. Other 4625 failures remain under Authentication.
- **SMB / file sharing**: SMBServer/Security 551 for explicit SMB authentication
  failure; Security 5140 for network-share access; Security 5145 for shared-object
  authorization checks. Share names, relative paths, client addresses, accounts,
  session/logon IDs, access masks and native status codes are retained when present.
- Audit Success/Failure keyword bits determine 5140/5145 outcomes. Missing or
  ambiguous bits leave the outcome unknown. A successful 5145 check does not
  prove completed file access; its failure refers to share permissions, not NTFS
  permissions. Type-3 logons and SMB records are separate observations, not merged
  into unique sessions or treated as TCP connection/disconnection events.

5140 requires prior **File Share** auditing; 5145 requires **Detailed File Share**
auditing and can produce many records. They have independent source limits.
The viewer only reads logs: it never changes audit policy or channel settings.
Empty results do not identify whether auditing was enabled, and enabling it later
cannot recover past accesses. These logs describe incoming access to this host.
See Microsoft's [5145 event reference](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-5145)
for the distinction between share-level checks and filesystem permission failures.

Availability depends on retained accessible records and previously enabled
auditing. No auditing, power or logging configuration is changed. SSH means
local server observations, not outgoing clients; unnamed transport closes have
unknown authentication. Separate observations are retained rather than merged
into unique session counts. RDP requires remote-address or RDP-station evidence.

## Bounds and interpretation

Queries use a half-open UTC interval and show local times with offsets. Commands
time out after 90 seconds and cancellation kills and reaps their child process.
The newest 50,000 normalized events are displayed; source truncation is reported.
macOS report reads are capped at 8 MiB per file, 64 MiB total, 5,000 files and
90 seconds. Symlinks, binary dumps, archives and sysdiagnose bundles are excluded.

Shutdown initiation does not prove completed power-off. Unexpected restart and
bugcheck reports use their later report timestamps. Modern Standby entry does
not establish low-power residency; exit can be internal. Events alone do not
establish Wake-on-LAN or a diagnostic cause. Missing records are not proof of
absence. No background recording or usage-duration inference is performed.

Verification: `conda run -n base python -m unittest discover -s test -p test_system_events.py`.
