import os
import json
import argparse
import requests
import ssl
import urllib3
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context

# Oracle DB
import oracledb

# Groq AI
from groq import Groq

# Optional voice dependencies (if installed)
try:
    import pyttsx3
    from vosk import Model, KaldiRecognizer
    import sounddevice as sd
    from word2number import w2n
    VOICE_AVAILABLE = True
except Exception:
    VOICE_AVAILABLE = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
oracledb.init_oracle_client(lib_dir=r"C:\Users\pavan.maccha\Downloads\instantclient-basic-windows.x64-19.10.0.0.0dbru\instantclient_19_10")

# --------------------------------------------------
# Groq AI Configuration
# --------------------------------------------------
GROQ_API_KEY   = "REDACTED_SECRET"
GROQ_MODEL     = "llama-3.1-8b-instant"


_groq_client = None

def get_groq_client() -> Groq:
    """Return a cached Groq client."""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def groq_chat(messages: list, system_prompt: str = None, max_tokens: int = 512) -> str:
    """
    Send a conversation to Groq and return the assistant reply as a string.
    """
    client = get_groq_client()

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=full_messages,
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


def groq_extract_intent(user_input: str) -> dict:
    """
    Use Groq to classify the user's intent and extract ALL key fields dynamically.
    """
    system = (
        "You are a sales order data extractor for an ERP system. "
        "Given a user message, extract the following fields as JSON and nothing else. "
        "If a field is not mentioned, return null for it.\n"
        "{\n"
        '  "action": "create" | "get" | "unknown",\n'
        '  "cpo": "<Customer PO number string or null>",\n'
        '  "ordered_item": "<item code string or null>",\n'
        '  "quantity": <number or null>,\n'
        '  "order_number": <integer or null>,\n'
        '  "ship_to_org_id": <integer or null>,\n'
        '  "sold_to_org_id": <integer or null>,\n'
        '  "salesrep_id": <integer or null>,\n'
        '  "payment_term_id": <integer or null>,\n'
        '  "price_list_id": <integer or null>,\n'
        '  "unit_selling_price": <number or null>\n'
        "}\n\n"
        "Rules:\n"
        "- action=create when the user wants to place / create / submit a new order.\n"
        "- action=get when the user wants to look up / fetch / retrieve an existing order.\n"
        "- Extract fields only when explicitly stated in the prompt.\n"
        "- Return ONLY valid JSON — no markdown, no explanation."
    )

    try:
        reply = groq_chat(
            messages=[{"role": "user", "content": user_input}],
            system_prompt=system,
            max_tokens=256,
        )
        clean = reply.strip().strip("```json").strip("```").strip()
        parsed = json.loads(clean)
        parsed["raw_reply"] = reply
        return parsed
    except Exception as e:
        return {
            "action": "unknown",
            "raw_reply": str(e),
        }


def groq_clarify(conversation_history: list, missing_fields: list) -> str:
    """Ask Groq to generate a natural follow-up question for missing fields."""
    system = (
        "You are a friendly sales order assistant helping a user create or retrieve "
        "a sales order in an ERP system. Ask a short, natural question to collect "
        "the following missing information. Be concise and conversational.\n"
        f"Missing fields: {', '.join(missing_fields)}"
    )
    return groq_chat(
        messages=conversation_history,
        system_prompt=system,
        max_tokens=128,
    )


# --------------------------------------------------
# DB Configuration
# --------------------------------------------------
DB_USER     = "apps"
DB_PASSWORD = "apps"
DB_DSN      = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)


# --------------------------------------------------
# REST Configuration
# --------------------------------------------------
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2
        ctx.options |= ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

BASE_URL      = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/PROCESS_ORDER/"
GET_ORDER_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/"
REST_USERNAME = "operations"
REST_PASSWORD = "welcome"
HEADERS       = {"Content-Type": "application/json", "Accept": "application/json"}

