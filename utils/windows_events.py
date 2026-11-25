"""Pure Windows event decoders shared by GUI and CLI tools; safe to import on any OS."""

from dataclasses import dataclass
import datetime as dt
import xml.etree.ElementTree as ET

DEVICE_EJECTION_PROVIDER = "Microsoft-Windows-Kernel-PnP"
DEVICE_EJECTION_EVENT_ID = 225
DEVICE_REMOVAL_VETO_CHANNEL = "Microsoft-Windows-Kernel-PnP/Device Management"
DEVICE_REMOVAL_VETO_EVENT_ID = 1000
XML_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
_VETO_TYPE_NAMES = (
    "Unknown", "Legacy device", "Pending close", "Windows application",
    "Windows service", "Outstanding open handles", "Device", "Driver",
    "Illegal device request", "Insufficient power", "Non-disableable device",
    "Legacy driver", "Insufficient rights", "Already removed",
)


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


@dataclass(frozen=True)
class DeviceRemovalVetoEvent:
    """Device Management veto with its recorded PNP_VETO_TYPE and veto name."""

    time: dt.datetime
    record_id: str
    device: str
    veto_type: int
    veto_name: str

    @property
    def veto_type_description(self) -> str:
        """Return the recorded numeric code with its Windows veto type label."""
        code = self.veto_type
        name = _VETO_TYPE_NAMES[code] if 0 <= code < len(_VETO_TYPE_NAMES) else "Unrecognized"
        return f"{code} ({name})"


def _ejection_fields(
    xml: str, event_id: int, *, channel: str | None = None,
) -> tuple[dt.datetime, str, dict[str, str]]:
    """Validate the event identity and decode the common header and named data."""
    root = ET.fromstring(xml)
    provider = root.find("e:System/e:Provider", XML_NS)
    created = root.find("e:System/e:TimeCreated", XML_NS)
    if (provider is None or provider.get("Name") != DEVICE_EJECTION_PROVIDER
            or root.findtext("e:System/e:EventID", "", XML_NS) != str(event_id)):
        raise ValueError("Unexpected provider or event ID")
    if channel is not None and root.findtext("e:System/e:Channel", "", XML_NS) != channel:
        raise ValueError("Unexpected event channel")
    if created is None:
        raise ValueError("Missing event timestamp")
    timestamp = dt.datetime.fromisoformat(created.get("SystemTime", ""))
    if timestamp.tzinfo is None:
        raise ValueError("Event timestamp has no timezone")
    data = {node.get("Name", ""): node.text or ""
            for node in root.findall("e:EventData/e:Data", XML_NS)}
    return timestamp, root.findtext("e:System/e:EventRecordID", "", XML_NS), data


def parse_device_ejection_event(xml: str) -> DeviceEjectionEvent:
    """Decode one event 225, raising ValueError/ParseError for invalid records."""
    timestamp, record_id, data = _ejection_fields(xml, DEVICE_EJECTION_EVENT_ID)
    for required in ("ProcessId", "ProcessName", "DeviceInstance"):
        if not data.get(required):
            raise ValueError(f"Missing event field: {required}")
    pid = int(data["ProcessId"])
    if pid < 0:
        raise ValueError("Invalid recorded PID")
    return DeviceEjectionEvent(timestamp, record_id, pid, data["ProcessName"],
                               data["DeviceInstance"], data.get("VetoingDevices", ""))


def parse_device_removal_veto_event(xml: str) -> DeviceRemovalVetoEvent:
    """Decode one event 1000, raising ValueError/ParseError for invalid records."""
    timestamp, record_id, data = _ejection_fields(
        xml, DEVICE_REMOVAL_VETO_EVENT_ID, channel=DEVICE_REMOVAL_VETO_CHANNEL)
    if not data.get("DeviceInstanceId"):
        raise ValueError("Missing event field: DeviceInstanceId")
    veto_type = int(data.get("VetoType", ""))
    return DeviceRemovalVetoEvent(timestamp, record_id, data["DeviceInstanceId"],
                                 veto_type, data.get("VetoName", ""))


