"""
Sales Order Draft Creation and Validation Module
This module provides functionality to create and validate sales order drafts. It includes classes and functions to resolve item, customer, pricing, and terms/rep values, as well as to validate the draft data against the resolved values.
"""

import datetime
import hmac
import html as html_lib
import importlib
import io
import json
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from functools import lru_cache, wraps
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import requests
import urllib3
from flask import Flask, Response, jsonify, request, send_from_directory, session
from pydantic import BaseModel, Field, ValidationError
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
from werkzeug.middleware.proxy_fix import ProxyFix

# Import new centralized modules
import config_manager
import system_prompts

try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except ImportError:
    ORACLEDB_AVAILABLE = False

try:
    openpyxl_mod = importlib.import_module("openpyxl")
    openpyxl_styles = importlib.import_module("openpyxl.styles")
    Workbook = openpyxl_mod.Workbook
    Alignment = openpyxl_styles.Alignment
    Border = openpyxl_styles.Border
    Font = openpyxl_styles.Font
    PatternFill = openpyxl_styles.PatternFill
    Side = openpyxl_styles.Side
    OPENPYXL_AVAILABLE = True
except Exception:
    Workbook = None
    Alignment = Border = Font = PatternFill = Side = None
    OPENPYXL_AVAILABLE = False


# =========================================================
# Configuration - Using config_manager module
# =========================================================

app_config = config_manager.load_config()


# =========================================================
# Flask App / Globals
# =========================================================

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

if int(config_manager.get_config_value("trusted_proxy_hops", 0) or 0) > 0:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Only suppress TLS warnings in explicit dev/test mode
if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _tls_verify_enabled():
    """Returns False when config.json sets verify_ssl=false OR the env var overrides."""
    if os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes"):
        return False
    cfg_val = app_config.get("verify_ssl", True)
    if isinstance(cfg_val, bool):
        return cfg_val
    return str(cfg_val).strip().lower() not in ("false", "0", "no")

GROK_BASE_URL = "https://api.x.ai/v1"
GROK_DEFAULT_MODEL = "grok-3"
oracle_initialized = False

_last_operation = {
    "type": None,
    "data": None,
    "raw": None,
    "email_html": "",
    "ai_summary": ""
}

_auto_email = {
    "enabled": False,
    "to": "",
}

_scheduler = {
    "active": False,
    "interval_mins": 60,
    "customer_name": "",
    "to_email": "",
    "last_run": None,
    "last_status": None,
    "runs": 0,
}
_stop_event = threading.Event()
_scheduler_thread = None

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


# =========================================================
# Core Helpers
# =========================================================

# LLM-OT-02 / OWASP: Use proper TLS verification. DISABLE_TLS_VERIFY env var
# may be set to '1' only in isolated dev/test environments — never in production.
_TLS_VERIFY_DISABLED = os.environ.get("DISABLE_TLS_VERIFY", "").lower() in ("1", "true", "yes")


class ForceTLSAdapter(HTTPAdapter):
    """Adapter that supports legacy cipher suites for older ERP endpoints.
    TLS certificate verification is controlled by config.json 'verify_ssl' key
    (default: true). Set to false only for internal ERP servers with self-signed certs."""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        if not _tls_verify_enabled():
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


# Use config_manager functions
def get_org_id():
    return config_manager.get_org_id()


def get_order_type_id():
    return config_manager.get_order_type_id()


def get_default_payment_term_id():
    return config_manager.get_default_payment_term_id()


def get_default_price_list_id():
    return config_manager.get_default_price_list_id()


def get_default_salesrep_id():
    return config_manager.get_default_salesrep_id()


def get_default_ship_to_org_id():
    return config_manager.get_default_ship_to_org_id()


def get_default_sold_to_org_id():
    return config_manager.get_default_sold_to_org_id()


def get_default_inventory_item_id():
    return config_manager.get_default_inventory_item_id()


def get_max_choices():
    return config_manager.get_max_choices()


def get_operating_unit():
    return config_manager.get_operating_unit()


def get_rest_header():
    return config_manager.get_rest_header()


def get_service_urls():
    return config_manager.get_service_urls()


def build_session():
    req_session = requests.Session()
    req_session.mount("https://", ForceTLSAdapter())
    req_session.auth = HTTPBasicAuth(app_config["api_user"], app_config["api_password"])
    req_session.verify = _tls_verify_enabled()
    if not req_session.verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return req_session


def sync_runtime_from_config():
    _auto_email["enabled"] = bool(app_config.get("auto_email_enabled", False))
    _auto_email["to"] = str(app_config.get("auto_email_to", "") or "").strip()

    _scheduler["interval_mins"] = int(app_config.get("scheduler_default_interval_mins", 60) or 60)
    _scheduler["customer_name"] = str(app_config.get("scheduler_default_customer_name", "") or "").strip()
    _scheduler["to_email"] = str(app_config.get("scheduler_default_to_email", "") or "").strip()


sync_runtime_from_config()


def initialize_oracle():
    global oracle_initialized

    if oracle_initialized:
        return

    if not ORACLEDB_AVAILABLE:
        raise RuntimeError("oracledb is not installed. Run: pip install oracledb")

    client_path = app_config.get("oracle_client_path")

    try:
        if client_path and os.path.exists(client_path):
            oracledb.init_oracle_client(lib_dir=client_path)
        else:
            try:
                oracledb.init_oracle_client()
            except Exception:
                pass
    except Exception as e:
        print(f"Oracle Client Init Warning: {e}")

    oracle_initialized = True


def get_db_connection():
    initialize_oracle()

    dsn = (
        "(DESCRIPTION="
        "(ADDRESS=(PROTOCOL=TCP)"
        f"(HOST={app_config['db_host']})"
        f"(PORT={app_config['db_port']}))"
        "(CONNECT_DATA="
        f"(SERVICE_NAME={app_config['db_service']})))"
    )

    return oracledb.connect(
        user=app_config["db_user"],
        password=app_config["db_password"],
        dsn=dsn
    )


def execute_query(sql, params=None):
    params = params or {}

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [col[0] for col in cur.description]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]


def _extract_requested_chart_type(user_input: str) -> Optional[str]:
    lower = str(user_input or "").lower()
    if "pie" in lower:
        return "pie"
    if "doughnut" in lower or "donut" in lower:
        return "donut"
    # Distribution phrasing usually maps better to pie/doughnut visuals.
    if any(token in lower for token in ["status", "distribution", "breakdown", "share", "proportion"]):
        return "pie"
    if "line" in lower or "trend" in lower:
        return "line"
    if "bar" in lower or "column" in lower or "histogram" in lower:
        return "bar"
    return None


def _is_visualization_requested(user_input: str) -> bool:
    lower = str(user_input or "").lower()
    tokens = [
        "chart",
        "graph",
        "plot",
        "visual",
        "visualization",
        "representation",
        "show me",
        "bar representation",
        "bar chart",
        "line chart",
        "pie chart",
        "doughnut",
    ]
    return any(token in lower for token in tokens)


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
    if not rows:
        return {"ok": False, "reason": "Visualization cannot be generated because the operation returned no rows."}
    if not columns:
        return {"ok": False, "reason": "Visualization cannot be generated because the result has no columns."}

    display_rows = rows[:60]
    numeric_cols: List[str] = []
    label_cols: List[str] = []

    for idx, col in enumerate(columns):
        col_values = [r[idx] if isinstance(r, list) and idx < len(r) else "" for r in display_rows]
        non_empty_vals = [v for v in col_values if str(v).strip() not in ("", "None", "null")]
        if not non_empty_vals:
            continue
        numeric_hits = sum(1 for v in non_empty_vals if _to_float_or_none(v) is not None)
        if numeric_hits / len(non_empty_vals) >= 0.75:
            numeric_cols.append(col)
        else:
            label_cols.append(col)

    if not numeric_cols:
        return {
            "ok": False,
            "reason": "Visualization cannot be generated because the returned data has no numeric columns to plot.",
        }

    # Prefer categorical identifier columns for labels when present.
    preferred_label_hints = ("status", "type", "category", "name", "code")
    label_col = None
    for col in label_cols:
        lower_col = col.lower()
        if any(h in lower_col for h in preferred_label_hints):
            label_col = col
            break
    if label_col is None:
        label_col = label_cols[0] if label_cols else columns[0]
    label_idx = columns.index(label_col)
    labels = [
        str((row[label_idx] if isinstance(row, list) and label_idx < len(row) else "") or "-")
        for row in display_rows
    ]

    lower_cols = " ".join(c.lower() for c in columns)
    is_time_series = any(w in lower_cols for w in ("date", "month", "year", "period", "week", "day", "time"))
    inferred_type = "line" if is_time_series else "bar"
    chart_type = preferred_type or inferred_type

    supported_types = {"bar", "line", "pie", "doughnut"}
    if chart_type not in supported_types:
        chart_type = inferred_type

    palette = [
        "rgba(37,99,235,0.75)", "rgba(16,185,129,0.75)", "rgba(245,158,11,0.75)", "rgba(239,68,68,0.75)",
        "rgba(20,184,166,0.75)", "rgba(249,115,22,0.75)", "rgba(99,102,241,0.75)", "rgba(234,88,12,0.75)",
    ]

    if chart_type in {"pie", "doughnut"}:
        preferred_numeric = None
        for col in numeric_cols:
            lower_col = col.lower()
            if any(h in lower_col for h in ("count", "qty", "quantity", "total", "amount", "value")):
                preferred_numeric = col
                break
        numeric_subset = [preferred_numeric] if preferred_numeric else [numeric_cols[0]]
    else:
        numeric_subset = numeric_cols[:4]
    datasets: List[Dict[str, Any]] = []

    for i, col in enumerate(numeric_subset):
        col_idx = columns.index(col)
        data_points: List[float] = []
        for row in display_rows:
            raw = row[col_idx] if isinstance(row, list) and col_idx < len(row) else None
            val = _to_float_or_none(raw)
            data_points.append(val if val is not None else 0.0)
        color = palette[i % len(palette)]
        datasets.append(
            {
                "label": col,
                "data": data_points,
                "backgroundColor": color,
                "borderColor": color.replace("0.75", "1"),
                "borderWidth": 1,
                "fill": False,
            }
        )

    return {
        "ok": True,
        "config": {
            "type": chart_type,
            "label_column": label_col,
            "labels": labels,
            "datasets": datasets,
            "numeric_columns": numeric_subset,
            "row_count": len(rows),
        },
    }


def _build_visualization_payload(user_input: str, columns: List[str], rows: List[List[str]]) -> Dict[str, Any]:
    requested = _is_visualization_requested(user_input)
    if not requested:
        return {"requested": False, "available": False, "reason": "", "chart_config": None}

    preferred_type = _extract_requested_chart_type(user_input)
    chart_result = _build_chart_config(columns, rows, preferred_type=preferred_type)
    if not chart_result.get("ok"):
        return {
            "requested": True,
            "available": False,
            "reason": chart_result.get("reason", "Visualization cannot be generated for this operation."),
            "chart_config": None,
        }

    return {
        "requested": True,
        "available": True,
        "reason": "",
        "chart_config": chart_result.get("config"),
    }


def _build_transaction_visualization_payload(user_input: str) -> Dict[str, Any]:
    requested = _is_visualization_requested(user_input)
    if not requested:
        return {"requested": False, "available": False, "reason": "", "chart_config": None}
    return {
        "requested": True,
        "available": False,
        "reason": (
            "Visualization is not available for this operation because it performs a transactional action "
            "and does not return report-style numeric result data."
        ),
        "chart_config": None,
    }


class CreateOrderDraft(BaseModel):
    cust_po_number: Optional[str] = None
    inventory_item_id: Optional[int] = None
    ordered_item: Optional[str] = None
    ordered_quantity: Optional[float] = Field(default=None, gt=0)
    customer_name: Optional[str] = None
    sold_to_org_id: Optional[int] = None
    ship_to_org_id: Optional[int] = None
    price_list_id: Optional[int] = None
    unit_list_price: Optional[float] = Field(default=None, ge=0)
    unit_selling_price: Optional[float] = Field(default=None, ge=0)
    payment_term_id: Optional[int] = None
    salesrep_id: Optional[int] = None
    currency: Optional[str] = None


def _resolve_item_values(draft: CreateOrderDraft) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    options: Dict[str, Any] = {}

    if draft.inventory_item_id:
        sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
            FROM MTL_SYSTEM_ITEMS_B
            WHERE INVENTORY_ITEM_ID = :item_id
            AND ORGANIZATION_ID = :org_id
            AND ROWNUM = 1
        """
        rows = execute_query(sql, {"item_id": int(draft.inventory_item_id), "org_id": int(get_org_id())})
        if rows:
            row = rows[0]
            resolved["inventory_item_id"] = int(row["INVENTORY_ITEM_ID"])
            resolved["ordered_item"] = row.get("SEGMENT1") or draft.ordered_item or ""
            return {"resolved": resolved, "options": options}

    if draft.ordered_item:
        sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
            FROM MTL_SYSTEM_ITEMS_B
            WHERE UPPER(SEGMENT1) LIKE :item_name
            AND ORGANIZATION_ID = :org_id
            ORDER BY SEGMENT1
            FETCH FIRST 25 ROWS ONLY
        """
        rows = execute_query(sql, {"item_name": f"%{str(draft.ordered_item).upper()}%", "org_id": int(get_org_id())})
        if len(rows) == 1:
            row = rows[0]
            resolved["inventory_item_id"] = int(row["INVENTORY_ITEM_ID"])
            resolved["ordered_item"] = row.get("SEGMENT1") or draft.ordered_item or ""
        elif rows:
            options["items"] = [
                {
                    "inventory_item_id": int(r["INVENTORY_ITEM_ID"]),
                    "segment1": r.get("SEGMENT1") or "",
                    "description": r.get("DESCRIPTION") or "",
                }
                for r in rows
            ]
        else:
            options["items"] = []

    return {"resolved": resolved, "options": options}


def _resolve_customer_values(draft: CreateOrderDraft) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    options: Dict[str, Any] = {}

    if draft.sold_to_org_id:
        sql = """
            SELECT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME, hca.ACCOUNT_NUMBER
            FROM HZ_CUST_ACCOUNTS hca
            JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
            WHERE hca.CUST_ACCOUNT_ID = :cust_account_id
            AND hca.STATUS = 'A'
            FETCH FIRST 1 ROWS ONLY
        """
        rows = execute_query(sql, {"cust_account_id": int(draft.sold_to_org_id)})
        if rows:
            resolved["sold_to_org_id"] = int(rows[0]["CUST_ACCOUNT_ID"])
            resolved["customer_name"] = rows[0].get("PARTY_NAME") or draft.customer_name or ""
        else:
            options["customers"] = []
    elif draft.customer_name:
        sql = """
            SELECT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME, hca.ACCOUNT_NUMBER
            FROM HZ_CUST_ACCOUNTS hca
            JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
            WHERE UPPER(hp.PARTY_NAME) LIKE :cust_name
            AND hca.STATUS = 'A'
            ORDER BY hp.PARTY_NAME
            FETCH FIRST 25 ROWS ONLY
        """
        rows = execute_query(sql, {"cust_name": f"%{str(draft.customer_name).upper()}%"})
        if len(rows) == 1:
            resolved["sold_to_org_id"] = int(rows[0]["CUST_ACCOUNT_ID"])
            resolved["customer_name"] = rows[0].get("PARTY_NAME") or draft.customer_name
        elif rows:
            options["customers"] = [
                {
                    "cust_account_id": int(r["CUST_ACCOUNT_ID"]),
                    "customer_name": r.get("PARTY_NAME") or "",
                    "account_number": r.get("ACCOUNT_NUMBER") or "",
                }
                for r in rows
            ]
        else:
            options["customers"] = []

    sold_to = resolved.get("sold_to_org_id") or draft.sold_to_org_id
    if sold_to and not draft.ship_to_org_id:
        sql = """
            SELECT hcsu.SITE_USE_ID, hcsu.LOCATION,
                   hl.ADDRESS1, hl.CITY, hl.STATE, hl.POSTAL_CODE
            FROM HZ_CUST_ACCT_SITES_ALL hcas
            JOIN HZ_CUST_SITE_USES_ALL hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
            JOIN HZ_PARTY_SITES hps ON hps.PARTY_SITE_ID = hcas.PARTY_SITE_ID
            JOIN HZ_LOCATIONS hl ON hl.LOCATION_ID = hps.LOCATION_ID
            WHERE hcas.CUST_ACCOUNT_ID = :cust_account_id
            AND hcas.ORG_ID = :org_id
            AND hcsu.SITE_USE_CODE = 'SHIP_TO'
            AND hcsu.STATUS = 'A'
            ORDER BY hcsu.SITE_USE_ID
            FETCH FIRST 25 ROWS ONLY
        """
        site_rows = execute_query(sql, {"cust_account_id": int(sold_to), "org_id": int(get_org_id())})
        if len(site_rows) == 1:
            resolved["ship_to_org_id"] = int(site_rows[0]["SITE_USE_ID"])
        elif site_rows:
            options["sites"] = [
                {
                    "ship_to_org_id": int(r["SITE_USE_ID"]),
                    "location": r.get("LOCATION") or "",
                    "address": ", ".join(
                        [
                            p for p in [r.get("ADDRESS1") or "", r.get("CITY") or "", r.get("STATE") or "", r.get("POSTAL_CODE") or ""] if p
                        ]
                    ),
                }
                for r in site_rows
            ]
    elif draft.ship_to_org_id:
        site_sql = """
            SELECT hcsu.SITE_USE_ID, hcsu.LOCATION,
                   hl.ADDRESS1, hl.CITY, hl.STATE, hl.POSTAL_CODE,
                   hcas.CUST_ACCOUNT_ID
            FROM HZ_CUST_ACCT_SITES_ALL hcas
            JOIN HZ_CUST_SITE_USES_ALL hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
            JOIN HZ_PARTY_SITES hps ON hps.PARTY_SITE_ID = hcas.PARTY_SITE_ID
            JOIN HZ_LOCATIONS hl ON hl.LOCATION_ID = hps.LOCATION_ID
            WHERE hcsu.SITE_USE_ID = :ship_to_org_id
            AND hcas.ORG_ID = :org_id
            AND hcsu.SITE_USE_CODE = 'SHIP_TO'
            AND hcsu.STATUS = 'A'
            FETCH FIRST 1 ROWS ONLY
        """
        site_rows = execute_query(site_sql, {"ship_to_org_id": int(draft.ship_to_org_id), "org_id": int(get_org_id())})
        if site_rows:
            resolved["ship_to_org_id"] = int(site_rows[0]["SITE_USE_ID"])
            if not resolved.get("sold_to_org_id"):
                resolved["sold_to_org_id"] = int(site_rows[0]["CUST_ACCOUNT_ID"])
        else:
            options.setdefault("sites", [])

    return {"resolved": resolved, "options": options}


