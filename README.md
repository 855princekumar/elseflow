# ElsaFlow

## Index

* Overview
* Workflow
* Demo
* Trade Mechanism
* Features
* Data Source and Real-Time Intelligence
* Trading Strategy and Capital Model
* Core Algorithm and Decision Strategy
* Polymarket Track Alignment
* Target Domains and Use Cases
* Economic Model and Agent Monetization
* Autonomous Trading Model and Capital Safety Logic
* LLM + OSINT Agent Flow
* How It Works
* System Architecture
* Execution Sequence
* Project Structure
* Setup and Run
* Database
* Alignment with Elsa and x402
* Notes

---

ElsaFlow is an autonomous research-to-execution trading agent designed to demonstrate the execution model of agentic systems aligned with Elsa and x402.

The system is implemented as a single Python script that automatically sets up its environment, installs dependencies, and launches a full Streamlit-based interface. It simulates a complete pipeline from research to execution, including cost handling and settlement.

---

## Overview

ElsaFlow showcases how an autonomous agent can operate end-to-end without manual intervention:

* Accept user intent and wallet input
* Perform structured research
* Derive sentiment and make decisions
* Execute trades in a simulated testnet environment
* Apply x402-style monetization
* Settle results and persist data

---

## Workflow

<img width="1536" height="1024" alt="work-flow" src="https://github.com/user-attachments/assets/618b2871-7e40-47e2-a16e-0154f34de40a" />

---

## Demo

Loom Video:
https://www.loom.com/share/ad1290f386534856a2a21af546db9c37

---

## Trade Mechanism

<img width="1536" height="1024" alt="trade-mechanism" src="https://github.com/user-attachments/assets/7ea1c500-b36d-4f59-8b1d-86539543c3b9" />

---

## Features

### Autonomous Agent Pipeline

* Research → Decision → Execution → Settlement

### Research Module

* Perplexity-style structured output

### Decision Engine

* Positive → YES
* Negative → NO
* Neutral → SKIP

### Execution Layer

* Simulated testnet trades

### x402 Monetization Simulation

* Cost tracking

### Settlement Engine

* Profit/loss simulation

### Persistence

* SQLite database

### User Interface

* Minimal Streamlit UI acting as control layer

---

## Data Source and Real-Time Intelligence

ElsaFlow is designed to operate on OSINT-based real-world data.

The backend integrates with systems like **ShadowBroker (OSS data aggregator)**:

* Real-time data ingestion
* Event-driven signals
* Continuous analysis

This enables dynamic decision-making instead of static logic.

---

## Trading Strategy and Capital Model

* User sets **initial capital**
* Agent trades until:

  * Capital + profit threshold (e.g., 50%) reached

### Break-even Logic

* Initial capital is returned
* System enters **profit-only mode**

---

## Core Algorithm and Decision Strategy

1. OSINT Data Ingestion
2. Sentiment Analysis
3. Decision Mapping
4. Confidence Scoring
5. Trade Execution
6. Continuous learning loop

---

## Polymarket Track Alignment

Built for:

Track 2 — Polymarket Agent

* Converts signals → trades
* Simulates execution
* Provides explainable outputs

---

## Target Domains and Use Cases

* Crypto
* Finance
* Prediction markets
* Elections
* AI / IoT trends

---

## Economic Model and Agent Monetization

* Agents pay for:

  * Research
  * Execution

* x402 enables:

  * Autonomous cost handling
  * Continuous economic activity

---

## Autonomous Trading Model and Capital Safety Logic

### Minimal Interface

User only:

* Selects category (mapped to ShadowBroker data)
* Defines intent
* Sets capital

---

### Capital Safety Flow

1. Initial Trading Phase
2. Recovery Phase
3. Safe Rollback → Capital returned

---

### Profit Loop

* Agent trades using only profits
* 50% profit → returned to user
* Remaining → reinvested

---

### Risk Control

* Max loss: 40% of profits
* If triggered:

  * Agent halts trading
  * Switches to analysis mode
  * Requires user approval

---

### Transparency

* SQLite logs
* Full trade history
* Performance tracking

---

## LLM + OSINT Agent Flow

