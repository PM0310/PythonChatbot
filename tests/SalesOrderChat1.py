import streamlit as st
import SalesOrderBot5 as bot
import json

st.set_page_config(page_title="Sales Order Assistant", page_icon="📦", layout="wide")
st.title("📦 Sales Order Assistant")

# --------------------------------------------------
# Session state bootstrap
# --------------------------------------------------
def _init_state():
    defaults = {
        "messages":     [],
        "stage":        "ask_cpo",
        "cpo":          None,
        "ordered_item": None,
        "qty":          None,
        "item_rows":    [], "item_chosen":  None,
        "price_rows":   [], "price_chosen": None,
        "term_rows":    [], "term_chosen":  None,
        "rep_rows":     [], "rep_chosen":   None,
        "site_rows":    [], "site_chosen":  None,
        "db":           None,
        "order_done":   False,
        "api_result":   None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# --------------------------------------------------
# Chat helpers
# --------------------------------------------------
def assistant_say(msg: str):
    st.session_state.messages.append({"role": "assistant", "content": msg})

def user_say(msg: str):
    st.session_state.messages.append({"role": "user", "content": msg})

# --------------------------------------------------
# ERP response parser  (ported from reference file)
# --------------------------------------------------
def extract_erp_details(result: dict) -> dict:
    data = result.get("OutputParameters", result)

    status       = data.get("X_RETURN_STATUS", "N/A")
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

    header     = data.get("X_HEADER_REC",     {}) or {}
    header_val = data.get("X_HEADER_VAL_REC", {}) or {}

    header_details = {
        # ── Order Identity ─────────────────────────────
        "Order Number":          header.get("ORDER_NUMBER",              "N/A"),
        "Header ID":             header.get("HEADER_ID",                 "N/A"),
        "Customer PO":           header.get("CUST_PO_NUMBER",            "N/A"),
        "Orig Sys Document Ref": header.get("ORIG_SYS_DOCUMENT_REF",     "N/A"),
        # ── Status & Dates ─────────────────────────────
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
        # ── Financial ──────────────────────────────────
        "Currency":              header.get("TRANSACTIONAL_CURR_CODE",   "N/A"),
        "Payment Term ID":       header.get("PAYMENT_TERM_ID",           "N/A"),
        "Payment Term":          header_val.get("PAYMENT_TERM",          "N/A"),
        "Price List ID":         header.get("PRICE_LIST_ID",             "N/A"),
        "Price List":            header_val.get("PRICE_LIST",            "N/A"),
        # ── Org & Type ─────────────────────────────────
        "Org ID":                header.get("ORG_ID",                    "N/A"),
        "Order Type ID":         header.get("ORDER_TYPE_ID",             "N/A"),
        "Order Type":            header_val.get("ORDER_TYPE",            "N/A"),
        "Order Source ID":       header.get("ORDER_SOURCE_ID",           "N/A"),
        "Order Source":          header_val.get("ORDER_SOURCE",          "N/A"),
        # ── Parties ────────────────────────────────────
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
        # ── Sales ──────────────────────────────────────
        "Salesrep ID":           header.get("SALESREP_ID",               "N/A"),
        "Salesrep":              header_val.get("SALESREP",              "N/A"),
        "Demand Class":          header_val.get("DEMAND_CLASS",          "N/A"),
        # ── Shipping ───────────────────────────────────
        "Ship From Org":         header_val.get("SHIP_FROM_ORG",         "N/A"),
        "Freight Carrier":       header_val.get("FREIGHT_CARRIER",       "N/A"),
        "Shipping Method":       header_val.get("SHIPPING_METHOD",       "N/A"),
        "FOB Point":             header_val.get("FOB_POINT",             "N/A"),
        "Freight Terms":         header_val.get("FREIGHT_TERMS",         "N/A"),
        # ── Misc ───────────────────────────────────────
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
            # ── Identity ───────────────────────────────
            "Line #":               line.get("LINE_NUMBER",              "N/A"),
            "Line ID":              line.get("LINE_ID",                  "N/A"),
            "Header ID":            line.get("HEADER_ID",                "N/A"),
            "Shipment #":           line.get("SHIPMENT_NUMBER",          "N/A"),
            "Orig Sys Line Ref":    line.get("ORIG_SYS_LINE_REF",        "N/A"),
            # ── Item ───────────────────────────────────
            "Item":                 line.get("ORDERED_ITEM",             "N/A"),
            "Item Description":     val.get("INVENTORY_ITEM",            "N/A"),
            "Inventory Item ID":    line.get("INVENTORY_ITEM_ID",        "N/A"),
            "Item Type":            line.get("ITEM_TYPE_CODE",           "N/A"),
            # ── Quantity & Price ───────────────────────
            "Qty Ordered":          line.get("ORDERED_QUANTITY",         "N/A"),
            "Qty Cancelled":        line.get("CANCELLED_QUANTITY",       "N/A"),
            "UOM":                  line.get("ORDER_QUANTITY_UOM",       "N/A"),
            "Pricing Qty":          line.get("PRICING_QUANTITY",         "N/A"),
            "Unit List Price":      line.get("UNIT_LIST_PRICE",          "N/A"),
            "Unit Selling Price":   line.get("UNIT_SELLING_PRICE",       "N/A"),
            # ── Dates ──────────────────────────────────
            "Request Date":         line.get("REQUEST_DATE",             "N/A"),
            "Promise Date":         line.get("PROMISE_DATE",             "N/A"),
            "Earliest Accept Date": line.get("EARLIEST_ACCEPTABLE_DATE", "N/A"),
            "Latest Accept Date":   line.get("LATEST_ACCEPTABLE_DATE",   "N/A"),
            "Pricing Date":         line.get("PRICING_DATE",             "N/A"),
            # ── Status ─────────────────────────────────
            "Return Status":        line.get("RETURN_STATUS",            "N/A"),
            "Flow Status":          line.get("FLOW_STATUS_CODE",         "N/A"),
            "Line Category":        line.get("LINE_CATEGORY_CODE",       "N/A"),
            "Open Flag":            line.get("OPEN_FLAG",                "N/A"),
            "Booked Flag":          line.get("BOOKED_FLAG",              "N/A"),
            "Cancelled Flag":       line.get("CANCELLED_FLAG",           "N/A"),
            "Shippable Flag":       line.get("SHIPPABLE_FLAG",           "N/A"),
            "Operation":            line.get("OPERATION",                "N/A"),
            # ── Line Type & Pricing ────────────────────
            "Line Type ID":         line.get("LINE_TYPE_ID",             "N/A"),
            "Line Type":            val.get("LINE_TYPE",                 "N/A"),
            "Payment Term":         val.get("PAYMENT_TERM",              "N/A"),
            "Price List":           val.get("PRICE_LIST",                "N/A"),
            "Calculate Price Flag": line.get("CALCULATE_PRICE_FLAG",     "N/A"),
            # ── Shipping ───────────────────────────────
            "Ship To Org":          val.get("SHIP_TO_ORG",               "N/A"),
            "Ship To Address":      val.get("SHIP_TO_ADDRESS1",          "N/A"),
            "Ship To City":         val.get("SHIP_TO_CITY",              "N/A"),
            "Ship To State":        val.get("SHIP_TO_STATE",             "N/A"),
            "Ship To Country":      val.get("SHIP_TO_COUNTRY",           "N/A"),
            "Ship From Org":        val.get("SHIP_FROM_ORG",             "N/A"),
            "Shipping Method":      val.get("SHIPPING_METHOD",           "N/A"),
            "Freight Carrier":      val.get("FREIGHT_CARRIER",           "N/A"),
            "Source Type":          val.get("SOURCE_TYPE",               "N/A"),
            "Ship Tolerance Above": line.get("SHIP_TOLERANCE_ABOVE",     "N/A"),
            "Ship Tolerance Below": line.get("SHIP_TOLERANCE_BELOW",     "N/A"),
            # ── Tax ────────────────────────────────────
            "Tax Code":             line.get("TAX_CODE",                 "N/A"),
            "Tax Exempt Flag":      line.get("TAX_EXEMPT_FLAG",          "N/A"),
            # ── Audit ──────────────────────────────────
            "Created By":           line.get("CREATED_BY",               "N/A"),
            "Creation Date":        line.get("CREATION_DATE",            "N/A"),
            "Last Updated By":      line.get("LAST_UPDATED_BY",          "N/A"),
            "Last Update Date":     line.get("LAST_UPDATE_DATE",         "N/A"),
        })

    return {
        "status":         status,
        "message":        message_text,
        "header_details": header_details,
        "lines":          lines,
    }