def _resolve_pricing_values(draft: CreateOrderDraft, item_id: Optional[int]) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    options: Dict[str, Any] = {}

    if draft.price_list_id:
        sql = """
            SELECT LIST_HEADER_ID AS price_list_id, CURRENCY_CODE
            FROM QP_LIST_HEADERS_B
            WHERE LIST_HEADER_ID = :price_list_id
            AND ACTIVE_FLAG = 'Y'
            AND LIST_TYPE_CODE = 'PRL'
            FETCH FIRST 1 ROWS ONLY
        """
        rows = execute_query(sql, {"price_list_id": int(draft.price_list_id)})
        if rows:
            resolved["price_list_id"] = int(rows[0]["PRICE_LIST_ID"])
        else:
            options["prices"] = []
    if draft.unit_list_price is not None:
        resolved["unit_list_price"] = float(draft.unit_list_price)
    if draft.unit_selling_price is not None:
        resolved["unit_selling_price"] = float(draft.unit_selling_price)

    if item_id and ("price_list_id" not in resolved or "unit_list_price" not in resolved):
        sql = """
            SELECT DISTINCT qlh.LIST_HEADER_ID AS price_list_id,
                            qlt.NAME AS price_list_name,
                            qll.OPERAND AS unit_list_price
            FROM QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa
            WHERE qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
            AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
            AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
            AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
            AND qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL' AND qlh.CURRENCY_CODE = 'USD'
            ORDER BY qlh.LIST_HEADER_ID
            FETCH FIRST 25 ROWS ONLY
        """
        rows = execute_query(sql, {"item_id_str": str(item_id)})
        if len(rows) == 1:
            resolved.setdefault("price_list_id", int(rows[0]["PRICE_LIST_ID"]))
            resolved.setdefault("unit_list_price", float(rows[0]["UNIT_LIST_PRICE"] or 0))
        elif rows:
            options["prices"] = [
                {
                    "price_list_id": int(r["PRICE_LIST_ID"]),
                    "price_list_name": r.get("PRICE_LIST_NAME") or "",
                    "unit_list_price": float(r.get("UNIT_LIST_PRICE") or 0),
                }
                for r in rows
            ]

    if "unit_selling_price" not in resolved and "unit_list_price" in resolved:
        resolved["unit_selling_price"] = float(resolved["unit_list_price"])

    return {"resolved": resolved, "options": options}


def _resolve_term_and_rep_values(draft: CreateOrderDraft) -> Dict[str, Any]:
    resolved: Dict[str, Any] = {}
    options: Dict[str, Any] = {}

    if draft.payment_term_id:
        try:
            term_rows = execute_query(
                """
                SELECT TERM_ID, NAME
                FROM RA_TERMS_VL
                WHERE TERM_ID = :term_id
                AND (START_DATE_ACTIVE IS NULL OR START_DATE_ACTIVE <= SYSDATE)
                AND (END_DATE_ACTIVE IS NULL OR END_DATE_ACTIVE >= SYSDATE)
                FETCH FIRST 1 ROWS ONLY
                """,
                {"term_id": int(draft.payment_term_id)},
            )
            if term_rows:
                resolved["payment_term_id"] = int(term_rows[0]["TERM_ID"])
            else:
                options["terms"] = []
        except Exception:
            options["terms"] = []
    else:
        resolved["payment_term_id"] = int(get_default_payment_term_id())

    if not draft.payment_term_id:
        try:
            terms = execute_query(
                """
                SELECT TERM_ID, NAME
                FROM RA_TERMS_VL
                WHERE (START_DATE_ACTIVE IS NULL OR START_DATE_ACTIVE <= SYSDATE)
                AND (END_DATE_ACTIVE IS NULL OR END_DATE_ACTIVE >= SYSDATE)
                ORDER BY TERM_ID
                FETCH FIRST 25 ROWS ONLY
                """
            )
            options["terms"] = [{"term_id": int(t["TERM_ID"]), "term_name": t.get("NAME") or ""} for t in terms]
        except Exception:
            options["terms"] = []

    if not draft.salesrep_id:
        try:
            reps = execute_query(
                """
                SELECT SALESREP_ID, NAME AS SALESREP_NAME
                FROM JTF_RS_SALESREPS
                WHERE ORG_ID = :org_id AND STATUS = 'A' AND END_DATE_ACTIVE IS NULL
                ORDER BY SALESREP_ID
                FETCH FIRST 25 ROWS ONLY
                """,
                {"org_id": int(get_org_id())},
            )
            options["reps"] = [{"salesrep_id": int(r["SALESREP_ID"]), "salesrep_name": r.get("SALESREP_NAME") or ""} for r in reps]
        except Exception:
            options["reps"] = []
    else:
        try:
            reps = execute_query(
                """
                SELECT SALESREP_ID, NAME AS SALESREP_NAME
                FROM JTF_RS_SALESREPS
                WHERE SALESREP_ID = :salesrep_id
                AND ORG_ID = :org_id
                AND STATUS = 'A'
                AND END_DATE_ACTIVE IS NULL
                FETCH FIRST 1 ROWS ONLY
                """,
                {"salesrep_id": int(draft.salesrep_id), "org_id": int(get_org_id())},
            )
            if reps:
                resolved["salesrep_id"] = int(reps[0]["SALESREP_ID"])
            else:
                options["reps"] = []
        except Exception:
            options["reps"] = []

    return {"resolved": resolved, "options": options}


def resolve_create_order_draft(draft: CreateOrderDraft, strict_mode: bool = False) -> Dict[str, Any]:
    warnings: List[str] = []
    base_resolved: Dict[str, Any] = {
        "cust_po_number": (draft.cust_po_number or "").strip(),
        "ordered_quantity": float(draft.ordered_quantity or 1),
        "order_type_id": int(get_order_type_id()),
        "currency": (draft.currency or "USD").strip() or "USD",
    }

    try:
        item_res = _resolve_item_values(draft)
    except Exception as e:
        item_res = {"resolved": {}, "options": {"items": []}}
        warnings.append(f"Item lookup unavailable: {e}")
    base_resolved.update(item_res["resolved"])

    try:
        cust_res = _resolve_customer_values(draft)
    except Exception as e:
        cust_res = {"resolved": {}, "options": {"customers": [], "sites": []}}
        warnings.append(f"Customer/site lookup unavailable: {e}")
    base_resolved.update(cust_res["resolved"])

    item_id_for_price = base_resolved.get("inventory_item_id")
    try:
        price_res = _resolve_pricing_values(draft, item_id_for_price)
    except Exception as e:
        price_res = {"resolved": {}, "options": {"prices": []}}
        warnings.append(f"Pricing lookup unavailable: {e}")
    base_resolved.update(price_res["resolved"])

    try:
        term_rep_res = _resolve_term_and_rep_values(draft)
    except Exception as e:
        term_rep_res = {"resolved": {}, "options": {"terms": [], "reps": []}}
        warnings.append(f"Terms/rep lookup unavailable: {e}")
    base_resolved.update(term_rep_res["resolved"])

    if not strict_mode:
        # Hard defaults only for non-strict mode
        base_resolved.setdefault("sold_to_org_id", int(get_default_sold_to_org_id()))
        base_resolved.setdefault("ship_to_org_id", int(get_default_ship_to_org_id()))
        base_resolved.setdefault("price_list_id", int(get_default_price_list_id()))
        base_resolved.setdefault("unit_list_price", float(draft.unit_list_price or 0))
        base_resolved.setdefault("unit_selling_price", float(draft.unit_selling_price or base_resolved.get("unit_list_price") or 0))
    else:
        if draft.unit_list_price is not None:
            base_resolved["unit_list_price"] = float(draft.unit_list_price)
        elif base_resolved.get("unit_list_price") is None:
            base_resolved["unit_list_price"] = 0.0

        if draft.unit_selling_price is not None:
            base_resolved["unit_selling_price"] = float(draft.unit_selling_price)
        elif base_resolved.get("unit_selling_price") is None:
            base_resolved["unit_selling_price"] = float(base_resolved.get("unit_list_price") or 0)

    missing: List[str] = []
    if not strict_mode and not base_resolved.get("inventory_item_id"):
        default_item_id = get_default_inventory_item_id()
        if default_item_id:
            try:
                base_resolved["inventory_item_id"] = int(default_item_id)
            except Exception:
                pass

    if not base_resolved.get("inventory_item_id"):
        missing.append("inventory_item_id")
    if strict_mode and not base_resolved.get("sold_to_org_id"):
        missing.append("sold_to_org_id")
    if strict_mode and not base_resolved.get("ship_to_org_id"):
        missing.append("ship_to_org_id")
    if strict_mode and not base_resolved.get("price_list_id"):
        missing.append("price_list_id")
    if strict_mode and not base_resolved.get("payment_term_id"):
        missing.append("payment_term_id")
    if strict_mode and not base_resolved.get("salesrep_id"):
        missing.append("salesrep_id")

    options: Dict[str, Any] = {}
    options.update(item_res.get("options") or {})
    options.update(cust_res.get("options") or {})
    options.update(price_res.get("options") or {})
    options.update(term_rep_res.get("options") or {})

    return {
        "resolved": base_resolved,
        "missing": missing,
        "options": options,
        "warnings": (["Some values were auto-filled from defaults and database lookups." if not missing else "Some required values still need selection."] + warnings),
    }


def _fetch_quick_item_suggestions(search_text: str = "") -> List[Dict[str, Any]]:
    like_val = f"%{str(search_text or '').upper()}%"
    bind_params = {"org_id": int(get_org_id()), "item_name": like_val if like_val != "%%" else "%%"}
    try:
        rows = execute_query(
            """
            SELECT
                msi.INVENTORY_ITEM_ID,
                msi.SEGMENT1,
                msi.DESCRIPTION,
                COUNT(*) AS ORDER_COUNT
            FROM OE_ORDER_LINES_ALL ool
            JOIN OE_ORDER_HEADERS_ALL ooh ON ooh.HEADER_ID = ool.HEADER_ID
            JOIN MTL_SYSTEM_ITEMS_B msi
              ON msi.INVENTORY_ITEM_ID = ool.INVENTORY_ITEM_ID
             AND msi.ORGANIZATION_ID = :org_id
            WHERE ool.ORG_ID = :org_id
              AND ooh.ORG_ID = :org_id
              AND (:item_name = '%%' OR UPPER(msi.SEGMENT1) LIKE :item_name)
            GROUP BY msi.INVENTORY_ITEM_ID, msi.SEGMENT1, msi.DESCRIPTION
            ORDER BY COUNT(*) DESC, msi.SEGMENT1
            FETCH FIRST 10 ROWS ONLY
            """,
            bind_params,
        )
    except Exception:
        rows = execute_query(
            """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, 0 AS ORDER_COUNT
            FROM MTL_SYSTEM_ITEMS_B
            WHERE ORGANIZATION_ID = :org_id
            AND (:item_name = '%%' OR UPPER(SEGMENT1) LIKE :item_name)
            ORDER BY SEGMENT1
            FETCH FIRST 10 ROWS ONLY
            """,
            bind_params,
        )

    # If search text is too specific and returns no rows, still provide top-ordered items.
    if not rows and like_val != "%%":
        try:
            rows = execute_query(
                """
                SELECT
                    msi.INVENTORY_ITEM_ID,
                    msi.SEGMENT1,
                    msi.DESCRIPTION,
                    COUNT(*) AS ORDER_COUNT
                FROM OE_ORDER_LINES_ALL ool
                JOIN OE_ORDER_HEADERS_ALL ooh ON ooh.HEADER_ID = ool.HEADER_ID
                JOIN MTL_SYSTEM_ITEMS_B msi
                  ON msi.INVENTORY_ITEM_ID = ool.INVENTORY_ITEM_ID
                 AND msi.ORGANIZATION_ID = :org_id
                WHERE ool.ORG_ID = :org_id
                  AND ooh.ORG_ID = :org_id
                GROUP BY msi.INVENTORY_ITEM_ID, msi.SEGMENT1, msi.DESCRIPTION
                ORDER BY COUNT(*) DESC, msi.SEGMENT1
                FETCH FIRST 10 ROWS ONLY
                """,
                {"org_id": int(get_org_id())},
            )
        except Exception:
            rows = execute_query(
                """
                SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, 0 AS ORDER_COUNT
                FROM MTL_SYSTEM_ITEMS_B
                WHERE ORGANIZATION_ID = :org_id
                ORDER BY SEGMENT1
                FETCH FIRST 10 ROWS ONLY
                """,
                {"org_id": int(get_org_id())},
            )

    return [
        {
            "inventory_item_id": int(r["INVENTORY_ITEM_ID"]),
            "segment1": r.get("SEGMENT1") or "",
            "description": r.get("DESCRIPTION") or "",
            "order_count": int(r.get("ORDER_COUNT") or 0),
        }
        for r in rows
    ]


def _fetch_quick_customer_suggestions(search_text: str = "") -> List[Dict[str, Any]]:
    like_val = f"%{str(search_text or '').upper()}%"
    rows = execute_query(
        """
        SELECT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME, hca.ACCOUNT_NUMBER
        FROM HZ_CUST_ACCOUNTS hca
        JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
        WHERE hca.STATUS = 'A'
        AND (:cust_name = '%%' OR UPPER(hp.PARTY_NAME) LIKE :cust_name)
        ORDER BY hp.PARTY_NAME
        FETCH FIRST 10 ROWS ONLY
        """,
        {"cust_name": like_val if like_val != "%%" else "%%"},
    )
    return [
        {
            "cust_account_id": int(r["CUST_ACCOUNT_ID"]),
            "customer_name": r.get("PARTY_NAME") or "",
            "account_number": r.get("ACCOUNT_NUMBER") or "",
        }
        for r in rows
    ]


def validate_create_order_data(draft: CreateOrderDraft, resolution: Dict[str, Any]) -> Dict[str, Any]:
    resolved = resolution.get("resolved") or {}
    options = resolution.get("options") or {}
    errors: List[Dict[str, str]] = []
    suggestions: Dict[str, Any] = {}

    if not resolved.get("inventory_item_id"):
        errors.append({
            "field": "item",
            "message": "Item not found. Please select one of the suggested frequently ordered items.",
        })
        item_suggestions = list(options.get("items") or [])
        if not item_suggestions:
            try:
                item_suggestions = _fetch_quick_item_suggestions(draft.ordered_item or "")
            except Exception:
                item_suggestions = []
        suggestions["items"] = item_suggestions

    if not resolved.get("sold_to_org_id"):
        errors.append({"field": "customer", "message": "Customer not found. Please select a valid customer."})
        customer_suggestions = list(options.get("customers") or [])
        if not customer_suggestions:
            try:
                customer_suggestions = _fetch_quick_customer_suggestions(draft.customer_name or "")
            except Exception:
                customer_suggestions = []
        suggestions["customers"] = customer_suggestions

    if not resolved.get("ship_to_org_id"):
        errors.append({"field": "ship_to", "message": "Ship-to site not found for the customer. Please select a site."})
        suggestions["sites"] = list(options.get("sites") or [])

    if not resolved.get("price_list_id"):
        errors.append({"field": "price", "message": "Price list not found for the selected item. Please select a valid price list."})
        suggestions["prices"] = list(options.get("prices") or [])

    if resolved.get("ordered_quantity") is None or float(resolved.get("ordered_quantity") or 0) <= 0:
        errors.append({"field": "quantity", "message": "Ordered quantity must be greater than 0."})

    if not resolved.get("payment_term_id"):
        errors.append({"field": "payment_term", "message": "Payment term not found. Please select a valid payment term."})
        suggestions["terms"] = list(options.get("terms") or [])

    if not resolved.get("salesrep_id"):
        errors.append({"field": "salesrep", "message": "Sales rep not found. Please select a valid sales rep."})
        suggestions["reps"] = list(options.get("reps") or [])

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "suggestions": suggestions,
        "resolved": resolved,
    }


# =========================================================
# Grok (xAI) Helpers
# =========================================================

def get_grok_api_key():
    key = (
        config_manager.get_config_value("xai_api_key")
        or config_manager.get_config_value("grok_api_key")
        or os.getenv("XAI_API_KEY")
        or os.getenv("GROK_API_KEY")
    )
    if key:
        key = str(key).strip()
    return key or ""


def get_grok_base_url():
    return str(config_manager.get_config_value("grok_base_url") or GROK_BASE_URL).rstrip("/")


def get_grok_model():
    return config_manager.get_config_value("grok_model") or GROK_DEFAULT_MODEL



def grok_chat_completion(messages, temperature=0, max_tokens=None):
    api_key = get_grok_api_key()

    if not api_key:
        raise ValueError("Grok (xAI) API key is not configured.")

    payload = {
        "model": get_grok_model(),
        "messages": messages,
        "temperature": temperature
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    url = f"{get_grok_base_url()}/chat/completions"
    max_retries = int(config_manager.get_config_value("grok_max_retries", 2) or 2)
    base_delay = float(config_manager.get_config_value("grok_retry_base_seconds", 1.5) or 1.5)

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=60
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            body = ""
            if e.response is not None:
                body = str(e.response.text or "")[:500]

            if status in (400, 401, 403, 404):
                raise ValueError(
                    f"AI request rejected (HTTP {status}) by {url} using model '{get_grok_model()}'. "
                    f"Provider response: {body} "
                    "Check that grok_base_url, grok_model and the API key in config.json belong to the same provider."
                ) from e

            if status == 429:
                retry_after = 0
                if e.response is not None:
                    retry_after_raw = str(e.response.headers.get("Retry-After", "")).strip()
                    if retry_after_raw.isdigit():
                        retry_after = int(retry_after_raw)

                if attempt < max_retries:
                    sleep_seconds = retry_after if retry_after > 0 else base_delay * (2 ** attempt)
                    time.sleep(min(sleep_seconds, 15))
                    continue

                wait_hint = f" Retry after {retry_after}s." if retry_after > 0 else " Please wait a few seconds and try again."
                raise ValueError(f"AI service is rate-limited (HTTP 429).{wait_hint}") from e

            if status in (500, 502, 503, 504) and attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue

            raise

        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise ValueError(f"AI service request failed: {e}") from e


def build_history_string(history):
    lines = []
    for msg in history[-8:]:
        role = str(msg.get("role", ""))
        content = str(msg.get("content", ""))
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def grok_chat_completion_stream(messages, temperature=0, max_tokens=None):
    api_key = get_grok_api_key()
    if not api_key:
        raise ValueError("Grok (xAI) API key is not configured.")

    payload = {
        "model": get_grok_model(),
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    response = requests.post(
        f"{get_grok_base_url()}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
        stream=True,
    )
    response.raise_for_status()

    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        choices = event.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            content = delta.get("content") or ""
            if content:
                yield content


def generate_general_chat_response(history, user_input):
    api_key = get_grok_api_key()
    if not api_key:
        return (
            "I can answer general AI-style questions after you set xai_api_key in config.json "
            "(or the XAI_API_KEY environment variable)."
        )

    system_prompt = (
        "You are a helpful AI assistant. Answer clearly and directly. "
        "For ERP or sales order requests, suggest specific commands only when useful."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        role = str(msg.get("role", "")).strip().lower()
        if role not in ("user", "assistant", "system"):
            continue
        content = str(msg.get("content", "")).strip()
        if content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_input})

    try:
        response = grok_chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=700,
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"AI response error: {e}"


def generate_general_chat_response_stream(history, user_input):
    messages = [{
        "role": "system",
        "content": (
            "You are a helpful AI assistant. Answer clearly and directly. "
            "For ERP or sales order requests, suggest specific commands only when useful."
        ),
    }]
    for msg in history[-10:]:
        role = str(msg.get("role", "")).strip().lower()
        if role not in ("user", "assistant", "system"):
            continue
        content = str(msg.get("content", "")).strip()
        if content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_input})
    return grok_chat_completion_stream(messages, temperature=0.7, max_tokens=700)


