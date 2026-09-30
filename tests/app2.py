import streamlit as st
import SalesOrderBot2 as SalesOrderbot
import anthropic
import json
import re
import os
from pathlib import Path
from dotenv import load_dotenv

# Load API key from ClaudeKey.env
env_path = Path(__file__).parent / "ClaudeKey.env"
load_dotenv(dotenv_path=env_path)

# Verify API key loaded - show clear error if missing
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    st.error(
        "ANTHROPIC_API_KEY not found in ClaudeKey.env. "
        "Please make sure ClaudeKey.env is in the same folder as app.py "
        "and contains: ANTHROPIC_API_KEY=sk-ant-your-key-here"
    )
    st.stop()

# Page Config
st.set_page_config(page_title="SalesOrderbot AI Assistant", page_icon="=")
st.title("= SalesOrderbot AI Assistant")

# Field definitions
FIELDS = [
    ("cpo",              "Customer PO Number"),
    ("item_id",          "Item ID"),
    ("ordered_item",     "Ordered Item"),
    ("qty",              "Quantity"),
    ("unit_price",       "Unit Price"),
    ("selling_price",    "Selling Price"),
    ("payment_term_id",  "Payment Term ID"),
    ("price_list_id",    "Price List ID"),
    ("salesrep_id",      "Salesrep ID"),
    ("line_type_id",     "Line Type ID"),
    ("ship_to_org",      "Ship To Org"),
    ("sold_to_org",      "Sold To Org"),
    ("operating_unit",   "Operating Unit"),
]
FIELD_KEYS = [f[0] for f in FIELDS]

# System Prompt for Claude
SYSTEM_PROMPT = """You are a smart and friendly Sales Order Assistant for an Oracle EBS ERP system.
Your job is to help users create sales orders by collecting the following 13 fields through natural conversation.

FIELDS TO COLLECT:
1.  cpo            - Customer PO Number        (text, e.g. PO-1234)
2.  item_id        - Item ID                   (integer, e.g. 101)
3.  ordered_item   - Ordered Item name/code    (text, e.g. ITEM-A)
4.  qty            - Quantity                  (integer, e.g. 10)
5.  unit_price     - Unit Price                (decimal, e.g. 150.00)
6.  selling_price  - Selling Price             (decimal, e.g. 140.00)
7.  payment_term_id - Payment Term ID          (integer, e.g. 1001)
8.  price_list_id  - Price List ID             (integer, e.g. 2002)
9.  salesrep_id    - Salesrep ID               (integer, e.g. 3003)
10. line_type_id   - Line Type ID              (integer, e.g. 4004)
11. ship_to_org    - Ship To Org ID            (integer, e.g. 5005)
12. sold_to_org    - Sold To Org ID            (integer, e.g. 6006)
13. operating_unit - Operating Unit code       (text, e.g. OU-HYD)

RULES:
- Be conversational, helpful, and concise.
- If the user provides multiple fields at once (comma-separated or natural language), extract ALL of them in one go.
- Validate types strictly:
    - item_id, qty, payment_term_id, price_list_id, salesrep_id, line_type_id, ship_to_org, sold_to_org must be integers
    - unit_price, selling_price must be decimals/floats
    - cpo, ordered_item, operating_unit are text
- If a value is invalid, politely ask the user to correct it.
- Always track which fields are already collected and which are still missing.
- Ask only for missing fields, never re-ask for fields already provided.
- Once ALL 13 fields are collected, show the user a clear summary table and ask for confirmation.
- If the user confirms (says yes / confirm / submit / looks good / proceed), output ONLY this JSON block and nothing else:

```json
{
  "ORDER_READY": true,
  "cpo": "...",
  "item_id": 101,
  "ordered_item": "...",
  "qty": 10,
  "unit_price": 150.00,
  "selling_price": 140.00,
  "payment_term_id": 1001,
  "price_list_id": 2002,
  "salesrep_id": 3003,
  "line_type_id": 4004,
  "ship_to_org": 5005,
  "sold_to_org": 6006,
  "operating_unit": "OU-HYD"
}
```

- If the user wants to change a value after the summary, update it, show the revised summary, and ask for confirmation again.
- Keep responses short and focused.
- Start by warmly greeting the user and asking them to provide order details (all at once or one by one).
"""

