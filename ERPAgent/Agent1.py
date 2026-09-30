"""
ERPAgent / Agent1.py
--------------------
Flask backend that reproduces every operation of the Streamlit app
`SalesOrderChatAndVoiceBot3.py` (which itself drives `SalesOrderChatandVoiceBot2.py`)
but serves a custom Glass UI (static/index.html) instead of Streamlit.

Operations covered:
  * AI chat + intent extraction (create / get / search / order_details / email)
  * Guided sales-order creation (item -> price -> selling price -> term ->
    salesrep -> line type -> customer -> ship-to site -> confirm -> submit)
  * Retrieve a specific order by number
  * Advanced order search (year / date range / status)
  * Order details by customer
  * Add another line to an existing order
  * Manual email, auto-email on every retrieval, scheduled background reports
  * Voice input (Vosk) and voice output (pyttsx3)
"""

import os
import re
import sys
import json
import uuid
import smtplib
import datetime
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, jsonify, session, send_from_directory
from openai import OpenAI

# --------------------------------------------------
# Import the shared ERP engine (SalesOrderChatandVoiceBot2.py)
# --------------------------------------------------
_BOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "SalesOrderChatAndVoice")
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

import SalesOrderChatandVoiceBot2 as bot  # noqa: E402

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.secret_key = os.environ.get("ERPAGENT_SECRET", "erp-agent-glass-ui-secret")

