"""
EBS to Oracle APEX AI Service Backend

Purpose:
- Expose sales order operations as stateless APIs for Oracle APEX
- Support AI-assisted intent + dynamic SQL generation for ERP order data
- Avoid chatbot-specific UI/session flow

Key features:
- API-key authentication (APEX friendly)
- CORS for APEX apps
- Oracle EBS REST operation endpoints (get/create orders)
- AI dynamic SQL endpoint for analytics/reporting
"""

import hmac
import json
import os
import re
import secrets
import ssl
import time
from functools import lru_cache

import requests
import urllib3
from flask import Flask, Response, jsonify, request
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context

try:
    from flask_cors import CORS
    FLASK_CORS_AVAILABLE = True
except Exception:
    CORS = None
    FLASK_CORS_AVAILABLE = False

import config_manager
import pydantic_ai_adapter
import system_prompts

try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except Exception:
    ORACLEDB_AVAILABLE = False
    oracledb = None


# =========================================================
# App / Config
# =========================================================

app_config = config_manager.load_config()
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)


def _allowed_origins():
    raw = config_manager.get_config_value("apex_allowed_origins", "*")
    if isinstance(raw, list):
        vals = [str(v).strip() for v in raw if str(v).strip()]
        return vals or ["*"]
    txt = str(raw or "").strip()
    if not txt:
        return ["*"]
    if "," in txt:
        vals = [v.strip() for v in txt.split(",") if v.strip()]
        return vals or ["*"]
    return [txt]


_ALLOWED_ORIGINS = _allowed_origins()

if FLASK_CORS_AVAILABLE:
    CORS(
        app,
        resources={r"/api/*": {"origins": _ALLOWED_ORIGINS if _ALLOWED_ORIGINS != ["*"] else "*"}},
        supports_credentials=False,
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )


@app.after_request
def _cors_fallback(resp):
    if FLASK_CORS_AVAILABLE:
        return resp
    origin = request.headers.get("Origin", "")
    if _ALLOWED_ORIGINS == ["*"]:
        resp.headers["Access-Control-Allow-Origin"] = origin or "*"
    elif origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.route("/api/<path:_p>", methods=["OPTIONS"])
def _options(_p):
    return Response(status=204)


if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# =========================================================
# Auth Helpers (APEX API Key)
# =========================================================


def _collect_api_keys():
    keys = set()

    cfg_keys = config_manager.get_config_value("apex_api_keys", "")
    if isinstance(cfg_keys, list):
        for k in cfg_keys:
            val = str(k or "").strip()
            if val:
                keys.add(val)
    else:
        for k in str(cfg_keys or "").split(","):
            val = k.strip()
            if val:
                keys.add(val)

    single = str(config_manager.get_config_value("apex_api_key", "") or "").strip()
    if single:
        keys.add(single)

    env_key = str(os.getenv("APEX_API_KEY", "")).strip()
    if env_key:
        keys.add(env_key)

    return keys


