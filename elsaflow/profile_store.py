from __future__ import annotations

from pathlib import Path
import json

from elsaflow.openrouter_client import normalize_openrouter_model


DEFAULT_PROFILE = {
    "user_wallet_address": "0x4B8d19699C449182EcE4E7DcB1256b9c274B190e",
    "agent_wallet_address": "0x69556B01F3793b1EA859a446cfe8c7DdEeBa498F",
    "settlement_asset": "USDC",
    "selected_models": ["nvidia/nemotron-3-super-120b-a12b:free"],
    "api_keys": {
        "openrouter": "",
    },
}


def load_profile(profile_path: Path) -> dict:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if not profile_path.exists():
        save_profile(profile_path, DEFAULT_PROFILE)
        return DEFAULT_PROFILE.copy()
    with profile_path.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    if "api_keys" not in profile:
        profile["api_keys"] = {"openrouter": ""}
    if "openrouter" not in profile["api_keys"]:
        profile["api_keys"]["openrouter"] = ""
    if "selected_models" not in profile or not profile["selected_models"]:
        profile["selected_models"] = ["nvidia/nemotron-3-super-120b-a12b:free"]
    profile["selected_models"] = list(dict.fromkeys(normalize_openrouter_model(item) for item in profile["selected_models"]))
    return profile


def save_profile(profile_path: Path, payload: dict) -> None:
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with profile_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
