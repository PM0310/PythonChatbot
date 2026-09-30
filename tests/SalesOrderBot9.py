import os
import sys
import json
import argparse
import requests
import ssl
import urllib3
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
import oracledb
from groq import Groq

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

# --------------------------------------------------
# Groq AI Configuration
# --------------------------------------------------
GROQ_API_KEY   = "REDACTED_SECRET"
GROQ_MODEL     = "llama-3.1-8b-instant"

_groq_client = None

def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client

def groq_extract_intent(user_input: str) -> dict:
    client = get_groq_client()
    system = (
        "You are a sales order data extractor for an ERP system. "
        "Given a user message, extract the following fields as JSON and nothing else. "
        "If a field is not mentioned, return null for it.\n"
        "{\n"
        '  "action": "create" | "get" | "unknown",\n'
        '  "cpo": "<Customer PO number string or null>",\n'
        '  "ordered_item": "<item code string or null>",\n'
        '  "quantity": <number or null>,\n'
        '  "order_number": <integer or null>,\n'
        '  "salesrep_id": <integer or null>,\n'
        '  "payment_term_id": <integer or null>,\n'
        '  "price_list_id": <integer or null>,\n'
        '  "unit_list_price": <number or null>,\n'
        '  "unit_selling_price": <number or null>,\n'
        '  "sold_to_org_id": <integer or null>,\n'
        '  "ship_to_org_id": <integer or null>,\n'
        '  "inventory_item_id": <integer or null>\n'
        "}\n\n"
        "Rules:\n"
        "- action=create when the user wants to place / create / submit a new order.\n"
        "- action=get when the user wants to look up / fetch / retrieve an existing order.\n"
        "- Extract fields only when explicitly stated in the prompt.\n"
        "- Return ONLY valid JSON — no markdown, no explanation."
    )
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_input}
            ],
            max_tokens=256,
            temperature=0.1,
        )
        reply = response.choices[0].message.content.strip()
        clean = reply.strip("```json").strip("```").strip()
        return json.loads(clean)
    except Exception:
        return {"action": "unknown"}

def groq_clarify(conversation_history: list, missing_fields: list) -> str:
    system = (
        "You are a friendly sales order assistant helping a user create or retrieve "
        "a sales order in an ERP system. Ask a short, natural question to collect "
        "the following missing information. Be concise and conversational.\n"
        f"Missing fields: {', '.join(missing_fields)}"
    )
    try:
        response = get_groq_client().chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system}] + conversation_history,
            max_tokens=128,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return f"I still need the following information: {', '.join(missing_fields)}."

# --------------------------------------------------
# DB & REST Configuration
# --------------------------------------------------
DB_USER     = "apps"
DB_PASSWORD = "apps"
DB_DSN      = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)

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

ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Centroid Manufacturing"
MAX_CHOICES    = 10

def parse_numeric_value(val, allow_float=False):
    if val is None: return None
    val = str(val).strip()
    try: return float(val) if allow_float else int(val)
    except ValueError: pass
    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try: return float(digits) if allow_float else int(digits)
        except ValueError: pass
    return None

def prompt_user_selection(label: str, rows: list, display_fn) -> dict:
    if len(rows) == 1:
        print(f"     [AUTO-SELECTED] {label}: {display_fn(rows[0])}")
        return rows[0]
    print(f"\n  Multiple {label} records found. Please choose one:")
    for idx, row in enumerate(rows, start=1):
        print(f"    [{idx}] {display_fn(row)}")
    while True:
        raw = input(f"  Enter choice (1-{len(rows)}) or type 'quit' to exit: ").strip()
        if raw.lower() in ("exit", "quit", "stop"):
            print("Exiting chat...")
            sys.exit(0)
        try:
            choice = int(raw)
            if 1 <= choice <= len(rows):
                selected = rows[choice - 1]
                print(f"     [SELECTED] {label}: {display_fn(selected)}")
                return selected
        except ValueError: pass
        print(f"  Invalid input. Enter a number between 1 and {len(rows)}.")


