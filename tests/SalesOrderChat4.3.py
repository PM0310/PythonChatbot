import streamlit as st
import SalesOrderBot15 as bot
import json
import pandas as pd
import re

st.set_page_config(page_title="Sales Order Assistant", page_icon="📦", layout="wide")
st.markdown("""
    <style>
    /* 1. Set main background to white */
    .stApp {
        background-color: #FFFFFF;
    }

    /* 2. Reset default Streamlit chat row backgrounds */
    [data-testid="stChatMessage"] {
        background-color: transparent !important;
        display: flex !important;
        width: 100% !important;
        margin-bottom: 10px;
        gap: 0px !important;
    }

    /* 3. HIDE AVATARS (Icons) */
    [data-testid="stChatMessageAvatarAssistant"], 
    [data-testid="stChatMessageAvatarUser"] {
        display: none !important;
    }

    /* 4. AI Assistant: LEFT Aligned, Grey Bubble, Black Text */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        flex-direction: row !important; 
        justify-content: flex-start !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
        background-color: #E9ECEF !important;
        color: #000000 !important;
        border-radius: 0px 15px 15px 15px !important; 
        padding: 12px 18px !important;
        margin-left: 0px !important;
        max-width: 75% !important;
        flex-grow: 0 !important;
    }

    /* 5. User: RIGHT Aligned, Orange Bubble, White Text */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        flex-direction: row-reverse !important; 
        justify-content: flex-start !important;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background-color: #FF8C00 !important;
        color: #FFFFFF !important;
        border-radius: 15px 0px 15px 15px !important; 
        padding: 12px 18px !important;
        margin-right: 0px !important;
        max-width: 75% !important;
        flex-grow: 0 !important;
        text-align: left !important;
    }

    /* 6. Force text and Markdown elements to inherit bubble colors */
    [data-testid="stChatMessage"] div.stMarkdown p, 
    [data-testid="stChatMessage"] div.stMarkdown h1,
    [data-testid="stChatMessage"] div.stMarkdown h2,
    [data-testid="stChatMessage"] div.stMarkdown h3 {
        color: inherit !important;
    }

    /* 7. Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #F8F9FA;
        border-right: 1px solid #E0E0E0;
    }
    [data-testid="stCaptionContainer"] p {
        color: #FF8C00 !important;
        font-weight: 500;
        font-size: 1.5rem;
    }
    
    /* 8. Voice Button Styling */
    .voice-btn {
        width: 100%;
        padding: 10px;
        background-color: #FF8C00;
        color: white;
        border-radius: 10px;
        border: none;
        font-size: 16px;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📦 Sales Order Assistant")
st.caption("🚀 Presented by CENTROID ")

# --------------------------------------------------
# Session state bootstrap
# --------------------------------------------------
def _init_state():
    defaults = {
        "messages":       [],
        "stage":          "chat",
        "action":         None,
        "get_order_num":  None,
        "voice_prompt":   None,
        # --- Pagination Offsets ---
        "offsets": {
            "item": 0, "price": 0, "term": 0, "rep": 0, "site": 0,
            "customer": 0, "customer_by_item": 0, "line_type": 0
        },
        # Accumulated order fields
        "collected": {
            "cpo": None, "ordered_item": None, "quantity": None,
            "order_number": None,
            "inventory_item_id": None,
            "price_list_id": None, "price_list_name": None,
            "unit_list_price": None, "unit_selling_price": None,
            "payment_term_id": None, "payment_term_name": None,
            "salesrep_id": None, "salesrep_name": None,
            "sold_to_org_id": None, "ship_to_org_id": None,
            "customer_name": None,
            "cust_account_id": None, 
            "line_type_id": None,
        },
        # Selection UI data
        "item_rows":              [],
        "price_rows":             [],
        "term_rows":              [],
        "rep_rows":               [],
        "site_rows":              [],
        "customer_rows":          [],       
        "customer_by_item_rows":  [],
        "line_type_rows":         [],
        # ERP results
        "api_result":             None,
        "gh_history":             [],
        # Add-line flow state
        "add_line_stage":         None,     
        "add_line_data":          {},       
        "add_line_header_id":     None,     
        "add_line_order_number":  None,     
        "add_line_item_rows":     [],
        "add_line_price_rows":    [],
        "add_line_term_rows":     [],
        "add_line_return":        "done",  
        # Selling price override
        "selling_price_override": False,    
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def assistant_say(msg: str):
    st.session_state.messages.append({"role": "assistant", "content": msg})

def user_say(msg: str):
    st.session_state.messages.append({"role": "user", "content": msg})

def gh_add(role, content):
    st.session_state.gh_history.append({"role": role, "content": content})

def merge_fields(extracted: dict):
    for k, v in extracted.items():
        if k in st.session_state.collected and v is not None:
            st.session_state.collected[k] = v

def missing_minimum() -> list:
    c = st.session_state.collected
    missing = []
    if not c.get("cpo"):
        missing.append("Customer PO Number")
    if not c.get("ordered_item") and not c.get("inventory_item_id"):
        missing.append("Ordered Item code")
    if not c.get("quantity"):
        missing.append("Ordered Quantity")
    if not c.get("line_type_id"):
        missing.append("Line Type ID")
    return missing

# --------------------------------------------------
# UI Helpers for Pagination
# --------------------------------------------------
def render_selection_ui(label, row_key, offset_key, display_fn, on_confirm, next_stage="resolve"):
    rows = st.session_state[row_key]

    if not rows:
        st.warning(f"No {label} records found.")
        if st.button("⬅️ Go Back"):
            st.session_state.stage = "chat"
            st.rerun()
        return

    opts = [f"[{i+1}] {display_fn(r)}" for i, r in enumerate(rows)]
    choice = st.radio(f"**Select {label}:**", opts)

    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if st.button(f"✅ Confirm {label}"):
            idx = opts.index(choice)
            on_confirm(rows[idx])
            st.session_state.stage = next_stage
            st.rerun()

    with col2:
        if len(rows) >= bot.MAX_CHOICES:
            if st.button("📑 Fetch Next Rows"):
                st.session_state.offsets[offset_key] += bot.MAX_CHOICES
                st.session_state.stage = next_stage
                st.rerun()
        if st.session_state.offsets.get(offset_key, 0) > 0:
            if st.button("⬅️ Previous Rows"):
                st.session_state.offsets[offset_key] = max(
                    0, st.session_state.offsets[offset_key] - bot.MAX_CHOICES
                )
                st.session_state.stage = next_stage
                st.rerun()

    with col3:
        if st.button("❌ Cancel"):
            st.session_state.stage = "chat"
            st.rerun()

# --------------------------------------------------
# ERP PARSING & DISPLAY HELPERS
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
        "Order Number":        header.get("ORDER_NUMBER",            "N/A"),
        "Header ID":           header.get("HEADER_ID",               "N/A"),
        "Customer PO":         header.get("CUST_PO_NUMBER",          "N/A"),
        "Return Status":       header.get("RETURN_STATUS",           "N/A"),
        "Flow Status":         header.get("FLOW_STATUS_CODE",        "N/A"),
        "Order Category":      header.get("ORDER_CATEGORY_CODE",     "N/A"),
        "Currency":            header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term":        header_val.get("PAYMENT_TERM",        "N/A"),
        "Price List":          header_val.get("PRICE_LIST",          "N/A"),
        "Order Type":          header_val.get("ORDER_TYPE",          "N/A"),
        "Customer":            header_val.get("SOLD_TO_ORG",         "N/A"),
        "Ship To":             header_val.get("SHIP_TO_ORG",         "N/A"),
        "Bill To":             header_val.get("INVOICE_TO_ORG",      "N/A"),
        "Salesrep":            header_val.get("SALESREP",            "N/A"),
        "Booked Flag":         header.get("BOOKED_FLAG",             "N/A"),
        "Open Flag":           header.get("OPEN_FLAG",               "N/A"),
    }

    line_tbl     = data.get("X_LINE_TBL",     {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}

    def _get_items(tbl, *keys):
        for k in keys:
            v = tbl.get(k)
            if v is not None:
                return [v] if isinstance(v, dict) else list(v)
        return []

    raw_lines     = _get_items(line_tbl,     "X_LINE_TBL_ITEM",     "P_LINE_TBL_ITEM")
    raw_line_vals = _get_items(line_val_tbl, "X_LINE_VAL_TBL_ITEM", "P_LINE_VAL_TBL_ITEM")

    lines = []
    for i, line in enumerate(raw_lines):
        val = raw_line_vals[i] if i < len(raw_line_vals) else {}
        lines.append({
            "Line #":             line.get("LINE_NUMBER",          "N/A"),
            "Line ID":            line.get("LINE_ID",              "N/A"),
            "Item":               line.get("ORDERED_ITEM",         "N/A"),
            "Item Description":   val.get("INVENTORY_ITEM",        "N/A"),
            "Qty Ordered":        line.get("ORDERED_QUANTITY",     "N/A"),
            "UOM":                line.get("ORDER_QUANTITY_UOM",   "N/A"),
            "Unit List Price":    line.get("UNIT_LIST_PRICE",      "N/A"),
            "Unit Selling Price": line.get("UNIT_SELLING_PRICE",   "N/A"),
            "Line Type":          val.get("LINE_TYPE",             "N/A"),
            "Payment Term":       val.get("PAYMENT_TERM",          "N/A"),
            "Flow Status":        line.get("FLOW_STATUS_CODE",     "N/A"),
            "Return Status":      line.get("RETURN_STATUS",        "N/A"),
        })

    return {
        "status":         status,
        "message":        message_text,
        "header_details": header_details,
        "lines":          lines,
    }

def _render_line_section(lines: list, col_keys: list):
    active_cols = [
        k for k in col_keys
        if any(ln.get(k) not in (None, "", "N/A") for ln in lines)
    ]
    if not active_cols:
        st.info("No data available in this section.")
        return
    if len(lines) == 1:
        line = lines[0]
        md_rows = "\n".join(
            f"| **{k}** | {line.get(k, 'N/A')} |"
            for k in active_cols
        )
        st.markdown(f"| Field | Value |\n|---|---|\n{md_rows}")
    else:
        records = []
        for ln in lines:
            row = {"Line #": ln.get("Line #", "N/A")}
            for k in active_cols:
                if k != "Line #":
                    row[k] = ln.get(k, "N/A")
            records.append(row)
        df = pd.DataFrame(records).replace("N/A", "")
        st.dataframe(df, use_container_width=True, hide_index=True)

def display_erp_response(result: dict, context_label: str = "Order"):
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
        f"{emoji} **{context_label} {status_label}!** &nbsp;|&nbsp; "
        f"Order # `{d['header_details'].get('Order Number', 'N/A')}` &nbsp;|&nbsp; "
        f"Header ID `{d['header_details'].get('Header ID', 'N/A')}`"
    )
    assistant_say(banner)
    st.markdown(banner)

    if d["message"] and d["message"] != "N/A":
        st.markdown("### 💬 ERP Messages")
        for msg in d["message"].split(" | "):
            if msg.strip():
                st.warning(msg.strip())

    st.markdown("---")
    st.markdown("## 🧾 Header Details")
    hd = d["header_details"]
    header_sections = {
        "📋 Order Identity": {
            "Order Number": hd.get("Order Number"), "Header ID": hd.get("Header ID"),
            "Customer PO":  hd.get("Customer PO"),  "Order Category": hd.get("Order Category"),
            "Order Type":   hd.get("Order Type")
        },
        "📅 Dates & Status": {
            "Return Status": hd.get("Return Status"), "Flow Status": hd.get("Flow Status"),
            "Booked Flag":   hd.get("Booked Flag"),   "Open Flag":    hd.get("Open Flag"),
            "Ordered Date":  hd.get("Ordered Date")
        },
        "💰 Financial & Parties": {
            "Currency":     hd.get("Currency"),    "Payment Term": hd.get("Payment Term"),
            "Price List":   hd.get("Price List"),  "Customer":     hd.get("Customer"),
            "Ship To":      hd.get("Ship To"),     "Bill To":      hd.get("Bill To"),
            "Salesrep":     hd.get("Salesrep")
        }
    }
    h_tabs = st.tabs(list(header_sections.keys()))
    for tab, (_, fields) in zip(h_tabs, header_sections.items()):
        with tab:
            md_rows = "\n".join(
                f"| **{k}** | {v} |" for k, v in fields.items() if v and v != "N/A"
            )
            if md_rows:
                st.markdown(f"| Field | Value |\n|---|---|\n{md_rows}")
            else:
                st.info("No data available in this section.")

    st.markdown("---")
    n_lines = len(d["lines"])
    st.markdown(
        f"## 📦 Line Details "
        f"<span style='font-size:0.85rem;color:gray;'>({n_lines} line{'s' if n_lines!=1 else ''})</span>",
        unsafe_allow_html=True,
    )
    if d["lines"]:
        line_sections = {
            "📋 Identity":       ["Line #", "Line ID", "Item", "Item Description"],
            "📦 Qty & Price":    ["Line #", "Qty Ordered", "UOM", "Unit List Price", "Unit Selling Price"],
            "🔖 Status":         ["Line #", "Return Status", "Flow Status"],
            "💰 Type & Pricing": ["Line #", "Line Type", "Payment Term"]
        }
        l_tabs = st.tabs(list(line_sections.keys()))
        for tab, (_, col_keys) in zip(l_tabs, line_sections.items()):
            with tab:
                _render_line_section(d["lines"], col_keys)
    else:
        st.info("ℹ️ No line details found in the response.")

    st.markdown("---")
    with st.expander("🔍 View Full Raw API Response"):
        st.json(result)

# --------------------------------------------------
# Render existing chat messages
# --------------------------------------------------
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# --------------------------------------------------
# Welcome (first load)
# --------------------------------------------------
if not st.session_state.messages:
    welcome = (
        "👋 Welcome to the Centroid Sales Order Assistant!\n\n"
    )
    assistant_say(welcome)
    gh_add("assistant", welcome)
    st.rerun()

# ==================================================
# SHOW CURRENT COLLECTED FIELDS  (sidebar)
# ==================================================
with st.sidebar:
    st.markdown("### 📋 Fields Collected")
    c = st.session_state.collected
    known = {k: v for k, v in c.items() if v is not None}
    if known:
        for k, v in known.items():
            st.markdown(f"**{k}**: `{v}`")
    else:
        st.info("No fields collected yet.")
    
    st.markdown("---")
    
    # --------------------------------------------------
    # VOICE INPUT TRIGGER
    # --------------------------------------------------
    st.markdown("### 🎙️ Voice Input")
    if bot.VOICE_AVAILABLE:
        if st.button("🎤 Start Listening (4s)", use_container_width=True):
            with st.spinner("Listening... Please speak now."):
                voice_result = bot.recognize_speech_vosk()
                if voice_result:
                    st.session_state.voice_prompt = voice_result
                else:
                    st.warning("Didn't catch that. Please try again.")
    else:
        st.warning("Voice packages are not installed on this server.")

    st.markdown("---")
    if st.button("🔄 Reset / Start Over", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ==================================================
# STAGES: UI Resolution State Machine
# ==================================================
stage = st.session_state.stage

# --------------------------------------------------
# select_item
# --------------------------------------------------
if stage == "select_item":
    def confirm_item(row):
        st.session_state.collected["inventory_item_id"] = row["inventory_item_id"]
        st.session_state.collected["ordered_item"]      = row["segment1"]
        assistant_say(f"✅ Item selected: `{row['segment1']}` — {row['description']}")

    render_selection_ui(
        "Inventory Item", "item_rows", "item",
        lambda r: f"ID={r['inventory_item_id']}  {r['segment1']}  {r['description']}",
        confirm_item
    )

# --------------------------------------------------
# select_price
# --------------------------------------------------
elif stage == "select_price":
    def confirm_price(row):
        st.session_state.collected["price_list_id"]      = row["price_list_id"]
        st.session_state.collected["price_list_name"]    = row["price_list_name"]
        st.session_state.collected["unit_list_price"]    = row["unit_list_price"]
        st.session_state.collected["unit_selling_price"] = row["unit_list_price"]
        assistant_say(f"✅ Price List: `{row['price_list_name']}` — Unit Price: `${row['unit_list_price']:.2f}`")
        st.session_state.stage = "selling_price_override"

    render_selection_ui(
        "Price List", "price_rows", "price",
        lambda r: f"ID={r['price_list_id']}  {r['price_list_name']}  ${r['unit_list_price']:.2f}",
        confirm_price,
        next_stage="selling_price_override"
    )

# --------------------------------------------------
# selling_price_override
# --------------------------------------------------
elif stage == "selling_price_override":
    c = st.session_state.collected
    unit_price = c.get("unit_list_price", 0.0)
    st.markdown(f"**Unit List Price:** `${unit_price:.2f}`")
    st.markdown("Enter a custom selling price, or leave blank to use the list price:")

    selling_input = st.text_input("Selling Price (optional)", value="", key="selling_price_input")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("✅ Confirm Selling Price"):
            val = bot.parse_numeric_value(selling_input, allow_float=True) if selling_input.strip() else None
            c["unit_selling_price"] = val if val is not None else unit_price
            assistant_say(f"✅ Selling Price set to: `${c['unit_selling_price']:.2f}`")
            st.session_state.stage = "resolve"
            st.rerun()

# --------------------------------------------------
# select_term
# --------------------------------------------------
elif stage == "select_term":
    def confirm_term(row):
        st.session_state.collected["payment_term_id"]   = row["term_id"]
        st.session_state.collected["payment_term_name"] = row["term_name"]
        assistant_say(f"✅ Payment Term: `{row['term_name']}`")

    render_selection_ui(
        "Payment Term", "term_rows", "term",
        lambda r: f"ID={r['term_id']}  {r['term_name']}",
        confirm_term
    )

# --------------------------------------------------
# select_rep
# --------------------------------------------------
elif stage == "select_rep":
    def confirm_rep(row):
        st.session_state.collected["salesrep_id"]   = row["salesrep_id"]
        st.session_state.collected["salesrep_name"] = row["salesrep_name"]
        assistant_say(f"✅ Sales Rep: `{row['salesrep_name']}`")

    render_selection_ui(
        "Sales Rep", "rep_rows", "rep",
        lambda r: f"ID={r['salesrep_id']}  {r['salesrep_name']}",
        confirm_rep
    )

# --------------------------------------------------
# select_line_type 
# --------------------------------------------------
elif stage == "select_line_type":
    st.markdown("### 📝 Select Line Type")
    st.info("A Line Type is required to process the order. Select from the list below.")

    rows = st.session_state.get("line_type_rows", [])
    if not rows:
        rows = bot.get_line_type_rows(offset=st.session_state.offsets.get("line_type", 0))
        st.session_state.line_type_rows = rows

    if rows:
        opts = [f"[{i+1}] {r['line_type_name']} (ID: {r['line_type_id']})" for i, r in enumerate(rows)]
        choice = st.radio("**Select Line Type:**", opts)

        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        with col1:
            if st.button("✅ Confirm Line Type"):
                idx = opts.index(choice)
                selected = rows[idx]
                st.session_state.collected["line_type_id"] = selected["line_type_id"]
                assistant_say(f"✅ Line Type: `{selected['line_type_name']}` (ID: {selected['line_type_id']})")
                st.session_state.stage = "resolve"
                st.rerun()
        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page"):
                    st.session_state.offsets["line_type"] += bot.MAX_CHOICES
                    st.session_state.line_type_rows = bot.get_line_type_rows(
                        offset=st.session_state.offsets["line_type"]
                    )
                    st.rerun()
        with col3:
            if st.session_state.offsets.get("line_type", 0) > 0:
                if st.button("⬅️ Previous Page"):
                    st.session_state.offsets["line_type"] = max(
                        0, st.session_state.offsets["line_type"] - bot.MAX_CHOICES
                    )
                    st.session_state.line_type_rows = bot.get_line_type_rows(
                        offset=st.session_state.offsets["line_type"]
                    )
                    st.rerun()
        with col4:
            if st.button("❌ Cancel"):
                st.session_state.stage = "chat"
                st.rerun()
    else:
        st.warning("No line types found. Enter a Line Type ID manually:")
        lt_input = st.text_input("Line Type ID:", key="line_type_manual_input")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Line Type"):
                val = bot.parse_numeric_value(lt_input)
                if val is not None:
                    st.session_state.collected["line_type_id"] = val
                    assistant_say(f"✅ Line Type ID set to: `{val}`")
                    st.session_state.stage = "resolve"
                    st.rerun()
                else:
                    st.error("Please enter a valid numeric ID.")
        with col2:
            if st.button("❌ Cancel"):
                st.session_state.stage = "chat"
                st.rerun()

# --------------------------------------------------
# select_customer
# --------------------------------------------------
elif stage == "select_customer":
    st.markdown("### 🔍 Select Customer")

    search_val = st.text_input(
        "Search customer by name:",
        value=st.session_state.collected.get("customer_name") or "",
        key="customer_search_input"
    )
    if st.button("🔍 Search"):
        st.session_state.offsets["customer"] = 0
        st.session_state.collected["customer_name"] = search_val
        rows = bot.get_customer_by_name_rows(search_val, offset=0)
        st.session_state.customer_rows = rows
        st.rerun()

    rows = st.session_state.get("customer_rows", [])

    if rows:
        opts = [
            f"[{i+1}] {r['customer_name']}  (Acct#: {r['account_number']}, ID: {r['cust_account_id']})"
            for i, r in enumerate(rows)
        ]
        choice = st.radio("**Select Customer:**", opts)

        col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
        with col1:
            if st.button("✅ Confirm Customer"):
                idx = opts.index(choice)
                selected = rows[idx]
                st.session_state.collected["cust_account_id"] = selected["cust_account_id"]
                st.session_state.collected["customer_name"]   = selected["customer_name"]
                sites = bot.get_customer_sites_by_account(selected["cust_account_id"])
                if not sites:
                    assistant_say(f"⚠️ No active SHIP_TO sites found for `{selected['customer_name']}`.")
                    st.session_state.stage = "chat"
                elif len(sites) == 1:
                    st.session_state.collected["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                    st.session_state.collected["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                    assistant_say(
                        f"✅ Customer: `{sites[0]['customer_name']}`  "
                        f"| Sold-to: `{sites[0]['sold_to_org_id']}`  "
                        f"| Ship-to: `{sites[0]['ship_to_org_id']}`"
                    )
                    st.session_state.stage = "resolve"
                else:
                    st.session_state.site_rows = sites
                    st.session_state.stage     = "select_site"
                st.rerun()

        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page"):
                    st.session_state.offsets["customer"] += bot.MAX_CHOICES
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(
                        name, offset=st.session_state.offsets["customer"]
                    )
                    st.rerun()

        with col3:
            if st.session_state.offsets["customer"] > 0:
                if st.button("⬅️ Prev Page"):
                    st.session_state.offsets["customer"] = max(
                        0, st.session_state.offsets["customer"] - bot.MAX_CHOICES
                    )
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(
                        name, offset=st.session_state.offsets["customer"]
                    )
                    st.rerun()

        with col4:
            if st.button("❌ Cancel"):
                st.session_state.stage = "chat"
                st.rerun()
    else:
        st.info("Use the search box above to find customers.")
        if st.button("❌ Cancel"):
            st.session_state.stage = "chat"
            st.rerun()

# --------------------------------------------------
# select_customer_by_item
# --------------------------------------------------
elif stage == "select_customer_by_item":
    c = st.session_state.collected
    item_name = c.get("ordered_item", "selected item")
    st.markdown(f"### 🔍 Select Customer for Item: `{item_name}`")
    st.info("Showing customers who have previously ordered this item (or all active customers as fallback).")

    rows = st.session_state.get("customer_by_item_rows", [])

    if not rows:
        rows = bot.get_customers_by_inventory_item_rows(
            c["inventory_item_id"],
            offset=st.session_state.offsets["customer_by_item"]
        )
        st.session_state.customer_by_item_rows = rows

    if rows:
        opts = [
            f"[{i+1}] {r['customer_name']}  (Acct#: {r['account_number']}, ID: {r['cust_account_id']})"
            for i, r in enumerate(rows)
        ]
        choice = st.radio("**Select Customer:**", opts)

        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
        with col1:
            if st.button("✅ Confirm Customer"):
                idx = opts.index(choice)
                selected = rows[idx]
                st.session_state.collected["cust_account_id"] = selected["cust_account_id"]
                st.session_state.collected["customer_name"]   = selected["customer_name"]
                sites = bot.get_customer_sites_by_account(selected["cust_account_id"])
                if not sites:
                    assistant_say(f"⚠️ No active SHIP_TO sites found for `{selected['customer_name']}`.")
                    st.session_state.stage = "chat"
                elif len(sites) == 1:
                    st.session_state.collected["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                    st.session_state.collected["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                    assistant_say(
                        f"✅ Customer: `{sites[0]['customer_name']}`  "
                        f"| Sold-to: `{sites[0]['sold_to_org_id']}`  "
                        f"| Ship-to: `{sites[0]['ship_to_org_id']}`"
                    )
                    st.session_state.stage = "resolve"
                else:
                    st.session_state.site_rows = sites
                    st.session_state.stage     = "select_site"
                st.rerun()

        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page"):
                    st.session_state.offsets["customer_by_item"] += bot.MAX_CHOICES
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(
                        c["inventory_item_id"],
                        offset=st.session_state.offsets["customer_by_item"]
                    )
                    st.rerun()

        with col3:
            if st.session_state.offsets["customer_by_item"] > 0:
                if st.button("⬅️ Prev Page"):
                    st.session_state.offsets["customer_by_item"] = max(
                        0, st.session_state.offsets["customer_by_item"] - bot.MAX_CHOICES
                    )
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(
                        c["inventory_item_id"],
                        offset=st.session_state.offsets["customer_by_item"]
                    )
                    st.rerun()

        with col4:
            if st.button("🔍 Search by Name Instead"):
                st.session_state.customer_rows = []
                st.session_state.stage = "select_customer"
                st.rerun()

        with col5:
            if st.button("❌ Cancel"):
                st.session_state.stage = "chat"
                st.rerun()
    else:
        st.warning("No customers found for this item. Try searching by name.")
        if st.button("🔍 Search by Name"):
            st.session_state.customer_rows = []
            st.session_state.stage = "select_customer"
            st.rerun()
        if st.button("❌ Cancel"):
            st.session_state.stage = "chat"
            st.rerun()

# --------------------------------------------------
# select_site
# --------------------------------------------------
elif stage == "select_site":
    def confirm_site(row):
        st.session_state.collected["sold_to_org_id"] = row["sold_to_org_id"]
        st.session_state.collected["ship_to_org_id"] = row["ship_to_org_id"]
        st.session_state.collected["customer_name"]  = row["customer_name"]
        assistant_say(
            f"✅ Customer: `{row['customer_name']}`  "
            f"| Sold-to: `{row['sold_to_org_id']}`  "
            f"| Ship-to: `{row['ship_to_org_id']}`"
        )

    render_selection_ui(
        "Customer Site", "site_rows", "site",
        lambda r: (
            f"Customer={r['customer_name']}  "
            f"[{r['location']}] {r['address']}  "
            f"(SoldTo={r['sold_to_org_id']} | ShipTo={r['ship_to_org_id']})"
        ),
        confirm_site
    )

# ==================================================
# STAGE: resolve — Smart Step-by-Step DB Fetching
# ==================================================
elif stage == "resolve":
    c    = st.session_state.collected
    offs = st.session_state.offsets

    with st.spinner("⏳ Resolving order details..."):
        try:
            # Step 1 — Resolve Item
            if c.get("ordered_item") and not c.get("inventory_item_id"):
                rows = bot.get_inventory_item_rows(c["ordered_item"], offset=offs["item"])
                if len(rows) == 1 and offs["item"] == 0:
                    c["inventory_item_id"] = rows[0]["inventory_item_id"]
                    c["ordered_item"]      = rows[0]["segment1"]
                    st.rerun()
                else:
                    st.session_state.item_rows = rows
                    st.session_state.stage     = "select_item"
                    st.rerun()

            # Step 2 — Resolve Price 
            if c.get("inventory_item_id") and c.get("quantity") and not c.get("price_list_id"):
                rows = bot.get_price_details_rows(
                    c["ordered_item"], float(c["quantity"]), c["inventory_item_id"], offset=offs["price"]
                )
                if len(rows) == 1 and offs["price"] == 0:
                    c["price_list_id"] = rows[0]["price_list_id"]
                    
                    if not c.get("unit_list_price"):
                        c["unit_list_price"] = rows[0]["unit_list_price"]
                        
                    if not c.get("unit_selling_price"):
                        c["unit_selling_price"] = rows[0]["unit_list_price"]
                        st.session_state.stage  = "selling_price_override"
                    
                    st.rerun()
                else:
                    st.session_state.price_rows = rows
                    st.session_state.stage      = "select_price"
                    st.rerun()

            # Step 3 — Resolve Payment Term
            if not c.get("payment_term_id"):
                rows = bot.get_payment_term_rows(offset=offs["term"])
                if len(rows) == 1 and offs["term"] == 0:
                    c["payment_term_id"]   = rows[0]["term_id"]
                    c["payment_term_name"] = rows[0]["term_name"]
                    st.rerun()
                else:
                    st.session_state.term_rows = rows
                    st.session_state.stage     = "select_term"
                    st.rerun()

            # Step 4 — Resolve Salesrep
            if not c.get("salesrep_id"):
                rows = bot.get_salesrep_rows(offset=offs["rep"])
                if len(rows) == 1 and offs["rep"] == 0:
                    c["salesrep_id"]   = rows[0]["salesrep_id"]
                    c["salesrep_name"] = rows[0]["salesrep_name"]
                    st.rerun()
                else:
                    st.session_state.rep_rows = rows
                    st.session_state.stage    = "select_rep"
                    st.rerun()

            # Step 5 — Resolve Line Type ID
            if not c.get("line_type_id"):
                st.session_state.stage = "select_line_type"
                st.rerun()

            # Step 6 — Resolve Customer
            if not c.get("sold_to_org_id") or not c.get("ship_to_org_id"):
                if c.get("customer_name") and not c.get("cust_account_id"):
                    rows = bot.get_customer_by_name_rows(
                        c["customer_name"], offset=offs["customer"]
                    )
                    st.session_state.customer_rows = rows
                    st.session_state.stage         = "select_customer"
                    st.rerun()
                elif c.get("inventory_item_id") and not c.get("cust_account_id"):
                    rows = bot.get_customers_by_inventory_item_rows(
                        c["inventory_item_id"],
                        offset=offs["customer_by_item"]
                    )
                    st.session_state.customer_by_item_rows = rows
                    st.session_state.stage                 = "select_customer_by_item"
                    st.rerun()

            # Everything resolved → go to confirmation
            st.session_state.stage = "confirm_order"
            st.rerun()

        except Exception as e:
            assistant_say(f"❌ Error during resolution: {e}")
            st.session_state.stage = "error"
            st.rerun()

# ==================================================
# STAGE: confirm_order — review before submit
# ==================================================
elif stage == "confirm_order":
    c = st.session_state.collected
    summary = "**📋 Order Summary — please review before submitting:**\n\n"
    summary += "| Field | Value |\n|---|---|\n"
    for label, val in c.items():
        if val is not None and not label.endswith("_name"):
            summary += f"| **{label}** | `{val}` |\n"

    if not any("Order Summary" in m["content"] for m in st.session_state.messages):
        assistant_say(summary)
        assistant_say("Does everything look correct? Click below to submit.")
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Submit Order"):
            with st.spinner("⏳ Submitting Order..."):
                try:
                    payload = bot.create_payload(
                        p_cust_po         = c["cpo"],
                        p_item_id         = c["inventory_item_id"],
                        p_ordered_item    = c["ordered_item"],
                        p_qty             = c["quantity"],
                        p_price           = c["unit_list_price"],
                        p_selling_price   = c["unit_selling_price"],
                        p_payment_term_id = c["payment_term_id"],
                        p_price_list_id   = c["price_list_id"],
                        p_salesrep_id     = c["salesrep_id"],
                        p_line_type_id    = c["line_type_id"],
                        p_ship_to_org     = c["ship_to_org_id"],
                        p_sold_to_org     = c["sold_to_org_id"],
                        p_operating_unit  = bot.OPERATING_UNIT,
                    )
                    result = bot.send_order(payload)
                    st.session_state.api_result = result

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
                        if header_id:
                            st.session_state.add_line_header_id    = int(str(header_id).strip())
                        if order_number:
                            st.session_state.add_line_order_number = int(str(order_number).strip())
                    except Exception:
                        pass

                    st.session_state.stage = "done"
                    # Set return routing just in case they cancel adding a line later
                    st.session_state.add_line_return = "done"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Submit Error: {e}")
                    st.session_state.stage = "error"
                    st.rerun()
    with col2:
        if st.button("🔄 Start Over"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

# ==================================================
# STAGE: done — show result + Add Another Line option
# ==================================================
elif stage == "done":
    result = st.session_state.get("api_result", {})
    st.success("✅ Operation completed successfully!")
    display_erp_response(result, context_label="Order")

    st.markdown("---")

    header_id    = st.session_state.get("add_line_header_id")
    order_number = st.session_state.get("add_line_order_number")

    if header_id and order_number:
        st.markdown(f"### ➕ Add Another Line to Order #{order_number}?")
        col_add, col_new = st.columns(2)
        with col_add:
            if st.button("➕ Add a Line"):
                st.session_state.add_line_stage     = "add_line_item"
                st.session_state.add_line_data      = {}
                st.session_state.add_line_item_rows = []
                st.session_state.add_line_price_rows= []
                st.session_state.add_line_term_rows = []
                st.session_state.offsets["item"]    = 0
                st.session_state.offsets["price"]   = 0
                st.session_state.offsets["term"]    = 0
                st.session_state.stage              = "add_line_flow"
                st.session_state.add_line_return    = "done"
                st.rerun()
        with col_new:
            if st.button("🆕 Create Another Order"):
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.rerun()
    else:
        if st.button("🆕 Create Another Order"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

# ==================================================
# STAGE: show_get_order (Advanced Search / Single Order)
# ==================================================
elif stage == "show_get_order":
    result = st.session_state.get("api_result", {})

    if isinstance(result, dict) and "total_count" in result:
        st.success(f"✅ Found {result['total_count']} orders matching your criteria!")
        df = pd.DataFrame(result["rows"], columns=["Order Number", "Status", "Creation Date"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        if st.button("🔍 Start New Search"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()
    else:
        st.success("✅ Operation completed successfully!")
        display_erp_response(result, context_label="Retrieved Order")

        st.markdown("---")

        # ── Extract Order IDs so we can dynamically add a line ──
        try:
            out  = result.get("OutputParameters", result)
            hdr  = out.get("X_HEADER_REC", {})
            
            order_number = hdr.get("ORDER_NUMBER") or hdr.get("order_number")
            header_id    = hdr.get("HEADER_ID")    or hdr.get("header_id")
            
            if header_id:
                st.session_state.add_line_header_id    = int(str(header_id).strip())
            if order_number:
                st.session_state.add_line_order_number = int(str(order_number).strip())
        except Exception:
            pass

        header_id    = st.session_state.get("add_line_header_id")
        order_number = st.session_state.get("add_line_order_number")

        if header_id and order_number:
            st.markdown(f"### ➕ Add a Line to Order #{order_number}?")
            col_add, col_new = st.columns(2)
            with col_add:
                if st.button("➕ Add a Line"):
                    # Reset add-line sub-state
                    st.session_state.add_line_stage     = "add_line_item"
                    st.session_state.add_line_data      = {}
                    st.session_state.add_line_item_rows = []
                    st.session_state.add_line_price_rows= []
                    st.session_state.add_line_term_rows = []
                    st.session_state.offsets["item"]    = 0
                    st.session_state.offsets["price"]   = 0
                    st.session_state.offsets["term"]    = 0
                    st.session_state.stage              = "add_line_flow"
                    # Smart Route: Return here if they hit "cancel" while adding the line
                    st.session_state.add_line_return    = "show_get_order" 
                    st.rerun()
            with col_new:
                if st.button("🔍 Start New Search"):
                    for k in list(st.session_state.keys()):
                        del st.session_state[k]
                    st.rerun()
        else:
            if st.button("🔍 Start New Search"):
                for k in list(st.session_state.keys()):
                    del st.session_state[k]
                st.rerun()

# ==================================================
# STAGE: add_line_flow
# ==================================================
elif stage == "add_line_flow":
    header_id    = st.session_state.add_line_header_id
    order_number = st.session_state.add_line_order_number
    sub          = st.session_state.add_line_stage
    ald          = st.session_state.add_line_data
    offs         = st.session_state.offsets
    return_stage = st.session_state.get("add_line_return", "done")

    st.markdown(f"### ➕ Adding Line to Order #{order_number} (Header ID: {header_id})")

    if sub == "add_line_item":
        item_search = st.text_input("Enter item name/prefix to search:", key="add_line_item_search")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔍 Search Items"):
                offs["item"] = 0
                rows = bot.get_inventory_item_rows(item_search, offset=0)
                st.session_state.add_line_item_rows = rows
                st.rerun()
        with col2:
            if st.button("❌ Cancel Add Line"):
                st.session_state.add_line_stage = None
                st.session_state.stage          = return_stage
                st.rerun()

        rows = st.session_state.add_line_item_rows
        if rows:
            opts = [f"[{i+1}] {r['segment1']}  {r['description']}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Item:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Item"):
                    idx = opts.index(choice)
                    ald["inventory_item_id"] = rows[idx]["inventory_item_id"]
                    ald["ordered_item"]      = rows[idx]["segment1"]
                    st.session_state.add_line_stage = "add_line_qty"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next"):
                        offs["item"] += bot.MAX_CHOICES
                        st.session_state.add_line_item_rows = bot.get_inventory_item_rows(
                            item_search, offset=offs["item"]
                        )
                        st.rerun()

    elif sub == "add_line_qty":
        st.markdown(f"**Item:** `{ald.get('ordered_item')}`")
        qty_input = st.text_input("Enter Quantity:", key="add_line_qty_input")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Quantity"):
                qty = bot.parse_numeric_value(qty_input, allow_float=True)
                if qty is None:
                    st.error("Invalid quantity. Please enter a number.")
                else:
                    ald["quantity"] = qty
                    rows = bot.get_price_details_rows(
                        ald["ordered_item"], qty, ald["inventory_item_id"], offset=0
                    )
                    st.session_state.add_line_price_rows = rows
                    offs["price"] = 0
                    st.session_state.add_line_stage = "add_line_price"
                    st.rerun()
        with col2:
            if st.button("❌ Cancel"):
                st.session_state.add_line_stage = None
                st.session_state.stage          = return_stage
                st.rerun()

    elif sub == "add_line_price":
        st.markdown(f"**Item:** `{ald.get('ordered_item')}`  |  **Qty:** `{ald.get('quantity')}`")
        rows = st.session_state.add_line_price_rows
        if not rows:
            st.warning("No price lists found for this item.")
            if st.button("⬅️ Back to Item"):
                st.session_state.add_line_stage = "add_line_item"
                st.rerun()
        else:
            opts = [f"[{i+1}] {r['price_list_name']}  ${r['unit_list_price']:.2f}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Price List:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Price"):
                    idx = opts.index(choice)
                    ald["price_list_id"]      = rows[idx]["price_list_id"]
                    ald["unit_list_price"]    = rows[idx]["unit_list_price"]
                    ald["unit_selling_price"] = rows[idx]["unit_list_price"]
                    st.session_state.add_line_stage = "add_line_selling_price"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next"):
                        offs["price"] += bot.MAX_CHOICES
                        st.session_state.add_line_price_rows = bot.get_price_details_rows(
                            ald["ordered_item"], ald["quantity"], ald["inventory_item_id"], offset=offs["price"]
                        )
                        st.rerun()

    elif sub == "add_line_selling_price":
        unit_price = ald.get("unit_list_price", 0.0)
        st.markdown(f"**Unit List Price:** `${unit_price:.2f}`")
        sp_input = st.text_input("Selling Price (leave blank to use list price):", key="add_line_sp")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Selling Price"):
                val = bot.parse_numeric_value(sp_input, allow_float=True) if sp_input.strip() else None
                ald["unit_selling_price"] = val if val is not None else unit_price
                rows = bot.get_payment_term_rows(offset=0)
                st.session_state.add_line_term_rows = rows
                offs["term"] = 0
                st.session_state.add_line_stage = "add_line_term"
                st.rerun()

    elif sub == "add_line_term":
        rows = st.session_state.add_line_term_rows
        if not rows:
            st.warning("No payment terms found.")
            if st.button("⬅️ Back"):
                st.session_state.add_line_stage = "add_line_selling_price"
                st.rerun()
        else:
            opts = [f"[{i+1}] {r['term_name']}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Payment Term:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Term"):
                    idx = opts.index(choice)
                    ald["payment_term_id"] = rows[idx]["term_id"]
                    st.session_state.add_line_stage = "add_line_line_type"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next"):
                        offs["term"] += bot.MAX_CHOICES
                        st.session_state.add_line_term_rows = bot.get_payment_term_rows(offset=offs["term"])
                        st.rerun()

    elif sub == "add_line_line_type":
        st.markdown(f"**Item:** `{ald.get('ordered_item')}`")
        st.info("Select a Line Type from the list below.")

        lt_rows = st.session_state.get("add_line_lt_rows", [])
        if not lt_rows:
            lt_rows = bot.get_line_type_rows(offset=offs.get("line_type", 0))
            st.session_state.add_line_lt_rows = lt_rows

        if lt_rows:
            lt_opts = [f"[{i+1}] {r['line_type_name']} (ID: {r['line_type_id']})" for i, r in enumerate(lt_rows)]
            lt_choice = st.radio("**Select Line Type:**", lt_opts)
            c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
            with c1:
                if st.button("✅ Confirm Line Type"):
                    idx = lt_opts.index(lt_choice)
                    ald["line_type_id"] = lt_rows[idx]["line_type_id"]
                    st.session_state.add_line_stage = "add_line_submit"
                    st.rerun()
            with c2:
                if len(lt_rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next"):
                        offs["line_type"] = offs.get("line_type", 0) + bot.MAX_CHOICES
                        st.session_state.add_line_lt_rows = bot.get_line_type_rows(offset=offs["line_type"])
                        st.rerun()
            with c3:
                if offs.get("line_type", 0) > 0:
                    if st.button("⬅️ Prev"):
                        offs["line_type"] = max(0, offs.get("line_type", 0) - bot.MAX_CHOICES)
                        st.session_state.add_line_lt_rows = bot.get_line_type_rows(offset=offs["line_type"])
                        st.rerun()
            with c4:
                if st.button("❌ Cancel"):
                    st.session_state.add_line_stage = None
                    st.session_state.stage          = return_stage
                    st.rerun()
        else:
            st.warning("No line types found. Enter manually:")
            lt_input = st.text_input("Enter Line Type ID:", key="add_line_lt")
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("✅ Confirm Line Type"):
                    val = bot.parse_numeric_value(lt_input)
                    if val is not None:
                        ald["line_type_id"] = val
                        st.session_state.add_line_stage = "add_line_submit"
                        st.rerun()
                    else:
                        st.error("Please enter a valid numeric ID.")
            with col2:
                if st.button("❌ Cancel"):
                    st.session_state.add_line_stage = None
                    st.session_state.stage          = return_stage
                    st.rerun()

    elif sub == "add_line_submit":
        st.markdown("**📋 New Line Summary:**")
        st.markdown(f"- Item: `{ald.get('ordered_item')}`")
        st.markdown(f"- Quantity: `{ald.get('quantity')}`")
        st.markdown(f"- Unit List Price: `${ald.get('unit_list_price', 0):.2f}`")
        st.markdown(f"- Selling Price: `${ald.get('unit_selling_price', 0):.2f}`")
        st.markdown(f"- Payment Term ID: `{ald.get('payment_term_id')}`")
        st.markdown(f"- Line Type ID: `{ald.get('line_type_id')}`")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Submit Line"):
                with st.spinner("⏳ Adding line to order..."):
                    try:
                        payload = bot.create_add_line_payload(
                            p_header_id       = header_id,
                            p_item_id         = ald["inventory_item_id"],
                            p_ordered_item    = ald["ordered_item"],
                            p_qty             = ald["quantity"],
                            p_price           = ald["unit_list_price"],
                            p_selling_price   = ald["unit_selling_price"],
                            p_payment_term_id = ald["payment_term_id"],
                            p_price_list_id   = ald["price_list_id"],
                            p_line_type_id    = ald["line_type_id"],
                        )
                        result = bot.send_order(payload)
                        assistant_say(f"✅ Line added successfully to Order #{order_number}!")
                        st.session_state.api_result = result
                        st.session_state.add_line_stage = None
                        st.session_state.add_line_data  = {}
                        # Always route to "done" on success so the updated line details display clearly
                        st.session_state.stage          = "done"
                        st.rerun()
                    except Exception as e:
                        assistant_say(f"❌ Failed to add line: {e}")
                        st.session_state.stage = "error"
                        st.rerun()
        with col2:
            if st.button("❌ Cancel"):
                st.session_state.add_line_stage = None
                st.session_state.stage          = return_stage
                st.rerun()

# ==================================================
# STAGE: fetch_get_order
# ==================================================
elif stage == "fetch_get_order":
    with st.spinner(f"⏳ Retrieving Order {st.session_state.get_order_num}..."):
        try:
            result = bot.get_order(st.session_state.get_order_num)
            st.session_state.api_result = result
            st.session_state.stage      = "show_get_order"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ Failed: {e}")
            st.session_state.stage = "error"
            st.rerun()

# ==================================================
# STAGE: error
# ==================================================
elif stage == "error":
    if st.button("🔄 Start Over"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

# ==================================================
# MAIN CHAT INPUT
# ==================================================
elif stage == "chat":
    placeholder = "Try: 'Get orders from last year' or 'Create order for CM94532'"
    
    # 1. Grab text input from chat box
    text_prompt = st.chat_input(placeholder)
    
    # 2. Check if a voice prompt was gathered from the sidebar button
    voice_prompt = st.session_state.get("voice_prompt")
    
    # Decide which prompt to act on (prioritize new text input over cached voice prompt)
    prompt = text_prompt if text_prompt else voice_prompt

    if prompt:
        # Clear the voice prompt so it doesn't loop
        if "voice_prompt" in st.session_state:
            st.session_state.voice_prompt = None

        if prompt.strip().lower() in ("exit", "quit", "stop"):
            st.warning("Chat session ended by user. Refresh the page to start over.")
            st.stop()

        user_say(prompt)
        gh_add("user", prompt)
        
        extracted = bot.github_extract_intent(prompt)
        
        explicit_mapping = {
            "CUST_PO_NUMBER": "cpo",
            "ORDERED_ITEM": "ordered_item",
            "ORDERED_QUANTITY": "quantity",
            "UNIT_LIST_PRICE": "unit_list_price",
            "UNIT_SELLING_PRICE": "unit_selling_price",
            "PAYMENT_TERM_ID": "payment_term_id",
            "SALESREP_ID": "salesrep_id",
            "LINE_TYPE_ID": "line_type_id",
            "SHIP_TO_ORG_ID": "ship_to_org_id",
            "SOLD_TO_ORG_ID": "sold_to_org_id"
        }
        
        for explicit_key, internal_key in explicit_mapping.items():
            match = re.search(rf"{explicit_key}\s*(?:is|=|:)\s*([A-Za-z0-9_.-]+)", prompt, re.IGNORECASE)
            if match:
                val = match.group(1)
                if val.replace('.', '', 1).isdigit():
                    val = float(val) if '.' in val else int(val)
                extracted[internal_key] = val
        
        if "create" in prompt.lower():
            extracted["action"] = "create"
            
        action = extracted.get("action", "unknown")
        
        merge_fields(extracted)

        if (extracted.get("year") or extracted.get("date_range") or
                (extracted.get("status") and not extracted.get("order_number"))):
            with st.spinner("⏳ Searching database..."):
                try:
                    res = bot.get_orders_advanced(
                        extracted.get("date_range"),
                        extracted.get("year"),
                        extracted.get("status")
                    )
                    st.session_state.api_result = res
                    st.session_state.stage      = "show_get_order"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ DB Search Error: {e}")
                    st.rerun()

        elif action == "get" or st.session_state.action == "get":
            st.session_state.action = "get"
            order_num = st.session_state.collected.get("order_number")
            if order_num is None:
                q = bot.github_clarify(st.session_state.gh_history, ["Order Number"])
                assistant_say(q)
                gh_add("assistant", q)
                st.rerun()
            else:
                st.session_state.get_order_num = int(order_num)
                st.session_state.stage         = "fetch_get_order"
                st.rerun()

        elif action == "create" or st.session_state.action == "create":
            st.session_state.action = "create"
            missing = missing_minimum()
            
            if missing:
                missing_str = ", ".join(f"**{m}**" for m in missing)
                strict_response = f"I am ready to build the payload, but I am still missing: {missing_str}. Please provide them."
                
                assistant_say(strict_response)
                gh_add("assistant", strict_response)
                st.rerun()
            else:
                st.session_state.stage = "resolve"
                st.rerun()

        else:
            fallback = bot.github_clarify(
                st.session_state.gh_history,
                ["action: 'create a new order', 'get order by number', or 'search orders by year'"]
            )
            assistant_say(fallback)
            gh_add("assistant", fallback)
            st.rerun()