import streamlit as st
import SalesOrderBot12 as bot
import json
import pandas as pd

st.set_page_config(page_title="Sales Order Assistant", page_icon="📦", layout="wide")
st.title("📦 Sales Order Assistant")
st.caption("🤖 Powered by Groq · llama-3.1-8b-instant")

# --------------------------------------------------
# Session state bootstrap
# --------------------------------------------------
def _init_state():
    defaults = {
        "messages":      [],
        "stage":         "chat",
        "action":        None,
        "get_order_num": None,
        "offsets": {"item": 0, "price": 0, "term": 0, "rep": 0, "site": 0},
        # ALL possible payload fields in one flat dict.
        # Groq extraction populates whatever the user mentioned.
        # Each resolve guard checks this before hitting the DB.
        "collected": {
            "cpo":               None,   # CUST_PO_NUMBER
            "ordered_item":      None,   # SEGMENT1 / item code
            "quantity":          None,   # ORDERED_QUANTITY
            "order_number":      None,   # for GET
            "inventory_item_id": None,   # user may supply directly
            "price_list_id":     None,   # user may supply directly
            "price_list_name":   None,
            "unit_list_price":   None,   # user may supply directly
            "unit_selling_price":None,   # user may supply directly
            "payment_term_id":   None,   # user may supply directly
            "payment_term_name": None,
            "salesrep_id":       None,   # user may supply directly
            "salesrep_name":     None,
            "sold_to_org_id":    None,   # user may supply directly
            "ship_to_org_id":    None,   # user may supply directly
            "customer_name":     None,
        },
        "item_rows":  [], "price_rows": [], "term_rows":  [],
        "rep_rows":   [], "site_rows":  [],
        "api_result":    None,
        "groq_history":  [],
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
    st.session_state.groq_history.append({"role": role, "content": content})


def merge_fields(extracted: dict):
    """
    Merge Groq-extracted fields into collected.
    Groq returns keys that match collected keys directly.
    Never overwrite an existing value with None.
    """
    c = st.session_state.collected
    mapping = {
        # groq key        → collected key
        "cpo":               "cpo",
        "ordered_item":      "ordered_item",
        "quantity":          "quantity",
        "order_number":      "order_number",
        "inventory_item_id": "inventory_item_id",
        "price_list_id":     "price_list_id",
        "unit_list_price":   "unit_list_price",
        "unit_selling_price":"unit_selling_price",
        "payment_term_id":   "payment_term_id",
        "salesrep_id":       "salesrep_id",
        "sold_to_org_id":    "sold_to_org_id",
        "ship_to_org_id":    "ship_to_org_id",
        "customer_name":     "customer_name",
    }
    for groq_key, col_key in mapping.items():
        val = extracted.get(groq_key)
        if val is not None:
            c[col_key] = val

    # Also uppercase the item code if present
    if c.get("ordered_item"):
        c["ordered_item"] = str(c["ordered_item"]).strip().upper()


def missing_minimum() -> list:
    """Return the 3 hard-minimum fields still missing."""
    c = st.session_state.collected
    missing = []
    if not c.get("cpo"):
        missing.append("CUST_PO_NUMBER")
    if not c.get("ordered_item") and not c.get("inventory_item_id"):
        missing.append("ORDERED_ITEM code (e.g. CM94532) or INVENTORY_ITEM_ID")
    if c.get("quantity") is None:
        missing.append("ORDERED_QUANTITY")
    return missing


def all_payload_fields_present() -> bool:
    """
    Returns True when every field needed to call the REST API is already
    in collected — meaning zero DB lookups are required.
    """
    c = st.session_state.collected
    return all([
        c.get("cpo"),
        c.get("ordered_item") or c.get("inventory_item_id"),
        c.get("quantity") is not None,
        c.get("inventory_item_id"),
        c.get("price_list_id"),
        c.get("unit_list_price")  is not None,
        c.get("unit_selling_price") is not None,
        c.get("payment_term_id"),
        c.get("salesrep_id"),
        c.get("sold_to_org_id"),
        c.get("ship_to_org_id"),
    ])


# --------------------------------------------------
# Generic paginated selection UI
# --------------------------------------------------
def render_selection_ui(label, row_key, offset_key, display_fn, on_confirm):
    rows = st.session_state[row_key]
    if not rows:
        st.warning(f"No {label} records found.")
        if st.button("⬅️ Go Back"):
            st.session_state.stage = "chat"
            st.rerun()
        return

    opts   = [f"[{i+1}] {display_fn(r)}" for i, r in enumerate(rows)]
    choice = st.radio(f"**Select {label}:**", opts, key=f"radio_{offset_key}")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button(f"✅ Confirm {label}", key=f"confirm_{offset_key}"):
            idx = opts.index(choice)
            on_confirm(rows[idx])
            st.session_state.stage = "resolve"
            st.rerun()
    with col2:
        if len(rows) >= bot.MAX_CHOICES:
            if st.button("📑 Next Page", key=f"next_{offset_key}"):
                st.session_state.offsets[offset_key] += bot.MAX_CHOICES
                st.session_state.stage = "resolve"
                st.rerun()
    with col3:
        if st.button("❌ Cancel", key=f"cancel_{offset_key}"):
            st.session_state.stage = "chat"
            st.rerun()


# --------------------------------------------------
# ERP response parser & display
# --------------------------------------------------
def extract_erp_details(result: dict) -> dict:
    data         = result.get("OutputParameters", result)
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
        "Order Number":  header.get("ORDER_NUMBER",            "N/A"),
        "Header ID":     header.get("HEADER_ID",               "N/A"),
        "Customer PO":   header.get("CUST_PO_NUMBER",          "N/A"),
        "Return Status": header.get("RETURN_STATUS",           "N/A"),
        "Flow Status":   header.get("FLOW_STATUS_CODE",        "N/A"),
        "Order Category":header.get("ORDER_CATEGORY_CODE",     "N/A"),
        "Ordered Date":  header.get("ORDERED_DATE",            "N/A"),
        "Currency":      header.get("TRANSACTIONAL_CURR_CODE", "N/A"),
        "Payment Term":  header_val.get("PAYMENT_TERM",        "N/A"),
        "Price List":    header_val.get("PRICE_LIST",          "N/A"),
        "Order Type":    header_val.get("ORDER_TYPE",          "N/A"),
        "Customer":      header_val.get("SOLD_TO_ORG",         "N/A"),
        "Ship To":       header_val.get("SHIP_TO_ORG",         "N/A"),
        "Bill To":       header_val.get("INVOICE_TO_ORG",      "N/A"),
        "Salesrep":      header_val.get("SALESREP",            "N/A"),
        "Booked Flag":   header.get("BOOKED_FLAG",             "N/A"),
        "Open Flag":     header.get("OPEN_FLAG",               "N/A"),
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
            "Line #":             line.get("LINE_NUMBER",         "N/A"),
            "Line ID":            line.get("LINE_ID",             "N/A"),
            "Item":               line.get("ORDERED_ITEM",        "N/A"),
            "Item Description":   val.get("INVENTORY_ITEM",       "N/A"),
            "Qty Ordered":        line.get("ORDERED_QUANTITY",    "N/A"),
            "UOM":                line.get("ORDER_QUANTITY_UOM",  "N/A"),
            "Unit List Price":    line.get("UNIT_LIST_PRICE",     "N/A"),
            "Unit Selling Price": line.get("UNIT_SELLING_PRICE",  "N/A"),
            "Line Type":          val.get("LINE_TYPE",            "N/A"),
            "Payment Term":       val.get("PAYMENT_TERM",         "N/A"),
            "Flow Status":        line.get("FLOW_STATUS_CODE",    "N/A"),
            "Return Status":      line.get("RETURN_STATUS",       "N/A"),
        })

    return {"status": status, "message": message_text,
            "header_details": header_details, "lines": lines}


