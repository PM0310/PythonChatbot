import os
import sys
import json
import datetime
import argparse
import requests
import ssl
import urllib3
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
import oracledb
from openai import OpenAI

# --------------------------------------------------
# Voice Dependencies Initialization
# --------------------------------------------------
try:
    import pyttsx3
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    from word2number import w2n
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

# --------------------------------------------------
# Configuration
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

MODEL_PATH = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
DURATION_SECONDS = 6
MODE = "text"

# Cached singletons for voice engine and Vosk model
_tts_engine = None
_vosk_model = None

# --------------------------------------------------
# Voice / Output Abstraction 
# --------------------------------------------------
def _get_tts_engine():
    global _tts_engine
    if _tts_engine is None:
        _tts_engine = pyttsx3.init()
    return _tts_engine

def speak(text: str):
    if VOICE_AVAILABLE and MODE == "voice":
        try:
            engine = _get_tts_engine()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"  [TTS Error: {e}]")

def load_vosk_model():
    global _vosk_model
    if _vosk_model is not None:
        return _vosk_model
    if not os.path.isdir(MODEL_PATH):
        raise FileNotFoundError(f"Vosk model directory not found: {MODEL_PATH}")
    _vosk_model = Model(MODEL_PATH)
    return _vosk_model

def recognize_speech_vosk(duration=DURATION_SECONDS):
    if not VOICE_AVAILABLE:
        return ""
    try:
        model = load_vosk_model()
        rec = KaldiRecognizer(model, SAMPLE_RATE)
        print("  🎤 Listening...", flush=True)
        data = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        sd.wait()
        if not rec.AcceptWaveform(data.tobytes()):
            res = json.loads(rec.FinalResult())
        else:
            res = json.loads(rec.Result())
        text = res.get("text", "").strip()
        if not text:
            print("  (No speech detected, please try again)")
        return text
    except Exception as e:
        print(f"  [Microphone error: {e}]")
        return ""

def print_msg(text: str, speak_text: str = None):
    """Prints to console and speaks if voice mode is active."""
    print(text)
    if MODE == "voice":
        speak(speak_text if speak_text is not None else text.strip(" :[]\n-"))

def speak_list(items: list, format_fn):
    """Prints and speaks a numbered list. format_fn(item) returns (display_text, voice_text)."""
    for i, item in enumerate(items, 1):
        display, voice = format_fn(item)
        print(f"    {i}. {display}")
    if MODE == "voice":
        summary_parts = []
        for i, item in enumerate(items, 1):
            _, voice = format_fn(item)
            summary_parts.append(f"Option {i}, {voice}")
        speak(". ".join(summary_parts))

def ask_msg(prompt_text: str, speak_text: str = None) -> str:
    """Takes input via keyboard or voice depending on mode."""
    if MODE == "voice":
        speak(speak_text if speak_text is not None else prompt_text.strip(" :[]\n-"))
        print(prompt_text, end="", flush=True)
        val = recognize_speech_vosk()
        print(" " + val)
        return val
    else:
        return input(prompt_text).strip()

def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)

class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

def parse_numeric_value(val, allow_float=False):
    if val is None: return None
    val = str(val).strip()
    try: return float(val) if allow_float else int(val)
    except ValueError: pass

    if VOICE_AVAILABLE:
        try:
            return int(w2n.word_to_num(val))
        except Exception:
            pass

    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try: return float(digits) if allow_float else int(digits)
        except ValueError: pass
    return None

# --------------------------------------------------
# AI Intent Extraction
# --------------------------------------------------
def github_extract_intent(user_input: str) -> dict:
    client = OpenAI(
        base_url="https://models.inference.ai.azure.com",
        api_key=GITHUB_TOKEN,
    )
    current_year = datetime.date.today().year
    current_date = datetime.date.today().strftime("%B %d, %Y")

    system = (
        f"You are an ERP Assistant. Today is {current_date} (Year: {current_year}). Extract user intent into JSON.\n"
        "FIELDS:\n"
        "- action: 'create' or 'get' or 'unknown'\n"
        "- date_range: 'this_month', 'this_week', 'last_30_days', or null\n"
        "- year: integer (e.g., 2000, 2024) or null\n"
        "- status: string (e.g., 'BOOKED', 'ENTERED', 'CANCELLED') or null\n"
        "- order_number: integer or null\n"
        "- cpo: string or null\n"
        "- customer_name: string or null\n"
        "- ordered_item: string or null\n"
        "- quantity: number or null\n"
        "\n"
        "LOGIC RULES:\n"
        "1. If user mentions a time period (last 30 days, etc.), set date_range and action='get'.\n"
        "2. If user mentions relative years like 'last year', calculate the integer year based on the current year.\n"
        "3. If user mentions a specific year or a status, set them and action='get'.\n"
        "4. If user provides an order number, set action='get'.\n"
        "5. If user provides a customer name, extract it into 'customer_name'.\n"
        "6. Return ONLY raw JSON."
    )
    try:
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_input}],
            temperature=0.0,
        )
        clean = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        return {"action": "unknown"}

