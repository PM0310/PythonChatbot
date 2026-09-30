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
oracledb.init_oracle_client(
    lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10"
)

GROQ_API_KEY = "REDACTED_SECRET"
GROQ_MODEL   = "llama-3.3-70b-versatile"

DB_USER, DB_PASSWORD = "apps", "apps"
DB_DSN = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

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
    if val is None:
        return None
    val = str(val).strip()
    try:
        return float(val) if allow_float else int(val)
    except ValueError:
        pass
    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try:
            return float(digits) if allow_float else int(digits)
        except ValueError:
            pass
    return None


# --------------------------------------------------
# 2. Groq AI — Full Field Extraction
#    Extracts EVERY possible payload field in one call.
#    app.py merges the result into st.session_state.collected.
# --------------------------------------------------
EXTRACT_SYSTEM = """\
You are an ERP sales order assistant.
Today is {today} (Year: {year}).

Parse the user message and extract EVERY field that is explicitly mentioned.
Return ONLY a single valid JSON object — no markdown, no explanation.

JSON schema (null for anything not mentioned):
{{
  "action":             "create" | "get" | "unknown",
  "cpo":                "<CUST_PO_NUMBER string or null>",
  "ordered_item":       "<item/segment code e.g. CM94532 or null>",
  "quantity":           <integer or null>,
  "order_number":       <integer or null>,
  "inventory_item_id":  <integer or null>,
  "price_list_id":      <integer or null>,
  "unit_list_price":    <float or null>,
  "unit_selling_price": <float or null>,
  "payment_term_id":    <integer or null>,
  "salesrep_id":        <integer or null>,
  "sold_to_org_id":     <integer or null>,
  "ship_to_org_id":     <integer or null>,
  "customer_name":      "<string or null>",
  "date_range":         "this_month" | "this_week" | "last_30_days" | null,
  "year":               <integer or null>,
  "status":             "<BOOKED|ENTERED|CANCELLED or null>"
}}

Rules:
- action=create  when user wants to place/create/submit a new order.
- action=get     when user wants to look up/fetch/retrieve an order.
- CUST_PO_NUMBER appears after keywords like "PO number", "CUST_PO_NUMBER is/=".
- Extract IDs, prices, quantities only when explicitly stated.
- For relative years like "last year" compute the actual integer year.
- Return ONLY valid JSON.
"""

_ALL_KEYS = [
    "action", "cpo", "ordered_item", "quantity", "order_number",
    "inventory_item_id", "price_list_id", "unit_list_price", "unit_selling_price",
    "payment_term_id", "salesrep_id", "sold_to_org_id", "ship_to_org_id",
    "customer_name", "date_range", "year", "status",
]


def groq_extract_intent(user_input: str) -> dict:
    """
    Extract EVERY payload field from the user's message in a single Groq call.
    Returns a dict; unmentioned fields are None.
    This is the ONLY place Groq parses fields — app.py merges the result.
    """
    client = Groq(api_key=GROQ_API_KEY)
    today  = datetime.date.today()
    system = EXTRACT_SYSTEM.format(today=today.strftime("%B %d, %Y"), year=today.year)

    defaults = {k: None for k in _ALL_KEYS}
    defaults["action"] = "unknown"

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_input},
            ],
            max_tokens=400,
            temperature=0.0,
        )
        raw   = response.choices[0].message.content.strip()
        clean = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        # Merge parsed values over defaults (only non-None values)
        for k, v in parsed.items():
            if k in defaults and v is not None:
                defaults[k] = v
    except Exception as e:
        defaults["_parse_error"] = str(e)

    return defaults


def groq_clarify(conversation_history: list, missing_fields: list) -> str:
    """Generate a natural follow-up question for missing fields."""
    system = (
        "You are a friendly ERP sales order assistant. "
        "Ask a short, natural, single-sentence question to collect the missing information.\n"
        f"Missing: {', '.join(missing_fields)}"
    )
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "system", "content": system}] + conversation_history,
            max_tokens=100,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return f"Could you please provide: {', '.join(missing_fields)}?"


# --------------------------------------------------
# 3. DB Row-Fetchers
#    Each function fetches candidate rows for the UI.
#    The CALLER (app.py resolve stage) is responsible
#    for checking whether to call these at all.
# --------------------------------------------------