def _render_line_section(lines: list, col_keys: list):
    active_cols = [k for k in col_keys
                   if any(ln.get(k) not in (None, "", "N/A") for ln in lines)]
    if not active_cols:
        st.info("No data available in this section."); return
    if len(lines) == 1:
        line = lines[0]
        st.markdown("| Field | Value |\n|---|---|\n" +
                    "\n".join(f"| **{k}** | {line.get(k,'N/A')} |" for k in active_cols))
    else:
        records = [{"Line #": ln.get("Line #", "N/A"),
                    **{k: ln.get(k, "N/A") for k in active_cols if k != "Line #"}}
                   for ln in lines]
        st.dataframe(pd.DataFrame(records).replace("N/A", ""),
                     use_container_width=True, hide_index=True)


def display_erp_response(result: dict, context_label: str = "Order"):
    d  = extract_erp_details(result)
    sv = str(d["status"]).upper()
    emoji = {"S": "✅", "E": "❌", "W": "⚠️"}.get(sv, "ℹ️")
    label = {"S": "Success", "E": "Error",   "W": "Warning"}.get(sv, sv)
    banner = (f"{emoji} **{context_label} {label}!** &nbsp;|&nbsp; "
              f"Order # `{d['header_details'].get('Order Number','N/A')}` &nbsp;|&nbsp; "
              f"Header ID `{d['header_details'].get('Header ID','N/A')}`")
    assistant_say(banner)
    st.markdown(banner)

    if d["message"] and d["message"] != "N/A":
        st.markdown("### 💬 ERP Messages")
        for msg in d["message"].split(" | "):
            if msg.strip(): st.warning(msg.strip())

    st.markdown("---")
    st.markdown("## 🧾 Header Details")
    hd = d["header_details"]
    header_sections = {
        "📋 Order Identity":     ["Order Number","Header ID","Customer PO","Order Category","Order Type"],
        "📅 Dates & Status":     ["Return Status","Flow Status","Booked Flag","Open Flag","Ordered Date"],
        "💰 Financial & Parties":["Currency","Payment Term","Price List","Customer","Ship To","Bill To","Salesrep"],
    }
    h_tabs = st.tabs(list(header_sections.keys()))
    for tab, (_, fields) in zip(h_tabs, header_sections.items()):
        with tab:
            md = "\n".join(f"| **{k}** | {hd.get(k,'N/A')} |"
                           for k in fields if hd.get(k) and hd.get(k) != "N/A")
            st.markdown(f"| Field | Value |\n|---|---|\n{md}") if md else st.info("No data.")

    st.markdown("---")
    n = len(d["lines"])
    st.markdown(f"## 📦 Line Details <span style='color:gray;font-size:0.85rem'>({n} line{'s' if n!=1 else ''})</span>",
                unsafe_allow_html=True)
    if d["lines"]:
        line_sections = {
            "📋 Identity":       ["Line #","Line ID","Item","Item Description"],
            "📦 Qty & Price":    ["Line #","Qty Ordered","UOM","Unit List Price","Unit Selling Price"],
            "🔖 Status":         ["Line #","Return Status","Flow Status"],
            "💰 Type & Pricing": ["Line #","Line Type","Payment Term"],
        }
        l_tabs = st.tabs(list(line_sections.keys()))
        for tab, (_, cols) in zip(l_tabs, line_sections.items()):
            with tab: _render_line_section(d["lines"], cols)
    else:
        st.info("No line details found.")

    st.markdown("---")
    with st.expander("🔍 Full Raw API Response"):
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
        "👋 Welcome to the **Sales Order Assistant**!\n\n"
        "You can **create** a new order or **retrieve** an existing one.\n\n"
        "💡 Tip — supply as many fields as you know and I'll skip the DB lookups:\n"
        "```\ncreate a sales_order with CUST_PO_NUMBER=PO028,\n"
        "ORDERED_ITEM=CM94532, ORDERED_QUANTITY=1,\n"
        "UNIT_LIST_PRICE=145.0, UNIT_SELLING_PRICE=145.0,\n"
        "PAYMENT_TERM_ID=1000, SALESREP_ID=1001,\n"
        "SHIP_TO_ORG_ID=3730, SOLD_TO_ORG_ID=3347\n```"
    )
    assistant_say(welcome)
    gh_add("assistant", welcome)
    st.rerun()

