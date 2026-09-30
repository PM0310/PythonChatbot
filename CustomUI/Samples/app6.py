"""
Sales Order Chatbot — Flask backend with dynamic AI-SQL Generation & Config Management.
"""

import json
import os
import ssl
import re
import datetime
import smtplib
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import requests.adapters
import urllib3
from urllib3.util.ssl_ import create_urllib3_context
from requests.auth import HTTPBasicAuth
from flask import Flask, request, jsonify, send_from_directory

# ── Dynamic Configuration Management ──────────────
CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    
    # Default fallback config
    default_cfg = {
        "db_host": "cendb.centroid.com",
        "db_port": "1541",
        "db_service": "EBS122",
        "db_user": "apps",
        "db_password": "apps",
        "api_base_url": "https://cendb.ad.centroid.com:4463",
        "api_user": "operations",
        "api_password": "welcome",
        "oracle_client_path": r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10",
        "openai_api_key": "REDACTED_SECRET",
        "openai_model": "gpt-4o"
    }
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_cfg, f, indent=4)
    return default_cfg

app_config = load_config()

# ── Imports & Setup ───────────────────────────────
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except ImportError:
    ORACLEDB_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ORG_ID = "204"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

# ── Database Connection ───────────────────────────
def _get_db_connection():
    if not ORACLEDB_AVAILABLE:
        raise RuntimeError("oracledb is not installed.")
    try:
        client_path = app_config.get("oracle_client_path")
        if client_path:
            oracledb.init_oracle_client(lib_dir=client_path)
    except Exception:
        pass  # already initialized
    
    dsn_string = (
        "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)"
        f"(HOST={app_config['db_host']})(PORT={app_config['db_port']}))"
        f"(CONNECT_DATA=(SERVICE_NAME={app_config['db_service']})))"
    )
    
    return oracledb.connect(
        user=app_config['db_user'], 
        password=app_config['db_password'], 
        dsn=dsn_string
    )

def execute_query(sql: str, params: dict = None) -> list:
    if params is None: 
        params = {}
    with _get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0].upper() for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]

# ── API Connection ────────────────────────────────
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def _build_session():
    s = requests.Session()
    s.mount("https://", ForceTLSAdapter())
    s.auth = HTTPBasicAuth(app_config["api_user"], app_config["api_password"])
    s.verify = False
    return s

# ── AI Agents (Intent, Summary, SQL Generation) ───
def get_openai_client():
    api_key = app_config["openai_api_key"]
    return OpenAI(base_url="https://models.inference.ai.azure.com", api_key=api_key)

def build_history_string(conversation_history):
    lines = []
    for msg in conversation_history[-5:]:
        role = str(msg.get('role', ''))
        content = str(msg.get('content', ''))
        lines.append(role + ": " + content)
    return "\n".join(lines)

def ai_extract_intent(conversation_history: list, user_input: str) -> dict:
    if not OPENAI_AVAILABLE: 
        return {"action": "unknown"}
    
    try:
        client = get_openai_client()
        history_str = build_history_string(conversation_history)
        
        system_prompt = """You are an ERP Sales Order Assistant. Extract the user's intent into JSON.
FIELDS:
- action: 'create', 'email', 'schedule', 'stop_schedule', or 'dynamic_query'
RULES:
1. If the user asks ANY question about retrieving data (orders, items, customers, totals, etc.), set action='dynamic_query'.
2. If the user refers to something in the previous messages (e.g., 'what about order 123?'), use the history context and set action='dynamic_query'.
3. If they want to create an order, set action='create'."""

        user_prompt_text = "History:\n" + history_str + "\n\nPrompt: " + str(user_input)
        
        ai_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_text}
        ]

        response = client.chat.completions.create(
            model=app_config["openai_model"],
            messages=ai_messages,
            temperature=0.0,
        )
        
        clean_response = response.choices[0].message.content.strip()
        clean_response = clean_response.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_response)
        
    except Exception as e:
        print("Intent error: " + str(e))
        return {"action": "unknown"}

