"""
Flask backend for the Sales Order Assistant.
Replaces the Streamlit UI with a REST API consumed by a custom HTML/CSS/JS frontend.
"""
import os
import json
import re
import threading
import datetime
import smtplib
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# import app
from flask import Flask, request, jsonify, session, send_from_directory
from openai import OpenAI

import SalesOrderChatandVoiceBot2 as bot

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = "centroid-sales-order-assistant-2024-secret-key"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_TYPE"] = "filesystem"
app.config["PERMANENT_SESSION_LIFETIME"] = datetime.timedelta(hours=4)


@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# ──────────────────────────────────────────────────
# FAQ Data
# ──────────────────────────────────────────────────
FAQ_DATA = {
    "How do I create a new sales order?": "To create a new sales order, you can type a command like 'Create an order' or 'Create order for item AS54888'. I will guide you step-by-step to gather the Customer PO, Item, Quantity, and Line Type.",
    "How do I look up an existing order?": "Simply type 'Get order #12345' or 'Show me order 12345'.",
    "How do I send order details via email?": "Just say 'Send email to example@domain.com'. I will gather the details of the last operation we worked on and format it into a neat table for you to send.",
    "Can I search for orders by date or status?": "Yes! You can use natural language searches such as 'Show booked orders from 2024' or 'Find cancelled orders'.",
    "How do I see all orders for a specific customer?": "Type 'Order details for customer [Name]' (e.g., 'Order details for customer ACME'). This will pull up a comprehensive table of their past orders, shipments, and invoice balances.",
    "Can I add more items to an existing order?": "Yes. After you create a new order or retrieve an existing one, a button labeled 'Add a Line' will appear, allowing you to append new items to that specific order.",
    "How do I use voice commands?": "Click the microphone icon next to the chat bar. Wait for the 'Listening...' notification to appear, then speak your command clearly.",
    "How do I cancel an operation?": "If you are in the middle of creating an order and want to stop, simply click the 'Back to Chat' button available on all screens.",
}

# ──────────────────────────────────────────────────
# Session state helpers
# ──────────────────────────────────────────────────
_sessions: dict = {}  # sid -> state dict


def _default_state():
    return {
        "messages": [],
        "stage": "chat",
        "action": None,
        "get_order_num": None,
        "voice_prompt": None,
        "voice_error": None,
        "faq_pending": None,
        "pending_field": None,
        "email_payload_html": "",
        "offsets": {
            "item": 0, "price": 0, "term": 0, "rep": 0, "site": 0,
            "customer": 0, "customer_by_item": 0, "line_type": 0,
        },
        "collected": {
            "cpo": None, "ordered_item": None, "quantity": None, "order_number": None,
            "inventory_item_id": None, "price_list_id": None, "price_list_name": None,
            "unit_list_price": None, "unit_selling_price": None, "payment_term_id": None,
            "payment_term_name": None, "salesrep_id": None, "salesrep_name": None,
            "sold_to_org_id": None, "ship_to_org_id": None, "customer_name": None,
            "cust_account_id": None, "line_type_id": None, "email_address": None,
        },
        "item_rows": [], "price_rows": [], "term_rows": [], "rep_rows": [],
        "site_rows": [], "customer_rows": [], "customer_by_item_rows": [],
        "line_type_rows": [],
        "api_result": None,
        "gh_history": [],
        "add_line_stage": None, "add_line_data": {}, "add_line_header_id": None,
        "add_line_order_number": None, "add_line_item_rows": [], "add_line_price_rows": [],
        "add_line_term_rows": [], "add_line_return": "done",
        "selling_price_override": False,
        "order_details_customer_name": None,
        "order_details_rows": [],
        "order_details_page": 0,
        "adv_search_page": 0,
        "adv_search_filters": {},
        "auto_email_enabled": False,
        "auto_email_to": "",
        "auto_email_status": None,
        "auto_email_error": "",
    }


def _get_state():
    sid = session.get("sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["sid"] = sid
        session.permanent = True
    if sid not in _sessions:
        _sessions[sid] = _default_state()
    return _sessions[sid]


def _reset_state():
    sid = session.get("sid")
    if sid and sid in _sessions:
        msgs = _sessions[sid].get("messages", [])
        gh = _sessions[sid].get("gh_history", [])
        payload = _sessions[sid].get("email_payload_html", "")
        _sessions[sid] = _default_state()
        _sessions[sid]["messages"] = msgs
        _sessions[sid]["gh_history"] = gh
        _sessions[sid]["email_payload_html"] = payload
    return _get_state()


# ──────────────────────────────────────────────────
# Text helpers
# ──────────────────────────────────────────────────
def clean_text_for_speech(text: str) -> str:
    text = re.sub(r'[*_~`|#>-]', '', text)
    text = re.sub(r'[^\w\s.,?!]', '', text)
    return text.strip()


def merge_fields(state, extracted: dict):
    for k, v in extracted.items():
        if k in state["collected"] and v is not None:
            state["collected"][k] = v


def missing_minimum(state) -> list:
    c = state["collected"]
    missing = []
    if not c.get("cpo"):
        missing.append("Customer PO Number")
    if not c.get("ordered_item") and not c.get("inventory_item_id"):
        missing.append("Ordered Item code")
    if not c.get("quantity"):
        missing.append("Ordered Quantity")
    return missing


# ──────────────────────────────────────────────────
# AI helpers
# ──────────────────────────────────────────────────
def get_smart_intent(history: list, prompt: str) -> dict:
    try:
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=bot.GITHUB_TOKEN)
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
        system_prompt = (
            "You are an ERP intent extraction engine. Analyze the conversation history and the latest user prompt. "
            "Determine the intended action. Possible actions: "
            "'create' (create a new order), 'get' (retrieve a SPECIFIC order by its order number), "
            "'search' (search/filter/list orders by year, date range, or status), "
            "'email' (send email), 'order_details' (get all order history for a specific customer by name), or 'unknown'. "
            "CRITICAL: Use action='search' (NOT 'get') when the user mentions a year, date range, status, or wants to list/filter multiple orders without a specific order number. "
            "CRITICAL: Use action='get' ONLY when the user provides a specific order number. "
            "CRITICAL: If the user is answering a clarification question (e.g., saying 'yes' to 'are you looking for order 64460?'), infer the action and numbers directly from the assistant's previous question. "
            "CRITICAL: Convert spoken word numbers into digits (e.g., 'sixty four thousand four hundred sixty' -> 64460). "
            "Extract any of these keys if present: 'order_number' (integer, only for specific order lookup), "
            "'customer_name' (string), 'cpo' (string), 'ordered_item' (string), 'quantity' (number), "
            "'line_type_id' (number), 'email_address' (string), 'year' (4-digit integer), "
            "'status' (string — e.g. BOOKED, ENTERED, CANCELLED, SHIPPED, CLOSED), "
            "'date_range' (string — e.g. 'last month', 'last quarter', 'this week'). "
            "Respond ONLY with a valid JSON object, no explanation."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"History:\n{history_str}\n\nLatest prompt: {prompt}"},
            ],
            temperature=0.0,
            max_tokens=150,
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        elif content.startswith("```"):
            content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def generate_ai_summary(operation_name: str, data: dict) -> str:
    try:
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=bot.GITHUB_TOKEN)
        data_str = str(data)[:2000]
        system_prompt = (
            "You are a helpful Oracle ERP Chatbot Assistant. Summarize the result of the following ERP operation "
            "in 2-3 friendly, conversational sentences. Focus heavily on whether the operation was a SUCCESS or FAILURE. "
            "Highlight key identifiers (like Order Numbers, Header IDs, or Items). DO NOT output raw JSON or code snippets."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Operation: {operation_name}\nData: {data_str}"},
            ],
            temperature=0.3,
            max_tokens=150,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Operation completed. (AI Summary generation failed)"