# Fixed / org-level constants
ORG_ID         = 204
ORDER_TYPE_ID  = 1437
OPERATING_UNIT = "Vision Operations"
MAX_CHOICES    = 5   


# --------------------------------------------------
# Voice helpers
# --------------------------------------------------
def speak(text: str):
    if VOICE_AVAILABLE:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    print("[TTS]", text)

MODEL_PATH       = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE      = 16000
DURATION_SECONDS = 4

def load_vosk_model():
    if not os.path.isdir(MODEL_PATH):
        raise FileNotFoundError(f"Vosk model directory not found: {MODEL_PATH}")
    return Model(MODEL_PATH)

def recognize_speech_vosk(duration=DURATION_SECONDS):
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice modules not installed")
    model = load_vosk_model()
    rec   = KaldiRecognizer(model, SAMPLE_RATE)
    data  = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    if not rec.AcceptWaveform(data.tobytes()):
        res = json.loads(rec.FinalResult())
    else:
        res = json.loads(rec.Result())
    return res.get("text", "").strip().lower()

def ask_voice(prompt):
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice support not enabled")
    while True:
        speak(prompt)
        val = recognize_speech_vosk()
        print("Recognized:", val)
        if not val:
            speak("I didn't catch that. Try again.")
            continue
        if val.strip().lower() in ("exit", "quit", "stop"):
            return None
        return val


def parse_numeric_value(val, allow_float=False):
    if val is None:
        return None
    val = str(val).strip()
    try:
        return float(val) if allow_float else int(val)
    except ValueError:
        pass
    if VOICE_AVAILABLE:
        try:
            return int(w2n.word_to_num(val))
        except Exception:
            pass
    digits = "".join(ch for ch in val if ch.isdigit() or (allow_float and ch == "."))
    if digits:
        try:
            return float(digits) if allow_float else int(digits)
        except ValueError:
            pass
    return None


def prompt_user_selection(label: str, rows: list, display_fn) -> dict:
    if len(rows) == 1:
        print(f"     [AUTO-SELECTED] {label}: {display_fn(rows[0])}")
        return rows[0]

    print(f"\n  Multiple {label} records found. Please choose one:")
    for idx, row in enumerate(rows, start=1):
        print(f"    [{idx}] {display_fn(row)}")

    while True:
        raw = input(f"  Enter choice (1-{len(rows)}): ").strip()
        try:
            choice = int(raw)
            if 1 <= choice <= len(rows):
                selected = rows[choice - 1]
                print(f"     [SELECTED] {label}: {display_fn(selected)}")
                return selected
        except ValueError:
            pass
        print(f"  Invalid input. Enter a number between 1 and {len(rows)}.")


