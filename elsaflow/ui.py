from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import time

import pandas as pd
import plotly.express as px
import streamlit as st

from elsaflow.approval_queue import approve_trade_intent
from elsaflow.agent import ElsaFlowAgent
from elsaflow.audit import record_audit_event
from elsaflow.backtest import REQUIRED_BACKTEST_COLUMNS, load_backtest_csv, run_backtest
from elsaflow.config import load_settings
from elsaflow.database import Database
from elsaflow.models import SessionState, utc_now
from elsaflow.openrouter_client import normalize_openrouter_model
from elsaflow.profile_store import load_profile, save_profile
from elsaflow.source_catalog import SHADOWBROKER_SOURCE_CATALOG
from elsaflow.wallet_signer import build_signer
from elsaflow.x402_client import X402ClientWrapper

EXPORT_CANDIDATES = [
    Path(r"C:\Users\pk-linux\Downloads\2026-04-18T11-28_export.csv"),
    Path(r"C:\Users\pk-linux\Downloads\1-2026-04-18T11-28_export.csv"),
    Path(r"C:\Users\pk-linux\Downloads\2-2026-04-18T11-28_export.csv"),
    Path(r"C:\Users\pk-linux\Downloads\4-2026-04-18T11-29_export.csv"),
    Path(r"C:\Users\pk-linux\Downloads\5-2026-04-18T11-29_export.csv"),
]


def _bootstrap_state() -> tuple[ElsaFlowAgent, Database]:
    settings = load_settings()
    db = Database(settings.database_path)
    agent = ElsaFlowAgent(settings, db)
    return agent, db


def _ensure_session() -> SessionState:
    if "elsaflow_session" not in st.session_state:
        st.session_state.elsaflow_session = SessionState()
    return st.session_state.elsaflow_session


def _ensure_autonomous_controller() -> dict:
    if "autonomous_controller" not in st.session_state:
        st.session_state.autonomous_controller = {
            "active": False,
            "paused": False,
            "stop_requested": False,
            "successful_trades": 0,
            "analysis_attempts": 0,
            "history": [],
            "next_topic_index": 0,
        }
    return st.session_state.autonomous_controller


def _legacy_profile_path(settings) -> Path:
    return settings.database_path.parent / "runtime_profile.json"


def _short_wallet(address: str) -> str:
    if not address or len(address) < 12:
        return address
    return f"{address[:6]}...{address[-4:]}"


def _source_label(source: str) -> str:
    return {
        "gdelt": "Verified public feed: GDELT",
        "usgs": "Verified public feed: USGS",
        "celestrak": "Verified public feed: CelesTrak",
        "satnogs": "Verified public feed: SatNOGS",
        "shadowbroker": "ShadowBroker connector",
        "no_live_match": "No live ShadowBroker-compatible match",
    }.get(source, f"Derived source: {source}")


def _parse_model_input(model_text: str) -> list[str]:
    raw_items = [item.strip() for item in model_text.split(",") if item.strip()]
    if not raw_items:
        return ["nvidia/nemotron-3-super-120b-a12b:free"]
    normalized = [normalize_openrouter_model(item) for item in raw_items]
    return list(dict.fromkeys(normalized))


def _latest_status(logs: pd.DataFrame) -> tuple[str, float]:
    if logs.empty:
        return "Idle", 0.0
    latest = str(logs.iloc[0]["message"])
    lowered = latest.lower()
    if "searching osint" in lowered:
        return "Searching sources", 0.2
    if "collected" in lowered or "research report generated" in lowered:
        return "Collecting evidence", 0.4
    if "model lane" in lowered or "sending synthesized evidence" in lowered:
        return "Calling OpenRouter", 0.65
    if "decision computed" in lowered:
        return "Decision ready", 0.8
    if "execution status" in lowered:
        return "Executing paper trade", 0.92
    if "autonomous run satisfied" in lowered or "completed" in lowered:
        return "Completed", 1.0
    return latest, 0.5


