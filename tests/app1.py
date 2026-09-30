import streamlit as st
import SalesOrderBot2 as SalesOrderbot
import json

st.set_page_config(page_title="SalesOrderbot Assistant", page_icon="📦")
st.title("📦 SalesOrderbot Assistant")

# --- Field definitions with display names ---
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

FIELD_KEYS   = [f[0] for f in FIELDS]
FIELD_LABELS = [f[1] for f in FIELDS]

FIELDS_HINT = "\n".join([f"{i+1}. {label}" for i, (_, label) in enumerate(FIELDS)])
WELCOME_MSG = (
    "Hello! I can help you create a Sales Order.\n\n"
    "Please provide **all values in a single message**, separated by **commas** or **new lines**, "
    "in the following order:\n\n"
    f"{FIELDS_HINT}\n\n"
    "**Example (comma-separated):**\n"
    "`PO-1234, 101, ITEM-A, 10, 150.00, 140.00, 1001, 2002, 3003, 4004, 5005, 6006, OU-HYD`"
)

# --- 1. Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": WELCOME_MSG}]

if "order_complete" not in st.session_state:
    st.session_state.order_complete = False

# --- 2. Display Chat History ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- Helper: parse single-line / multi-line input into a dict ---
def parse_input(raw: str) -> dict | None:
    if "\n" in raw:
        parts = [p.strip() for p in raw.strip().splitlines() if p.strip()]
    else:
        parts = [p.strip() for p in raw.strip().split(",") if p.strip()]

    if len(parts) != len(FIELD_KEYS):
        return None

    return dict(zip(FIELD_KEYS, parts))


