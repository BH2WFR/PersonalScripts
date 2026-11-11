# Windows event decoding

[Utility index](../README.md)

Import explicitly from [utils.windows_events](../windows_events.py). This module
uses only the standard library and is safe to import on every supported OS. It
does not query logs, resolve process IDs, request privileges or modify devices.

`parse_device_ejection_event(xml: str) -> DeviceEjectionEvent` validates the
provider `Microsoft-Windows-Kernel-PnP` and event ID `225`, then reads the named
`ProcessId`, `ProcessName` and `DeviceInstance` fields. The result retains the
timezone-aware timestamp, record ID and optional `VetoingDevices`. Missing or
invalid required fields raise `ValueError`; malformed XML raises `ET.ParseError`.

`DeviceEjectionEvent.pid` is the recorded blocking PID, not the publisher's PID.
`executable` can be an NT device path. Neither identifies a currently running
process reliably. Records include non-USB devices; no matching event does not
prove that removal was safe.

Both `device-ejection-history.py` and the Windows collector in
`system-event-viewer/` use this decoder. Native querying and presentation remain
in the consuming tools; the CLI retains its existing private parser/type aliases.
