import os
import sys
import json
import datetime
import requests
import ssl
import urllib3
import argparse
import re
import threading
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
import oracledb
from openai import OpenAI

try:
    import pyttsx3
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    from word2number import w2n
    VOICE_AVAILABLE = True
except Exception:
    VOICE_AVAILABLE = False

# --------------------------------------------------
# 1. Initialization & Configuration
# --------------------------------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

GITHUB_TOKEN   = "REDACTED_SECRET"
GITHUB_MODEL   = "gpt-4o"

DB_USER, DB_PASSWORD = "apps", "apps"
DB_DSN      = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

BASE_URL      = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/PROCESS_ORDER/"
GET_ORDER_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
HEADERS       = {"Content-Type": "application/json", "Accept": "application/json"}

ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Vision Operations"
MAX_CHOICES    = 10

# Global Auto-Email Configuration
AUTO_EMAIL_ENABLED = False
AUTO_EMAIL_TO = ""

# --------------------------------------------------
# Voice Configuration
# --------------------------------------------------
VOSK_MODEL_PATH  = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE      = 16000
VOICE_DURATION   = 5      
INPUT_MODE       = "text"  

_tts_lock = threading.Lock() if VOICE_AVAILABLE else None
_vosk_model_cache = None

def speak(text: str):
    """Text-to-speech output."""
    print(f"\n  🔊  {text}")
    if VOICE_AVAILABLE:
        with _tts_lock:
            engine = None
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 160)
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                print(f"  [TTS error: {e}]")
            finally:
                if engine is not None:
                    try: engine.stop()
                    except Exception: pass

def stop_speaking():
    if VOICE_AVAILABLE and _tts_lock is not None:
        _tts_lock.acquire()
        _tts_lock.release()

def load_vosk_model():
    global _vosk_model_cache
    if _vosk_model_cache is not None: return _vosk_model_cache
    if not os.path.isdir(VOSK_MODEL_PATH): raise FileNotFoundError(f"Vosk model not found: {VOSK_MODEL_PATH}")
    _vosk_model_cache = Model(VOSK_MODEL_PATH)
    return _vosk_model_cache

def recognize_speech(duration: int = VOICE_DURATION) -> str:
    if not VOICE_AVAILABLE: return None
    try:
        model = load_vosk_model()
        rec   = KaldiRecognizer(model, SAMPLE_RATE)
        print(f"  🎙️  Listening for {duration} seconds...")
        audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
        if rec.AcceptWaveform(audio.tobytes()):
            result = json.loads(rec.Result())
        else:
            result = json.loads(rec.FinalResult())
        text = result.get("text", "").strip().lower()
        print(f"  📝  Recognised: '{text}'")
        return text
    except Exception as e:
        print(f"  [Speech recognition error: {e}]")
        return None

def output(text: str):
    if INPUT_MODE == "voice": speak(text)
    else: print(f"\n  {text}")

def get_input(prompt: str, duration: int = VOICE_DURATION) -> str:
    if INPUT_MODE == "voice":
        speak(prompt)
        recognized = recognize_speech(duration)
        if not recognized:
            print("\n  🤖  [Voice not understood. Activating chat input...]")
            print(f"  ⌨️   {prompt}", end=" ")
            return input().strip()
        return recognized
    else:
        print(f"\n  {prompt}", end="")
        return input().strip()

def parse_numeric_value(val, allow_float=False):
    if val is None: return None
    val = str(val).strip()
    try: return float(val) if allow_float else int(val)
    except ValueError: pass
    if VOICE_AVAILABLE:
        try: return int(w2n.word_to_num(val))
        except Exception: pass
    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try: return float(digits) if allow_float else int(digits)
        except ValueError: pass
    return None

def get_numeric_input(prompt: str, allow_float: bool = False, duration: int = VOICE_DURATION):
    while True:
        raw = get_input(prompt, duration)
        val = parse_numeric_value(raw, allow_float=allow_float)
        if val is not None: return val
        output("I didn't catch a valid number. Please try again.")

def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)

def execute_query(sql: str, params: dict) -> list:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0].upper() for col in cur.description]
        rows    = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]

class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

# --------------------------------------------------
# 2. AI Intelligence & Email Generation
# --------------------------------------------------
def get_smart_intent(history: list, prompt: str) -> dict:
    """Uses OpenAI to extract intents & parameters from the full conversational context."""
    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=GITHUB_TOKEN,
        )
        # Grab last 6 interaction turns to establish context
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
        
        system_prompt = (
            "You are an ERP intent extraction engine. Analyze the conversation history and the latest user prompt. "
            "Determine the intended action. Possible actions: "
            "'create' (create a new order), "
            "'get' (retrieve a SPECIFIC order by its order number), "
            "'search' (search/filter/list orders by year, date range, or status — use this when NO specific order number is mentioned), "
            "'email' (send email), "
            "'order_details' (get all order history for a specific customer by name), "
            "'schedule' (schedule an automated task/report to run periodically), "
            "or 'unknown'. "
            "CRITICAL: Use action='search' (NOT 'get') when the user mentions a year, date range, status, or wants to list/filter multiple orders without a specific order number. "
            "CRITICAL: Use action='get' ONLY when the user provides a specific order number. "
            "CRITICAL: If the user is answering a clarification question, infer the action directly from the assistant's previous question. "
            "Extract any of these keys if present: "
            "'order_number' (integer), 'customer_name' (string), 'cpo' (string), 'ordered_item' (string), "
            "'quantity' (number), 'line_type_id' (number), 'email_address' (string), 'year' (4-digit integer), "
            "'status' (string), 'date_range' (string), 'schedule_interval' (string - e.g., 'daily', '30 minutes', '1 hour'). "
            "Respond ONLY with a valid JSON object, no explanation."
        )
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"History:\n{history_str}\n\nLatest prompt: {prompt}"}
            ],
            temperature=0.0,
            max_tokens=150
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
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=GITHUB_TOKEN)
        data_str = str(data)[:2000]
        system_prompt = (
            "You are a helpful Oracle ERP Chatbot Assistant. Summarize the result of the following ERP operation "
            "in 2-3 friendly, conversational sentences. Focus heavily on whether the operation was a SUCCESS or FAILURE. "
            "Highlight key identifiers (like Order Numbers, Header IDs, or Items). DO NOT output raw JSON or code snippets."
        )
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Operation: {operation_name}\nData: {data_str}"}
            ],
            temperature=0.3,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Operation completed. (AI Summary generation failed)"

