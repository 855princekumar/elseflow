from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from elsaflow.backtest import load_backtest_csv, run_backtest
from elsaflow.config import load_settings
from elsaflow.models import SessionState


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ElsaFlow backtest validation.")
    parser.add_argument("--csv", default="data/backtest_sample.csv", help="Path to backtest CSV")
    parser.add_argument("--capital", type=float, default=10.0, help="Bootstrap capital in USD")
    parser.add_argument("--topic", default="Backtest basket", help="Topic label for the backtest session")
    args = parser.parse_args()

    settings = load_settings()
    dataset = load_backtest_csv(Path(args.csv))
    session = SessionState(
        market_topic=args.topic,
        selected_category="Backtest",
        bootstrap_principal_usd=args.capital,
        available_capital_usd=args.capital,
        simulation_mode="backtest",
    )
    results, summary = run_backtest(settings, session, dataset)

    print("ElsaFlow Backtest Summary")
    print("-------------------------")
    for key, value in summary.items():
        print(f"{key}: {value}")

    print("\nLast 5 rows")
    print(results.tail(5).to_string(index=False))


if __name__ == "__main__":
    main()