def github_clarify(conversation_history: list, missing_fields: list) -> str:
    system = (
        "You are a friendly sales order assistant helping a user create or retrieve "
        "a sales order in an ERP system. Ask a short, natural question to collect "
        "the following missing information. Be concise and conversational.\n"
        f"Missing fields: {', '.join(missing_fields)}"
    )
    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=GITHUB_TOKEN,
        )
        response = client.chat.completions.create(
            model=GITHUB_MODEL,
            messages=[{"role": "system", "content": system}] + conversation_history,
            max_tokens=128,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return f"I still need the following information: {', '.join(missing_fields)}."

# --------------------------------------------------
# DB Core Functions 
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

def get_line_type_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT ott.TRANSACTION_TYPE_ID, otl.NAME
                  FROM OE_TRANSACTION_TYPES_ALL ott
                  JOIN OE_TRANSACTION_TYPES_TL otl ON otl.TRANSACTION_TYPE_ID = ott.TRANSACTION_TYPE_ID
                 WHERE ott.TRANSACTION_TYPE_CODE = 'LINE'
                   AND otl.LANGUAGE = USERENV('LANG')
                   AND NVL(ott.END_DATE_ACTIVE, SYSDATE + 1) > SYSDATE
                   AND ott.ORG_ID = :org_id
                 ORDER BY otl.NAME
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"line_type_id": int(r[0]), "line_type_name": r[1] or ""} for r in rows]

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
                SELECT DISTINCT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME AS customer_name, hca.ACCOUNT_NUMBER
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
                SELECT DISTINCT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME AS customer_name, hca.ACCOUNT_NUMBER
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
        SELECT hcsu.SITE_USE_ID, hcsu.LOCATION, hl.ADDRESS1, hl.CITY, hl.STATE, hl.POSTAL_CODE,
               hca.CUST_ACCOUNT_ID, hp.PARTY_NAME
          FROM HZ_CUST_ACCT_SITES_ALL hcas
          JOIN HZ_CUST_SITE_USES_ALL  hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
          JOIN HZ_PARTY_SITES         hps  ON hps.PARTY_SITE_ID      = hcas.PARTY_SITE_ID
          JOIN HZ_LOCATIONS           hl   ON hl.LOCATION_ID         = hps.LOCATION_ID
          JOIN HZ_CUST_ACCOUNTS       hca  ON hca.CUST_ACCOUNT_ID    = hcas.CUST_ACCOUNT_ID
          JOIN HZ_PARTIES             hp   ON hp.PARTY_ID            = hca.PARTY_ID
         WHERE hcas.CUST_ACCOUNT_ID = :cust_account_id
           AND hcas.ORG_ID          = :org_id
           AND hcsu.SITE_USE_CODE   = 'SHIP_TO'
           AND hcsu.STATUS          = 'A'
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