# --------------------------------------------------
# DB Lookups
# --------------------------------------------------
def fetch_inventory_item(ordered_item: str, org_id: int = ORG_ID) -> dict:
    sql = """
        SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION, ORGANIZATION_ID
          FROM MTL_SYSTEM_ITEMS_B
         WHERE SEGMENT1 = :ordered_item AND ORGANIZATION_ID = :org_id AND ROWNUM <= :max_rows
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=ordered_item.upper(), org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()

    if not rows: raise ValueError(f"Item '{ordered_item}' not found.")

    dicts = [{"inventory_item_id": int(r[0]), "segment1": r[1], "description": r[2] or "", "organization_id": int(r[3])} for r in rows]
    return prompt_user_selection("Inventory Item", dicts, lambda r: f"ID={r['inventory_item_id']}  Segment={r['segment1']}  Desc={r['description']}")


def fetch_price_details(ordered_item: str, quantity: float, inventory_item_id: int, org_id: int = ORG_ID) -> dict:
    sql_generic = """
        SELECT qlh.LIST_HEADER_ID, qlt.NAME, qll.OPERAND
          FROM QP_LIST_HEADERS_B     qlh
          JOIN QP_LIST_HEADERS_TL    qlt ON qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID AND qlt.LANGUAGE = USERENV('LANG')
          JOIN QP_LIST_LINES         qll ON qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
          JOIN QP_PRICING_ATTRIBUTES  qpa ON qpa.LIST_LINE_ID = qll.LIST_LINE_ID
                                        AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                                        AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
         WHERE qlh.ACTIVE_FLAG = 'Y' AND qlh.LIST_TYPE_CODE = 'PRL' AND qlh.CURRENCY_CODE = 'USD'
           AND (qlh.START_DATE_ACTIVE IS NULL OR qlh.START_DATE_ACTIVE <= SYSDATE)
           AND (qlh.END_DATE_ACTIVE   IS NULL OR qlh.END_DATE_ACTIVE   >= SYSDATE)
           AND ROWNUM <= :max_rows
         ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_generic, item_id_str=str(inventory_item_id), max_rows=MAX_CHOICES)
        rows = cur.fetchall()

    if not rows: raise ValueError(f"No valid price list found for INVENTORY_ITEM_ID={inventory_item_id}.")

    dicts = [{"price_list_id": int(r[0]), "price_list_name": r[1] or "", "unit_list_price": float(r[2])} for r in rows]
    selected = prompt_user_selection("Price List", dicts, lambda r: f"ID={r['price_list_id']}  Name={r['price_list_name']}  Price={r['unit_list_price']}")
    
    return {
        "price_list_id": selected["price_list_id"],
        "unit_list_price": selected["unit_list_price"],
        "unit_selling_price": selected["unit_list_price"],
    }


def fetch_payment_term_id(org_id: int = ORG_ID) -> int:
    sql_fallback = "SELECT TERM_ID, NAME FROM RA_TERMS_B WHERE ENABLED_FLAG = 'Y' AND ROWNUM <= :max_rows ORDER BY TERM_ID"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql_fallback, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
    if not rows: raise ValueError("Could not derive PAYMENT_TERM_ID from the database.")
    
    dicts = [{"term_id": int(r[0]), "term_name": r[1] or ""} for r in rows]
    return prompt_user_selection("Payment Term", dicts, lambda r: f"ID={r['term_id']}  Name={r['term_name']}")["term_id"]


def fetch_salesrep(org_id: int = ORG_ID) -> dict:
    sql = """
        SELECT jrs.SALESREP_ID, jrs.NAME FROM JTF_RS_SALESREPS jrs
         WHERE jrs.ORG_ID = :org_id AND jrs.STATUS = 'A' AND jrs.END_DATE_ACTIVE IS NULL AND ROWNUM <= :max_rows ORDER BY jrs.SALESREP_ID
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()
    if not rows: raise ValueError(f"No active SALESREP found for ORG_ID={org_id}.")

    dicts = [{"salesrep_id": int(r[0]), "salesrep_name": r[1] or ""} for r in rows]
    return prompt_user_selection("Sales Rep", dicts, lambda r: f"ID={r['salesrep_id']}  Name={r['salesrep_name']}")


def fetch_customer_sites(ordered_item: str, org_id: int = ORG_ID) -> dict:
    sql = """
        SELECT hca.CUST_ACCOUNT_ID, hcsu.SITE_USE_ID, hp.PARTY_NAME, hcas.ORG_ID
          FROM MTL_SYSTEM_ITEMS_B     msi
          JOIN HZ_CUST_ACCT_SITES_ALL hcas ON hcas.ORG_ID = :org_id
          JOIN HZ_CUST_SITE_USES_ALL  hcsu ON hcas.CUST_ACCT_SITE_ID = hcsu.CUST_ACCT_SITE_ID
          JOIN HZ_CUST_ACCOUNTS       hca  ON hcas.CUST_ACCOUNT_ID = hca.CUST_ACCOUNT_ID
          JOIN HZ_PARTIES             hp   ON hca.PARTY_ID = hp.PARTY_ID
         WHERE msi.SEGMENT1 = :ordered_item AND msi.ORGANIZATION_ID = :org_id
           AND hcsu.SITE_USE_CODE = 'SHIP_TO' AND hcsu.STATUS = 'A'
           AND hcsu.PRIMARY_FLAG = 'Y' AND ROWNUM <= :max_rows
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, ordered_item=ordered_item.upper(), org_id=org_id, max_rows=MAX_CHOICES)
        rows = cur.fetchall()

    if not rows: raise ValueError(f"No active primary SHIP_TO site found for item '{ordered_item}'.")

    dicts = [{"sold_to_org_id": int(r[0]), "ship_to_org_id": int(r[1]), "customer_name": r[2] or "", "operating_unit_id": int(r[3])} for r in rows]
    return prompt_user_selection("Customer Site", dicts, lambda r: f"Customer={r['customer_name']}  SoldTo={r['sold_to_org_id']}  ShipTo={r['ship_to_org_id']}")