# --------------------------------------------------
# ERP response renderer  (ported from reference file)
# --------------------------------------------------
def display_erp_response(result: dict):
    d = extract_erp_details(result)

    status_val = str(d["status"]).upper()
    if status_val == "S":
        emoji, status_label = "✅", "Success"
    elif status_val == "E":
        emoji, status_label = "❌", "Error"
    elif status_val == "W":
        emoji, status_label = "⚠️", "Warning"
    else:
        emoji, status_label = "ℹ️", status_val

    banner = (
        f"{emoji} **Order {status_label}!** &nbsp;|&nbsp; "
        f"Order # `{d['header_details'].get('Order Number', 'N/A')}` &nbsp;|&nbsp; "
        f"Header ID `{d['header_details'].get('Header ID', 'N/A')}`"
    )
    assistant_say(banner)
    st.markdown(banner)

    # ── ERP Messages ──────────────────────────────────────────
    if d["message"] and d["message"] != "N/A":
        st.markdown("### 💬 ERP Messages")
        for msg in d["message"].split(" | "):
            if msg.strip():
                st.warning(msg.strip())

    # ── HEADER DETAILS ────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 🧾 Header Details")

    hd = d["header_details"]
    header_sections = {
        "📋 Order Identity": {
            "Order Number":          hd.get("Order Number"),
            "Header ID":             hd.get("Header ID"),
            "Customer PO":           hd.get("Customer PO"),
            "Orig Sys Document Ref": hd.get("Orig Sys Document Ref"),
            "Order Category":        hd.get("Order Category"),
            "Order Type":            hd.get("Order Type"),
            "Order Source":          hd.get("Order Source"),
            "Transaction Phase":     hd.get("Transaction Phase"),
            "Operation":             hd.get("Operation"),
        },
        "📅 Dates & Status": {
            "Return Status":  hd.get("Return Status"),
            "Flow Status":    hd.get("Flow Status"),
            "Booked Flag":    hd.get("Booked Flag"),
            "Open Flag":      hd.get("Open Flag"),
            "Cancelled Flag": hd.get("Cancelled Flag"),
            "Ordered Date":   hd.get("Ordered Date"),
            "Request Date":   hd.get("Request Date"),
            "Pricing Date":   hd.get("Pricing Date"),
        },
        "💰 Financial": {
            "Currency":        hd.get("Currency"),
            "Payment Term":    hd.get("Payment Term"),
            "Price List":      hd.get("Price List"),
            "Tax Exempt Flag": hd.get("Tax Exempt Flag"),
        },
        "🏢 Parties": {
            "Customer":        hd.get("Customer"),
            "Customer Number": hd.get("Customer Number"),
            "Ship To":         hd.get("Ship To"),
            "Ship To Address": hd.get("Ship To Address"),
            "Ship To City":    hd.get("Ship To City"),
            "Ship To State":   hd.get("Ship To State"),
            "Ship To Zip":     hd.get("Ship To Zip"),
            "Ship To Country": hd.get("Ship To Country"),
            "Bill To":         hd.get("Bill To"),
            "Bill To Address": hd.get("Bill To Address"),
            "Bill To City":    hd.get("Bill To City"),
            "Bill To State":   hd.get("Bill To State"),
            "Bill To Zip":     hd.get("Bill To Zip"),
            "Bill To Country": hd.get("Bill To Country"),
            "Salesrep":        hd.get("Salesrep"),
            "Demand Class":    hd.get("Demand Class"),
        },
        "🚚 Shipping": {
            "Ship From Org":   hd.get("Ship From Org"),
            "Freight Carrier": hd.get("Freight Carrier"),
            "Shipping Method": hd.get("Shipping Method"),
            "FOB Point":       hd.get("FOB Point"),
            "Freight Terms":   hd.get("Freight Terms"),
        },
        "🔧 System Info": {
            "Org ID":           hd.get("Org ID"),
            "Order Type ID":    hd.get("Order Type ID"),
            "Order Source ID":  hd.get("Order Source ID"),
            "Payment Term ID":  hd.get("Payment Term ID"),
            "Price List ID":    hd.get("Price List ID"),
            "Salesrep ID":      hd.get("Salesrep ID"),
            "Version Number":   hd.get("Version Number"),
            "Lock Control":     hd.get("Lock Control"),
            "XML Message ID":   hd.get("XML Message ID"),
            "Created By":       hd.get("Created By"),
            "Creation Date":    hd.get("Creation Date"),
            "Last Updated By":  hd.get("Last Updated By"),
            "Last Update Date": hd.get("Last Update Date"),
        },
    }

    h_tabs = st.tabs(list(header_sections.keys()))
    for tab, (_, fields) in zip(h_tabs, header_sections.items()):
        with tab:
            rows = "\n".join(
                f"| **{k}** | {v} |"
                for k, v in fields.items()
                if v and v != "N/A"
            )
            if rows:
                st.markdown(f"| Field | Value |\n|---|---|\n{rows}")
            else:
                st.info("No data available in this section.")

    # ── LINE DETAILS ──────────────────────────────────────────
    st.markdown("---")
    st.markdown("## 📦 Line Details")

    if d["lines"]:
        line_sections = {
            "📋 Identity": [
                "Line #", "Line ID", "Header ID", "Shipment #",
                "Orig Sys Line Ref", "Item", "Item Description",
                "Inventory Item ID", "Item Type",
            ],
            "📦 Quantity & Price": [
                "Qty Ordered", "Qty Cancelled", "UOM", "Pricing Qty",
                "Unit List Price", "Unit Selling Price", "Calculate Price Flag",
            ],
            "📅 Dates": [
                "Request Date", "Promise Date", "Earliest Accept Date",
                "Latest Accept Date", "Pricing Date",
            ],
            "🔖 Status": [
                "Return Status", "Flow Status", "Line Category",
                "Open Flag", "Booked Flag", "Cancelled Flag",
                "Shippable Flag", "Operation",
            ],
            "💰 Type & Pricing": [
                "Line Type ID", "Line Type", "Payment Term",
                "Price List", "Tax Code", "Tax Exempt Flag",
            ],
            "🚚 Shipping": [
                "Ship To Org", "Ship To Address", "Ship To City",
                "Ship To State", "Ship To Country", "Ship From Org",
                "Shipping Method", "Freight Carrier", "Source Type",
                "Ship Tolerance Above", "Ship Tolerance Below",
            ],
            "🔧 System Info": [
                "Created By", "Creation Date",
                "Last Updated By", "Last Update Date",
            ],
        }

        l_tabs = st.tabs(list(line_sections.keys()))
        for tab, (_, keys) in zip(l_tabs, line_sections.items()):
            with tab:
                for li, line in enumerate(d["lines"]):
                    if len(d["lines"]) > 1:
                        st.markdown(f"**Line {line.get('Line #', li + 1)}**")
                    rows = "\n".join(
                        f"| **{k}** | {line.get(k, 'N/A')} |"
                        for k in keys
                        if line.get(k) and line.get(k) != "N/A"
                    )
                    if rows:
                        st.markdown(f"| Field | Value |\n|---|---|\n{rows}")
                    else:
                        st.info("No data available in this section.")
    else:
        st.info("ℹ️ No line details found in the response.")

    # ── Raw Response ──────────────────────────────────────────
    st.markdown("---")
    with st.expander("🔍 View Full Raw API Response"):
        st.json(result)


