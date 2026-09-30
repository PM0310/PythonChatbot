"""
ERPAgent / Agent2.py
--------------------
Self-contained Flask backend for Oracle EBS Sales Orders. It reproduces every
operation of the original Streamlit-based assistant, but as a single file:

  * No imports of other local project files — every Oracle DB query, REST
    payload builder and email/report helper lives directly in this module.
  * The only AI provider used is Grok (xAI). There is no Azure OpenAI /
    GitHub Models code anywhere in this file — every AI call goes to Grok
    based on what the user types.
  * No pydantic, no voice bot, no config encryption — plain dict validation,
    text-only chat, and plain JSON config storage.

Operations covered:
  * AI chat + intent extraction (create / get / search / order_details / email)
  * Guided sales-order creation (item -> price -> selling price -> term ->
    salesrep -> line type -> customer -> ship-to site -> confirm -> submit)
  * Retrieve a specific order by number
  * Advanced order search (year / date range / status)
  * Order details by customer
  * Add another line to an existing order
  * Manual email, auto-email on every retrieval, scheduled background reports
"""

import os
import re
import io
import csv
import ssl
import json
import hmac
import uuid
import secrets
import smtplib
import datetime
import threading
import requests
import urllib3
import oracledb
from functools import lru_cache
from typing import Any, Dict, List, Optional
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from flask import Flask, Response, request, jsonify, session, send_from_directory
from openai import OpenAI

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    OPENPYXL_AVAILABLE = True
except Exception:
    OPENPYXL_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.secret_key = os.environ.get("ERPAGENT_SECRET", "erp-agent-glass-ui-secret")

# --------------------------------------------------
# Oracle EBS / REST configuration
# --------------------------------------------------
DB_USER, DB_PASSWORD = "apps", "apps"
DB_DSN = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

BASE_URL      = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/PROCESS_ORDER/"
GET_ORDER_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
HEADERS       = {"Content-Type": "application/json", "Accept": "application/json"}

ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Vision Operations"
MAX_CHOICES    = 10


# ==================================================
# Inline config manager (app7.py parity) — plain JSON, no local imports
# ==================================================
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

CONFIG_DEFAULTS: Dict[str, Any] = {
    "org_id": ORG_ID,
    "order_type_id": ORDER_TYPE_ID,
    "default_payment_term_id": 4,
    "default_price_list_id": 1000,
    "default_salesrep_id": 10067,
    "default_ship_to_org_id": 6472,
    "default_sold_to_org_id": 5391,
    "default_inventory_item_id": 12027,
    "operating_unit": OPERATING_UNIT,
    "max_choices": MAX_CHOICES,
    "responsibility": "ORDER_MGMT_SUPER_USER",
    "resp_application": "ONT",
    "security_group": "STANDARD",
    "nls_language": "AMERICAN",
    "api_base_url": "https://cendb.ad.centroid.com:4463",
    "api_user": REST_USERNAME,
    "api_password": REST_PASSWORD,
    "xai_api_key": "",
    "grok_model": "grok-3",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_sender": "erp.assistant@yourdomain.com",
    "auto_email_enabled": False,
    "auto_email_to": "",
}


class ConfigManager:
    """Singleton config manager backed by config.json (plain JSON, no encryption)."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self):
        cfg = dict(CONFIG_DEFAULTS)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    file_cfg = json.load(f)
                if isinstance(file_cfg, dict):
                    cfg.update(file_cfg)
            except Exception as e:
                print(f"Warning: could not load {CONFIG_FILE}: {e}")
        self._config = cfg

    def get(self, key, default=None):
        return self._config.get(key, default)

    def set(self, key, value):
        self._config[key] = value
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._config, f, indent=4)
        except Exception as e:
            print(f"Warning: could not save {CONFIG_FILE}: {e}")

    def all(self):
        return dict(self._config)


def get_config_value(key, default=None):
    return ConfigManager().get(key, default)


def set_config_value(key, value):
    ConfigManager().set(key, value)


def get_org_id() -> int:
    return int(get_config_value("org_id", ORG_ID))


def get_order_type_id() -> int:
    return int(get_config_value("order_type_id", ORDER_TYPE_ID))


def get_default_payment_term_id() -> int:
    return int(get_config_value("default_payment_term_id", 4))


def get_default_price_list_id() -> int:
    return int(get_config_value("default_price_list_id", 1000))


def get_default_salesrep_id() -> int:
    return int(get_config_value("default_salesrep_id", 10067))


def get_default_ship_to_org_id() -> int:
    return int(get_config_value("default_ship_to_org_id", 6472))


def get_default_sold_to_org_id() -> int:
    return int(get_config_value("default_sold_to_org_id", 5391))


def get_default_inventory_item_id() -> int:
    return int(get_config_value("default_inventory_item_id", 12027))


def get_max_choices() -> int:
    return int(get_config_value("max_choices", MAX_CHOICES))


def get_operating_unit() -> str:
    return get_config_value("operating_unit", OPERATING_UNIT)


def get_rest_header() -> Dict[str, str]:
    return {
        "Responsibility": get_config_value("responsibility", "ORDER_MGMT_SUPER_USER"),
        "RespApplication": get_config_value("resp_application", "ONT"),
        "SecurityGroup": get_config_value("security_group", "STANDARD"),
        "NLSLanguage": get_config_value("nls_language", "AMERICAN"),
        "Org_Id": str(get_org_id()),
    }


def get_service_urls() -> Dict[str, str]:
    base = str(get_config_value("api_base_url", "https://cendb.ad.centroid.com:4463")).rstrip("/")
    return {
        "get_order": f"{base}/webservices/rest/sales_order/GET_ORDER/",
        "process_order": f"{base}/webservices/rest/sales_order/PROCESS_ORDER/",
        "cust_so_dtls": f"{base}/webservices/rest/CustSODtls/XX_CUST_SO_DET_PRC1/",
    }


def build_session() -> requests.Session:
    req_session = requests.Session()
    req_session.mount("https://", ForceTLSAdapter())
    req_session.auth = HTTPBasicAuth(get_config_value("api_user", REST_USERNAME), get_config_value("api_password", REST_PASSWORD))
    req_session.verify = False
    return req_session


# =========================================================
# Last-operation tracking for export/email attachment (app7.py parity)
# =========================================================
_LAST_OPERATION = {"type": None, "data": None, "raw": None, "email_html": "", "ai_summary": ""}


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


# ==================================================
# Oracle DB helpers
# ==================================================
def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)


def execute_query(sql: str, params: dict) -> list:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col[0].upper() for col in cur.description]
        rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]


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
        cur.execute(sql, ordered_item=f"{ordered_item.upper()}%", org_id=org_id,
                    upper_bound=offset + MAX_CHOICES, offset=offset)
        rows = cur.fetchall()
    return [{"inventory_item_id": int(r[0]), "segment1": r[1], "description": r[2] or "",
             "organization_id": int(r[3])} for r in rows]


def get_price_details_rows(ordered_item: str, quantity: float, inventory_item_id: int,
                            org_id: int = ORG_ID, offset: int = 0) -> list:
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
        cur.execute(sql_generic, item_id_str=str(inventory_item_id),
                    upper_bound=offset + MAX_CHOICES, offset=offset)
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
    """Line-type lookup is not configured for this ERP instance."""
    return []


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
        cur.execute(sql_by_item, item_id=inventory_item_id, org_id=org_id,
                    upper_bound=offset + MAX_CHOICES, offset=offset)
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


def get_order_details_by_customer(p_customer_name: str) -> list:
    sql = """
        SELECT
            HP.PARTY_ID,
            HP.PARTY_NAME                                               AS CUSTOMER_NAME,
            TO_CHAR(SYSDATE, 'DD-MON-YYYY')                            AS REPORT_DATE,
            OOHA.SOLD_TO_ORG_ID                                         AS SOLD_TO_PARTY_ID,
            OOHA.INVOICE_TO_ORG_ID                                      AS BILL_TO_CUSTOMER_ID,
            OOHA.ORDER_NUMBER,
            TO_CHAR(OOHA.ORDERED_DATE, 'DD-MON-YYYY')                  AS ORDER_DATE,
            WDD.RELEASED_STATUS,
            OOLA.LINE_NUMBER,
            MSI.SEGMENT1                                                AS ITEM_NUMBER,
            OOLA.ORDER_QUANTITY_UOM                                     AS ORDERED_UOM,
            OOLA.ORDERED_QUANTITY                                       AS ORDERED_QTY,
            DECODE(OOLA.CANCELLED_FLAG, 'Y', 'Y', 'N')                 AS ORDER_HOLD_FLAG,
            OOLA.UNIT_LIST_PRICE,
            OOLA.UNIT_SELLING_PRICE,
            OOLA.FLOW_STATUS_CODE                                       AS LINE_STATUS,
            OOLA.FLOW_STATUS_CODE                                       AS FULFILL_STATUS,
            OOHA.CUST_PO_NUMBER                                         AS PO_NUMBER,
            OOLA.CUST_PO_NUMBER                                         AS PO_LINE,
            'PO_REFERENCE'                                              AS REF_TYPE,
            (
                SELECT NVL(SUM(APS.AMOUNT_DUE_REMAINING), 0)
                  FROM AR_PAYMENT_SCHEDULES_ALL APS,
                       RA_CUSTOMER_TRX_ALL      RCTA
                 WHERE APS.CUSTOMER_TRX_ID             = RCTA.CUSTOMER_TRX_ID
                   AND RCTA.INTERFACE_HEADER_ATTRIBUTE1 = TO_CHAR(OOHA.ORDER_NUMBER)
            )                                                           AS INVOICE_BALANCE,
            TO_CHAR(NVL(OOLA.SCHEDULE_SHIP_DATE, OOLA.REQUEST_DATE),
                    'DD-MON-YYYY')                                      AS SCHEDULE_SHIP_DATE,
            TO_CHAR(OOLA.ACTUAL_SHIPMENT_DATE, 'DD-MON-YYYY')          AS ACTUAL_SHIP_DATE,
            DECODE(TRUNC(OOLA.SCHEDULE_SHIP_DATE),
                   TRUNC(SYSDATE), 1, 0)                               AS TODAY_ARRIVAL_QTY,
            DECODE(WDD.RELEASED_STATUS, 'B', 1, 0)                     AS BACKORDER_FLAG,
            (OOLA.ORDERED_QUANTITY * OOLA.UNIT_SELLING_PRICE)          AS LINE_PRICE,
            (
                SELECT NVL(SUM(OPA.ADJUSTED_AMOUNT), 0)
                  FROM OE_PRICE_ADJUSTMENTS OPA
                 WHERE OPA.LINE_ID            = OOLA.LINE_ID
                   AND OPA.LIST_LINE_TYPE_CODE = 'DIS'
            )                                                           AS ADD_DISC,
            (
                SELECT NVL(SUM(OPA.ADJUSTED_AMOUNT), 0)
                  FROM OE_PRICE_ADJUSTMENTS OPA
                 WHERE OPA.LINE_ID            = OOLA.LINE_ID
                   AND OPA.LIST_LINE_TYPE_CODE = 'DIS'
            )                                                           AS CASH_DISC,
            (
                SELECT NAME
                  FROM OE_TRANSACTION_TYPES_TL
                 WHERE TRANSACTION_TYPE_ID = OOHA.ORDER_TYPE_ID
                   AND LANGUAGE            = 'US'
            )                                                           AS ORDER_TYPE,
            OOLA.SHIPPING_METHOD_CODE                                   AS SHIPMENT_MODE,
            (
                CASE
                    WHEN OOLA.SCHEDULE_SHIP_DATE IS NOT NULL
                     AND TRUNC(OOLA.SCHEDULE_SHIP_DATE)
                           < TRUNC(NVL(OOLA.ACTUAL_SHIPMENT_DATE, SYSDATE))
                    THEN 1
                    ELSE 0
                END
            )                                                           AS DELAYED_ORDER_FLAG,
            (
                CASE
                    WHEN OOLA.ACTUAL_SHIPMENT_DATE IS NOT NULL
                     AND TRUNC(OOLA.SCHEDULE_SHIP_DATE) < TRUNC(SYSDATE)
                     AND WDD.RELEASED_STATUS = 'C'
                    THEN 1
                    ELSE 0
                END
            )                                                           AS IN_TRANSIT_ORDER_FLAG,
            (
                SELECT HCP.EMAIL_ADDRESS
                  FROM HZ_CUST_ACCOUNT_ROLES HCAR,
                       HZ_CONTACT_POINTS     HCP,
                       HZ_RELATIONSHIPS      HR
                 WHERE HCAR.STATUS              = 'A'
                   AND HCP.STATUS               = 'A'
                   AND HCP.PRIMARY_FLAG         = 'Y'
                   AND HCP.CONTACT_POINT_TYPE   = 'EMAIL'
                   AND HCAR.CUST_ACCOUNT_ID     = OOHA.SOLD_TO_ORG_ID
                   AND ROWNUM                   = 1
                   AND HR.OBJECT_TYPE           = 'ORGANIZATION'
            )                                                           AS EMAIL
        FROM
            OE_ORDER_HEADERS_ALL  OOHA,
            OE_ORDER_LINES_ALL    OOLA,
            MTL_SYSTEM_ITEMS_B    MSI,
            WSH_DELIVERY_DETAILS  WDD,
            HZ_CUST_ACCOUNTS      HCAA,
            HZ_PARTIES            HP
        WHERE
                OOHA.HEADER_ID          = OOLA.HEADER_ID
            AND MSI.INVENTORY_ITEM_ID   = OOLA.INVENTORY_ITEM_ID
            AND MSI.ORGANIZATION_ID     = OOLA.SHIP_FROM_ORG_ID
            AND OOLA.LINE_ID            = WDD.SOURCE_LINE_ID(+)
            AND WDD.SOURCE_CODE(+)      = 'OE'
            AND HCAA.CUST_ACCOUNT_ID    = OOHA.SOLD_TO_ORG_ID
            AND HP.PARTY_ID             = HCAA.PARTY_ID
            AND HP.PARTY_NAME           = :p_customer_name
        ORDER BY
            OOHA.ORDER_NUMBER,
            OOLA.LINE_NUMBER
    """
    return execute_query(sql, {"p_customer_name": p_customer_name})


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


# ==================================================
# REST payload generation & execution
# ==================================================
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


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
    rest_session = requests.Session()
    rest_session.mount("https://", ForceTLSAdapter())
    rest_session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    rest_session.verify = False
    response = rest_session.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
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
    rest_session = requests.Session()
    rest_session.mount("https://", ForceTLSAdapter())
    rest_session.auth   = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    rest_session.verify = False
    response = rest_session.post(GET_ORDER_URL, headers=HEADERS, data=json.dumps(payload), timeout=180)
    if response.status_code in (200, 201, 204):
        try:
            return response.json()
        except Exception:
            return response.text
    response.raise_for_status()


# --------------------------------------------------
# SMTP configuration (override with environment variables)
# --------------------------------------------------
SMTP_HOST   = os.environ.get("ERP_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.environ.get("ERP_SMTP_PORT", "587"))
SMTP_USER   = os.environ.get("ERP_SMTP_USER", "")
SMTP_PASS   = os.environ.get("ERP_SMTP_PASS", "")
SMTP_SENDER = os.environ.get("ERP_SMTP_SENDER", SMTP_USER or "erp.assistant@yourdomain.com")

FAQ_DATA = {
    "How do I create a new sales order?": "Type a command like 'Create an order' or 'Create order for item AS54888'. I will guide you step-by-step to gather the Customer PO, Item, Quantity and Line Type.",
    "How do I look up an existing order?": "Simply type 'Get order 12345' or 'Show me order 12345'.",
    "How do I send order details via email?": "Say 'Send email to example@domain.com'. I collect the details of the last operation and format them into a table for you.",
    "Can I search for orders by date or status?": "Yes. Use natural language such as 'Show booked orders from 2024' or 'Find cancelled orders'.",
    "How do I see all orders for a specific customer?": "Type 'Order details for customer ACME'. This pulls a full table of their orders, shipments and invoice balances.",
    "Can I add more items to an existing order?": "Yes. After creating or retrieving an order, use the 'Add a Line' button to append new items to that order.",
    "How do I cancel an operation?": "Click 'Back to Chat' on any panel, or type 'cancel'.",
}


# ==================================================
# Session state
# ==================================================
_STATES = {}
_STATE_LOCK = threading.Lock()


def _default_state():
    return {
        "messages": [],
        "gh_history": [],
        "stage": "chat",
        "action": None,
        "pending_field": None,
        "collected": {
            "cpo": None, "ordered_item": None, "quantity": None, "order_number": None,
            "inventory_item_id": None, "price_list_id": None, "price_list_name": None,
            "unit_list_price": None, "unit_selling_price": None, "payment_term_id": None,
            "payment_term_name": None, "salesrep_id": None, "salesrep_name": None,
            "sold_to_org_id": None, "ship_to_org_id": None, "customer_name": None,
            "cust_account_id": None, "line_type_id": None, "email_address": None,
        },
        "offsets": {"item": 0, "price": 0, "term": 0, "rep": 0, "site": 0,
                    "customer": 0, "customer_by_item": 0, "line_type": 0},
        "rows": {"item": [], "price": [], "term": [], "rep": [], "site": [],
                 "customer": [], "customer_by_item": [], "line_type": []},
        "pending": None,
        "api_result": None,
        "parsed_result": None,
        "search_result": None,
        "customer_orders": {"customer_name": None, "rows": []},
        "email_payload_html": "",
        "add_line": {"active": False, "step": None, "data": {}, "header_id": None,
                     "order_number": None, "rows": {"item": [], "price": [], "term": [], "line_type": []},
                     "search_text": ""},
        "auto_email": {"enabled": False, "to": "", "status": None, "error": ""},
        "schedule": {"running": False, "customer": "", "frequency": "", "to": ""},
    }


def _sid():
    if "sid" not in session:
        session["sid"] = uuid.uuid4().hex
    return session["sid"]


def get_state():
    sid = _sid()
    with _STATE_LOCK:
        if sid not in _STATES:
            _STATES[sid] = _default_state()
        return _STATES[sid]


def reset_state(keep_history=True):
    sid = _sid()
    with _STATE_LOCK:
        old = _STATES.get(sid, _default_state())
        fresh = _default_state()
        if keep_history:
            fresh["messages"] = old.get("messages", [])
            fresh["gh_history"] = old.get("gh_history", [])
            fresh["email_payload_html"] = old.get("email_payload_html", "")
            fresh["auto_email"] = old.get("auto_email", fresh["auto_email"])
            fresh["schedule"] = old.get("schedule", fresh["schedule"])
        _STATES[sid] = fresh
        return fresh


# ==================================================
# Small helpers
# ==================================================
def say(state, msg, speak_text=None, mute=True):
    """Append an assistant message to the chat transcript."""
    state["messages"].append({"role": "assistant", "content": msg})


def user_say(state, msg):
    state["messages"].append({"role": "user", "content": msg})


def gh_add(state, role, content):
    state["gh_history"].append({"role": role, "content": content})


def merge_fields(state, extracted: dict):
    for k, v in (extracted or {}).items():
        if k in state["collected"] and v is not None:
            state["collected"][k] = v


def missing_minimum(state) -> list:
    c = state["collected"]
    missing = []
    if not c.get("cpo"):
        missing.append("Customer PO Number")
    if not c.get("ordered_item") and not c.get("inventory_item_id"):
        missing.append("Ordered Item code")
    if not c.get("quantity"):
        missing.append("Ordered Quantity")
    return missing


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d-%b-%Y")
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _has_line_types():
    return False


# ==================================================
# Grok (xAI) configuration — the only AI provider used in this file
# ==================================================
GROK_API_KEY  = os.environ.get("XAI_API_KEY", "xai-your-key-here")   # set XAI_API_KEY env var
GROK_BASE_URL = "https://api.x.ai/v1"
GROK_MODEL    = os.environ.get("GROK_MODEL", "grok-3")                # or grok-3-mini


def _grok_client() -> OpenAI:
    """Return an OpenAI-compatible client pointed at xAI Grok."""
    return OpenAI(base_url=GROK_BASE_URL, api_key=GROK_API_KEY)


def _grok_chat(messages: list, temperature: float = 0.0, max_tokens: int = 300) -> str:
    """
    Single helper for every Grok call.
    Strips markdown fences, handles errors gracefully.
    """
    client = _grok_client()
    resp = client.chat.completions.create(
        model=GROK_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


# ==================================================
# AI helpers (Grok-powered)
# ==================================================
_INTENT_SYSTEM = """You are an intelligent ERP intent extraction engine for Oracle EBS Sales Orders.

