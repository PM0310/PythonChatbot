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

# --------------------------------------------------
# Voice & Audio Libraries (Optional but recommended)
# --------------------------------------------------
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

# Global State Variables
AUTO_EMAIL_ENABLED = False
AUTO_EMAIL_TO = ""
stop_schedule_event = threading.Event()
global_last_html_payload = ""

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
# 2. AI Intelligence & Smart Intent Engine
# --------------------------------------------------
def get_smart_intent(history: list, prompt: str, current_action: str) -> dict:
    """Uses OpenAI to extract intents & parameters specifically configured for the console bot."""
    try:
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=GITHUB_TOKEN)
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
        
        system_prompt = f"""You are an ERP intent extraction engine. 
Current ongoing action in the session: '{current_action}'. (If unknown, infer from user prompt).
Possible actions: 'create', 'get', 'search', 'email', 'order_details', 'schedule_report', 'stop_schedule', or 'unknown'.

CRITICAL RULES:
1. Convert ANY spoken word numbers into digits (e.g., "sixty four thousand" -> 64000).
2. If the user provides a specific 5 or 6 digit number (e.g., 64460), extract it as 'order_number' and set action to 'get'.
3. If the user asks for orders from "last year", output {datetime.datetime.now().year - 1} for 'year'.
4. If the user wants to cancel or stop a schedule, set action to 'stop_schedule'.

Extract keys: 'order_number', 'customer_name', 'cpo', 'ordered_item', 'quantity', 'year', 'status', 'date_range', 'email_address', 'schedule_interval'.
Respond ONLY with a valid JSON object."""

        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"History:\n{history_str}\n\nLatest prompt: {prompt}"}],
            temperature=0.0,
            max_tokens=150
        )
        content = response.choices[0].message.content.strip()
        if "```" in content:
            content = content.split("```")[1].replace("json", "").strip()
        return json.loads(content)
    except Exception:  
        return {}

def generate_ai_summary(operation_name: str, data: dict) -> str:
    try:
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=GITHUB_TOKEN)
        data_str = str(data)[:2000]
        system_prompt = (
            "You are a helpful Oracle ERP Chatbot Assistant. Summarize the result of the following ERP operation "
            "in 2-3 friendly, conversational sentences. Focus heavily on whether the operation was a SUCCESS or FAILURE. "
            "Highlight key identifiers. DO NOT output raw JSON."
        )
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"Operation: {operation_name}\nData: {data_str}"}],
            temperature=0.3, max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Operation completed. (AI Summary generation failed)"

def github_clarify(conversation_history: list, missing_fields: list) -> str:
    system = f"You are a helpful ERP assistant. Ask the user conversationally to provide: {', '.join(missing_fields)}."
    try:
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=GITHUB_TOKEN)
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[{"role": "system", "content": system}] + conversation_history[-4:],
            temperature=0.3, max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return f"Please provide: {', '.join(missing_fields)}."

