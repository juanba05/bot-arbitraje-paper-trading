#!/usr/bin/env python
"""
WhatsApp bridge (Twilio webhook) for remote command intake.

Design goals:
- No dependency installs (stdlib only)
- Strict sender allowlist
- Optional PIN requirement
- Local append-only inbox log for auditability

This script does NOT read .env files.
It only uses process environment variables.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "datos"
INBOX_FILE = DATA_DIR / "wsp_inbox.jsonl"
STATE_FILE = DATA_DIR / "wsp_state.json"
CODEX_LAST_FILE = DATA_DIR / "wsp_codex_last.txt"
CHAT_HISTORY_FILE = DATA_DIR / "wsp_codex_chat.jsonl"
PROJECT_FILES = [ROOT / "CONTEXTO_PROYECTO.txt", ROOT / "OPERATIVA_DIARIA.md"]


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def ensure_paths() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not INBOX_FILE.exists():
        INBOX_FILE.touch()
    if not STATE_FILE.exists():
        STATE_FILE.write_text("{}", encoding="utf-8")


def _normalize_number(n: str) -> str:
    n = (n or "").strip()
    if not n:
        return ""
    if n.startswith("whatsapp:"):
        return n
    if n.startswith("+"):
        return f"whatsapp:{n}"
    return f"whatsapp:+{n}"


def load_cfg() -> Dict[str, str]:
    cfg = {
        "allowed_from": _normalize_number(os.getenv("WSP_ALLOWED_FROM", "")),
        "require_pin": os.getenv("WSP_REQUIRE_PIN", "false").lower() in {"1", "true", "yes"},
        "pin": os.getenv("WSP_PIN", "").strip(),
        "twilio_sid": os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
        "twilio_token": os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        "twilio_from": _normalize_number(os.getenv("TWILIO_WHATSAPP_FROM", "")),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "ai_model": os.getenv("WSP_AI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini",
    }
    return cfg


def append_inbox(item: Dict[str, Any]) -> None:
    with INBOX_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> Dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parse_user_text(body: str, require_pin: bool, pin: str) -> Dict[str, Any]:
    text = (body or "").strip()
    if not text:
        return {"ok": False, "reason": "empty", "text": ""}

    if require_pin:
        if not pin:
            return {"ok": False, "reason": "pin_not_set", "text": ""}
        # Expected format: "<PIN> your message..."
        if not text.startswith(pin):
            return {"ok": False, "reason": "pin_invalid", "text": ""}
        text = text[len(pin):].strip()
        if not text:
            return {"ok": False, "reason": "empty_after_pin", "text": ""}

    return {"ok": True, "reason": "ok", "text": text}


def twiml(message: str) -> bytes:
    safe = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe}</Message></Response>'
    return xml.encode("utf-8")


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "WspBridge/1.0"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/whatsapp":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw)
        from_num = _normalize_number(form.get("From", [""])[0])
        body = form.get("Body", [""])[0]
        msg_sid = form.get("MessageSid", [""])[0]

        cfg = load_cfg()
        accepted = True
        reason = "ok"
        parsed = {"ok": True, "text": body}

        if not cfg["allowed_from"]:
            accepted = False
            reason = "allowed_from_not_set"
        elif from_num != cfg["allowed_from"]:
            accepted = False
            reason = "sender_not_allowed"
        else:
            parsed = parse_user_text(body, bool(cfg["require_pin"]), cfg["pin"])
            if not parsed["ok"]:
                accepted = False
                reason = parsed["reason"]

        item = {
            "ts": now_iso(),
            "from": from_num,
            "raw_body": body,
            "text": parsed.get("text", ""),
            "message_sid": msg_sid,
            "accepted": accepted,
            "reason": reason,
        }
        append_inbox(item)

        state = load_state()
        state["last_event"] = item
        if accepted:
            state["last_accepted_text"] = parsed["text"]
            state["last_accepted_ts"] = item["ts"]
        save_state(state)

        if accepted:
            reply = "Recibido. Mensaje en cola local."
        else:
            reply = f"Rechazado ({reason})."

        payload = twiml(reply)
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep console clean; explicit logs are stored in inbox/state files.
        return


def cmd_serve(port: int) -> int:
    ensure_paths()
    # Security-first default: listen only on localhost.
    # Remote access should come through an outbound tunnel (e.g. ngrok),
    # not by exposing the process directly on LAN/WAN interfaces.
    host = "127.0.0.1"
    httpd = ThreadingHTTPServer((host, port), BridgeHandler)
    print(f"[WSP] Bridge listening on http://127.0.0.1:{port}")
    print("[WSP] Endpoints: POST /whatsapp | GET /health")
    print("[WSP] Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[WSP] Stopped by user.")
    finally:
        httpd.server_close()
    return 0


def cmd_status() -> int:
    ensure_paths()
    state = load_state()
    if not state:
        print("[WSP] No state yet.")
        return 0
    last = state.get("last_event") or {}
    print("[WSP] Last event:")
    print(json.dumps(last, ensure_ascii=False, indent=2))
    return 0


def cmd_pending(limit: int) -> int:
    ensure_paths()
    lines = INBOX_FILE.read_text(encoding="utf-8").splitlines()
    rows = []
    for ln in lines:
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    accepted = [r for r in rows if r.get("accepted")]
    for r in accepted[-limit:]:
        print(f"{r.get('ts')} | {r.get('from')} | {r.get('text')}")
    print(f"[WSP] accepted_messages={len(accepted)} total_events={len(rows)}")
    return 0


def twilio_send_message(account_sid: str, auth_token: str, from_whatsapp: str, to_whatsapp: str, body: str) -> Dict[str, Any]:
    if not account_sid or not auth_token or not from_whatsapp or not to_whatsapp:
        raise ValueError("Missing Twilio credentials or numbers in environment.")

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = urlencode(
        {"From": from_whatsapp, "To": to_whatsapp, "Body": body}
    ).encode("utf-8")
    auth_raw = f"{account_sid}:{auth_token}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("ascii")

    req = Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", f"Basic {auth_b64}")
    with urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def twilio_list_messages(account_sid: str, auth_token: str, page_size: int = 50) -> Dict[str, Any]:
    if not account_sid or not auth_token:
        raise ValueError("Missing Twilio credentials in environment.")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json?PageSize={page_size}"
    auth_raw = f"{account_sid}:{auth_token}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("ascii")
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Basic {auth_b64}")
    with urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _seed_poll_cursor_if_needed(max_messages: int = 20) -> None:
    """
    Prevent replaying historical WhatsApp messages when agent starts.
    If there is no cursor yet, set it to the newest message SID.
    """
    cfg = load_cfg()
    state = load_state()
    if str(state.get("last_polled_sid", "")).strip():
        return
    data = twilio_list_messages(cfg["twilio_sid"], cfg["twilio_token"], page_size=max_messages)
    items = data.get("messages", []) or []
    if not items:
        return
    newest_sid = str(items[0].get("sid", "")).strip()
    if newest_sid:
        state["last_polled_sid"] = newest_sid
        state["cursor_seeded_ts"] = now_iso()
        save_state(state)


def cmd_poll(max_messages: int) -> int:
    ensure_paths()
    cfg = load_cfg()
    state = load_state()
    last_sid = str(state.get("last_polled_sid", "")).strip()

    data = twilio_list_messages(cfg["twilio_sid"], cfg["twilio_token"], page_size=max_messages)
    items = data.get("messages", []) or []
    # Twilio returns newest first. Build only "new" items until boundary.
    new_items = []
    for msg in items:
        sid = str(msg.get("sid", "")).strip()
        if last_sid and sid and sid == last_sid:
            break
        new_items.append(msg)

    accepted_count = 0
    seen_new_sid = last_sid

    # Process oldest -> newest among truly new items.
    for msg in reversed(new_items):
        sid = str(msg.get("sid", "")).strip()

        from_num = _normalize_number(str(msg.get("from", "")))
        to_num = _normalize_number(str(msg.get("to", "")))
        body = str(msg.get("body", "") or "")
        direction = str(msg.get("direction", "") or "").lower()

        # Keep only inbound WhatsApp messages targeting our sandbox number.
        if "inbound" not in direction:
            continue
        if cfg["twilio_from"] and to_num != cfg["twilio_from"]:
            continue

        accepted = True
        reason = "ok"
        parsed = {"ok": True, "text": body}

        if not cfg["allowed_from"]:
            accepted = False
            reason = "allowed_from_not_set"
        elif from_num != cfg["allowed_from"]:
            accepted = False
            reason = "sender_not_allowed"
        else:
            parsed = parse_user_text(body, bool(cfg["require_pin"]), cfg["pin"])
            if not parsed["ok"]:
                accepted = False
                reason = parsed["reason"]

        event = {
            "ts": now_iso(),
            "source": "twilio_poll",
            "from": from_num,
            "to": to_num,
            "raw_body": body,
            "text": parsed.get("text", ""),
            "message_sid": sid,
            "accepted": accepted,
            "reason": reason,
        }
        append_inbox(event)

        state["last_event"] = event
        if accepted:
            accepted_count += 1
            state["last_accepted_text"] = parsed["text"]
            state["last_accepted_ts"] = event["ts"]

        if sid:
            seen_new_sid = sid

    if seen_new_sid:
        state["last_polled_sid"] = seen_new_sid
    save_state(state)

    print(f"[WSP] poll processed={len(new_items)} accepted_new={accepted_count}")
    return 0


def cmd_send(to: str, text: str) -> int:
    cfg = load_cfg()
    to_whatsapp = _normalize_number(to)
    result = twilio_send_message(
        account_sid=cfg["twilio_sid"],
        auth_token=cfg["twilio_token"],
        from_whatsapp=cfg["twilio_from"],
        to_whatsapp=to_whatsapp,
        body=text,
    )
    sid = result.get("sid", "<no-sid>")
    status = result.get("status", "<no-status>")
    print(f"[WSP] sent sid={sid} status={status}")
    return 0


def _read_inbox_rows() -> list[Dict[str, Any]]:
    ensure_paths()
    rows: list[Dict[str, Any]] = []
    for ln in INBOX_FILE.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            rows.append(json.loads(ln))
        except Exception:
            continue
    return rows


def _clip(text: str, max_len: int = 1100) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _run_script(args: list[str], timeout: int = 120) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable] + args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = out if out else ""
    if err:
        combined = (combined + "\n" + err).strip()
    return proc.returncode, _clip(combined, 1100)


def _find_codex_cmd() -> str:
    candidates = [
        str(Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd"),
        "codex.cmd",
    ]
    for c in candidates:
        if c.endswith(".cmd") and Path(c).exists():
            return c
    return candidates[-1]


def _run_codex_exec(user_prompt: str, timeout: int = 1200) -> tuple[int, str]:
    ensure_paths()
    codex_cmd = _find_codex_cmd()
    started_at = dt.datetime.now().timestamp()
    try:
        if CODEX_LAST_FILE.exists():
            CODEX_LAST_FILE.unlink()
    except Exception:
        pass

    normalized_user_prompt = " ".join((user_prompt or "").split())
    wrapped = (
        "Usuario remoto por WhatsApp pidio:\n"
        f"{normalized_user_prompt}\n\n"
        "Ejecuta en este repositorio los cambios necesarios, sin comandos destructivos.\n"
        "NO pidas mas contexto: si hay ambiguedad, asume la opcion mas segura y deja nota breve.\n"
        "Respuesta FINAL en espanol y maximo 900 caracteres con este formato:\n"
        "HECHO: ...\nARCHIVOS: ...\nSIGUIENTE: ...\n"
    )

    cmd = [
        codex_cmd,
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "-C",
        str(ROOT),
        "-o",
        str(CODEX_LAST_FILE),
        wrapped,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    msg = ""
    try:
        if CODEX_LAST_FILE.exists():
            mtime = CODEX_LAST_FILE.stat().st_mtime
            # Avoid stale replies from previous executions.
            if mtime >= started_at - 1:
                msg = CODEX_LAST_FILE.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        msg = ""
    if not msg:
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        msg = (out + "\n" + err).strip()
    if not msg:
        msg = "Codex no devolvio salida util en esta ejecucion."
    return proc.returncode, _clip(msg, 1150)


def _looks_incomplete_response(text: str) -> bool:
    t = (text or "").lower()
    markers = [
        "falta el resto del mensaje",
        "falta el contenido",
        "falta el detalle del pedido",
        "falta el detalle",
        "pegame el mensaje completo",
        "pégame el mensaje completo",
        "pasame exactamente",
        "pásame exactamente",
        "necesito mas contexto",
        "necesito más contexto",
    ]
    return any(m in t for m in markers)


def _looks_codex_runtime_error(text: str) -> bool:
    t = (text or "").lower()
    markers = [
        "stream disconnected",
        "error sending request",
        "reconnecting...",
        "channel closed",
        "failed to install system skills",
        "codex no devolvio salida util",
    ]
    return any(m in t for m in markers)


def _read_chat_history(limit: int = 8) -> list[Dict[str, str]]:
    ensure_paths()
    if not CHAT_HISTORY_FILE.exists():
        return []
    rows: list[Dict[str, str]] = []
    for ln in CHAT_HISTORY_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
            role = str(obj.get("role", "")).strip()
            text = str(obj.get("text", "")).strip()
            if role in {"user", "assistant"} and text:
                rows.append({"role": role, "text": text})
        except Exception:
            continue
    return rows[-limit:]


def _append_chat(role: str, text: str) -> None:
    ensure_paths()
    item = {"ts": now_iso(), "role": role, "text": _clip(text, 4000)}
    with CHAT_HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _read_project_context(max_chars: int = 24000) -> str:
    chunks = []
    for p in PROJECT_FILES:
        try:
            if p.exists():
                txt = p.read_text(encoding="utf-8", errors="replace")
                chunks.append(f"=== {p.name} ===\n{txt}")
        except Exception:
            continue
    merged = "\n\n".join(chunks).strip()
    return _clip(merged, max_chars) if merged else "(sin contexto de archivos)"


def _extract_responses_text(payload: Dict[str, Any]) -> str:
    txt = str(payload.get("output_text", "") or "").strip()
    if txt:
        return txt
    out = payload.get("output", []) or []
    parts = []
    for item in out:
        for c in item.get("content", []) or []:
            t = c.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t.strip())
    return "\n".join(parts).strip()


def _run_openai_chat_turn(cfg: Dict[str, Any], user_text: str, timeout: int = 90) -> tuple[int, str]:
    api_key = cfg.get("openai_api_key", "")
    if not api_key:
        return (2, "OPENAI_API_KEY no configurada en esta terminal.")

    history_limit = int(os.getenv("WSP_CHAT_HISTORY_LIMIT", "80"))
    history = _read_chat_history(limit=max(10, history_limit))
    normalized_user = " ".join((user_text or "").split())
    convo = []
    for h in history:
        prefix = "USUARIO" if h["role"] == "user" else "ASISTENTE"
        convo.append(f"{prefix}: {h['text']}")
    convo_block = "\n".join(convo) if convo else "(sin historial previo)"
    project_ctx = _read_project_context(max_chars=int(os.getenv("WSP_CONTEXT_MAX_CHARS", "24000")))

    prompt = (
        "Canal remoto por WhatsApp para colaborar sobre este proyecto local.\n"
        "Tu rol: ingeniero pragmatico. Responde en espanol.\n"
        "Reglas:\n"
        "- Conversacion natural, sin pedir formato rigido.\n"
        "- Si el usuario pide recomendaciones, propone plan claro.\n"
        "- Si el usuario pide cambios de codigo, primero propone y espera confirmacion explicita ('ok aplicalo').\n"
        "- Nunca respondas con texto tipo 'pasame el mensaje completo'.\n"
        "- Respuesta breve util (max 900 chars).\n\n"
        f"CONTEXTO DEL PROYECTO:\n{project_ctx}\n\n"
        f"HISTORIAL RECIENTE:\n{convo_block}\n\n"
        f"NUEVO MENSAJE DEL USUARIO:\n{normalized_user}\n"
    )

    body = {
        "model": cfg.get("ai_model", "gpt-5-mini"),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        "max_output_tokens": 700,
    }
    req = Request("https://api.openai.com/v1/responses", method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    raw = json.dumps(body).encode("utf-8")
    try:
        with urlopen(req, data=raw, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        out = _extract_responses_text(data)
        if not out:
            return (1, "Respuesta vacia del modelo.")
        return (0, _clip(out, 1100))
    except HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        return (1, _clip(f"HTTP {e.code} en OpenAI API. {detail}", 1100))
    except URLError as e:
        return (1, _clip(f"Error de red OpenAI API: {e}", 1100))
    except Exception as e:
        return (1, _clip(f"Error OpenAI API: {type(e).__name__}", 1100))


def _codex_login_status() -> tuple[int, str]:
    cmd = [_find_codex_cmd(), "login", "status"]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=40,
        check=False,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return proc.returncode, _clip((out + "\n" + err).strip(), 900)


def _run_apply_via_codex(user_text: str, timeout: int = 1500) -> tuple[int, str]:
    history = _read_chat_history(limit=30)
    convo = []
    for h in history:
        prefix = "USUARIO" if h["role"] == "user" else "ASISTENTE"
        convo.append(f"{prefix}: {h['text']}")
    convo_block = "\n".join(convo) if convo else "(sin historial)"
    prompt = (
        "Aplicar cambios en este repositorio basados en conversacion remota por WhatsApp.\n"
        "El usuario ya dio confirmacion explicita para aplicar ahora.\n"
        "No usar comandos destructivos. Ejecutar cambios y validar (py_compile/tests basicos si aplica).\n"
        "Responder breve en espanol con:\n"
        "HECHO: ...\nARCHIVOS: ...\nVALIDACION: ...\nSIGUIENTE: ...\n\n"
        f"Historial reciente:\n{convo_block}\n\n"
        f"Mensaje de confirmacion/aplicacion:\n{user_text}\n"
    )
    return _run_codex_exec(prompt, timeout=timeout)


def _reply(cfg: Dict[str, Any], to_whatsapp: str, text: str) -> str:
    result = twilio_send_message(
        account_sid=cfg["twilio_sid"],
        auth_token=cfg["twilio_token"],
        from_whatsapp=cfg["twilio_from"],
        to_whatsapp=to_whatsapp,
        body=_clip(text, 1200),
    )
    return str(result.get("sid", ""))


def _format_preflight_output(raw: str) -> str:
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    picked = []
    for ln in lines:
        if "ESTADO GLOBAL" in ln:
            picked.append(ln)
        elif ln.startswith("[OK]") or ln.startswith("[WARN]") or ln.startswith("[FAIL]"):
            picked.append(ln)
    if not picked:
        picked = lines[-12:]
    return "\n".join(picked[-16:]) if picked else "Sin salida de preflight."


def _handle_remote_command(text: str, cfg: Dict[str, Any]) -> tuple[str, bool]:
    cmd = " ".join((text or "").strip().split()).lower()
    if not cmd:
        return ("Comando vacio. Envia: help", False)

    if cmd in {"help", "ayuda"}:
        return (
            "Control: status|start|detener|preflight|detener bridge. Conversacion libre: escribe normal. Para aplicar cambios: 'ok aplicalo ...'",
            False,
        )

    if cmd == "ping":
        return ("pong", False)

    if cmd in {"status", "estado"}:
        rc, out = _run_script(["lanzar_sesion.py", "status"], timeout=30)
        if rc == 0:
            return (f"STATUS\n{out}", False)
        return (f"STATUS ERROR rc={rc}\n{out}", False)

    if cmd == "codex status":
        rc, out = _codex_login_status()
        if rc == 0:
            return (f"CODEX STATUS OK\n{out}", False)
        return (f"CODEX STATUS ERROR rc={rc}\n{out}", False)

    if cmd in {"ai status", "openai status"}:
        if cfg.get("openai_api_key"):
            return (f"OPENAI STATUS OK\nmodelo={cfg.get('ai_model','gpt-5-mini')}", False)
        return ("OPENAI STATUS ERROR\nFalta OPENAI_API_KEY en esta terminal.", False)

    if cmd.startswith("ok aplicalo") or cmd.startswith("aplicalo"):
        _append_chat("user", text)
        rc, out = _run_apply_via_codex(user_text=text, timeout=1500)
        if _looks_incomplete_response(out) or _looks_codex_runtime_error(out):
            return (f"APLICACION ERROR rc={rc}\n{out}", False)
        _append_chat("assistant", out)
        if rc == 0:
            return (f"APLICACION OK\n{out}", False)
        return (f"APLICACION ERROR rc={rc}\n{out}", False)

    if cmd.startswith("codex "):
        user_prompt = text.strip()[len("codex "):].strip()
        if not user_prompt:
            return ("Uso: 1234 codex <pedido>", False)
        _append_chat("user", user_prompt)
        rc, out = _run_apply_via_codex(user_text=user_prompt, timeout=1500)
        if _looks_incomplete_response(out):
            rc, out = _run_apply_via_codex(user_text=f"{user_prompt}. Ejecutalo sin pedir aclaraciones innecesarias.")
        if _looks_incomplete_response(out):
            return ("CODEX ERROR\nRespuesta incompleta del motor. Reintenta en 30s.", False)
        _append_chat("assistant", out)
        if rc == 0 and not _looks_codex_runtime_error(out):
            return (f"CODEX OK\n{out}", False)
        return (f"CODEX ERROR rc={rc}\n{out}", False)

    if cmd == "start":
        rc, out = _run_script(["lanzar_sesion.py", "start", "--mode", "both"], timeout=40)
        if rc == 0:
            return (f"START BOTH OK\n{out}", False)
        return (f"START BOTH ERROR rc={rc}\n{out}", False)

    if cmd == "start bot":
        rc, out = _run_script(["lanzar_sesion.py", "start", "--mode", "bot"], timeout=40)
        if rc == 0:
            return (f"START BOT OK\n{out}", False)
        return (f"START BOT ERROR rc={rc}\n{out}", False)

    if cmd == "start dashboard":
        rc, out = _run_script(["lanzar_sesion.py", "start", "--mode", "dashboard"], timeout=40)
        if rc == 0:
            return (f"START DASHBOARD OK\n{out}", False)
        return (f"START DASHBOARD ERROR rc={rc}\n{out}", False)

    if cmd in {"detener", "apagar"}:
        rc, out = _run_script(["lanzar_sesion.py", "stop"], timeout=40)
        if rc == 0:
            return (f"DETENER OK\n{out}", False)
        return (f"DETENER ERROR rc={rc}\n{out}", False)

    if cmd == "preflight":
        rc, out = _run_script(["preflight_operativo.py"], timeout=180)
        view = _format_preflight_output(out)
        if rc == 0:
            return (f"PREFLIGHT\n{view}", False)
        return (f"PREFLIGHT ERROR rc={rc}\n{view}", False)

    if cmd in {"detener bridge", "apagar bridge"}:
        return ("Bridge detenido por comando remoto.", True)

    if cmd.startswith("stop"):
        return ("No uses 'stop' en Twilio Sandbox. Usa 'detener' o 'detener bridge'.", False)

    # Fallback conversational mode: natural chat via OpenAI API.
    _append_chat("user", text)
    rc, out = _run_openai_chat_turn(cfg, text, timeout=90)
    _append_chat("assistant", out)
    if rc == 0:
        return (f"CHAT OK\n{out}", False)
    return (f"CHAT ERROR rc={rc}\n{out}", False)


def _dispatch_new_messages(max_messages: int, verbose: bool = True) -> tuple[int, int, bool]:
    cmd_poll(max_messages=max_messages)
    cfg = load_cfg()
    state = load_state()
    rows = _read_inbox_rows()

    dispatched = set(state.get("dispatched_sids", []))
    new_dispatched = 0
    replies = 0
    should_stop = False

    for event in rows:
        if not event.get("accepted"):
            continue
        if event.get("source") != "twilio_poll":
            continue
        sid = str(event.get("message_sid", "")).strip()
        if not sid or sid in dispatched:
            continue

        text = str(event.get("text", "")).strip()
        to = _normalize_number(str(event.get("from", "")))
        reply_text, stop_after = _handle_remote_command(text, cfg)
        try:
            _reply(cfg, to, reply_text)
            replies += 1
        except Exception as exc:
            err = f"ERROR enviando respuesta: {type(exc).__name__}"
            if verbose:
                print(f"[WSP] {err}")
        dispatched.add(sid)
        new_dispatched += 1
        if stop_after:
            should_stop = True

    # Keep bounded state size.
    state["dispatched_sids"] = list(dispatched)[-500:]
    state["last_dispatch_ts"] = now_iso()
    save_state(state)

    if verbose:
        print(f"[WSP] dispatch processed={new_dispatched} replies={replies}")
    return new_dispatched, replies, should_stop


def cmd_agent(interval: int, max_messages: int) -> int:
    ensure_paths()
    _seed_poll_cursor_if_needed(max_messages=min(max_messages, 20))
    print(f"[WSP] Agent activo | interval={interval}s max={max_messages}")
    print("[WSP] Comandos: status/start/detener/preflight + chat libre (OpenAI) + 'ok aplicalo ...' (Codex)")
    try:
        while True:
            _, _, should_stop = _dispatch_new_messages(max_messages=max_messages, verbose=True)
            if should_stop:
                print("[WSP] stop bridge recibido. Saliendo.")
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[WSP] Agent detenido por usuario.")
    return 0


def cmd_agent_once(max_messages: int) -> int:
    _dispatch_new_messages(max_messages=max_messages, verbose=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="WhatsApp bridge helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run local webhook server")
    serve.add_argument("--port", type=int, default=8787)

    sub.add_parser("status", help="Show last webhook event")

    pending = sub.add_parser("pending", help="Show accepted pending messages")
    pending.add_argument("--limit", type=int, default=20)

    poll = sub.add_parser("poll", help="Fetch inbound WhatsApp messages from Twilio API")
    poll.add_argument("--max", type=int, default=50, help="Max messages to inspect")

    agent = sub.add_parser("agent", help="Poll + execute allowed remote commands + auto-reply")
    agent.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    agent.add_argument("--max", type=int, default=50, help="Max messages to inspect per cycle")

    agent_once = sub.add_parser("agent-once", help="Single cycle of poll+dispatch")
    agent_once.add_argument("--max", type=int, default=50, help="Max messages to inspect")

    send = sub.add_parser("send", help="Send outbound WhatsApp message via Twilio API")
    send.add_argument("--to", required=True, help="Destination number, e.g. +549351...")
    send.add_argument("--text", required=True, help="Message body")

    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "serve":
        return cmd_serve(port=args.port)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "pending":
        return cmd_pending(limit=args.limit)
    if args.cmd == "poll":
        return cmd_poll(max_messages=args.max)
    if args.cmd == "agent":
        return cmd_agent(interval=args.interval, max_messages=args.max)
    if args.cmd == "agent-once":
        return cmd_agent_once(max_messages=args.max)
    if args.cmd == "send":
        return cmd_send(to=args.to, text=args.text)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