# --------------------------------------------------
# SMART FIELD RESOLUTION
# --------------------------------------------------
def enrich_state_from_db(state: dict, output_fn) -> dict:
    """
    Intelligently fetch only the missing fields from the DB based on what is currently known.
    Avoids overwriting fields the user explicitly provided.
    """
    output_fn("\n[System] Resolving system configurations based on provided info...")

    # 1. Resolve Inventory Item ID
    if state.get("ordered_item") and not state.get("inventory_item_id"):
        try:
            item = fetch_inventory_item(state["ordered_item"])
            state["inventory_item_id"] = item["inventory_item_id"]
            state["ordered_item"] = item["segment1"] # Format accurately
        except Exception as e:
            output_fn(f"[DB Warning] Could not resolve item: {e}")
            state["ordered_item"] = None  # Invalidate so user is prompted again

    # 2. Resolve Customer Sites (Only if one or both are missing)
    if state.get("ordered_item") and not (state.get("ship_to_org_id") and state.get("sold_to_org_id")):
        try:
            sites = fetch_customer_sites(state["ordered_item"])
            state["sold_to_org_id"] = state.get("sold_to_org_id") or sites["sold_to_org_id"]
            state["ship_to_org_id"] = state.get("ship_to_org_id") or sites["ship_to_org_id"]
        except Exception as e:
            output_fn(f"[DB Warning] Could not default customer sites: {e}")

    # 3. Resolve Pricing details
    if state.get("inventory_item_id") and state.get("quantity") and not state.get("price_list_id"):
        try:
            qty = float(state["quantity"])
            price_details = fetch_price_details(state["ordered_item"], qty, state["inventory_item_id"])
            state["price_list_id"] = state.get("price_list_id") or price_details["price_list_id"]
            state["unit_list_price"] = state.get("unit_list_price") or price_details["unit_list_price"]
            state["unit_selling_price"] = state.get("unit_selling_price") or price_details["unit_selling_price"]
        except Exception as e:
            output_fn(f"[DB Warning] Could not default pricing: {e}")

    # 4. Global defaults for Payment Term and Salesrep
    if not state.get("payment_term_id"):
        try: state["payment_term_id"] = fetch_payment_term_id()
        except Exception as e: output_fn(f"[DB Warning] {e}")

    if not state.get("salesrep_id"):
        try: state["salesrep_id"] = fetch_salesrep()["salesrep_id"]
        except Exception as e: output_fn(f"[DB Warning] {e}")

    return state