def _incoming_api_key():
    key = str(request.headers.get("X-API-Key", "") or "").strip()
    if key:
        return key
    auth = str(request.headers.get("Authorization", "") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def require_api_key(f):
    def wrapped(*args, **kwargs):
        configured = _collect_api_keys()
        incoming = _incoming_api_key()
        if not configured:
            return jsonify({"error": "API key is not configured on server."}), 401
        if not incoming:
            return jsonify({"error": "Missing API key."}), 401

        incoming_b = incoming.encode()
        for key in configured:
            if hmac.compare_digest(incoming_b, key.encode()):
                return f(*args, **kwargs)
        return jsonify({"error": "Invalid API key."}), 401

    wrapped.__name__ = f.__name__
    return wrapped


# =========================================================
# Core Integrations
# =========================================================


def _tls_verify_enabled():
    if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
        return False
    cfg_val = app_config.get("verify_ssl", True)
    if isinstance(cfg_val, bool):
        return cfg_val
    return str(cfg_val).strip().lower() not in ("false", "0", "no")


class ForceTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        if not _tls_verify_enabled():
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def build_session():
    req_session = requests.Session()
    req_session.mount("https://", ForceTLSAdapter())
    req_session.auth = HTTPBasicAuth(app_config.get("api_user", ""), app_config.get("api_password", ""))
    req_session.verify = _tls_verify_enabled()
    return req_session


oracle_initialized = False


def initialize_oracle():
    global oracle_initialized
    if oracle_initialized:
        return
    if not ORACLEDB_AVAILABLE:
        raise RuntimeError("oracledb is not installed. Run: pip install oracledb")

    client_path = app_config.get("oracle_client_path")
    try:
        if client_path and os.path.exists(client_path):
            oracledb.init_oracle_client(lib_dir=client_path)
        else:
            try:
                oracledb.init_oracle_client()
            except Exception:
                pass
    except Exception as exc:
        print(f"Oracle Client Init Warning: {exc}")

    oracle_initialized = True


def get_db_connection():
    initialize_oracle()

    dsn = (
        "(DESCRIPTION="
        "(ADDRESS=(PROTOCOL=TCP)"
        f"(HOST={app_config['db_host']})"
        f"(PORT={app_config['db_port']}))"
        "(CONNECT_DATA="
        f"(SERVICE_NAME={app_config['db_service']})))"
    )

    return oracledb.connect(
        user=app_config["db_user"],
        password=app_config["db_password"],
        dsn=dsn,
    )


def execute_query(sql, params=None):
    params = params or {}
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col[0] for col in (cur.description or [])]
            rows = cur.fetchall() if columns else []
    return [dict(zip(columns, row)) for row in rows]


# =========================================================
# Copilot / AI Helpers
# =========================================================

COPILOT_BASE_URL = "https://models.inference.ai.azure.com"


def get_copilot_token():
    token = (
        config_manager.get_config_value("github_copilot_token")
        or config_manager.get_config_value("github_token")
        or config_manager.get_config_value("openai_api_key")
        or os.getenv("GITHUB_COPILOT_TOKEN")
        or os.getenv("GITHUB_TOKEN")
    )
    return str(token or "").strip()


def get_models_base_url():
    return str(config_manager.get_config_value("github_models_base_url") or COPILOT_BASE_URL).rstrip("/")


def get_copilot_model():
    return config_manager.get_config_value("copilot_model") or config_manager.get_config_value("openai_model") or "gpt-4o"


def get_llm_backend():
    backend = str(config_manager.get_config_value("llm_backend", "legacy") or "legacy").strip().lower()
    return "pydantic_ai" if backend in ("pydantic_ai", "pydantic-ai", "pydanticai") else "legacy"


def build_history_string(history):
    lines = []
    for msg in (history or [])[-8:]:
        lines.append(f"{msg.get('role', '')}: {msg.get('content', '')}")
    return "\n".join(lines)