def get_inventory_item_rows(ordered_item: str, org_id: int = ORG_ID, offset: int = 0) -> list:
    """Fetch inventory item rows by SEGMENT1 prefix match with pagination."""
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, ORGANIZATION_ID
                  FROM MTL_SYSTEM_ITEMS_B
                 WHERE SEGMENT1 LIKE :seg AND ORGANIZATION_ID = :org_id
                 ORDER BY INVENTORY_ITEM_ID
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,
                        seg=f"{ordered_item.upper()}%",
                        org_id=org_id,
                        upper_bound=offset + MAX_CHOICES,
                        offset=offset)
            rows = cur.fetchall()
    return [
        {"inventory_item_id": int(r[0]), "segment1": r[1],
         "description": r[2] or "", "organization_id": int(r[3])}
        for r in rows
    ]


def get_price_details_rows(ordered_item: str, quantity: float,
                            inventory_item_id: int,
                            org_id: int = ORG_ID, offset: int = 0) -> list:
    """Fetch active price list rows for the given inventory item with pagination."""
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT qlh.LIST_HEADER_ID  AS price_list_id,
                                qlt.NAME            AS price_list_name,
                                qll.OPERAND         AS unit_list_price,
                                qlh.START_DATE_ACTIVE
                  FROM QP_LIST_HEADERS_B     qlh,
                       QP_LIST_HEADERS_TL    qlt,
                       QP_LIST_LINES         qll,
                       QP_PRICING_ATTRIBUTES qpa
                 WHERE qlt.LIST_HEADER_ID   = qlh.LIST_HEADER_ID
                   AND qlt.LANGUAGE         = USERENV('LANG')
                   AND qll.LIST_HEADER_ID   = qlh.LIST_HEADER_ID
                   AND qpa.LIST_LINE_ID     = qll.LIST_LINE_ID
                   AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                   AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
                   AND qlh.ACTIVE_FLAG      = 'Y'
                   AND qlh.LIST_TYPE_CODE   = 'PRL'
                   AND qlh.CURRENCY_CODE    = 'USD'
                 ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,
                        item_id_str=str(inventory_item_id),
                        upper_bound=offset + MAX_CHOICES,
                        offset=offset)
            rows = cur.fetchall()
    return [
        {"price_list_id": int(r[0]), "price_list_name": r[1] or "",
         "unit_list_price": float(r[2])}
        for r in rows
    ]


def get_payment_term_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    """Fetch active payment term rows with pagination."""
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT TERM_ID, NAME
                  FROM RA_TERMS_VL
                 WHERE (START_DATE_ACTIVE IS NULL OR START_DATE_ACTIVE <= SYSDATE)
                   AND (END_DATE_ACTIVE   IS NULL OR END_DATE_ACTIVE   >= SYSDATE)
                 ORDER BY TERM_ID
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, upper_bound=offset + MAX_CHOICES, offset=offset)
            rows = cur.fetchall()
    return [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]


def get_salesrep_rows(org_id: int = ORG_ID, offset: int = 0) -> list:
    """Fetch active sales rep rows with pagination."""
    sql = """
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT jrs.SALESREP_ID, jrs.NAME AS salesrep_name
                  FROM JTF_RS_SALESREPS jrs
                 WHERE jrs.ORG_ID = :org_id
                   AND jrs.STATUS = 'A'
                   AND jrs.END_DATE_ACTIVE IS NULL
                 ORDER BY jrs.SALESREP_ID
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, org_id=org_id, upper_bound=offset + MAX_CHOICES, offset=offset)
            rows = cur.fetchall()
    return [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]


def get_customer_site_rows(ordered_item: str, org_id: int = ORG_ID,
                            offset: int = 0,
                            sold_to_org_id: int = None,
                            ship_to_org_id: int = None) -> list:
    """
    Fetch SHIP_TO customer site rows with optional filters.
    If sold_to_org_id or ship_to_org_id are provided they are used as WHERE filters
    so the result set is pre-narrowed.
    """
    extra = []
    if ship_to_org_id is not None:
        extra.append(f"AND hcsu.SITE_USE_ID = {int(ship_to_org_id)}")
    if sold_to_org_id is not None:
        extra.append(f"AND hca.CUST_ACCOUNT_ID = {int(sold_to_org_id)}")
    extra_sql = " ".join(extra)

    sql = f"""
        SELECT * FROM (
            SELECT a.*, ROWNUM rnum FROM (
                SELECT DISTINCT
                       hca.CUST_ACCOUNT_ID  AS sold_to_org_id,
                       hcsu.SITE_USE_ID     AS ship_to_org_id,
                       hp.PARTY_NAME        AS customer_name
                  FROM MTL_SYSTEM_ITEMS_B     msi,
                       HZ_CUST_ACCT_SITES_ALL hcas,
                       HZ_CUST_SITE_USES_ALL  hcsu,
                       HZ_CUST_ACCOUNTS       hca,
                       HZ_PARTIES             hp
                 WHERE hcas.ORG_ID               = :org_id
                   AND hcsu.CUST_ACCT_SITE_ID    = hcas.CUST_ACCT_SITE_ID
                   AND hca.CUST_ACCOUNT_ID        = hcas.CUST_ACCOUNT_ID
                   AND hp.PARTY_ID                = hca.PARTY_ID
                   AND msi.SEGMENT1 LIKE :seg
                   AND msi.ORGANIZATION_ID        = :org_id
                   AND hcsu.SITE_USE_CODE         = 'SHIP_TO'
                   {extra_sql}
                 ORDER BY hp.PARTY_NAME
            ) a WHERE ROWNUM <= :upper_bound
        ) WHERE rnum > :offset
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql,
                        org_id=org_id,
                        seg=f"{ordered_item.upper()}%",
                        upper_bound=offset + MAX_CHOICES,
                        offset=offset)
            rows = cur.fetchall()
    return [
        {"sold_to_org_id": int(r[0]), "ship_to_org_id": int(r[1]),
         "customer_name": r[2] or ""}
        for r in rows
    ]