def resolve_customer(customer_name: str) -> dict | None:
    offset = 0
    selected_customer = None
    while True:
        customers = get_customer_by_name_rows(customer_name, offset=offset)
        if not customers:
            if offset == 0:
                print_msg(f"\n  No customers found matching '{customer_name}'.")
                return None
            else:
                print_msg("\n  No more customers found.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print_msg(f"\n  Customers matching '{customer_name}':", f"Found {len(customers)} customers matching {customer_name}. Please choose.")
        speak_list(customers, lambda c: (
            f"{c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})",
            c['customer_name']
        ))

        has_more = len(customers) == MAX_CHOICES
        nav_options = []
        if has_more: nav_options.append("N = Next page")
        if offset > 0: nav_options.append("P = Previous page")
        nav_options.append("0 = Cancel")
        
        choice = ask_msg(f"  Enter choice [{', '.join(nav_options)}]: ", "Say a number, next, previous, or cancel").strip().lower()

        if choice in ("0", "cancel", "zero"): return None
        elif choice in ("n", "next") and has_more: offset += MAX_CHOICES; continue
        elif choice in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        else:
            idx = parse_numeric_value(choice)
            if idx and 1 <= idx <= len(customers):
                selected_customer = customers[idx - 1]
                break
            else:
                print_msg("  Invalid selection, please try again.")

    return _resolve_customer_sites(selected_customer)

def resolve_customer_by_item(inventory_item_id: int, item_segment1: str) -> dict | None:
    offset = 0
    selected_customer = None
    print_msg(f"\n  🔍  No customer specified. Suggesting customers based on item '{item_segment1}'...")

    while True:
        customers = get_customers_by_inventory_item_rows(inventory_item_id, offset=offset)
        if not customers:
            if offset == 0:
                print_msg(f"  No customers found for item '{item_segment1}'. Please enter a customer name manually.")
                manual_name = ask_msg("  Enter customer name to search: ")
                if not manual_name: return None
                return resolve_customer(manual_name)
            else:
                print_msg("  No more customers.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print_msg(f"\n  Customers who have ordered '{item_segment1}' (or all active customers):",
                  "Here are the customers. Please choose.")
        speak_list(customers, lambda c: (
            f"{c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})",
            c['customer_name']
        ))

        has_more = len(customers) == MAX_CHOICES
        nav_options = []
        if has_more: nav_options.append("N = Next page")
        if offset > 0: nav_options.append("P = Previous page")
        nav_options.append("S = Search by name instead")
        nav_options.append("0 = Cancel")
        
        choice = ask_msg(f"  Enter choice [{', '.join(nav_options)}]: ", "Say a number, next, previous, search, or cancel").strip().lower()

        if choice in ("0", "cancel", "zero"): return None
        elif choice in ("s", "search"):
            manual_name = ask_msg("  Enter customer name to search: ")
            if not manual_name: return None
            return resolve_customer(manual_name)
        elif choice in ("n", "next") and has_more: offset += MAX_CHOICES; continue
        elif choice in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        else:
            idx = parse_numeric_value(choice)
            if idx and 1 <= idx <= len(customers):
                selected_customer = customers[idx - 1]
                break
            else:
                print_msg("  Invalid selection, please try again.")

    return _resolve_customer_sites(selected_customer)

def _resolve_customer_sites(selected_customer: dict) -> dict | None:
    sites = get_customer_sites_by_account(selected_customer["cust_account_id"])
    if not sites:
        print_msg(f"\n  No active SHIP_TO sites found for '{selected_customer['customer_name']}'.")
        return None

    if len(sites) == 1:
        site = sites[0]
        print_msg(f"\n  Auto-selected ship-to site: {site['location']} — {site['address']}")
        return {"sold_to_org_id": site["sold_to_org_id"], "ship_to_org_id": site["ship_to_org_id"], "customer_name": site["customer_name"]}

    print_msg(f"\n  '{selected_customer['customer_name']}' has {len(sites)} ship-to sites. Please select one:")
    speak_list(sites, lambda s: (
        f"[{s['location']}] {s['address']}  (Site ID: {s['ship_to_org_id']})",
        f"{s['location']}, {s['address']}"
    ))
    
    while True:
        choice = ask_msg("  Enter choice (0 = Cancel): ", "Please say the site number, or zero to cancel").strip().lower()
        if choice in ("0", "cancel", "zero"): return None
        idx = parse_numeric_value(choice)
        if idx and 1 <= idx <= len(sites):
            site = sites[idx - 1]
            return {"sold_to_org_id": site["sold_to_org_id"], "ship_to_org_id": site["ship_to_org_id"], "customer_name": site["customer_name"]}
        print_msg("  Invalid selection, please try again.")

def get_orders_advanced(range_type=None, year=None, status=None):
    bind_vars = {"org": ORG_ID}

    if year:
        bind_vars["yr"] = int(year)
        date_clause = "EXTRACT(YEAR FROM CREATION_DATE) = :yr"
    elif range_type:
        date_map = {"this_month": "TRUNC(SYSDATE, 'MM')", "this_week": "TRUNC(SYSDATE, 'IW')", "last_30_days": "SYSDATE - 30"}
        date_clause = f"CREATION_DATE >= {date_map.get(range_type, 'SYSDATE - 7')}"
    else:
        date_clause = "1=1"

    if status:
        bind_vars["status_filter"] = f"%{status.upper()}%"
        status_clause = "UPPER(FLOW_STATUS_CODE) LIKE :status_filter"
    else:
        status_clause = "1=1"

    sql_main  = f"SELECT ORDER_NUMBER, FLOW_STATUS_CODE, CREATION_DATE FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org ORDER BY CREATION_DATE DESC"
    sql_count = f"SELECT COUNT(*) FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org"

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql_count, bind_vars)
            total_count = cur.fetchone()[0]
            cur.execute(sql_main, bind_vars)
            rows = cur.fetchall()
            return {"total_count": total_count, "rows": rows}
    except Exception as e:
        raise Exception(f"SQL Error: {e}")