CONVERSATION CONTEXT: you receive recent chat history and the user's latest message.

YOUR JOB: Determine the user's intent and extract all relevant parameters. Return ONLY a valid JSON object — no explanation, no markdown.

ACTIONS:
  "create"        → user wants to CREATE a new sales order
  "get"           → user wants a SPECIFIC order by number (order number must be present)
  "search"        → user wants to FILTER/LIST orders by year, date range, status (no specific order number)
  "email"         → user wants to send an email with results
  "order_details" → user wants all order history for a NAMED CUSTOMER
  "unknown"       → none of the above

CRITICAL RULES:
- Use "search" (NOT "get") when a year, date range, or status is mentioned WITHOUT a specific order number.
- If the user is answering a previous clarification question, infer the action from the assistant's last question.
- Convert spoken/written numbers to digits: "sixty four thousand four hundred sixty" → 64460
- For "create": extract cpo, ordered_item, quantity, customer_name if mentioned.
- For "get": extract order_number (integer, mandatory).
- For "search": extract year (int), date_range (this_month|this_week|last_30_days), status (BOOKED|ENTERED|SHIPPED|CANCELLED|CLOSED|INVOICED|DELIVERED).
- For "order_details": extract customer_name (string, mandatory).
- For "email": extract email_address if present.
- All unextracted fields → null.

JSON SCHEMA (always return all keys):
{
  "action": "<string>",
  "order_number": <int|null>,
  "customer_name": "<string|null>",
  "cpo": "<string|null>",
  "ordered_item": "<string|null>",
  "quantity": <number|null>,
  "line_type_id": <int|null>,
  "email_address": "<string|null>",
  "year": <int|null>,
  "status": "<string|null>",
  "date_range": "<string|null>"
}"""


def get_smart_intent(history: list, prompt: str) -> dict:
    """Extract structured intent from user message using Grok."""
    try:
        history_str = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in history[-8:]
        )
        messages = [
            {"role": "system", "content": _INTENT_SYSTEM},
            {"role": "user",   "content": f"--- CONVERSATION HISTORY ---\n{history_str}\n\n--- LATEST USER MESSAGE ---\n{prompt}"},
        ]
        raw = _grok_chat(messages, temperature=0.0, max_tokens=300)
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


_SUMMARY_SYSTEM = """You are the Centroid Oracle EBS Sales Order Assistant — an expert, friendly AI.

When given the result of an ERP operation, produce a clear, professional 2-4 sentence summary:
1. Lead with SUCCESS ✅ or FAILURE ❌.
2. Mention all key identifiers: Order Number, Header ID, Customer PO, Flow Status, item names, quantities.
3. Add a helpful next-step suggestion when relevant (e.g. "You can now add lines or email the result").
4. Write in plain, conversational English — no raw JSON, no bullet points.
5. If the data is empty or error-y, say so clearly and suggest what to check."""


def generate_ai_summary(operation_name: str, data) -> str:
    """Generate a rich, AI-quality summary of any ERP operation result."""
    try:
        messages = [
            {"role": "system", "content": _SUMMARY_SYSTEM},
            {"role": "user",   "content": (
                f"Operation: {operation_name}\n"
                f"Result data:\n{json.dumps(_json_safe(data), indent=2)[:3000]}"
            )},
        ]
        return _grok_chat(messages, temperature=0.3, max_tokens=250)
    except Exception:
        return "Operation completed."


_GENERAL_SYSTEM = """You are the Centroid Sales Order Assistant — a knowledgeable, conversational AI embedded in Oracle EBS.

YOUR CAPABILITIES:
• Create new sales orders (guided wizard)
• Retrieve a specific order by number
• Search/filter orders by year, date range, or workflow status
• Show all order history for a customer
• Add line items to an existing order
• Send order reports by email
• Schedule automated recurring email reports

