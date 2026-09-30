import streamlit as st
import SalesOrderChatandVoiceBot2 as bot
import json
import pandas as pd
import re
import threading
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import datetime

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
    "Can I schedule automated reports?": "Yes! Type 'Schedule a report daily' or 'Schedule for every 30 minutes'. I'll ask you whether it's for a specific customer or all of them.",
    "Can I search for orders by date or status?": "Yes! You can use natural language searches such as 'Show booked orders from 2024' or 'Find cancelled orders'.",
    "How do I see all orders for a specific customer?": "Type 'Order details for customer [Name]' (e.g., 'Order details for customer ACME'). This will pull up a comprehensive table of their past orders, shipments, and invoice balances.",
    "How do I use voice commands?": "Click the 🎙️ microphone icon next to the chat bar. Wait for the 'Listening...' notification to appear, then speak your command clearly.",
    "How do I cancel an operation?": "If you are in the middle of creating an order and want to stop, simply click the '🏠 Back to Chat' button available on all screens."
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
        "email_payload_html": "",  
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
            "cust_account_id": None, "line_type_id": None, "email_address": None,
            "schedule_interval": None
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
        "adv_search_page": 0,
        "adv_search_filters": {},
        "auto_email_enabled": False,   
        "auto_email_to": "",           
        "auto_email_status": None,     
        "auto_email_error": "",        
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# --------------------------------------------------
# Universal Back to Chat Helper
# --------------------------------------------------
def go_back_to_chat():
    msgs = st.session_state.get("messages", [])
    hist = st.session_state.get("gh_history", [])
    payload = st.session_state.get("email_payload_html", "")
    for k in list(st.session_state.keys()): 
        del st.session_state[k]
    st.session_state["messages"] = msgs
    st.session_state["gh_history"] = hist
    st.session_state["email_payload_html"] = payload
    _init_state()
    st.session_state.stage = "chat"
    st.rerun()

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
                except Exception:
                    pass
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
# Background Scheduler Logic
# --------------------------------------------------
def scheduled_worker(interval_mins: int, customer_name: str, to_email: str):
    """Background thread that executes the fetch and email continuously."""
    while True:
        time.sleep(interval_mins * 60)
        try:
            if customer_name.lower() in ["all", "all customers"]:
                # Broad Search for All
                res = bot.get_orders_advanced(None, None, None)
                ai_summary = "Automated scheduled report summarizing all recent orders."
                html_payload = generate_search_html(res, ai_summary)
                send_erp_email(to_email, "Scheduled Report: All Orders", "Your automated report is attached below.", html_payload)
            else:
                # Specific Customer
                rows = get_order_details_by_customer(customer_name)
                if rows:
                    ai_summary = f"Automated scheduled report summarizing recent activity for {customer_name}."
                    html_payload = generate_customer_html(rows, customer_name, ai_summary)
                    send_erp_email(to_email, f"Scheduled Report: {customer_name}", "Your automated report is attached below.", html_payload)
        except Exception as e:
            print(f"Scheduler Error: {e}")

def start_schedule_thread(interval_str: str, cust_name: str, to_email: str):
    # Parse standard intervals
    mins = 1440 # Default daily
    interval_lower = interval_str.lower()
    
    if "30" in interval_lower and "min" in interval_lower:
        mins = 30
    elif "1" in interval_lower and "hour" in interval_lower:
        mins = 60
    elif "daily" in interval_lower or "day" in interval_lower:
        mins = 1440
    else:
        # Extract arbitrary minutes if present
        nums = re.findall(r'\d+', interval_lower)
        if nums and "min" in interval_lower:
            mins = int(nums[0])
        elif nums and "hour" in interval_lower:
            mins = int(nums[0]) * 60
            
    t = threading.Thread(target=scheduled_worker, args=(mins, cust_name, to_email), daemon=True)
    t.start()

# --------------------------------------------------
# Smart Context Aware AI Functions
# --------------------------------------------------
def get_smart_intent(history: list, prompt: str) -> dict:
    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=bot.GITHUB_TOKEN,
        )
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
        
        system_prompt = (
            "You are an ERP intent extraction engine. Analyze the conversation history and the latest user prompt. "
            "Determine the intended action. Possible actions: "
            "'create' (create a new order), "
            "'get' (retrieve a SPECIFIC order by its order number), "
            "'search' (search/filter/list orders by year, date range, or status — use this when NO specific order number is mentioned), "
            "'email' (send email), "
            "'order_details' (get all order history for a specific customer by name), "
            "'schedule' (schedule an automated task/report to run periodically), "
            "or 'unknown'. "
            "CRITICAL: Use action='search' (NOT 'get') when the user mentions a year, date range, status, or wants to list/filter multiple orders without a specific order number. "
            "CRITICAL: Use action='get' ONLY when the user provides a specific order number. "
            "CRITICAL: If the user is answering a clarification question, infer the action directly from the assistant's previous question. "
            "Extract any of these keys if present: "
            "'order_number' (integer), 'customer_name' (string), 'cpo' (string), 'ordered_item' (string), "
            "'quantity' (number), 'line_type_id' (number), 'email_address' (string), 'year' (4-digit integer), "
            "'status' (string), 'date_range' (string), 'schedule_interval' (string - e.g., 'daily', '30 minutes', '1 hour'). "
            "Respond ONLY with a valid JSON object, no explanation."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"History:\n{history_str}\n\nLatest prompt: {prompt}"}
            ],
            temperature=0.0,
            max_tokens=150
        )
        
        content = response.choices[0].message.content.strip()

        if content.startswith("```json"):
            content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        elif content.startswith("```"):
            content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}

    except Exception as e:  
        return {}

def generate_ai_summary(operation_name: str, data: dict) -> str:
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
    except Exception:
        return "Operation completed. (AI Summary generation failed)"

