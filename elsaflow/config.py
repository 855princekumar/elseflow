from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

from elsaflow.models import TransferPolicy, WalletConfig


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = BASE_DIR / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "elsaflow.db"


@dataclass
class AppSettings:
    shadowbroker_base_url: str
    elsa_x402_base_url: str
    database_path: Path
    wallet: WalletConfig
    transfer_policy: TransferPolicy
    model_endpoints: dict[str, str]


def load_settings() -> AppSettings:
    load_dotenv()
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)

    model_endpoints = {
        "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
    }

    return AppSettings(
        shadowbroker_base_url=os.getenv("SHADOWBROKER_BASE_URL", "http://localhost:8080"),
        elsa_x402_base_url=os.getenv("ELSAX402_BASE_URL", "http://localhost:4020"),
        database_path=Path(os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))),
        wallet=WalletConfig(),
        transfer_policy=TransferPolicy(),
        model_endpoints=model_endpoints,
    )