def is_erp_or_data_query(user_input):
    text = str(user_input or "").lower()
    keywords = [
        "order",
        "orders",
        "customer",
        "customers",
        "line",
        "item",
        "invoice",
        "shipment",
        "booked",
        "entered",
        "cancelled",
        "po",
        "sales",
        "sql",
        "query",
        "report",
        "email",
        "erp",
        "track",
        "tracking",
        "shipping",
        "ship to",
    ]
    return any(k in text for k in keywords)


def should_route_to_dynamic_query(action, intent, user_input):
    lower = str(user_input or "").lower().strip()

    # Custom date windows and SQL-like filters are not covered by current REST shortcuts.
    has_between_range = bool(re.search(r"\bbetween\b.+\band\b", lower))
    has_from_to_range = bool(re.search(r"\bfrom\b.+\bto\b", lower))
    has_like_filter = " like " in f" {lower} "
    has_explicit_date = bool(
        re.search(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", lower)
        or re.search(r"\b\d{4}-\d{2}-\d{2}\b", lower)
        or re.search(r"\b\d{1,2}[-/][a-z]{3,9}[-/]\d{2,4}\b", lower)
    )

    if action in ("get", "get_range") and (has_between_range or has_from_to_range or has_like_filter or has_explicit_date):
        return True

    if action == "get":
        # REST get supports only order_number OR customer_name lookups.
        if intent.get("date_range") or intent.get("year") or intent.get("status"):
            return True

    if action == "get_range":
        supported_ranges = {None, "this_month", "this_week", "last_30_days"}
        if intent.get("date_range") not in supported_ranges:
            return True
        # REST get_range does not support customer-name filtering.
        if intent.get("customer_name"):
            return True

    return False


def extract_dynamic_filters_from_text(user_input):
    text = str(user_input or "").strip()
    filters = {}

    like_match = re.search(
        r"(?:customer\s+name|customer)\s+like\s+([a-z0-9_\-\.&\s]+?)(?:\s+(?:and|or|where|with|between)\b|$)",
        text,
        re.IGNORECASE,
    )
    if like_match:
        customer_like = like_match.group(1).strip(" .,")
        if customer_like:
            filters["customer_name_like"] = customer_like

    return filters


KNOWN_ORDER_STATUSES = {
    "entered": "ENTERED",
    "booked": "BOOKED",
    "shipped": "SHIPPED",
    "cancelled": "CANCELLED",
    "canceled": "CANCELLED",
    "closed": "CLOSED",
    "awaiting_shipping": "AWAITING_SHIPPING",
    "awaiting shipping": "AWAITING_SHIPPING",
}


def _extract_order_tracking_filters(user_input):
    text = str(user_input or "").strip()
    lower = text.lower()

    filters = {
        "order_numbers": [],
        "status": None,
        "customer_name_like": None,
        "ordered_item_like": None,
        "po_number": None,
        "ship_to_org_id": None,
        "date_range": None,
        "year": None,
    }

    explicit_order_nums = re.findall(r"(?:order\s*(?:number|#)?\s*)(\d{4,})", lower)
    hash_order_nums = re.findall(r"#(\d{4,})", lower)
    order_nums = explicit_order_nums + hash_order_nums
    if order_nums:
        filters["order_numbers"] = list(dict.fromkeys(int(n) for n in order_nums))

    for key, status_val in KNOWN_ORDER_STATUSES.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            filters["status"] = status_val
            break

    customer_match = re.search(
        r"(?:customer|party|account)\s*(?:name)?\s*(?:is|=|like)?\s*['\"]?([a-z0-9_\-\.&\s]{2,})",
        text,
        re.IGNORECASE,
    )
    if customer_match:
        cust = customer_match.group(1).strip(" .,\"'")
        stop_words = [" and ", " with ", " where ", " status ", " item ", " po ", " ship "]
        for stop in stop_words:
            idx = cust.lower().find(stop)
            if idx > 0:
                cust = cust[:idx].strip()
        if cust:
            filters["customer_name_like"] = cust

    item_match = re.search(r"(?:item|ordered item)\s*(?:is|=|like)?\s*([a-z0-9_\-\.]+)", text, re.IGNORECASE)
    if item_match:
        item_val = item_match.group(1).strip(" .,")
        if item_val:
            filters["ordered_item_like"] = item_val

    po_match = re.search(r"\b(?:po|customer\s*po)\s*(?:number|#)?\s*[:=]?\s*([a-z0-9_\-\/\.]+)", text, re.IGNORECASE)
    if po_match:
        po_val = po_match.group(1).strip(" .,")
        if po_val:
            filters["po_number"] = po_val

    ship_to_match = re.search(r"ship(?:ping)?\s*to\s*(?:org|site|id)?\s*#?\s*(\d+)", lower)
    if ship_to_match:
        filters["ship_to_org_id"] = int(ship_to_match.group(1))

    if "this month" in lower:
        filters["date_range"] = "this_month"
    elif "this week" in lower:
        filters["date_range"] = "this_week"
    elif "last 30" in lower:
        filters["date_range"] = "last_30_days"

    year_match = re.search(r"\b(20\d{2})\b", lower)
    if year_match and ("year" in lower or "in " in lower or "for " in lower):
        filters["year"] = int(year_match.group(1))

    return filters


def _should_use_order_tracking_query(user_input, filters):
    lower = str(user_input or "").lower()
    if filters.get("order_numbers"):
        return True

    tracking_words = ("track", "tracking", "shipping", "shipment", "ship to", "delivery status")
    has_tracking_term = any(w in lower for w in tracking_words)
    has_order_context = "order" in lower or "orders" in lower

    combo_fields = [
        "status",
        "customer_name_like",
        "ordered_item_like",
        "po_number",
        "ship_to_org_id",
        "date_range",
        "year",
    ]
    combo_count = sum(1 for key in combo_fields if filters.get(key) not in (None, "", []))

    return (has_order_context or has_tracking_term) and combo_count >= 2


def _build_order_tracking_query(filters):
    where_clauses = ["ooha.ORG_ID = :org_id"]
    bind_params = {"org_id": int(get_org_id())}

    order_numbers = filters.get("order_numbers") or []
    if order_numbers:
        placeholders = []
        for idx, num in enumerate(order_numbers):
            key = f"order_num_{idx}"
            placeholders.append(f":{key}")
            bind_params[key] = int(num)
        where_clauses.append(f"ooha.ORDER_NUMBER IN ({', '.join(placeholders)})")

    status = filters.get("status")
    if status:
        bind_params["status_val"] = str(status).upper()
        where_clauses.append("UPPER(ooha.FLOW_STATUS_CODE) = :status_val")

    customer_name_like = filters.get("customer_name_like")
    if customer_name_like:
        bind_params["cust_like"] = f"%{str(customer_name_like).upper()}%"
        where_clauses.append("UPPER(hp.PARTY_NAME) LIKE :cust_like")

    ordered_item_like = filters.get("ordered_item_like")
    if ordered_item_like:
        bind_params["item_like"] = f"%{str(ordered_item_like).upper()}%"
        where_clauses.append("UPPER(oola.ORDERED_ITEM) LIKE :item_like")

    po_number = filters.get("po_number")
    if po_number:
        bind_params["po_like"] = f"%{str(po_number).upper()}%"
        where_clauses.append("UPPER(ooha.CUST_PO_NUMBER) LIKE :po_like")

    ship_to_org_id = filters.get("ship_to_org_id")
    if ship_to_org_id:
        bind_params["ship_to_org_id"] = int(ship_to_org_id)
        where_clauses.append("ooha.SHIP_TO_ORG_ID = :ship_to_org_id")

    year = filters.get("year")
    if year:
        bind_params["year_val"] = int(year)
        where_clauses.append("EXTRACT(YEAR FROM ooha.ORDERED_DATE) = :year_val")

    date_range = filters.get("date_range")
    if date_range == "this_month":
        where_clauses.append("ooha.ORDERED_DATE >= TRUNC(SYSDATE, 'MM')")
    elif date_range == "this_week":
        where_clauses.append("ooha.ORDERED_DATE >= TRUNC(SYSDATE, 'IW')")
    elif date_range == "last_30_days":
        where_clauses.append("ooha.ORDERED_DATE >= SYSDATE - 30")

    where_sql = "\nAND ".join(where_clauses)

    sql = f"""
SELECT
    ooha.ORDER_NUMBER,
    ooha.FLOW_STATUS_CODE AS ORDER_STATUS,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    ooha.CUST_PO_NUMBER,
    ooha.SHIP_TO_ORG_ID,
    NVL(hcsu.LOCATION, 'N/A') AS SHIP_TO_LOCATION,
    TRIM(
        NVL(hl.ADDRESS1, '')
        || CASE WHEN hl.CITY IS NOT NULL THEN ', ' || hl.CITY ELSE '' END
        || CASE WHEN hl.STATE IS NOT NULL THEN ', ' || hl.STATE ELSE '' END
        || CASE WHEN hl.POSTAL_CODE IS NOT NULL THEN ' ' || hl.POSTAL_CODE ELSE '' END
    ) AS SHIP_TO_ADDRESS,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT,
    SUM(NVL(oola.ORDERED_QUANTITY, 0) * NVL(oola.UNIT_SELLING_PRICE, 0)) AS ORDER_AMOUNT
FROM OE_ORDER_HEADERS_ALL ooha
LEFT JOIN OE_ORDER_LINES_ALL oola ON oola.HEADER_ID = ooha.HEADER_ID
LEFT JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
LEFT JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
LEFT JOIN HZ_CUST_SITE_USES_ALL hcsu ON hcsu.SITE_USE_ID = ooha.SHIP_TO_ORG_ID
LEFT JOIN HZ_CUST_ACCT_SITES_ALL hcas ON hcas.CUST_ACCT_SITE_ID = hcsu.CUST_ACCT_SITE_ID
LEFT JOIN HZ_PARTY_SITES hps ON hps.PARTY_SITE_ID = hcas.PARTY_SITE_ID
LEFT JOIN HZ_LOCATIONS hl ON hl.LOCATION_ID = hps.LOCATION_ID
WHERE {where_sql}
GROUP BY
    ooha.ORDER_NUMBER,
    ooha.FLOW_STATUS_CODE,
    ooha.ORDERED_DATE,
    hp.PARTY_NAME,
    ooha.CUST_PO_NUMBER,
    ooha.SHIP_TO_ORG_ID,
    hcsu.LOCATION,
    hl.ADDRESS1,
    hl.CITY,
    hl.STATE,
    hl.POSTAL_CODE
ORDER BY ooha.ORDERED_DATE DESC, ooha.ORDER_NUMBER DESC
FETCH FIRST 200 ROWS ONLY
""".strip()

    return sql, bind_params


def has_explicit_sql_operator_request(user_input):
    text = str(user_input or "").lower()
    return bool(
        re.search(r"\bnot\s+in\b", text)
        or re.search(r"\bin\b", text)
        or re.search(r"\bnot\s+like\b", text)
        or re.search(r"\blike\b", text)
        or re.search(r"\bbetween\b", text)
        or re.search(r"\bwhere\b", text)
        or re.search(r"\bwhose\b", text)
        or re.search(r"(>=|<=|<>|!=|=|>|<)", text)
    )


ORDER_SCHEMA_TABLES = [
    "OE_ORDER_HEADERS_ALL",
    "OE_ORDER_LINES_ALL",
    "HZ_CUST_ACCOUNTS",
    "HZ_PARTIES",
    "RA_TERMS_VL",
    "QP_LIST_HEADERS_VL",
    "MTL_SYSTEM_ITEMS_B",
    "MTL_ONHAND_QUANTITIES",
    "OE_TRANSACTION_TYPES_TL",
]


@lru_cache(maxsize=1)
def get_order_schema_context():
    static_context = {
        "OE_ORDER_HEADERS_ALL": [
            "HEADER_ID", "ORDER_NUMBER", "ORDERED_DATE", "CREATION_DATE", "FLOW_STATUS_CODE",
            "CUST_PO_NUMBER", "SOLD_TO_ORG_ID", "SHIP_TO_ORG_ID", "INVOICE_TO_ORG_ID",
            "TRANSACTIONAL_CURR_CODE", "PAYMENT_TERM_ID", "PRICE_LIST_ID", "ORG_ID"
        ],
        "OE_ORDER_LINES_ALL": [
            "LINE_ID", "HEADER_ID", "LINE_NUMBER", "FLOW_STATUS_CODE", "INVENTORY_ITEM_ID",
            "ORDERED_ITEM", "ORDERED_QUANTITY", "ORDER_QUANTITY_UOM", "UNIT_LIST_PRICE",
            "UNIT_SELLING_PRICE", "SHIP_FROM_ORG_ID", "ORG_ID"
        ],
        "HZ_CUST_ACCOUNTS": ["CUST_ACCOUNT_ID", "PARTY_ID", "ACCOUNT_NUMBER", "STATUS"],
        "HZ_PARTIES": ["PARTY_ID", "PARTY_NAME", "PARTY_NUMBER", "STATUS"],
        "MTL_SYSTEM_ITEMS_B": ["INVENTORY_ITEM_ID", "SEGMENT1", "DESCRIPTION", "ORGANIZATION_ID"],
    }

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                table_in = ",".join(f"'{t}'" for t in ORDER_SCHEMA_TABLES)
                sql = f"""
                    SELECT TABLE_NAME, COLUMN_NAME
                    FROM ALL_TAB_COLUMNS
                    WHERE TABLE_NAME IN ({table_in})
                    ORDER BY TABLE_NAME, COLUMN_ID
                """
                cur.execute(sql)
                rows = cur.fetchall()

        if rows:
            table_map = {}
            for table_name, column_name in rows:
                table_map.setdefault(str(table_name), []).append(str(column_name))
            static_context = table_map
    except Exception:
        pass

    lines = ["Order-domain tables and columns:"]
    for table_name in sorted(static_context.keys()):
        cols = static_context[table_name]
        lines.append(f"- {table_name}: {', '.join(cols[:80])}")
    return "\n".join(lines)


# =========================================================
# AI / Intent / Dynamic SQL
# =========================================================

def ai_extract_intent(history, user_input):
    lower = user_input.lower().strip()

    if lower in ("hi", "hello", "hey", "help", "commands", "?"):
        return {"action": "help"}

    email_match = re.search(
        r"(?:send|email|mail)\s+(?:email\s+)?(?:to\s+)?([\w.+-]+@[\w.-]+\.\w+)",
        user_input,
        re.IGNORECASE,
    )
    if email_match:
        return {"action": "email", "email_address": email_match.group(1)}

    if not get_grok_api_key():
        if any(k in lower for k in ["highly ordered items", "high ordered items", "top ordered items", "most ordered items", "top items", "ordered items from database", "ordered items from data base"]):
            return {"action": "highly_ordered_items"}
        if any(k in lower for k in ["create", "new order", "place order"]):
            return {"action": "create"}
        if any(k in lower for k in ["customer orders", "orders for", "customer details"]):
            return {"action": "get"}
        if any(k in lower for k in ["this month", "this week", "last 30", "booked", "entered", "cancelled"]):
            return {"action": "get_range"}
        if re.search(r"\b\d{4,}\b", lower):
            return {"action": "get"}
        return {"action": "dynamic_query"}

    try:
        history_str = build_history_string(history)

        # Use system prompt from centralized module
        system_prompt = system_prompts.INTENT_EXTRACTION_SYSTEM_PROMPT

        user_prompt = system_prompts.build_intent_user_prompt(history_str, user_input)

        response = grok_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0
        )

        content = response["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()
        intent = json.loads(content)

        if "action" not in intent:
            intent["action"] = "dynamic_query"

        return intent

    except Exception as e:
        print(f"Intent Detection Error: {e}")
        return {"action": "dynamic_query"}


def generate_ai_summary(operation_type, data):
    if not get_grok_api_key():
        return ""

    try:
        data_json = json.dumps(data, indent=2, default=str)[:3000]

        # Use system prompt from centralized module
        system_prompt = system_prompts.get_ai_summary_system_prompt()

        user_prompt = system_prompts.build_summary_user_prompt(operation_type, data_json)

        response = grok_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=300
        )

        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"AI summary error: {e}")
        return ""


def generate_dynamic_sql(history, user_input):
    if not get_grok_api_key():
        return {
            "sql": "",
            "explanation": "Grok (xAI) API key is missing. Update xai_api_key in config.json."
        }

    try:
        history_str = build_history_string(history)

        # Use centralized prompt and harden it with explicit operator handling.
        base_system_prompt = system_prompts.DYNAMIC_SQL_GENERATION_SYSTEM_PROMPT
        schema_context = (
            "STRICT OPERATOR RULES:\n"
            "1) Preserve user operators exactly when present: IN, NOT IN, LIKE, NOT LIKE, BETWEEN, >, <, >=, <=, =, !=, <>.\n"
            "2) Apply filters to the correct column(s) from order tables; do not drop any filter unless impossible.\n"
            "3) If a requested column can exist in multiple tables, use the joined table that semantically matches the request.\n"
            "4) Return only JSON with keys: sql, explanation.\n\n"
            + get_order_schema_context()
        )

        user_prompt = (
            system_prompts.build_sql_generation_user_prompt(history_str, user_input)
            + "\n\n"
            + get_order_schema_context()
        )

        response = grok_chat_completion(
            messages=[
                {"role": "system", "content": base_system_prompt + "\n\n" + schema_context},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0
        )

        content = response["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)

    except Exception as e:
        return {"sql": "", "explanation": f"AI SQL Generation Error: {e}"}


def is_safe_select_query(sql):
    """OWASP LLM-OT-05 / A03-Injection: Validate that the AI-generated SQL is
    a safe SELECT statement.  Uses both a keyword blacklist (to catch obvious
    DML/DDL) and pattern checks for common injection techniques such as
    stacked queries, UNION-based data exfiltration and comment-based bypasses."""
    sql_upper = sql.upper().strip()

    # Must start with SELECT
    if not sql_upper.startswith("SELECT"):
        return False

    # Blacklist dangerous DML/DDL/execution keywords (word-boundary aware)
    dangerous_keywords = [
        r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\bDROP\b",
        r"\bALTER\b", r"\bTRUNCATE\b", r"\bMERGE\b", r"\bCREATE\b",
        r"\bEXEC\b", r"\bEXECUTE\b", r"\bBEGIN\b", r"\bDECLARE\b",
        r"\bGRANT\b", r"\bREVOKE\b", r"\bCOMMIT\b", r"\bROLLBACK\b",
        r"\bXP_\w+",  # MSSQL extended procs
        r"\bUTL_FILE\b", r"\bUTL_HTTP\b", r"\bUTL_TCP\b",  # Oracle UTL
        r"\bDBMS_\w+",  # Oracle DBMS packages
    ]
    for pattern in dangerous_keywords:
        if re.search(pattern, sql_upper):
            return False

    # Block stacked/multi-statement queries
    if re.search(r";\s*\S", sql_upper):
        return False

    # Block comment-based injection attempts
    if re.search(r"(/\*)|(\*/)|(--)|(\\/\\*)", sql_upper):
        return False

    # Block UNION-based exfiltration from non-ERP tables (basic check)
    if re.search(r"\bUNION\b", sql_upper):
        return False

    return True


# =========================================================
# Combined Operations Detection & SQL Generation
# =========================================================

def detect_combined_operations(history, user_input):
    """
    Detect if user request contains combined operations.
    Returns dict with is_combined, operations, and SQL type.
    """
    if not get_grok_api_key():
        # Fallback: simple pattern matching
        lower = user_input.lower()
        combined_patterns = [
            (r"(order|booked|entered|cancelled).*(customer|party|account)", "combined_orders_customers"),
            (r"(order|booked|entered|cancelled).*(inventory|item|onhand)", "combined_orders_inventory"),
            (r"(customer|party|account).*(order|booked)", "combined_customers_orders"),
            (r"(order|sales).*(payment term|price list|salesrep)", "combined_orders_setup"),
            (r"(status|booked|cancelled).*(year|month|date|2024|2023)", "combined_orders_date"),
        ]
        
        for pattern, query_type in combined_patterns:
            if re.search(pattern, lower):
                return {
                    "is_combined": True,
                    "operations": query_type.split("_")[1:],
                    "requires_dynamic_sql": True,
                    "dynamic_sql_type": query_type,
                    "filters": {}
                }
        
        return {
            "is_combined": False,
            "operations": [],
            "requires_dynamic_sql": False,
            "dynamic_sql_type": None,
            "filters": {}
        }

    try:
        history_str = build_history_string(history)
        system_prompt = system_prompts.COMBINED_OPERATIONS_DETECTION_SYSTEM_PROMPT
        user_prompt = system_prompts.build_combined_operations_user_prompt(user_input)

        response = grok_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0
        )

        content = response["choices"][0]["message"]["content"].strip()
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)

    except Exception as e:
        print(f"Combined operations detection error: {e}")
        return {
            "is_combined": False,
            "operations": [],
            "requires_dynamic_sql": False,
            "dynamic_sql_type": None,
            "filters": {}
        }