```mermaid
flowchart LR

A[User Input UI] --> B[Agent Controller]

B --> C[Custom LLM Model]
C --> D[Decision Engine]

B --> E[ShadowBroker Local API]
E --> F[OSINT Data Stream]

F --> C

D --> G[Execution Engine]
G --> H[Trade Simulation]

H --> I[x402 Cost Layer]
I --> J[Settlement Engine]

J --> K[SQLite DB]
K --> L[UI Logs & Dashboard]
```

---

## ShadowBroker Integration 

<img width="1897" height="872" alt="image" src="https://github.com/user-attachments/assets/c8e690fe-1b01-40de-b4d9-312bfd1dedea" />

```python
# Placeholder for ShadowBroker API integration

def fetch_osint_data(category):
    """
    Connect to local ShadowBroker instance
    Fetch relevant OSINT data for selected market
    """
    pass
```

---

## How It Works

1. User inputs wallet, intent, market
2. Agent fetches OSINT data
3. LLM processes signals
4. Decision engine selects trade
5. Execution simulated
6. Cost applied (x402)
7. Settlement computed
8. Stored in DB
9. Displayed in UI

## System Architecture

```mermaid
flowchart TD

A[User Interface - Streamlit] --> B[User Inputs]
B --> B1[Wallet Address]
B --> B2[Market Selection]
B --> B3[Intent]
B --> B4[Payout Preference]

B --> C[Research Module]
C --> C1[Topic Mapping]
C --> C2[Generate Summary]
C --> C3[Assign Sentiment]

C3 -->|positive| D1
C3 -->|neutral| D2
C3 -->|negative| D3

D1 --> E[Decision Engine]
D2 --> E
D3 --> E

E --> F[Decision Output + Confidence]

F --> G[Execution Layer]
G --> G1[Simulate Trade]
G --> G2[Generate Tx Hash]
G --> G3[Assign Amount]
G --> G4[Set Status SUCCESS]

G --> H[x402 Cost Module]
H --> H1[Research Cost]
H --> H2[Execution Cost]
H --> H3[Total Cost]

H --> I[Settlement Engine]
I --> I1[Profit Calculation]
I --> I2[Convert to USD/Crypto]
I --> I3[Assign Wallet Transfer]

I --> J[SQLite Database]
J --> J1[Store Trade Data]

J --> K[UI Output Panels]
K --> K1[Research]
K --> K2[Decision]
K --> K3[Execution]
K --> K4[Costs]
K --> K5[Settlement]

K --> L[Live Logs]
L --> L1[Research Started]
L --> L2[Decision Computed]
L --> L3[Execution Triggered]
L --> L4[x402 Payment Processed]
L --> L5[Settlement Completed]
```

---

## Execution Sequence

```mermaid
sequenceDiagram
    participant User
    participant UI
    participant Research
    participant Decision
    participant Execution
    participant x402
    participant Settlement
    participant DB

    User->>UI: Provide wallet + intent
    UI->>Research: Run research(topic)
    Research->>Decision: Return sentiment
    Decision->>Execution: Send decision
    Execution->>Execution: Generate tx hash
    Execution->>x402: Request cost payment
    x402-->>Execution: Payment confirmed
    Execution->>Settlement: Execute result
    Settlement->>DB: Store trade data
    DB-->>UI: Return stored result
    UI-->>User: Display logs and output
```

---

## Project Structure

This project is intentionally implemented as a single-file system:

* Python script handles setup and runtime
* Virtual environment is created automatically
* Dependencies are installed dynamically
* Streamlit app is embedded in the same file

---

## Setup and Run

### Requirements

* Python 3.8+

### Run the application

```bash
python your_script_name.py
```

The script will:

* Create a virtual environment
* Install dependencies
* Launch the Streamlit interface

---

## Access the Application

Open in browser:

http://localhost:8501

---

## Database

* SQLite database file: trades.db
* Automatically created on first run
* Stores all trade executions and metadata

---

## Alignment with Elsa and x402

ElsaFlow demonstrates:

* Intent-based agent design
* Autonomous execution pipeline
* Simulated agent-side cost handling (x402)
* Testnet-style execution abstraction
* Self-custodial user interaction

The system focuses on architecture and execution flow rather than real on-chain integration, ensuring stability and reproducibility.

---

## Notes

* No external APIs required
* Fully deterministic behavior
* Designed for hackathon demonstration
* Optimized for fast setup and execution

---

## License

MIT License
