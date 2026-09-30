"""
Sales Order Chatbot - Flask backend with dynamic AI-SQL generation,
order operations, and app5-compatible email formatting.

Oracle APEX compatibility updates:
- Stateless API key auth for APEX Web Source calls
- Session login still supported for browser clients
- CORS support for APEX-hosted UIs
- Health endpoint for APEX integration checks
"""

import datetime
import hmac
import html as html_lib
import io
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache, wraps

import requests
import urllib3
from flask import Flask, Response, jsonify, request, send_from_directory, session
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

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except Exception:
    openpyxl = None
    OPENPYXL_AVAILABLE = False


app_config = config_manager.load_config()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)


def _get_allowed_origins():
    raw = config_manager.get_config_value("apex_allowed_origins", "*")
    if isinstance(raw, list):
        vals = [str(v).strip() for v in raw if str(v).strip()]
        return vals or ["*"]
    txt = str(raw or "").strip()
    if not txt:
        return ["*"]
    return [p.strip() for p in txt.split(",") if p.strip()] if "," in txt else [txt]


if FLASK_CORS_AVAILABLE:
    CORS(
        app,
        resources={r"/api/*": {"origins": _get_allowed_origins()}},
        supports_credentials=True,
        methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )


@app.after_request
def add_cors_headers(resp):
    if FLASK_CORS_AVAILABLE:
        return resp
    origin = request.headers.get("Origin", "*")
    allowed = _get_allowed_origins()
    if allowed == ["*"]:
        resp.headers["Access-Control-Allow-Origin"] = origin
    elif origin in allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp


@app.route("/api/<path:_rest>", methods=["OPTIONS"])
def api_options(_rest):
    return Response(status=204)


if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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


def get_org_id():
    return config_manager.get_org_id()


def get_rest_header():
    return config_manager.get_rest_header()


def get_service_urls():
    return config_manager.get_service_urls()


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
        print(f"Oracle Client init warning: {exc}")
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
            columns = [c[0] for c in (cur.description or [])]
            rows = cur.fetchall() if columns else []
    return [dict(zip(columns, row)) for row in rows]


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