def generate_combined_sql(query_type, filters):
    """
    Generate SQL for specific combined operation types.
    Uses Oracle Apps standard tables.
    Returns {"sql": str, "params": dict, "explanation": str} or None.

    OWASP LLM-OT-05 / OWASP A03-Injection:
    All user-controlled filter values are passed as Oracle bind parameters
    (:name syntax), never interpolated directly into the SQL string.
    """
    org_id = int(get_org_id())
    filters = filters or {}
    params: dict = {"org_id": org_id}

    if query_type == "combined_orders_customers":
        year = filters.get("year")
        status = str(filters.get("status") or "BOOKED").upper()
        customer_like = str(filters.get("customer_name_like") or filters.get("customer_name") or "").strip()

        params["status_val"] = status

        date_clause = ""
        if year:
            try:
                params["year_val"] = int(year)
                date_clause = "AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = :year_val"
            except (ValueError, TypeError):
                pass

        customer_clause = ""
        if customer_like:
            params["cust_like"] = f"%{customer_like.upper()}%"
            customer_clause = "AND UPPER(hp.PARTY_NAME) LIKE :cust_like"

        sql = f"""
SELECT
    ooha.ORDER_NUMBER,
    ooha.HEADER_ID,
    ooha.FLOW_STATUS_CODE AS ORDER_STATUS,
    ooha.CUST_PO_NUMBER,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
    TO_CHAR(ooha.CREATION_DATE, 'DD-MON-YYYY') AS CREATED_DATE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    hp.PARTY_ID,
    hca.ACCOUNT_NUMBER,
    hca.CUST_ACCOUNT_ID,
    ooha.TRANSACTIONAL_CURR_CODE AS CURRENCY,
    ooha.PAYMENT_TERM_ID,
    ooha.PRICE_LIST_ID,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT
FROM OE_ORDER_HEADERS_ALL ooha
INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
INNER JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
INNER JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
WHERE ooha.ORG_ID = :org_id
AND UPPER(ooha.FLOW_STATUS_CODE) = :status_val
{date_clause}
{customer_clause}
GROUP BY
    ooha.ORDER_NUMBER, ooha.HEADER_ID, ooha.FLOW_STATUS_CODE,
    ooha.CUST_PO_NUMBER, ooha.ORDERED_DATE, ooha.CREATION_DATE,
    hp.PARTY_NAME, hp.PARTY_ID, hca.ACCOUNT_NUMBER, hca.CUST_ACCOUNT_ID,
    ooha.TRANSACTIONAL_CURR_CODE, ooha.PAYMENT_TERM_ID, ooha.PRICE_LIST_ID
ORDER BY ooha.ORDERED_DATE DESC, ooha.ORDER_NUMBER DESC
"""

    elif query_type == "combined_orders_inventory":
        sql = """
SELECT
    ooha.ORDER_NUMBER,
    oola.LINE_NUMBER,
    oola.LINE_ID,
    msi.SEGMENT1 AS ITEM_CODE,
    msi.DESCRIPTION AS ITEM_DESCRIPTION,
    oola.ORDERED_QUANTITY,
    oola.ORDER_QUANTITY_UOM,
    oola.UNIT_SELLING_PRICE,
    (oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS LINE_TOTAL,
    oola.FLOW_STATUS_CODE AS LINE_STATUS,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE
FROM OE_ORDER_HEADERS_ALL ooha
INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
INNER JOIN MTL_SYSTEM_ITEMS_B msi ON msi.INVENTORY_ITEM_ID = oola.INVENTORY_ITEM_ID
WHERE ooha.ORG_ID = :org_id
AND UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'
ORDER BY ooha.ORDERED_DATE DESC, ooha.ORDER_NUMBER, oola.LINE_NUMBER
"""

    elif query_type == "combined_orders_setup":
        sql = """
SELECT
    ooha.ORDER_NUMBER,
    ooha.HEADER_ID,
    ooha.FLOW_STATUS_CODE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    rt.NAME AS PAYMENT_TERM,
    qpl.NAME AS PRICE_LIST_NAME,
    ooha.TRANSACTIONAL_CURR_CODE,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT,
    SUM(oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS ORDER_TOTAL
FROM OE_ORDER_HEADERS_ALL ooha
LEFT JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
LEFT JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
LEFT JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
LEFT JOIN RA_TERMS_VL rt ON rt.TERM_ID = ooha.PAYMENT_TERM_ID
LEFT JOIN QP_LIST_HEADERS_VL qpl ON qpl.LIST_HEADER_ID = ooha.PRICE_LIST_ID
WHERE ooha.ORG_ID = :org_id
GROUP BY
    ooha.ORDER_NUMBER, ooha.HEADER_ID, ooha.FLOW_STATUS_CODE,
    hp.PARTY_NAME, rt.NAME, qpl.NAME, ooha.TRANSACTIONAL_CURR_CODE
ORDER BY ooha.ORDERED_DATE DESC
"""

    elif query_type == "combined_orders_date":
        try:
            params["year_val"] = int(filters.get("year") or 2024)
        except (ValueError, TypeError):
            params["year_val"] = 2024
        params["status_val"] = str(filters.get("status") or "BOOKED").upper()

        sql = """
SELECT
    ooha.ORDER_NUMBER,
    ooha.HEADER_ID,
    ooha.FLOW_STATUS_CODE,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT,
    SUM(oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS ORDER_AMOUNT
FROM OE_ORDER_HEADERS_ALL ooha
INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
LEFT JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
LEFT JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
WHERE ooha.ORG_ID = :org_id
AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = :year_val
AND UPPER(ooha.FLOW_STATUS_CODE) = :status_val
GROUP BY
    ooha.ORDER_NUMBER, ooha.HEADER_ID, ooha.FLOW_STATUS_CODE,
    ooha.ORDERED_DATE, hp.PARTY_NAME
ORDER BY ooha.ORDERED_DATE DESC, ooha.ORDER_NUMBER DESC
"""

    elif query_type == "combined_customers_orders":
        sql = """
SELECT
    hp.PARTY_NAME AS CUSTOMER_NAME,
    hp.PARTY_ID,
    hca.ACCOUNT_NUMBER,
    COUNT(DISTINCT ooha.HEADER_ID) AS TOTAL_ORDERS,
    COUNT(DISTINCT CASE WHEN UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED' THEN ooha.HEADER_ID END) AS BOOKED_ORDERS,
    COUNT(DISTINCT CASE WHEN UPPER(ooha.FLOW_STATUS_CODE) = 'SHIPPED' THEN ooha.HEADER_ID END) AS SHIPPED_ORDERS,
    COUNT(DISTINCT CASE WHEN UPPER(ooha.FLOW_STATUS_CODE) = 'CANCELLED' THEN ooha.HEADER_ID END) AS CANCELLED_ORDERS,
    SUM(oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS TOTAL_ORDER_VALUE
FROM HZ_PARTIES hp
LEFT JOIN HZ_CUST_ACCOUNTS hca ON hca.PARTY_ID = hp.PARTY_ID
LEFT JOIN OE_ORDER_HEADERS_ALL ooha ON ooha.SOLD_TO_ORG_ID = hca.CUST_ACCOUNT_ID
LEFT JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
WHERE (hca.ORG_ID = :org_id OR hca.ORG_ID IS NULL)
AND hp.PARTY_TYPE = 'CUSTOMER'
GROUP BY hp.PARTY_NAME, hp.PARTY_ID, hca.ACCOUNT_NUMBER
ORDER BY TOTAL_ORDER_VALUE DESC NULLS LAST
"""

    else:
        # Default to generic dynamic SQL
        return None

    return {
        "sql": sql.strip(),
        "params": params,
        "explanation": f"Combined query generated for: {query_type.replace('_', ' ')}"
    }



# =========================================================
# ERP Operation Helpers (from app5 flow)
# =========================================================

def get_order(order_number):
    urls = get_service_urls()
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": get_rest_header(),
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_ORDER_NUMBER": int(order_number),
            },
        }
    }

    session = build_session()
    resp = session.post(urls["get_order"], headers={"Content-Type": "application/json", "Accept": "application/json"}, data=json.dumps(payload), timeout=180)
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def get_customer_orders(customer_name):
    urls = get_service_urls()
    session = build_session()
    resp = session.get(
        urls["cust_so_dtls"],
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        params={"P_CUSTOMER_NAME": customer_name},
        timeout=180,
    )
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


def create_order(order_data):
    validated = CreateOrderDraft.model_validate(order_data)
    resolution = resolve_create_order_draft(validated, strict_mode=True)
    validation = validate_create_order_data(validated, resolution)
    if not validation.get("ok"):
        raise ValueError(json.dumps({
            "kind": "validation",
            "errors": validation.get("errors", []),
            "suggestions": validation.get("suggestions", {}),
            "resolved": validation.get("resolved", {}),
        }))
    data = resolution.get("resolved", {})

    if resolution.get("missing"):
        raise ValueError(f"Missing required values: {', '.join(resolution['missing'])}")

    urls = get_service_urls()
    payload = {
        "PROCESS_ORDER_Input": {
            "RESTHeader": get_rest_header(),
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG": "N",
                    "CUST_PO_NUMBER": data.get("cust_po_number", ""),
                    "ORDER_TYPE_ID": int(data.get("order_type_id", get_order_type_id())),
                    "ORG_ID": int(get_org_id()),
                    "PAYMENT_TERM_ID": int(data.get("payment_term_id", get_default_payment_term_id())),
                    "PRICE_LIST_ID": int(data.get("price_list_id", get_default_price_list_id())),
                    "SALESREP_ID": int(data.get("salesrep_id", get_default_salesrep_id())),
                    "SHIP_TO_ORG_ID": int(data.get("ship_to_org_id", get_default_ship_to_org_id())),
                    "SOLD_TO_ORG_ID": int(data.get("sold_to_org_id", get_default_sold_to_org_id())),
                    "TRANSACTIONAL_CURR_CODE": data.get("currency", "USD"),
                    "OPERATION": "CREATE",
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID": int(data.get("inventory_item_id", get_default_inventory_item_id())),
                        "ORDERED_ITEM": data.get("ordered_item", ""),
                        "ORDERED_QUANTITY": float(data.get("ordered_quantity", 1)),
                        "PAYMENT_TERM_ID": int(data.get("payment_term_id", get_default_payment_term_id())),
                        "PRICE_LIST_ID": int(data.get("price_list_id", get_default_price_list_id())),
                        "UNIT_LIST_PRICE": float(data.get("unit_list_price", 0)),
                        "UNIT_SELLING_PRICE": float(data.get("unit_selling_price", 0)),
                        "OPERATION": "CREATE",
                    }
                },
                "P_RTRIM_DATA": "n",
                "P_OPERATING_UNIT": get_operating_unit(),
                "P_DEBUG_LEVEL": 10,
            },
        }
    }

    session = build_session()
    resp = session.post(urls["process_order"], headers={"Content-Type": "application/json", "Accept": "application/json"}, data=json.dumps(payload), timeout=180)
    if resp.status_code in (200, 201, 204):
        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}
    resp.raise_for_status()


@app.route("/api/create-order/draft", methods=["POST"])
def api_create_order_draft():
    started_at = time.time()

    def respond(payload, stage="completed"):
        data = dict(payload or {})
        data["ui_state"] = {
            "stage": stage,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "thinking": "Analyzing create-order values.",
            "fetching": "Resolving missing values from Oracle master data.",
        }
        return jsonify(data)

    body = request.get_json(force=True) or {}
    try:
        if not str(body.get("ordered_item") or "").strip() and not body.get("inventory_item_id"):
            return respond({
                "ok": False,
                "error": "Item name is required to start create-order guidance.",
                "field": "ordered_item",
            }, stage="validation"), 400

        draft = CreateOrderDraft.model_validate(body)
        result = resolve_create_order_draft(draft, strict_mode=True)
        validation = validate_create_order_data(draft, result)
        return respond({"ok": True, **result, "validation": validation}, stage="completed")
    except ValidationError as ve:
        return respond({"ok": False, "error": str(ve)}, stage="validation"), 400
    except Exception as e:
        return respond({"ok": False, "error": str(e)}, stage="failed"), 500


@app.route("/api/create-order/item-resolve", methods=["POST"])
def api_create_order_item_resolve():
    """Resolve create-order item input into a single item or LOV candidates.
    Flow:
    1) Exact item-code match (SEGMENT1)
    2) If no exact match, fallback to first-letter LIKE search
    """
    started_at = time.time()

    def respond(payload, stage="completed"):
        data = dict(payload or {})
        data["ui_state"] = {
            "stage": stage,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "thinking": "Validating item input.",
            "fetching": "Searching Oracle item master.",
        }
        return jsonify(data)

    body = request.get_json(force=True) or {}
    item_name = str(body.get("ordered_item") or "").strip()
    if not item_name:
        return respond({
            "ok": False,
            "message": "Item name is required.",
            "resolution": "missing_input",
            "lov": [],
        }, stage="validation"), 400

    try:
        org_id = int(get_org_id())
        item_upper = item_name.upper()

        exact_sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
            FROM MTL_SYSTEM_ITEMS_B
            WHERE ORGANIZATION_ID = :org_id
            AND UPPER(SEGMENT1) = :item_name
            FETCH FIRST 5 ROWS ONLY
        """
        exact_rows = execute_query(exact_sql, {"org_id": org_id, "item_name": item_upper})

        if len(exact_rows) == 1:
            row = exact_rows[0]
            return respond({
                "ok": True,
                "resolution": "exact_match",
                "item": {
                    "inventory_item_id": int(row["INVENTORY_ITEM_ID"]),
                    "ordered_item": row.get("SEGMENT1") or item_name,
                    "description": row.get("DESCRIPTION") or "",
                },
                "lov": [],
                "message": "Item matched exactly.",
            }, stage="completed")

        if len(exact_rows) > 1:
            lov = [
                {
                    "inventory_item_id": int(r["INVENTORY_ITEM_ID"]),
                    "segment1": r.get("SEGMENT1") or "",
                    "description": r.get("DESCRIPTION") or "",
                }
                for r in exact_rows
            ]
            return respond({
                "ok": True,
                "resolution": "multiple_exact",
                "item": None,
                "lov": lov,
                "message": "Multiple exact item-code matches found. Select one from the LOV.",
            }, stage="completed")

        first_letter = item_upper[0]
        like_sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
            FROM MTL_SYSTEM_ITEMS_B
            WHERE ORGANIZATION_ID = :org_id
            AND UPPER(SEGMENT1) LIKE :first_letter_like
            ORDER BY SEGMENT1
            FETCH FIRST 25 ROWS ONLY
        """
        like_rows = execute_query(
            like_sql,
            {
                "org_id": org_id,
                "first_letter_like": f"{first_letter}%",
            },
        )

        if len(like_rows) == 1:
            row = like_rows[0]
            return respond({
                "ok": True,
                "resolution": "single_like",
                "item": {
                    "inventory_item_id": int(row["INVENTORY_ITEM_ID"]),
                    "ordered_item": row.get("SEGMENT1") or item_name,
                    "description": row.get("DESCRIPTION") or "",
                },
                "lov": [],
                "message": "No exact match. Resolved from first-letter LIKE search.",
            }, stage="completed")

        if like_rows:
            lov = [
                {
                    "inventory_item_id": int(r["INVENTORY_ITEM_ID"]),
                    "segment1": r.get("SEGMENT1") or "",
                    "description": r.get("DESCRIPTION") or "",
                }
                for r in like_rows
            ]
            return respond({
                "ok": True,
                "resolution": "lov_required",
                "item": None,
                "lov": lov,
                "message": (
                    "Item not found exactly. Showing List of Values using first-letter LIKE search."
                ),
            }, stage="completed")

        # Item not found even with first-letter search — return frequently ordered items as fallback LOV
        try:
            fallback_rows = _fetch_quick_item_suggestions("")
        except Exception:
            fallback_rows = []

        fallback_lov = [
            {
                "inventory_item_id": int(r["inventory_item_id"]),
                "segment1": r.get("segment1") or "",
                "description": r.get("description") or "",
            }
            for r in fallback_rows
        ]

        return respond({
            "ok": True,
            "resolution": "no_match",
            "item": None,
            "lov": fallback_lov,
            "message": (
                f"Item '{item_name}' not found in the item master. "
                f"Showing frequently ordered items below — please select the correct one."
            ),
        }, stage="completed")
    except Exception as e:
        return respond({
            "ok": False,
            "resolution": "error",
            "message": str(e),
            "lov": [],
        }, stage="failed"), 500


def add_line_payload(header_id, item_id, ordered_item, qty, price, selling_price, payment_term_id, price_list_id):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": get_rest_header(),
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {"HEADER_ID": int(header_id), "ORG_ID": int(get_org_id()), "OPERATION": "UPDATE"},
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "HEADER_ID": int(header_id),
                        "INVENTORY_ITEM_ID": int(item_id),
                        "ORDERED_ITEM": ordered_item,
                        "ORDERED_QUANTITY": float(qty),
                        "PAYMENT_TERM_ID": int(payment_term_id),
                        "PRICE_LIST_ID": int(price_list_id),
                        "UNIT_LIST_PRICE": float(price),
                        "UNIT_SELLING_PRICE": float(selling_price),
                        "OPERATION": "CREATE",
                    }
                },
                "P_RTRIM_DATA": "n",
                "P_OPERATING_UNIT": get_operating_unit(),
                "P_DEBUG_LEVEL": 10,
            },
        }
    }