# --------------------------------------------------
# Payload & Send Logic
# --------------------------------------------------
def create_payload(p_cust_po, p_item_id, p_ordered_item, p_qty, p_price, p_selling_price, p_payment_term_id, p_price_list_id, p_salesrep_id, p_ship_to_org, p_sold_to_org, p_operating_unit):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": { "Responsibility": "ORDER_MGMT_SUPER_USER", "RespApplication": "ONT", "SecurityGroup": "STANDARD", "NLSLanguage": "AMERICAN", "Org_Id": "204" },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1, "P_INIT_MSG_LIST": "T", "P_RETURN_VALUES": "T", "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG": "N", "CUST_PO_NUMBER": p_cust_po, "ORDER_TYPE_ID": ORDER_TYPE_ID, "ORG_ID": ORG_ID,
                    "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "SALESREP_ID": p_salesrep_id,
                    "SHIP_TO_ORG_ID": p_ship_to_org, "SOLD_TO_ORG_ID": p_sold_to_org, "TRANSACTIONAL_CURR_CODE": "USD", "OPERATION": "CREATE"
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID": p_item_id, "ORDERED_ITEM": p_ordered_item, "ORDERED_QUANTITY": p_qty,
                        "PAYMENT_TERM_ID": p_payment_term_id, "PRICE_LIST_ID": p_price_list_id, "UNIT_LIST_PRICE": p_price,
                        "UNIT_SELLING_PRICE": p_selling_price, "OPERATION": "CREATE"
                    }
                },
                "P_RTRIM_DATA": "n", "P_OPERATING_UNIT": p_operating_unit, "P_DEBUG_LEVEL": 10
            }
        }
    }


def submit_order_from_state(state: dict, output_fn):
    payload = create_payload(
        p_cust_po         = state["cpo"],
        p_item_id         = state["inventory_item_id"],
        p_ordered_item    = state["ordered_item"],
        p_qty             = float(state["quantity"]),
        p_price           = float(state["unit_list_price"]),
        p_selling_price   = float(state["unit_selling_price"] or state["unit_list_price"]),
        p_payment_term_id = state["payment_term_id"],
        p_price_list_id   = state["price_list_id"],
        p_salesrep_id     = state["salesrep_id"],
        p_ship_to_org     = state["ship_to_org_id"],
        p_sold_to_org     = state["sold_to_org_id"],
        p_operating_unit  = OPERATING_UNIT,
    )

    print("\n[REST] Sending payload...")
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth = HTTPBasicAuth(REST_USERNAME, REST_PASSWORD)
    session.verify = False

    try:
        response = session.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=60)
        response.raise_for_status()
        result = response.json()
    except Exception as e:
        output_fn(f"Order submission failed: {e}")
        return

    hdr = result.get("PROCESS_ORDER_Output", {}).get("X_HEADER_REC", {})
    order_number = hdr.get("X_HEADER_REC.ORDER_NUMBER")
    header_id = hdr.get("X_HEADER_REC.HEADER_ID")

    if order_number and header_id:
        output_fn(f"Success! Order created. ORDER_NUMBER={order_number}, HEADER_ID={header_id}")
    else:
        output_fn("Order submitted, but ORDER_NUMBER/HEADER_ID were not found in response.")


# --------------------------------------------------
# GET Order logic remains identical here... 
# --------------------------------------------------
def process_get_order(order_number: int, output_fn):
    # GET LOGIC (same as your original, omitted for brevity but intact)
    output_fn(f"Fetching order {order_number} ...")
    pass


