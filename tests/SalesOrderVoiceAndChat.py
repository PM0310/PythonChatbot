import os
import sys
import json
import datetime
import requests
import ssl
import urllib3
import argparse
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
import oracledb
from openai import OpenAI

# --------------------------------------------------
# Optional Voice Dependencies
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

# --------------------------------------------------
# Voice Configuration
# --------------------------------------------------
VOSK_MODEL_PATH  = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE      = 16000
VOICE_DURATION   = 5      # seconds to record per prompt
INPUT_MODE       = "text"  # global: "text" or "voice"

# --------------------------------------------------
# Voice Helpers
# --------------------------------------------------
def speak(text: str):
    """Text-to-speech output. Always also prints to console."""
    print(f"\n  🔊  {text}")
    if VOICE_AVAILABLE:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 160)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"  [TTS error: {e}]")


def load_vosk_model():
    if not os.path.isdir(VOSK_MODEL_PATH):
        raise FileNotFoundError(f"Vosk model not found: {VOSK_MODEL_PATH}")
    return Model(VOSK_MODEL_PATH)


def recognize_speech(duration: int = VOICE_DURATION) -> str:
    """
    Records audio for `duration` seconds and returns the recognised text.
    Falls back to empty string on any error.
    """
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice packages (vosk, sounddevice, pyttsx3, word2number) are not installed.")
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
        return ""


# --------------------------------------------------
# Unified Input / Output helpers
# --------------------------------------------------
def output(text: str):
    """Print (and speak in voice mode)."""
    if INPUT_MODE == "voice":
        speak(text)
    else:
        print(f"\n  {text}")


def get_input(prompt: str, duration: int = VOICE_DURATION) -> str:
    """
    In text mode  → prints prompt, reads from stdin.
    In voice mode → speaks prompt, records audio, returns recognised text.
    Returns empty string if nothing captured.
    """
    if INPUT_MODE == "voice":
        speak(prompt)
        return recognize_speech(duration)
    else:
        print(f"\n  {prompt}", end="")
        return input().strip()


def get_numeric_input(prompt: str, allow_float: bool = False, duration: int = VOICE_DURATION):
    """
    Keeps asking until a valid number is returned.
    In voice mode word-to-number conversion is attempted first.
    """
    while True:
        raw = get_input(prompt, duration)
        val = parse_numeric_value(raw, allow_float=allow_float)
        if val is not None:
            return val
        output("I didn't catch a valid number. Please try again.")


# --------------------------------------------------
# Numeric parser (supports spoken numbers in voice mode)
# --------------------------------------------------
def parse_numeric_value(val, allow_float=False):
    if val is None:
        return None
    val = str(val).strip()
    try:
        return float(val) if allow_float else int(val)
    except ValueError:
        pass
    # Try word-to-number (voice mode)
    if VOICE_AVAILABLE:
        try:
            return int(w2n.word_to_num(val))
        except Exception:
            pass
    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try:
            return float(digits) if allow_float else int(digits)
        except ValueError:
            pass
    return None


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


# --------------------------------------------------
# 2. AI Intent Extraction
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
# 3. DB Core Functions (WITH OFFSET FOR PAGINATION)
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


# --------------------------------------------------
# Customer Search by Name
# --------------------------------------------------
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


# --------------------------------------------------
# Customer Lookup by Inventory Item
# --------------------------------------------------
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
        SELECT hcsu.SITE_USE_ID,
               hcsu.LOCATION,
               hl.ADDRESS1,
               hl.CITY,
               hl.STATE,
               hl.POSTAL_CODE,
               hca.CUST_ACCOUNT_ID,
               hp.PARTY_NAME
          FROM HZ_CUST_ACCT_SITES_ALL hcas
          JOIN HZ_CUST_SITE_USES_ALL  hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
          JOIN HZ_PARTY_SITES          hps  ON hps.PARTY_SITE_ID      = hcas.PARTY_SITE_ID
          JOIN HZ_LOCATIONS            hl   ON hl.LOCATION_ID         = hps.LOCATION_ID
          JOIN HZ_CUST_ACCOUNTS        hca  ON hca.CUST_ACCOUNT_ID    = hcas.CUST_ACCOUNT_ID
          JOIN HZ_PARTIES              hp   ON hp.PARTY_ID            = hca.PARTY_ID
         WHERE hcas.CUST_ACCOUNT_ID = :cust_account_id
           AND hcas.ORG_ID          = :org_id
           AND hcsu.SITE_USE_CODE   = 'SHIP_TO'
           AND hcsu.STATUS          = 'A'
         ORDER BY hcsu.SITE_USE_ID
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, cust_account_id=cust_account_id, org_id=org_id)
        rows = cur.fetchall()
    return [
        {
            "ship_to_org_id": int(r[0]),
            "location":       r[1] or "",
            "address":        f"{r[2] or ''}, {r[3] or ''}, {r[4] or ''} {r[5] or ''}".strip(", "),
            "sold_to_org_id": int(r[6]),
            "customer_name":  r[7] or ""
        }
        for r in rows
    ]


