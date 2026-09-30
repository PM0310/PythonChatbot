"""
Sales Order Chatbot — Flask backend with custom UI.
Calls Oracle EBS REST API: GET_ORDER to retrieve sales order details.
"""

import json
import ssl
import re
import datetime
import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import requests
import requests.adapters
import urllib3
from urllib3.util.ssl_ import create_urllib3_context
from requests.auth import HTTPBasicAuth
from flask import Flask, request, jsonify, send_from_directory, Response

# ── Optional voice packages ───────────────────────
try:
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

try:
    from word2number import w2n
    W2N_AVAILABLE = True
except ImportError:
    W2N_AVAILABLE = False

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from xhtml2pdf import pisa
    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False

# ── Suppress only the InsecureRequestWarning ──────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration ─────────────────────────────────
BASE_URL = "https://cendb.ad.centroid.com:4463"
GET_ORDER_URL = f"{BASE_URL}/webservices/rest/sales_order/GET_ORDER/"
PROCESS_ORDER_URL = f"{BASE_URL}/webservices/rest/sales_order/PROCESS_ORDER/"
CUST_SO_DTLS_URL = f"{BASE_URL}/webservices/rest/CustSODtls/XX_CUST_SO_DET_PRC1/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
ORG_ID = "204"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

# ── AI Summary configuration ─────────────────────
GITHUB_TOKEN = "REDACTED_SECRET"
GITHUB_MODEL = "gpt-4o"


def generate_ai_summary(operation_type: str, data: dict) -> str:
    """Generate a concise AI summary of an ERP operation result using GPT-4o."""
    if not OPENAI_AVAILABLE:
        return ""

    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=GITHUB_TOKEN,
        )

        today = datetime.datetime.now().strftime("%B %d, %Y")
        data_json = json.dumps(data, indent=2, default=str)[:3000]  # truncate for token limit

        system_prompt = (
            f"You are an ERP Sales Order Analyst. Today is {today}. "
            "Given the result of an ERP operation, write a concise executive summary (3-5 sentences). "
            "Highlight key details: order number, customer, status, amounts, line items count, "
            "any issues or exceptions. Be professional and actionable. "
            "Do NOT use markdown formatting — plain text only."
        )

        if operation_type == "order":
            user_prompt = f"Summarize this sales order lookup result:\n{data_json}"
        elif operation_type == "customer_orders":
            user_prompt = f"Summarize these customer order details:\n{data_json}"
        elif operation_type == "create":
            user_prompt = f"Summarize this order creation result:\n{data_json}"
        else:
            user_prompt = f"Summarize this ERP operation result:\n{data_json}"

        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI summary error: {e}")
        return ""

# ── Voice configuration ──────────────────────────
VOSK_MODEL_PATH = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
VOICE_DURATION = 5  # seconds to record
_vosk_model = None


def _load_vosk_model():
    """Lazy-load the Vosk model."""
    global _vosk_model
    if _vosk_model is None and VOSK_AVAILABLE:
        import os
        if os.path.exists(VOSK_MODEL_PATH):
            _vosk_model = Model(VOSK_MODEL_PATH)
            print(f"Vosk model loaded from {VOSK_MODEL_PATH}")
        else:
            print(f"WARNING: Vosk model not found at {VOSK_MODEL_PATH}")
    return _vosk_model


def recognize_speech(duration: int = VOICE_DURATION) -> str:
    """Record audio for `duration` seconds and return recognized text using Vosk."""
    model = _load_vosk_model()
    if model is None:
        return ""
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    print(f"\U0001f399  Listening for {duration} seconds...")
    audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                   channels=1, dtype="int16")
    sd.wait()
    if rec.AcceptWaveform(audio.tobytes()):
        result = json.loads(rec.Result())
    else:
        result = json.loads(rec.FinalResult())
    text = result.get("text", "").strip()
    print(f"\U0001f4dd  Recognised: '{text}'")
    return text


_tts_lock = threading.Lock()


def speak(text: str):
    """Speak text aloud using pyttsx3 (thread-safe)."""
    if not PYTTSX3_AVAILABLE:
        return
    print(f"\U0001f50a  {text}")
    with _tts_lock:
        engine = pyttsx3.init()
        engine.setProperty("rate", 160)
        engine.say(text)
        engine.runAndWait()
        engine.stop()


# ── Voice text normalization ──────────────────────
_WORD_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}

_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
    "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million", "billion",
}


def _convert_number_words(words: list) -> str:
    """Convert a list of number-word tokens to a digit string."""
    if not words:
        return ""

    phrase = " ".join(words)

    compound = {"ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
                "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
                "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
                "ninety", "hundred", "thousand", "million", "billion"}
    tens_words = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy",
                  "eighty", "ninety"}
    multipliers = {"hundred", "thousand", "million", "billion"}
    has_multiplier = any(w.lower() in multipliers for w in words)
    all_single = all(w.lower() in _WORD_DIGITS for w in words)

    if W2N_AVAILABLE and (has_multiplier or (not all_single and len(words) <= 3)):
        try:
            result = str(w2n.word_to_num(phrase))
            return result
        except Exception:
            pass

    result_parts = []
    compound_buf = []

    def flush_compound():
        if not compound_buf:
            return
        sub = " ".join(compound_buf)
        if W2N_AVAILABLE:
            try:
                result_parts.append(str(w2n.word_to_num(sub)))
            except Exception:
                for w in compound_buf:
                    result_parts.append(_WORD_DIGITS.get(w.lower(), w))
        else:
            for w in compound_buf:
                result_parts.append(_WORD_DIGITS.get(w.lower(), w))
        compound_buf.clear()

    for w in words:
        wl = w.lower()
        if wl in compound:
            compound_buf.append(w)
        elif wl in _WORD_DIGITS:
            if compound_buf and compound_buf[-1].lower() in tens_words:
                compound_buf.append(w)
            else:
                flush_compound()
                result_parts.append(_WORD_DIGITS[wl])
        else:
            flush_compound()
            result_parts.append(w)

    flush_compound()
    return "".join(result_parts)


