import argparse
import json
import os
import signal
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "datos")
os.makedirs(DATA_DIR, exist_ok=True)
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
SESSION_FILE = os.path.join(DATA_DIR, "sesion_procesos.json")


def _can_import_dotenv(python_exe):
    try:
        r = subprocess.run(
            [python_exe, "-c", "import dotenv"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return r.returncode == 0
    except Exception:
        return False


def _resolver_python():
    candidatos = [sys.executable, os.path.join(os.path.expanduser("~"), "anaconda3", "python.exe")]
    for exe in candidatos:
        if exe and os.path.exists(exe) and _can_import_dotenv(exe):
            return exe
    return sys.executable


def _python_cmd(script_name):
    return [_resolver_python(), script_name]


def _pid_vivo(pid):
    if pid is None:
        return False
    try:
        if os.name == "nt":
            # Prefer Get-Process on Windows; tasklist can fail with access denied
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Get-Process -Id {pid} | Out-Null"],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode == 0:
                return True
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                check=False,
            )
            return r.returncode == 0 and str(pid) in r.stdout
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _new_process(cmd, log_name):
    log_path = os.path.join(LOG_DIR, log_name)
    log_file = open(log_path, "a", encoding="utf-8")
    kwargs = {
        "cwd": BASE_DIR,
        "stdout": log_file,
        "stderr": log_file,
        "stdin": subprocess.DEVNULL,
    }
    proc = subprocess.Popen(cmd, **kwargs)
    return proc, log_path


def start(mode):
    procesos = []
    if mode in ("both", "bot"):
        p_bot, log_bot = _new_process(_python_cmd("bot_principal.py"), "sesion_bot.log")
        procesos.append({
            "name": "bot", "pid": p_bot.pid, "cmd": "bot_principal.py", "log": log_bot
        })
    if mode in ("both", "dashboard"):
        p_dash, log_dash = _new_process(_python_cmd("dashboard.py"), "sesion_dashboard.log")
        procesos.append({
            "name": "dashboard", "pid": p_dash.pid, "cmd": "dashboard.py", "log": log_dash
        })

    payload = {
        "timestamp": datetime.now().isoformat(),
        "mode": mode,
        "processes": procesos,
    }
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("Procesos iniciados:")
    for p in procesos:
        print(f" - {p['name']} (PID {p['pid']}) | log: {p.get('log')}")
    print(f"Sesión guardada en: {SESSION_FILE}")


def stop():
    if not os.path.exists(SESSION_FILE):
        print("No hay sesión activa registrada.")
        return

    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        sesion = json.load(f)

    procesos = sesion.get("processes", [])
    if not procesos:
        print("Sesión sin procesos.")
        return

    for p in procesos:
        pid = p.get("pid")
        nombre = p.get("name", "?")
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, signal.SIGTERM)
            print(f"Detenido: {nombre} (PID {pid})")
        except Exception as e:
            print(f"No se pudo detener {nombre} (PID {pid}): {e}")


def status():
    if not os.path.exists(SESSION_FILE):
        print("Sin sesión registrada.")
        return

    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        sesion = json.load(f)

    print(f"Sesión: {sesion.get('timestamp')} | modo={sesion.get('mode')}")
    for p in sesion.get("processes", []):
        pid = p.get("pid")
        estado = "vivo" if _pid_vivo(pid) else "caido"
        print(f" - {p.get('name')} (PID {pid}) [{estado}]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lanzador de bot + dashboard")
    parser.add_argument("action", choices=["start", "stop", "status"], help="Acción a ejecutar")
    parser.add_argument("--mode", choices=["both", "bot", "dashboard"], default="both",
                        help="Qué levantar en start")
    args = parser.parse_args()

    if args.action == "start":
        start(args.mode)
    elif args.action == "stop":
        stop()
    else:
        status()
