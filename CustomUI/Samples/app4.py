"""
Sales Order Chatbot — Flask backend with custom UI.
Calls Oracle EBS REST API and Direct Database Queries.
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
import oracledb

# ── Optional packages ────────────────────────────
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

# ── Suppress InsecureRequestWarning ───────────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Database & API Configuration ──────────────────
# Ensure this matches your instantclient path
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

DB_USER, DB_PASSWORD = "apps", "apps"
DB_DSN = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

BASE_URL = "https://cendb.ad.centroid.com:4463"
GET_ORDER_URL = f"{BASE_URL}/webservices/rest/sales_order/GET_ORDER/"
PROCESS_ORDER_URL = f"{BASE_URL}/webservices/rest/sales_order/PROCESS_ORDER/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
ORG_ID = "204"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

GITHUB_TOKEN = "REDACTED_SECRET"
GITHUB_MODEL = "gpt-4o"

# ── Database Connection Helpers ───────────────────
def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)

def execute_query(sql: str, params: dict) -> list:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0].upper() for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]

def get_order_details_by_customer(p_customer_name: str = None) -> list:
    """
    Direct Database Query using NVL to fetch either a specific customer 
    or ALL customers (if p_customer_name is None) for the last 3 years.
    """
    sql = """
        SELECT
            HP.PARTY_ID, 
            HP.PARTY_NAME AS CUSTOMER_NAME, 
            TO_CHAR(SYSDATE, 'DD-MON-YYYY') AS REPORT_DATE, 
            OOHA.SOLD_TO_ORG_ID AS SOLD_TO_PARTY_ID, 
            OOHA.INVOICE_TO_ORG_ID AS BILL_TO_CUSTOMER_ID, 
            OOHA.ORDER_NUMBER, 
            TO_CHAR(OOHA.ORDERED_DATE, 'DD-MON-YYYY') AS ORDER_DATE, 
            WDD.RELEASED_STATUS, 
            OOLA.LINE_NUMBER, 
            MSI.SEGMENT1 AS ITEM_NUMBER, 
            OOLA.ORDER_QUANTITY_UOM AS ORDERED_UOM, 
            OOLA.ORDERED_QUANTITY AS ORDERED_QTY, 
            DECODE(OOLA.CANCELLED_FLAG, 'Y', 'Y', 'N') AS ORDER_HOLD_FLAG,
            OOLA.UNIT_LIST_PRICE, 
            OOLA.UNIT_SELLING_PRICE,
            OOHA.FLOW_STATUS_CODE AS HEADER_STATUS,
            OOLA.FLOW_STATUS_CODE AS LINE_STATUS, 
            OOHA.CUST_PO_NUMBER AS "PO_NUMBER",
            OOLA.CUST_PO_NUMBER AS "PO_LINE",
            'PO_REFERENCE' AS "REF_TYPE",
            (
                SELECT NVL(SUM(APS.AMOUNT_DUE_REMAINING), 0)
                FROM AR_PAYMENT_SCHEDULES_ALL APS, RA_CUSTOMER_TRX_ALL RCTA 
                WHERE APS.CUSTOMER_TRX_ID = RCTA.CUSTOMER_TRX_ID 
                AND RCTA.INTERFACE_HEADER_ATTRIBUTE1 = TO_CHAR(OOHA.ORDER_NUMBER) 
            ) AS INVOICE_BALANCE, 
            TO_CHAR(NVL(OOLA.SCHEDULE_SHIP_DATE, OOLA.REQUEST_DATE), 'DD-MON-YYYY') AS SCHEDULE_SHIP_DATE,
            TO_CHAR(OOLA.ACTUAL_SHIPMENT_DATE, 'DD-MON-YYYY') AS ACTUAL_SHIP_DATE, 
            DECODE(TRUNC(OOLA.SCHEDULE_SHIP_DATE), TRUNC(SYSDATE), 1, 0) AS TODAY_ARRIVAL_QTY,
            DECODE(WDD.RELEASED_STATUS, 'B', 1, 0) AS BACKORDER_FLAG,
            (OOLA.ORDERED_QUANTITY * OOLA.UNIT_SELLING_PRICE) AS LINE_PRICE,
            (
                SELECT NVL(SUM(OPA.ADJUSTED_AMOUNT), 0)
                FROM OE_PRICE_ADJUSTMENTS OPA  
                WHERE OPA.LINE_ID = OOLA.LINE_ID 
                AND OPA.LIST_LINE_TYPE_CODE = 'DIS' 
            ) AS ADD_DISC, 
            (
                SELECT NVL(SUM(OPA.ADJUSTED_AMOUNT), 0)
                FROM OE_PRICE_ADJUSTMENTS OPA  
                WHERE OPA.LINE_ID = OOLA.LINE_ID  
                AND OPA.LIST_LINE_TYPE_CODE = 'DIS' 
            ) AS CASH_DISC,  
            (
                SELECT NAME
                FROM OE_TRANSACTION_TYPES_TL  
                WHERE TRANSACTION_TYPE_ID = OOHA.ORDER_TYPE_ID  
                AND LANGUAGE = 'US' 
            ) AS ORDER_TYPE,  
            OOLA.SHIPPING_METHOD_CODE AS SHIPMENT_MODE,  
            (CASE
                WHEN OOLA.SCHEDULE_SHIP_DATE IS NOT NULL  
                AND TRUNC(OOLA.SCHEDULE_SHIP_DATE) < TRUNC(NVL(OOLA.ACTUAL_SHIPMENT_DATE, SYSDATE)) 
                THEN 1 ELSE 0 END
            ) AS DELAYED_ORDER_FLAG, 
            (CASE
                WHEN OOLA.ACTUAL_SHIPMENT_DATE IS NOT NULL  
                AND TRUNC(OOLA.SCHEDULE_SHIP_DATE) < TRUNC(SYSDATE) 
                AND WDD.RELEASED_STATUS = 'C'
                THEN 1 ELSE 0 END 
            ) AS IN_TRANSIT_ORDER_FLAG, 
            (
                SELECT HCP.EMAIL_ADDRESS
                FROM HZ_CONTACT_POINTS HCP
                WHERE HCP.OWNER_TABLE_NAME = 'HZ_PARTIES'
                AND HCP.OWNER_TABLE_ID = HP.PARTY_ID
                AND HCP.STATUS = 'A'
                AND HCP.CONTACT_POINT_TYPE = 'EMAIL'
                AND ROWNUM = 1
            ) AS EMAIL 
        FROM
            OE_ORDER_HEADERS_ALL OOHA, 
            OE_ORDER_LINES_ALL OOLA,
            MTL_SYSTEM_ITEMS_B MSI, 
            WSH_DELIVERY_DETAILS WDD, 
            HZ_CUST_ACCOUNTS HCAA, 
            HZ_PARTIES HP 
        WHERE
            OOHA.HEADER_ID = OOLA.HEADER_ID 
        AND MSI.INVENTORY_ITEM_ID = OOLA.INVENTORY_ITEM_ID 
        AND MSI.ORGANIZATION_ID = OOLA.SHIP_FROM_ORG_ID 
        AND OOLA.LINE_ID = WDD.SOURCE_LINE_ID(+)
        AND WDD.SOURCE_CODE(+) = 'OE' 
        AND HCAA.CUST_ACCOUNT_ID = OOHA.SOLD_TO_ORG_ID 
        AND HP.PARTY_ID = HCAA.PARTY_ID 
        AND UPPER(HP.PARTY_NAME) = NVL(UPPER(:p_customer_name), UPPER(HP.PARTY_NAME))
        AND OOHA.ORDERED_DATE >= ADD_MONTHS(SYSDATE, -36)
        ORDER BY OOHA.ORDER_NUMBER, OOLA.LINE_NUMBER
    """
    params = {"p_customer_name": p_customer_name} if p_customer_name else {"p_customer_name": None}
    return execute_query(sql, params)


# ── AI Summary & Voice Helpers ───────────────────
def generate_ai_summary(operation_type: str, data: dict) -> str:
    if not OPENAI_AVAILABLE:
        return ""
    try:
        client = OpenAI(base_url="https://models.inference.ai.azure.com", api_key=GITHUB_TOKEN)
        today = datetime.datetime.now().strftime("%B %d, %Y")
        data_json = json.dumps(data, indent=2, default=str)[:3000]
        system_prompt = (
            f"You are an ERP Sales Order Analyst. Today is {today}. "
            "Write a concise executive summary (3-5 sentences) of this operation. "
            "Do NOT use markdown formatting — plain text only."
        )
        user_prompt = f"Summarize this ERP operation result:\n{data_json}"
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.3, max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"AI summary error: {e}")
        return ""


# ── API Calls & Adapters ──────────────────────────
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def _build_session():
    s = requests.Session()
    s.mount("https://", ForceTLSAdapter())
    s.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    s.verify = False
    return s

def get_order(order_number: int) -> dict:
    payload = {"PROCESS_ORDER_Input": {"RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": ORG_ID}, "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T", "P_ORDER_NUMBER": order_number}}}
    resp = _build_session().post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
    if resp.status_code in (200, 201, 204):
        try: return resp.json()
        except: return {"raw": resp.text}
    resp.raise_for_status()


# ── Parsers ───────────────────────────────────────
def parse_order_response(data: dict) -> dict:
    try:
        output = data.get("OutputParameters", data)
        header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
        header_val = output.get("X_HEADER_VAL_REC", output.get("HEADER_VAL_REC", {}))
        lines_raw = output.get("X_LINE_TBL", output.get("LINE_TBL", {}))
        
        items = lines_raw.get("X_LINE_TBL_ITEM", lines_raw.get("LINE_TBL_ITEM", [])) if isinstance(lines_raw, dict) else (lines_raw if isinstance(lines_raw, list) else [])
        if isinstance(items, dict): items = [items]
        
        lines = []
        for item in items:
            lines.append({
                "Line": item.get("LINE_NUMBER", ""),
                "Item": item.get("ORDERED_ITEM", ""),
                "Qty": item.get("ORDERED_QUANTITY", ""),
                "Status": item.get("FLOW_STATUS_CODE", ""),
            })

        cname = header_val.get("SOLD_TO_ORG", "") or header.get("SOLD_TO_ORG", header.get("SOLD_TO_ORG_ID", ""))
        return {
            "order_number": header.get("ORDER_NUMBER", ""),
            "status": header.get("FLOW_STATUS_CODE", ""),
            "customer_name": cname,
            "lines": lines,
            "header_details": header,
        }
    except Exception as e:
        return {"error": f"Failed to parse: {e}", "raw": data}


# ── Global State & Caching ────────────────────────
_last_operation = {
    "type": None,
    "data": None,
    "ai_summary": "",
    "pdf_html": ""
}

# ── Auto-email Loop State ─────────────────────────
_auto_loop = {
    "active": False,
    "to_email": "",
    "current_customer": "",
    "total_customers": 0,
    "processed": 0,
    "last_status": None,
    "started_at": None,
}
_stop_loop_event = threading.Event()
_loop_thread = None


def get_all_customer_names() -> list:
    """Fetch distinct customer names from HZ_PARTIES that have sales orders."""
    sql = """
        SELECT DISTINCT HP.PARTY_NAME AS CUSTOMER_NAME
        FROM HZ_PARTIES HP
        JOIN HZ_CUST_ACCOUNTS HCA ON HCA.PARTY_ID = HP.PARTY_ID
        JOIN OE_ORDER_HEADERS_ALL OOHA ON OOHA.SOLD_TO_ORG_ID = HCA.CUST_ACCOUNT_ID
        WHERE OOHA.ORG_ID = :org_id
        AND OOHA.ORDERED_DATE >= ADD_MONTHS(SYSDATE, -36)
        AND HP.PARTY_NAME IS NOT NULL
        ORDER BY HP.PARTY_NAME
    """
    rows = execute_query(sql, {"org_id": int(ORG_ID)})
    return [r["CUSTOMER_NAME"] for r in rows]


def _generate_customer_email_html(cust_name: str, rows: list) -> str:
    """Build email HTML report for a specific customer's orders."""
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    th = "border: 1px solid #cbd5e1; padding: 8px; text-align: left; font-weight: bold; background: #1a365d; color: white;"
    td = "border: 1px solid #cbd5e1; padding: 6px 8px;"

    columns = [
        ("Order #", "ORDER_NUMBER"),
        ("Order Date", "ORDER_DATE"),
        ("Item", "ITEM_NUMBER"),
        ("Qty", "ORDERED_QTY"),
        ("Line Price", "LINE_PRICE"),
        ("Header Status", "HEADER_STATUS"),
        ("Line Status", "LINE_STATUS"),
        ("Ship Date", "SCHEDULE_SHIP_DATE"),
        ("Invoice Bal", "INVOICE_BALANCE"),
    ]

    table = "<table style='border-collapse: collapse; width: 100%; font-size: 12px;'><tr>"
    for label, _ in columns:
        table += f"<th style='{th}'>{label}</th>"
    table += "</tr>"
    for r in rows[:100]:
        table += "<tr>"
        for _, key in columns:
            val = r.get(key, "")
            if val is None:
                val = ""
            if key in ("LINE_PRICE", "INVOICE_BALANCE") and val and str(val).replace(".", "", 1).replace("-", "", 1).isdigit():
                val = f"${float(val):,.2f}"
            table += f"<td style='{td}'>{val}</td>"
        table += "</tr>"
    table += "</table>"
    if len(rows) > 100:
        table += f"<p style='font-size:11px;color:#64748b;'>Showing 100 of {len(rows)} records.</p>"

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
        <h2 style="color: #1a365d;">Sales Order Report — {cust_name}</h2>
        <p style="font-size: 13px; color: #64748b;">Report Date: {report_date} | Records: {len(rows)}</p>
        <hr style="border: 0.5px solid #e2e8f0;">
        <h3 style="color: #334155;">Order Details</h3>
        {table}
        <hr style="border: 0.5px solid #e2e8f0; margin-top: 20px;">
        <p style="font-size: 11px; color: #94a3b8;">
            This email was sent automatically by the Sales Order Assistant.<br>
            Support: erp.support@centroid.com
        </p>
    </body>
    </html>
    """


def send_erp_email(to_email: str, subject: str, html_content: str) -> tuple:
    """Send an HTML email via Gmail SMTP."""
    sender = "erp.assistant@yourdomain.com"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    msg.attach(MIMEText(f"Please view this email in an HTML-capable client.", "plain"))
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


def _auto_loop_worker(to_email: str):
    """Background thread: iterate all customers, send email for each, loop until stopped."""
    _stop_loop_event.clear()
    _auto_loop["active"] = True
    _auto_loop["to_email"] = to_email
    _auto_loop["started_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    while not _stop_loop_event.is_set():
        try:
            # Fetch fresh list of customers each iteration
            customers = get_all_customer_names()
            _auto_loop["total_customers"] = len(customers)
            _auto_loop["processed"] = 0
            print(f"📧 Auto-loop: Starting cycle with {len(customers)} customers → {to_email}")

            for cust_name in customers:
                if _stop_loop_event.is_set():
                    break

                _auto_loop["current_customer"] = cust_name
                try:
                    rows = get_order_details_by_customer(cust_name)
                    if rows:
                        html = _generate_customer_email_html(cust_name, rows)
                        subject = f"Sales Order Report: {cust_name}"
                        success, msg = send_erp_email(to_email, subject, html)
                        _auto_loop["last_status"] = f"✅ {cust_name}: {msg}" if success else f"❌ {cust_name}: {msg}"
                        print(f"  {'✅' if success else '❌'} {cust_name} ({len(rows)} rows) → {msg}")
                    else:
                        _auto_loop["last_status"] = f"⏭️ {cust_name}: No orders, skipped"
                        print(f"  ⏭️ {cust_name}: No orders, skipped")
                except Exception as e:
                    _auto_loop["last_status"] = f"❌ {cust_name}: Error - {e}"
                    print(f"  ❌ {cust_name}: {e}")

                _auto_loop["processed"] += 1

                # Small delay between emails to avoid SMTP throttling
                if not _stop_loop_event.is_set():
                    _stop_loop_event.wait(timeout=5)

            # After completing all customers, wait before next cycle
            if not _stop_loop_event.is_set():
                _auto_loop["last_status"] = f"🔄 Cycle complete ({len(customers)} customers). Waiting 60s before next cycle..."
                print(f"📧 Auto-loop: Cycle complete. Waiting 60s...")
                _stop_loop_event.wait(timeout=60)

        except Exception as e:
            _auto_loop["last_status"] = f"❌ Loop error: {e}"
            print(f"❌ Auto-loop error: {e}")
            if not _stop_loop_event.is_set():
                _stop_loop_event.wait(timeout=30)

    _auto_loop["active"] = False
    _auto_loop["current_customer"] = ""
    print("📧 Auto-loop: Stopped.")


def _start_auto_loop(to_email: str):
    """Start the auto email loop in a background thread."""
    global _loop_thread
    _stop_auto_loop()
    _loop_thread = threading.Thread(target=_auto_loop_worker, args=(to_email,), daemon=True)
    _loop_thread.start()


def _stop_auto_loop():
    """Stop the auto email loop."""
    global _loop_thread
    _stop_loop_event.set()
    _auto_loop["active"] = False
    if _loop_thread and _loop_thread.is_alive():
        _loop_thread.join(timeout=3)
    _loop_thread = None
    _stop_loop_event.clear()

# ── HTML & PDF Generation ─────────────────────────
def _generate_full_pdf_html(op_type: str, parsed: dict, ai_summary: str = "") -> str:
    """
    Generates a clean, corporate PDF report layout containing all records.
    Designed to handle 1000+ records efficiently using xhtml2pdf constraints.
    Does NOT match the email layout.
    """
    report_date = datetime.datetime.now().strftime("%B %d, %Y")
    
    if op_type == "customer_orders":
        customer_name = parsed.get("customer_name", "All Customers")
        table_data = parsed.get("rows", [])
        
        columns_to_display = [
            ("Customer Name", "CUSTOMER_NAME"),
            ("Order Number", "ORDER_NUMBER"),
            ("Order Date", "ORDER_DATE"),
            ("Item Number", "ITEM_NUMBER"),
            ("Ordered Qty", "ORDERED_QTY"),
            ("Line Status", "LINE_STATUS"),
            ("Ship Date", "SCHEDULE_SHIP_DATE"),
            ("Line Price", "LINE_PRICE")
        ]
        
    elif op_type == "order":
        customer_name = parsed.get("customer_name", "Unknown")
        table_data = parsed.get("lines", [])
        columns_to_display = [
            ("Line Number", "Line"),
            ("Ordered Item", "Item"),
            ("Quantity", "Qty"),
            ("Line Status", "Status")
        ]
    else:
        return "<html><body><h2>No data available for report.</h2></body></html>"

    if not table_data:
        return "<html><body><h2>No data available for report.</h2></body></html>"

    th_html = ""
    actual_keys = []
    
    if isinstance(table_data[0], dict):
        for label, key in columns_to_display:
            if key in table_data[0]:
                actual_keys.append(key)
                th_html += f"<th style='background-color: #1a365d; color: white; padding: 6px 8px; border: 1px solid #cbd5e1; text-align: left; font-weight: bold;'>{label}</th>"
        
        if not actual_keys:
            actual_keys = list(table_data[0].keys())
            th_html = "".join(f"<th style='background-color: #1a365d; color: white; padding: 6px 8px; border: 1px solid #cbd5e1; text-align: left; font-weight: bold;'>{k.replace('_', ' ').title()}</th>" for k in actual_keys)
            
        rows_html = ""
        for i, row in enumerate(table_data):
            bg_color = "#f8fafc" if i % 2 == 0 else "#ffffff"
            tr = f"<tr style='background-color: {bg_color};'>"
            for key in actual_keys:
                val = str(row.get(key, ""))
                if key == "LINE_PRICE" and val.replace('.','',1).lstrip('-').isdigit():
                    val = f"${float(val):,.2f}"
                tr += f"<td style='padding: 6px 8px; border: 1px solid #cbd5e1; color: #334155;'>{val}</td>"
            tr += "</tr>"
            rows_html += tr

    html = f"""
    <html>
    <head>
        <style>
            @page {{
                size: A4 landscape;
                margin: 1.5cm;
                @frame header {{
                    -pdf-frame-content: headerContent;
                    top: 1cm;
                    margin-left: 1.5cm;
                    margin-right: 1.5cm;
                    height: 2cm;
                }}
                @frame footer {{
                    -pdf-frame-content: footerContent;
                    bottom: 1cm;
                    margin-left: 1.5cm;
                    margin-right: 1.5cm;
                    height: 1cm;
                }}
            }}
            body {{ font-family: Helvetica, Arial, sans-serif; font-size: 10px; }}
            table {{ width: 100%; border-collapse: collapse; }}
            .summary-box {{ background-color: #eff6ff; border: 1px solid #bfdbfe; padding: 10px; margin-bottom: 15px; font-size: 11px; }}
        </style>
    </head>
    <body>
        <div id="headerContent">
            <table style="width: 100%; border: none;">
                <tr>
                    <td style="width: 50%; border: none;">
                        <h1 style="color: #1a365d; font-size: 24px; margin: 0;">CENTROID</h1>
                        <p style="color: #64748b; font-size: 10px; margin: 0;">Sales Order Assistant</p>
                    </td>
                    <td style="width: 50%; text-align: right; border: none;">
                        <h2 style="color: #0f172a; font-size: 18px; margin: 0;">Order Details Report</h2>
                        <p style="color: #64748b; font-size: 10px; margin: 0;">Customer: <b>{customer_name}</b><br/>Generated on: {report_date}</p>
                    </td>
                </tr>
            </table>
            <hr style="border: 0.5px solid #1a365d; margin-bottom: 15px;"/>
        </div>

        <div id="footerContent" style="text-align: right; font-size: 9px; color: #94a3b8;">
            <hr style="border: 0.5px solid #e2e8f0; margin-bottom: 5px;"/>
            Page <pdf:pagenumber> of <pdf:pagecount>
        </div>

        {f"<div class='summary-box'><b>AI Summary:</b><br/>{ai_summary}</div>" if ai_summary else ""}

        <table>
            <thead>
                <tr>{th_html}</tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """
    return html

import io
def generate_pdf(html_content: str) -> bytes:
    if not XHTML2PDF_AVAILABLE or not html_content: return b""
    try:
        buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=buffer)
        if pisa_status.err: return b""
        return buffer.getvalue()
    except Exception: return b""


# ── Flask API Definitions ──────────────────────────
app = Flask(__name__, static_folder="static", static_url_path="/static")

@app.route("/")
def index():
    return send_from_directory("static", "index4.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True)
    user_msg = (body.get("message") or "").strip()
    lower = user_msg.lower()

    if not user_msg: return jsonify({"reply": "Please type a message.", "type": "text"})

    # Customer Orders intent logic
    cust_match = re.search(
        r"(?:customer\s+(?:orders?|details?)\s+(?:(?:for|of)\s+)?(.+)|orders?\s+(?:for|of|by)\s+(?:customer\s+)?(.+))",
        lower
    )
    
    if cust_match or "all customers" in lower or "all orders" in lower:
        if "all customers" in lower or "all orders" in lower:
            # Fetch all customer names from HZ_PARTIES first
            try:
                customers = get_all_customer_names()
                all_rows = []
                for cname in customers:
                    cust_rows = get_order_details_by_customer(cname)
                    all_rows.extend(cust_rows)
                parsed = {"rows": all_rows, "count": len(all_rows), "customer_name": "All Customers", "customer_list": customers, "customer_count": len(customers)}
                
                summary = generate_ai_summary("customer_orders", parsed)
                _last_operation["type"] = "customer_orders"
                _last_operation["data"] = parsed
                _last_operation["ai_summary"] = summary
                _last_operation["pdf_html"] = _generate_full_pdf_html("customer_orders", parsed, summary)
                
                return jsonify({"reply": parsed, "type": "customer_orders", "ai_summary": summary})
            except Exception as e:
                return jsonify({"reply": f"DB Error: {e}", "type": "error"})
        else:
            cust_name = (cust_match.group(1) or cust_match.group(2) or "").strip()
            display_name = cust_name.title()

            try:
                rows = get_order_details_by_customer(cust_name)
                parsed = {"rows": rows, "count": len(rows), "customer_name": display_name}
                
                summary = generate_ai_summary("customer_orders", parsed)
                _last_operation["type"] = "customer_orders"
                _last_operation["data"] = parsed
                _last_operation["ai_summary"] = summary
                _last_operation["pdf_html"] = _generate_full_pdf_html("customer_orders", parsed, summary)
                
                return jsonify({"reply": parsed, "type": "customer_orders", "ai_summary": summary})
            except Exception as e:
                return jsonify({"reply": f"DB Error: {e}", "type": "error"})

    # Specific Order lookup logic
    order_match = re.search(r"\b(\d{4,})\b", lower)
    if order_match:
        order_num = int(order_match.group(1))
        try:
            raw = get_order(order_num)
            parsed = parse_order_response(raw)
            summary = generate_ai_summary("order", parsed)
            
            _last_operation["type"] = "order"
            _last_operation["data"] = parsed
            _last_operation["ai_summary"] = summary
            _last_operation["pdf_html"] = _generate_full_pdf_html("order", parsed, summary)
            
            return jsonify({"reply": parsed, "type": "order", "ai_summary": summary})
        except Exception as e:
            return jsonify({"reply": f"API Error: {e}", "type": "error"})

    return jsonify({"reply": "I am the Sales Order Assistant. Ask me for 'Customer orders for ACME' or 'Get order 67965'.", "type": "text"})

@app.route("/api/download-pdf")
def api_download_pdf():
    html_payload = _last_operation.get("pdf_html", "")
    if not html_payload:
        return jsonify({"error": "No operation data available."}), 400

    pdf_bytes = generate_pdf(html_payload)
    if not pdf_bytes:
        return jsonify({"error": "PDF generation failed."}), 500

    op = _last_operation.get("type", "Report")
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=SalesOrder_{op}.pdf"},
    )


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    """Send the last operation's data as an email."""
    body = request.get_json(force=True)
    to_email = (body.get("to_email") or "").strip()
    if not to_email:
        return jsonify({"reply": "Email address is required.", "type": "error"})

    parsed = _last_operation.get("data")
    if not parsed:
        return jsonify({"reply": "No data to send. Look up an order or customer first.", "type": "error"})

    op_type = _last_operation.get("type")
    if op_type == "customer_orders":
        cust_name = parsed.get("customer_name", "Unknown")
        html = _generate_customer_email_html(cust_name, parsed.get("rows", []))
        subject = f"Sales Order Report: {cust_name}"
    else:
        subject = "Sales Order Report"
        html = _last_operation.get("pdf_html", "<p>No data available.</p>")

    success, msg = send_erp_email(to_email, subject, html)
    if success:
        return jsonify({"reply": f"✅ Email sent to {to_email}!", "type": "email_success"})
    else:
        return jsonify({"reply": f"❌ Email failed: {msg}", "type": "error"})


@app.route("/api/auto-loop/start", methods=["POST"])
def api_auto_loop_start():
    """Start auto email loop: fetch all customers, send email for each, repeat."""
    body = request.get_json(force=True)
    to_email = (body.get("to_email") or "").strip()
    if not to_email:
        return jsonify({"error": "Recipient email is required."}), 400

    _start_auto_loop(to_email)
    return jsonify({"ok": True, "message": f"Auto-loop started → {to_email}", **_auto_loop})


@app.route("/api/auto-loop/stop", methods=["POST"])
def api_auto_loop_stop():
    """Stop the auto email loop."""
    _stop_auto_loop()
    return jsonify({"ok": True, "message": "Auto-loop stopped.", **_auto_loop})


@app.route("/api/auto-loop/status")
def api_auto_loop_status():
    """Get auto-loop status."""
    return jsonify(_auto_loop)

if __name__ == "__main__":
    print("Sales Order Chatbot running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)