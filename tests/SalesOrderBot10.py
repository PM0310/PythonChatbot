import os
import sys
import json
import datetime
import requests
import ssl
import urllib3
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
import oracledb
from groq import Groq

# --------------------------------------------------
# 1. Initialization & Configuration
# --------------------------------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Update this path if necessary for your environment
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

GROQ_API_KEY   = "REDACTED_SECRET"
GROQ_MODEL     = "llama-3.1-8b-instant"

DB_USER, DB_PASSWORD = "apps", "apps"
DB_DSN      = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

BASE_URL      = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/PROCESS_ORDER/"
GET_ORDER_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
HEADERS       = {"Content-Type": "application/json", "Accept": "application/json"}

ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Centroid Manufacturing"
MAX_CHOICES    = 10

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
    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try: return float(digits) if allow_float else int(digits)
        except ValueError: pass
    return None

# --------------------------------------------------
# 2. AI Intent Extraction
# --------------------------------------------------
def groq_extract_intent(user_input: str) -> dict:
    client = Groq(api_key=GROQ_API_KEY)
    system = (
        "You are an ERP Assistant. Extract user intent into JSON.\n"
        "FIELDS:\n"
        "- action: 'create' or 'get' or 'unknown'\n"
        "- date_range: 'this_month', 'this_week', 'last_30_days', or null\n"
        "- year: integer (e.g., 2000, 2024) or null\n"
        "- status: string (e.g., 'BOOKED', 'ENTERED', 'CANCELLED') or null\n"
        "- order_number: integer or null\n"
        "- cpo: string or null\n"
        "- ordered_item: string or null\n"
        "- quantity: number or null\n"
        "\n"
        "LOGIC RULES:\n"
        "1. If user mentions a time period (last 30 days, etc.), set date_range and action='get'.\n"
        "2. If user mentions a year or a status, set them and action='get'.\n"
        "3. If user provides an order number, set action='get'.\n"
        "4. Return ONLY raw JSON."
    )
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_input}],
            temperature=0.0,
        )
        clean = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception:
        return {"action": "unknown"}

# --------------------------------------------------
# 3. DB Core Functions (Pagination + Fixes)
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
    # Fix for ORA-01791: Included qlh.START_DATE_ACTIVE in SELECT DISTINCT
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
    # Fix for ORA-00904: Replaced ENABLED_FLAG with Date Active logic on RA_TERMS_VL
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

def get_customer_site_rows(ordered_item: str, org_id: int = ORG_ID, offset: int = 0) -> list:
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT hca.CUST_ACCOUNT_ID AS sold_to_org_id, hcsu.SITE_USE_ID AS ship_to_org_id, hp.PARTY_NAME AS customer_name
                  FROM MTL_SYSTEM_ITEMS_B msi, HZ_CUST_ACCT_SITES_ALL hcas, HZ_CUST_SITE_USES_ALL hcsu, HZ_CUST_ACCOUNTS hca, HZ_PARTIES hp
                 WHERE hcas.ORG_ID = :org_id AND hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID AND hca.CUST_ACCOUNT_ID = hcas.CUST_ACCOUNT_ID AND hp.PARTY_ID = hca.PARTY_ID
                   AND msi.SEGMENT1 LIKE :ordered_item AND msi.ORGANIZATION_ID = :org_id AND hcsu.SITE_USE_CODE = 'SHIP_TO'
                 ORDER BY hp.PARTY_NAME
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=f"{ordered_item.upper()}%", org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"sold_to_org_id": int(r[0]), "ship_to_org_id": int(r[1]), "customer_name": r[2] or ""} for r in rows]