# --------------------------------------------------
# Render chat history
# --------------------------------------------------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# --------------------------------------------------
# Stage machine
# --------------------------------------------------
stage = st.session_state.stage

# ── STAGE: ask_cpo ────────────────────────────────
if stage == "ask_cpo":
    if not any(m["role"] == "assistant" for m in st.session_state.messages):
        assistant_say("Hello! I can help you create a Sales Order.\n\nWhat is the **Customer PO Number**?")
        st.rerun()

    if prompt := st.chat_input("Enter Customer PO Number..."):
        user_say(prompt)
        st.session_state.cpo = prompt.strip()
        assistant_say(f"Got it — PO: **{st.session_state.cpo}**.\n\nWhat is the **Ordered Item** (e.g. `CM94532`)?")
        st.session_state.stage = "ask_item"
        st.rerun()

# ── STAGE: ask_item ───────────────────────────────
elif stage == "ask_item":
    if prompt := st.chat_input("Enter Ordered Item code..."):
        user_say(prompt)
        st.session_state.ordered_item = prompt.strip().upper()
        assistant_say(f"Item: **{st.session_state.ordered_item}**.\n\nWhat is the **Ordered Quantity**?")
        st.session_state.stage = "ask_qty"
        st.rerun()

# ── STAGE: ask_qty ────────────────────────────────
elif stage == "ask_qty":
    if prompt := st.chat_input("Enter Quantity..."):
        user_say(prompt)
        qty = bot.parse_numeric_value(prompt, allow_float=False)
        if qty is None:
            assistant_say("⚠️ That doesn't look like a valid number. Please enter the **Quantity** again.")
            st.rerun()
        else:
            st.session_state.qty = float(qty)
            assistant_say(f"Quantity: **{int(qty)}**.\n\n⏳ Looking up inventory item...")
            st.session_state.stage = "lookup_item"
            st.rerun()

