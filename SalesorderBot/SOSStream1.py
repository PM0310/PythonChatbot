import streamlit as st
import SOSStream as bot  # Ensure your backend file is named SalesOrderChatandVoiceBot.py
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

# --- IMPORTANT: Threading Control for Streamlit ---
@st.cache_resource
def get_schedule_event():
    return threading.Event()

stop_schedule_event = get_schedule_event()

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
# HTML Generation & Email Helpers
# --------------------------------------------------
def generate_search_html(res: list, ai_summary: str) -> str:
    """Generate HTML table from search results."""
    if not res:
        return "<p>No results found.</p>"
    df = pd.DataFrame(res)
    html = f"<p><strong>Summary:</strong> {ai_summary}</p>"
    html += df.to_html(index=False, border=1)
    return html

def generate_customer_html(rows: list, customer_name: str, ai_summary: str) -> str:
    """Generate HTML table for customer order details."""
    if not rows:
        return "<p>No orders found for this customer.</p>"
    df = pd.DataFrame(rows)
    html = f"<p><strong>Customer:</strong> {customer_name}</p>"
    html += f"<p><strong>Summary:</strong> {ai_summary}</p>"
    html += df.to_html(index=False, border=1)
    return html

def get_order_details_by_customer(customer_name: str) -> list:
    """Retrieve order details for a specific customer."""
    try:
        return bot.get_order_details_by_customer(customer_name)
    except Exception:
        return []

def send_erp_email(to_email: str, subject: str, body: str, html_content: str):
    """Send email with HTML content."""
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = bot.EMAIL_FROM
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        msg.attach(MIMEText(html_content, 'html'))
        
        with smtplib.SMTP(bot.SMTP_SERVER, bot.SMTP_PORT) as server:
            server.starttls()
            server.login(bot.SMTP_USER, bot.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"Email send error: {e}")

# --------------------------------------------------
# Background Scheduler Logic
# --------------------------------------------------
def scheduled_worker(interval_secs: int, customer_name: str, to_email: str):
    """Background thread that executes the fetch and email continuously."""
    print(f"\n  ⏱️  [Scheduler active: {interval_secs/60} mins | Target: {customer_name or 'ALL'} | Email: {to_email}]")
    
    stop_schedule_event.clear()
    
    while not stop_schedule_event.is_set():
        stopped_early = stop_schedule_event.wait(timeout=interval_secs)
        
        if stopped_early:
            print("\n  🛑  [Scheduler has been explicitly stopped]")
            break
            
        try:
            if not customer_name or customer_name.lower() in ["all", "all customers", "everyone"]:
                res = bot.get_orders_advanced(None, None, None)
                ai_summary = "Automated scheduled report summarizing all recent orders."
                html_payload = generate_search_html(res, ai_summary)
                send_erp_email(to_email, "Scheduled Report: All Orders", "Your automated report is attached below.", html_payload)
            else:
                rows = get_order_details_by_customer(customer_name)
                if rows:
                    ai_summary = f"Automated scheduled report summarizing recent activity for {customer_name}."
                    html_payload = generate_customer_html(rows, customer_name, ai_summary)
                    send_erp_email(to_email, f"Scheduled Report: {customer_name}", "Your automated report is attached below.", html_payload)
        except Exception as e:
            print(f"\n  ⚠️  [Scheduler Error: {e}]")

def start_schedule_thread(interval_str: str, cust_name: str, to_email: str):
    mins = 1440 
    interval_lower = interval_str.lower()
    
    if "30" in interval_lower and "min" in interval_lower: mins = 30
    elif "1" in interval_lower and "hour" in interval_lower: mins = 60
    elif "daily" in interval_lower or "day" in interval_lower: mins = 1440
    else:
        nums = re.findall(r'\d+', interval_lower)
        if nums and "min" in interval_lower:
            mins = int(nums[0])
        elif nums and "hour" in interval_lower:
            mins = int(nums[0]) * 60
            
    secs = mins * 60
    t = threading.Thread(target=scheduled_worker, args=(secs, cust_name, to_email), daemon=True)
    t.start()

# --------------------------------------------------
# Smart Context Aware AI Functions
# --------------------------------------------------
def get_smart_intent(history: list, prompt: str, current_action: str) -> dict:
    """Uses OpenAI to extract intents & parameters from the full conversational context."""
    try:
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=bot.GITHUB_TOKEN,
        )
        history_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history[-6:]])
        current_year = datetime.datetime.now().year
        
        system_prompt = f"""You are an ERP intent extraction engine. 
Current ongoing action in the session: '{current_action}'. (If None, infer from user prompt).

Possible actions to return: 'create' (create order), 'get' (retrieve specific order by number), 'search' (find multiple orders by date/status), 'email' (send email), 'order_details' (customer order history), 'schedule' (automated report), 'stop_schedule' (stop or cancel an automated report schedule), or 'unknown'.

RULES:
1. If the user provides a number or value answering a previous bot question, ASSUME the action remains '{current_action}'.
2. CRITICAL: Convert ANY spoken word numbers into digits (e.g., "sixty four thousand four hundred sixty" -> 64460). Do not leave them as text.
3. If the user gives a specific 5 or 6 digit number (e.g., 64460), extract it as 'order_number' and set action to 'get' (unless current_action is 'create').
4. The current year is {current_year}. If the user asks for orders from 'last year', output {current_year - 1} for the year. If they say 'this year', output {current_year}.
5. If the user wants to cancel or stop a schedule, set action to 'stop_schedule'.

Extract any of these keys if present:
- 'order_number' (integer)
- 'customer_name' (string)
- 'cpo' (string)
- 'ordered_item' (string)
- 'quantity' (number)
- 'line_type_id' (number)
- 'email_address' (string)
- 'year' (integer)
- 'status' (string)
- 'date_range' (string)

Respond ONLY with a valid JSON object."""

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
        
        return json.loads(content)
    except Exception as e:
        print(f"⚠️  [Smart Intent Error: {e}]")
        return {"action": "unknown"}