# Session State Init
welcome_trigger = False
if "messages" not in st.session_state:
    st.session_state.messages        = []
    st.session_state.ai_history      = []
    st.session_state.order_submitted = False
    welcome_trigger = True

if "ai_history" not in st.session_state:
    st.session_state.ai_history = []

if "order_submitted" not in st.session_state:
    st.session_state.order_submitted = False


# Call Claude API
def call_claude(user_message: str) -> str:
    # Use the key loaded at startup - already verified it exists
    client = anthropic.Anthropic(api_key="REDACTED_SECRET")

    st.session_state.ai_history.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=st.session_state.ai_history
    )

    reply = response.content[0].text

    st.session_state.ai_history.append({"role": "assistant", "content": reply})
    return reply


# Extract ORDER_READY JSON from Claude reply
def extract_order_json(text: str) -> dict | None:
    pattern = r"```json\s*(\{.*?\})\s*```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if data.get("ORDER_READY") is True:
                return data
        except json.JSONDecodeError:
            pass
    return None


# Submit order to ERP
def submit_to_erp(order: dict):
    try:
        parsed_qty     = SalesOrderbot.parse_numeric_value(str(order["qty"]),           allow_float=False)
        parsed_price   = SalesOrderbot.parse_numeric_value(str(order["unit_price"]),    allow_float=True)
        parsed_selling = SalesOrderbot.parse_numeric_value(str(order["selling_price"]), allow_float=True)

        payload = SalesOrderbot.create_payload(
            p_cust_po         = order["cpo"],
            p_item_id         = int(order["item_id"]),
            p_ordered_item    = order["ordered_item"],
            p_qty             = parsed_qty,
            p_price           = parsed_price   or 0,
            p_selling_price   = parsed_selling or 0,
            p_payment_term_id = int(order["payment_term_id"]),
            p_price_list_id   = int(order["price_list_id"]),
            p_salesrep_id     = int(order["salesrep_id"]),
            p_line_type_id    = int(order["line_type_id"]),
            p_ship_to_org     = int(order["ship_to_org"]),
            p_sold_to_org     = int(order["sold_to_org"]),
            p_operating_unit  = order["operating_unit"]
        )

        result = SalesOrderbot.send_order(payload)
        display_erp_response(result)

    except Exception as e:
        st.error(f"ERP submission failed: {str(e)}")


# Flat table renderer
def flat_table(rows: dict) -> None:
    visible = {k: v for k, v in rows.items() if v and str(v) != "N/A"}
    if not visible:
        st.info("No data available.")
        return
    md = "| **Field** | **Value** |\n|:---|:---|\n"
    md += "\n".join(f"| {k} | {v} |" for k, v in visible.items())
    st.markdown(md)