# --------------------------------------------------
# Voice-aware Selection Helper
# --------------------------------------------------
def pick_from_list(items: list, label_fn, entity_name: str, allow_nav: bool = True) -> dict | None:
    """
    Generic paginated list picker that works in both text and voice mode.

    label_fn(item) → str   returns the display label for an item.

    In voice mode:
      - Reads all options aloud.
      - Listens for a spoken number ("one", "two", "1", "2", …).
      - N/P navigation is skipped (voice users always see full page).

    Returns the selected dict, or None if user cancels.
    """
    if INPUT_MODE == "voice":
        # Read list aloud
        speak(f"Here are the available {entity_name} options:")
        for i, item in enumerate(items, 1):
            speak(f"Option {i}: {label_fn(item)}")
        speak("Say the number of your choice, or say cancel.")
        while True:
            raw = recognize_speech()
            if "cancel" in raw:
                return None
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(items):
                speak(f"You selected: {label_fn(items[idx - 1])}")
                return items[idx - 1]
            speak("Sorry, I didn't catch a valid option. Please say a number.")
    else:
        # Text mode — standard numbered list
        for i, item in enumerate(items, 1):
            print(f"    {i}. {label_fn(item)}")
        print("  Enter choice (0 = Cancel): ", end="")
        while True:
            raw = input().strip().upper()
            if raw == "0":
                return None
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(items):
                return items[idx - 1]
            print("  Invalid selection, try again: ", end="")


# --------------------------------------------------
# Customer Resolution Flow (by name)
# --------------------------------------------------
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
            selected_customer = pick_from_list(
                customers,
                lambda c: f"{c['customer_name']}, Account Number {c['account_number']}",
                "customers"
            )
            if selected_customer is None:
                return None
            break
        else:
            for i, c in enumerate(customers, 1):
                print(f"    {i}. {c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})")
            nav_options = []
            if has_more:   nav_options.append("N = Next page")
            if offset > 0: nav_options.append("P = Previous page")
            nav_options.append("0 = Cancel")
            print(f"  Enter choice [{', '.join(nav_options)}]: ", end="")
            choice = input().strip().upper()
            if choice == "0":
                return None
            elif choice == "N" and has_more:
                offset += MAX_CHOICES; continue
            elif choice == "P" and offset > 0:
                offset -= MAX_CHOICES; continue
            else:
                idx = parse_numeric_value(choice)
                if idx and 1 <= idx <= len(customers):
                    selected_customer = customers[idx - 1]; break
                else:
                    print("  Invalid selection, please try again.")

    return _resolve_customer_sites(selected_customer)