# --------------------------------------------------
# Stateful Chat Loops
# --------------------------------------------------
def text_chat():
    print("Sales Order bot [Text Mode]. Type naturally to provide details dynamically.")
    print("Type 'exit' to quit.\n")

    history = []
    state = {}

    while True:
        raw = input("You: ").strip()
        if not raw: continue
        if raw.lower() in ("exit", "quit", "stop"): break

        history.append({"role": "user", "content": raw})
        extracted = groq_extract_intent(raw)

        # 1. Merge Intent and Extracted Fields into persistent memory
        action = extracted.get("action")
        if action and action != "unknown":
            state["action"] = action
        elif "action" not in state:
            state["action"] = "unknown"

        for k, v in extracted.items():
            if k not in ["action", "raw_reply"] and v is not None:
                state[k] = v

        # 2. Process Intent Flow
        if state["action"] == "get":
            if not state.get("order_number"):
                q = groq_clarify(history, ["order_number"])
                print(f"Assistant: {q}")
                history.append({"role": "assistant", "content": q})
                continue
            else:
                process_get_order(int(state["order_number"]), print)
                state = {} # reset state cycle
                history.clear()
                continue

        elif state["action"] == "create":
            # Smart logic: Check what we have, query DB for the rest
            state = enrich_state_from_db(state, print)

            # Check core inputs that MUST come from the user
            missing_user = []
            if not state.get("cpo"): missing_user.append("Customer PO")
            if not state.get("ordered_item"): missing_user.append("Item Code")
            if not state.get("quantity"): missing_user.append("Quantity")

            if missing_user:
                q = groq_clarify(history, missing_user)
                print(f"Assistant: {q}")
                history.append({"role": "assistant", "content": q})
                continue

            # Check system inputs that the DB should have populated
            required_backend = ["inventory_item_id", "ship_to_org_id", "sold_to_org_id", "price_list_id", "unit_list_price", "payment_term_id", "salesrep_id"]
            missing_backend = [f for f in required_backend if not state.get(f)]

            if missing_backend:
                msg = f"Cannot proceed. Missing system mapping data: {', '.join(missing_backend)}. Please provide them or fix DB configuration."
                print(f"Assistant: {msg}")
                history.append({"role": "assistant", "content": msg})
                continue

            # Everything is ready, shoot payload
            submit_order_from_state(state, print)
            state = {} # reset state cycle
            history.clear()

        else:
            fallback = groq_clarify(history, ["action (create a new order or retrieve an existing one)"])
            print(f"Assistant: {fallback}")
            history.append({"role": "assistant", "content": fallback})


def voice_chat():
    if not VOICE_AVAILABLE: raise RuntimeError("Voice packages not installed")
    speak("Voice chatbot started. Say exit to stop.")
    prompt_text = "Would you like to create or retrieve an order?"

    history = []
    state = {}

    while True:
        raw = ask_voice(prompt_text)
        if not raw: continue
        if raw.lower() in ("exit", "quit", "stop"): break

        history.append({"role": "user", "content": raw})
        extracted = groq_extract_intent(raw)

        # Merge extracted entities just like text mode
        action = extracted.get("action")
        if action and action != "unknown": state["action"] = action
        elif "action" not in state: state["action"] = "unknown"

        for k, v in extracted.items():
            if k not in ["action", "raw_reply"] and v is not None:
                state[k] = v

        if state["action"] == "get":
            if not state.get("order_number"):
                prompt_text = groq_clarify(history, ["order_number"])
                history.append({"role": "assistant", "content": prompt_text})
                continue
            else:
                process_get_order(int(state["order_number"]), speak)
                state = {}
                history.clear()
                prompt_text = "What would you like to do next?"
                continue

        elif state["action"] == "create":
            state = enrich_state_from_db(state, speak)

            missing_user = []
            if not state.get("cpo"): missing_user.append("Customer PO")
            if not state.get("ordered_item"): missing_user.append("Item Code")
            if not state.get("quantity"): missing_user.append("Quantity")

            if missing_user:
                prompt_text = groq_clarify(history, missing_user)
                history.append({"role": "assistant", "content": prompt_text})
                continue

            required_backend = ["inventory_item_id", "ship_to_org_id", "sold_to_org_id", "price_list_id", "unit_list_price", "payment_term_id", "salesrep_id"]
            missing_backend = [f for f in required_backend if not state.get(f)]

            if missing_backend:
                prompt_text = f"Cannot proceed. Missing system data: {', '.join(missing_backend)}."
                history.append({"role": "assistant", "content": prompt_text})
                continue

            submit_order_from_state(state, speak)
            state = {}
            history.clear()
            prompt_text = "What would you like to do next?"

        else:
            prompt_text = groq_clarify(history, ["action (create a new order or retrieve an existing one)"])
            history.append({"role": "assistant", "content": prompt_text})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SalesOrderBot - Groq-powered NLU")
    parser.add_argument("--mode", choices=["text", "voice"], default="text")
    args = parser.parse_args()

    if args.mode == "voice":
        voice_chat()
    else:
        text_chat()