# --------------------------------------------------
# 4. Advanced Reporting (DB direct search)
# --------------------------------------------------
def get_orders_advanced(range_type=None, year=None, status=None):
    if year:
        date_clause = f"EXTRACT(YEAR FROM CREATION_DATE) = {int(year)}"
    elif range_type:
        date_map = {
            "this_month":  "TRUNC(SYSDATE, 'MM')",
            "this_week":   "TRUNC(SYSDATE, 'IW')",
            "last_30_days": "SYSDATE - 30",
        }
        date_clause = f"CREATION_DATE >= {date_map.get(range_type, 'SYSDATE - 7')}"
    else:
        date_clause = "1=1"

    status_clause = (
        f"UPPER(FLOW_STATUS_CODE) LIKE '%{status.upper()}%'" if status else "1=1"
    )

    sql_main  = (f"SELECT ORDER_NUMBER, FLOW_STATUS_CODE, CREATION_DATE "
                 f"FROM OE_ORDER_HEADERS_ALL "
                 f"WHERE {date_clause} AND {status_clause} AND ORG_ID = :org "
                 f"ORDER BY CREATION_DATE DESC")
    sql_count = (f"SELECT COUNT(*) FROM OE_ORDER_HEADERS_ALL "
                 f"WHERE {date_clause} AND {status_clause} AND ORG_ID = :org")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_count, org=ORG_ID)
            total_count = cur.fetchone()[0]
            cur.execute(sql_main, org=ORG_ID)
            rows = cur.fetchall()
    return {"total_count": total_count, "rows": rows}


# --------------------------------------------------
# 5. REST Payload Builder
# --------------------------------------------------
def create_payload(p_cust_po, p_item_id, p_ordered_item, p_qty,
                   p_price, p_selling_price, p_payment_term_id,
                   p_price_list_id, p_salesrep_id,
                   p_ship_to_org, p_sold_to_org, p_operating_unit):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility":  "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup":   "STANDARD",
                "NLSLanguage":     "AMERICAN",
                "Org_Id":          "204",
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
                    "OPERATION":               "CREATE",
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
                        "OPERATION":          "CREATE",
                    }
                },
                "P_RTRIM_DATA":     "n",
                "P_OPERATING_UNIT": p_operating_unit,
                "P_DEBUG_LEVEL":    10,
            },
        }
    }


# --------------------------------------------------
# 6. REST Callers
# --------------------------------------------------
def send_order(payload: dict):
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(BASE_URL, headers=HEADERS,
                            data=json.dumps(payload), timeout=60)
    if response.status_code in (200, 201, 204):
        try:
            return response.json()
        except Exception:
            return response.text
    response.raise_for_status()


def get_order(order_number: int) -> dict:
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility":  "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup":   "STANDARD",
                "NLSLanguage":     "AMERICAN",
                "Org_Id":          str(ORG_ID),
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST":      "T",
                "P_RETURN_VALUES":      "T",
                "P_ACTION_COMMIT":      "T",
                "P_ORDER_NUMBER":       order_number,
            },
        }
    }
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False
    response = session.post(GET_ORDER_URL, headers=HEADERS,
                            data=json.dumps(payload), timeout=60)
    if response.status_code in (200, 201, 204):
        try:
            return response.json()
        except Exception:
            return response.text
    response.raise_for_status()