# Extract ERP response details
def extract_erp_details(result: dict) -> dict:
    data       = result.get("OutputParameters", result)
    status     = data.get("X_RETURN_STATUS", "N/A")
    header     = data.get("X_HEADER_REC",     {}) or {}
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}

    messages_raw = data.get("X_MESSAGES", {})
    message_list = []
    if isinstance(messages_raw, dict):
        items = messages_raw.get("X_MESSAGES_ITEM", [])
        if isinstance(items, list):
            message_list = [m.get("MESSAGE_TEXT", "") for m in items if m.get("MESSAGE_TEXT")]
        elif isinstance(items, dict):
            msg = items.get("MESSAGE_TEXT", "")
            if msg:
                message_list = [msg]
    message_text = " | ".join(message_list) if message_list else "N/A"

    header_details = {
        "Order Number":          header.get("ORDER_NUMBER",            "N/A"),
        "Header ID":             header.get("HEADER_ID",               "N/A"),
        "Customer PO":           header.get("CUST_PO_NUMBER",          "N/A"),
        "Orig Sys Document Ref": header.get("ORIG_SYS_DOCUMENT_REF",   "N/A"),
        "Return Status":         header.get("RETURN_STATUS",           "N/A"),
        "Flow Status":           header.get("FLOW_STATUS_CODE",        "N/A"),
        "Order Category":        header.get("ORDER_CATEGORY_CODE",     "N/A"),
        "Operation":             header.get("OPERATION",               "N/A"),
        "Ordered Date":          header.get("ORDERED_DATE",            "N/A"),
        "Request Date":          header.get("REQUEST_DATE",            "N/A"),
        "Pricing Date":          header.get("PRICING_DATE",            "N/A"),
        "Booked Flag":           header.get("BOOKED_FLAG",             "N/A"),
        "Open Flag":             header.get("OPEN_FLAG",               "N/A"),
        "Cancelled Flag":        header.get("CANCELLED_FLAG",          "N/A"),
        "Transaction Phase":     header.get("TRANSACTION_PHASE_CODE",  "N/A"),
        "Currency":              header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term ID":       header.get("PAYMENT_TERM_ID",         "N/A"),
        "Payment Term":          header_val.get("PAYMENT_TERM",        "N/A"),
        "Price List ID":         header.get("PRICE_LIST_ID",           "N/A"),
        "Price List":            header_val.get("PRICE_LIST",          "N/A"),
        "Org ID":                header.get("ORG_ID",                  "N/A"),
        "Order Type ID":         header.get("ORDER_TYPE_ID",           "N/A"),
        "Order Type":            header_val.get("ORDER_TYPE",          "N/A"),
        "Order Source":          header_val.get("ORDER_SOURCE",        "N/A"),
        "Customer":              header_val.get("SOLD_TO_ORG",         "N/A"),
        "Customer Number":       header_val.get("CUSTOMER_NUMBER",     "N/A"),
        "Ship To":               header_val.get("SHIP_TO_ORG",         "N/A"),
        "Ship To Address":       header_val.get("SHIP_TO_ADDRESS1",    "N/A"),
        "Ship To City":          header_val.get("SHIP_TO_CITY",        "N/A"),
        "Ship To State":         header_val.get("SHIP_TO_STATE",       "N/A"),
        "Ship To Country":       header_val.get("SHIP_TO_COUNTRY",     "N/A"),
        "Bill To":               header_val.get("INVOICE_TO_ORG",      "N/A"),
        "Bill To Address":       header_val.get("INVOICE_TO_ADDRESS1", "N/A"),
        "Salesrep":              header_val.get("SALESREP",            "N/A"),
        "Ship From Org":         header_val.get("SHIP_FROM_ORG",       "N/A"),
        "Freight Carrier":       header_val.get("FREIGHT_CARRIER",     "N/A"),
        "Shipping Method":       header_val.get("SHIPPING_METHOD",     "N/A"),
        "FOB Point":             header_val.get("FOB_POINT",           "N/A"),
        "Freight Terms":         header_val.get("FREIGHT_TERMS",       "N/A"),
        "Tax Exempt Flag":       header.get("TAX_EXEMPT_FLAG",         "N/A"),
        "Created By":            header.get("CREATED_BY",              "N/A"),
        "Creation Date":         header.get("CREATION_DATE",           "N/A"),
        "Last Updated By":       header.get("LAST_UPDATED_BY",         "N/A"),
        "Last Update Date":      header.get("LAST_UPDATE_DATE",        "N/A"),
    }

    line_tbl      = data.get("X_LINE_TBL",     {}) or {}
    line_val_tbl  = data.get("X_LINE_VAL_TBL", {}) or {}
    raw_lines     = line_tbl.get("P_LINE_TBL_ITEM",     [])
    raw_line_vals = line_val_tbl.get("P_LINE_VAL_TBL_ITEM", [])
    if isinstance(raw_lines,     dict): raw_lines     = [raw_lines]
    if isinstance(raw_line_vals, dict): raw_line_vals = [raw_line_vals]

    lines = []
    for i, line in enumerate(raw_lines):
        val = raw_line_vals[i] if i < len(raw_line_vals) else {}
        lines.append({
            "Line #":             line.get("LINE_NUMBER",         "N/A"),
            "Line ID":            line.get("LINE_ID",             "N/A"),
            "Header ID":          line.get("HEADER_ID",           "N/A"),
            "Item":               line.get("ORDERED_ITEM",        "N/A"),
            "Item Description":   val.get("INVENTORY_ITEM",       "N/A"),
            "Inventory Item ID":  line.get("INVENTORY_ITEM_ID",   "N/A"),
            "Item Type":          line.get("ITEM_TYPE_CODE",      "N/A"),
            "Qty Ordered":        line.get("ORDERED_QUANTITY",    "N/A"),
            "Qty Cancelled":      line.get("CANCELLED_QUANTITY",  "N/A"),
            "UOM":                line.get("ORDER_QUANTITY_UOM",  "N/A"),
            "Unit List Price":    line.get("UNIT_LIST_PRICE",     "N/A"),
            "Unit Selling Price": line.get("UNIT_SELLING_PRICE",  "N/A"),
            "Request Date":       line.get("REQUEST_DATE",        "N/A"),
            "Promise Date":       line.get("PROMISE_DATE",        "N/A"),
            "Return Status":      line.get("RETURN_STATUS",       "N/A"),
            "Flow Status":        line.get("FLOW_STATUS_CODE",    "N/A"),
            "Line Category":      line.get("LINE_CATEGORY_CODE",  "N/A"),
            "Open Flag":          line.get("OPEN_FLAG",           "N/A"),
            "Booked Flag":        line.get("BOOKED_FLAG",         "N/A"),
            "Shippable Flag":     line.get("SHIPPABLE_FLAG",      "N/A"),
            "Line Type":          val.get("LINE_TYPE",            "N/A"),
            "Payment Term":       val.get("PAYMENT_TERM",         "N/A"),
            "Price List":         val.get("PRICE_LIST",           "N/A"),
            "Ship To Org":        val.get("SHIP_TO_ORG",          "N/A"),
            "Ship To City":       val.get("SHIP_TO_CITY",         "N/A"),
            "Ship To Country":    val.get("SHIP_TO_COUNTRY",      "N/A"),
            "Ship From Org":      val.get("SHIP_FROM_ORG",        "N/A"),
            "Shipping Method":    val.get("SHIPPING_METHOD",      "N/A"),
            "Tax Code":           line.get("TAX_CODE",            "N/A"),
            "Tax Exempt Flag":    line.get("TAX_EXEMPT_FLAG",     "N/A"),
            "Created By":         line.get("CREATED_BY",          "N/A"),
            "Creation Date":      line.get("CREATION_DATE",       "N/A"),
            "Last Updated By":    line.get("LAST_UPDATED_BY",     "N/A"),
            "Last Update Date":   line.get("LAST_UPDATE_DATE",    "N/A"),
        })

    return {
        "status":         status,
        "message":        message_text,
        "header_details": header_details,
        "lines":          lines,
    }