# --------------------------------------------------
# 4. Advanced Reporting & UI Selections
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

    sql_main = f"SELECT ORDER_NUMBER, FLOW_STATUS_CODE, CREATION_DATE FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org ORDER BY CREATION_DATE DESC"
    sql_count = f"SELECT COUNT(*) FROM OE_ORDER_HEADERS_ALL WHERE {date_clause} AND {status_clause} AND ORG_ID = :org"

    print(f"\nSearching Database: Year={year or 'ANY'}, Status={status or 'ANY'}...")
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(sql_count, org=ORG_ID)
            total_count = cur.fetchone()[0]
            cur.execute(sql_main, org=ORG_ID)
            rows = cur.fetchall()

            print(f"--- Found {total_count} Orders ---")
            if total_count > 0:
                print(f"{'Order Number':<15} | {'Status':<20} | {'Date'}")
                print("-" * 55)
                for r in rows[:20]: print(f"{r[0]:<15} | {r[1]:<20} | {r[2].strftime('%Y-%m-%d')}")
                if total_count > 20: print(f"... and {total_count - 20} more.")
    except Exception as e:
        print(f"SQL Error: {e}")

def prompt_user_selection(label: str, rows: list, display_fn, has_more: bool) -> any:
    if len(rows) == 1 and not has_more:
        print(f"     [AUTO-SELECTED] {label}: {display_fn(rows[0])}")
        return rows[0]
    
    print(f"\n  Multiple {label} records found:")
    for idx, row in enumerate(rows, start=1):
        print(f"    [{idx}] {display_fn(row)}")
    if has_more: print(f"    [N] Fetch Next {MAX_CHOICES} Records")

    while True:
        raw = input(f"  Enter choice (1-{len(rows)}){' or N' if has_more else ''} (q=quit): ").strip().lower()
        if raw in ("exit", "quit", "q", "stop"): sys.exit(0)
        if raw == 'n' and has_more: return "NEXT"
        try:
            choice = int(raw)
            if 1 <= choice <= len(rows):
                sel = rows[choice - 1]
                print(f"     [SELECTED] {label}: {display_fn(sel)}")
                return sel
        except ValueError: pass
        print("  Invalid input.")

def fetch_all_from_db(state: dict) -> dict:
    ordered_item = state.get("ordered_item")
    quantity = state.get("quantity")
    
    # Item Selection
    offset = 0
    while True:
        rows = get_inventory_item_rows(ordered_item, offset=offset)
        if not rows and offset == 0: raise ValueError(f"Item '{ordered_item}' not found.")
        sel = prompt_user_selection("Inventory Item", rows, lambda r: f"ID={r['inventory_item_id']}  {r['segment1']}  {r['description']}", len(rows) == MAX_CHOICES)
        if sel == "NEXT": offset += MAX_CHOICES
        else: inventory_item_id = sel["inventory_item_id"]; break

    # Price Selection
    offset = 0
    while True:
        rows = get_price_details_rows(ordered_item, quantity, inventory_item_id, offset=offset)
        if not rows and offset == 0: raise ValueError("No valid price list found.")
        sel = prompt_user_selection("Price List", rows, lambda r: f"{r['price_list_name']}  ${r['unit_list_price']}", len(rows) == MAX_CHOICES)
        if sel == "NEXT": offset += MAX_CHOICES
        else: price_list_id, unit_price = sel["price_list_id"], sel["unit_list_price"]; break

    # Term Selection
    offset = 0
    while True:
        rows = get_payment_term_rows(offset=offset)
        sel = prompt_user_selection("Payment Term", rows, lambda r: r['term_name'], len(rows) == MAX_CHOICES)
        if sel == "NEXT": offset += MAX_CHOICES
        else: payment_term_id = sel["term_id"]; break

    # Rep Selection
    offset = 0
    while True:
        rows = get_salesrep_rows(offset=offset)
        sel = prompt_user_selection("Sales Rep", rows, lambda r: r['salesrep_name'], len(rows) == MAX_CHOICES)
        if sel == "NEXT": offset += MAX_CHOICES
        else: salesrep_id = sel["salesrep_id"]; break

    # Site Selection
    offset = 0
    while True:
        rows = get_customer_site_rows(ordered_item, offset=offset)
        sel = prompt_user_selection("Customer Site", rows, lambda r: f"{r['customer_name']} (SoldTo: {r['sold_to_org_id']})", len(rows) == MAX_CHOICES)
        if sel == "NEXT": offset += MAX_CHOICES
        else: sold_to_org_id, ship_to_org_id = sel["sold_to_org_id"], sel["ship_to_org_id"]; break

    return {
        "inventory_item_id": inventory_item_id, "price_list_id": price_list_id, "unit_list_price": unit_price,
        "unit_selling_price": unit_price, "payment_term_id": payment_term_id, "salesrep_id": salesrep_id,
        "sold_to_org_id": sold_to_org_id, "ship_to_org_id": ship_to_org_id,
    }

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
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price,
                    "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
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