# --------------------------------------------------
# Customer Resolution by Inventory Item
# --------------------------------------------------
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
                if not customer_name:
                    return None
                return resolve_customer(customer_name)
            else:
                output("No more customers.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        output(f"Customers who have ordered '{item_segment1}':")
        has_more = len(customers) == MAX_CHOICES

        if INPUT_MODE == "voice":
            speak("Say the number of the customer, say 'search' to search by name, or say 'cancel'.")
            for i, c in enumerate(customers, 1):
                speak(f"Option {i}: {c['customer_name']}, Account Number {c['account_number']}")
            raw = recognize_speech()
            if "cancel" in raw:
                return None
            if "search" in raw:
                customer_name = get_input("Say the customer name to search:", duration=6)
                if not customer_name:
                    return None
                return resolve_customer(customer_name)
            idx = parse_numeric_value(raw)
            if idx and 1 <= idx <= len(customers):
                selected_customer = customers[idx - 1]; break
            speak("I didn't catch a valid choice. Let's try again.")
            continue
        else:
            for i, c in enumerate(customers, 1):
                print(f"    {i}. {c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})")
            nav_options = []
            if has_more:   nav_options.append("N = Next page")
            if offset > 0: nav_options.append("P = Previous page")
            nav_options.extend(["S = Search by name instead", "0 = Cancel"])
            print(f"  Enter choice [{', '.join(nav_options)}]: ", end="")
            choice = input().strip().upper()
            if choice == "0":
                return None
            elif choice == "S":
                print("  Enter customer name to search: ", end="")
                manual_name = input().strip()
                if not manual_name:
                    return None
                return resolve_customer(manual_name)
            elif choice == "N" and has_more:
                offset += MAX_CHOICES; continue
            elif choice == "P" and offset > 0:
                offset -= MAX_CHOICES; continue
            else:
                idx = parse_numeric_value(choice)
                if idx and 1 <= idx <= len(customers):
                    selected_customer = customers[idx - 1]; break
                else:
                    print("  Invalid selection, please try again.")

    return _resolve_customer_sites(selected_customer)


def _resolve_customer_sites(selected_customer: dict) -> dict | None:
    sites = get_customer_sites_by_account(selected_customer["cust_account_id"])

    if not sites:
        output(f"No active SHIP_TO sites found for '{selected_customer['customer_name']}'.")
        return None

    if len(sites) == 1:
        site = sites[0]
        output(f"Auto-selected ship-to site: {site['location']} — {site['address']}")
        return {"sold_to_org_id": site["sold_to_org_id"], "ship_to_org_id": site["ship_to_org_id"], "customer_name": site["customer_name"]}

    output(f"'{selected_customer['customer_name']}' has {len(sites)} ship-to sites. Please select one:")
    selected_site = pick_from_list(
        sites,
        lambda s: f"{s['location']}, {s['address']}",
        "ship-to sites"
    )
    if selected_site is None:
        return None
    return {"sold_to_org_id": selected_site["sold_to_org_id"], "ship_to_org_id": selected_site["ship_to_org_id"], "customer_name": selected_site["customer_name"]}


# --------------------------------------------------
# 4. Advanced Reporting API
# --------------------------------------------------
def get_orders_advanced(range_type=None, year=None, status=None):
    if year:
        date_clause = f"EXTRACT(YEAR FROM CREATION_DATE) = {year}"
    elif range_type:
        date_map = {"this_month": "TRUNC(SYSDATE, 'MM')", "this_week": "TRUNC(SYSDATE, 'IW')", "last_30_days": "SYSDATE - 30"}
        date_clause = f"CREATION_DATE >= {date_map.get(range_type, 'SYSDATE - 7')}"
    else:
        date_clause = "1=1"

    status_clause = f"UPPER(FLOW_STATUS_CODE) LIKE '%{status.upper()}%'" if status else "1=1"
    sql_main  = f"SELECT ORDER_NUMBER, FLOW_STATUS_CODE, CREATION_DATE FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org ORDER BY CREATION_DATE DESC"
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
def create_payload(p_cust_po, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price,
                   p_payment_term_id, p_price_list_id, p_salesrep_id,
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
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id,
                    "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                }},
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": p_operating_unit, "P_DEBUG_LEVEL": 10
            }
        }
    }


def create_add_line_payload(p_header_id, p_item_id, p_ordered_item, p_qty,
                            p_price, p_selling_price, p_payment_term_id, p_price_list_id):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT",
                "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {"HEADER_ID": p_header_id, "ORG_ID": ORG_ID, "OPERATION": "UPDATE"},
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "HEADER_ID": p_header_id, "INVENTORY_ITEM_ID": p_item_id,
                        "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty,
                        "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id,
                        "UNIT_LIST_PRICE": p_price, "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                    }
                },
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": OPERATING_UNIT, "P_DEBUG_LEVEL": 10
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
            "RESTHeader": {
                "Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT",
                "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_ORDER_NUMBER": order_number
            }
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