# -------------------------------------------------------------------
# Helper: Extract details from Oracle EBS OutputParameters response
# -------------------------------------------------------------------
def extract_erp_details(result: dict) -> dict:
    # Unwrap OutputParameters if present
    data = result.get("OutputParameters", result)

    # ── Overall Return Status ──────────────────────────────────
    status = data.get("X_RETURN_STATUS", "N/A")

    # ── Messages ──────────────────────────────────────────────
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

    # ── Header Record (X_HEADER_REC) ───────────────────────────
    header = data.get("X_HEADER_REC", {}) or {}

    # ── Header Val Record (X_HEADER_VAL_REC) ──────────────────
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}

    # Build full header details dict — ID fields from REC, names from VAL_REC
    header_details = {
        # ── Order Identity ─────────────────────────────────────
        "Order Number":          header.get("ORDER_NUMBER",              "N/A"),
        "Header ID":             header.get("HEADER_ID",                 "N/A"),
        "Customer PO":           header.get("CUST_PO_NUMBER",            "N/A"),
        "Orig Sys Document Ref": header.get("ORIG_SYS_DOCUMENT_REF",     "N/A"),
        # ── Status & Dates ─────────────────────────────────────
        "Return Status":         header.get("RETURN_STATUS",             "N/A"),
        "Flow Status":           header.get("FLOW_STATUS_CODE",          "N/A"),
        "Order Category":        header.get("ORDER_CATEGORY_CODE",       "N/A"),
        "Operation":             header.get("OPERATION",                 "N/A"),
        "Ordered Date":          header.get("ORDERED_DATE",              "N/A"),
        "Request Date":          header.get("REQUEST_DATE",              "N/A"),
        "Pricing Date":          header.get("PRICING_DATE",              "N/A"),
        "Booked Flag":           header.get("BOOKED_FLAG",               "N/A"),
        "Open Flag":             header.get("OPEN_FLAG",                 "N/A"),
        "Cancelled Flag":        header.get("CANCELLED_FLAG",            "N/A"),
        "Transaction Phase":     header.get("TRANSACTION_PHASE_CODE",    "N/A"),
        # ── Financial ──────────────────────────────────────────
        "Currency":              header.get("TRANSACTIONAL_CURR_CODE",   "N/A"),
        "Payment Term ID":       header.get("PAYMENT_TERM_ID",           "N/A"),
        "Payment Term":          header_val.get("PAYMENT_TERM",          "N/A"),
        "Price List ID":         header.get("PRICE_LIST_ID",             "N/A"),
        "Price List":            header_val.get("PRICE_LIST",            "N/A"),
        # ── Org & Type ─────────────────────────────────────────
        "Org ID":                header.get("ORG_ID",                    "N/A"),
        "Order Type ID":         header.get("ORDER_TYPE_ID",             "N/A"),
        "Order Type":            header_val.get("ORDER_TYPE",            "N/A"),
        "Order Source ID":       header.get("ORDER_SOURCE_ID",           "N/A"),
        "Order Source":          header_val.get("ORDER_SOURCE",          "N/A"),
        # ── Parties ────────────────────────────────────────────
        "Sold To Org ID":        header.get("SOLD_TO_ORG_ID",            "N/A"),
        "Customer":              header_val.get("SOLD_TO_ORG",           "N/A"),
        "Customer Number":       header_val.get("CUSTOMER_NUMBER",       "N/A"),
        "Ship To Org ID":        header.get("SHIP_TO_ORG_ID",            "N/A"),
        "Ship To":               header_val.get("SHIP_TO_ORG",           "N/A"),
        "Ship To Address":       header_val.get("SHIP_TO_ADDRESS1",      "N/A"),
        "Ship To City":          header_val.get("SHIP_TO_CITY",          "N/A"),
        "Ship To State":         header_val.get("SHIP_TO_STATE",         "N/A"),
        "Ship To Zip":           header_val.get("SHIP_TO_ZIP",           "N/A"),
        "Ship To Country":       header_val.get("SHIP_TO_COUNTRY",       "N/A"),
        "Invoice To Org ID":     header.get("INVOICE_TO_ORG_ID",         "N/A"),
        "Bill To":               header_val.get("INVOICE_TO_ORG",        "N/A"),
        "Bill To Address":       header_val.get("INVOICE_TO_ADDRESS1",   "N/A"),
        "Bill To City":          header_val.get("INVOICE_TO_CITY",       "N/A"),
        "Bill To State":         header_val.get("INVOICE_TO_STATE",      "N/A"),
        "Bill To Zip":           header_val.get("INVOICE_TO_ZIP",        "N/A"),
        "Bill To Country":       header_val.get("INVOICE_TO_COUNTRY",    "N/A"),
        # ── Sales ──────────────────────────────────────────────
        "Salesrep ID":           header.get("SALESREP_ID",               "N/A"),
        "Salesrep":              header_val.get("SALESREP",              "N/A"),
        "Demand Class":          header_val.get("DEMAND_CLASS",          "N/A"),
        # ── Shipping ───────────────────────────────────────────
        "Ship From Org":         header_val.get("SHIP_FROM_ORG",         "N/A"),
        "Freight Carrier":       header_val.get("FREIGHT_CARRIER",       "N/A"),
        "Shipping Method":       header_val.get("SHIPPING_METHOD",       "N/A"),
        "FOB Point":             header_val.get("FOB_POINT",             "N/A"),
        "Freight Terms":         header_val.get("FREIGHT_TERMS",         "N/A"),
        # ── Misc ───────────────────────────────────────────────
        "Tax Exempt Flag":       header.get("TAX_EXEMPT_FLAG",           "N/A"),
        "Version Number":        header.get("VERSION_NUMBER",            "N/A"),
        "Lock Control":          header.get("LOCK_CONTROL",              "N/A"),
        "XML Message ID":        header.get("XML_MESSAGE_ID",            "N/A"),
        "Created By":            header.get("CREATED_BY",                "N/A"),
        "Creation Date":         header.get("CREATION_DATE",             "N/A"),
        "Last Updated By":       header.get("LAST_UPDATED_BY",           "N/A"),
        "Last Update Date":      header.get("LAST_UPDATE_DATE",          "N/A"),
    }

    # ── Line Table ─────────────────────────────────────────────
    line_tbl     = data.get("X_LINE_TBL",     {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}

    raw_lines     = line_tbl.get("P_LINE_TBL_ITEM",     [])
    raw_line_vals = line_val_tbl.get("P_LINE_VAL_TBL_ITEM", [])

    if isinstance(raw_lines,     dict): raw_lines     = [raw_lines]
    if isinstance(raw_line_vals, dict): raw_line_vals = [raw_line_vals]

    lines = []
    for i, line in enumerate(raw_lines):
        val = raw_line_vals[i] if i < len(raw_line_vals) else {}
        lines.append({
            # ── Identity ───────────────────────────────────────
            "Line #":              line.get("LINE_NUMBER",           "N/A"),
            "Line ID":             line.get("LINE_ID",               "N/A"),
            "Header ID":           line.get("HEADER_ID",             "N/A"),
            "Shipment #":          line.get("SHIPMENT_NUMBER",       "N/A"),
            "Orig Sys Line Ref":   line.get("ORIG_SYS_LINE_REF",     "N/A"),
            # ── Item ───────────────────────────────────────────
            "Item":                line.get("ORDERED_ITEM",          "N/A"),
            "Item Description":    val.get("INVENTORY_ITEM",         "N/A"),
            "Inventory Item ID":   line.get("INVENTORY_ITEM_ID",     "N/A"),
            "Item Type":           line.get("ITEM_TYPE_CODE",        "N/A"),
            # ── Quantity & Price ───────────────────────────────
            "Qty Ordered":         line.get("ORDERED_QUANTITY",      "N/A"),
            "Qty Cancelled":       line.get("CANCELLED_QUANTITY",    "N/A"),
            "UOM":                 line.get("ORDER_QUANTITY_UOM",    "N/A"),
            "Pricing Qty":         line.get("PRICING_QUANTITY",      "N/A"),
            "Unit List Price":     line.get("UNIT_LIST_PRICE",       "N/A"),
            "Unit Selling Price":  line.get("UNIT_SELLING_PRICE",    "N/A"),
            # ── Dates ──────────────────────────────────────────
            "Request Date":        line.get("REQUEST_DATE",          "N/A"),
            "Promise Date":        line.get("PROMISE_DATE",          "N/A"),
            "Earliest Accept Date":line.get("EARLIEST_ACCEPTABLE_DATE","N/A"),
            "Latest Accept Date":  line.get("LATEST_ACCEPTABLE_DATE","N/A"),
            "Pricing Date":        line.get("PRICING_DATE",          "N/A"),
            # ── Status ─────────────────────────────────────────
            "Return Status":       line.get("RETURN_STATUS",         "N/A"),
            "Flow Status":         line.get("FLOW_STATUS_CODE",      "N/A"),
            "Line Category":       line.get("LINE_CATEGORY_CODE",    "N/A"),
            "Open Flag":           line.get("OPEN_FLAG",             "N/A"),
            "Booked Flag":         line.get("BOOKED_FLAG",           "N/A"),
            "Cancelled Flag":      line.get("CANCELLED_FLAG",        "N/A"),
            "Shippable Flag":      line.get("SHIPPABLE_FLAG",        "N/A"),
            "Operation":           line.get("OPERATION",             "N/A"),
            # ── Line Type & Pricing ────────────────────────────
            "Line Type ID":        line.get("LINE_TYPE_ID",          "N/A"),
            "Line Type":           val.get("LINE_TYPE",              "N/A"),
            "Payment Term":        val.get("PAYMENT_TERM",           "N/A"),
            "Price List":          val.get("PRICE_LIST",             "N/A"),
            "Calculate Price Flag":line.get("CALCULATE_PRICE_FLAG",  "N/A"),
            # ── Shipping ───────────────────────────────────────
            "Ship To Org":         val.get("SHIP_TO_ORG",            "N/A"),
            "Ship To Address":     val.get("SHIP_TO_ADDRESS1",       "N/A"),
            "Ship To City":        val.get("SHIP_TO_CITY",           "N/A"),
            "Ship To State":       val.get("SHIP_TO_STATE",          "N/A"),
            "Ship To Country":     val.get("SHIP_TO_COUNTRY",        "N/A"),
            "Ship From Org":       val.get("SHIP_FROM_ORG",          "N/A"),
            "Shipping Method":     val.get("SHIPPING_METHOD",        "N/A"),
            "Freight Carrier":     val.get("FREIGHT_CARRIER",        "N/A"),
            "Source Type":         val.get("SOURCE_TYPE",            "N/A"),
            "Ship Tolerance Above":line.get("SHIP_TOLERANCE_ABOVE",  "N/A"),
            "Ship Tolerance Below":line.get("SHIP_TOLERANCE_BELOW",  "N/A"),
            # ── Tax ────────────────────────────────────────────
            "Tax Code":            line.get("TAX_CODE",              "N/A"),
            "Tax Exempt Flag":     line.get("TAX_EXEMPT_FLAG",       "N/A"),
            # ── Audit ──────────────────────────────────────────
            "Created By":          line.get("CREATED_BY",            "N/A"),
            "Creation Date":       line.get("CREATION_DATE",         "N/A"),
            "Last Updated By":     line.get("LAST_UPDATED_BY",       "N/A"),
            "Last Update Date":    line.get("LAST_UPDATE_DATE",      "N/A"),
        })

    return {
        "status":         status,
        "message":        message_text,
        "header_details": header_details,
        "lines":          lines,
    }


# -------------------------------------------------------------------
# Helper: Render a single flat "Field | Value" markdown table,
# skipping rows where value is missing or "N/A"
# -------------------------------------------------------------------
def _flat_table(rows: dict[str, str]) -> None:
    """Render a simple two-column markdown table (Field | Value)."""
    visible = {k: v for k, v in rows.items() if v and str(v) != "N/A"}
    if not visible:
        st.info("No data available.")
        return
    md = "| **Field** | **Value** |\n|:---|:---|\n"
    md += "\n".join(f"| {k} | {v} |" for k, v in visible.items())
    st.markdown(md)


# --- Helper: Render extracted ERP details as flat tables ---
def display_erp_response(result: dict):
    d = extract_erp_details(result)

    # Status emoji
    status_val = str(d["status"]).upper()
    if status_val == "S":
        emoji, status_label = "✅", "Success"
    elif status_val == "E":
        emoji, status_label = "❌", "Error"
    elif status_val == "W":
        emoji, status_label = "⚠️", "Warning"
    else:
        emoji, status_label = "ℹ️", status_val

    # Top-level status banner
    banner = (
        f"{emoji} **Order {status_label}!** &nbsp;|&nbsp; "
        f"Order # `{d['header_details'].get('Order Number', 'N/A')}` &nbsp;|&nbsp; "
        f"Header ID `{d['header_details'].get('Header ID', 'N/A')}`"
    )
    st.session_state.messages.append({"role": "assistant", "content": banner})
    st.markdown(banner)

    # ── ERP Messages ──────────────────────────────────────────
    if d["message"] and d["message"] != "N/A":
        st.markdown("### 💬 ERP Messages")
        for msg in d["message"].split(" | "):
            if msg.strip():
                st.warning(msg.strip())

    # ── HEADER DETAILS — single flat table ────────────────────
    st.markdown("---")
    st.markdown("## 🧾 Header Details")
    _flat_table(d["header_details"])

    # ── LINE DETAILS — one flat table per line ─────────────────
    st.markdown("---")
    st.markdown("## 📦 Line Details")

    if d["lines"]:
        for li, line in enumerate(d["lines"]):
            if len(d["lines"]) > 1:
                st.markdown(f"### Line {line.get('Line #', li + 1)}")
            _flat_table(line)
    else:
        st.info("ℹ️ No line details found in the response.")

    # ── Full Raw Response (collapsible) ────────────────────────
    st.markdown("---")
    with st.expander("🔍 View Full Raw API Response"):
        st.json(result)


# --- 3. Chat Input Logic ---
if prompt := st.chat_input("Paste all values here (comma or newline separated)..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if not st.session_state.order_complete:

        order_data = parse_input(prompt)

        # Validation: wrong number of values
        if order_data is None:
            raw_count = len(prompt.strip().splitlines()) if "\n" in prompt else len(prompt.strip().split(","))
            err = (
                f"⚠️ Expected **{len(FIELD_KEYS)} values** but received **{raw_count}**.\n\n"
                f"Please provide all {len(FIELD_KEYS)} values in order:\n\n{FIELDS_HINT}"
            )
            st.session_state.messages.append({"role": "assistant", "content": err})
            with st.chat_message("assistant"):
                st.markdown(err)

        else:
            # Confirmation table
            confirm_lines = "\n".join(
                [f"| **{label}** | `{order_data[key]}` |" for key, label in FIELDS]
            )
            confirm_msg = (
                "Here's a summary of what I received:\n\n"
                "| Field | Value |\n|---|---|\n"
                + confirm_lines
                + "\n\nSending to ERP... ⏳"
            )
            st.session_state.messages.append({"role": "assistant", "content": confirm_msg})
            with st.chat_message("assistant"):
                st.markdown(confirm_msg)

            st.session_state.order_complete = True

            # Submit to ERP
            with st.chat_message("assistant"):
                try:
                    d = order_data

                    parsed_qty     = SalesOrderbot.parse_numeric_value(d['qty'],           allow_float=False)
                    parsed_price   = SalesOrderbot.parse_numeric_value(d['unit_price'],    allow_float=True)
                    parsed_selling = SalesOrderbot.parse_numeric_value(d['selling_price'], allow_float=True)

                    payload = SalesOrderbot.create_payload(
                        p_cust_po         = d['cpo'],
                        p_item_id         = int(d['item_id']),
                        p_ordered_item    = d['ordered_item'],
                        p_qty             = parsed_qty,
                        p_price           = parsed_price   or 0,
                        p_selling_price   = parsed_selling or 0,
                        p_payment_term_id = int(d['payment_term_id']),
                        p_price_list_id   = int(d['price_list_id']),
                        p_salesrep_id     = int(d['salesrep_id']),
                        p_line_type_id    = int(d['line_type_id']),
                        p_ship_to_org     = int(d['ship_to_org']),
                        p_sold_to_org     = int(d['sold_to_org']),
                        p_operating_unit  = d['operating_unit']
                    )

                    result = SalesOrderbot.send_order(payload)
                    display_erp_response(result)

                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})

            # New Session Button
            if st.button("🔄 Start New Session"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()