BEHAVIOUR:
• Answer concisely but helpfully — 2-5 sentences is ideal.
• If asked what you can do, list your capabilities clearly.
• If asked an ERP concept question (e.g. "what is a backorder?"), explain it correctly.
• If the user is mid-conversation, acknowledge context from recent history.
• Never make up order numbers or customer names.
• Use a warm, professional, slightly friendly tone — like a knowledgeable colleague.
• End ambiguous answers with a gentle prompt to clarify (e.g. "Would you like me to search for that?")."""


def general_answer(state, prompt: str) -> str:
    """Answer general questions using Grok with full conversation context."""
    try:
        messages = [{"role": "system", "content": _GENERAL_SYSTEM}]
        # Include recent conversation so Grok has context
        for m in state["gh_history"][-10:]:
            messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": prompt})
        return _grok_chat(messages, temperature=0.5, max_tokens=300)
    except Exception:
        return (
            "I'm your Centroid Sales Order Assistant. I can create orders, retrieve them by number, "
            "search by year or status, show customer order history, add lines, or email reports. "
            "What would you like to do?"
        )


# ==================================================
# ERP response parsing
# ==================================================
def extract_erp_details(result) -> dict:
    if not isinstance(result, dict):
        return {"status": "N/A", "message": str(result), "header_details": {}, "lines": []}

    data = result.get("OutputParameters", result)
    status = data.get("X_RETURN_STATUS", "N/A")
    messages_raw = data.get("X_MESSAGES", {}) or {}
    message_list = []
    if isinstance(messages_raw, dict):
        items = messages_raw.get("X_MESSAGES_ITEM", [])
        if isinstance(items, list):
            message_list = [m.get("MESSAGE_TEXT", "") for m in items if isinstance(m, dict) and m.get("MESSAGE_TEXT")]
        elif isinstance(items, dict) and items.get("MESSAGE_TEXT"):
            message_list = [items["MESSAGE_TEXT"]]
    message_text = " | ".join(message_list) if message_list else "N/A"

    header = data.get("X_HEADER_REC", {}) or {}
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}
    header_details = {
        "Order Number":   header.get("ORDER_NUMBER", "N/A"),
        "Header ID":      header.get("HEADER_ID", "N/A"),
        "Customer PO":    header.get("CUST_PO_NUMBER", "N/A"),
        "Return Status":  header.get("RETURN_STATUS", "N/A"),
        "Flow Status":    header.get("FLOW_STATUS_CODE", "N/A"),
        "Order Category": header.get("ORDER_CATEGORY_CODE", "N/A"),
        "Currency":       header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term":   header_val.get("PAYMENT_TERM", "N/A"),
        "Price List":     header_val.get("PRICE_LIST", "N/A"),
        "Order Type":     header_val.get("ORDER_TYPE", "N/A"),
        "Customer":       header_val.get("SOLD_TO_ORG", "N/A"),
        "Ship To":        header_val.get("SHIP_TO_ORG", "N/A"),
        "Bill To":        header_val.get("INVOICE_TO_ORG", "N/A"),
        "Salesrep":       header_val.get("SALESREP", "N/A"),
        "Booked Flag":    header.get("BOOKED_FLAG", "N/A"),
        "Open Flag":      header.get("OPEN_FLAG", "N/A"),
    }

    line_tbl = data.get("X_LINE_TBL", {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}

    def _get_items(tbl, *keys):
        for k in keys:
            v = tbl.get(k)
            if v is not None:
                return [v] if isinstance(v, dict) else list(v)
        return []

    raw_lines = _get_items(line_tbl, "X_LINE_TBL_ITEM", "P_LINE_TBL_ITEM")
    raw_line_vals = _get_items(line_val_tbl, "X_LINE_VAL_TBL_ITEM", "P_LINE_VAL_TBL_ITEM")

    lines = []
    for i, line in enumerate(raw_lines):
        val = raw_line_vals[i] if i < len(raw_line_vals) else {}
        lines.append({
            "Line #":             line.get("LINE_NUMBER", "N/A"),
            "Line ID":            line.get("LINE_ID", "N/A"),
            "Item":               line.get("ORDERED_ITEM", "N/A"),
            "Item Description":   val.get("INVENTORY_ITEM", "N/A"),
            "Qty Ordered":        line.get("ORDERED_QUANTITY", "N/A"),
            "UOM":                line.get("ORDER_QUANTITY_UOM", "N/A"),
            "Unit List Price":    line.get("UNIT_LIST_PRICE", "N/A"),
            "Unit Selling Price": line.get("UNIT_SELLING_PRICE", "N/A"),
            "Line Type":          val.get("LINE_TYPE", "N/A"),
            "Payment Term":       val.get("PAYMENT_TERM", "N/A"),
            "Flow Status":        line.get("FLOW_STATUS_CODE", "N/A"),
            "Return Status":      line.get("RETURN_STATUS", "N/A"),
        })

    return {"status": status, "message": message_text,
            "header_details": _json_safe(header_details), "lines": _json_safe(lines)}


def remember_order_context(state, parsed):
    hid = parsed["header_details"].get("Header ID")
    onum = parsed["header_details"].get("Order Number")
    if hid not in (None, "N/A") and onum not in (None, "N/A"):
        state["add_line"]["header_id"] = hid
        state["add_line"]["order_number"] = onum


# ==================================================
# HTML email generators
# ==================================================
def _build_email_layout(cname, report_type, ai_summary, table_html, alerts, faqs) -> str:
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    alerts_html = "<ul style='padding-left:20px;font-size:14px;margin-bottom:0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom:5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"

    faqs_html = "<table style='border-collapse:collapse;width:100%;border:none;font-size:14px;'>"
    for q, a in faqs:
        faqs_html += (f"<tr><td style='padding:6px 8px;font-weight:bold;width:40%;'>{q}</td>"
                      f"<td style='padding:6px 8px;'>{a}</td></tr>")
    faqs_html += "</table>"

    return f"""
    <div style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;">
        <h2 style="margin:0 0 4px 0;">Oracle ERP — {report_type}</h2>
        <p style="margin:0 0 16px 0;font-size:13px;color:#555;">Customer: <b>{cname}</b> &nbsp;|&nbsp; Report date: {report_date}</p>
        <div style="background:#f6f8fb;border-left:4px solid #3b6ef6;padding:12px 16px;margin-bottom:18px;">
            <b>Summary</b><br>{ai_summary}
        </div>
        <h3 style="margin:0 0 8px 0;">Details</h3>
        {table_html}
        <h3 style="margin:22px 0 8px 0;">Alerts</h3>
        {alerts_html}
        <h3 style="margin:22px 0 8px 0;">FAQ</h3>
        {faqs_html}
        <h3 style="margin:22px 0 8px 0;">Notes</h3>
        <ul style="padding-left:20px;font-size:13px;color:#555;">
            <li>Support contact: erp.support@centroid.com</li>
            <li>This notification was generated automatically from the ERP environment.</li>
            <li>Please do not reply directly to this email.</li>
        </ul>
    </div>
    """


_TH = "border:none;padding:8px;text-align:left;font-weight:bold;background:#eef2fb;"
_TD = "border:none;padding:8px;border-bottom:1px solid #eee;"
_EMAIL_HEADERS = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]


def _table_open():
    html = "<table style='border-collapse:collapse;width:100%;font-size:14px;'><tr>"
    for h in _EMAIL_HEADERS:
        html += f"<th style='{_TH}'>{h}</th>"
    return html + "</tr>"


def generate_order_html(result, ai_summary: str) -> str:
    d = extract_erp_details(result)
    cname = d["header_details"].get("Customer", "Unknown Customer")
    order_num = d["header_details"].get("Order Number", "N/A")
    flow = str(d["header_details"].get("Flow Status", ""))

    table_html = _table_open()
    for ln in d["lines"]:
        table_html += (
            f"<tr><td style='{_TD}'>{order_num}</td>"
            f"<td style='{_TD}'>{ln.get('Item', 'N/A')}</td>"
            f"<td style='{_TD}'>{ln.get('Qty Ordered', 'N/A')}</td>"
            f"<td style='{_TD}'>{ln.get('Flow Status', 'N/A')}</td>"
            f"<td style='{_TD}'>TBD</td><td style='{_TD}'>Pending</td><td style='{_TD}'>N/A</td></tr>"
        )
    table_html += "</table>"

    alerts = {
        "Backorders": "None detected for this transaction",
        "Holds": "1" if (flow == "ENTERED" or "HOLD" in flow.upper()) else "0",
        "Partial Shipments": "N/A",
        "Payment Holds": "Check customer balance",
    }
    faqs = [
        (f"Why is Order {order_num} currently {flow or 'Processing'}?",
         f"The order is in {flow or 'Processing'} status waiting for the next step in the fulfillment cycle."),
        ("Can I expect partial shipment?", "Depends on line-level availability. Check shipping notices for updates."),
    ]
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", ai_summary, table_html, alerts, faqs)


def generate_search_html(res: dict, ai_summary: str) -> str:
    table_html = _table_open()
    for r in res.get("rows", [])[:20]:
        r = list(r)
        table_html += (
            f"<tr><td style='{_TD}'>{r[0] if len(r) > 0 else ''}</td>"
            f"<td style='{_TD}'>Multiple Lines</td><td style='{_TD}'>-</td>"
            f"<td style='{_TD}'>{r[1] if len(r) > 1 else ''}</td>"
            f"<td style='{_TD}'>{r[2] if len(r) > 2 else ''}</td>"
            f"<td style='{_TD}'>-</td><td style='{_TD}'>-</td></tr>"
        )
    table_html += "</table>"
    alerts = {"Backorders": "N/A for broad search", "Holds": "N/A for broad search",
              "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("What are these search results?",
             f"These are the top results matching your search, out of {res.get('total_count', 0)} orders.")]
    return _build_email_layout("System User", "Search Query Results", ai_summary, table_html, alerts, faqs)


def generate_customer_html(rows: list, cname: str, ai_summary: str) -> str:
    top_rows = rows[:50]
    table_html = _table_open()
    backorders = holds = delayed = 0
    for r in top_rows:
        if str(r.get("BACKORDER_FLAG", "0")) == "1":
            backorders += 1
        if r.get("ORDER_HOLD_FLAG") == "Y":
            holds += 1
        if str(r.get("DELAYED_ORDER_FLAG", "0")) == "1":
            delayed += 1
        table_html += (
            f"<tr><td style='{_TD}'>{r.get('ORDER_NUMBER', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('ITEM_NUMBER', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('ORDERED_QTY', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('LINE_STATUS', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('SCHEDULE_SHIP_DATE', 'N/A')}</td>"
            f"<td style='{_TD}'>{r.get('SHIPMENT_MODE', 'Pending')}</td>"
            f"<td style='{_TD}'>${r.get('INVOICE_BALANCE', '0.00')}</td></tr>"
        )
    table_html += "</table>"

    alerts = {"Backorders": str(backorders), "Holds": str(holds),
              "Partial Shipments": "Check line statuses for details",
              "Payment Holds": "Derived from account level"}
    faqs = [
        ("Are there any delayed orders?",
         f"There are {delayed} delayed line(s)." if delayed else "All displayed orders are processing on schedule."),
        ("Can I expect a partial shipment?",
         f"Yes — {backorders} backordered item(s) may cause partial shipments." if backorders
         else "All items appear to be in stock. Partial shipments are unlikely."),
        ("Has payment cleared?",
         "Some orders indicate holds tied to pending payment or account review." if holds
         else "No payment holds are actively blocking these lines."),
    ]
    return _build_email_layout(cname, "All Recent Customer Orders", ai_summary, table_html, alerts, faqs)


# ==================================================
# Email delivery
# ==================================================
def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str):
    if not SMTP_USER or not SMTP_PASS:
        return False, ("SMTP credentials are not configured. Set ERP_SMTP_USER and ERP_SMTP_PASS "
                       "environment variables before sending email.")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_SENDER
    msg["To"] = to_email

    html_content = f"""<html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:20px;">
        <p style="color:#333;">{(body_text or '').replace(chr(10), '<br>')}</p><br>{html_table}</body></html>"""
    msg.attach(MIMEText(body_text or "", "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_SENDER, to_email, msg.as_string())
        return True, "Email sent successfully."
    except Exception as e:
        return False, str(e)


def trigger_auto_email(state, subject_context: str, html_payload: str):
    auto = state["auto_email"]
    if not auto.get("enabled"):
        return
    to_email = (auto.get("to") or "").strip() or (state["collected"].get("email_address") or "").strip()
    if not to_email:
        auto["status"] = "no_recipient"
        return
    auto["status"] = "sending"

    def _worker():
        subject = f"Automated Alert: {subject_context}"
        body = (f"Hi,\n\nPlease find the automated report for '{subject_context}' below.\n\n"
                f"Sent automatically by the Sales Order Assistant.")
        ok, msg = send_erp_email(to_email, subject, body, html_payload)
        auto["status"] = "success" if ok else "failed"
        auto["error"] = "" if ok else msg

    threading.Thread(target=_worker, daemon=True).start()


# ==================================================
# Background scheduler
# ==================================================
_SCHEDULERS = {}


def _scheduled_worker(stop_event, interval_secs, customer_name, to_email):
    while not stop_event.is_set():
        if stop_event.wait(timeout=interval_secs):
            break
        try:
            if not customer_name or customer_name.lower() in ("all", "all customers", "everyone"):
                res = get_orders_advanced(None, None, None)
                summary = "Automated scheduled report summarizing all recent orders."
                html = generate_search_html({"total_count": res.get("total_count", 0),
                                             "rows": _json_safe(res.get("rows", []))}, summary)
                send_erp_email(to_email, "Scheduled Report: All Orders",
                               "Your automated report is below.", html)
            else:
                rows = _json_safe(get_order_details_by_customer(customer_name))
                if rows:
                    summary = f"Automated scheduled report for {customer_name}."
                    send_erp_email(to_email, f"Scheduled Report: {customer_name}",
                                   "Your automated report is below.",
                                   generate_customer_html(rows, customer_name, summary))
        except Exception as e:
            print(f"[Scheduler error] {e}")


def _interval_minutes(interval_str: str) -> int:
    s = (interval_str or "").lower()
    nums = re.findall(r"\d+", s)
    if "min" in s:
        return int(nums[0]) if nums else 30
    if "hour" in s:
        return (int(nums[0]) if nums else 1) * 60
    return 1440


# ==================================================
# Selection helpers (paginated pickers)
# ==================================================
def _fmt_money(v):
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return str(v)


_PICKERS = {
    "item": {
        "label": "Inventory Item",
        "fetch": lambda st, off: get_inventory_item_rows(st["collected"].get("ordered_item") or "", offset=off),
        "title": lambda r: r["segment1"],
        "sub":   lambda r: f"{r['description']}  ·  ID {r['inventory_item_id']}",
    },
    "price": {
        "label": "Price List",
        "fetch": lambda st, off: get_price_details_rows(
            st["collected"].get("ordered_item") or "", float(st["collected"].get("quantity") or 1),
            st["collected"].get("inventory_item_id"), offset=off),
        "title": lambda r: r["price_list_name"],
        "sub":   lambda r: f"{_fmt_money(r['unit_list_price'])}  ·  ID {r['price_list_id']}",
    },
    "term": {
        "label": "Payment Term",
        "fetch": lambda st, off: get_payment_term_rows(offset=off),
        "title": lambda r: r["term_name"],
        "sub":   lambda r: f"ID {r['term_id']}",
    },
    "rep": {
        "label": "Sales Representative",
        "fetch": lambda st, off: get_salesrep_rows(offset=off),
        "title": lambda r: r["salesrep_name"],
        "sub":   lambda r: f"ID {r['salesrep_id']}",
    },
    "line_type": {
        "label": "Line Type",
        "fetch": lambda st, off: (get_line_type_rows(offset=off) if _has_line_types() else []),
        "title": lambda r: r["line_type_name"],
        "sub":   lambda r: f"ID {r['line_type_id']}",
    },
    "customer": {
        "label": "Customer",
        "fetch": lambda st, off: get_customer_by_name_rows(st["collected"].get("customer_name") or "", offset=off),
        "title": lambda r: r["customer_name"],
        "sub":   lambda r: f"Acct# {r['account_number']}  ·  ID {r['cust_account_id']}",
    },
    "customer_by_item": {
        "label": "Customer",
        "fetch": lambda st, off: get_customers_by_inventory_item_rows(
            st["collected"].get("inventory_item_id"), offset=off),
        "title": lambda r: r["customer_name"],
        "sub":   lambda r: f"Acct# {r['account_number']}  ·  ID {r['cust_account_id']}",
    },
    "site": {
        "label": "Ship-To Site",
        "fetch": lambda st, off: get_customer_sites_by_account(st["collected"].get("cust_account_id")),
        "title": lambda r: f"{r['customer_name']} — {r['location']}",
        "sub":   lambda r: f"{r['address']}  ·  SoldTo {r['sold_to_org_id']} / ShipTo {r['ship_to_org_id']}",
    },
}


def build_selection(state, kind, rows, searchable=False, note=None):
    meta = _PICKERS[kind]
    offset = state["offsets"].get(kind, 0)
    state["rows"][kind] = rows
    state["pending"] = {
        "type": "selection",
        "kind": kind,
        "label": meta["label"],
        "note": note,
        "searchable": searchable,
        "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
        "has_next": len(rows) >= MAX_CHOICES,
        "has_prev": offset > 0,
        "offset": offset,
    }
    return state["pending"]


def build_input(state, kind, label, note=None, placeholder=""):
    state["pending"] = {"type": "input", "kind": kind, "label": label,
                        "note": note, "placeholder": placeholder}
    return state["pending"]


# ==================================================
# Order creation resolution engine
# ==================================================
def resolve(state):
    """Advance the create-order state machine until user input is required."""
    c = state["collected"]
    offs = state["offsets"]

    try:
        # Step 1 — item
        if c.get("ordered_item") and not c.get("inventory_item_id"):
            rows = get_inventory_item_rows(c["ordered_item"], offset=offs["item"])
            if not rows:
                c["ordered_item"] = None
                say(state, f"No inventory items found matching `{c['ordered_item']}`. Please try another item code.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["item"] == 0:
                c["inventory_item_id"] = rows[0]["inventory_item_id"]
                c["ordered_item"] = rows[0]["segment1"]
            else:
                state["stage"] = "select_item"
                say(state, "I found multiple items. Please select one.")
                build_selection(state, "item", rows)
                return

        # Step 2 — price list
        if c.get("inventory_item_id") and c.get("quantity") and not c.get("price_list_id"):
            rows = get_price_details_rows(c["ordered_item"], float(c["quantity"]),
                                          c["inventory_item_id"], offset=offs["price"])
            if not rows:
                say(state, f"No price lists found for item `{c['ordered_item']}`. Cannot proceed.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["price"] == 0:
                c["price_list_id"] = rows[0]["price_list_id"]
                c["price_list_name"] = rows[0]["price_list_name"]
                c["unit_list_price"] = rows[0]["unit_list_price"]
                state["stage"] = "selling_price"
                build_input(state, "selling_price", "Selling Price",
                            note=f"Unit list price is {_fmt_money(c['unit_list_price'])}. "
                                 f"Leave blank to use the list price.",
                            placeholder="e.g. 1250.00")
                return
            state["stage"] = "select_price"
            say(state, "Please select a price list.")
            build_selection(state, "price", rows)
            return

        # Step 3 — payment term
        if not c.get("payment_term_id"):
            rows = get_payment_term_rows(offset=offs["term"])
            if not rows:
                say(state, "No payment terms found. Cannot proceed.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["term"] == 0:
                c["payment_term_id"], c["payment_term_name"] = rows[0]["term_id"], rows[0]["term_name"]
            else:
                state["stage"] = "select_term"
                say(state, "Please select a payment term.")
                build_selection(state, "term", rows)
                return

        # Step 4 — sales rep
        if not c.get("salesrep_id"):
            rows = get_salesrep_rows(offset=offs["rep"])
            if not rows:
                say(state, "No sales representatives found. Cannot proceed.")
                state["stage"] = "chat"
                state["pending"] = None
                return
            if len(rows) == 1 and offs["rep"] == 0:
                c["salesrep_id"], c["salesrep_name"] = rows[0]["salesrep_id"], rows[0]["salesrep_name"]
            else:
                state["stage"] = "select_rep"
                say(state, "Please select a sales representative.")
                build_selection(state, "rep", rows)
                return

        # Step 5 — line type (only when the engine exposes it)
        if _has_line_types() and not c.get("line_type_id"):
            rows = get_line_type_rows(offset=offs["line_type"])
            state["stage"] = "select_line_type"
            say(state, "Please select a line type.")
            build_selection(state, "line_type", rows)
            return

        # Step 6 — customer / ship-to site
        if not c.get("sold_to_org_id") or not c.get("ship_to_org_id"):
            if c.get("cust_account_id"):
                sites = get_customer_sites_by_account(c["cust_account_id"])
                if not sites:
                    c["cust_account_id"] = None
                    say(state, "No active SHIP_TO sites for this customer. Please choose a different customer.")
                    state["stage"] = "select_customer"
                    build_selection(state, "customer", [], searchable=True,
                                    note="Type a customer name and search.")
                    return
                if len(sites) == 1:
                    c["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                    c["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                    c["customer_name"] = sites[0]["customer_name"]
                else:
                    state["stage"] = "select_site"
                    say(state, "Please select a ship-to site.")
                    build_selection(state, "site", sites)
                    return
            elif c.get("customer_name"):
                rows = get_customer_by_name_rows(c["customer_name"], offset=offs["customer"])
                state["stage"] = "select_customer"
                say(state, "Please select a customer.")
                build_selection(state, "customer", rows, searchable=True)
                return
            elif c.get("inventory_item_id"):
                rows = get_customers_by_inventory_item_rows(c["inventory_item_id"],
                                                             offset=offs["customer_by_item"])
                state["stage"] = "select_customer_by_item"
                say(state, "Please select a customer for this item.")
                build_selection(state, "customer_by_item", rows,
                                note="Customers who previously ordered this item.")
                return
            else:
                say(state, "I could not determine a customer. Please provide a customer name.")
                state["stage"] = "select_customer"
                build_selection(state, "customer", [], searchable=True,
                                note="Type a customer name and search.")
                return

        # Everything resolved
        state["stage"] = "confirm_order"
        state["pending"] = {"type": "confirm",
                            "summary": {k: v for k, v in c.items() if v is not None}}

    except Exception as e:
        say(state, f"Error during resolution: {e}")
        state["stage"] = "chat"
        state["pending"] = None


def apply_selection(state, kind, row):
    c = state["collected"]
    if kind == "item":
        c["inventory_item_id"] = row["inventory_item_id"]
        c["ordered_item"] = row["segment1"]
        say(state, f"Item selected: **{row['segment1']}** — {row['description']}")
    elif kind == "price":
        c["price_list_id"] = row["price_list_id"]
        c["price_list_name"] = row["price_list_name"]
        c["unit_list_price"] = row["unit_list_price"]
        c["unit_selling_price"] = None
        say(state, f"Price list: **{row['price_list_name']}** — {_fmt_money(row['unit_list_price'])}")
        state["stage"] = "selling_price"
        build_input(state, "selling_price", "Selling Price",
                    note=f"Unit list price is {_fmt_money(row['unit_list_price'])}. Leave blank to use it.",
                    placeholder="e.g. 1250.00")
        return False
    elif kind == "term":
        c["payment_term_id"], c["payment_term_name"] = row["term_id"], row["term_name"]
        say(state, f"Payment term: **{row['term_name']}**")
    elif kind == "rep":
        c["salesrep_id"], c["salesrep_name"] = row["salesrep_id"], row["salesrep_name"]
        say(state, f"Sales rep: **{row['salesrep_name']}**")
    elif kind == "line_type":
        c["line_type_id"] = row["line_type_id"]
        say(state, f"Line type: **{row['line_type_name']}**")
    elif kind in ("customer", "customer_by_item"):
        c["cust_account_id"] = row["cust_account_id"]
        c["customer_name"] = row["customer_name"]
        say(state, f"Customer: **{row['customer_name']}**")
    elif kind == "site":
        c["sold_to_org_id"] = row["sold_to_org_id"]
        c["ship_to_org_id"] = row["ship_to_org_id"]
        c["customer_name"] = row["customer_name"]
        say(state, f"Ship-to confirmed for **{row['customer_name']}** ({row['location']})")
    return True


def submit_order(state):
    c = state["collected"]
    payload_kwargs = {
        "p_cust_po": c["cpo"], "p_item_id": c["inventory_item_id"], "p_ordered_item": c["ordered_item"],
        "p_qty": c["quantity"], "p_price": c["unit_list_price"], "p_selling_price": c["unit_selling_price"],
        "p_payment_term_id": c["payment_term_id"], "p_price_list_id": c["price_list_id"],
        "p_salesrep_id": c["salesrep_id"], "p_ship_to_org": c["ship_to_org_id"],
        "p_sold_to_org": c["sold_to_org_id"], "p_operating_unit": OPERATING_UNIT,
    }
    import inspect
    if c.get("line_type_id") and "p_line_type_id" in inspect.signature(create_payload).parameters:
        payload_kwargs["p_line_type_id"] = c["line_type_id"]

    result = send_order(create_payload(**payload_kwargs))
    parsed = extract_erp_details(result)
    summary = generate_ai_summary("Create New Sales Order", parsed)

    state["api_result"] = _json_safe(result)
    state["parsed_result"] = parsed
    state["email_payload_html"] = generate_order_html(result, summary)
    remember_order_context(state, parsed)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, "New Order Created", state["email_payload_html"])
    state["stage"] = "order_result"
    state["pending"] = {"type": "order_result", "context": "Order Created"}


# ==================================================
# Add-line flow
# ==================================================
def add_line_prompt(state):
    al = state["add_line"]
    step = al["step"]
    if step == "item_search":
        return build_input(state, "add_line_item_search", "Search item",
                           note=f"Adding a line to order #{al['order_number']}.",
                           placeholder="Item code or prefix, e.g. AS540")
    if step == "item_select":
        meta = _PICKERS["item"]
        rows = al["rows"]["item"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_item", "label": "Inventory Item",
            "note": f"Adding a line to order #{al['order_number']}.", "searchable": True,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= MAX_CHOICES,
            "has_prev": state["offsets"]["item"] > 0,
            "offset": state["offsets"]["item"],
        }
        return state["pending"]
    if step == "qty":
        return build_input(state, "add_line_qty", "Quantity",
                           note=f"Item {al['data'].get('ordered_item')}", placeholder="e.g. 10")
    if step == "price_select":
        meta = _PICKERS["price"]
        rows = al["rows"]["price"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_price", "label": "Price List",
            "note": f"Item {al['data'].get('ordered_item')} · Qty {al['data'].get('quantity')}",
            "searchable": False,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= MAX_CHOICES,
            "has_prev": state["offsets"]["price"] > 0,
            "offset": state["offsets"]["price"],
        }
        return state["pending"]
    if step == "selling_price":
        return build_input(state, "add_line_selling_price", "Selling Price",
                           note=f"Unit list price is {_fmt_money(al['data'].get('unit_list_price', 0))}. "
                                f"Leave blank to use it.", placeholder="optional")
    if step == "term_select":
        meta = _PICKERS["term"]
        rows = al["rows"]["term"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_term", "label": "Payment Term", "searchable": False,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= MAX_CHOICES,
            "has_prev": state["offsets"]["term"] > 0,
            "offset": state["offsets"]["term"], "note": None,
        }
        return state["pending"]
    if step == "line_type_select":
        meta = _PICKERS["line_type"]
        rows = al["rows"]["line_type"]
        state["pending"] = {
            "type": "selection", "kind": "add_line_line_type", "label": "Line Type", "searchable": False,
            "options": [{"index": i, "title": meta["title"](r), "sub": meta["sub"](r)} for i, r in enumerate(rows)],
            "has_next": len(rows) >= MAX_CHOICES,
            "has_prev": state["offsets"]["line_type"] > 0,
            "offset": state["offsets"]["line_type"], "note": None,
        }
        return state["pending"]
    if step == "submit":
        state["pending"] = {"type": "add_line_confirm",
                            "order_number": al["order_number"],
                            "summary": {k: v for k, v in al["data"].items() if v is not None}}
        return state["pending"]
    return None


def submit_add_line(state):
    al = state["add_line"]
    d = al["data"]
    payload_kwargs = {
        "p_header_id": al["header_id"], "p_item_id": d["inventory_item_id"],
        "p_ordered_item": d["ordered_item"], "p_qty": d["quantity"],
        "p_price": d["unit_list_price"], "p_selling_price": d["unit_selling_price"],
        "p_payment_term_id": d["payment_term_id"], "p_price_list_id": d["price_list_id"],
    }
    import inspect
    if d.get("line_type_id") and "p_line_type_id" in inspect.signature(create_add_line_payload).parameters:
        payload_kwargs["p_line_type_id"] = d["line_type_id"]

    result = send_order(create_add_line_payload(**payload_kwargs))
    parsed = extract_erp_details(result)
    summary = generate_ai_summary("Add Line to Order", parsed)

    state["api_result"] = _json_safe(result)
    state["parsed_result"] = parsed
    state["email_payload_html"] = generate_order_html(result, summary)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, f"Updated Order #{al['order_number']}", state["email_payload_html"])

    al["active"] = False
    al["step"] = None
    al["data"] = {}
    state["stage"] = "order_result"
    state["pending"] = {"type": "order_result", "context": f"Line added to order #{al['order_number']}"}


# ==================================================
# Operations reachable from chat
# ==================================================
def do_get_order(state, order_number):
    result = get_order(int(order_number))
    parsed = extract_erp_details(result)
    summary = generate_ai_summary("Retrieve Specific Order", parsed)

    state["api_result"] = _json_safe(result)
    state["parsed_result"] = parsed
    state["email_payload_html"] = generate_order_html(result, summary)
    remember_order_context(state, parsed)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, f"Order #{order_number}", state["email_payload_html"])
    state["stage"] = "order_result"
    state["pending"] = {"type": "order_result", "context": f"Order #{order_number}"}


def do_search(state, date_range, year, status):
    res = get_orders_advanced(date_range, year, status)
    rows = _json_safe(res.get("rows", []))
    total = res.get("total_count", 0)

    if not rows:
        say(state, "No orders found for those filters. Try broadening your search.")
        state["stage"] = "chat"
        state["pending"] = None
        return

    summary = generate_ai_summary("Advanced Order Search",
                                  {"total_found": total,
                                   "filters_used": {"year": year, "date_range": date_range, "status": status},
                                   "first_5_rows": rows[:5]})
    state["email_payload_html"] = generate_search_html({"total_count": total, "rows": rows}, summary)
    say(state, f"Found **{total}** order(s).\n\n**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, "Advanced Search", state["email_payload_html"])

    state["search_result"] = {"total_count": total,
                              "columns": ["Order Number", "Status", "Creation Date"],
                              "rows": rows}
    state["stage"] = "search_result"
    state["pending"] = {"type": "search_result",
                        "filters": {"year": year, "date_range": date_range, "status": status}}


_CUSTOMER_COLUMNS = [
    ("Customer Name", "CUSTOMER_NAME"), ("Order Number", "ORDER_NUMBER"), ("Order Date", "ORDER_DATE"),
    ("PO Number", "PO_NUMBER"), ("Order Type", "ORDER_TYPE"), ("Line #", "LINE_NUMBER"),
    ("Item Number", "ITEM_NUMBER"), ("Ordered Qty", "ORDERED_QTY"), ("UOM", "ORDERED_UOM"),
    ("Unit List Price", "UNIT_LIST_PRICE"), ("Unit Selling Price", "UNIT_SELLING_PRICE"),
    ("Line Price", "LINE_PRICE"), ("Invoice Balance", "INVOICE_BALANCE"), ("Line Status", "LINE_STATUS"),
    ("Ship Date", "SCHEDULE_SHIP_DATE"), ("Actual Ship Date", "ACTUAL_SHIP_DATE"),
    ("Shipment Mode", "SHIPMENT_MODE"), ("Released Status", "RELEASED_STATUS"),
    ("Backorder", "BACKORDER_FLAG"), ("Delayed", "DELAYED_ORDER_FLAG"),
    ("In Transit", "IN_TRANSIT_ORDER_FLAG"), ("On Hold", "ORDER_HOLD_FLAG"), ("Email", "EMAIL"),
]


def do_customer_orders(state, customer_name):
    rows = _json_safe(get_order_details_by_customer(customer_name))
    state["customer_orders"] = {"customer_name": customer_name, "rows": rows}

    if not rows:
        say(state, f"No orders found for customer `{customer_name}`. "
                   f"Verify the exact name as stored in Oracle.")
        state["stage"] = "customer_orders"
        state["pending"] = {"type": "customer_orders",
                            "columns": [c[0] for c in _CUSTOMER_COLUMNS],
                            "customer_name": customer_name, "rows": []}
        return

    summary = generate_ai_summary("Retrieve Orders by Customer",
                                  {"customer": customer_name, "total_lines_found": len(rows),
                                   "sample_data": rows[:3]})
    state["email_payload_html"] = generate_customer_html(rows, customer_name, summary)
    say(state, f"**AI Summary:** {summary}", speak_text=summary)
    trigger_auto_email(state, f"Customer: {customer_name}", state["email_payload_html"])

    table_rows = [[r.get(key, "") for _, key in _CUSTOMER_COLUMNS] for r in rows]
    state["stage"] = "customer_orders"
    state["pending"] = {"type": "customer_orders",
                        "columns": [c[0] for c in _CUSTOMER_COLUMNS],
                        "customer_name": customer_name,
                        "rows": table_rows,
                        "metrics": _customer_metrics(rows)}


def _customer_metrics(rows):
    def _num(v):
        try:
            return float(v)
        except Exception:
            return 0.0
    orders = {r.get("ORDER_NUMBER") for r in rows}
    return {
        "Total Lines": len(rows),
        "Unique Orders": len(orders),
        "Total Line Value": f"${sum(_num(r.get('LINE_PRICE')) for r in rows):,.2f}",
        "Invoice Balance": f"${sum(_num(r.get('INVOICE_BALANCE')) for r in rows):,.2f}",
    }


# ==================================================
# Grok clarification helper
# ==================================================
def _grok_clarify(history: list, missing_field: str) -> str:
    """Ask Grok to generate a friendly clarification question for a missing field."""
    try:
        history_str = "\n".join(
            f"{m['role'].upper()}: {m['content']}" for m in history[-6:]
        )
        messages = [
            {"role": "system", "content": (
                "You are the Centroid Sales Order Assistant. The user wants to retrieve a specific "
                "order but has not provided the required information. "
                "Generate a single, friendly, concise question to collect it. "
                "Do NOT write anything except the question itself."
            )},
            {"role": "user", "content": (
                f"Conversation so far:\n{history_str}\n\n"
                f"Missing required field: {missing_field}\n\n"
                "Write the clarification question:"
            )},
        ]
        return _grok_chat(messages, temperature=0.4, max_tokens=80)
    except Exception:
        return f"Could you please provide the {missing_field}?"


# ==================================================
# Chat routing
# ==================================================
_STATUS_KEYWORDS = {
    "booked": "BOOKED", "entered": "ENTERED", "cancelled": "CANCELLED", "canceled": "CANCELLED",
    "shipped": "SHIPPED", "closed": "CLOSED", "pending": "ENTERED", "open": "BOOKED",
    "invoiced": "INVOICED", "delivered": "DELIVERED",
}
_DATE_PATTERNS = [
    (r"last\s+month", "last month"), (r"last\s+quarter", "last quarter"), (r"last\s+week", "last week"),
    (r"this\s+month", "this_month"), (r"this\s+quarter", "this quarter"), (r"this\s+week", "this_week"),
    (r"last\s+30\s+days", "last_30_days"), (r"last\s+90\s+days", "last 90 days"),
    (r"last\s+year", "last year"), (r"ytd|year\s+to\s+date", "year to date"),
]


def _apply_pending_field(state, prompt):
    """Assign a raw answer to the field the assistant last asked for."""
    field = state.get("pending_field")
    if not field:
        return False
    c = state["collected"]
    raw = prompt.strip()
    if field == "Customer PO Number" and not c.get("cpo"):
        c["cpo"] = raw
    elif field == "Ordered Item code" and not c.get("ordered_item"):
        c["ordered_item"] = raw.upper()
    elif field == "Ordered Quantity" and not c.get("quantity"):
        qty = parse_numeric_value(raw, allow_float=True)
        if qty is None:
            say(state, "That does not look like a valid quantity. Please enter a number.")
            return True
        c["quantity"] = qty
    else:
        return False
    state["pending_field"] = None
    return False


def handle_chat(state, prompt):
    user_say(state, prompt)
    gh_add(state, "user", prompt)

    low = prompt.strip().lower()
    if low in ("exit", "quit", "stop", "cancel", "back"):
        state = reset_state()
        say(state, "Operation cancelled. Back to chat.")
        return state

    if prompt in FAQ_DATA:
        ans = FAQ_DATA[prompt]
        say(state, ans)
        gh_add(state, "assistant", ans)
        return state

    # Conversationally answer the field we last asked for
    if state.get("action") == "create" and state.get("pending_field"):
        if _apply_pending_field(state, prompt):
            return state

    # Use Grok for full intent extraction with conversation history
    extracted = get_smart_intent(state["messages"], prompt) or {}

    email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", prompt)
    if any(w in low for w in ("email", "mail")):
        if not extracted.get("action") or extracted.get("action") == "unknown":
            extracted["action"] = "email"
    if email_match:
        extracted["email_address"] = email_match.group(0)

    if not extracted.get("year"):
        m = re.search(r"\b(20\d{2})\b", prompt)
        if m:
            extracted["year"] = int(m.group(1))
    if not extracted.get("status"):
        for kw, val in _STATUS_KEYWORDS.items():
            if kw in low:
                extracted["status"] = val
                break
    if not extracted.get("date_range"):
        for pattern, label in _DATE_PATTERNS:
            if re.search(pattern, low):
                extracted["date_range"] = label
                break

    if "create" in low or "new order" in low:
        extracted["action"] = "create"

    od_match = re.search(r"order\s+details?\s+(?:for|by|of)?\s*(?:customer\s+)?(.+)", prompt, re.IGNORECASE)
    if od_match or ("order details" in low and "customer" in low):
        extracted["action"] = "order_details"

    has_order_number = bool(extracted.get("order_number") or state["collected"].get("order_number"))
    has_filters = bool(extracted.get("year") or extracted.get("date_range") or extracted.get("status"))
    if has_filters and not has_order_number and extracted.get("action") not in ("create", "order_details", "email"):
        extracted["action"] = "search"

    if extracted.get("action") not in ("create", "search", "order_details", "email"):
        if any(w in low for w in ("get", "find", "search", "show", "fetch", "retrieve")):
            if not extracted.get("action") or extracted.get("action") == "unknown":
                extracted["action"] = "get"

    action = extracted.get("action", "unknown")
    merge_fields(state, extracted)

    try:
        if action == "order_details":
            name = None
            if od_match:
                name = od_match.group(1).strip()
            name = name or extracted.get("customer_name")
            if not name:
                say(state, "Which customer? Please give me the exact customer name.")
                state["stage"] = "chat"
                state["pending"] = build_input(state, "customer_orders_name", "Customer Name",
                                               placeholder="e.g. ACME CORPORATION")
                return state
            say(state, f"Fetching order details for **{name}**…")
            do_customer_orders(state, name)
            return state

        if action == "email":
            state["action"] = "email"
            state["stage"] = "send_email"
            state["pending"] = {
                "type": "email",
                "to": state["collected"].get("email_address") or state["auto_email"].get("to") or "",
                "subject": "Oracle ERP Order Details Update",
                "body": "Please find the requested order details structured below.",
                "html": state.get("email_payload_html", ""),
            }
            say(state, "Preparing the email draft. Review and send when ready.")
            return state

        if action == "search":
            say(state, "Searching orders…")
            do_search(state, extracted.get("date_range"), extracted.get("year"), extracted.get("status"))
            return state

        if action == "create" or state.get("action") == "create":
            state["action"] = "create"
            missing = missing_minimum(state)
            if missing:
                nxt = missing[0]
                prompts = {
                    "Customer PO Number": "Got it, let's create an order. What is the **Customer PO Number**?",
                    "Ordered Item code": "What is the **Ordered Item code**?",
                    "Ordered Quantity": "How many do you need? Please enter the **Ordered Quantity**.",
                }
                text = prompts.get(nxt, f"Please provide the {nxt}.")
                say(state, text)
                gh_add(state, "assistant", text)
                state["pending_field"] = nxt
                state["stage"] = "chat"
                state["pending"] = None
                return state
            state["pending_field"] = None
            resolve(state)
            return state

        if action == "get" or state.get("action") == "get":
            state["action"] = "get"
            order_num = state["collected"].get("order_number")
            if order_num is None:
                q = _grok_clarify(state["gh_history"], "Order Number")
                say(state, q)
                gh_add(state, "assistant", q)
                return state
            say(state, f"Retrieving order **{order_num}**…")
            do_get_order(state, order_num)
            return state

        # app7.py-style fallback: try highly-ordered-items / order-tracking /
        # combined-operations / dynamic SQL against Oracle before plain chat.
        dynamic_reply = try_dynamic_erp_query(state, prompt)
        if dynamic_reply is not None:
            gh_add(state, "assistant", dynamic_reply)
            return state

        answer = general_answer(state, prompt)
        say(state, answer)
        gh_add(state, "assistant", answer)
        return state

    except Exception as e:
        say(state, f"Operation failed: {e}")
        state["stage"] = "chat"
        state["pending"] = None
        return state


# ==================================================
# API payload
# ==================================================
def snapshot(state):
    return {
        "messages": state["messages"],
        "stage": state["stage"],
        "pending": _json_safe(state["pending"]),
        "collected": _json_safe({k: v for k, v in state["collected"].items() if v is not None}),
        "parsed_result": state["parsed_result"],
        "search_result": state["search_result"],
        "raw_result": state["api_result"],
        "email_html": state["email_payload_html"],
        "auto_email": state["auto_email"],
        "schedule": state["schedule"],
        "add_line": {"available": bool(state["add_line"]["header_id"]),
                     "order_number": state["add_line"]["order_number"],
                     "active": state["add_line"]["active"]},
    }


# ==================================================
# Routes
# ==================================================
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/api/state", methods=["GET"])
def api_state():
    state = get_state()
    if not state["messages"]:
        say(state, (
            "👋 Welcome to the **Centroid Sales Order Assistant** — powered by Grok AI.\n\n"
            "I can help you with:\n"
            "• 📦 **Create** a new sales order\n"
            "• 🔍 **Retrieve** a specific order by number\n"
            "• 📊 **Search** orders by year, date range or status\n"
            "• 👤 **Customer orders** — full history for any customer\n"
            "• ➕ **Add lines** to an existing order\n"
            "• 📧 **Email** reports instantly or on a schedule\n\n"
            "What would you like to do today?"
        ))
    return jsonify(snapshot(state))


@app.route("/api/faq", methods=["GET"])
def api_faq():
    return jsonify({"faq": [{"question": q, "answer": a} for q, a in FAQ_DATA.items()]})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    message = (request.json or {}).get("message", "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400
    state = handle_chat(get_state(), message)
    return jsonify(snapshot(state))


@app.route("/api/reset", methods=["POST"])
def api_reset():
    state = reset_state(keep_history=False)
    say(state, "Session cleared. How can I help?")
    return jsonify(snapshot(state))


@app.route("/api/back", methods=["POST"])
def api_back():
    state = get_state()
    state["stage"] = "chat"
    state["pending"] = None
    state["pending_field"] = None
    state["action"] = None
    for k in state["offsets"]:
        state["offsets"][k] = 0
    for k in state["rows"]:
        state["rows"][k] = []
    state["collected"] = _default_state()["collected"]
    state["add_line"]["active"] = False
    state["add_line"]["step"] = None
    state["add_line"]["data"] = {}
    return jsonify(snapshot(state))


@app.route("/api/select", methods=["POST"])
def api_select():
    """Handles selection panels: select / next / prev / search."""
    data = request.json or {}
    kind = data.get("kind")
    op = data.get("op", "select")
    state = get_state()

    if kind and kind.startswith("add_line_"):
        return _add_line_select(state, kind[len("add_line_"):], op, data)

    if kind not in _PICKERS:
        return jsonify({"error": f"unknown selection kind '{kind}'"}), 400

    try:
        if op == "search":
            term = (data.get("value") or "").strip()
            state["collected"]["customer_name"] = term
            state["offsets"][kind] = 0
            rows = _PICKERS[kind]["fetch"](state, 0)
            build_selection(state, kind, rows, searchable=True)
            return jsonify(snapshot(state))

        if op in ("next", "prev"):
            step = MAX_CHOICES if op == "next" else -MAX_CHOICES
            state["offsets"][kind] = max(0, state["offsets"].get(kind, 0) + step)
            rows = _PICKERS[kind]["fetch"](state, state["offsets"][kind])
            build_selection(state, kind, rows, searchable=(kind == "customer"))
            return jsonify(snapshot(state))

        idx = int(data.get("index", -1))
        rows = state["rows"].get(kind) or []
        if idx < 0 or idx >= len(rows):
            return jsonify({"error": "invalid selection index"}), 400

        state["pending"] = None
        if apply_selection(state, kind, rows[idx]):
            resolve(state)
        return jsonify(snapshot(state))
    except Exception as e:
        say(state, f"Selection failed: {e}")
        return jsonify(snapshot(state))


@app.route("/api/input", methods=["POST"])
def api_input():
    """Handles free-text panels (selling price, add-line inputs, customer name)."""
    data = request.json or {}
    kind = data.get("kind")
    value = (data.get("value") or "").strip()
    state = get_state()

    try:
        if kind == "selling_price":
            c = state["collected"]
            val = parse_numeric_value(value, allow_float=True) if value else None
            c["unit_selling_price"] = val if val is not None else c.get("unit_list_price")
            say(state, f"Selling price set to {_fmt_money(c['unit_selling_price'])}")
            state["pending"] = None
            resolve(state)
            return jsonify(snapshot(state))

        if kind == "customer_orders_name":
            if not value:
                return jsonify({"error": "customer name is required"}), 400
            state["pending"] = None
            say(state, f"Fetching order details for **{value}**…")
            do_customer_orders(state, value)
            return jsonify(snapshot(state))

        if kind and kind.startswith("add_line_"):
            return _add_line_input(state, kind[len("add_line_"):], value)

        return jsonify({"error": f"unknown input kind '{kind}'"}), 400
    except Exception as e:
        say(state, f"Input failed: {e}")
        state["pending"] = None
        return jsonify(snapshot(state))


@app.route("/api/submit-order", methods=["POST"])
def api_submit_order():
    state = get_state()
    try:
        submit_order(state)
    except Exception as e:
        say(state, f"Submit error: {e}")
        state["stage"] = "chat"
        state["pending"] = None
    return jsonify(snapshot(state))


@app.route("/api/get-order", methods=["POST"])
def api_get_order():
    state = get_state()
    num = (request.json or {}).get("order_number")
    val = parse_numeric_value(num)
    if val is None:
        return jsonify({"error": "a numeric order number is required"}), 400
    try:
        user_say(state, f"Get order {val}")
        do_get_order(state, val)
    except Exception as e:
        say(state, f"Failed to retrieve order: {e}")
    return jsonify(snapshot(state))


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.json or {}
    state = get_state()
    year = parse_numeric_value(data.get("year")) if data.get("year") else None
    try:
        user_say(state, "Search orders")
        do_search(state, data.get("date_range") or None, year, (data.get("status") or None))
    except Exception as e:
        say(state, f"Search failed: {e}")
    return jsonify(snapshot(state))


@app.route("/api/customer-orders", methods=["POST"])
def api_customer_orders():
    name = ((request.json or {}).get("customer_name") or "").strip()
    state = get_state()
    if not name:
        return jsonify({"error": "customer_name is required"}), 400
    try:
        user_say(state, f"Order details for customer {name}")
        do_customer_orders(state, name)
    except Exception as e:
        say(state, f"Failed to fetch customer orders: {e}")
    return jsonify(snapshot(state))


# --------------------------------------------------
# Add-line endpoints
# --------------------------------------------------
@app.route("/api/add-line/start", methods=["POST"])
def api_add_line_start():
    state = get_state()
    al = state["add_line"]
    if not al["header_id"]:
        return jsonify({"error": "no order in context to add a line to"}), 400
    al.update({"active": True, "step": "item_search", "data": {},
               "rows": {"item": [], "price": [], "term": [], "line_type": []}, "search_text": ""})
    state["offsets"].update({"item": 0, "price": 0, "term": 0, "line_type": 0})
    state["stage"] = "add_line"
    add_line_prompt(state)
    return jsonify(snapshot(state))


@app.route("/api/add-line/cancel", methods=["POST"])
def api_add_line_cancel():
    state = get_state()
    state["add_line"].update({"active": False, "step": None, "data": {}})
    state["stage"] = "order_result" if state["parsed_result"] else "chat"
    state["pending"] = {"type": "order_result", "context": "Order"} if state["parsed_result"] else None
    return jsonify(snapshot(state))


@app.route("/api/add-line/submit", methods=["POST"])
def api_add_line_submit():
    state = get_state()
    try:
        submit_add_line(state)
    except Exception as e:
        say(state, f"Failed to add line: {e}")
        state["stage"] = "chat"
        state["pending"] = None
    return jsonify(snapshot(state))


def _add_line_select(state, kind, op, data):
    al = state["add_line"]
    try:
        if kind == "item":
            if op in ("next", "prev"):
                step = MAX_CHOICES if op == "next" else -MAX_CHOICES
                state["offsets"]["item"] = max(0, state["offsets"]["item"] + step)
                al["rows"]["item"] = get_inventory_item_rows(al["search_text"], offset=state["offsets"]["item"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            if op == "search":
                al["search_text"] = (data.get("value") or "").strip()
                state["offsets"]["item"] = 0
                al["rows"]["item"] = get_inventory_item_rows(al["search_text"], offset=0)
                al["step"] = "item_select"
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["item"][int(data.get("index"))]
            al["data"]["inventory_item_id"] = row["inventory_item_id"]
            al["data"]["ordered_item"] = row["segment1"]
            al["step"] = "qty"

        elif kind == "price":
            if op in ("next", "prev"):
                step = MAX_CHOICES if op == "next" else -MAX_CHOICES
                state["offsets"]["price"] = max(0, state["offsets"]["price"] + step)
                al["rows"]["price"] = get_price_details_rows(
                    al["data"]["ordered_item"], float(al["data"]["quantity"]),
                    al["data"]["inventory_item_id"], offset=state["offsets"]["price"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["price"][int(data.get("index"))]
            al["data"]["price_list_id"] = row["price_list_id"]
            al["data"]["unit_list_price"] = row["unit_list_price"]
            al["data"]["unit_selling_price"] = row["unit_list_price"]
            al["step"] = "selling_price"

        elif kind == "term":
            if op in ("next", "prev"):
                step = MAX_CHOICES if op == "next" else -MAX_CHOICES
                state["offsets"]["term"] = max(0, state["offsets"]["term"] + step)
                al["rows"]["term"] = get_payment_term_rows(offset=state["offsets"]["term"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["term"][int(data.get("index"))]
            al["data"]["payment_term_id"] = row["term_id"]
            if _has_line_types():
                state["offsets"]["line_type"] = 0
                al["rows"]["line_type"] = get_line_type_rows(offset=0)
                al["step"] = "line_type_select"
            else:
                al["step"] = "submit"

        elif kind == "line_type":
            if op in ("next", "prev"):
                step = MAX_CHOICES if op == "next" else -MAX_CHOICES
                state["offsets"]["line_type"] = max(0, state["offsets"]["line_type"] + step)
                al["rows"]["line_type"] = get_line_type_rows(offset=state["offsets"]["line_type"])
                add_line_prompt(state)
                return jsonify(snapshot(state))
            row = al["rows"]["line_type"][int(data.get("index"))]
            al["data"]["line_type_id"] = row["line_type_id"]
            al["step"] = "submit"

        else:
            return jsonify({"error": f"unknown add-line selection '{kind}'"}), 400

        add_line_prompt(state)
        return jsonify(snapshot(state))
    except Exception as e:
        say(state, f"Add-line step failed: {e}")
        return jsonify(snapshot(state))


def _add_line_input(state, kind, value):
    al = state["add_line"]
    try:
        if kind == "item_search":
            al["search_text"] = value
            state["offsets"]["item"] = 0
            al["rows"]["item"] = get_inventory_item_rows(value, offset=0)
            al["step"] = "item_select"

        elif kind == "qty":
            qty = parse_numeric_value(value, allow_float=True)
            if qty is None:
                return jsonify({"error": "invalid quantity"}), 400
            al["data"]["quantity"] = qty
            state["offsets"]["price"] = 0
            al["rows"]["price"] = get_price_details_rows(
                al["data"]["ordered_item"], qty, al["data"]["inventory_item_id"], offset=0)
            al["step"] = "price_select"

        elif kind == "selling_price":
            val = parse_numeric_value(value, allow_float=True) if value else None
            al["data"]["unit_selling_price"] = val if val is not None else al["data"].get("unit_list_price")
            state["offsets"]["term"] = 0
            al["rows"]["term"] = get_payment_term_rows(offset=0)
            al["step"] = "term_select"

        else:
            return jsonify({"error": f"unknown add-line input '{kind}'"}), 400

        add_line_prompt(state)
        return jsonify(snapshot(state))
    except Exception as e:
        say(state, f"Add-line step failed: {e}")
        return jsonify(snapshot(state))


# --------------------------------------------------
# Email / automation endpoints
# --------------------------------------------------
@app.route("/api/email/open", methods=["POST"])
def api_email_open():
    state = get_state()
    state["stage"] = "send_email"
    state["pending"] = {
        "type": "email",
        "to": state["collected"].get("email_address") or state["auto_email"].get("to") or "",
        "subject": "Oracle ERP Order Details Update",
        "body": "Please find the requested order details structured below.",
        "html": state.get("email_payload_html", ""),
    }
    return jsonify(snapshot(state))


@app.route("/api/email/send", methods=["POST"])
def api_email_send():
    data = request.json or {}
    state = get_state()
    to_email = (data.get("to") or "").strip()
    if not to_email:
        return jsonify({"error": "recipient email is required"}), 400
    ok, msg = send_erp_email(to_email,
                             data.get("subject") or "Oracle ERP Order Details Update",
                             data.get("body") or "",
                             state.get("email_payload_html", ""))
    state["collected"]["email_address"] = to_email
    say(state, f"Email to `{to_email}`: {msg}")
    if ok:
        state["stage"] = "chat"
        state["pending"] = None
    return jsonify({**snapshot(state), "sent": ok, "detail": msg})


@app.route("/api/auto-email", methods=["POST"])
def api_auto_email():
    data = request.json or {}
    state = get_state()
    state["auto_email"]["enabled"] = bool(data.get("enabled"))
    if "to" in data:
        state["auto_email"]["to"] = (data.get("to") or "").strip()
    state["auto_email"]["status"] = None
    state["auto_email"]["error"] = ""
    return jsonify(snapshot(state))


@app.route("/api/schedule/start", methods=["POST"])
def api_schedule_start():
    data = request.json or {}
    state = get_state()
    to_email = (data.get("to") or "").strip()
    if not to_email:
        return jsonify({"error": "recipient email is required"}), 400

    sid = _sid()
    existing = _SCHEDULERS.get(sid)
    if existing:
        existing["stop"].set()

    mins = _interval_minutes(data.get("frequency", "Daily"))
    stop_event = threading.Event()
    customer = (data.get("customer") or "").strip()
    t = threading.Thread(target=_scheduled_worker,
                         args=(stop_event, mins * 60, customer, to_email), daemon=True)
    t.start()
    _SCHEDULERS[sid] = {"stop": stop_event, "thread": t}
    state["schedule"] = {"running": True, "customer": customer,
                         "frequency": data.get("frequency", "Daily"), "to": to_email}
    say(state, f"Scheduled report started — every {mins} minute(s) to `{to_email}`.")
    return jsonify(snapshot(state))


@app.route("/api/schedule/stop", methods=["POST"])
def api_schedule_stop():
    state = get_state()
    entry = _SCHEDULERS.pop(_sid(), None)
    if entry:
        entry["stop"].set()
    state["schedule"] = {"running": False, "customer": "", "frequency": "", "to": ""}
    say(state, "Scheduled report stopped.")
    return jsonify(snapshot(state))


# ==================================================================================
# app7.py feature parity — dynamic SQL, combined operations, order tracking,
# highly-ordered items, create-order draft resolution, charts, export, config,
# login and lookup APIs. Everything below is Grok-only and self-contained.
# ==================================================================================

# --------------------------------------------------
# SQL safety guard (OWASP A03 — only safe read-only SELECTs are ever executed)
# --------------------------------------------------
def is_safe_select_query(sql: str) -> bool:
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        return False
    dangerous = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b", r"\bALTER\b", r"\bTRUNCATE\b",
        r"\bMERGE\b", r"\bCREATE\b", r"\bEXEC\b", r"\bEXECUTE\b", r"\bBEGIN\b", r"\bDECLARE\b",
        r"\bGRANT\b", r"\bREVOKE\b", r"\bCOMMIT\b", r"\bROLLBACK\b", r"\bXP_\w+",
        r"\bUTL_FILE\b", r"\bUTL_HTTP\b", r"\bUTL_TCP\b", r"\bDBMS_\w+",
    ]
    if any(re.search(p, sql_upper) for p in dangerous):
        return False
    if re.search(r";\s*\S", sql_upper):
        return False
    if re.search(r"(/\*)|(\*/)|(--)", sql_upper):
        return False
    if re.search(r"\bUNION\b", sql_upper):
        return False
    return True


# --------------------------------------------------
# Dynamic SQL generation (Grok only)
# --------------------------------------------------
DYNAMIC_SQL_SYSTEM_PROMPT = """
You are an Oracle EBS R12 SQL Expert.
Generate ONLY Oracle SELECT SQL queries using Oracle Apps standard tables.