def get_orders_advanced(range_type=None, year=None, status=None):
    date_filter_dropped = False
    if year:
        date_clause = f"EXTRACT(YEAR FROM ooha.CREATION_DATE) = {int(year)}"
    elif range_type:
        date_map = {
            "this_month": "TRUNC(SYSDATE, 'MM')",
            "this_week": "TRUNC(SYSDATE, 'IW')",
            "last_30_days": "SYSDATE - 30",
        }
        date_clause = f"ooha.CREATION_DATE >= {date_map.get(range_type, 'SYSDATE - 7')}"
    else:
        date_clause = "1=1"

    bind_vars = {"org": int(get_org_id())}
    matched_on = None

    if status:
        status_upper = status.upper()
        bind_vars["status_val"] = f"%{status_upper}%"

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                header_status_clause = "UPPER(ooha.FLOW_STATUS_CODE) LIKE :status_val"
                sql_count_hdr = (
                    f"SELECT COUNT(DISTINCT ooha.ORDER_NUMBER) "
                    f"FROM OE_ORDER_HEADERS_ALL ooha, OE_ORDER_LINES_ALL oola "
                    f"WHERE ooha.HEADER_ID = oola.HEADER_ID "
                    f"AND {date_clause} AND {header_status_clause} AND ooha.ORG_ID = :org"
                )
                cur.execute(sql_count_hdr, bind_vars)
                hdr_count = cur.fetchone()[0]

                if hdr_count > 0:
                    matched_on = "header_status"
                    status_clause = header_status_clause
                else:
                    line_status_clause = "UPPER(oola.FLOW_STATUS_CODE) LIKE :status_val"
                    sql_count_line = (
                        f"SELECT COUNT(DISTINCT ooha.ORDER_NUMBER) "
                        f"FROM OE_ORDER_HEADERS_ALL ooha, OE_ORDER_LINES_ALL oola "
                        f"WHERE ooha.HEADER_ID = oola.HEADER_ID "
                        f"AND {date_clause} AND {line_status_clause} AND ooha.ORG_ID = :org"
                    )
                    cur.execute(sql_count_line, bind_vars)
                    line_count = cur.fetchone()[0]

                    if line_count > 0:
                        matched_on = "line_status"
                        status_clause = line_status_clause
                    else:
                        sql_count_hdr_nodate = (
                            f"SELECT COUNT(DISTINCT ooha.ORDER_NUMBER) "
                            f"FROM OE_ORDER_HEADERS_ALL ooha, OE_ORDER_LINES_ALL oola "
                            f"WHERE ooha.HEADER_ID = oola.HEADER_ID "
                            f"AND {header_status_clause} AND ooha.ORG_ID = :org"
                        )
                        bind_nodate = {"org": int(get_org_id()), "status_val": f"%{status_upper}%"}
                        cur.execute(sql_count_hdr_nodate, bind_nodate)
                        hdr_nodate = cur.fetchone()[0]

                        if hdr_nodate > 0:
                            matched_on = "header_status"
                            status_clause = header_status_clause
                            date_clause = "1=1"
                            date_filter_dropped = True
                        else:
                            sql_count_line_nodate = (
                                f"SELECT COUNT(DISTINCT ooha.ORDER_NUMBER) "
                                f"FROM OE_ORDER_HEADERS_ALL ooha, OE_ORDER_LINES_ALL oola "
                                f"WHERE ooha.HEADER_ID = oola.HEADER_ID "
                                f"AND {line_status_clause} AND ooha.ORG_ID = :org"
                            )
                            cur.execute(sql_count_line_nodate, bind_nodate)
                            line_nodate = cur.fetchone()[0]

                            if line_nodate > 0:
                                matched_on = "line_status"
                                status_clause = line_status_clause
                                date_clause = "1=1"
                                date_filter_dropped = True
                            else:
                                matched_on = "none"
                                status_clause = "1=0"
    else:
        status_clause = "1=1"

    sql_count = (
        f"SELECT COUNT(DISTINCT ooha.ORDER_NUMBER) "
        f"FROM OE_ORDER_HEADERS_ALL ooha, OE_ORDER_LINES_ALL oola "
        f"WHERE ooha.HEADER_ID = oola.HEADER_ID "
        f"AND {date_clause} AND {status_clause} AND ooha.ORG_ID = :org"
    )
    sql_main = (
        f"SELECT ooha.ORDER_NUMBER, ooha.FLOW_STATUS_CODE AS HEADER_STATUS, "
        f"oola.FLOW_STATUS_CODE AS LINE_STATUS, "
        f"TO_CHAR(ooha.CREATION_DATE, 'DD-MON-YYYY') AS CREATION_DATE "
        f"FROM OE_ORDER_HEADERS_ALL ooha, OE_ORDER_LINES_ALL oola "
        f"WHERE ooha.HEADER_ID = oola.HEADER_ID "
        f"AND {date_clause} AND {status_clause} AND ooha.ORG_ID = :org "
        f"ORDER BY ooha.CREATION_DATE DESC, ooha.ORDER_NUMBER"
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql_count, bind_vars)
            total_count = cur.fetchone()[0]
            cur.execute(sql_main, bind_vars)
            rows = cur.fetchall()

    return {
        "total_count": total_count,
        "matched_on": matched_on,
        "date_filter_dropped": date_filter_dropped,
        "orders": [
            {
                "order_number": int(r[0]),
                "header_status": r[1] or "",
                "line_status": r[2] or "",
                "creation_date": r[3] or "",
            }
            for r in rows[:200]
        ],
    }


def get_highly_ordered_items(year=None, top_n=25):
    """Return top ordered items by total quantity from Oracle order tables."""
    binds = {
        "org_id": int(get_org_id()),
        "top_n": int(top_n),
    }

    year_clause = ""
    if year:
        year_clause = "AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = :year"
        binds["year"] = int(year)

    sql = f"""
        SELECT *
        FROM (
            SELECT
                NVL(msi.SEGMENT1, TO_CHAR(oola.INVENTORY_ITEM_ID)) AS ITEM_CODE,
                NVL(msi.DESCRIPTION, 'N/A') AS ITEM_DESCRIPTION,
                COUNT(*) AS ORDER_LINE_COUNT,
                COUNT(DISTINCT ooha.ORDER_NUMBER) AS ORDER_COUNT,
                ROUND(SUM(NVL(oola.ORDERED_QUANTITY, 0)), 2) AS TOTAL_ORDERED_QTY,
                ROUND(AVG(NVL(oola.ORDERED_QUANTITY, 0)), 2) AS AVG_LINE_QTY,
                ROUND(SUM(NVL(oola.ORDERED_QUANTITY, 0) * NVL(oola.UNIT_SELLING_PRICE, 0)), 2) AS TOTAL_REVENUE
            FROM OE_ORDER_HEADERS_ALL ooha
            JOIN OE_ORDER_LINES_ALL oola ON oola.HEADER_ID = ooha.HEADER_ID
            LEFT JOIN MTL_SYSTEM_ITEMS_B msi
                ON msi.INVENTORY_ITEM_ID = oola.INVENTORY_ITEM_ID
               AND msi.ORGANIZATION_ID = oola.ORG_ID
            WHERE ooha.ORG_ID = :org_id
              AND NVL(oola.ORDERED_QUANTITY, 0) > 0
              {year_clause}
            GROUP BY NVL(msi.SEGMENT1, TO_CHAR(oola.INVENTORY_ITEM_ID)), NVL(msi.DESCRIPTION, 'N/A')
            ORDER BY SUM(NVL(oola.ORDERED_QUANTITY, 0)) DESC
        )
        WHERE ROWNUM <= :top_n
    """

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, binds)
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()

    return {
        "year": int(year) if year else None,
        "top_n": int(top_n),
        "count": len(rows),
        "rows": [dict(zip(cols, row)) for row in rows],
    }


def parse_create_order_response(data):
    try:
        output = data.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {})
        if not output:
            output = data.get("OutputParameters", data)

        header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
        return_status = output.get("X_RETURN_STATUS", output.get("RETURN_STATUS", ""))
        msg_count = output.get("X_MSG_COUNT", output.get("MSG_COUNT", 0))
        msg_data = output.get("X_MSG_DATA", output.get("MSG_DATA", ""))

        order_number = header.get("ORDER_NUMBER", "")
        header_id = header.get("HEADER_ID", "")
        status = header.get("FLOW_STATUS_CODE", "")
        cust_po = header.get("CUST_PO_NUMBER", "")

        return {
            "order_number": order_number,
            "header_id": header_id,
            "return_status": return_status,
            "flow_status": status,
            "cust_po_number": cust_po,
            "msg_count": msg_count,
            "msg_data": msg_data,
            "success": return_status in ("S", "s"),
        }
    except Exception as e:
        return {"error": f"Failed to parse response: {e}", "raw": data}


def parse_customer_orders(data):
    try:
        output = data.get("OutputParameters", data)
        rows_raw = output.get("X_RESULT") or output.get("P_RESULT") or output.get("ResultSet") or output

        if isinstance(rows_raw, dict):
            inner = rows_raw.get("X_RESULT_ITEM") or rows_raw.get("P_RESULT_ITEM") or rows_raw.get("Row") or rows_raw.get("ROW")
            if inner is None:
                rows = [rows_raw]
            elif isinstance(inner, dict):
                rows = [inner]
            else:
                rows = list(inner)
        elif isinstance(rows_raw, list):
            rows = rows_raw
        else:
            rows = []

        return {"rows": rows, "count": len(rows), "raw_keys": list(rows[0].keys()) if rows else []}
    except Exception as e:
        return {"error": f"Failed to parse customer orders: {e}", "raw": data}


def parse_order_response(data):
    try:
        output = data.get("OutputParameters", data)
        header = output.get("X_HEADER_REC", output.get("HEADER_REC", {}))
        header_val = output.get("X_HEADER_VAL_REC", output.get("HEADER_VAL_REC", {}))
        lines_raw = output.get("X_LINE_TBL", output.get("LINE_TBL", {}))
        lines_val_raw = output.get("X_LINE_VAL_TBL", output.get("LINE_VAL_TBL", {}))
        messages = output.get("X_MSG_DATA", output.get("MSG_DATA", ""))

        if isinstance(lines_raw, dict):
            items = lines_raw.get("X_LINE_TBL_ITEM", lines_raw.get("LINE_TBL_ITEM", []))
            if isinstance(items, dict):
                items = [items]
        elif isinstance(lines_raw, list):
            items = lines_raw
        else:
            items = []

        if isinstance(lines_val_raw, dict):
            val_items = lines_val_raw.get("X_LINE_VAL_TBL_ITEM", lines_val_raw.get("LINE_VAL_TBL_ITEM", []))
            if isinstance(val_items, dict):
                val_items = [val_items]
        elif isinstance(lines_val_raw, list):
            val_items = lines_val_raw
        else:
            val_items = []

        lines = []
        for idx, item in enumerate(items):
            val = val_items[idx] if idx < len(val_items) else {}
            lines.append({
                "Line": item.get("LINE_NUMBER", ""),
                "Item": item.get("ORDERED_ITEM", ""),
                "Qty": item.get("ORDERED_QUANTITY", ""),
                "UOM": item.get("ORDER_QUANTITY_UOM", ""),
                "Unit Price": item.get("UNIT_SELLING_PRICE", ""),
                "Status": item.get("FLOW_STATUS_CODE", ""),
                "Ship To": val.get("SHIP_TO_ORG", ""),
                "Ship From": val.get("SHIP_FROM_ORG", ""),
            })

        cname = header_val.get("SOLD_TO_ORG", "") or header.get("SOLD_TO_ORG", header.get("SOLD_TO_ORG_ID", ""))
        header_details = {
            "Order Number": header.get("ORDER_NUMBER", ""),
            "Header ID": header.get("HEADER_ID", ""),
            "Customer PO": header.get("CUST_PO_NUMBER", ""),
            "Flow Status": header.get("FLOW_STATUS_CODE", ""),
            "Ordered Date": header.get("ORDERED_DATE", ""),
            "Currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
            "Customer Name": cname,
            "Ship To": header_val.get("SHIP_TO_ORG", ""),
            "Bill To": header_val.get("INVOICE_TO_ORG", ""),
        }

        return {
            "order_number": header.get("ORDER_NUMBER", ""),
            "status": header.get("FLOW_STATUS_CODE", ""),
            "ordered_date": header.get("ORDERED_DATE", ""),
            "customer_name": cname,
            "currency": header.get("TRANSACTIONAL_CURR_CODE", ""),
            "lines": lines,
            "messages": messages,
            "header_details": header_details,
        }
    except Exception as e:
        return {"error": f"Failed to parse response: {e}", "raw": data}


# =========================================================
# Email Format (same style as app5)
# =========================================================

