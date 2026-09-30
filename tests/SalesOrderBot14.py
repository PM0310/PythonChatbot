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
OPERATING_UNIT = "Vision Operations"
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
# 2. AI Intent Extraction (With Date Fix)
# --------------------------------------------------
def groq_extract_intent(user_input: str) -> dict:
    client = Groq(api_key=GROQ_API_KEY)
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
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_input}],
            temperature=0.0,
        )
        clean = response.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
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
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
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
    """
    Search customers by partial name match (case-insensitive).
    Returns a list of distinct customers with their account IDs.
    """
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
        cur.execute(
            sql,
            cust_name=f"%{customer_name.upper()}%",
            upper_bound=offset + MAX_CHOICES,
            offset=offset
        )
        rows = cur.fetchall()
    return [
        {
            "cust_account_id": int(r[0]),
            "customer_name": r[1] or "",
            "account_number": r[2] or ""
        }
        for r in rows
    ]


# --------------------------------------------------
# NEW: Customer Lookup by Inventory Item
# --------------------------------------------------
def get_customers_by_inventory_item_rows(inventory_item_id: int, org_id: int = ORG_ID, offset: int = 0) -> list:
    """
    Find customers who have previously ordered a given inventory item,
    by querying OE_ORDER_LINES_ALL joined to customer tables.
    Returns distinct customers with their account IDs.
    Falls back to all active customers if no order history found.
    """
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
        cur.execute(
            sql_by_item,
            item_id=inventory_item_id,
            org_id=org_id,
            upper_bound=offset + MAX_CHOICES,
            offset=offset
        )
        rows = cur.fetchall()

    if rows:
        return [
            {
                "cust_account_id": int(r[0]),
                "customer_name":   r[1] or "",
                "account_number":  r[2] or ""
            }
            for r in rows
        ]

    # --- Fallback: return all active customers (first page) ---
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
    return [
        {
            "cust_account_id": int(r[0]),
            "customer_name":   r[1] or "",
            "account_number":  r[2] or ""
        }
        for r in rows
    ]


