from __future__ import annotations

from statistics import mean

from elsaflow.models import DecisionReport, ResearchReport, TransferPolicy
from elsaflow.openrouter_client import request_openrouter_vote


SUPPORTED_MODELS = ["nvidia/nemotron-3-super-120b-a12b:free"]


def build_decision_report(
    research: ResearchReport,
    policy: TransferPolicy,
    available_capital_usd: float,
    active_models: list[str] | None = None,
    openrouter_api_key: str = "",
) -> DecisionReport:
    chosen_models = active_models or SUPPORTED_MODELS
    votes = [request_openrouter_vote(model, research, openrouter_api_key=openrouter_api_key) for model in chosen_models]
    yes_votes = sum(1 for vote in votes if vote.decision == "YES")
    no_votes = sum(1 for vote in votes if vote.decision == "NO")
    consensus_confidence = mean(vote.confidence for vote in votes) * 100

    if consensus_confidence < policy.min_confidence_percent:
        action = "SKIP"
        trade_bias = "flat"
    elif yes_votes > no_votes:
        action = "BUY_YES"
        trade_bias = "bullish"
    elif no_votes > yes_votes:
        action = "BUY_NO"
        trade_bias = "bearish"
    else:
        action = "SKIP"
        trade_bias = "flat"

    amount_usd = round(max(0.0, available_capital_usd * (policy.per_trade_risk_percent / 100)), 2)
    if action == "SKIP":
        amount_usd = 0.0

    reasons = [
        f"Consensus confidence: {consensus_confidence:.1f}%",
        f"Sentiment score: {research.sentiment_score:.2f}",
        f"Trade bias: {trade_bias}",
    ] + research.discovered_edges

    return DecisionReport(
        action=action,
        confidence_score=consensus_confidence,
        trade_bias=trade_bias,
        amount_usd=amount_usd,
        reasons=reasons,
        votes=votes,
    )
