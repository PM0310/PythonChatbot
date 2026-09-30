import os
import json
import argparse
import requests
import ssl
import urllib3
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context

# Oracle DB
import oracledb

# Optional voice dependencies (if installed)
try:
    import pyttsx3
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    from word2number import w2n
    VOICE_AVAILABLE = True
except Exception:
    VOICE_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

# --------------------------------------------------
# DB Configuration
# --------------------------------------------------
DB_USER     = "apps"
DB_PASSWORD = "apps"
DB_DSN      = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"


def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)


# --------------------------------------------------
# REST Configuration
# --------------------------------------------------
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2
        ctx.options |= ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


BASE_URL      = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/PROCESS_ORDER/"
GET_ORDER_URL  = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
HEADERS       = {"Content-Type": "application/json", "Accept": "application/json"}

# Fixed / org-level constants
ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Centroid Manufacturing"
MAX_CHOICES    = 5   # Max records shown to user for selection


# --------------------------------------------------
# Voice helpers
# --------------------------------------------------
def speak(text: str):
    if VOICE_AVAILABLE:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    print("[TTS]", text)


MODEL_PATH       = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE      = 16000
DURATION_SECONDS = 4


def load_vosk_model():
    if not os.path.isdir(MODEL_PATH):
        raise FileNotFoundError(f"Vosk model directory not found: {MODEL_PATH}")
    return Model(MODEL_PATH)


def recognize_speech_vosk(duration=DURATION_SECONDS):
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice modules not installed")
    model = load_vosk_model()
    rec   = KaldiRecognizer(model, SAMPLE_RATE)
    data  = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    if not rec.AcceptWaveform(data.tobytes()):
        res = json.loads(rec.FinalResult())
    else:
        res = json.loads(rec.Result())
    return res.get("text", "").strip().lower()


# --------------------------------------------------
# Numeric parser
# --------------------------------------------------
def parse_numeric_value(val, allow_float=False):
    if val is None:
        return None
    val = str(val).strip()
    try:
        return float(val) if allow_float else int(val)
    except ValueError:
        pass
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


# --------------------------------------------------
# Interactive selection helper
# --------------------------------------------------
def prompt_user_selection(label: str, rows: list, display_fn) -> dict:
    """
    Present up to MAX_CHOICES rows and return the user-selected one.
    Auto-selects when only one row exists.

    :param label:      Human-readable name of what is being selected.
    :param rows:       List of row dicts (already capped at MAX_CHOICES).
    :param display_fn: Callable(row) -> str — formats a row for display.
    :returns:          The selected row dict.
    """
    if len(rows) == 1:
        print(f"     [AUTO-SELECTED] {label}: {display_fn(rows[0])}")
        return rows[0]

    print(f"\n  Multiple {label} records found. Please choose one:")
    for idx, row in enumerate(rows, start=1):
        print(f"    [{idx}] {display_fn(row)}")

    while True:
        raw = input(f"  Enter choice (1-{len(rows)}): ").strip()
        try:
            choice = int(raw)
            if 1 <= choice <= len(rows):
                selected = rows[choice - 1]
                print(f"     [SELECTED] {label}: {display_fn(selected)}")
                return selected
        except ValueError:
            pass
        print(f"  Invalid input. Enter a number between 1 and {len(rows)}.")


# --------------------------------------------------
# DB Lookups — each limited to MAX_CHOICES rows
# --------------------------------------------------

