from __future__ import annotations

from dataclasses import asdict

from elsaflow.models import ApprovalItem, TradeIntent, utc_now


def create_trade_approval(db, session_id: str, intent: TradeIntent) -> ApprovalItem:
    approval = ApprovalItem(
        approval_id=f"approval_{intent.intent_id}",
        approval_type="trade_intent",
        target_id=intent.intent_id,
        status="PENDING",
        summary=f"Approve {intent.side} {intent.market_id} for ${intent.amount_usd:.2f}",
    )
    db.insert_payload("approvals", session_id, asdict(approval), key="approval_id")
    return approval


def approve_trade_intent(db, session_id: str, approval_payload: dict, approver: str, notes: str = "") -> dict:
    approval_payload["status"] = "APPROVED"
    approval_payload["reviewed_at"] = utc_now()
    approval_payload["reviewed_by"] = approver
    approval_payload["notes"] = notes
    db.update_payload_status("approvals", "approval_id", approval_payload["approval_id"], approval_payload)
    return approval_payload
