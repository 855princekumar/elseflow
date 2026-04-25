from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from elsaflow.decision import build_decision_report
from elsaflow.execution import simulate_execution
from elsaflow.models import OsintSignal, ResearchReport, SessionState
from elsaflow.settlement import apply_execution_to_session, evaluate_transfer


REQUIRED_BACKTEST_COLUMNS = {
    "timestamp",
    "category",
    "market_topic",
    "sentiment_score",
    "relevance_score",
    "market_move_pct",
}


def load_backtest_csv(csv_path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    missing = REQUIRED_BACKTEST_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
    return frame


def build_research_from_row(row: pd.Series) -> ResearchReport:
    sentiment = float(row["sentiment_score"])
    relevance = float(row["relevance_score"])
    topic = str(row["market_topic"])
    category = str(row["category"])
    signals = [
        OsintSignal(
            source="backtest.primary",
            title=f"{topic} base signal",
            summary=str(row.get("note", "Historical OSINT replay signal")),
            url="https://example.com/backtest/1",
            sentiment_score=sentiment,
            relevance_score=relevance,
        ),
        OsintSignal(
            source="backtest.confirmation",
            title=f"{topic} confirmation signal",
            summary="Secondary confirming signal used for replay.",
            url="https://example.com/backtest/2",
            sentiment_score=max(-1.0, min(1.0, sentiment * 0.85)),
            relevance_score=max(0.0, min(1.0, relevance * 0.95)),
        ),
        OsintSignal(
            source="backtest.noise-filter",
            title=f"{topic} uncertainty filter",
            summary="Noise-adjusted replay feature.",
            url="https://example.com/backtest/3",
            sentiment_score=max(-1.0, min(1.0, sentiment * 0.65)),
            relevance_score=max(0.0, min(1.0, relevance * 0.9)),
        ),
    ]
    summary = f"Replay row for {topic}: sentiment {sentiment:.2f}, relevance {relevance:.2f}."
    edges = []
    if sentiment > 0.25:
        edges.append("Historical OSINT leaned bullish")
    elif sentiment < -0.05:
        edges.append("Historical OSINT leaned bearish")
    else:
        edges.append("Historical OSINT was mixed")
    if relevance >= 0.75:
        edges.append("Signal quality was high")
    return ResearchReport(
        market_topic=topic,
        category=category,
        summary=summary,
        signals=signals,
        sentiment_score=sentiment,
        confidence_score=relevance,
        discovered_edges=edges,
        created_at=str(row["timestamp"]),
    )


def _apply_market_move(execution, market_move_pct: float):
    execution = deepcopy(execution)
    if execution.status == "SKIPPED" or execution.amount_usd <= 0:
        execution.pnl_usd = 0.0
        return execution

    directional_move = market_move_pct if execution.side == "BUY_YES" else -market_move_pct
    execution.exit_price = round(max(0.01, execution.entry_price * (1 + directional_move)), 4)
    execution.pnl_usd = round(execution.amount_usd * directional_move, 2)
    return execution


def _compute_max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_drawdown = 0.0
    for point in equity_curve:
        peak = max(peak, point)
        if peak > 0:
            drawdown = (peak - point) / peak
            max_drawdown = max(max_drawdown, drawdown)
    return round(max_drawdown * 100, 2)


def validate_backtest_records(records: list[dict], bootstrap_capital_usd: float) -> list[str]:
    issues: list[str] = []
    for record in records:
        if record["available_capital_usd"] < 0:
            issues.append(f"Capital went negative on {record['timestamp']}")
        if record["trade_amount_usd"] < 0:
            issues.append(f"Trade amount was negative on {record['timestamp']}")
        if record["transfer_amount_usd"] < 0:
            issues.append(f"Transfer amount was negative on {record['timestamp']}")
        if record["decision_action"] == "SKIP" and abs(record["pnl_usd"]) > 0:
            issues.append(f"Skip decision still produced PnL on {record['timestamp']}")
        if record["reserved_profit_usd"] < 0:
            issues.append(f"Reserved profit became negative on {record['timestamp']}")
        hard_floor = bootstrap_capital_usd * 0.1
        if record["available_capital_usd"] < 0 and record["available_capital_usd"] < hard_floor:
            issues.append(f"Capital breached hard floor on {record['timestamp']}")
    return issues


def run_backtest(settings, base_session: SessionState, dataset: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    session = deepcopy(base_session)
    session.available_capital_usd = session.bootstrap_principal_usd
    session.recovered_principal_usd = 0.0
    session.reserved_profit_usd = 0.0
    session.cumulative_profit_usd = 0.0
    session.realized_pnl_usd = 0.0

    records: list[dict] = []
    equity_curve = [session.available_capital_usd]

    for _, row in dataset.iterrows():
        research = build_research_from_row(row)
        decision = build_decision_report(
            research,
            settings.transfer_policy,
            session.available_capital_usd,
            active_models=session.selected_models,
            openrouter_api_key=settings.model_endpoints.get("openrouter", ""),
        )
        execution = simulate_execution(decision, market_id=research.market_topic, execution_mode="backtest")
        execution = _apply_market_move(execution, float(row["market_move_pct"]))
        session = apply_execution_to_session(session, execution.pnl_usd)
        transfer = evaluate_transfer(session, settings.transfer_policy, settings.wallet.settlement_asset)
        equity_curve.append(session.available_capital_usd + session.reserved_profit_usd)

        expected_direction = "BUY_YES" if float(row["market_move_pct"]) > 0 else "BUY_NO" if float(row["market_move_pct"]) < 0 else "SKIP"
        direction_match = decision.action == expected_direction or (expected_direction == "SKIP" and decision.action == "SKIP")
        records.append(
            {
                "timestamp": row["timestamp"],
                "category": research.category,
                "market_topic": research.market_topic,
                "sentiment_score": research.sentiment_score,
                "relevance_score": research.confidence_score,
                "decision_action": decision.action,
                "expected_direction": expected_direction,
                "direction_match": direction_match,
                "decision_confidence_pct": round(decision.confidence_score, 2),
                "trade_amount_usd": decision.amount_usd,
                "market_move_pct": round(float(row["market_move_pct"]) * 100, 2),
                "pnl_usd": execution.pnl_usd,
                "available_capital_usd": session.available_capital_usd,
                "reserved_profit_usd": session.reserved_profit_usd,
                "recovered_principal_usd": session.recovered_principal_usd,
                "transfer_amount_usd": transfer.amount_usd if transfer else 0.0,
                "transfer_reason": transfer.reason if transfer else "",
                "notes": row.get("note", ""),
            }
        )

    results = pd.DataFrame(records)
    total_trades = int((results["trade_amount_usd"] > 0).sum()) if not results.empty else 0
    wins = int((results["pnl_usd"] > 0).sum()) if not results.empty else 0
    validation_issues = validate_backtest_records(records, session.bootstrap_principal_usd)

    summary = {
        "rows": int(len(results)),
        "total_trades": total_trades,
        "skipped_trades": int((results["decision_action"] == "SKIP").sum()) if not results.empty else 0,
        "win_rate_pct": round((wins / total_trades) * 100, 2) if total_trades else 0.0,
        "directional_accuracy_pct": round(results["direction_match"].mean() * 100, 2) if not results.empty else 0.0,
        "total_pnl_usd": round(results["pnl_usd"].sum(), 2) if not results.empty else 0.0,
        "ending_capital_usd": round(session.available_capital_usd, 2),
        "reserved_profit_usd": round(session.reserved_profit_usd, 2),
        "recovered_principal_usd": round(session.recovered_principal_usd, 2),
        "max_drawdown_pct": _compute_max_drawdown(equity_curve),
        "validation_issues": validation_issues,
        "validation_passed": not validation_issues,
    }
    return results, summary
