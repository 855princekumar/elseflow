from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class WalletConfig:
    user_wallet_address: str = ""
    agent_wallet_address: str = ""
    settlement_asset: str = "USDC"


@dataclass
class SignerConfig:
    signer_type: str = "dry-run"
    signer_label: str = "Dry Run Signer"
    wallet_address: str = ""
    key_reference: str = ""
    chain: str = "base"
    enabled: bool = False


@dataclass
class TransferPolicy:
    bootstrap_amount_usd: float = 10.0
    profit_transfer_threshold_usd: float = 5.0
    capital_recovery_enabled: bool = True
    max_drawdown_percent: float = 50.0
    min_confidence_percent: float = 65.0
    per_trade_risk_percent: float = 10.0
    require_manual_approval: bool = True
    rebalance_after_recovery: bool = True


@dataclass
class ControlPolicy:
    live_trading_enabled: bool = False
    require_manual_trade_approval: bool = True
    require_manual_transfer_approval: bool = True
    max_trade_notional_usd: float = 25.0
    max_daily_notional_usd: float = 100.0
    approved_by_default: str = ""
    kill_switch_enabled: bool = False


@dataclass
class ModelVote:
    model_name: str
    decision: str
    confidence: float
    rationale: str
    provider_status: str = ""
    provider_model: str = ""
    request_preview: str = ""
    response_preview: str = ""


@dataclass
class OsintSignal:
    source: str
    title: str
    summary: str
    url: str
    sentiment_score: float
    relevance_score: float
    collected_at: str = field(default_factory=utc_now)


@dataclass
class ResearchReport:
    market_topic: str
    category: str
    summary: str
    signals: list[OsintSignal]
    sentiment_score: float
    confidence_score: float
    discovered_edges: list[str]
    created_at: str = field(default_factory=utc_now)


@dataclass
class DecisionReport:
    action: str
    confidence_score: float
    trade_bias: str
    amount_usd: float
    reasons: list[str]
    votes: list[ModelVote]
    created_at: str = field(default_factory=utc_now)


@dataclass
class ExecutionReport:
    order_id: str
    market_id: str
    status: str
    side: str
    amount_usd: float
    entry_price: float
    exit_price: float
    pnl_usd: float
    tx_hash: str
    execution_mode: str
    approval_status: str = ""
    intent_id: str = ""
    settlement_reference: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class TransferReport:
    transfer_id: str
    status: str
    reason: str
    amount_usd: float
    asset: str
    destination_wallet: str
    moderator: str
    created_at: str = field(default_factory=utc_now)


@dataclass
class TradeIntent:
    intent_id: str
    order_id: str
    market_id: str
    side: str
    amount_usd: float
    execution_mode: str
    signer_wallet_address: str
    approval_status: str
    rationale: str
    created_at: str = field(default_factory=utc_now)
    approved_at: str = ""
    approved_by: str = ""
    tx_hash: str = ""


@dataclass
class ApprovalItem:
    approval_id: str
    approval_type: str
    target_id: str
    status: str
    summary: str
    created_at: str = field(default_factory=utc_now)
    reviewed_at: str = ""
    reviewed_by: str = ""
    notes: str = ""


@dataclass
class X402PaymentRecord:
    payment_id: str
    resource_url: str
    status: str
    amount: str
    network: str
    pay_to: str
    scheme: str
    response_code: int
    created_at: str = field(default_factory=utc_now)
    settlement_response: str = ""


@dataclass
class AuditEvent:
    event_id: str
    event_type: str
    severity: str
    summary: str
    details_json: str
    created_at: str = field(default_factory=utc_now)


@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: new_id("session"))
    user_wallet_address: str = ""
    agent_wallet_address: str = ""
    selected_category: str = "Crypto"
    market_topic: str = ""
    user_intent: str = ""
    simulation_mode: str = "paper"
    is_running: bool = False
    safe_trade_mode: bool = True
    autonomous_mode: bool = False
    signer_config: SignerConfig = field(default_factory=SignerConfig)
    control_policy: ControlPolicy = field(default_factory=ControlPolicy)
    min_successful_autonomous_trades: int = 1
    max_autonomous_trades: int = 5
    max_analysis_attempts: int = 25
    bootstrap_principal_usd: float = 10.0
    available_capital_usd: float = 10.0
    reserved_profit_usd: float = 0.0
    recovered_principal_usd: float = 0.0
    cumulative_profit_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    selected_models: list[str] = field(default_factory=lambda: ["nvidia/nemotron-3-super-120b-a12b:free"])
    last_updated_at: str = field(default_factory=utc_now)


def to_record(data: Any) -> dict[str, Any]:
    if hasattr(data, "__dataclass_fields__"):
        return asdict(data)
    if isinstance(data, dict):
        return data
    raise TypeError(f"Unsupported record type: {type(data)!r}")
