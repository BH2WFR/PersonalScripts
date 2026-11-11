"""Pure Windows event decoders shared by GUI and CLI tools; safe to import on any OS."""

from dataclasses import dataclass
import datetime as dt
import xml.etree.ElementTree as ET

DEVICE_EJECTION_PROVIDER = "Microsoft-Windows-Kernel-PnP"
DEVICE_EJECTION_EVENT_ID = 225
XML_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}


@dataclass(frozen=True)
class DeviceEjectionEvent:
    """Historical removal veto; paths and IDs are retained as Windows recorded them.

    Attributes:
        time: Timezone-aware event timestamp.
        record_id: System log record identifier.
        pid: Recorded blocking PID, never the event publisher's PID.
        executable: Recorded ProcessName, possibly an NT device path.
        device: DeviceInstance identifying the removal target.
        affected_devices: Optional VetoingDevices field from newer event versions.
    """

    time: dt.datetime
    record_id: str
    pid: int
    executable: str
    device: str
    affected_devices: str = ""


def parse_device_ejection_event(xml: str) -> DeviceEjectionEvent:
    """Decode one event 225, raising ValueError/ParseError for invalid records."""
    root = ET.fromstring(xml)
    provider = root.find("e:System/e:Provider", XML_NS)
    created = root.find("e:System/e:TimeCreated", XML_NS)
    if (provider is None or provider.get("Name") != DEVICE_EJECTION_PROVIDER
            or root.findtext("e:System/e:EventID", "", XML_NS) != str(DEVICE_EJECTION_EVENT_ID)):
        raise ValueError("Unexpected provider or event ID")
    if created is None:
        raise ValueError("Missing event timestamp")
    timestamp = dt.datetime.fromisoformat(created.get("SystemTime", ""))
    if timestamp.tzinfo is None:
        raise ValueError("Event timestamp has no timezone")
    data = {node.get("Name", ""): node.text or ""
            for node in root.findall("e:EventData/e:Data", XML_NS)}
    for required in ("ProcessId", "ProcessName", "DeviceInstance"):
        if not data.get(required):
            raise ValueError(f"Missing event field: {required}")
    pid = int(data["ProcessId"])
    if pid < 0:
        raise ValueError("Invalid recorded PID")
    return DeviceEjectionEvent(timestamp, root.findtext("e:System/e:EventRecordID", "", XML_NS),
                      pid, data["ProcessName"], data["DeviceInstance"], data.get("VetoingDevices", ""))