# ── STAGE: lookup_item ────────────────────────────
elif stage == "lookup_item":
    try:
        sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, ORGANIZATION_ID
              FROM MTL_SYSTEM_ITEMS_B
             WHERE SEGMENT1        = :ordered_item
               AND ORGANIZATION_ID = :org_id
               AND ROWNUM          <= :max_rows
        """
        with bot.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, ordered_item=st.session_state.ordered_item,
                            org_id=bot.ORG_ID, max_rows=bot.MAX_CHOICES)
                rows = cur.fetchall()

        if not rows:
            assistant_say(f"❌ Item **{st.session_state.ordered_item}** not found. Please re-enter the item.")
            st.session_state.stage = "ask_item"
            st.rerun()

        dicts = [{"inventory_item_id": int(r[0]), "segment1": r[1],
                  "description": r[2] or "", "organization_id": int(r[3])} for r in rows]
        st.session_state.item_rows = dicts

        if len(dicts) == 1:
            st.session_state.item_chosen = dicts[0]
            assistant_say(f"✅ **Inventory Item** auto-selected: `{dicts[0]['segment1']}` — {dicts[0]['description']}")
            st.session_state.stage = "lookup_price"
        else:
            assistant_say(f"Found **{len(dicts)}** inventory items. Please select one below.")
            st.session_state.stage = "select_item"
        st.rerun()

    except Exception as e:
        assistant_say(f"❌ DB error during item lookup: `{e}`")
        st.session_state.stage = "ask_item"
        st.rerun()

# ── STAGE: select_item ────────────────────────────
elif stage == "select_item":
    rows = st.session_state.item_rows
    options = [f"[{i+1}] ID={r['inventory_item_id']}  Segment={r['segment1']}  Desc={r['description']}"
               for i, r in enumerate(rows)]
    choice = st.radio("**Select Inventory Item:**", options, key="radio_item")
    if st.button("Confirm Item Selection", key="btn_item"):
        idx = options.index(choice)
        st.session_state.item_chosen = rows[idx]
        user_say(f"Selected Item: {choice}")
        assistant_say(f"✅ Item confirmed: `{rows[idx]['segment1']}` — {rows[idx]['description']}")
        st.session_state.stage = "lookup_price"
        st.rerun()

# ── STAGE: lookup_price ───────────────────────────
elif stage == "lookup_price":
    item_id_str = str(st.session_state.item_chosen["inventory_item_id"])

    sql_order_type = """
        SELECT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND
          FROM OE_ORDER_TYPES_V      oot
          JOIN QP_LIST_HEADERS_B     qlh ON qlh.LIST_HEADER_ID = oot.PRICE_LIST_ID
          JOIN QP_LIST_HEADERS_TL    qlt ON qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID
                                        AND qlt.LANGUAGE = USERENV('LANG')
          JOIN QP_LIST_LINES         qll ON qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES qpa ON qpa.LIST_LINE_ID = qll.LIST_LINE_ID
                                        AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                                        AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
         WHERE oot.ORDER_TYPE_ID = :order_type_id AND qlh.ACTIVE_FLAG = 'Y'
           AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE)
           AND (qll.END_DATE_ACTIVE   IS NULL OR qll.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
    """
    sql_customer = """
        SELECT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND
          FROM HZ_CUST_ACCT_SITES_ALL  hcas
          JOIN HZ_CUST_SITE_USES_ALL   hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
                                           AND hcsu.SITE_USE_CODE = 'BILL_TO' AND hcsu.STATUS = 'A'
          JOIN QP_LIST_HEADERS_B       qlh  ON qlh.LIST_HEADER_ID = hcsu.PRICE_LIST_ID
          JOIN QP_LIST_HEADERS_TL      qlt  ON qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID
                                           AND qlt.LANGUAGE = USERENV('LANG')
          JOIN QP_LIST_LINES           qll  ON qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES   qpa  ON qpa.LIST_LINE_ID = qll.LIST_LINE_ID
                                           AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                                           AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
         WHERE hcas.ORG_ID = :org_id AND hcas.STATUS = 'A'
           AND qlh.ACTIVE_FLAG = 'Y' AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
    """
    sql_generic = """
        SELECT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND
          FROM QP_LIST_HEADERS_B     qlh
          JOIN QP_LIST_HEADERS_TL    qlt ON qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID
                                        AND qlt.LANGUAGE = USERENV('LANG')
          JOIN QP_LIST_LINES         qll ON qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES qpa ON qpa.LIST_LINE_ID = qll.LIST_LINE_ID
                                        AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                                        AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
         WHERE qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL'
           AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND (qll.START_DATE_ACTIVE IS NULL OR qll.START_DATE_ACTIVE <= SYSDATE)
           AND (qll.END_DATE_ACTIVE   IS NULL OR qll.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
         ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
    """
    try:
        rows, source = [], ""
        with bot.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_order_type, item_id_str=item_id_str,
                            order_type_id=bot.ORDER_TYPE_ID, max_rows=bot.MAX_CHOICES)
                rows = cur.fetchall()
                if rows:
                    source = f"Order Type ({bot.ORDER_TYPE_ID})"
                if not rows:
                    cur.execute(sql_customer, item_id_str=item_id_str,
                                org_id=bot.ORG_ID, max_rows=bot.MAX_CHOICES)
                    rows = cur.fetchall()
                    if rows: source = "Customer Bill-To Site"
                if not rows:
                    cur.execute(sql_generic, item_id_str=item_id_str, max_rows=bot.MAX_CHOICES)
                    rows = cur.fetchall()
                    if rows: source = "Generic Active Price List"

        if not rows:
            assistant_say(f"❌ No price list found for item ID `{item_id_str}`. Cannot continue.")
            st.session_state.stage = "error"; st.rerun()

        dicts = [{"price_list_id": int(r[0]), "price_list_name": r[1] or "",
                  "unit_list_price": float(r[2])} for r in rows]
        st.session_state.price_rows = dicts

        if len(dicts) == 1:
            st.session_state.price_chosen = dicts[0]
            assistant_say(f"✅ **Price List** auto-selected (source: {source}): "
                          f"`{dicts[0]['price_list_name']}` — ${dicts[0]['unit_list_price']:.2f}")
            st.session_state.stage = "lookup_term"
        else:
            assistant_say(f"Found **{len(dicts)}** price lists (source: {source}). Please select one below.")
            st.session_state.stage = "select_price"
        st.rerun()

    except Exception as e:
        assistant_say(f"❌ DB error during price list lookup: `{e}`")
        st.session_state.stage = "error"; st.rerun()

# ── STAGE: select_price ───────────────────────────
elif stage == "select_price":
    rows = st.session_state.price_rows
    options = [f"[{i+1}] ID={r['price_list_id']}  Name={r['price_list_name']}  Price=${r['unit_list_price']:.2f}"
               for i, r in enumerate(rows)]
    choice = st.radio("**Select Price List:**", options, key="radio_price")
    if st.button("Confirm Price List Selection", key="btn_price"):
        idx = options.index(choice)
        st.session_state.price_chosen = rows[idx]
        user_say(f"Selected Price List: {choice}")
        assistant_say(f"✅ Price List confirmed: `{rows[idx]['price_list_name']}` — ${rows[idx]['unit_list_price']:.2f}")
        st.session_state.stage = "lookup_term"; st.rerun()

# ── STAGE: lookup_term ────────────────────────────
elif stage == "lookup_term":
    sql_cust = """
        SELECT DISTINCT hcsu.PAYMENT_TERM_ID, rt.NAME
          FROM HZ_CUST_ACCT_SITES_ALL hcas
          JOIN HZ_CUST_SITE_USES_ALL  hcsu ON hcsu.CUST_ACCT_SITE_ID = hcas.CUST_ACCT_SITE_ID
          JOIN RA_TERMS_B             rt   ON rt.TERM_ID = hcsu.PAYMENT_TERM_ID
         WHERE hcsu.SITE_USE_CODE = 'BILL_TO' AND hcsu.STATUS = 'A'
           AND hcas.STATUS = 'A' AND hcas.ORG_ID = :org_id
           AND hcsu.PAYMENT_TERM_ID IS NOT NULL AND ROWNUM <= :max_rows
    """
    sql_fall = """
        SELECT TERM_ID, NAME FROM RA_TERMS_B
         WHERE ENABLED_FLAG = 'Y' AND ROWNUM <= :max_rows ORDER BY TERM_ID
    """
    try:
        rows = []
        with bot.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_cust, org_id=bot.ORG_ID, max_rows=bot.MAX_CHOICES)
                rows = cur.fetchall()
        if not rows:
            with bot.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql_fall, max_rows=bot.MAX_CHOICES)
                    rows = cur.fetchall()

        if not rows:
            assistant_say("❌ No payment terms found. Cannot continue.")
            st.session_state.stage = "error"; st.rerun()

        dicts = [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]
        st.session_state.term_rows = dicts

        if len(dicts) == 1:
            st.session_state.term_chosen = dicts[0]
            assistant_say(f"✅ **Payment Term** auto-selected: `{dicts[0]['term_name']}`")
            st.session_state.stage = "lookup_rep"
        else:
            assistant_say(f"Found **{len(dicts)}** payment terms. Please select one below.")
            st.session_state.stage = "select_term"
        st.rerun()

    except Exception as e:
        assistant_say(f"❌ DB error during payment term lookup: `{e}`")
        st.session_state.stage = "error"; st.rerun()

# ── STAGE: select_term ────────────────────────────
elif stage == "select_term":
    rows = st.session_state.term_rows
    options = [f"[{i+1}] ID={r['term_id']}  Name={r['term_name']}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Payment Term:**", options, key="radio_term")
    if st.button("Confirm Payment Term", key="btn_term"):
        idx = options.index(choice)
        st.session_state.term_chosen = rows[idx]
        user_say(f"Selected Payment Term: {choice}")
        assistant_say(f"✅ Payment Term confirmed: `{rows[idx]['term_name']}`")
        st.session_state.stage = "lookup_rep"; st.rerun()

# ── STAGE: lookup_rep ─────────────────────────────
elif stage == "lookup_rep":
    sql = """
        SELECT jrs.SALESREP_ID, jrs.NAME
          FROM JTF_RS_SALESREPS jrs
         WHERE jrs.ORG_ID = :org_id AND jrs.STATUS = 'A'
           AND jrs.END_DATE_ACTIVE IS NULL AND ROWNUM <= :max_rows
         ORDER BY jrs.SALESREP_ID
    """
    try:
        with bot.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, org_id=bot.ORG_ID, max_rows=bot.MAX_CHOICES)
                rows = cur.fetchall()

        if not rows:
            assistant_say(f"❌ No active sales reps found for ORG_ID={bot.ORG_ID}. Cannot continue.")
            st.session_state.stage = "error"; st.rerun()

        dicts = [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]
        st.session_state.rep_rows = dicts

        if len(dicts) == 1:
            st.session_state.rep_chosen = dicts[0]
            assistant_say(f"✅ **Sales Rep** auto-selected: `{dicts[0]['salesrep_name']}`")
            st.session_state.stage = "lookup_site"
        else:
            assistant_say(f"Found **{len(dicts)}** sales reps. Please select one below.")
            st.session_state.stage = "select_rep"
        st.rerun()

    except Exception as e:
        assistant_say(f"❌ DB error during sales rep lookup: `{e}`")
        st.session_state.stage = "error"; st.rerun()

# ── STAGE: select_rep ─────────────────────────────
elif stage == "select_rep":
    rows = st.session_state.rep_rows
    options = [f"[{i+1}] ID={r['salesrep_id']}  Name={r['salesrep_name']}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Sales Rep:**", options, key="radio_rep")
    if st.button("Confirm Sales Rep", key="btn_rep"):
        idx = options.index(choice)
        st.session_state.rep_chosen = rows[idx]
        user_say(f"Selected Sales Rep: {choice}")
        assistant_say(f"✅ Sales Rep confirmed: `{rows[idx]['salesrep_name']}`")
        st.session_state.stage = "lookup_site"; st.rerun()

# ── STAGE: lookup_site ────────────────────────────
elif stage == "lookup_site":
    sql = """
        SELECT hca.CUST_ACCOUNT_ID, hcsu.SITE_USE_ID, hp.PARTY_NAME, hcas.ORG_ID
          FROM MTL_SYSTEM_ITEMS_B     msi
          JOIN HZ_CUST_ACCT_SITES_ALL hcas ON hcas.ORG_ID = :org_id
          JOIN HZ_CUST_SITE_USES_ALL  hcsu ON hcas.CUST_ACCT_SITE_ID = hcsu.CUST_ACCT_SITE_ID
          JOIN HZ_CUST_ACCOUNTS       hca  ON hcas.CUST_ACCOUNT_ID = hca.CUST_ACCOUNT_ID
          JOIN HZ_PARTIES             hp   ON hca.PARTY_ID = hp.PARTY_ID
         WHERE msi.SEGMENT1 = :ordered_item AND msi.ORGANIZATION_ID = :org_id
           AND hcsu.SITE_USE_CODE = 'SHIP_TO' AND hcsu.STATUS = 'A'
           AND hcas.STATUS = 'A' AND hca.STATUS = 'A'
           AND hcsu.PRIMARY_FLAG = 'Y' AND ROWNUM <= :max_rows
    """
    try:
        with bot.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, ordered_item=st.session_state.ordered_item,
                            org_id=bot.ORG_ID, max_rows=bot.MAX_CHOICES)
                rows = cur.fetchall()

        if not rows:
            assistant_say(f"❌ No active SHIP_TO sites found for item `{st.session_state.ordered_item}`.")
            st.session_state.stage = "error"; st.rerun()

        dicts = [{"sold_to_org_id": int(r[0]), "ship_to_org_id": int(r[1]),
                  "customer_name": r[2] or "", "operating_unit_id": int(r[3])} for r in rows]
        st.session_state.site_rows = dicts

        if len(dicts) == 1:
            st.session_state.site_chosen = dicts[0]
            assistant_say(f"✅ **Customer Site** auto-selected: `{dicts[0]['customer_name']}` "
                          f"(SoldTo: {dicts[0]['sold_to_org_id']}, ShipTo: {dicts[0]['ship_to_org_id']})")
            st.session_state.stage = "confirm_order"
        else:
            assistant_say(f"Found **{len(dicts)}** customer sites. Please select one below.")
            st.session_state.stage = "select_site"
        st.rerun()

    except Exception as e:
        assistant_say(f"❌ DB error during customer site lookup: `{e}`")
        st.session_state.stage = "error"; st.rerun()

# ── STAGE: select_site ────────────────────────────
elif stage == "select_site":
    rows = st.session_state.site_rows
    options = [f"[{i+1}] Customer={r['customer_name']}  SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}"
               for i, r in enumerate(rows)]
    choice = st.radio("**Select Customer Site:**", options, key="radio_site")
    if st.button("Confirm Customer Site", key="btn_site"):
        idx = options.index(choice)
        st.session_state.site_chosen = rows[idx]
        user_say(f"Selected Customer Site: {choice}")
        assistant_say(f"✅ Customer Site confirmed: `{rows[idx]['customer_name']}`")
        st.session_state.stage = "confirm_order"; st.rerun()

# ── STAGE: confirm_order ──────────────────────────
elif stage == "confirm_order":
    ic = st.session_state.item_chosen
    pc = st.session_state.price_chosen
    tc = st.session_state.term_chosen
    rc = st.session_state.rep_chosen
    sc = st.session_state.site_chosen

    summary = f"""
**Order Summary — please review before submitting:**

| Field | Value |
|---|---|
| Customer PO | `{st.session_state.cpo}` |
| Ordered Item | `{st.session_state.ordered_item}` |
| Quantity | `{int(st.session_state.qty)}` |
| Inventory Item ID | `{ic['inventory_item_id']}` |
| Price List | `{pc['price_list_name']}` (ID: {pc['price_list_id']}) |
| Unit Price | `${pc['unit_list_price']:.2f}` |
| Payment Term | `{tc['term_name']}` (ID: {tc['term_id']}) |
| Sales Rep | `{rc['salesrep_name']}` (ID: {rc['salesrep_id']}) |
| Customer | `{sc['customer_name']}` |
| Sold-To Org | `{sc['sold_to_org_id']}` |
| Ship-To Org | `{sc['ship_to_org_id']}` |
| Operating Unit | `{bot.OPERATING_UNIT}` |
"""
    if not any("Order Summary" in m["content"] for m in st.session_state.messages):
        assistant_say(summary)
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Submit Order", key="btn_submit"):
            st.session_state.stage = "submit_order"; st.rerun()
    with col2:
        if st.button("🔄 Start Over", key="btn_restart"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

# ── STAGE: submit_order ───────────────────────────
elif stage == "submit_order":
    ic = st.session_state.item_chosen
    pc = st.session_state.price_chosen
    tc = st.session_state.term_chosen
    rc = st.session_state.rep_chosen
    sc = st.session_state.site_chosen

    with st.spinner("⏳ Submitting order to ERP..."):
        try:
            payload = bot.create_payload(
                p_cust_po         = st.session_state.cpo,
                p_item_id         = ic["inventory_item_id"],
                p_ordered_item    = st.session_state.ordered_item,
                p_qty             = st.session_state.qty,
                p_price           = pc["unit_list_price"],
                p_selling_price   = pc["unit_list_price"],
                p_payment_term_id = tc["term_id"],
                p_price_list_id   = pc["price_list_id"],
                p_salesrep_id     = rc["salesrep_id"],
                p_ship_to_org     = sc["ship_to_org_id"],
                p_sold_to_org     = sc["sold_to_org_id"],
                p_operating_unit  = bot.OPERATING_UNIT,
            )
            result = bot.send_order(payload)
            st.session_state.api_result = result
            st.session_state.stage = "done"
            st.rerun()

        except Exception as e:
            assistant_say(f"❌ Order submission failed: `{e}`")
            st.session_state.stage = "error"; st.rerun()

# ── STAGE: done ───────────────────────────────────
elif stage == "done":
    result = st.session_state.get("api_result", {})

    # Render full header + line details using the reference parser/renderer
    display_erp_response(result)

    st.markdown("---")
    if st.button("🔄 Create Another Order", key="btn_new"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ── STAGE: error ──────────────────────────────────
elif stage == "error":
    if st.button("🔄 Start Over", key="btn_error_restart"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()