# --------------------------------------------------
# REST Payload Generation
# --------------------------------------------------
def create_payload(p_cust_po, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price,
                   p_payment_term_id, p_price_list_id, p_salesrep_id, p_line_type_id,
                   p_ship_to_org, p_sold_to_org, p_operating_unit):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT",
                           "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": "204"},
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG": "N", "CUST_PO_NUMBER": p_cust_po, "ORDER_TYPE_ID": ORDER_TYPE_ID, "ORG_ID": ORG_ID,
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "SALESREP_ID": p_salesrep_id,
                    "SHIP_TO_ORG_ID": p_ship_to_org, "SOLD_TO_ORG_ID": p_sold_to_org,
                    "TRANSACTIONAL_CURR_CODE": "USD", "OPERATION": "CREATE"
                },
                "P_LINE_TBL": {"P_LINE_TBL_ITEM": {
                    "INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty,
                    "LINE_TYPE_ID": p_line_type_id,
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id,
                    "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                }},
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": p_operating_unit, "P_DEBUG_LEVEL": 10
            }
        }
    }

def send_order(payload):
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=60)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except Exception: return response.text
    response.raise_for_status()

def get_order(order_number: int) -> dict:
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)},
            "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T", "P_ORDER_NUMBER": order_number}
        }
    }
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=60)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except Exception: return response.text
    response.raise_for_status()


def create_add_line_payload(p_header_id, p_item_id, p_ordered_item, p_qty,
                            p_price, p_selling_price, p_payment_term_id, p_price_list_id,
                            p_line_type_id=None):
    line_item = {
        "HEADER_ID":          p_header_id,
        "INVENTORY_ITEM_ID":  p_item_id,
        "ORDERED_ITEM":       p_ordered_item,
        "ORDERED_QUANTITY":   p_qty,
        "PAYMENT_TERM_ID":    p_payment_term_id,
        "PRICE_LIST_ID":      p_price_list_id,
        "UNIT_LIST_PRICE":    p_price,
        "UNIT_SELLING_PRICE": p_selling_price,
        "OPERATION":          "CREATE"
    }
    if p_line_type_id is not None:
        line_item["LINE_TYPE_ID"] = p_line_type_id
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT",
                "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "HEADER_ID": p_header_id, "ORG_ID": ORG_ID, "OPERATION": "UPDATE"
                },
                "P_LINE_TBL": {"P_LINE_TBL_ITEM": line_item},
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": OPERATING_UNIT, "P_DEBUG_LEVEL": 10
            }
        }
    }


