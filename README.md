# ElsaFlow

ElsaFlow is an autonomous research-to-execution trading agent built to demonstrate the execution model of agentic systems aligned with Elsa and x402.

The system is designed as a self-contained Python application that sets up its own environment, performs structured research, makes decisions, simulates execution, and logs outcomes through a clean Streamlit interface.

---

## Overview

ElsaFlow showcases how an autonomous agent can operate end-to-end:

- Accept user intent and wallet input
- Perform structured market research
- Derive sentiment and make decisions
- Execute simulated trades in a testnet-style environment
- Apply x402-style cost accounting
- Settle results and log outcomes

The application runs as a single Python script with automatic environment setup and dependency management.

---

## Demo

Loom Video:
https://www.loom.com/share/ad1290f386534856a2a21af546db9c37

---

## Features

### Autonomous Agent Pipeline
- Research → Decision → Execution → Settlement
- Deterministic and reproducible logic

### Research Module
- Perplexity-style structured output
- Market-specific sentiment mapping

### Decision Engine
- Positive → YES
- Negative → NO
- Neutral → SKIP
- Confidence scoring

### Execution Layer
- Simulated testnet trading
- Transaction hash generation
- Execution logs

### x402 Monetization Simulation
- Research cost
- Execution cost
- Total cost tracking

### Settlement Engine
- Profit/loss calculation
- User-directed payout preference

### Persistence
- SQLite database logging
- Full trade history stored locally

### User Interface
- Streamlit-based UI
- Light/Dark mode toggle
- Live execution logs
- Structured output panels

---

## How It Works

1. User enters wallet address, intent, and market
2. Agent performs research and assigns sentiment
3. Decision engine determines action
4. Execution layer simulates a trade with transaction hash
5. x402 module simulates cost of operations
6. Settlement engine calculates outcome
7. Data is stored in SQLite
8. UI displays full pipeline and logs

---

## Project Structure

This project is intentionally designed as a single-file system:

- setup + runtime handled inside one Python script
- virtual environment created automatically
- dependencies installed dynamically
- Streamlit app runs from the same file

---

## Setup and Run

### Requirements
- Python 3.8+

### Run the application

```bash
python your_script_name.py
