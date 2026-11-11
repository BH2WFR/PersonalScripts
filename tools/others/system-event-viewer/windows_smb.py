"""SMB/share audit evidence, separate from protocol-unspecified network logons."""

from .models import EventKind, SECURITY_PROVIDER


SMB_PROVIDER = "Microsoft-Windows-SMBServer"
AUDIT_SUCCESS = 0x0020000000000000
AUDIT_FAILURE = 0x0010000000000000


def parse_smb_event(
    source: str, event_id: int, data: dict[str, str], keywords: str, message: str,
) -> tuple[EventKind, str, str] | None:
    """Classify native SMB failures/share checks and type-3 network authentication.

    Share access-check success does not prove that a file operation completed.
    Missing/ambiguous audit keywords leave the check outcome unspecified.
    """
    kind: EventKind
    if source == SECURITY_PROVIDER and event_id in (4624, 4625) and data.get("LogonType") == "3":
        kind = EventKind.NETWORK_AUTH
        label = "Network logon succeeded" if event_id == 4624 else "Network logon failed"
        label += " (type 3; protocol not established by this record)"
    elif source == SECURITY_PROVIDER and event_id in (5140, 5145):
        kind = EventKind.SMB
        try:
            flags = int(keywords, 0) if keywords else 0
        except ValueError:
            flags = 0
        success, failure = bool(flags & AUDIT_SUCCESS), bool(flags & AUDIT_FAILURE)
        if event_id == 5145:
            label = "Shared object access check"
            if failure and not success:
                label += " denied at share level"
            elif success and not failure:
                label += " allowed at share level (not proof of completed file access)"
            else:
                label += "; outcome unavailable"
        else:
            label = "Network share access"
            if failure and not success:
                label += " failed"
            elif success and not failure:
                label += " succeeded"
            else:
                label += "; outcome unavailable"
    elif source == SMB_PROVIDER and event_id == 551:
        kind, label = EventKind.SMB, "SMB session authentication failed"
    else:
        return None
    details = [label]
    for key in ("TargetUserName", "TargetDomainName", "SubjectUserName", "SubjectDomainName", "UserName",
                "ClientName", "ClientAddress", "IpAddress", "IpPort", "WorkstationName", "ShareName",
                "ShareLocalPath", "RelativeTargetName", "AccessMask", "AccessList", "AccessReason",
                "Status", "TranslatedStatus", "SubStatus", "FailureReason", "AuthenticationPackageName", "SPN"):
        if data.get(key):
            details.append(f"{key}={data[key]}")
    if message:
        details.append(" ".join(message.split()))
    user = data.get("TargetUserName") or data.get("SubjectUserName") or data.get("UserName", "")
    domain = data.get("TargetDomainName") or data.get("SubjectDomainName", "")
    if domain and user:
        user = f"{domain}\\{user}"
    identity = data.get("TargetLogonId") or data.get("SubjectLogonId") or data.get("SessionId", "")
    session = "; ".join(part for part in (user, f"session/logon {identity}" if identity else "") if part)
    return kind, "; ".join(details), session