# --------------------------------------------------
# SMTP configuration (override with environment variables)
# --------------------------------------------------
SMTP_HOST   = os.environ.get("ERP_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.environ.get("ERP_SMTP_PORT", "587"))
SMTP_USER   = os.environ.get("ERP_SMTP_USER", "")
SMTP_PASS   = os.environ.get("ERP_SMTP_PASS", "")
SMTP_SENDER = os.environ.get("ERP_SMTP_SENDER", SMTP_USER or "erp.assistant@yourdomain.com")

FAQ_DATA = {
    "How do I create a new sales order?": "Type a command like 'Create an order' or 'Create order for item AS54888'. I will guide you step-by-step to gather the Customer PO, Item, Quantity and Line Type.",
    "How do I look up an existing order?": "Simply type 'Get order 12345' or 'Show me order 12345'.",
    "How do I send order details via email?": "Say 'Send email to example@domain.com'. I collect the details of the last operation and format them into a table for you.",
    "Can I search for orders by date or status?": "Yes. Use natural language such as 'Show booked orders from 2024' or 'Find cancelled orders'.",
    "How do I see all orders for a specific customer?": "Type 'Order details for customer ACME'. This pulls a full table of their orders, shipments and invoice balances.",
    "Can I add more items to an existing order?": "Yes. After creating or retrieving an order, use the 'Add a Line' button to append new items to that order.",
    "How do I use voice commands?": "Click the microphone button next to the chat bar, wait for 'Listening…' then speak your command clearly.",
    "How do I cancel an operation?": "Click 'Back to Chat' on any panel, or type 'cancel'.",
}


# ==================================================
# Session state
# ==================================================
_STATES = {}
_STATE_LOCK = threading.Lock()


def _default_state():
    return {
        "messages": [],
        "gh_history": [],
        "stage": "chat",
        "action": None,
        "pending_field": None,
        "collected": {
            "cpo": None, "ordered_item": None, "quantity": None, "order_number": None,
            "inventory_item_id": None, "price_list_id": None, "price_list_name": None,
            "unit_list_price": None, "unit_selling_price": None, "payment_term_id": None,
            "payment_term_name": None, "salesrep_id": None, "salesrep_name": None,
            "sold_to_org_id": None, "ship_to_org_id": None, "customer_name": None,
            "cust_account_id": None, "line_type_id": None, "email_address": None,
        },
        "offsets": {"item": 0, "price": 0, "term": 0, "rep": 0, "site": 0,
                    "customer": 0, "customer_by_item": 0, "line_type": 0},
        "rows": {"item": [], "price": [], "term": [], "rep": [], "site": [],
                 "customer": [], "customer_by_item": [], "line_type": []},
        "pending": None,
        "api_result": None,
        "parsed_result": None,
        "search_result": None,
        "customer_orders": {"customer_name": None, "rows": []},
        "email_payload_html": "",
        "add_line": {"active": False, "step": None, "data": {}, "header_id": None,
                     "order_number": None, "rows": {"item": [], "price": [], "term": [], "line_type": []},
                     "search_text": ""},
        "auto_email": {"enabled": False, "to": "", "status": None, "error": ""},
        "schedule": {"running": False, "customer": "", "frequency": "", "to": ""},
    }


def _sid():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def get_state():
    sid = _sid()
    with _STATE_LOCK:
        if sid not in _STATES:
            _STATES[sid] = _default_state()
        return _STATES[sid]


def reset_state(keep_history=True):
    sid = _sid()
    with _STATE_LOCK:
        old = _STATES.get(sid, _default_state())
        fresh = _default_state()
        if keep_history:
            fresh["messages"] = old.get("messages", [])
            fresh["gh_history"] = old.get("gh_history", [])
            fresh["email_payload_html"] = old.get("email_payload_html", "")
            fresh["auto_email"] = old.get("auto_email", fresh["auto_email"])
            fresh["schedule"] = old.get("schedule", fresh["schedule"])
        _STATES[sid] = fresh
        return fresh


# ==================================================
# Small helpers
# ==================================================
def clean_text_for_speech(text: str) -> str:
    text = re.sub(r"[*_~`|#>-]", "", text or "")
    text = re.sub(r"[^\w\s.,?!]", "", text)
    return text.strip()


def say(state, msg, speak_text=None, mute=True):
    """Append an assistant message. TTS is driven from the browser, so mute by default."""
    state["messages"].append({"role": "assistant", "content": msg,
                              "speak": speak_text if speak_text else clean_text_for_speech(msg)})
    if not mute and bot.VOICE_AVAILABLE:
        threading.Thread(target=_safe_speak,
                         args=(speak_text or clean_text_for_speech(msg),), daemon=True).start()


def _safe_speak(text):
    try:
        bot.speak(text)
    except Exception:
        pass


def user_say(state, msg):
    state["messages"].append({"role": "user", "content": msg})


def gh_add(state, role, content):
    state["gh_history"].append({"role": role, "content": content})


def merge_fields(state, extracted: dict):
    for k, v in (extracted or {}).items():
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


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d-%b-%Y")
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _has_line_types():
    return hasattr(bot, "get_line_type_rows")


# ==================================================
# AI helpers
# ==================================================
def _openai_client():
    return OpenAI(base_url="https://models.inference.ai.azure.com", api_key=bot.GITHUB_TOKEN)


def get_smart_intent(history: list, prompt: str) -> dict:
    try:
        client = _openai_client()
        history_str = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-6:])
        system_prompt = (
            "You are an ERP intent extraction engine. Analyze the conversation history and the latest user prompt. "
            "Determine the intended action. Possible actions: 'create', 'get' (a SPECIFIC order by number), "
            "'search' (filter/list orders by year, date range or status when NO order number is given), "
            "'email', 'order_details' (all order history for a customer name), or 'unknown'. "
            "CRITICAL: use 'search' (not 'get') when a year, date range or status is mentioned without an order number. "
            "CRITICAL: if the user is answering a clarification question, infer the action from the previous assistant question. "
            "CRITICAL: convert spoken numbers into digits (e.g. 'sixty four thousand four hundred sixty' -> 64460). "
            "Extract any of: 'order_number' (int), 'customer_name', 'cpo', 'ordered_item', 'quantity', "
            "'line_type_id', 'email_address', 'year' (int), 'status', 'date_range'. "
            "Respond ONLY with a valid JSON object."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": f"History:\n{history_str}\n\nLatest prompt: {prompt}"}],
            temperature=0.0, max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?|```$", "", content).strip()
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def generate_ai_summary(operation_name: str, data) -> str:
    try:
        client = _openai_client()
        system_prompt = (
            "You are a helpful Oracle ERP Chatbot Assistant. Summarize the result of the following ERP operation "
            "in 2-3 friendly, conversational sentences. Focus on whether the operation was a SUCCESS or FAILURE. "
            "Highlight key identifiers (Order Numbers, Header IDs, Items). Do NOT output raw JSON."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": f"Operation: {operation_name}\nData: {str(_json_safe(data))[:2000]}"}],
            temperature=0.3, max_tokens=180,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Operation completed."


def general_answer(state, prompt: str) -> str:
    try:
        client = _openai_client()
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[{"role": "system", "content":
                       "You are the Centroid Sales Order Assistant for Oracle EBS. Answer briefly and helpfully. "
                       "You can create orders, retrieve orders by number, search orders, list customer order "
                       "details, add lines and email reports."}] + state["gh_history"][-6:] +
                     [{"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ("I can create a sales order, retrieve an order by number, search orders by year or status, "
                "show order details for a customer, add a line to an order, or email a report.")


# ==================================================
# ERP response parsing
# ==================================================
def extract_erp_details(result) -> dict:
    if not isinstance(result, dict):
        return {"status": "N/A", "message": str(result), "header_details": {}, "lines": []}

    data = result.get("OutputParameters", result)
    status = data.get("X_RETURN_STATUS", "N/A")
    messages_raw = data.get("X_MESSAGES", {}) or {}
    message_list = []
    if isinstance(messages_raw, dict):
        items = messages_raw.get("X_MESSAGES_ITEM", [])
        if isinstance(items, list):
            message_list = [m.get("MESSAGE_TEXT", "") for m in items if isinstance(m, dict) and m.get("MESSAGE_TEXT")]
        elif isinstance(items, dict) and items.get("MESSAGE_TEXT"):
            message_list = [items["MESSAGE_TEXT"]]
    message_text = " | ".join(message_list) if message_list else "N/A"

    header = data.get("X_HEADER_REC", {}) or {}
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}
    header_details = {
        "Order Number":   header.get("ORDER_NUMBER", "N/A"),
        "Header ID":      header.get("HEADER_ID", "N/A"),
        "Customer PO":    header.get("CUST_PO_NUMBER", "N/A"),
        "Return Status":  header.get("RETURN_STATUS", "N/A"),
        "Flow Status":    header.get("FLOW_STATUS_CODE", "N/A"),
        "Order Category": header.get("ORDER_CATEGORY_CODE", "N/A"),
        "Currency":       header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term":   header_val.get("PAYMENT_TERM", "N/A"),
        "Price List":     header_val.get("PRICE_LIST", "N/A"),
        "Order Type":     header_val.get("ORDER_TYPE", "N/A"),
        "Customer":       header_val.get("SOLD_TO_ORG", "N/A"),
        "Ship To":        header_val.get("SHIP_TO_ORG", "N/A"),
        "Bill To":        header_val.get("INVOICE_TO_ORG", "N/A"),
        "Salesrep":       header_val.get("SALESREP", "N/A"),
        "Booked Flag":    header.get("BOOKED_FLAG", "N/A"),
        "Open Flag":      header.get("OPEN_FLAG", "N/A"),
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
            "Line #":             line.get("LINE_NUMBER", "N/A"),
            "Line ID":            line.get("LINE_ID", "N/A"),
            "Item":               line.get("ORDERED_ITEM", "N/A"),
            "Item Description":   val.get("INVENTORY_ITEM", "N/A"),
            "Qty Ordered":        line.get("ORDERED_QUANTITY", "N/A"),
            "UOM":                line.get("ORDER_QUANTITY_UOM", "N/A"),
            "Unit List Price":    line.get("UNIT_LIST_PRICE", "N/A"),
            "Unit Selling Price": line.get("UNIT_SELLING_PRICE", "N/A"),
            "Line Type":          val.get("LINE_TYPE", "N/A"),
            "Payment Term":       val.get("PAYMENT_TERM", "N/A"),
            "Flow Status":        line.get("FLOW_STATUS_CODE", "N/A"),
            "Return Status":      line.get("RETURN_STATUS", "N/A"),
        })

    return {"status": status, "message": message_text,
            "header_details": _json_safe(header_details), "lines": _json_safe(lines)}


def remember_order_context(state, parsed):
    hid = parsed["header_details"].get("Header ID")
    onum = parsed["header_details"].get("Order Number")
    if hid not in (None, "N/A") and onum not in (None, "N/A"):
        state["add_line"]["header_id"] = hid
        state["add_line"]["order_number"] = onum


# ==================================================
# HTML email generators
# ==================================================
def _build_email_layout(cname, report_type, ai_summary, table_html, alerts, faqs) -> str:
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    alerts_html = "<ul style='padding-left:20px;font-size:14px;margin-bottom:0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom:5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"

    faqs_html = "<table style='border-collapse:collapse;width:100%;border:none;font-size:14px;'>"
    for q, a in faqs:
        faqs_html += (f"<tr><td style='padding:6px 8px;font-weight:bold;width:40%;'>{q}</td>"
                      f"<td style='padding:6px 8px;'>{a}</td></tr>")
    faqs_html += "</table>"

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
        <h2 style="margin:0 0 4px 0;">Oracle ERP — {report_type}</h2>
        <p style="margin:0 0 16px 0;font-size:13px;color:#555;">Customer: <b>{cname}</b> &nbsp;|&nbsp; Report date: {report_date}</p>
        <div style="background:#f6f8fb;border-left:4px solid #3b6ef6;padding:12px 16px;margin-bottom:18px;">
            <b>Summary</b><br>{ai_summary}
        </div>
        <h3 style="margin:0 0 8px 0;">Details</h3>
        {table_html}
        <h3 style="margin:22px 0 8px 0;">Alerts</h3>
        {alerts_html}
        <h3 style="margin:22px 0 8px 0;">FAQ</h3>
        {faqs_html}
        <h3 style="margin:22px 0 8px 0;">Notes</h3>
        <ul style="padding-left:20px;font-size:13px;color:#555;">
            <li>Support contact: erp.support@centroid.com</li>
            <li>This notification was generated automatically from the ERP environment.</li>
            <li>Please do not reply directly to this email.</li>
        </ul>
    </div>
    """


_TH = "border:none;padding:8px;text-align:left;font-weight:bold;background:#eef2fb;"
_TD = "border:none;padding:8px;border-bottom:1px solid #eee;"
_EMAIL_HEADERS = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]


def _table_open():
    html = "<table style='border-collapse:collapse;width:100%;font-size:14px;'><tr>"
    for h in _EMAIL_HEADERS:
        html += f"<th style='{_TH}'>{h}</th>"
    return html + "</tr>"


def generate_order_html(result, ai_summary: str) -> str:
    d = extract_erp_details(result)
    cname = d["header_details"].get("Customer", "Unknown Customer")
    order_num = d["header_details"].get("Order Number", "N/A")
    flow = str(d["header_details"].get("Flow Status", ""))

    table_html = _table_open()
    for ln in d["lines"]:
        table_html += (
            f"<tr><td style='{_TD}'>{order_num}</td>"
            f"<td style='{_TD}'>{ln.get('Item', 'N/A')}</td>"
            f"<td style='{_TD}'>{ln.get('Qty Ordered', 'N/A')}</td>"
            f"<td style='{_TD}'>{ln.get('Flow Status', 'N/A')}</td>"
            f"<td style='{_TD}'>TBD</td><td style='{_TD}'>Pending</td><td style='{_TD}'>N/A</td></tr>"
        )
    table_html += "</table>"

    alerts = {
        "Backorders": "None detected for this transaction",
        "Holds": "1" if (flow == "ENTERED" or "HOLD" in flow.upper()) else "0",
        "Partial Shipments": "N/A",
        "Payment Holds": "Check customer balance",
    }
    faqs = [
        (f"Why is Order {order_num} currently {flow or 'Processing'}?",
         f"The order is in {flow or 'Processing'} status waiting for the next step in the fulfillment cycle."),
        ("Can I expect partial shipment?", "Depends on line-level availability. Check shipping notices for updates."),
    ]
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", ai_summary, table_html, alerts, faqs)


def generate_search_html(res: dict, ai_summary: str) -> str:
    table_html = _table_open()
    for r in res.get("rows", [])[:20]:
        r = list(r)
        table_html += (
            f"<tr><td style='{_TD}'>{r[0] if len(r) > 0 else ''}</td>"
            f"<td style='{_TD}'>Multiple Lines</td><td style='{_TD}'>-</td>"
            f"<td style='{_TD}'>{r[1] if len(r) > 1 else ''}</td>"
            f"<td style='{_TD}'>{r[2] if len(r) > 2 else ''}</td>"
            f"<td style='{_TD}'>-</td><td style='{_TD}'>-</td></tr>"
        )
    table_html += "</table>"
    alerts = {"Backorders": "N/A for broad search", "Holds": "N/A for broad search",
              "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("What are these search results?",
             f"These are the top results matching your search, out of {res.get('total_count', 0)} orders.")]
    return _build_email_layout("System User", "Search Query Results", ai_summary, table_html, alerts, faqs)


def generate_customer_html(rows: list, cname: str, ai_summary: str) -> str:
    top_rows = rows[:50]
    table_html = _table_open()
    backorders = holds = delayed = 0
    for r in top_rows:
        if str(r.get("BACKORDER_FLAG", "0")) == "1":
            backorders += 1
        if r.get("ORDER_HOLD_FLAG") == "Y":
            holds += 1
        if str(r.get("DELAYED_ORDER_FLAG", "0")) == "1":
            delayed += 1
        table_html += (
            f"<tr><td style='{_TD}'>{r.get('ORDER_NUMBER', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('ITEM_NUMBER', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('ORDERED_QTY', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('LINE_STATUS', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('SCHEDULE_SHIP_DATE', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('SHIPMENT_MODE', 'Pending')}</td>"
            f"<td style='{_TD}'>${r.get('INVOICE_BALANCE', '0.00')}</td></tr>"
        )
    table_html += "</table>"

    alerts = {"Backorders": str(backorders), "Holds": str(holds),
              "Partial Shipments": "Check line statuses for details",
              "Payment Holds": "Derived from account level"}
    faqs = [
        ("Are there any delayed orders?",
         f"There are {delayed} delayed line(s)." if delayed else "All displayed orders are processing on schedule."),
        ("Can I expect a partial shipment?",
         f"Yes — {backorders} backordered item(s) may cause partial shipments." if backorders
         else "All items appear to be in stock. Partial shipments are unlikely."),
        ("Has payment cleared?",
         "Some orders indicate holds tied to pending payment or account review." if holds
         else "No payment holds are actively blocking these lines."),
    ]
    return _build_email_layout(cname, "All Recent Customer Orders", ai_summary, table_html, alerts, faqs)


# ==================================================
# Email delivery
# ==================================================
def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str):
    if not SMTP_USER or not SMTP_PASS:
        return False, ("SMTP credentials are not configured. Set ERP_SMTP_USER and ERP_SMTP_PASS "
                       "environment variables before sending email.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_SENDER
    msg["To"] = to_email

    html_content = f"""<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
        <p style="color:#333;">{(body_text or '').replace(chr(10), '<br>')}</p><br>{html_table}</body></html>"""
    msg.attach(MIMEText(body_text or "", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_SENDER, to_email, msg.as_string())
        return True, "Email sent successfully."
    except Exception as e:
        return False, str(e)


def trigger_auto_email(state, subject_context: str, html_payload: str):
    auto = state["auto_email"]
    if not auto.get("enabled"):
        return
    to_email = (auto.get("to") or "").strip() or (state["collected"].get("email_address") or "").strip()
    if not to_email:
        auto["status"] = "no_recipient"
        return
    auto["status"] = "sending"

    def _worker():
        subject = f"Automated Alert: {subject_context}"
        body = (f"Hi,\n\nPlease find the automated report for '{subject_context}' below.\n\n"
                f"Sent automatically by the Sales Order Assistant.")
        ok, msg = send_erp_email(to_email, subject, body, html_payload)
        auto["status"] = "success" if ok else "failed"
        auto["error"] = "" if ok else msg

    threading.Thread(target=_worker, daemon=True).start()


# ==================================================
# Background scheduler
# ==================================================
_SCHEDULERS = {}


def _scheduled_worker(stop_event, interval_secs, customer_name, to_email):
    while not stop_event.is_set():
        if stop_event.wait(timeout=interval_secs):
            break
        try:
            if not customer_name or customer_name.lower() in ("all", "all customers", "everyone"):
                res = bot.get_orders_advanced(None, None, None)
                summary = "Automated scheduled report summarizing all recent orders."
                html = generate_search_html({"total_count": res.get("total_count", 0),
                                             "rows": _json_safe(res.get("rows", []))}, summary)
                send_erp_email(to_email, "Scheduled Report: All Orders",
                               "Your automated report is below.", html)
            else:
                rows = _json_safe(bot.get_order_details_by_customer(customer_name))
                if rows:
                    summary = f"Automated scheduled report for {customer_name}."
                    send_erp_email(to_email, f"Scheduled Report: {customer_name}",
                                   "Your automated report is below.",
                                   generate_customer_html(rows, customer_name, summary))
        except Exception as e:
            print(f"[Scheduler error] {e}")


def _interval_minutes(interval_str: str) -> int:
    s = (interval_str or "").lower()
    nums = re.findall(r"\d+", s)
    if "min" in s:
        return int(nums[0]) if nums else 30
    if "hour" in s:
        return (int(nums[0]) if nums else 1) * 60
    return 1440


# ==================================================
# Selection helpers (paginated pickers)
# ==================================================
def _fmt_money(v):
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return str(v)


_PICKERS = {
    "item": {
        "label": "Inventory Item",
        "fetch": lambda st, off: bot.get_inventory_item_rows(st["collected"].get("ordered_item") or "", offset=off),
        "title": lambda r: r["segment1"],
        "sub":   lambda r: f"{r['description']}  ·  ID {r['inventory_item_id']}",
    },
    "price": {
        "label": "Price List",
        "fetch": lambda st, off: bot.get_price_details_rows(
            st["collected"].get("ordered_item") or "", float(st["collected"].get("quantity") or 1),
            st["collected"].get("inventory_item_id"), offset=off),
        "title": lambda r: r["price_list_name"],
        "sub":   lambda r: f"{_fmt_money(r['unit_list_price'])}  ·  ID {r['price_list_id']}",
    },
    "term": {
        "label": "Payment Term",
        "fetch": lambda st, off: bot.get_payment_term_rows(offset=off),
        "title": lambda r: r["term_name"],
        "sub":   lambda r: f"ID {r['term_id']}",
    },
    "rep": {
        "label": "Sales Representative",
        "fetch": lambda st, off: bot.get_salesrep_rows(offset=off),
        "title": lambda r: r["salesrep_name"],
        "sub":   lambda r: f"ID {r['salesrep_id']}",
    },
    "line_type": {
        "label": "Line Type",
        "fetch": lambda st, off: (bot.get_line_type_rows(offset=off) if _has_line_types() else []),
        "title": lambda r: r["line_type_name"],
        "sub":   lambda r: f"ID {r['line_type_id']}",
    },
    "customer": {
        "label": "Customer",
        "fetch": lambda st, off: bot.get_customer_by_name_rows(st["collected"].get("customer_name") or "", offset=off),
        "title": lambda r: r["customer_name"],
        "sub":   lambda r: f"Acct# {r['account_number']}  ·  ID {r['cust_account_id']}",
    },
    "customer_by_item": {
        "label": "Customer",
        "fetch": lambda st, off: bot.get_customers_by_inventory_item_rows(
            st["collected"].get("inventory_item_id"), offset=off),
        "title": lambda r: r["customer_name"],
        "sub":   lambda r: f"Acct# {r['account_number']}  ·  ID {r['cust_account_id']}",
    },
    "site": {
        "label": "Ship-To Site",
        "fetch": lambda st, off: bot.get_customer_sites_by_account(st["collected"].get("cust_account_id")),
        "title": lambda r: f"{r['customer_name']} — {r['location']}",
        "sub":   lambda r: f"{r['address']}  ·  SoldTo {r['sold_to_org_id']} / ShipTo {r['ship_to_org_id']}",
    },
}


def build_selection(state, kind, rows, searchable=False, note=None):
    meta = _PICKERS[kind]
    offset = state["offsets"].get(kind, 0)
    state["rows"][kind] = rows
    state["pending"] = {
        "type": "selection",
        "kind": kind,
        "label": meta["label"],
        "note": note,
        "searchable": searchable,
        "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
        "has_next": len(rows) >= bot.MAX_CHOICES,
        "has_prev": offset > 0,
        "offset": offset,
    }
    return state["pending"]


def build_input(state, kind, label, note=None, placeholder=""):
    state["pending"] = {"type": "input", "kind": kind, "label": label,
                        "note": note, "placeholder": placeholder}
    return state["pending"]


# ==================================================
# Order creation resolution engine
# ==================================================
def resolve(state):
    """Advance the create-order state machine until user input is required."""
    c = state["collected"]
    offs = state["offsets"]

    try:
        # Step 1 — item
        if c.get("ordered_item") and not c.get("inventory_item_id"):
            rows = bot.get_inventory_item_rows(c["ordered_item"], offset=offs["item"])
            if not rows:
                c["ordered_item"] = None
                say(state, f"No inventory items found matching `{c['ordered_item']}`. Please try another item code.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["item"] == 0:
                c["inventory_item_id"] = rows[0]["inventory_item_id"]
                c["ordered_item"] = rows[0]["segment1"]
            else:
                state["stage"] = "select_item"
                say(state, "I found multiple items. Please select one.")
                build_selection(state, "item", rows)
                return

        # Step 2 — price list
        if c.get("inventory_item_id") and c.get("quantity") and not c.get("price_list_id"):
            rows = bot.get_price_details_rows(c["ordered_item"], float(c["quantity"]),
                                              c["inventory_item_id"], offset=offs["price"])
            if not rows:
                say(state, f"No price lists found for item `{c['ordered_item']}`. Cannot proceed.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["price"] == 0:
                c["price_list_id"] = rows[0]["price_list_id"]
                c["price_list_name"] = rows[0]["price_list_name"]
                c["unit_list_price"] = rows[0]["unit_list_price"]
                state["stage"] = "selling_price"
                build_input(state, "selling_price", "Selling Price",
                            note=f"Unit list price is {_fmt_money(c['unit_list_price'])}. "
                                 f"Leave blank to use the list price.",
                            placeholder="e.g. 1250.00")
                return
            state["stage"] = "select_price"
            say(state, "Please select a price list.")
            build_selection(state, "price", rows)
            return

        # Step 3 — payment term
        if not c.get("payment_term_id"):
            rows = bot.get_payment_term_rows(offset=offs["term"])
            if not rows:
                say(state, "No payment terms found. Cannot proceed.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["term"] == 0:
                c["payment_term_id"], c["payment_term_name"] = rows[0]["term_id"], rows[0]["term_name"]
            else:
                state["stage"] = "select_term"
                say(state, "Please select a payment term.")
                build_selection(state, "term", rows)
                return

        # Step 4 — sales rep
        if not c.get("salesrep_id"):
            rows = bot.get_salesrep_rows(offset=offs["rep"])
            if not rows:
                say(state, "No sales representatives found. Cannot proceed.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["rep"] == 0:
                c["salesrep_id"], c["salesrep_name"] = rows[0]["salesrep_id"], rows[0]["salesrep_name"]
            else:
                state["stage"] = "select_rep"
                say(state, "Please select a sales representative.")
                build_selection(state, "rep", rows)
                return

        # Step 5 — line type (only when the engine exposes it)
        if _has_line_types() and not c.get("line_type_id"):
            rows = bot.get_line_type_rows(offset=offs["line_type"])
            state["stage"] = "select_line_type"
            say(state, "Please select a line type.")
            build_selection(state, "line_type", rows)
            return

        # Step 6 — customer / ship-to site
        if not c.get("sold_to_org_id") or not c.get("ship_to_org_id"):
            if c.get("cust_account_id"):
                sites = bot.get_customer_sites_by_account(c["cust_account_id"])
                if not sites:
                    c["cust_account_id"] = None
                    say(state, "No active SHIP_TO sites for this customer. Please choose a different customer.")
                    state["stage"] = "select_customer"
                    build_selection(state, "customer", [], searchable=True,
                                    note="Type a customer name and search.")
                    return
                if len(sites) == 1:
                    c["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                    c["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                    c["customer_name"] = sites[0]["customer_name"]
                else:
                    state["stage"] = "select_site"
                    say(state, "Please select a ship-to site.")
                    build_selection(state, "site", sites)
                    return
            elif c.get("customer_name"):
                rows = bot.get_customer_by_name_rows(c["customer_name"], offset=offs["customer"])
                state["stage"] = "select_customer"
                say(state, "Please select a customer.")
                build_selection(state, "customer", rows, searchable=True)
                return
            elif c.get("inventory_item_id"):
                rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"],
                                                                offset=offs["customer_by_item"])
                state["stage"] = "select_customer_by_item"
                say(state, "Please select a customer for this item.")
                build_selection(state, "customer_by_item", rows,
                                note="Customers who previously ordered this item.")
                return
            else:
                say(state, "I could not determine a customer. Please provide a customer name.")
                state["stage"] = "select_customer"
                build_selection(state, "customer", [], searchable=True,
                                note="Type a customer name and search.")
                return

        # Everything resolved
        state["stage"] = "confirm_order"
        state["pending"] = {"type": "confirm",
                            "summary": {k: v for k, v in c.items() if v is not None}}

    except Exception as e:
        say(state, f"Error during resolution: {e}")
        state["stage"] = "chat"
        state["pending"] = None


def apply_selection(state, kind, row):
    c = state["collected"]
    if kind == "item":
        c["inventory_item_id"] = row["inventory_item_id"]
        c["ordered_item"] = row["segment1"]
        say(state, f"Item selected: **{row['segment1']}** — {row['description']}")
    elif kind == "price":
        c["price_list_id"] = row["price_list_id"]
        c["price_list_name"] = row["price_list_name"]
        c["unit_list_price"] = row["unit_list_price"]
        c["unit_selling_price"] = None
        say(state, f"Price list: **{row['price_list_name']}** — {_fmt_money(row['unit_list_price'])}")
        state["stage"] = "selling_price"
        build_input(state, "selling_price", "Selling Price",
                    note=f"Unit list price is {_fmt_money(row['unit_list_price'])}. Leave blank to use it.",
                    placeholder="e.g. 1250.00")
        return False
    elif kind == "term":
        c["payment_term_id"], c["payment_term_name"] = row["term_id"], row["term_name"]
        say(state, f"Payment term: **{row['term_name']}**")
    elif kind == "rep":
        c["salesrep_id"], c["salesrep_name"] = row["salesrep_id"], row["salesrep_name"]
        say(state, f"Sales rep: **{row['salesrep_name']}**")
    elif kind == "line_type":
        c["line_type_id"] = row["line_type_id"]
        say(state, f"Line type: **{row['line_type_name']}**")
    elif kind in ("customer", "customer_by_item"):
        c["cust_account_id"] = row["cust_account_id"]
        c["customer_name"] = row["customer_name"]
        say(state, f"Customer: **{row['customer_name']}**")
    elif kind == "site":
        c["sold_to_org_id"] = row["sold_to_org_id"]
        c["ship_to_org_id"] = row["ship_to_org_id"]
        c["customer_name"] = row["customer_name"]
        say(state, f"Ship-to confirmed for **{row['customer_name']}** ({row['location']})")
    return True


def submit_order(state):
    c = state["collected"]
    payload_kwargs = {
        "p_cust_po": c["cpo"], "p_item_id": c["inventory_item_id"], "p_ordered_item": c["ordered_item"],
        "p_qty": c["quantity"], "p_price": c["unit_list_price"], "p_selling_price": c["unit_selling_price"],
        "p_payment_term_id": c["payment_term_id"], "p_price_list_id": c["price_list_id"],
        "p_salesrep_id": c["salesrep_id"], "p_ship_to_org": c["ship_to_org_id"],
        "p_sold_to_org": c["sold_to_org_id"], "p_operating_unit": bot.OPERATING_UNIT,
    }
    import inspect
    if c.get("line_type_id") and "p_line_type_id" in inspect.signature(bot.create_payload).parameters:
        payload_kwargs["p_line_type_id"] = c["line_type_id"]

    result = bot.send_order(bot.create_payload(**payload_kwargs))
    parsed = extract_erp_details(result)
    summary = generate_ai_summary("Create New Sales Order", parsed)

    state["api_result"] = _json_safe(result)
    state["parsed_result"] = parsed
    state["email_payload_html"] = generate_order_html(result, summary)
    remember_order_context(state, parsed)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, "New Order Created", state["email_payload_html"])
    state["stage"] = "order_result"
    state["pending"] = {"type": "order_result", "context": "Order Created"}


# ==================================================
# Add-line flow
# ==================================================
def add_line_prompt(state):
    al = state["add_line"]
    step = al["step"]
    if step == "item_search":
        return build_input(state, "add_line_item_search", "Search item",
                           note=f"Adding a line to order #{al['order_number']}.",
                           placeholder="Item code or prefix, e.g. AS540")
    if step == "item_select":
        meta = _PICKERS["item"]
        rows = al["rows"]["item"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_item", "label": "Inventory Item",
            "note": f"Adding a line to order #{al['order_number']}.", "searchable": True,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= bot.MAX_CHOICES,
            "has_prev": state["offsets"]["item"] > 0,
            "offset": state["offsets"]["item"],
        }
        return state["pending"]
    if step == "qty":
        return build_input(state, "add_line_qty", "Quantity",
                           note=f"Item {al['data'].get('ordered_item')}", placeholder="e.g. 10")
    if step == "price_select":
        meta = _PICKERS["price"]
        rows = al["rows"]["price"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_price", "label": "Price List",
            "note": f"Item {al['data'].get('ordered_item')} · Qty {al['data'].get('quantity')}",
            "searchable": False,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= bot.MAX_CHOICES,
            "has_prev": state["offsets"]["price"] > 0,
            "offset": state["offsets"]["price"],
        }
        return state["pending"]
    if step == "selling_price":
        return build_input(state, "add_line_selling_price", "Selling Price",
                           note=f"Unit list price is {_fmt_money(al['data'].get('unit_list_price', 0))}. "
                                f"Leave blank to use it.", placeholder="optional")
    if step == "term_select":
        meta = _PICKERS["term"]
        rows = al["rows"]["term"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_term", "label": "Payment Term", "searchable": False,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= bot.MAX_CHOICES,
            "has_prev": state["offsets"]["term"] > 0,
            "offset": state["offsets"]["term"], "note": None,
        }
        return state["pending"]
    if step == "line_type_select":
        meta = _PICKERS["line_type"]
        rows = al["rows"]["line_type"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_line_type", "label": "Line Type", "searchable": False,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= bot.MAX_CHOICES,
            "has_prev": state["offsets"]["line_type"] > 0,
            "offset": state["offsets"]["line_type"], "note": None,
        }
        return state["pending"]
    if step == "submit":
        state["pending"] = {"type": "add_line_confirm",
                            "order_number": al["order_number"],
                            "summary": {k: v for k, v in al["data"].items() if v is not None}}
        return state["pending"]
    return None


def submit_add_line(state):
    al = state["add_line"]
    d = al["data"]
    payload_kwargs = {
        "p_header_id": al["header_id"], "p_item_id": d["inventory_item_id"],
        "p_ordered_item": d["ordered_item"], "p_qty": d["quantity"],
        "p_price": d["unit_list_price"], "p_selling_price": d["unit_selling_price"],
        "p_payment_term_id": d["payment_term_id"], "p_price_list_id": d["price_list_id"],
    }
    import inspect
    if d.get("line_type_id") and "p_line_type_id" in inspect.signature(bot.create_add_line_payload).parameters:
        payload_kwargs["p_line_type_id"] = d["line_type_id"]

    result = bot.send_order(bot.create_add_line_payload(**payload_kwargs))
    parsed = extract_erp_details(result)
    summary = generate_ai_summary("Add Line to Order", parsed)

    state["api_result"] = _json_safe(result)
    state["parsed_result"] = parsed
    state["email_payload_html"] = generate_order_html(result, summary)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, f"Updated Order #{al['order_number']}", state["email_payload_html"])

    al["active"] = False
    al["step"] = None
    al["data"] = {}
    state["stage"] = "order_result"
    state["pending"] = {"type": "order_result", "context": f"Line added to order #{al['order_number']}"}


# ==================================================
# Operations reachable from chat
# ==================================================
def do_get_order(state, order_number):
    result = bot.get_order(int(order_number))
    parsed = extract_erp_details(result)
    summary = generate_ai_summary("Retrieve Specific Order", parsed)

    state["api_result"] = _json_safe(result)
    state["parsed_result"] = parsed
    state["email_payload_html"] = generate_order_html(result, summary)
    remember_order_context(state, parsed)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, f"Order #{order_number}", state["email_payload_html"])
    state["stage"] = "order_result"
    state["pending"] = {"type": "order_result", "context": f"Order #{order_number}"}


def do_search(state, date_range, year, status):
    res = bot.get_orders_advanced(date_range, year, status)
    rows = _json_safe(res.get("rows", []))
    total = res.get("total_count", 0)

    if not rows:
        say(state, "No orders found for those filters. Try broadening your search.")
        state["stage"] = "chat"
        state["pending"] = None
        return

    summary = generate_ai_summary("Advanced Order Search",
                                  {"total_found": total,
                                   "filters_used": {"year": year, "date_range": date_range, "status": status},
                                   "first_5_rows": rows[:5]})
    state["email_payload_html"] = generate_search_html({"total_count": total, "rows": rows}, summary)
    say(state, f"Found **{total}** order(s).\n\n**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, "Advanced Search", state["email_payload_html"])

    state["search_result"] = {"total_count": total,
                              "columns": ["Order Number", "Status", "Creation Date"],
                              "rows": rows}
    state["stage"] = "search_result"
    state["pending"] = {"type": "search_result",
                        "filters": {"year": year, "date_range": date_range, "status": status}}


_CUSTOMER_COLUMNS = [
    ("Customer Name", "CUSTOMER_NAME"), ("Order Number", "ORDER_NUMBER"), ("Order Date", "ORDER_DATE"),
    ("PO Number", "PO_NUMBER"), ("Order Type", "ORDER_TYPE"), ("Line #", "LINE_NUMBER"),
    ("Item Number", "ITEM_NUMBER"), ("Ordered Qty", "ORDERED_QTY"), ("UOM", "ORDERED_UOM"),
    ("Unit List Price", "UNIT_LIST_PRICE"), ("Unit Selling Price", "UNIT_SELLING_PRICE"),
    ("Line Price", "LINE_PRICE"), ("Invoice Balance", "INVOICE_BALANCE"), ("Line Status", "LINE_STATUS"),
    ("Ship Date", "SCHEDULE_SHIP_DATE"), ("Actual Ship Date", "ACTUAL_SHIP_DATE"),
    ("Shipment Mode", "SHIPMENT_MODE"), ("Released Status", "RELEASED_STATUS"),
    ("Backorder", "BACKORDER_FLAG"), ("Delayed", "DELAYED_ORDER_FLAG"),
    ("In Transit", "IN_TRANSIT_ORDER_FLAG"), ("On Hold", "ORDER_HOLD_FLAG"), ("Email", "EMAIL"),
]


def do_customer_orders(state, customer_name):
    rows = _json_safe(bot.get_order_details_by_customer(customer_name))
    state["customer_orders"] = {"customer_name": customer_name, "rows": rows}

    if not rows:
        say(state, f"No orders found for customer `{customer_name}`. "
                   f"Verify the exact name as stored in Oracle.")
        state["stage"] = "customer_orders"
        state["pending"] = {"type": "customer_orders",
                            "columns": [c[0] for c in _CUSTOMER_COLUMNS],
                            "customer_name": customer_name, "rows": []}
        return

    summary = generate_ai_summary("Retrieve Orders by Customer",
                                  {"customer": customer_name, "total_lines_found": len(rows),
                                   "sample_data": rows[:3]})
    state["email_payload_html"] = generate_customer_html(rows, customer_name, summary)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, f"Customer: {customer_name}", state["email_payload_html"])

    table_rows = [[r.get(key, "") for _, key in _CUSTOMER_COLUMNS] for r in rows]
    state["stage"] = "customer_orders"
    state["pending"] = {"type": "customer_orders",
                        "columns": [c[0] for c in _CUSTOMER_COLUMNS],
                        "customer_name": customer_name,
                        "rows": table_rows,
                        "metrics": _customer_metrics(rows)}


def _customer_metrics(rows):
    def _num(v):
        try:
            return float(v)
        except Exception:
            return 0.0
    orders = {r.get("ORDER_NUMBER") for r in rows}
    return {
        "Total Lines": len(rows),
        "Unique Orders": len(orders),
        "Total Line Value": f"${sum(_num(r.get('LINE_PRICE')) for r in rows):,.2f}",
        "Invoice Balance": f"${sum(_num(r.get('INVOICE_BALANCE')) for r in rows):,.2f}",
    }


# ==================================================
# Chat routing
# ==================================================
_STATUS_KEYWORDS = {
    "booked": "BOOKED", "entered": "ENTERED", "cancelled": "CANCELLED", "canceled": "CANCELLED",
    "shipped": "SHIPPED", "closed": "CLOSED", "pending": "ENTERED", "open": "BOOKED",
    "invoiced": "INVOICED", "delivered": "DELIVERED",
}
_DATE_PATTERNS = [
    (r"last\s+month", "last month"), (r"last\s+quarter", "last quarter"), (r"last\s+week", "last week"),
    (r"this\s+month", "this_month"), (r"this\s+quarter", "this quarter"), (r"this\s+week", "this_week"),
    (r"last\s+30\s+days", "last_30_days"), (r"last\s+90\s+days", "last 90 days"),
    (r"last\s+year", "last year"), (r"ytd|year\s+to\s+date", "year to date"),
]


def _apply_pending_field(state, prompt):
    """Assign a raw answer to the field the assistant last asked for."""
    field = state.get("pending_field")
    if not field:
        return False
    c = state["collected"]
    raw = prompt.strip()
    if field == "Customer PO Number" and not c.get("cpo"):
        c["cpo"] = raw
    elif field == "Ordered Item code" and not c.get("ordered_item"):
        c["ordered_item"] = raw.upper()
    elif field == "Ordered Quantity" and not c.get("quantity"):
        qty = bot.parse_numeric_value(raw, allow_float=True)
        if qty is None:
            say(state, "That does not look like a valid quantity. Please enter a number.")
            return True
        c["quantity"] = qty
    else:
        return False
    state["pending_field"] = None
    return False


def handle_chat(state, prompt):
    user_say(state, prompt)
    gh_add(state, "user", prompt)

    low = prompt.strip().lower()
    if low in ("exit", "quit", "stop", "cancel", "back"):
        state = reset_state()
        say(state, "Operation cancelled. Back to chat.")
        return state

    if prompt in FAQ_DATA:
        ans = FAQ_DATA[prompt]
        say(state, ans)
        gh_add(state, "assistant", ans)
        return state

    # Conversationally answer the field we last asked for
    if state.get("action") == "create" and state.get("pending_field"):
        if _apply_pending_field(state, prompt):
            return state

    smart = get_smart_intent(state["messages"], prompt)
    extracted = {}
    try:
        extracted = bot.github_extract_intent(prompt) or {}
    except Exception:
        extracted = {}
    for k, v in smart.items():
        if v is not None and str(v).strip() != "":
            extracted[k] = v

    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", prompt)
    if any(w in low for w in ("email", "mail")):
        if not extracted.get("action") or extracted.get("action") == "unknown":
            extracted["action"] = "email"
    if email_match:
        extracted["email_address"] = email_match.group(0)

    if not extracted.get("year"):
        m = re.search(r"\b(20\d{2})\b", prompt)
        if m:
            extracted["year"] = int(m.group(1))
    if not extracted.get("status"):
        for kw, val in _STATUS_KEYWORDS.items():
            if kw in low:
                extracted["status"] = val
                break
    if not extracted.get("date_range"):
        for pattern, label in _DATE_PATTERNS:
            if re.search(pattern, low):
                extracted["date_range"] = label
                break

    if "create" in low or "new order" in low:
        extracted["action"] = "create"

    od_match = re.search(r"order\s+details?\s+(?:for|by|of)?\s*(?:customer\s+)?(.+)", prompt, re.IGNORECASE)
    if od_match or ("order details" in low and "customer" in low):
        extracted["action"] = "order_details"

    has_order_number = bool(extracted.get("order_number") or state["collected"].get("order_number"))
    has_filters = bool(extracted.get("year") or extracted.get("date_range") or extracted.get("status"))
    if has_filters and not has_order_number and extracted.get("action") not in ("create", "order_details", "email"):
        extracted["action"] = "search"

    if extracted.get("action") not in ("create", "search", "order_details", "email"):
        if any(w in low for w in ("get", "find", "search", "show", "fetch", "retrieve")):
            if not extracted.get("action") or extracted.get("action") == "unknown":
                extracted["action"] = "get"

    action = extracted.get("action", "unknown")
    merge_fields(state, extracted)

    try:
        if action == "order_details":
            name = None
            if od_match:
                name = od_match.group(1).strip()
            name = name or extracted.get("customer_name")
            if not name:
                say(state, "Which customer? Please give me the exact customer name.")
                state["stage"] = "chat"
                state["pending"] = build_input(state, "customer_orders_name", "Customer Name",
                                               placeholder="e.g. ACME CORPORATION")
                return state
            say(state, f"Fetching order details for **{name}**…")
            do_customer_orders(state, name)
            return state

        if action == "email":
            state["action"] = "email"
            state["stage"] = "send_email"
            state["pending"] = {
                "type": "email",
                "to": state["collected"].get("email_address") or state["auto_email"].get("to") or "",
                "subject": "Oracle ERP Order Details Update",
                "body": "Please find the requested order details structured below.",
                "html": state.get("email_payload_html", ""),
            }
            say(state, "Preparing the email draft. Review and send when ready.")
            return state

        if action == "search":
            say(state, "Searching orders…")
            do_search(state, extracted.get("date_range"), extracted.get("year"), extracted.get("status"))
            return state

        if action == "create" or state.get("action") == "create":
            state["action"] = "create"
            missing = missing_minimum(state)
            if missing:
                nxt = missing[0]
                prompts = {
                    "Customer PO Number": "Got it, let's create an order. What is the **Customer PO Number**?",
                    "Ordered Item code": "What is the **Ordered Item code**?",
                    "Ordered Quantity": "How many do you need? Please enter the **Ordered Quantity**.",
                }
                text = prompts.get(nxt, f"Please provide the {nxt}.")
                say(state, text)
                gh_add(state, "assistant", text)
                state["pending_field"] = nxt
                state["stage"] = "chat"
                state["pending"] = None
                return state
            state["pending_field"] = None
            resolve(state)
            return state

        if action == "get" or state.get("action") == "get":
            state["action"] = "get"
            order_num = state["collected"].get("order_number")
            if order_num is None:
                q = bot.github_clarify(state["gh_history"], ["Order Number"])
                say(state, q)
                gh_add(state, "assistant", q)
                return state
            say(state, f"Retrieving order **{order_num}**…")
            do_get_order(state, order_num)
            return state

        answer = general_answer(state, prompt)
        say(state, answer)
        gh_add(state, "assistant", answer)
        return state

    except Exception as e:
        say(state, f"Operation failed: {e}")
        state["stage"] = "chat"
        state["pending"] = None
        return state


# ==================================================
# API payload
# ==================================================
def snapshot(state):
    return {
        "messages": state["messages"],
        "stage": state["stage"],
        "pending": _json_safe(state["pending"]),
        "collected": _json_safe({k: v for k, v in state["collected"].items() if v is not None}),
        "parsed_result": state["parsed_result"],
        "search_result": state["search_result"],
        "raw_result": state["api_result"],
        "email_html": state["email_payload_html"],
        "auto_email": state["auto_email"],
        "schedule": state["schedule"],
        "add_line": {"available": bool(state["add_line"]["header_id"]),
                     "order_number": state["add_line"]["order_number"],
                     "active": state["add_line"]["active"]},
        "voice_available": bool(bot.VOICE_AVAILABLE),
    }


# ==================================================
# Routes
# ==================================================
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/state", methods=["GET"])
def api_state():
    state = get_state()
    if not state["messages"]:
        say(state, "Welcome to the Centroid Sales Order Assistant. Ask me to create, retrieve, "
                   "search or email sales orders.")
    return jsonify(snapshot(state))


@app.route("/api/faq", methods=["GET"])
def api_faq():
    return jsonify({"faq": [{"question": q, "answer": a} for q, a in FAQ_DATA.items()]})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    message = (request.json or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400
    state = handle_chat(get_state(), message)
    return jsonify(snapshot(state))


@app.route("/api/reset", methods=["POST"])
def api_reset():
    state = reset_state(keep_history=False)
    say(state, "Session cleared. How can I help?")
    return jsonify(snapshot(state))


@app.route("/api/back", methods=["POST"])
def api_back():
    state = get_state()
    state["stage"] = "chat"
    state["pending"] = None
    state["pending_field"] = None
    state["action"] = None
    for k in state["offsets"]:
        state["offsets"][k] = 0
    for k in state["rows"]:
        state["rows"][k] = []
    state["collected"] = _default_state()["collected"]
    state["add_line"]["active"] = False
    state["add_line"]["step"] = None
    state["add_line"]["data"] = {}
    return jsonify(snapshot(state))


@app.route("/api/select", methods=["POST"])
def api_select():
    """Handles selection panels: select / next / prev / search."""
    data = request.json or {}
    kind = data.get("kind")
    op = data.get("op", "select")
    state = get_state()

    if kind and kind.startswith("add_line_"):
        return _add_line_select(state, kind[len("add_line_"):], op, data)

    if kind not in _PICKERS:
        return jsonify({"error": f"unknown selection kind '{kind}'"}), 400

    try:
        if op == "search":
            term = (data.get("value") or "").strip()
            state["collected"]["customer_name"] = term
            state["offsets"][kind] = 0
            rows = _PICKERS[kind]["fetch"](state, 0)
            build_selection(state, kind, rows, searchable=True)
            return jsonify(snapshot(state))

        if op in ("next", "prev"):
            step = bot.MAX_CHOICES if op == "next" else -bot.MAX_CHOICES
            state["offsets"][kind] = max(0, state["offsets"].get(kind, 0) + step)
            rows = _PICKERS[kind]["fetch"](state, state["offsets"][kind])
            build_selection(state, kind, rows, searchable=(kind == "customer"))
            return jsonify(snapshot(state))

        idx = int(data.get("index", -1))
        rows = state["rows"].get(kind) or []
        if idx < 0 or idx >= len(rows):
            return jsonify({"error": "invalid selection index"}), 400

        state["pending"] = None
        if apply_selection(state, kind, rows[idx]):
            resolve(state)
        return jsonify(snapshot(state))
    except Exception as e:
        say(state, f"Selection failed: {e}")
        return jsonify(snapshot(state))


@app.route("/api/input", methods=["POST"])
def api_input():
    """Handles free-text panels (selling price, add-line inputs, customer name)."""
    data = request.json or {}
    kind = data.get("kind")
    value = (data.get("value") or "").strip()
    state = get_state()

    try:
        if kind == "selling_price":
            c = state["collected"]
            val = bot.parse_numeric_value(value, allow_float=True) if value else None
            c["unit_selling_price"] = val if val is not None else c.get("unit_list_price")
            say(state, f"Selling price set to {_fmt_money(c['unit_selling_price'])}")
            state["pending"] = None
            resolve(state)
            return jsonify(snapshot(state))

        if kind == "customer_orders_name":
            if not value:
                return jsonify({"error": "customer name is required"}), 400
            state["pending"] = None
            say(state, f"Fetching order details for **{value}**…")
            do_customer_orders(state, value)
            return jsonify(snapshot(state))

        if kind and kind.startswith("add_line_"):
            return _add_line_input(state, kind[len("add_line_"):], value)

        return jsonify({"error": f"unknown input kind '{kind}'"}), 400
    except Exception as e:
        say(state, f"Input failed: {e}")
        state["pending"] = None
        return jsonify(snapshot(state))


@app.route("/api/submit-order", methods=["POST"])
def api_submit_order():
    state = get_state()
    try:
        submit_order(state)
    except Exception as e:
        say(state, f"Submit error: {e}")
        state["stage"] = "chat"
        state["pending"] = None
    return jsonify(snapshot(state))


@app.route("/api/get-order", methods=["POST"])
def api_get_order():
    state = get_state()
    num = (request.json or {}).get("order_number")
    val = bot.parse_numeric_value(num)
    if val is None:
        return jsonify({"error": "a numeric order number is required"}), 400
    try:
        user_say(state, f"Get order {val}")
        do_get_order(state, val)
    except Exception as e:
        say(state, f"Failed to retrieve order: {e}")
    return jsonify(snapshot(state))


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json or {}
    state = get_state()
    year = bot.parse_numeric_value(data.get("year")) if data.get("year") else None
    try:
        user_say(state, "Search orders")
        do_search(state, data.get("date_range") or None, year, (data.get("status") or None))
    except Exception as e:
        say(state, f"Search failed: {e}")
    return jsonify(snapshot(state))


@app.route("/api/customer-orders", methods=["POST"])
def api_customer_orders():
    name = ((request.json or {}).get("customer_name") or "").strip()
    state = get_state()
    if not name:
        return jsonify({"error": "customer_name is required"}), 400
    try:
        user_say(state, f"Order details for customer {name}")
        do_customer_orders(state, name)
    except Exception as e:
        say(state, f"Failed to fetch customer orders: {e}")
    return jsonify(snapshot(state))


# --------------------------------------------------
# Add-line endpoints
# --------------------------------------------------
@app.route("/api/add-line/start", methods=["POST"])
def api_add_line_start():
    state = get_state()
    al = state["add_line"]
    if not al["header_id"]:
        return jsonify({"error": "no order in context to add a line to"}), 400
    al.update({"active": True, "step": "item_search", "data": {},
               "rows": {"item": [], "price": [], "term": [], "line_type": []}, "search_text": ""})
    state["offsets"].update({"item": 0, "price": 0, "term": 0, "line_type": 0})
    state["stage"] = "add_line"
    add_line_prompt(state)
    return jsonify(snapshot(state))


@app.route("/api/add-line/cancel", methods=["POST"])
def api_add_line_cancel():
    state = get_state()
    state["add_line"].update({"active": False, "step": None, "data": {}})
    state["stage"] = "order_result" if state["parsed_result"] else "chat"
    state["pending"] = {"type": "order_result", "context": "Order"} if state["parsed_result"] else None
    return jsonify(snapshot(state))


@app.route("/api/add-line/submit", methods=["POST"])
def api_add_line_submit():
    state = get_state()
    try:
        submit_add_line(state)
    except Exception as e:
        say(state, f"Failed to add line: {e}")
        state["stage"] = "chat"
        state["pending"] = None
    return jsonify(snapshot(state))


def _add_line_select(state, kind, op, data):
    al = state["add_line"]
    try:
        if kind == "item":
            if op in ("next", "prev"):
                step = bot.MAX_CHOICES if op == "next" else -bot.MAX_CHOICES
                state["offsets"]["item"] = max(0, state["offsets"]["item"] + step)
                al["rows"]["item"] = bot.get_inventory_item_rows(al["search_text"], offset=state["offsets"]["item"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            if op == "search":
                al["search_text"] = (data.get("value") or "").strip()
                state["offsets"]["item"] = 0
                al["rows"]["item"] = bot.get_inventory_item_rows(al["search_text"], offset=0)
                al["step"] = "item_select"
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["item"][int(data.get("index"))]
            al["data"]["inventory_item_id"] = row["inventory_item_id"]
            al["data"]["ordered_item"] = row["segment1"]
            al["step"] = "qty"

        elif kind == "price":
            if op in ("next", "prev"):
                step = bot.MAX_CHOICES if op == "next" else -bot.MAX_CHOICES
                state["offsets"]["price"] = max(0, state["offsets"]["price"] + step)
                al["rows"]["price"] = bot.get_price_details_rows(
                    al["data"]["ordered_item"], float(al["data"]["quantity"]),
                    al["data"]["inventory_item_id"], offset=state["offsets"]["price"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["price"][int(data.get("index"))]
            al["data"]["price_list_id"] = row["price_list_id"]
            al["data"]["unit_list_price"] = row["unit_list_price"]
            al["data"]["unit_selling_price"] = row["unit_list_price"]
            al["step"] = "selling_price"

        elif kind == "term":
            if op in ("next", "prev"):
                step = bot.MAX_CHOICES if op == "next" else -bot.MAX_CHOICES
                state["offsets"]["term"] = max(0, state["offsets"]["term"] + step)
                al["rows"]["term"] = bot.get_payment_term_rows(offset=state["offsets"]["term"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["term"][int(data.get("index"))]
            al["data"]["payment_term_id"] = row["term_id"]
            if _has_line_types():
                state["offsets"]["line_type"] = 0
                al["rows"]["line_type"] = bot.get_line_type_rows(offset=0)
                al["step"] = "line_type_select"
            else:
                al["step"] = "submit"

        elif kind == "line_type":
            if op in ("next", "prev"):
                step = bot.MAX_CHOICES if op == "next" else -bot.MAX_CHOICES
                state["offsets"]["line_type"] = max(0, state["offsets"]["line_type"] + step)
                al["rows"]["line_type"] = bot.get_line_type_rows(offset=state["offsets"]["line_type"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["line_type"][int(data.get("index"))]
            al["data"]["line_type_id"] = row["line_type_id"]
            al["step"] = "submit"

        else:
            return jsonify({"error": f"unknown add-line selection '{kind}'"}), 400

        add_line_prompt(state)
        return jsonify(snapshot(state))
    except Exception as e:
        say(state, f"Add-line step failed: {e}")
        return jsonify(snapshot(state))


def _add_line_input(state, kind, value):
    al = state["add_line"]
    try:
        if kind == "item_search":
            al["search_text"] = value
            state["offsets"]["item"] = 0
            al["rows"]["item"] = bot.get_inventory_item_rows(value, offset=0)
            al["step"] = "item_select"

        elif kind == "qty":
            qty = bot.parse_numeric_value(value, allow_float=True)
            if qty is None:
                return jsonify({"error": "invalid quantity"}), 400
            al["data"]["quantity"] = qty
            state["offsets"]["price"] = 0
            al["rows"]["price"] = bot.get_price_details_rows(
                al["data"]["ordered_item"], qty, al["data"]["inventory_item_id"], offset=0)
            al["step"] = "price_select"

        elif kind == "selling_price":
            val = bot.parse_numeric_value(value, allow_float=True) if value else None
            al["data"]["unit_selling_price"] = val if val is not None else al["data"].get("unit_list_price")
            state["offsets"]["term"] = 0
            al["rows"]["term"] = bot.get_payment_term_rows(offset=0)
            al["step"] = "term_select"

        else:
            return jsonify({"error": f"unknown add-line input '{kind}'"}), 400

        add_line_prompt(state)
        return jsonify(snapshot(state))
    except Exception as e:
        say(state, f"Add-line step failed: {e}")
        return jsonify(snapshot(state))


# --------------------------------------------------
# Email / automation endpoints
# --------------------------------------------------
@app.route("/api/email/open", methods=["POST"])
def api_email_open():
    state = get_state()
    state["stage"] = "send_email"
    state["pending"] = {
        "type": "email",
        "to": state["collected"].get("email_address") or state["auto_email"].get("to") or "",
        "subject": "Oracle ERP Order Details Update",
        "body": "Please find the requested order details structured below.",
        "html": state.get("email_payload_html", ""),
    }
    return jsonify(snapshot(state))


@app.route("/api/email/send", methods=["POST"])
def api_email_send():
    data = request.json or {}
    state = get_state()
    to_email = (data.get("to") or "").strip()
    if not to_email:
        return jsonify({"error": "recipient email is required"}), 400
    ok, msg = send_erp_email(to_email,
                             data.get("subject") or "Oracle ERP Order Details Update",
                             data.get("body") or "",
                             state.get("email_payload_html", ""))
    state["collected"]["email_address"] = to_email
    say(state, f"Email to `{to_email}`: {msg}")
    if ok:
        state["stage"] = "chat"
        state["pending"] = None
    return jsonify({**snapshot(state), "sent": ok, "detail": msg})


@app.route("/api/auto-email", methods=["POST"])
def api_auto_email():
    data = request.json or {}
    state = get_state()
    state["auto_email"]["enabled"] = bool(data.get("enabled"))
    if "to" in data:
        state["auto_email"]["to"] = (data.get("to") or "").strip()
    state["auto_email"]["status"] = None
    state["auto_email"]["error"] = ""
    return jsonify(snapshot(state))


@app.route("/api/schedule/start", methods=["POST"])
def api_schedule_start():
    data = request.json or {}
    state = get_state()
    to_email = (data.get("to") or "").strip()
    if not to_email:
        return jsonify({"error": "recipient email is required"}), 400

    sid = _sid()
    existing = _SCHEDULERS.get(sid)
    if existing:
        existing["stop"].set()

    mins = _interval_minutes(data.get("frequency", "Daily"))
    stop_event = threading.Event()
    customer = (data.get("customer") or "").strip()
    t = threading.Thread(target=_scheduled_worker,
                         args=(stop_event, mins * 60, customer, to_email), daemon=True)
    t.start()
    _SCHEDULERS[sid] = {"stop": stop_event, "thread": t}
    state["schedule"] = {"running": True, "customer": customer,
                         "frequency": data.get("frequency", "Daily"), "to": to_email}
    say(state, f"Scheduled report started — every {mins} minute(s) to `{to_email}`.")
    return jsonify(snapshot(state))


@app.route("/api/schedule/stop", methods=["POST"])
def api_schedule_stop():
    state = get_state()
    entry = _SCHEDULERS.pop(_sid(), None)
    if entry:
        entry["stop"].set()
    state["schedule"] = {"running": False, "customer": "", "frequency": "", "to": ""}
    say(state, "Scheduled report stopped.")
    return jsonify(snapshot(state))


# --------------------------------------------------
# Voice endpoints
# --------------------------------------------------
@app.route("/api/voice/listen", methods=["POST"])
def api_voice_listen():
    if not bot.VOICE_AVAILABLE:
        return jsonify({"error": "voice packages are not installed on the server"}), 400
    duration = int((request.json or {}).get("duration") or getattr(bot, "VOICE_DURATION", 5))
    try:
        bot.stop_speaking()
        text = bot.recognize_speech(max(duration, 5))
        if text is None:
            return jsonify({"error": "microphone error"}), 500
        return jsonify({"text": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/voice/speak", methods=["POST"])
def api_voice_speak():
    text = (request.json or {}).get("text", "")
    if not text:
        return jsonify({"error": "text is required"}), 400
    if not bot.VOICE_AVAILABLE:
        return jsonify({"spoken": False})
    threading.Thread(target=_safe_speak, args=(clean_text_for_speech(text),), daemon=True).start()
    return jsonify({"spoken": True})


if __name__ == "__main__":
    print("ERPAgent Glass UI  →  http://127.0.0.1:5010")
    app.run(host="0.0.0.0", port=5010, debug=False, threaded=True)