def extract_erp_details(result: dict) -> dict:
    data = result.get("OutputParameters", result)
    status       = data.get("X_RETURN_STATUS", "N/A")
    messages_raw = data.get("X_MESSAGES", {})
    message_list = []

    if isinstance(messages_raw, dict):
        items = messages_raw.get("X_MESSAGES_ITEM", [])
        if isinstance(items, list): message_list = [m.get("MESSAGE_TEXT", "") for m in items if m.get("MESSAGE_TEXT")]
        elif isinstance(items, dict):
            msg = items.get("MESSAGE_TEXT", "")
            if msg: message_list = [msg]
    message_text = " | ".join(message_list) if message_list else "N/A"

    header     = data.get("X_HEADER_REC",     {}) or {}
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}

    header_details = {
        "Order Number":        header.get("ORDER_NUMBER",            "N/A"),
        "Header ID":           header.get("HEADER_ID",               "N/A"),
        "Customer PO":         header.get("CUST_PO_NUMBER",          "N/A"),
        "Return Status":       header.get("RETURN_STATUS",           "N/A"),
        "Flow Status":         header.get("FLOW_STATUS_CODE",        "N/A"),
        "Order Category":      header.get("ORDER_CATEGORY_CODE",     "N/A"),
        "Currency":            header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term":        header_val.get("PAYMENT_TERM",        "N/A"),
        "Price List":          header_val.get("PRICE_LIST",          "N/A"),
        "Order Type":          header_val.get("ORDER_TYPE",          "N/A"),
        "Customer":            header_val.get("SOLD_TO_ORG",         "N/A"),
        "Ship To":             header_val.get("SHIP_TO_ORG",         "N/A"),
        "Bill To":             header_val.get("INVOICE_TO_ORG",      "N/A"),
        "Salesrep":            header_val.get("SALESREP",            "N/A"),
        "Booked Flag":         header.get("BOOKED_FLAG",             "N/A"),
        "Open Flag":           header.get("OPEN_FLAG",               "N/A"),
    }

    line_tbl     = data.get("X_LINE_TBL",     {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}

    def _get_items(tbl, *keys):
        for k in keys:
            v = tbl.get(k)
            if v is not None: return [v] if isinstance(v, dict) else list(v)
        return []

    raw_lines     = _get_items(line_tbl,     "X_LINE_TBL_ITEM",     "P_LINE_TBL_ITEM")
    raw_line_vals = _get_items(line_val_tbl, "X_LINE_VAL_TBL_ITEM", "P_LINE_VAL_TBL_ITEM")

    lines = []
    for i, line in enumerate(raw_lines):
        val = raw_line_vals[i] if i < len(raw_line_vals) else {}
        lines.append({
            "Line #":             line.get("LINE_NUMBER",          "N/A"),
            "Item":               line.get("ORDERED_ITEM",         "N/A"),
            "Qty Ordered":        line.get("ORDERED_QUANTITY",     "N/A"),
            "Flow Status":        line.get("FLOW_STATUS_CODE",     "N/A"),
        })

    return {"status": status, "message": message_text, "header_details": header_details, "lines": lines}

def _build_email_layout(cname: str, report_type: str, ai_summary: str, table_html: str, alerts: dict, faqs: list) -> str:
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    alerts_html = "<ul style='padding-left: 20px; font-size: 14px; margin-bottom: 0;'>"
    for k, v in alerts.items(): alerts_html += f"<li style='margin-bottom: 5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"
    
    faqs_html = "<table style='border-collapse: collapse; width: 100%; border: none; font-size: 14px;'><tr><th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>Question</th><th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>AI Answer</th></tr>"
    for q, a in faqs: faqs_html += f"<tr><td style='padding: 8px;'>{q}</td><td style='padding: 8px;'>{a}</td></tr>"
    faqs_html += "</table>"
    
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 800px; margin: auto; color: #000; padding: 10px;">
        <h3 style="color: #000; font-size: 16px; margin-top: 0;">Header Details</h3>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 20px;">
            <li style="margin-bottom: 5px;">Subject Target: {cname}</li>
            <li style="margin-bottom: 5px;">Date of Report: {report_date}</li>
            <li style="margin-bottom: 5px;">Statement Period: {report_type}</li>
        </ul>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        <h3 style="color: #000; font-size: 16px;">Executive Summary</h3>
        <p style="font-size: 14px;">"{ai_summary}"</p>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        <h3 style="color: #000; font-size: 16px;">Order Detail Table</h3>
        {table_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        <h3 style="color: #000; font-size: 16px;">Exceptions & Alerts</h3>
        {alerts_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        <h3 style="color: #000; font-size: 16px;">FAQ'S</h3>
        {faqs_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 30px;">
            <li style="margin-bottom: 5px;">Support contact: erp.support@centroid.com</li>
            <li style="margin-bottom: 5px;">Disclaimer: This notification was generated automatically from the ERP environment</li>
            <li style="margin-bottom: 5px;">Do-not-reply notice: Please do not reply directly to this email.</li>
        </ul>
    </div>
    """

def generate_order_html(result: dict, ai_summary: str) -> str:
    d = extract_erp_details(result)
    cname = d["header_details"].get("Customer", "Unknown Customer")
    order_num = d["header_details"].get("Order Number", "N/A")
    th_style, td_style = "border: none; padding: 8px; text-align: left; font-weight: bold;", "border: none; padding: 8px;"
    table_html = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Line Item", "Qty", "Status"]: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    has_holds = d["header_details"].get("Flow Status") == "ENTERED" or "HOLD" in str(d["header_details"].get("Flow Status", "")).upper()
    for ln in d["lines"]:
        table_html += f"<tr><td style='{td_style}'>{order_num}</td><td style='{td_style}'>{ln.get('Item')}</td><td style='{td_style}'>{ln.get('Qty Ordered')}</td><td style='{td_style}'>{ln.get('Flow Status')}</td></tr>"
    table_html += "</table>"
    alerts = {"Backorders": "None detected", "Holds": "1" if has_holds else "0", "Payment Holds": "Check customer balance"}
    faqs = [(f"Why is Order {order_num} currently {d['header_details'].get('Flow Status')}?", "It is waiting for the next fulfillment step.")]
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", ai_summary, table_html, alerts, faqs)

def generate_search_html(res: dict, ai_summary: str) -> str:
    th_style, td_style = "border: none; padding: 8px; text-align: left; font-weight: bold;", "border: none; padding: 8px;"
    table_html = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Status", "Creation Date"]: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    for r in res.get("rows", [])[:20]:
        table_html += f"<tr><td style='{td_style}'>{r[0]}</td><td style='{td_style}'>{r[1]}</td><td style='{td_style}'>{r[2]}</td></tr>"
    table_html += "</table>"
    alerts = {"Backorders": "N/A for broad search", "Holds": "N/A"}
    faqs = [("What are these search results?", f"Top results matching your query ({res.get('total_count', 0)} orders found).")]
    return _build_email_layout("Multiple Customers", "Search Query Results", ai_summary, table_html, alerts, faqs)

def generate_customer_html(rows: list, cname: str, ai_summary: str) -> str:
    top_rows = rows[:50]
    th_style, td_style = "border: none; padding: 8px; text-align: left; font-weight: bold;", "border: none; padding: 8px;"
    table_html = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Item", "Qty", "Status", "Ship Date", "Balance"]: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    backorders = holds = delayed = 0
    for r in top_rows:
        if str(r.get("BACKORDER_FLAG", "0")) == "1": backorders += 1
        if r.get("ORDER_HOLD_FLAG") == "Y": holds += 1
        if str(r.get("DELAYED_ORDER_FLAG", "0")) == "1": delayed += 1
        table_html += f"<tr><td style='{td_style}'>{r.get('ORDER_NUMBER')}</td><td style='{td_style}'>{r.get('ITEM_NUMBER')}</td><td style='{td_style}'>{r.get('ORDERED_QTY')}</td><td style='{td_style}'>{r.get('LINE_STATUS')}</td><td style='{td_style}'>{r.get('SCHEDULE_SHIP_DATE')}</td><td style='{td_style}'>${r.get('INVOICE_BALANCE', '0.00')}</td></tr>"
    table_html += "</table>"
    alerts = {"Backorders": str(backorders), "Holds": str(holds)}
    faqs = [("Are there any delayed orders?", "Yes, some delays noted." if delayed > 0 else "Processing on schedule.")]
    return _build_email_layout(cname, "Recent Customer Orders", ai_summary, table_html, alerts, faqs)

def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str) -> tuple:
    sender = "erp.assistant@yourdomain.com"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    html_content = f"<html><body><p style='color: #333;'>{body_text.replace(chr(10), '<br>')}</p><br>{html_table}</body></html>"
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

def trigger_auto_email(subject_context: str, html_payload: str):
    if not AUTO_EMAIL_ENABLED or not AUTO_EMAIL_TO: return
    def _do_send():
        subject = f"Automated ERP Update — {subject_context}"
        body = "Hi,\n\nPlease find the automated report attached below.\n\nRegards,\nSales Order Assistant"
        success, msg = send_erp_email(AUTO_EMAIL_TO, subject, body, html_payload)
        if success: print(f"\n  📧  [Auto-Email sent successfully to {AUTO_EMAIL_TO}]")
        else: print(f"\n  ⚠️  [Auto-Email failed: {msg}]")
    threading.Thread(target=_do_send, daemon=True).start()

# --------------------------------------------------
# 3. Scheduled Worker Logic
# --------------------------------------------------
def scheduled_worker(interval_mins: int, customer_name: str, to_email: str):
    print(f"\n  ⏱️  [Scheduler active: {interval_mins} mins | Target: {customer_name or 'ALL'} | Email: {to_email}]")
    while True:
        time.sleep(interval_mins * 60)
        try:
            if not customer_name or customer_name.lower() in ["all", "all customers", "everyone"]:
                res = get_orders_advanced(None, None, None)
                ai_summary = "Automated scheduled report summarizing all recent orders."
                html_payload = generate_search_html(res, ai_summary)
                send_erp_email(to_email, "Scheduled Report: All Orders", "Your automated report is attached below.", html_payload)
                print("\n  📧  [Scheduled Email sent for ALL Customers]")
            else:
                rows = get_order_details_by_customer(customer_name)
                if rows:
                    ai_summary = f"Automated scheduled report summarizing recent activity for {customer_name}."
                    html_payload = generate_customer_html(rows, customer_name, ai_summary)
                    send_erp_email(to_email, f"Scheduled Report: {customer_name}", "Your automated report is attached below.", html_payload)
                    print(f"\n  📧  [Scheduled Email sent for {customer_name}]")
        except Exception as e:
            print(f"\n  ⚠️  [Scheduler Error: {e}]")

def start_schedule_thread(interval_str: str, customer_name: str, to_email: str):
    """Parse interval string and start scheduler thread."""
    mins = 1440
    if "30" in interval_str and "min" in interval_str: mins = 30
    elif "1" in interval_str and "hour" in interval_str: mins = 60
    elif "daily" in interval_str or "day" in interval_str: mins = 1440
    else:
        nums = re.findall(r'\d+', interval_str)
        if nums and "min" in interval_str: mins = int(nums[0])
        elif nums and "hour" in interval_str: mins = int(nums[0]) * 60
    
    thread = threading.Thread(target=scheduled_worker, args=(mins, customer_name, to_email), daemon=True)
    thread.start()

# --------------------------------------------------
# 4. DB Core Functions
# --------------------------------------------------
def get_inventory_item_rows(ordered_item: str, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, ORGANIZATION_ID
                  FROM MTL_SYSTEM_ITEMS_B
                 WHERE SEGMENT1 LIKE :ordered_item AND ORGANIZATION_ID = :org_id
                 ORDER BY INVENTORY_ITEM_ID
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=f"{ordered_item.upper()}%", org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"inventory_item_id": int(r[0]), "segment1": r[1], "description": r[2] or "", "organization_id": int(r[3])} for r in rows]

def get_price_details_rows(ordered_item: str, quantity: float, inventory_item_id: int, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql_generic = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT qlh.LIST_HEADER_ID AS price_list_id,
                                qlt.NAME AS price_list_name,
                                qll.OPERAND AS unit_list_price,
                                qlh.START_DATE_ACTIVE
                  FROM QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa
                 WHERE qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
                   AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
                   AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                   AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
                   AND qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL' AND qlh.CURRENCY_CODE = 'USD'
                 ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_generic, item_id_str=str(inventory_item_id), upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"price_list_id": int(r[0]), "price_list_name": r[1] or "", "unit_list_price": float(r[2])} for r in rows]

def get_payment_term_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT TERM_ID, NAME
                FROM RA_TERMS_VL
                WHERE (START_DATE_ACTIVE IS NULL OR START_DATE_ACTIVE <= SYSDATE)
                  AND (END_DATE_ACTIVE IS NULL OR END_DATE_ACTIVE >= SYSDATE)
                ORDER BY TERM_ID
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]

def get_salesrep_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT jrs.SALESREP_ID, jrs.NAME AS salesrep_name FROM JTF_RS_SALESREPS jrs
                 WHERE jrs.ORG_ID = :org_id AND jrs.STATUS = 'A' AND jrs.END_DATE_ACTIVE IS NULL ORDER BY jrs.SALESREP_ID
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]

def get_customer_by_name_rows(customer_name: str, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT hca.CUST_ACCOUNT_ID,
                                hp.PARTY_NAME AS customer_name,
                                hca.ACCOUNT_NUMBER
                  FROM HZ_CUST_ACCOUNTS hca
                  JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
                 WHERE UPPER(hp.PARTY_NAME) LIKE :cust_name
                   AND hca.STATUS = 'A'
                 ORDER BY hp.PARTY_NAME
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, cust_name=f"%{customer_name.upper()}%", upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"cust_account_id": int(r[0]), "customer_name": r[1] or "", "account_number": r[2] or ""} for r in rows]

def get_customers_by_inventory_item_rows(inventory_item_id: int, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql_by_item = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT hca.CUST_ACCOUNT_ID,
                                hp.PARTY_NAME AS customer_name,
                                hca.ACCOUNT_NUMBER
                  FROM OE_ORDER_LINES_ALL   ool
                  JOIN OE_ORDER_HEADERS_ALL ooh ON ooh.HEADER_ID    = ool.HEADER_ID
                  JOIN HZ_CUST_ACCOUNTS     hca ON hca.CUST_ACCOUNT_ID = ooh.SOLD_TO_ORG_ID
                  JOIN HZ_PARTIES           hp  ON hp.PARTY_ID       = hca.PARTY_ID
                 WHERE ool.INVENTORY_ITEM_ID = :item_id
                   AND ool.ORG_ID            = :org_id
                   AND hca.STATUS            = 'A'
                 ORDER BY hp.PARTY_NAME
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_by_item, item_id=inventory_item_id, org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()

    if rows:
        return [{"cust_account_id": int(r[0]), "customer_name": r[1] or "", "account_number": r[2] or ""} for r in rows]

    sql_all = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT hca.CUST_ACCOUNT_ID,
                                hp.PARTY_NAME AS customer_name,
                                hca.ACCOUNT_NUMBER
                  FROM HZ_CUST_ACCOUNTS hca
                  JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
                 WHERE hca.STATUS = 'A'
                 ORDER BY hp.PARTY_NAME
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_all, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"cust_account_id": int(r[0]), "customer_name": r[1] or "", "account_number": r[2] or ""} for r in rows]

def get_customer_sites_by_account(cust_account_id: int, org_id: int = ORG_ID) -> list:
    sql = """
        SELECT hcsu.SITE_USE_ID, hcsu.LOCATION, hl.ADDRESS1, hl.CITY, hl.STATE, hl.POSTAL_CODE, hca.CUST_ACCOUNT_ID, hp.PARTY_NAME
          FROM HZ_CUST_ACCT_SITES_ALL hcas
          JOIN HZ_CUST_SITE_USES_ALL  hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
          JOIN HZ_PARTY_SITES         hps  ON hps.PARTY_SITE_ID      = hcas.PARTY_SITE_ID
          JOIN HZ_LOCATIONS           hl   ON hl.LOCATION_ID         = hps.LOCATION_ID
          JOIN HZ_CUST_ACCOUNTS       hca  ON hca.CUST_ACCOUNT_ID    = hcas.CUST_ACCOUNT_ID
          JOIN HZ_PARTIES             hp   ON hp.PARTY_ID            = hca.PARTY_ID
         WHERE hcas.CUST_ACCOUNT_ID = :cust_account_id AND hcas.ORG_ID = :org_id
           AND hcsu.SITE_USE_CODE   = 'SHIP_TO' AND hcsu.STATUS = 'A'
         ORDER BY hcsu.SITE_USE_ID
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, cust_account_id=cust_account_id, org_id=org_id)
        rows = cur.fetchall()
    return [{
            "ship_to_org_id": int(r[0]), "location": r[1] or "",
            "address": f"{r[2] or ''}, {r[3] or ''}, {r[4] or ''} {r[5] or ''}".strip(", "),
            "sold_to_org_id": int(r[6]), "customer_name": r[7] or ""
        } for r in rows]

def get_order_details_by_customer(p_customer_name: str = None) -> list:
    cust_filter = "AND HP.PARTY_NAME = :p_customer_name" if p_customer_name else ""
    sql = f"""
        SELECT HP.PARTY_ID, HP.PARTY_NAME AS CUSTOMER_NAME, OOHA.SOLD_TO_ORG_ID, OOHA.ORDER_NUMBER, 
               TO_CHAR(OOHA.ORDERED_DATE, 'DD-MON-YYYY') AS ORDER_DATE, WDD.RELEASED_STATUS, OOLA.LINE_NUMBER, 
               MSI.SEGMENT1 AS ITEM_NUMBER, OOLA.ORDERED_QUANTITY AS ORDERED_QTY, OOLA.FLOW_STATUS_CODE AS LINE_STATUS, 
               TO_CHAR(NVL(OOLA.SCHEDULE_SHIP_DATE, OOLA.REQUEST_DATE), 'DD-MON-YYYY') AS SCHEDULE_SHIP_DATE, 
               DECODE(WDD.RELEASED_STATUS, 'B', 1, 0) AS BACKORDER_FLAG, DECODE(OOLA.CANCELLED_FLAG, 'Y', 'Y', 'N') AS ORDER_HOLD_FLAG,
               (OOLA.ORDERED_QUANTITY * OOLA.UNIT_SELLING_PRICE) AS LINE_PRICE
          FROM OE_ORDER_HEADERS_ALL OOHA, OE_ORDER_LINES_ALL OOLA, MTL_SYSTEM_ITEMS_B MSI, WSH_DELIVERY_DETAILS WDD, HZ_CUST_ACCOUNTS HCAA, HZ_PARTIES HP 
         WHERE OOHA.HEADER_ID = OOLA.HEADER_ID AND MSI.INVENTORY_ITEM_ID = OOLA.INVENTORY_ITEM_ID 
           AND MSI.ORGANIZATION_ID = OOLA.SHIP_FROM_ORG_ID AND OOLA.LINE_ID = WDD.SOURCE_LINE_ID(+)
           AND WDD.SOURCE_CODE(+) = 'OE' AND HCAA.CUST_ACCOUNT_ID = OOHA.SOLD_TO_ORG_ID 
           AND HP.PARTY_ID = HCAA.PARTY_ID {cust_filter}
         ORDER BY OOHA.ORDER_NUMBER, OOLA.LINE_NUMBER
    """
    params = {"p_customer_name": p_customer_name} if p_customer_name else {}
    rows = execute_query(sql, params)
    return rows if rows else []

def get_orders_advanced(range_type=None, year=None, status=None):
    if year: date_clause = f"EXTRACT(YEAR FROM CREATION_DATE) = {year}"
    elif range_type:
        date_map = {"this_month": "TRUNC(SYSDATE, 'MM')", "this_week": "TRUNC(SYSDATE, 'IW')", "last_30_days": "SYSDATE - 30"}
        date_clause = f"CREATION_DATE >= {date_map.get(range_type, 'SYSDATE - 7')}"
    else: date_clause = "1=1"
    status_clause = f"UPPER(FLOW_STATUS_CODE) LIKE '%{status.upper()}%'" if status else "1=1"
    
    sql_main  = f"SELECT ORDER_NUMBER, FLOW_STATUS_CODE, TO_CHAR(CREATION_DATE, 'DD-MON-YYYY') FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org ORDER BY CREATION_DATE DESC"
    sql_count = f"SELECT COUNT(*) FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org"

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql_count, org=ORG_ID)
            total_count = cur.fetchone()[0]
            cur.execute(sql_main, org=ORG_ID)
            rows = cur.fetchall()
            return {"total_count": total_count, "rows": rows}
    except Exception as e:
        raise Exception(f"SQL Error: {e}")

# --------------------------------------------------
# 5. REST Payload Generation & Execution
# --------------------------------------------------
def create_payload(p_cust_po, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price, p_payment_term_id, p_price_list_id, p_salesrep_id, p_ship_to_org, p_sold_to_org, p_operating_unit):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": "204"},
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG": "N", "CUST_PO_NUMBER": p_cust_po, "ORDER_TYPE_ID": ORDER_TYPE_ID, "ORG_ID": ORG_ID,
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "SALESREP_ID": p_salesrep_id,
                    "SHIP_TO_ORG_ID": p_ship_to_org, "SOLD_TO_ORG_ID": p_sold_to_org, "TRANSACTIONAL_CURR_CODE": "USD", "OPERATION": "CREATE"
                },
                "P_LINE_TBL": {"P_LINE_TBL_ITEM": {
                    "INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty,
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                }},
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": p_operating_unit, "P_DEBUG_LEVEL": 10
            }
        }
    }

