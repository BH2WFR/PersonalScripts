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

`parse_device_removal_veto_event(xml: str) -> DeviceRemovalVetoEvent` decodes
Kernel-PnP event 1000 in the Device Management channel. It returns the timestamp,
channel-local record ID, target `DeviceInstanceId`, numeric `VetoType` and
`VetoName` (empty when absent). The veto name can identify a volume, device,
driver or other source depending on the [Windows veto type](https://learn.microsoft.com/en-us/windows/win32/api/cfg/ne-cfg-pnp_veto_type).
The publisher PID does not identify a blocking process. Invalid records raise
the same exceptions as the event 225 decoder.

Both `device-ejection-history.py` and the Windows collector in `system-event-viewer/`
use these decoders. `DeviceRemovalVetoEvent.veto_type_description` formats the code
with its Windows type name and retains unfamiliar codes. Each tool queries its
own sources and renders the recorded fields.