def copilot_chat_completion(messages, temperature=0, max_tokens=None):
    token = get_copilot_token()
    if not token:
        raise ValueError("GitHub Copilot token is not configured")

    payload = {"model": get_copilot_model(), "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    url = f"{get_models_base_url()}/chat/completions"
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


def build_history_string(history):
    lines = []
    for msg in (history or [])[-8:]:
        lines.append(f"{msg.get('role', '')}: {msg.get('content', '')}")
    return "\n".join(lines)


def generate_general_chat_response(history, user_input):
    if not get_copilot_token():
        return "Set github_copilot_token in config.json to enable general AI responses."

    system_prompt = getattr(system_prompts, "GENERAL_CHAT_SYSTEM_PROMPT", "You are a helpful AI assistant.")
    messages = [{"role": "system", "content": system_prompt}]
    for msg in (history or [])[-10:]:
        role = str(msg.get("role", "")).strip().lower()
        if role in ("user", "assistant", "system") and str(msg.get("content", "")).strip():
            messages.append({"role": role, "content": str(msg.get("content", "")).strip()})
    messages.append({"role": "user", "content": str(user_input or "")})

    try:
        res = copilot_chat_completion(messages=messages, temperature=0.7, max_tokens=700)
        return res["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"AI response error: {exc}"


def ai_extract_intent(history, user_input):
    lower = str(user_input or "").lower().strip()
    if lower in ("hi", "hello", "hey", "help", "commands", "?"):
        return {"action": "help"}

    email_match = re.search(r"(?:send|email|mail)\s+(?:to\s+)?([\w.+-]+@[\w.-]+\.\w+)", str(user_input or ""), re.IGNORECASE)
    if email_match:
        return {"action": "email", "email_address": email_match.group(1)}

    if not get_copilot_token():
        if "create" in lower and "order" in lower:
            return {"action": "create"}
        if "orders" in lower and "customer" in lower:
            return {"action": "get"}
        m = re.search(r"\border\s*#?\s*(\d{4,})\b", lower)
        if m:
            return {"action": "get", "order_number": int(m.group(1))}
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
            res = copilot_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            content = res["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
            intent = json.loads(content)
        if "action" not in intent:
            intent["action"] = "dynamic_query"
        return intent
    except Exception:
        return {"action": "dynamic_query"}


@lru_cache(maxsize=1)
def get_order_schema_context():
    tables = {
        "OE_ORDER_HEADERS_ALL": ["HEADER_ID", "ORDER_NUMBER", "ORDERED_DATE", "CREATION_DATE", "FLOW_STATUS_CODE", "CUST_PO_NUMBER", "SOLD_TO_ORG_ID", "SHIP_TO_ORG_ID", "ORG_ID"],
        "OE_ORDER_LINES_ALL": ["LINE_ID", "HEADER_ID", "LINE_NUMBER", "FLOW_STATUS_CODE", "INVENTORY_ITEM_ID", "ORDERED_ITEM", "ORDERED_QUANTITY", "UNIT_SELLING_PRICE", "ORG_ID"],
        "HZ_CUST_ACCOUNTS": ["CUST_ACCOUNT_ID", "PARTY_ID", "ACCOUNT_NUMBER", "STATUS"],
        "HZ_PARTIES": ["PARTY_ID", "PARTY_NAME", "PARTY_NUMBER", "STATUS"],
    }
    lines = ["Order-domain tables and columns:"]
    for table, cols in tables.items():
        lines.append(f"- {table}: {', '.join(cols)}")
    return "\n".join(lines)


def generate_dynamic_sql(history, user_input):
    if not get_copilot_token():
        return {"sql": "", "explanation": "GitHub Copilot token is missing."}
    try:
        history_str = build_history_string(history)
        base_system_prompt = system_prompts.DYNAMIC_SQL_GENERATION_SYSTEM_PROMPT
        schema_context = (
            "STRICT OPERATOR RULES:\n"
            "1) Preserve IN, NOT IN, LIKE, NOT LIKE, BETWEEN, >, <, >=, <=, =, !=, <>.\n"
            "2) Keep all user filters unless impossible.\n"
            "3) Return only JSON keys: sql, explanation.\n\n"
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

        user_prompt = system_prompts.build_sql_generation_user_prompt(history_str, user_input) + "\n\n" + schema_context
        res = copilot_chat_completion(
            messages=[
                {"role": "system", "content": base_system_prompt + "\n\n" + schema_context},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
        content = res["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as exc:
        return {"sql": "", "explanation": f"AI SQL generation error: {exc}"}


def is_safe_select_query(sql):
    sql_upper = str(sql or "").upper().strip()
    if not sql_upper.startswith("SELECT"):
        return False
    dangerous = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b", r"\bALTER\b",
        r"\bTRUNCATE\b", r"\bMERGE\b", r"\bCREATE\b", r"\bEXEC\b", r"\bEXECUTE\b",
        r"\bBEGIN\b", r"\bDECLARE\b", r"\bGRANT\b", r"\bREVOKE\b", r"\bCOMMIT\b", r"\bROLLBACK\b",
        r"\bUTL_FILE\b", r"\bUTL_HTTP\b", r"\bUTL_TCP\b", r"\bDBMS_\w+",
    ]
    for pat in dangerous:
        if re.search(pat, sql_upper):
            return False
    if re.search(r";\s*\S", sql_upper):
        return False
    if re.search(r"(/\*)|(\*/)|(--)", sql_upper):
        return False
    if re.search(r"\bUNION\b", sql_upper):
        return False
    return True


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
    s = build_session()
    resp = s.post(
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
    s = build_session()
    resp = s.get(
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
                    "ORG_ID": int(get_org_id()),
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
    s = build_session()
    resp = s.post(
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


def parse_create_order_response(data):
    output = data.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {}) if isinstance(data, dict) else {}
    if not output and isinstance(data, dict):
        output = data.get("OutputParameters", data)
    header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
    ret = output.get("X_RETURN_STATUS", output.get("RETURN_STATUS", ""))
    return {
        "order_number": header.get("ORDER_NUMBER", ""),
        "header_id": header.get("HEADER_ID", ""),
        "return_status": ret,
        "flow_status": header.get("FLOW_STATUS_CODE", ""),
        "cust_po_number": header.get("CUST_PO_NUMBER", ""),
        "success": ret in ("S", "s"),
        "msg_data": output.get("X_MSG_DATA", output.get("MSG_DATA", "")),
    }


def parse_customer_orders(data):
    output = data.get("OutputParameters", data) if isinstance(data, dict) else {}
    rows_raw = output.get("X_RESULT") or output.get("P_RESULT") or output.get("ResultSet") or output
    if isinstance(rows_raw, dict):
        inner = rows_raw.get("X_RESULT_ITEM") or rows_raw.get("P_RESULT_ITEM") or rows_raw.get("Row") or rows_raw.get("ROW")
        rows = [rows_raw] if inner is None else ([inner] if isinstance(inner, dict) else list(inner))
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

    header_details = {
        "Order Number": header.get("ORDER_NUMBER", ""),
        "Header ID": header.get("HEADER_ID", ""),
        "Customer PO": header.get("CUST_PO_NUMBER", ""),
        "Flow Status": header.get("FLOW_STATUS_CODE", ""),
        "Ordered Date": header.get("ORDERED_DATE", ""),
        "Currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
    }
    return {
        "order_number": header.get("ORDER_NUMBER", ""),
        "status": header.get("FLOW_STATUS_CODE", ""),
        "ordered_date": header.get("ORDERED_DATE", ""),
        "currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
        "lines": lines,
        "header_details": header_details,
    }


def _build_email_layout(cname, report_type, ai_summary, table_html):
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    cname_s = html_lib.escape(str(cname))
    report_type_s = html_lib.escape(str(report_type))
    ai_summary_s = html_lib.escape(str(ai_summary))
    return f"""
    <div style='font-family: Arial, sans-serif; max-width: 860px; margin: auto; color: #000; padding: 12px;'>
      <h3 style='margin-top:0;'>Header Details</h3>
      <ul style='padding-left:20px;'>
        <li>Customer Name: {cname_s}</li>
        <li>Date of Report: {report_date}</li>
        <li>Statement Period: {report_type_s}</li>
      </ul>
      <hr>
      <h3>Executive Summary</h3>
      <p>{ai_summary_s}</p>
      <hr>
      <h3>Order Detail Table</h3>
      {table_html}
      <hr>
      <ul style='padding-left:20px;'>
        <li>Support contact: erp.support@centroid.com</li>
        <li>Do-not-reply notice: Please do not reply directly to this email.</li>
      </ul>
    </div>
    """


def _generate_dynamic_table_email_html(columns, rows, explanation=""):
    th = "background:#003366;color:#fff;padding:8px;text-align:left;font-size:0.82rem;"
    td = "padding:8px;border-bottom:1px solid #e5e7eb;font-size:0.82rem;"
    table = "<table style='width:100%;border-collapse:collapse;'><tr>"
    for col in columns:
        table += f"<th style='{th}'>{html_lib.escape(str(col))}</th>"
    table += "</tr>"
    for row in rows:
        table += "<tr>"
        for cell in row:
            table += f"<td style='{td}'>{html_lib.escape(str(cell))}</td>"
        table += "</tr>"
    table += "</table>"
    summary = explanation or f"Dynamic query returned {len(rows)} row(s)."
    return _build_email_layout("Dynamic Query", "Query Results", summary, table)


_last_operation = {
    "type": None,
    "data": None,
    "raw": None,
    "email_html": "",
    "ai_summary": "",
}


def _get_filename(ext="xlsx"):
    op = _last_operation.get("type") or "report"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{op}_{ts}.{ext}"


def _generate_excel():
    if not OPENPYXL_AVAILABLE:
        return b""
    op_type = _last_operation.get("type")
    data = _last_operation.get("data")
    if not op_type or not data:
        return b""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"

    if op_type == "dynamic_table":
        cols = data.get("columns", [])
        rows = data.get("rows", [])
        if cols:
            ws.append(cols)
            for row in rows:
                ws.append(row)
    else:
        ws.append(["Field", "Value"])
        for k, v in data.items():
            ws.append([k, str(v)])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _generate_csv():
    import csv

    op_type = _last_operation.get("type")
    data = _last_operation.get("data")
    if not op_type or not data:
        return b""

    s = io.StringIO()
    w = csv.writer(s)
    if op_type == "dynamic_table":
        w.writerow(data.get("columns", []))
        for row in data.get("rows", []):
            w.writerow(row)
    else:
        w.writerow(["Field", "Value"])
        for k, v in data.items():
            w.writerow([k, v])
    return s.getvalue().encode("utf-8-sig")


def _generate_json_file():
    data = _last_operation.get("data")
    if not data:
        return b""
    return json.dumps(data, indent=2, default=str).encode("utf-8")


def send_erp_email(to_email, subject, body_text, html_table, attachment_format="excel"):
    smtp_user = config_manager.get_config_value("smtp_user", "")
    smtp_password = config_manager.get_config_value("smtp_password", "")
    smtp_sender = config_manager.get_config_value("smtp_sender", "erp.assistant@yourdomain.com")

    if not smtp_user or not smtp_password:
        return False, "SMTP credentials missing. Configure smtp_user and smtp_password."

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp_sender
    msg["To"] = to_email

    html_content = f"""
    <html><body style='font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;'>
      <p style='color:#333;'>{html_lib.escape(body_text).replace(chr(10), '<br>')}</p>
      {html_table}
    </body></html>
    """

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body_text, "plain"))
    alt.attach(MIMEText(html_content, "html"))
    msg.attach(alt)

    fmt = str(attachment_format or "excel").lower().strip()
    if fmt == "csv":
        payload = _generate_csv()
        if payload:
            part = MIMEApplication(payload, _subtype="csv")
            part.add_header("Content-Disposition", "attachment", filename=_get_filename("csv"))
            msg.attach(part)
    elif fmt == "json":
        payload = _generate_json_file()
        if payload:
            part = MIMEApplication(payload, _subtype="json")
            part.add_header("Content-Disposition", "attachment", filename=_get_filename("json"))
            msg.attach(part)
    else:
        payload = _generate_excel()
        if payload:
            part = MIMEApplication(payload, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part.add_header("Content-Disposition", "attachment", filename=_get_filename("xlsx"))
            msg.attach(part)

    try:
        host = config_manager.get_config_value("smtp_host", "smtp.gmail.com")
        port = int(config_manager.get_config_value("smtp_port", 587))
        server = smtplib.SMTP(host, port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully"
    except Exception as exc:
        return False, str(exc)


def _get_api_key_from_request():
    return str(request.headers.get("X-API-Key") or request.headers.get("x-api-key") or "").strip()


def _api_key_valid():
    configured = str(config_manager.get_config_value("apex_api_key", "") or os.getenv("APEX_API_KEY", "")).strip()
    incoming = _get_api_key_from_request()
    if not configured or not incoming:
        return False
    return hmac.compare_digest(incoming.encode(), configured.encode())


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("authenticated") or _api_key_valid():
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized. Use login session or X-API-Key."}), 401

    return decorated


_SECRET_KEYS = {
    "db_password",
    "github_copilot_token",
    "github_token",
    "openai_api_key",
    "api_password",
    "smtp_password",
    "login_password",
    "apex_api_key",
}


@app.route("/")
def index():
    try:
        return send_from_directory("static", "index7.html")
    except Exception:
        return jsonify({"service": "Sales Order Chatbot API", "status": "ok"})


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
            "service": "oracle-rest-chatbot",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "db_ok": db_ok,
            "db_error": db_error,
            "apex_auth_mode": "X-API-Key or Session",
        }
    )


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    stored_username = str(app_config.get("login_username", "")).strip()
    stored_password = str(app_config.get("login_password", "")).strip()

    user_ok = hmac.compare_digest(username.encode(), stored_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), stored_password.encode())
    if user_ok and pass_ok:
        session["authenticated"] = True
        session["user"] = username
        return jsonify({"ok": True, "message": "Login successful", "user": username})
    return jsonify({"ok": False, "error": "Invalid username or password"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET", "POST"])
@require_login
def route_config_manager():
    if request.method == "POST":
        new_config = request.get_json(force=True) or {}
        for key, value in new_config.items():
            if key in _SECRET_KEYS:
                if value and str(value).strip():
                    config_manager.set_config_value(key, value)
            else:
                config_manager.set_config_value(key, value)
        updated = config_manager.load_config()
        safe = {k: ("***" if k in _SECRET_KEYS else v) for k, v in updated.items()}
        return jsonify({"status": "success", "config": safe})

    safe = {k: ("***" if k in _SECRET_KEYS else v) for k, v in config_manager.load_config().items()}
    return jsonify(safe)


@app.route("/api/chat", methods=["POST"])
@require_login
def chat():
    started_at = time.time()

    def respond(payload, stage="completed"):
        data = dict(payload or {})
        data["ui_state"] = {
            "stage": stage,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "thinking": "AI analyzed your request.",
            "fetching": "Fetched data from Oracle and prepared response.",
        }
        return jsonify(data)

    try:
        body = request.get_json(force=True) or {}
        user_msg = str(body.get("message", "")).strip()
        history = body.get("history", [])
        if not user_msg:
            return respond({"reply": "Please enter a message.", "type": "text"}, stage="validation")

        intent = ai_extract_intent(history, user_msg)
        action = intent.get("action", "dynamic_query")

        lower = user_msg.lower()
        if action == "help" or lower in ("help", "commands", "?"):
            return respond(
                {
                    "reply": "Try: Get order 67965, Get customer orders for Vision, Create order, Send email to user@domain.com, or any SQL-style report request.",
                    "type": "text",
                }
            )

        if action == "email":
            return respond(
                {
                    "reply": {
                        "to_email": intent.get("email_address", ""),
                        "has_data": _last_operation.get("type") is not None,
                    },
                    "type": "email_form",
                }
            )

        if action == "create" or ("create" in lower and "order" in lower):
            return respond({"reply": "create_form", "type": "create_form", "prefilled": intent})

        if action == "get" and intent.get("order_number"):
            raw = get_order(int(intent.get("order_number")))
            parsed = parse_order_response(raw)
            _last_operation["type"] = "order"
            _last_operation["data"] = parsed
            _last_operation["raw"] = raw
            cols = ["Line", "Item", "Qty", "UOM", "Unit Price", "Status"]
            rows = [[ln.get(c, "") for c in cols] for ln in parsed.get("lines", [])]
            _last_operation["email_html"] = _generate_dynamic_table_email_html(cols, rows, f"Order #{parsed.get('order_number', '')} details")
            return respond({"reply": parsed, "type": "order"})

        if action == "get" and intent.get("customer_name"):
            raw = get_customer_orders(str(intent.get("customer_name")))
            parsed = parse_customer_orders(raw)
            parsed["customer_name"] = str(intent.get("customer_name"))
            _last_operation["type"] = "customer_orders"
            _last_operation["data"] = parsed
            _last_operation["raw"] = raw
            keys = parsed.get("raw_keys", [])
            rows = [[str(r.get(k, "")) for k in keys] for r in parsed.get("rows", [])]
            _last_operation["email_html"] = _generate_dynamic_table_email_html(keys, rows, "Customer orders report")
            return respond({"reply": parsed, "type": "customer_orders"})

        if action == "general" and not any(k in lower for k in ["order", "customer", "erp", "sql", "invoice"]):
            return respond({"reply": generate_general_chat_response(history, user_msg), "type": "text"})

        ai_result = generate_dynamic_sql(history, user_msg)
        sql_query = re.sub(r"[;\s/]+$", "", str(ai_result.get("sql", "")).strip())
        explanation = ai_result.get("explanation", "Query executed successfully.")
        if not sql_query:
            return respond({"reply": explanation, "type": "error"}, stage="failed")
        if not is_safe_select_query(sql_query):
            return respond({"reply": "Security Error: Only safe SELECT queries are allowed.", "type": "error"}, stage="failed")

        results = execute_query(sql_query)
        if not results:
            return respond({"reply": "No records found.", "type": "text"})

        columns = list(results[0].keys())
        rows = [[str(row.get(col, "")) for col in columns] for row in results]
        _last_operation["type"] = "dynamic_table"
        _last_operation["data"] = {"columns": columns, "rows": rows, "sql": sql_query}
        _last_operation["raw"] = results
        _last_operation["email_html"] = _generate_dynamic_table_email_html(columns, rows, explanation)

        return respond(
            {
                "type": "dynamic_table",
                "sql": sql_query,
                "explanation": explanation,
                "columns": columns,
                "rows": rows,
            }
        )

    except requests.exceptions.ConnectionError:
        return respond({"reply": "Could not connect to Oracle EBS server. Check network/VPN.", "type": "error"}, stage="failed")
    except Exception as exc:
        return respond({"reply": f"Unexpected Error: {exc}", "type": "error"}, stage="failed")


@app.route("/api/create-order", methods=["POST"])
@require_login
def api_create_order():
    body = request.get_json(force=True) or {}
    try:
        raw = create_order(body)
        parsed = parse_create_order_response(raw)
        _last_operation["type"] = "create"
        _last_operation["data"] = parsed
        _last_operation["raw"] = raw
        table_cols = ["Field", "Value"]
        table_rows = [[k, str(v)] for k, v in parsed.items()]
        _last_operation["email_html"] = _generate_dynamic_table_email_html(table_cols, table_rows, "Create order result")
        return jsonify({"reply": parsed, "type": "create_result"})
    except Exception as exc:
        return jsonify({"reply": f"Create order error: {exc}", "type": "error"})


@app.route("/api/send-email", methods=["POST"])
@require_login
def api_send_email():
    body = request.get_json(force=True) or {}
    to_email = str(body.get("to_email", "")).strip()
    subject = str(body.get("subject") or "Oracle ERP Order Details Update").strip()
    body_text = str(body.get("body") or "Please find the requested order details below.").strip()
    attachment_format = str(body.get("attachment_format") or "excel").strip().lower()

    if not to_email:
        return jsonify({"reply": "Email address is required.", "type": "error"})

    html_payload = _last_operation.get("email_html", "")
    if not html_payload:
        return jsonify({"reply": "No recent operation data to send.", "type": "error"})

    ok, msg = send_erp_email(to_email, subject, body_text, html_payload, attachment_format)
    if ok:
        return jsonify({"reply": f"Email sent successfully to {to_email}", "type": "email_success"})
    return jsonify({"reply": f"Error sending email: {msg}", "type": "error"})


@app.route("/api/email-preview", methods=["GET"])
@require_login
def api_email_preview():
    return jsonify(
        {
            "html": _last_operation.get("email_html", ""),
            "has_data": _last_operation.get("type") is not None,
            "operation_type": _last_operation.get("type"),
        }
    )


@app.route("/api/download", methods=["GET"])
@require_login
def api_download():
    if not _last_operation.get("type") or not _last_operation.get("data"):
        return jsonify({"error": "No operation data available. Perform a query first."}), 400

    fmt = str(request.args.get("format", "excel")).lower().strip()
    if fmt == "csv":
        data = _generate_csv()
        if not data:
            return jsonify({"error": "CSV generation failed."}), 500
        return Response(data, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={_get_filename('csv')}"})

    if fmt == "json":
        data = _generate_json_file()
        if not data:
            return jsonify({"error": "JSON generation failed."}), 500
        return Response(data, mimetype="application/json", headers={"Content-Disposition": f"attachment; filename={_get_filename('json')}"})

    if not OPENPYXL_AVAILABLE:
        return jsonify({"error": "openpyxl not installed. Run: pip install openpyxl"}), 500
    data = _generate_excel()
    if not data:
        return jsonify({"error": "Excel generation failed."}), 500
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={_get_filename('xlsx')}"},
    )


@app.route("/api/download-excel", methods=["GET"])
@require_login
def api_download_excel():
    return api_download()


if __name__ == "__main__":
    host = str(config_manager.get_config_value("app_host", "0.0.0.0"))
    port = int(config_manager.get_config_value("app_port", 5000))
    debug = bool(config_manager.get_config_value("app_debug", False))
    use_reloader = bool(config_manager.get_config_value("app_use_reloader", False))
    print(f"Oracle APEX-ready Sales Order Chatbot running on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
"""
Sales Order Chatbot - Flask backend with dynamic AI-SQL generation,
order operations, and email formatting compatible with app5.

Refactored to use:
- config_manager: Centralized configuration management
- system_prompts: Centralized system prompts for AI/LLM
- Oracle Apps Standard Tables: Dynamic SQL using Oracle EBS standard tables

Oracle APEX compatibility:
- CORS support for APEX pages
- Stateless API-key authentication for APEX_WEB_SERVICE calls
- Health endpoint for APEX Web Source checks
"""

import datetime
import hmac
import html as html_lib
import io
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import lru_cache, wraps

import requests
import urllib3
from flask import Flask, Response, jsonify, request, send_from_directory, session
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

try:
    import openpyxl
    OPENPYXL_AVAILABLE = True
except Exception:
    openpyxl = None
    OPENPYXL_AVAILABLE = False


# =========================================================
# Configuration
# =========================================================

app_config = config_manager.load_config()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Session settings that work better with cross-origin frontends like APEX.
app.config["SESSION_COOKIE_SAMESITE"] = str(
    config_manager.get_config_value("session_cookie_samesite", "Lax") or "Lax"
)
app.config["SESSION_COOKIE_SECURE"] = bool(
    config_manager.get_config_value("session_cookie_secure", False)
)


def _apex_allowed_origins():
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


_ALLOWED_ORIGINS = _apex_allowed_origins()

if FLASK_CORS_AVAILABLE:
    CORS(
        app,
        resources={r"/api/*": {"origins": _ALLOWED_ORIGINS if _ALLOWED_ORIGINS != ["*"] else "*"}},
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
        expose_headers=["Content-Disposition"],
    )


@app.after_request
def add_cors_headers(resp):
    if FLASK_CORS_AVAILABLE:
        return resp
    origin = request.headers.get("Origin", "")
    allow_any = _ALLOWED_ORIGINS == ["*"]
    if allow_any:
        resp.headers["Access-Control-Allow-Origin"] = origin or "*"
    elif origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp


@app.route("/api/<path:_rest>", methods=["OPTIONS"])
def api_options(_rest):
    return Response(status=204)


if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _tls_verify_enabled():
    if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
        return False
    cfg_val = app_config.get("verify_ssl", True)
    if isinstance(cfg_val, bool):
        return cfg_val
    return str(cfg_val).strip().lower() not in ("false", "0", "no")


COPILOT_BASE_URL = "https://models.inference.ai.azure.com"
oracle_initialized = False

_last_operation = {
    "type": None,
    "data": None,
    "raw": None,
    "email_html": "",
    "ai_summary": "",
}

_SECRET_KEYS = {
    "db_password",
    "github_copilot_token",
    "github_token",
    "openai_api_key",
    "api_password",
    "smtp_password",
    "login_password",
    "apex_api_key",
    "apex_api_keys",
}


# =========================================================
# Core Helpers
# =========================================================


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


def get_org_id():
    return config_manager.get_org_id()


def get_service_urls():
    return config_manager.get_service_urls()


def get_rest_header():
    return config_manager.get_rest_header()


def get_order_type_id():
    return config_manager.get_order_type_id()


def get_default_payment_term_id():
    return config_manager.get_default_payment_term_id()


def get_default_price_list_id():
    return config_manager.get_default_price_list_id()


def get_default_salesrep_id():
    return config_manager.get_default_salesrep_id()


def get_default_ship_to_org_id():
    return config_manager.get_default_ship_to_org_id()


def get_default_sold_to_org_id():
    return config_manager.get_default_sold_to_org_id()


def get_default_inventory_item_id():
    return config_manager.get_default_inventory_item_id()


def build_session():
    req_session = requests.Session()
    req_session.mount("https://", ForceTLSAdapter())
    req_session.auth = HTTPBasicAuth(app_config.get("api_user", ""), app_config.get("api_password", ""))
    req_session.verify = _tls_verify_enabled()
    return req_session


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
# AI Helpers
# =========================================================


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


def copilot_chat_completion(messages, temperature=0, max_tokens=None):
    token = get_copilot_token()
    if not token:
        raise ValueError("GitHub Copilot token is not configured.")

    payload = {
        "model": get_copilot_model(),
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    url = f"{get_models_base_url()}/chat/completions"
    max_retries = int(config_manager.get_config_value("copilot_max_retries", 2) or 2)
    base_delay = float(config_manager.get_config_value("copilot_retry_base_seconds", 1.5) or 1.5)

    for attempt in range(max_retries + 1):
        try:
            res = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "api-key": token,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            res.raise_for_status()
            return res.json()
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


def build_history_string(history):
    lines = []
    for msg in (history or [])[-8:]:
        role = str(msg.get("role", ""))
        content = str(msg.get("content", ""))
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def is_erp_or_data_query(user_input):
    text = str(user_input or "").lower()
    keywords = [
        "order", "orders", "customer", "customers", "line", "item", "invoice", "shipment",
        "booked", "entered", "cancelled", "po", "sales", "sql", "query", "report", "erp",
        "track", "tracking", "shipping", "ship to", "email",
    ]
    return any(k in text for k in keywords)


def generate_general_chat_response(history, user_input):
    if not get_copilot_token():
        return (
            "I can answer general AI-style questions after you set github_copilot_token in config.json "
            "(or GITHUB_TOKEN/GITHUB_COPILOT_TOKEN environment variable)."
        )

    default_prompt = (
        "You are a helpful AI assistant. Answer clearly and directly. "
        "For ERP or sales order requests, suggest specific commands only when useful."
    )
    system_prompt = getattr(system_prompts, "GENERAL_CHAT_SYSTEM_PROMPT", default_prompt)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in (history or [])[-10:]:
        role = str(msg.get("role", "")).strip().lower()
        if role not in ("user", "assistant", "system"):
            continue
        content = str(msg.get("content", "")).strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": str(user_input or "")})

    try:
        response = copilot_chat_completion(messages=messages, temperature=0.7, max_tokens=700)
        return response["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        return f"AI response error: {exc}"


def ai_extract_intent(history, user_input):
    text = str(user_input or "")
    lower = text.lower().strip()

    if lower in ("hi", "hello", "hey", "help", "commands", "?"):
        return {"action": "help"}

    email_match = re.search(r"(?:send|email|mail)\s+(?:to\s+)?([\w.+-]+@[\w.-]+\.\w+)", text, re.IGNORECASE)
    if email_match:
        return {"action": "email", "email_address": email_match.group(1)}

    # Deterministic fallback when token is unavailable.
    if not get_copilot_token():
        if re.search(r"\b(create|new|place)\b.*\border\b", lower):
            return {"action": "create"}
        if re.search(r"\border\s*#?\s*(\d{4,})\b", lower):
            m = re.search(r"\border\s*#?\s*(\d{4,})\b", lower)
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
                user_input=text,
                system_prompt=system_prompt,
                chat_completion=copilot_chat_completion,
                model_name=get_copilot_model(),
                base_url=get_models_base_url(),
                token=get_copilot_token(),
                user_prompt_builder=system_prompts.build_intent_user_prompt,
            )
        else:
            user_prompt = system_prompts.build_intent_user_prompt(history_str, text)
            res = copilot_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
            content = res["choices"][0]["message"]["content"].replace("```json", "").replace("```", "").strip()
            intent = json.loads(content)

        if "action" not in intent:
            intent["action"] = "dynamic_query"
        return intent
    except Exception:
        return {"action": "dynamic_query"}


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


def generate_ai_summary(operation_type, data):
    if not get_copilot_token():
        return ""

    try:
        data_json = json.dumps(data, indent=2, default=str)[:3000]
        system_prompt = system_prompts.get_ai_summary_system_prompt()

        if get_llm_backend() == "pydantic_ai":
            return pydantic_ai_adapter.generate_summary(
                operation_type=operation_type,
                data_json=data_json,
                system_prompt=system_prompt,
                chat_completion=copilot_chat_completion,
                model_name=get_copilot_model(),
                base_url=get_models_base_url(),
                token=get_copilot_token(),
                user_prompt_builder=system_prompts.build_summary_user_prompt,
            )

        user_prompt = system_prompts.build_summary_user_prompt(operation_type, data_json)
        response = copilot_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


# =========================================================
# ERP Operation Helpers
# =========================================================


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
                    "ORDER_TYPE_ID": int(order_data.get("order_type_id", get_order_type_id())),
                    "ORG_ID": int(get_org_id()),
                    "PAYMENT_TERM_ID": int(order_data.get("payment_term_id", get_default_payment_term_id())),
                    "PRICE_LIST_ID": int(order_data.get("price_list_id", get_default_price_list_id())),
                    "SALESREP_ID": int(order_data.get("salesrep_id", get_default_salesrep_id())),
                    "SHIP_TO_ORG_ID": int(order_data.get("ship_to_org_id", get_default_ship_to_org_id())),
                    "SOLD_TO_ORG_ID": int(order_data.get("sold_to_org_id", get_default_sold_to_org_id())),
                    "TRANSACTIONAL_CURR_CODE": order_data.get("currency", "USD"),
                    "OPERATION": "CREATE",
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID": int(order_data.get("inventory_item_id", get_default_inventory_item_id())),
                        "ORDERED_ITEM": order_data.get("ordered_item", ""),
                        "ORDERED_QUANTITY": float(order_data.get("ordered_quantity", 1)),
                        "PAYMENT_TERM_ID": int(order_data.get("payment_term_id", get_default_payment_term_id())),
                        "PRICE_LIST_ID": int(order_data.get("price_list_id", get_default_price_list_id())),
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


def parse_create_order_response(data):
    try:
        output = data.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {})
        if not output:
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
    except Exception as exc:
        return {"error": f"Failed to parse response: {exc}", "raw": data}


def parse_customer_orders(data):
    try:
        output = data.get("OutputParameters", data)
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
    except Exception as exc:
        return {"error": f"Failed to parse customer orders: {exc}", "raw": data}


def parse_order_response(data):
    try:
        output = data.get("OutputParameters", data)
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
            "customer_name": header.get("SOLD_TO_ORG", header.get("SOLD_TO_ORG_ID", "")),
            "currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
            "lines": lines,
            "header_details": {
                "Order Number": header.get("ORDER_NUMBER", ""),
                "Header ID": header.get("HEADER_ID", ""),
                "Customer PO": header.get("CUST_PO_NUMBER", ""),
                "Flow Status": header.get("FLOW_STATUS_CODE", ""),
                "Ordered Date": header.get("ORDERED_DATE", ""),
                "Currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
            },
        }
    except Exception as exc:
        return {"error": f"Failed to parse response: {exc}", "raw": data}


# =========================================================
# Email + Export Helpers
# =========================================================


def _build_email_layout(cname, report_type, ai_summary, table_html):
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    cname_s = html_lib.escape(str(cname))
    report_type_s = html_lib.escape(str(report_type))
    ai_summary_s = html_lib.escape(str(ai_summary))

    return f"""
    <div style='font-family: Arial, sans-serif; max-width: 860px; margin: auto; color: #000; padding: 12px;'>
      <h3 style='margin-top:0;'>Header Details</h3>
      <ul style='padding-left:20px;'>
        <li>Customer Name: {cname_s}</li>
        <li>Date of Report: {report_date}</li>
        <li>Statement Period: {report_type_s}</li>
      </ul>
      <hr>
      <h3>Executive Summary</h3>
      <p>{ai_summary_s}</p>
      <hr>
      <h3>Order Detail Table</h3>
      {table_html}
      <hr>
      <ul style='padding-left:20px;'>
        <li>Support contact: erp.support@centroid.com</li>
        <li>Do-not-reply notice: Please do not reply directly to this email.</li>
      </ul>
    </div>
    """


def _generate_dynamic_table_email_html(columns, rows, explanation=""):
    th = "background:#003366;color:#fff;padding:8px;text-align:left;font-size:0.82rem;"
    td = "padding:8px;border-bottom:1px solid #e5e7eb;font-size:0.82rem;"

    table = "<table style='width:100%;border-collapse:collapse;'><tr>"
    for col in columns:
        table += f"<th style='{th}'>{html_lib.escape(str(col))}</th>"
    table += "</tr>"

    for row in rows:
        table += "<tr>"
        for cell in row:
            table += f"<td style='{td}'>{html_lib.escape(str(cell))}</td>"
        table += "</tr>"
    table += "</table>"

    summary = explanation or f"Dynamic query returned {len(rows)} row(s)."
    return _build_email_layout("Dynamic Query", "Query Results", summary, table)


def _get_filename(ext="xlsx"):
    op = _last_operation.get("type") or "report"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{op}_{ts}.{ext}"


def _generate_excel():
    if not OPENPYXL_AVAILABLE:
        return b""
    op_type = _last_operation.get("type")
    data = _last_operation.get("data")
    if not op_type or not data:
        return b""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"

    if op_type == "dynamic_table":
        cols = data.get("columns", [])
        rows = data.get("rows", [])
        if cols:
            ws.append(cols)
            for row in rows:
                ws.append(row)
    else:
        ws.append(["Field", "Value"])
        for k, v in data.items():
            if k == "success":
                continue
            ws.append([k, str(v)])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _generate_csv():
    import csv

    op_type = _last_operation.get("type")
    data = _last_operation.get("data")
    if not op_type or not data:
        return b""

    out = io.StringIO()
    writer = csv.writer(out)

    if op_type == "dynamic_table":
        writer.writerow(data.get("columns", []))
        for row in data.get("rows", []):
            writer.writerow(row)
    else:
        writer.writerow(["Field", "Value"])
        for k, v in data.items():
            if k == "success":
                continue
            writer.writerow([k, v])

    return out.getvalue().encode("utf-8-sig")


def _generate_json_file():
    data = _last_operation.get("data")
    if not data:
        return b""
    return json.dumps(data, indent=2, default=str).encode("utf-8")


def send_erp_email(to_email, subject, body_text, html_table, attachment_format="excel"):
    smtp_user = config_manager.get_config_value("smtp_user", "")
    smtp_password = config_manager.get_config_value("smtp_password", "")
    smtp_sender = config_manager.get_config_value("smtp_sender", "erp.assistant@yourdomain.com")

    if not smtp_user or not smtp_password:
        return False, "SMTP credentials are missing. Configure smtp_user and smtp_password in config.json."

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp_sender
    msg["To"] = to_email

    html_content = f"""
    <html><body style='font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;'>
      <p style='color:#333;'>{html_lib.escape(body_text).replace(chr(10), '<br>')}</p>
      <br>
      {html_table}
    </body></html>
    """

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(body_text, "plain"))
    alt_part.attach(MIMEText(html_content, "html"))
    msg.attach(alt_part)

    fmt = str(attachment_format or "excel").lower().strip()
    if fmt == "csv":
        payload = _generate_csv()
        if payload:
            part = MIMEApplication(payload, _subtype="csv")
            part.add_header("Content-Disposition", "attachment", filename=_get_filename("csv"))
            msg.attach(part)
    elif fmt == "json":
        payload = _generate_json_file()
        if payload:
            part = MIMEApplication(payload, _subtype="json")
            part.add_header("Content-Disposition", "attachment", filename=_get_filename("json"))
            msg.attach(part)
    else:
        payload = _generate_excel()
        if payload:
            part = MIMEApplication(payload, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part.add_header("Content-Disposition", "attachment", filename=_get_filename("xlsx"))
            msg.attach(part)

    try:
        host = config_manager.get_config_value("smtp_host", "smtp.gmail.com")
        port = int(config_manager.get_config_value("smtp_port", 587))
        server = smtplib.SMTP(host, port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully!"
    except Exception as exc:
        return False, str(exc)


# =========================================================
# Auth (Session + APEX API Key)
# =========================================================


def _collect_api_keys():
    keys = set()

    cfg_keys = config_manager.get_config_value("apex_api_keys", "")
    if isinstance(cfg_keys, list):
        for k in cfg_keys:
            kk = str(k or "").strip()
            if kk:
                keys.add(kk)
    else:
        for k in str(cfg_keys or "").split(","):
            kk = k.strip()
            if kk:
                keys.add(kk)

    single_cfg_key = str(config_manager.get_config_value("apex_api_key", "") or "").strip()
    if single_cfg_key:
        keys.add(single_cfg_key)

    env_key = str(os.getenv("APEX_API_KEY", "")).strip()
    if env_key:
        keys.add(env_key)

    return keys


def _get_request_api_key():
    key = str(request.headers.get("X-API-Key", "") or "").strip()
    if key:
        return key

    auth = str(request.headers.get("Authorization", "") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return ""


def has_valid_api_key():
    configured = _collect_api_keys()
    if not configured:
        return False

    incoming = _get_request_api_key()
    if not incoming:
        return False

    incoming_b = incoming.encode()
    for key in configured:
        try:
            if hmac.compare_digest(incoming_b, key.encode()):
                return True
        except Exception:
            continue
    return False


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("authenticated"):
            return f(*args, **kwargs)
        if has_valid_api_key():
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized. Please log in or provide a valid API key."}), 401

    return decorated


# =========================================================
# Routes
# =========================================================


@app.route("/")
def index():
    try:
        return send_from_directory("static", "index7.html")
    except Exception:
        return jsonify({"service": "Sales Order Chatbot API", "ok": True})


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
            "service": "sales-order-chatbot",
            "time": datetime.datetime.utcnow().isoformat() + "Z",
            "db_ok": db_ok,
            "db_error": db_error,
            "allowed_origins": _ALLOWED_ORIGINS,
            "apex_api_key_configured": len(_collect_api_keys()) > 0,
        }
    )


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    stored_username = str(app_config.get("login_username", "")).strip()
    stored_password = str(app_config.get("login_password", "")).strip()

    user_ok = hmac.compare_digest(username.encode(), stored_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), stored_password.encode())

    if user_ok and pass_ok:
        session["authenticated"] = True
        session["user"] = username
        return jsonify({"ok": True, "message": "Login successful", "user": username})

    return jsonify({"ok": False, "error": "Invalid username or password"}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET", "POST"])
@require_login
def route_config_manager():
    if request.method == "POST":
        new_config = request.get_json(force=True) or {}
        for key, value in new_config.items():
            if key in _SECRET_KEYS:
                if value and str(value).strip():
                    config_manager.set_config_value(key, value)
            else:
                config_manager.set_config_value(key, value)

        safe = {k: ("***" if k in _SECRET_KEYS else v) for k, v in config_manager.load_config().items()}
        return jsonify({"status": "success", "config": safe})

    safe = {k: ("***" if k in _SECRET_KEYS else v) for k, v in config_manager.load_config().items()}
    return jsonify(safe)


@app.route("/api/chat", methods=["POST"])
@app.route("/api/apex/chat", methods=["POST"])
@require_login
def chat():
    started_at = time.time()

    def respond(payload, stage="completed"):
        data = dict(payload or {})
        data["ui_state"] = {
            "stage": stage,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "thinking": "AI analyzed your request.",
            "fetching": "Fetched data from Oracle and prepared a response.",
        }
        return jsonify(data)

    try:
        body = request.get_json(force=True) or {}
        user_msg = str(body.get("message", "")).strip()
        history = body.get("history", [])

        if not user_msg:
            return respond({"reply": "Please enter a message.", "type": "text"}, stage="validation")

        lower = user_msg.lower().strip()
        if lower in ("hi", "hello", "hey"):
            return respond({
                "reply": "Hello! I'm the Sales Order Assistant. You can get orders, create orders, run dynamic SQL reports, and send email exports.",
                "type": "text",
            })
        if lower in ("help", "commands", "?"):
            return respond({
                "reply": "Try: Get order 67965, Orders for customer Vision, Create order, Send email to user@domain.com",
                "type": "text",
            })

        intent = ai_extract_intent(history, user_msg)
        action = intent.get("action", "dynamic_query")

        if action == "create":
            return respond({"reply": "create_form", "type": "create_form", "prefilled": intent})

        if action == "email":
            return respond({
                "reply": {
                    "to_email": intent.get("email_address", ""),
                    "has_data": _last_operation["type"] is not None,
                },
                "type": "email_form",
            })

        if action == "get":
            customer_name = intent.get("customer_name")
            order_number = intent.get("order_number")

            if customer_name and not order_number:
                raw = get_customer_orders(customer_name)
                parsed = parse_customer_orders(raw)
                parsed["customer_name"] = customer_name
                _last_operation["type"] = "customer_orders"
                _last_operation["data"] = parsed
                _last_operation["raw"] = raw
                keys = parsed.get("raw_keys", [])
                rows = [[str(r.get(k, "")) for k in keys] for r in parsed.get("rows", [])]
                _last_operation["email_html"] = _generate_dynamic_table_email_html(keys, rows, "Customer orders report")
                _last_operation["ai_summary"] = generate_ai_summary("customer_orders", parsed)
                return respond({"reply": parsed, "type": "customer_orders", "ai_summary": _last_operation["ai_summary"]})

            if order_number:
                raw = get_order(int(order_number))
                parsed = parse_order_response(raw)
                _last_operation["type"] = "order"
                _last_operation["data"] = parsed
                _last_operation["raw"] = raw
                cols = ["Line", "Item", "Qty", "UOM", "Unit Price", "Status"]
                rows = [[ln.get(c, "") for c in cols] for ln in parsed.get("lines", [])]
                _last_operation["email_html"] = _generate_dynamic_table_email_html(cols, rows, f"Order #{parsed.get('order_number', '')} details")
                _last_operation["ai_summary"] = generate_ai_summary("order", parsed)
                return respond({"reply": parsed, "type": "order", "ai_summary": _last_operation["ai_summary"]})

        if action == "general" or (action == "dynamic_query" and not is_erp_or_data_query(user_msg)):
            answer = intent.get("general_answer", "") or generate_general_chat_response(history, user_msg)
            return respond({"reply": answer, "type": "text"})

        # Dynamic SQL fallback
        ai_result = generate_dynamic_sql(history, user_msg)
        sql_query = re.sub(r"[;\s/]+$", "", str(ai_result.get("sql", "")).strip()).strip()
        explanation = ai_result.get("explanation", "Query executed successfully.")

        if not sql_query:
            return respond({"reply": explanation, "type": "error"}, stage="failed")
        if not is_safe_select_query(sql_query):
            return respond({"reply": "Security Error: Only safe SELECT queries are allowed.", "type": "error"}, stage="failed")

        try:
            results = execute_query(sql_query)
        except Exception as db_exc:
            return respond({"reply": f"SQL execution error: {db_exc}", "type": "error", "sql": sql_query}, stage="failed")

        if not results:
            return respond({"reply": "No records found.", "type": "text"})

        columns = list(results[0].keys())
        rows = [[str(row.get(col, "")) for col in columns] for row in results]
        _last_operation["type"] = "dynamic_table"
        _last_operation["data"] = {"columns": columns, "rows": rows, "sql": sql_query}
        _last_operation["raw"] = results
        _last_operation["email_html"] = _generate_dynamic_table_email_html(columns, rows, explanation)
        _last_operation["ai_summary"] = generate_ai_summary("dynamic_table", _last_operation["data"])

        return respond(
            {
                "type": "dynamic_table",
                "sql": sql_query,
                "explanation": explanation,
                "columns": columns,
                "rows": rows,
                "ai_summary": _last_operation["ai_summary"],
            }
        )

    except requests.exceptions.ConnectionError:
        return respond({"reply": "Could not connect to Oracle EBS server. Check network/VPN.", "type": "error"}, stage="failed")
    except Exception as exc:
        return respond({"reply": f"Unexpected Error: {exc}", "type": "error"}, stage="failed")


@app.route("/api/create-order", methods=["POST"])
@require_login
def api_create_order():
    body = request.get_json(force=True) or {}
    try:
        raw = create_order(body)
        parsed = parse_create_order_response(raw)
        _last_operation["type"] = "create"
        _last_operation["data"] = parsed
        _last_operation["raw"] = raw
        rows = [[k, str(v)] for k, v in parsed.items()]
        _last_operation["email_html"] = _generate_dynamic_table_email_html(["Field", "Value"], rows, "Create order result")
        _last_operation["ai_summary"] = generate_ai_summary("create", parsed)
        return jsonify({"reply": parsed, "type": "create_result", "ai_summary": _last_operation["ai_summary"]})
    except requests.exceptions.HTTPError as exc:
        return jsonify({"reply": f"REST API error: {exc}", "type": "error"})
    except requests.exceptions.ConnectionError:
        return jsonify({"reply": "Could not connect to Oracle EBS server.", "type": "error"})
    except Exception as exc:
        return jsonify({"reply": f"Something went wrong: {exc}", "type": "error"})


@app.route("/api/send-email", methods=["POST"])
@require_login
def api_send_email():
    body = request.get_json(force=True) or {}
    to_email = str(body.get("to_email") or "").strip()
    subject = str(body.get("subject") or "Oracle ERP Order Details Update").strip()
    body_text = str(body.get("body") or "Please find the requested order details below.").strip()

    if not to_email:
        return jsonify({"reply": "Email address is required.", "type": "error"})

    html_payload = _last_operation.get("email_html", "")
    if not html_payload:
        return jsonify({"reply": "No recent operation data to send. Please run a query first.", "type": "error"})

    attachment_format = str(body.get("attachment_format") or "excel").strip().lower()
    ok, msg = send_erp_email(to_email, subject, body_text, html_payload, attachment_format)
    if ok:
        return jsonify({"reply": f"Email sent successfully to {to_email}!", "type": "email_success"})
    return jsonify({"reply": f"Error sending email: {msg}", "type": "error"})


@app.route("/api/email-preview", methods=["GET"])
@require_login
def api_email_preview():
    return jsonify(
        {
            "html": _last_operation.get("email_html", ""),
            "has_data": _last_operation.get("type") is not None,
            "operation_type": _last_operation.get("type"),
        }
    )


@app.route("/api/download", methods=["GET"])
@require_login
def api_download():
    if not _last_operation.get("type") or not _last_operation.get("data"):
        return jsonify({"error": "No operation data available. Perform a query first."}), 400

    fmt = str(request.args.get("format", "excel")).lower().strip()

    if fmt == "csv":
        data = _generate_csv()
        if not data:
            return jsonify({"error": "CSV generation failed."}), 500
        return Response(
            data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={_get_filename('csv')}"},
        )

    if fmt == "json":
        data = _generate_json_file()
        if not data:
            return jsonify({"error": "JSON generation failed."}), 500
        return Response(
            data,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={_get_filename('json')}"},
        )

    if not OPENPYXL_AVAILABLE:
        return jsonify({"error": "openpyxl not installed. Run: pip install openpyxl"}), 500

    data = _generate_excel()
    if not data:
        return jsonify({"error": "Excel generation failed."}), 500

    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={_get_filename('xlsx')}"},
    )


@app.route("/api/download-excel", methods=["GET"])
@require_login
def api_download_excel():
    return api_download()


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":
    host = str(config_manager.get_config_value("app_host", "0.0.0.0"))
    port = int(config_manager.get_config_value("app_port", 5000))
    debug = bool(config_manager.get_config_value("app_debug", False))
    use_reloader = bool(config_manager.get_config_value("app_use_reloader", False))
    print(f"Oracle APEX-ready Sales Order Chatbot running on http://{host}:{port}")
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