# --------------------------------------------------
# 6. Add Another Line Flow
# --------------------------------------------------
def collect_line_details() -> dict | None:
    item_input = get_input("Enter or say item name/prefix to search (or say cancel): ", duration=5)
    if not item_input or item_input.lower() in ("cancel", "0"):
        return None

    offset = 0
    selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            output("No items found.")
            return None
        output(f"Items matching '{item_input}':")
        selected_item = pick_from_list(items, lambda it: f"{it['segment1']} — {it['description']}", "items")
        if selected_item:
            break
        return None

    qty = get_numeric_input("Enter or say the quantity:", allow_float=True)

    offset = 0
    selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            output("No price lists found.")
            return None
        output(f"Price lists for '{selected_item['segment1']}':")
        selected_price = pick_from_list(
            prices,
            lambda p: f"{p['price_list_name']} — Unit Price {p['unit_list_price']:.2f}",
            "price lists"
        )
        if selected_price:
            break
        return None

    offset = 0
    selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms:
            output("No payment terms found.")
            return None
        output("Payment terms:")
        selected_term = pick_from_list(terms, lambda t: t["term_name"], "payment terms")
        if selected_term:
            break
        return None

    unit_price = selected_price["unit_list_price"]
    output(f"Unit list price is {unit_price:.2f}.")
    sp_raw = get_input("Say or enter the selling price, or press Enter / say same to use the list price:", duration=5)
    selling_price = parse_numeric_value(sp_raw, allow_float=True) if sp_raw else unit_price

    return {
        "inventory_item_id": selected_item["inventory_item_id"],
        "ordered_item":      selected_item["segment1"],
        "quantity":          qty,
        "unit_list_price":   unit_price,
        "selling_price":     selling_price,
        "price_list_id":     selected_price["price_list_id"],
        "payment_term_id":   selected_term["term_id"],
    }


def add_line_to_order(order_number: int, header_id: int) -> None:
    while True:
        print("\n" + "─" * 60)
        answer = get_input(f"Add another line to Order {order_number}? Say or type A to add, or anything else to finish:")
        if answer.strip().upper() != "A":
            output("Done. No more lines will be added.")
            break

        line = collect_line_details()
        if line is None:
            output("Line entry cancelled.")
            continue

        payload = create_add_line_payload(
            p_header_id=header_id, p_item_id=line["inventory_item_id"],
            p_ordered_item=line["ordered_item"], p_qty=line["quantity"],
            p_price=line["unit_list_price"], p_selling_price=line["selling_price"],
            p_payment_term_id=line["payment_term_id"], p_price_list_id=line["price_list_id"],
        )
        print(f"\n  📤  Sending add-line payload:\n{json.dumps(payload, indent=2)}")
        try:
            result = send_order(payload)
            output(f"Line added successfully to Order {order_number}.")
            print(f"  Response: {json.dumps(result, indent=2)}")
        except Exception as e:
            output(f"Failed to add line: {e}")

        

