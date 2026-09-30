import streamlit as st
import SalesOrderBot6 as bot
import json
import pandas as pd
from groq import Groq

# ─────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sales Order Assistant",
    page_icon="📦",
    layout="wide",
)

# ─────────────────────────────────────────────────────────────────
# CUSTOM CSS  – dark industrial + AI panel
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600&display=swap');

/* ── global ──────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background: #0f1117;
    color: #e0e6f0;
}

/* ── main title ──────────────────────────────────── */
h1 {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 1.45rem !important;
    letter-spacing: 0.06em;
    color: #7dd3fc !important;
    border-bottom: 1px solid #1e293b;
    padding-bottom: 0.5rem;
}

/* ── column divider ─────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border: none !important;
}

/* ── AI panel card ──────────────────────────────── */
.ai-card {
    background: #0d1520;
    border: 1px solid #1e3a5f;
    border-radius: 12px;
    padding: 1rem 1rem 0.75rem 1rem;
}

.ai-card-header {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #38bdf8;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    border-bottom: 1px solid #1e3a5f;
    padding-bottom: 0.55rem;
    margin-bottom: 0.65rem;
}

/* ── chat history scroll area ────────────────────── */
.ai-history {
    max-height: 380px;
    overflow-y: auto;
    margin-bottom: 0.6rem;
    padding-right: 3px;
}
.ai-history::-webkit-scrollbar { width: 3px; }
.ai-history::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 2px; }

/* ── bubble styles ───────────────────────────────── */
.bubble-user {
    background: #112240;
    border-left: 3px solid #38bdf8;
    border-radius: 0 8px 8px 0;
    padding: 0.45rem 0.75rem;
    margin: 0.35rem 0;
    font-size: 0.8rem;
    color: #bae6fd;
    word-break: break-word;
}
.bubble-ai {
    background: #0a1929;
    border-left: 3px solid #0ea5e9;
    border-radius: 0 8px 8px 0;
    padding: 0.45rem 0.75rem;
    margin: 0.35rem 0;
    font-size: 0.8rem;
    color: #e0f2fe;
    line-height: 1.55;
    word-break: break-word;
}
.bubble-label {
    font-size: 0.65rem;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.08em;
    opacity: 0.55;
    margin-bottom: 0.1rem;
}

/* ── context badge ───────────────────────────────── */
.ctx-badge {
    display: inline-block;
    background: #0c2340;
    border: 1px solid #1e4976;
    border-radius: 20px;
    padding: 0.12rem 0.6rem;
    font-size: 0.7rem;
    font-family: 'IBM Plex Mono', monospace;
    color: #7dd3fc;
    margin-bottom: 0.55rem;
    margin-right: 0.2rem;
}

/* ── suggestion chips ────────────────────────────── */
.chip-row { margin-bottom: 0.55rem; display: flex; flex-wrap: wrap; gap: 0.3rem; }
.chip {
    background: #162032;
    border: 1px solid #1e4976;
    border-radius: 6px;
    padding: 0.18rem 0.55rem;
    font-size: 0.7rem;
    color: #93c5fd;
    cursor: pointer;
    font-family: 'IBM Plex Mono', monospace;
}

/* ── main workflow chat ──────────────────────────── */
[data-testid="stChatMessage"] {
    background: #131923 !important;
    border: 1px solid #1e2d3d !important;
    border-radius: 8px !important;
}

/* ── buttons ─────────────────────────────────────── */
.stButton > button {
    background: #0c4a6e;
    color: #e0f2fe;
    border: 1px solid #0369a1;
    border-radius: 6px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    transition: all 0.15s;
}
.stButton > button:hover {
    background: #075985;
    border-color: #38bdf8;
    color: #fff;
}

/* ── text input ──────────────────────────────────── */
input[type="text"], [data-testid="stTextInput"] input {
    background: #0d1520 !important;
    color: #e0f2fe !important;
    border: 1px solid #1e3a5f !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.8rem !important;
}