def _build_email_layout(cname, report_type, ai_summary, table_html, alerts, faqs):
    # OWASP LLM-OT-05 / A03-XSS: All user/AI-controlled strings are HTML-escaped
    # before injection into the email template.
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    cname_s = html_lib.escape(str(cname))
    report_type_s = html_lib.escape(str(report_type))
    ai_summary_s = html_lib.escape(str(ai_summary))

    alerts_html = "<ul style='padding-left: 20px; font-size: 14px; margin-bottom: 0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom: 5px;'>{html_lib.escape(str(k))}: {html_lib.escape(str(v))}</li>"
    alerts_html += "</ul>"

    faqs_html = (
        "<table style='border-collapse: collapse; width: 100%; border: none; font-size: 14px;'>"
        "<tr><th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>Question</th>"
        "<th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>AI Answer</th></tr>"
    )
    for q, a in faqs:
        faqs_html += f"<tr><td style='padding: 8px;'>{html_lib.escape(str(q))}</td><td style='padding: 8px;'>{html_lib.escape(str(a))}</td></tr>"
    faqs_html += "</table>"

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 800px; margin: auto; color: #000; padding: 10px;">

        <h3 style="color: #000; font-size: 16px; margin-top: 0;">Header Details</h3>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 20px;">
            <li style="margin-bottom: 5px;">Customer Name: {cname_s}</li>
            <li style="margin-bottom: 5px;">Contact Name: Account Primary</li>
            <li style="margin-bottom: 5px;">Date of Report: {report_date}</li>
            <li style="margin-bottom: 5px;">Statement Period: {report_type_s}</li>
        </ul>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">

        <h3 style="color: #000; font-size: 16px;">Executive Summary</h3>
        <p>{ai_summary_s}</p>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">

        <h3 style="color: #000; font-size: 16px;">Order Detail Table</h3>
        {table_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">

        <h3 style="color: #000; font-size: 16px;">Exceptions & Alerts</h3>
        {alerts_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">

        <h3 style="color: #000; font-size: 16px;">FAQ'S</h3>
        {faqs_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">

        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 30px;">
            <li style="margin-bottom: 5px;">Support contact: erp.support@centroid.com</li>
            <li style="margin-bottom: 5px;">Disclaimer: This notification was generated automatically from the ERP environment</li>
            <li style="margin-bottom: 5px;">Do-not-reply notice: Please do not reply directly to this email.</li>
        </ul>
    </div>
    """


def _generate_order_email_html(parsed):
    order_num = parsed.get("order_number", "N/A")
    cname = parsed.get("customer_name", "Unknown Customer")
    status = parsed.get("status", "N/A")
    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"

    table = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"

    for ln in parsed.get("lines", []):
        table += "<tr>"
        table += f"<td style='{td}'>{order_num}</td>"
        table += f"<td style='{td}'>{ln.get('Item', 'N/A')}</td>"
        table += f"<td style='{td}'>{ln.get('Qty', 'N/A')}</td>"
        table += f"<td style='{td}'>{ln.get('Status', 'N/A')}</td>"
        table += f"<td style='{td}'>TBD</td>"
        table += f"<td style='{td}'>Pending</td>"
        table += f"<td style='{td}'>N/A</td>"
        table += "</tr>"
    table += "</table>"

    has_holds = status in ("ENTERED",) or "HOLD" in str(status).upper()
    alerts = {
        "Backorders": "None detected for this specific transaction",
        "Holds": "1" if has_holds else "0",
        "Partial Shipments": "N/A",
        "Payment Holds": "Check customer balance",
    }
    faqs = [
        (f"Why is Order {order_num} currently {status}?", f"The order is in {status} status waiting for the next step in the fulfillment cycle."),
        ("Can I expect partial shipment?", "Depends on line-level availability. Check shipping notices for updates."),
    ]
    summary = f"Order #{order_num} for customer {cname} is currently in {status} status."
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", summary, table, alerts, faqs)


def _generate_create_email_html(parsed):
    order_num = parsed.get("order_number", "N/A")
    status = parsed.get("flow_status", "N/A")
    cust_po = parsed.get("cust_po_number", "N/A")
    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"

    table = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Customer PO", "Status", "Return Status"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    table += f"<tr><td style='{td}'>{order_num}</td><td style='{td}'>{cust_po}</td><td style='{td}'>{status}</td><td style='{td}'>{parsed.get('return_status', '')}</td></tr>"
    table += "</table>"

    alerts = {"Backorders": "N/A", "Holds": "0", "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("Was the order booked?", f"Order #{order_num} has status: {status}.")]
    summary = f"New order #{order_num} was created with PO {cust_po}. Current status: {status}."
    return _build_email_layout("N/A", f"New Order Created: #{order_num}", summary, table, alerts, faqs)


def _generate_customer_orders_email_html(parsed):
    cname = parsed.get("customer_name", "Unknown Customer")
    rows = parsed.get("rows", [])
    keys = parsed.get("raw_keys", [])
    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"

    display_keys = keys[:7] if len(keys) > 7 else keys
    table = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in display_keys:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for r in rows:
        table += "<tr>"
        for k in display_keys:
            table += f"<td style='{td}'>{r.get(k, 'N/A')}</td>"
        table += "</tr>"
    table += "</table>"

    alerts = {"Backorders": "0", "Holds": "0", "Partial Shipments": "Check line statuses", "Payment Holds": "0"}
    faqs = [("Are there any delayed orders?", "Check the table for delayed order flags.")]
    summary = f"{len(rows)} order record(s) found for customer {cname}."
    return _build_email_layout(cname, "All Recent Customer Orders", summary, table, alerts, faqs)


def _generate_orders_advanced_email_html(data, range_type=None, year=None, status=None):
    orders = data.get("orders", [])
    total = data.get("total_count", 0)

    label_parts = []
    if range_type:
        label_parts.append(range_type.replace("_", " ").title())
    if year:
        label_parts.append(str(year))
    if status:
        label_parts.append(status)
    filter_label = ", ".join(label_parts) or "All"

    th = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td = "border: none; padding: 8px;"

    table = "<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    for h in ["Order #", "Header Status", "Line Status", "Creation Date"]:
        table += f"<th style='{th}'>{h}</th>"
    table += "</tr>"
    for o in orders:
        table += f"<tr><td style='{td}'>{o.get('order_number', '')}</td>"
        table += f"<td style='{td}'>{o.get('header_status', '')}</td>"
        table += f"<td style='{td}'>{o.get('line_status', '')}</td>"
        table += f"<td style='{td}'>{o.get('creation_date', '')}</td></tr>"
    table += "</table>"

    alerts = {"Total Orders": str(total), "Filter": filter_label}
    faqs = [("What filter was applied?", f"Filter: {filter_label}")]
    summary_text = f"{total} order(s) found with filter: {filter_label}."
    return _build_email_layout("N/A", f"Orders Report: {filter_label}", summary_text, table, alerts, faqs)


def _generate_excel():
    if not OPENPYXL_AVAILABLE:
        return b""

    op_type = _last_operation.get("type")
    parsed = _last_operation.get("data")
    if not op_type or not parsed:
        return b""

    wb = Workbook()
    header_font = Font(bold=True, color="FFFFFF", size=10)
    header_fill = PatternFill(start_color="003366", end_color="003366", fill_type="solid")
    thin_border = Border(left=Side(style="thin"), right=Side(style="thin"), top=Side(style="thin"), bottom=Side(style="thin"))

    def style_header(ws, row_num, col_count):
        for col in range(1, col_count + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = thin_border

    def style_data(ws, start_row, end_row, col_count):
        for row in range(start_row, end_row + 1):
            for col in range(1, col_count + 1):
                cell = ws.cell(row=row, column=col)
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")

    def auto_width(ws):
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_len + 3, 40)

    if op_type == "order":
        ws = wb.active
        ws.title = "Header Details"
        hdr = parsed.get("header_details", {})
        ws.append(["Field", "Value"])
        style_header(ws, 1, 2)
        row_num = 2
        for key, val in hdr.items():
            val_str = str(val) if val not in (None, "", "None") else ""
            if val_str:
                ws.append([key, val_str])
                row_num += 1
        style_data(ws, 2, row_num, 2)
        auto_width(ws)

        lines = parsed.get("lines", [])
        if lines:
            ws2 = wb.create_sheet("Line Details")
            cols = list(lines[0].keys())
            ws2.append(cols)
            style_header(ws2, 1, len(cols))
            for line in lines:
                ws2.append([line.get(c, "") for c in cols])
            style_data(ws2, 2, len(lines) + 1, len(cols))
            auto_width(ws2)

    elif op_type in ("create", "add_line"):
        ws = wb.active
        ws.title = "Order Details"
        ws.append(["Field", "Value"])
        style_header(ws, 1, 2)
        row_num = 2
        for key, val in parsed.items():
            if key == "success":
                continue
            val_str = str(val) if val not in (None, "", "None") else ""
            if val_str:
                ws.append([key, val_str])
                row_num += 1
        style_data(ws, 2, row_num, 2)
        auto_width(ws)

    elif op_type == "customer_orders":
        ws = wb.active
        ws.title = "Customer Orders"
        rows = parsed.get("rows", [])
        keys = parsed.get("raw_keys", [])
        if not keys and rows:
            keys = list(rows[0].keys())
        if keys:
            ws.append(keys)
            style_header(ws, 1, len(keys))
            for row in rows:
                ws.append([row.get(k, "") for k in keys])
            style_data(ws, 2, len(rows) + 1, len(keys))
            auto_width(ws)

    elif op_type == "orders_advanced":
        ws = wb.active
        ws.title = "Orders Report"
        orders = parsed.get("orders", [])
        cols = ["order_number", "header_status", "line_status", "creation_date"]
        ws.append(["Order #", "Header Status", "Line Status", "Creation Date"])
        style_header(ws, 1, len(cols))
        for o in orders:
            ws.append([o.get(c, "") for c in cols])
        style_data(ws, 2, len(orders) + 1, len(cols))
        auto_width(ws)

    elif op_type == "dynamic_table":
        ws = wb.active
        ws.title = "Query Results"
        columns = parsed.get("columns", [])
        rows = parsed.get("rows", [])
        if columns:
            ws.append(columns)
            style_header(ws, 1, len(columns))
            for row in rows:
                ws.append(row)
            style_data(ws, 2, len(rows) + 1, len(columns))
            auto_width(ws)
        else:
            return b""
    else:
        return b""

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _generate_csv():
    import csv as _csv
    op_type = _last_operation.get("type")
    data = _last_operation.get("data")
    if not op_type or not data:
        return b""

    buf = io.StringIO()
    writer = _csv.writer(buf)

    if op_type == "dynamic_table":
        columns = data.get("columns", [])
        rows = data.get("rows", [])
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)

    elif op_type == "order":
        hdr = data.get("header_details", {})
        writer.writerow(["Field", "Value"])
        for k, v in hdr.items():
            writer.writerow([k, v])
        lines = data.get("lines", [])
        if lines:
            writer.writerow([])
            writer.writerow(["--- Lines ---"])
            writer.writerow(list(lines[0].keys()))
            for line in lines:
                writer.writerow(list(line.values()))

    elif op_type == "customer_orders":
        rows = data.get("rows", [])
        if rows:
            keys = data.get("raw_keys") or list(rows[0].keys())
            writer.writerow(keys)
            for row in rows:
                writer.writerow([row.get(k, "") for k in keys])

    elif op_type == "orders_advanced":
        orders = data.get("orders", [])
        cols = ["order_number", "header_status", "line_status", "creation_date"]
        writer.writerow(cols)
        for o in orders:
            writer.writerow([o.get(c, "") for c in cols])

    elif op_type in ("create", "add_line"):
        writer.writerow(["Field", "Value"])
        for k, v in data.items():
            if k != "success":
                writer.writerow([k, v])
    else:
        return b""

    return buf.getvalue().encode("utf-8-sig")  # utf-8-sig for Excel CSV compatibility


def _generate_json_file():
    op_type = _last_operation.get("type")
    data = _last_operation.get("data")
    if not op_type or not data:
        return b""
    try:
        return json.dumps(data, indent=2, default=str).encode("utf-8")
    except Exception:
        return b""


def _generate_dynamic_table_email_html(columns, rows, explanation=""):
    th = "background:#003366;color:#fff;padding:8px;text-align:left;font-size:0.82rem;"
    td = "padding:8px;border-bottom:1px solid #e5e7eb;font-size:0.82rem;"
    table = f"<table style='width:100%;border-collapse:collapse;'><tr>"
    for col in columns:
        table += f"<th style='{th}'>{col}</th>"
    table += "</tr>"
    for row in rows:
        table += "<tr>"
        for cell in row:
            table += f"<td style='{td}'>{cell}</td>"
        table += "</tr>"
    table += "</table>"
    alerts = {"Total Rows": str(len(rows)), "Columns": str(len(columns))}
    summary_text = explanation or f"Dynamic query returned {len(rows)} row(s)."
    faqs = [("How was this generated?", "Dynamic SQL query based on your request.")]
    return _build_email_layout("Dynamic Query", "Query Results", summary_text, table, alerts, faqs)


def _get_filename(ext="xlsx"):
    op = _last_operation.get("type") or "report"
    data = _last_operation.get("data") or {}
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if op == "order":
        return f"Order_{data.get('order_number', 'N-A')}_{ts}.{ext}"
    if op == "customer_orders":
        cname = data.get("customer_name", "unknown").replace(" ", "_")
        return f"CustOrders_{cname}_{ts}.{ext}"
    if op == "create":
        return f"NewOrder_{data.get('order_number', 'N-A')}_{ts}.{ext}"
    if op == "orders_advanced":
        return f"OrdersReport_{ts}.{ext}"
    if op == "dynamic_table":
        return f"QueryResults_{ts}.{ext}"
    return f"ERP_Report_{ts}.{ext}"


# Keep legacy alias for callers that haven't been updated yet
def _get_excel_filename():
    return _get_filename("xlsx")


def send_erp_email(to_email, subject, body_text, html_table, attachment_format="excel"):
    smtp_user = config_manager.get_config_value("smtp_user", "")
    smtp_password = config_manager.get_config_value("smtp_password", "")
    smtp_sender = config_manager.get_config_value("smtp_sender", "erp.assistant@yourdomain.com")

    if not smtp_user or not smtp_password:
        return False, "SMTP credentials are missing. Configure smtp_user and smtp_password in config.json."

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp_sender
    msg["To"] = to_email

    html_content = f"""
    <html>
    <head></head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <p style="color: #333;">{body_text.replace(chr(10), '<br>')}</p>
        <br>
        {html_table}
    </body>
    </html>
    """

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(body_text, "plain"))
    alt_part.attach(MIMEText(html_content, "html"))
    msg.attach(alt_part)

    fmt = (attachment_format or "excel").lower().strip()
    if fmt == "csv":
        file_bytes = _generate_csv()
        fname = _get_filename("csv")
        if file_bytes:
            part = MIMEApplication(file_bytes, _subtype="csv")
            part.add_header("Content-Disposition", "attachment", filename=fname)
            msg.attach(part)
    elif fmt == "json":
        file_bytes = _generate_json_file()
        fname = _get_filename("json")
        if file_bytes:
            part = MIMEApplication(file_bytes, _subtype="json")
            part.add_header("Content-Disposition", "attachment", filename=fname)
            msg.attach(part)
    else:  # default: excel
        file_bytes = _generate_excel()
        if file_bytes:
            fname = _get_filename("xlsx")
            part = MIMEApplication(file_bytes, _subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            part.add_header("Content-Disposition", "attachment", filename=fname)
            msg.attach(part)

    try:
        server = smtplib.SMTP(config_manager.get_config_value("smtp_host", "smtp.gmail.com"), int(config_manager.get_config_value("smtp_port", 587)))
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)


def trigger_auto_email(context):
    if not _auto_email["enabled"] or not _auto_email["to"]:
        return

    html_payload = _last_operation.get("email_html", "")
    if not html_payload:
        return

    to_email = _auto_email["to"]
    subject = f"Automated ERP Update - {context}"
    body_text = (
        "Hi,\n\nPlease find the automated report attached below.\n\n"
        "This email was sent automatically after the operation completed.\n\n"
        "Regards,\nSales Order Assistant"
    )
    threading.Thread(
        target=send_erp_email,
        args=(to_email, subject, body_text, html_payload),
        daemon=True,
    ).start()


def _scheduled_worker(interval_mins, customer_name, to_email):
    _stop_event.clear()
    while not _stop_event.is_set():
        stopped = _stop_event.wait(timeout=interval_mins * 60)
        if stopped:
            break
        try:
            target = customer_name.strip() if customer_name else ""
            if target:
                raw = get_customer_orders(target)
                parsed = parse_customer_orders(raw)
                parsed["customer_name"] = target
                html_payload = _generate_customer_orders_email_html(parsed)
                subject = f"Scheduled Report: {target}"
            else:
                html_payload = _last_operation.get("email_html", "")
                subject = "Scheduled Report: Latest Order Data"

            if html_payload:
                body_text = "Your automated scheduled report is attached below."
                success, msg = send_erp_email(to_email, subject, body_text, html_payload)
                _scheduler["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _scheduler["runs"] += 1
                _scheduler["last_status"] = "sent" if success else f"failed: {msg}"
            else:
                _scheduler["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _scheduler["last_status"] = "skipped: no data"
        except Exception as e:
            _scheduler["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _scheduler["last_status"] = f"error: {e}"


def _start_scheduler(interval_mins, customer_name, to_email):
    global _scheduler_thread
    _stop_scheduler()
    _scheduler["active"] = True
    _scheduler["interval_mins"] = interval_mins
    _scheduler["customer_name"] = customer_name
    _scheduler["to_email"] = to_email
    _scheduler["runs"] = 0
    _scheduler["last_run"] = None
    _scheduler["last_status"] = None
    _scheduler_thread = threading.Thread(
        target=_scheduled_worker,
        args=(interval_mins, customer_name, to_email),
        daemon=True,
    )
    _scheduler_thread.start()


def _stop_scheduler():
    global _scheduler_thread
    _stop_event.set()
    _scheduler["active"] = False
    if _scheduler_thread and _scheduler_thread.is_alive():
        _scheduler_thread.join(timeout=2)
    _scheduler_thread = None
    _stop_event.clear()


def get_all_customer_names():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
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
            cur.execute(sql, {"org_id": int(get_org_id())})
            rows = cur.fetchall()
    return [r[0] for r in rows if r and r[0]]


def _auto_loop_worker(to_email):
    _stop_loop_event.clear()
    _auto_loop["active"] = True
    _auto_loop["to_email"] = to_email
    _auto_loop["started_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    while not _stop_loop_event.is_set():
        try:
            customers = get_all_customer_names()
            _auto_loop["total_customers"] = len(customers)
            _auto_loop["processed"] = 0

            for cust_name in customers:
                if _stop_loop_event.is_set():
                    break

                _auto_loop["current_customer"] = cust_name
                try:
                    raw = get_customer_orders(cust_name)
                    parsed = parse_customer_orders(raw)
                    parsed["customer_name"] = cust_name
                    rows = parsed.get("rows", [])

                    if rows:
                        _last_operation["type"] = "customer_orders"
                        _last_operation["data"] = parsed
                        _last_operation["raw"] = raw
                        html_payload = _generate_customer_orders_email_html(parsed)
                        _last_operation["email_html"] = html_payload
                        subject = f"Sales Order Report: {cust_name}"
                        body_text = f"Automated Sales Order Report for customer: {cust_name}"
                        success, msg = send_erp_email(to_email, subject, body_text, html_payload)
                        _auto_loop["last_status"] = f"OK {cust_name}: {msg}" if success else f"FAIL {cust_name}: {msg}"
                    else:
                        _auto_loop["last_status"] = f"SKIP {cust_name}: No orders"
                except Exception as e:
                    _auto_loop["last_status"] = f"ERR {cust_name}: {e}"

                _auto_loop["processed"] += 1
                if not _stop_loop_event.is_set():
                    _stop_loop_event.wait(timeout=5)

            if not _stop_loop_event.is_set():
                _auto_loop["last_status"] = f"Cycle complete ({len(customers)} customers). Waiting 60s..."
                _stop_loop_event.wait(timeout=60)
        except Exception as e:
            _auto_loop["last_status"] = f"Loop error: {e}"
            if not _stop_loop_event.is_set():
                _stop_loop_event.wait(timeout=30)

    _auto_loop["active"] = False
    _auto_loop["current_customer"] = ""


def _start_auto_loop(to_email):
    global _loop_thread
    _stop_auto_loop()
    _loop_thread = threading.Thread(target=_auto_loop_worker, args=(to_email,), daemon=True)
    _loop_thread.start()


def _stop_auto_loop():
    global _loop_thread
    _stop_loop_event.set()
    _auto_loop["active"] = False
    if _loop_thread and _loop_thread.is_alive():
        _loop_thread.join(timeout=3)
    _loop_thread = None
    _stop_loop_event.clear()


# =========================================================
# Auth Helpers  (OWASP LLM-OT-01 / OWASP A01-Broken Access)
# =========================================================

def require_login(f):
    """Decorator: reject requests that have no authenticated session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "Unauthorized. Please log in."}), 401
        return f(*args, **kwargs)
    return decorated


# =========================================================
# Routes
# =========================================================


def stream_general_chat_response(history, user_msg, started_at):
    def event_stream():
        full_text = ""
        try:
            for chunk in generate_general_chat_response_stream(history, user_msg):
                full_text += chunk
                yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
            payload = {
                "reply": full_text.strip(),
                "type": "text",
                "ui_state": {
                    "stage": "completed",
                    "elapsed_ms": int((time.time() - started_at) * 1000),
                    "thinking": "AI analyzed your request.",
                    "fetching": "Fetched data from Oracle and prepared a response when needed.",
                },
            }
            yield f"data: {json.dumps({'type': 'final', 'data': payload})}\n\n"
        except Exception as exc:
            payload = {"reply": f"AI response error: {exc}", "type": "error"}
            yield f"data: {json.dumps({'type': 'final', 'data': payload})}\n\n"

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.route("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index7.html")


@app.route("/api/login", methods=["POST"])
def login():
    """Login endpoint - validates against EBS ISG REST API credentials (api_user / api_password)."""
    data = request.get_json(force=True) or {}
    username = data.get("username", "").strip()
    password = str(data.get("password", ""))

    # --- EBS ISG REST API credentials (api_user / api_password from config.json) ---
    stored_username = str(config_manager.get_config_value("api_user", "") or "").strip()
    stored_password = str(config_manager.get_config_value("api_password", "") or "")

    # --- Previous login: used dedicated login_username / login_password fields ---
    # stored_username = str(config_manager.get_config_value("login_username", "") or "").strip()
    # stored_password = str(config_manager.get_config_value("login_password", "") or "")

    # Timing-safe comparison (OWASP A02 - prevents timing-based enumeration)
    user_ok = hmac.compare_digest(username.encode(), stored_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), stored_password.encode())

    if user_ok and pass_ok:
        session["authenticated"] = True
        session["user"] = username
        return jsonify({
            "ok": True,
            "message": "Login successful",
            "user": username
        })
    else:
        return jsonify({
            "ok": False,
            "error": "Invalid username or password"
        }), 401


# Sensitive keys never returned in GET response
_SECRET_KEYS = {
    "db_password", "xai_api_key", "grok_api_key",
    "api_password", "smtp_password",
    "login_password",
}


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/config", methods=["GET", "POST"])
@require_login
def route_config_manager():
    if request.method == "POST":
        new_config = request.get_json(force=True) or {}
        # Only allow known non-secret keys to be updated via this endpoint;
        # password/token fields require the user to explicitly provide a
        # non-empty value (empty string = "leave unchanged").
        for key, value in new_config.items():
            if key in _SECRET_KEYS:
                if value and str(value).strip():
                    config_manager.set_config_value(key, value)
            else:
                config_manager.set_config_value(key, value)
        sync_runtime_from_config()
        # Return redacted config (never echo secrets)
        safe = {k: ("***" if k in _SECRET_KEYS else v)
                for k, v in config_manager.load_config().items()}
        return jsonify({"status": "success", "config": safe})

    # GET: return config with secrets redacted
    safe = {k: ("***" if k in _SECRET_KEYS else v)
            for k, v in config_manager.load_config().items()}
    return jsonify(safe)


@app.route("/openapi.yaml", methods=["GET"])
def openapi_spec():
    """Publishes an OpenAPI document using the externally visible tunnel URL."""
    spec_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi_external_rest.yaml")
    with open(spec_path, "r", encoding="utf-8") as spec_file:
        specification = spec_file.read()

    public_url = str(config_manager.get_config_value("ngrok_public_url", "") or "").strip().rstrip("/")
    server_url = public_url or request.url_root.rstrip("/")
    return Response(
        specification.replace("https://YOUR_PUBLIC_HOST", server_url),
        mimetype="application/yaml; charset=utf-8",
    )