# --------------------------------------------------
# HTML Generators for Email
# --------------------------------------------------
def _build_email_layout(cname: str, report_type: str, ai_summary: str, table_html: str, alerts: dict, faqs: list) -> str:
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    alerts_html = "<ul style='padding-left: 20px; font-size: 14px; margin-bottom: 0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom: 5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"
    
    faqs_html = """
    <table style='border-collapse: collapse; width: 100%; border: none; font-size: 14px;'>
        <tr>
            <th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>Question</th>
            <th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>AI Answer</th>
        </tr>
    """
    for q, a in faqs:
        faqs_html += f"<tr><td style='padding: 8px;'>{q}</td><td style='padding: 8px;'>{a}</td></tr>"
    faqs_html += "</table>"
    
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 800px; margin: auto; color: #000; padding: 10px;">
        
        <h3 style="color: #000; font-size: 16px; margin-top: 0;">Header Details</h3>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 20px;">
            <li style="margin-bottom: 5px;">Subject Target: {cname}</li>
            <li style="margin-bottom: 5px;">Date of Report: {report_date}</li>
            <li style="margin-bottom: 5px;">Statement Period: {report_type}</li>
        </ul>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
        <h3 style="color: #000; font-size: 16px;">Executive Summary</h3>
        "{ai_summary}"</p>
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
        <h3 style="color: #000; font-size: 16px;">Order Detail Table</h3>
        {table_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
        <h3 style="color: #000; font-size: 16px;">Exceptions & Alerts</h3>
        {alerts_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
        <h3 style="color: #000; font-size: 16px;">FAQ'S</h3>
        {faqs_html}
        <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
        <h3 style="color: #000; font-size: 16px;"></h3>
        <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 30px;">
            <li style="margin-bottom: 5px;">Support contact:  erp.support@centroid.com</li>
            <li style="margin-bottom: 5px;">Disclaimer : This notification was generated automatically from the ERP environment</li>
            <li style="margin-bottom: 5px;">Do-not-reply notice: Please do not reply directly to this email.</li>
        </ul>
    </div>
    """

def generate_order_html(result: dict, ai_summary: str) -> str:
    d = extract_erp_details(result)
    cname = d["header_details"].get("Customer", "Unknown Customer")
    order_num = d["header_details"].get("Order Number", "N/A")
    
    th_style = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td_style = "border: none; padding: 8px;"
    
    table_html = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    headers = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]
    for h in headers: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    
    has_holds = False
    if d["header_details"].get("Flow Status") == "ENTERED" or "HOLD" in str(d["header_details"].get("Flow Status", "")).upper():
        has_holds = True
        
    for ln in d["lines"]:
        table_html += "<tr>"
        table_html += f"<td style='{td_style}'>{order_num}</td>"
        table_html += f"<td style='{td_style}'>{ln.get('Item', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{ln.get('Qty Ordered', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{ln.get('Flow Status', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>TBD</td>"
        table_html += f"<td style='{td_style}'>Pending</td>"
        table_html += f"<td style='{td_style}'>N/A</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    alerts = {
        "Backorders": "None detected for this specific transaction",
        "Holds": "1" if has_holds else "0",
        "Partial Shipments": "N/A",
        "Payment Holds": "Check customer balance"
    }
    
    faqs = [
        (f"Why is Order {order_num} currently {d['header_details'].get('Flow Status', 'Processing')}?", f"The order is in {d['header_details'].get('Flow Status', 'Processing')} status waiting for the next step in the fulfillment cycle."),
        ("Can I expect partial shipment?", "Depends on line-level availability. Check shipping notices for updates.")
    ]
    
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", ai_summary, table_html, alerts, faqs)

def generate_search_html(res: dict, ai_summary: str) -> str:
    th_style = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td_style = "border: none; padding: 8px;"
    
    table_html = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    headers = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]
    for h in headers: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    
    for r in res.get("rows", [])[:20]:
        table_html += "<tr>"
        table_html += f"<td style='{td_style}'>{r[0]}</td>"
        table_html += f"<td style='{td_style}'>Multiple Lines</td>"
        table_html += f"<td style='{td_style}'>-</td>"
        table_html += f"<td style='{td_style}'>{r[1]}</td>"
        table_html += f"<td style='{td_style}'>{r[2]}</td>"
        table_html += f"<td style='{td_style}'>-</td>"
        table_html += f"<td style='{td_style}'>-</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    alerts = {"Backorders": "N/A for broad search", "Holds": "N/A for broad search", "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("What are these search results?", f"These are the top results matching your recent system search query, showing up to {res.get('total_count', 0)} orders.")]
    
    return _build_email_layout("Multiple Customers", "Search Query Results", ai_summary, table_html, alerts, faqs)

def generate_customer_html(rows: list, cname: str, ai_summary: str) -> str:
    top_rows = rows[:50]
    th_style = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td_style = "border: none; padding: 8px;"
    
    table_html = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    headers = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]
    for h in headers: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    
    backorders, holds, delayed = 0, 0, 0
    for r in top_rows:
        if str(r.get("BACKORDER_FLAG", "0")) == "1": backorders += 1
        if r.get("ORDER_HOLD_FLAG") == "Y": holds += 1
        if str(r.get("DELAYED_ORDER_FLAG", "0")) == "1": delayed += 1
        
        table_html += "<tr>"
        table_html += f"<td style='{td_style}'>{r.get('ORDER_NUMBER', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('ITEM_NUMBER', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('ORDERED_QTY', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('LINE_STATUS', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('SCHEDULE_SHIP_DATE', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('SHIPMENT_MODE', 'Pending')}</td>"
        table_html += f"<td style='{td_style}'>${r.get('INVOICE_BALANCE', '0.00')}</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    alerts = {
        "Backorders": str(backorders),
        "Holds": str(holds),
        "Partial Shipments": "Check line statuses for specific details",
        "Payment Holds": "Derived from Account Level (0 active currently)"
    }
    
    faqs = []
    if delayed > 0:
        faqs.append(("Why are some orders delayed?", f"There are {delayed} line(s) experiencing delays, potentially due to inventory constraints or transit exceptions."))
    else:
        faqs.append(("Are there any delayed orders?", "Currently, all displayed orders are processing on schedule without delays."))
        
    if backorders > 0:
        faqs.append(("Can I expect a partial shipment?", f"Yes, due to {backorders} backordered item(s), partial shipments may occur to fulfill available lines."))
    else:
        faqs.append(("Can I expect a partial shipment?", "All items appear to be in stock. Partial shipments are unlikely."))
        
    if holds > 0:
        faqs.append(("Has payment cleared?", "Some orders indicate holds, which may be tied to pending payment receipt or general account review."))
    else:
        faqs.append(("Has payment cleared?", "Payment pending receipt. No payment holds are actively blocking these recent lines."))
        
    return _build_email_layout(cname, "All Recent Customer Orders", ai_summary, table_html, alerts, faqs)

# --------------------------------------------------
# Email Logic
# --------------------------------------------------
def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str) -> tuple:
    sender = "erp.assistant@yourdomain.com"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    html_content = f"""
    <html>
    <head>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <p style="color: #333;">{body_text.replace(chr(10), '<br>')}</p>
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
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login("pavanmaccha042@gmail.com", "ltvxbwhkzkrptueg")
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)


# --------------------------------------------------
# Auto Email Worker
# --------------------------------------------------
def _do_auto_send(to_email: str, subject_context: str, html_payload: str):
    subject   = f"Automated Alert: {subject_context}"
    body_text = (
        f"Hi,\n\nPlease find the automated report for '{subject_context}' attached below.\n\n"
        f"This email was sent automatically based on your active configuration.\n\nRegards,\nSales Order Assistant"
    )
    success, msg = send_erp_email(to_email, subject, body_text, html_payload)
    if success:
        st.session_state["auto_email_status"] = "success"
    else:
        st.session_state["auto_email_status"] = "failed"
        st.session_state["auto_email_error"]  = msg


def trigger_auto_email(subject_context: str, html_payload: str):
    to_email = (
        st.session_state.get("auto_email_to", "").strip()
        or st.session_state.collected.get("email_address", "").strip()
    )
    if not to_email:
        st.session_state["auto_email_status"] = "no_recipient"
        return

    st.session_state["auto_email_status"] = "sending"
    t = threading.Thread(
        target=_do_auto_send,
        args=(to_email, subject_context, html_payload),
        daemon=True,
    )
    t.start()


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
        if st.button("🏠 Back to Chat", key=f"back_empty_{label.replace(' ','_')}"):
            go_back_to_chat()
        return

    opts = [f"[{i+1}] {display_fn(r)}" for i, r in enumerate(rows)]
    choice = st.radio(f"**Select {label}:**", opts)

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button(f"✅ Confirm {label}", key=f"conf_{label.replace(' ','_')}"):
            idx = opts.index(choice)
            on_confirm(rows[idx])
            st.session_state.stage = next_stage
            st.rerun()
    with col2:
        if len(rows) >= bot.MAX_CHOICES:
            if st.button("📑 Fetch Next Rows", key=f"next_{label.replace(' ','_')}"):
                st.session_state.offsets[offset_key] += bot.MAX_CHOICES
                st.session_state.stage = next_stage
                st.rerun()
        if st.session_state.offsets.get(offset_key, 0) > 0:
            if st.button("⬅️ Previous Rows", key=f"prev_{label.replace(' ','_')}"):
                st.session_state.offsets[offset_key] = max(0, st.session_state.offsets[offset_key] - bot.MAX_CHOICES)
                st.session_state.stage = next_stage
                st.rerun()
    with col3:
        if st.button("🏠 Back to Chat", key=f"back_sel_{label.replace(' ','_')}"):
            go_back_to_chat()

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
            if st.button("⬅️ Previous Page", key="od_prev"):
                st.session_state.order_details_page -= 1
                st.rerun()
    with pc3:
        if end < total:
            if st.button("Next Page ➡️", key="od_next"):
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

    # --------------------------------------------------
    # Auto Email Settings (sidebar)
    # --------------------------------------------------
    st.markdown("### 📧 Auto Email Settings")
    st.caption("When enabled, an email is sent **automatically** after every completed operation (Search, Create, Retrieve, etc.).")

    auto_enabled = st.toggle(
        "🔔 Auto-send after operations",
        value=st.session_state.get("auto_email_enabled", False),
        key="sidebar_auto_email_toggle",
    )
    st.session_state["auto_email_enabled"] = auto_enabled

    if auto_enabled:
        auto_to = st.text_input(
            "Recipient Email:",
            value=st.session_state.get("auto_email_to", ""),
            placeholder="recipient@company.com",
            key="sidebar_auto_email_to",
        )
        st.session_state["auto_email_to"] = auto_to.strip()

        if not auto_to.strip():
            st.warning("⚠️ Enter a recipient email to activate auto-send.")
        else:
            st.success(f"✅ Auto-send active → `{auto_to.strip()}`")

        # Show last auto-send status
        auto_status = st.session_state.get("auto_email_status")
        if auto_status == "sending":
            st.info("📤 Sending email in background…")
        elif auto_status == "success":
            st.success("📬 Last auto-email sent successfully!")
        elif auto_status == "failed":
            st.error(f"❌ Last auto-email failed: {st.session_state.get('auto_email_error','')}")
        elif auto_status == "no_recipient":
            st.warning("⚠️ Auto-send skipped — no recipient configured.")

        # Reset status button
        if auto_status in ("success", "failed", "no_recipient"):
            if st.button("Clear Status", key="btn_clear_auto_status"):
                st.session_state["auto_email_status"] = None
                st.session_state["auto_email_error"]  = ""
                st.rerun()
    else:
        st.caption("Auto-email is disabled. Use the 'Send email to …' command to email results manually.")

    st.markdown("---")
    
    with st.expander("❓ Frequently Asked Questions (FAQ)"):
        st.info("Click any question below to ask the AI:")
        for i, question in enumerate(FAQ_DATA.keys()):
            if st.button(f"🗣️ {question}", key=f"faq_btn_{i}", use_container_width=True):
                st.session_state.faq_pending = question

    st.markdown("---")
    if st.button("🔄 Clear Chat & Start Over", use_container_width=True, key="clear_chat_sidebar"):
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

    to_email = st.text_input(
        "To:",
        value=c.get("email_address", "") or st.session_state.get("auto_email_to", ""),
    )
    subject  = st.text_input("Subject:", value="Oracle ERP Order Details Update")
    body     = st.text_area("Message Body:", value="Please find the requested order details structured below.")

    html_preview = st.session_state.get("email_payload_html", "")
    with st.expander("Preview Data to be Sent"):
        if html_preview:
            st.markdown(html_preview, unsafe_allow_html=True)
        else:
            st.warning("No recent operation data found to attach to this email.")

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("✅ Send Email", key="btn_send_email"):
            if not to_email:
                st.error("Email address is required.")
            else:
                with st.spinner("Dispatching email..."):
                    success, msg = send_erp_email(to_email, subject, body, html_preview)
                    if success:
                        assistant_say(
                            f"✅ Email sent successfully to `{to_email}`!",
                            speak_text="The email was sent successfully."
                        )
                        st.session_state.stage = "chat"
                        st.rerun()
                    else:
                        st.error(f"Error sending email: {msg}")
    with col2:
        if st.button("🏠 Back to Chat", key="btn_email_back"):
            go_back_to_chat()

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
        if st.button("✅ Confirm Selling Price", key="btn_conf_sp"):
            val = bot.parse_numeric_value(selling_input, allow_float=True) if selling_input.strip() else None
            c["unit_selling_price"] = val if val is not None else unit_price
            assistant_say(f"✅ Selling Price set to: `${c['unit_selling_price']:.2f}`", speak_text=f"Selling price confirmed at {c['unit_selling_price']} dollars.")
            st.session_state.stage = "resolve"
            st.rerun()
    with col2:
        if st.button("🏠 Back to Chat", key="btn_sp_back"):
            go_back_to_chat()

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
            if st.button("✅ Confirm Line Type", key="btn_lt_conf"):
                idx = opts.index(choice)
                selected = rows[idx]
                st.session_state.collected["line_type_id"] = selected["line_type_id"]
                assistant_say(f"✅ Line Type: `{selected['line_type_name']}` (ID: {selected['line_type_id']})", speak_text=f"Line type confirmed as {selected['line_type_name']}")
                st.session_state.stage = "resolve"
                st.rerun()
        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page", key="btn_lt_next"):
                    st.session_state.offsets["line_type"] += bot.MAX_CHOICES
                    st.session_state.line_type_rows = bot.get_line_type_rows(offset=st.session_state.offsets["line_type"])
                    st.rerun()
        with col3:
            if st.session_state.offsets.get("line_type", 0) > 0:
                if st.button("⬅️ Previous Page", key="btn_lt_prev"):
                    st.session_state.offsets["line_type"] = max(0, st.session_state.offsets["line_type"] - bot.MAX_CHOICES)
                    st.session_state.line_type_rows = bot.get_line_type_rows(offset=st.session_state.offsets["line_type"])
                    st.rerun()
        with col4:
            if st.button("🏠 Back to Chat", key="btn_lt_back_1"):
                go_back_to_chat()
    else:
        st.warning("No line types found. Enter a Line Type ID manually:")
        lt_input = st.text_input("Line Type ID:", key="line_type_manual_input")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Line Type", key="btn_lt_man_conf"):
                val = bot.parse_numeric_value(lt_input)
                if val is not None:
                    st.session_state.collected["line_type_id"] = val
                    assistant_say(f"✅ Line Type ID set to: `{val}`", speak_text="Line type confirmed.")
                    st.session_state.stage = "resolve"
                    st.rerun()
                else:
                    st.error("Please enter a valid numeric ID.")
        with col2:
            if st.button("🏠 Back to Chat", key="btn_lt_back_2"):
                go_back_to_chat()

elif stage == "select_customer":
    st.markdown("### 🔍 Select Customer")
    search_val = st.text_input("Search customer by name:", value=st.session_state.collected.get("customer_name") or "", key="customer_search_input")
    if st.button("🔍 Search", key="btn_cust_search"):
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
            if st.button("✅ Confirm Customer", key="btn_cust_conf"):
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
                if st.button("📑 Next Page", key="btn_cust_next"):
                    st.session_state.offsets["customer"] += bot.MAX_CHOICES
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(name, offset=st.session_state.offsets["customer"])
                    st.rerun()
        with col3:
            if st.session_state.offsets["customer"] > 0:
                if st.button("⬅️ Prev Page", key="btn_cust_prev"):
                    st.session_state.offsets["customer"] = max(0, st.session_state.offsets["customer"] - bot.MAX_CHOICES)
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(name, offset=st.session_state.offsets["customer"])
                    st.rerun()
        with col4:
            if st.button("🏠 Back to Chat", key="btn_cust_back_1"):
                go_back_to_chat()
    else:
        st.info("Use the search box above to find customers.")
        if st.button("🏠 Back to Chat", key="btn_cust_back_2"):
            go_back_to_chat()

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
            if st.button("✅ Confirm Customer", key="btn_cbi_conf"):
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
                        f"✅ Customer: `{sites[0]['customer_name']}`  | Sold-to: `{sites[0]['sold_to_org_id']}`  | Ship-to: `{sites[0]['ship_to_org_id']}`"
                    )

    # /* 3. General Chat Row Setup */
    # [data-testid="stChatMessage"] {
    #     background-color: transparent !important;
    #     border: none !important;
    #     padding: 0.5rem 1rem !important;
    #     gap: 0px !important;
    # }

    # # /* 4. USER MESSAGE: ChatGPT/Claude style (Right-aligned, soft gray bubble) */
    # # [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    #     display: flex !important;
    #     flex-direction: row-reverse !important;
    #     margin-bottom: 15px;
    # }
    # [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
    #     background-color: #f4f4f4 !important;
    #     color: #0d0d0d !important;
    #     padding: 12px 20px !important;
    #     border-radius: 20px 20px 4px 20px !important;
    #     max-width: 70% !important;
    #     font-size: 16px;
    #     line-height: 1.5;
    #     text-align: left !important;
    # }

    # /* 5. ASSISTANT MESSAGE: Plain text, no bubble, left-aligned */
    # [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
    #     display: flex !important;
    #     flex-direction: row !important;
    #     margin-bottom: 25px;
    # }
    # [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
    #     background-color: transparent !important;
    #     color: #0d0d0d !important;
    #     padding: 0px 10px !important;
    #     max-width: 85% !important;
    #     font-size: 16px;
    #     line-height: 1.6;
    # }

    # /* 6. Fix Markdown typography inheritance */
    # [data-testid="stChatMessage"] div.stMarkdown p, 
    # [data-testid="stChatMessage"] div.stMarkdown h1,
    # [data-testid="stChatMessage"] div.stMarkdown h2,
    # [data-testid="stChatMessage"] div.stMarkdown h3 { color: inherit !important; margin-bottom: 0.5rem; }

    # /* 7. Chat Input Bar Styling */
    # [data-testid="stChatInput"] {
    #     border-radius: 24px !important;
    #     border: 1px solid #e5e5e5 !important;
    #     background-color: #f9f9f9 !important;
    # }
    # [data-testid="stChatInput"]:focus-within {
    #     border-color: #b3b3b3 !important;
    #     background-color: #ffffff !important;
    # }
    
    # /* 8. Modern Buttons (Including Mic & FAQ) */
    # .stButton>button {
    #     border-radius: 24px;
    #     border: 1px solid #e5e5e5;
    #     background-color: #ffffff;
    #     color: #0d0d0d;
    #     font-size: 1.2rem;
    #     transition: all 0.2s ease;
    # }
    # .stButton>button:hover {
    #     background-color: #f4f4f4;
    #     border-color: #cccccc;
    # }

    # /* Smaller text for FAQ buttons to look neat in sidebar */
    # [data-testid="stSidebar"] .stButton>button {
    #     font-size: 0.9rem;
    #     padding: 0.25rem 0.75rem;
    #     text-align: left;
    #     justify-content: flex-start;
    # }
    
    # /* 9. Sidebar styling */
    # [data-testid="stSidebar"] { background-color: #f9f9f9; border-right: 1px solid #e5e5e5; }
    # [data-testid="stCaptionContainer"] p { color: #555555 !important; font-weight: 500; font-size: 1.1rem; }
    # </style>
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
    "How do I cancel an operation?": "If you are in the middle of creating an order and want to stop, simply click the '🏠 Back to Chat' button available on all screens."
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
        "email_payload_html": "",  
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
        "adv_search_page": 0,
        "adv_search_filters": {},
        "auto_email_enabled": False,   
        "auto_email_to": "",           
        "auto_email_status": None,     
        "auto_email_error": "",        
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# --------------------------------------------------
# Universal Back to Chat Helper
# --------------------------------------------------
def go_back_to_chat():
    msgs = st.session_state.get("messages", [])
    hist = st.session_state.get("gh_history", [])
    payload = st.session_state.get("email_payload_html", "")
    for k in list(st.session_state.keys()): 
        del st.session_state[k]
    st.session_state["messages"] = msgs
    st.session_state["gh_history"] = hist
    st.session_state["email_payload_html"] = payload
    _init_state()
    st.session_state.stage = "chat"
    st.rerun()

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
                except Exception:
                    pass
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
# Smart Context Aware AI Functions
# --------------------------------------------------
def get_smart_intent(history: list, prompt: str) -> dict:
    try:
        client = OpenAI(
            base_url="[https://models.inference.ai.azure.com](https://models.inference.ai.azure.com)",
            api_key=bot.GITHUB_TOKEN,
        )
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
        
        system_prompt = (
            "You are an ERP intent extraction engine. Analyze the conversation history and the latest user prompt. "
            "Determine the intended action. Possible actions: "
            "'create' (create a new order), "
            "'get' (retrieve a SPECIFIC order by its order number), "
            "'search' (search/filter/list orders by year, date range, or status — use this when NO specific order number is mentioned), "
            "'email' (send email), "
            "'order_details' (get all order history for a specific customer by name), "
            "or 'unknown'. "
            "CRITICAL: Convert spoken word numbers into digits (e.g., 'sixty four thousand four hundred sixty' -> 64460). "
            "Respond ONLY with a valid JSON object."
        )
        response = client.chat.completions.create(
            model=bot.GITHUB_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"History:\n{history_str}\n\nLatest prompt: {prompt}"}
            ],
            temperature=0.0,
            max_tokens=150
        )
        
        content = response.choices[0].message.content.strip()

        if content.startswith("
```json"):
            content = content[7:]
            if content.endswith("```"): content = content[:-3]
            content = content.strip()
        elif content.startswith("
```"):
            content = content[3:]
            if content.endswith("```"): content = content[:-3]
            content = content.strip()

        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}

    except Exception:  
        return {}

def generate_ai_summary(operation_name: str, data: dict) -> str:
    try:
        client = OpenAI(
            base_url="[https://models.inference.ai.azure.com](https://models.inference.ai.azure.com)",
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
    except Exception:
        return "Operation completed. (AI Summary generation failed)"

# --------------------------------------------------
# HTML Generators for Email
# --------------------------------------------------
def _build_email_layout(cname: str, report_type: str, ai_summary: str, table_html: str, alerts: dict, faqs: list) -> str:
    report_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    alerts_html = "<ul style='padding-left: 20px; font-size: 14px; margin-bottom: 0;'>"
    for k, v in alerts.items():
        alerts_html += f"<li style='margin-bottom: 5px;'>{k}: {v}</li>"
    alerts_html += "</ul>"
    
    faqs_html = """
    # <table style='border-collapse: collapse; width: 100%; border: none; font-size: 14px;'>
    #     <tr>
    #         <th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>Question</th>
    #         <th style='text-align: left; padding: 8px; border-bottom: 1px solid #ccc;'>AI Answer</th>
    #     </tr>
    # """
    # for q, a in faqs:
    #     faqs_html += f"<tr><td style='padding: 8px;'>{q}</td><td style='padding: 8px;'>{a}</td></tr>"
    # faqs_html += "</table>"
    
    # return f"""
    # <div style="font-family: Arial, sans-serif; max-width: 800px; margin: auto; color: #000; padding: 10px;">
        
    #     <h3 style="color: #000; font-size: 16px; margin-top: 0;">Header Details</h3>
    #     <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 20px;">
    #         <li style="margin-bottom: 5px;">Customer Name: {cname}</li>
    #         <li style="margin-bottom: 5px;">Contact Name: Account Primary</li>
    #         <li style="margin-bottom: 5px;">Date of Report: {report_date}</li>
    #         <li style="margin-bottom: 5px;">Statement Period: {report_type}</li>
    #     </ul>
    #     <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
    #     <h3 style="color: #000; font-size: 16px;">Executive Summary</h3>
    #     "{ai_summary}"</p>
    #     <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
    #     <h3 style="color: #000; font-size: 16px;">Order Detail Table</h3>
    #     {table_html}
    #     <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
    #     <h3 style="color: #000; font-size: 16px;">Exceptions & Alerts</h3>
    #     {alerts_html}
    #     <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
    #     <h3 style="color: #000; font-size: 16px;">FAQ'S</h3>
    #     {faqs_html}
    #     <hr style="border: 0; border-top: 1px solid #aaa; margin: 20px 0;">
        
    #     <h3 style="color: #000; font-size: 16px;"></h3>
    #     <ul style="list-style-type: disc; padding-left: 20px; font-size: 14px; margin-bottom: 30px;">
    #         <li style="margin-bottom: 5px;">Support contact:  erp.support@centroid.com</li>
    #         <li style="margin-bottom: 5px;">Disclaimer : This notification was generated automatically from the ERP environment</li>
    #         <li style="margin-bottom: 5px;">Do-not-reply notice: Please do not reply directly to this email.</li>
    #     </ul>
    # </div>
    # """

def generate_order_html(result: dict, ai_summary: str) -> str:
    d = extract_erp_details(result)
    cname = d["header_details"].get("Customer", "Unknown Customer")
    order_num = d["header_details"].get("Order Number", "N/A")
    
    th_style = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td_style = "border: none; padding: 8px;"
    
    table_html = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    headers = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]
    for h in headers: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    
    has_holds = False
    if d["header_details"].get("Flow Status") == "ENTERED" or "HOLD" in str(d["header_details"].get("Flow Status", "")).upper():
        has_holds = True
        
    for ln in d["lines"]:
        table_html += "<tr>"
        table_html += f"<td style='{td_style}'>{order_num}</td>"
        table_html += f"<td style='{td_style}'>{ln.get('Item', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{ln.get('Qty Ordered', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{ln.get('Flow Status', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>TBD</td>"
        table_html += f"<td style='{td_style}'>Pending</td>"
        table_html += f"<td style='{td_style}'>N/A</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    alerts = {
        "Backorders": "None detected for this specific transaction",
        "Holds": "1" if has_holds else "0",
        "Partial Shipments": "N/A",
        "Payment Holds": "Check customer balance"
    }
    
    faqs = [
        (f"Why is Order {order_num} currently {d['header_details'].get('Flow Status', 'Processing')}?", f"The order is in {d['header_details'].get('Flow Status', 'Processing')} status waiting for the next step in the fulfillment cycle."),
        ("Can I expect partial shipment?", "Depends on line-level availability. Check shipping notices for updates.")
    ]
    
    return _build_email_layout(cname, f"Transaction: Order #{order_num}", ai_summary, table_html, alerts, faqs)