# --------------------------------------------------
# 7. create_order_flow  (voice-aware)
# --------------------------------------------------
def create_order_flow(intent: dict, conversation_history: list) -> None:

    # ── CPO ─────────────────────────────────────────────────────────
    cpo = intent.get("cpo")
    if not cpo:
        cpo = get_input("Please say or enter the Customer PO Number:", duration=5)
        while not cpo:
            output("Customer PO is required.")
            cpo = get_input("Please say or enter the Customer PO Number:", duration=5)

    # ── Ordered Item ────────────────────────────────────────────────
    item_input = intent.get("ordered_item", "")
    if not item_input:
        item_input = get_input("Please say or enter the item name or prefix to search:", duration=5)
        while not item_input:
            output("Item is required.")
            item_input = get_input("Please say or enter the item name or prefix to search:", duration=5)

    offset = 0
    selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            if offset == 0:
                output(f"No items found matching '{item_input}'.")
                item_input = get_input("Please try a different item name:", duration=5)
                if not item_input:
                    output("Order creation cancelled.")
                    return
                continue
            else:
                output("No more items.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        output(f"Items matching '{item_input}':")

        if INPUT_MODE == "voice":
            selected_item = pick_from_list(items, lambda it: f"{it['segment1']}, {it['description']}", "items")
            if selected_item:
                break
            output("Order creation cancelled.")
            return
        else:
            for i, it in enumerate(items, 1):
                print(f"    {i}. [{it['segment1']}] {it['description']}")
            nav = []
            if len(items) == MAX_CHOICES: nav.append("N = Next page")
            if offset > 0:               nav.append("P = Previous page")
            nav.append("0 = Cancel")
            print(f"  Choice [{', '.join(nav)}]: ", end="")
            c = input().strip().upper()
            if c == "0":
                output("Order creation cancelled.")
                return
            if c == "N" and len(items) == MAX_CHOICES: offset += MAX_CHOICES; continue
            if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
            idx = parse_numeric_value(c)
            if idx and 1 <= idx <= len(items):
                selected_item = items[idx - 1]; break
            print("  Invalid selection.")

    # ── Quantity ────────────────────────────────────────────────────
    qty_hint = intent.get("quantity")
    qty = parse_numeric_value(qty_hint, allow_float=True) if qty_hint else None
    if qty is None:
        qty = get_numeric_input("Please say or enter the quantity:", allow_float=True)

    # ── Customer ────────────────────────────────────────────────────
    customer_name = intent.get("customer_name")
    customer_info = None

    if customer_name:
        output(f"Resolving customer '{customer_name}'...")
        while customer_info is None:
            customer_info = resolve_customer(customer_name)
            if customer_info is None:
                retry = get_input("Could not resolve customer. Try a different name? Say yes or no:", duration=4)
                if "yes" not in retry.lower():
                    output("Order creation cancelled.")
                    return
                customer_name = get_input("Say or enter the customer name to search:", duration=6)
                if not customer_name:
                    output("Order creation cancelled.")
                    return
    else:
        output(f"No customer specified — looking up customers for item '{selected_item['segment1']}'...")
        while customer_info is None:
            customer_info = resolve_customer_by_item(selected_item["inventory_item_id"], selected_item["segment1"])
            if customer_info is None:
                retry = get_input("Could not resolve customer. Search by name? Say yes or no:", duration=4)
                if "yes" not in retry.lower():
                    output("Order creation cancelled.")
                    return
                fallback_name = get_input("Say or enter the customer name to search:", duration=6)
                if not fallback_name:
                    output("Order creation cancelled.")
                    return
                customer_info = resolve_customer(fallback_name)

    sold_to_org_id = customer_info["sold_to_org_id"]
    ship_to_org_id = customer_info["ship_to_org_id"]
    output(f"Customer confirmed: {customer_info['customer_name']}, Sold-to ID {sold_to_org_id}, Ship-to ID {ship_to_org_id}")

    # ── Price List ──────────────────────────────────────────────────
    offset = 0
    selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            if offset == 0:
                output(f"No price lists found for '{selected_item['segment1']}'. Cannot proceed.")
                return
            offset = max(0, offset - MAX_CHOICES); continue

        output(f"Price lists for '{selected_item['segment1']}':")

        if INPUT_MODE == "voice":
            selected_price = pick_from_list(
                prices,
                lambda p: f"{p['price_list_name']}, Unit Price {p['unit_list_price']:.2f}",
                "price lists"
            )
            if selected_price: break
            return
        else:
            for i, p in enumerate(prices, 1):
                print(f"    {i}. {p['price_list_name']} — Unit Price: {p['unit_list_price']:.2f}")
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
            if idx and 1 <= idx <= len(prices):
                selected_price = prices[idx - 1]; break
            print("  Invalid.")

    unit_price = selected_price["unit_list_price"]
    output(f"Unit list price is {unit_price:.2f}.")
    sp_raw = get_input("Say or enter the selling price, or press Enter / say same:", duration=5)
    selling_price = parse_numeric_value(sp_raw, allow_float=True) if sp_raw else unit_price

    # ── Payment Term ────────────────────────────────────────────────
    offset = 0
    selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms:
            output("No payment terms found." if offset == 0 else "No more.")
            return
        output("Payment terms:")
        if INPUT_MODE == "voice":
            selected_term = pick_from_list(terms, lambda t: t["term_name"], "payment terms")
            if selected_term: break
            return
        else:
            for i, t in enumerate(terms, 1):
                print(f"    {i}. {t['term_name']}")
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
            if idx and 1 <= idx <= len(terms):
                selected_term = terms[idx - 1]; break
            print("  Invalid.")

    # ── Salesrep ────────────────────────────────────────────────────
    offset = 0
    selected_rep = None
    while True:
        reps = get_salesrep_rows(offset=offset)
        if not reps:
            output("No salesreps found." if offset == 0 else "No more.")
            return
        output("Sales representatives:")
        if INPUT_MODE == "voice":
            selected_rep = pick_from_list(reps, lambda r: r["salesrep_name"], "sales representatives")
            if selected_rep: break
            return
        else:
            for i, r in enumerate(reps, 1):
                print(f"    {i}. {r['salesrep_name']}")
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
            if idx and 1 <= idx <= len(reps):
                selected_rep = reps[idx - 1]; break
            print("  Invalid.")

    # ── Build & Submit ───────────────────────────────────────────────
    payload = create_payload(
        p_cust_po=cpo, 
        p_item_id=selected_item["inventory_item_id"],
        p_ordered_item=selected_item["segment1"], p_qty=qty,
        p_price=unit_price, p_selling_price=selling_price,
        p_payment_term_id=selected_term["term_id"],
        p_price_list_id=selected_price["price_list_id"],
        p_salesrep_id=selected_rep["salesrep_id"],
        p_ship_to_org=ship_to_org_id, p_sold_to_org=sold_to_org_id,
        p_operating_unit=OPERATING_UNIT
    )

    output("Submitting your order, please wait...")
    try:
        result = send_order(payload)
        output("Order created successfully!")
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
            print(f"  ⚠️  Response parse warning: {parse_err}")

        if order_number: order_number = int(str(order_number).strip())
        if header_id:    header_id    = int(str(header_id).strip())

        if not header_id:
            output("Could not auto-extract Header ID.")
            manual = get_input("Please say or enter the Header ID shown in the response (or say skip):", duration=5)
            if manual and "skip" not in manual.lower():
                header_id = parse_numeric_value(manual)
        if not order_number:
            manual = get_input("Please say or enter the Order Number shown in the response (or say skip):", duration=5)
            if manual and "skip" not in manual.lower():
                order_number = parse_numeric_value(manual)

        if header_id and order_number:
            add_line_to_order(int(order_number), int(header_id))
        else:
            output("Header ID or Order Number unavailable — skipping add-line option.")

    except Exception as e:
        output(f"Order creation failed: {e}")


# --------------------------------------------------
# 8. Main Entry Point
# --------------------------------------------------
def main():
    global INPUT_MODE

    parser = argparse.ArgumentParser(description="ERP Sales Order Assistant")
    parser.add_argument(
        "--mode", choices=["text", "voice"], default="text",
        help="Input mode: 'text' (keyboard) or 'voice' (microphone). Default: text"
    )
    args = parser.parse_args()
    INPUT_MODE = args.mode

    if INPUT_MODE == "voice" and not VOICE_AVAILABLE:
        print("ERROR: Voice packages are not installed.")
        print("Please install: pip install pyttsx3 vosk sounddevice word2number")
        sys.exit(1)

    print("=" * 60)
    print("  ERP Sales Order Assistant")
    print(f"  Mode: {'🎙️  VOICE' if INPUT_MODE == 'voice' else '⌨️   TEXT'}")
    print("=" * 60)

    if INPUT_MODE == "voice":
        speak("Welcome to the ERP Sales Order Assistant. Say exit or quit to stop.")
    else:
        print("\n  Type your request below. Type 'exit' or 'quit' to stop.\n")

    conversation_history = []

    while True:
        if INPUT_MODE == "voice":
            speak("How can I help you? Say create order or get order.")
            user_input = recognize_speech(duration=6)
        else:
            print("\nYou: ", end="")
            user_input = input().strip()

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye", "stop"):
            output("Goodbye!")
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
                    output(f"Here are the details for Order {order_number}:")
                    print(f"\n{json.dumps(result, indent=2)}")
                except Exception as e:
                    output(f"Error fetching order: {e}")
            else:
                try:
                    data = get_orders_advanced(
                        range_type=intent.get("date_range"),
                        year=intent.get("year"),
                        status=intent.get("status")
                    )
                    output(f"Total orders found: {data['total_count']}")
                    for row in data["rows"][:20]:
                        line = f"Order {row[0]}, Status {row[1]}, Created {row[2]}"
                        print(f"    {line}")
                        if INPUT_MODE == "voice":
                            speak(line)
                except Exception as e:
                    output(f"Error fetching orders: {e}")
        else:
            clarification = github_clarify(conversation_history, ["action (create order or get order info)"])
            output(f"Assistant: {clarification}")
            conversation_history.append({"role": "assistant", "content": clarification})


if __name__ == "__main__":
    main()