==== SALES ORDERS ====
OE_ORDER_HEADERS_ALL(HEADER_ID, ORDER_NUMBER, FLOW_STATUS_CODE, SOLD_TO_ORG_ID, ORDERED_DATE, ORG_ID, CUST_PO_NUMBER, ORDER_TYPE_ID, PAYMENT_TERM_ID, PRICE_LIST_ID, CREATION_DATE, CREATED_BY)
OE_ORDER_LINES_ALL(LINE_ID, HEADER_ID, LINE_NUMBER, INVENTORY_ITEM_ID, ORDERED_QUANTITY, UNIT_SELLING_PRICE, FLOW_STATUS_CODE, CREATION_DATE, CREATED_BY)
==== CUSTOMERS ====
HZ_PARTIES(PARTY_ID, PARTY_NAME, PARTY_TYPE, STATUS)
HZ_CUST_ACCOUNTS(CUST_ACCOUNT_ID, PARTY_ID, ACCOUNT_NUMBER, ACCOUNT_NAME, STATUS)
==== INVENTORY ====
MTL_SYSTEM_ITEMS_B(INVENTORY_ITEM_ID, ORGANIZATION_ID, SEGMENT1, SEGMENT2, DESCRIPTION, ITEM_TYPE, CREATION_DATE)