def generate_search_html(res: dict, ai_summary: str) -> str:
    th_style = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td_style = "border: none; padding: 8px;"
    
    table_html = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    headers = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]
    for h in headers: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    
    for r in res["rows"][:20]:
        table_html += "<tr>"
        table_html += f"<td style='{td_style}'>{r[0]}</td>"
        table_html += f"<td style='{td_style}'>Multiple Lines</td>"
        table_html += f"<td style='{td_style}'>-</td>"
        table_html += f"<td style='{td_style}'>{r[1]}</td>"
        table_html += f"<td style='{td_style}'>{r[2]}</td>"
        table_html += f"<td style='{td_style}'>-</td>"
        table_html += f"<td style='{td_style}'>-</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    alerts = {"Backorders": "N/A for broad search", "Holds": "N/A for broad search", "Partial Shipments": "N/A", "Payment Holds": "N/A"}
    faqs = [("What are these search results?", f"These are the top results matching your recent system search query, showing up to {res['total_count']} orders.")]
    
    return _build_email_layout("System User", "Search Query Results", ai_summary, table_html, alerts, faqs)

def generate_customer_html(rows: list, cname: str, ai_summary: str) -> str:
    top_rows = rows[:50]
    th_style = "border: none; padding: 8px; text-align: left; font-weight: bold;"
    td_style = "border: none; padding: 8px;"
    
    table_html = f"<table style='border-collapse: collapse; width: 100%; font-size: 14px;'><tr>"
    headers = ["Order #", "Line Item", "Qty", "Status", "Ship Date", "Tracking", "Invoice Balance"]
    for h in headers: table_html += f"<th style='{th_style}'>{h}</th>"
    table_html += "</tr>"
    
    backorders, holds, delayed = 0, 0, 0
    for r in top_rows:
        if str(r.get("BACKORDER_FLAG", "0")) == "1": backorders += 1
        if r.get("ORDER_HOLD_FLAG") == "Y": holds += 1
        if str(r.get("DELAYED_ORDER_FLAG", "0")) == "1": delayed += 1
        
        table_html += "<tr>"
        table_html += f"<td style='{td_style}'>{r.get('ORDER_NUMBER', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('ITEM_NUMBER', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('ORDERED_QTY', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('LINE_STATUS', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('SCHEDULE_SHIP_DATE', 'N/A')}</td>"
        table_html += f"<td style='{td_style}'>{r.get('SHIPMENT_MODE', 'Pending')}</td>"
        table_html += f"<td style='{td_style}'>${r.get('INVOICE_BALANCE', '0.00')}</td>"
        table_html += "</tr>"
    table_html += "</table>"
    
    alerts = {
        "Backorders": str(backorders),
        "Holds": str(holds),
        "Partial Shipments": "Check line statuses for specific details",
        "Payment Holds": "Derived from Account Level (0 active currently)"
    }
    
    faqs = []
    if delayed > 0:
        faqs.append(("Why are some orders delayed?", f"There are {delayed} line(s) experiencing delays, potentially due to inventory constraints or transit exceptions."))
    else:
        faqs.append(("Are there any delayed orders?", "Currently, all displayed orders are processing on schedule without delays."))
        
    if backorders > 0:
        faqs.append(("Can I expect a partial shipment?", f"Yes, due to {backorders} backordered item(s), partial shipments may occur to fulfill available lines."))
    else:
        faqs.append(("Can I expect a partial shipment?", "All items appear to be in stock. Partial shipments are unlikely."))
        
    if holds > 0:
        faqs.append(("Has payment cleared?", "Some orders indicate holds, which may be tied to pending payment receipt or general account review."))
    else:
        faqs.append(("Has payment cleared?", "Payment pending receipt. No payment holds are actively blocking these recent lines."))
        
    return _build_email_layout(cname, "All Recent Customer Orders", ai_summary, table_html, alerts, faqs)

