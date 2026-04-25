from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

import pandas as pd

from elsaflow.models import SessionState, to_record


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_wallet_address TEXT NOT NULL,
                    agent_wallet_address TEXT NOT NULL,
                    selected_category TEXT NOT NULL,
                    market_topic TEXT NOT NULL,
                    user_intent TEXT NOT NULL,
                    simulation_mode TEXT NOT NULL,
                    is_running INTEGER NOT NULL,
                    bootstrap_principal_usd REAL NOT NULL,
                    available_capital_usd REAL NOT NULL,
                    reserved_profit_usd REAL NOT NULL,
                    recovered_principal_usd REAL NOT NULL,
                    cumulative_profit_usd REAL NOT NULL,
                    realized_pnl_usd REAL NOT NULL,
                    last_updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decision_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS executions (
                    order_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transfers (
                    transfer_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trade_intents (
                    intent_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS x402_payments (
                    payment_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_profiles (
                    profile_key TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def upsert_session(self, session: SessionState) -> None:
        payload = to_record(session)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, user_wallet_address, agent_wallet_address, selected_category,
                    market_topic, user_intent, simulation_mode, is_running,
                    bootstrap_principal_usd, available_capital_usd, reserved_profit_usd,
                    recovered_principal_usd, cumulative_profit_usd, realized_pnl_usd,
                    last_updated_at
                ) VALUES (
                    :session_id, :user_wallet_address, :agent_wallet_address, :selected_category,
                    :market_topic, :user_intent, :simulation_mode, :is_running,
                    :bootstrap_principal_usd, :available_capital_usd, :reserved_profit_usd,
                    :recovered_principal_usd, :cumulative_profit_usd, :realized_pnl_usd,
                    :last_updated_at
                )
                ON CONFLICT(session_id) DO UPDATE SET
                    user_wallet_address=excluded.user_wallet_address,
                    agent_wallet_address=excluded.agent_wallet_address,
                    selected_category=excluded.selected_category,
                    market_topic=excluded.market_topic,
                    user_intent=excluded.user_intent,
                    simulation_mode=excluded.simulation_mode,
                    is_running=excluded.is_running,
                    bootstrap_principal_usd=excluded.bootstrap_principal_usd,
                    available_capital_usd=excluded.available_capital_usd,
                    reserved_profit_usd=excluded.reserved_profit_usd,
                    recovered_principal_usd=excluded.recovered_principal_usd,
                    cumulative_profit_usd=excluded.cumulative_profit_usd,
                    realized_pnl_usd=excluded.realized_pnl_usd,
                    last_updated_at=excluded.last_updated_at
                """,
                {**payload, "is_running": int(payload["is_running"])},
            )

    def insert_payload(self, table: str, session_id: str, payload: dict[str, Any], key: str | None = None) -> None:
        created_at = payload.get("created_at")
        with self.connect() as conn:
            if key:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({key}, session_id, created_at, payload_json) VALUES (?, ?, ?, ?)",
                    (payload[key], session_id, created_at, json.dumps(payload)),
                )
            else:
                conn.execute(
                    f"INSERT INTO {table} (session_id, created_at, payload_json) VALUES (?, ?, ?)",
                    (session_id, created_at, json.dumps(payload)),
                )

    def log(self, session_id: str, level: str, message: str, created_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO logs (session_id, level, message, created_at) VALUES (?, ?, ?, ?)",
                (session_id, level, message, created_at),
            )

    def read_table(self, table: str) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql_query(f"SELECT * FROM {table} ORDER BY ROWID DESC", conn)

    def update_payload_status(self, table: str, key_name: str, key_value: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                f"UPDATE {table} SET payload_json = ?, created_at = ? WHERE {key_name} = ?",
                (json.dumps(payload), payload.get("created_at", ""), key_value),
            )

    def load_app_profile(self, profile_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM app_profiles WHERE profile_key = ?",
                (profile_key,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def save_app_profile(self, profile_key: str, payload: dict[str, Any], updated_at: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO app_profiles (profile_key, updated_at, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_key) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (profile_key, updated_at, json.dumps(payload)),
            )