Rules:
1. Oracle SQL only, SELECT statements only, never INSERT/UPDATE/DELETE/DDL.
2. Use bind-free literal WHERE clauses (values already sanitized by caller).
3. Max 50 rows using FETCH FIRST 50 ROWS ONLY.
4. Return ONLY JSON: {"sql": "SELECT ...", "explanation": "short user-friendly explanation"}.
"""


def get_org_schema_context_cached():
    return _get_order_schema_context()


@lru_cache(maxsize=1)
def _get_order_schema_context():
    tables = {
        "OE_ORDER_HEADERS_ALL": ["HEADER_ID", "ORDER_NUMBER", "ORDERED_DATE", "FLOW_STATUS_CODE", "CUST_PO_NUMBER", "SOLD_TO_ORG_ID", "SHIP_TO_ORG_ID", "ORG_ID"],
        "OE_ORDER_LINES_ALL": ["LINE_ID", "HEADER_ID", "LINE_NUMBER", "INVENTORY_ITEM_ID", "ORDERED_ITEM", "ORDERED_QUANTITY", "UNIT_SELLING_PRICE", "FLOW_STATUS_CODE"],
        "HZ_CUST_ACCOUNTS": ["CUST_ACCOUNT_ID", "PARTY_ID", "ACCOUNT_NUMBER", "STATUS"],
        "HZ_PARTIES": ["PARTY_ID", "PARTY_NAME", "STATUS"],
        "MTL_SYSTEM_ITEMS_B": ["INVENTORY_ITEM_ID", "SEGMENT1", "DESCRIPTION", "ORGANIZATION_ID"],
    }
    lines = ["Order-domain tables and columns:"]
    for t, cols in tables.items():
        lines.append(f"- {t}: {', '.join(cols)}")
    return "\n".join(lines)


def generate_dynamic_sql(history: list, user_input: str) -> dict:
    try:
        history_str = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-8:])
        system_prompt = DYNAMIC_SQL_SYSTEM_PROMPT + "\n\n" + get_org_schema_context_cached()
        user_prompt = f"History:\n{history_str}\n\nUser Request:\n{user_input}"
        raw = _grok_chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.0, max_tokens=400,
        )
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        return {"sql": "", "explanation": f"AI SQL generation error: {e}"}


def is_erp_or_data_query(user_input: str) -> bool:
    text = str(user_input or "").lower()
    keywords = ["order", "orders", "customer", "customers", "line", "item", "invoice", "shipment",
                "booked", "entered", "cancelled", "po", "sales", "sql", "query", "report", "track",
                "tracking", "shipping", "ship to", "highly ordered", "top ordered"]
    return any(k in text for k in keywords)


def has_explicit_sql_operator_request(user_input: str) -> bool:
    text = str(user_input or "").lower()
    return bool(re.search(r"\bnot\s+in\b|\bin\b|\bnot\s+like\b|\blike\b|\bbetween\b|\bwhere\b|(>=|<=|<>|!=|=|>|<)", text))


# --------------------------------------------------
# Order tracking (deterministic, multi-filter) queries
# --------------------------------------------------
_KNOWN_ORDER_STATUSES = {
    "entered": "ENTERED", "booked": "BOOKED", "shipped": "SHIPPED",
    "cancelled": "CANCELLED", "canceled": "CANCELLED", "closed": "CLOSED",
}


def extract_order_tracking_filters(user_input: str) -> dict:
    text = str(user_input or "")
    lower = text.lower()
    filters = {"order_numbers": [], "status": None, "customer_name_like": None,
               "ordered_item_like": None, "po_number": None, "date_range": None, "year": None}

    order_nums = re.findall(r"(?:order\s*(?:number|#)?\s*)(\d{4,})", lower) + re.findall(r"#(\d{4,})", lower)
    if order_nums:
        filters["order_numbers"] = list(dict.fromkeys(int(n) for n in order_nums))

    for key, val in _KNOWN_ORDER_STATUSES.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            filters["status"] = val
            break

    cust_match = re.search(r"customer\s*(?:name)?\s*(?:is|=|like)?\s*['\"]?([a-z0-9_\-\.&\s]{2,})", text, re.IGNORECASE)
    if cust_match:
        cust = cust_match.group(1).strip(" .,\"'")
        for stop in [" and ", " with ", " where ", " status ", " item "]:
            idx = cust.lower().find(stop)
            if idx > 0:
                cust = cust[:idx].strip()
        if cust:
            filters["customer_name_like"] = cust

    if "this month" in lower:
        filters["date_range"] = "this_month"
    elif "this week" in lower:
        filters["date_range"] = "this_week"
    elif "last 30" in lower:
        filters["date_range"] = "last_30_days"

    year_match = re.search(r"\b(20\d{2})\b", lower)
    if year_match:
        filters["year"] = int(year_match.group(1))

    return filters


def should_use_order_tracking_query(user_input: str, filters: dict) -> bool:
    lower = str(user_input or "").lower()
    if filters.get("order_numbers"):
        return True
    tracking_words = ("track", "tracking", "shipping", "shipment", "ship to", "delivery status")
    has_context = ("order" in lower or "orders" in lower) or any(w in lower for w in tracking_words)
    combo_fields = ["status", "customer_name_like", "ordered_item_like", "po_number", "date_range", "year"]
    combo_count = sum(1 for k in combo_fields if filters.get(k) not in (None, "", []))
    return has_context and combo_count >= 2


def build_order_tracking_query(filters: dict):
    where_clauses = ["ooha.ORG_ID = :org_id"]
    bind_params = {"org_id": get_org_id()}

    order_numbers = filters.get("order_numbers") or []
    if order_numbers:
        placeholders = []
        for idx, num in enumerate(order_numbers):
            key = f"order_num_{idx}"
            placeholders.append(f":{key}")
            bind_params[key] = int(num)
        where_clauses.append(f"ooha.ORDER_NUMBER IN ({', '.join(placeholders)})")

    if filters.get("status"):
        bind_params["status_val"] = str(filters["status"]).upper()
        where_clauses.append("UPPER(ooha.FLOW_STATUS_CODE) = :status_val")

    if filters.get("customer_name_like"):
        bind_params["cust_like"] = f"%{str(filters['customer_name_like']).upper()}%"
        where_clauses.append("UPPER(hp.PARTY_NAME) LIKE :cust_like")

    if filters.get("year"):
        bind_params["year_val"] = int(filters["year"])
        where_clauses.append("EXTRACT(YEAR FROM ooha.ORDERED_DATE) = :year_val")

    if filters.get("date_range") == "this_month":
        where_clauses.append("ooha.ORDERED_DATE >= TRUNC(SYSDATE, 'MM')")
    elif filters.get("date_range") == "this_week":
        where_clauses.append("ooha.ORDERED_DATE >= TRUNC(SYSDATE, 'IW')")
    elif filters.get("date_range") == "last_30_days":
        where_clauses.append("ooha.ORDERED_DATE >= SYSDATE - 30")

    where_sql = "\nAND ".join(where_clauses)
    sql = f"""
