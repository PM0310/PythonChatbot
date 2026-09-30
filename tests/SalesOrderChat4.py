import streamlit as st
import SalesOrderBot9 as bot
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
        "messages":       [],
        "stage":          "chat",          # single conversational stage
        "action":         None,
        "get_order_num":  None,
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
        },
        # Selection UI data
        "item_rows":   [], "price_rows":  [], "term_rows":   [],
        "rep_rows":    [], "site_rows":   [],
        # ERP results
        "api_result":      None,
        "groq_history":    [],
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
    for k, v in extracted.items():
        if k in st.session_state.collected and v is not None:
            st.session_state.collected[k] = v

def missing_minimum() -> list:
    c = st.session_state.collected
    missing = []
    if not c.get("cpo"): missing.append("Customer PO Number")
    if not c.get("ordered_item") and not c.get("inventory_item_id"): missing.append("Ordered Item code")
    if not c.get("quantity"): missing.append("Ordered Quantity")
    return missing

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
        "👋 Welcome to the Sales Order Assistant!\n\n"
        "You can **create** a new order or **retrieve** an existing one. "
        "Share whatever details you know — I'll automatically fetch everything else from the ERP."
    )
    assistant_say(welcome); gh_add("assistant", welcome)
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
    if st.button("🔄 Reset / Start Over"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# ==================================================
# STAGES: UI Resolution State Machine
# ==================================================
stage = st.session_state.stage

if stage == "select_item":
    rows = st.session_state.item_rows
    opts = [f"[{i+1}] ID={r['inventory_item_id']}  {r['segment1']}  {r['description']}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Inventory Item:**", opts)
    if st.button("Confirm Item"):
        idx = opts.index(choice)
        st.session_state.collected["inventory_item_id"] = rows[idx]["inventory_item_id"]
        st.session_state.collected["ordered_item"]      = rows[idx]["segment1"]
        assistant_say(f"✅ Item selected: `{rows[idx]['segment1']}`"); st.session_state.stage = "resolve"; st.rerun()

elif stage == "select_price":
    rows = st.session_state.price_rows
    opts = [f"[{i+1}] ID={r['price_list_id']}  {r['price_list_name']}  ${r['unit_list_price']:.2f}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Price List:**", opts)
    if st.button("Confirm Price List"):
        idx = opts.index(choice)
        st.session_state.collected["price_list_id"]   = rows[idx]["price_list_id"]
        st.session_state.collected["price_list_name"] = rows[idx]["price_list_name"]
        st.session_state.collected["unit_list_price"] = rows[idx]["unit_list_price"]
        st.session_state.collected["unit_selling_price"] = rows[idx]["unit_list_price"]
        assistant_say(f"✅ Price List: `{rows[idx]['price_list_name']}`"); st.session_state.stage = "resolve"; st.rerun()

elif stage == "select_term":
    rows = st.session_state.term_rows
    opts = [f"[{i+1}] ID={r['term_id']}  {r['term_name']}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Payment Term:**", opts)
    if st.button("Confirm Payment Term"):
        idx = opts.index(choice)
        st.session_state.collected["payment_term_id"]   = rows[idx]["term_id"]
        st.session_state.collected["payment_term_name"] = rows[idx]["term_name"]
        assistant_say(f"✅ Payment Term: `{rows[idx]['term_name']}`"); st.session_state.stage = "resolve"; st.rerun()

elif stage == "select_rep":
    rows = st.session_state.rep_rows
    opts = [f"[{i+1}] ID={r['salesrep_id']}  {r['salesrep_name']}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Sales Rep:**", opts)
    if st.button("Confirm Sales Rep"):
        idx = opts.index(choice)
        st.session_state.collected["salesrep_id"]   = rows[idx]["salesrep_id"]
        st.session_state.collected["salesrep_name"] = rows[idx]["salesrep_name"]
        assistant_say(f"✅ Sales Rep: `{rows[idx]['salesrep_name']}`"); st.session_state.stage = "resolve"; st.rerun()

elif stage == "select_site":
    rows = st.session_state.site_rows
    opts = [f"[{i+1}] Customer={r['customer_name']}  SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}" for i, r in enumerate(rows)]
    choice = st.radio("**Select Customer Site:**", opts)
    if st.button("Confirm Customer Site"):
        idx = opts.index(choice)
        st.session_state.collected["sold_to_org_id"] = rows[idx]["sold_to_org_id"]
        st.session_state.collected["ship_to_org_id"] = rows[idx]["ship_to_org_id"]
        st.session_state.collected["customer_name"]  = rows[idx]["customer_name"]
        assistant_say(f"✅ Customer: `{rows[idx]['customer_name']}`"); st.session_state.stage = "resolve"; st.rerun()

# ==================================================
# STAGE: resolve — Smart Step-by-Step DB Fetching
# ==================================================
elif stage == "resolve":
    c = st.session_state.collected
    with st.spinner("⏳ Resolving order details..."):
        try:
            # 1. Resolve Item
            if c.get("ordered_item") and not c.get("inventory_item_id"):
                rows = bot.get_inventory_item_rows(c["ordered_item"])
                if len(rows) == 1: c["inventory_item_id"] = rows[0]["inventory_item_id"]; st.rerun()
                else: st.session_state.item_rows = rows; st.session_state.stage = "select_item"; st.rerun()
            
            # 2. Resolve Price
            if c.get("inventory_item_id") and c.get("quantity") and not c.get("price_list_id"):
                rows = bot.get_price_details_rows(c["ordered_item"], float(c["quantity"]), c["inventory_item_id"])
                if len(rows) == 1: 
                    c["price_list_id"], c["unit_list_price"], c["unit_selling_price"] = rows[0]["price_list_id"], rows[0]["unit_list_price"], rows[0]["unit_list_price"]
                    st.rerun()
                else: st.session_state.price_rows = rows; st.session_state.stage = "select_price"; st.rerun()

            # 3. Resolve Payment Term
            if not c.get("payment_term_id"):
                rows = bot.get_payment_term_rows()
                if len(rows) == 1: c["payment_term_id"] = rows[0]["term_id"]; st.rerun()
                else: st.session_state.term_rows = rows; st.session_state.stage = "select_term"; st.rerun()

            # 4. Resolve Sales Rep
            if not c.get("salesrep_id"):
                rows = bot.get_salesrep_rows()
                if len(rows) == 1: c["salesrep_id"] = rows[0]["salesrep_id"]; st.rerun()
                else: st.session_state.rep_rows = rows; st.session_state.stage = "select_rep"; st.rerun()

            # 5. Resolve Customer Sites
            if c.get("ordered_item") and (not c.get("sold_to_org_id") or not c.get("ship_to_org_id")):
                rows = bot.get_customer_site_rows(c["ordered_item"])
                if len(rows) == 1: 
                    c["sold_to_org_id"], c["ship_to_org_id"], c["customer_name"] = rows[0]["sold_to_org_id"], rows[0]["ship_to_org_id"], rows[0]["customer_name"]
                    st.rerun()
                else: st.session_state.site_rows = rows; st.session_state.stage = "select_site"; st.rerun()

            # Everything is resolved! Move to confirmation.
            st.session_state.stage = "confirm_order"
            st.rerun()

        except Exception as e:
            assistant_say(f"❌ Error during resolution: {e}")
            st.session_state.stage = "error"
            st.rerun()

# ==================================================
# STAGE: show_get_order & done (Raw API Display)
# ==================================================
elif stage in ["show_get_order", "done"]:
    st.success("✅ Operation completed successfully!")
    st.json(st.session_state.get("api_result", {}))
    st.markdown("---")
    if st.button("🔄 Start Over"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

elif stage == "error":
    if st.button("🔄 Start Over"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

elif stage == "fetch_get_order":
    with st.spinner(f"⏳ Retrieving Order {st.session_state.get_order_num}..."):
        try:
            result = bot.get_order(st.session_state.get_order_num)
            st.session_state.api_result = result
            st.session_state.stage = "show_get_order"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ Failed: {e}"); st.session_state.stage = "error"; st.rerun()

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
                        p_cust_po = c["cpo"], p_item_id = c["inventory_item_id"], p_ordered_item = c["ordered_item"],
                        p_qty = c["quantity"], p_price = c["unit_list_price"], p_selling_price = c["unit_selling_price"],
                        p_payment_term_id = c["payment_term_id"], p_price_list_id = c["price_list_id"],
                        p_salesrep_id = c["salesrep_id"], p_ship_to_org = c["ship_to_org_id"], p_sold_to_org = c["sold_to_org_id"],
                        p_operating_unit = bot.OPERATING_UNIT,
                    )
                    st.session_state.api_result = bot.send_order(payload)
                    st.session_state.stage = "done"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Submit Error: {e}"); st.session_state.stage = "error"; st.rerun()
    with col2:
        if st.button("🔄 Start Over"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

# ==================================================
# MAIN CHAT INPUT
# ==================================================
elif stage == "chat":
    placeholder = "Tell me anything you know: 'Create order for CM94532, qty 5, PO ABC-001' or 'quit'..."
    if prompt := st.chat_input(placeholder):
        if prompt.strip().lower() in ("exit", "quit", "stop"):
            st.warning("Chat session ended by user. Refresh the page to start over.")
            st.stop()

        user_say(prompt); gh_add("user", prompt)
        extracted = bot.groq_extract_intent(prompt)
        action    = extracted.get("action", "unknown")
        merge_fields(extracted)

        if action == "get" or st.session_state.action == "get":
            st.session_state.action = "get"
            order_num = st.session_state.collected.get("order_number")
            if order_num is None:
                q = bot.groq_clarify(st.session_state.groq_history, ["Order Number"])
                assistant_say(q); gh_add("assistant", q); st.rerun()
            else:
                st.session_state.get_order_num = int(order_num)
                st.session_state.stage = "fetch_get_order"; st.rerun()

        elif action == "create" or st.session_state.action == "create":
            st.session_state.action = "create"
            missing = missing_minimum()
            if missing:
                q = bot.groq_clarify(st.session_state.groq_history, missing)
                assistant_say(q); gh_add("assistant", q); st.rerun()
            else:
                st.session_state.stage = "resolve"; st.rerun()
        else:
            fallback = bot.groq_clarify(st.session_state.groq_history, ["action: create a new order or retrieve an existing one"])
            assistant_say(fallback); gh_add("assistant", fallback); st.rerun()