# ──────────────────────────────────────────────────
# ERP parsing
# ──────────────────────────────────────────────────
def extract_erp_details(result: dict) -> dict:
    data = result.get("OutputParameters", result)
    status = data.get("X_RETURN_STATUS", "N/A")
    messages_raw = data.get("X_MESSAGES", {})
    message_list = []
    if isinstance(messages_raw, dict):
        items = messages_raw.get("X_MESSAGES_ITEM", [])
        if isinstance(items, list):
            message_list = [m.get("MESSAGE_TEXT", "") for m in items if m.get("MESSAGE_TEXT")]
        elif isinstance(items, dict):
            msg = items.get("MESSAGE_TEXT", "")
            if msg:
                message_list = [msg]
    message_text = " | ".join(message_list) if message_list else "N/A"

    header = data.get("X_HEADER_REC", {}) or {}
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}
    header_details = {
        "Order Number": header.get("ORDER_NUMBER", "N/A"),
        "Header ID": header.get("HEADER_ID", "N/A"),
        "Customer PO": header.get("CUST_PO_NUMBER", "N/A"),
        "Return Status": header.get("RETURN_STATUS", "N/A"),
        "Flow Status": header.get("FLOW_STATUS_CODE", "N/A"),
        "Order Category": header.get("ORDER_CATEGORY_CODE", "N/A"),
        "Currency": header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term": header_val.get("PAYMENT_TERM", "N/A"),
        "Price List": header_val.get("PRICE_LIST", "N/A"),
        "Order Type": header_val.get("ORDER_TYPE", "N/A"),
        "Customer": header_val.get("SOLD_TO_ORG", "N/A"),
        "Ship To": header_val.get("SHIP_TO_ORG", "N/A"),
        "Bill To": header_val.get("INVOICE_TO_ORG", "N/A"),
        "Salesrep": header_val.get("SALESREP", "N/A"),
        "Booked Flag": header.get("BOOKED_FLAG", "N/A"),
        "Open Flag": header.get("OPEN_FLAG", "N/A"),
    }

    line_tbl = data.get("X_LINE_TBL", {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}

    def _get_items(tbl, *keys):
        for k in keys:
            v = tbl.get(k)
            if v is not None:
                return [v] if isinstance(v, dict) else list(v)
        return []

    raw_lines = _get_items(line_tbl, "X_LINE_TBL_ITEM", "P_LINE_TBL_ITEM")
    raw_line_vals = _get_items(line_val_tbl, "X_LINE_VAL_TBL_ITEM", "P_LINE_VAL_TBL_ITEM")
    lines = []
    for i, line in enumerate(raw_lines):
        val = raw_line_vals[i] if i < len(raw_line_vals) else {}
        lines.append({
            "Line #": line.get("LINE_NUMBER", "N/A"),
            "Line ID": line.get("LINE_ID", "N/A"),
            "Item": line.get("ORDERED_ITEM", "N/A"),
            "Item Description": val.get("INVENTORY_ITEM", "N/A"),
            "Qty Ordered": line.get("ORDERED_QUANTITY", "N/A"),
            "UOM": line.get("ORDER_QUANTITY_UOM", "N/A"),
            "Unit List Price": line.get("UNIT_LIST_PRICE", "N/A"),
            "Unit Selling Price": line.get("UNIT_SELLING_PRICE", "N/A"),
            "Line Type": val.get("LINE_TYPE", "N/A"),
            "Payment Term": val.get("PAYMENT_TERM", "N/A"),
            "Flow Status": line.get("FLOW_STATUS_CODE", "N/A"),
            "Return Status": line.get("RETURN_STATUS", "N/A"),
        })
    return {"status": status, "message": message_text, "header_details": header_details, "lines": lines}


# ──────────────────────────────────────────────────
# HTML Generators for Email
# ──────────────────────────────────────────────────
def _build_email_layout(cname, report_type, ai_summary, table_html, alerts, faqs):
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    alerts_html = "<ul style='padding-left:20px;font-size:14px;margin-bottom:0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom:5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"
    faqs_html = "<table style='border-collapse:collapse;width:100%;border:none;font-size:14px;'>"
    faqs_html += "<tr><th style='text-align:left;padding:8px;border-bottom:1px solid #ccc;'>Question</th>"
    faqs_html += "<th style='text-align:left;padding:8px;border-bottom:1px solid #ccc;'>AI Answer</th></tr>"
    for q, a in faqs:
        faqs_html += f"<tr><td style='padding:8px;'>{q}</td><td style='padding:8px;'>{a}</td></tr>"
    faqs_html += "</table>"
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:800px;margin:auto;color:#000;padding:10px;">
        <h3 style="color:#000;font-size:16px;margin-top:0;">Header Details</h3>
        <ul style="list-style-type:disc;padding-left:20px;font-size:14px;margin-bottom:20px;">
            <li>Customer Name: {cname}</li><li>Contact Name: Account Primary</li>
            <li>Date of Report: {report_date}</li><li>Statement Period: {report_type}</li>
        </ul><hr>
        <h3 style="color:#000;font-size:16px;">Executive Summary</h3><p>{ai_summary}</p><hr>
        <h3 style="color:#000;font-size:16px;">Order Detail Table</h3>{table_html}<hr>
        <h3 style="color:#000;font-size:16px;">Exceptions & Alerts</h3>{alerts_html}<hr>
        <h3 style="color:#000;font-size:16px;">FAQ'S</h3>{faqs_html}<hr>
        <ul style="padding-left:20px;font-size:14px;">
            <li>Support contact: erp.support@centroid.com</li>
            <li>Disclaimer: This notification was generated automatically from the ERP environment</li>
            <li>Do-not-reply notice: Please do not reply directly to this email.</li>
        </ul>
    </div>"""


def generate_order_html(result, ai_summary):
    d = extract_erp_details(result)
    cname = d["header_details"].get("Customer", "Unknown Customer")
    order_num = d["header_details"].get("Order Number", "N/A")
    th = "border:none;padding:8px;text-align:left;font-weight:bold;"
    td = "border:none;padding:8px;"
    table = f"<table style='border-collapse:collapse;width:100%;font-size:14px;'><tr>"
    for h in ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for ln in d["lines"]:
        table += f"<tr><td style='{td}'>{order_num}</td><td style='{td}'>{ln.get('Item','N/A')}</td>"
        table += f"<td style='{td}'>{ln.get('Qty Ordered','N/A')}</td><td style='{td}'>{ln.get('Flow Status','N/A')}</td>"
        table += f"<td style='{td}'>TBD</td><td style='{td}'>Pending</td><td style='{td}'>N/A</td></tr>"
    table += "</table>"
    alerts = {"Backorders": "None detected", "Holds": "0", "Partial Shipments": "N/A", "Payment Holds": "Check customer balance"}
    faqs = [("Why is this order in current status?", "The order is waiting for the next step in the fulfillment cycle.")]
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", ai_summary, table, alerts, faqs)


def generate_search_html(res, ai_summary):
    th = "border:none;padding:8px;text-align:left;font-weight:bold;"
    td = "border:none;padding:8px;"
    table = f"<table style='border-collapse:collapse;width:100%;font-size:14px;'><tr>"
    for h in ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for r in res["rows"][:20]:
        table += f"<tr><td style='{td}'>{r[0]}</td><td style='{td}'>Multiple Lines</td><td style='{td}'>-</td>"
        table += f"<td style='{td}'>{r[1]}</td><td style='{td}'>{r[2]}</td><td style='{td}'>-</td><td style='{td}'>-</td></tr>"
    table += "</table>"
    alerts = {"Backorders": "N/A", "Holds": "N/A", "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("What are these search results?", f"Top results matching your query, up to {res['total_count']} orders.")]
    return _build_email_layout("System User", "Search Query Results", ai_summary, table, alerts, faqs)


def generate_customer_html(rows, cname, ai_summary):
    top_rows = rows[:50]
    th = "border:none;padding:8px;text-align:left;font-weight:bold;"
    td = "border:none;padding:8px;"
    table = f"<table style='border-collapse:collapse;width:100%;font-size:14px;'><tr>"
    for h in ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for r in top_rows:
        table += f"<tr><td style='{td}'>{r.get('ORDER_NUMBER','N/A')}</td>"
        table += f"<td style='{td}'>{r.get('ITEM_NUMBER','N/A')}</td>"
        table += f"<td style='{td}'>{r.get('ORDERED_QTY','N/A')}</td>"
        table += f"<td style='{td}'>{r.get('LINE_STATUS','N/A')}</td>"
        table += f"<td style='{td}'>{r.get('SCHEDULE_SHIP_DATE','N/A')}</td>"
        table += f"<td style='{td}'>{r.get('SHIPMENT_MODE','Pending')}</td>"
        table += f"<td style='{td}'>${r.get('INVOICE_BALANCE','0.00')}</td></tr>"
    table += "</table>"
    alerts = {"Backorders": "0", "Holds": "0", "Partial Shipments": "Check line statuses", "Payment Holds": "0"}
    faqs = [("Are there any delayed orders?", "Check the table for delayed order flags.")]
    return _build_email_layout(cname, "All Recent Customer Orders", ai_summary, table, alerts, faqs)


# ──────────────────────────────────────────────────
# Email
# ──────────────────────────────────────────────────
def send_erp_email(to_email, subject, body_text, html_table):
    sender = "erp.assistant@yourdomain.com"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    html_content = f"""<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
        <p style="color:#333;">{body_text.replace(chr(10),'<br>')}</p><br>{html_table}</body></html>"""
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login("pavanmaccha042@gmail.com", "ltvxbwhkzkrptueg")
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────────
# Order details by customer query
# ──────────────────────────────────────────────────
_ORDER_DETAIL_COLUMNS = [
    ("Customer Name", "CUSTOMER_NAME"), ("Order Number", "ORDER_NUMBER"),
    ("Order Date", "ORDER_DATE"), ("PO Number", "PO_NUMBER"),
    ("Line #", "LINE_NUMBER"), ("Item Number", "ITEM_NUMBER"),
    ("Ordered Qty", "ORDERED_QTY"), ("UOM", "ORDERED_UOM"),
    ("Unit List Price", "UNIT_LIST_PRICE"), ("Unit Selling Price", "UNIT_SELLING_PRICE"),
    ("Line Price", "LINE_PRICE"), ("Invoice Balance", "INVOICE_BALANCE"),
    ("Line Status", "LINE_STATUS"), ("Ship Date", "SCHEDULE_SHIP_DATE"),
    ("Actual Ship Date", "ACTUAL_SHIP_DATE"), ("Shipment Mode", "SHIPMENT_MODE"),
    ("On Hold", "ORDER_HOLD_FLAG"),
]


def get_order_details_by_customer(p_customer_name):
    sql = """
        SELECT HP.PARTY_NAME AS CUSTOMER_NAME, OOHA.ORDER_NUMBER,
            TO_CHAR(OOHA.ORDERED_DATE,'DD-MON-YYYY') AS ORDER_DATE,
            OOHA.CUST_PO_NUMBER AS PO_NUMBER, OOLA.CUST_PO_NUMBER AS PO_LINE,
            OOLA.LINE_NUMBER, MSI.SEGMENT1 AS ITEM_NUMBER,
            OOLA.ORDER_QUANTITY_UOM AS ORDERED_UOM, OOLA.ORDERED_QUANTITY AS ORDERED_QTY,
            OOLA.UNIT_LIST_PRICE, OOLA.UNIT_SELLING_PRICE,
            (OOLA.ORDERED_QUANTITY * OOLA.UNIT_SELLING_PRICE) AS LINE_PRICE,
            OOLA.FLOW_STATUS_CODE AS LINE_STATUS,
            TO_CHAR(NVL(OOLA.SCHEDULE_SHIP_DATE,OOLA.REQUEST_DATE),'DD-MON-YYYY') AS SCHEDULE_SHIP_DATE,
            TO_CHAR(OOLA.ACTUAL_SHIPMENT_DATE,'DD-MON-YYYY') AS ACTUAL_SHIP_DATE,
            OOLA.SHIPPING_METHOD_CODE AS SHIPMENT_MODE,
            DECODE(OOLA.CANCELLED_FLAG,'Y','Y','N') AS ORDER_HOLD_FLAG,
            (SELECT NVL(SUM(APS.AMOUNT_DUE_REMAINING),0) FROM AR_PAYMENT_SCHEDULES_ALL APS,
             RA_CUSTOMER_TRX_ALL RCTA WHERE APS.CUSTOMER_TRX_ID=RCTA.CUSTOMER_TRX_ID
             AND RCTA.INTERFACE_HEADER_ATTRIBUTE1=TO_CHAR(OOHA.ORDER_NUMBER)) AS INVOICE_BALANCE
        FROM OE_ORDER_HEADERS_ALL OOHA, OE_ORDER_LINES_ALL OOLA,
            MTL_SYSTEM_ITEMS_B MSI, HZ_CUST_ACCOUNTS HCAA, HZ_PARTIES HP
        WHERE OOHA.HEADER_ID=OOLA.HEADER_ID AND MSI.INVENTORY_ITEM_ID=OOLA.INVENTORY_ITEM_ID
            AND MSI.ORGANIZATION_ID=OOLA.SHIP_FROM_ORG_ID
            AND HCAA.CUST_ACCOUNT_ID=OOHA.SOLD_TO_ORG_ID AND HP.PARTY_ID=HCAA.PARTY_ID
            AND HP.PARTY_NAME=:p_customer_name
        ORDER BY OOHA.ORDER_NUMBER, OOLA.LINE_NUMBER
    """
    rows = bot.execute_query(sql, {"p_customer_name": p_customer_name})
    return rows if rows else []


# ══════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/state", methods=["GET"])
def api_state():
    """Return current session state to the frontend."""
    s = _get_state()
    return jsonify({
        "stage": s["stage"],
        "messages": s["messages"],
        "collected": s["collected"],
        "auto_email_enabled": s["auto_email_enabled"],
        "auto_email_to": s["auto_email_to"],
        "auto_email_status": s["auto_email_status"],
        "faq": list(FAQ_DATA.keys()),
    })


@app.route("/api/back", methods=["POST"])
def api_back():
    s = _reset_state()
    s["stage"] = "chat"
    return jsonify({"ok": True, "stage": "chat"})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    sid = session.get("sid")
    if sid and sid in _sessions:
        del _sessions[sid]
    return jsonify({"ok": True})


@app.route("/api/faq", methods=["POST"])
def api_faq():
    q = request.json.get("question", "")
    s = _get_state()
    if q in FAQ_DATA:
        ans = FAQ_DATA[q]
        s["messages"].append({"role": "user", "content": q})
        s["messages"].append({"role": "assistant", "content": ans})
        return jsonify({"answer": ans, "messages": s["messages"]})
    return jsonify({"answer": "I don't have an answer for that.", "messages": s["messages"]})


# ──────────────────────────────────────────────────
# Main chat endpoint
# ──────────────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def api_chat():
    s = _get_state()
    prompt = request.json.get("message", "").strip()
    if not prompt:
        return jsonify({"error": "Empty message"}), 400

    if prompt.lower() in ("exit", "quit", "stop", "cancel"):
        _reset_state()
        s = _get_state()
        s["stage"] = "chat"
        return jsonify({"messages": s["messages"], "stage": "chat", "response": "Returning to chat."})

    s["messages"].append({"role": "user", "content": prompt})
    s["gh_history"].append({"role": "user", "content": prompt})

    # Smart intent extraction
    smart_extracted = get_smart_intent(s["messages"], prompt)
    extracted = bot.github_extract_intent(prompt) if hasattr(bot, "github_extract_intent") else {}
    for k, v in smart_extracted.items():
        if v is not None and str(v).strip() != "":
            extracted[k] = v

    prompt_lower = prompt.lower()
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', prompt)

    if "email" in prompt_lower or "mail" in prompt_lower or "send" in prompt_lower:
        if not extracted.get("action") or extracted.get("action") == "unknown":
            extracted["action"] = "email"
        if email_match:
            extracted["email_address"] = email_match.group(0)

    if not extracted.get("year"):
        year_match = re.search(r'\b(20\d{2})\b', prompt)
        if year_match:
            extracted["year"] = int(year_match.group(1))

    if not extracted.get("status"):
        status_keywords = {
            "booked": "BOOKED", "entered": "ENTERED", "cancelled": "CANCELLED",
            "canceled": "CANCELLED", "shipped": "SHIPPED", "closed": "CLOSED",
            "pending": "ENTERED", "open": "BOOKED", "invoiced": "INVOICED", "delivered": "DELIVERED",
        }
        for kw, val in status_keywords.items():
            if kw in prompt_lower:
                extracted["status"] = val
                break

    if not extracted.get("date_range"):
        for pattern, label in [
            (r'last\s+month', 'last month'), (r'last\s+quarter', 'last quarter'),
            (r'last\s+week', 'last week'), (r'this\s+month', 'this month'),
            (r'this\s+quarter', 'this quarter'), (r'this\s+week', 'this week'),
            (r'last\s+30\s+days', 'last 30 days'), (r'last\s+90\s+days', 'last 90 days'),
            (r'last\s+year', 'last year'), (r'ytd|year\s+to\s+date', 'year to date'),
        ]:
            if re.search(pattern, prompt_lower):
                extracted["date_range"] = label
                break

    # Determine action
    if "create" in prompt_lower or "new order" in prompt_lower:
        extracted["action"] = "create"

    od_customer_match = re.search(r'order\s+details?\s+(?:for|by|of)?\s+(?:customer\s+)?(.+)', prompt_lower)
    if od_customer_match or ("order details" in prompt_lower and "customer" in prompt_lower):
        extracted["action"] = "order_details"

    has_specific_order = bool(extracted.get("order_number") or s["collected"].get("order_number"))
    has_search_filters = bool(extracted.get("year") or extracted.get("date_range") or extracted.get("status"))
    if has_search_filters and not has_specific_order and extracted.get("action") not in ["create", "order_details", "email"]:
        extracted["action"] = "search"

    if extracted.get("action") not in ["create", "search", "order_details", "email"]:
        if any(w in prompt_lower for w in ["get", "find", "search", "show", "fetch", "retrieve"]):
            if not extracted.get("action") or extracted.get("action") == "unknown":
                extracted["action"] = "get"

    action = extracted.get("action", "unknown")
    merge_fields(s, extracted)

    response_msg = ""

    # ── ORDER DETAILS BY CUSTOMER ──
    if action == "order_details" or (od_customer_match and action not in ["create", "email"]):
        name_match = re.search(r'order\s+details?\s+(?:for|by|of)?\s+(?:customer\s+)?(.+)', prompt, re.IGNORECASE)
        cname = ""
        if name_match:
            cname = name_match.group(1).strip()
        elif extracted.get("customer_name"):
            cname = extracted.get("customer_name")
        s["order_details_customer_name"] = cname
        s["order_details_rows"] = []
        s["order_details_page"] = 0
        s["stage"] = "order_details_by_customer"
        response_msg = "Opening order details search for customer orders..."
        s["messages"].append({"role": "assistant", "content": response_msg})
        return jsonify({"messages": s["messages"], "stage": s["stage"],
                        "customer_name": cname, "response": response_msg})

    # ── EMAIL ──
    if action == "email" or s["action"] == "email":
        s["action"] = "email"
        s["stage"] = "send_email_flow"
        response_msg = "Preparing email draft. Please verify the details."
        s["messages"].append({"role": "assistant", "content": response_msg})
        return jsonify({"messages": s["messages"], "stage": s["stage"],
                        "email_payload_html": s.get("email_payload_html", ""),
                        "collected": s["collected"], "response": response_msg})

    # ── ADVANCED SEARCH ──
    if action == "search":
        adv_year = extracted.get("year")
        adv_date_range = extracted.get("date_range")
        adv_status = extracted.get("status")
        try:
            res = bot.get_orders_advanced(adv_date_range, adv_year, adv_status)
            if not res or not isinstance(res, dict):
                response_msg = "No results returned from the search. Try different filters."
                s["messages"].append({"role": "assistant", "content": response_msg})
                return jsonify({"messages": s["messages"], "stage": "chat", "response": response_msg})
            total = res.get("total_count", 0)
            rows = res.get("rows", [])
            if total == 0 or not rows:
                response_msg = "No orders found. Try broadening your search."
                s["messages"].append({"role": "assistant", "content": response_msg})
                return jsonify({"messages": s["messages"], "stage": "chat", "response": response_msg})

            summary_ctx = {"total_found": total, "filters": {"year": adv_year, "date_range": adv_date_range, "status": adv_status}, "sample": rows[:5]}
            ai_summary = generate_ai_summary("Advanced Order Search", summary_ctx)
            s["email_payload_html"] = generate_search_html(res, ai_summary)

            # Convert datetime objects in rows to strings
            serializable_rows = []
            for r in rows:
                if isinstance(r, (list, tuple)):
                    serializable_rows.append([str(c) if not isinstance(c, (str, int, float, type(None))) else c for c in r])
                else:
                    serializable_rows.append(r)

            response_msg = f"Found {total} order(s).\n\n{ai_summary}"
            s["messages"].append({"role": "assistant", "content": response_msg})
            s["api_result"] = {"total_count": total, "rows": serializable_rows, "columns": res.get("columns", ["Order Number", "Status", "Creation Date"])}
            s["stage"] = "show_advanced_search"
            return jsonify({"messages": s["messages"], "stage": s["stage"],
                            "search_results": s["api_result"], "response": response_msg})
        except Exception as e:
            response_msg = f"Search Error: {str(e)}"
            s["messages"].append({"role": "assistant", "content": response_msg})
            return jsonify({"messages": s["messages"], "stage": "chat", "response": response_msg})

    # ── CREATE ORDER ──
    if action == "create" or s["action"] == "create":
        s["action"] = "create"
        missing = missing_minimum(s)
        if missing:
            next_missing = missing[0]
            prompts = {
                "Customer PO Number": "Got it. Let's create an order. What is the **Customer PO Number**?",
                "Ordered Item code": "What is the **Ordered Item code** you would like?",
                "Ordered Quantity": "How many do you need? Please enter the **Ordered Quantity**.",
            }
            response_msg = prompts.get(next_missing, f"Please provide the {next_missing}.")
            s["pending_field"] = next_missing
            s["messages"].append({"role": "assistant", "content": response_msg})
            s["gh_history"].append({"role": "assistant", "content": response_msg})
            return jsonify({"messages": s["messages"], "stage": "chat", "response": response_msg})
        else:
            return _begin_resolve(s)

    # ── GET SPECIFIC ORDER ──
    if action == "get" or s["action"] == "get":
        s["action"] = "get"
        order_num = s["collected"].get("order_number")
        if order_num is None:
            q = bot.github_clarify(s["gh_history"], ["Order Number"])
            s["messages"].append({"role": "assistant", "content": q})
            s["gh_history"].append({"role": "assistant", "content": q})
            return jsonify({"messages": s["messages"], "stage": "chat", "response": q})
        else:
            try:
                result = bot.get_order(int(order_num))
                parsed = extract_erp_details(result)
                ai_summary = generate_ai_summary("Retrieve Specific Order", parsed)
                s["email_payload_html"] = generate_order_html(result, ai_summary)
                response_msg = f"**AI Summary:**\n{ai_summary}"
                s["messages"].append({"role": "assistant", "content": response_msg})
                s["api_result"] = result
                # Extract header_id and order_number for add-line
                hid = parsed["header_details"].get("Header ID")
                onum = parsed["header_details"].get("Order Number")
                if hid and hid != "N/A":
                    s["add_line_header_id"] = hid
                    s["add_line_order_number"] = onum
                s["stage"] = "show_get_order"
                return jsonify({"messages": s["messages"], "stage": s["stage"],
                                "order_data": parsed, "api_result": result,
                                "response": response_msg})
            except Exception as e:
                response_msg = f"Failed to retrieve order: {e}"
                s["messages"].append({"role": "assistant", "content": response_msg})
                return jsonify({"messages": s["messages"], "stage": "chat", "response": response_msg})

    # ── UNKNOWN ──
    fallback = bot.github_clarify(
        s["gh_history"],
        ["action: 'create a new order', 'get order by number', 'search orders by year/status/date range', or 'order details for customer <name>'"],
    )
    s["messages"].append({"role": "assistant", "content": fallback})
    s["gh_history"].append({"role": "assistant", "content": fallback})
    return jsonify({"messages": s["messages"], "stage": "chat", "response": fallback})


# ──────────────────────────────────────────────────
# Resolve flow (item → price → term → rep → customer → confirm)
# ──────────────────────────────────────────────────
def _begin_resolve(s):
    c = s["collected"]
    offs = s["offsets"]

    # Step 1 — Resolve Item
    if c.get("ordered_item") and not c.get("inventory_item_id"):
        rows = bot.get_inventory_item_rows(c["ordered_item"], offset=offs["item"])
        if not rows:
            msg = f"No inventory items found matching '{c['ordered_item']}'. Please try a different item code."
            c["ordered_item"] = None
            s["messages"].append({"role": "assistant", "content": msg})
            s["stage"] = "chat"
            return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})
        elif len(rows) == 1 and offs["item"] == 0:
            c["inventory_item_id"] = rows[0]["inventory_item_id"]
            c["ordered_item"] = rows[0]["segment1"]
            return _begin_resolve(s)  # continue resolving
        else:
            s["item_rows"] = rows
            s["stage"] = "select_item"
            msg = "Please select an item from the list."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "select_item",
                            "rows": rows, "response": msg})

    # Step 2 — Resolve Price
    if c.get("inventory_item_id") and c.get("quantity") and not c.get("price_list_id"):
        rows = bot.get_price_details_rows(c["ordered_item"], float(c["quantity"]), c["inventory_item_id"], offset=offs["price"])
        if not rows:
            msg = f"No price lists found for item '{c['ordered_item']}'. Cannot proceed."
            s["messages"].append({"role": "assistant", "content": msg})
            s["stage"] = "chat"
            return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})
        elif len(rows) == 1 and offs["price"] == 0:
            c["price_list_id"] = rows[0]["price_list_id"]
            c["unit_list_price"] = rows[0]["unit_list_price"]
            c["unit_selling_price"] = rows[0]["unit_list_price"]
            s["stage"] = "selling_price_override"
            msg = f"Unit List Price: ${rows[0]['unit_list_price']:.2f}. Enter a custom selling price or confirm to use the list price."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "selling_price_override",
                            "unit_list_price": rows[0]["unit_list_price"], "response": msg})
        else:
            s["price_rows"] = rows
            s["stage"] = "select_price"
            msg = "Please select a price list."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "select_price",
                            "rows": rows, "response": msg})

    # Step 3 — Resolve Payment Term
    if not c.get("payment_term_id"):
        rows = bot.get_payment_term_rows(offset=offs["term"])
        if not rows:
            msg = "No payment terms found. Cannot proceed."
            s["messages"].append({"role": "assistant", "content": msg})
            s["stage"] = "chat"
            return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})
        elif len(rows) == 1 and offs["term"] == 0:
            c["payment_term_id"] = rows[0]["term_id"]
            c["payment_term_name"] = rows[0]["term_name"]
            return _begin_resolve(s)
        else:
            s["term_rows"] = rows
            s["stage"] = "select_term"
            msg = "Please select a payment term."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "select_term",
                            "rows": rows, "response": msg})

    # Step 4 — Resolve Salesrep
    if not c.get("salesrep_id"):
        rows = bot.get_salesrep_rows(offset=offs["rep"])
        if not rows:
            msg = "No sales representatives found. Cannot proceed."
            s["messages"].append({"role": "assistant", "content": msg})
            s["stage"] = "chat"
            return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})
        elif len(rows) == 1 and offs["rep"] == 0:
            c["salesrep_id"] = rows[0]["salesrep_id"]
            c["salesrep_name"] = rows[0]["salesrep_name"]
            return _begin_resolve(s)
        else:
            s["rep_rows"] = rows
            s["stage"] = "select_rep"
            msg = "Please select a sales representative."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "select_rep",
                            "rows": rows, "response": msg})

    # Step 5 — Resolve Line Type
    if not c.get("line_type_id") and hasattr(bot, 'get_line_type_rows'):
        rows = bot.get_line_type_rows(offset=offs.get("line_type", 0))
        s["line_type_rows"] = rows
        s["stage"] = "select_line_type"
        msg = "Please select a line type."
        s["messages"].append({"role": "assistant", "content": msg})
        return jsonify({"messages": s["messages"], "stage": "select_line_type",
                        "rows": rows, "response": msg})

    # Step 6 — Resolve Customer
    if not c.get("sold_to_org_id") or not c.get("ship_to_org_id"):
        if c.get("cust_account_id"):
            sites = bot.get_customer_sites_by_account(c["cust_account_id"])
            if not sites:
                msg = "No active SHIP_TO sites for this customer."
                c["cust_account_id"] = None
                s["stage"] = "select_customer"
                s["messages"].append({"role": "assistant", "content": msg})
                return jsonify({"messages": s["messages"], "stage": "select_customer",
                                "rows": [], "response": msg})
            elif len(sites) == 1:
                c["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                c["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                c["customer_name"] = sites[0]["customer_name"]
                return _begin_resolve(s)
            else:
                s["site_rows"] = sites
                s["stage"] = "select_site"
                msg = "Please select a ship-to site."
                s["messages"].append({"role": "assistant", "content": msg})
                return jsonify({"messages": s["messages"], "stage": "select_site",
                                "rows": sites, "response": msg})
        elif c.get("customer_name"):
            rows = bot.get_customer_by_name_rows(c["customer_name"], offset=offs["customer"])
            s["customer_rows"] = rows
            s["stage"] = "select_customer"
            msg = "Please select a customer."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "select_customer",
                            "rows": rows, "response": msg})
        elif c.get("inventory_item_id"):
            rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=offs["customer_by_item"])
            s["customer_by_item_rows"] = rows
            s["stage"] = "select_customer_by_item"
            msg = "Please select a customer."
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"messages": s["messages"], "stage": "select_customer_by_item",
                            "rows": rows, "response": msg})
        else:
            msg = "Could not determine a customer. Please provide a customer name."
            s["messages"].append({"role": "assistant", "content": msg})
            s["stage"] = "chat"
            return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})

    # All resolved → confirm
    s["stage"] = "confirm_order"
    summary_items = {k: v for k, v in c.items() if v is not None}
    msg = "Order Summary — please review before submitting."
    s["messages"].append({"role": "assistant", "content": msg})
    return jsonify({"messages": s["messages"], "stage": "confirm_order",
                    "collected": summary_items, "response": msg})


# ──────────────────────────────────────────────────
# Selection endpoints
# ──────────────────────────────────────────────────
@app.route("/api/select", methods=["POST"])
def api_select():
    s = _get_state()
    data = request.json
    stage = data.get("stage")
    idx = data.get("index", 0)

    if stage == "select_item":
        rows = s.get("item_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["inventory_item_id"] = row["inventory_item_id"]
            s["collected"]["ordered_item"] = row["segment1"]
            msg = f"Item selected: {row['segment1']} — {row['description']}"
            s["messages"].append({"role": "assistant", "content": msg})
            return _begin_resolve(s)

    elif stage == "select_price":
        rows = s.get("price_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["price_list_id"] = row["price_list_id"]
            s["collected"]["price_list_name"] = row["price_list_name"]
            s["collected"]["unit_list_price"] = row["unit_list_price"]
            s["collected"]["unit_selling_price"] = row["unit_list_price"]
            msg = f"Price List: {row['price_list_name']} — Unit Price: ${row['unit_list_price']:.2f}"
            s["messages"].append({"role": "assistant", "content": msg})
            s["stage"] = "selling_price_override"
            return jsonify({"messages": s["messages"], "stage": "selling_price_override",
                            "unit_list_price": row["unit_list_price"], "response": msg})

    elif stage == "select_term":
        rows = s.get("term_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["payment_term_id"] = row["term_id"]
            s["collected"]["payment_term_name"] = row["term_name"]
            msg = f"Payment Term: {row['term_name']}"
            s["messages"].append({"role": "assistant", "content": msg})
            return _begin_resolve(s)

    elif stage == "select_rep":
        rows = s.get("rep_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["salesrep_id"] = row["salesrep_id"]
            s["collected"]["salesrep_name"] = row["salesrep_name"]
            msg = f"Sales Rep: {row['salesrep_name']}"
            s["messages"].append({"role": "assistant", "content": msg})
            return _begin_resolve(s)

    elif stage == "select_line_type":
        rows = s.get("line_type_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["line_type_id"] = row["line_type_id"]
            msg = f"Line Type: {row['line_type_name']} (ID: {row['line_type_id']})"
            s["messages"].append({"role": "assistant", "content": msg})
            return _begin_resolve(s)

    elif stage == "select_customer":
        rows = s.get("customer_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["cust_account_id"] = row["cust_account_id"]
            s["collected"]["customer_name"] = row["customer_name"]
            sites = bot.get_customer_sites_by_account(row["cust_account_id"])
            if not sites:
                msg = f"No active SHIP_TO sites found for {row['customer_name']}."
                s["messages"].append({"role": "assistant", "content": msg})
                s["stage"] = "chat"
                return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})
            elif len(sites) == 1:
                s["collected"]["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                s["collected"]["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                msg = f"Customer: {sites[0]['customer_name']} | Sold-to: {sites[0]['sold_to_org_id']} | Ship-to: {sites[0]['ship_to_org_id']}"
                s["messages"].append({"role": "assistant", "content": msg})
                return _begin_resolve(s)
            else:
                s["site_rows"] = sites
                s["stage"] = "select_site"
                msg = "Multiple sites found. Please select a ship-to site."
                s["messages"].append({"role": "assistant", "content": msg})
                return jsonify({"messages": s["messages"], "stage": "select_site",
                                "rows": sites, "response": msg})

    elif stage == "select_customer_by_item":
        rows = s.get("customer_by_item_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["cust_account_id"] = row["cust_account_id"]
            s["collected"]["customer_name"] = row["customer_name"]
            sites = bot.get_customer_sites_by_account(row["cust_account_id"])
            if not sites:
                msg = f"No active SHIP_TO sites found for {row['customer_name']}."
                s["messages"].append({"role": "assistant", "content": msg})
                s["stage"] = "chat"
                return jsonify({"messages": s["messages"], "stage": "chat", "response": msg})
            elif len(sites) == 1:
                s["collected"]["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                s["collected"]["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                msg = f"Customer: {sites[0]['customer_name']}"
                s["messages"].append({"role": "assistant", "content": msg})
                return _begin_resolve(s)
            else:
                s["site_rows"] = sites
                s["stage"] = "select_site"
                return jsonify({"messages": s["messages"], "stage": "select_site",
                                "rows": sites, "response": "Select a ship-to site."})

    elif stage == "select_site":
        rows = s.get("site_rows", [])
        if 0 <= idx < len(rows):
            row = rows[idx]
            s["collected"]["sold_to_org_id"] = row["sold_to_org_id"]
            s["collected"]["ship_to_org_id"] = row["ship_to_org_id"]
            s["collected"]["customer_name"] = row["customer_name"]
            msg = f"Customer: {row['customer_name']} | Ship-to: {row['ship_to_org_id']}"
            s["messages"].append({"role": "assistant", "content": msg})
            return _begin_resolve(s)

    return jsonify({"error": "Invalid selection"}), 400


@app.route("/api/selling-price", methods=["POST"])
def api_selling_price():
    s = _get_state()
    sp = request.json.get("selling_price", "")
    c = s["collected"]
    if sp and sp.strip():
        val = bot.parse_numeric_value(sp, allow_float=True)
        if val is not None:
            c["unit_selling_price"] = val
    else:
        c["unit_selling_price"] = c.get("unit_list_price", 0)
    msg = f"Selling Price set to: ${c['unit_selling_price']:.2f}"
    s["messages"].append({"role": "assistant", "content": msg})
    return _begin_resolve(s)


@app.route("/api/confirm-order", methods=["POST"])
def api_confirm_order():
    s = _get_state()
    c = s["collected"]
    try:
        import inspect
        payload_kwargs = {
            "p_cust_po": c["cpo"], "p_item_id": c["inventory_item_id"],
            "p_ordered_item": c["ordered_item"], "p_qty": c["quantity"],
            "p_price": c["unit_list_price"], "p_selling_price": c["unit_selling_price"],
            "p_payment_term_id": c["payment_term_id"], "p_price_list_id": c["price_list_id"],
            "p_salesrep_id": c["salesrep_id"], "p_ship_to_org": c["ship_to_org_id"],
            "p_sold_to_org": c["sold_to_org_id"], "p_operating_unit": bot.OPERATING_UNIT,
        }
        _cp_params = inspect.signature(bot.create_payload).parameters
        if c.get("line_type_id") and "p_line_type_id" in _cp_params:
            payload_kwargs["p_line_type_id"] = c["line_type_id"]
        payload = bot.create_payload(**payload_kwargs)
        result = bot.send_order(payload)
        s["api_result"] = result
        parsed = extract_erp_details(result)
        ai_summary = generate_ai_summary("Create New Sales Order", parsed)
        s["email_payload_html"] = generate_order_html(result, ai_summary)
        hid = parsed["header_details"].get("Header ID")
        onum = parsed["header_details"].get("Order Number")
        if hid and hid != "N/A":
            s["add_line_header_id"] = hid
            s["add_line_order_number"] = onum
        response_msg = f"**AI Summary:**\n{ai_summary}"
        s["messages"].append({"role": "assistant", "content": response_msg})
        s["stage"] = "done"
        return jsonify({"messages": s["messages"], "stage": "done",
                        "order_data": parsed, "response": response_msg,
                        "header_id": hid, "order_number": onum})
    except Exception as e:
        msg = f"Submit Error: {e}"
        s["messages"].append({"role": "assistant", "content": msg})
        s["stage"] = "error"
        return jsonify({"messages": s["messages"], "stage": "error", "response": msg})


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    s = _get_state()
    data = request.json
    to_email = data.get("to", "")
    subject = data.get("subject", "Oracle ERP Order Details Update")
    body = data.get("body", "Please find the requested order details structured below.")
    html = s.get("email_payload_html", "")
    if not to_email:
        return jsonify({"error": "Email address is required."}), 400
    success, msg = send_erp_email(to_email, subject, body, html)
    if success:
        response_msg = f"Email sent successfully to {to_email}!"
        s["messages"].append({"role": "assistant", "content": response_msg})
        s["stage"] = "chat"
        return jsonify({"ok": True, "messages": s["messages"], "stage": "chat", "response": response_msg})
    else:
        return jsonify({"ok": False, "error": msg})


@app.route("/api/order-details", methods=["POST"])
def api_order_details():
    s = _get_state()
    cname = request.json.get("customer_name", "").strip()
    if not cname:
        return jsonify({"error": "Customer name is required."}), 400
    try:
        rows = get_order_details_by_customer(cname)
        s["order_details_customer_name"] = cname
        s["order_details_rows"] = rows
        s["order_details_page"] = 0
        if rows:
            summary_ctx = {"customer": cname, "total_lines_found": len(rows), "sample_data": rows[:3]}
            ai_summary = generate_ai_summary("Retrieve Orders by Customer", summary_ctx)
            s["email_payload_html"] = generate_customer_html(rows, cname, ai_summary)
            # Convert rows for JSON serialization
            serializable = []
            for r in rows:
                sr = {}
                for k, v in r.items():
                    sr[k] = str(v) if not isinstance(v, (str, int, float, type(None))) else v
                serializable.append(sr)
            response_msg = f"Found {len(rows)} line(s) for customer '{cname}'.\n\n{ai_summary}"
            s["messages"].append({"role": "assistant", "content": response_msg})
            return jsonify({"ok": True, "rows": serializable, "total": len(rows),
                            "columns": [lbl for lbl, _ in _ORDER_DETAIL_COLUMNS],
                            "ai_summary": ai_summary, "response": response_msg,
                            "messages": s["messages"]})
        else:
            response_msg = f"No orders found for customer '{cname}'."
            s["messages"].append({"role": "assistant", "content": response_msg})
            return jsonify({"ok": True, "rows": [], "total": 0, "response": response_msg,
                            "messages": s["messages"]})
    except Exception as e:
        msg = f"Error fetching order details: {e}"
        s["messages"].append({"role": "assistant", "content": msg})
        return jsonify({"ok": False, "error": msg, "messages": s["messages"]})


@app.route("/api/fetch-next", methods=["POST"])
def api_fetch_next():
    """Fetch next/prev page of selection rows."""
    s = _get_state()
    data = request.json
    stage = data.get("stage")
    direction = data.get("direction", "next")  # "next" or "prev"

    offset_key_map = {
        "select_item": "item", "select_price": "price", "select_term": "term",
        "select_rep": "rep", "select_customer": "customer",
        "select_customer_by_item": "customer_by_item", "select_line_type": "line_type",
    }
    ok = offset_key_map.get(stage)
    if not ok:
        return jsonify({"error": "Invalid stage"}), 400

    if direction == "next":
        s["offsets"][ok] += bot.MAX_CHOICES
    else:
        s["offsets"][ok] = max(0, s["offsets"][ok] - bot.MAX_CHOICES)

    fetch_map = {
        "select_item": lambda: bot.get_inventory_item_rows(s["collected"]["ordered_item"], offset=s["offsets"]["item"]),
        "select_price": lambda: bot.get_price_details_rows(s["collected"]["ordered_item"], float(s["collected"]["quantity"]), s["collected"]["inventory_item_id"], offset=s["offsets"]["price"]),
        "select_term": lambda: bot.get_payment_term_rows(offset=s["offsets"]["term"]),
        "select_rep": lambda: bot.get_salesrep_rows(offset=s["offsets"]["rep"]),
        "select_customer": lambda: bot.get_customer_by_name_rows(s["collected"].get("customer_name", ""), offset=s["offsets"]["customer"]),
        "select_customer_by_item": lambda: bot.get_customers_by_inventory_item_rows(s["collected"]["inventory_item_id"], offset=s["offsets"]["customer_by_item"]),
    }
    if hasattr(bot, 'get_line_type_rows'):
        fetch_map["select_line_type"] = lambda: bot.get_line_type_rows(offset=s["offsets"]["line_type"])

    rows = fetch_map.get(stage, lambda: [])()
    row_key_map = {
        "select_item": "item_rows", "select_price": "price_rows", "select_term": "term_rows",
        "select_rep": "rep_rows", "select_customer": "customer_rows",
        "select_customer_by_item": "customer_by_item_rows", "select_line_type": "line_type_rows",
    }
    s[row_key_map[stage]] = rows
    return jsonify({"rows": rows, "offset": s["offsets"][ok]})


@app.route("/api/search-customer", methods=["POST"])
def api_search_customer():
    s = _get_state()
    name = request.json.get("name", "").strip()
    s["offsets"]["customer"] = 0
    s["collected"]["customer_name"] = name
    rows = bot.get_customer_by_name_rows(name, offset=0)
    s["customer_rows"] = rows
    s["stage"] = "select_customer"
    return jsonify({"rows": rows, "stage": "select_customer"})


@app.route("/api/add-line", methods=["POST"])
def api_add_line():
    """Handle add-line flow steps."""
    s = _get_state()
    data = request.json
    action = data.get("action")

    if action == "start":
        s["add_line_stage"] = "add_line_item"
        s["add_line_data"] = {}
        s["add_line_item_rows"] = []
        s["add_line_price_rows"] = []
        s["add_line_term_rows"] = []
        return jsonify({"ok": True, "sub_stage": "add_line_item"})

    elif action == "search_items":
        query = data.get("query", "")
        s["offsets"]["item"] = 0
        rows = bot.get_inventory_item_rows(query, offset=0)
        s["add_line_item_rows"] = rows
        return jsonify({"rows": rows})

    elif action == "select_item":
        idx = data.get("index", 0)
        rows = s.get("add_line_item_rows", [])
        if 0 <= idx < len(rows):
            s["add_line_data"]["inventory_item_id"] = rows[idx]["inventory_item_id"]
            s["add_line_data"]["ordered_item"] = rows[idx]["segment1"]
            s["add_line_stage"] = "add_line_qty"
            return jsonify({"ok": True, "sub_stage": "add_line_qty",
                            "ordered_item": rows[idx]["segment1"]})

    elif action == "set_qty":
        qty = data.get("quantity")
        val = bot.parse_numeric_value(str(qty), allow_float=True)
        if val is None:
            return jsonify({"error": "Invalid quantity"}), 400
        s["add_line_data"]["quantity"] = val
        rows = bot.get_price_details_rows(s["add_line_data"]["ordered_item"], val,
                                          s["add_line_data"]["inventory_item_id"], offset=0)
        s["add_line_price_rows"] = rows
        s["add_line_stage"] = "add_line_price"
        return jsonify({"ok": True, "sub_stage": "add_line_price", "rows": rows})

    elif action == "select_price":
        idx = data.get("index", 0)
        rows = s.get("add_line_price_rows", [])
        if 0 <= idx < len(rows):
            s["add_line_data"]["price_list_id"] = rows[idx]["price_list_id"]
            s["add_line_data"]["unit_list_price"] = rows[idx]["unit_list_price"]
            s["add_line_data"]["unit_selling_price"] = rows[idx]["unit_list_price"]
            s["add_line_stage"] = "add_line_selling_price"
            return jsonify({"ok": True, "sub_stage": "add_line_selling_price",
                            "unit_list_price": rows[idx]["unit_list_price"]})

    elif action == "set_selling_price":
        sp = data.get("selling_price", "")
        ald = s["add_line_data"]
        if sp and str(sp).strip():
            val = bot.parse_numeric_value(str(sp), allow_float=True)
            if val is not None:
                ald["unit_selling_price"] = val
        else:
            ald["unit_selling_price"] = ald.get("unit_list_price", 0)
        rows = bot.get_payment_term_rows(offset=0)
        s["add_line_term_rows"] = rows
        s["add_line_stage"] = "add_line_term"
        return jsonify({"ok": True, "sub_stage": "add_line_term", "rows": rows})

    elif action == "select_term":
        idx = data.get("index", 0)
        rows = s.get("add_line_term_rows", [])
        if 0 <= idx < len(rows):
            s["add_line_data"]["payment_term_id"] = rows[idx]["term_id"]
            s["add_line_stage"] = "add_line_submit"
            return jsonify({"ok": True, "sub_stage": "add_line_submit",
                            "add_line_data": s["add_line_data"]})

    elif action == "submit":
        ald = s["add_line_data"]
        header_id = s.get("add_line_header_id")
        try:
            import inspect
            payload_kwargs = {
                "p_header_id": header_id, "p_item_id": ald["inventory_item_id"],
                "p_ordered_item": ald["ordered_item"], "p_qty": ald["quantity"],
                "p_price": ald["unit_list_price"], "p_selling_price": ald["unit_selling_price"],
                "p_payment_term_id": ald["payment_term_id"], "p_price_list_id": ald["price_list_id"],
            }
            _alp = inspect.signature(bot.create_add_line_payload).parameters
            if ald.get("line_type_id") and "p_line_type_id" in _alp:
                payload_kwargs["p_line_type_id"] = ald["line_type_id"]
            payload = bot.create_add_line_payload(**payload_kwargs)
            result = bot.send_order(payload)
            s["api_result"] = result
            parsed = extract_erp_details(result)
            ai_summary = generate_ai_summary("Add Line to Order", parsed)
            s["email_payload_html"] = generate_order_html(result, ai_summary)
            msg = f"**AI Summary:**\n{ai_summary}"
            s["messages"].append({"role": "assistant", "content": msg})
            s["add_line_stage"] = None
            s["add_line_data"] = {}
            s["stage"] = "done"
            return jsonify({"ok": True, "messages": s["messages"], "stage": "done",
                            "order_data": parsed, "response": msg})
        except Exception as e:
            msg = f"Failed to add line: {e}"
            s["messages"].append({"role": "assistant", "content": msg})
            return jsonify({"ok": False, "error": msg, "messages": s["messages"]})

    return jsonify({"error": "Invalid add-line action"}), 400


@app.route("/api/voice", methods=["POST"])
def api_voice():
    """Handle voice input — supports browser Web Speech API (preferred) or server-side mic."""
    data = request.json or {}
    
    # If browser already transcribed via Web Speech API, just return it
    browser_text = data.get("text", "").strip()
    if browser_text:
        return jsonify({"text": browser_text})
    
    # Fallback: server-side microphone recording
    if not bot.VOICE_AVAILABLE:
        return jsonify({"error": "Voice not available. Use browser microphone instead.", "use_browser": True}), 400
    try:
        bot.stop_speaking()
        listen_secs = max(getattr(bot, "VOICE_DURATION", 5), 5)
        voice_result = bot.recognize_speech(listen_secs)
        if voice_result and isinstance(voice_result, str) and voice_result.strip():
            return jsonify({"text": voice_result.strip()})
        elif voice_result is None or voice_result is False:
            return jsonify({"error": "Microphone error — check your audio device."}), 500
        else:
            return jsonify({"error": "Nothing heard — try speaking louder."}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice-status", methods=["GET"])
def api_voice_status():
    """Check if server-side voice is available."""
    return jsonify({"server_voice": bot.VOICE_AVAILABLE})


@app.route("/api/auto-email", methods=["POST"])
def api_auto_email():
    s = _get_state()
    data = request.json
    s["auto_email_enabled"] = data.get("enabled", False)
    s["auto_email_to"] = data.get("to", "").strip()
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 50)
    print("  Sales Order Assistant")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