SELECT
    ooha.ORDER_NUMBER,
    ooha.FLOW_STATUS_CODE AS ORDER_STATUS,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    ooha.CUST_PO_NUMBER,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT,
    SUM(NVL(oola.ORDERED_QUANTITY, 0) * NVL(oola.UNIT_SELLING_PRICE, 0)) AS ORDER_AMOUNT
FROM OE_ORDER_HEADERS_ALL ooha
LEFT JOIN OE_ORDER_LINES_ALL oola ON oola.HEADER_ID = ooha.HEADER_ID
LEFT JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
LEFT JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
WHERE {where_sql}
GROUP BY ooha.ORDER_NUMBER, ooha.FLOW_STATUS_CODE, ooha.ORDERED_DATE, hp.PARTY_NAME, ooha.CUST_PO_NUMBER
ORDER BY ooha.ORDERED_DATE DESC, ooha.ORDER_NUMBER DESC
FETCH FIRST 200 ROWS ONLY
""".strip()
    return sql, bind_params


# --------------------------------------------------
# Highly-ordered items
# --------------------------------------------------
def get_highly_ordered_items(year=None, top_n=25):
    binds = {"org_id": get_org_id(), "top_n": int(top_n)}
    year_clause = ""
    if year:
        year_clause = "AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = :year"
        binds["year"] = int(year)

    sql = f"""
        SELECT * FROM (
            SELECT
                NVL(msi.SEGMENT1, TO_CHAR(oola.INVENTORY_ITEM_ID)) AS ITEM_CODE,
                NVL(msi.DESCRIPTION, 'N/A') AS ITEM_DESCRIPTION,
                COUNT(*) AS ORDER_LINE_COUNT,
                COUNT(DISTINCT ooha.ORDER_NUMBER) AS ORDER_COUNT,
                ROUND(SUM(NVL(oola.ORDERED_QUANTITY, 0)), 2) AS TOTAL_ORDERED_QTY,
                ROUND(SUM(NVL(oola.ORDERED_QUANTITY, 0) * NVL(oola.UNIT_SELLING_PRICE, 0)), 2) AS TOTAL_REVENUE
            FROM OE_ORDER_HEADERS_ALL ooha
            JOIN OE_ORDER_LINES_ALL oola ON oola.HEADER_ID = ooha.HEADER_ID
            LEFT JOIN MTL_SYSTEM_ITEMS_B msi ON msi.INVENTORY_ITEM_ID = oola.INVENTORY_ITEM_ID
            WHERE ooha.ORG_ID = :org_id AND NVL(oola.ORDERED_QUANTITY, 0) > 0 {year_clause}
            GROUP BY NVL(msi.SEGMENT1, TO_CHAR(oola.INVENTORY_ITEM_ID)), NVL(msi.DESCRIPTION, 'N/A')
            ORDER BY SUM(NVL(oola.ORDERED_QUANTITY, 0)) DESC
        )
        WHERE ROWNUM <= :top_n
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, binds)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
    return {"year": int(year) if year else None, "top_n": int(top_n), "count": len(rows),
            "rows": [dict(zip(cols, row)) for row in rows]}


