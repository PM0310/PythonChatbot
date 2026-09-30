import streamlit as st
import SalesOrderChatandVoiceBot2 as bot
import json
import pandas as pd
import re
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI

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
    
    /* 8. Modern Buttons (Including Mic & FAQ) */
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

    /* Smaller text for FAQ buttons to look neat in sidebar */
    [data-testid="stSidebar"] .stButton>button {
        font-size: 0.9rem;
        padding: 0.25rem 0.75rem;
        text-align: left;
        justify-content: flex-start;
    }
    
    /* 9. Sidebar styling */
    [data-testid="stSidebar"] { background-color: #f9f9f9; border-right: 1px solid #e5e5e5; }
    [data-testid="stCaptionContainer"] p { color: #555555 !important; font-weight: 500; font-size: 1.1rem; }
    </style>
    """, unsafe_allow_html=True)

st.title("📦 Sales Order Assistant")
st.caption("🚀 Presented by CENTROID ")

# --------------------------------------------------
# FAQ Data Dictionary
# --------------------------------------------------
FAQ_DATA = {
    "How do I create a new sales order?": "To create a new sales order, you can type a command like 'Create an order' or 'Create order for item AS54888'. I will guide you step-by-step to gather the Customer PO, Item, Quantity, and Line Type.",
    "How do I look up an existing order?": "Simply type 'Get order #12345' or 'Show me order 12345'.",
    "How do I send order details via email?": "Just say 'Send email to example@domain.com'. I will gather the details of the last operation we worked on and format it into a neat table for you to send.",
    "Can I search for orders by date or status?": "Yes! You can use natural language searches such as 'Show booked orders from 2024' or 'Find cancelled orders'.",
    "How do I see all orders for a specific customer?": "Type 'Order details for customer [Name]' (e.g., 'Order details for customer ACME'). This will pull up a comprehensive table of their past orders, shipments, and invoice balances.",
    "Can I add more items to an existing order?": "Yes. After you create a new order or retrieve an existing one, a button labeled '➕ Add a Line' will appear at the bottom, allowing you to append new items to that specific order.",
    "How do I use voice commands?": "Click the 🎙️ microphone icon next to the chat bar. Wait for the 'Listening...' notification to appear, then speak your command clearly.",
    "How do I cancel an operation?": "If you are in the middle of creating an order and want to stop, simply type or say 'Cancel', 'Stop', or 'Quit', or click the '🔄 Reset / Start Over' button in the sidebar."
}

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
        "voice_error":    None,
        "faq_pending":    None,
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
            "cust_account_id": None, "line_type_id": None, "email_address": None
        },
        "item_rows": [], "price_rows": [], "term_rows": [], "rep_rows": [], "site_rows": [],
        "customer_rows": [], "customer_by_item_rows": [], "line_type_rows": [],
        "api_result": None, "gh_history": [],
        "add_line_stage": None, "add_line_data": {}, "add_line_header_id": None,     
        "add_line_order_number": None, "add_line_item_rows": [], "add_line_price_rows": [],
        "add_line_term_rows": [], "add_line_return": "done", "selling_price_override": False,
        "order_details_customer_name": None,
        "order_details_rows": [],
        "order_details_page": 0,
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
                    bot.speak(text_to_speak)
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
    return missing

# --------------------------------------------------
# AI Summarization Function
# --------------------------------------------------
def generate_ai_summary(operation_name: str, data: dict) -> str:
    """Uses OpenAI to dynamically summarize ERP transaction results."""
    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=bot.GITHUB_TOKEN,
        )
        data_str = str(data)[:2000]
        system_prompt = (
            "You are a helpful Oracle ERP Chatbot Assistant. Summarize the result of the following ERP operation "
            "in 2-3 friendly, conversational sentences. Focus heavily on whether the operation was a SUCCESS or FAILURE. "
            "Highlight key identifiers (like Order Numbers, Header IDs, or Items). DO NOT output raw JSON or code snippets."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Operation: {operation_name}\nData: {data_str}"}
            ],
            temperature=0.3,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "Operation completed. (AI Summary generation failed)"

# --------------------------------------------------
# Email Logic
# --------------------------------------------------
def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str) -> tuple:
    """
    Constructs and sends an email via SMTP.
    # For Oracle APEX integrations, this can be seamlessly swapped with a REST call to your APEX_MAIL endpoint.
    """
    sender = "erp.assistant@yourdomain.com"
    smtp_server = "smtp.yourserver.com"
    smtp_port = 587
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    html_content = f"""
    <html>
    <head>
    <style>
        body {{ font-family: Arial, sans-serif; color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin-top: 15px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; color: #0d0d0d; }}
    </style>
    </head>
    <body>
        <p>{body_text.replace(chr(10), '<br>')}</p>
        <br>
        {html_table}
    </body>
    </html>
    """
    
    part1 = MIMEText(body_text, "plain")
    part2 = MIMEText(html_content, "html")
    msg.attach(part1)
    msg.attach(part2)

    try:
        # Uncomment and configure these lines for a live SMTP server
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login("pavanmaccha042@gmail.com", "ltvxbwhkzkrptueg")
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
        
        # MOCK SEND (Simulating Success)
        print(f"Mock email successfully dispatched to {to_email}")
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)

def build_html_from_last_operation():
    """Converts the previously performed ERP operation into a structured HTML table."""
    html = ""
    
    # 1. Specific Order (Create / Get)
    if st.session_state.get("api_result") and "total_count" not in st.session_state["api_result"]:
        d = extract_erp_details(st.session_state["api_result"])
        html += "<h3>Order Header Details</h3><table>"
        html += "<tr><th>Field</th><th>Value</th></tr>"
        for k, v in d["header_details"].items():
            if v and v != "N/A":
                html += f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"
        html += "</table><br>"
        
        if d["lines"]:
            html += "<h3>Order Line Details</h3><table>"
            headers = list(d["lines"][0].keys())
            html += "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
            for line in d["lines"]:
                html += "<tr>" + "".join(f"<td>{line.get(h, '')}</td>" for h in headers) + "</tr>"
            html += "</table>"
            
    # 2. Advanced Search Results
    elif st.session_state.get("api_result") and "total_count" in st.session_state["api_result"]:
        res = st.session_state["api_result"]
        html += f"<h3>Search Results ({res['total_count']} found)</h3><table>"
        html += "<tr><th>Order Number</th><th>Status</th><th>Creation Date</th></tr>"
        for r in res["rows"]:
            html += f"<tr><td>{r[0]}</td><td>{r[1]}</td><td>{r[2]}</td></tr>"
        html += "</table>"
        
    # 3. Customer Order Details
    elif st.session_state.get("order_details_rows"):
        rows = st.session_state["order_details_rows"][:50] # Limit to 50 for email payload
        html += f"<h3>Customer Order Details (Showing top {len(rows)})</h3><table>"
        html += "<tr>" + "".join(f"<th>{lbl}</th>" for lbl, _ in _ORDER_DETAIL_COLUMNS[:10]) + "</tr>"
        for r in rows:
            html += "<tr>" + "".join(f"<td>{r.get(key, '')}</td>" for lbl, key in _ORDER_DETAIL_COLUMNS[:10]) + "</tr>"
        html += "</table>"
        
    return html

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
# get_order_details_by_customer()
# --------------------------------------------------
def get_order_details_by_customer(p_customer_name: str) -> list:
    sql = """
        SELECT
            HP.PARTY_ID, 
            HP.PARTY_NAME                                           AS CUSTOMER_NAME, 
            TO_CHAR(SYSDATE, 'DD-MON-YYYY')                        AS REPORT_DATE, 
            OOHA.SOLD_TO_ORG_ID                                     AS SOLD_TO_PARTY_ID, 
            OOHA.INVOICE_TO_ORG_ID                                  AS BILL_TO_CUSTOMER_ID, 
            OOHA.ORDER_NUMBER, 
            TO_CHAR(OOHA.ORDERED_DATE, 'DD-MON-YYYY')              AS ORDER_DATE, 
            WDD.RELEASED_STATUS, 
            OOLA.LINE_NUMBER, 
            MSI.SEGMENT1                                            AS ITEM_NUMBER, 
            OOLA.ORDER_QUANTITY_UOM                                 AS ORDERED_UOM, 
            OOLA.ORDERED_QUANTITY                                   AS ORDERED_QTY, 
            DECODE(OOLA.CANCELLED_FLAG, 'Y', 'Y', 'N')             AS ORDER_HOLD_FLAG,
            OOLA.UNIT_LIST_PRICE, 
            OOLA.UNIT_SELLING_PRICE, 
            OOLA.FLOW_STATUS_CODE                                   AS LINE_STATUS, 
            OOLA.FLOW_STATUS_CODE                                   AS FULFILL_STATUS, 
            OOHA.CUST_PO_NUMBER                                     AS PO_NUMBER,
            OOLA.CUST_PO_NUMBER                                     AS PO_LINE,
            'PO_REFERENCE'                                          AS REF_TYPE,
            (
                SELECT NVL(SUM(APS.AMOUNT_DUE_REMAINING), 0)
                FROM AR_PAYMENT_SCHEDULES_ALL APS, RA_CUSTOMER_TRX_ALL RCTA 
                WHERE APS.CUSTOMER_TRX_ID = RCTA.CUSTOMER_TRX_ID 
                AND RCTA.INTERFACE_HEADER_ATTRIBUTE1 = TO_CHAR(OOHA.ORDER_NUMBER) 
            )                                                       AS INVOICE_BALANCE, 
            TO_CHAR(NVL(OOLA.SCHEDULE_SHIP_DATE, OOLA.REQUEST_DATE), 'DD-MON-YYYY')
                                                                    AS SCHEDULE_SHIP_DATE,
            TO_CHAR(OOLA.ACTUAL_SHIPMENT_DATE, 'DD-MON-YYYY')      AS ACTUAL_SHIP_DATE, 
            DECODE(TRUNC(OOLA.SCHEDULE_SHIP_DATE), TRUNC(SYSDATE), 1, 0)
                                                                    AS TODAY_ARRIVAL_QTY,
            DECODE(WDD.RELEASED_STATUS, 'B', 1, 0)                 AS BACKORDER_FLAG,
            (OOLA.ORDERED_QUANTITY * OOLA.UNIT_SELLING_PRICE)      AS LINE_PRICE,
            (
                SELECT NVL(SUM(OPA.ADJUSTED_AMOUNT), 0)
                FROM OE_PRICE_ADJUSTMENTS OPA  
                WHERE OPA.LINE_ID = OOLA.LINE_ID 
                AND OPA.LIST_LINE_TYPE_CODE = 'DIS' 
            )                                                       AS ADD_DISC, 
            (
                SELECT NVL(SUM(OPA.ADJUSTED_AMOUNT), 0)
                FROM OE_PRICE_ADJUSTMENTS OPA  
                WHERE OPA.LINE_ID = OOLA.LINE_ID  
                AND OPA.LIST_LINE_TYPE_CODE = 'DIS' 
            )                                                       AS CASH_DISC,  
            (
                SELECT NAME
                FROM OE_TRANSACTION_TYPES_TL  
                WHERE TRANSACTION_TYPE_ID = OOHA.ORDER_TYPE_ID  
                AND LANGUAGE = 'US' 
            )                                                       AS ORDER_TYPE,  
            OOLA.SHIPPING_METHOD_CODE                               AS SHIPMENT_MODE,  
            (CASE
                WHEN OOLA.SCHEDULE_SHIP_DATE IS NOT NULL  
                AND TRUNC(OOLA.SCHEDULE_SHIP_DATE) < TRUNC(NVL(OOLA.ACTUAL_SHIPMENT_DATE, SYSDATE)) 
                THEN 1 ELSE 0 END
            )                                                       AS DELAYED_ORDER_FLAG, 
            (CASE
                WHEN OOLA.ACTUAL_SHIPMENT_DATE IS NOT NULL  
                AND TRUNC(OOLA.SCHEDULE_SHIP_DATE) < TRUNC(SYSDATE) 
                AND WDD.RELEASED_STATUS = 'C'
                THEN 1 ELSE 0 END 
            )                                                       AS IN_TRANSIT_ORDER_FLAG, 
            (
                SELECT HCP.EMAIL_ADDRESS
                FROM HZ_CUST_ACCOUNT_ROLES HCAR, HZ_CONTACT_POINTS HCP, HZ_RELATIONSHIPS HR 
                WHERE HCAR.STATUS = 'A' 
                AND HCP.STATUS = 'A' 
                AND HCP.PRIMARY_FLAG = 'Y' 
                AND HCP.CONTACT_POINT_TYPE = 'EMAIL'
                AND HCAR.CUST_ACCOUNT_ID = OOHA.SOLD_TO_ORG_ID 
                AND ROWNUM = 1 
                AND HR.OBJECT_TYPE = 'ORGANIZATION'
            )                                                       AS EMAIL 
        FROM
            OE_ORDER_HEADERS_ALL OOHA, 
            OE_ORDER_LINES_ALL OOLA,
            MTL_SYSTEM_ITEMS_B MSI, 
            WSH_DELIVERY_DETAILS WDD, 
            HZ_CUST_ACCOUNTS HCAA, 
            HZ_PARTIES HP 
        WHERE
            OOHA.HEADER_ID = OOLA.HEADER_ID 
        AND MSI.INVENTORY_ITEM_ID = OOLA.INVENTORY_ITEM_ID 
        AND MSI.ORGANIZATION_ID = OOLA.SHIP_FROM_ORG_ID 
        AND OOLA.LINE_ID = WDD.SOURCE_LINE_ID(+)
        AND WDD.SOURCE_CODE(+) = 'OE' 
        AND HCAA.CUST_ACCOUNT_ID = OOHA.SOLD_TO_ORG_ID 
        AND HP.PARTY_ID = HCAA.PARTY_ID 
        AND HP.PARTY_NAME = :p_customer_name
        ORDER BY OOHA.ORDER_NUMBER, OOLA.LINE_NUMBER
    """
    rows = bot.execute_query(sql, {"p_customer_name": p_customer_name})
    return rows if rows else []

_ORDER_DETAIL_COLUMNS = [
    ("Customer Name",      "CUSTOMER_NAME"),
    ("Order Number",       "ORDER_NUMBER"),
    ("Order Date",         "ORDER_DATE"),
    ("PO Number",          "PO_NUMBER"),
    ("PO Line",            "PO_LINE"),
    ("Order Type",         "ORDER_TYPE"),
    ("Line #",             "LINE_NUMBER"),
    ("Item Number",        "ITEM_NUMBER"),
    ("Ordered Qty",        "ORDERED_QTY"),
    ("UOM",                "ORDERED_UOM"),
    ("Unit List Price",    "UNIT_LIST_PRICE"),
    ("Unit Selling Price", "UNIT_SELLING_PRICE"),
    ("Line Price",         "LINE_PRICE"),
    ("Invoice Balance",    "INVOICE_BALANCE"),
    ("Add Disc",           "ADD_DISC"),
    ("Cash Disc",          "CASH_DISC"),
    ("Line Status",        "LINE_STATUS"),
    ("Fulfill Status",     "FULFILL_STATUS"),
    ("Ship Date",          "SCHEDULE_SHIP_DATE"),
    ("Actual Ship Date",   "ACTUAL_SHIP_DATE"),
    ("Shipment Mode",      "SHIPMENT_MODE"),
    ("Released Status",    "RELEASED_STATUS"),
    ("Backorder",          "BACKORDER_FLAG"),
    ("Delayed",            "DELAYED_ORDER_FLAG"),
    ("In Transit",         "IN_TRANSIT_ORDER_FLAG"),
    ("Today Arrival",      "TODAY_ARRIVAL_QTY"),
    ("On Hold",            "ORDER_HOLD_FLAG"),
    ("Sold-To Party ID",   "SOLD_TO_PARTY_ID"),
    ("Bill-To ID",         "BILL_TO_CUSTOMER_ID"),
    ("Email",              "EMAIL"),
    ("Report Date",        "REPORT_DATE"),
]

_ROWS_PER_PAGE = 50

def _display_order_details_table(rows: list, customer_name: str):
    total = len(rows)
    page  = st.session_state.order_details_page
    start = page * _ROWS_PER_PAGE
    end   = min(start + _ROWS_PER_PAGE, total)
    page_rows = rows[start:end]

    col_labels  = [lbl for lbl, _ in _ORDER_DETAIL_COLUMNS]

    records = []
    for r in page_rows:
        records.append({lbl: r.get(key, "") for lbl, key in _ORDER_DETAIL_COLUMNS})

    df = pd.DataFrame(records, columns=col_labels)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Lines",     total)
    m2.metric("Unique Orders",   df["Order Number"].nunique() if "Order Number" in df.columns else "—")
    m3.metric("Total Line Value",
              f"${df['Line Price'].replace('', 0).apply(lambda x: float(x) if str(x).replace('.','',1).lstrip('-').isdigit() else 0).sum():,.2f}"
              if "Line Price" in df.columns else "—")
    m4.metric("Invoice Balance",
              f"${df['Invoice Balance'].replace('', 0).apply(lambda x: float(x) if str(x).replace('.','',1).lstrip('-').isdigit() else 0).sum():,.2f}"
              if "Invoice Balance" in df.columns else "—")

    st.markdown(f"Showing rows **{start+1}–{end}** of **{total}**")
    st.dataframe(df, use_container_width=True, hide_index=True)

    pc1, pc2, pc3 = st.columns([1, 2, 1])
    with pc1:
        if page > 0:
            if st.button("⬅️ Previous Page"):
                st.session_state.order_details_page -= 1
                st.rerun()
    with pc3:
        if end < total:
            if st.button("Next Page ➡️"):
                st.session_state.order_details_page += 1
                st.rerun()

    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download All Results as CSV",
        data=csv_bytes,
        file_name=f"order_details_{customer_name.replace(' ', '_')}.csv",
        mime="text/csv",
    )

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
    
    with st.expander("❓ Frequently Asked Questions (FAQ)"):
        st.info("Click any question below to ask the AI:")
        for i, question in enumerate(FAQ_DATA.keys()):
            if st.button(f"🗣️ {question}", key=f"faq_btn_{i}", use_container_width=True):
                st.session_state.faq_pending = question

    st.markdown("---")
    if st.button("🔄 Reset / Start Over", use_container_width=True):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

st.markdown("---")

# ==================================================
# STAGES: UI Resolution State Machine
# ==================================================
stage = st.session_state.stage

# --------------------------------------------------
# STAGE: Send Email
# --------------------------------------------------
if stage == "send_email_flow":
    st.markdown("### 📧 Send Email")
    st.info("The order data from your last operation has been automatically attached as a formatted table.")
    c = st.session_state.collected
    
    to_email = st.text_input("To:", value=c.get("email_address", ""))
    subject = st.text_input("Subject:", value="Oracle ERP Order Details Update")
    body = st.text_area("Message Body:", value="Please find the requested order details structured below.")
    
    with st.expander("Preview Data to be Sent"):
        html_preview = build_html_from_last_operation()
        if html_preview:
            st.markdown(html_preview, unsafe_allow_html=True)
        else:
            st.warning("No recent operation data found to attach to this email.")

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("✅ Send Email"):
            if not to_email:
                st.error("Email address is required.")
            else:
                with st.spinner("Dispatching email..."):
                    success, msg = send_erp_email(to_email, subject, body, html_preview)
                    if success:
                        assistant_say(f"✅ Email sent successfully to `{to_email}`!", speak_text="The email was sent successfully.")
                        st.session_state.stage = "chat"
                        st.rerun()
                    else:
                        st.error(f"Error sending email: {msg}")
    with col2:
        if st.button("❌ Cancel"):
            st.session_state.stage = "chat"
            st.rerun()

elif stage == "select_item":
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
        st.session_state.collected["ship_to_org_id"] = row["ship_to_org_id"]
        st.session_state.collected["customer_name"]  = row["customer_name"]
        assistant_say(
            f"✅ Customer: `{row['customer_name']}`  | Sold-to: `{row['sold_to_org_id']}`  | Ship-to: `{row['ship_to_org_id']}`",
            speak_text=f"Customer shipping site confirmed."
        )

    render_selection_ui("Customer Site", "site_rows", "site", lambda r: f"Customer={r['customer_name']}  [{r['location']}] {r['address']}  (SoldTo={r['sold_to_org_id']} | ShipTo={r['ship_to_org_id']})", confirm_site)

# ==================================================
# STAGE: order_details_by_customer
# ==================================================
elif stage == "order_details_by_customer":
    st.markdown("## 🔎 Order Details by Customer")
    st.info("Enter a customer name (exact match, as stored in Oracle HZ_PARTIES) to retrieve all order lines.")

    cname_input = st.text_input(
        "Customer Name:",
        value=st.session_state.get("order_details_customer_name") or "",
        placeholder="e.g. ACME CORPORATION",
        key="od_customer_name_input",
    )

    col_search, col_cancel = st.columns([1, 5])
    with col_search:
        search_clicked = st.button("🔍 Fetch Order Details")
    with col_cancel:
        if st.button("❌ Cancel"):
            st.session_state.stage = "chat"
            st.rerun()

    if search_clicked:
        if not cname_input.strip():
            st.error("Please enter a customer name before searching.")
        else:
            with st.spinner(f"⏳ Fetching order details for **{cname_input}**..."):
                try:
                    rows = get_order_details_by_customer(cname_input.strip())
                    st.session_state.order_details_customer_name = cname_input.strip()
                    st.session_state.order_details_rows = rows
                    st.session_state.order_details_page = 0
                    
                    if rows:
                        summary_context = {
                            "customer": cname_input.strip(), 
                            "total_lines_found": len(rows), 
                            "sample_data": rows[:3]
                        }
                        ai_summary = generate_ai_summary("Retrieve Orders by Customer", summary_context)
                        assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)
                    else:
                        assistant_say(
                            f"ℹ️ No orders found for customer `{cname_input.strip()}`. "
                            "Please verify the exact customer name as stored in the system.",
                            speak_text=f"No orders found for {cname_input.strip()}."
                        )
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Error fetching order details: {e}", speak_text="There was an error fetching order details.")
                    st.rerun()

    rows = st.session_state.get("order_details_rows", [])
    customer_name = st.session_state.get("order_details_customer_name", "")
    if rows and customer_name:
        st.markdown(f"### 📦 Results for: `{customer_name}`")
        st.markdown("---")
        _display_order_details_table(rows, customer_name)

        st.markdown("---")
        if st.button("🔍 Search Another Customer"):
            st.session_state.order_details_rows = []
            st.session_state.order_details_customer_name = None
            st.session_state.order_details_page = 0
            st.rerun()

        if st.button("🏠 Back to Chat"):
            st.session_state.stage = "chat"
            st.rerun()

# ==================================================
# STAGE: resolve
# ==================================================
elif stage == "resolve":
    c    = st.session_state.collected
    offs = st.session_state.offsets

    with st.spinner("⏳ Resolving order details..."):
        try:
            # Step 1 — Resolve Item
            if c.get("ordered_item") and not c.get("inventory_item_id"):
                rows = bot.get_inventory_item_rows(c["ordered_item"], offset=offs["item"])
                if not rows:
                    assistant_say(
                        f"⚠️ No inventory items found matching `{c['ordered_item']}`. Please try a different item code.",
                        speak_text="No items found. Please try a different item code."
                    )
                    c["ordered_item"] = None
                    st.session_state.stage = "chat"
                    st.rerun()
                elif len(rows) == 1 and offs["item"] == 0:
                    c["inventory_item_id"], c["ordered_item"] = rows[0]["inventory_item_id"], rows[0]["segment1"]
                    st.rerun()
                else:
                    st.session_state.item_rows, st.session_state.stage = rows, "select_item"
                    assistant_say("Please select an item from the list below.", speak_text="I found multiple items. Please select one.")
                    st.rerun()

            # Step 2 — Resolve Price
            if c.get("inventory_item_id") and c.get("quantity") and not c.get("price_list_id"):
                rows = bot.get_price_details_rows(c["ordered_item"], float(c["quantity"]), c["inventory_item_id"], offset=offs["price"])
                if not rows:
                    assistant_say(
                        f"⚠️ No price lists found for item `{c['ordered_item']}`. Cannot proceed.",
                        speak_text="No price lists found for this item."
                    )
                    st.session_state.stage = "chat"
                    st.rerun()
                elif len(rows) == 1 and offs["price"] == 0:
                    c["price_list_id"] = rows[0]["price_list_id"]
                    if not c.get("unit_list_price"): c["unit_list_price"] = rows[0]["unit_list_price"]
                    if not c.get("unit_selling_price"):
                        c["unit_selling_price"] = rows[0]["unit_list_price"]
                        st.session_state.stage  = "selling_price_override"
                    st.rerun()
                else:
                    st.session_state.price_rows, st.session_state.stage = rows, "select_price"
                    assistant_say("Please select a price list.", speak_text="I found multiple price lists. Please select one.")
                    st.rerun()

            # Step 3 — Resolve Payment Term
            if not c.get("payment_term_id"):
                rows = bot.get_payment_term_rows(offset=offs["term"])
                if not rows:
                    assistant_say("⚠️ No payment terms found. Cannot proceed.", speak_text="No payment terms found.")
                    st.session_state.stage = "chat"
                    st.rerun()
                elif len(rows) == 1 and offs["term"] == 0:
                    c["payment_term_id"], c["payment_term_name"] = rows[0]["term_id"], rows[0]["term_name"]
                    st.rerun()
                else:
                    st.session_state.term_rows, st.session_state.stage = rows, "select_term"
                    assistant_say("Please select a payment term.", speak_text="Please select a payment term.")
                    st.rerun()

            # Step 4 — Resolve Salesrep
            if not c.get("salesrep_id"):
                rows = bot.get_salesrep_rows(offset=offs["rep"])
                if not rows:
                    assistant_say("⚠️ No sales representatives found. Cannot proceed.", speak_text="No sales representatives found.")
                    st.session_state.stage = "chat"
                    st.rerun()
                elif len(rows) == 1 and offs["rep"] == 0:
                    c["salesrep_id"], c["salesrep_name"] = rows[0]["salesrep_id"], rows[0]["salesrep_name"]
                    st.rerun()
                else:
                    st.session_state.rep_rows, st.session_state.stage = rows, "select_rep"
                    assistant_say("Please select a sales representative.", speak_text="Please select a sales representative.")
                    st.rerun()

            # Step 5 — Resolve Line Type
            if not c.get("line_type_id") and hasattr(bot, 'get_line_type_rows'):
                st.session_state.stage = "select_line_type"
                assistant_say("Please select a line type.", speak_text="Please select a line type.")
                st.rerun()

            # Step 6 — Resolve Customer
            if not c.get("sold_to_org_id") or not c.get("ship_to_org_id"):
                if c.get("cust_account_id"):
                    sites = bot.get_customer_sites_by_account(c["cust_account_id"])
                    if not sites:
                        assistant_say(f"⚠️ No active SHIP_TO sites for this customer. Please choose a different customer.")
                        c["cust_account_id"] = None
                        st.session_state.stage = "select_customer"
                        st.rerun()
                    elif len(sites) == 1:
                        c["sold_to_org_id"] = sites[0]["sold_to_org_id"]
                        c["ship_to_org_id"] = sites[0]["ship_to_org_id"]
                        c["customer_name"]  = sites[0]["customer_name"]
                        st.rerun()
                    else:
                        st.session_state.site_rows = sites
                        st.session_state.stage = "select_site"
                        assistant_say("Please select a ship-to site.", speak_text="Please select a ship to site.")
                        st.rerun()
                elif c.get("customer_name"):
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(c["customer_name"], offset=offs["customer"])
                    st.session_state.stage         = "select_customer"
                    assistant_say("Please select a customer.", speak_text="Please select a customer.")
                    st.rerun()
                elif c.get("inventory_item_id"):
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=offs["customer_by_item"])
                    st.session_state.stage                 = "select_customer_by_item"
                    assistant_say("Please select a customer.", speak_text="Please select a customer.")
                    st.rerun()
                else:
                    assistant_say("⚠️ Could not determine a customer. Please provide a customer name.", speak_text="Please provide a customer name.")
                    st.session_state.stage = "chat"
                    st.rerun()

            # All resolved → go to confirmation
            st.session_state.stage = "confirm_order"
            st.rerun()

        except Exception as e:
            assistant_say(f"❌ Error during resolution: {e}", speak_text="There was an error resolving the order details.")
            st.session_state.stage = "error"
            st.rerun()

# ==================================================
# STAGE: confirm_order
# ==================================================
elif stage == "confirm_order":
    c = st.session_state.collected
    summary = "**📋 Order Summary — please review before submitting:**\n\n| Field | Value |\n|---|---|\n"
    for label, val in c.items():
        if val is not None and not label.endswith("_name"):
            summary += f"| **{label}** | `{val}` |\n"

    if not any("Order Summary" in m["content"] for m in st.session_state.messages):
        assistant_say(summary, speak_text="Please review the order summary below. Does everything look correct? Click submit when ready.")
        st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Submit Order"):
            with st.spinner("⏳ Submitting Order..."):
                try:
                    payload_kwargs = {
                        "p_cust_po": c["cpo"], "p_item_id": c["inventory_item_id"], "p_ordered_item": c["ordered_item"],
                        "p_qty": c["quantity"], "p_price": c["unit_list_price"], "p_selling_price": c["unit_selling_price"],
                        "p_payment_term_id": c["payment_term_id"], "p_price_list_id": c["price_list_id"],
                        "p_salesrep_id": c["salesrep_id"], "p_ship_to_org": c["ship_to_org_id"], 
                        "p_sold_to_org": c["sold_to_org_id"], "p_operating_unit": bot.OPERATING_UNIT
                    }
                    import inspect as _inspect
                    _cp_params = _inspect.signature(bot.create_payload).parameters
                    if c.get("line_type_id") and "p_line_type_id" in _cp_params:
                        payload_kwargs["p_line_type_id"] = c["line_type_id"]

                    payload = bot.create_payload(**payload_kwargs)
                    result = bot.send_order(payload)
                    st.session_state.api_result = result
                    
                    parsed_data = extract_erp_details(result)
                    ai_summary = generate_ai_summary("Create New Sales Order", parsed_data)
                    assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

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
                        if header_id: st.session_state.add_line_header_id = int(str(header_id).strip())
                        if order_number: st.session_state.add_line_order_number = int(str(order_number).strip())
                    except Exception: pass

                    st.session_state.stage = "done"
                    st.session_state.add_line_return = "done"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Submit Error: {e}", speak_text="There was an error submitting the order.")
                    st.session_state.stage = "error"
                    st.rerun()
    with col2:
        if st.button("🔄 Start Over"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

# ==================================================
# STAGE: done
# ==================================================
elif stage == "done":
    result = st.session_state.get("api_result", {})
    display_erp_response(result, context_label="Order")

    st.markdown("---")

    header_id    = st.session_state.get("add_line_header_id")
    order_number = st.session_state.get("add_line_order_number")

    if header_id and order_number:
        st.markdown(f"### ➕ Add Another Line to Order #{order_number}?")
        col_add, col_new = st.columns(2)
        with col_add:
            if st.button("➕ Add a Line"):
                st.session_state.add_line_stage, st.session_state.add_line_data = "add_line_item", {}
                st.session_state.add_line_item_rows, st.session_state.add_line_price_rows, st.session_state.add_line_term_rows = [], [], []
                st.session_state.offsets["item"], st.session_state.offsets["price"], st.session_state.offsets["term"] = 0, 0, 0
                st.session_state.stage, st.session_state.add_line_return = "add_line_flow", "done"
                st.rerun()
        with col_new:
            if st.button("🆕 Create Another Order"):
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()
    else:
        if st.button("🆕 Create Another Order"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()

# ==================================================
# STAGE: show_get_order
# ==================================================
elif stage == "show_get_order":
    result = st.session_state.get("api_result", {})

    if isinstance(result, dict) and "total_count" in result:
        df = pd.DataFrame(result["rows"], columns=["Order Number", "Status", "Creation Date"])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown("---")
        if st.button("🔍 Start New Search"):
            for k in list(st.session_state.keys()): del st.session_state[k]
            st.rerun()
    else:
        display_erp_response(result, context_label="Retrieved Order")
        st.markdown("---")

        try:
            out = result.get("PROCESS_ORDER_Output", {}).get("OutputParameters", {})
            if not out:
                out = result.get("OutputParameters", result)
            hdr = out.get("X_HEADER_REC", {}) or {}
            order_number = hdr.get("ORDER_NUMBER") or hdr.get("order_number")
            header_id    = hdr.get("HEADER_ID")    or hdr.get("header_id")
            if header_id: st.session_state.add_line_header_id = int(str(header_id).strip())
            if order_number: st.session_state.add_line_order_number = int(str(order_number).strip())
        except Exception: pass

        header_id, order_number = st.session_state.get("add_line_header_id"), st.session_state.get("add_line_order_number")

        if header_id and order_number:
            st.markdown(f"### ➕ Add a Line to Order #{order_number}?")
            col_add, col_new = st.columns(2)
            with col_add:
                if st.button("➕ Add a Line"):
                    st.session_state.add_line_stage, st.session_state.add_line_data = "add_line_item", {}
                    st.session_state.add_line_item_rows, st.session_state.add_line_price_rows, st.session_state.add_line_term_rows = [], [], []
                    st.session_state.offsets["item"], st.session_state.offsets["price"], st.session_state.offsets["term"] = 0, 0, 0
                    st.session_state.stage, st.session_state.add_line_return = "add_line_flow", "show_get_order"
                    st.rerun()
            with col_new:
                if st.button("🔍 Start New Search"):
                    for k in list(st.session_state.keys()): del st.session_state[k]
                    st.rerun()
        else:
            if st.button("🔍 Start New Search"):
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.rerun()

# ==================================================
# STAGE: add_line_flow
# ==================================================
elif stage == "add_line_flow":
    header_id, order_number = st.session_state.add_line_header_id, st.session_state.add_line_order_number
    sub, ald, offs = st.session_state.add_line_stage, st.session_state.add_line_data, st.session_state.offsets
    return_stage = st.session_state.get("add_line_return", "done")

    if sub == "add_line_item" and st.session_state.get("add_line_lt_rows"):
        st.session_state.add_line_lt_rows = []

    st.markdown(f"### ➕ Adding Line to Order #{order_number} (Header ID: {header_id})")

    if sub == "add_line_item":
        item_search = st.text_input("Enter item name/prefix to search:", key="add_line_item_search")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔍 Search Items"):
                offs["item"] = 0
                st.session_state.add_line_item_rows = bot.get_inventory_item_rows(item_search, offset=0)
                st.rerun()
        with col2:
            if st.button("❌ Cancel Add Line"):
                st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                st.rerun()

        rows = st.session_state.add_line_item_rows
        if rows:
            opts = [f"[{i+1}] {r['segment1']}  {r['description']}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Item:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Item"):
                    idx = opts.index(choice)
                    ald["inventory_item_id"], ald["ordered_item"] = rows[idx]["inventory_item_id"], rows[idx]["segment1"]
                    st.session_state.add_line_stage = "add_line_qty"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next"):
                        offs["item"] += bot.MAX_CHOICES
                        st.session_state.add_line_item_rows = bot.get_inventory_item_rows(item_search, offset=offs["item"])
                        st.rerun()

    elif sub == "add_line_qty":
        st.markdown(f"**Item:** `{ald.get('ordered_item')}`")
        qty_input = st.text_input("Enter Quantity:", key="add_line_qty_input")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Quantity"):
                qty = bot.parse_numeric_value(qty_input, allow_float=True)
                if qty is None: st.error("Invalid quantity. Please enter a number.")
                else:
                    ald["quantity"] = qty
                    st.session_state.add_line_price_rows = bot.get_price_details_rows(ald["ordered_item"], qty, ald["inventory_item_id"], offset=0)
                    offs["price"], st.session_state.add_line_stage = 0, "add_line_price"
                    st.rerun()
        with col2:
            if st.button("❌ Cancel"):
                st.session_state.add_line_stage, st.session_state.stage = None, return_stage
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
                    ald["price_list_id"], ald["unit_list_price"], ald["unit_selling_price"] = rows[idx]["price_list_id"], rows[idx]["unit_list_price"], rows[idx]["unit_list_price"]
                    st.session_state.add_line_stage = "add_line_selling_price"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next"):
                        offs["price"] += bot.MAX_CHOICES
                        st.session_state.add_line_price_rows = bot.get_price_details_rows(ald["ordered_item"], ald["quantity"], ald["inventory_item_id"], offset=offs["price"])
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
                st.session_state.add_line_term_rows = bot.get_payment_term_rows(offset=0)
                offs["term"], st.session_state.add_line_stage = 0, "add_line_term"
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
                    if hasattr(bot, 'get_line_type_rows'):
                        st.session_state.add_line_stage = "add_line_line_type"
                    else:
                        st.session_state.add_line_stage = "add_line_submit"
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
                    st.session_state.add_line_stage, st.session_state.stage = None, return_stage
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
                    else: st.error("Please enter a valid numeric ID.")
            with col2:
                if st.button("❌ Cancel"):
                    st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                    st.rerun()

    elif sub == "add_line_submit":
        st.markdown("**📋 New Line Summary:**")
        st.markdown(f"- Item: `{ald.get('ordered_item')}`")
        st.markdown(f"- Quantity: `{ald.get('quantity')}`")
        st.markdown(f"- Unit List Price: `${ald.get('unit_list_price', 0):.2f}`")
        st.markdown(f"- Selling Price: `${ald.get('unit_selling_price', 0):.2f}`")
        st.markdown(f"- Payment Term ID: `{ald.get('payment_term_id')}`")
        if ald.get("line_type_id"): st.markdown(f"- Line Type ID: `{ald.get('line_type_id')}`")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Submit Line"):
                with st.spinner("⏳ Adding line to order..."):
                    try:
                        payload_kwargs = {
                            "p_header_id": header_id, "p_item_id": ald["inventory_item_id"],
                            "p_ordered_item": ald["ordered_item"], "p_qty": ald["quantity"],
                            "p_price": ald["unit_list_price"], "p_selling_price": ald["unit_selling_price"],
                            "p_payment_term_id": ald["payment_term_id"], "p_price_list_id": ald["price_list_id"]
                        }
                        import inspect as _inspect
                        _alp_params = _inspect.signature(bot.create_add_line_payload).parameters
                        if ald.get("line_type_id") and "p_line_type_id" in _alp_params:
                            payload_kwargs["p_line_type_id"] = ald["line_type_id"]
                        
                        payload = bot.create_add_line_payload(**payload_kwargs)
                        result = bot.send_order(payload)
                        st.session_state.api_result = result
                        
                        parsed_data = extract_erp_details(result)
                        ai_summary = generate_ai_summary("Add Line to Order", parsed_data)
                        assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

                        st.session_state.add_line_stage, st.session_state.add_line_data, st.session_state.stage = None, {}, "done"
                        st.rerun()
                    except Exception as e:
                        assistant_say(f"❌ Failed to add line: {e}", speak_text="Failed to add line.")
                        st.session_state.stage = "error"
                        st.rerun()
        with col2:
            if st.button("❌ Cancel"):
                st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                st.rerun()

# ==================================================
# STAGE: fetch_get_order
# ==================================================
elif stage == "fetch_get_order":
    with st.spinner(f"⏳ Retrieving Order {st.session_state.get_order_num}..."):
        try:
            result = bot.get_order(st.session_state.get_order_num)
            
            parsed_data = extract_erp_details(result)
            ai_summary = generate_ai_summary("Retrieve Specific Order", parsed_data)
            assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

            st.session_state.api_result, st.session_state.stage = result, "show_get_order"
            st.rerun()
        except Exception as e:
            assistant_say(f"❌ Failed: {e}", speak_text="Failed to retrieve the order.")
            st.session_state.stage = "error"
            st.rerun()

# ==================================================
# STAGE: error
# ==================================================
elif stage == "error":
    if st.button("🔄 Start Over"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

# ==================================================
# MAIN CHAT INPUT & VOICE BUTTON 
# ==================================================
col_mic, col_chat = st.columns([1, 10])

with col_mic:
    if bot.VOICE_AVAILABLE:
        if stage == "chat" and st.session_state.get("voice_error") == "silence":
            st.session_state.voice_error = None

        mic_ok = (stage == "chat") and (st.session_state.get("voice_error") != "mic")

        if st.button("🎙️", disabled=not mic_ok, use_container_width=True, help="Click to speak"):
            bot.stop_speaking()

            listen_secs = max(getattr(bot, "VOICE_DURATION", 5), 5)
            st.toast("🎙️ Listening… speak now", icon="🎙️")

            with st.spinner(f"Listening ({listen_secs}s) — speak clearly and close to the mic…"):
                voice_result = bot.recognize_speech(listen_secs)

            if voice_result and isinstance(voice_result, str) and voice_result.strip():
                st.session_state.voice_prompt = voice_result.strip()
                st.session_state.voice_error  = None
                st.rerun()

            elif voice_result is None or voice_result is False:
                st.session_state.voice_error = "mic"
                st.toast("Microphone error — check your audio device and refresh the page.", icon="⚠️")

            else:
                st.session_state.voice_error = "silence"
                st.toast("Nothing heard — try speaking louder or moving closer to the mic.", icon="🎙️")

with col_chat:
    text_prompt = st.chat_input("Try: 'Create order for CM94532' or 'Send email to myname@domain.com'", disabled=(stage != "chat"))

# Decide which prompt to act on
prompt = text_prompt if text_prompt else st.session_state.get("voice_prompt")

is_faq_request = False
if st.session_state.get("faq_pending"):
    prompt = st.session_state.faq_pending
    st.session_state.faq_pending = None
    is_faq_request = True

if prompt:
    if "voice_prompt" in st.session_state: st.session_state.voice_prompt = None

    if prompt.strip().lower() in ("exit", "quit", "stop", "cancel"):
        st.warning("Canceling operation and starting over...")
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()

    user_say(prompt)
    gh_add("user", prompt)

    if is_faq_request and prompt in FAQ_DATA:
        ans = FAQ_DATA[prompt]
        if hasattr(bot, 'clean_text_for_speech'):
            assistant_say(ans, speak_text=bot.clean_text_for_speech(ans))
        else:
            assistant_say(ans)
        gh_add("assistant", ans)
        st.rerun()

    # --------------------------------------------------
    # NEW: Intercept "Send Email" Intent
    # --------------------------------------------------
    prompt_lower = prompt.lower()
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', prompt)
    
    if "email" in prompt_lower or "mail" in prompt_lower or "send" in prompt_lower:
        extracted = {"action": "email"}
        if email_match:
            extracted["email_address"] = email_match.group(0)
    else:
        extracted = bot.github_extract_intent(prompt)

    if st.session_state.get("pending_field") and st.session_state.action == "create":
        pf = st.session_state.pending_field
        pf_map = {
            "Customer PO Number": "cpo",
            "Ordered Item code":  "ordered_item",
            "Ordered Quantity":   "quantity",
            "Line Type ID":       "line_type_id"
        }
        internal_key = pf_map.get(pf)
        if internal_key and not extracted.get(internal_key):
            raw_val = prompt.strip()
            if internal_key in ["quantity", "line_type_id"]:
                nums = re.findall(r'\d+\.?\d*', raw_val)
                if nums:
                    extracted[internal_key] = float(nums[0]) if '.' in nums[0] else int(nums[0])
            else:
                extracted[internal_key] = raw_val
        st.session_state.pending_field = None

    explicit_mapping = {
        "CUST_PO_NUMBER":     "cpo",              "ORDERED_ITEM":       "ordered_item",
        "ORDERED_QUANTITY":   "quantity",          "UNIT_LIST_PRICE":    "unit_list_price",
        "UNIT_SELLING_PRICE": "unit_selling_price","PAYMENT_TERM_ID":    "payment_term_id",
        "SALESREP_ID":        "salesrep_id",       "LINE_TYPE_ID":       "line_type_id",
        "SHIP_TO_ORG_ID":     "ship_to_org_id",   "SOLD_TO_ORG_ID":     "sold_to_org_id"
    }
    for explicit_key, internal_key in explicit_mapping.items():
        match = re.search(rf"{explicit_key}\s*(?:is|=|:)\s*([A-Za-z0-9_.-]+)", prompt, re.IGNORECASE)
        if match:
            val = match.group(1)
            extracted[internal_key] = float(val) if '.' in val else int(val) if val.isdigit() else val

    if "create" in prompt_lower:
        extracted["action"] = "create"
    elif any(word in prompt_lower for word in ["get", "find", "search", "show", "fetch", "retrieve"]) and extracted.get("action") != "email":
        extracted["action"] = "get"

    od_customer_match = re.search(
        r'order\s+details?\s+(?:for|by|of)?\s+(?:customer\s+)?(.+)',
        prompt_lower
    )
    if od_customer_match or ("order details" in prompt_lower and "customer" in prompt_lower):
        name_match = re.search(
            r'order\s+details?\s+(?:for|by|of)?\s+(?:customer\s+)?(.+)',
            prompt, re.IGNORECASE
        )
        if name_match:
            st.session_state.order_details_customer_name = name_match.group(1).strip()
        st.session_state.order_details_rows = []
        st.session_state.order_details_page = 0
        st.session_state.stage = "order_details_by_customer"
        assistant_say(
            f"🔎 Opening order details search for customer orders...",
            speak_text="Opening order details search."
        )
        st.rerun()

    year_match = re.search(r'\b(20\d{2})\b', prompt)
    if year_match and not extracted.get("year"):
        extracted["year"] = int(year_match.group(1))

    order_match = re.search(
        r'(?:order|#|no\.?|number)\s*(\d{3,})|(?<!\d)(\d{5,})(?!\d)',
        prompt, re.IGNORECASE
    )
    if order_match and not extracted.get("order_number"):
        raw_num = order_match.group(1) or order_match.group(2)
        if raw_num:
            extracted["order_number"] = int(raw_num)

    action = extracted.get("action", "unknown")
    merge_fields(extracted)

    has_specific_order = bool(st.session_state.collected.get("order_number"))
    wants_advanced = (
        extracted.get("year") or
        extracted.get("date_range") or
        (extracted.get("status") and not has_specific_order)
    )

    # --------------------------------------------------
    # Dispatch Email Intent Stage Check
    # --------------------------------------------------
    if action == "email" or st.session_state.action == "email":
        st.session_state.action = "email"
        st.session_state.stage = "send_email_flow"
        assistant_say("Preparing email draft. Please verify the details above.", speak_text="Preparing email draft.")
        st.rerun()

    elif wants_advanced and not has_specific_order:
        with st.spinner("⏳ Searching database..."):
            try:
                res = bot.get_orders_advanced(
                    extracted.get("date_range"),
                    extracted.get("year"),
                    extracted.get("status")
                )
                
                summary_context = {"total_found": res["total_count"], "first_5_rows": res["rows"][:5]}
                ai_summary = generate_ai_summary("Search Multiple Orders", summary_context)
                assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

                st.session_state.api_result, st.session_state.stage = res, "show_get_order"
                st.rerun()
            except Exception as e:
                assistant_say(f"❌ DB Search Error: {e}", speak_text="There was an error searching the database.")
                st.rerun()

    elif action == "get" or st.session_state.action == "get":
        st.session_state.action = "get"
        order_num = st.session_state.collected.get("order_number")
        if order_num is None:
            q = bot.github_clarify(st.session_state.gh_history, ["Order Number"])
            assistant_say(q, speak_text=clean_text_for_speech(q))
            gh_add("assistant", q)
            st.rerun()
        else:
            st.session_state.get_order_num = int(order_num)
            st.session_state.stage = "fetch_get_order"
            st.rerun()

    elif action == "create" or st.session_state.action == "create":
        st.session_state.action = "create"
        missing = missing_minimum()

        if missing:
            next_missing = missing[0]
            if next_missing == "Customer PO Number":
                response_text = "Got it. Let's create an order. What is the **Customer PO Number**?"
            elif next_missing == "Ordered Item code":
                response_text = "What is the **Ordered Item code** you would like?"
            elif next_missing == "Ordered Quantity":
                response_text = "How many do you need? Please enter the **Ordered Quantity**."
            elif next_missing == "Line Type ID":
                response_text = "Finally, what is the **Line Type ID**?"
            else:
                response_text = f"Please provide the {next_missing}."

            assistant_say(response_text, speak_text=clean_text_for_speech(response_text))
            gh_add("assistant", response_text)
            st.session_state.pending_field = next_missing
            st.rerun()
        else:
            st.session_state.stage = "resolve"
            st.rerun()

    else:
        fallback = bot.github_clarify(
            st.session_state.gh_history,
            ["action: 'create a new order', 'get order by number', 'search orders by year', or 'order details for customer <name>'"]
        )
        assistant_say(fallback, speak_text=clean_text_for_speech(fallback))
        gh_add("assistant", fallback)
        st.rerun()