def create_add_line_payload(p_header_id, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price, p_payment_term_id, p_price_list_id):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)},
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {"HEADER_ID": p_header_id, "ORG_ID": ORG_ID, "OPERATION": "UPDATE"},
                "P_LINE_TBL": {"P_LINE_TBL_ITEM": {
                    "HEADER_ID": p_header_id, "INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty,
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                }},
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": OPERATING_UNIT, "P_DEBUG_LEVEL": 10
            }
        }
    }

def send_order(payload):
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except Exception: return response.text
    response.raise_for_status()

def get_order(order_number: int) -> dict:
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)},
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_ORDER_NUMBER": order_number
            }
        }
    }
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except Exception: return response.text
    response.raise_for_status()


# --------------------------------------------------
# Interactive Helpers & Selection
# --------------------------------------------------
def pick_from_list(items: list, label_fn, entity_name: str) -> dict | None:
    if INPUT_MODE == "voice":
        speak(f"Here are the available {entity_name} options:")
        for i, item in enumerate(items, 1): speak(f"Option {i}: {label_fn(item)}")
        speak("Say the number of your choice, or say cancel.")
        while True:
            raw = recognize_speech()
            if not raw:
                print("\n  🤖  [Voice not understood. Activating chat input...]")
                print("  ⌨️   Enter the number of your choice (0 = Cancel): ", end="")
                raw = input().strip()
            if "cancel" in raw.lower() or raw == "0": return None
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(items):
                speak(f"You selected: {label_fn(items[idx - 1])}")
                return items[idx - 1]
            speak("Sorry, I didn't catch a valid option. Please say or enter a number.")
    else:
        for i, item in enumerate(items, 1): print(f"    {i}. {label_fn(item)}")
        print("  Enter choice (0 = Cancel): ", end="")
        while True:
            raw = input().strip().upper()
            if raw == "0": return None
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(items): return items[idx - 1]
            print("  Invalid selection, try again: ", end="")