def copilot_chat_completion(messages, temperature=0, max_tokens=None):
    token = get_copilot_token()
    if not token:
        raise ValueError("GitHub Copilot token is not configured")

    payload = {"model": get_copilot_model(), "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    url = f"{get_models_base_url()}/chat/completions"
    max_retries = int(config_manager.get_config_value("copilot_max_retries", 2) or 2)
    base_delay = float(config_manager.get_config_value("copilot_retry_base_seconds", 1.5) or 1.5)

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "api-key": token,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 401:
                raise ValueError("AI auth failed (401). Update github_copilot_token in config.") from exc
            if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(min(base_delay * (2 ** attempt), 15))
                continue
            raise
        except requests.exceptions.RequestException as exc:
            if attempt < max_retries:
                time.sleep(min(base_delay * (2 ** attempt), 15))
                continue
            raise ValueError(f"AI service request failed: {exc}") from exc


@lru_cache(maxsize=1)
def get_order_schema_context():
    static_context = {
        "OE_ORDER_HEADERS_ALL": [
            "HEADER_ID", "ORDER_NUMBER", "ORDERED_DATE", "CREATION_DATE", "FLOW_STATUS_CODE",
            "CUST_PO_NUMBER", "SOLD_TO_ORG_ID", "SHIP_TO_ORG_ID", "INVOICE_TO_ORG_ID",
            "TRANSACTIONAL_CURR_CODE", "PAYMENT_TERM_ID", "PRICE_LIST_ID", "ORG_ID",
        ],
        "OE_ORDER_LINES_ALL": [
            "LINE_ID", "HEADER_ID", "LINE_NUMBER", "FLOW_STATUS_CODE", "INVENTORY_ITEM_ID",
            "ORDERED_ITEM", "ORDERED_QUANTITY", "ORDER_QUANTITY_UOM", "UNIT_LIST_PRICE",
            "UNIT_SELLING_PRICE", "SHIP_FROM_ORG_ID", "ORG_ID",
        ],
        "HZ_CUST_ACCOUNTS": ["CUST_ACCOUNT_ID", "PARTY_ID", "ACCOUNT_NUMBER", "STATUS"],
        "HZ_PARTIES": ["PARTY_ID", "PARTY_NAME", "PARTY_NUMBER", "STATUS"],
        "MTL_SYSTEM_ITEMS_B": ["INVENTORY_ITEM_ID", "SEGMENT1", "DESCRIPTION", "ORGANIZATION_ID"],
    }

    lines = ["Order-domain tables and columns:"]
    for table_name in sorted(static_context.keys()):
        cols = static_context[table_name]
        lines.append(f"- {table_name}: {', '.join(cols)}")
    return "\n".join(lines)


def ai_extract_intent(history, user_input):
    lower = str(user_input or "").lower().strip()

    if not get_copilot_token():
        # Minimal deterministic fallback for APEX workflows.
        if re.search(r"\b(create|new|place)\b.*\border\b", lower):
            return {"action": "create"}
        m = re.search(r"\border\s*#?\s*(\d{4,})\b", lower)
        if m:
            return {"action": "get", "order_number": int(m.group(1))}
        if "customer" in lower and "order" in lower:
            return {"action": "get"}
        return {"action": "dynamic_query"}

    try:
        history_str = build_history_string(history)
        system_prompt = system_prompts.INTENT_EXTRACTION_SYSTEM_PROMPT

        if get_llm_backend() == "pydantic_ai":
            intent = pydantic_ai_adapter.extract_intent(
                history_str=history_str,
                user_input=user_input,
                system_prompt=system_prompt,
                chat_completion=copilot_chat_completion,
                model_name=get_copilot_model(),
                base_url=get_models_base_url(),
                token=get_copilot_token(),
                user_prompt_builder=system_prompts.build_intent_user_prompt,
            )
        else:
            user_prompt = system_prompts.build_intent_user_prompt(history_str, user_input)
            response = copilot_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            content = response["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
            intent = json.loads(content)

        if "action" not in intent:
            intent["action"] = "dynamic_query"
        return intent
    except Exception:
        return {"action": "dynamic_query"}


def generate_dynamic_sql(history, user_input):
    if not get_copilot_token():
        return {
            "sql": "",
            "explanation": "GitHub Copilot token is missing. Update github_copilot_token in config.json.",
        }

    try:
        history_str = build_history_string(history)
        base_system_prompt = system_prompts.DYNAMIC_SQL_GENERATION_SYSTEM_PROMPT
        schema_context = (
            "STRICT OPERATOR RULES:\n"
            "1) Preserve user operators exactly when present: IN, NOT IN, LIKE, NOT LIKE, BETWEEN, >, <, >=, <=, =, !=, <>.\n"
            "2) Apply filters to correct order-domain columns; do not drop filters unless impossible.\n"
            "3) Return only JSON with keys: sql, explanation.\n\n"
            + get_order_schema_context()
        )

        if get_llm_backend() == "pydantic_ai":
            return pydantic_ai_adapter.generate_dynamic_sql(
                history_str=history_str,
                user_input=user_input,
                system_prompt=base_system_prompt,
                schema_context=schema_context,
                chat_completion=copilot_chat_completion,
                model_name=get_copilot_model(),
                base_url=get_models_base_url(),
                token=get_copilot_token(),
                user_prompt_builder=system_prompts.build_sql_generation_user_prompt,
            )

        user_prompt = (
            system_prompts.build_sql_generation_user_prompt(history_str, user_input)
            + "\n\n"
            + get_order_schema_context()
        )
        response = copilot_chat_completion(
            messages=[
                {"role": "system", "content": base_system_prompt + "\n\n" + schema_context},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )

        content = response["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as exc:
        return {"sql": "", "explanation": f"AI SQL Generation Error: {exc}"}


def is_safe_select_query(sql):
    sql_upper = str(sql or "").upper().strip()
    if not sql_upper.startswith("SELECT"):
        return False

    dangerous_keywords = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b", r"\bALTER\b",
        r"\bTRUNCATE\b", r"\bMERGE\b", r"\bCREATE\b", r"\bEXEC\b", r"\bEXECUTE\b",
        r"\bBEGIN\b", r"\bDECLARE\b", r"\bGRANT\b", r"\bREVOKE\b", r"\bCOMMIT\b", r"\bROLLBACK\b",
        r"\bUTL_FILE\b", r"\bUTL_HTTP\b", r"\bUTL_TCP\b", r"\bDBMS_\w+",
    ]
    for pattern in dangerous_keywords:
        if re.search(pattern, sql_upper):
            return False

    if re.search(r";\s*\S", sql_upper):
        return False
    if re.search(r"(/\*)|(\*/)|(--)", sql_upper):
        return False
    if re.search(r"\bUNION\b", sql_upper):
        return False

    return True


# =========================================================
# EBS REST Operations
# =========================================================


def parse_create_order_response(data):
    output = data.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {}) if isinstance(data, dict) else {}
    if not output and isinstance(data, dict):
        output = data.get("OutputParameters", data)

    header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
    return_status = output.get("X_RETURN_STATUS", output.get("RETURN_STATUS", ""))
    return {
        "order_number": header.get("ORDER_NUMBER", ""),
        "header_id": header.get("HEADER_ID", ""),
        "return_status": return_status,
        "flow_status": header.get("FLOW_STATUS_CODE", ""),
        "cust_po_number": header.get("CUST_PO_NUMBER", ""),
        "msg_data": output.get("X_MSG_DATA", output.get("MSG_DATA", "")),
        "success": return_status in ("S", "s"),
    }


def parse_customer_orders(data):
    output = data.get("OutputParameters", data) if isinstance(data, dict) else {}
    rows_raw = output.get("X_RESULT") or output.get("P_RESULT") or output.get("ResultSet") or output

    if isinstance(rows_raw, dict):
        inner = rows_raw.get("X_RESULT_ITEM") or rows_raw.get("P_RESULT_ITEM") or rows_raw.get("Row") or rows_raw.get("ROW")
        if inner is None:
            rows = [rows_raw]
        elif isinstance(inner, dict):
            rows = [inner]
        else:
            rows = list(inner)
    elif isinstance(rows_raw, list):
        rows = rows_raw
    else:
        rows = []

    return {"rows": rows, "count": len(rows), "raw_keys": list(rows[0].keys()) if rows else []}


def parse_order_response(data):
    output = data.get("OutputParameters", data) if isinstance(data, dict) else {}
    header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
    lines_raw = output.get("X_LINE_TBL", output.get("LINE_TBL", {}))

    if isinstance(lines_raw, dict):
        items = lines_raw.get("X_LINE_TBL_ITEM", lines_raw.get("LINE_TBL_ITEM", []))
        if isinstance(items, dict):
            items = [items]
    elif isinstance(lines_raw, list):
        items = lines_raw
    else:
        items = []

    lines = []
    for item in items:
        lines.append(
            {
                "Line": item.get("LINE_NUMBER", ""),
                "Item": item.get("ORDERED_ITEM", ""),
                "Qty": item.get("ORDERED_QUANTITY", ""),
                "UOM": item.get("ORDER_QUANTITY_UOM", ""),
                "Unit Price": item.get("UNIT_SELLING_PRICE", ""),
                "Status": item.get("FLOW_STATUS_CODE", ""),
            }
        )

    return {
        "order_number": header.get("ORDER_NUMBER", ""),
        "status": header.get("FLOW_STATUS_CODE", ""),
        "ordered_date": header.get("ORDERED_DATE", ""),
        "currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
        "lines": lines,
    }


def get_order(order_number):
    urls = get_service_urls()
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": get_rest_header(),
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_ORDER_NUMBER": int(order_number),
            },
        }
    }

    req_session = build_session()
    resp = req_session.post(
        urls["get_order"],
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps(payload),
        timeout=180,
    )
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def get_customer_orders(customer_name):
    urls = get_service_urls()
    req_session = build_session()
    resp = req_session.get(
        urls["cust_so_dtls"],
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        params={"P_CUSTOMER_NAME": customer_name},
        timeout=180,
    )
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def create_order(order_data):
    urls = get_service_urls()
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": get_rest_header(),
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG": "N",
                    "CUST_PO_NUMBER": order_data.get("cust_po_number", ""),
                    "ORDER_TYPE_ID": int(order_data.get("order_type_id", config_manager.get_order_type_id())),
                    "ORG_ID": int(config_manager.get_org_id()),
                    "PAYMENT_TERM_ID": int(order_data.get("payment_term_id", config_manager.get_default_payment_term_id())),
                    "PRICE_LIST_ID": int(order_data.get("price_list_id", config_manager.get_default_price_list_id())),
                    "SALESREP_ID": int(order_data.get("salesrep_id", config_manager.get_default_salesrep_id())),
                    "SHIP_TO_ORG_ID": int(order_data.get("ship_to_org_id", config_manager.get_default_ship_to_org_id())),
                    "SOLD_TO_ORG_ID": int(order_data.get("sold_to_org_id", config_manager.get_default_sold_to_org_id())),
                    "TRANSACTIONAL_CURR_CODE": order_data.get("currency", "USD"),
                    "OPERATION": "CREATE",
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID": int(order_data.get("inventory_item_id", config_manager.get_default_inventory_item_id())),
                        "ORDERED_ITEM": order_data.get("ordered_item", ""),
                        "ORDERED_QUANTITY": float(order_data.get("ordered_quantity", 1)),
                        "PAYMENT_TERM_ID": int(order_data.get("payment_term_id", config_manager.get_default_payment_term_id())),
                        "PRICE_LIST_ID": int(order_data.get("price_list_id", config_manager.get_default_price_list_id())),
                        "UNIT_LIST_PRICE": float(order_data.get("unit_list_price", 0)),
                        "UNIT_SELLING_PRICE": float(order_data.get("unit_selling_price", 0)),
                        "OPERATION": "CREATE",
                    }
                },
                "P_RTRIM_DATA": "n",
                "P_OPERATING_UNIT": config_manager.get_operating_unit(),
                "P_DEBUG_LEVEL": 10,
            },
        }
    }

    req_session = build_session()
    resp = req_session.post(
        urls["process_order"],
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps(payload),
        timeout=180,
    )
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