def normalize_voice_text(text: str) -> str:
    """Convert spoken text to a form the intent matcher can handle."""
    if not text:
        return text

    text = text.strip()

    tokens = text.split()
    result_tokens = []
    num_buffer = []

    def flush_number_buffer():
        if not num_buffer:
            return
        converted = _convert_number_words(num_buffer)
        result_tokens.append(converted)
        num_buffer.clear()

    for token in tokens:
        if token.lower() in _NUMBER_WORDS:
            num_buffer.append(token)
        else:
            flush_number_buffer()
            result_tokens.append(token)

    flush_number_buffer()
    return " ".join(result_tokens)


# ── TLS adapter for legacy Oracle EBS ciphers ────
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def get_order(order_number: int) -> dict:
    """Call Oracle EBS GET_ORDER REST service."""
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility": "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Org_Id": ORG_ID,
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_ORDER_NUMBER": order_number,
            },
        }
    }

    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False

    resp = session.post(
        GET_ORDER_URL,
        headers=HEADERS,
        data=json.dumps(payload),
        timeout=180,
    )

    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def _build_session():
    """Create a requests session with TLS adapter and auth."""
    s = requests.Session()
    s.mount("https://", ForceTLSAdapter())
    s.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    s.verify = False
    return s


def get_customer_orders(customer_name: str) -> dict:
    """Call CustSODtls REST service to get sales order details by customer name."""
    session = _build_session()
    resp = session.get(
        CUST_SO_DTLS_URL,
        headers=HEADERS,
        params={"P_CUSTOMER_NAME": customer_name},
        timeout=180,
    )
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def create_order(order_data: dict) -> dict:
    """Call Oracle EBS PROCESS_ORDER REST service to create a sales order."""
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility": "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Org_Id": ORG_ID,
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "ATTRIBUTE1": "WEB",
                    "ATTRIBUTE6": order_data.get("attribute6", "000004783"),
                    "CUST_PO_NUMBER": order_data.get("cust_po_number", ""),
                    "ORDER_TYPE_ID": int(order_data.get("order_type_id", 1430)),
                    "ORG_ID": int(ORG_ID),
                    "PAYMENT_TERM_ID": int(order_data.get("payment_term_id", 4)),
                    "PRICE_LIST_ID": int(order_data.get("price_list_id", 1000)),
                    "SALESREP_ID": int(order_data.get("salesrep_id", 10067)),
                    "SHIP_TO_ORG_ID": int(order_data.get("ship_to_org_id", 6472)),
                    "SOLD_TO_ORG_ID": int(order_data.get("sold_to_org_id", 5391)),
                    "TRANSACTIONAL_CURR_CODE": order_data.get("currency", "USD"),
                    "OPERATION": "CREATE",
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": [
                        {
                            "INVENTORY_ITEM_ID": int(order_data.get("inventory_item_id", 12027)),
                            "ORDERED_ITEM": order_data.get("ordered_item", ""),
                            "LINE_TYPE_ID": int(order_data.get("line_type_id", 1427)),
                            "ORDERED_QUANTITY": int(order_data.get("ordered_quantity", 1)),
                            "SCHEDULE_SHIP_DATE": order_data.get("schedule_ship_date", ""),
                            "UNIT_LIST_PRICE": float(order_data.get("unit_list_price", 0)),
                            "UNIT_SELLING_PRICE": float(order_data.get("unit_selling_price", 0)),
                            "OPERATION": "CREATE",
                        }
                    ]
                },
                "P_ACTION_REQUEST_TBL": {
                    "P_ACTION_REQUEST_TBL_ITEM": [
                        {
                            "REQUEST_TYPE": "BOOK_ORDER",
                            "ENTITY_CODE": "HEADER",
                        }
                    ]
                },
                "P_RTRIM_DATA": "Y",
            },
        }
    }

    session = _build_session()
    resp = session.post(
        PROCESS_ORDER_URL,
        headers=HEADERS,
        data=json.dumps(payload),
        timeout=180,
    )

    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def parse_create_order_response(data: dict) -> dict:
    """Parse the PROCESS_ORDER response into a displayable summary."""
    try:
        output = data.get("OutputParameters", data)
        header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
        return_status = output.get("X_RETURN_STATUS", output.get("RETURN_STATUS", ""))
        msg_count = output.get("X_MSG_COUNT", output.get("MSG_COUNT", 0))
        msg_data = output.get("X_MSG_DATA", output.get("MSG_DATA", ""))

        order_number = header.get("ORDER_NUMBER", "")
        status = header.get("FLOW_STATUS_CODE", "")
        cust_po = header.get("CUST_PO_NUMBER", "")

        return {
            "order_number": order_number,
            "return_status": return_status,
            "flow_status": status,
            "cust_po_number": cust_po,
            "msg_count": msg_count,
            "msg_data": msg_data,
            "success": return_status in ("S", "s"),
        }
    except Exception as e:
        return {"error": f"Failed to parse response: {e}", "raw": data}


def parse_customer_orders(data: dict) -> dict:
    """Parse the CustSODtls response into a displayable structure."""
    try:
        output = data.get("OutputParameters", data)
        # The result set can be nested under various keys
        rows_raw = (
            output.get("X_RESULT", None)
            or output.get("P_RESULT", None)
            or output.get("ResultSet", None)
            or output
        )
        # Normalise to list of dicts
        if isinstance(rows_raw, dict):
            inner = (
                rows_raw.get("X_RESULT_ITEM", None)
                or rows_raw.get("P_RESULT_ITEM", None)
                or rows_raw.get("Row", None)
                or rows_raw.get("ROW", None)
            )
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
    except Exception as e:
        return {"error": f"Failed to parse customer orders: {e}", "raw": data}