# --------------------------------------------------
# Email Logic
# --------------------------------------------------
def send_erp_email(to_email: str, subject: str, body_text: str, html_table: str) -> tuple:
    sender = "erp.assistant@yourdomain.com"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    html_content = f"""
    <html>
    <head>
    </head>
    <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
        <p style="color: #333;">{body_text.replace(chr(10), '<br>')}</p>
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
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login("pavanmaccha042@gmail.com", "ltvxbwhkzkrptueg")
        server.sendmail(sender, to_email, msg.as_string())
        server.quit()
        return True, "Email sent successfully!"
    except Exception as e:
        return False, str(e)


# --------------------------------------------------
# Auto Email — Background processing logic
# --------------------------------------------------
def _do_auto_send(to_email: str, report_context: str, html_payload: str):
    subject   = f"Automated ERP Update — {report_context}"
    body_text = (
        f"Hi,\n\nPlease find the automated order details report for "
        f"'{report_context}' attached below.\n\n"
        f"This email was sent automatically.\n\nRegards,\nSales Order Assistant"
    )
    success, msg = send_erp_email(to_email, subject, body_text, html_payload)
    if success:
        st.session_state["auto_email_status"] = "success"
    else:
        st.session_state["auto_email_status"] = "failed"
        st.session_state["auto_email_error"]  = msg


def trigger_auto_email(report_context: str, html_payload: str):
    if not st.session_state.get("auto_email_enabled"):
        return

    to_email = (
        st.session_state.get("auto_email_to", "").strip()
        or st.session_state.collected.get("email_address", "").strip()
    )
    if not to_email:
        st.session_state["auto_email_status"] = "no_recipient"
        return

    st.session_state["auto_email_status"] = "sending"
    t = threading.Thread(
        target=_do_auto_send,
        args=(to_email, report_context, html_payload),
        daemon=True,
    )
    t.start()


# --------------------------------------------------
# Background Scheduler Loop
# --------------------------------------------------
def scheduled_worker(interval_secs: int, customer: str, email: str):
    while True:
        time.sleep(interval_secs)
        try:
            # Re-fetch the data in the background
            rows = get_order_details_by_customer(customer)
            if rows:
                cname = customer if customer else "ALL Customers"
                summary_context = {
                    "customer": cname,
                    "total_lines_found": len(rows),
                    "sample_data": rows[:3]
                }
                ai_summary = generate_ai_summary("Scheduled Order Report", summary_context)
                html = generate_customer_html(rows, cname, ai_summary)
                
                subject   = f"Scheduled ERP Report — {cname}"
                body_text = f"Attached is your scheduled automated report for {cname}."
                send_erp_email(email, subject, body_text, html)
        except Exception:
            pass 


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
        if st.button("🏠 Back to Chat", key=f"back_empty_{label.replace(' ','_')}"):
            go_back_to_chat()
        return

    opts = [f"[{i+1}] {display_fn(r)}" for i, r in enumerate(rows)]
    choice = st.radio(f"**Select {label}:**", opts)

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        if st.button(f"✅ Confirm {label}", key=f"conf_{label.replace(' ','_')}"):
            idx = opts.index(choice)
            on_confirm(rows[idx])
            st.session_state.stage = next_stage
            st.rerun()
    with col2:
        if len(rows) >= bot.MAX_CHOICES:
            if st.button("📑 Fetch Next Rows", key=f"next_{label.replace(' ','_')}"):
                st.session_state.offsets[offset_key] += bot.MAX_CHOICES
                st.session_state.stage = next_stage
                st.rerun()
        if st.session_state.offsets.get(offset_key, 0) > 0:
            if st.button("⬅️ Previous Rows", key=f"prev_{label.replace(' ','_')}"):
                st.session_state.offsets[offset_key] = max(0, st.session_state.offsets[offset_key] - bot.MAX_CHOICES)
                st.session_state.stage = next_stage
                st.rerun()
    with col3:
        if st.button("🏠 Back to Chat", key=f"back_sel_{label.replace(' ','_')}"):
            go_back_to_chat()

# --------------------------------------------------
# get_order_details_by_customer()
# --------------------------------------------------
def get_order_details_by_customer(p_customer_name: str = None) -> list:
    cust_filter = "AND HP.PARTY_NAME = :p_customer_name" if p_customer_name else ""
    sql = f"""
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
        {cust_filter}
        ORDER BY OOHA.ORDER_NUMBER, OOLA.LINE_NUMBER
    """
    params = {"p_customer_name": p_customer_name} if p_customer_name else {}
    rows = bot.execute_query(sql, params)
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
            if st.button("⬅️ Previous Page", key="od_prev"):
                st.session_state.order_details_page -= 1
                st.rerun()
    with pc3:
        if end < total:
            if st.button("Next Page ➡️", key="od_next"):
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

    # --------------------------------------------------
    # Auto Email Settings (sidebar)
    # --------------------------------------------------
    st.markdown("### 📧 Auto Email Settings")
    st.caption("When enabled, an email is sent **automatically** after ANY data retrieval operation completes.")

    auto_enabled = st.toggle(
        "🔔 Auto-send reports",
        value=st.session_state.get("auto_email_enabled", False),
        key="sidebar_auto_email_toggle",
    )
    st.session_state["auto_email_enabled"] = auto_enabled

    if auto_enabled:
        auto_to = st.text_input(
            "Recipient Email:",
            value=st.session_state.get("auto_email_to", ""),
            placeholder="recipient@company.com",
            key="sidebar_auto_email_to",
        )
        st.session_state["auto_email_to"] = auto_to.strip()

        if not auto_to.strip():
            st.warning("⚠️ Enter a recipient email to activate auto-send.")
        else:
            st.success(f"✅ Auto-send active → `{auto_to.strip()}`")

        auto_status = st.session_state.get("auto_email_status")
        if auto_status == "sending":
            st.info("📤 Sending email in background…")
        elif auto_status == "success":
            st.success("📬 Last auto-email sent successfully!")
        elif auto_status == "failed":
            st.error(f"❌ Last auto-email failed: {st.session_state.get('auto_email_error','')}")
        elif auto_status == "no_recipient":
            st.warning("⚠️ Auto-send skipped — no recipient configured.")

        if auto_status in ("success", "failed", "no_recipient"):
            if st.button("Clear Status", key="btn_clear_auto_status"):
                st.session_state["auto_email_status"] = None
                st.session_state["auto_email_error"]  = ""
                st.rerun()

    st.markdown("---")

    # --------------------------------------------------
    # Scheduled Reports Settings (sidebar)
    # --------------------------------------------------
    with st.expander("⏱️ Scheduled Reports"):
        st.caption("Run background tasks to automatically email reports at set intervals.")
        sched_cust = st.text_input("Customer Name (Leave blank for ALL customers):", key="sched_cust")
        sched_freq = st.selectbox("Frequency:", ["30 Minutes", "1 Hour", "Daily"], key="sched_freq")
        sched_email = st.text_input("Recipient Email for Schedule:", value=st.session_state.get("auto_email_to",""), key="sched_email")
        
        if st.button("▶️ Start Schedule", use_container_width=True):
            if not sched_email:
                st.error("Recipient email is required for scheduling.")
            else:
                secs = 1800 if sched_freq == "30 Minutes" else 3600 if sched_freq == "1 Hour" else 86400
                t = threading.Thread(target=scheduled_worker, args=(secs, sched_cust, sched_email), daemon=True)
                t.start()
                st.success(f"Started {sched_freq} schedule for {sched_cust if sched_cust else 'ALL Customers'}.")

    st.markdown("---")
    
    with st.expander("❓ Frequently Asked Questions (FAQ)"):
        st.info("Click any question below to ask the AI:")
        for i, question in enumerate(FAQ_DATA.keys()):
            if st.button(f"🗣️ {question}", key=f"faq_btn_{i}", use_container_width=True):
                st.session_state.faq_pending = question

    st.markdown("---")
    if st.button("🔄 Clear Chat & Start Over", use_container_width=True, key="clear_chat_sidebar"):
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

    if st.session_state.get("auto_email_enabled"):
        st.info(
            "📌 **Auto-send is ON**. Most operations will email automatically.\n\n"
            "You can still use this form to manually send the last fetched operation data."
        )
    else:
        st.info("The order data from your last operation has been automatically attached as a formatted table.")

    c = st.session_state.collected

    to_email = st.text_input(
        "To:",
        value=c.get("email_address", "") or st.session_state.get("auto_email_to", ""),
    )
    subject  = st.text_input("Subject:", value="Oracle ERP Order Details Update")
    body     = st.text_area("Message Body:", value="Please find the requested order details structured below.")

    html_preview = st.session_state.get("email_payload_html", "")
    with st.expander("Preview Data to be Sent"):
        if html_preview:
            st.markdown(html_preview, unsafe_allow_html=True)
        else:
            st.warning("No recent operation data found to attach to this email.")

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("✅ Send Email", key="btn_send_email"):
            if not to_email:
                st.error("Email address is required.")
            else:
                with st.spinner("Dispatching email..."):
                    success, msg = send_erp_email(to_email, subject, body, html_preview)
                    if success:
                        assistant_say(
                            f"✅ Email sent successfully to `{to_email}`!",
                            speak_text="The email was sent successfully."
                        )
                        st.session_state.stage = "chat"
                        st.rerun()
                    else:
                        st.error(f"Error sending email: {msg}")
    with col2:
        if st.button("🏠 Back to Chat", key="btn_email_back"):
            go_back_to_chat()

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
        if st.button("✅ Confirm Selling Price", key="btn_conf_sp"):
            val = bot.parse_numeric_value(selling_input, allow_float=True) if selling_input.strip() else None
            c["unit_selling_price"] = val if val is not None else unit_price
            assistant_say(f"✅ Selling Price set to: `${c['unit_selling_price']:.2f}`", speak_text=f"Selling price confirmed at {c['unit_selling_price']} dollars.")
            st.session_state.stage = "resolve"
            st.rerun()
    with col2:
        if st.button("🏠 Back to Chat", key="btn_sp_back"):
            go_back_to_chat()

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
            if st.button("✅ Confirm Line Type", key="btn_lt_conf"):
                idx = opts.index(choice)
                selected = rows[idx]
                st.session_state.collected["line_type_id"] = selected["line_type_id"]
                assistant_say(f"✅ Line Type: `{selected['line_type_name']}` (ID: {selected['line_type_id']})", speak_text=f"Line type confirmed as {selected['line_type_name']}")
                st.session_state.stage = "resolve"
                st.rerun()
        with col2:
            if len(rows) >= bot.MAX_CHOICES:
                if st.button("📑 Next Page", key="btn_lt_next"):
                    st.session_state.offsets["line_type"] += bot.MAX_CHOICES
                    st.session_state.line_type_rows = bot.get_line_type_rows(offset=st.session_state.offsets["line_type"])
                    st.rerun()
        with col3:
            if st.session_state.offsets.get("line_type", 0) > 0:
                if st.button("⬅️ Previous Page", key="btn_lt_prev"):
                    st.session_state.offsets["line_type"] = max(0, st.session_state.offsets["line_type"] - bot.MAX_CHOICES)
                    st.session_state.line_type_rows = bot.get_line_type_rows(offset=st.session_state.offsets["line_type"])
                    st.rerun()
        with col4:
            if st.button("🏠 Back to Chat", key="btn_lt_back_1"):
                go_back_to_chat()
    else:
        st.warning("No line types found. Enter a Line Type ID manually:")
        lt_input = st.text_input("Line Type ID:", key="line_type_manual_input")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Line Type", key="btn_lt_man_conf"):
                val = bot.parse_numeric_value(lt_input)
                if val is not None:
                    st.session_state.collected["line_type_id"] = val
                    assistant_say(f"✅ Line Type ID set to: `{val}`", speak_text="Line type confirmed.")
                    st.session_state.stage = "resolve"
                    st.rerun()
                else:
                    st.error("Please enter a valid numeric ID.")
        with col2:
            if st.button("🏠 Back to Chat", key="btn_lt_back_2"):
                go_back_to_chat()

elif stage == "select_customer":
    st.markdown("### 🔍 Select Customer")
    search_val = st.text_input("Search customer by name:", value=st.session_state.collected.get("customer_name") or "", key="customer_search_input")
    if st.button("🔍 Search", key="btn_cust_search"):
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
            if st.button("✅ Confirm Customer", key="btn_cust_conf"):
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
                if st.button("📑 Next Page", key="btn_cust_next"):
                    st.session_state.offsets["customer"] += bot.MAX_CHOICES
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(name, offset=st.session_state.offsets["customer"])
                    st.rerun()
        with col3:
            if st.session_state.offsets["customer"] > 0:
                if st.button("⬅️ Prev Page", key="btn_cust_prev"):
                    st.session_state.offsets["customer"] = max(0, st.session_state.offsets["customer"] - bot.MAX_CHOICES)
                    name = st.session_state.collected.get("customer_name", "")
                    st.session_state.customer_rows = bot.get_customer_by_name_rows(name, offset=st.session_state.offsets["customer"])
                    st.rerun()
        with col4:
            if st.button("🏠 Back to Chat", key="btn_cust_back_1"):
                go_back_to_chat()
    else:
        st.info("Use the search box above to find customers.")
        if st.button("🏠 Back to Chat", key="btn_cust_back_2"):
            go_back_to_chat()

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
            if st.button("✅ Confirm Customer", key="btn_cbi_conf"):
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
                if st.button("📑 Next Page", key="btn_cbi_next"):
                    st.session_state.offsets["customer_by_item"] += bot.MAX_CHOICES
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=st.session_state.offsets["customer_by_item"])
                    st.rerun()
        with col3:
            if st.session_state.offsets["customer_by_item"] > 0:
                if st.button("⬅️ Prev Page", key="btn_cbi_prev"):
                    st.session_state.offsets["customer_by_item"] = max(0, st.session_state.offsets["customer_by_item"] - bot.MAX_CHOICES)
                    st.session_state.customer_by_item_rows = bot.get_customers_by_inventory_item_rows(c["inventory_item_id"], offset=st.session_state.offsets["customer_by_item"])
                    st.rerun()
        with col4:
            if st.button("🔍 Search by Name Instead", key="btn_cbi_search"):
                st.session_state.customer_rows, st.session_state.stage = [], "select_customer"
                st.rerun()
        with col5:
            if st.button("🏠 Back to Chat", key="btn_cbi_back_1"):
                go_back_to_chat()
    else:
        st.warning("No customers found for this item. Try searching by name.")
        if st.button("🔍 Search by Name", key="btn_cbi_search_2"):
            st.session_state.customer_rows, st.session_state.stage = [], "select_customer"
            st.rerun()
        if st.button("🏠 Back to Chat", key="btn_cbi_back_2"):
            go_back_to_chat()

elif stage == "select_site":
    def confirm_site(row):
        st.session_state.collected["sold_to_org_id"] = row["sold_to_org_id"]
        st.session_state.collected["ship_to_org_id"] = row["ship_to_org_id"]
        st.session_state.collected["customer_name"]  = row["customer_name"]
        assistant_say(
            f"✅ Customer: `{row['customer_name']}`  | Sold-to: `{row['sold_to_org_id']}`  | Ship-to: `{row['ship_to_org_id']}`",
            speak_text="Customer shipping site confirmed."
        )

    render_selection_ui("Customer Site", "site_rows", "site", lambda r: f"Customer={r['customer_name']}  [{r['location']}] {r['address']}  (SoldTo={r['sold_to_org_id']} | ShipTo={r['ship_to_org_id']})", confirm_site)

# ==================================================
# ==================================================
# STAGE: order_details_by_customer
# ==================================================
elif stage == "order_details_by_customer":
    st.markdown("## 🔎 Order Details by Customer")
    st.info("Enter a customer name (exact match, as stored in Oracle HZ_PARTIES) to retrieve all order lines.")

    auto_status = st.session_state.get("auto_email_status")
    auto_to     = st.session_state.get("auto_email_to", "")
    if st.session_state.get("auto_email_enabled"):
        if auto_status == "sending":
            st.info(f"📤 Auto-sending email to **{auto_to}** in background…")
        elif auto_status == "success":
            st.success(f"📬 Email automatically sent to **{auto_to}** after data load!")
        elif auto_status == "failed":
            err = st.session_state.get("auto_email_error", "")
            st.error(f"❌ Auto-email failed to **{auto_to}**: {err}")
            if st.button("🔁 Retry Auto Email", key="btn_retry_auto"):
                html_payload  = st.session_state.get("email_payload_html", "")
                customer_name = st.session_state.get("order_details_customer_name", "")
                st.session_state["auto_email_status"] = None
                trigger_auto_email(f"Customer: {customer_name}", html_payload)
                st.rerun()
        elif auto_status == "no_recipient":
            st.warning("⚠️ Auto-send skipped — no recipient email configured. Set one in the sidebar.")
    else:
        st.caption("ℹ️ Auto-send is OFF. Use 'Send email to …' command to email results manually.")

    st.markdown("---")

    cname_input = st.text_input(
        "Customer Name:",
        value=st.session_state.get("order_details_customer_name") or "",
        placeholder="e.g. ACME CORPORATION",
        key="od_customer_name_input",
    )

    col_search, _ = st.columns([1, 5])
    with col_search:
        search_clicked = st.button("🔍 Fetch Order Details", key="btn_od_fetch")

    if search_clicked:
        if not cname_input.strip():
            st.error("Please enter a customer name before searching.")
        else:
            st.session_state["auto_email_status"] = None
            st.session_state["auto_email_error"]  = ""

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

                        html_payload = generate_customer_html(rows, cname_input.strip(), ai_summary)
                        st.session_state.email_payload_html = html_payload

                        assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

                        if st.session_state.get("auto_email_enabled"):
                            trigger_auto_email(f"Customer: {cname_input.strip()}", html_payload)
                            to_addr = st.session_state.get("auto_email_to", "")
                            if to_addr:
                                assistant_say(
                                    f"📤 Auto-sending order report to **{to_addr}** in the background…",
                                    speak_text=f"Sending email to {to_addr} automatically.",
                                    mute=False,
                                )
                            else:
                                assistant_say(
                                    "⚠️ Auto-send is ON but no recipient email is set in the sidebar. "
                                    "Please add one to activate automatic delivery.",
                                    speak_text="Auto-send is on but no recipient is configured.",
                                )

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

    rows         = st.session_state.get("order_details_rows", [])
    customer_name = st.session_state.get("order_details_customer_name", "")
    if rows and customer_name:
        st.markdown(f"### 📦 Results for: `{customer_name}`")
        st.markdown("---")
        _display_order_details_table(rows, customer_name)

        st.markdown("---")

        col_another, col_resend = st.columns([1, 1])
        with col_another:
            if st.button("🔍 Search Another Customer", key="btn_od_another"):
                st.session_state.order_details_rows            = []
                st.session_state.order_details_customer_name   = None
                st.session_state.order_details_page            = 0
                st.session_state["auto_email_status"]          = None
                st.rerun()
        with col_resend:
            if st.button("📧 Send Email Manually", key="btn_od_manual_email"):
                st.session_state.stage = "send_email_flow"
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🏠 Back to Chat", key="btn_od_back"):
        go_back_to_chat()

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
                    go_back_to_chat()
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
                    go_back_to_chat()
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
                    go_back_to_chat()
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
                    go_back_to_chat()
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
                        assistant_say("⚠️ No active SHIP_TO sites for this customer. Please choose a different customer.")
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
                    go_back_to_chat()

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
        if st.button("✅ Submit Order", key="btn_conf_submit"):
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
                    
                    st.session_state.email_payload_html = generate_order_html(result, ai_summary)
                    assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

                    if st.session_state.get("auto_email_enabled"):
                        trigger_auto_email(f"New Order Created", st.session_state.email_payload_html)

                    st.session_state.stage = "done"
                    st.session_state.add_line_return = "done"
                    st.rerun()
                except Exception as e:
                    assistant_say(f"❌ Submit Error: {e}", speak_text="There was an error submitting the order.")
                    st.session_state.stage = "error"
                    st.rerun()
    with col2:
        if st.button("🏠 Back to Chat", key="btn_conf_back"):
            go_back_to_chat()

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
            if st.button("➕ Add a Line", key="btn_done_add"):
                st.session_state.add_line_stage, st.session_state.add_line_data = "add_line_item", {}
                st.session_state.add_line_item_rows, st.session_state.add_line_price_rows, st.session_state.add_line_term_rows = [], [], []
                st.session_state.offsets["item"], st.session_state.offsets["price"], st.session_state.offsets["term"] = 0, 0, 0
                st.session_state.stage, st.session_state.add_line_return = "add_line_flow", "done"
                st.rerun()
        with col_new:
            if st.button("🏠 Back to Chat", key="btn_done_back_1"):
                go_back_to_chat()
    else:
        if st.button("🏠 Back to Chat", key="btn_done_back_2"):
            go_back_to_chat()

# ==================================================
# STAGE: show_get_order
# ==================================================
elif stage == "show_get_order":
    result = st.session_state.get("api_result", {})

    if isinstance(result, dict) and "total_count" in result:
        rows     = result.get("rows", [])
        col_names = result.get("columns", [])
        if rows:
            if col_names and isinstance(rows[0], (list, tuple)):
                df = pd.DataFrame(rows, columns=col_names)
            elif isinstance(rows[0], dict):
                df = pd.DataFrame(rows)
            else:
                try:
                    df = pd.DataFrame(rows, columns=["Order Number", "Status", "Creation Date"][:len(rows[0])])
                except Exception:
                    df = pd.DataFrame(rows)
        else:
            df = pd.DataFrame()
        st.markdown(f"**{result['total_count']}** orders found.")
        st.dataframe(df, use_container_width=True, hide_index=True)
        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv_bytes, file_name="search_results.csv", mime="text/csv")
        st.markdown("---")
        if st.button("🏠 Back to Chat", key="btn_sgo_back_1"):
            go_back_to_chat()
    else:
        display_erp_response(result, context_label="Retrieved Order")
        st.markdown("---")

        header_id, order_number = st.session_state.get("add_line_header_id"), st.session_state.get("add_line_order_number")

        if header_id and order_number:
            st.markdown(f"### ➕ Add a Line to Order #{order_number}?")
            col_add, col_new = st.columns(2)
            with col_add:
                if st.button("➕ Add a Line", key="btn_sgo_add"):
                    st.session_state.add_line_stage, st.session_state.add_line_data = "add_line_item", {}
                    st.session_state.add_line_item_rows, st.session_state.add_line_price_rows, st.session_state.add_line_term_rows = [], [], []
                    st.session_state.offsets["item"], st.session_state.offsets["price"], st.session_state.offsets["term"] = 0, 0, 0
                    st.session_state.stage, st.session_state.add_line_return = "add_line_flow", "show_get_order"
                    st.rerun()
            with col_new:
                if st.button("🏠 Back to Chat", key="btn_sgo_back_2"):
                    go_back_to_chat()
        else:
            if st.button("🏠 Back to Chat", key="btn_sgo_back_3"):
                go_back_to_chat()

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
            if st.button("🔍 Search Items", key="btn_al_search"):
                offs["item"] = 0
                st.session_state.add_line_item_rows = bot.get_inventory_item_rows(item_search, offset=0)
                st.rerun()
        with col2:
            if st.button("❌ Cancel Line Addition", key="btn_al_can_1"):
                st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                st.rerun()

        rows = st.session_state.add_line_item_rows
        if rows:
            opts = [f"[{i+1}] {r['segment1']}  {r['description']}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Item:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Item", key="btn_al_ci"):
                    idx = opts.index(choice)
                    ald["inventory_item_id"], ald["ordered_item"] = rows[idx]["inventory_item_id"], rows[idx]["segment1"]
                    st.session_state.add_line_stage = "add_line_qty"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next", key="btn_al_in"):
                        offs["item"] += bot.MAX_CHOICES
                        st.session_state.add_line_item_rows = bot.get_inventory_item_rows(item_search, offset=offs["item"])
                        st.rerun()

    elif sub == "add_line_qty":
        st.markdown(f"**Item:** `{ald.get('ordered_item')}`")
        qty_input = st.text_input("Enter Quantity:", key="add_line_qty_input")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Quantity", key="btn_al_cq"):
                qty = bot.parse_numeric_value(qty_input, allow_float=True)
                if qty is None: st.error("Invalid quantity. Please enter a number.")
                else:
                    ald["quantity"] = qty
                    st.session_state.add_line_price_rows = bot.get_price_details_rows(ald["ordered_item"], qty, ald["inventory_item_id"], offset=0)
                    offs["price"], st.session_state.add_line_stage = 0, "add_line_price"
                    st.rerun()
        with col2:
            if st.button("❌ Cancel Line Addition", key="btn_al_can_2"):
                st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                st.rerun()

    elif sub == "add_line_price":
        st.markdown(f"**Item:** `{ald.get('ordered_item')}`  |  **Qty:** `{ald.get('quantity')}`")
        rows = st.session_state.add_line_price_rows
        if not rows:
            st.warning("No price lists found for this item.")
            if st.button("⬅️ Back to Item", key="btn_al_bi"):
                st.session_state.add_line_stage = "add_line_item"
                st.rerun()
        else:
            opts = [f"[{i+1}] {r['price_list_name']}  ${r['unit_list_price']:.2f}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Price List:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Price", key="btn_al_cp"):
                    idx = opts.index(choice)
                    ald["price_list_id"], ald["unit_list_price"], ald["unit_selling_price"] = rows[idx]["price_list_id"], rows[idx]["unit_list_price"], rows[idx]["unit_list_price"]
                    st.session_state.add_line_stage = "add_line_selling_price"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next", key="btn_al_pn"):
                        offs["price"] += bot.MAX_CHOICES
                        st.session_state.add_line_price_rows = bot.get_price_details_rows(ald["ordered_item"], ald["quantity"], ald["inventory_item_id"], offset=offs["price"])
                        st.rerun()

    elif sub == "add_line_selling_price":
        unit_price = ald.get("unit_list_price", 0.0)
        st.markdown(f"**Unit List Price:** `${unit_price:.2f}`")
        sp_input = st.text_input("Selling Price (leave blank to use list price):", key="add_line_sp")
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("✅ Confirm Selling Price", key="btn_al_csp"):
                val = bot.parse_numeric_value(sp_input, allow_float=True) if sp_input.strip() else None
                ald["unit_selling_price"] = val if val is not None else unit_price
                st.session_state.add_line_term_rows = bot.get_payment_term_rows(offset=0)
                offs["term"], st.session_state.add_line_stage = 0, "add_line_term"
                st.rerun()

    elif sub == "add_line_term":
        rows = st.session_state.add_line_term_rows
        if not rows:
            st.warning("No payment terms found.")
            if st.button("⬅️ Back", key="btn_al_bt"):
                st.session_state.add_line_stage = "add_line_selling_price"
                st.rerun()
        else:
            opts = [f"[{i+1}] {r['term_name']}" for i, r in enumerate(rows)]
            choice = st.radio("**Select Payment Term:**", opts)
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                if st.button("✅ Confirm Term", key="btn_al_ct"):
                    idx = opts.index(choice)
                    ald["payment_term_id"] = rows[idx]["term_id"]
                    if hasattr(bot, 'get_line_type_rows'):
                        st.session_state.add_line_stage = "add_line_line_type"
                    else:
                        st.session_state.add_line_stage = "add_line_submit"
                    st.rerun()
            with c2:
                if len(rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next", key="btn_al_tn"):
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
                if st.button("✅ Confirm Line Type", key="btn_al_clt"):
                    idx = lt_opts.index(lt_choice)
                    ald["line_type_id"] = lt_rows[idx]["line_type_id"]
                    st.session_state.add_line_stage = "add_line_submit"
                    st.rerun()
            with c2:
                if len(lt_rows) >= bot.MAX_CHOICES:
                    if st.button("📑 Next", key="btn_al_ln"):
                        offs["line_type"] = offs.get("line_type", 0) + bot.MAX_CHOICES
                        st.session_state.add_line_lt_rows = bot.get_line_type_rows(offset=offs["line_type"])
                        st.rerun()
            with c3:
                if offs.get("line_type", 0) > 0:
                    if st.button("⬅️ Prev", key="btn_al_lp"):
                        offs["line_type"] = max(0, offs.get("line_type", 0) - bot.MAX_CHOICES)
                        st.session_state.add_line_lt_rows = bot.get_line_type_rows(offset=offs["line_type"])
                        st.rerun()
            with c4:
                if st.button("❌ Cancel Line Addition", key="btn_al_can_3"):
                    st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                    st.rerun()
        else:
            st.warning("No line types found. Enter manually:")
            lt_input = st.text_input("Enter Line Type ID:", key="add_line_lt")
            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("✅ Confirm Line Type", key="btn_al_cmlt"):
                    val = bot.parse_numeric_value(lt_input)
                    if val is not None:
                        ald["line_type_id"] = val
                        st.session_state.add_line_stage = "add_line_submit"
                        st.rerun()
                    else: st.error("Please enter a valid numeric ID.")
            with col2:
                if st.button("❌ Cancel Line Addition", key="btn_al_can_4"):
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
            if st.button("✅ Submit Line", key="btn_al_sl"):
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

                        st.session_state.email_payload_html = generate_order_html(result, ai_summary)
                        assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

                        if st.session_state.get("auto_email_enabled"):
                            trigger_auto_email(f"Updated Order #{order_number}", st.session_state.email_payload_html)

                        st.session_state.add_line_stage, st.session_state.add_line_data, st.session_state.stage = None, {}, "done"
                        st.rerun()
                    except Exception as e:
                        assistant_say(f"❌ Failed to add line: {e}", speak_text="Failed to add line.")
                        st.session_state.stage = "error"
                        st.rerun()
        with col2:
            if st.button("❌ Cancel Line Addition", key="btn_al_can_5"):
                st.session_state.add_line_stage, st.session_state.stage = None, return_stage
                st.rerun()

# ==================================================
# STAGE: show_advanced_search 
# ==================================================
elif stage == "show_advanced_search":
    res = st.session_state.get("api_result", {})
    rows        = res.get("rows", [])
    total_count = res.get("total_count", 0)
    col_names   = res.get("columns", [])

    st.markdown("## 🔍 Advanced Order Search Results")
    st.markdown(f"**{total_count}** order(s) matched your search filters.")
    st.markdown("---")

    if rows:
        if col_names and isinstance(rows[0], (list, tuple)):
            df = pd.DataFrame(rows, columns=col_names)
        elif isinstance(rows[0], dict):
            df = pd.DataFrame(rows)
        else:
            expected = ["Order Number", "Status", "Creation Date"]
            try:
                df = pd.DataFrame(rows, columns=expected[:len(rows[0])])
            except Exception:
                df = pd.DataFrame(rows)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Orders", total_count)
        m2.metric("Showing",      len(df))

        status_col = next((c for c in df.columns if "status" in c.lower()), None)
        if status_col:
            m3.metric("Unique Statuses", df[status_col].nunique())
        else:
            m3.metric("Columns", len(df.columns))

        date_col = next((c for c in df.columns if "date" in c.lower() or "ordered" in c.lower()), None)
        if date_col:
            m4.metric("Date Column", date_col)
        else:
            m4.metric("Rows", len(df))

        st.markdown("---")

        if status_col and df[status_col].nunique() > 1:
            statuses = ["All"] + sorted(df[status_col].dropna().unique().tolist())
            sel_status = st.selectbox("Filter by Status:", statuses, key="adv_status_filter")
            if sel_status != "All":
                df = df[df[status_col] == sel_status]

        adv_page     = st.session_state.get("adv_search_page", 0)
        rows_per_pg  = 50
        start        = adv_page * rows_per_pg
        end          = min(start + rows_per_pg, len(df))
        st.markdown(f"Showing rows **{start+1}–{end}** of **{len(df)}**")
        st.dataframe(df.iloc[start:end], use_container_width=True, hide_index=True)

        pc1, pc2, pc3 = st.columns([1, 2, 1])
        with pc1:
            if adv_page > 0:
                if st.button("⬅️ Previous", key="adv_prev"):
                    st.session_state.adv_search_page = adv_page - 1
                    st.rerun()
        with pc3:
            if end < len(df):
                if st.button("Next ➡️", key="adv_next"):
                    st.session_state.adv_search_page = adv_page + 1
                    st.rerun()

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Results as CSV",
            data=csv_bytes,
            file_name="advanced_search_results.csv",
            mime="text/csv",
        )

    else:
        st.info("No rows to display.")

    st.markdown("---")
    col_email, col_back = st.columns([1, 4])
    with col_email:
        if st.button("📧 Email Results", key="btn_adv_email"):
            st.session_state.stage = "send_email_flow"
            st.rerun()
    with col_back:
        if st.button("🏠 Back to Chat", key="btn_adv_back"):
            st.session_state.adv_search_page = 0
            go_back_to_chat()


# ==================================================
# STAGE: fetch_get_order
# ==================================================
elif stage == "fetch_get_order":
    with st.spinner(f"⏳ Retrieving Order {st.session_state.get_order_num}..."):
        try:
            result = bot.get_order(st.session_state.get_order_num)
            
            parsed_data = extract_erp_details(result)
            ai_summary = generate_ai_summary("Retrieve Specific Order", parsed_data)
            
            st.session_state.email_payload_html = generate_order_html(result, ai_summary)
            assistant_say(f"✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

            if st.session_state.get("auto_email_enabled"):
                trigger_auto_email(f"Order #{st.session_state.get_order_num}", st.session_state.email_payload_html)

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
    if st.button("🏠 Back to Chat", key="btn_err_back"):
        go_back_to_chat()

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
        st.warning("Canceling operation and returning to chat...")
        go_back_to_chat()

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
    # Intercept & Smart Intent Extraction
    # --------------------------------------------------
    with st.spinner("🧠 Understanding intent..."):
        smart_extracted = get_smart_intent(st.session_state.messages, prompt)
    
    extracted = bot.github_extract_intent(prompt) if hasattr(bot, 'github_extract_intent') else {}

    # Smart Extracted fields overwrite standard regex fields
    for k, v in smart_extracted.items():
        if v is not None and str(v).strip() != "":
            extracted[k] = v

    # --------------------------------------------------
    # Step A: Simple regex/rule fallbacks on raw prompt
    # --------------------------------------------------
    prompt_lower = prompt.lower()
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', prompt)

    if "email" in prompt_lower or "mail" in prompt_lower or "send" in prompt_lower:
        if not extracted.get("action") or extracted.get("action") == "unknown":
            extracted["action"] = "email"
        if email_match:
            extracted["email_address"] = email_match.group(0)

    if not extracted.get("year"):
        year_match = re.search(r'\b(20\d{2})\b', prompt)
        if year_match:
            extracted["year"] = int(year_match.group(1))

    if not extracted.get("status"):
        status_keywords = {
            "booked":    "BOOKED",
            "entered":   "ENTERED",
            "cancelled": "CANCELLED",
            "canceled":  "CANCELLED",
            "shipped":   "SHIPPED",
            "closed":    "CLOSED",
            "pending":   "ENTERED",
            "open":      "BOOKED",
            "invoiced":  "INVOICED",
            "delivered": "DELIVERED",
        }
        for kw, val in status_keywords.items():
            if kw in prompt_lower:
                extracted["status"] = val
                break

    if not extracted.get("date_range"):
        date_range_patterns = [
            (r'last\s+month',   'last month'),
            (r'last\s+quarter', 'last quarter'),
            (r'last\s+week',    'last week'),
            (r'this\s+month',   'this month'),
            (r'this\s+quarter', 'this quarter'),
            (r'this\s+week',    'this week'),
            (r'last\s+30\s+days', 'last 30 days'),
            (r'last\s+90\s+days', 'last 90 days'),
            (r'last\s+year',    'last year'),
            (r'ytd|year\s+to\s+date', 'year to date'),
        ]
        for pattern, label in date_range_patterns:
            if re.search(pattern, prompt_lower):
                extracted["date_range"] = label
                break

    # --------------------------------------------------
    # Step B: Determine final action with correct priority
    # --------------------------------------------------

    if "create" in prompt_lower or "new order" in prompt_lower:
        extracted["action"] = "create"

    od_customer_match = re.search(
        r'order\s+details?\s+(?:for|by|of)?\s+(?:customer\s+)?(.+)',
        prompt_lower
    )
    if od_customer_match or ("order details" in prompt_lower and "customer" in prompt_lower):
        extracted["action"] = "order_details"

    has_specific_order = bool(extracted.get("order_number") or st.session_state.collected.get("order_number"))
    has_search_filters = bool(
        extracted.get("year") or
        extracted.get("date_range") or
        extracted.get("status")
    )
    if has_search_filters and not has_specific_order and extracted.get("action") not in ["create", "order_details", "email"]:
        extracted["action"] = "search"

    if extracted.get("action") not in ["create", "search", "order_details", "email"]:
        if any(w in prompt_lower for w in ["get", "find", "search", "show", "fetch", "retrieve"]):
            if not extracted.get("action") or extracted.get("action") == "unknown":
                extracted["action"] = "get"

    action = extracted.get("action", "unknown")
    merge_fields(extracted)

    # --------------------------------------------------
    # Step C: Route to order_details_by_customer stage
    # --------------------------------------------------
    if action == "order_details" or (od_customer_match and action not in ["create", "email"]):
        name_match = re.search(
            r'order\s+details?\s+(?:for|by|of)?\s+(?:customer\s+)?(.+)',
            prompt, re.IGNORECASE
        )
        if name_match:
            st.session_state.order_details_customer_name = name_match.group(1).strip()
        elif extracted.get("customer_name"):
            st.session_state.order_details_customer_name = extracted.get("customer_name")

        st.session_state.order_details_rows = []
        st.session_state.order_details_page = 0
        st.session_state.stage = "order_details_by_customer"
        assistant_say(
            "🔎 Opening order details search for customer orders...",
            speak_text="Opening order details search."
        )
        st.rerun()

    # --------------------------------------------------
    # Step D: Dispatch to correct handler
    # --------------------------------------------------

    if action == "email" or st.session_state.action == "email":
        st.session_state.action = "email"
        st.session_state.stage = "send_email_flow"
        assistant_say("Preparing email draft. Please verify the details above.", speak_text="Preparing email draft.")
        st.rerun()

    elif action == "search":
        adv_year       = extracted.get("year")
        adv_date_range = extracted.get("date_range")
        adv_status     = extracted.get("status")

        confirm_msg = "🔍 Searching orders"
        parts = []
        if adv_year:       parts.append(f"year **{adv_year}**")
        if adv_date_range: parts.append(f"range **{adv_date_range}**")
        if adv_status:     parts.append(f"status **{adv_status}**")
        if parts:          confirm_msg += " for " + ", ".join(parts)
        confirm_msg += "..."

        assistant_say(confirm_msg, speak_text=clean_text_for_speech(confirm_msg))

        with st.spinner("⏳ Searching database..."):
            try:
                res = bot.get_orders_advanced(adv_date_range, adv_year, adv_status)

                if not res or not isinstance(res, dict):
                    assistant_say("⚠️ No results returned from the search. Try different filters.", speak_text="No results found.")
                    st.rerun()

                total = res.get("total_count", 0)
                rows  = res.get("rows", [])

                if total == 0 or not rows:
                    no_res_msg = (
                        f"ℹ️ No orders found"
                        + (f" for year **{adv_year}**" if adv_year else "")
                        + (f" with status **{adv_status}**" if adv_status else "")
                        + (f" in range **{adv_date_range}**" if adv_date_range else "")
                        + ". Try broadening your search."
                    )
                    assistant_say(no_res_msg, speak_text="No orders found. Try broadening your search.")
                    st.rerun()

                summary_context = {
                    "total_found": total,
                    "filters_used": {"year": adv_year, "date_range": adv_date_range, "status": adv_status},
                    "first_5_rows": rows[:5]
                }
                ai_summary = generate_ai_summary("Advanced Order Search", summary_context)

                st.session_state.email_payload_html = generate_search_html(res, ai_summary)
                assistant_say(f"✅ Found **{total}** order(s).\n\n✨ **AI Summary:**\n{ai_summary}", speak_text=ai_summary)

                if st.session_state.get("auto_email_enabled"):
                    trigger_auto_email("Advanced Search", st.session_state.email_payload_html)

                st.session_state.api_result = res
                st.session_state.stage = "show_advanced_search"
                st.rerun()

            except Exception as e:
                assistant_say(f"❌ Search Error: {str(e)}\n\nPlease check the filters and try again.", speak_text="There was an error during the search.")
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

    else:
        fallback = bot.github_clarify(
            st.session_state.gh_history,
            ["action: 'create a new order', 'get order by number', 'search orders by year/status/date range', or 'order details for customer <name>'"]
        )
        assistant_say(fallback, speak_text=clean_text_for_speech(fallback))
        gh_add("assistant", fallback)
        st.rerun()