def _render_status_strip(logs: pd.DataFrame) -> None:
    status_text, progress_value = _latest_status(logs)
    st.markdown(
        """
        <style>
        .sticky-status {
            position: sticky;
            top: 0.25rem;
            z-index: 999;
            background: rgba(17, 24, 39, 0.96);
            border: 1px solid rgba(148, 163, 184, 0.25);
            border-radius: 12px;
            padding: 0.75rem 1rem;
            margin-bottom: 1rem;
            backdrop-filter: blur(8px);
        }
        .sticky-status .label {
            color: #cbd5e1;
            font-size: 0.82rem;
            margin-bottom: 0.35rem;
        }
        .sticky-status .value {
            color: #f8fafc;
            font-size: 1rem;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="sticky-status"><div class="label">Live Agent Status</div><div class="value">{status_text}</div></div>',
        unsafe_allow_html=True,
    )
    st.progress(progress_value)


def _render_terminal(logs: pd.DataFrame) -> None:
    if logs.empty:
        st.info("No agent activity yet.")
        return
    lines = [
        f"[{row.created_at}] {row.level:<7} {row.message}"
        for row in logs.sort_values("created_at").itertuples(index=False)
    ]
    st.code("\n".join(lines[-120:]), language="text")


def _decode_payload_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "payload_json" not in frame.columns:
        return pd.DataFrame()
    decoded = frame.copy()
    decoded["payload_json"] = decoded["payload_json"].apply(json.loads)
    return pd.json_normalize(decoded["payload_json"])


def _transaction_ledger(execution_rows: pd.DataFrame, session: SessionState) -> pd.DataFrame:
    if execution_rows.empty:
        return pd.DataFrame()
    ledger = execution_rows.copy()
    ledger["payload_json"] = ledger["payload_json"].apply(json.loads)
    expanded = pd.json_normalize(ledger["payload_json"])
    if expanded.empty:
        return pd.DataFrame()
    expanded["from_wallet"] = session.agent_wallet_address
    expanded["to_market"] = expanded["market_id"].fillna("")
    expanded["settlement_wallet"] = session.user_wallet_address
    expanded["paper_tx_stage"] = expanded["status"].map(
        {
            "FILLED": "Order simulated and settled in paper ledger",
            "SKIPPED": "No order sent because decision was skipped",
        }
    ).fillna("Pending")
    keep = [
        "created_at",
        "order_id",
        "side",
        "amount_usd",
        "entry_price",
        "exit_price",
        "pnl_usd",
        "tx_hash",
        "from_wallet",
        "to_market",
        "settlement_wallet",
        "paper_tx_stage",
    ]
    return expanded[keep].sort_values("created_at", ascending=False)


def _process_autonomous_step(agent: ElsaFlowAgent, db: Database, session: SessionState, settings) -> None:
    controller = _ensure_autonomous_controller()
    if not controller["active"] or controller["paused"] or controller["stop_requested"]:
        session.is_running = False
        return
    if session.available_capital_usd <= 0:
        controller["active"] = False
        session.is_running = False
        db.log(session.session_id, "WARNING", "Autonomous controller stopped: capital exhausted", utc_now())
        return
    if controller["successful_trades"] >= session.max_autonomous_trades:
        controller["active"] = False
        session.is_running = False
        db.log(session.session_id, "INFO", f"Autonomous controller reached max successful trades: {session.max_autonomous_trades}", utc_now())
        return
    if controller["analysis_attempts"] >= session.max_analysis_attempts and controller["successful_trades"] >= session.min_successful_autonomous_trades:
        controller["active"] = False
        session.is_running = False
        db.log(session.session_id, "INFO", "Autonomous controller stopped at analysis cap after satisfying minimum successful trades", utc_now())
        return
    if controller["analysis_attempts"] >= session.max_analysis_attempts:
        controller["active"] = False
        session.is_running = False
        db.log(session.session_id, "WARNING", "Autonomous controller hit analysis cap before reaching minimum successful trades", utc_now())
        return

    session.is_running = True
    controller["analysis_attempts"] += 1
    if session.autonomous_mode:
        session.market_topic = agent.choose_topic(session.selected_category, session.user_intent, controller["next_topic_index"])
        controller["next_topic_index"] += 1
    session.last_updated_at = utc_now()
    db.upsert_session(session)
    result = agent.run_cycle(session, openrouter_api_key=settings.model_endpoints.get("openrouter", ""))
    st.session_state.last_results = result
    controller["history"].append(result)
    session.available_capital_usd = result["session"].available_capital_usd
    session.recovered_principal_usd = result["session"].recovered_principal_usd
    session.reserved_profit_usd = result["session"].reserved_profit_usd
    session.cumulative_profit_usd = result["session"].cumulative_profit_usd
    session.realized_pnl_usd = result["session"].realized_pnl_usd
    session.last_updated_at = result["session"].last_updated_at
    if result["execution"].status != "SKIPPED":
        controller["successful_trades"] += 1
    if controller["successful_trades"] >= session.max_autonomous_trades:
        controller["active"] = False
        session.is_running = False
    time.sleep(0.15)
    st.rerun()


def _export_summary_table(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for path in paths:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path)
            rows.append(
                {
                    "File": path.name,
                    "Rows": len(frame),
                    "Columns": ", ".join(frame.columns[:6]),
                    "Filled trades": int(frame["status"].eq("FILLED").sum()) if "status" in frame.columns else int(frame["Action"].ne("SKIP").sum()) if "Action" in frame.columns else 0,
                    "Skipped trades": int(frame["status"].eq("SKIPPED").sum()) if "status" in frame.columns else int(frame["Action"].eq("SKIP").sum()) if "Action" in frame.columns else 0,
                }
            )
        except Exception:
            continue
    return pd.DataFrame(rows)


def _export_findings(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        name = path.name
        if "Why" in frame.columns:
            rate_limited = frame["Why"].astype(str).str.contains("429 Client Error", case=False, na=False).sum()
            if rate_limited:
                findings.append(f"{name}: {rate_limited} model lanes hit OpenRouter 429 rate limits and fell back to heuristics.")
        if "Source" in frame.columns:
            fallback_count = frame["Source"].astype(str).str.contains("fallback", case=False, na=False).sum()
            if fallback_count:
                findings.append(f"{name}: {fallback_count} displayed sources came from fallback data instead of stronger live connectors.")
            no_match_count = frame["Source"].astype(str).str.contains("no live shadowbroker-compatible match", case=False, na=False).sum()
            if no_match_count:
                findings.append(f"{name}: {no_match_count} rows had no live ShadowBroker-compatible source match for the requested topic.")
        if "pnl_usd" in frame.columns and frame["pnl_usd"].abs().sum() == 0:
            findings.append(f"{name}: all paper-trade PnL values were zero, so the execution simulator did not generate meaningful price movement in that export.")
        if "PnL USD" in frame.columns and frame["PnL USD"].abs().sum() == 0:
            findings.append(f"{name}: autonomous summary shows zero realized paper PnL across all captured cycles.")
    return findings


def _natural_language_summary(research, decision, execution, transfer, session: SessionState) -> str:
    if decision.action == "BUY_YES":
        recommendation = "take a bullish trade"
    elif decision.action == "BUY_NO":
        recommendation = "take a bearish trade"
    else:
        recommendation = "skip the trade for now"

    transfer_line = (
        f"A transfer event of ${transfer.amount_usd:.2f} to your wallet in {transfer.asset} was prepared because {transfer.reason.lower()}."
        if transfer
        else "No transfer back to your wallet was triggered in this cycle."
    )

    return (
        f"Based on {len(research.signals)} collected OSINT signals for {research.market_topic or research.category}, "
        f"ElsaFlow recommends that the agent {recommendation}. "
        f"The signal mix came in at sentiment {research.sentiment_score:.2f} and confidence {decision.confidence_score:.1f}%, "
        f"so the proposed trade size is ${decision.amount_usd:.2f}. "
        f"The latest execution result was {execution.status.lower()} with PnL of ${execution.pnl_usd:.2f}. "
        f"{transfer_line} The agent wallet currently holds ${session.available_capital_usd:.2f} of active strategy capital."
    )


def _autonomous_summary(history: list[dict], session: SessionState) -> str:
    executed = sum(1 for item in history if item["execution"].status != "SKIPPED")
    total_pnl = sum(item["execution"].pnl_usd for item in history)
    transfers = sum(1 for item in history if item["transfer"] is not None)
    min_target = max(1, min(session.min_successful_autonomous_trades, session.max_autonomous_trades))
    return (
        f"Autonomous mode completed {len(history)} cycles with {executed} executed trades. "
        f"Minimum successful trade target was {min_target} and maximum successful trade cap was {session.max_autonomous_trades}. "
        f"Total simulated PnL was ${total_pnl:.2f}, and {transfers} transfer events were prepared. "
        f"Agent strategy capital is now ${session.available_capital_usd:.2f}."
    )


def _model_mode_label(vote) -> str:
    rationale = vote.rationale.lower()
    if "openrouter live call succeeded" in rationale:
        return "Live"
    if "fallback heuristic" in rationale:
        return "Heuristic"
    return "Unknown"


def _votes_table(decision) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Model": vote.model_name,
                "Mode": _model_mode_label(vote),
                "Provider Model": vote.provider_model or vote.model_name,
                "Decision": vote.decision,
                "Confidence %": round(vote.confidence * 100, 1),
                "Why": vote.rationale,
            }
            for vote in decision.votes
        ]
    )


def _sources_table(research) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Source": _source_label(signal.source),
                "Title": signal.title,
                "Summary": signal.summary,
                "URL": signal.url,
                "Sentiment": round(signal.sentiment_score, 2),
                "Relevance": round(signal.relevance_score, 2),
            }
            for signal in research.signals
        ]
    )


def run_app() -> None:
    st.set_page_config(page_title="ElsaFlow", page_icon=":chart_with_upwards_trend:", layout="wide")
    agent, db = _bootstrap_state()
    session = _ensure_session()
    controller = _ensure_autonomous_controller()
    settings = agent.settings
    profile = load_profile(db, _legacy_profile_path(settings))
    current_logs = db.read_table("logs")
    session_logs = current_logs[current_logs["session_id"] == session.session_id].copy() if not current_logs.empty else pd.DataFrame()

    st.title("ElsaFlow")
    st.caption("OSINT-grounded research-to-trade agent with paper execution, wallet policy controls, and transfer simulation.")
    st.warning(
        "This build is for research, simulation, and controlled operator workflows. "
        "It does not promise profit and should not be wired to unattended live capital without audited integrations."
    )
    _render_status_strip(session_logs)

    with st.sidebar:
        st.header("Wallets & Policy")
        session.user_wallet_address = st.text_input(
            "User wallet address",
            value=session.user_wallet_address or profile.get("user_wallet_address", ""),
            help="Your personal receive wallet. ElsaFlow prepares return transfers to this address when profit or capital-recovery rules trigger.",
        )
        session.agent_wallet_address = st.text_input(
            "Agent wallet address",
            value=session.agent_wallet_address or profile.get("agent_wallet_address", ""),
            help="The dedicated agent wallet identity. In this build it is for paper-mode accounting and future signing integration, not live custody.",
        )
        settings.wallet.user_wallet_address = session.user_wallet_address
        settings.wallet.agent_wallet_address = session.agent_wallet_address
        settlement_assets = ["USDC", "USDT", "ETH", "POL"]
        saved_asset = profile.get("settlement_asset", "USDC")
        settings.wallet.settlement_asset = st.selectbox(
            "Settlement asset",
            settlement_assets,
            index=settlement_assets.index(saved_asset) if saved_asset in settlement_assets else 0,
            help="Which asset ElsaFlow should pretend to settle transfers in when it prepares return events.",
        )

        st.subheader("Signer Wallet")
        session.signer_config.signer_type = st.selectbox(
            "Signer type",
            ["dry-run", "local-key-ref"],
            index=0 if session.signer_config.signer_type == "dry-run" else 1,
            help="dry-run keeps signing simulated. local-key-ref uses a stored key reference string and prepares deterministic signatures for live-ready intents.",
        )
        session.signer_config.wallet_address = st.text_input(
            "Signer wallet address",
            value=session.signer_config.wallet_address or session.agent_wallet_address,
            help="Wallet address associated with the signer interface for live-ready intents.",
        )
        session.signer_config.key_reference = st.text_input(
            "Signer key reference",
            value=session.signer_config.key_reference,
            type="password",
            help="Reference to the signing secret or custody handle. This build stores only the reference string, not a raw private key vault.",
        )
        session.signer_config.enabled = st.checkbox(
            "Enable signer",
            value=session.signer_config.enabled,
            help="Turns on signer readiness checks for live-ready trade intents.",
        )

        st.subheader("Controls")
        session.control_policy.live_trading_enabled = st.checkbox(
            "Enable live-ready mode",
            value=session.control_policy.live_trading_enabled,
            help="Allows manual-live-ready intents to be created. It still does not bypass the approval queue.",
        )
        session.control_policy.require_manual_trade_approval = st.checkbox(
            "Require manual trade approval",
            value=session.control_policy.require_manual_trade_approval,
            help="Every live-ready trade intent must be approved before signing or execution.",
        )
        session.control_policy.kill_switch_enabled = st.checkbox(
            "Kill switch",
            value=session.control_policy.kill_switch_enabled,
            help="Hard operational stop for live-ready intent generation.",
        )
        session.control_policy.max_trade_notional_usd = st.number_input(
            "Max trade notional (USD)",
            min_value=1.0,
            value=float(session.control_policy.max_trade_notional_usd),
            step=1.0,
            help="Hard control limit for any one live-ready intent.",
        )
        session.control_policy.max_daily_notional_usd = st.number_input(
            "Max daily notional (USD)",
            min_value=1.0,
            value=float(session.control_policy.max_daily_notional_usd),
            step=1.0,
            help="Aggregate daily notional guardrail for compliance readiness.",
        )

        st.subheader("Model Router")
        model_default_text = ", ".join(profile.get("selected_models", ["nvidia/nemotron-3-super-120b-a12b:free"]))
        model_text = st.text_input(
            "OpenRouter models",
            value=model_default_text,
            help="Comma-separated model IDs. Example: nvidia/nemotron-3-super-120b-a12b:free",
        )
        session.selected_models = _parse_model_input(model_text)
        st.caption("These model IDs are sent to OpenRouter for real analysis calls. Alias-like names are normalized and duplicates are removed to avoid unnecessary rate-limit failures.")
        if model_text.strip():
            resolved_text = ", ".join(session.selected_models)
            st.caption(f"Resolved models: {resolved_text}")

        key_defaults = profile.get("api_keys", {})
        openrouter_key = st.text_input(
            "OpenRouter API key",
            value=key_defaults.get("openrouter", settings.model_endpoints.get("openrouter", "")),
            type="password",
            help="Single API key used for real OpenRouter analysis requests. If requests hit limits or fail, ElsaFlow falls back to a heuristic lane.",
        )
        settings.model_endpoints = {
            "openrouter": openrouter_key,
        }
        if st.button("Save Runtime Settings", use_container_width=True):
            save_profile(
                db,
                {
                    "user_wallet_address": session.user_wallet_address,
                    "agent_wallet_address": session.agent_wallet_address,
                    "settlement_asset": settings.wallet.settlement_asset,
                    "selected_models": session.selected_models,
                    "api_keys": settings.model_endpoints,
                },
            )
            st.success("Runtime settings saved to SQLite.")

        settings.transfer_policy.bootstrap_amount_usd = st.number_input(
            "Bootstrap capital (USD)", min_value=1.0, value=float(session.bootstrap_principal_usd), step=1.0,
            help="Starting paper capital the autonomous agent can risk and recycle through the strategy.",
        )
        session.bootstrap_principal_usd = settings.transfer_policy.bootstrap_amount_usd
        if session.available_capital_usd <= 0:
            session.available_capital_usd = session.bootstrap_principal_usd

        settings.transfer_policy.profit_transfer_threshold_usd = st.number_input(
            "Profit transfer threshold (USD)", min_value=1.0, value=settings.transfer_policy.profit_transfer_threshold_usd, step=1.0,
            help="When protected profit exceeds this amount, ElsaFlow prepares a transfer event back to your wallet.",
        )
        settings.transfer_policy.max_drawdown_percent = st.slider(
            "Max drawdown floor (%)", min_value=10, max_value=80, value=int(settings.transfer_policy.max_drawdown_percent),
            help="Capital preservation floor. Higher values protect more capital but reduce reinvestment freedom.",
        )
        settings.transfer_policy.min_confidence_percent = st.slider(
            "Minimum model confidence (%)", min_value=40, max_value=95, value=int(settings.transfer_policy.min_confidence_percent),
            help="Trades below this consensus confidence are skipped.",
        )
        settings.transfer_policy.per_trade_risk_percent = st.slider(
            "Risk per trade (%)", min_value=1, max_value=30, value=int(settings.transfer_policy.per_trade_risk_percent),
            help="Percentage of available capital allocated to each paper trade.",
        )
        settings.transfer_policy.require_manual_approval = st.checkbox(
            "Manual approval required for transfers", value=settings.transfer_policy.require_manual_approval,
            help="Keeps transfer events in a pending state instead of auto-finalizing them.",
        )
        session.safe_trade_mode = st.checkbox("Safe trade mode", value=session.safe_trade_mode, help="Leaves execution in the safest paper-only posture and warns instead of acting aggressively.")
        session.autonomous_mode = st.checkbox("Autonomous mode", value=session.autonomous_mode, help="Lets ElsaFlow keep cycling through opportunities automatically instead of requiring one manual run per topic.")
        session.min_successful_autonomous_trades = int(
            st.number_input(
                "Min successful autonomous trades",
                min_value=1,
                max_value=50,
                value=int(session.min_successful_autonomous_trades),
                step=1,
                help="The minimum number of non-skipped paper trades ElsaFlow should try to achieve before the run is considered worthwhile.",
            )
        )
        session.max_autonomous_trades = int(
            st.number_input(
                "Max successful autonomous trades",
                min_value=1,
                max_value=50,
                value=int(session.max_autonomous_trades),
                step=1,
                help="Upper cap on non-skipped paper trades in one autonomous batch.",
            )
        )
        session.max_analysis_attempts = int(
            st.number_input(
                "Max autonomous analysis attempts",
                min_value=1,
                max_value=200,
                value=int(session.max_analysis_attempts),
                step=1,
                help="Safety cap on how many opportunities ElsaFlow will analyze while trying to hit the successful-trade target.",
            )
        )
        st.caption("Autonomous mode keeps scanning for candidates until it reaches the successful-trade target or hits the analysis safety cap. Trading still remains paper-only.")

    top_left, top_mid, top_right = st.columns([1.2, 1.2, 1.6])
    with top_left:
        session.selected_category = st.selectbox(
            "Category", ["Crypto", "Finance", "Prediction Markets", "Elections", "AI", "IoT"], index=0,
            help="Main research domain. This controls the topic pool and source matching behavior.",
        )
        session.market_topic = st.text_input(
            "Market topic",
            value=session.market_topic,
            placeholder="e.g. ETH ETF approval odds",
            help="Specific hypothesis or market the agent should investigate. Leave blank in autonomous mode to let ElsaFlow choose topics.",
        )
    with top_mid:
        session.user_intent = st.text_area(
            "Intent / hypothesis",
            value=session.user_intent,
            placeholder="Describe what the agent should investigate and how cautious it should be.",
            height=120,
            help="Natural-language guidance that shapes topic generation and how the agent frames the research.",
        )
        session.simulation_mode = st.selectbox(
            "Execution mode",
            ["paper", "manual-live-ready"],
            index=0,
            help="Paper keeps every trade simulated. Manual-live-ready keeps the workflow explicit for future adapter work, but still does not send real orders.",
        )
    with top_right:
        st.markdown("### Capital Policy")
        st.write(f"Bootstrap principal: `${session.bootstrap_principal_usd:.2f}`")
        st.write(f"Available capital: `${session.available_capital_usd:.2f}`")
        st.write(f"Recovered principal: `${session.recovered_principal_usd:.2f}`")
        st.write(f"Reserved profit: `${session.reserved_profit_usd:.2f}`")
        st.write(f"Realized PnL: `${session.realized_pnl_usd:.2f}`")
        st.caption("Paper Transaction Ledger")
        execution_snapshot = db.read_table("executions")
        if not execution_snapshot.empty:
            execution_snapshot = execution_snapshot[execution_snapshot["session_id"] == session.session_id]
        ledger_preview = _transaction_ledger(execution_snapshot, session)
        if not ledger_preview.empty:
            st.dataframe(ledger_preview.head(5), use_container_width=True, hide_index=True)
        else:
            st.write("No paper transactions yet.")

    run_col, auto_col, pause_col, stop_col, reset_col = st.columns([1, 1, 1, 1, 1])
    with run_col:
        if st.button("Run Agent Cycle", type="primary", use_container_width=True):
            session.last_updated_at = utc_now()
            db.upsert_session(session)
            results = agent.run_cycle(session, openrouter_api_key=settings.model_endpoints.get("openrouter", ""))
            st.session_state.last_results = results
            controller["history"] = []
            st.success("Agent cycle completed.")
    with auto_col:
        if st.button("Run Autonomous Session", use_container_width=True):
            controller["active"] = True
            controller["paused"] = False
            controller["stop_requested"] = False
            controller["successful_trades"] = 0
            controller["analysis_attempts"] = 0
            controller["history"] = []
            controller["next_topic_index"] = 0
            session.is_running = True
            db.upsert_session(session)
            st.success("Autonomous controller started.")
            st.rerun()
    with pause_col:
        if st.button("Pause Autonomous", use_container_width=True):
            controller["paused"] = True
            controller["active"] = False
            session.is_running = False
            db.upsert_session(session)
            st.info("Autonomous controller paused.")
    with stop_col:
        if st.button("Stop Autonomous", use_container_width=True):
            controller["stop_requested"] = True
            controller["paused"] = False
            controller["active"] = False
            session.is_running = False
            db.upsert_session(session)
            st.warning("Autonomous controller stopped.")
    with reset_col:
        if st.button("Reset Session Capital", use_container_width=True):
            session.available_capital_usd = session.bootstrap_principal_usd
            session.recovered_principal_usd = 0.0
            session.reserved_profit_usd = 0.0
            session.cumulative_profit_usd = 0.0
            session.realized_pnl_usd = 0.0
            session.last_updated_at = utc_now()
            controller["history"] = []
            db.upsert_session(session)
            st.info("Session capital state reset.")

    if controller["active"]:
        if session.simulation_mode != "paper":
            controller["active"] = False
            st.warning("Autonomous session is currently restricted to paper mode.")
        else:
            _process_autonomous_step(agent, db, session, settings)

    last_results = st.session_state.get("last_results")
    st.markdown("## Live Agent Console")
    st.caption("Terminal-style trace of what the agent is doing, what it sends to the API, and how each step resolves.")
    refreshed_logs = db.read_table("logs")
    refreshed_session_logs = refreshed_logs[refreshed_logs["session_id"] == session.session_id].copy() if not refreshed_logs.empty else pd.DataFrame()
    _render_terminal(refreshed_session_logs)

    st.markdown("## x402 Paid Research Test")
    st.caption("Use this to test x402 payment-handshake support against a protected API endpoint.")
    x402_col_a, x402_col_b = st.columns([1.6, 0.8])
    with x402_col_a:
        x402_url = st.text_input(
            "x402 protected resource URL",
            value=st.session_state.get("x402_test_url", ""),
            placeholder="https://your-x402-resource.example/api/research",
        )
        st.session_state.x402_test_url = x402_url
    with x402_col_b:
        if st.button("Run x402 Test", use_container_width=True):
            try:
                signer = build_signer(session.signer_config)
                wrapper = X402ClientWrapper(signer)
                payload, payment = wrapper.get_json(db, session.session_id, x402_url)
                st.session_state.x402_payload = payload
                st.session_state.x402_payment = payment
                record_audit_event(
                    db,
                    session.session_id,
                    "x402_test",
                    "INFO",
                    f"x402 test executed for {x402_url}",
                    {"url": x402_url, "payment_status": getattr(payment, 'status', 'NO_PAYMENT')},
                )
                st.success("x402 test completed.")
            except Exception as exc:
                record_audit_event(db, session.session_id, "x402_test_failed", "ERROR", f"x402 test failed for {x402_url}", {"error": str(exc)})
                st.error(f"x402 test failed: {exc}")
    if st.session_state.get("x402_payment") is not None:
        payment = st.session_state["x402_payment"]
        st.write(f"Payment status: `{payment.status}` on `{payment.network}` amount `{payment.amount}`")
        st.code(payment.settlement_response or "No settlement response captured", language="json")
    if st.session_state.get("x402_payload") is not None:
        st.json(st.session_state["x402_payload"])

    if last_results:
        research = last_results["research"]
        decision = last_results["decision"]
        execution = last_results["execution"]
        transfer = last_results["transfer"]
        sources_df = _sources_table(research)
        votes_df = _votes_table(decision)

        st.markdown("## Showcase Summary")
        st.info(_natural_language_summary(research, decision, execution, transfer, last_results["session"]))

        metric_a, metric_b, metric_c, metric_d = st.columns(4)
        metric_a.metric("Recommendation", decision.action.replace("_", " "))
        metric_b.metric("Confidence", f"{decision.confidence_score:.1f}%")
        metric_c.metric("Trade size", f"${decision.amount_usd:.2f}")
        metric_d.metric("PnL", f"${execution.pnl_usd:.2f}")

        st.markdown("## Verified Data")
        st.dataframe(sources_df, use_container_width=True, hide_index=True)

        st.markdown("## Model Comparison")
        st.dataframe(votes_df, use_container_width=True, hide_index=True)
        st.caption("Live means the lane received a real OpenRouter response. Heuristic means the lane fell back locally because the request failed or no key was configured.")

        with st.expander("Model IO Trace"):
            for vote in decision.votes:
                st.markdown(f"### {vote.model_name}")
                st.write(f"Resolved model: `{vote.provider_model or vote.model_name}`")
                st.write(f"Status: `{vote.provider_status or 'unknown'}`")
                st.write("Request preview:")
                st.code(vote.request_preview or "No request captured", language="json")
                st.write("Response preview:")
                st.code(vote.response_preview or "No response captured", language="json")

        with st.expander("Source Collection Trace"):
            for signal in research.signals:
                st.markdown(f"### {_source_label(signal.source)}")
                st.write(f"Title: {signal.title}")
                st.write(f"Summary: {signal.summary}")
                st.write(f"URL: {signal.url or 'n/a'}")
                st.write(f"Sentiment: {signal.sentiment_score:.2f} | Relevance: {signal.relevance_score:.2f}")

        st.markdown("## Execution Outcome")
        outcome_col, wallet_col = st.columns([1.2, 1.2])
        with outcome_col:
            st.write(f"Status: `{execution.status}`")
            st.write(f"Execution mode: `{execution.execution_mode}`")
            st.write(f"Safe trade mode: `{'ON' if session.safe_trade_mode else 'OFF'}`")
            st.write(f"Trade bias: `{decision.trade_bias}`")
            st.write(f"Transaction hash: `{execution.tx_hash or 'n/a'}`")
        with wallet_col:
            st.write(f"User wallet: `{_short_wallet(session.user_wallet_address)}`")
            st.write(f"Agent wallet: `{_short_wallet(session.agent_wallet_address)}`")
            st.write(f"Agent active capital: `${last_results['session'].available_capital_usd:.2f}`")
            if transfer:
                st.success(f"Prepared transfer: ${transfer.amount_usd:.2f} {transfer.asset} to user wallet")
            else:
                st.write("Prepared transfer: none")

        with st.expander("Raw technical details"):
            raw_left, raw_mid, raw_right = st.columns(3)
            with raw_left:
                st.subheader("Research JSON")
                st.json(asdict(research))
            with raw_mid:
                st.subheader("Decision JSON")
                st.json(asdict(decision))
            with raw_right:
                st.subheader("Execution JSON")
                st.json(asdict(execution))
                if transfer:
                    st.subheader("Transfer JSON")
                    st.json(asdict(transfer))

    autonomous_history = controller["history"]
    if autonomous_history:
        st.markdown("## Autonomous Run")
        st.info(_autonomous_summary(autonomous_history, autonomous_history[-1]["session"]))
        st.caption(
            f"Controller state: active={controller['active']} | paused={controller['paused']} | "
            f"successful_trades={controller['successful_trades']} | analysis_attempts={controller['analysis_attempts']}"
        )
        auto_rows = pd.DataFrame(
            [
                {
                    "Cycle": index + 1,
                    "Topic": item["research"].market_topic,
                    "Action": item["decision"].action,
                    "Confidence %": round(item["decision"].confidence_score, 1),
                    "PnL USD": item["execution"].pnl_usd,
                    "Transfer": item["transfer"].reason if item["transfer"] else "",
                    "Capital USD": item["session"].available_capital_usd,
                }
                for index, item in enumerate(autonomous_history)
            ]
        )
        st.dataframe(auto_rows, use_container_width=True, hide_index=True)

    st.markdown("## Analytics")
    execution_rows = db.read_table("executions")
    if not execution_rows.empty:
        session_execution_rows = execution_rows[execution_rows["session_id"] == session.session_id].copy()
        session_execution_rows["payload_json"] = session_execution_rows["payload_json"].apply(json.loads)
        expanded = pd.json_normalize(session_execution_rows["payload_json"])
        if not expanded.empty and "created_at" in expanded.columns and "pnl_usd" in expanded.columns:
            expanded["created_at"] = pd.to_datetime(expanded["created_at"])
            fig = px.line(expanded.sort_values("created_at"), x="created_at", y="pnl_usd", markers=True, title="PnL By Execution")
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(expanded, use_container_width=True)
        st.markdown("## Paper Transaction Ledger")
        ledger = _transaction_ledger(execution_rows[execution_rows["session_id"] == session.session_id].copy(), session)
        if not ledger.empty:
            st.dataframe(ledger, use_container_width=True, hide_index=True)
        else:
            st.info("No paper transactions available for this session.")
    else:
        st.info("No executions yet. Run a cycle to populate analytics.")

    with st.expander("ShadowBroker OSINT source map"):
        st.caption("Snapshot of source types this build is shaped around for future ShadowBroker integration.")
        st.dataframe(pd.DataFrame(SHADOWBROKER_SOURCE_CATALOG), use_container_width=True)

    st.markdown("## Manual Approval Queue")
    approvals_raw = db.read_table("approvals")
    approvals_session = approvals_raw[approvals_raw["session_id"] == session.session_id].copy() if not approvals_raw.empty else pd.DataFrame()
    approvals_view = _decode_payload_frame(approvals_session)
    if not approvals_view.empty:
        st.dataframe(approvals_view, use_container_width=True, hide_index=True)
        pending = approvals_view[approvals_view["status"] == "PENDING"]
        if not pending.empty:
            selected_approval_id = st.selectbox("Pending approval", pending["approval_id"].tolist())
            approver_name = st.text_input("Approver name", value="operator")
            approval_notes = st.text_input("Approval notes", value="Reviewed in dashboard")
            if st.button("Approve Selected Intent", use_container_width=True):
                approval_payload = pending[pending["approval_id"] == selected_approval_id].iloc[0].to_dict()
                approve_trade_intent(db, session.session_id, approval_payload, approver_name, approval_notes)
                intents_raw = db.read_table("trade_intents")
                intents_session = intents_raw[intents_raw["session_id"] == session.session_id].copy()
                intents_view = _decode_payload_frame(intents_session)
                if not intents_view.empty:
                    target_id = approval_payload["target_id"]
                    intent_row = intents_view[intents_view["intent_id"] == target_id]
                    if not intent_row.empty:
                        intent_payload = intent_row.iloc[0].to_dict()
                        intent_payload["approval_status"] = "APPROVED"
                        intent_payload["approved_at"] = utc_now()
                        intent_payload["approved_by"] = approver_name
                        signer = build_signer(session.signer_config)
                        if signer.can_sign():
                            intent_payload["tx_hash"] = signer.sign_message(f"{intent_payload['market_id']}:{intent_payload['side']}:{intent_payload['amount_usd']}")
                        db.update_payload_status("trade_intents", "intent_id", intent_payload["intent_id"], intent_payload)
                        record_audit_event(
                            db,
                            session.session_id,
                            "trade_intent_approved",
                            "INFO",
                            f"Trade intent {intent_payload['intent_id']} approved by {approver_name}",
                            {"tx_hash": intent_payload.get("tx_hash", ""), "approval_notes": approval_notes},
                        )
                st.success("Trade intent approved.")
                st.rerun()
    else:
        st.info("No approval items yet.")

    st.markdown("## Trade Intents")
    intents_raw = db.read_table("trade_intents")
    intents_session = intents_raw[intents_raw["session_id"] == session.session_id].copy() if not intents_raw.empty else pd.DataFrame()
    intents_view = _decode_payload_frame(intents_session)
    if not intents_view.empty:
        st.dataframe(intents_view, use_container_width=True, hide_index=True)
    else:
        st.info("No live-ready trade intents created yet.")

    st.markdown("## Audit Events")
    audits_raw = db.read_table("audit_events")
    audits_session = audits_raw[audits_raw["session_id"] == session.session_id].copy() if not audits_raw.empty else pd.DataFrame()
    audits_view = _decode_payload_frame(audits_session)
    if not audits_view.empty:
        st.dataframe(audits_view, use_container_width=True, hide_index=True)
    else:
        st.info("No audit events yet.")

    st.markdown("## Export Analysis")
    available_exports = [path for path in EXPORT_CANDIDATES if path.exists()]
    export_summary = _export_summary_table(available_exports)
    if not export_summary.empty:
        st.dataframe(export_summary, use_container_width=True, hide_index=True)
        findings = _export_findings(available_exports)
        if findings:
            st.warning("\n\n".join(findings))
    else:
        st.info("No local export CSVs were found in Downloads.")

    st.markdown("## Backtest & Validation")
    default_backtest_path = Path(__file__).resolve().parent.parent / "data" / "backtest_sample.csv"
    backtest_col, validation_col = st.columns([1.2, 1.8])
    with backtest_col:
        use_sample = st.checkbox("Use bundled sample dataset", value=True)
        uploaded_csv = st.file_uploader("Optional backtest CSV", type=["csv"])
        dataset_error = ""
        if use_sample:
            dataset = load_backtest_csv(default_backtest_path)
        elif uploaded_csv is not None:
            dataset = pd.read_csv(uploaded_csv)
            missing = REQUIRED_BACKTEST_COLUMNS.difference(dataset.columns)
            if missing:
                dataset_error = f"Uploaded CSV is missing: {', '.join(sorted(missing))}"
        else:
            dataset = pd.DataFrame()

        if dataset_error:
            st.error(dataset_error)

        if not dataset.empty and not dataset_error and st.button("Run Backtest", use_container_width=True):
            bt_results, bt_summary = run_backtest(settings, session, dataset)
            st.session_state.backtest_results = bt_results
            st.session_state.backtest_summary = bt_summary
            st.success("Backtest completed.")

        st.caption("Required CSV columns: timestamp, category, market_topic, sentiment_score, relevance_score, market_move_pct")

    with validation_col:
        bt_summary = st.session_state.get("backtest_summary")
        if bt_summary:
            metric_a, metric_b, metric_c, metric_d = st.columns(4)
            metric_a.metric("Rows", bt_summary["rows"])
            metric_b.metric("Trades", bt_summary["total_trades"])
            metric_c.metric("Win rate", f"{bt_summary['win_rate_pct']:.2f}%")
            metric_d.metric("Max DD", f"{bt_summary['max_drawdown_pct']:.2f}%")

            metric_e, metric_f, metric_g, metric_h = st.columns(4)
            metric_e.metric("Directional accuracy", f"{bt_summary['directional_accuracy_pct']:.2f}%")
            metric_f.metric("Total PnL", f"${bt_summary['total_pnl_usd']:.2f}")
            metric_g.metric("Ending capital", f"${bt_summary['ending_capital_usd']:.2f}")
            metric_h.metric("Reserved profit", f"${bt_summary['reserved_profit_usd']:.2f}")

            if bt_summary["validation_passed"]:
                st.success("Validation passed. No replay-rule violations were detected in this run.")
            else:
                st.error("Validation found issues in the replay.")
                st.write(bt_summary["validation_issues"])
        else:
            st.info("Run a backtest to see validation metrics.")

    bt_results = st.session_state.get("backtest_results")
    if bt_results is not None and not bt_results.empty:
        chart_col, replay_col = st.columns([1.2, 1.2])
        with chart_col:
            equity = bt_results.copy()
            equity["timestamp"] = pd.to_datetime(equity["timestamp"])
            equity["equity_usd"] = equity["available_capital_usd"] + equity["reserved_profit_usd"]
            fig = px.line(
                equity.sort_values("timestamp"),
                x="timestamp",
                y="equity_usd",
                markers=True,
                title="Backtest Equity Curve",
            )
            st.plotly_chart(fig, use_container_width=True)
        with replay_col:
            st.caption("Replay the exact decisions row by row to inspect alignment and transfer triggers.")
            st.dataframe(bt_results, use_container_width=True)

    st.markdown("## Logs")
    logs = db.read_table("logs")
    if not logs.empty:
        activity_logs = logs[logs["session_id"] == session.session_id].copy()
        if not activity_logs.empty:
            st.caption("Live-style agent activity stream for the current session")
            st.dataframe(activity_logs[["created_at", "level", "message"]], use_container_width=True, hide_index=True)
        else:
            st.dataframe(logs, use_container_width=True)
    else:
        st.info("No logs yet.")
