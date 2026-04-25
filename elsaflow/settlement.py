from __future__ import annotations

from elsaflow.models import SessionState, TransferPolicy, TransferReport, new_id, utc_now


def apply_execution_to_session(session: SessionState, pnl_usd: float) -> SessionState:
    session.realized_pnl_usd = round(session.realized_pnl_usd + pnl_usd, 2)
    session.cumulative_profit_usd = round(max(0.0, session.cumulative_profit_usd + pnl_usd), 2)
    session.available_capital_usd = round(max(0.0, session.available_capital_usd + pnl_usd), 2)
    session.last_updated_at = utc_now()
    return session


def evaluate_transfer(session: SessionState, policy: TransferPolicy, asset: str) -> TransferReport | None:
    recovered_gap = max(0.0, session.bootstrap_principal_usd - session.recovered_principal_usd)
    excess_over_bootstrap = max(0.0, session.available_capital_usd - session.bootstrap_principal_usd)
    threshold_hit = excess_over_bootstrap >= policy.profit_transfer_threshold_usd

    if policy.capital_recovery_enabled and recovered_gap > 0 and session.cumulative_profit_usd >= recovered_gap:
        amount = round(recovered_gap, 2)
        session.recovered_principal_usd = round(session.recovered_principal_usd + amount, 2)
        session.available_capital_usd = round(max(0.0, session.available_capital_usd - amount), 2)
        session.reserved_profit_usd = round(session.reserved_profit_usd + amount, 2)
        session.last_updated_at = utc_now()
        return TransferReport(
            transfer_id=new_id("transfer"),
            status="PENDING_APPROVAL" if policy.require_manual_approval else "READY",
            reason="Recovered bootstrap principal",
            amount_usd=amount,
            asset=asset,
            destination_wallet=session.user_wallet_address,
            moderator="elsa-x402",
        )

    current_floor = session.bootstrap_principal_usd * (1 - (policy.max_drawdown_percent / 100))
    protected_profit = max(0.0, session.available_capital_usd - current_floor)
    if threshold_hit and protected_profit > 0:
        amount = round(min(excess_over_bootstrap, protected_profit), 2)
        session.available_capital_usd = round(max(0.0, session.available_capital_usd - amount), 2)
        session.reserved_profit_usd = round(session.reserved_profit_usd + amount, 2)
        session.last_updated_at = utc_now()
        return TransferReport(
            transfer_id=new_id("transfer"),
            status="PENDING_APPROVAL" if policy.require_manual_approval else "READY",
            reason="Profit threshold reached",
            amount_usd=amount,
            asset=asset,
            destination_wallet=session.user_wallet_address,
            moderator="elsa-x402",
        )

    return None