def resolve_customer(customer_name: str) -> dict | None:
    offset = 0
    selected_customer = None
    while True:
        customers = get_customer_by_name_rows(customer_name, offset=offset)
        if not customers:
            if offset == 0:
                output(f"No customers found matching '{customer_name}'.")
                return None
            else:
                output("No more customers found.")
                offset = max(0, offset - MAX_CHOICES)
                continue
        output(f"Customers matching '{customer_name}':")
        has_more = len(customers) == MAX_CHOICES

        if INPUT_MODE == "voice":
            selected_customer = pick_from_list(customers, lambda c: f"{c['customer_name']}, Account Number {c['account_number']}", "customers")
            if selected_customer is None: return None
            break
        else:
            for i, c in enumerate(customers, 1): print(f"    {i}. {c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})")
            nav_options = []
            if has_more:   nav_options.append("N = Next page")
            if offset > 0: nav_options.append("P = Previous page")
            nav_options.append("0 = Cancel")
            print(f"  Enter choice [{', '.join(nav_options)}]: ", end="")
            choice = input().strip().upper()
            if choice == "0": return None
            elif choice == "N" and has_more: offset += MAX_CHOICES; continue
            elif choice == "P" and offset > 0: offset -= MAX_CHOICES; continue
            else:
                idx = parse_numeric_value(choice)
                if idx and 1 <= idx <= len(customers):
                    selected_customer = customers[idx - 1]; break
                else: print("  Invalid selection, please try again.")

    sites = get_customer_sites_by_account(selected_customer["cust_account_id"])
    if not sites:
        output(f"No active SHIP_TO sites found for '{selected_customer['customer_name']}'.")
        return None
    if len(sites) == 1:
        site = sites[0]
        output(f"Auto-selected ship-to site: {site['location']} — {site['address']}")
        return {"sold_to_org_id": site["sold_to_org_id"], "ship_to_org_id": site["ship_to_org_id"], "customer_name": site["customer_name"]}

    output(f"'{selected_customer['customer_name']}' has {len(sites)} ship-to sites. Please select one:")
    selected_site = pick_from_list(sites, lambda s: f"{s['location']}, {s['address']}", "ship-to sites")
    if selected_site is None: return None
    return {"sold_to_org_id": selected_site["sold_to_org_id"], "ship_to_org_id": selected_site["ship_to_org_id"], "customer_name": selected_site["customer_name"]}