# --------------------------------------------------
# HTML Generators for Email
# --------------------------------------------------
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
        </ul>
    </div>
    """

def extract_erp_details(result: dict) -> dict:
    data = result.get("OutputParameters", result)
    status = data.get("X_RETURN_STATUS", "N/A")
    header = data.get("X_HEADER_REC", {}) or {}
    
    header_details = {
        "Order Number": header.get("ORDER_NUMBER", "N/A"),
        "Flow Status": header.get("FLOW_STATUS_CODE", "N/A")
    }
    raw_lines = data.get("X_LINE_TBL", {}).get("X_LINE_TBL_ITEM", [])
    if isinstance(raw_lines, dict): raw_lines = [raw_lines]
    
    lines = []
    for line in raw_lines:
        lines.append({
            "Line #": line.get("LINE_NUMBER", "N/A"),
            "Item": line.get("ORDERED_ITEM", "N/A"),
            "Qty Ordered": line.get("ORDERED_QUANTITY", "N/A"),
            "Flow Status": line.get("FLOW_STATUS_CODE", "N/A")
        })
    return {"status": status, "header_details": header_details, "lines": lines}

def generate_order_html(result: dict, ai_summary: str) -> str:
    d = extract_erp_details(result)
    order_num = d["header_details"].get("Order Number", "N/A")
    table_html = "<table style='width: 100%; text-align: left; border-collapse: collapse;'><tr><th style='padding:8px; border-bottom:1px solid #ccc;'>Order #</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Item</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Qty</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Status</th></tr>"
    for ln in d["lines"]:
        table_html += f"<tr><td style='padding:8px;'>{order_num}</td><td style='padding:8px;'>{ln.get('Item')}</td><td style='padding:8px;'>{ln.get('Qty Ordered')}</td><td style='padding:8px;'>{ln.get('Flow Status')}</td></tr>"
    table_html += "</table>"
    return _build_email_layout("N/A", f"Order #{order_num}", ai_summary, table_html, {"Holds": "0"}, [])

def generate_search_html(res: dict, ai_summary: str) -> str:
    table_html = "<table style='width: 100%; text-align: left; border-collapse: collapse;'><tr><th style='padding:8px; border-bottom:1px solid #ccc;'>Order #</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Status</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Date</th></tr>"
    for r in res.get("rows", [])[:20]:
        table_html += f"<tr><td style='padding:8px;'>{r[0]}</td><td style='padding:8px;'>{r[1]}</td><td style='padding:8px;'>{r[2]}</td></tr>"
    table_html += "</table>"
    return _build_email_layout("Multiple", "Search Results", ai_summary, table_html, {"Note": "Showing top 20"}, [])

def generate_customer_html(rows: list, cname: str, ai_summary: str) -> str:
    table_html = "<table style='width: 100%; text-align: left; border-collapse: collapse;'><tr><th style='padding:8px; border-bottom:1px solid #ccc;'>Order #</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Item</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Qty</th><th style='padding:8px; border-bottom:1px solid #ccc;'>Status</th></tr>"
    for r in rows[:50]:
        table_html += f"<tr><td style='padding:8px;'>{r.get('ORDER_NUMBER')}</td><td style='padding:8px;'>{r.get('ITEM_NUMBER')}</td><td style='padding:8px;'>{r.get('ORDERED_QTY')}</td><td style='padding:8px;'>{r.get('LINE_STATUS')}</td></tr>"
    table_html += "</table>"
    return _build_email_layout(cname, "Recent Orders", ai_summary, table_html, {"Note": "Showing top 50"}, [])

def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str) -> tuple:
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, "erp.assistant@yourdomain.com", to_email
    html_content = f"<html><body><p>{body_text.replace(chr(10), '<br>')}</p><br>{html_table}</body></html>"
    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(html_content, "html"))
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login("pavanmaccha042@gmail.com", "ltvxbwhkzkrptueg")
        server.sendmail(msg["From"], to_email, msg.as_string())
        server.quit()
        return True, "Success"
    except Exception as e: return False, str(e)

def trigger_auto_email(subject_context: str, html_payload: str):
    if not AUTO_EMAIL_ENABLED or not AUTO_EMAIL_TO: return
    def _do_send():
        send_erp_email(AUTO_EMAIL_TO, f"Automated ERP Update — {subject_context}", "Please find the automated report attached.", html_payload)
        print(f"\n  📧  [Auto-Email sent to {AUTO_EMAIL_TO}]")
    threading.Thread(target=_do_send, daemon=True).start()

# --------------------------------------------------
# 3. Scheduled Worker Logic (With Stop Support)
# --------------------------------------------------
def scheduled_worker(interval_secs: int, customer_name: str, to_email: str):
    print(f"\n  ⏱️  [Scheduler active: {interval_secs/60} mins | Target: {customer_name or 'ALL'} | Email: {to_email}]")
    stop_schedule_event.clear()
    
    while not stop_schedule_event.is_set():
        stopped_early = stop_schedule_event.wait(timeout=interval_secs)
        if stopped_early:
            print("\n  🛑  [Scheduler has been explicitly stopped by user]")
            break
            
        try:
            if not customer_name or customer_name.lower() in ["all", "everyone"]:
                res = get_orders_advanced(None, None, None)
                summ_ctx = {"total_found": res.get("total_count", 0), "first_5_rows": res.get("rows", [])[:5]}
                ai_summary = generate_ai_summary("Advanced Order Search", summ_ctx)
                html_payload = generate_search_html(res, ai_summary)
                send_erp_email(to_email, "Scheduled Report: All Orders", "Report attached.", html_payload)
            else:
                rows = get_order_details_by_customer(customer_name)
                if rows:
                    summ_ctx = {"customer": customer_name, "count": len(rows), "samples": rows[:3]}
                    ai_summary = generate_ai_summary("Retrieve Orders by Customer", summ_ctx)
                    html_payload = generate_customer_html(rows, customer_name, ai_summary)
                    send_erp_email(to_email, f"Scheduled Report: {customer_name}", "Report attached.", html_payload)
            print("\n  📧  [Scheduled Email dispatched]")
        except Exception as e:
            print(f"\n  ⚠️  [Scheduler Error: {e}]")

def start_schedule_thread(interval_str: str, cust_name: str, to_email: str):
    mins = 1440 # Default daily
    interval_lower = interval_str.lower()
    
    if "30" in interval_lower and "min" in interval_lower: mins = 30
    elif "1" in interval_lower and "hour" in interval_lower: mins = 60
    elif "daily" in interval_lower or "day" in interval_lower: mins = 1440
    else:
        nums = re.findall(r'\d+', interval_lower)
        if nums and "min" in interval_lower: mins = int(nums[0])
        elif nums and "hour" in interval_lower: mins = int(nums[0]) * 60
            
    secs = mins * 60
    t = threading.Thread(target=scheduled_worker, args=(secs, cust_name, to_email), daemon=True)
    t.start()

# --------------------------------------------------
# 4. DB Core Functions
# --------------------------------------------------
def get_inventory_item_rows(ordered_item: str, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = "SELECT * FROM (SELECT a.*, ROWNUM rnum FROM (SELECT DISTINCT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, ORGANIZATION_ID FROM MTL_SYSTEM_ITEMS_B WHERE SEGMENT1 LIKE :ordered_item AND ORGANIZATION_ID = :org_id ORDER BY INVENTORY_ITEM_ID) a WHERE ROWNUM <= :upper_bound) WHERE rnum > :offset"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=f"{ordered_item.upper()}%", org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        return [{"inventory_item_id": int(r[0]), "segment1": r[1], "description": r[2] or ""} for r in cur.fetchall()]

def get_price_details_rows(ordered_item: str, quantity: float, inventory_item_id: int, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = "SELECT * FROM (SELECT a.*, ROWNUM rnum FROM (SELECT DISTINCT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND FROM QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa WHERE qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG') AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1' AND qpa.PRODUCT_ATTR_VALUE = :item AND qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL' AND qlh.CURRENCY_CODE = 'USD' ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST) a WHERE ROWNUM <= :upper_bound) WHERE rnum > :offset"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, item=str(inventory_item_id), upper_bound=offset + MAX_CHOICES, offset=offset)
        return [{"price_list_id": int(r[0]), "price_list_name": r[1] or "", "unit_list_price": float(r[2])} for r in cur.fetchall()]

def get_payment_term_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = "SELECT * FROM (SELECT a.*, ROWNUM rnum FROM (SELECT DISTINCT TERM_ID, NAME FROM RA_TERMS_VL WHERE (START_DATE_ACTIVE IS NULL OR START_DATE_ACTIVE <= SYSDATE) AND (END_DATE_ACTIVE IS NULL OR END_DATE_ACTIVE >= SYSDATE) ORDER BY TERM_ID) a WHERE ROWNUM <= :upper_bound) WHERE rnum > :offset"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, upper_bound=offset + MAX_CHOICES, offset=offset)
        return [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in cur.fetchall()]

def get_salesrep_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = "SELECT * FROM (SELECT a.*, ROWNUM rnum FROM (SELECT DISTINCT jrs.SALESREP_ID, jrs.NAME FROM JTF_RS_SALESREPS jrs WHERE jrs.ORG_ID = :org_id AND jrs.STATUS = 'A' AND jrs.END_DATE_ACTIVE IS NULL ORDER BY jrs.SALESREP_ID) a WHERE ROWNUM <= :upper_bound) WHERE rnum > :offset"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        return [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in cur.fetchall()]

def get_customer_by_name_rows(customer_name: str, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = "SELECT * FROM (SELECT a.*, ROWNUM rnum FROM (SELECT DISTINCT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME, hca.ACCOUNT_NUMBER FROM HZ_CUST_ACCOUNTS hca JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID WHERE UPPER(hp.PARTY_NAME) LIKE :cust_name AND hca.STATUS = 'A' ORDER BY hp.PARTY_NAME) a WHERE ROWNUM <= :upper_bound) WHERE rnum > :offset"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, cust_name=f"%{customer_name.upper()}%", upper_bound=offset + MAX_CHOICES, offset=offset)
        return [{"cust_account_id": int(r[0]), "customer_name": r[1] or "", "account_number": r[2] or ""} for r in cur.fetchall()]

def get_customer_sites_by_account(cust_account_id: int, org_id: int = ORG_ID) -> list:
    sql = "SELECT hcsu.SITE_USE_ID, hcsu.LOCATION, hl.ADDRESS1, hl.CITY, hl.STATE, hl.POSTAL_CODE, hca.CUST_ACCOUNT_ID, hp.PARTY_NAME FROM HZ_CUST_ACCT_SITES_ALL hcas JOIN HZ_CUST_SITE_USES_ALL hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID JOIN HZ_PARTY_SITES hps ON hps.PARTY_SITE_ID = hcas.PARTY_SITE_ID JOIN HZ_LOCATIONS hl ON hl.LOCATION_ID = hps.LOCATION_ID JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = hcas.CUST_ACCOUNT_ID JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID WHERE hcas.CUST_ACCOUNT_ID = :cust_account_id AND hcas.ORG_ID = :org_id AND hcsu.SITE_USE_CODE = 'SHIP_TO' AND hcsu.STATUS = 'A' ORDER BY hcsu.SITE_USE_ID"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, cust_account_id=cust_account_id, org_id=org_id)
        return [{"ship_to_org_id": int(r[0]), "location": r[1] or "", "address": f"{r[2] or ''} {r[3] or ''}".strip(), "sold_to_org_id": int(r[6]), "customer_name": r[7] or ""} for r in cur.fetchall()]

def get_order_details_by_customer(p_customer_name: str = None) -> list:
    cust_filter = "AND UPPER(HP.PARTY_NAME) = nvl(UPPER(:p_customer_name),UPPER(HP.PARTY_NAME))" if p_customer_name else ""
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
           AND OOHA.ORDERED_DATE >= ADD_MONTHS(SYSDATE, -6)
         ORDER BY OOHA.ORDER_NUMBER, OOLA.LINE_NUMBER
    """
    params = {"p_customer_name": p_customer_name} if p_customer_name else {}
    return execute_query(sql, params)