def parse_order_response(data: dict) -> dict:
    """Extract key fields from the GET_ORDER response into a flat summary."""
    try:
        output = data.get("OutputParameters", data)
        header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
        header_val = output.get("X_HEADER_VAL_REC", output.get("HEADER_VAL_REC", {}))
        lines_raw = output.get("X_LINE_TBL", output.get("LINE_TBL", {}))
        lines_val_raw = output.get("X_LINE_VAL_TBL", output.get("LINE_VAL_TBL", {}))
        messages = output.get("X_MSG_DATA", output.get("MSG_DATA", ""))

        # Normalise lines to a list
        if isinstance(lines_raw, dict):
            items = lines_raw.get("X_LINE_TBL_ITEM", lines_raw.get("LINE_TBL_ITEM", []))
            if isinstance(items, dict):
                items = [items]
        elif isinstance(lines_raw, list):
            items = lines_raw
        else:
            items = []

        # Normalise line value records
        if isinstance(lines_val_raw, dict):
            val_items = lines_val_raw.get("X_LINE_VAL_TBL_ITEM", lines_val_raw.get("LINE_VAL_TBL_ITEM", []))
            if isinstance(val_items, dict):
                val_items = [val_items]
        elif isinstance(lines_val_raw, list):
            val_items = lines_val_raw
        else:
            val_items = []

        lines = []
        for idx, item in enumerate(items):
            val = val_items[idx] if idx < len(val_items) else {}
            lines.append({
                "Line": item.get("LINE_NUMBER", ""),
                "Item": item.get("ORDERED_ITEM", ""),
                "Qty": item.get("ORDERED_QUANTITY", ""),
                "UOM": item.get("ORDER_QUANTITY_UOM", ""),
                "Unit Price": item.get("UNIT_SELLING_PRICE", ""),
                "Status": item.get("FLOW_STATUS_CODE", ""),
                # Extended fields for PDF
                "List Price": item.get("UNIT_LIST_PRICE", ""),
                "Line Type ID": item.get("LINE_TYPE_ID", ""),
                "Request Date": item.get("REQUEST_DATE", ""),
                "Promise Date": item.get("PROMISE_DATE", ""),
                "Shipment #": item.get("SHIPMENT_NUMBER", ""),
                "Open Flag": item.get("OPEN_FLAG", ""),
                "Booked Flag": item.get("BOOKED_FLAG", ""),
                "Cancelled Qty": item.get("CANCELLED_QUANTITY", ""),
                "Item Type": item.get("ITEM_TYPE_CODE", ""),
                "Ship To": val.get("SHIP_TO_ORG", ""),
                "Ship From": val.get("SHIP_FROM_ORG", ""),
                "Line Type": val.get("LINE_TYPE", ""),
            })

        # Full header details for PDF
        cname = header_val.get("SOLD_TO_ORG", "") or header.get("SOLD_TO_ORG", header.get("SOLD_TO_ORG_ID", ""))
        header_details = {
            "Order Number": header.get("ORDER_NUMBER", ""),
            "Header ID": header.get("HEADER_ID", ""),
            "Customer PO": header.get("CUST_PO_NUMBER", ""),
            "Flow Status": header.get("FLOW_STATUS_CODE", ""),
            "Order Category": header.get("ORDER_CATEGORY_CODE", ""),
            "Ordered Date": header.get("ORDERED_DATE", ""),
            "Request Date": header.get("REQUEST_DATE", ""),
            "Pricing Date": header.get("PRICING_DATE", ""),
            "Currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
            "Booked Flag": header.get("BOOKED_FLAG", ""),
            "Open Flag": header.get("OPEN_FLAG", ""),
            "Cancelled Flag": header.get("CANCELLED_FLAG", ""),
            "Org ID": header.get("ORG_ID", ""),
            "Order Type": header_val.get("ORDER_TYPE", "") or header.get("ORDER_TYPE_ID", ""),
            "Customer Name": cname,
            "Customer Number": header_val.get("CUSTOMER_NUMBER", ""),
            "Ship To": header_val.get("SHIP_TO_ORG", ""),
            "Ship To Address": header_val.get("SHIP_TO_ADDRESS1", ""),
            "Ship To City": header_val.get("SHIP_TO_CITY", ""),
            "Ship To State": header_val.get("SHIP_TO_STATE", ""),
            "Ship To Country": header_val.get("SHIP_TO_COUNTRY", ""),
            "Bill To": header_val.get("INVOICE_TO_ORG", ""),
            "Bill To Address": header_val.get("INVOICE_TO_ADDRESS1", ""),
            "Salesrep": header_val.get("SALESREP", "") or header.get("SALESREP_ID", ""),
            "Payment Term": header_val.get("PAYMENT_TERM", "") or header.get("PAYMENT_TERM_ID", ""),
            "Price List": header_val.get("PRICE_LIST", "") or header.get("PRICE_LIST_ID", ""),
            "Shipping Method": header_val.get("SHIPPING_METHOD", ""),
            "Freight Terms": header_val.get("FREIGHT_TERMS", ""),
            "FOB Point": header_val.get("FOB_POINT", ""),
        }

        return {
            "order_number": header.get("ORDER_NUMBER", ""),
            "status": header.get("FLOW_STATUS_CODE", ""),
            "ordered_date": header.get("ORDERED_DATE", ""),
            "customer_name": cname,
            "currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
            "lines": lines,
            "messages": messages,
            "header_details": header_details,
        }
    except Exception as e:
        return {"error": f"Failed to parse response: {e}", "raw": data}