# --------------------------------------------------
# DB Core Functions (Return Rows Only)
# --------------------------------------------------
def get_inventory_item_rows(ordered_item: str, org_id: int = ORG_ID) -> list:
    sql = """
        SELECT * FROM (
            SELECT DISTINCT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, ORGANIZATION_ID
              FROM MTL_SYSTEM_ITEMS_B
             WHERE SEGMENT1 = :ordered_item AND ORGANIZATION_ID = :org_id
             ORDER BY INVENTORY_ITEM_ID
        ) WHERE ROWNUM <= :max_rows
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=ordered_item.upper(), org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
    if not rows: raise ValueError(f"Item '{ordered_item}' not found.")
    return [{"inventory_item_id": int(r[0]), "segment1": r[1], "description": r[2] or "", "organization_id": int(r[3])} for r in rows]

def get_price_details_rows(ordered_item: str, quantity: float, inventory_item_id: int, org_id: int = ORG_ID) -> list:
    sql_order_type = """
        SELECT * FROM (
            SELECT DISTINCT qlh.LIST_HEADER_ID AS price_list_id, qlt.NAME AS price_list_name, qll.OPERAND AS unit_list_price
              FROM OE_ORDER_TYPES_V oot, QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa
             WHERE oot.PRICE_LIST_ID = qlh.LIST_HEADER_ID AND qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
               AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE = :item_id_str AND oot.ORDER_TYPE_ID = :order_type_id AND qlh.ACTIVE_FLAG = 'Y' AND qlh.CURRENCY_CODE = 'USD'
               AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE) AND (qlh.END_DATE_ACTIVE IS NULL OR qlh.END_DATE_ACTIVE >= SYSDATE)
               AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE) AND (qll.END_DATE_ACTIVE IS NULL OR qll.END_DATE_ACTIVE >= SYSDATE)
             ORDER BY qll.OPERAND DESC
        ) WHERE ROWNUM <= :max_rows
    """
    sql_customer = """
        SELECT * FROM (
            SELECT DISTINCT qlh.LIST_HEADER_ID AS price_list_id, qlt.NAME AS price_list_name, qll.OPERAND AS unit_list_price
              FROM HZ_CUST_ACCT_SITES_ALL hcas, HZ_CUST_SITE_USES_ALL hcsu, QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa
             WHERE hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID AND hcsu.SITE_USE_CODE = 'BILL_TO' AND hcsu.STATUS = 'A'
               AND qlh.LIST_HEADER_ID = hcsu.PRICE_LIST_ID AND qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
               AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
               AND qpa.PRODUCT_ATTR_VALUE = :item_id_str AND hcas.ORG_ID = :org_id AND hcas.STATUS = 'A' AND qlh.ACTIVE_FLAG = 'Y' AND qlh.CURRENCY_CODE = 'USD'
               AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE) AND (qlh.END_DATE_ACTIVE IS NULL OR qlh.END_DATE_ACTIVE >= SYSDATE)
             ORDER BY qll.OPERAND DESC
        ) WHERE ROWNUM <= :max_rows
    """
    sql_generic = """
        SELECT * FROM (
            SELECT DISTINCT qlh.LIST_HEADER_ID AS price_list_id, qlt.NAME AS price_list_name, qll.OPERAND AS unit_list_price
              FROM QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa
             WHERE qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG') AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
               AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1' AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
               AND qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL' AND qlh.CURRENCY_CODE = 'USD'
               AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE) AND (qlh.END_DATE_ACTIVE IS NULL OR qlh.END_DATE_ACTIVE >= SYSDATE)
               AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE) AND (qll.END_DATE_ACTIVE IS NULL OR qll.END_DATE_ACTIVE >= SYSDATE)
             ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
        ) WHERE ROWNUM <= :max_rows
    """
    item_id_str = str(inventory_item_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_order_type, item_id_str=item_id_str, order_type_id=ORDER_TYPE_ID, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
        if not rows:
            cur.execute(sql_customer, item_id_str=item_id_str, org_id=org_id, max_rows=MAX_CHOICES)
            rows = cur.fetchall()
        if not rows:
            cur.execute(sql_generic, item_id_str=item_id_str, max_rows=MAX_CHOICES)
            rows = cur.fetchall()
    if not rows: raise ValueError("No valid price list found.")
    return [{"price_list_id": int(r[0]), "price_list_name": r[1] or "", "unit_list_price": float(r[2])} for r in rows]

def get_payment_term_rows(org_id: int = ORG_ID) -> list:
    sql_customer = """
        SELECT * FROM (
            SELECT DISTINCT hcsu.PAYMENT_TERM_ID, rt.NAME AS term_name
              FROM HZ_CUST_ACCT_SITES_ALL hcas, HZ_CUST_SITE_USES_ALL hcsu, RA_TERMS_B rt
             WHERE hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID AND rt.TERM_ID = hcsu.PAYMENT_TERM_ID
               AND hcsu.SITE_USE_CODE = 'BILL_TO' AND hcsu.STATUS = 'A' AND hcas.STATUS = 'A' AND hcas.ORG_ID = :org_id AND hcsu.PAYMENT_TERM_ID IS NOT NULL
             ORDER BY hcsu.PAYMENT_TERM_ID
        ) WHERE ROWNUM <= :max_rows
    """
    sql_fallback = """
        SELECT * FROM (SELECT DISTINCT TERM_ID, NAME FROM RA_TERMS_B WHERE ENABLED_FLAG = 'Y' ORDER BY TERM_ID) WHERE ROWNUM <= :max_rows
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_customer, org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
        if not rows:
            cur.execute(sql_fallback, max_rows=MAX_CHOICES)
            rows = cur.fetchall()
    if not rows: raise ValueError("Could not derive PAYMENT_TERM_ID.")
    return [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]

