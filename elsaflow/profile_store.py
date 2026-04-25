from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import json

from elsaflow.database import Database
from elsaflow.openrouter_client import normalize_openrouter_model


DEFAULT_PROFILE = {
    "user_wallet_address": "",
    "agent_wallet_address": "",
    "settlement_asset": "USDC",
    "selected_models": ["nvidia/nemotron-3-super-120b-a12b:free"],
    "api_keys": {
        "openrouter": "",
    },
}
PROFILE_KEY = "runtime_profile"


def _normalize_profile(profile: dict) -> dict:
    if "api_keys" not in profile:
        profile["api_keys"] = {"openrouter": ""}
    if "openrouter" not in profile["api_keys"]:
        profile["api_keys"]["openrouter"] = ""
    if "selected_models" not in profile or not profile["selected_models"]:
        profile["selected_models"] = ["nvidia/nemotron-3-super-120b-a12b:free"]
    profile["selected_models"] = list(dict.fromkeys(normalize_openrouter_model(item) for item in profile["selected_models"]))
    return profile


def load_profile(db: Database, legacy_profile_path: Path | None = None) -> dict:
    profile = db.load_app_profile(PROFILE_KEY)
    if profile is not None:
        return _normalize_profile(profile)

    if legacy_profile_path and legacy_profile_path.exists():
        with legacy_profile_path.open("r", encoding="utf-8") as handle:
            profile = json.load(handle)
        normalized = _normalize_profile(profile)
        save_profile(db, normalized)
        legacy_profile_path.unlink(missing_ok=True)
        return normalized

    return deepcopy(DEFAULT_PROFILE)


def save_profile(db: Database, payload: dict) -> None:
    db.save_app_profile(
        PROFILE_KEY,
        _normalize_profile(payload),
        datetime.now(timezone.utc).isoformat(),
    )
