"""
Agent1 - Sales Order Agent (Groq AI)
Implements all app7.1.py functionality with Groq as the AI backend.

Configuration: Agents/config.json
API Key:       Set grok_api_key in Agents/config.json (or GROQ_API_KEY env var)
Model:         set via grok_model in config.json (Groq model id)
Port:          5001                     (overridable via app_port in config.json)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from typing import Any, Dict, Optional

# =========================================================
# Path / Config Bootstrap
# =========================================================

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
_CUSTOMUI_DIR = os.path.abspath(os.path.join(_AGENT_DIR, "..", "CustomUI"))

# Add CustomUI to sys.path so shared modules (config_manager, pydantic_ai_adapter,
# system_prompts) are importable.
if _CUSTOMUI_DIR not in sys.path:
    sys.path.insert(0, _CUSTOMUI_DIR)

# Patch config_manager BEFORE any module uses it so the singleton loads
# Agents/config.json instead of CustomUI/config.json.
import config_manager as _cm
_cm.CONFIG_FILE = os.path.join(_AGENT_DIR, "config.json")
_cm.KEY_FILE    = os.path.join(_AGENT_DIR, "config.key")

# Keep Groq credentials separate from the shared backend configuration.
_cm.ENCRYPTED_FIELDS = (_cm.ENCRYPTED_FIELDS - {"openai_api_key"}) | {"grok_api_key", "login_password"}
for _k in {"openai_api_key", "openai_model"}:
    _cm.DEFAULT_CONFIG.pop(_k, None)
_cm.DEFAULT_CONFIG.setdefault("grok_api_key",   "")
_cm.DEFAULT_CONFIG.setdefault("grok_model",     "openai/gpt-oss-120b")
_cm.DEFAULT_CONFIG.setdefault("grok_base_url",  "https://api.groq.com/openai/v1")

_cm.ConfigManager._instance = None          # force re-init with new paths

# =========================================================
# Groq AI Helpers
# =========================================================

import requests as _requests

GROK_BASE_URL = "https://api.groq.com/openai/v1"


def get_grok_token() -> str:
    """Read the Groq API key from env vars or Agents/config.json."""
    token = os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")
    if not token:
        token = _cm.get_config_value("grok_api_key")
    if token:
        token = str(token).strip()
    return token or ""


def get_grok_model() -> str:
    return str(_cm.get_config_value("grok_model") or "openai/gpt-oss-120b")


def get_grok_base_url() -> str:
    return str(_cm.get_config_value("grok_base_url") or GROK_BASE_URL).rstrip("/")


def grok_chat_completion(
    messages: list,
    temperature: float = 0,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """Send a chat completion request to the Groq API.

    The Groq API is OpenAI-compatible; only the base URL and auth key differ.
    """
    token = get_grok_token()
    if not token:
        raise ValueError(
            "Groq API key is not configured. "
            "Set grok_api_key in Agents/config.json."
        )

    payload: Dict[str, Any] = {
        "model": get_grok_model(),
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    url = f"{get_grok_base_url()}/chat/completions"
    max_retries = int(_cm.get_config_value("grok_max_retries", 2) or 2)
    base_delay = float(_cm.get_config_value("grok_retry_base_seconds", 1.5) or 1.5)

    for attempt in range(max_retries + 1):
        try:
            response = _requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            return response.json()

        except _requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None

            if status == 401:
                raise ValueError(
                    "Groq auth failed (401). Verify grok_api_key in Agents/config.json "
                    "or set the GROQ_API_KEY environment variable."
                ) from exc

            if status == 429:
                retry_after = 0
                if exc.response is not None:
                    raw = str(exc.response.headers.get("Retry-After", "")).strip()
                    if raw.isdigit():
                        retry_after = int(raw)
                if attempt < max_retries:
                    sleep_secs = retry_after if retry_after > 0 else base_delay * (2 ** attempt)
                    time.sleep(min(sleep_secs, 15))
                    continue
                hint = f" Retry after {retry_after}s." if retry_after > 0 else ""
                raise ValueError(f"Groq API rate-limited (HTTP 429).{hint}") from exc

            if status in (500, 502, 503, 504) and attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue

            raise

        except _requests.exceptions.RequestException as exc:
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise ValueError(f"Groq API request failed: {exc}") from exc

    raise RuntimeError("grok_chat_completion: exhausted retries unexpectedly")


# =========================================================
# Load app7.1.py as a sub-module and inject Grok backend
# =========================================================

_app71_path = os.path.join(_CUSTOMUI_DIR, "app7.1.py")

_spec = importlib.util.spec_from_file_location("_agent1_core", _app71_path)
_app71 = importlib.util.module_from_spec(_spec)
sys.modules["_agent1_core"] = _app71

# Execute app7.1.py — config_manager already points to Agents/config.json
_spec.loader.exec_module(_app71)

# ----------------------------------------------------------
# Swap every Copilot reference inside the loaded module for
# the Groq equivalents.  Module globals are resolved at call
# time in Python, so patching here affects all callers inside
# _app71 without needing to touch app7.1.py.
# ----------------------------------------------------------
_app71.COPILOT_BASE_URL        = GROK_BASE_URL
_app71.get_copilot_token       = get_grok_token
_app71.get_models_base_url     = get_grok_base_url
_app71.get_copilot_model       = get_grok_model
_app71.copilot_chat_completion = grok_chat_completion

# Disable the OpenAI fallback path — Agent1 uses Groq only.
_app71._try_openai_fallback = lambda payload: None

# Replace hardcoded Copilot error messages with Groq equivalents.
_orig_generate_dynamic_sql = _app71.generate_dynamic_sql
def _grok_generate_dynamic_sql(history, user_input):
    if not get_grok_token():
        return {"sql": "", "explanation": "Groq API key is not configured. Set grok_api_key in Agents/config.json."}
    return _orig_generate_dynamic_sql(history, user_input)
_app71.generate_dynamic_sql = _grok_generate_dynamic_sql

_orig_general_chat = _app71.generate_general_chat_response
def _grok_general_chat(history, user_input):
    if not get_grok_token():
        return "Set grok_api_key in Agents/config.json to enable AI responses."
    return _orig_general_chat(history, user_input)
_app71.generate_general_chat_response = _grok_general_chat

# Ensure the config GET endpoint masks the Groq API key.
_app71._SECRET_KEYS = (_app71._SECRET_KEYS - {"openai_api_key"}) | {"grok_api_key"}

# Expose the Flask application object at Agent1 module level.
app = _app71.app

# ----------------------------------------------------------
# Point Flask to Agents/static so HTML files are self-contained
# in this folder and index7.1.html is the default UI page.
# ----------------------------------------------------------
_agents_static = os.path.join(_AGENT_DIR, "static")
app.static_folder = _agents_static
app.static_url_path = "/static"

from flask import send_from_directory, request, session, jsonify
import hmac

@app.route("/", endpoint="agent1_index")
def _agent1_index():
    return send_from_directory(_agents_static, "index7.1.html")

@app.route("/dashboard", endpoint="agent1_dashboard")
def _agent1_dashboard():
    return send_from_directory(_agents_static, "dashboard.html")

# Override login to use login_username / login_password from Agents/config.json
# instead of the api_user / api_password that app7.1.py defaults to.
def _agent1_login():
    data = request.get_json(force=True) or {}
    username = data.get("username", "").strip()
    password = str(data.get("password", ""))

    stored_username = str(_cm.get_config_value("login_username", "") or "").strip()
    stored_password = str(_cm.get_config_value("login_password", "") or "")

    user_ok = hmac.compare_digest(username.encode(), stored_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), stored_password.encode())

    if user_ok and pass_ok:
        session.permanent = True
        session["authenticated"] = True
        session["user"] = username
        session["auth_at"] = int(time.time())
        return jsonify({"ok": True, "message": "Login successful", "user": username})
    return jsonify({"ok": False, "error": "Invalid username or password"}), 401

app.view_functions["login"] = _agent1_login

# =========================================================
# Entry point
# =========================================================

if __name__ == "__main__":
    host        = str(_cm.get_config_value("app_host", "0.0.0.0"))
    port        = int(_cm.get_config_value("app_port", 5001))
    debug       = bool(_cm.get_config_value("app_debug", False))
    use_reloader = bool(_cm.get_config_value("app_use_reloader", False))
    print(f"Agent1 (Groq AI / {get_grok_model()}) running on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