def get_orders_advanced(range_type=None, year=None, status=None):
    date_clause = f"EXTRACT(YEAR FROM CREATION_DATE) = {year}" if year else "1=1"
    status_clause = f"UPPER(FLOW_STATUS_CODE) LIKE '%{status.upper()}%'" if status else "1=1"
    sql_main  = f"SELECT ORDER_NUMBER, FLOW_STATUS_CODE, TO_CHAR(CREATION_DATE, 'DD-MON-YYYY') FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org ORDER BY CREATION_DATE DESC"
    sql_count = f"SELECT COUNT(*) FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_count, org=ORG_ID); total_count = cur.fetchone()[0]
        cur.execute(sql_main, org=ORG_ID); rows = cur.fetchall()
        return {"total_count": total_count, "rows": rows}

# --------------------------------------------------
# 5. REST Execution
# --------------------------------------------------
def create_payload(p_cust_po, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price, p_payment_term_id, p_price_list_id, p_salesrep_id, p_ship_to_org, p_sold_to_org, p_operating_unit):
    return {"PROCESS_ORDER_Input": {"RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": "204"}, "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T", "P_HEADER_REC": {"BOOKED_FLAG": "N", "CUST_PO_NUMBER": p_cust_po, "ORDER_TYPE_ID": ORDER_TYPE_ID, "ORG_ID": ORG_ID, "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "SALESREP_ID": p_salesrep_id, "SHIP_TO_ORG_ID": p_ship_to_org, "SOLD_TO_ORG_ID": p_sold_to_org, "TRANSACTIONAL_CURR_CODE": "USD", "OPERATION": "CREATE"}, "P_LINE_TBL": {"P_LINE_TBL_ITEM": {"INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty, "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"}}, "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": p_operating_unit, "P_DEBUG_LEVEL": 10}}}