# ── In-memory store for last operation data (per-process) ─────
_last_operation = {
    "type": None,          # "order", "create", "customer_orders"
    "data": None,          # parsed result dict
    "raw": None,           # raw API response
    "email_html": "",     # pre-built email HTML
    "pdf_html": "",       # full tabular HTML for PDF (all rows)
    "ai_summary": "",
}

# ── Auto-email & Scheduler state ──────────────────────────────
_auto_email = {
    "enabled": False,
    "to": "",
}

_scheduler = {
    "active": False,
    "interval_mins": 60,
    "customer_name": "",
    "to_email": "",
    "last_run": None,
    "last_status": None,
    "runs": 0,
}
_stop_event = threading.Event()
_scheduler_thread = None


def _scheduled_worker(interval_mins: int, customer_name: str, to_email: str):
    """Background thread: fetch order data and email on a recurring interval."""
    _stop_event.clear()
    while not _stop_event.is_set():
        stopped = _stop_event.wait(timeout=interval_mins * 60)
        if stopped:
            break
        try:
            target = customer_name.strip() if customer_name else ""
            if target:
                raw = get_customer_orders(target)
                parsed = parse_customer_orders(raw)
                parsed["customer_name"] = target
                summary = generate_ai_summary("customer_orders", parsed)
                _last_operation["pdf_html"] = _generate_full_pdf_html("customer_orders", parsed, summary)
                html_payload = _generate_customer_orders_email_html(parsed)
                subject = f"Scheduled Report: {target}"
            else:
                html_payload = _last_operation.get("email_html", "")
                subject = "Scheduled Report: Latest Order Data"

            if html_payload:
                body_text = "Your automated scheduled report is attached below."
                success, msg = send_erp_email(to_email, subject, body_text, html_payload)
                _scheduler["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _scheduler["runs"] += 1
                _scheduler["last_status"] = "sent" if success else f"failed: {msg}"
            else:
                _scheduler["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _scheduler["last_status"] = "skipped: no data"
        except Exception as e:
            _scheduler["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _scheduler["last_status"] = f"error: {e}"


def _start_scheduler(interval_mins: int, customer_name: str, to_email: str):
    """Start the scheduler background thread."""
    global _scheduler_thread
    _stop_scheduler()
    _scheduler["active"] = True
    _scheduler["interval_mins"] = interval_mins
    _scheduler["customer_name"] = customer_name
    _scheduler["to_email"] = to_email
    _scheduler["runs"] = 0
    _scheduler["last_run"] = None
    _scheduler["last_status"] = None
    _scheduler_thread = threading.Thread(
        target=_scheduled_worker,
        args=(interval_mins, customer_name, to_email),
        daemon=True,
    )
    _scheduler_thread.start()


def _stop_scheduler():
    """Stop the scheduler background thread."""
    global _scheduler_thread
    _stop_event.set()
    _scheduler["active"] = False
    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=2)
    _scheduler_thread = None
    _stop_event.clear()


def trigger_auto_email(context: str):
    """Send auto-email if enabled, using the last operation's HTML."""
    if not _auto_email["enabled"] or not _auto_email["to"]:
        return
    html_payload = _last_operation.get("email_html", "")
    if not html_payload:
        return
    to_email = _auto_email["to"]
    subject = f"Automated ERP Update — {context}"
    body_text = (
        "Hi,\n\nPlease find the automated report attached below.\n\n"
        "This email was sent automatically after the operation completed.\n\n"
        "Regards,\nSales Order Assistant"
    )
    threading.Thread(
        target=send_erp_email,
        args=(to_email, subject, body_text, html_payload),
        daemon=True,
    ).start()


# ── Email Template (Matches Bot UI Style) ───────────────
def _build_email_layout(cname: str, report_type: str, ai_summary: str,
                        table_html: str, alerts: dict, faqs: list) -> str:
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    alerts_html = "<ul style='padding-left: 20px; font-size: 14px; margin-bottom: 0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom: 5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"

    faqs_html = (
        "<table style='border-collapse: collapse; width: 100%; border: none; font-size: 14px;'>"
        "<tr><th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>Question</th>"
        "<th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>AI Answer</th></tr>"
    )
    for q, a in faqs:
        faqs_html += f"<tr><td style='padding: 8px;'>{q}</td><td style='padding: 8px;'>{a}</td></tr>"
    faqs_html += "</table>"

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 800px; margin: auto; color: #000; padding: 10px;">

        <h3 style="color: #000; font-size: 16px; margin-top: 0;">Header Details</h3>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 20px;">
            <li style="margin-bottom: 5px;">Customer Name: {cname}</li>
            <li style="margin-bottom: 5px;">Contact Name: Account Primary</li>
            <li style="margin-bottom: 5px;">Date of Report: {report_date}</li>
            <li style="margin-bottom: 5px;">Statement Period: {report_type}</li>
        </ul>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">

        <h3 style="color: #000; font-size: 16px;">Executive Summary</h3>
        <p>{ai_summary}</p>
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


def _generate_order_email_html(parsed: dict) -> str:
    """Build email HTML from a GET_ORDER parsed result."""
    order_num = parsed.get("order_number", "N/A")
    cname = parsed.get("customer_name", "Unknown Customer")
    status = parsed.get("status", "N/A")
    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"
    table = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for ln in parsed.get("lines", []):
        table += "<tr>"
        table += f"<td style='{td}'>{order_num}</td>"
        table += f"<td style='{td}'>{ln.get('Item', 'N/A')}</td>"
        table += f"<td style='{td}'>{ln.get('Qty', 'N/A')}</td>"
        table += f"<td style='{td}'>{ln.get('Status', 'N/A')}</td>"
        table += f"<td style='{td}'>TBD</td>"
        table += f"<td style='{td}'>Pending</td>"
        table += f"<td style='{td}'>N/A</td>"
        table += "</tr>"
    table += "</table>"
    has_holds = status in ("ENTERED",) or "HOLD" in str(status).upper()
    alerts = {
        "Backorders": "None detected for this specific transaction",
        "Holds": "1" if has_holds else "0",
        "Partial Shipments": "N/A",
        "Payment Holds": "Check customer balance",
    }
    faqs = [
        (f"Why is Order {order_num} currently {status}?",
         f"The order is in {status} status waiting for the next step in the fulfillment cycle."),
        ("Can I expect partial shipment?",
         "Depends on line-level availability. Check shipping notices for updates."),
    ]
    summary = f"Order #{order_num} for customer {cname} is currently in {status} status."
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", summary, table, alerts, faqs)


def _generate_create_email_html(parsed: dict) -> str:
    """Build email HTML from a PROCESS_ORDER (create) result."""
    order_num = parsed.get("order_number", "N/A")
    status = parsed.get("flow_status", "N/A")
    cust_po = parsed.get("cust_po_number", "N/A")
    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"
    table = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Customer PO", "Status", "Return Status"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    table += f"<tr><td style='{td}'>{order_num}</td><td style='{td}'>{cust_po}</td>"
    table += f"<td style='{td}'>{status}</td><td style='{td}'>{parsed.get('return_status', '')}</td></tr>"
    table += "</table>"
    alerts = {"Backorders": "N/A", "Holds": "0", "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("Was the order booked?", f"Order #{order_num} has status: {status}.")]
    summary = f"New order #{order_num} was created with PO {cust_po}. Current status: {status}."
    return _build_email_layout("N/A", f"New Order Created: #{order_num}", summary, table, alerts, faqs)


def _generate_customer_orders_email_html(parsed: dict) -> str:
    """Build email HTML from a CustSODtls result."""
    cname = parsed.get("customer_name", "Unknown Customer")
    rows = parsed.get("rows", [])
    keys = parsed.get("raw_keys", [])
    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"
    # Use up to 7 columns or all if fewer
    display_keys = keys[:7] if len(keys) > 7 else keys
    table = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in display_keys:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for r in rows[:50]:
        table += "<tr>"
        for k in display_keys:
            table += f"<td style='{td}'>{r.get(k, 'N/A')}</td>"
        table += "</tr>"
    table += "</table>"
    alerts = {"Backorders": "0", "Holds": "0", "Partial Shipments": "Check line statuses", "Payment Holds": "0"}
    faqs = [("Are there any delayed orders?", "Check the table for delayed order flags.")]
    summary = f"{len(rows)} order record(s) found for customer {cname}."
    return _build_email_layout(cname, "All Recent Customer Orders", summary, table, alerts, faqs)


# ── Full-data PDF Table HTML ──────────────────────

def _generate_full_pdf_html(op_type: str, parsed: dict, ai_summary: str = "") -> str:
    """Build a comprehensive PDF report HTML matching the Bot UI Layout (All rows)."""
    ts = datetime.datetime.now().strftime("%B %d, %Y %I:%M %p")

    # Strict basic CSS that xhtml2pdf handles perfectly without tearing tables
    css = """
    @page { 
        size: A4 landscape; 
        margin: 1cm;
        @frame footer { 
            -pdf-frame-content: footerContent; 
            bottom: 1cm; margin-left: 1cm; margin-right: 1cm; height: 1cm; text-align: right; 
        }
    }
    body { font-family: Helvetica, sans-serif; font-size: 10px; color: #1a1a1a; }
    h1 { color: #2563eb; font-size: 18px; margin-bottom: 5px; }
    h2 { color: #1e40af; font-size: 14px; margin-top: 15px; margin-bottom: 5px; border-bottom: 1px solid #cbd5e1; padding-bottom: 2px; }
    table { width: 100%; border-collapse: collapse; margin-top: 5px; }
    th { background-color: #2563eb; color: white; padding: 6px; font-weight: bold; text-align: left; border: 1px solid #94a3b8; }
    td { padding: 6px; border: 1px solid #cbd5e1; }
    .bg-light { background-color: #f8fafc; }
    .label { font-weight: bold; background-color: #e2e8f0; width: 25%; }
    .summary-box { background-color: #eff6ff; border: 1px solid #bfdbfe; padding: 10px; border-radius: 4px; margin-bottom: 15px; font-size: 11px; }
    """

    html = f"<html><head><style>{css}</style></head><body>"
    
    summary_html = f"<div class='summary-box'><b>✨ AI Summary:</b><br/>{ai_summary}</div>" if ai_summary else ""

    if op_type == "order":
        order_num = parsed.get("order_number", "N/A")
        status = parsed.get("status", "N/A")
        hdr = parsed.get("header_details", {})
        lines = parsed.get("lines", [])
        
        html += f"<h1>📋 Order #{order_num}</h1>"
        html += f"<p>Generated: {ts}</p>"
        html += summary_html
        
        html += "<h2>🧾 Header Details</h2>"
        html += "<table>"
        keys = list(hdr.keys())
        for i in range(0, len(keys), 2):
            k1 = keys[i]
            v1 = str(hdr[k1]) if hdr[k1] not in (None, "None", "") else "—"
            k2 = keys[i+1] if i+1 < len(keys) else None
            v2 = str(hdr[k2]) if k2 and hdr[k2] not in (None, "None", "") else "—"
            
            row_html = f"<tr><td class='label'>{k1}</td><td>{v1}</td>"
            if k2:
                row_html += f"<td class='label'>{k2}</td><td>{v2}</td>"
            else:
                row_html += "<td class='label'></td><td></td>"
            row_html += "</tr>"
            html += row_html
        html += "</table>"
        
        html += f"<h2>📦 Line Details ({len(lines)} line(s))</h2>"
        if lines:
            html += "<table><thead><tr>"
            cols = ["Line", "Item", "Qty", "UOM", "Unit Price", "List Price", "Status"]
            for c in cols: html += f"<th>{c}</th>"
            html += "</tr></thead><tbody>"
            for i, ln in enumerate(lines):
                bg = "class='bg-light'" if i % 2 == 0 else ""
                html += f"<tr {bg}>"
                for c in cols:
                    html += f"<td>{ln.get(c, '')}</td>"
                html += "</tr>"
            html += "</tbody></table>"
        else:
            html += "<p>No line items found.</p>"

    elif op_type == "customer_orders":
        cname = parsed.get("customer_name", "Unknown")
        rows = parsed.get("rows", [])
        
        html += f"<h1>👤 Customer Orders — {cname}</h1>"
        html += f"<p>Generated: {ts} | Total Records: {len(rows)}</p>"
        html += summary_html
        
        if rows:
            keys = parsed.get("raw_keys") or list(rows[0].keys())
            # Truncate to reasonable width for PDF fitting (8 columns max)
            display_keys = keys[:8] if len(keys) > 8 else keys
            
            html += "<table><thead><tr>"
            for k in display_keys: html += f"<th>{k}</th>"
            html += "</tr></thead><tbody>"
            for i, r in enumerate(rows):
                bg = "class='bg-light'" if i % 2 == 0 else ""
                html += f"<tr {bg}>"
                for k in display_keys:
                    val = r.get(k, "")
                    if ("PRICE" in k.upper() or "BALANCE" in k.upper()) and str(val).replace('.','',1).lstrip('-').isdigit():
                        val = f"${float(val):,.2f}"
                    html += f"<td>{val}</td>"
                html += "</tr>"
            html += "</tbody></table>"
        else:
            html += "<p>No orders found for this customer.</p>"

    elif op_type == "create":
        order_num = parsed.get("order_number", "N/A")
        html += f"<h1>➕ Order Creation Result — #{order_num}</h1>"
        html += f"<p>Generated: {ts}</p>"
        html += summary_html
        
        html += "<h2>Order Details</h2>"
        html += "<table>"
        details = [
            ("Order Number", parsed.get("order_number", "")),
            ("Return Status", parsed.get("return_status", "")),
            ("Customer PO", parsed.get("cust_po_number", "")),
            ("Flow Status", parsed.get("flow_status", "")),
            ("Message Count", parsed.get("msg_count", "")),
            ("Message", parsed.get("msg_data", "")),
        ]
        for i in range(0, len(details), 2):
            k1, v1 = details[i]
            v1 = str(v1) if v1 else "—"
            if i+1 < len(details):
                k2, v2 = details[i+1]
                v2 = str(v2) if v2 else "—"
                html += f"<tr><td class='label'>{k1}</td><td>{v1}</td><td class='label'>{k2}</td><td>{v2}</td></tr>"
            else:
                html += f"<tr><td class='label'>{k1}</td><td>{v1}</td><td class='label'></td><td></td></tr>"
        html += "</table>"
        
    html += "<div id='footerContent'>Page <pdf:pagenumber> of <pdf:pagecount></div>"
    html += "</body></html>"
    return html


# ── PDF Generation ────────────────────────────────
import io


def generate_pdf(html_content: str) -> bytes:
    """Convert ready HTML string to PDF bytes using xhtml2pdf."""
    if not XHTML2PDF_AVAILABLE or not html_content:
        return b""
    try:
        buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=buffer)
        if pisa_status.err:
            print(f"PDF generation error: {pisa_status.err}")
            return b""
        return buffer.getvalue()
    except Exception as e:
        print(f"PDF generation failed: {e}")
        return b""


def _get_pdf_filename() -> str:
    """Generate a descriptive PDF filename based on the last operation."""
    op_type = _last_operation.get("type") or "report"
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    data = _last_operation.get("data") or {}
    if op_type == "order":
        label = f"Order_{data.get('order_number', 'unknown')}"
    elif op_type == "customer_orders":
        cname = data.get("customer_name", "customer").replace(" ", "_")
        label = f"CustomerOrders_{cname}"
    elif op_type == "create":
        label = f"NewOrder_{data.get('order_number', 'unknown')}"
    else:
        label = "ERP_Report"
    return f"{label}_{ts}.pdf"


def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str) -> tuple:
    """Send an email with the formatted HTML report and attached PDF."""
    sender = "erp.assistant@yourdomain.com"
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    html_content = f"""
    <html>
    <head></head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <p style="color: #333;">{body_text.replace(chr(10), '<br>')}</p>
        <br>
        {html_table}
    </body>
    </html>
    """

    # Attach text and HTML as alternatives inside a sub-part
    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(body_text, "plain"))
    alt_part.attach(MIMEText(html_content, "html"))
    msg.attach(alt_part)

    # Generate and attach PDF (use full tabular pdf_html if available)
    pdf_source = _last_operation.get("pdf_html") or html_table
    pdf_bytes = generate_pdf(pdf_source)
    if pdf_bytes:
        pdf_name = _get_pdf_filename()
        pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_part.add_header("Content-Disposition", "attachment", filename=pdf_name)
        msg.attach(pdf_part)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login("pavanmaccha042@gmail.com", "ltvxbwhkzkrptueg")
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)