# =========================================================
# API Endpoints (APEX Service Layer)
# =========================================================


@app.route("/api/health", methods=["GET"])
def api_health():
    db_ok = False
    db_error = ""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM DUAL")
                cur.fetchone()
        db_ok = True
    except Exception as exc:
        db_error = str(exc)

    return jsonify(
        {
            "ok": True,
            "service": "ebs-to-apex",
            "time": time.time(),
            "db_ok": db_ok,
            "db_error": db_error,
            "apex_api_key_configured": len(_collect_api_keys()) > 0,
        }
    )


@app.route("/api/apex/order/get", methods=["POST"])
@require_api_key
def api_apex_get_order():
    body = request.get_json(force=True) or {}
    order_number = body.get("order_number")
    customer_name = body.get("customer_name")

    if order_number:
        try:
            raw = get_order(int(order_number))
            parsed = parse_order_response(raw)
            return jsonify({"ok": True, "type": "order", "data": parsed})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    if customer_name:
        try:
            raw = get_customer_orders(str(customer_name))
            parsed = parse_customer_orders(raw)
            parsed["customer_name"] = str(customer_name)
            return jsonify({"ok": True, "type": "customer_orders", "data": parsed})
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": False, "error": "Provide order_number or customer_name."}), 400


@app.route("/api/apex/order/create", methods=["POST"])
@require_api_key
def api_apex_create_order():
    body = request.get_json(force=True) or {}
    try:
        raw = create_order(body)
        parsed = parse_create_order_response(raw)
        return jsonify({"ok": True, "type": "create_order", "data": parsed})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.route("/api/apex/ai/intent", methods=["POST"])
