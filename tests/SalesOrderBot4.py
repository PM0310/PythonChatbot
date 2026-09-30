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
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
HEADERS       = {"Content-Type": "application/json", "Accept": "application/json"}

# Fixed / org-level constants
ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Centroid Manufacturing"


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
# DB Lookups
# --------------------------------------------------

def fetch_inventory_item_id(ordered_item: str, org_id: int = ORG_ID) -> int:
    sql = """
        SELECT INVENTORY_ITEM_ID
          FROM MTL_SYSTEM_ITEMS_B
         WHERE SEGMENT1        = :ordered_item
           AND ORGANIZATION_ID = :org_id
           AND ROWNUM          = 1
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, ordered_item=ordered_item.upper(), org_id=org_id)
            row = cur.fetchone()
    if not row:
        raise ValueError(
            f"Item '{ordered_item}' not found in MTL_SYSTEM_ITEMS_B "
            f"for ORGANIZATION_ID={org_id}"
        )
    return int(row[0])


def fetch_price_details(ordered_item: str, quantity: float, org_id: int = ORG_ID) -> dict:
    """
    Strategy 1: Fetch price list assigned to the Order Type (ORDER_TYPE_ID).
    This ensures the price list is valid for the order being created.

    Strategy 2 (fallback): Fetch price list assigned to customer account site.

    Strategy 3 (last resort): Any active USD price list for this item.
    """

    # Strategy 1: Price list tied to the Order Type used in the payload
    sql_order_type = """
        SELECT qlh.LIST_HEADER_ID    AS price_list_id,
               qll.OPERAND           AS unit_list_price
          FROM OE_ORDER_TYPES_V       oot
          JOIN QP_LIST_HEADERS_B      qlh
               ON  qlh.LIST_HEADER_ID = oot.PRICE_LIST_ID
          JOIN QP_LIST_LINES          qll
               ON  qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES  qpa
               ON  qpa.LIST_LINE_ID      = qll.LIST_LINE_ID
               AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE = (
                       SELECT TO_CHAR(INVENTORY_ITEM_ID)
                         FROM MTL_SYSTEM_ITEMS_B
                        WHERE SEGMENT1        = :ordered_item
                          AND ORGANIZATION_ID = :org_id
                          AND ROWNUM          = 1
                   )
         WHERE oot.ORDER_TYPE_ID = :order_type_id
           AND qlh.ACTIVE_FLAG   = 'Y'
           AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE)
           AND (qll.END_DATE_ACTIVE   IS NULL OR qll.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM = 1
    """

    # Strategy 2: Price list from customer account site (BILL_TO)
    sql_customer = """
        SELECT qlh.LIST_HEADER_ID    AS price_list_id,
               qll.OPERAND           AS unit_list_price
          FROM HZ_CUST_ACCT_SITES_ALL  hcas
          JOIN HZ_CUST_SITE_USES_ALL   hcsu
               ON  hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
               AND hcsu.SITE_USE_CODE      = 'BILL_TO'
               AND hcsu.STATUS             = 'A'
          JOIN QP_LIST_HEADERS_B          qlh
               ON  qlh.LIST_HEADER_ID      = hcsu.PRICE_LIST_ID
          JOIN QP_LIST_LINES              qll
               ON  qll.LIST_HEADER_ID      = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES      qpa
               ON  qpa.LIST_LINE_ID        = qll.LIST_LINE_ID
               AND qpa.PRODUCT_ATTRIBUTE   = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE  = (
                       SELECT TO_CHAR(INVENTORY_ITEM_ID)
                         FROM MTL_SYSTEM_ITEMS_B
                        WHERE SEGMENT1        = :ordered_item
                          AND ORGANIZATION_ID = :org_id
                          AND ROWNUM          = 1
                   )
         WHERE hcas.ORG_ID      = :org_id
           AND hcas.STATUS      = 'A'
           AND qlh.ACTIVE_FLAG  = 'Y'
           AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM = 1
    """

    # Strategy 3: Any active USD price list containing this item (last resort)
    sql_generic = """
        SELECT qlh.LIST_HEADER_ID    AS price_list_id,
               qll.OPERAND           AS unit_list_price
          FROM QP_LIST_HEADERS_B     qlh
          JOIN QP_LIST_LINES         qll
               ON  qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES  qpa
               ON  qpa.LIST_LINE_ID      = qll.LIST_LINE_ID
               AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE = (
                       SELECT TO_CHAR(INVENTORY_ITEM_ID)
                         FROM MTL_SYSTEM_ITEMS_B
                        WHERE SEGMENT1        = :ordered_item
                          AND ORGANIZATION_ID = :org_id
                          AND ROWNUM          = 1
                   )
         WHERE qlh.ACTIVE_FLAG    = 'Y'
           AND qlh.LIST_TYPE_CODE = 'PRL'
           AND qlh.CURRENCY_CODE  = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE)
           AND (qll.END_DATE_ACTIVE   IS NULL OR qll.END_DATE_ACTIVE   >= SYSDATE)
         ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
         FETCH FIRST 1 ROWS ONLY
    """

    row = None

    with get_connection() as conn:
        with conn.cursor() as cur:

            # Try Strategy 1: Order Type price list
            cur.execute(sql_order_type,
                        ordered_item=ordered_item.upper(),
                        org_id=org_id,
                        order_type_id=ORDER_TYPE_ID)
            row = cur.fetchone()
            if row:
                print(f"     PRICE LIST SOURCE : Order Type ({ORDER_TYPE_ID})")

            # Try Strategy 2: Customer site price list
            if not row:
                cur.execute(sql_customer,
                            ordered_item=ordered_item.upper(),
                            org_id=org_id)
                row = cur.fetchone()
                if row:
                    print(f"     PRICE LIST SOURCE : Customer Bill-To Site")

            # Try Strategy 3: Generic active price list
            if not row:
                cur.execute(sql_generic,
                            ordered_item=ordered_item.upper(),
                            org_id=org_id)
                row = cur.fetchone()
                if row:
                    print(f"     PRICE LIST SOURCE : Generic Active Price List")

    if not row:
        raise ValueError(
            f"No valid price list found for item '{ordered_item}' in ORG_ID={org_id}. "
            f"Please check QP_LIST_HEADERS_B and QP_PRICING_ATTRIBUTES."
        )

    price_list_id    = int(row[0])
    unit_list_price  = float(row[1])

    return {
        "price_list_id":      price_list_id,
        "unit_list_price":    unit_list_price,
        "unit_selling_price": unit_list_price,   # selling = list price by default
    }


def fetch_payment_term_id(ordered_item: str, org_id: int = ORG_ID) -> int:
    # First try: get payment term from customer bill-to site
    sql_customer = """
        SELECT hcsu.PAYMENT_TERM_ID
          FROM HZ_CUST_ACCT_SITES_ALL hcas
          JOIN HZ_CUST_SITE_USES_ALL  hcsu
               ON  hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
         WHERE hcsu.SITE_USE_CODE      = 'BILL_TO'
           AND hcsu.STATUS             = 'A'
           AND hcas.STATUS             = 'A'
           AND hcas.ORG_ID             = :org_id
           AND hcsu.PAYMENT_TERM_ID IS NOT NULL
           AND ROWNUM                  = 1
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_customer, org_id=org_id)
            row = cur.fetchone()

    if row and row[0] is not None:
        return int(row[0])

    # Fallback: first active term from RA_TERMS_B
    sql_fallback = """
        SELECT TERM_ID
          FROM RA_TERMS_B
         WHERE ENABLED_FLAG = 'Y'
           AND ROWNUM       = 1
         ORDER BY TERM_ID
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_fallback)
            row = cur.fetchone()

    if not row or row[0] is None:
        raise ValueError("Could not derive PAYMENT_TERM_ID from the database.")
    return int(row[0])


def fetch_salesrep_and_org_ids(ordered_item: str, org_id: int = ORG_ID) -> dict:
    """
    Fetches SALESREP_ID, SOLD_TO_ORG_ID, and SHIP_TO_ORG_ID.

    SOLD_TO_ORG_ID = HZ_CUST_ACCOUNTS.CUST_ACCOUNT_ID
    SHIP_TO_ORG_ID = HZ_CUST_SITE_USES_ALL.SITE_USE_ID (primary active SHIP_TO site)

    Uses a proper join across MTL_SYSTEM_ITEMS_B, HZ_CUST_ACCT_SITES_ALL,
    HZ_CUST_SITE_USES_ALL, HZ_CUST_ACCOUNTS, and HZ_PARTIES to get both IDs
    tied to the correct item and org.
    """

    # Fetch SOLD_TO_ORG_ID and SHIP_TO_ORG_ID
    sql_org_ids = """
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
           AND ROWNUM              = 1
    """

    # Fetch SALESREP_ID
    sql_salesrep = """
        SELECT SALESREP_ID
          FROM JTF_RS_SALESREPS
         WHERE ORG_ID          = :org_id
           AND STATUS          = 'A'
           AND END_DATE_ACTIVE IS NULL
           AND ROWNUM          = 1
         ORDER BY SALESREP_ID
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_org_ids, ordered_item=ordered_item.upper(), org_id=org_id)
            row_org = cur.fetchone()

            cur.execute(sql_salesrep, org_id=org_id)
            row_s = cur.fetchone()

    if not row_org:
        raise ValueError(
            f"No active primary SHIP_TO site found for item '{ordered_item}' "
            f"and ORG_ID={org_id}. "
            f"Check HZ_CUST_ACCT_SITES_ALL / HZ_CUST_SITE_USES_ALL."
        )

    sold_to_org_id, ship_to_org_id, customer_name, operating_unit_id = row_org

    if not row_s or row_s[0] is None:
        raise ValueError(f"No active SALESREP found for ORG_ID={org_id}.")

    # Print extra info for debugging
    print(f"     CUSTOMER NAME     : {customer_name}")
    print(f"     OPERATING UNIT ID : {operating_unit_id}")

    return {
        "salesrep_id":    int(row_s[0]),
        "sold_to_org_id": int(sold_to_org_id),
        "ship_to_org_id": int(ship_to_org_id),
    }


