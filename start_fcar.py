# -*- coding: utf-8 -*-
"""
FCAR - inicializador sem CMD (Windows)
- Sobe o servidor Flask em segundo plano
- Abre o navegador automaticamente
- Salva o PID para permitir fechar depois
"""
import os
import re
import sys
import time
import socket
import webbrowser
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent

def guess_entry_file() -> Path:
    # Se existir start.py, preferir. Caso contrário, usar app.py
    for name in ("start.py", "app.py"):
        p = BASE / name
        if p.exists():
            return p
    raise FileNotFoundError("Não achei start.py nem app.py na pasta do FCAR.")

def guess_port(entry_file: Path) -> int:
    # tenta achar "port=####" no arquivo
    try:
        txt = entry_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 5055
    m = re.search(r"port\s*=\s*(\d{2,5})", txt)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    return 5055

def wait_port(host: str, port: int, timeout_s: float = 12.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.25)
    return False

def main():
    entry = guess_entry_file()
    port = guess_port(entry)

    log_path = BASE / "fcar_start.log"
    pid_path = BASE / "fcar.pid"

    # Se já tem PID e a porta responde, apenas abre no navegador
    if pid_path.exists():
        if wait_port("127.0.0.1", port, timeout_s=1.2):
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return

    # Descobre o python a usar (preferir o venv local)
    venv_py = BASE / "venv" / "Scripts" / ("pythonw.exe" if sys.executable.lower().endswith("pythonw.exe") else "python.exe")
    py = str(venv_py) if venv_py.exists() else sys.executable

    log_path.parent.mkdir(parents=True, exist_ok=True)
    logf = open(log_path, "a", encoding="utf-8", errors="ignore")

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    p = subprocess.Popen(
        [py, str(entry)],
        cwd=str(BASE),
        stdout=logf,
        stderr=logf,
        creationflags=creationflags
    )

    pid_path.write_text(str(p.pid), encoding="utf-8")

    # Espera servidor e abre o navegador
    wait_port("127.0.0.1", port, timeout_s=18.0)
    webbrowser.open(f"http://127.0.0.1:{port}/")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            (BASE / "fcar_start.log").write_text(f"ERRO: {e}\n", encoding="utf-8")
        except Exception:
            pass
        raise