def generate_dynamic_sql(conversation_history: list, user_input: str) -> dict:
    """GPT-4o generates Oracle SQL based on EBS schema and conversational memory."""
    try:
        client = get_openai_client()
        history_str = build_history_string(conversation_history)
        
        schema_context = """
        You are an Oracle EBS R12 SQL Expert. Generate a valid Oracle SQL query to answer the user's request.
        Available Schema:
        - OE_ORDER_HEADERS_ALL (HEADER_ID, ORDER_NUMBER, FLOW_STATUS_CODE, SOLD_TO_ORG_ID, ORDERED_DATE, ORG_ID, CUST_PO_NUMBER)
        - OE_ORDER_LINES_ALL (LINE_ID, HEADER_ID, LINE_NUMBER, INVENTORY_ITEM_ID, ORDERED_QUANTITY, UNIT_SELLING_PRICE, FLOW_STATUS_CODE)
        - HZ_PARTIES (PARTY_ID, PARTY_NAME)
        - HZ_CUST_ACCOUNTS (CUST_ACCOUNT_ID, PARTY_ID, ACCOUNT_NUMBER)
        - MTL_SYSTEM_ITEMS_B (INVENTORY_ITEM_ID, ORGANIZATION_ID, SEGMENT1 as item_name, DESCRIPTION)
        
        Rules:
        1. Joins: HZ_CUST_ACCOUNTS.PARTY_ID = HZ_PARTIES.PARTY_ID. OE_ORDER_HEADERS_ALL.SOLD_TO_ORG_ID = HZ_CUST_ACCOUNTS.CUST_ACCOUNT_ID.
        2. Always use standard Oracle SQL syntax.
        3. Restrict rows to maximum 50 using `WHERE ROWNUM <= 50`.
        4. Return ONLY the raw SQL string inside a JSON block with the key "sql". Provide a natural language explanation in the key "explanation".
        """
        
        user_prompt_text = "History:\n" + history_str + "\n\nPrompt: " + str(user_input)
        
        ai_messages = [
            {"role": "system", "content": schema_context}, 
            {"role": "user", "content": user_prompt_text}
        ]
        
        response = client.chat.completions.create(
            model=app_config["openai_model"],
            messages=ai_messages,
            temperature=0.0,
        )
        
        clean_response = response.choices[0].message.content.strip()
        clean_response = clean_response.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_response)
        
    except Exception as e:
        error_msg = "AI SQL Generation Error: " + str(e)
        return {"sql": "", "explanation": error_msg}

# ── Flask Application & Endpoints ─────────────────
app = Flask(__name__, static_folder="static", static_url_path="/static")

@app.route("/")
def index():
    return send_from_directory("static", "index5.html")

@app.route("/api/config", methods=["GET", "POST"])
def config_manager():
    global app_config
    if request.method == "POST":
        new_config = request.get_json(force=True)
        app_config.update(new_config)
        with open(CONFIG_FILE, "w") as f:
            json.dump(app_config, f, indent=4)
        return jsonify({"status": "success", "config": app_config})
    return jsonify(app_config)

@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True)
    user_msg = str(body.get("message") or "").strip()
    history = body.get("history", [])

    if not user_msg:
        return jsonify({"reply": "Please type a message.", "type": "text"})

    # Determine intent using memory
    intent = ai_extract_intent(history, user_msg)
    action = intent.get("action", "dynamic_query")

    if action == "dynamic_query":
        # 1. Generate SQL
        ai_response = generate_dynamic_sql(history, user_msg)
        sql_query = str(ai_response.get("sql", "")).strip()
        explanation = str(ai_response.get("explanation", "Here is the data you requested."))

        if not sql_query:
            return jsonify({"reply": explanation, "type": "text"})

        # Security check: Read-only
        if not sql_query.upper().startswith("SELECT"):
            return jsonify({
                "reply": "Security Error: Only SELECT queries are permitted.", 
                "type": "error"
            })

        # 2. Execute SQL
        try:
            results = execute_query(sql_query)
            if not results:
                empty_msg = explanation + "\n\nNo records found for this query."
                return jsonify({"reply": empty_msg, "type": "text"})
            
            columns = list(results[0].keys())
            rows = [[str(row[col]) for col in columns] for row in results]
            
            return jsonify({
                "type": "dynamic_table",
                "explanation": explanation,
                "sql": sql_query,
                "columns": columns,
                "rows": rows
            })
            
        except Exception as db_err:
            error_msg = "Database Error executing AI-generated query:\n`" + sql_query + "`\n\nError: " + str(db_err)
            return jsonify({
                "reply": error_msg,
                "type": "error"
            })

    elif action == "create":
        return jsonify({"reply": "create_form", "type": "create_form"})
        
    else:
        maintenance_msg = "Action '" + str(action) + "' is under maintenance in this demo."
        return jsonify({"reply": maintenance_msg, "type": "text"})


if __name__ == "__main__":
    print("AI Dynamic SQL Chatbot running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)