def resolve_customer_by_item(inventory_item_id: int, item_segment1: str) -> dict | None:
    offset = 0
    selected_customer = None
    output(f"No customer specified. Suggesting customers based on item '{item_segment1}'...")
    while True:
        customers = get_customers_by_inventory_item_rows(inventory_item_id, offset=offset)
        if not customers:
            if offset == 0:
                output(f"No customers found for item '{item_segment1}'. Please provide a customer name.")
                customer_name = get_input("Say or type the customer name to search: ", duration=6)
                if not customer_name: return None
                return resolve_customer(customer_name)
            else:
                output("No more customers.")
                offset = max(0, offset - MAX_CHOICES); continue

        output(f"Customers who have ordered '{item_segment1}':")
        has_more = len(customers) == MAX_CHOICES

        if INPUT_MODE == "voice":
            speak("Say the number of the customer, say 'search' to search by name, or say 'cancel'.")
            for i, c in enumerate(customers, 1): speak(f"Option {i}: {c['customer_name']}, Account Number {c['account_number']}")
            raw = recognize_speech()
            if not raw:
                print("\n  🤖  [Voice not understood. Activating chat input...]")
                raw = input("  ⌨️   Enter choice number, 'search', or 'cancel': ").strip()
            if "cancel" in raw.lower() or raw == "0": return None
            if "search" in raw.lower():
                customer_name = get_input("Say or enter the customer name to search:", duration=6)
                if not customer_name: return None
                return resolve_customer(customer_name)
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(customers):
                selected_customer = customers[idx - 1]; break
            speak("I didn't catch a valid choice. Let's try again.")
            continue
        else:
            for i, c in enumerate(customers, 1): print(f"    {i}. {c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})")
            nav_options = []
            if has_more:   nav_options.append("N = Next page")
            if offset > 0: nav_options.append("P = Previous page")
            nav_options.extend(["S = Search by name instead", "0 = Cancel"])
            print(f"  Enter choice [{', '.join(nav_options)}]: ", end="")
            choice = input().strip().upper()
            if choice == "0": return None
            elif choice == "S":
                print("  Enter customer name to search: ", end="")
                manual_name = input().strip()
                if not manual_name: return None
                return resolve_customer(manual_name)
            elif choice == "N" and has_more: offset += MAX_CHOICES; continue
            elif choice == "P" and offset > 0: offset -= MAX_CHOICES; continue
            else:
                idx = parse_numeric_value(choice)
                if idx and 1 <= idx <= len(customers):
                    selected_customer = customers[idx - 1]; break
                else: print("  Invalid selection, please try again.")

    sites = get_customer_sites_by_account(selected_customer["cust_account_id"])
    if not sites: return None
    if len(sites) == 1:
        site = sites[0]
        output(f"Auto-selected ship-to site: {site['location']} — {site['address']}")
        return {"sold_to_org_id": site["sold_to_org_id"], "ship_to_org_id": site["ship_to_org_id"], "customer_name": site["customer_name"]}
    output(f"'{selected_customer['customer_name']}' has {len(sites)} ship-to sites. Please select one:")
    selected_site = pick_from_list(sites, lambda s: f"{s['location']}, {s['address']}", "ship-to sites")
    if selected_site is None: return None
    return {"sold_to_org_id": selected_site["sold_to_org_id"], "ship_to_org_id": selected_site["ship_to_org_id"], "customer_name": selected_site["customer_name"]}