def get_order_rest(order_number: int):
    payload = {"PROCESS_ORDER_Input": {"RESTHeader": {"Responsibility": "ORDER_MGMT_SUPER_USER", "Org_Id": str(ORG_ID)}, "InputParameters": {"P_API_VERSION_NUMBER": 1, "P_ORDER_NUMBER": order_number}}}
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=60)
    if response.status_code in (200, 201, 204):
        try: print(json.dumps(response.json(), indent=2))
        except Exception: print(response.text)
    else: response.raise_for_status()

def process_order_creation(state: dict):
    try: db = fetch_all_from_db(state)
    except Exception as e: print(f"DB lookup failed: {e}"); return

    payload = create_payload(
        state.get("cpo"), db["inventory_item_id"], state.get("ordered_item"), state.get("quantity"),
        db["unit_list_price"], db["unit_selling_price"], db["payment_term_id"], db["price_list_id"],
        db["salesrep_id"], db["ship_to_org_id"], db["sold_to_org_id"], OPERATING_UNIT
    )
    try:
        result = send_order(payload)
        hdr = result.get("PROCESS_ORDER_Output", {}).get("X_HEADER_REC", {})
        o_num = hdr.get("ORDER_NUMBER")
        if o_num: print(f"✅ Order successfully created! ORDER_NUMBER = {o_num}")
        else: print("⚠️ Order submitted, but ORDER_NUMBER not returned. Raw Output:", result)
    except Exception as e: print(f"❌ Order submission failed: {e}")

# --------------------------------------------------
# 6. Main Chat Loop
# --------------------------------------------------
def ask_text(prompt):
    while True:
        val = input(prompt).strip()
        if not val: continue
        if val.lower() in ("exit", "quit", "stop"):
            print("Exiting chat...")
            sys.exit(0)
        return val

def text_chat():
    print("📦 ERP Assistant Active. Commands: 'quit' to exit.")
    print("Try: 'Get booked orders from 2000', 'Get order 12345', or 'Create order'")
    while True:
        raw = ask_text("\nYou: ")
        parsed = groq_extract_intent(raw)
        action = parsed.get("action")

        # Scenario A: Advanced Search (Year, Date Range, Status)
        if parsed.get("year") or parsed.get("date_range") or (parsed.get("status") and not parsed.get("order_number")):
            get_orders_advanced(parsed.get("date_range"), parsed.get("year"), parsed.get("status"))

        # Scenario B: Retrieve Specific Order (REST)
        elif action == "get":
            order_num = parsed.get("order_number") or parse_numeric_value(ask_text("Enter Order Number to retrieve: "))
            if order_num: get_order_rest(int(order_num))
            else: print("Invalid order number.")

        # Scenario C: Create Order Flow
        elif action == "create":
            if not parsed.get("cpo"): parsed["cpo"] = ask_text("Customer PO Number: ")
            if not parsed.get("ordered_item"): parsed["ordered_item"] = ask_text("Ordered Item (e.g. CM94532): ").upper()
            if parsed.get("quantity") is None: parsed["quantity"] = parse_numeric_value(ask_text("Ordered Quantity: "), allow_float=False)
            process_order_creation(parsed)

        else: print("Could not understand intent. Try 'Orders from last 30 days' or 'Create order'.")

if __name__ == "__main__":
    text_chat()