def fetch_inventory_item(ordered_item: str, org_id: int = ORG_ID) -> dict:
    """
    Returns one selected inventory item dict.
    Prompts user if multiple rows are found (up to MAX_CHOICES shown).
    Chain anchor: the returned inventory_item_id feeds into price-list lookup.
    """
    sql = """
        SELECT INVENTORY_ITEM_ID,
               SEGMENT1,
               DESCRIPTION,
               ORGANIZATION_ID
          FROM MTL_SYSTEM_ITEMS_B
         WHERE SEGMENT1        = :ordered_item
           AND ORGANIZATION_ID = :org_id
           AND ROWNUM          <= :max_rows
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,
                        ordered_item=ordered_item.upper(),
                        org_id=org_id,
                        max_rows=MAX_CHOICES)
            rows = cur.fetchall()

    if not rows:
        raise ValueError(
            f"Item '{ordered_item}' not found in MTL_SYSTEM_ITEMS_B "
            f"for ORGANIZATION_ID={org_id}"
        )

    dicts = [
        {
            "inventory_item_id": int(r[0]),
            "segment1":          r[1],
            "description":       r[2] or "",
            "organization_id":   int(r[3]),
        }
        for r in rows
    ]

    def display(r):
        return f"ID={r['inventory_item_id']}  Segment={r['segment1']}  Desc={r['description']}"

    return prompt_user_selection("Inventory Item", dicts, display)


def fetch_price_details(ordered_item: str,
                        quantity: float,
                        inventory_item_id: int,
                        org_id: int = ORG_ID) -> dict:
    """
    Three-strategy price-list lookup chained on the selected inventory_item_id.
    Each strategy is capped at MAX_CHOICES rows; user selects if multiple found.
    Returns { price_list_id, unit_list_price, unit_selling_price }.
    """

    sql_order_type = """
        SELECT qlh.LIST_HEADER_ID    AS price_list_id,
               qlt.NAME              AS price_list_name,
               qll.OPERAND           AS unit_list_price
          FROM OE_ORDER_TYPES_V       oot
          JOIN QP_LIST_HEADERS_B      qlh
               ON  qlh.LIST_HEADER_ID = oot.PRICE_LIST_ID
          JOIN QP_LIST_HEADERS_TL     qlt
               ON  qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID
               AND qlt.LANGUAGE       = USERENV('LANG')
          JOIN QP_LIST_LINES          qll
               ON  qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES  qpa
               ON  qpa.LIST_LINE_ID      = qll.LIST_LINE_ID
               AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
         WHERE oot.ORDER_TYPE_ID = :order_type_id
           AND qlh.ACTIVE_FLAG   = 'Y'
           AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE)
           AND (qll.END_DATE_ACTIVE   IS NULL OR qll.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
    """

    sql_customer = """
        SELECT qlh.LIST_HEADER_ID    AS price_list_id,
               qlt.NAME              AS price_list_name,
               qll.OPERAND           AS unit_list_price
          FROM HZ_CUST_ACCT_SITES_ALL  hcas
          JOIN HZ_CUST_SITE_USES_ALL   hcsu
               ON  hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
               AND hcsu.SITE_USE_CODE      = 'BILL_TO'
               AND hcsu.STATUS             = 'A'
          JOIN QP_LIST_HEADERS_B          qlh
               ON  qlh.LIST_HEADER_ID      = hcsu.PRICE_LIST_ID
          JOIN QP_LIST_HEADERS_TL         qlt
               ON  qlt.LIST_HEADER_ID      = qlh.LIST_HEADER_ID
               AND qlt.LANGUAGE            = USERENV('LANG')
          JOIN QP_LIST_LINES              qll
               ON  qll.LIST_HEADER_ID      = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES      qpa
               ON  qpa.LIST_LINE_ID        = qll.LIST_LINE_ID
               AND qpa.PRODUCT_ATTRIBUTE   = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE  = :item_id_str
         WHERE hcas.ORG_ID      = :org_id
           AND hcas.STATUS      = 'A'
           AND qlh.ACTIVE_FLAG  = 'Y'
           AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
    """

    sql_generic = """
        SELECT qlh.LIST_HEADER_ID    AS price_list_id,
               qlt.NAME              AS price_list_name,
               qll.OPERAND           AS unit_list_price
          FROM QP_LIST_HEADERS_B     qlh
          JOIN QP_LIST_HEADERS_TL    qlt
               ON  qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID
               AND qlt.LANGUAGE       = USERENV('LANG')
          JOIN QP_LIST_LINES         qll
               ON  qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES  qpa
               ON  qpa.LIST_LINE_ID      = qll.LIST_LINE_ID
               AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
         WHERE qlh.ACTIVE_FLAG    = 'Y'
           AND qlh.LIST_TYPE_CODE = 'PRL'
           AND qlh.CURRENCY_CODE  = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE)
           AND (qll.END_DATE_ACTIVE   IS NULL OR qll.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
         ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
    """

    def to_dicts(raw_rows):
        return [
            {
                "price_list_id":   int(r[0]),
                "price_list_name": r[1] or "",
                "unit_list_price": float(r[2]),
            }
            for r in raw_rows
        ]

    def display(r):
        return (f"ID={r['price_list_id']}  Name={r['price_list_name']}  "
                f"Price={r['unit_list_price']}")

    rows = []
    source_label = ""

    with get_connection() as conn:
        with conn.cursor() as cur:

            # Convert to string once — PRODUCT_ATTR_VALUE is VARCHAR2;
            # passing as a number causes Oracle to implicitly cast every
            # row value with TO_NUMBER, which fails on non-numeric entries.
            item_id_str = str(inventory_item_id)

            # Strategy 1 — Order Type price list (chained on inventory_item_id)
            cur.execute(sql_order_type,
                        item_id_str=item_id_str,
                        order_type_id=ORDER_TYPE_ID,
                        max_rows=MAX_CHOICES)
            rows = cur.fetchall()
            if rows:
                source_label = f"Order Type ({ORDER_TYPE_ID})"

            # Strategy 2 — Customer Bill-To site (chained on inventory_item_id)
            if not rows:
                cur.execute(sql_customer,
                            item_id_str=item_id_str,
                            org_id=org_id,
                            max_rows=MAX_CHOICES)
                rows = cur.fetchall()
                if rows:
                    source_label = "Customer Bill-To Site"

            # Strategy 3 — Generic active price list (chained on inventory_item_id)
            if not rows:
                cur.execute(sql_generic,
                            item_id_str=item_id_str,
                            max_rows=MAX_CHOICES)
                rows = cur.fetchall()
                if rows:
                    source_label = "Generic Active Price List"

    if not rows:
        raise ValueError(
            f"No valid price list found for INVENTORY_ITEM_ID={inventory_item_id} "
            f"in ORG_ID={org_id}. "
            f"Please check QP_LIST_HEADERS_B and QP_PRICING_ATTRIBUTES."
        )

    print(f"     PRICE LIST SOURCE : {source_label}")
    selected = prompt_user_selection("Price List", to_dicts(rows), display)

    return {
        "price_list_id":      selected["price_list_id"],
        "unit_list_price":    selected["unit_list_price"],
        "unit_selling_price": selected["unit_list_price"],   # selling = list price by default
    }


def fetch_payment_term_id(org_id: int = ORG_ID) -> int:
    """
    Fetches up to MAX_CHOICES payment terms; prompts user if more than one.
    Returns the selected PAYMENT_TERM_ID.
    """
    sql_customer = """
        SELECT DISTINCT hcsu.PAYMENT_TERM_ID,
               rt.NAME AS term_name
          FROM HZ_CUST_ACCT_SITES_ALL hcas
          JOIN HZ_CUST_SITE_USES_ALL  hcsu
               ON  hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
          JOIN RA_TERMS_B              rt
               ON  rt.TERM_ID             = hcsu.PAYMENT_TERM_ID
         WHERE hcsu.SITE_USE_CODE      = 'BILL_TO'
           AND hcsu.STATUS             = 'A'
           AND hcas.STATUS             = 'A'
           AND hcas.ORG_ID             = :org_id
           AND hcsu.PAYMENT_TERM_ID IS NOT NULL
           AND ROWNUM                  <= :max_rows
    """

    sql_fallback = """
        SELECT TERM_ID,
               NAME
          FROM RA_TERMS_B
         WHERE ENABLED_FLAG = 'Y'
           AND ROWNUM       <= :max_rows
         ORDER BY TERM_ID
    """

    def to_dicts(raw_rows):
        return [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in raw_rows]

    def display(r):
        return f"ID={r['term_id']}  Name={r['term_name']}"

    rows = []
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_customer, org_id=org_id, max_rows=MAX_CHOICES)
            rows = cur.fetchall()

    if not rows:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_fallback, max_rows=MAX_CHOICES)
                rows = cur.fetchall()

    if not rows:
        raise ValueError("Could not derive PAYMENT_TERM_ID from the database.")

    selected = prompt_user_selection("Payment Term", to_dicts(rows), display)
    return selected["term_id"]


def fetch_salesrep(org_id: int = ORG_ID) -> dict:
    """
    Fetches up to MAX_CHOICES active sales reps; prompts user if more than one.
    Returns { salesrep_id, salesrep_name }.
    """
    sql = """
        SELECT jrs.SALESREP_ID,
               jrs.NAME AS salesrep_name
          FROM JTF_RS_SALESREPS jrs
         WHERE jrs.ORG_ID          = :org_id
           AND jrs.STATUS          = 'A'
           AND jrs.END_DATE_ACTIVE IS NULL
           AND ROWNUM              <= :max_rows
         ORDER BY jrs.SALESREP_ID
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, org_id=org_id, max_rows=MAX_CHOICES)
            rows = cur.fetchall()

    if not rows:
        raise ValueError(f"No active SALESREP found for ORG_ID={org_id}.")

    dicts = [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]

    def display(r):
        return f"ID={r['salesrep_id']}  Name={r['salesrep_name']}"

    return prompt_user_selection("Sales Rep", dicts, display)