# --------------------------------------------------
# Execution Flows
# --------------------------------------------------
def collect_line_details() -> dict | None:
    item_input = get_input("Enter or say item name/prefix to search (or say cancel): ", duration=5)
    if not item_input or item_input.lower() in ("cancel", "0"): return None
    offset = 0; selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items: output("No items found."); return None
        output(f"Items matching '{item_input}':")
        selected_item = pick_from_list(items, lambda it: f"{it['segment1']} — {it['description']}", "items")
        if selected_item: break
        return None
    qty = get_numeric_input("Enter or say the quantity:", allow_float=True)
    offset = 0; selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices: output("No price lists found."); return None
        output(f"Price lists for '{selected_item['segment1']}':")
        selected_price = pick_from_list(prices, lambda p: f"{p['price_list_name']} — Unit Price {p['unit_list_price']:.2f}", "price lists")
        if selected_price: break
        return None
    offset = 0; selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms: output("No payment terms found."); return None
        output("Payment terms:")
        selected_term = pick_from_list(terms, lambda t: t["term_name"], "payment terms")
        if selected_term: break
        return None
    unit_price = selected_price["unit_list_price"]
    output(f"Unit list price is {unit_price:.2f}.")
    sp_raw = get_input("Say or enter the selling price, or press Enter / say same to use the list price:", duration=5)
    selling_price = parse_numeric_value(sp_raw, allow_float=True) if sp_raw else unit_price
    return {
        "inventory_item_id": selected_item["inventory_item_id"], "ordered_item": selected_item["segment1"], "quantity": qty,
        "unit_list_price": unit_price, "selling_price": selling_price, "price_list_id": selected_price["price_list_id"], "payment_term_id": selected_term["term_id"],
    }

def add_line_to_order(order_number: int, header_id: int) -> None:
    while True:
        print("\n" + "─" * 60)
        answer = get_input(f"Add a line to Order {order_number}? Say or type A to add, or anything else to finish:")
        if answer.strip().upper() != "A":
            output("Done. No lines will be added.")
            break
        line = collect_line_details()
        if line is None: output("Line entry cancelled."); continue

        payload = create_add_line_payload(
            p_header_id=header_id, p_item_id=line["inventory_item_id"], p_ordered_item=line["ordered_item"], p_qty=line["quantity"],
            p_price=line["unit_list_price"], p_selling_price=line["selling_price"], p_payment_term_id=line["payment_term_id"], p_price_list_id=line["price_list_id"],
        )
        print(f"\n  📤  Sending add-line payload:\n{json.dumps(payload, indent=2)}")
        try:
            result = send_order(payload)
            output(f"Line added successfully to Order {order_number}.")
            print(f"  Response: {json.dumps(result, indent=2)}")
            
            # Send Auto Email
            parsed_data = extract_erp_details(result)
            ai_summary = generate_ai_summary("Add Line to Existing Order", parsed_data)
            html_payload = generate_order_html(result, ai_summary)
            trigger_auto_email(f"Updated Order #{order_number}", html_payload)

        except Exception as e:
            output(f"Failed to add line: {e}")

def standalone_add_line_flow():
    order_num_str = get_input("Please say or enter the existing Order Number:")
    if not order_num_str: return
    order_number = parse_numeric_value(order_num_str)
    if not order_number: output("Invalid order number."); return

    output(f"Fetching details for order {order_number} to extract Header ID...")
    try:
        result = get_order(int(order_number))
        header_id = None
        try:
            out  = result.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {})
            hdr  = out.get("X_HEADER_REC", {})
            header_id = hdr.get("HEADER_ID") or hdr.get("header_id")
            if not header_id: header_id = result.get("HEADER_ID")
        except Exception: pass

        if not header_id:
            manual = get_input("Could not automatically extract Header ID. Please say or enter the Header ID:")
            header_id = parse_numeric_value(manual)

        if header_id: add_line_to_order(int(order_number), int(header_id))
        else: output("Cannot proceed without a Header ID.")
    except Exception as e:
        output(f"Error fetching order: {e}")

def _print_order_details_table(rows: list, customer_name: str) -> None:
    _ORDER_DETAIL_DISPLAY = [
        ("Customer Name", "CUSTOMER_NAME"), ("Order Number", "ORDER_NUMBER"), ("Item Number", "ITEM_NUMBER"),
        ("Ordered Qty", "ORDERED_QTY"), ("Line Status", "LINE_STATUS"), ("Ship Date", "SCHEDULE_SHIP_DATE"),
        ("Invoice Balance", "INVOICE_BALANCE")
    ]
    if not rows:
        output(f"No order details found for customer: '{customer_name}'")
        return
    output(f"Order details for customer: '{customer_name}'  ({len(rows)} line(s) found)")
    print()
    col_widths = {lbl: len(lbl) for lbl, _ in _ORDER_DETAIL_DISPLAY}
    for row in rows:
        for lbl, key in _ORDER_DETAIL_DISPLAY:
            val = str(row.get(key, "") or "")
            col_widths[lbl] = max(col_widths[lbl], len(val))
    header = " | ".join(lbl.ljust(col_widths[lbl]) for lbl, _ in _ORDER_DETAIL_DISPLAY)
    sep    = "-+-".join("-" * col_widths[lbl] for lbl, _ in _ORDER_DETAIL_DISPLAY)
    print(f"  {header}")
    print(f"  {sep}")
    for row in rows:
        line = " | ".join(str(row.get(key, "") or "").ljust(col_widths[lbl]) for lbl, key in _ORDER_DETAIL_DISPLAY)
        print(f"  {line}")
    print()

def order_details_by_customer_flow() -> None:
    customer_name = get_input("Please say or enter the exact customer name to look up order details:", duration=6)
    if not customer_name or customer_name.strip().lower() in ("cancel", "0", "exit"):
        output("Order details lookup cancelled.")
        return
    customer_name = customer_name.strip()
    output(f"Fetching order details for customer: '{customer_name}' ...")
    try:
        rows = get_order_details_by_customer(customer_name)
    except Exception as e:
        output(f"Error fetching order details: {e}")
        return

    if not rows:
        output(f"No orders found for customer '{customer_name}'. Please verify the exact name.")
        return

    _print_order_details_table(rows, customer_name)

    if INPUT_MODE == "voice":
        unique_orders = len({r.get("ORDER_NUMBER") for r in rows})
        speak(f"I found {len(rows)} order line{'s' if len(rows) != 1 else ''} across {unique_orders} order{'s' if unique_orders != 1 else ''} for {customer_name}.")

    summary_context = {"customer": customer_name, "total_lines_found": len(rows), "sample_data": rows[:3]}
    ai_summary = generate_ai_summary("Retrieve Orders by Customer", summary_context)
    html_payload = generate_customer_html(rows, customer_name, ai_summary)
    
    trigger_auto_email(f"Customer: {customer_name}", html_payload)