def get_salesrep_rows(org_id: int = ORG_ID) -> list:
    sql = """
        SELECT * FROM (
            SELECT DISTINCT jrs.SALESREP_ID, jrs.NAME AS salesrep_name FROM JTF_RS_SALESREPS jrs
             WHERE jrs.ORG_ID = :org_id AND jrs.STATUS = 'A' AND jrs.END_DATE_ACTIVE IS NULL ORDER BY jrs.SALESREP_ID
        ) WHERE ROWNUM <= :max_rows
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
    if not rows: raise ValueError("No active SALESREP found.")
    return [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]

def get_customer_site_rows(ordered_item: str, org_id: int = ORG_ID) -> list:
    sql = """
        SELECT * FROM (
            SELECT DISTINCT hca.CUST_ACCOUNT_ID AS sold_to_org_id, hcsu.SITE_USE_ID AS ship_to_org_id, hp.PARTY_NAME AS customer_name, hcas.ORG_ID AS operating_unit_id
              FROM MTL_SYSTEM_ITEMS_B msi, HZ_CUST_ACCT_SITES_ALL hcas, HZ_CUST_SITE_USES_ALL hcsu, HZ_CUST_ACCOUNTS hca, HZ_PARTIES hp
             WHERE hcas.ORG_ID = :org_id AND hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID AND hca.CUST_ACCOUNT_ID = hcas.CUST_ACCOUNT_ID AND hp.PARTY_ID = hca.PARTY_ID
               AND msi.SEGMENT1 = :ordered_item AND msi.ORGANIZATION_ID = :org_id AND hcsu.SITE_USE_CODE = 'SHIP_TO'
               AND hcsu.STATUS = 'A' AND hcas.STATUS = 'A' AND hca.STATUS = 'A' AND hcsu.PRIMARY_FLAG = 'Y'
             ORDER BY hp.PARTY_NAME
        ) WHERE ROWNUM <= :max_rows
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=ordered_item.upper(), org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
    if not rows: raise ValueError("No active primary SHIP_TO site found.")
    return [{"sold_to_org_id": int(r[0]), "ship_to_org_id": int(r[1]), "customer_name": r[2] or "", "operating_unit_id": int(r[3])} for r in rows]


# --------------------------------------------------
# CLI Database Resolvers
# --------------------------------------------------
def fetch_inventory_item(ordered_item: str, org_id: int = ORG_ID) -> dict:
    rows = get_inventory_item_rows(ordered_item, org_id)
    return prompt_user_selection("Inventory Item", rows, lambda r: f"ID={r['inventory_item_id']}  Segment={r['segment1']}  Desc={r['description']}")

def fetch_price_details(ordered_item: str, quantity: float, inventory_item_id: int, org_id: int = ORG_ID) -> dict:
    rows = get_price_details_rows(ordered_item, quantity, inventory_item_id, org_id)
    selected = prompt_user_selection("Price List", rows, lambda r: f"ID={r['price_list_id']}  Name={r['price_list_name']}  Price={r['unit_list_price']}")
    return {"price_list_id": selected["price_list_id"], "unit_list_price": selected["unit_list_price"], "unit_selling_price": selected["unit_list_price"]}

def fetch_payment_term_id(org_id: int = ORG_ID) -> int:
    rows = get_payment_term_rows(org_id)
    return prompt_user_selection("Payment Term", rows, lambda r: f"ID={r['term_id']}  Name={r['term_name']}")["term_id"]

def fetch_salesrep(org_id: int = ORG_ID) -> dict:
    rows = get_salesrep_rows(org_id)
    return prompt_user_selection("Sales Rep", rows, lambda r: f"ID={r['salesrep_id']}  Name={r['salesrep_name']}")

def fetch_customer_sites(ordered_item: str, org_id: int = ORG_ID) -> dict:
    rows = get_customer_site_rows(ordered_item, org_id)
    selected = prompt_user_selection("Customer Site", rows, lambda r: f"Customer={r['customer_name']}  SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}")
    return selected