# Display ERP response
def display_erp_response(result: dict):
    d = extract_erp_details(result)

    status_val = str(d["status"]).upper()
    if status_val == "S":
        emoji, status_label = "OK", "Success"
    elif status_val == "E":
        emoji, status_label = "X", "Error"
    elif status_val == "W":
        emoji, status_label = "!", "Warning"
    else:
        emoji, status_label = "i", status_val

    banner = (
        f"**Order {status_label}!** | "
        f"Order # `{d['header_details'].get('Order Number', 'N/A')}` | "
        f"Header ID `{d['header_details'].get('Header ID', 'N/A')}`"
    )
    st.markdown(banner)

    if d["message"] and d["message"] != "N/A":
        st.markdown("### ERP Messages")
        for msg in d["message"].split(" | "):
            if msg.strip():
                st.warning(msg.strip())

    st.markdown("---")
    st.markdown("## Header Details")
    flat_table(d["header_details"])

    st.markdown("---")
    st.markdown("## Line Details")
    if d["lines"]:
        for li, line in enumerate(d["lines"]):
            if len(d["lines"]) > 1:
                st.markdown(f"### Line {line.get('Line #', li + 1)}")
            flat_table(line)
    else:
        st.info("No line details found in the response.")

    st.markdown("---")
    with st.expander("View Full Raw API Response"):
        st.json(result)


# Display existing chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# Generate welcome message on first load
if welcome_trigger:
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            welcome = call_claude(
                "Hello! Greet the user warmly and ask them to provide the sales order details. "
                "Let them know they can type everything at once or one by one."
            )
        st.markdown(welcome)
    st.session_state.messages.append({"role": "assistant", "content": welcome})


# Main Chat Input
if not st.session_state.order_submitted:
    if prompt := st.chat_input("Type your message here..."):

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = call_claude(prompt)

            order_data = extract_order_json(reply)

            if order_data:
                submitting_msg = "All details confirmed! Submitting your order to ERP..."
                st.markdown(submitting_msg)
                st.session_state.messages.append({"role": "assistant", "content": submitting_msg})
                st.session_state.order_submitted = True
                submit_to_erp(order_data)
            else:
                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})

else:
    st.info("Order has been submitted successfully. Start a new session to create another order.")
    if st.button("Start New Session"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