@app.route("/api/chat", methods=["POST"])
def chat():
    started_at = time.time()

    def respond(payload, stage="completed"):
        data = dict(payload or {})
        data["ui_state"] = {
            "stage": stage,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "thinking": "AI analyzed your request.",
            "fetching": "Fetched data from Oracle and prepared a response when needed.",
        }
        return jsonify(data)

    try:
        body = request.get_json(force=True)
        user_msg = str(body.get("message", "")).strip()
        history = body.get("history", [])
        stream_requested = bool(body.get("stream", False))

        if not user_msg:
            return respond({"reply": "Please enter a message.", "type": "text"}, stage="validation")

        lower = user_msg.lower().strip()
        if lower in ("hi", "hello", "hey"):
            return respond({
                "reply": "Hello! I'm the Sales Order Assistant. You can get orders, track orders with shipping details, combine multiple filters in dynamic queries, create orders, add line items, and send email reports.",
                "type": "text",
            }, stage="completed")
        if lower in ("help", "?", "commands"):
            return respond({
                "reply": "Try: Get order 67965, Track order 67965 with shipping details, Show highly ordered items, Orders with status BOOKED and customer Vision, Create order, Add line to order 67965, Send email to user@domain.com",
                "type": "text",
            }, stage="completed")

        # Guardrail: make create-order phrases deterministic and avoid AI misclassification.
        force_create = bool(
            re.search(r"\b(create|new|place|book)\b", lower)
            and re.search(r"\border\b", lower)
        )
        force_highly_ordered_items = bool(
            (
                re.search(r"\b(highly|high|hidhly|top|most)\b", lower)
                and re.search(r"\b(ordered|order)\b", lower)
                and re.search(r"\b(item|items)\b", lower)
            )
            or ("ordered items" in lower and ("database" in lower or "data base" in lower))
        )

        intent = ai_extract_intent(history, user_msg)
        if force_create:
            intent["action"] = "create"
        if force_highly_ordered_items:
            intent["action"] = "highly_ordered_items"
        action = intent.get("action", "dynamic_query")
        viz_requested = _is_visualization_requested(user_msg)

        if should_route_to_dynamic_query(action, intent, user_msg):
            action = "dynamic_query"

        txn_viz_payload = _build_transaction_visualization_payload(user_msg)

        if action == "create":
            prefilled = {}
            cpo = intent.get("cust_po_number")
            item_name = intent.get("ordered_item")
            qty = intent.get("ordered_quantity")
            cust_name = intent.get("customer_name")

            if cpo:
                prefilled["cust_po_number"] = str(cpo)

            if qty:
                try:
                    prefilled["ordered_quantity"] = float(qty)
                except (ValueError, TypeError):
                    pass

            if cust_name:
                prefilled["customer_name"] = str(cust_name)

            if item_name:
                prefilled["ordered_item_input"] = str(item_name)
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            sql_exact = """
                                SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
                                FROM MTL_SYSTEM_ITEMS_B
                                WHERE UPPER(SEGMENT1) = :item_name
                                AND ORGANIZATION_ID = :org_id
                                AND ROWNUM = 1
                            """
                            cur.execute(sql_exact, item_name=str(item_name).upper(), org_id=get_org_id())
                            row = cur.fetchone()
                            if row:
                                prefilled["inventory_item_id"] = int(row[0])
                                prefilled["ordered_item"] = row[1]
                                prefilled["item_description"] = row[2] or ""
                                prefilled["item_validated"] = True
                            else:
                                prefilled["item_validated"] = False
                except Exception as e:
                    print(f"Item validation error: {e}")
                    prefilled["item_validated"] = False

            if cust_name:
                try:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            sql_cust = """
                                SELECT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME, hca.ACCOUNT_NUMBER
                                FROM HZ_CUST_ACCOUNTS hca
                                JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
                                WHERE UPPER(hp.PARTY_NAME) LIKE :cust_name
                                AND hca.STATUS = 'A'
                                AND ROWNUM <= 5
                                ORDER BY hp.PARTY_NAME
                            """
                            cur.execute(sql_cust, cust_name=f"%{str(cust_name).upper()}%")
                            cust_rows = cur.fetchall()
                            if cust_rows and len(cust_rows) == 1:
                                prefilled["cust_account_id"] = int(cust_rows[0][0])
                                prefilled["customer_name_validated"] = cust_rows[0][1]
                                prefilled["customer_validated"] = True
                            else:
                                prefilled["customer_validated"] = False
                except Exception as e:
                    print(f"Customer validation error: {e}")
                    prefilled["customer_validated"] = False

            try:
                draft = CreateOrderDraft.model_validate(
                    {
                        "cust_po_number": prefilled.get("cust_po_number"),
                        "ordered_item": prefilled.get("ordered_item_input") or prefilled.get("ordered_item"),
                        "ordered_quantity": prefilled.get("ordered_quantity"),
                        "customer_name": prefilled.get("customer_name"),
                        "inventory_item_id": prefilled.get("inventory_item_id"),
                        "sold_to_org_id": prefilled.get("cust_account_id"),
                    }
                )
                resolved_result = resolve_create_order_draft(draft, strict_mode=True)
                validation = validate_create_order_data(draft, resolved_result)
                prefilled["validation_errors"] = validation.get("errors", [])
                prefilled["suggestions"] = validation.get("suggestions", {})
                prefilled["resolved"] = validation.get("resolved", {})
            except Exception:
                pass

            return respond(
                {
                    "reply": "create_form",
                    "type": "create_form",
                    "visualization": txn_viz_payload,
                    "prefilled": prefilled,
                    "ui_meta": {
                        "wizard_name": "guided_create_order",
                        "steps": [
                            "Resolve Item",
                            "Confirm Quantity",
                            "Resolve Customer and Site",
                            "Resolve Price",
                            "Resolve Payment and Sales Rep",
                            "Submit Order",
                        ],
                        "required_fields": [
                            "inventory_item_id",
                            "ordered_quantity",
                            "sold_to_org_id",
                            "ship_to_org_id",
                            "price_list_id",
                            "payment_term_id",
                            "salesrep_id",
                        ],
                    },
                },
                stage="completed",
            )

        if action == "add_line":
            order_num = intent.get("order_number")
            return respond(
                {
                    "reply": {"order_number": order_num or "", "header_id": ""},
                    "type": "add_line_form",
                    "visualization": txn_viz_payload,
                },
                stage="completed",
            )

        if action == "email":
            return respond(
                {
                    "reply": {"to_email": intent.get("email_address", ""), "has_data": _last_operation["type"] is not None},
                    "type": "email_form",
                    "visualization": txn_viz_payload,
                },
                stage="completed",
            )

        if action == "highly_ordered_items":
            year = intent.get("year")
            top_n = intent.get("top_n") or 25
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", lower)
            if year is None and year_match:
                year = int(year_match.group(1))
            top_match = re.search(r"\btop\s+(\d{1,3})\b", lower)
            if top_match:
                top_n = int(top_match.group(1))
            top_n = max(1, min(int(top_n), 200))
            data = get_highly_ordered_items(year=year, top_n=top_n)

            if not data.get("rows"):
                return respond({"reply": "No highly ordered items found for the selected criteria.", "type": "text"}, stage="completed")

            cols = [
                "ITEM_CODE",
                "ITEM_DESCRIPTION",
                "ORDER_LINE_COUNT",
                "ORDER_COUNT",
                "TOTAL_ORDERED_QTY",
                "AVG_LINE_QTY",
                "TOTAL_REVENUE",
            ]
            rows = [[str(r.get(c, "")) for c in cols] for r in data.get("rows", [])]
            label = f"Top {top_n} highly ordered items" + (f" for {year}" if year else "")

            _last_operation["type"] = "dynamic_table"
            _last_operation["data"] = {"columns": cols, "rows": rows, "sql": "Built-in highly ordered items query"}
            _last_operation["raw"] = data
            _last_operation["email_html"] = _generate_dynamic_table_email_html(cols, rows, label)

            summary = generate_ai_summary("highly_ordered_items", data)
            _last_operation["ai_summary"] = summary
            trigger_auto_email(label)
            viz_payload = _build_visualization_payload(user_msg, cols, rows)

            return respond(
                {
                    "type": "dynamic_table",
                    "columns": cols,
                    "rows": rows,
                    "ai_summary": summary,
                    "visualization": viz_payload,
                },
                stage="completed",
            )

        if action == "get_range":
            range_type = intent.get("date_range")
            year = intent.get("year")
            status = intent.get("status")
            data = get_orders_advanced(range_type=range_type, year=year, status=status)
            _last_operation["type"] = "orders_advanced"
            _last_operation["data"] = data
            _last_operation["raw"] = data
            label_parts = []
            if range_type:
                label_parts.append(range_type.replace("_", " "))
            if year:
                label_parts.append(str(year))
            if status:
                label_parts.append(status)
            label = ", ".join(label_parts) or "all"
            matched_on = data.get("matched_on")
            date_filter_dropped = data.get("date_filter_dropped", False)
            if matched_on and status:
                if matched_on == "header_status":
                    label += " (matched on Header Status)"
                elif matched_on == "line_status":
                    label += " (matched on Line Status)"
                elif matched_on == "none":
                    label += " (no match in Header or Line Status)"
            if date_filter_dropped:
                label += " - No orders for requested date range, showing all dates"
            _last_operation["email_html"] = _generate_orders_advanced_email_html(data, range_type, year, status)
            summary = generate_ai_summary("orders_advanced", data)
            _last_operation["ai_summary"] = summary
            trigger_auto_email(f"Orders advanced: {label}")
            oa_rows_raw = data.get("orders") or []
            oa_columns = list(oa_rows_raw[0].keys()) if oa_rows_raw else []
            oa_rows = [[str(r.get(col, "")) for col in oa_columns] for r in oa_rows_raw]
            viz_payload = _build_visualization_payload(user_msg, oa_columns, oa_rows)
            return respond(
                {
                    "reply": data,
                    "type": "orders_advanced",
                    "ai_summary": summary,
                    "filter_label": label,
                    "matched_on": matched_on,
                    "visualization": viz_payload,
                },
                stage="completed",
            )

        if action == "get":
            customer_name = intent.get("customer_name")
            order_number = intent.get("order_number")

            if customer_name and not order_number:
                raw = get_customer_orders(customer_name)
                parsed = parse_customer_orders(raw)
                parsed["customer_name"] = customer_name
                _last_operation["type"] = "customer_orders"
                _last_operation["data"] = parsed
                _last_operation["raw"] = raw
                _last_operation["email_html"] = _generate_customer_orders_email_html(parsed)
                trigger_auto_email(f"Customer: {customer_name}")
                summary = generate_ai_summary("customer_orders", parsed)
                _last_operation["ai_summary"] = summary
                co_rows_raw = parsed.get("rows") or []
                if co_rows_raw and isinstance(co_rows_raw[0], dict):
                    co_columns = list(co_rows_raw[0].keys())
                    co_rows = [[str(r.get(col, "")) for col in co_columns] for r in co_rows_raw]
                else:
                    co_columns, co_rows = [], []
                viz_payload = _build_visualization_payload(user_msg, co_columns, co_rows)
                return respond(
                    {
                        "reply": parsed,
                        "type": "customer_orders",
                        "ai_summary": summary,
                        "visualization": viz_payload,
                    },
                    stage="completed",
                )

            if order_number:
                raw = get_order(int(order_number))
                parsed = parse_order_response(raw)
                _last_operation["type"] = "order"
                _last_operation["data"] = parsed
                _last_operation["raw"] = raw
                _last_operation["email_html"] = _generate_order_email_html(parsed)
                trigger_auto_email(f"Order #{order_number}")
                summary = generate_ai_summary("order", parsed)
                _last_operation["ai_summary"] = summary
                order_lines = parsed.get("lines") or []
                if order_lines and isinstance(order_lines[0], dict):
                    ol_columns = list(order_lines[0].keys())
                    ol_rows = [[str(r.get(col, "")) for col in ol_columns] for r in order_lines]
                else:
                    ol_columns, ol_rows = [], []
                viz_payload = _build_visualization_payload(user_msg, ol_columns, ol_rows)
                return respond(
                    {
                        "reply": parsed,
                        "type": "order",
                        "ai_summary": summary,
                        "visualization": viz_payload,
                    },
                    stage="completed",
                )

        if action == "general":
            answer = intent.get("general_answer", "")
            if answer:
                return respond({"reply": answer, "type": "text"}, stage="completed")
            if stream_requested:
                return stream_general_chat_response(history, user_msg, started_at)
            answer = generate_general_chat_response(history, user_msg)
            return respond({"reply": answer, "type": "text"}, stage="completed")

        # If intent model falls back to dynamic SQL for non-ERP prompts,
        # treat it as normal conversational AI chat.
        if action == "dynamic_query" and not is_erp_or_data_query(user_msg):
            if stream_requested:
                return stream_general_chat_response(history, user_msg, started_at)
            answer = generate_general_chat_response(history, user_msg)
            return respond({"reply": answer, "type": "text"}, stage="completed")

        # Deterministic tracking/report query path for multi-column order filters.
        tracking_filters = _extract_order_tracking_filters(user_msg)
        if _should_use_order_tracking_query(user_msg, tracking_filters):
            tracking_sql, tracking_binds = _build_order_tracking_query(tracking_filters)
            try:
                tracking_results = execute_query(tracking_sql, tracking_binds)
            except Exception as db_exc:
                return respond({
                    "reply": f"Tracking query execution error: {db_exc}",
                    "type": "error",
                }, stage="failed")

            if tracking_results:
                columns = list(tracking_results[0].keys())
                rows = [[str(row.get(col, "")) for col in columns] for row in tracking_results]
                explanation = "Order tracking details generated using combined filters (order/status/customer/item/PO/shipping/date)."
                _last_operation["type"] = "dynamic_table"
                _last_operation["data"] = {"columns": columns, "rows": rows, "sql": tracking_sql}
                _last_operation["raw"] = tracking_results
                _last_operation["email_html"] = _generate_dynamic_table_email_html(columns, rows, explanation)
                trigger_auto_email("Order tracking query")
                viz_payload = _build_visualization_payload(user_msg, columns, rows)
                return respond({
                    "type": "dynamic_table",
                    "columns": columns,
                    "rows": rows,
                    "query_mode": "tracking",
                    "visualization": viz_payload,
                }, stage="completed")

        # Check for combined operations (2 or more conditions/operations)
        combined_ops = detect_combined_operations(history, user_msg)
        if (
            not has_explicit_sql_operator_request(user_msg)
            and combined_ops.get("requires_dynamic_sql")
            and combined_ops.get("dynamic_sql_type")
        ):
            print(f"[Combined Operations Detected] Type: {combined_ops.get('dynamic_sql_type')}")
            merged_filters = dict(combined_ops.get("filters", {}) or {})
            merged_filters.update(extract_dynamic_filters_from_text(user_msg))
            
            # Generate SQL for combined operations
            combined_result = generate_combined_sql(
                combined_ops.get("dynamic_sql_type"),
                merged_filters
            )
            
            if combined_result and combined_result.get("sql"):
                sql_query = combined_result.get("sql", "").strip()
                sql_params = combined_result.get("params", {})
                # Oracle execute() should not receive SQL statement terminators.
                sql_query = re.sub(r"[;\s/]+$", "", sql_query).strip()
                explanation = combined_result.get("explanation", "Combined query executed successfully.")

                if is_safe_select_query(sql_query):
                    try:
                        results = execute_query(sql_query, sql_params)
                        if results:
                            columns = list(results[0].keys())
                            rows = [[str(row.get(col, "")) for col in columns] for row in results]
                            _last_operation["type"] = "dynamic_table"
                            _last_operation["data"] = {"columns": columns, "rows": rows, "sql": sql_query}
                            _last_operation["raw"] = results
                            _last_operation["email_html"] = _generate_dynamic_table_email_html(columns, rows, explanation)
                            trigger_auto_email("Dynamic combined query")
                            viz_payload = _build_visualization_payload(user_msg, columns, rows)
                            return respond({
                                "type": "dynamic_table",
                                "columns": columns,
                                "rows": rows,
                                "is_combined_operation": True,
                                "visualization": viz_payload,
                            }, stage="completed")
                        else:
                            if viz_requested:
                                return respond(
                                    {
                                        "reply": "Visualization cannot be generated because the operation returned no rows.",
                                        "type": "text",
                                    },
                                    stage="completed",
                                )
                            return respond({"reply": "No records found for the combined query.", "type": "text"}, stage="completed")
                    except Exception as db_exc:
                        return respond({
                            "reply": f"SQL execution error: {db_exc}",
                            "type": "error",
                        }, stage="failed")
                else:
                    return respond({"reply": "Security Error: Only safe SELECT queries are allowed.", "type": "error"}, stage="failed")

        # Dynamic Query fallback (single operation or AI-generated)
        ai_result = generate_dynamic_sql(history, user_msg)
        sql_query = ai_result.get("sql", "").strip()
        # Oracle execute() should not receive SQL statement terminators.
        sql_query = re.sub(r"[;\s/]+$", "", sql_query).strip()
        explanation = ai_result.get("explanation", "Query executed successfully.")

        if not sql_query:
            return respond({"reply": explanation, "type": "error"}, stage="failed")

        if not is_safe_select_query(sql_query):
            return respond({"reply": "Security Error: Only safe SELECT queries are allowed.", "type": "error"}, stage="failed")

        try:
            results = execute_query(sql_query)
        except Exception as db_exc:
            return respond({
                "reply": f"SQL execution error: {db_exc}",
                "type": "error",
            }, stage="failed")
        if not results:
            if viz_requested:
                return respond(
                    {
                        "reply": "Visualization cannot be generated because the operation returned no rows.",
                        "type": "text",
                    },
                    stage="completed",
                )
            return respond({"reply": "No records found.", "type": "text"}, stage="completed")

        columns = list(results[0].keys())
        rows = [[str(row.get(col, "")) for col in columns] for row in results]
        _last_operation["type"] = "dynamic_table"
        _last_operation["data"] = {"columns": columns, "rows": rows, "sql": sql_query}
        _last_operation["raw"] = results
        _last_operation["email_html"] = _generate_dynamic_table_email_html(columns, rows, explanation)
        trigger_auto_email("Dynamic SQL query")
        viz_payload = _build_visualization_payload(user_msg, columns, rows)
        return respond({
            "type": "dynamic_table",
            "columns": columns,
            "rows": rows,
            "visualization": viz_payload,
        }, stage="completed")

    except requests.exceptions.ConnectionError:
        return respond({"reply": "Could not connect to Oracle EBS server. Check network/VPN.", "type": "error"}, stage="failed")
    except Exception as e:
        return respond({"reply": f"Unexpected Error: {e}", "type": "error"}, stage="failed")


# =========================================================
# Lookup APIs (create wizard compatibility)
# =========================================================

@app.route("/api/orders/<int:order_number>", methods=["GET"])
def api_get_order(order_number):
    """Return a single sales order for external tool integrations."""
    try:
        return jsonify({"type": "order", "reply": parse_order_response(get_order(order_number))})
    except requests.exceptions.HTTPError as exc:
        return jsonify({"type": "error", "reply": f"REST API error: {exc}"}), 502
    except requests.exceptions.ConnectionError:
        return jsonify({"type": "error", "reply": "Could not connect to Oracle EBS server."}), 502
    except Exception as exc:
        return jsonify({"type": "error", "reply": f"Error retrieving order: {exc}"}), 500