def get_customer_sites_by_account(cust_account_id: int, org_id: int = ORG_ID) -> list:
    """
    Fetch all SHIP_TO sites for a given customer account.
    """
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
# Customer Resolution Flow (by name)
# --------------------------------------------------
def resolve_customer(customer_name: str) -> dict | None:
    """
    Interactive flow:
      1. Search customers by name.
      2. If multiple matches → user picks one.
      3. Fetch ship-to sites for that customer.
      4. If multiple sites → user picks one.
    Returns: {"sold_to_org_id": ..., "ship_to_org_id": ..., "customer_name": ...}
    or None if user aborts.
    """
    offset = 0
    selected_customer = None

    while True:
        customers = get_customer_by_name_rows(customer_name, offset=offset)
        if not customers:
            if offset == 0:
                print(f"\n  No customers found matching '{customer_name}'.")
                return None
            else:
                print("\n  No more customers found.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print(f"\n  Customers matching '{customer_name}':")
        for i, c in enumerate(customers, 1):
            print(f"    {i}. {c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})")

        has_more = len(customers) == MAX_CHOICES
        nav_options = []
        if has_more:
            nav_options.append("N = Next page")
        if offset > 0:
            nav_options.append("P = Previous page")
        nav_options.append("0 = Cancel")
        print(f"  Enter choice [{', '.join(nav_options)}]: ", end="")
        choice = input().strip().upper()

        if choice == "0":
            return None
        elif choice == "N" and has_more:
            offset += MAX_CHOICES
            continue
        elif choice == "P" and offset > 0:
            offset -= MAX_CHOICES
            continue
        else:
            idx = parse_numeric_value(choice)
            if idx and 1 <= idx <= len(customers):
                selected_customer = customers[idx - 1]
                break
            else:
                print("  Invalid selection, please try again.")

    return _resolve_customer_sites(selected_customer)


# --------------------------------------------------
# NEW: Customer Resolution by Inventory Item
# --------------------------------------------------
def resolve_customer_by_item(inventory_item_id: int, item_segment1: str) -> dict | None:
    """
    Interactive flow when no customer name is provided:
      1. Look up customers who have ordered this item (or fall back to all active customers).
      2. User picks one.
      3. Fetch and select ship-to site.
    Returns: {"sold_to_org_id": ..., "ship_to_org_id": ..., "customer_name": ...}
    or None if user aborts.
    """
    offset = 0
    selected_customer = None

    print(f"\n  🔍  No customer specified. Suggesting customers based on item '{item_segment1}'...")

    while True:
        customers = get_customers_by_inventory_item_rows(inventory_item_id, offset=offset)

        if not customers:
            if offset == 0:
                print(f"  No customers found for item '{item_segment1}'. Please enter a customer name manually.")
                print("  Enter customer name to search: ", end="")
                manual_name = input().strip()
                if not manual_name:
                    return None
                return resolve_customer(manual_name)
            else:
                print("  No more customers.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        # Label the list clearly so user knows why these customers appeared
        print(f"\n  Customers who have ordered '{item_segment1}' (or all active customers):")
        for i, c in enumerate(customers, 1):
            print(f"    {i}. {c['customer_name']} (Account#: {c['account_number']}, ID: {c['cust_account_id']})")

        has_more = len(customers) == MAX_CHOICES
        nav_options = []
        if has_more:
            nav_options.append("N = Next page")
        if offset > 0:
            nav_options.append("P = Previous page")
        nav_options.append("S = Search by name instead")
        nav_options.append("0 = Cancel")
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
            offset += MAX_CHOICES
            continue
        elif choice == "P" and offset > 0:
            offset -= MAX_CHOICES
            continue
        else:
            idx = parse_numeric_value(choice)
            if idx and 1 <= idx <= len(customers):
                selected_customer = customers[idx - 1]
                break
            else:
                print("  Invalid selection, please try again.")

    return _resolve_customer_sites(selected_customer)


def _resolve_customer_sites(selected_customer: dict) -> dict | None:
    """
    Shared helper: given a selected customer dict, fetch & resolve ship-to sites.
    Returns: {"sold_to_org_id": ..., "ship_to_org_id": ..., "customer_name": ...}
    """
    sites = get_customer_sites_by_account(selected_customer["cust_account_id"])

    if not sites:
        print(f"\n  No active SHIP_TO sites found for '{selected_customer['customer_name']}'.")
        return None

    if len(sites) == 1:
        site = sites[0]
        print(f"\n  Auto-selected ship-to site: {site['location']} — {site['address']}")
        return {
            "sold_to_org_id": site["sold_to_org_id"],
            "ship_to_org_id": site["ship_to_org_id"],
            "customer_name":  site["customer_name"]
        }

    print(f"\n  '{selected_customer['customer_name']}' has {len(sites)} ship-to sites. Please select one:")
    for i, s in enumerate(sites, 1):
        print(f"    {i}. [{s['location']}] {s['address']}  (Site ID: {s['ship_to_org_id']})")
    print("  Enter choice (0 = Cancel): ", end="")

    while True:
        choice = input().strip()
        idx = parse_numeric_value(choice)
        if idx == 0:
            return None
        if idx and 1 <= idx <= len(sites):
            site = sites[idx - 1]
            return {
                "sold_to_org_id": site["sold_to_org_id"],
                "ship_to_org_id": site["ship_to_org_id"],
                "customer_name":  site["customer_name"]
            }
        print("  Invalid selection, please try again: ", end="")


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
                "P_HEADER_REC": {
                    "HEADER_ID": p_header_id, "ORG_ID": ORG_ID, "OPERATION": "UPDATE"
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
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
    """
    Interactively collects item, quantity, price list for a new line.
    Returns a dict with all resolved line fields, or None if user cancels.
    """
    print("\n  Enter item name/prefix to search (or 0 to cancel): ", end="")
    item_input = input().strip()
    if item_input == "0":
        return None

    offset = 0
    selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            print("  No items found." if offset == 0 else "  No more items.")
            return None
        print(f"\n  Items matching '{item_input}':")
        for i, it in enumerate(items, 1):
            print(f"    {i}. [{it['segment1']}] {it['description']}")
        nav = []
        if len(items) == MAX_CHOICES: nav.append("N=Next")
        if offset > 0:               nav.append("P=Prev")
        nav.append("0=Cancel")
        print(f"  Choice [{', '.join(nav)}]: ", end="")
        c = input().strip().upper()
        if c == "0": return None
        if c == "N" and len(items) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(items):
            selected_item = items[idx - 1]; break
        print("  Invalid.")

    print("  Enter quantity: ", end="")
    qty = None
    while qty is None:
        qty = parse_numeric_value(input().strip(), allow_float=True)
        if qty is None: print("  Invalid quantity. Try again: ", end="")

    offset = 0
    selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            print("  No price lists found." if offset == 0 else "  No more price lists.")
            return None
        print(f"\n  Price lists for '{selected_item['segment1']}':")
        for i, p in enumerate(prices, 1):
            print(f"    {i}. {p['price_list_name']} — Unit Price: {p['unit_list_price']:.2f}")
        nav = []
        if len(prices) == MAX_CHOICES: nav.append("N=Next")
        if offset > 0:                 nav.append("P=Prev")
        nav.append("0=Cancel")
        print(f"  Choice [{', '.join(nav)}]: ", end="")
        c = input().strip().upper()
        if c == "0": return None
        if c == "N" and len(prices) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(prices):
            selected_price = prices[idx - 1]; break
        print("  Invalid.")

    offset = 0
    selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms:
            print("  No payment terms found." if offset == 0 else "  No more.")
            return None
        print("\n  Payment terms:")
        for i, t in enumerate(terms, 1):
            print(f"    {i}. {t['term_name']}")
        nav = []
        if len(terms) == MAX_CHOICES: nav.append("N=Next")
        if offset > 0:                nav.append("P=Prev")
        nav.append("0=Cancel")
        print(f"  Choice [{', '.join(nav)}]: ", end="")
        c = input().strip().upper()
        if c == "0": return None
        if c == "N" and len(terms) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(terms):
            selected_term = terms[idx - 1]; break
        print("  Invalid.")

    unit_price = selected_price["unit_list_price"]
    print(f"\n  Unit list price is {unit_price:.2f}. Enter selling price (or press Enter to use list price): ", end="")
    sp_input = input().strip()
    selling_price = parse_numeric_value(sp_input, allow_float=True) if sp_input else unit_price

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
    """
    Loop that lets the user keep adding lines to an already-created order.
    """
    while True:
        print("\n" + "─" * 60)
        print(f"  ➕  Add Another Line to Order #{order_number} (Header ID: {header_id})?")
        print("  Press [A] to add a line, or any other key to finish: ", end="")
        answer = input().strip().upper()
        if answer != "A":
            print("  ✅  Done. No more lines will be added.")
            break

        line = collect_line_details()
        if line is None:
            print("  ⚠️  Line entry cancelled.")
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
        )

        print(f"\n  📤  Sending add-line payload:")
        print(json.dumps(payload, indent=2))

        try:
            result = send_order(payload)
            print(f"\n  ✅  Line added successfully to Order #{order_number}.")
            print(f"  Response: {json.dumps(result, indent=2)}")
        except Exception as e:
            print(f"\n  ❌  Failed to add line: {e}")


# --------------------------------------------------
# 7. create_order_flow
#    Mandatory fields (in order): CPO → Item → Quantity → Customer
#    Customer resolution:
#      - If customer_name provided in intent → resolve_customer(name)
#      - If NOT provided                    → resolve_customer_by_item(item_id)
# --------------------------------------------------
def create_order_flow(intent: dict, conversation_history: list) -> None:
    """
    Mandatory field order:
      1. CPO            ← mandatory, prompt if missing
      2. Ordered Item   ← mandatory, prompt if missing
      3. Quantity       ← mandatory, prompt if missing
      4. Customer       ← mandatory (4th), resolved by name OR by item
    Then: Price List → Selling Price → Payment Term → Salesrep → Submit
    """

    # ══════════════════════════════════════════════
    # MANDATORY FIELD 1: CPO
    # ══════════════════════════════════════════════
    cpo = intent.get("cpo")
    if not cpo:
        print("\n  [Mandatory] Enter Customer PO Number: ", end="")
        while not cpo:
            cpo = input().strip()
            if not cpo:
                print("  CPO is required. Please enter a value: ", end="")

    # ══════════════════════════════════════════════
    # MANDATORY FIELD 2: Ordered Item
    # ══════════════════════════════════════════════
    ordered_item_hint = intent.get("ordered_item", "")
    item_input = ordered_item_hint  # pre-fill from intent if available

    if not item_input:
        print("\n  [Mandatory] Enter item name/prefix to search: ", end="")
        while not item_input:
            item_input = input().strip()
            if not item_input:
                print("  Item is required. Please enter a value: ", end="")

    offset = 0
    selected_item = None
    while True:
        items = get_inventory_item_rows(item_input, offset=offset)
        if not items:
            if offset == 0:
                print(f"  No items found matching '{item_input}'. Please try a different name: ", end="")
                item_input = input().strip()
                if not item_input:
                    print("  Order creation cancelled.")
                    return
                continue
            else:
                print("  No more items.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print(f"\n  Items matching '{item_input}':")
        for i, it in enumerate(items, 1):
            print(f"    {i}. [{it['segment1']}] {it['description']}")

        nav = []
        if len(items) == MAX_CHOICES: nav.append("N = Next page")
        if offset > 0:               nav.append("P = Previous page")
        nav.append("0 = Cancel")
        print(f"  Choice [{', '.join(nav)}]: ", end="")
        c = input().strip().upper()

        if c == "0":
            print("  Order creation cancelled.")
            return
        if c == "N" and len(items) == MAX_CHOICES: offset += MAX_CHOICES; continue
        if c == "P" and offset > 0: offset -= MAX_CHOICES; continue
        idx = parse_numeric_value(c)
        if idx and 1 <= idx <= len(items):
            selected_item = items[idx - 1]
            break
        print("  Invalid selection.")

    # ══════════════════════════════════════════════
    # MANDATORY FIELD 3: Quantity
    # ══════════════════════════════════════════════
    qty_hint = intent.get("quantity")
    qty = parse_numeric_value(qty_hint, allow_float=True) if qty_hint else None

    if qty is None:
        print("\n  [Mandatory] Enter quantity: ", end="")
    while qty is None:
        qty = parse_numeric_value(input().strip(), allow_float=True)
        if qty is None:
            print("  Quantity is required and must be a number. Try again: ", end="")

    # ══════════════════════════════════════════════
    # MANDATORY FIELD 4: Customer
    # Branch A: customer_name provided in intent → search by name
    # Branch B: not provided                    → derive from selected item
    # ══════════════════════════════════════════════
    customer_name = intent.get("customer_name")
    customer_info = None

    if customer_name:
        # Branch A — user told us a customer name
        print(f"\n  [Mandatory] Resolving customer '{customer_name}'...")
        while customer_info is None:
            customer_info = resolve_customer(customer_name)
            if customer_info is None:
                print("  Could not resolve customer. Try a different name? (Y/N): ", end="")
                if input().strip().upper() != "Y":
                    print("  Order creation cancelled.")
                    return
                print("  Enter customer name to search: ", end="")
                customer_name = input().strip()
                if not customer_name:
                    print("  Order creation cancelled.")
                    return
    else:
        # Branch B — derive customer from the selected item
        print(f"\n  [Mandatory] No customer specified — looking up customers for item '{selected_item['segment1']}'...")
        while customer_info is None:
            customer_info = resolve_customer_by_item(
                selected_item["inventory_item_id"],
                selected_item["segment1"]
            )
            if customer_info is None:
                print("  Could not resolve customer. Try searching by name? (Y/N): ", end="")
                if input().strip().upper() != "Y":
                    print("  Order creation cancelled.")
                    return
                print("  Enter customer name to search: ", end="")
                fallback_name = input().strip()
                if not fallback_name:
                    print("  Order creation cancelled.")
                    return
                customer_info = resolve_customer(fallback_name)

    sold_to_org_id = customer_info["sold_to_org_id"]
    ship_to_org_id = customer_info["ship_to_org_id"]
    print(f"\n  ✔ Customer  : {customer_info['customer_name']}")
    print(f"  ✔ Sold-to ID: {sold_to_org_id}  |  Ship-to ID: {ship_to_org_id}")

    # ══════════════════════════════════════════════
    # Price List  (non-mandatory but required to proceed)
    # ══════════════════════════════════════════════
    offset = 0
    selected_price = None
    while True:
        prices = get_price_details_rows(item_input, qty, selected_item["inventory_item_id"], offset=offset)
        if not prices:
            if offset == 0:
                print(f"  No price lists found for '{selected_item['segment1']}'. Cannot proceed.")
                return
            else:
                print("  No more price lists.")
                offset = max(0, offset - MAX_CHOICES)
                continue

        print(f"\n  Price lists for '{selected_item['segment1']}':")
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
    print(f"\n  Unit list price: {unit_price:.2f}. Enter selling price (Enter = same): ", end="")
    sp_input = input().strip()
    selling_price = parse_numeric_value(sp_input, allow_float=True) if sp_input else unit_price

    # ══════════════════════════════════════════════
    # Payment Term
    # ══════════════════════════════════════════════
    offset = 0
    selected_term = None
    while True:
        terms = get_payment_term_rows(offset=offset)
        if not terms:
            print("  No payment terms found." if offset == 0 else "  No more.")
            return
        print("\n  Payment terms:")
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

    # ══════════════════════════════════════════════
    # Salesrep
    # ══════════════════════════════════════════════
    offset = 0
    selected_rep = None
    while True:
        reps = get_salesrep_rows(offset=offset)
        if not reps:
            print("  No salesreps found." if offset == 0 else "  No more.")
            return
        print("\n  Sales representatives:")
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

    # ══════════════════════════════════════════════
    # Build & Submit Payload
    # ══════════════════════════════════════════════
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
        p_ship_to_org     = ship_to_org_id,
        p_sold_to_org     = sold_to_org_id,
        p_operating_unit  = OPERATING_UNIT
    )

    print("\n  ⏳  Submitting order...")
    try:
        result = send_order(payload)
        print("\n  ✅  Order created successfully!")
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

        if order_number:
            order_number = int(str(order_number).strip())
        if header_id:
            header_id = int(str(header_id).strip())

        if not header_id:
            print("\n  ⚠️  Could not auto-extract Header ID from response.")
            print("  Please enter the Header ID shown in the response above (or press Enter to skip): ", end="")
            manual = input().strip()
            if manual:
                header_id = parse_numeric_value(manual)
        if not order_number:
            print("  Please enter the Order Number shown in the response above (or press Enter to skip): ", end="")
            manual = input().strip()
            if manual:
                order_number = parse_numeric_value(manual)

        if header_id and order_number:
            add_line_to_order(int(order_number), int(header_id))
        else:
            print("\n  ⚠️  Header ID / Order Number unavailable — skipping add-line option.")

    except Exception as e:
        print(f"\n  ❌  Order creation failed: {e}")


# --------------------------------------------------
# 8. Main Entry Point
# --------------------------------------------------
def main():
    print("=" * 60)
    print("  ERP Sales Order Assistant")
    print("=" * 60)
    conversation_history = []

    while True:
        print("\nYou: ", end="")
        user_input = input().strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "bye"):
            print("  Goodbye!")
            break

        conversation_history.append({"role": "user", "content": user_input})
        intent = groq_extract_intent(user_input)
        action = intent.get("action", "unknown")

        if action == "create":
            create_order_flow(intent, conversation_history)

        elif action == "get":
            order_number = intent.get("order_number")
            if order_number:
                try:
                    result = get_order(int(order_number))
                    print(f"\n  Order details:\n{json.dumps(result, indent=2)}")
                except Exception as e:
                    print(f"\n  ❌  Error fetching order: {e}")
            else:
                try:
                    data = get_orders_advanced(
                        range_type = intent.get("date_range"),
                        year       = intent.get("year"),
                        status     = intent.get("status")
                    )
                    print(f"\n  Total orders found: {data['total_count']}")
                    for row in data["rows"][:20]:
                        print(f"    Order#: {row[0]}  Status: {row[1]}  Created: {row[2]}")
                except Exception as e:
                    print(f"\n  ❌  Error fetching orders: {e}")
        else:
            clarification = groq_clarify(conversation_history, ["action (create order or get order info)"])
            print(f"\n  Assistant: {clarification}")
            conversation_history.append({"role": "assistant", "content": clarification})


if __name__ == "__main__":
    main()