# ── Flask App ─────────────────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="/static")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """Handle a chat message from the user."""
    body = request.get_json(force=True)
    user_msg = (body.get("message") or "").strip()

    if not user_msg:
        return jsonify({"reply": "Please type a message.", "type": "text"})

    # Normalize voice input (convert spoken numbers to digits, etc.)
    normalized = normalize_voice_text(user_msg)
    print(f"\U0001f4ac  Input: '{user_msg}' -> Normalized: '{normalized}'")

    lower = normalized.lower()

    # Check for greetings
    greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
    if lower in greetings:
        return jsonify({
            "reply": "Hello! I'm the Sales Order Assistant.\n\nYou can:\n\u2022 **Get order 67965** \u2014 Look up a sales order\n\u2022 **Customer orders for Vision Operations** \u2014 Orders by customer\n\u2022 **Create order** \u2014 Create a new sales order\n\u2022 **Send email to user@domain.com** \u2014 Email last operation results",
            "type": "text",
        })

    # Check for help
    if lower in ("help", "?", "commands"):
        return jsonify({
            "reply": "Here's what I can do:\n\n\u2022 **Get order [number]** \u2014 Retrieve details for a sales order\n\u2022 **Customer orders for [name]** \u2014 Get all orders for a customer\n\u2022 **Create order** \u2014 Create a new sales order\n\u2022 **Send email to [address]** \u2014 Email the last operation results\n\u2022 **help** \u2014 Show this message",
            "type": "text",
        })

    import re

    # Check for send email intent
    email_match = re.search(
        r"(?:send|email|mail)\s+(?:email\s+)?(?:to\s+)?([\w.+-]+@[\w.-]+\.\w+)",
        normalized, re.IGNORECASE,
    )
    if email_match:
        to_addr = email_match.group(1)
        return jsonify({
            "reply": {"to_email": to_addr, "has_data": _last_operation["type"] is not None},
            "type": "email_form",
        })

    # Check for generic email/send intent (no address provided)
    if re.search(r"\b(send|email|mail)\b", lower) and not re.search(r"\b(create|new|place|book|add|get|show|order|customer)\b", lower):
        return jsonify({
            "reply": {"to_email": "", "has_data": _last_operation["type"] is not None},
            "type": "email_form",
        })

    # Check for create order intent (broader patterns for voice)
    if re.search(r"\b(create|new|place|book|add|make)\s+(a\s+|an\s+|the\s+|new\s+)?(sales\s+)?order\b", lower):
        return jsonify({"reply": "create_form", "type": "create_form"})

    # Check for customer order lookup — broader patterns for voice
    cust_match = re.search(
        r"(?:"
        r"customer\s+(?:orders?|details?)\s+(?:(?:for|of)\s+)?(.+)"
        r"|orders?\s+(?:for|of|by)\s+(?:customer\s+)?(.+)"
        r"|(?:show|get|find|look\s*up|fetch|retrieve)\s+customer\s+orders?\s*(?:(?:for|of|by)\s+)?(.+)"
        r")",
        normalized, re.IGNORECASE,
    )
    if cust_match:
        cust_name = (cust_match.group(1) or cust_match.group(2) or cust_match.group(3) or "").strip().strip("'\"")
        # Remove trailing filler words from voice
        cust_name = re.sub(r"\s+(please|thanks|thank you)$", "", cust_name, flags=re.IGNORECASE).strip()
        if cust_name:
            try:
                raw = get_customer_orders(cust_name)
                parsed = parse_customer_orders(raw)
                parsed["customer_name"] = cust_name
                summary = generate_ai_summary("customer_orders", parsed)
                
                _last_operation["type"] = "customer_orders"
                _last_operation["data"] = parsed
                _last_operation["raw"] = raw
                _last_operation["ai_summary"] = summary
                _last_operation["email_html"] = _generate_customer_orders_email_html(parsed)
                _last_operation["pdf_html"] = _generate_full_pdf_html("customer_orders", parsed, summary)
                
                trigger_auto_email(f"Customer: {cust_name}")
                return jsonify({"reply": parsed, "type": "customer_orders", "ai_summary": summary})
            except requests.exceptions.HTTPError as e:
                return jsonify({"reply": f"REST API error: {e}", "type": "error"})
            except requests.exceptions.ConnectionError:
                return jsonify({
                    "reply": "Could not connect to the Oracle EBS server. Please check network/VPN.",
                    "type": "error",
                })
            except Exception as e:
                return jsonify({"reply": f"Something went wrong: {e}", "type": "error"})

    # Try to extract an order number from normalized text (digits)
    order_match = re.search(r"\b(\d{4,})\b", normalized)
    if order_match:
        order_num = int(order_match.group(1))
        try:
            raw = get_order(order_num)
            parsed = parse_order_response(raw)
            summary = generate_ai_summary("order", parsed)
            
            _last_operation["type"] = "order"
            _last_operation["data"] = parsed
            _last_operation["raw"] = raw
            _last_operation["ai_summary"] = summary
            _last_operation["email_html"] = _generate_order_email_html(parsed)
            _last_operation["pdf_html"] = _generate_full_pdf_html("order", parsed, summary)
            
            trigger_auto_email(f"Order #{order_num}")
            return jsonify({"reply": parsed, "type": "order", "ai_summary": summary})
        except requests.exceptions.HTTPError as e:
            return jsonify({"reply": f"REST API error: {e}", "type": "error"})
        except requests.exceptions.ConnectionError:
            return jsonify({
                "reply": "Could not connect to the Oracle EBS server. Please check network/VPN.",
                "type": "error",
            })
        except Exception as e:
            return jsonify({"reply": f"Something went wrong: {e}", "type": "error"})

    # Broad "get/show/find order" without a number — ask for it
    if re.search(r"\b(get|show|find|look\s*up|fetch|retrieve|check)\s+(an?\s+|the\s+)?(sales\s+)?order\b", lower):
        return jsonify({
            "reply": "Which order number would you like to look up? Please say or type the number.",
            "type": "text",
        })

    return jsonify({
        "reply": "I couldn't understand your request.\n\nTry something like:\n\u2022 **Get order 67965**\n\u2022 **Customer orders for Vision Operations**\n\u2022 **Create order**\n\u2022 **Send email to user@domain.com**",
        "type": "text",
    })


