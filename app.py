from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_STAMP = VENV_DIR / ".elsaflow_requirements.sha256"
BOOTSTRAP_ENV = "ELSAFLOW_STREAMLIT_BOOTSTRAPPED"


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()


def _venv_ready() -> bool:
    return _venv_python().exists()


def _running_inside_target_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == _venv_python().resolve()
    except FileNotFoundError:
        return False


def _create_venv_if_needed() -> None:
    if _venv_ready():
        return
    print("ElsaFlow: creating virtual environment...")
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(VENV_DIR)


def _install_requirements_if_needed() -> None:
    current_hash = _requirements_hash()
    if REQUIREMENTS_STAMP.exists() and REQUIREMENTS_STAMP.read_text(encoding="utf-8").strip() == current_hash:
        return

    print("ElsaFlow: installing Python dependencies...")
    subprocess.run(
        [_venv_python().as_posix(), "-m", "pip", "install", "-r", REQUIREMENTS_FILE.as_posix()],
        check=True,
        cwd=PROJECT_ROOT,
    )
    REQUIREMENTS_STAMP.write_text(current_hash, encoding="utf-8")


def _launch_streamlit_from_venv() -> None:
    env = os.environ.copy()
    env[BOOTSTRAP_ENV] = "1"
    print("ElsaFlow: launching Streamlit...")
    subprocess.run(
        [_venv_python().as_posix(), "-m", "streamlit", "run", Path(__file__).name],
        check=True,
        cwd=PROJECT_ROOT,
        env=env,
    )


def _bootstrap_and_launch() -> None:
    _create_venv_if_needed()
    _install_requirements_if_needed()
    _launch_streamlit_from_venv()


def _run_streamlit_app() -> None:
    from elsaflow.ui import run_app

    run_app()


if __name__ == "__main__":
    if os.environ.get(BOOTSTRAP_ENV) == "1" and _running_inside_target_venv():
        _run_streamlit_app()
    else:
        _bootstrap_and_launch()