# --------------------------------------------------
# Add Another Line Flow
# --------------------------------------------------
def collect_line_details() -> dict | None:
    item_input = ask_msg("\n  Enter item name/prefix to search (or 0 to cancel): ",
                         "Say the item name or prefix to search, or zero to cancel.")
    if item_input in ("0", "zero", "cancel"):
        return None

    offset = 0
    selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            print_msg("  No items found." if offset == 0 else "  No more items.")
            return None
        print_msg(f"\n  Items matching '{item_input}':", "Items found. Please choose.")
        speak_list(items, lambda it: (
            f"[{it['segment1']}] {it['description']}",
            f"{it['segment1']}, {it['description']}"
        ))
        nav = []
        if len(items) == MAX_CHOICES: nav.append("N=Next")
        if offset > 0:               nav.append("P=Prev")
        nav.append("0=Cancel")
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"): return None
        if c in ("n", "next") and len(items) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(items):
            selected_item = items[idx - 1]; break
        print_msg("  Invalid.", "Invalid selection.")

    qty_input = ask_msg("  Enter quantity: ", "Please say the quantity.")
    qty = parse_numeric_value(qty_input, allow_float=True)
    while qty is None:
        qty_input = ask_msg("  Invalid quantity. Try again: ", "Invalid quantity. Try again.")
        qty = parse_numeric_value(qty_input, allow_float=True)

    offset = 0
    selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            print_msg("  No price lists found." if offset == 0 else "  No more price lists.")
            return None
        print_msg(f"\n  Price lists for '{selected_item['segment1']}':", "Price lists found. Please choose.")
        speak_list(prices, lambda p: (
            f"{p['price_list_name']} — Unit Price: {p['unit_list_price']:.2f}",
            f"{p['price_list_name']}, price {p['unit_list_price']:.2f} dollars"
        ))
        nav = []
        if len(prices) == MAX_CHOICES: nav.append("N=Next")
        if offset > 0:                 nav.append("P=Prev")
        nav.append("0=Cancel")
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"): return None
        if c in ("n", "next") and len(prices) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(prices):
            selected_price = prices[idx - 1]; break
        print_msg("  Invalid.", "Invalid selection.")

    offset = 0
    selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms:
            print_msg("  No payment terms found." if offset == 0 else "  No more.")
            return None
        print_msg("\n  Payment terms:", "Payment terms. Please choose.")
        speak_list(terms, lambda t: (t['term_name'], t['term_name']))
        nav = []
        if len(terms) == MAX_CHOICES: nav.append("N=Next")
        if offset > 0:                nav.append("P=Prev")
        nav.append("0=Cancel")
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"): return None
        if c in ("n", "next") and len(terms) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(terms):
            selected_term = terms[idx - 1]; break
        print_msg("  Invalid.", "Invalid selection.")

    # Line Type selection
    line_type_id = None
    val = ask_msg("\n  Enter Line Type ID (or press Enter to see available options): ",
                  "Say the line type ID, or say list to see options.")
    if val.strip().lower() not in ("", "list", "options", "show"):
        line_type_id = parse_numeric_value(val)
    if line_type_id is None:
        offset_lt = 0
        while line_type_id is None:
            lt_rows = get_line_type_rows(offset=offset_lt)
            if not lt_rows:
                if offset_lt == 0:
                    val = ask_msg("  No line types found. Enter ID manually (0 to skip): ",
                                  "No line types found. Say the ID manually or zero to skip.")
                    if val.strip() in ("0", "zero", "cancel", "skip"):
                        break
                    line_type_id = parse_numeric_value(val)
                    break
                else:
                    offset_lt = max(0, offset_lt - MAX_CHOICES); continue
            speak_list(lt_rows, lambda lt: (
                f"{lt['line_type_name']} (ID: {lt['line_type_id']})",
                lt['line_type_name']
            ))
            has_more = len(lt_rows) == MAX_CHOICES
            nav = []
            if has_more: nav.append("N=Next")
            if offset_lt > 0: nav.append("P=Prev")
            nav.append("0=Skip")
            c = ask_msg(f"  Choice [{', '.join(nav)}]: ",
                        "Say a number, next, previous, or skip").strip().lower()
            if c in ("0", "skip", "zero"): break
            if c in ("n", "next") and has_more: offset_lt += MAX_CHOICES; continue
            if c in ("p", "prev", "previous") and offset_lt > 0: offset_lt -= MAX_CHOICES; continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(lt_rows):
                line_type_id = lt_rows[idx - 1]["line_type_id"]; break
            print_msg("  Invalid.", "Invalid selection.")

    unit_price = selected_price["unit_list_price"]
    sp_input = ask_msg(f"\n  Unit list price is {unit_price:.2f}. Enter selling price (or Enter to use list price): ",
                       f"Unit price is {unit_price:.2f}. Say the selling price or press enter.")
    selling_price = parse_numeric_value(sp_input, allow_float=True) if sp_input else unit_price

    return {
        "inventory_item_id": selected_item["inventory_item_id"],
        "ordered_item":      selected_item["segment1"],
        "quantity":          qty,
        "unit_list_price":   unit_price,
        "selling_price":     selling_price,
        "price_list_id":     selected_price["price_list_id"],
        "payment_term_id":   selected_term["term_id"],
        "line_type_id":      line_type_id,
    }


def add_line_to_order(order_number: int, header_id: int) -> None:
    while True:
        print_msg("\n" + "─" * 60)
        print_msg(f"  ➕  Add Another Line to Order #{order_number} (Header ID: {header_id})?")
        answer = ask_msg("  Press [A] to add a line, or any other key to finish: ",
                         "Say add to add a line, or done to finish.").strip().lower()
        if answer not in ("a", "add"):
            print_msg("  ✅  Done. No more lines will be added.", "Done. No more lines.")
            break

        line = collect_line_details()
        if line is None:
            print_msg("  ⚠️  Line entry cancelled.")
            continue

        payload = create_add_line_payload(
            p_header_id       = header_id,
            p_item_id         = line["inventory_item_id"],
            p_ordered_item    = line["ordered_item"],
            p_qty             = line["quantity"],
            p_price           = line["unit_list_price"],
            p_selling_price   = line["selling_price"],
            p_payment_term_id = line["payment_term_id"],
            p_price_list_id   = line["price_list_id"],
            p_line_type_id    = line.get("line_type_id"),
        )

        print_msg("\n  ⏳  Adding line...", "Adding line to order.")
        try:
            result = send_order(payload)
            print_msg(f"\n  ✅  Line added successfully to Order #{order_number}.",
                      f"Line added successfully to Order {order_number}.")
            print(f"  Response: {json.dumps(result, indent=2)}")
        except Exception as e:
            print_msg(f"\n  ❌  Failed to add line: {e}")