@app.route("/api/create-order", methods=["POST"])
def api_create_order():
    """Accept order form data and call PROCESS_ORDER REST service."""
    body = request.get_json(force=True)
    try:
        raw = create_order(body)
        parsed = parse_create_order_response(raw)
        summary = generate_ai_summary("create", parsed)
        
        _last_operation["type"] = "create"
        _last_operation["data"] = parsed
        _last_operation["raw"] = raw
        _last_operation["ai_summary"] = summary
        _last_operation["email_html"] = _generate_create_email_html(parsed)
        _last_operation["pdf_html"] = _generate_full_pdf_html("create", parsed, summary)
        
        trigger_auto_email(f"New Order #{parsed.get('order_number', '')}")
        return jsonify({"reply": parsed, "type": "create_result", "ai_summary": summary})
    except requests.exceptions.HTTPError as e:
        return jsonify({"reply": f"REST API error: {e}", "type": "error"})
    except requests.exceptions.ConnectionError:
        return jsonify({
            "reply": "Could not connect to the Oracle EBS server. Please check network/VPN.",
            "type": "error",
        })
    except Exception as e:
        return jsonify({"reply": f"Something went wrong: {e}", "type": "error"})


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    """Send the last operation result as an email."""
    body = request.get_json(force=True)
    to_email = (body.get("to_email") or "").strip()
    subject = (body.get("subject") or "Oracle ERP Order Details Update").strip()
    body_text = (body.get("body") or "Please find the requested order details structured below.").strip()

    if not to_email:
        return jsonify({"reply": "Email address is required.", "type": "error"})

    html_payload = _last_operation.get("email_html", "")
    if not html_payload:
        return jsonify({"reply": "No recent operation data to send. Please look up an order first.", "type": "error"})

    success, msg = send_erp_email(to_email, subject, body_text, html_payload)
    if success:
        return jsonify({"reply": f"Email sent successfully to {to_email} with PDF attachment!", "type": "email_success"})
    else:
        return jsonify({"reply": f"Error sending email: {msg}", "type": "error"})