@app.route("/api/customer-orders", methods=["GET"])
def api_get_customer_orders():
    """Return prior sales orders for a named customer."""
    customer_name = request.args.get("customer_name", "").strip()
    if not customer_name:
        return jsonify({"type": "error", "reply": "customer_name is required."}), 400
    try:
        result = parse_customer_orders(get_customer_orders(customer_name))
        result["customer_name"] = customer_name
        return jsonify({"type": "customer_orders", "reply": result})
    except requests.exceptions.HTTPError as exc:
        return jsonify({"type": "error", "reply": f"REST API error: {exc}"}), 502
    except requests.exceptions.ConnectionError:
        return jsonify({"type": "error", "reply": "Could not connect to Oracle EBS server."}), 502
    except Exception as exc:
        return jsonify({"type": "error", "reply": f"Error retrieving customer orders: {exc}"}), 500


@app.route("/api/lookup-items", methods=["GET"])
def api_lookup_items():
    search = request.args.get("search", "").strip()
    offset = int(request.args.get("offset", 0))
    if not search:
        return jsonify({"items": [], "has_more": False})
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT * FROM (
                        SELECT a.*, ROWNUM rnum FROM (
                            SELECT DISTINCT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
                            FROM MTL_SYSTEM_ITEMS_B
                            WHERE SEGMENT1 LIKE :ordered_item AND ORGANIZATION_ID = :org_id
                            ORDER BY INVENTORY_ITEM_ID
                        ) a WHERE ROWNUM <= :upper_bound
                    ) WHERE rnum > :offset
                """
                cur.execute(sql, ordered_item=f"{search.upper()}%", org_id=get_org_id(), upper_bound=offset + get_max_choices(), offset=offset)
                rows = cur.fetchall()
        items = [{"inventory_item_id": int(r[0]), "segment1": r[1], "description": r[2] or ""} for r in rows]
        return jsonify({"items": items, "has_more": len(items) == get_max_choices()})
    except Exception as e:
        return jsonify({"items": [], "has_more": False, "error": str(e)})


@app.route("/api/lookup-customers", methods=["GET"])
def api_lookup_customers():
    search = request.args.get("search", "").strip()
    item_id = request.args.get("item_id", "").strip()
    offset = int(request.args.get("offset", 0))

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                if search:
                    sql = """
                        SELECT * FROM (
                            SELECT a.*, ROWNUM rnum FROM (
                                SELECT DISTINCT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME AS customer_name, hca.ACCOUNT_NUMBER
                                FROM HZ_CUST_ACCOUNTS hca
                                JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
                                WHERE UPPER(hp.PARTY_NAME) LIKE :cust_name AND hca.STATUS = 'A'
                                ORDER BY hp.PARTY_NAME
                            ) a WHERE ROWNUM <= :upper_bound
                        ) WHERE rnum > :offset
                    """
                    cur.execute(sql, cust_name=f"%{search.upper()}%", upper_bound=offset + get_max_choices(), offset=offset)
                elif item_id:
                    sql = """
                        SELECT * FROM (
                            SELECT a.*, ROWNUM rnum FROM (
                                SELECT DISTINCT hca.CUST_ACCOUNT_ID, hp.PARTY_NAME AS customer_name, hca.ACCOUNT_NUMBER
                                FROM OE_ORDER_LINES_ALL ool
                                JOIN OE_ORDER_HEADERS_ALL ooh ON ooh.HEADER_ID = ool.HEADER_ID
                                JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooh.SOLD_TO_ORG_ID
                                JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
                                WHERE ool.INVENTORY_ITEM_ID = :item_id AND ool.ORG_ID = :org_id AND hca.STATUS = 'A'
                                ORDER BY hp.PARTY_NAME
                            ) a WHERE ROWNUM <= :upper_bound
                        ) WHERE rnum > :offset
                    """
                    cur.execute(sql, item_id=int(item_id), org_id=get_org_id(), upper_bound=offset + get_max_choices(), offset=offset)
                else:
                    return jsonify({"customers": [], "has_more": False})

                rows = cur.fetchall()

        customers = [{"cust_account_id": int(r[0]), "customer_name": r[1] or "", "account_number": r[2] or ""} for r in rows]
        return jsonify({"customers": customers, "has_more": len(customers) == get_max_choices()})
    except Exception as e:
        return jsonify({"customers": [], "has_more": False, "error": str(e)})


@app.route("/api/lookup-customer-sites", methods=["GET"])
def api_lookup_customer_sites():
    cust_account_id = request.args.get("cust_account_id", "").strip()
    if not cust_account_id:
        return jsonify({"sites": []})

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT hcsu.SITE_USE_ID, hcsu.LOCATION,
                           hl.ADDRESS1, hl.CITY, hl.STATE, hl.POSTAL_CODE,
                           hca.CUST_ACCOUNT_ID, hp.PARTY_NAME
                    FROM HZ_CUST_ACCT_SITES_ALL hcas
                    JOIN HZ_CUST_SITE_USES_ALL hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
                    JOIN HZ_PARTY_SITES hps ON hps.PARTY_SITE_ID = hcas.PARTY_SITE_ID
                    JOIN HZ_LOCATIONS hl ON hl.LOCATION_ID = hps.LOCATION_ID
                    JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = hcas.CUST_ACCOUNT_ID
                    JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
                    WHERE hcas.CUST_ACCOUNT_ID = :cust_account_id
                    AND hcas.ORG_ID = :org_id
                    AND hcsu.SITE_USE_CODE = 'SHIP_TO'
                    AND hcsu.STATUS = 'A'
                    ORDER BY hcsu.SITE_USE_ID
                """
                cur.execute(sql, cust_account_id=int(cust_account_id), org_id=get_org_id())
                rows = cur.fetchall()

        sites = [{
            "ship_to_org_id": int(r[0]),
            "location": r[1] or "",
            "address": f"{r[2] or ''}, {r[3] or ''}, {r[4] or ''} {r[5] or ''}".strip(", "),
            "sold_to_org_id": int(r[6]),
            "customer_name": r[7] or "",
        } for r in rows]
        return jsonify({"sites": sites})
    except Exception as e:
        return jsonify({"sites": [], "error": str(e)})


@app.route("/api/lookup-prices", methods=["GET"])
def api_lookup_prices():
    item_id = request.args.get("item_id", "").strip()
    offset = int(request.args.get("offset", 0))
    if not item_id:
        return jsonify({"prices": [], "has_more": False})

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                sql = """
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
                cur.execute(sql, item_id_str=str(item_id), upper_bound=offset + get_max_choices(), offset=offset)
                rows = cur.fetchall()

        prices = [{"price_list_id": int(r[0]), "price_list_name": r[1] or "", "unit_list_price": float(r[2])} for r in rows]
        return jsonify({"prices": prices, "has_more": len(prices) == get_max_choices()})
    except Exception as e:
        return jsonify({"prices": [], "has_more": False, "error": str(e)})


@app.route("/api/lookup-payment-terms", methods=["GET"])
def api_lookup_payment_terms():
    offset = int(request.args.get("offset", 0))
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
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
                cur.execute(sql, upper_bound=offset + get_max_choices(), offset=offset)
                rows = cur.fetchall()

        terms = [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]
        return jsonify({"terms": terms, "has_more": len(terms) == get_max_choices()})
    except Exception as e:
        return jsonify({"terms": [], "has_more": False, "error": str(e)})


@app.route("/api/lookup-salesreps", methods=["GET"])
def api_lookup_salesreps():
    offset = int(request.args.get("offset", 0))
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT * FROM (
                        SELECT a.*, ROWNUM rnum FROM (
                            SELECT DISTINCT jrs.SALESREP_ID, jrs.NAME AS salesrep_name
                            FROM JTF_RS_SALESREPS jrs
                            WHERE jrs.ORG_ID = :org_id AND jrs.STATUS = 'A' AND jrs.END_DATE_ACTIVE IS NULL
                            ORDER BY jrs.SALESREP_ID
                        ) a WHERE ROWNUM <= :upper_bound
                    ) WHERE rnum > :offset
                """
                cur.execute(sql, org_id=get_org_id(), upper_bound=offset + get_max_choices(), offset=offset)
                rows = cur.fetchall()

        reps = [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]
        return jsonify({"reps": reps, "has_more": len(reps) == get_max_choices()})
    except Exception as e:
        return jsonify({"reps": [], "has_more": False, "error": str(e)})


# =========================================================
# Operation Endpoints
# =========================================================

@app.route("/api/create-order", methods=["POST"])
def api_create_order():
    started_at = time.time()

    def respond(payload, stage="completed"):
        data = dict(payload or {})
        data["ui_state"] = {
            "stage": stage,
            "elapsed_ms": int((time.time() - started_at) * 1000),
            "thinking": "Preparing create-order payload.",
            "fetching": "Submitting order to Oracle ERP.",
        }
        return jsonify(data)

    body = request.get_json(force=True)
    viz_requested = bool(body.get("_visualization_requested", False))
    viz_payload = {
        "requested": viz_requested,
        "available": False,
        "reason": (
            "Visualization is not available for this operation because it performs a transactional action "
            "and does not return report-style numeric result data."
        ) if viz_requested else "",
        "chart_config": None,
    }
    try:
        raw = create_order(body)
        parsed = parse_create_order_response(raw)
        _last_operation["type"] = "create"
        _last_operation["data"] = parsed
        _last_operation["raw"] = raw
        _last_operation["email_html"] = _generate_create_email_html(parsed)
        trigger_auto_email(f"New Order #{parsed.get('order_number', '')}")
        summary = generate_ai_summary("create", parsed)
        _last_operation["ai_summary"] = summary
        return respond({"reply": parsed, "type": "create_result", "ai_summary": summary, "visualization": viz_payload}, stage="completed")
    except ValueError as e:
        err_text = str(e or "")
        try:
            payload = json.loads(err_text)
        except Exception:
            payload = None

        if isinstance(payload, dict) and payload.get("kind") == "validation":
            return respond(
                {
                    "type": "create_validation_error",
                    "visualization": viz_payload,
                    "reply": {
                        "message": "Some values are invalid. Please fix the highlighted fields.",
                        "errors": payload.get("errors", []),
                        "suggestions": payload.get("suggestions", {}),
                        "resolved": payload.get("resolved", {}),
                    },
                }
            , stage="validation")
        return respond({"reply": f"Validation error: {err_text}", "type": "error"}, stage="validation")
    except requests.exceptions.HTTPError as e:
        return respond({"reply": f"REST API error: {e}", "type": "error"}, stage="failed")
    except requests.exceptions.ConnectionError:
        return respond({"reply": "Could not connect to Oracle EBS server.", "type": "error"}, stage="failed")
    except Exception as e:
        return respond({"reply": f"Something went wrong: {e}", "type": "error"}, stage="failed")


@app.route("/api/orders-advanced", methods=["GET"])
def api_orders_advanced():
    range_type = request.args.get("range_type", "").strip() or None
    year = request.args.get("year", "").strip() or None
    status = request.args.get("status", "").strip() or None
    if year:
        year = int(year)
    try:
        data = get_orders_advanced(range_type=range_type, year=year, status=status)
        _last_operation["type"] = "orders_advanced"
        _last_operation["data"] = data
        _last_operation["raw"] = data
        _last_operation["email_html"] = _generate_orders_advanced_email_html(data, range_type, year, status)
        summary = generate_ai_summary("orders_advanced", data)
        _last_operation["ai_summary"] = summary
        trigger_auto_email("Orders advanced report")
        return jsonify({"reply": data, "type": "orders_advanced", "ai_summary": summary})
    except Exception as e:
        return jsonify({"reply": f"Error querying orders: {e}", "type": "error"})


@app.route("/api/add-line", methods=["POST"])
def api_add_line():
    body = request.get_json(force=True)
    viz_requested = bool(body.get("_visualization_requested", False))
    viz_payload = {
        "requested": viz_requested,
        "available": False,
        "reason": (
            "Visualization is not available for this operation because it performs a transactional action "
            "and does not return report-style numeric result data."
        ) if viz_requested else "",
        "chart_config": None,
    }
    header_id = body.get("header_id")
    if not header_id:
        return jsonify({"reply": "header_id is required.", "type": "error"})

    try:
        payload = add_line_payload(
            header_id=header_id,
            item_id=body.get("inventory_item_id"),
            ordered_item=body.get("ordered_item", ""),
            qty=body.get("ordered_quantity", 1),
            price=body.get("unit_list_price", 0),
            selling_price=body.get("unit_selling_price", 0),
            payment_term_id=body.get("payment_term_id", get_default_payment_term_id()),
            price_list_id=body.get("price_list_id", get_default_price_list_id()),
        )
        urls = get_service_urls()
        session = build_session()
        resp = session.post(urls["process_order"], headers={"Content-Type": "application/json", "Accept": "application/json"}, data=json.dumps(payload), timeout=180)

        if resp.status_code in (200, 201, 204):
            try:
                raw = resp.json()
            except Exception:
                raw = {"raw": resp.text}
        else:
            resp.raise_for_status()

        parsed = parse_create_order_response(raw)
        _last_operation["type"] = "add_line"
        _last_operation["data"] = parsed
        _last_operation["raw"] = raw
        _last_operation["email_html"] = _generate_create_email_html(parsed)
        trigger_auto_email(f"Add line to header #{header_id}")
        summary = generate_ai_summary("add_line", parsed)
        _last_operation["ai_summary"] = summary
        return jsonify({"reply": parsed, "type": "add_line_result", "ai_summary": summary, "visualization": viz_payload})

    except requests.exceptions.HTTPError as e:
        return jsonify({"reply": f"REST API error: {e}", "type": "error"})
    except requests.exceptions.ConnectionError:
        return jsonify({"reply": "Could not connect to Oracle EBS server.", "type": "error"})
    except Exception as e:
        return jsonify({"reply": f"Something went wrong: {e}", "type": "error"})


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    body = request.get_json(force=True)
    viz_requested = bool(body.get("_visualization_requested", False))
    viz_payload = {
        "requested": viz_requested,
        "available": False,
        "reason": (
            "Visualization is not available for this operation because it performs a transactional action "
            "and does not return report-style numeric result data."
        ) if viz_requested else "",
        "chart_config": None,
    }
    to_email = (body.get("to_email") or "").strip()
    subject = (body.get("subject") or "Oracle ERP Order Details Update").strip()
    body_text = (body.get("body") or "Please find the requested order details structured below.").strip()

    if not to_email:
        return jsonify({"reply": "Email address is required.", "type": "error"})

    html_payload = _last_operation.get("email_html", "")
    if not html_payload:
        return jsonify({"reply": "No recent operation data to send. Please look up or create an order first.", "type": "error"})

    attachment_format = (body.get("attachment_format") or "excel").strip().lower()
    success, msg = send_erp_email(to_email, subject, body_text, html_payload, attachment_format)
    if success:
        return jsonify({
            "reply": f"Email sent successfully to {to_email}! (attachment: {attachment_format})",
            "type": "email_success",
            "visualization": viz_payload,
        })

    return jsonify({"reply": f"Error sending email: {msg}", "type": "error"})


@app.route("/api/email-preview")
def api_email_preview():
    return jsonify({
        "html": _last_operation.get("email_html", ""),
        "has_data": _last_operation["type"] is not None,
        "operation_type": _last_operation["type"],
    })


@app.route("/api/auto-email", methods=["POST"])
def api_auto_email():
    data = request.get_json(force=True)
    _auto_email["enabled"] = bool(data.get("enabled", False))
    _auto_email["to"] = (data.get("to") or "").strip()
    config_manager.set_config_value("auto_email_enabled", _auto_email["enabled"])
    config_manager.set_config_value("auto_email_to", _auto_email["to"])
    return jsonify({"ok": True, **_auto_email})


@app.route("/api/auto-email", methods=["GET"])
def api_auto_email_status():
    return jsonify(_auto_email)


@app.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    data = request.get_json(force=True)
    to_email = (data.get("to_email") or "").strip()
    customer_name = (data.get("customer_name") or "").strip()
    interval_str = (data.get("interval") or "60").strip()

    if not to_email:
        return jsonify({"error": "Recipient email is required."}), 400

    mins = 60
    interval_lower = interval_str.lower()
    if "daily" in interval_lower or "day" in interval_lower:
        mins = 1440
    elif "hour" in interval_lower:
        nums = re.findall(r"\d+", interval_str)
        mins = int(nums[0]) * 60 if nums else 60
    elif "min" in interval_lower:
        nums = re.findall(r"\d+", interval_str)
        mins = int(nums[0]) if nums else 60
    else:
        nums = re.findall(r"\d+", interval_str)
        if nums:
            mins = int(nums[0])

    _start_scheduler(mins, customer_name, to_email)
    return jsonify({
        "ok": True,
        "message": f"Scheduler started: every {mins} min(s) -> {to_email}",
        **_scheduler,
    })


@app.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    _stop_scheduler()
    return jsonify({"ok": True, "message": "Scheduler stopped.", **_scheduler})


@app.route("/api/scheduler/status")
def api_scheduler_status():
    return jsonify(_scheduler)


@app.route("/api/auto-loop/start", methods=["POST"])
def api_auto_loop_start():
    body = request.get_json(force=True)
    to_email = (body.get("to_email") or "").strip()
    if not to_email:
        return jsonify({"error": "Recipient email is required."}), 400

    _start_auto_loop(to_email)
    return jsonify({"ok": True, "message": f"Auto-loop started -> {to_email}", **_auto_loop})


@app.route("/api/auto-loop/stop", methods=["POST"])
def api_auto_loop_stop():
    _stop_auto_loop()
    return jsonify({"ok": True, "message": "Auto-loop stopped.", **_auto_loop})


@app.route("/api/auto-loop/status")
def api_auto_loop_status():
    return jsonify(_auto_loop)


@app.route("/api/download-excel")
def api_download_excel():
    return api_download()


@app.route("/api/download")
def api_download():
    if not _last_operation.get("type") or not _last_operation.get("data"):
        return jsonify({"error": "No operation data available. Perform a query first."}), 400

    fmt = request.args.get("format", "excel").lower().strip()

    if fmt == "csv":
        data = _generate_csv()
        if not data:
            return jsonify({"error": "CSV generation failed or no data available."}), 500
        fname = _get_filename("csv")
        return Response(
            data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    if fmt == "json":
        data = _generate_json_file()
        if not data:
            return jsonify({"error": "JSON generation failed or no data available."}), 500
        fname = _get_filename("json")
        return Response(
            data,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )

    # Default: Excel
    if not OPENPYXL_AVAILABLE:
        return jsonify({"error": "openpyxl not installed. Run: pip install openpyxl"}), 500
    data = _generate_excel()
    if not data:
        return jsonify({"error": "Excel generation failed."}), 500
    fname = _get_filename("xlsx")
    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# =========================================================
# Main
# =========================================================

if __name__ == "__main__":
    host = str(config_manager.get_config_value("app_host", "0.0.0.0"))
    port = int(config_manager.get_config_value("app_port", 5000))
    debug = bool(config_manager.get_config_value("app_debug", False))
    use_reloader = bool(config_manager.get_config_value("app_use_reloader", False))
    tls_enabled = bool(config_manager.get_config_value("app_tls_enabled", True))
    scheme = "https" if tls_enabled else "http"
    print(f"AI Dynamic SQL + Sales Order Chatbot running on {scheme}://{host}:{port}")
    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=use_reloader,
        ssl_context="adhoc" if tls_enabled else None,
    )
