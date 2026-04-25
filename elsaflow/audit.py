from __future__ import annotations

from dataclasses import asdict
import json

from elsaflow.models import AuditEvent, new_id


def record_audit_event(db, session_id: str, event_type: str, severity: str, summary: str, details: dict | None = None) -> AuditEvent:
    event = AuditEvent(
        event_id=new_id("audit"),
        event_type=event_type,
        severity=severity,
        summary=summary,
        details_json=json.dumps(details or {}),
    )
    db.insert_payload("audit_events", session_id, asdict(event), key="event_id")
    return event