def fetch_all_from_db(state: dict) -> dict:
    ordered_item = state.get("ordered_item")
    quantity = state.get("quantity")
    if state.get("inventory_item_id"): inventory_item_id = state["inventory_item_id"]
    else: inventory_item_id = fetch_inventory_item(ordered_item)["inventory_item_id"]

    if state.get("price_list_id") and state.get("unit_list_price") is not None:
        price_list_id = state["price_list_id"]
        unit_list_price = state["unit_list_price"]
        unit_selling_price = state.get("unit_selling_price", unit_list_price)
    else:
        pd = fetch_price_details(ordered_item, quantity, inventory_item_id)
        price_list_id, unit_list_price, unit_selling_price = pd["price_list_id"], pd["unit_list_price"], pd["unit_selling_price"]

    if state.get("payment_term_id"): payment_term_id = state["payment_term_id"]
    else: payment_term_id = fetch_payment_term_id()

    if state.get("salesrep_id"): salesrep_id = state["salesrep_id"]
    else: salesrep_id = fetch_salesrep()["salesrep_id"]

    if state.get("sold_to_org_id") and state.get("ship_to_org_id"):
        sold_to_org_id, ship_to_org_id = state["sold_to_org_id"], state["ship_to_org_id"]
    else:
        sites = fetch_customer_sites(ordered_item)
        sold_to_org_id, ship_to_org_id = sites["sold_to_org_id"], sites["ship_to_org_id"]

    return {
        "inventory_item_id": inventory_item_id, "price_list_id": price_list_id, "unit_list_price": unit_list_price,
        "unit_selling_price": unit_selling_price, "payment_term_id": payment_term_id, "salesrep_id": salesrep_id,
        "sold_to_org_id": sold_to_org_id, "ship_to_org_id": ship_to_org_id,
    }


# --------------------------------------------------
# Payload & Rest
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
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty,
                        "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price,
                        "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                    }
                },
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

def extract_order_header(result):
    if not isinstance(result, dict): return None, None
    hdr = result.get("X_HEADER_REC") or result.get("PROCESS_ORDER_Output", {}).get("X_HEADER_REC")
    if not isinstance(hdr, dict): return None, None
    return hdr.get("X_HEADER_REC.ORDER_NUMBER"), hdr.get("X_HEADER_REC.HEADER_ID")

def get_order(order_number: int) -> dict:
    payload = {"PROCESS_ORDER_Input": {"RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": str(ORG_ID)}, "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T", "P_ORDER_NUMBER": order_number}}}
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=60)
    if response.status_code in (200, 201, 204):
        try: return response.json()
        except Exception: return response.text
    response.raise_for_status()

# --------------------------------------------------
# CLI Chat Loop
# --------------------------------------------------
def ask_text(prompt):
    while True:
        val = input(prompt).strip()
        if not val: continue
        if val.lower() in ("exit", "quit", "stop"):
            print("Exiting chat...")
            sys.exit(0)
        return val

def process_order(state: dict, output_fn):
    try: db = fetch_all_from_db(state)
    except Exception as e: output_fn(f"DB lookup failed: {e}"); return

    payload = create_payload(
        state.get("cpo"), db["inventory_item_id"], state.get("ordered_item"), state.get("quantity"),
        db["unit_list_price"], db["unit_selling_price"], db["payment_term_id"], db["price_list_id"],
        db["salesrep_id"], db["ship_to_org_id"], db["sold_to_org_id"], OPERATING_UNIT
    )
    try:
        result = send_order(payload)
        order_number, header_id = extract_order_header(result)
        if order_number: output_fn(f"Order created. ORDER_NUMBER={order_number}, HEADER_ID={header_id}")
        else: output_fn("Order submitted, but ORDER_NUMBER not found.")
    except Exception as e: output_fn(f"Order submission failed: {e}")

def process_get_order(order_number: int, output_fn):
    try:
        result = get_order(order_number)
        output_fn(f"Order {order_number} retrieved successfully.")
        print(json.dumps(result, indent=2))
    except Exception as e:
        output_fn(f"GET ORDER failed: {e}")

def text_chat():
    print("Sales Order chatbot [Groq NLP Mode]. Commands: 'quit' to exit.\n")
    while True:
        raw = ask_text("You: ")
        parsed = groq_extract_intent(raw)
        action = parsed.get("action")

        if action == "get":
            order_num = parsed.get("order_number") or parse_numeric_value(ask_text("Enter Order Number to retrieve: "))
            if order_num: process_get_order(int(order_num), print)
            else: print("Invalid order number.")
        elif action == "create":
            if not parsed.get("cpo"): parsed["cpo"] = ask_text("Customer PO Number: ")
            if not parsed.get("ordered_item"): parsed["ordered_item"] = ask_text("Ordered Item (e.g. CM94532): ").upper()
            if parsed.get("quantity") is None: parsed["quantity"] = parse_numeric_value(ask_text("Ordered Quantity: "), allow_float=False)
            process_order(parsed, print)
        else: print("Could not understand the intent. Please say create or get.")

if __name__ == "__main__":
    text_chat()