@app.route("/api/email-preview")
def api_email_preview():
    """Return the current email HTML preview."""
    return jsonify({
        "html": _last_operation.get("email_html", ""),
        "has_data": _last_operation["type"] is not None,
        "operation_type": _last_operation["type"],
    })


@app.route("/api/download-pdf")
def api_download_pdf():
    """Generate and download a PDF of the last operation data (full tabular)."""
    html_payload = _last_operation.get("pdf_html") or _last_operation.get("email_html", "")
    if not html_payload:
        return jsonify({"error": "No operation data available. Please look up an order first."}), 400

    pdf_bytes = generate_pdf(html_payload)
    if not pdf_bytes:
        return jsonify({"error": "PDF generation failed. xhtml2pdf may not be installed."}), 500

    filename = _get_pdf_filename()
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/auto-email", methods=["POST"])
def api_auto_email():
    """Toggle auto-email after every operation."""
    data = request.get_json(force=True)
    _auto_email["enabled"] = bool(data.get("enabled", False))
    _auto_email["to"] = (data.get("to") or "").strip()
    return jsonify({"ok": True, **_auto_email})


@app.route("/api/auto-email", methods=["GET"])
def api_auto_email_status():
    """Get auto-email config."""
    return jsonify(_auto_email)


@app.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    """Start the recurring email scheduler."""
    data = request.get_json(force=True)
    to_email = (data.get("to_email") or "").strip()
    customer_name = (data.get("customer_name") or "").strip()
    interval_str = (data.get("interval") or "60").strip()

    if not to_email:
        return jsonify({"error": "Recipient email is required."}), 400

    # Parse interval
    mins = 60
    interval_lower = interval_str.lower()
    if "daily" in interval_lower or "day" in interval_lower:
        mins = 1440
    elif "hour" in interval_lower:
        nums = re.findall(r"\d+", interval_str)
        mins = int(nums[0]) * 60 if nums else 60
    elif "min" in interval_lower:
        nums = re.findall(r"\d+", interval_str)
        mins = int(nums[0]) if nums else 60
    else:
        nums = re.findall(r"\d+", interval_str)
        if nums:
            mins = int(nums[0])

    _start_scheduler(mins, customer_name, to_email)
    return jsonify({
        "ok": True,
        "message": f"Scheduler started: every {mins} min(s) → {to_email}",
        **_scheduler,
    })


@app.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    """Stop the recurring email scheduler."""
    _stop_scheduler()
    return jsonify({"ok": True, "message": "Scheduler stopped.", **_scheduler})


@app.route("/api/scheduler/status")
def api_scheduler_status():
    """Get the current scheduler state."""
    return jsonify(_scheduler)


@app.route("/api/voice", methods=["POST"])
def api_voice():
    """Server-side voice recognition using Vosk (fallback when browser Speech API unavailable)."""
    if not VOSK_AVAILABLE:
        return jsonify({"text": "", "error": "Voice packages not installed. Use browser microphone instead."})
    try:
        text = recognize_speech(VOICE_DURATION)
        if text:
            return jsonify({"text": text})
        return jsonify({"text": "", "error": "No speech detected. Try again."})
    except Exception as e:
        return jsonify({"text": "", "error": f"Voice error: {e}"})


@app.route("/api/speak", methods=["POST"])
def api_speak():
    """Server-side TTS using pyttsx3 (optional)."""
    if not PYTTSX3_AVAILABLE:
        return jsonify({"ok": False, "error": "pyttsx3 not installed."})
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "No text provided."})
    t = threading.Thread(target=speak, args=(text,), daemon=True)
    t.start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Sales Order Chatbot running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)