def create_order_flow(intent: dict, conversation_history: list) -> None:
    cpo = intent.get("cpo")
    if not cpo:
        cpo = get_input("Please say or enter the Customer PO Number:", duration=5)
        while not cpo:
            output("Customer PO is required.")
            cpo = get_input("Please say or enter the Customer PO Number:", duration=5)

    item_input = intent.get("ordered_item", "")
    if not item_input:
        item_input = get_input("Please say or enter the item name or prefix to search:", duration=5)
        while not item_input:
            output("Item is required.")
            item_input = get_input("Please say or enter the item name or prefix to search:", duration=5)

    offset = 0; selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            if offset == 0:
                output(f"No items found matching '{item_input}'.")
                item_input = get_input("Please try a different item name:", duration=5)
                if not item_input: output("Cancelled."); return
                continue
            else:
                output("No more items.")
                offset = max(0, offset - MAX_CHOICES); continue
        output(f"Items matching '{item_input}':")
        if INPUT_MODE == "voice":
            selected_item = pick_from_list(items, lambda it: f"{it['segment1']}, {it['description']}", "items")
            if selected_item: break
            output("Cancelled."); return
        else:
            for i, it in enumerate(items, 1): print(f"    {i}. [{it['segment1']}] {it['description']}")
            nav = []
            if len(items) == MAX_CHOICES: nav.append("N = Next page")
            if offset > 0:                nav.append("P = Previous page")
            nav.append("0 = Cancel")
            print(f"  Choice [{', '.join(nav)}]: ", end="")
            c = input().strip().upper()
            if c == "0": output("Cancelled."); return
            if c == "N" and len(items) == MAX_CHOICES: offset += MAX_CHOICES; continue
            if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(items): selected_item = items[idx - 1]; break
            print("  Invalid selection.")

    qty_hint = intent.get("quantity")
    qty = parse_numeric_value(qty_hint, allow_float=True) if qty_hint else None
    if qty is None:
        qty = get_numeric_input("Please say or enter the quantity:", allow_float=True)

    customer_name = intent.get("customer_name")
    customer_info = None
    if customer_name:
        output(f"Resolving customer '{customer_name}'...")
        while customer_info is None:
            customer_info = resolve_customer(customer_name)
            if customer_info is None:
                retry = get_input("Could not resolve customer. Try a different name? Say yes or no:", duration=4)
                if "yes" not in retry.lower(): output("Cancelled."); return
                customer_name = get_input("Say or enter the customer name to search:", duration=6)
                if not customer_name: output("Cancelled."); return
    else:
        output(f"No customer specified — looking up customers for item '{selected_item['segment1']}'...")
        while customer_info is None:
            customer_info = resolve_customer_by_item(selected_item["inventory_item_id"], selected_item["segment1"])
            if customer_info is None:
                retry = get_input("Could not resolve customer. Search by name? Say yes or no:", duration=4)
                if "yes" not in retry.lower(): output("Cancelled."); return
                fallback_name = get_input("Say or enter the customer name to search:", duration=6)
                if not fallback_name: output("Cancelled."); return
                customer_info = resolve_customer(fallback_name)

    sold_to_org_id = customer_info["sold_to_org_id"]
    ship_to_org_id = customer_info["ship_to_org_id"]
    output(f"Customer confirmed: {customer_info['customer_name']}")

    offset = 0; selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            if offset == 0: output(f"No price lists found for '{selected_item['segment1']}'. Cannot proceed."); return
            offset = max(0, offset - MAX_CHOICES); continue
        output(f"Price lists for '{selected_item['segment1']}':")
        if INPUT_MODE == "voice":
            selected_price = pick_from_list(prices, lambda p: f"{p['price_list_name']}, Unit Price {p['unit_list_price']:.2f}", "price lists")
            if selected_price: break
            return
        else:
            for i, p in enumerate(prices, 1): print(f"    {i}. {p['price_list_name']} — Unit Price: {p['unit_list_price']:.2f}")
            nav = []
            if len(prices) == MAX_CHOICES: nav.append("N = Next page")
            if offset > 0:                 nav.append("P = Previous page")
            nav.append("0 = Cancel")
            print(f"  Choice [{', '.join(nav)}]: ", end="")
            c = input().strip().upper()
            if c == "0": return
            if c == "N" and len(prices) == MAX_CHOICES: offset += MAX_CHOICES; continue
            if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(prices): selected_price = prices[idx - 1]; break
            print("  Invalid.")

    unit_price = selected_price["unit_list_price"]
    output(f"Unit list price is {unit_price:.2f}.")
    sp_raw = get_input("Say or enter the selling price, or press Enter / say same:", duration=5)
    selling_price = parse_numeric_value(sp_raw, allow_float=True) if sp_raw else unit_price

    offset = 0; selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms: output("No payment terms found." if offset == 0 else "No more."); return
        output("Payment terms:")
        if INPUT_MODE == "voice":
            selected_term = pick_from_list(terms, lambda t: t["term_name"], "payment terms")
            if selected_term: break
            return
        else:
            for i, t in enumerate(terms, 1): print(f"    {i}. {t['term_name']}")
            nav = []
            if len(terms) == MAX_CHOICES: nav.append("N = Next page")
            if offset > 0:               nav.append("P = Previous page")
            nav.append("0 = Cancel")
            print(f"  Choice [{', '.join(nav)}]: ", end="")
            c = input().strip().upper()
            if c == "0": return
            if c == "N" and len(terms) == MAX_CHOICES: offset += MAX_CHOICES; continue
            if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(terms): selected_term = terms[idx - 1]; break
            print("  Invalid.")

    offset = 0; selected_rep = None
    while True:
        reps = get_salesrep_rows(offset=offset)
        if not reps: output("No salesreps found." if offset == 0 else "No more."); return
        output("Sales representatives:")
        if INPUT_MODE == "voice":
            selected_rep = pick_from_list(reps, lambda r: r["salesrep_name"], "sales representatives")
            if selected_rep: break
            return
        else:
            for i, r in enumerate(reps, 1): print(f"    {i}. {r['salesrep_name']}")
            nav = []
            if len(reps) == MAX_CHOICES: nav.append("N = Next page")
            if offset > 0:              nav.append("P = Previous page")
            nav.append("0 = Cancel")
            print(f"  Choice [{', '.join(nav)}]: ", end="")
            c = input().strip().upper()
            if c == "0": return
            if c == "N" and len(reps) == MAX_CHOICES: offset += MAX_CHOICES; continue
            if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(reps): selected_rep = reps[idx - 1]; break
            print("  Invalid.")

    payload = create_payload(
        p_cust_po=cpo, p_item_id=selected_item["inventory_item_id"],
        p_ordered_item=selected_item["segment1"], p_qty=qty,
        p_price=unit_price, p_selling_price=selling_price,
        p_payment_term_id=selected_term["term_id"], p_price_list_id=selected_price["price_list_id"],
        p_salesrep_id=selected_rep["salesrep_id"], p_ship_to_org=ship_to_org_id, p_sold_to_org=sold_to_org_id, p_operating_unit=OPERATING_UNIT
    )

    output("Submitting your order, please wait...")
    try:
        result = send_order(payload)
        output("Order created successfully!")
        print(f"  Response: {json.dumps(result, indent=2)}")

        # Send Auto Email
        parsed_data = extract_erp_details(result)
        ai_summary = generate_ai_summary("Create New Sales Order", parsed_data)
        html_payload = generate_order_html(result, ai_summary)
        trigger_auto_email("New Sales Order", html_payload)

        order_number = None; header_id = None
        try:
            out  = result.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {})
            hdr  = out.get("X_HEADER_REC", {})
            order_number = hdr.get("ORDER_NUMBER") or hdr.get("order_number")
            header_id    = hdr.get("HEADER_ID")    or hdr.get("header_id")
            if not header_id:
                out2 = result.get("OutputParameters", {})
                hdr2 = out2.get("X_HEADER_REC", {})
                order_number = order_number or hdr2.get("ORDER_NUMBER")
                header_id    = hdr2.get("HEADER_ID")
            if not header_id:
                order_number = order_number or result.get("ORDER_NUMBER")
                header_id    = result.get("HEADER_ID")
        except Exception as parse_err: pass

        if order_number: order_number = int(str(order_number).strip())
        if header_id:    header_id    = int(str(header_id).strip())

        if not header_id:
            output("Could not auto-extract Header ID.")
            manual = get_input("Please say or enter the Header ID shown in the response (or say skip):", duration=5)
            if manual and "skip" not in manual.lower(): header_id = parse_numeric_value(manual)
        if not order_number:
            manual = get_input("Please say or enter the Order Number shown in the response (or say skip):", duration=5)
            if manual and "skip" not in manual.lower(): order_number = parse_numeric_value(manual)

        if header_id and order_number:
            add_line_to_order(int(order_number), int(header_id))

    except Exception as e:
        output(f"Order creation failed: {e}")