# --------------------------------------------------
# Sidebar — live view of collected fields
# --------------------------------------------------
with st.sidebar:
    st.markdown("### 📋 Collected Fields")
    c     = st.session_state.collected
    known = {k: v for k, v in c.items() if v is not None}
    if known:
        for k, v in known.items():
            st.markdown(f"**{k}**: `{v}`")
        # Show what's still needed
        missing = missing_minimum()
        if missing:
            st.markdown("---\n**⚠️ Still needed:**")
            for m in missing: st.markdown(f"- {m}")
        elif all_payload_fields_present():
            st.success("✅ All fields present — next submit skips DB!")
    else:
        st.info("No fields collected yet.")

    if st.button("🔄 Reset / Start Over"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# ==================================================
# STAGE: Selection UIs
# ==================================================
stage = st.session_state.stage

if stage == "select_item":
    def _confirm_item(row):
        c = st.session_state.collected
        c["inventory_item_id"] = row["inventory_item_id"]
        c["ordered_item"]      = row["segment1"]
        assistant_say(f"✅ Item: `{row['segment1']}` (ID={row['inventory_item_id']})")

    render_selection_ui("Inventory Item", "item_rows", "item",
                        lambda r: f"ID={r['inventory_item_id']}  {r['segment1']}  {r['description']}",
                        _confirm_item)

elif stage == "select_price":
    def _confirm_price(row):
        c = st.session_state.collected
        c["price_list_id"]      = row["price_list_id"]
        c["price_list_name"]    = row["price_list_name"]
        c["unit_list_price"]    = row["unit_list_price"]
        c["unit_selling_price"] = row["unit_list_price"]
        assistant_say(f"✅ Price List: `{row['price_list_name']}` — ${row['unit_list_price']:.2f}")

    render_selection_ui("Price List", "price_rows", "price",
                        lambda r: f"ID={r['price_list_id']}  {r['price_list_name']}  ${r['unit_list_price']:.2f}",
                        _confirm_price)

elif stage == "select_term":
    def _confirm_term(row):
        c = st.session_state.collected
        c["payment_term_id"]   = row["term_id"]
        c["payment_term_name"] = row["term_name"]
        assistant_say(f"✅ Payment Term: `{row['term_name']}` (ID={row['term_id']})")

    render_selection_ui("Payment Term", "term_rows", "term",
                        lambda r: f"ID={r['term_id']}  {r['term_name']}",
                        _confirm_term)

elif stage == "select_rep":
    def _confirm_rep(row):
        c = st.session_state.collected
        c["salesrep_id"]   = row["salesrep_id"]
        c["salesrep_name"] = row["salesrep_name"]
        assistant_say(f"✅ Sales Rep: `{row['salesrep_name']}` (ID={row['salesrep_id']})")

    render_selection_ui("Sales Rep", "rep_rows", "rep",
                        lambda r: f"ID={r['salesrep_id']}  {r['salesrep_name']}",
                        _confirm_rep)

elif stage == "select_site":
    def _confirm_site(row):
        c = st.session_state.collected
        c["sold_to_org_id"] = row["sold_to_org_id"]
        c["ship_to_org_id"] = row["ship_to_org_id"]
        c["customer_name"]  = row["customer_name"]
        assistant_say(f"✅ Customer: `{row['customer_name']}` "
                      f"(SoldTo={row['sold_to_org_id']}, ShipTo={row['ship_to_org_id']})")

    render_selection_ui("Customer Site", "site_rows", "site",
                        lambda r: f"Customer={r['customer_name']}  "
                                  f"SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}",
                        _confirm_site)

# ==================================================
# STAGE: resolve
# Guard-based step-by-step resolver.
# Each step checks: "does collected already have this value?"
#   YES → skip entirely (no DB call, no UI)
#   NO  → fetch rows; if 1 row auto-select, else show UI
# ==================================================
elif stage == "resolve":
    c    = st.session_state.collected
    offs = st.session_state.offsets

    with st.spinner("⏳ Resolving order details..."):
        try:
            # ── GUARD 1: Inventory Item ───────────────────
            # Skip if inventory_item_id already known.
            if c.get("inventory_item_id") is None:
                if not c.get("ordered_item"):
                    assistant_say("❌ ORDERED_ITEM or INVENTORY_ITEM_ID is required.")
                    st.session_state.stage = "error"; st.rerun()

                rows = bot.get_inventory_item_rows(c["ordered_item"], offset=offs["item"])
                if not rows:
                    assistant_say(f"❌ Item `{c['ordered_item']}` not found in ERP.")
                    st.session_state.stage = "error"; st.rerun()
                if len(rows) == 1 and offs["item"] == 0:
                    c["inventory_item_id"] = rows[0]["inventory_item_id"]
                    c["ordered_item"]      = rows[0]["segment1"]
                    # stay in resolve — fall through to next guard
                else:
                    st.session_state.item_rows = rows
                    st.session_state.stage = "select_item"; st.rerun()
            else:
                # inventory_item_id already set; ensure ordered_item is also set
                if not c.get("ordered_item"):
                    c["ordered_item"] = str(c["inventory_item_id"])

            # ── GUARD 2: Price List ───────────────────────
            # Skip if BOTH price_list_id AND unit_list_price already known.
            if c.get("price_list_id") is None or c.get("unit_list_price") is None:
                rows = bot.get_price_details_rows(
                    c["ordered_item"], float(c["quantity"] or 1),
                    c["inventory_item_id"], offset=offs["price"])
                if not rows:
                    assistant_say("❌ No price list found for this item.")
                    st.session_state.stage = "error"; st.rerun()
                if len(rows) == 1 and offs["price"] == 0:
                    c["price_list_id"]      = rows[0]["price_list_id"]
                    c["unit_list_price"]    = rows[0]["unit_list_price"]
                    c["unit_selling_price"] = c.get("unit_selling_price") or rows[0]["unit_list_price"]
                else:
                    st.session_state.price_rows = rows
                    st.session_state.stage = "select_price"; st.rerun()
            else:
                # Both price fields supplied by user — ensure selling price is set
                if c.get("unit_selling_price") is None:
                    c["unit_selling_price"] = c["unit_list_price"]

            # ── GUARD 3: Payment Term ─────────────────────
            # Skip if payment_term_id already known.
            if c.get("payment_term_id") is None:
                rows = bot.get_payment_term_rows(offset=offs["term"])
                if not rows:
                    assistant_say("❌ No payment terms found.")
                    st.session_state.stage = "error"; st.rerun()
                if len(rows) == 1 and offs["term"] == 0:
                    c["payment_term_id"]   = rows[0]["term_id"]
                    c["payment_term_name"] = rows[0]["term_name"]
                else:
                    st.session_state.term_rows = rows
                    st.session_state.stage = "select_term"; st.rerun()

            # ── GUARD 4: Sales Rep ────────────────────────
            # Skip if salesrep_id already known.
            if c.get("salesrep_id") is None:
                rows = bot.get_salesrep_rows(offset=offs["rep"])
                if not rows:
                    assistant_say("❌ No active sales reps found.")
                    st.session_state.stage = "error"; st.rerun()
                if len(rows) == 1 and offs["rep"] == 0:
                    c["salesrep_id"]   = rows[0]["salesrep_id"]
                    c["salesrep_name"] = rows[0]["salesrep_name"]
                else:
                    st.session_state.rep_rows = rows
                    st.session_state.stage = "select_rep"; st.rerun()

            # ── GUARD 5: Customer Site ────────────────────
            # Skip if BOTH sold_to_org_id AND ship_to_org_id already known.
            if c.get("sold_to_org_id") is None or c.get("ship_to_org_id") is None:
                rows = bot.get_customer_site_rows(
                    c["ordered_item"], offset=offs["site"],
                    sold_to_org_id=c.get("sold_to_org_id"),
                    ship_to_org_id=c.get("ship_to_org_id"))
                if not rows:
                    assistant_say("❌ No customer sites found for this item.")
                    st.session_state.stage = "error"; st.rerun()
                if len(rows) == 1 and offs["site"] == 0:
                    c["sold_to_org_id"] = rows[0]["sold_to_org_id"]
                    c["ship_to_org_id"] = rows[0]["ship_to_org_id"]
                    c["customer_name"]  = rows[0]["customer_name"]
                else:
                    st.session_state.site_rows = rows
                    st.session_state.stage = "select_site"; st.rerun()

            # ── All resolved → confirm ────────────────────
            st.session_state.stage = "confirm_order"
            st.rerun()

        except Exception as e:
            assistant_say(f"❌ Resolution error: `{e}`")
            st.session_state.stage = "error"; st.rerun()

# ==================================================
# STAGE: confirm_order
# ==================================================
elif stage == "confirm_order":
    c = st.session_state.collected

    if not any("Order Summary" in m["content"] for m in st.session_state.messages):
        summary = "**📋 Order Summary — please review before submitting:**\n\n| Field | Value |\n|---|---|\n"
        display_map = {
            "CUST_PO_NUMBER":    c.get("cpo"),
            "ORDERED_ITEM":      c.get("ordered_item"),
            "ORDERED_QUANTITY":  c.get("quantity"),
            "INVENTORY_ITEM_ID": c.get("inventory_item_id"),
            "PRICE_LIST_ID":     c.get("price_list_id"),
            "UNIT_LIST_PRICE":   c.get("unit_list_price"),
            "UNIT_SELLING_PRICE":c.get("unit_selling_price"),
            "PAYMENT_TERM_ID":   c.get("payment_term_id"),
            "SALESREP_ID":       c.get("salesrep_id"),
            "SOLD_TO_ORG_ID":    c.get("sold_to_org_id"),
            "SHIP_TO_ORG_ID":    c.get("ship_to_org_id"),
            "OPERATING_UNIT":    bot.OPERATING_UNIT,
        }
        for label, val in display_map.items():
            if val is not None:
                summary += f"| **{label}** | `{val}` |\n"
        assistant_say(summary)
        assistant_say("Does everything look correct? Click **Submit Order** to proceed.")
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Submit Order", key="btn_submit"):
            with st.spinner("⏳ Submitting order to ERP..."):
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
                        p_ship_to_org     = c["ship_to_org_id"],
                        p_sold_to_org     = c["sold_to_org_id"],
                        p_operating_unit  = bot.OPERATING_UNIT,
                    )
                    st.session_state.api_result = bot.send_order(payload)
                    st.session_state.stage = "done"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Submit failed: `{e}`")
                    st.session_state.stage = "error"; st.rerun()
    with col2:
        if st.button("🔄 Start Over", key="btn_restart"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

# ==================================================
# STAGE: done / show_get_order
# ==================================================
elif stage in ("done", "show_get_order"):
    result = st.session_state.get("api_result", {})

    if isinstance(result, dict) and "total_count" in result:
        st.success(f"✅ Found **{result['total_count']}** orders matching your criteria!")
        if result["rows"]:
            df = pd.DataFrame(result["rows"],
                              columns=["Order Number", "Flow Status", "Creation Date"])
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No rows returned.")
    else:
        context = "Order" if stage == "done" else "Retrieved Order"
        display_erp_response(result, context_label=context)

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🆕 Create Another Order" if stage == "done" else "🔍 New Search"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()
    with col2:
        if st.button("🔍 Get an Order"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

# ==================================================
# STAGE: error
# ==================================================
elif stage == "error":
    if st.button("🔄 Start Over"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# ==================================================
# STAGE: fetch_get_order
# ==================================================
elif stage == "fetch_get_order":
    with st.spinner(f"⏳ Retrieving Order {st.session_state.get_order_num}..."):
        try:
            result = bot.get_order(st.session_state.get_order_num)
            st.session_state.api_result = result
            st.session_state.stage = "show_get_order"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ Failed to retrieve order: `{e}`")
            st.session_state.stage = "error"; st.rerun()

# ==================================================
# MAIN CHAT INPUT  (stage == "chat")
# ==================================================
elif stage == "chat":
    # Quick-action buttons on first load
    if not any(m["role"] == "user" for m in st.session_state.messages):
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🆕 Create Sales Order", use_container_width=True):
                user_say("Create a new sales order")
                gh_add("user", "Create a new sales order")
                st.session_state.action = "create"
                q = bot.groq_clarify(st.session_state.groq_history,
                                     ["CUST_PO_NUMBER", "ORDERED_ITEM", "ORDERED_QUANTITY"])
                assistant_say(q); gh_add("assistant", q)
                st.rerun()
        with col2:
            if st.button("🔍 Get Sales Order", use_container_width=True):
                user_say("Retrieve an existing sales order")
                gh_add("user", "Retrieve an existing sales order")
                st.session_state.action = "get"
                q = bot.groq_clarify(st.session_state.groq_history, ["Order Number"])
                assistant_say(q); gh_add("assistant", q)
                st.rerun()

    placeholder = (
        "e.g. create sales_order with CUST_PO_NUMBER=PO028, ORDERED_ITEM=CM94532, "
        "ORDERED_QUANTITY=1, UNIT_LIST_PRICE=145.0, PAYMENT_TERM_ID=1000, "
        "SALESREP_ID=1001, SHIP_TO_ORG_ID=3730, SOLD_TO_ORG_ID=3347"
    )

    if prompt := st.chat_input(placeholder):
        if prompt.strip().lower() in ("exit", "quit", "stop"):
            st.warning("Session ended. Refresh to start over.")
            st.stop()

        user_say(prompt)
        gh_add("user", prompt)

        # ── Step 1: Extract all fields from user message ──
        extracted = bot.groq_extract_intent(prompt)
        action    = extracted.get("action", "unknown")

        # ── Step 2: Merge into collected ──────────────────
        merge_fields(extracted)

        c = st.session_state.collected

        # ── Advanced search (year / date_range / status) ──
        if extracted.get("year") or extracted.get("date_range") or \
           (extracted.get("status") and not c.get("order_number")):
            with st.spinner("⏳ Searching orders..."):
                try:
                    res = bot.get_orders_advanced(
                        extracted.get("date_range"),
                        extracted.get("year"),
                        extracted.get("status"))
                    st.session_state.api_result = res
                    st.session_state.stage = "show_get_order"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Search error: `{e}`"); st.rerun()

        # ── GET specific order by number ──────────────────
        elif action == "get" or st.session_state.action == "get":
            st.session_state.action = "get"
            order_num = c.get("order_number")
            if order_num is None:
                q = bot.groq_clarify(st.session_state.groq_history, ["Order Number"])
                assistant_say(q); gh_add("assistant", q); st.rerun()
            else:
                st.session_state.get_order_num = int(order_num)
                st.session_state.stage = "fetch_get_order"; st.rerun()

        # ── CREATE order ──────────────────────────────────
        elif action == "create" or st.session_state.action == "create":
            st.session_state.action = "create"

            # Check the 3 hard-minimum fields
            missing = missing_minimum()
            if missing:
                # Acknowledge what was captured so far
                captured = [k for k, v in c.items() if v is not None]
                if captured:
                    ack = ("✅ Captured: " +
                           ", ".join(f"**{k}**=`{c[k]}`" for k in captured[:6]) + ".")
                    assistant_say(ack); gh_add("assistant", ack)

                q = bot.groq_clarify(st.session_state.groq_history, missing)
                assistant_say(q); gh_add("assistant", q); st.rerun()
            else:
                # Minimum fields present — go to resolve
                # (Guards inside resolve will skip DB for any already-supplied field)
                st.session_state.stage = "resolve"; st.rerun()

        # ── Unknown intent ────────────────────────────────
        else:
            # Check if some order fields were captured even without a clear action
            captured = [k for k, v in c.items() if v is not None]
            if captured:
                ack = ("Got: " +
                       ", ".join(f"**{k}**=`{c[k]}`" for k in captured[:6]) +
                       ". Should I **create** a new order or **get** an existing one?")
                assistant_say(ack); gh_add("assistant", ack)
            else:
                fallback = bot.groq_clarify(
                    st.session_state.groq_history,
                    ["action: 'create a new order', 'get order by number', "
                     "or 'search orders by year/status'"])
                assistant_say(fallback); gh_add("assistant", fallback)
            st.rerun()
