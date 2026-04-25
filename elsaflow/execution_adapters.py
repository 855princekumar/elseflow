from __future__ import annotations

from dataclasses import asdict

from elsaflow.approval_queue import create_trade_approval
from elsaflow.audit import record_audit_event
from elsaflow.execution import simulate_execution
from elsaflow.models import DecisionReport, ExecutionReport, SessionState, TradeIntent, new_id
from elsaflow.wallet_signer import build_signer


class PaperExecutionAdapter:
    def execute(self, db, session: SessionState, decision: DecisionReport, market_id: str) -> tuple[ExecutionReport, TradeIntent | None]:
        execution = simulate_execution(decision, market_id=market_id, execution_mode="paper")
        return execution, None


class LiveIntentAdapter:
    def execute(self, db, session: SessionState, decision: DecisionReport, market_id: str) -> tuple[ExecutionReport, TradeIntent | None]:
        signer = build_signer(session.signer_config)
        intent = TradeIntent(
            intent_id=new_id("intent"),
            order_id=new_id("order"),
            market_id=market_id,
            side=decision.action,
            amount_usd=decision.amount_usd,
            execution_mode="manual-live-ready",
            signer_wallet_address=session.signer_config.wallet_address or session.agent_wallet_address,
            approval_status="PENDING" if session.control_policy.require_manual_trade_approval else "READY",
            rationale=" / ".join(decision.reasons[:3]),
        )
        db.insert_payload("trade_intents", session.session_id, asdict(intent), key="intent_id")
        create_trade_approval(db, session.session_id, intent)
        record_audit_event(
            db,
            session.session_id,
            "trade_intent_created",
            "INFO",
            f"Manual approval required for live intent {intent.intent_id}",
            {
                "market_id": market_id,
                "side": decision.action,
                "amount_usd": decision.amount_usd,
                "signer_type": session.signer_config.signer_type,
                "signer_ready": signer.can_sign(),
            },
        )
        execution = ExecutionReport(
            order_id=intent.order_id,
            market_id=market_id,
            status="PENDING_APPROVAL",
            side=decision.action,
            amount_usd=decision.amount_usd,
            entry_price=0.0,
            exit_price=0.0,
            pnl_usd=0.0,
            tx_hash="",
            execution_mode="manual-live-ready",
            approval_status=intent.approval_status,
            intent_id=intent.intent_id,
            settlement_reference="",
        )
        return execution, intent