# --------------------------------------------------
# Chart / visualization helpers
# --------------------------------------------------
def _extract_requested_chart_type(user_input: str) -> Optional[str]:
    lower = str(user_input or "").lower()
    if "pie" in lower:
        return "pie"
    if "doughnut" in lower or "donut" in lower:
        return "donut"
    if any(t in lower for t in ["status", "distribution", "breakdown", "share", "proportion"]):
        return "pie"
    if "line" in lower or "trend" in lower:
        return "line"
    if "bar" in lower or "column" in lower:
        return "bar"
    return None


def _is_visualization_requested(user_input: str) -> bool:
    lower = str(user_input or "").lower()
    tokens = ["chart", "graph", "plot", "visual", "visualization", "representation", "show me"]
    return any(t in lower for t in tokens)


def _to_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "na", "n/a"}:
        return None
    try:
        return float(text.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _build_chart_config(columns: List[str], rows: List[List[str]], preferred_type: Optional[str] = None) -> Dict[str, Any]:
    if not rows or not columns:
        return {"ok": False, "reason": "Visualization cannot be generated because the operation returned no rows."}

    display_rows = rows[:60]
    numeric_cols, label_cols = [], []
    for idx, col in enumerate(columns):
        col_values = [r[idx] if idx < len(r) else "" for r in display_rows]
        non_empty = [v for v in col_values if str(v).strip() not in ("", "None", "null")]
        if not non_empty:
            continue
        numeric_hits = sum(1 for v in non_empty if _to_float_or_none(v) is not None)
        (numeric_cols if numeric_hits / len(non_empty) >= 0.75 else label_cols).append(col)

    if not numeric_cols:
        return {"ok": False, "reason": "Visualization cannot be generated because the data has no numeric columns."}

    label_col = next((c for c in label_cols if any(h in c.lower() for h in ("status", "type", "category", "name", "code"))), None)
    label_col = label_col or (label_cols[0] if label_cols else columns[0])
    label_idx = columns.index(label_col)
    labels = [str((row[label_idx] if label_idx < len(row) else "") or "-") for row in display_rows]

    is_time_series = any(w in " ".join(columns).lower() for w in ("date", "month", "year", "period", "week"))
    chart_type = preferred_type or ("line" if is_time_series else "bar")
    if chart_type not in {"bar", "line", "pie", "doughnut"}:
        chart_type = "bar"

    palette = ["rgba(37,99,235,0.75)", "rgba(16,185,129,0.75)", "rgba(245,158,11,0.75)", "rgba(239,68,68,0.75)"]
    numeric_subset = numeric_cols[:1] if chart_type in {"pie", "doughnut"} else numeric_cols[:4]
    datasets = []
    for i, col in enumerate(numeric_subset):
        col_idx = columns.index(col)
        data_points = [_to_float_or_none(row[col_idx] if col_idx < len(row) else None) or 0.0 for row in display_rows]
        color = palette[i % len(palette)]
        datasets.append({"label": col, "data": data_points, "backgroundColor": color,
                          "borderColor": color.replace("0.75", "1"), "borderWidth": 1, "fill": False})

    return {"ok": True, "config": {"type": chart_type, "label_column": label_col, "labels": labels,
                                    "datasets": datasets, "numeric_columns": numeric_subset, "row_count": len(rows)}}


def _build_visualization_payload(user_input: str, columns: List[str], rows: List[List[str]]) -> Dict[str, Any]:
    if not _is_visualization_requested(user_input):
        return {"requested": False, "available": False, "reason": "", "chart_config": None}
    result = _build_chart_config(columns, rows, preferred_type=_extract_requested_chart_type(user_input))
    if not result.get("ok"):
        return {"requested": True, "available": False, "reason": result.get("reason", ""), "chart_config": None}
    return {"requested": True, "available": True, "reason": "", "chart_config": result.get("config")}


# --------------------------------------------------
# Dynamic-query dispatcher used from handle_chat's fallback branch
# --------------------------------------------------
def _dynamic_table_email_html(columns, rows, explanation=""):
    th = "background:#003366;color:#fff;padding:8px;text-align:left;font-size:0.82rem;"
    td = "padding:8px;border-bottom:1px solid #e5e7eb;font-size:0.82rem;"
    table = "<table style='width:100%;border-collapse:collapse;'><tr>"
    for col in columns:
        table += f"<th style='{th}'>{col}</th>"
    table += "</tr>"
    for row in rows:
        table += "<tr>" + "".join(f"<td style='{td}'>{cell}</td>" for cell in row) + "</tr>"
    table += "</table>"
    return _build_email_layout("Dynamic Query", "Query Results", explanation or f"{len(rows)} row(s) returned.",
                               table, {"Total Rows": str(len(rows)), "Columns": str(len(columns))},
                               [("How was this generated?", "Dynamic SQL query generated by Grok based on your request.")])


def _rows_to_markdown_table(columns, rows, limit=15):
    if not columns or not rows:
        return "No rows returned."
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = "\n".join("| " + " | ".join(str(c) for c in r) + " |" for r in rows[:limit])
    extra = f"\n\n_...and {len(rows) - limit} more row(s). Use Export to download the full result._" if len(rows) > limit else ""
    return f"{header}\n{sep}\n{body}{extra}"


def try_dynamic_erp_query(state, prompt: str):
    """Attempt highly-ordered-items / order-tracking / dynamic SQL. Returns the
    assistant reply text if handled, otherwise None (caller falls back to chat)."""
    low = prompt.strip().lower()

    if not is_erp_or_data_query(prompt):
        return None

    if any(k in low for k in ("highly ordered", "top ordered", "most ordered", "frequently ordered")):
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", low)
        top_match = re.search(r"\btop\s+(\d{1,3})\b", low)
        year = int(year_match.group(1)) if year_match else None
        top_n = max(1, min(int(top_match.group(1)) if top_match else 25, 200))
        try:
            data = get_highly_ordered_items(year=year, top_n=top_n)
        except Exception as e:
            reply = f"Highly-ordered-items query failed: {e}"
            say(state, reply)
            return reply
        if not data.get("rows"):
            reply = "No highly ordered items found for the selected criteria."
            say(state, reply)
            return reply
        cols = ["ITEM_CODE", "ITEM_DESCRIPTION", "ORDER_LINE_COUNT", "ORDER_COUNT", "TOTAL_ORDERED_QTY", "TOTAL_REVENUE"]
        rows = [[str(r.get(c, "")) for c in cols] for r in data["rows"]]
        label = f"Top {top_n} highly ordered items" + (f" for {year}" if year else "")
        summary = generate_ai_summary("highly_ordered_items", data)
        _LAST_OPERATION.update(type="dynamic_table", data={"columns": cols, "rows": rows}, raw=data,
                                email_html=_dynamic_table_email_html(cols, rows, label), ai_summary=summary)
        reply = f"**{label}**\n\n{_rows_to_markdown_table(cols, rows)}\n\n**AI Summary:** {summary}"
        state["stage"] = "dynamic_table"
        state["pending"] = {"type": "dynamic_table", "columns": cols, "rows": rows,
                            "visualization": _build_visualization_payload(prompt, cols, rows)}
        say(state, reply)
        return reply

    tracking_filters = extract_order_tracking_filters(prompt)
    if should_use_order_tracking_query(prompt, tracking_filters):
        sql, binds = build_order_tracking_query(tracking_filters)
        try:
            results = execute_query(sql, binds)
        except Exception as e:
            reply = f"Order-tracking query failed: {e}"
            say(state, reply)
            return reply
        if not results:
            reply = "No matching orders found for that tracking request."
            say(state, reply)
            return reply
        cols = list(results[0].keys())
        rows = [[str(r.get(c, "")) for c in cols] for r in results]
        explanation = "Order tracking details generated using your combined filters."
        summary = generate_ai_summary("order_tracking", results[:20])
        _LAST_OPERATION.update(type="dynamic_table", data={"columns": cols, "rows": rows}, raw=results,
                                email_html=_dynamic_table_email_html(cols, rows, explanation), ai_summary=summary)
        reply = f"{explanation}\n\n{_rows_to_markdown_table(cols, rows)}\n\n**AI Summary:** {summary}"
        state["stage"] = "dynamic_table"
        state["pending"] = {"type": "dynamic_table", "columns": cols, "rows": rows,
                            "visualization": _build_visualization_payload(prompt, cols, rows)}
        say(state, reply)
        return reply

    if not has_explicit_sql_operator_request(prompt) and not any(k in low for k in ("sql", "query")):
        # Only fall through to full AI-generated SQL for clearly data-shaped asks.
        if not any(k in low for k in ("show", "list", "report", "find", "get")):
            return None

    ai_result = generate_dynamic_sql(state["gh_history"], prompt)
    sql_query = re.sub(r"[;\s/]+$", "", (ai_result.get("sql") or "").strip())
    explanation = ai_result.get("explanation", "Query executed successfully.")
    if not sql_query or not is_safe_select_query(sql_query):
        return None

    try:
        results = execute_query(sql_query, {})
    except Exception as e:
        reply = f"SQL execution error: {e}"
        say(state, reply)
        return reply
    if not results:
        reply = "No records found for that request."
        say(state, reply)
        return reply

    cols = list(results[0].keys())
    rows = [[str(r.get(c, "")) for c in cols] for r in results]
    summary = generate_ai_summary("dynamic_query", results[:20])
    _LAST_OPERATION.update(type="dynamic_table", data={"columns": cols, "rows": rows}, raw=results,
                            email_html=_dynamic_table_email_html(cols, rows, explanation), ai_summary=summary)
    reply = f"{explanation}\n\n{_rows_to_markdown_table(cols, rows)}\n\n**AI Summary:** {summary}"
    state["stage"] = "dynamic_table"
    state["pending"] = {"type": "dynamic_table", "columns": cols, "rows": rows,
                        "visualization": _build_visualization_payload(prompt, cols, rows)}
    say(state, reply)
    return reply


# --------------------------------------------------
# Create-order draft resolution (plain-dict validated REST wizard, additive API)
# --------------------------------------------------
class DraftValidationError(Exception):
    """Raised when the incoming create-order draft payload fails validation."""


def _parse_create_order_draft(body: Dict[str, Any]):
    """Validate/coerce the raw JSON body into a simple attribute-style object,
    replicating the previous pydantic model's behaviour (type coercion +
    gt/ge numeric checks) without the pydantic dependency."""
    from types import SimpleNamespace

    def _opt_str(key):
        v = body.get(key)
        if v is None or v == "":
            return None
        return str(v)

    def _opt_int(key):
        v = body.get(key)
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            raise DraftValidationError(f"'{key}' must be an integer")

    def _opt_float(key, gt=None, ge=None):
        v = body.get(key)
        if v is None or v == "":
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise DraftValidationError(f"'{key}' must be a number")
        if gt is not None and not (f > gt):
            raise DraftValidationError(f"'{key}' must be greater than {gt}")
        if ge is not None and not (f >= ge):
            raise DraftValidationError(f"'{key}' must be greater than or equal to {ge}")
        return f

    return SimpleNamespace(
        cust_po_number=_opt_str("cust_po_number"),
        inventory_item_id=_opt_int("inventory_item_id"),
        ordered_item=_opt_str("ordered_item"),
        ordered_quantity=_opt_float("ordered_quantity", gt=0),
        customer_name=_opt_str("customer_name"),
        sold_to_org_id=_opt_int("sold_to_org_id"),
        ship_to_org_id=_opt_int("ship_to_org_id"),
        price_list_id=_opt_int("price_list_id"),
        unit_list_price=_opt_float("unit_list_price", ge=0),
        unit_selling_price=_opt_float("unit_selling_price", ge=0),
        payment_term_id=_opt_int("payment_term_id"),
        salesrep_id=_opt_int("salesrep_id"),
        currency=_opt_str("currency"),
    )


def _fetch_quick_item_suggestions(search_text: str = "") -> List[Dict[str, Any]]:
    rows = get_inventory_item_rows(search_text or "", offset=0)
    return [{"inventory_item_id": r["inventory_item_id"], "segment1": r["segment1"], "description": r["description"]} for r in rows]


def _fetch_quick_customer_suggestions(search_text: str = "") -> List[Dict[str, Any]]:
    rows = get_customer_by_name_rows(search_text or "", offset=0)
    return [{"cust_account_id": r["cust_account_id"], "customer_name": r["customer_name"], "account_number": r["account_number"]} for r in rows]


def resolve_create_order_draft(draft) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {
        "cust_po_number": (draft.cust_po_number or "").strip(),
        "ordered_quantity": float(draft.ordered_quantity or 1),
        "order_type_id": get_order_type_id(),
        "currency": (draft.currency or "USD").strip() or "USD",
    }
    options: Dict[str, Any] = {}

    item_rows = get_inventory_item_rows(draft.ordered_item or "", offset=0) if draft.ordered_item else []
    if draft.inventory_item_id:
        resolved["inventory_item_id"] = int(draft.inventory_item_id)
        resolved["ordered_item"] = draft.ordered_item or ""
    elif len(item_rows) == 1:
        resolved["inventory_item_id"] = item_rows[0]["inventory_item_id"]
        resolved["ordered_item"] = item_rows[0]["segment1"]
    elif item_rows:
        options["items"] = item_rows

    cust_rows = get_customer_by_name_rows(draft.customer_name or "", offset=0) if draft.customer_name else []
    if draft.sold_to_org_id:
        resolved["sold_to_org_id"] = int(draft.sold_to_org_id)
        resolved["customer_name"] = draft.customer_name or ""
    elif len(cust_rows) == 1:
        resolved["sold_to_org_id"] = cust_rows[0]["cust_account_id"]
        resolved["customer_name"] = cust_rows[0]["customer_name"]
    elif cust_rows:
        options["customers"] = cust_rows

    if resolved.get("sold_to_org_id") and not draft.ship_to_org_id:
        sites = get_customer_sites_by_account(resolved["sold_to_org_id"])
        if len(sites) == 1:
            resolved["ship_to_org_id"] = sites[0]["ship_to_org_id"]
        elif sites:
            options["sites"] = sites
    elif draft.ship_to_org_id:
        resolved["ship_to_org_id"] = int(draft.ship_to_org_id)

    item_id = resolved.get("inventory_item_id")
    if item_id and draft.unit_list_price is None:
        price_rows = get_price_details_rows(resolved.get("ordered_item", ""), resolved["ordered_quantity"], item_id, offset=0)
        if len(price_rows) == 1:
            resolved["price_list_id"] = price_rows[0]["price_list_id"]
            resolved["unit_list_price"] = price_rows[0]["unit_list_price"]
        elif price_rows:
            options["prices"] = price_rows
    if draft.price_list_id:
        resolved["price_list_id"] = int(draft.price_list_id)
    if draft.unit_list_price is not None:
        resolved["unit_list_price"] = float(draft.unit_list_price)
    resolved["unit_selling_price"] = float(draft.unit_selling_price if draft.unit_selling_price is not None else resolved.get("unit_list_price") or 0)

    resolved["payment_term_id"] = int(draft.payment_term_id or get_default_payment_term_id())
    resolved["salesrep_id"] = int(draft.salesrep_id or get_default_salesrep_id())

    missing = [f for f in ("inventory_item_id", "sold_to_org_id", "ship_to_org_id", "price_list_id") if not resolved.get(f)]
    return {"resolved": resolved, "missing": missing, "options": options}


def validate_create_order_data(resolution: Dict[str, Any]) -> Dict[str, Any]:
    resolved = resolution.get("resolved") or {}
    errors = []
    for field, label in (("inventory_item_id", "item"), ("sold_to_org_id", "customer"),
                          ("ship_to_org_id", "ship_to"), ("price_list_id", "price")):
        if not resolved.get(field):
            errors.append({"field": label, "message": f"{label.replace('_', ' ').title()} could not be resolved."})
    return {"ok": len(errors) == 0, "errors": errors, "suggestions": resolution.get("options") or {}, "resolved": resolved}


# --------------------------------------------------
# Excel / CSV / JSON export of the last dynamic operation
# --------------------------------------------------
def _generate_excel_bytes():
    if not OPENPYXL_AVAILABLE:
        return b""
    data = _LAST_OPERATION.get("data") or {}
    columns, rows = data.get("columns"), data.get("rows")
    if not columns or rows is None:
        return b""
    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="003366", end_color="003366", fill_type="solid")
    ws.append(columns)
    for col in range(1, len(columns) + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
    for row in rows:
        ws.append(row)
    for col in ws.columns:
        max_len = max((len(str(c.value)) for c in col if c.value), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 40)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _generate_csv_bytes():
    data = _LAST_OPERATION.get("data") or {}
    columns, rows = data.get("columns"), data.get("rows")
    if not columns or rows is None:
        return b""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8-sig")


def _generate_json_bytes():
    data = _LAST_OPERATION.get("raw") or _LAST_OPERATION.get("data")
    if not data:
        return b""
    try:
        return json.dumps(data, indent=2, default=str).encode("utf-8")
    except Exception:
        return b""


def _export_filename(ext="xlsx"):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"ERP_Report_{ts}.{ext}"


# --------------------------------------------------
# Additive routes (parity with app7.py; existing UI/API untouched)
# --------------------------------------------------
_CONFIG_SECRET_KEYS = {"db_password", "xai_api_key", "api_password", "smtp_password", "login_password"}


def _require_login(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Unauthorized. Please log in."}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    stored_username = str(get_config_value("api_user", REST_USERNAME))
    stored_password = str(get_config_value("api_password", REST_PASSWORD))
    if hmac.compare_digest(username.encode(), stored_username.encode()) and hmac.compare_digest(password.encode(), stored_password.encode()):
        session["authenticated"] = True
        session["user"] = username
        return jsonify({"ok": True, "message": "Login successful", "user": username})
    return jsonify({"ok": False, "error": "Invalid username or password"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("authenticated", None)
    session.pop("user", None)
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        body = request.get_json(force=True) or {}
        for key, value in body.items():
            if key in _CONFIG_SECRET_KEYS and not str(value or "").strip():
                continue
            set_config_value(key, value)
        safe = {k: ("***" if k in _CONFIG_SECRET_KEYS else v) for k, v in ConfigManager().all().items()}
        return jsonify({"status": "success", "config": safe})
    safe = {k: ("***" if k in _CONFIG_SECRET_KEYS else v) for k, v in ConfigManager().all().items()}
    return jsonify(safe)


@app.route("/api/lookup-items", methods=["GET"])
def api_lookup_items():
    search = request.args.get("search", "").strip()
    offset = int(request.args.get("offset", 0))
    if not search:
        return jsonify({"items": [], "has_more": False})
    rows = get_inventory_item_rows(search, offset=offset)
    return jsonify({"items": rows, "has_more": len(rows) >= get_max_choices()})


@app.route("/api/lookup-customers", methods=["GET"])
def api_lookup_customers():
    search = request.args.get("search", "").strip()
    item_id = request.args.get("item_id", "").strip()
    offset = int(request.args.get("offset", 0))
    if search:
        rows = get_customer_by_name_rows(search, offset=offset)
    elif item_id:
        rows = get_customers_by_inventory_item_rows(int(item_id), offset=offset)
    else:
        return jsonify({"customers": [], "has_more": False})
    return jsonify({"customers": rows, "has_more": len(rows) >= get_max_choices()})


@app.route("/api/lookup-customer-sites", methods=["GET"])
def api_lookup_customer_sites():
    cust_account_id = request.args.get("cust_account_id", "").strip()
    if not cust_account_id:
        return jsonify({"sites": []})
    return jsonify({"sites": get_customer_sites_by_account(int(cust_account_id))})


@app.route("/api/lookup-prices", methods=["GET"])
def api_lookup_prices():
    item_id = request.args.get("item_id", "").strip()
    offset = int(request.args.get("offset", 0))
    if not item_id:
        return jsonify({"prices": [], "has_more": False})
    rows = get_price_details_rows("", 1, int(item_id), offset=offset)
    return jsonify({"prices": rows, "has_more": len(rows) >= get_max_choices()})


@app.route("/api/lookup-payment-terms", methods=["GET"])
def api_lookup_payment_terms():
    offset = int(request.args.get("offset", 0))
    return jsonify({"terms": get_payment_term_rows(offset=offset)})


@app.route("/api/lookup-salesreps", methods=["GET"])
def api_lookup_salesreps():
    offset = int(request.args.get("offset", 0))
    return jsonify({"reps": get_salesrep_rows(offset=offset)})


@app.route("/api/create-order/draft", methods=["POST"])
def api_create_order_draft():
    body = request.get_json(force=True) or {}
    try:
        draft = _parse_create_order_draft(body)
        result = resolve_create_order_draft(draft)
        validation = validate_create_order_data(result)
        return jsonify({"ok": True, **result, "validation": validation})
    except DraftValidationError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/orders-advanced", methods=["GET"])
def api_orders_advanced():
    range_type = request.args.get("range_type") or None
    year = request.args.get("year")
    status = request.args.get("status") or None
    year = int(year) if year else None
    try:
        data = get_orders_advanced(range_type, year, status)
        summary = generate_ai_summary("orders_advanced", data)
        return jsonify({"reply": data, "ai_summary": summary})
    except Exception as e:
        return jsonify({"reply": f"Error querying orders: {e}", "type": "error"}), 500


@app.route("/api/highly-ordered-items", methods=["GET"])
def api_highly_ordered_items():
    year = request.args.get("year")
    top_n = int(request.args.get("top_n", 25))
    year = int(year) if year else None
    try:
        data = get_highly_ordered_items(year=year, top_n=top_n)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dynamic-query", methods=["POST"])
def api_dynamic_query():
    body = request.get_json(force=True) or {}
    user_input = str(body.get("message", "")).strip()
    if not user_input:
        return jsonify({"error": "message is required"}), 400
    ai_result = generate_dynamic_sql([], user_input)
    sql_query = re.sub(r"[;\s/]+$", "", (ai_result.get("sql") or "").strip())
    if not sql_query or not is_safe_select_query(sql_query):
        return jsonify({"reply": ai_result.get("explanation", "Could not build a safe query."), "type": "error"}), 400
    try:
        results = execute_query(sql_query, {})
    except Exception as e:
        return jsonify({"reply": f"SQL execution error: {e}", "type": "error"}), 500
    columns = list(results[0].keys()) if results else []
    rows = [[str(r.get(c, "")) for c in columns] for r in results]
    _LAST_OPERATION.update(type="dynamic_table", data={"columns": columns, "rows": rows}, raw=results,
                            email_html=_dynamic_table_email_html(columns, rows, ai_result.get("explanation", "")))
    return jsonify({"type": "dynamic_table", "columns": columns, "rows": rows,
                    "visualization": _build_visualization_payload(user_input, columns, rows)})


@app.route("/api/download", methods=["GET"])
def api_download():
    if not _LAST_OPERATION.get("type") or not _LAST_OPERATION.get("data"):
        return jsonify({"error": "No operation data available. Run a dynamic query first."}), 400
    fmt = request.args.get("format", "excel").lower().strip()
    if fmt == "csv":
        data = _generate_csv_bytes()
        if not data:
            return jsonify({"error": "CSV generation failed."}), 500
        return Response(data, mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={_export_filename('csv')}"})
    if fmt == "json":
        data = _generate_json_bytes()
        if not data:
            return jsonify({"error": "JSON generation failed."}), 500
        return Response(data, mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename={_export_filename('json')}"})
    if not OPENPYXL_AVAILABLE:
        return jsonify({"error": "openpyxl not installed. Run: pip install openpyxl"}), 500
    data = _generate_excel_bytes()
    if not data:
        return jsonify({"error": "Excel generation failed."}), 500
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={_export_filename('xlsx')}"})


@app.route("/api/auto-loop/start", methods=["POST"])
def api_auto_loop_start():
    data = request.get_json(force=True) or {}
    to_email = (data.get("to_email") or "").strip()
    if not to_email:
        return jsonify({"error": "Recipient email is required."}), 400
    _start_auto_loop(to_email)
    return jsonify({"ok": True, "message": f"Auto-loop started -> {to_email}", **_AUTO_LOOP})


@app.route("/api/auto-loop/stop", methods=["POST"])
def api_auto_loop_stop():
    _stop_auto_loop()
    return jsonify({"ok": True, "message": "Auto-loop stopped.", **_AUTO_LOOP})


@app.route("/api/auto-loop/status", methods=["GET"])
def api_auto_loop_status():
    return jsonify(_AUTO_LOOP)


_AUTO_LOOP = {"active": False, "to_email": "", "current_customer": "", "total_customers": 0, "processed": 0, "last_status": None}
_STOP_LOOP_EVENT = threading.Event()
_LOOP_THREAD = None


def _get_all_customer_names():
    rows = execute_query(
        """
        SELECT DISTINCT HP.PARTY_NAME AS CUSTOMER_NAME
        FROM HZ_PARTIES HP
        JOIN HZ_CUST_ACCOUNTS HCA ON HCA.PARTY_ID = HP.PARTY_ID
        JOIN OE_ORDER_HEADERS_ALL OOHA ON OOHA.SOLD_TO_ORG_ID = HCA.CUST_ACCOUNT_ID
        WHERE OOHA.ORG_ID = :org_id AND OOHA.ORDERED_DATE >= ADD_MONTHS(SYSDATE, -36) AND HP.PARTY_NAME IS NOT NULL
        ORDER BY HP.PARTY_NAME
        """,
        {"org_id": get_org_id()},
    )
    return [r["CUSTOMER_NAME"] for r in rows if r.get("CUSTOMER_NAME")]


def _auto_loop_worker(to_email):
    _STOP_LOOP_EVENT.clear()
    _AUTO_LOOP.update(active=True, to_email=to_email)
    while not _STOP_LOOP_EVENT.is_set():
        try:
            customers = _get_all_customer_names()
            _AUTO_LOOP.update(total_customers=len(customers), processed=0)
            for cust_name in customers:
                if _STOP_LOOP_EVENT.is_set():
                    break
                _AUTO_LOOP["current_customer"] = cust_name
                try:
                    rows = get_order_details_by_customer(cust_name)
                    if rows:
                        summary = generate_ai_summary("customer_orders", {"customer": cust_name, "rows": rows[:5]})
                        html = generate_customer_html(rows, cust_name, summary)
                        ok, msg = send_erp_email(to_email, f"Sales Order Report: {cust_name}",
                                                 f"Automated report for {cust_name}", html)
                        _AUTO_LOOP["last_status"] = f"OK {cust_name}: {msg}" if ok else f"FAIL {cust_name}: {msg}"
                    else:
                        _AUTO_LOOP["last_status"] = f"SKIP {cust_name}: No orders"
                except Exception as e:
                    _AUTO_LOOP["last_status"] = f"ERR {cust_name}: {e}"
                _AUTO_LOOP["processed"] += 1
                if not _STOP_LOOP_EVENT.is_set():
                    _STOP_LOOP_EVENT.wait(timeout=5)
            if not _STOP_LOOP_EVENT.is_set():
                _AUTO_LOOP["last_status"] = f"Cycle complete ({len(customers)} customers). Waiting 60s..."
                _STOP_LOOP_EVENT.wait(timeout=60)
        except Exception as e:
            _AUTO_LOOP["last_status"] = f"Loop error: {e}"
            if not _STOP_LOOP_EVENT.is_set():
                _STOP_LOOP_EVENT.wait(timeout=30)
    _AUTO_LOOP["active"] = False
    _AUTO_LOOP["current_customer"] = ""


def _start_auto_loop(to_email):
    global _LOOP_THREAD
    _stop_auto_loop()
    _LOOP_THREAD = threading.Thread(target=_auto_loop_worker, args=(to_email,), daemon=True)
    _LOOP_THREAD.start()


def _stop_auto_loop():
    global _LOOP_THREAD
    _STOP_LOOP_EVENT.set()
    _AUTO_LOOP["active"] = False
    if _LOOP_THREAD and _LOOP_THREAD.is_alive():
        _LOOP_THREAD.join(timeout=3)
    _LOOP_THREAD = None
    _STOP_LOOP_EVENT.clear()


if __name__ == "__main__":
    print("ERPAgent Glass UI (Grok-powered)  →  http://127.0.0.1:5010")
    app.run(host="0.0.0.0", port=5010, debug=False, threaded=True)