def create_add_line_payload(p_header_id, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price, p_payment_term_id, p_price_list_id):
    return {"PROCESS_ORDER_Input": {"RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)}, "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T", "P_HEADER_REC": {"HEADER_ID": p_header_id, "ORG_ID": ORG_ID, "OPERATION": "UPDATE"}, "P_LINE_TBL": {"P_LINE_TBL_ITEM": {"HEADER_ID": p_header_id, "INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty, "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"}}, "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": OPERATING_UNIT, "P_DEBUG_LEVEL": 10}}}

def send_order(payload):
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except: return response.text
    response.raise_for_status()

def get_order(order_number: int) -> dict:
    payload = {"PROCESS_ORDER_Input": {"RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)}, "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T", "P_ORDER_NUMBER": order_number}}}
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except: return response.text
    response.raise_for_status()


# --------------------------------------------------
# Interactive Flows
# --------------------------------------------------
def pick_from_list(items: list, label_fn, entity_name: str) -> dict | None:
    if INPUT_MODE == "voice":
        speak(f"Here are the options for {entity_name}:")
        for i, item in enumerate(items, 1): speak(f"Option {i}: {label_fn(item)}")
        speak("Say the number of your choice, or say cancel.")
        while True:
            raw = recognize_speech()
            if not raw:
                print("\n  🤖  [Voice not understood. Activating chat input...]")
                raw = input("  ⌨️   Enter choice (0 to Cancel): ").strip()
            if "cancel" in raw.lower() or raw == "0": return None
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(items):
                speak(f"You selected: {label_fn(items[idx - 1])}")
                return items[idx - 1]
            speak("Invalid choice. Try again.")
    else:
        for i, item in enumerate(items, 1): print(f"    {i}. {label_fn(item)}")
        while True:
            raw = input("  Enter choice (0 to Cancel): ").strip().upper()
            if raw == "0": return None
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(items): return items[idx - 1]
            print("  Invalid selection, try again.")

def _print_parsed_order_console(parsed_data):
    """Cleanly prints parsed Oracle Order Data to the terminal"""
    print("\n" + "="*50)
    print(" 🧾 ORDER DETAILS")
    print("="*50)
    hd = parsed_data.get("header_details", {})
    for k, v in hd.items():
        if v and v != "N/A":
            print(f"  • {k}: {v}")
            
    print("-" * 50)
    lines = parsed_data.get("lines", [])
    if not lines:
        print("  No line items found.")
    else:
        for i, ln in enumerate(lines, 1):
            item = ln.get("Item", "N/A")
            qty = ln.get("Qty Ordered", "N/A")
            stat = ln.get("Flow Status", "N/A")
            print(f"  📦 Line {i} -> Item: {item} | Qty: {qty} | Status: {stat}")
    print("="*50 + "\n")

def create_order_flow(intent: dict) -> None:
    global global_last_html_payload
    cpo = intent.get("cpo")
    if not cpo:
        cpo = get_input("Please say or enter the Customer PO Number:", duration=5)
        while not cpo: cpo = get_input("Customer PO is required:")

    item_input = intent.get("ordered_item", "")
    if not item_input:
        item_input = get_input("Please say or enter the item name or prefix to search:", duration=5)

    items = get_inventory_item_rows(item_input)
    if not items:
        output(f"No items found matching '{item_input}'. Cancelled.")
        return
        
    output(f"Items matching '{item_input}':")
    selected_item = pick_from_list(items, lambda it: f"{it['segment1']}, {it['description']}", "items")
    if not selected_item: return

    qty = parse_numeric_value(intent.get("quantity"), allow_float=True)
    if not qty: qty = get_numeric_input("Please say or enter the quantity:", allow_float=True)

    customer_name = intent.get("customer_name")
    if not customer_name: customer_name = get_input("Say or enter the customer name to search:", duration=6)
    
    customers = get_customer_by_name_rows(customer_name)
    if not customers:
        output("Customer not found. Cancelled.")
        return
        
    selected_customer = pick_from_list(customers, lambda c: f"{c['customer_name']}, Account {c['account_number']}", "customers")
    if not selected_customer: return
    
    sites = get_customer_sites_by_account(selected_customer["cust_account_id"])
    if not sites: output("No active ship-to sites found."); return
    site = sites[0]

    prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"])
    if not prices: output("No price lists found."); return
    selected_price = prices[0] # Auto-select first price list for brevity in console

    terms = get_payment_term_rows()
    if not terms: output("No payment terms found."); return
    selected_term = terms[0]

    reps = get_salesrep_rows()
    if not reps: output("No salesreps found."); return
    selected_rep = reps[0]

    payload = create_payload(
        p_cust_po=cpo, p_item_id=selected_item["inventory_item_id"], p_ordered_item=selected_item["segment1"], p_qty=qty,
        p_price=selected_price["unit_list_price"], p_selling_price=selected_price["unit_list_price"],
        p_payment_term_id=selected_term["term_id"], p_price_list_id=selected_price["price_list_id"],
        p_salesrep_id=selected_rep["salesrep_id"], p_ship_to_org=site["ship_to_org_id"], p_sold_to_org=site["sold_to_org_id"], p_operating_unit=OPERATING_UNIT
    )

    output("Submitting your order, please wait...")
    try:
        result = send_order(payload)
        parsed = extract_erp_details(result)
        summ = generate_ai_summary("Create New Sales Order", parsed)
        global_last_html_payload = generate_order_html(result, summ)
        
        output(f"Order created successfully! {summ}")
        _print_parsed_order_console(parsed)
        trigger_auto_email("New Sales Order", global_last_html_payload)
    except Exception as e:
        output(f"Order creation failed: {e}")

def schedule_report_flow(intent: dict):
    output("Let's schedule an automated report.")
    cust = intent.get("customer_name") or get_input("Enter or say the customer name (Leave blank to run for ALL customers): ", duration=6)
    freq = intent.get("schedule_interval") or get_input("Enter or say the frequency (e.g., 30 minutes, 1 hour, daily): ", duration=6)
    email = intent.get("email_address") or input("\n  ⌨️  Please type the recipient email address: ").strip()
    
    if not email:
        output("Email is required for scheduling. Cancelled.")
        return

    start_schedule_thread(freq, cust.strip(), email.strip())
    target_name = cust if cust.strip() else "ALL Customers"
    output(f"✅ Schedule started! Emailing {target_name} reports to {email} based on '{freq}'.")

def order_details_by_customer_flow(cname: str):
    global global_last_html_payload
    output(f"Fetching order details for customer: '{cname}' ...")
    try:
        rows = get_order_details_by_customer(cname)
        if not rows:
            output(f"No orders found for customer '{cname}'.")
            return
            
        print(f"\n--- Order details for customer: '{cname}'  ({len(rows)} lines) ---")
        for r in rows[:10]:
            print(f"  Order: {r.get('ORDER_NUMBER')} | Item: {r.get('ITEM_NUMBER')} | Qty: {r.get('ORDERED_QTY')} | Status: {r.get('LINE_STATUS')}")
        if len(rows) > 10: print("  ... (showing first 10 rows)")
        
        summ_ctx = {"customer": cname, "count": len(rows), "samples": rows[:3]}
        summ = generate_ai_summary("Retrieve Orders by Customer", summ_ctx)
        global_last_html_payload = generate_customer_html(rows, cname, summ)
        
        if INPUT_MODE == "voice":
            speak(f"I found {len(rows)} lines for {cname}. {summ}")
        else:
            print(f"\n✨ AI Summary: {summ}")
            
        trigger_auto_email(f"Customer: {cname}", global_last_html_payload)
        
    except Exception as e:
        output(f"Error fetching order details: {e}")

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

        if header_id: 
            # Implement adding logic similar to main stream if needed
            output("Add line functionality initialized...")
        else: output("Cannot proceed without a Header ID.")
    except Exception as e:
        output(f"Error fetching order: {e}")


# --------------------------------------------------
# 8. Main Entry Point (NATURAL LANGUAGE CHAT LOOP)
# --------------------------------------------------
def main():
    global INPUT_MODE, AUTO_EMAIL_ENABLED, AUTO_EMAIL_TO, global_last_html_payload

    parser = argparse.ArgumentParser(description="ERP Sales Order Assistant")
    parser.add_argument("--mode", choices=["text", "voice"], default="text", help="Input mode: 'text' or 'voice'")
    args = parser.parse_args()
    INPUT_MODE = args.mode

    if INPUT_MODE == "voice" and not VOICE_AVAILABLE:
        print("ERROR: Voice packages are not installed.")
        sys.exit(1)

    print("=" * 60)
    print("  ERP Sales Order Assistant")
    print(f"  Mode: {'🎙️  VOICE (with Text Fallback)' if INPUT_MODE == 'voice' else '⌨️   TEXT'}")
    print("=" * 60)

    print("\n  ⌨️  Would you like to auto-send reports to an email after every operation? (yes/no): ", end="")
    auto_ans = input().strip().lower()
    if "yes" in auto_ans or "y" == auto_ans:
        AUTO_EMAIL_ENABLED = True
        print("  ⌨️  Enter recipient email address: ", end="")
        AUTO_EMAIL_TO = input().strip()
        print(f"  ✅ Auto-send is ON for {AUTO_EMAIL_TO}\n")

    if INPUT_MODE == "voice": speak("Welcome to the ERP Sales Order Assistant.")
    else: print("\n  👋 Welcome to the Centroid Sales Order Assistant!\n")

    conversation_history = []
    
    while True:
        prompt = get_input("\nHow can I help you today? (Say 'exit' to quit)\nYou: ", duration=6)
        if not prompt: continue
        
        prompt_lower = prompt.lower()
        if prompt_lower in ["exit", "quit", "stop", "cancel"]:
            output("Exiting the assistant. Goodbye!")
            break
            
        conversation_history.append({"role": "user", "content": prompt})
        
        print("  🧠 Understanding intent...", end="\r")
        intent = get_smart_intent(conversation_history, prompt, "unknown")
        print("                            ", end="\r") # clear spinner
        
        action = intent.get("action", "unknown")
        
        # Basic fallback if AI misses explicit commands
        if action == "unknown":
            if "create" in prompt_lower or "new order" in prompt_lower: action = "create"
            elif "search" in prompt_lower: action = "search"
            elif "detail" in prompt_lower: action = "order_details"
            elif "email" in prompt_lower or "send" in prompt_lower: action = "email"
            elif "schedule" in prompt_lower: action = "schedule_report"
            elif "stop schedule" in prompt_lower or "cancel schedule" in prompt_lower: action = "stop_schedule"
            elif re.search(r'\b(20\d{2})\b', prompt_lower) or "last year" in prompt_lower: action = "search"
            elif re.search(r'\b\d{5,}\b', prompt_lower): action = "get"
        
        # Regex overrides for numbers and years
        year_match = re.search(r'\b(20\d{2})\b', prompt)
        if year_match and not intent.get("year"): intent["year"] = int(year_match.group(1))
        
        order_match = re.search(r'(?:order|#|no\.?|number)\s*(\d{3,})|(?<!\d)(\d{5,})(?!\d)', prompt, re.IGNORECASE)
        if order_match and not intent.get("order_number"):
            num = order_match.group(1) or order_match.group(2)
            if num and not (2010 <= int(num) <= 2030):
                intent["order_number"] = int(num)
        
        # --------------------------------------------------
        # ACTION ROUTING
        # --------------------------------------------------
        if action == "create":
            create_order_flow(intent)
        
        elif action == "get":
            order_num = intent.get("order_number")
            if not order_num:
                num_str = get_input("Please specify the Order Number you want to retrieve:")
                order_num = parse_numeric_value(num_str)
            
            if order_num:
                try:
                    result = get_order(int(order_num))
                    parsed = extract_erp_details(result)
                    summ = generate_ai_summary("Retrieve Specific Order", parsed)
                    global_last_html_payload = generate_order_html(result, summ)
                    
                    _print_parsed_order_console(parsed)
                    output(f"✨ AI Summary: {summ}")
                    
                    trigger_auto_email(f"Order #{order_num}", global_last_html_payload)
                except Exception as e:
                    output(f"Error fetching order: {e}")
                    
        elif action == "search":
            adv_year = intent.get("year")
            adv_range = intent.get("date_range")
            adv_status = intent.get("status")
            
            if not adv_year and "last year" in prompt_lower: adv_year = datetime.datetime.now().year - 1
            if not adv_status and "booked" in prompt_lower: adv_status = "BOOKED"
            if not adv_status and "entered" in prompt_lower: adv_status = "ENTERED"
            
            try:
                res = get_orders_advanced(adv_range, adv_year, adv_status)
                count = res.get('total_count', 0)
                output(f"Total orders found: {count}")
                
                if count > 0:
                    for row in res["rows"][:20]:
                        line = f"Order {row[0]}, Status {row[1]}, Created {row[2]}"
                        print(f"    {line}")
                        if INPUT_MODE == "voice": speak(line)
                        
                    summ = generate_ai_summary("Search Orders", {"total": count, "filters": [adv_year, adv_range, adv_status]})
                    global_last_html_payload = generate_search_html(res, summ)
                    trigger_auto_email("Search Results", global_last_html_payload)
                    
            except Exception as e:
                output(f"Error searching orders: {e}")
                
        elif action == "order_details":
            cname = intent.get("customer_name")
            if not cname:
                cname = get_input("Please specify the exact customer name:")
            if cname:
                order_details_by_customer_flow(cname)
                
        elif action == "email":
            email = intent.get("email_address")
            if not email:
                email = get_input("Please provide the destination email address:")
            if email and global_last_html_payload:
                success, msg = send_erp_email(email, "Oracle ERP Update", "Details attached.", global_last_html_payload)
                if success: output(f"Email successfully sent to {email}.")
                else: output(f"Failed to send email: {msg}")
            else:
                output("No recent data to send. Please fetch or search for an order first.")
                
        elif action == "schedule_report":
            schedule_report_flow(intent)
            
        elif action == "stop_schedule":
            stop_schedule_event.set()
            output("✅ Automated scheduled reports have been successfully stopped.")
            
        else:
            resp = github_clarify(conversation_history, ["Could not determine the action. Do you want to create an order, get an order, search, or check customer details?"])
            output(f"🤖 {resp}")
            conversation_history.append({"role": "assistant", "content": resp})

if __name__ == "__main__":
    main()