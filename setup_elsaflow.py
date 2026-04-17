import os
import sys
import subprocess
import venv
from pathlib import Path

# ---------------- VIRTUAL ENVIRONMENT SETUP ----------------

VENV_DIR = "elsaflow_venv"
REQUIREMENTS = ["streamlit"]

def setup_venv():
    """Create virtual environment if it doesn't exist"""
    venv_path = Path(VENV_DIR)
    if not venv_path.exists():
        print(f"Creating virtual environment in {VENV_DIR}...")
        venv.create(venv_path, with_pip=True)
        print("Virtual environment created successfully")
        return True
    return False

def get_venv_paths():
    """Get paths to python and streamlit inside the venv"""
    if sys.platform == "win32":
        python_path = os.path.join(VENV_DIR, "Scripts", "python.exe")
        streamlit_path = os.path.join(VENV_DIR, "Scripts", "streamlit.exe")
    else:
        python_path = os.path.join(VENV_DIR, "bin", "python")
        streamlit_path = os.path.join(VENV_DIR, "bin", "streamlit")
    return python_path, streamlit_path

def install_requirements():
    """Install required packages in virtual environment"""
    python_path, _ = get_venv_paths()
    print("Checking/Installing requirements...")
    subprocess.run([python_path, "-m", "pip", "install", "--upgrade", "pip"], 
                   capture_output=True, text=True)
    for package in REQUIREMENTS:
        print(f"Installing {package}...")
        result = subprocess.run([python_path, "-m", "pip", "install", package], 
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Error installing {package}: {result.stderr}")
            return False
    print("All requirements installed successfully")
    return True

def check_dependencies():
    """Check if streamlit is available in virtual environment"""
    _, streamlit_path = get_venv_paths()
    return os.path.exists(streamlit_path)

def create_streamlit_config():
    """Create a .streamlit/config.toml to disable telemetry/email prompt"""
    config_dir = Path(".streamlit")
    config_dir.mkdir(exist_ok=True)
    config_file = config_dir / "config.toml"
    config_content = """
[browser]
gatherUsageStats = false

[server]
headless = false
"""
    config_file.write_text(config_content.strip())
    print("Streamlit configuration created (telemetry disabled).")

def run_in_venv():
    """Run the Streamlit app within the virtual environment"""
    _, streamlit_path = get_venv_paths()
    script_path = os.path.abspath(__file__)
    # Create config before launching
    create_streamlit_config()
    # Launch Streamlit
    cmd = [streamlit_path, "run", script_path, "--", "--venv-mode"]
    try:
        result = subprocess.run(cmd, capture_output=False, text=True)
        return result.returncode
    except KeyboardInterrupt:
        print("\nStreamlit app stopped by user.")
        return 0

def run_main_app():
    """Main Streamlit application (only runs when --venv-mode is passed)"""
    import streamlit as st
    import random
    import sqlite3
    from datetime import datetime
    import time

    # ---------------- DATABASE ----------------
    conn = sqlite3.connect("trades.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wallet TEXT,
        topic TEXT,
        intent TEXT,
        decision TEXT,
        confidence INTEGER,
        profit REAL,
        tx_hash TEXT,
        research_summary TEXT,
        timestamp TEXT
    )
    """)
    conn.commit()

    # ---------------- LOGIC ----------------
    def run_research(topic):
        if topic == "AI":
            return "AI sector is growing rapidly due to strong policy and funding support.", "positive"
        elif topic == "Crypto":
            return "Crypto market shows mixed volatility with uncertain signals.", "neutral"
        else:
            return "Political instability may negatively impact markets.", "negative"

    def make_decision(sentiment):
        if sentiment == "positive":
            return "YES", 82
        elif sentiment == "negative":
            return "NO", 78
        return "SKIP", 60

    def generate_tx():
        return "0x" + "".join(random.choices("abcdef0123456789", k=40))

    def execute_trade(topic, decision):
        return {
            "market": topic,
            "side": decision,
            "amount": 30,
            "currency": "USDC",
            "tx_hash": generate_tx(),
            "status": "SUCCESS"
        }

    def simulate_costs():
        return {"research": 0.01, "execution": 0.02, "total": 0.03}

    def settle_trade(decision):
        if decision == "YES":
            return 25
        elif decision == "NO":
            return -10
        return 0

    # ---------------- UI ----------------
    st.set_page_config(layout="wide")

    if "dark" not in st.session_state:
        st.session_state.dark = False

    col_toggle, _ = st.columns([1,5])
    with col_toggle:
        if st.button("Toggle Theme"):
            st.session_state.dark = not st.session_state.dark

    if st.session_state.dark:
        st.markdown(
            "<style>body {background-color:#0e1117; color:white;} </style>",
            unsafe_allow_html=True
        )

    st.title("ElsaFlow — Autonomous Trading Agent")
    st.subheader("Input")

    col1, col2 = st.columns(2)
    with col1:
        wallet = st.text_input("Wallet Address")
        topic = st.selectbox("Market", ["AI", "Crypto", "Elections"])
    with col2:
        intent = st.text_input("Intent")
        payout = st.selectbox("Payout Preference", ["USD", "Crypto"])

    if st.button("Run Agent"):
        if not wallet:
            st.error("Wallet address required")
        else:
            logs = []
            placeholder = st.empty()

            def log_step(msg):
                logs.append(msg)
                with placeholder.container():
                    st.subheader("Live Logs")
                    for l in logs:
                        st.write(l)

            log_step("Starting research...")
            time.sleep(0.5)
            research, sentiment = run_research(topic)
            log_step("Research completed")
            time.sleep(0.5)
            decision, confidence = make_decision(sentiment)
            log_step(f"Decision computed: {decision}")
            time.sleep(0.5)
            execution = execute_trade(topic, decision)
            log_step("Execution triggered (Testnet)")
            time.sleep(0.5)
            costs = simulate_costs()
            log_step("x402 payment processed")
            time.sleep(0.5)
            profit = settle_trade(decision)
            log_step("Settlement completed")

            c.execute("""
                INSERT INTO trades (wallet, topic, intent, decision, confidence, profit, tx_hash, research_summary, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (wallet, topic, intent, decision, confidence, profit, execution["tx_hash"], research, datetime.now().isoformat()))
            conn.commit()

            st.divider()
            colA, colB = st.columns(2)
            with colA:
                st.subheader("Research")
                st.write(research)
                st.subheader("Decision")
                st.write(f"{decision} ({confidence}%)")
                st.subheader("Execution (Testnet)")
                st.json(execution)
            with colB:
                st.subheader("x402 Cost Breakdown")
                st.write(costs)
                st.subheader("Settlement")
                st.write(f"Profit: ${profit}")
                st.write(f"Sent to: {wallet}")

            st.success("Agent completed execution successfully")

# ---------------- MAIN ENTRY POINT ----------------

if __name__ == "__main__":
    if "--venv-mode" in sys.argv:
        run_main_app()
    else:
        print("=" * 50)
        print("ElsaFlow - Autonomous Trading Agent Setup")
        print("=" * 50)

        if not os.path.exists(VENV_DIR):
            print("First time setup detected...")
            setup_venv()
            install_requirements()
            print("\nSetup complete! Starting application...\n")
        else:
            print("Virtual environment found. Checking dependencies...")
            if not check_dependencies():
                print("Missing dependencies. Installing requirements...")
                install_requirements()
            else:
                print("All dependencies available.")
            print("\nStarting application...\n")

        # Launch the app using streamlit run
        exit_code = run_in_venv()
        sys.exit(exit_code)