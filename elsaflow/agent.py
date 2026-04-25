from __future__ import annotations

from dataclasses import asdict
from copy import deepcopy

from elsaflow.audit import record_audit_event
from elsaflow.config import AppSettings
from elsaflow.database import Database
from elsaflow.decision import build_decision_report
from elsaflow.execution_adapters import LiveIntentAdapter, PaperExecutionAdapter
from elsaflow.logging_utils import SessionLogger
from elsaflow.models import SessionState
from elsaflow.osint import ShadowBrokerClient, build_research_report
from elsaflow.settlement import apply_execution_to_session, evaluate_transfer

AUTO_TOPICS = {
    "Crypto": ["BTC volatility breakout", "ETH ETF approval odds", "SOL ecosystem expansion"],
    "Finance": ["Gold rally continuation", "Fed rate cut probability", "Small-cap squeeze strength"],
    "Prediction Markets": ["Oil spike persistence", "Election upset chances", "Inflation print shock"],
    "Elections": ["Coalition formation odds", "Swing-state momentum", "Turnout surprise probability"],
    "AI": ["Open-source model launch impact", "Chip export tightening", "Inference cost compression"],
    "IoT": ["decentralised IoT hardware adoption", "industrial sensor network growth", "edge device demand acceleration"],
}


class ElsaFlowAgent:
    def __init__(self, settings: AppSettings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.osint_client = ShadowBrokerClient(settings.shadowbroker_base_url)
        self.paper_adapter = PaperExecutionAdapter()
        self.live_adapter = LiveIntentAdapter()

    def run_cycle(self, session: SessionState, openrouter_api_key: str = "") -> dict:
        logger = SessionLogger(self.db, session.session_id)
        logger.info(f"Cycle started for topic: {session.market_topic or session.selected_category}")
        logger.info("Searching OSINT sources")

        signals = self.osint_client.fetch(session.selected_category, session.market_topic)
        logger.info(f"Collected {len(signals)} OSINT signals")
        for signal in signals[:5]:
            logger.info(f"Source captured: {signal.source} | {signal.title}")
        research = build_research_report(session.selected_category, session.market_topic, signals)
        self.db.insert_payload("research_reports", session.session_id, asdict(research))
        logger.info("Research report generated")
        logger.info("Sending synthesized evidence to model comparison lanes")

        decision = build_decision_report(
            research,
            self.settings.transfer_policy,
            session.available_capital_usd,
            active_models=session.selected_models,
            openrouter_api_key=openrouter_api_key,
        )
        self.db.insert_payload("decision_reports", session.session_id, asdict(decision))
        logger.info(f"Decision computed: {decision.action} at {decision.confidence_score:.1f}% confidence")
        for vote in decision.votes:
            logger.info(
                f"Model lane {vote.model_name} resolved to {vote.provider_model or vote.model_name} "
                f"with status {vote.provider_status or 'unknown'} and decision {vote.decision}"
            )

        if session.control_policy.kill_switch_enabled:
            logger.warning("Kill switch enabled: live-ready execution suppressed")
            execution, trade_intent = self.paper_adapter.execute(
                self.db,
                session,
                decision,
                market_id=session.market_topic or session.selected_category,
            )
            execution.approval_status = "BLOCKED_BY_KILL_SWITCH"
        elif session.simulation_mode == "manual-live-ready" and not session.control_policy.live_trading_enabled:
            logger.warning("Live-ready mode requested but live trading control is disabled; staying in paper mode")
            execution, trade_intent = self.paper_adapter.execute(
                self.db,
                session,
                decision,
                market_id=session.market_topic or session.selected_category,
            )
            execution.approval_status = "LIVE_CONTROL_DISABLED"
        elif session.simulation_mode == "manual-live-ready" and decision.amount_usd > session.control_policy.max_trade_notional_usd:
            logger.warning("Live-ready intent blocked by max trade notional control")
            execution, trade_intent = self.paper_adapter.execute(
                self.db,
                session,
                decision,
                market_id=session.market_topic or session.selected_category,
            )
            execution.approval_status = "BLOCKED_BY_NOTIONAL_LIMIT"
        elif session.simulation_mode == "manual-live-ready":
            execution, trade_intent = self.live_adapter.execute(
                self.db,
                session,
                decision,
                market_id=session.market_topic or session.selected_category,
            )
        else:
            execution, trade_intent = self.paper_adapter.execute(
                self.db,
                session,
                decision,
                market_id=session.market_topic or session.selected_category,
            )
        self.db.insert_payload("executions", session.session_id, asdict(execution), key="order_id")
        if session.safe_trade_mode:
            logger.info(f"Safe trade mode ON: {execution.execution_mode} execution remained non-custodial and simulated")
        elif execution.execution_mode == "manual-live-ready":
            logger.warning("Live-ready execution requested; manual approval queue enforced before any future signing or routing")
        else:
            logger.warning("Autonomous aggressive mode requested, but execution stayed in paper mode")
        logger.info(f"Execution status: {execution.status}")
        if trade_intent:
            logger.warning(f"Live trade intent queued for approval: {trade_intent.intent_id}")
            record_audit_event(
                self.db,
                session.session_id,
                "approval_required",
                "WARNING",
                f"Trade intent {trade_intent.intent_id} requires manual approval",
                {"intent_id": trade_intent.intent_id, "market_id": trade_intent.market_id, "amount_usd": trade_intent.amount_usd},
            )

        session = apply_execution_to_session(session, execution.pnl_usd)
        self.db.upsert_session(session)

        transfer = evaluate_transfer(session, self.settings.transfer_policy, self.settings.wallet.settlement_asset)
        if transfer:
            self.db.insert_payload("transfers", session.session_id, asdict(transfer), key="transfer_id")
            logger.info(f"Transfer event created: {transfer.reason} (${transfer.amount_usd:.2f})")
        else:
            logger.info("No transfer generated this cycle")

        self.db.upsert_session(session)
        return {
            "research": research,
            "decision": decision,
            "execution": execution,
            "trade_intent": trade_intent,
            "transfer": transfer,
            "session": session,
        }

    def choose_topic(self, category: str, user_intent: str, completed_cycles: int = 0) -> str:
        pool = AUTO_TOPICS.get(category, [category])
        if user_intent.strip():
            return f"{pool[completed_cycles % len(pool)]} | intent: {user_intent.strip()[:80]}"
        return pool[completed_cycles % len(pool)]

    def run_autonomous_session(
        self,
        session: SessionState,
        openrouter_api_key: str = "",
    ) -> list[dict]:
        history: list[dict] = []
        working_session = deepcopy(session)
        logger = SessionLogger(self.db, working_session.session_id)
        executed_trades = 0
        min_successful_trades = max(1, min(session.min_successful_autonomous_trades, session.max_autonomous_trades))
        max_analysis_cycles = max(session.max_autonomous_trades * 3, session.max_analysis_attempts, min_successful_trades)
        logger.info(
            f"Autonomous run started with min successful trades={min_successful_trades}, "
            f"max successful trades={session.max_autonomous_trades}, analysis cap={max_analysis_cycles}"
        )
        for cycle_index in range(max_analysis_cycles):
            if working_session.available_capital_usd <= 0:
                logger.warning("Autonomous run stopped: capital exhausted")
                break
            if executed_trades >= session.max_autonomous_trades:
                logger.info(f"Autonomous run reached target of {session.max_autonomous_trades} executed trades")
                break
            if not working_session.market_topic.strip():
                working_session.market_topic = self.choose_topic(
                    working_session.selected_category,
                    working_session.user_intent,
                    cycle_index,
                )
            result = self.run_cycle(working_session, openrouter_api_key=openrouter_api_key)
            history.append(result)
            working_session = result["session"]
            if result["decision"].action == "SKIP" or result["execution"].status == "SKIPPED":
                logger.info("Trade skipped, moving to next analysis and trade candidate")
            else:
                executed_trades += 1
                logger.info(f"Executed trade count updated to {executed_trades}/{session.max_autonomous_trades}")
            if session.autonomous_mode:
                working_session.market_topic = self.choose_topic(
                    working_session.selected_category,
                    working_session.user_intent,
                    cycle_index + 1,
                )
        if executed_trades < min_successful_trades:
            logger.warning(
                f"Autonomous run ended below minimum successful trade target: "
                f"{executed_trades}/{min_successful_trades} after {len(history)} analysis cycles"
            )
        else:
            logger.info(
                f"Autonomous run satisfied minimum successful trade target: "
                f"{executed_trades}/{min_successful_trades}"
            )
        return history
