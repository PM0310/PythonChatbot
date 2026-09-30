"""
MCP bridge for the Sales Order Flask agent.

This server exposes selected sales-order operations as MCP tools and forwards
requests to the existing Flask backend (app7.1.py).

Run example:
  python salesorder_mcp_server.py

Environment variables:
  SALESORDER_API_BASE_URL   Flask base URL (default: http://127.0.0.1:5000)
  SALESORDER_MCP_HOST       MCP bind host (default: 0.0.0.0)
  SALESORDER_MCP_PORT       MCP bind port (default: 8001)
  SALESORDER_MCP_PATH       MCP path (default: /mcp)
  SALESORDER_API_USER       Optional Flask login username
  SALESORDER_API_PASSWORD   Optional Flask login password
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests
from fastmcp import FastMCP


API_BASE_URL = os.environ.get("SALESORDER_API_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
MCP_HOST = os.environ.get("SALESORDER_MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.environ.get("SALESORDER_MCP_PORT", "8001"))
MCP_PATH = os.environ.get("SALESORDER_MCP_PATH", "/mcp")
API_USER = os.environ.get("SALESORDER_API_USER", "")
API_PASSWORD = os.environ.get("SALESORDER_API_PASSWORD", "")


mcp = FastMCP("salesorder-flask-mcp")
_session = requests.Session()
_logged_in = False


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        return resp.json()  # type: ignore[return-value]
    except Exception:
        text = (resp.text or "").strip()
        return {"raw": text[:4000]}


def _ensure_login() -> None:
    global _logged_in
    if _logged_in:
        return
    if not API_USER or not API_PASSWORD:
        return

    login_url = f"{API_BASE_URL}/api/login"
    resp = _session.post(
        login_url,
        json={"username": API_USER, "password": API_PASSWORD},
        timeout=30,
    )
    if resp.status_code != 200:
        payload = _safe_json(resp)
        raise RuntimeError(f"Flask login failed ({resp.status_code}): {payload}")

    payload = _safe_json(resp)
    if not payload.get("ok"):
        raise RuntimeError(f"Flask login rejected: {payload}")

    _logged_in = True


def _call_api(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    require_auth: bool = False,
) -> Dict[str, Any]:
    if require_auth:
        _ensure_login()

    url = f"{API_BASE_URL}{path}"
    resp = _session.request(method, url, json=json_body, params=params, timeout=180)
    payload = _safe_json(resp)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {path}: {payload}")
    return payload


@mcp.tool
def health() -> Dict[str, Any]:
    """Health check for MCP and Flask bridge connectivity."""
    try:
        payload = _call_api(
            "POST",
            "/api/chat",
            json_body={"message": "hello", "history": []},
            require_auth=False,
        )
        return {
            "ok": True,
            "mcp": "ready",
            "flask_base_url": API_BASE_URL,
            "chat_probe": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "mcp": "ready",
            "flask_base_url": API_BASE_URL,
            "error": str(exc),
        }


@mcp.tool
def salesorder_chat(message: str, history_json: str = "[]") -> Dict[str, Any]:
    """
    Route a user message to the Sales Order assistant chat endpoint.

    Args:
        message: User message.
        history_json: JSON array of prior chat messages.
    """
    history: Any
    try:
        history = json.loads(history_json or "[]")
        if not isinstance(history, list):
            history = []
    except Exception:
        history = []

    payload = _call_api(
        "POST",
        "/api/chat",
        json_body={"message": message, "history": history},
        require_auth=False,
    )
    return payload


@mcp.tool
def create_sales_order(order_payload_json: str) -> Dict[str, Any]:
    """
    Create a sales order through the Flask API.

    Args:
        order_payload_json: JSON object string expected by /api/create-order.
    """
    try:
        order_payload = json.loads(order_payload_json)
        if not isinstance(order_payload, dict):
            raise ValueError("order_payload_json must decode to a JSON object")
    except Exception as exc:
        raise ValueError(f"Invalid order_payload_json: {exc}") from exc

    payload = _call_api(
        "POST",
        "/api/create-order",
        json_body=order_payload,
        require_auth=False,
    )
    return payload


@mcp.tool
def get_order_by_number(order_number: int) -> Dict[str, Any]:
    """
    Fetch order details by order number via the chat endpoint for consistency.
    """
    message = f"Get order {int(order_number)}"
    payload = _call_api(
        "POST",
        "/api/chat",
        json_body={"message": message, "history": []},
        require_auth=False,
    )
    return payload


@mcp.tool
def get_customer_orders(customer_name: str) -> Dict[str, Any]:
    """
    Fetch all orders for a given customer name.

    Args:
        customer_name: Full or partial customer name to search.
    """
    message = f"Show orders for customer {customer_name}"
    payload = _call_api(
        "POST",
        "/api/chat",
        json_body={"message": message, "history": []},
        require_auth=False,
    )
    return payload


@mcp.tool
def get_orders_by_range(
    status: str = "",
    date_range: str = "",
    year: int = 0,
) -> Dict[str, Any]:
    """
    Fetch orders filtered by status and/or date range using the orders-advanced endpoint.

    Args:
        status: Order status filter (e.g. BOOKED, ENTERED, SHIPPED, CANCELLED).
        date_range: One of: this_month, this_week, last_30_days. Leave empty for no filter.
        year: 4-digit year filter (e.g. 2024). 0 means no filter.
    """
    params: Dict[str, Any] = {}
    if status:
        params["status"] = status.strip().upper()
    if date_range:
        params["range_type"] = date_range.strip().lower()
    if year and int(year) > 0:
        params["year"] = int(year)

    payload = _call_api(
        "GET",
        "/api/orders-advanced",
        params=params or None,
        require_auth=False,
    )
    return payload


@mcp.tool
def add_order_line(
    header_id: int,
    inventory_item_id: int,
    ordered_item: str,
    ordered_quantity: float,
    unit_list_price: float = 0.0,
    unit_selling_price: float = 0.0,
    payment_term_id: int = 0,
    price_list_id: int = 0,
) -> Dict[str, Any]:
    """
    Add a line item to an existing sales order.

    Args:
        header_id: HEADER_ID of the existing order to add a line to.
        inventory_item_id: Oracle INVENTORY_ITEM_ID for the item.
        ordered_item: Item code / SEGMENT1 string.
        ordered_quantity: Quantity to order (must be > 0).
        unit_list_price: List price per unit (optional).
        unit_selling_price: Selling price per unit (optional, defaults to list price).
        payment_term_id: Payment term ID (0 = use system default).
        price_list_id: Price list ID (0 = use system default).
    """
    body: Dict[str, Any] = {
        "header_id": int(header_id),
        "inventory_item_id": int(inventory_item_id),
        "ordered_item": ordered_item,
        "ordered_quantity": float(ordered_quantity),
        "unit_list_price": float(unit_list_price),
        "unit_selling_price": float(unit_selling_price) if unit_selling_price else float(unit_list_price),
    }
    if payment_term_id and int(payment_term_id) > 0:
        body["payment_term_id"] = int(payment_term_id)
    if price_list_id and int(price_list_id) > 0:
        body["price_list_id"] = int(price_list_id)

    payload = _call_api(
        "POST",
        "/api/add-line",
        json_body=body,
        require_auth=False,
    )
    return payload


@mcp.tool
def send_order_email(
    to_email: str,
    subject: str = "Oracle ERP Order Details Update",
    body: str = "Please find the requested order details structured below.",
    attachment_format: str = "excel",
) -> Dict[str, Any]:
    """
    Send the most recent operation result by email with an attachment.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        body: Plain text body of the email.
        attachment_format: One of: excel, csv, json.
    """
    payload = _call_api(
        "POST",
        "/api/send-email",
        json_body={
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "attachment_format": attachment_format.lower().strip(),
        },
        require_auth=False,
    )
    return payload


@mcp.tool
def lookup_items(search_text: str = "") -> Dict[str, Any]:
    """
    Search for inventory items by name/code prefix.

    Args:
        search_text: Item code or description to search for. Empty string returns top items.
    """
    payload = _call_api(
        "GET",
        "/api/lookup-items",
        params={"q": search_text.strip()} if search_text.strip() else None,
        require_auth=False,
    )
    return payload


@mcp.tool
def lookup_customers(search_text: str = "") -> Dict[str, Any]:
    """
    Search for customers by name.

    Args:
        search_text: Customer name or partial name to search. Empty returns top customers.
    """
    payload = _call_api(
        "GET",
        "/api/lookup-customers",
        params={"q": search_text.strip()} if search_text.strip() else None,
        require_auth=False,
    )
    return payload


@mcp.tool
def get_highly_ordered_items(year: int = 0, top_n: int = 25) -> Dict[str, Any]:
    """
    Retrieve the most frequently ordered items by total ordered quantity.

    Args:
        year: 4-digit year to filter by (0 = all years).
        top_n: Number of top items to return (1-200, default 25).
    """
    parts = ["Show top"]
    if top_n and int(top_n) > 0:
        parts.append(str(int(top_n)))
    parts.append("highly ordered items")
    if year and int(year) > 0:
        parts.append(f"in {int(year)}")
    message = " ".join(parts)

    payload = _call_api(
        "POST",
        "/api/chat",
        json_body={"message": message, "history": []},
        require_auth=False,
    )
    return payload


@mcp.tool
def get_dashboard_data() -> Dict[str, Any]:
    """
    Retrieve the agent dashboard: system status, last operation summary, scheduler state,
    auto-loop state, and auto-email configuration.
    """
    payload = _call_api(
        "GET",
        "/api/dashboard",
        require_auth=False,
    )
    return payload


if __name__ == "__main__":
    print(f"Starting Sales Order MCP server on http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}")
    print(f"Bridged Flask API base URL: {API_BASE_URL}")
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
        path=MCP_PATH,
    )
