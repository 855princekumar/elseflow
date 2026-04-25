from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from elsaflow.agent import ElsaFlowAgent
from elsaflow.config import load_settings
from elsaflow.database import Database
from elsaflow.decision import build_decision_report
from elsaflow.execution_adapters import LiveIntentAdapter, PaperExecutionAdapter
from elsaflow.models import OsintSignal, ResearchReport, SessionState
from elsaflow.openrouter_client import normalize_openrouter_model


class ElsaFlowCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(self.db_path)
        self.settings = load_settings()
        self.settings.database_path = self.db_path

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_openrouter_aliases_normalize_to_real_model(self) -> None:
        self.assertEqual(
            normalize_openrouter_model("chatgpt"),
            "nvidia/nemotron-3-super-120b-a12b:free",
        )
        self.assertEqual(
            normalize_openrouter_model("grok"),
            "nvidia/nemotron-3-super-120b-a12b:free",
        )

    def test_decision_report_uses_trade_size_from_policy(self) -> None:
        research = ResearchReport(
            market_topic="ETH ETF approval odds",
            category="Crypto",
            summary="Test",
            signals=[
                OsintSignal(
                    source="gdelt",
                    title="ETF odds improve",
                    summary="Test",
                    url="https://example.com",
                    sentiment_score=0.7,
                    relevance_score=0.8,
                )
            ],
            sentiment_score=0.7,
            confidence_score=0.8,
            discovered_edges=["Test edge"],
        )
        report = build_decision_report(research, self.settings.transfer_policy, available_capital_usd=20.0)
        self.assertGreaterEqual(report.amount_usd, 0.0)
        self.assertIn(report.action, {"BUY_YES", "BUY_NO", "SKIP"})

    def test_paper_execution_adapter_returns_execution_without_intent(self) -> None:
        research = ResearchReport(
            market_topic="BTC breakout",
            category="Crypto",
            summary="Test",
            signals=[],
            sentiment_score=0.7,
            confidence_score=0.9,
            discovered_edges=["Test edge"],
        )
        decision = build_decision_report(research, self.settings.transfer_policy, 10.0)
        adapter = PaperExecutionAdapter()
        session = SessionState(agent_wallet_address="0xabc", user_wallet_address="0xdef")
        execution, intent = adapter.execute(self.db, session, decision, "BTC breakout")
        self.assertIsNone(intent)
        self.assertIn(execution.status, {"FILLED", "SKIPPED"})

    def test_live_intent_adapter_creates_approval_backed_intent(self) -> None:
        research = ResearchReport(
            market_topic="ETH ETF approval odds",
            category="Crypto",
            summary="Test",
            signals=[],
            sentiment_score=0.7,
            confidence_score=0.9,
            discovered_edges=["Test edge"],
        )
        decision = build_decision_report(research, self.settings.transfer_policy, 10.0)
        adapter = LiveIntentAdapter()
        session = SessionState(agent_wallet_address="0xabc", user_wallet_address="0xdef", simulation_mode="manual-live-ready")
        session.signer_config.wallet_address = "0xabc"
        execution, intent = adapter.execute(self.db, session, decision, "ETH ETF approval odds")
        self.assertIsNotNone(intent)
        self.assertEqual(execution.status, "PENDING_APPROVAL")
        approvals = self.db.read_table("approvals")
        self.assertFalse(approvals.empty)

    def test_agent_cycle_runs_in_paper_mode(self) -> None:
        session = SessionState(
            selected_category="Crypto",
            market_topic="BTC breakout",
            user_wallet_address="0xuser",
            agent_wallet_address="0xagent",
        )
        agent = ElsaFlowAgent(self.settings, self.db)
        result = agent.run_cycle(session, openrouter_api_key="")
        self.assertIn("decision", result)
        self.assertIn("execution", result)
        logs = self.db.read_table("logs")
        self.assertFalse(logs.empty)


if __name__ == "__main__":
    unittest.main()