# --------------------------------------------------
# Create Order Flow
# --------------------------------------------------
def create_order_flow(intent: dict, conversation_history: list) -> None:
    cpo = intent.get("cpo")
    if not cpo:
        cpo = ask_msg("\n  [Mandatory] Enter Customer PO Number: ", "Please say the Customer PO Number.")
        while not cpo:
            cpo = ask_msg("  CPO is required. Please enter a value: ", "CPO is required.")

    ordered_item_hint = intent.get("ordered_item", "")
    item_input = ordered_item_hint

    if not item_input:
        item_input = ask_msg("\n  [Mandatory] Enter item name/prefix to search: ", "Please say the item name or prefix to search.")
        _voice_retries = 0
        while not item_input:
            _voice_retries += 1
            if MODE == "voice" and _voice_retries >= 2:
                print_msg("\n  I couldn't catch that. Let me show you the available items.",
                          "I couldn't catch that. Let me show you the available items. You can pick by saying a number.")
                item_input = "%"
                break
            item_input = ask_msg("  Item is required. Please enter a value: ", "Item is required. Please try again.")

    offset = 0
    selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            if offset == 0:
                item_input = ask_msg(f"  No items found matching '{item_input}'. Please try a different name: ")
                if not item_input:
                    print_msg("  Order creation cancelled.")
                    return
                continue
            else:
                print_msg("  No more items.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print_msg(f"\n  Items matching '{item_input}':", "Items found. Please choose.")
        speak_list(items, lambda it: (
            f"[{it['segment1']}] {it['description']}",
            f"{it['segment1']}, {it['description']}"
        ))

        nav = []
        if len(items) == MAX_CHOICES: nav.append("N = Next page")
        if offset > 0:               nav.append("P = Previous page")
        nav.append("0 = Cancel")
        
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"):
            print_msg("  Order creation cancelled.")
            return
        if c in ("n", "next") and len(items) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(items):
            selected_item = items[idx - 1]
            break
        print_msg("  Invalid selection.", "Invalid selection.")

    qty_hint = intent.get("quantity")
    qty = parse_numeric_value(qty_hint, allow_float=True) if qty_hint else None

    if qty is None:
        qty_input = ask_msg("\n  [Mandatory] Enter quantity: ", "Please say the quantity.")
        qty = parse_numeric_value(qty_input, allow_float=True)
    _qty_retries = 0
    while qty is None:
        _qty_retries += 1
        if MODE == "voice" and _qty_retries >= 2:
            common_qtys = [1, 5, 10, 25, 50, 100]
            print_msg("\n  I couldn't catch the quantity. Here are some common options:",
                      "I couldn't catch the quantity. Here are some common options. Say a number to pick.")
            speak_list(common_qtys, lambda q: (str(q), str(q)))
            c = ask_msg("  Choice (or say the quantity directly): ", "Say a number to select, or say the quantity directly.").strip()
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(common_qtys):
                qty = float(common_qtys[idx - 1])
                break
            elif idx and idx > len(common_qtys):
                qty = float(idx)
                break
            _qty_retries = 0
            continue
        qty_input = ask_msg("  Quantity is required and must be a number. Try again: ", "Quantity must be a number. Please try again.")
        qty = parse_numeric_value(qty_input, allow_float=True)

    customer_name = intent.get("customer_name")
    customer_info = None

    if customer_name:
        print_msg(f"\n  [Mandatory] Resolving customer '{customer_name}'...")
        while customer_info is None:
            customer_info = resolve_customer(customer_name)
            if customer_info is None:
                retry = ask_msg("  Could not resolve customer. Try a different name? (Y/N): ", "Try a different name? Say Yes or No").strip().upper()
                if retry not in ("Y", "YES"):
                    print_msg("  Order creation cancelled.")
                    return
                customer_name = ask_msg("  Enter customer name to search: ")
                if not customer_name: return
    else:
        print_msg(f"\n  [Mandatory] No customer specified — looking up customers for item '{selected_item['segment1']}'...")
        while customer_info is None:
            customer_info = resolve_customer_by_item(selected_item["inventory_item_id"], selected_item["segment1"])
            if customer_info is None:
                retry = ask_msg("  Could not resolve customer. Try searching by name? (Y/N): ").strip().upper()
                if retry not in ("Y", "YES"):
                    print_msg("  Order creation cancelled.")
                    return
                fallback_name = ask_msg("  Enter customer name to search: ")
                if not fallback_name: return
                customer_info = resolve_customer(fallback_name)

    sold_to_org_id = customer_info["sold_to_org_id"]
    ship_to_org_id = customer_info["ship_to_org_id"]
    print_msg(f"\n  ✔ Customer  : {customer_info['customer_name']}\n  ✔ Sold-to ID: {sold_to_org_id}  |  Ship-to ID: {ship_to_org_id}")

    # Line Type ID collection
    line_type_id = None
    val = ask_msg("\n  [Mandatory] Enter Line Type ID (or press Enter to see available options): ",
                  "Please say the line type ID, or say list to see available options.")
    if val.strip().lower() in ("", "list", "options", "show"):
        val = ""
    else:
        line_type_id = parse_numeric_value(val)

    if line_type_id is None:
        print_msg("\n  Here are the available line types:",
                  "Here are the available line types. Say a number to pick one.")
        offset_lt = 0
        while line_type_id is None:
            lt_rows = get_line_type_rows(offset=offset_lt)
            if not lt_rows:
                if offset_lt == 0:
                    print_msg("  No line types found in the system.")
                    while line_type_id is None:
                        val = ask_msg("  Please enter Line Type ID manually: ", "Please say the line type ID.")
                        line_type_id = parse_numeric_value(val)
                    break
                else:
                    print_msg("  No more line types.", "No more line types. Going back to the previous page.")
                    offset_lt = max(0, offset_lt - MAX_CHOICES)
                    continue

            speak_list(lt_rows, lambda lt: (
                f"{lt['line_type_name']} (ID: {lt['line_type_id']})",
                lt['line_type_name']
            ))

            has_more = len(lt_rows) == MAX_CHOICES
            nav = []
            if has_more: nav.append("N = Next")
            if offset_lt > 0: nav.append("P = Previous")
            nav.append("0 = Cancel")

            c = ask_msg(f"  Choice [{', '.join(nav)}]: ",
                        "Say a number to select, next for more options, or cancel").strip().lower()
            if c in ("0", "cancel", "zero"):
                print_msg("  Order creation cancelled.")
                return
            if c in ("n", "next") and has_more:
                print_msg("  Loading next values...", "Here are the next line types.")
                offset_lt += MAX_CHOICES
                continue
            if c in ("p", "prev", "previous") and offset_lt > 0:
                offset_lt -= MAX_CHOICES
                continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(lt_rows):
                line_type_id = lt_rows[idx - 1]["line_type_id"]
                print_msg(f"  ✔ Selected line type: {lt_rows[idx - 1]['line_type_name']} (ID: {line_type_id})")
                break
            print_msg("  Invalid selection, please try again.", "Invalid. Say a number to select.")

    offset = 0
    selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            if offset == 0:
                print_msg(f"  No price lists found for '{selected_item['segment1']}'. Cannot proceed.")
                return
            else:
                print_msg("  No more price lists.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print_msg(f"\n  Price lists for '{selected_item['segment1']}':", "Price lists found. Please choose.")
        speak_list(prices, lambda p: (
            f"{p['price_list_name']} — Unit Price: {p['unit_list_price']:.2f}",
            f"{p['price_list_name']}, price {p['unit_list_price']:.2f} dollars"
        ))

        nav = []
        if len(prices) == MAX_CHOICES: nav.append("N = Next page")
        if offset > 0:                 nav.append("P = Previous page")
        nav.append("0 = Cancel")
        
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"): return
        if c in ("n", "next") and len(prices) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(prices):
            selected_price = prices[idx - 1]; break
        print_msg("  Invalid.")

    unit_price = selected_price["unit_list_price"]
    sp_input = ask_msg(f"\n  Unit list price: {unit_price:.2f}. Enter selling price (Enter = same): ", f"Unit price is {unit_price:.2f}. Say the selling price or press enter to keep it.")
    selling_price = parse_numeric_value(sp_input, allow_float=True) if sp_input else unit_price

    offset = 0
    selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms:
            print_msg("  No payment terms found." if offset == 0 else "  No more.")
            return
        print_msg("\n  Payment terms:", "Payment terms. Please choose.")
        speak_list(terms, lambda t: (t['term_name'], t['term_name']))
        
        nav = []
        if len(terms) == MAX_CHOICES: nav.append("N = Next page")
        if offset > 0:               nav.append("P = Previous page")
        nav.append("0 = Cancel")
        
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"): return
        if c in ("n", "next") and len(terms) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(terms):
            selected_term = terms[idx - 1]; break
        print_msg("  Invalid.")

    offset = 0
    selected_rep = None
    while True:
        reps = get_salesrep_rows(offset=offset)
        if not reps:
            print_msg("  No salesreps found." if offset == 0 else "  No more.")
            return
        print_msg("\n  Sales representatives:", "Sales representatives. Please choose.")
        speak_list(reps, lambda r: (r['salesrep_name'], r['salesrep_name']))
            
        nav = []
        if len(reps) == MAX_CHOICES: nav.append("N = Next page")
        if offset > 0:              nav.append("P = Previous page")
        nav.append("0 = Cancel")
        
        c = ask_msg(f"  Choice [{', '.join(nav)}]: ", "Say a number, next, previous, or cancel").strip().lower()
        if c in ("0", "cancel", "zero"): return
        if c in ("n", "next") and len(reps) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c in ("p", "prev", "previous") and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(reps):
            selected_rep = reps[idx - 1]; break
        print_msg("  Invalid.")

    payload = create_payload(
        p_cust_po         = cpo,
        p_item_id         = selected_item["inventory_item_id"],
        p_ordered_item    = selected_item["segment1"],
        p_qty             = qty,
        p_price           = unit_price,
        p_selling_price   = selling_price,
        p_payment_term_id = selected_term["term_id"],
        p_price_list_id   = selected_price["price_list_id"],
        p_salesrep_id     = selected_rep["salesrep_id"],
        p_line_type_id    = line_type_id,
        p_ship_to_org     = ship_to_org_id,
        p_sold_to_org     = sold_to_org_id,
        p_operating_unit  = OPERATING_UNIT
    )

    print_msg("\n  ⏳  Submitting order...", "Submitting order.")
    try:
        result = send_order(payload)
        print_msg("\n  ✅  Order created successfully!", "Order created successfully.")
        print(f"  Response: {json.dumps(result, indent=2)}")

        order_number = None
        header_id    = None
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

        except Exception as parse_err:
            print_msg(f"  ⚠️  Response parse warning: {parse_err}")

        if order_number:
            order_number = int(str(order_number).strip())
        if header_id:
            header_id = int(str(header_id).strip())

        if not header_id:
            print_msg("\n  ⚠️  Could not auto-extract Header ID from response.")
            manual = ask_msg("  Please enter the Header ID shown above (or Enter to skip): ",
                             "Please say the Header ID, or say skip.")
            if manual and manual.lower() not in ("skip", ""):
                header_id = parse_numeric_value(manual)
        if not order_number:
            manual = ask_msg("  Please enter the Order Number shown above (or Enter to skip): ",
                             "Please say the Order Number, or say skip.")
            if manual and manual.lower() not in ("skip", ""):
                order_number = parse_numeric_value(manual)

        if header_id and order_number:
            add_line_to_order(int(order_number), int(header_id))
        else:
            print_msg("\n  ⚠️  Header ID / Order Number unavailable — skipping add-line option.")

    except Exception as e:
        print_msg(f"\n  ❌  Order creation failed: {e}")

# --------------------------------------------------
# Main Entry Point
# --------------------------------------------------
def main():
    global MODE
    parser = argparse.ArgumentParser(description="AI ERP Sales Order Assistant")
    parser.add_argument("--mode", choices=["text", "voice"], default="text", help="Operating mode: text or voice")
    args = parser.parse_args()

    MODE = args.mode
    if MODE == "voice" and not VOICE_AVAILABLE:
        print("Voice packages not installed. Defaulting to text mode.")
        MODE = "text"

    print("=" * 60)
    print("  ERP Sales Order Assistant" + (" (Voice Mode)" if MODE == "voice" else " (Text Mode)"))
    print("=" * 60)
    
    if MODE == "voice":
        speak("ERP Sales Order Assistant started. You can say exit to quit.")

    conversation_history = []

    while True:
        user_input = ask_msg("\nYou: ", "What would you like to do?")
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye", "stop"):
            print_msg("  Goodbye!", "Goodbye!")
            break

        conversation_history.append({"role": "user", "content": user_input})
        intent = github_extract_intent(user_input)
        action = intent.get("action", "unknown")

        if action == "create":
            create_order_flow(intent, conversation_history)

        elif action == "get":
            order_number = intent.get("order_number")
            if order_number:
                try:
                    result = get_order(int(order_number))
                    print_msg(f"\n  Order details:\n{json.dumps(result, indent=2)}", "Order fetched.")
                except Exception as e:
                    print_msg(f"\n  ❌  Error fetching order: {e}")
            else:
                try:
                    data = get_orders_advanced(
                        range_type = intent.get("date_range"),
                        year       = intent.get("year"),
                        status     = intent.get("status")
                    )
                    print_msg(f"\n  Total orders found: {data['total_count']}", f"Found {data['total_count']} orders.")
                    for row in data["rows"][:20]:
                        print(f"    Order#: {row[0]}  Status: {row[1]}  Created: {row[2]}")
                except Exception as e:
                    print_msg(f"\n  ❌  Error fetching orders: {e}")
        else:
            clarification = github_clarify(conversation_history, ["action (create order or get order info)"])
            print_msg(f"\n  Assistant: {clarification}", clarification)
            conversation_history.append({"role": "assistant", "content": clarification})

if __name__ == "__main__":
    main()