@require_api_key
def api_apex_ai_intent():
    body = request.get_json(force=True) or {}
    message = str(body.get("message", "") or "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"ok": False, "error": "message is required."}), 400

    intent = ai_extract_intent(history, message)
    return jsonify({"ok": True, "intent": intent})


@app.route("/api/apex/ai/query", methods=["POST"])
@require_api_key
def api_apex_ai_query():
    body = request.get_json(force=True) or {}
    message = str(body.get("message", "") or "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"ok": False, "error": "message is required."}), 400

    ai_result = generate_dynamic_sql(history, message)
    sql_query = re.sub(r"[;\s/]+$", "", str(ai_result.get("sql", "")).strip())
    explanation = ai_result.get("explanation", "Query executed successfully.")

    if not sql_query:
        return jsonify({"ok": False, "error": explanation, "sql": ""}), 400
    if not is_safe_select_query(sql_query):
        return jsonify({"ok": False, "error": "Security error: only safe SELECT queries are allowed.", "sql": sql_query}), 400

    try:
        results = execute_query(sql_query)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"SQL execution error: {exc}", "sql": sql_query}), 400

    columns = list(results[0].keys()) if results else []
    rows = [[str(row.get(col, "")) for col in columns] for row in results] if results else []

    return jsonify(
        {
            "ok": True,
            "sql": sql_query,
            "explanation": explanation,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    )


@app.route("/api/apex/ai/route", methods=["POST"])
@require_api_key
def api_apex_ai_route():
    """
    Single APEX endpoint:
    - Uses AI intent to route into order get/create/dynamic query operations.
    """
    body = request.get_json(force=True) or {}
    message = str(body.get("message", "") or "").strip()
    history = body.get("history", [])

    if not message:
        return jsonify({"ok": False, "error": "message is required."}), 400

    intent = ai_extract_intent(history, message)
    action = str(intent.get("action", "dynamic_query")).lower()

    if action == "create":
        return jsonify(
            {
                "ok": True,
                "action": "create",
                "next": "call /api/apex/order/create with order payload",
                "intent": intent,
            }
        )

    if action == "get":
        if intent.get("order_number"):
            try:
                raw = get_order(int(intent.get("order_number")))
                parsed = parse_order_response(raw)
                return jsonify({"ok": True, "action": "get", "type": "order", "data": parsed, "intent": intent})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc), "intent": intent}), 400

        if intent.get("customer_name"):
            try:
                raw = get_customer_orders(str(intent.get("customer_name")))
                parsed = parse_customer_orders(raw)
                parsed["customer_name"] = str(intent.get("customer_name"))
                return jsonify({"ok": True, "action": "get", "type": "customer_orders", "data": parsed, "intent": intent})
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc), "intent": intent}), 400

    # Default route: dynamic SQL
    ai_result = generate_dynamic_sql(history, message)
    sql_query = re.sub(r"[;\s/]+$", "", str(ai_result.get("sql", "")).strip())
    explanation = ai_result.get("explanation", "Query executed successfully.")

    if not sql_query:
        return jsonify({"ok": False, "error": explanation, "intent": intent}), 400
    if not is_safe_select_query(sql_query):
        return jsonify({"ok": False, "error": "Security error: only safe SELECT queries are allowed.", "intent": intent}), 400

    try:
        results = execute_query(sql_query)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"SQL execution error: {exc}", "sql": sql_query, "intent": intent}), 400

    columns = list(results[0].keys()) if results else []
    rows = [[str(row.get(col, "")) for col in columns] for row in results] if results else []

    return jsonify(
        {
            "ok": True,
            "action": "dynamic_query",
            "intent": intent,
            "sql": sql_query,
            "explanation": explanation,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        }
    )


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":
    host = str(config_manager.get_config_value("app_host", "0.0.0.0"))
    port = int(config_manager.get_config_value("app_port", 5000))
    debug = bool(config_manager.get_config_value("app_debug", False))
    use_reloader = bool(config_manager.get_config_value("app_use_reloader", False))
    print(f"EBS-to-APEX AI service running on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