hr { border-color: #1e293b !important; }

/* ── Groq badge (re-used the gemini class) ───────── */
.gemini-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    color: #f97316;
    background: #431407;
    border: 1px solid #9a3412;
    border-radius: 4px;
    padding: 0.1rem 0.4rem;
    margin-left: 0.4rem;
    vertical-align: middle;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────
# GROQ SETUP 
# ─────────────────────────────────────────────────────────────────
GROQ_API_KEY = "REDACTED_SECRET"   # ← Replace with your actual key!
GROQ_MODEL   = "llama-3.1-8b-instant"

# Initialize the Groq client
client = Groq(api_key=GROQ_API_KEY)


# ─────────────────────────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        # workflow
        "messages":             [],
        "stage":                "choose_action",
        "action":               None,
        "cpo":                  None,
        "ordered_item":         None,
        "qty":                  None,
        "get_order_num":        None,
        "item_rows":            [], "item_chosen":  None,
        "price_rows":           [], "price_chosen": None,
        "term_rows":            [], "term_chosen":  None,
        "rep_rows":             [],  "rep_chosen":  None,
        "site_rows":            [], "site_chosen":  None,
        "db":                   None,
        "order_done":           False,
        "api_result":           None,
        # AI assistant
        "ai_messages":      [],   # [{role, content}] for Groq history
        "ai_display":       [],   # [{role, text}]  for UI
        "ai_user_input":    "",
        "ai_pending_input": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─────────────────────────────────────────────────────────────────
# WORKFLOW HELPERS
# ─────────────────────────────────────────────────────────────────
def assistant_say(msg: str):
    st.session_state.messages.append({"role": "assistant", "content": msg})

def user_say(msg: str):
    st.session_state.messages.append({"role": "user", "content": msg})


# ─────────────────────────────────────────────────────────────────
# BUILD CONTEXT STRING FOR AI
# ─────────────────────────────────────────────────────────────────
def _build_context() -> str:
    s  = st.session_state
    stage_labels = {
        "choose_action":  "Waiting for user to choose Create or Get order",
        "ask_cpo":        "Asking for Customer PO Number",
        "ask_item":       "Asking for Ordered Item code",
        "ask_qty":        "Asking for Quantity",
        "lookup_item":    "Looking up inventory item in ERP",
        "select_item":    "User selecting from multiple inventory items",
        "lookup_price":   "Looking up price list",
        "select_price":   "User selecting from multiple price lists",
        "lookup_term":    "Looking up payment terms",
        "select_term":    "User selecting payment term",
        "lookup_rep":     "Looking up sales reps",
        "select_rep":     "User selecting sales rep",
        "lookup_site":    "Looking up customer ship-to sites",
        "select_site":    "User selecting customer site",
        "confirm_order":  "Showing order summary, awaiting user confirmation",
        "submit_order":   "Submitting order to ERP",
        "done":           "Order successfully submitted",
        "ask_get_order_num": "Asking for order number to retrieve",
        "fetch_get_order":   "Fetching order from ERP",
        "show_get_order":    "Displaying retrieved order",
        "error":             "Workflow encountered an error",
    }
    parts = [
        f"Stage: {stage_labels.get(s.stage, s.stage)}",
    ]
    if s.action:          parts.append(f"Action: {s.action}")
    if s.cpo:             parts.append(f"Customer PO: {s.cpo}")
    if s.ordered_item:    parts.append(f"Item Code: {s.ordered_item}")
    if s.qty:             parts.append(f"Quantity: {int(s.qty)}")
    if s.item_chosen:
        ic = s.item_chosen
        parts.append(f"Inventory Item: {ic.get('segment1')} (ID {ic.get('inventory_item_id')}) – {ic.get('description','')}")
    if s.price_chosen:
        pc = s.price_chosen
        parts.append(f"Price List: {pc.get('price_list_name')} @ ${pc.get('unit_list_price',0):.2f} (ID {pc.get('price_list_id')})")
    if s.term_chosen:
        parts.append(f"Payment Term: {s.term_chosen.get('term_name')} (ID {s.term_chosen.get('term_id')})")
    if s.rep_chosen:
        parts.append(f"Sales Rep: {s.rep_chosen.get('salesrep_name')} (ID {s.rep_chosen.get('salesrep_id')})")
    if s.site_chosen:
        sc = s.site_chosen
        parts.append(f"Customer: {sc.get('customer_name')} | SoldTo: {sc.get('sold_to_org_id')} | ShipTo: {sc.get('ship_to_org_id')}")
    if s.api_result:
        d = s.api_result.get("OutputParameters", s.api_result)
        hdr = d.get("X_HEADER_REC", {}) or {}
        on  = hdr.get("ORDER_NUMBER", "")
        st_ = hdr.get("RETURN_STATUS", "")
        if on:  parts.append(f"ERP Order Number: {on}")
        if st_: parts.append(f"ERP Return Status: {st_}")
    return "\n".join(parts)

SYSTEM_INSTRUCTION = """You are an expert ERP Sales Order AI Assistant embedded inside a Streamlit application.
The app helps users create and retrieve Oracle ERP Sales Orders.

Your role:
• Answer questions about the current order being created or retrieved.
• Explain Oracle ERP concepts (order types, price lists, payment terms, flow status codes, etc.).
• Guide users when they are confused about what to enter next.
• Diagnose errors returned by the ERP and suggest remedies.
• Be concise – keep answers under 180 words unless the user explicitly asks for more detail.
• Use bullet points for multi-step answers.
• Never invent order numbers or ERP data – only reference what is in the context.
• When the user asks "what should I do next?" always base your answer on the current stage context.
• You can speak about general Oracle Order Management (OM) best practices."""


# ─────────────────────────────────────────────────────────────────
# GROQ CHAT CALL
# ─────────────────────────────────────────────────────────────────
def call_groq(user_input: str) -> str:
    try:
        context_block = _build_context()
        system_with_ctx = (
            SYSTEM_INSTRUCTION
            + f"\n\n--- LIVE SESSION CONTEXT ---\n{context_block}\n---"
        )

        # Build message history for Groq
        messages = [{"role": "system", "content": system_with_ctx}]
        messages.extend(st.session_state.ai_messages)

        # Call Groq API
        chat_completion = client.chat.completions.create(
            messages=messages,
            model=GROQ_MODEL,
        )
        return chat_completion.choices[0].message.content

    except Exception as e:
        return f"❌ Groq error: `{e}`"


def _send_ai_message(user_input: str):
    """Push a user message through Groq and store results."""
    user_input = user_input.strip()
    if not user_input:
        return

    # Store in display list
    st.session_state.ai_display.append({"role": "user", "text": user_input})
    # Store in Groq history (before calling so it's not sent twice)
    st.session_state.ai_messages.append({"role": "user", "content": user_input})

    # Call Groq
    ai_reply = call_groq(user_input)

    # Store AI reply
    st.session_state.ai_display.append({"role": "assistant", "text": ai_reply})
    st.session_state.ai_messages.append({"role": "assistant", "content": ai_reply})


# ─────────────────────────────────────────────────────────────────
# SUGGESTION CHIPS
# ─────────────────────────────────────────────────────────────────
SUGGESTIONS_BY_STAGE = {
    "choose_action":     ["What is a Sales Order?", "Difference between Create and Get?"],
    "ask_cpo":           ["What is a Customer PO?", "Can I use any alphanumeric PO?"],
    "ask_item":          ["What item format is expected?", "Where do I find item codes?"],
    "ask_qty":           ["What UOM will be used?", "Can quantity be a decimal?"],
    "lookup_item":       ["Why might item lookup fail?", "What is Organization ID?"],
    "select_item":       ["Which item should I choose?", "What does Inventory Item ID mean?"],
    "lookup_price":      ["How are price lists matched?", "What if no price list is found?"],
    "select_price":      ["Which price list is best?", "What is list price vs selling price?"],
    "lookup_term":       ["What are payment terms?", "What does NET 30 mean?"],
    "select_term":       ["Which payment term should I pick?"],
    "lookup_rep":        ["What does a Sales Rep do in ERP?"],
    "select_rep":        ["Which rep should I select?"],
    "lookup_site":       ["What is a Ship-To site?", "What is Sold-To vs Ship-To?"],
    "select_site":       ["What is the difference between Sold-To and Ship-To?"],
    "confirm_order":     ["What happens after I submit?", "Can I edit after submitting?"],
    "done":              ["What does Flow Status mean?", "How do I track my order?"],
    "error":             ["How do I fix ERP errors?", "What does return status E mean?"],
    "show_get_order":    ["What does Booked Flag mean?", "Explain Flow Status codes"],
}


# ─────────────────────────────────────────────────────────────────
# ERP PARSER (unchanged from original)
# ─────────────────────────────────────────────────────────────────
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
        "Order Number":          header.get("ORDER_NUMBER",              "N/A"),
        "Header ID":             header.get("HEADER_ID",                 "N/A"),
        "Customer PO":           header.get("CUST_PO_NUMBER",            "N/A"),
        "Orig Sys Document Ref": header.get("ORIG_SYS_DOCUMENT_REF",     "N/A"),
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
        "Currency":              header.get("TRANSACTIONAL_CURR_CODE",   "N/A"),
        "Payment Term ID":       header.get("PAYMENT_TERM_ID",           "N/A"),
        "Payment Term":          header_val.get("PAYMENT_TERM",          "N/A"),
        "Price List ID":         header.get("PRICE_LIST_ID",             "N/A"),
        "Price List":            header_val.get("PRICE_LIST",            "N/A"),
        "Org ID":                header.get("ORG_ID",                    "N/A"),
        "Order Type ID":         header.get("ORDER_TYPE_ID",             "N/A"),
        "Order Type":            header_val.get("ORDER_TYPE",            "N/A"),
        "Order Source ID":       header.get("ORDER_SOURCE_ID",           "N/A"),
        "Order Source":          header_val.get("ORDER_SOURCE",          "N/A"),
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
        "Salesrep ID":           header.get("SALESREP_ID",               "N/A"),
        "Salesrep":              header_val.get("SALESREP",              "N/A"),
        "Demand Class":          header_val.get("DEMAND_CLASS",          "N/A"),
        "Ship From Org":         header_val.get("SHIP_FROM_ORG",         "N/A"),
        "Freight Carrier":       header_val.get("FREIGHT_CARRIER",       "N/A"),
        "Shipping Method":       header_val.get("SHIPPING_METHOD",       "N/A"),
        "FOB Point":             header_val.get("FOB_POINT",             "N/A"),
        "Freight Terms":         header_val.get("FREIGHT_TERMS",         "N/A"),
        "Tax Exempt Flag":       header.get("TAX_EXEMPT_FLAG",           "N/A"),
        "Version Number":        header.get("VERSION_NUMBER",            "N/A"),
        "Lock Control":          header.get("LOCK_CONTROL",              "N/A"),
        "XML Message ID":        header.get("XML_MESSAGE_ID",            "N/A"),
        "Created By":            header.get("CREATED_BY",                "N/A"),
        "Creation Date":         header.get("CREATION_DATE",             "N/A"),
        "Last Updated By":       header.get("LAST_UPDATED_BY",           "N/A"),
        "Last Update Date":      header.get("LAST_UPDATE_DATE",          "N/A"),
    }

    line_tbl     = data.get("X_LINE_TBL",     {}) or {}
    line_val_tbl = data.get("X_LINE_VAL_TBL", {}) or {}
    line_adj_tbl = data.get("X_LINE_ADJ_TBL", {}) or {}

    def _get_items(tbl, *keys):
        for k in keys:
            v = tbl.get(k)
            if v is not None:
                return [v] if isinstance(v, dict) else list(v)
        return []

    raw_lines     = _get_items(line_tbl,     "X_LINE_TBL_ITEM",     "P_LINE_TBL_ITEM")
    raw_line_vals = _get_items(line_val_tbl, "X_LINE_VAL_TBL_ITEM", "P_LINE_VAL_TBL_ITEM")
    raw_line_adjs = _get_items(line_adj_tbl, "X_LINE_ADJ_TBL_ITEM")

    adj_by_line_id = {}
    for adj in raw_line_adjs:
        lid = str(adj.get("LINE_ID", "") or "")
        if lid:
            adj_by_line_id[lid] = adj

    lines = []
    for i, line in enumerate(raw_lines):
        val     = raw_line_vals[i] if i < len(raw_line_vals) else {}
        line_id = str(line.get("LINE_ID", "") or "")
        adj     = adj_by_line_id.get(line_id, {})
        lines.append({
            "Line #":               line.get("LINE_NUMBER",              "N/A"),
            "Line ID":              line.get("LINE_ID",                  "N/A"),
            "Header ID":            line.get("HEADER_ID",                "N/A"),
            "Shipment #":           line.get("SHIPMENT_NUMBER",          "N/A"),
            "Orig Sys Line Ref":    line.get("ORIG_SYS_LINE_REF",        "N/A"),
            "Item":                 line.get("ORDERED_ITEM",             "N/A"),
            "Item Description":     val.get("INVENTORY_ITEM",            "N/A"),
            "Inventory Item ID":    line.get("INVENTORY_ITEM_ID",        "N/A"),
            "Item Type":            line.get("ITEM_TYPE_CODE",           "N/A"),
            "Qty Ordered":          line.get("ORDERED_QUANTITY",         "N/A"),
            "Qty Cancelled":        line.get("CANCELLED_QUANTITY",       "N/A"),
            "UOM":                  line.get("ORDER_QUANTITY_UOM",       "N/A"),
            "Pricing Qty":          line.get("PRICING_QUANTITY",         "N/A"),
            "Unit List Price":      line.get("UNIT_LIST_PRICE",          "N/A"),
            "Unit Selling Price":   line.get("UNIT_SELLING_PRICE",       "N/A"),
            "Unit Cost":            line.get("UNIT_COST",                "N/A"),
            "Tax Code":             adj.get("TAX_CODE") or line.get("TAX_CODE", "N/A"),
            "Tax Rate %":           adj.get("OPERAND",                   "N/A"),
            "Tax Amount":           adj.get("ADJUSTED_AMOUNT",           "N/A"),
            "Tax Value":            line.get("TAX_VALUE",                "N/A"),
            "Price Adj ID":         adj.get("PRICE_ADJUSTMENT_ID",       "N/A"),
            "List Line Type":       adj.get("LIST_LINE_TYPE_CODE",       "N/A"),
            "Request Date":         line.get("REQUEST_DATE",             "N/A"),
            "Promise Date":         line.get("PROMISE_DATE",             "N/A"),
            "Earliest Accept Date": line.get("EARLIEST_ACCEPTABLE_DATE", "N/A"),
            "Latest Accept Date":   line.get("LATEST_ACCEPTABLE_DATE",   "N/A"),
            "Pricing Date":         line.get("PRICING_DATE",             "N/A"),
            "Fulfillment Date":     line.get("FULFILLMENT_DATE",         "N/A"),
            "Return Status":        line.get("RETURN_STATUS",            "N/A"),
            "Flow Status":          line.get("FLOW_STATUS_CODE",         "N/A"),
            "Line Category":        line.get("LINE_CATEGORY_CODE",       "N/A"),
            "Open Flag":            line.get("OPEN_FLAG",                "N/A"),
            "Booked Flag":          line.get("BOOKED_FLAG",              "N/A"),
            "Cancelled Flag":       line.get("CANCELLED_FLAG",           "N/A"),
            "Shippable Flag":       line.get("SHIPPABLE_FLAG",           "N/A"),
            "Fulfilled Flag":       line.get("FULFILLED_FLAG",           "N/A"),
            "Operation":            line.get("OPERATION",                "N/A"),
            "Line Type ID":         line.get("LINE_TYPE_ID",             "N/A"),
            "Line Type":            val.get("LINE_TYPE",                 "N/A"),
            "Payment Term":         val.get("PAYMENT_TERM",              "N/A"),
            "Price List":           val.get("PRICE_LIST",                "N/A"),
            "Calculate Price Flag": line.get("CALCULATE_PRICE_FLAG",     "N/A"),
            "Tax Exempt Flag":      line.get("TAX_EXEMPT_FLAG",          "N/A"),
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
            "Customer PO": hd.get("Customer PO"), "Orig Sys Document Ref": hd.get("Orig Sys Document Ref"),
            "Order Category": hd.get("Order Category"), "Order Type": hd.get("Order Type"),
            "Order Source": hd.get("Order Source"), "Transaction Phase": hd.get("Transaction Phase"),
            "Operation": hd.get("Operation"),
        },
        "📅 Dates & Status": {
            "Return Status": hd.get("Return Status"), "Flow Status": hd.get("Flow Status"),
            "Booked Flag": hd.get("Booked Flag"), "Open Flag": hd.get("Open Flag"),
            "Cancelled Flag": hd.get("Cancelled Flag"), "Ordered Date": hd.get("Ordered Date"),
            "Request Date": hd.get("Request Date"), "Pricing Date": hd.get("Pricing Date"),
        },
        "💰 Financial": {
            "Currency": hd.get("Currency"), "Payment Term": hd.get("Payment Term"),
            "Price List": hd.get("Price List"), "Tax Exempt Flag": hd.get("Tax Exempt Flag"),
        },
        "🏢 Parties": {
            "Customer": hd.get("Customer"), "Customer Number": hd.get("Customer Number"),
            "Ship To": hd.get("Ship To"), "Ship To Address": hd.get("Ship To Address"),
            "Ship To City": hd.get("Ship To City"), "Ship To State": hd.get("Ship To State"),
            "Ship To Zip": hd.get("Ship To Zip"), "Ship To Country": hd.get("Ship To Country"),
            "Bill To": hd.get("Bill To"), "Bill To Address": hd.get("Bill To Address"),
            "Bill To City": hd.get("Bill To City"), "Bill To State": hd.get("Bill To State"),
            "Bill To Zip": hd.get("Bill To Zip"), "Bill To Country": hd.get("Bill To Country"),
            "Salesrep": hd.get("Salesrep"), "Demand Class": hd.get("Demand Class"),
        },
        "🚚 Shipping": {
            "Ship From Org": hd.get("Ship From Org"), "Freight Carrier": hd.get("Freight Carrier"),
            "Shipping Method": hd.get("Shipping Method"), "FOB Point": hd.get("FOB Point"),
            "Freight Terms": hd.get("Freight Terms"),
        },
        "🔧 System Info": {
            "Org ID": hd.get("Org ID"), "Order Type ID": hd.get("Order Type ID"),
            "Order Source ID": hd.get("Order Source ID"), "Payment Term ID": hd.get("Payment Term ID"),
            "Price List ID": hd.get("Price List ID"), "Salesrep ID": hd.get("Salesrep ID"),
            "Version Number": hd.get("Version Number"), "Lock Control": hd.get("Lock Control"),
            "Created By": hd.get("Created By"), "Creation Date": hd.get("Creation Date"),
            "Last Updated By": hd.get("Last Updated By"), "Last Update Date": hd.get("Last Update Date"),
        },
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
            "📋 Identity":       ["Line #","Line ID","Header ID","Shipment #","Orig Sys Line Ref","Item","Item Description","Inventory Item ID","Item Type"],
            "📦 Qty & Price":    ["Line #","Qty Ordered","Qty Cancelled","UOM","Pricing Qty","Unit List Price","Unit Selling Price","Unit Cost","Calculate Price Flag"],
            "📅 Dates":          ["Line #","Request Date","Promise Date","Earliest Accept Date","Latest Accept Date","Pricing Date","Fulfillment Date"],
            "🔖 Status":         ["Line #","Return Status","Flow Status","Line Category","Open Flag","Booked Flag","Cancelled Flag","Shippable Flag","Fulfilled Flag","Operation"],
            "💰 Type & Pricing":  ["Line #","Line Type ID","Line Type","Payment Term","Price List","Tax Exempt Flag"],
            "🧾 Tax & Adj":      ["Line #","Tax Code","Tax Rate %","Tax Amount","Tax Value","Price Adj ID","List Line Type"],
            "🚚 Shipping":       ["Line #","Ship To Org","Ship To Address","Ship To City","Ship To State","Ship To Country","Ship From Org","Shipping Method","Freight Carrier","Source Type","Ship Tolerance Above","Ship Tolerance Below"],
            "🔧 System Info":    ["Line #","Created By","Creation Date","Last Updated By","Last Update Date"],
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


# ─────────────────────────────────────────────────────────────────
# RENDER AI ASSISTANT PANEL
# ─────────────────────────────────────────────────────────────────
def render_ai_panel():
    st.markdown("""
    <div class="ai-card">
      <div class="ai-card-header">
        🤖 AI Assistant
        <span class="gemini-badge">Groq Llama 3.1</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Context badges ────────────────────────────────────────
    s = st.session_state
    ctx_items = []
    if s.ordered_item: ctx_items.append(f"📦 {s.ordered_item}")
    if s.qty:          ctx_items.append(f"🔢 Qty {int(s.qty)}")
    if s.price_chosen: ctx_items.append(f"💲{s.price_chosen.get('unit_list_price',0):.0f}")
    if s.site_chosen:  ctx_items.append(f"🏢 {s.site_chosen.get('customer_name','')[:16]}")

    if ctx_items:
        badges = " ".join(f'<span class="ctx-badge">{c}</span>' for c in ctx_items)
        st.markdown(badges, unsafe_allow_html=True)

    # ── Suggestion chips ──────────────────────────────────────
    chips = SUGGESTIONS_BY_STAGE.get(s.stage, ["What can you help me with?", "Explain this step"])
    cols  = st.columns(len(chips))
    for col, chip in zip(cols, chips):
        with col:
            if st.button(chip, key=f"chip_{chip[:30]}", use_container_width=True):
                st.session_state.ai_pending_input = chip
                st.rerun()

    st.markdown("---")

    # ── Chat history ──────────────────────────────────────────
    history_html = '<div class="ai-history" id="ai-hist">'
    if not st.session_state.ai_display:
        history_html += (
            '<div class="bubble-ai">'
            "👋 Hi! I'm your ERP Sales Order assistant powered by Groq. "
            "Ask me anything about this order, Oracle ERP concepts, or what to do next."
            "</div>"
        )
    else:
        for msg in st.session_state.ai_display:
            role  = msg["role"]
            text  = msg["text"].replace("\n", "<br>")
            label = "You" if role == "user" else "Groq"
            cls   = "bubble-user" if role == "user" else "bubble-ai"
            history_html += (
                f'<div class="bubble-label">{label}</div>'
                f'<div class="{cls}">{text}</div>'
            )
    history_html += "</div>"
    st.markdown(history_html, unsafe_allow_html=True)

    # ── Input box ─────────────────────────────────────────────
    ai_input = st.chat_input(
        "Ask the AI assistant…",
        key="ai_chat_input",
    )

    # Process typed input OR chip click
    pending = st.session_state.pop("ai_pending_input", None) if "ai_pending_input" in st.session_state else None
    query   = ai_input or pending

    if query:
        with st.spinner("Groq is thinking…"):
            _send_ai_message(query)
        st.rerun()

    # ── Clear chat button ─────────────────────────────────────
    if st.session_state.ai_display:
        if st.button("🗑️ Clear chat", key="btn_clear_ai", use_container_width=True):
            st.session_state.ai_display  = []
            st.session_state.ai_messages = []
            st.rerun()


# ─────────────────────────────────────────────────────────────────
# PAGE LAYOUT – two columns
# ─────────────────────────────────────────────────────────────────
main_col, ai_col = st.columns([3, 1.1], gap="large")

with main_col:
    st.title("📦 Sales Order Assistant")

    # ── Render existing chat history ──────────────────────────
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # ─────────────────────────────────────────────────────────
    # STAGE MACHINE
    # ─────────────────────────────────────────────────────────
    stage = st.session_state.stage

    # ── choose_action ─────────────────────────────────────────
    if stage == "choose_action":
        if not any(m["role"] == "assistant" for m in st.session_state.messages):
            assistant_say(
                "Hello! 👋 What would you like to do?\n\n"
                "- **Create** a new Sales Order\n"
                "- **Get** an existing Sales Order by Order Number"
            )
            st.rerun()

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🆕 Create Sales Order", key="btn_action_create", use_container_width=True):
                user_say("Create Sales Order")
                st.session_state.action = "create"
                assistant_say("Great! Let's create a new Sales Order.\n\nWhat is the **Customer PO Number**?")
                st.session_state.stage = "ask_cpo"
                st.rerun()
        with col2:
            if st.button("🔍 Get Sales Order", key="btn_action_get", use_container_width=True):
                user_say("Get Sales Order")
                st.session_state.action = "get"
                assistant_say("Sure! Please enter the **Order Number** you want to retrieve.")
                st.session_state.stage = "ask_get_order_num"
                st.rerun()

    # ── ask_get_order_num ─────────────────────────────────────
    elif stage == "ask_get_order_num":
        if prompt := st.chat_input("Enter Order Number to retrieve..."):
            user_say(prompt)
            order_num = bot.parse_numeric_value(prompt, allow_float=False)
            if order_num is None:
                assistant_say("⚠️ That doesn't look like a valid order number. Please try again.")
                st.rerun()
            else:
                st.session_state.get_order_num = int(order_num)
                assistant_say(f"⏳ Fetching Order **{int(order_num)}** from ERP...")
                st.session_state.stage = "fetch_get_order"
                st.rerun()

    # ── fetch_get_order ───────────────────────────────────────
    elif stage == "fetch_get_order":
        with st.spinner(f"⏳ Retrieving Order {st.session_state.get_order_num}..."):
            try:
                result = bot.get_order(st.session_state.get_order_num)
                st.session_state.api_result = result
                st.session_state.stage = "show_get_order"
                st.rerun()
            except Exception as e:
                assistant_say(f"❌ Failed to retrieve order: `{e}`")
                st.session_state.stage = "error"
                st.rerun()

    # ── show_get_order ────────────────────────────────────────
    elif stage == "show_get_order":
        result = st.session_state.get("api_result", {})
        display_erp_response(result, context_label="Retrieved Order")
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔍 Get Another Order", key="btn_get_another"):
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()
        with col2:
            if st.button("🆕 Create New Order", key="btn_go_create"):
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()

    # ── ask_cpo ───────────────────────────────────────────────
    elif stage == "ask_cpo":
        if prompt := st.chat_input("Enter Customer PO Number..."):
            user_say(prompt)
            st.session_state.cpo = prompt.strip()
            assistant_say(f"Got it — PO: **{st.session_state.cpo}**.\n\nWhat is the **Ordered Item** (e.g. `CM94532`)?")
            st.session_state.stage = "ask_item"
            st.rerun()

    # ── ask_item ──────────────────────────────────────────────
    elif stage == "ask_item":
        if prompt := st.chat_input("Enter Ordered Item code..."):
            user_say(prompt)
            st.session_state.ordered_item = prompt.strip().upper()
            assistant_say(f"Item: **{st.session_state.ordered_item}**.\n\nWhat is the **Ordered Quantity**?")
            st.session_state.stage = "ask_qty"
            st.rerun()

    # ── ask_qty ───────────────────────────────────────────────
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

    # ── lookup_item ───────────────────────────────────────────
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
                assistant_say(f"❌ Item **{st.session_state.ordered_item}** not found. Please re-enter.")
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

    # ── select_item ───────────────────────────────────────────
    elif stage == "select_item":
        rows    = st.session_state.item_rows
        options = [f"[{i+1}] ID={r['inventory_item_id']}  Segment={r['segment1']}  Desc={r['description']}"
                   for i, r in enumerate(rows)]
        choice  = st.radio("**Select Inventory Item:**", options, key="radio_item")
        if st.button("Confirm Item Selection", key="btn_item"):
            idx = options.index(choice)
            st.session_state.item_chosen = rows[idx]
            user_say(f"Selected Item: {choice}")
            assistant_say(f"✅ Item confirmed: `{rows[idx]['segment1']}` — {rows[idx]['description']}")
            st.session_state.stage = "lookup_price"
            st.rerun()

    # ── lookup_price ──────────────────────────────────────────
    elif stage == "lookup_price":
        item_id_str = str(st.session_state.item_chosen["inventory_item_id"])
        sql_order_type = """
            SELECT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND
              FROM OE_ORDER_TYPES_V    oot
              JOIN QP_LIST_HEADERS_B     qlh ON qlh.LIST_HEADER_ID = oot.PRICE_LIST_ID
              JOIN QP_LIST_HEADERS_TL    qlt ON qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
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
        sql_generic = """
            SELECT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND
              FROM QP_LIST_HEADERS_B     qlh
              JOIN QP_LIST_HEADERS_TL    qlt ON qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
              JOIN QP_LIST_LINES         qll ON qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
              JOIN QP_PRICING_ATTRIBUTES qpa ON qpa.LIST_LINE_ID = qll.LIST_LINE_ID
                                            AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                                            AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
             WHERE qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL'
               AND qlh.CURRENCY_CODE = 'USD'
               AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
               AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
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
                    if rows: source = f"Order Type ({bot.ORDER_TYPE_ID})"
                    if not rows:
                        cur.execute(sql_generic, item_id_str=item_id_str, max_rows=bot.MAX_CHOICES)
                        rows = cur.fetchall()
                        if rows: source = "Generic Active Price List"

            if not rows:
                assistant_say(f"❌ No price list found for item ID `{item_id_str}`.")
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
                assistant_say(f"Found **{len(dicts)}** price lists (source: {source}). Please select one.")
                st.session_state.stage = "select_price"
            st.rerun()

        except Exception as e:
            assistant_say(f"❌ DB error during price list lookup: `{e}`")
            st.session_state.stage = "error"; st.rerun()

    # ── select_price ──────────────────────────────────────────
    elif stage == "select_price":
        rows    = st.session_state.price_rows
        options = [f"[{i+1}] ID={r['price_list_id']}  Name={r['price_list_name']}  Price=${r['unit_list_price']:.2f}"
                   for i, r in enumerate(rows)]
        choice  = st.radio("**Select Price List:**", options, key="radio_price")
        if st.button("Confirm Price List Selection", key="btn_price"):
            idx = options.index(choice)
            st.session_state.price_chosen = rows[idx]
            user_say(f"Selected Price List: {choice}")
            assistant_say(f"✅ Price List confirmed: `{rows[idx]['price_list_name']}` — ${rows[idx]['unit_list_price']:.2f}")
            st.session_state.stage = "lookup_term"; st.rerun()

    # ── lookup_term ───────────────────────────────────────────
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
        sql_fall = "SELECT TERM_ID, NAME FROM RA_TERMS_B WHERE ENABLED_FLAG = 'Y' AND ROWNUM <= :max_rows ORDER BY TERM_ID"
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
                assistant_say("❌ No payment terms found."); st.session_state.stage = "error"; st.rerun()
            dicts = [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]
            st.session_state.term_rows = dicts
            if len(dicts) == 1:
                st.session_state.term_chosen = dicts[0]
                assistant_say(f"✅ **Payment Term** auto-selected: `{dicts[0]['term_name']}`")
                st.session_state.stage = "lookup_rep"
            else:
                assistant_say(f"Found **{len(dicts)}** payment terms. Please select one.")
                st.session_state.stage = "select_term"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ DB error during payment term lookup: `{e}`")
            st.session_state.stage = "error"; st.rerun()

    # ── select_term ───────────────────────────────────────────
    elif stage == "select_term":
        rows    = st.session_state.term_rows
        options = [f"[{i+1}] ID={r['term_id']}  Name={r['term_name']}" for i, r in enumerate(rows)]
        choice  = st.radio("**Select Payment Term:**", options, key="radio_term")
        if st.button("Confirm Payment Term", key="btn_term"):
            idx = options.index(choice)
            st.session_state.term_chosen = rows[idx]
            user_say(f"Selected Payment Term: {choice}")
            assistant_say(f"✅ Payment Term confirmed: `{rows[idx]['term_name']}`")
            st.session_state.stage = "lookup_rep"; st.rerun()

    # ── lookup_rep ────────────────────────────────────────────
    elif stage == "lookup_rep":
        sql = """
            SELECT jrs.SALESREP_ID, jrs.NAME FROM JTF_RS_SALESREPS jrs
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
                assistant_say(f"❌ No active sales reps found."); st.session_state.stage = "error"; st.rerun()
            dicts = [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]
            st.session_state.rep_rows = dicts
            if len(dicts) == 1:
                st.session_state.rep_chosen = dicts[0]
                assistant_say(f"✅ **Sales Rep** auto-selected: `{dicts[0]['salesrep_name']}`")
                st.session_state.stage = "lookup_site"
            else:
                assistant_say(f"Found **{len(dicts)}** sales reps. Please select one.")
                st.session_state.stage = "select_rep"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ DB error during sales rep lookup: `{e}`")
            st.session_state.stage = "error"; st.rerun()

    # ── select_rep ────────────────────────────────────────────
    elif stage == "select_rep":
        rows    = st.session_state.rep_rows
        options = [f"[{i+1}] ID={r['salesrep_id']}  Name={r['salesrep_name']}" for i, r in enumerate(rows)]
        choice  = st.radio("**Select Sales Rep:**", options, key="radio_rep")
        if st.button("Confirm Sales Rep", key="btn_rep"):
            idx = options.index(choice)
            st.session_state.rep_chosen = rows[idx]
            user_say(f"Selected Sales Rep: {choice}")
            assistant_say(f"✅ Sales Rep confirmed: `{rows[idx]['salesrep_name']}`")
            st.session_state.stage = "lookup_site"; st.rerun()

    # ── lookup_site ───────────────────────────────────────────
    elif stage == "lookup_site":
        sql = """
            SELECT hca.CUST_ACCOUNT_ID, hcsu.SITE_USE_ID, hp.PARTY_NAME, hcas.ORG_ID
              FROM MTL_SYSTEM_ITEMS_B   msi
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
                assistant_say(f"❌ No active SHIP_TO sites found."); st.session_state.stage = "error"; st.rerun()
            dicts = [{"sold_to_org_id": int(r[0]), "ship_to_org_id": int(r[1]),
                      "customer_name": r[2] or "", "operating_unit_id": int(r[3])} for r in rows]
            st.session_state.site_rows = dicts
            if len(dicts) == 1:
                st.session_state.site_chosen = dicts[0]
                assistant_say(f"✅ **Customer Site** auto-selected: `{dicts[0]['customer_name']}` "
                              f"(SoldTo: {dicts[0]['sold_to_org_id']}, ShipTo: {dicts[0]['ship_to_org_id']})")
                st.session_state.stage = "confirm_order"
            else:
                assistant_say(f"Found **{len(dicts)}** customer sites. Please select one.")
                st.session_state.stage = "select_site"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ DB error during customer site lookup: `{e}`")
            st.session_state.stage = "error"; st.rerun()

    # ── select_site ───────────────────────────────────────────
    elif stage == "select_site":
        rows    = st.session_state.site_rows
        options = [f"[{i+1}] Customer={r['customer_name']}  SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}"
                   for i, r in enumerate(rows)]
        choice  = st.radio("**Select Customer Site:**", options, key="radio_site")
        if st.button("Confirm Customer Site", key="btn_site"):
            idx = options.index(choice)
            st.session_state.site_chosen = rows[idx]
            user_say(f"Selected Customer Site: {choice}")
            assistant_say(f"✅ Customer Site confirmed: `{rows[idx]['customer_name']}`")
            st.session_state.stage = "confirm_order"; st.rerun()

    # ── confirm_order ─────────────────────────────────────────
    elif stage == "confirm_order":
        ic, pc, tc, rc, sc = (st.session_state.item_chosen, st.session_state.price_chosen,
                               st.session_state.term_chosen, st.session_state.rep_chosen,
                               st.session_state.site_chosen)
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
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()

    # ── submit_order ──────────────────────────────────────────
    elif stage == "submit_order":
        ic, pc, tc, rc, sc = (st.session_state.item_chosen, st.session_state.price_chosen,
                               st.session_state.term_chosen, st.session_state.rep_chosen,
                               st.session_state.site_chosen)
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

    # ── done ──────────────────────────────────────────────────
    elif stage == "done":
        result = st.session_state.get("api_result", {})
        display_erp_response(result, context_label="Order")
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🆕 Create Another Order", key="btn_new"):
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()
        with col2:
            if st.button("🔍 Get an Order", key="btn_goto_get"):
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()

    # ── error ─────────────────────────────────────────────────
    elif stage == "error":
        if st.button("🔄 Start Over", key="btn_error_restart"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()


# ── AI Panel column ───────────────────────────────────────────────
with ai_col:
    render_ai_panel()