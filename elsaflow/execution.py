from __future__ import annotations

from hashlib import sha1

from elsaflow.models import DecisionReport, ExecutionReport, new_id


def simulate_execution(decision: DecisionReport, market_id: str, execution_mode: str = "paper") -> ExecutionReport:
    if decision.action == "SKIP":
        return ExecutionReport(
            order_id=new_id("order"),
            market_id=market_id,
            status="SKIPPED",
            side="NONE",
            amount_usd=0.0,
            entry_price=0.0,
            exit_price=0.0,
            pnl_usd=0.0,
            tx_hash="",
            execution_mode=execution_mode,
        )

    entry_price = 0.48 if decision.action == "BUY_YES" else 0.52
    move = max(-0.08, min(0.12, (decision.confidence_score - 60) / 250))
    exit_price = round(entry_price + move, 4)
    pnl_ratio = (exit_price - entry_price) / max(entry_price, 0.01)
    pnl_usd = round(decision.amount_usd * pnl_ratio, 2)
    tx_hash = sha1(f"{market_id}:{decision.action}:{decision.amount_usd}".encode("utf-8")).hexdigest()

    return ExecutionReport(
        order_id=new_id("order"),
        market_id=market_id,
        status="FILLED",
        side=decision.action,
        amount_usd=decision.amount_usd,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl_usd=pnl_usd,
        tx_hash=tx_hash,
        execution_mode=execution_mode,
    )
