"""Provider-qualified activity categories and their Windows Event Log selectors.

IDs and labels follow native provider manifests; localized rendered messages and
all original fields remain available in the main Windows decoder's evidence.
"""

from dataclasses import dataclass

from .models import EventKind, SECURITY_PROVIDER


@dataclass(frozen=True)
class ActivitySource:
    """One channel/provider selector with explicit event IDs and neutral labels."""

    log: str
    provider: str
    kind: EventKind
    events: dict[int, str]


ACTIVITY_SOURCES: tuple[ActivitySource, ...] = (
    ActivitySource("System", "Microsoft-Windows-Kernel-Power", EventKind.BATTERY, {
        105: "Power source changed", 521: "Active battery count changed", 524: "Battery trigger met",
    }),
    ActivitySource("System", "Microsoft-Windows-Kernel-General", EventKind.TIME_CHANGE, {
        1: "System time changed", 22: "Time zone bias changed",
    }),
    ActivitySource("System", "Microsoft-Windows-Time-Service", EventKind.TIME_CHANGE, {
        35: "Time service synchronization", 36: "Time service not synchronized",
        37: "Valid time data received", 47: "No valid time response", 50: "Time difference detected",
    }),
    ActivitySource("Security", SECURITY_PROVIDER, EventKind.TIME_CHANGE, {4616: "System time changed (audit)"}),
    ActivitySource("Security", SECURITY_PROVIDER, EventKind.AUTHENTICATION, {
        4625: "Logon failed", 4740: "Account locked out", 4767: "Account unlocked",
    }),
    ActivitySource("System", "Microsoft-Windows-WindowsUpdateClient", EventKind.UPDATE, {
        19: "Update installed", 20: "Update installation failed", 21: "Update requires restart",
        22: "Update restart scheduled", 23: "Update uninstalled", 24: "Update removal failed",
        43: "Update installation started",
    }),
    ActivitySource("System", "Microsoft-Windows-Resource-Exhaustion-Detector", EventKind.RESOURCE, {
        2004: "Low virtual memory diagnosed",
    }),
    ActivitySource("System", "Service Control Manager", EventKind.SERVICE, {
        7000: "Service failed to start", 7001: "Service dependency failed", 7009: "Service connection timed out",
        7011: "Service response timed out", 7023: "Service terminated with error",
        7024: "Service terminated with service-specific error", 7031: "Service terminated unexpectedly",
        7034: "Service terminated unexpectedly", 7036: "Service state changed",
        7040: "Service start type changed", 7045: "Service installed",
    }),
    ActivitySource("System", "disk", EventKind.FILESYSTEM, {
        7: "Disk bad block", 11: "Disk controller error", 15: "Disk not ready",
        51: "Disk paging I/O error", 153: "Disk I/O retried", 157: "Disk surprise removal",
    }),
    ActivitySource("System", "Microsoft-Windows-Ntfs", EventKind.FILESYSTEM, {
        55: "Filesystem corruption", 98: "Volume health report", 140: "Transaction log flush failed",
    }),
    ActivitySource("Microsoft-Windows-Kernel-PnP/Configuration", "Microsoft-Windows-Kernel-PnP",
                   EventKind.DEVICE_CHANGE, {
        400: "Device configured", 410: "Device started", 411: "Device failed to start", 420: "Device deleted",
    }),
    ActivitySource("Microsoft-Windows-NetworkProfile/Operational", "Microsoft-Windows-NetworkProfile",
                   EventKind.NETWORK, {10000: "Network connected", 10001: "Network disconnected"}),
    ActivitySource("Microsoft-Windows-WLAN-AutoConfig/Operational", "Microsoft-Windows-WLAN-AutoConfig",
                   EventKind.NETWORK, {
        8001: "Wi-Fi connected", 8002: "Wi-Fi connection failed", 8003: "Wi-Fi disconnected",
    }),
)


def activity_filters() -> str:
    """Build PowerShell hashtable literals from static, application-owned selectors."""
    return ",\n".join(
        f"    @{{LogName='{source.log}'; ProviderName='{source.provider}'; Id=@({','.join(map(str, source.events))})}}"
        for source in ACTIVITY_SOURCES
    )


def parse_activity(source: str, event_id: int, data: dict[str, str], message: str) -> tuple[EventKind, str, str] | None:
    """Recognize only configured provider/ID pairs; retain useful native fields."""
    for definition in ACTIVITY_SOURCES:
        if source != definition.provider or event_id not in definition.events:
            continue
        parts = [definition.events[event_id]]
        for key in ("TargetUserName", "TargetDomainName", "LogonType", "IpAddress", "Status", "SubStatus",
                    "OldTime", "NewTime", "PreviousTime", "AcOnline", "IsAcOnline", "RemainingCapacity",
                    "FullChargeCapacity", "RemainingPercentage", "ValidBatteryCount", "ActiveBatteryCount",
                    "ErrorBatteryCount", "AbandonedBatteryCount", "DeviceInstanceId",
                    "DeviceInstanceID", "ServiceName", "ImagePath", "updateTitle", "errorCode", "Name", "SSID",
                    "param1", "param2"):
            if data.get(key):
                parts.append(f"{key}={data[key]}")
        if message:
            parts.append(" ".join(message.split()))
        return definition.kind, "; ".join(parts), data.get("TargetUserName", "")
    return None