# --------------------------------------------------
# Master lookup
# --------------------------------------------------
def fetch_all_from_db(ordered_item: str, quantity: float) -> dict:
    print(f"\n[DB] Looking up data for item '{ordered_item}' qty={quantity} ...")

    inventory_item_id = fetch_inventory_item_id(ordered_item)
    print(f"     INVENTORY_ITEM_ID : {inventory_item_id}")

    price_details = fetch_price_details(ordered_item, quantity)
    print(f"     PRICE_LIST_ID     : {price_details['price_list_id']}")
    print(f"     UNIT_LIST_PRICE   : {price_details['unit_list_price']}")
    print(f"     UNIT_SELLING_PRICE: {price_details['unit_selling_price']}")

    payment_term_id = fetch_payment_term_id(ordered_item)
    print(f"     PAYMENT_TERM_ID   : {payment_term_id}")

    org_ids = fetch_salesrep_and_org_ids(ordered_item)
    print(f"     SALESREP_ID       : {org_ids['salesrep_id']}")
    print(f"     SOLD_TO_ORG_ID    : {org_ids['sold_to_org_id']}")
    print(f"     SHIP_TO_ORG_ID    : {org_ids['ship_to_org_id']}")

    return {
        "inventory_item_id":  inventory_item_id,
        "price_list_id":      price_details["price_list_id"],
        "unit_list_price":    price_details["unit_list_price"],
        "unit_selling_price": price_details["unit_selling_price"],
        "payment_term_id":    payment_term_id,
        "salesrep_id":        org_ids["salesrep_id"],
        "sold_to_org_id":     org_ids["sold_to_org_id"],
        "ship_to_org_id":     org_ids["ship_to_org_id"],
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
    print("You only need to provide: Customer PO, Ordered Item, and Quantity.")
    print("All other values are fetched automatically from the database.\n")

    while True:
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
    speak("You only need to say the Customer PO, item name, and quantity.")

    while True:
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