# --------------------------------------------------
# Scheduled Auto Email Flow
# --------------------------------------------------
def schedule_report_flow():
    output("Let's schedule an automated report.")
    cust = get_input("Enter or say the customer name (Leave blank to run for ALL customers): ", duration=6)
    freq = get_input("Enter or say the frequency (e.g., 30 minutes, 1 hour, daily): ", duration=6)
    
    print("\n  ⌨️  Please type the recipient email address: ", end="")
    email = input().strip()
    if not email:
        output("Email is required for scheduling. Cancelled.")
        return

    freq_lower = freq.lower()
    mins = 1440
    if "30" in freq_lower and "min" in freq_lower: mins = 30
    elif "1" in freq_lower and "hour" in freq_lower: mins = 60
    elif "daily" in freq_lower or "day" in freq_lower: mins = 1440
    else:
        nums = re.findall(r'\d+', freq_lower)
        if nums and "min" in freq_lower: mins = int(nums[0])
        elif nums and "hour" in freq_lower: mins = int(nums[0]) * 60

    start_schedule_thread(str(mins) + " minutes", cust.strip(), email.strip())
    
    target_name = cust if cust.strip() else "ALL Customers"
    output(f"✅ Schedule started! Emailing {target_name} reports to {email} every {mins} minutes.")

# --------------------------------------------------
# 8. Main Entry Point
# --------------------------------------------------
def main():
    global INPUT_MODE, AUTO_EMAIL_ENABLED, AUTO_EMAIL_TO

    parser = argparse.ArgumentParser(description="ERP Sales Order Assistant")
    parser.add_argument("--mode", choices=["text", "voice"], default="text", help="Input mode: 'text' (keyboard) or 'voice' (microphone). Default: text")
    args = parser.parse_args()
    INPUT_MODE = args.mode

    if INPUT_MODE == "voice" and not VOICE_AVAILABLE:
        print("ERROR: Voice packages are not installed.")
        print("Please install: pip install pyttsx3 vosk sounddevice word2number")
        sys.exit(1)

    print("=" * 60)
    print("  ERP Sales Order Assistant")
    print(f"  Mode: {'🎙️  VOICE (with Text Fallback)' if INPUT_MODE == 'voice' else '⌨️   TEXT'}")
    print("=" * 60)

    # Initial Setup for Auto Emails
    print("\n  ⌨️  Would you like to auto-send reports to an email after every operation? (yes/no): ", end="")
    auto_ans = input().strip().lower()
    if "yes" in auto_ans or "y" == auto_ans:
        AUTO_EMAIL_ENABLED = True
        print("  ⌨️  Enter recipient email address: ", end="")
        AUTO_EMAIL_TO = input().strip()
        print(f"  ✅ Auto-send is ON for {AUTO_EMAIL_TO}\n")

    if INPUT_MODE == "voice": speak("Welcome to the ERP Sales Order Assistant.")
    else: print("\n  Welcome to the ERP Sales Order Assistant.\n")

    operations = [
        {"id": 1, "name": "Create Sales Order",                           "action": "create"},
        {"id": 2, "name": "Get Specific Sales Order",                     "action": "get_specific"},
        {"id": 3, "name": "Get Sales Orders by Date, Year, or Status",    "action": "get_range"},
        {"id": 4, "name": "Add Line Details to Existing Order",           "action": "add_line"},
        {"id": 5, "name": "Order Details by Customer",                    "action": "order_details_customer"},
        {"id": 6, "name": "Schedule an Automated Report",                 "action": "schedule_report"},
        {"id": 7, "name": "Quit / Exit",                                  "action": "quit"},
    ]

    while True:
        output("Main Menu:")
        selected_op = pick_from_list(operations, lambda x: x["name"], "operations")

        if not selected_op:
            output("Exiting the assistant. Goodbye!")
            break

        action = selected_op["action"]

        if action == "quit":
            output("Exiting the assistant. Goodbye!")
            break

        elif action == "create":
            create_order_flow({}, [])

        elif action == "get_specific":
            order_num_str = get_input("Please say or enter the specific Order Number:")
            if not order_num_str: continue
            order_num = parse_numeric_value(order_num_str)
            if order_num:
                try:
                    result = get_order(int(order_num))
                    output(f"Here are the details for Order {order_num}:")
                    print(f"\n{json.dumps(result, indent=2)}")
                    
                    parsed_data = extract_erp_details(result)
                    ai_summary = generate_ai_summary("Retrieve Specific Order", parsed_data)
                    html_payload = generate_order_html(result, ai_summary)
                    trigger_auto_email(f"Order #{order_num}", html_payload)

                except Exception as e:
                    output(f"Error fetching order: {e}")

        elif action == "get_range":
            query = get_input("Say or enter the date range, year, or status (like 'this month', '2024', or 'booked'):")
            if not query: continue
            
            # Using the new smart intent
            intent = get_smart_intent([], query)
            adv_year = intent.get("year")
            adv_date_range = intent.get("date_range")
            adv_status = intent.get("status")

            # Regex fallback
            if not adv_year:
                year_match = re.search(r'\b(20\d{2})\b', query)
                if year_match: adv_year = int(year_match.group(1))
            if not adv_status:
                if "booked" in query.lower(): adv_status = "BOOKED"
                if "entered" in query.lower(): adv_status = "ENTERED"

            try:
                data = get_orders_advanced(range_type=adv_date_range, year=adv_year, status=adv_status)
                output(f"Total orders found: {data['total_count']}")
                for row in data["rows"][:20]:
                    line = f"Order {row[0]}, Status {row[1]}, Created {row[2]}"
                    print(f"    {line}")
                    if INPUT_MODE == "voice": speak(line)

                # Send auto email
                summary_context = {"total_found": data['total_count'], "first_5_rows": data["rows"][:5]}
                ai_summary = generate_ai_summary("Advanced Order Search", summary_context)
                html_payload = generate_search_html(data, ai_summary)
                trigger_auto_email("Advanced Search", html_payload)

            except Exception as e:
                output(f"Error fetching orders: {e}")

        elif action == "add_line":
            standalone_add_line_flow()

        elif action == "order_details_customer":
            order_details_by_customer_flow()
            
        elif action == "schedule_report":
            schedule_report_flow()

if __name__ == "__main__":
    main()