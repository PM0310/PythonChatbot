import streamlit as st
import SalesOrderChatAndVoiceBot1 as bot
import json
import pandas as pd
import re
import threading

st.set_page_config(page_title="Sales Order Assistant", page_icon="📦", layout="wide")
st.markdown("""
    <style>
    /* 1. Main App Background & Font */
    .stApp { 
        background-color: #ffffff; 
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    /* 2. Hide Streamlit Default Avatars for a cleaner text interface */
    [data-testid="stChatMessageAvatarAssistant"], 
    [data-testid="stChatMessageAvatarUser"] { display: none !important; }

    /* 3. General Chat Row Setup */
    [data-testid="stChatMessage"] {
        background-color: transparent !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        gap: 0px !important;
    }

    /* 4. USER MESSAGE: ChatGPT/Claude style (Right-aligned, soft gray bubble) */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        display: flex !important;
        flex-direction: row-reverse !important;
        margin-bottom: 15px;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background-color: #f4f4f4 !important;
        color: #0d0d0d !important;
        padding: 12px 20px !important;
        border-radius: 20px 20px 4px 20px !important;
        max-width: 70% !important;
        font-size: 16px;
        line-height: 1.5;
        text-align: left !important;
    }

    /* 5. ASSISTANT MESSAGE: Plain text, no bubble, left-aligned */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
        display: flex !important;
        flex-direction: row !important;
        margin-bottom: 25px;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
        background-color: transparent !important;
        color: #0d0d0d !important;
        padding: 0px 10px !important;
        max-width: 85% !important;
        font-size: 16px;
        line-height: 1.6;
    }

    /* 6. Fix Markdown typography inheritance */
    [data-testid="stChatMessage"] div.stMarkdown p, 
    [data-testid="stChatMessage"] div.stMarkdown h1,
    [data-testid="stChatMessage"] div.stMarkdown h2,
    [data-testid="stChatMessage"] div.stMarkdown h3 { color: inherit !important; margin-bottom: 0.5rem; }

    /* 7. Chat Input Bar Styling */
    [data-testid="stChatInput"] {
        border-radius: 24px !important;
        border: 1px solid #e5e5e5 !important;
        background-color: #f9f9f9 !important;
    }
    [data-testid="stChatInput"]:focus-within {
        border-color: #b3b3b3 !important;
        background-color: #ffffff !important;
    }
    
    /* 8. Modern Buttons (Including Mic) */
    .stButton>button {
        border-radius: 24px;
        border: 1px solid #e5e5e5;
        background-color: #ffffff;
        color: #0d0d0d;
        font-size: 1.2rem;
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        background-color: #f4f4f4;
        border-color: #cccccc;
    }
    
    /* 9. Sidebar styling */
    [data-testid="stSidebar"] { background-color: #f9f9f9; border-right: 1px solid #e5e5e5; }
    [data-testid="stCaptionContainer"] p { color: #555555 !important; font-weight: 500; font-size: 1.1rem; }
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
        "pending_field":  None,
        "offsets": {
            "item": 0, "price": 0, "term": 0, "rep": 0, "site": 0,
            "customer": 0, "customer_by_item": 0, "line_type": 0
        },
        "collected": {
            "cpo": None, "ordered_item": None, "quantity": None, "order_number": None,
            "inventory_item_id": None, "price_list_id": None, "price_list_name": None,
            "unit_list_price": None, "unit_selling_price": None, "payment_term_id": None, 
            "payment_term_name": None, "salesrep_id": None, "salesrep_name": None,
            "sold_to_org_id": None, "ship_to_org_id": None, "customer_name": None,
            "cust_account_id": None, "line_type_id": None,
        },
        "item_rows": [], "price_rows": [], "term_rows": [], "rep_rows": [], "site_rows": [],
        "customer_rows": [], "customer_by_item_rows": [], "line_type_rows": [],
        "api_result": None, "gh_history": [],
        "add_line_stage": None, "add_line_data": {}, "add_line_header_id": None,     
        "add_line_order_number": None, "add_line_item_rows": [], "add_line_price_rows": [],
        "add_line_term_rows": [], "add_line_return": "done", "selling_price_override": False,    
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def clean_text_for_speech(text: str) -> str:
    text = re.sub(r'[*_~`|#>-]', '', text)
    text = re.sub(r'[^\w\s.,?!]', '', text)
    return text.strip()

def assistant_say(msg: str, speak_text: str = None, mute: bool = False):
    st.session_state.messages.append({"role": "assistant", "content": msg})
    if bot.VOICE_AVAILABLE and not mute:
        text_to_speak = speak_text if speak_text else clean_text_for_speech(msg)
        if text_to_speak:
            def threaded_speak():
                try:
                    bot.speak(text_to_speak)  # thread-safe via lock in bot module
                except Exception as e:
                    print(f"Speech thread error: {e}")
            t = threading.Thread(target=threaded_speak, daemon=True)
            t.start()

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
    if not c.get("cpo"): missing.append("Customer PO Number")
    if not c.get("ordered_item") and not c.get("inventory_item_id"): missing.append("Ordered Item code")
    if not c.get("quantity"): missing.append("Ordered Quantity")
    if not c.get("line_type_id") and hasattr(bot, 'get_line_type_rows'): missing.append("Line Type ID")
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
                st.session_state.offsets[offset_key] = max(0, st.session_state.offsets[offset_key] - bot.MAX_CHOICES)
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
        if isinstance(items, list): message_list = [m.get("MESSAGE_TEXT", "") for m in items if m.get("MESSAGE_TEXT")]
        elif isinstance(items, dict):
            msg = items.get("MESSAGE_TEXT", "")
            if msg: message_list = [msg]
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
            if v is not None: return [v] if isinstance(v, dict) else list(v)
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

    return {"status": status, "message": message_text, "header_details": header_details, "lines": lines}

def _render_line_section(lines: list, col_keys: list):
    active_cols = [k for k in col_keys if any(ln.get(k) not in (None, "", "N/A") for ln in lines)]
    if not active_cols:
        st.info("No data available in this section.")
        return
    if len(lines) == 1:
        line = lines[0]
        md_rows = "\n".join(f"| **{k}** | {line.get(k, 'N/A')} |" for k in active_cols)
        st.markdown(f"| Field | Value |\n|---|---|\n{md_rows}")
    else:
        records = []
        for ln in lines:
            row = {"Line #": ln.get("Line #", "N/A")}
            for k in active_cols:
                if k != "Line #": row[k] = ln.get(k, "N/A")
            records.append(row)
        df = pd.DataFrame(records).replace("N/A", "")
        st.dataframe(df, use_container_width=True, hide_index=True)

def display_erp_response(result: dict, context_label: str = "Order"):
    d = extract_erp_details(result)
    status_val = str(d["status"]).upper()

    if status_val == "S": emoji, status_label = "✅", "Success"
    elif status_val == "E": emoji, status_label = "❌", "Error"
    elif status_val == "W": emoji, status_label = "⚠️", "Warning"
    else: emoji, status_label = "ℹ️", status_val

    banner = (f"{emoji} **{context_label} {status_label}!** &nbsp;|&nbsp; "
              f"Order # `{d['header_details'].get('Order Number', 'N/A')}` &nbsp;|&nbsp; "
              f"Header ID `{d['header_details'].get('Header ID', 'N/A')}`")
    
    assistant_say(banner, speak_text=f"The {context_label} operation returned a {status_label} status.")
    st.markdown(banner)

    if d["message"] and d["message"] != "N/A":
        st.markdown("### 💬 ERP Messages")
        for msg in d["message"].split(" | "):
            if msg.strip(): st.warning(msg.strip())

    st.markdown("---")
    st.markdown("## 🧾 Header Details")
    hd = d["header_details"]
    header_sections = {
        "📋 Order Identity": {"Order Number": hd.get("Order Number"), "Header ID": hd.get("Header ID"), "Customer PO":  hd.get("Customer PO"),  "Order Category": hd.get("Order Category"), "Order Type":   hd.get("Order Type")},
        "📅 Dates & Status": {"Return Status": hd.get("Return Status"), "Flow Status": hd.get("Flow Status"), "Booked Flag":   hd.get("Booked Flag"),   "Open Flag":    hd.get("Open Flag"), "Ordered Date":  hd.get("Ordered Date")},
        "💰 Financial & Parties": {"Currency": hd.get("Currency"), "Payment Term": hd.get("Payment Term"), "Price List": hd.get("Price List"), "Customer": hd.get("Customer"), "Ship To": hd.get("Ship To"), "Bill To": hd.get("Bill To"), "Salesrep": hd.get("Salesrep")}
    }
    h_tabs = st.tabs(list(header_sections.keys()))
    for tab, (_, fields) in zip(h_tabs, header_sections.items()):
        with tab:
            md_rows = "\n".join(f"| **{k}** | {v} |" for k, v in fields.items() if v and v != "N/A")
            if md_rows: st.markdown(f"| Field | Value |\n|---|---|\n{md_rows}")
            else: st.info("No data available in this section.")

    st.markdown("---")
    n_lines = len(d["lines"])
    st.markdown(f"## 📦 Line Details <span style='font-size:0.85rem;color:gray;'>({n_lines} line{'s' if n_lines!=1 else ''})</span>", unsafe_allow_html=True)
    if d["lines"]:
        line_sections = {
            "📋 Identity":       ["Line #", "Line ID", "Item", "Item Description"],
            "📦 Qty & Price":    ["Line #", "Qty Ordered", "UOM", "Unit List Price", "Unit Selling Price"],
            "🔖 Status":         ["Line #", "Return Status", "Flow Status"],
            "💰 Type & Pricing": ["Line #", "Line Type", "Payment Term"]
        }
        l_tabs = st.tabs(list(line_sections.keys()))
        for tab, (_, col_keys) in zip(l_tabs, line_sections.items()):
            with tab: _render_line_section(d["lines"], col_keys)
    else:
        st.info("ℹ️ No line details found in the response.")

    st.markdown("---")
    with st.expander("🔍 View Full Raw API Response"):
        st.json(result)

# ==================================================
# CHAT CONTAINER
# ==================================================
chat_container = st.container(height=450, border=False)
with chat_container:
    if not st.session_state.messages:
        welcome = "👋 Welcome to the Centroid Sales Order Assistant!\n\n"
        assistant_say(welcome, speak_text="Welcome to the Centroid Sales Order Assistant.")
        gh_add("assistant", welcome)
        
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

# ==================================================
# SIDEBAR
# ==================================================
with st.sidebar:
    st.markdown("### 📋 Fields Collected")
    c = st.session_state.collected
    known = {k: v for k, v in c.items() if v is not None}
    if known:
        for k, v in known.items(): st.markdown(f"**{k}**: `{v}`")
    else:
        st.info("No fields collected yet.")
    st.markdown("---")
    if st.button("🔄 Reset / Start Over", use_container_width=True):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

st.markdown("---")

# ==================================================
# STAGES: UI Resolution State Machine
# ==================================================
stage = st.session_state.stage

if stage == "select_item":
    def confirm_item(row):
        st.session_state.collected["inventory_item_id"] = row["inventory_item_id"]
        st.session_state.collected["ordered_item"]      = row["segment1"]
        assistant_say(f"✅ Item selected: `{row['segment1']}` — {row['description']}", speak_text=f"Item selected: {row['segment1']}")

    render_selection_ui("Inventory Item", "item_rows", "item", lambda r: f"ID={r['inventory_item_id']}  {r['segment1']}  {r['description']}", confirm_item)

elif stage == "select_price":
    def confirm_price(row):
        st.session_state.collected["price_list_id"]      = row["price_list_id"]
        st.session_state.collected["price_list_name"]    = row["price_list_name"]
        st.session_state.collected["unit_list_price"]    = row["unit_list_price"]
        st.session_state.collected["unit_selling_price"] = row["unit_list_price"]
        assistant_say(f"✅ Price List: `{row['price_list_name']}` — Unit Price: `${row['unit_list_price']:.2f}`", speak_text=f"Price list selected: {row['price_list_name']}")
        st.session_state.stage = "selling_price_override"

    render_selection_ui("Price List", "price_rows", "price", lambda r: f"ID={r['price_list_id']}  {r['price_list_name']}  ${r['unit_list_price']:.2f}", confirm_price, next_stage="selling_price_override")

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
            assistant_say(f"✅ Selling Price set to: `${c['unit_selling_price']:.2f}`", speak_text=f"Selling price confirmed at {c['unit_selling_price']} dollars.")
            st.session_state.stage = "resolve"
            st.rerun()

elif stage == "select_term":
    def confirm_term(row):
        st.session_state.collected["payment_term_id"]   = row["term_id"]
        st.session_state.collected["payment_term_name"] = row["term_name"]
        assistant_say(f"✅ Payment Term: `{row['term_name']}`", speak_text=f"Payment term confirmed as {row['term_name']}")

    render_selection_ui("Payment Term", "term_rows", "term", lambda r: f"ID={r['term_id']}  {r['term_name']}", confirm_term)

elif stage == "select_rep":
    def confirm_rep(row):
        st.session_state.collected["salesrep_id"]   = row["salesrep_id"]
        st.session_state.collected["salesrep_name"] = row["salesrep_name"]
        assistant_say(f"✅ Sales Rep: `{row['salesrep_name']}`", speak_text=f"Sales representative confirmed as {row['salesrep_name']}")

    render_selection_ui("Sales Rep", "rep_rows", "rep", lambda r: f"ID={r['salesrep_id']}  {r['salesrep_name']}", confirm_rep)

elif stage == "select_line_type":
    st.markdown("### 📝 Select Line Type")
    st.info("A Line Type is required to process the order. Select from the list below.")

    rows = st.session_state.get("line_type_rows", [])
    if not rows and hasattr(bot, 'get_line_type_rows'):
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
                assistant_say(f"✅ Line Type: `{selected['line_type_name']}` (ID: {selected['line_type_id']})", speak_text=f"Line type confirmed as {selected['line_type_name']}")
                st.session_state.stage = "resolve"
                st.rerun()
        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page"):
                    st.session_state.offsets["line_type"] += bot.MAX_CHOICES
                    st.session_state.line_type_rows = bot.get_line_type_rows(offset=st.session_state.offsets["line_type"])
                    st.rerun()
        with col3:
            if st.session_state.offsets.get("line_type", 0) > 0:
                if st.button("⬅️ Previous Page"):
                    st.session_state.offsets["line_type"] = max(0, st.session_state.offsets["line_type"] - bot.MAX_CHOICES)
                    st.session_state.line_type_rows = bot.get_line_type_rows(offset=st.session_state.offsets["line_type"])
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
                    assistant_say(f"✅ Line Type ID set to: `{val}`", speak_text="Line type confirmed.")
                    st.session_state.stage = "resolve"
                    st.rerun()
                else:
                    st.error("Please enter a valid numeric ID.")
        with col2:
            if st.button("❌ Cancel"):
                st.session_state.stage = "chat"
                st.rerun()

elif stage == "select_customer":
    st.markdown("### 🔍 Select Customer")
    search_val = st.text_input("Search customer by name:", value=st.session_state.collected.get("customer_name") or "", key="customer_search_input")
    if st.button("🔍 Search"):
        st.session_state.offsets["customer"] = 0
        st.session_state.collected["customer_name"] = search_val
        st.session_state.customer_rows = bot.get_customer_by_name_rows(search_val, offset=0)
        st.rerun()

    rows = st.session_state.get("customer_rows", [])
    if rows:
        opts = [f"[{i+1}] {r['customer_name']}  (Acct#: {r['account_number']}, ID: {r['cust_account_id']})" for i, r in enumerate(rows)]
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
                        f"✅ Customer: `{sites[0]['customer_name']}`  | Sold-to: `{sites[0]['sold_to_org_id']}`  | Ship-to: `{sites[0]['ship_to_org_id']}`",
                        speak_text=f"Customer confirmed as {sites[0]['customer_name']}"
                    )
                    st.session_state.stage = "resolve"
                else:
                    st.session_state.site_rows, st.session_state.stage = sites, "select_site"
                st.rerun()
        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page"):
                    st.session_state.offsets["customer"] += bot.MAX_CHOICES
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(name, offset=st.session_state.offsets["customer"])
                    st.rerun()
        with col3:
            if st.session_state.offsets["customer"] > 0:
                if st.button("⬅️ Prev Page"):
                    st.session_state.offsets["customer"] = max(0, st.session_state.offsets["customer"] - bot.MAX_CHOICES)
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(name, offset=st.session_state.offsets["customer"])
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

elif stage == "select_customer_by_item":
    c = st.session_state.collected
    item_name = c.get("ordered_item", "selected item")

    # FIX 6: guard — if inventory_item_id is None, fall back to name search
    if not c.get("inventory_item_id"):
        assistant_say("⚠️ No item selected yet. Please search for a customer by name instead.")
        st.session_state.customer_rows = []
        st.session_state.stage = "select_customer"
        st.rerun()

    st.markdown(f"### 🔍 Select Customer for Item: `{item_name}`")
    st.info("Showing customers who have previously ordered this item (or all active customers as fallback).")

    rows = st.session_state.get("customer_by_item_rows", [])
    if not rows:
        st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=st.session_state.offsets["customer_by_item"])

    if st.session_state.customer_by_item_rows:
        opts = [f"[{i+1}] {r['customer_name']}  (Acct#: {r['account_number']}, ID: {r['cust_account_id']})" for i, r in enumerate(st.session_state.customer_by_item_rows)]
        choice = st.radio("**Select Customer:**", opts)

        col1, col2, col3, col4, col5 = st.columns([1, 1, 1, 1, 1])
        with col1:
            if st.button("✅ Confirm Customer"):
                idx = opts.index(choice)
                selected = st.session_state.customer_by_item_rows[idx]
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
                        f"✅ Customer: `{sites[0]['customer_name']}`  | Sold-to: `{sites[0]['sold_to_org_id']}`  | Ship-to: `{sites[0]['ship_to_org_id']}`",
                        speak_text=f"Customer confirmed as {sites[0]['customer_name']}"
                    )
                    st.session_state.stage = "resolve"
                else:
                    st.session_state.site_rows, st.session_state.stage = sites, "select_site"
                st.rerun()
        with col2:
            if len(st.session_state.customer_by_item_rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page"):
                    st.session_state.offsets["customer_by_item"] += bot.MAX_CHOICES
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=st.session_state.offsets["customer_by_item"])
                    st.rerun()
        with col3:
            if st.session_state.offsets["customer_by_item"] > 0:
                if st.button("⬅️ Prev Page"):
                    st.session_state.offsets["customer_by_item"] = max(0, st.session_state.offsets["customer_by_item"] - bot.MAX_CHOICES)
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=st.session_state.offsets["customer_by_item"])
                    st.rerun()
        with col4:
            if st.button("🔍 Search by Name Instead"):
                st.session_state.customer_rows, st.session_state.stage = [], "select_customer"
                st.rerun()
        with col5:
            if st.button("❌ Cancel"):
                st.session_state.stage = "chat"
                st.rerun()
    else:
        st.warning("No customers found for this item. Try searching by name.")
        if st.button("🔍 Search by Name"):
            st.session_state.customer_rows, st.session_state.stage = [], "select_customer"
            st.rerun()
        if st.button("❌ Cancel"):
            st.session_state.stage = "chat"
            st.rerun()

elif stage == "select_site":
    def confirm_site(row):
        st.session_state.collected["sold_to_org_id"] = row["sold_to_org_id"]
        st.session_state.collected