def fetch_customer_sites(ordered_item: str, org_id: int = ORG_ID) -> dict:
    """
    Fetches up to MAX_CHOICES active primary SHIP_TO customer sites
    linked to the ordered item's org.
    Chained on the ordered_item selected earlier.
    Prompts user if more than one.
    Returns { sold_to_org_id, ship_to_org_id, customer_name, operating_unit_id }.
    """
    sql = """
        SELECT
            hca.CUST_ACCOUNT_ID  AS sold_to_org_id,
            hcsu.SITE_USE_ID     AS ship_to_org_id,
            hp.PARTY_NAME        AS customer_name,
            hcas.ORG_ID          AS operating_unit_id
          FROM
            MTL_SYSTEM_ITEMS_B      msi
          JOIN HZ_CUST_ACCT_SITES_ALL hcas
               ON  hcas.ORG_ID         = :org_id
          JOIN HZ_CUST_SITE_USES_ALL  hcsu
               ON  hcas.CUST_ACCT_SITE_ID = hcsu.CUST_ACCT_SITE_ID
          JOIN HZ_CUST_ACCOUNTS        hca
               ON  hcas.CUST_ACCOUNT_ID   = hca.CUST_ACCOUNT_ID
          JOIN HZ_PARTIES               hp
               ON  hca.PARTY_ID           = hp.PARTY_ID
         WHERE
             msi.SEGMENT1          = :ordered_item
           AND msi.ORGANIZATION_ID = :org_id
           AND hcsu.SITE_USE_CODE  = 'SHIP_TO'
           AND hcsu.STATUS         = 'A'
           AND hcas.STATUS         = 'A'
           AND hca.STATUS          = 'A'
           AND hcsu.PRIMARY_FLAG   = 'Y'
           AND ROWNUM              <= :max_rows
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,
                        ordered_item=ordered_item.upper(),
                        org_id=org_id,
                        max_rows=MAX_CHOICES)
            rows = cur.fetchall()

    if not rows:
        raise ValueError(
            f"No active primary SHIP_TO site found for item '{ordered_item}' "
            f"and ORG_ID={org_id}. "
            f"Check HZ_CUST_ACCT_SITES_ALL / HZ_CUST_SITE_USES_ALL."
        )

    dicts = [
        {
            "sold_to_org_id":    int(r[0]),
            "ship_to_org_id":    int(r[1]),
            "customer_name":     r[2] or "",
            "operating_unit_id": int(r[3]),
        }
        for r in rows
    ]

    def display(r):
        return (f"Customer={r['customer_name']}  "
                f"SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}")

    selected = prompt_user_selection("Customer Site", dicts, display)
    print(f"     CUSTOMER NAME     : {selected['customer_name']}")
    print(f"     OPERATING UNIT ID : {selected['operating_unit_id']}")
    return selected


# --------------------------------------------------
# Master lookup — chained validation
# Each step uses the value chosen in the previous step.
# --------------------------------------------------
def fetch_all_from_db(ordered_item: str, quantity: float) -> dict:
    print(f"\n[DB] Looking up data for item '{ordered_item}' qty={quantity} ...")

    # Step 1 — Inventory Item (user selects if multiple; up to 5 shown)
    item = fetch_inventory_item(ordered_item)
    inventory_item_id = item["inventory_item_id"]
    print(f"     INVENTORY_ITEM_ID : {inventory_item_id}")

    # Step 2 — Price List (chained on inventory_item_id from Step 1)
    price_details = fetch_price_details(ordered_item, quantity, inventory_item_id)
    print(f"     PRICE_LIST_ID     : {price_details['price_list_id']}")
    print(f"     UNIT_LIST_PRICE   : {price_details['unit_list_price']}")
    print(f"     UNIT_SELLING_PRICE: {price_details['unit_selling_price']}")

    # Step 3 — Payment Term (user selects if multiple; up to 5 shown)
    payment_term_id = fetch_payment_term_id()
    print(f"     PAYMENT_TERM_ID   : {payment_term_id}")

    # Step 4 — Sales Rep (user selects if multiple; up to 5 shown)
    salesrep = fetch_salesrep()
    print(f"     SALESREP_ID       : {salesrep['salesrep_id']}")

    # Step 5 — Customer / Ship-To Site (chained on ordered_item from Step 1)
    sites = fetch_customer_sites(ordered_item)
    print(f"     SOLD_TO_ORG_ID    : {sites['sold_to_org_id']}")
    print(f"     SHIP_TO_ORG_ID    : {sites['ship_to_org_id']}")

    return {
        "inventory_item_id":  inventory_item_id,
        "price_list_id":      price_details["price_list_id"],
        "unit_list_price":    price_details["unit_list_price"],
        "unit_selling_price": price_details["unit_selling_price"],
        "payment_term_id":    payment_term_id,
        "salesrep_id":        salesrep["salesrep_id"],
        "sold_to_org_id":     sites["sold_to_org_id"],
        "ship_to_org_id":     sites["ship_to_org_id"],
    }


# --------------------------------------------------
# Payload builder
# --------------------------------------------------
def create_payload(
    p_cust_po,
    p_item_id,
    p_ordered_item,
    p_qty,
    p_price,
    p_selling_price,
    p_payment_term_id,
    p_price_list_id,
    p_salesrep_id,
    p_ship_to_org,
    p_sold_to_org,
    p_operating_unit,
):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility":  "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup":   "STANDARD",
                "NLSLanguage":     "AMERICAN",
                "Org_Id":          "204"
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST":      "T",
                "P_RETURN_VALUES":      "T",
                "P_ACTION_COMMIT":      "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG":            "N",
                    "CUST_PO_NUMBER":          p_cust_po,
                    "ORDER_TYPE_ID":           ORDER_TYPE_ID,
                    "ORG_ID":                  ORG_ID,
                    "PAYMENT_TERM_ID":         p_payment_term_id,
                    "PRICE_LIST_ID":           p_price_list_id,
                    "SALESREP_ID":             p_salesrep_id,
                    "SHIP_TO_ORG_ID":          p_ship_to_org,
                    "SOLD_TO_ORG_ID":          p_sold_to_org,
                    "TRANSACTIONAL_CURR_CODE": "USD",
                    "OPERATION":               "CREATE"
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID":  p_item_id,
                        "ORDERED_ITEM":       p_ordered_item,
                        "ORDERED_QUANTITY":   p_qty,
                        "PAYMENT_TERM_ID":    p_payment_term_id,
                        "PRICE_LIST_ID":      p_price_list_id,
                        "UNIT_LIST_PRICE":    p_price,
                        "UNIT_SELLING_PRICE": p_selling_price,
                        "OPERATION":          "CREATE"
                    }
                },
                "P_RTRIM_DATA":     "n",
                "P_OPERATING_UNIT": p_operating_unit,
                "P_DEBUG_LEVEL":    10
            }
        }
    }


# --------------------------------------------------
# REST sender
# --------------------------------------------------
def send_order(payload):
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(
        BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=60
    )
    print("Status Code:", response.status_code)
    print("Response:", response.text)
    if response.status_code in (200, 201, 204):
        try:
            return response.json()
        except Exception:
            return response.text
    if response.status_code == 500:
        raise RuntimeError("Server connection error")
    response.raise_for_status()


def extract_order_header(result):
    if not isinstance(result, dict):
        return None, None
    hdr = result.get("X_HEADER_REC")
    if hdr is None:
        hdr = result.get("PROCESS_ORDER_Output", {}).get("X_HEADER_REC")
    if not isinstance(hdr, dict):
        return None, None
    return hdr.get("X_HEADER_REC.ORDER_NUMBER"), hdr.get("X_HEADER_REC.HEADER_ID")



# --------------------------------------------------
# GET ORDER — payload builder
# --------------------------------------------------
def create_get_order_payload(p_order_number: int) -> dict:
    """
    Build the payload for the GET_ORDER REST endpoint.
    Only P_ORDER_NUMBER is required; all other header fields are fixed constants.
    """
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility":  "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup":   "STANDARD",
                "NLSLanguage":     "AMERICAN",
                "Org_Id":          str(ORG_ID)
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST":      "T",
                "P_RETURN_VALUES":      "T",
                "P_ACTION_COMMIT":      "T",
                "P_ORDER_NUMBER":       p_order_number
            }
        }
    }


# --------------------------------------------------
# GET ORDER — REST caller
# --------------------------------------------------
def get_order(order_number: int) -> dict:
    """
    Call the GET_ORDER REST endpoint and return the parsed JSON response.
    Uses the same TLS adapter and credentials as PROCESS_ORDER.
    """
    payload = create_get_order_payload(order_number)
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    print(f"\n[REST] GET ORDER payload: {json.dumps(payload, indent=2)}")
    response = session.post(
        GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=60
    )
    print("Status Code:", response.status_code)
    print("Response:", response.text)
    if response.status_code in (200, 201, 204):
        try:
            return response.json()
        except Exception:
            return response.text
    if response.status_code == 500:
        raise RuntimeError("Server connection error")
    response.raise_for_status()


# --------------------------------------------------
# GET ORDER — print helper
# --------------------------------------------------
def print_order_details(result: dict):
    """
    Pretty-print the key header and line fields from a GET_ORDER response.
    Handles both flat (X_HEADER_REC at root) and nested (OutputParameters) shapes.
    """
    if not isinstance(result, dict):
        print("Response is not a JSON object.")
        return

    data       = result.get("OutputParameters", result)
    status     = data.get("X_RETURN_STATUS", "N/A")
    print(f"\n{'='*60}")
    print(f"  GET ORDER RESPONSE  |  Return Status: {status}")
    print(f"{'='*60}")

    # ── Messages ──────────────────────────────────────────
    messages_raw = data.get("X_MESSAGES", {})
    if isinstance(messages_raw, dict):
        items = messages_raw.get("X_MESSAGES_ITEM", [])
        if isinstance(items, dict):
            items = [items]
        for m in items:
            txt = m.get("MESSAGE_TEXT", "")
            if txt:
                print(f"  [MSG] {txt}")

    # ── Header ────────────────────────────────────────────
    hdr     = data.get("X_HEADER_REC",     {}) or {}
    hdr_val = data.get("X_HEADER_VAL_REC", {}) or {}

    print(f"\n  --- HEADER ---")
    header_fields = [
        ("Order Number",       hdr.get("ORDER_NUMBER")),
        ("Header ID",          hdr.get("HEADER_ID")),
        ("Customer PO",        hdr.get("CUST_PO_NUMBER")),
        ("Order Type",         hdr_val.get("ORDER_TYPE")         or hdr.get("ORDER_TYPE_ID")),
        ("Order Date",         hdr.get("ORDERED_DATE")),
        ("Customer",           hdr_val.get("SOLD_TO_ORG")        or hdr.get("SOLD_TO_ORG_ID")),
        ("Ship To",            hdr_val.get("SHIP_TO_ORG")        or hdr.get("SHIP_TO_ORG_ID")),
        ("Bill To",            hdr_val.get("INVOICE_TO_ORG")     or hdr.get("INVOICE_TO_ORG_ID")),
        ("Currency",           hdr.get("TRANSACTIONAL_CURR_CODE")),
        ("Payment Term",       hdr_val.get("PAYMENT_TERM")       or hdr.get("PAYMENT_TERM_ID")),
        ("Price List",         hdr_val.get("PRICE_LIST")         or hdr.get("PRICE_LIST_ID")),
        ("Salesrep",           hdr_val.get("SALESREP")           or hdr.get("SALESREP_ID")),
        ("Booked Flag",        hdr.get("BOOKED_FLAG")),
        ("Flow Status",        hdr.get("FLOW_STATUS_CODE")),
        ("Return Status",      hdr.get("RETURN_STATUS")),
    ]
    for label, val in header_fields:
        if val not in (None, "", "N/A"):
            print(f"    {label:<22}: {val}")

    # ── Lines ─────────────────────────────────────────────
    line_tbl     = data.get("X_LINE_TBL",     {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}

    raw_lines     = line_tbl.get("P_LINE_TBL_ITEM",     [])
    raw_line_vals = line_val_tbl.get("P_LINE_VAL_TBL_ITEM", [])

    if isinstance(raw_lines,     dict): raw_lines     = [raw_lines]
    if isinstance(raw_line_vals, dict): raw_line_vals = [raw_line_vals]

    if raw_lines:
        print(f"\n  --- LINES ({len(raw_lines)}) ---")
        for i, line in enumerate(raw_lines):
            val = raw_line_vals[i] if i < len(raw_line_vals) else {}
            print(f"\n  Line {line.get('LINE_NUMBER', i+1)}")
            line_fields = [
                ("Line ID",            line.get("LINE_ID")),
                ("Item",               line.get("ORDERED_ITEM")),
                ("Item Description",   val.get("INVENTORY_ITEM")),
                ("Qty Ordered",        line.get("ORDERED_QUANTITY")),
                ("UOM",                line.get("ORDER_QUANTITY_UOM")),
                ("Unit List Price",    line.get("UNIT_LIST_PRICE")),
                ("Unit Selling Price", line.get("UNIT_SELLING_PRICE")),
                ("Line Type",          val.get("LINE_TYPE")  or line.get("LINE_TYPE_ID")),
                ("Payment Term",       val.get("PAYMENT_TERM")),
                ("Flow Status",        line.get("FLOW_STATUS_CODE")),
                ("Return Status",      line.get("RETURN_STATUS")),
                ("Ship To",            val.get("SHIP_TO_ORG")),
                ("Request Date",       line.get("REQUEST_DATE")),
                ("Promise Date",       line.get("PROMISE_DATE")),
            ]
            for label, v in line_fields:
                if v not in (None, "", "N/A"):
                    print(f"    {label:<22}: {v}")
    else:
        print("\n  No line details found in response.")

    print(f"\n{'='*60}\n")


# --------------------------------------------------
# GET ORDER — core flow
# --------------------------------------------------
def process_get_order(order_number: int, output_fn):
    """
    Fetch and display a sales order by order number.
    output_fn is called for top-level status messages (print or speak).
    """
    output_fn(f"Fetching order {order_number} ...")
    try:
        result = get_order(order_number)
    except Exception as e:
        output_fn(f"GET ORDER failed: {e}")
        return None

    print_order_details(result)
    output_fn(f"Order {order_number} retrieved successfully.")
    return result


# --------------------------------------------------
# Input helpers
# --------------------------------------------------
def ask_text(prompt):
    while True:
        val = input(prompt).strip()
        if not val:
            print("Enter a value, or type 'exit' to quit.")
            continue
        if val.lower() in ("exit", "quit", "stop"):
            return None
        return val


def ask_voice(prompt):
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice support not enabled")
    while True:
        speak(prompt)
        val = recognize_speech_vosk()
        print("Recognized:", val)
        if not val:
            speak("I didn't catch that. Try again.")
            continue
        if val.strip().lower() in ("exit", "quit", "stop"):
            return None
        return val


# --------------------------------------------------
# Core order flow
# --------------------------------------------------
def process_order(cpo: str, ordered_item: str, qty: float, output_fn):
    try:
        db = fetch_all_from_db(ordered_item, qty)
    except Exception as e:
        output_fn(f"DB lookup failed: {e}")
        return

    payload = create_payload(
        p_cust_po         = cpo,
        p_item_id         = db["inventory_item_id"],
        p_ordered_item    = ordered_item,
        p_qty             = qty,
        p_price           = db["unit_list_price"],
        p_selling_price   = db["unit_selling_price"],
        p_payment_term_id = db["payment_term_id"],
        p_price_list_id   = db["price_list_id"],
        p_salesrep_id     = db["salesrep_id"],
        p_ship_to_org     = db["ship_to_org_id"],
        p_sold_to_org     = db["sold_to_org_id"],
        p_operating_unit  = OPERATING_UNIT,
    )

    print("\n[REST] Sending payload:", json.dumps(payload, indent=2))

    try:
        result = send_order(payload)
    except Exception as e:
        output_fn(f"Order submission failed: {e}")
        return

    order_number, header_id = extract_order_header(result)
    if order_number and header_id:
        msg = f"Order created. ORDER_NUMBER={order_number}, HEADER_ID={header_id}"
    else:
        msg = "Order submitted, but ORDER_NUMBER / HEADER_ID not found in response."
    output_fn(msg)
    print(msg)


# --------------------------------------------------
# Text chat
# --------------------------------------------------
def text_chat():
    print("Sales Order chatbot [text mode].")
    print("Commands: 'create' to create a new order, 'get' to retrieve an existing order, 'exit' to quit.\n")

    while True:
        # ── Ask user which action they want ──────────────
        action = ask_text("Action (create / get): ")
        if action is None:
            break
        action = action.strip().lower()

        if action not in ("create", "get"):
            print("  Please type 'create' or 'get'.")
            continue

        # ── GET ORDER ─────────────────────────────────────
        if action == "get":
            order_num_str = ask_text("Enter Order Number to retrieve: ")
            if order_num_str is None:
                break
            order_num = parse_numeric_value(order_num_str, allow_float=False)
            if order_num is None:
                print("Invalid order number. Try again.")
                continue
            process_get_order(int(order_num), print)
            continue

        # ── CREATE ORDER ──────────────────────────────────
        cpo = ask_text("Customer PO Number: ")
        if cpo is None:
            break

        ordered_item = ask_text("Ordered Item (e.g. CM94532): ")
        if ordered_item is None:
            break

        qty_text = ask_text("Ordered Quantity: ")
        if qty_text is None:
            break

        qty = parse_numeric_value(qty_text, allow_float=False)
        if qty is None:
            print("Invalid quantity. Try again.")
            continue

        process_order(cpo, ordered_item.upper(), float(qty), print)


# --------------------------------------------------
# Voice chat
# --------------------------------------------------
def voice_chat():
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice packages not installed")
    speak("Sales order voice chatbot started. Say exit to stop.")
    speak("Say create to create an order, or say get to retrieve an order.")

    while True:
        # ── Ask user which action they want ──────────────
        action = ask_voice("Say create to create an order, or get to retrieve an order.")
        if action is None:
            break
        action = action.strip().lower()

        if "get" in action:
            order_num_txt = ask_voice("Please say the order number to retrieve.")
            if order_num_txt is None:
                break
            order_num = parse_numeric_value(order_num_txt, allow_float=False)
            if order_num is None:
                speak("Invalid order number. Please try again.")
                continue
            process_get_order(int(order_num), speak)
            continue

        if "create" not in action:
            speak("I did not understand. Please say create or get.")
            continue

        # ── CREATE ORDER ──────────────────────────────────
        cpo = ask_voice("Please say Customer PO Number.")
        if cpo is None:
            break

        ordered_item = ask_voice("Please say the ordered item number.")
        if ordered_item is None:
            break

        qty_txt = ask_voice("Please say the ordered quantity.")
        if qty_txt is None:
            break

        qty = parse_numeric_value(qty_txt, allow_float=False)
        if qty is None:
            speak("Invalid quantity. Please try again.")
            continue

        process_order(cpo, ordered_item.upper(), float(qty), speak)


# --------------------------------------------------
# Entry point
# --------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SalesOrderBot - item+qty only, rest from DB")
    parser.add_argument("--mode", choices=["text", "voice"], default="text")
    args = parser.parse_args()

    if args.mode == "voice":
        voice_chat()
    else:
        text_chat()