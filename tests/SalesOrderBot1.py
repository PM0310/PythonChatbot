import os
import json
import argparse
import requests
import ssl
import urllib3
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context

# Optional Oracle DB validation
try:
    import oracledb
    ORACLE_DB_VALIDATION = True
except ModuleNotFoundError:
    ORACLE_DB_VALIDATION = False
    print("WARNING: oracledb not installed; DB validation is disabled. pip install oracledb")

# --------------------------------------------------
# Configuration
# --------------------------------------------------
DB_USER = "apps"
DB_PASSWORD = "apps"
DB_DSN = "(DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=cendb.centroid.com)(PORT=1541))(CONNECT_DATA=(SERVICE_NAME=EBS122)))"

def get_db_connection():
    if not ORACLE_DB_VALIDATION:
        raise RuntimeError("Oracle DB validation is disabled")
    return oracledb.connect(
        user=DB_USER,
        password=DB_PASSWORD,
        dsn=DB_DSN,
        encoding="UTF-8",
        nencoding="UTF-8",
        timeout=5,
    )

def exists_in_db(sql, params):
    if not ORACLE_DB_VALIDATION:
        return True
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone() is not None
    except Exception as e:
        print("DB validation error:", e)
        return False

def validate_order_params(
    item_id, payment_term_id, price_list_id, salesrep_id, ship_to_org, sold_to_org
):
    if not exists_in_db(
        "SELECT 1 FROM mtl_system_items_b WHERE inventory_item_id = :id",
        {"id": item_id},
    ):
        raise ValueError(f"Inventory item not found: {item_id}")

    if not exists_in_db(
        "SELECT 1 id FROM ra_terms WHERE term_id = :id",
        {"id": payment_term_id},
    ):
        raise ValueError(f"Payment term not found: {payment_term_id}")

    if not exists_in_db(
        "SELECT 1 FROM price_list WHERE price_list_id = :id",
        {"id": price_list_id},
    ):
        raise ValueError(f"Price list not found: {price_list_id}")

    if not exists_in_db(
        "SELECT 1 FROM salesreps WHERE salesrep_id = :id",
        {"id": salesrep_id},
    ):
        raise ValueError(f"Salesrep not found: {salesrep_id}")

    if not exists_in_db(
        "SELECT 1 FROM organizations WHERE org_id = :id",
        {"id": ship_to_org},
    ):
        raise ValueError(f"Ship-to org not found: {ship_to_org}")

    if not exists_in_db(
        "SELECT 1 FROM organizations WHERE org_id = :id",
        {"id": sold_to_org},
    ):
        raise ValueError(f"Sold-to org not found: {sold_to_org}")

    return True

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

class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        ctx.options |= ssl.OP_NO_SSLv2
        ctx.options |= ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

BASE_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/PROCESS_ORDER/"
USERNAME = "operations"
PASSWORD = "welcome"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

def speak(text: str):
    if VOICE_AVAILABLE:
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    print("[TTS]", text)

MODEL_PATH = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
DURATION_SECONDS = 4

def load_vosk_model():
    if not os.path.isdir(MODEL_PATH):
        raise FileNotFoundError(f"Vosk model directory not found: {MODEL_PATH}")
    return Model(MODEL_PATH)

def recognize_speech_vosk(duration=DURATION_SECONDS):
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice modules not installed")
    model = load_vosk_model()
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    data = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    if not rec.AcceptWaveform(data.tobytes()):
        res = json.loads(rec.FinalResult())
    else:
        res = json.loads(rec.Result())
    return res.get("text", "").strip().lower()

def parse_salary_value(val):
    if val is None:
        return None
    val = str(val).strip()
    if val.isdigit():
        return int(val)
    if VOICE_AVAILABLE:
        try:
            return int(w2n.word_to_num(val))
        except Exception:
            pass
    digits = "".join(ch for ch in val if ch.isdigit())
    return int(digits) if digits else None

def create_payload(
    p_cust_po,
    p_item_id,
    p_qty,
    p_price,
    p_selling_price,
    p_payment_term_id,
    p_price_list_id,
    p_salesrep_id,
    p_line_type_id,
    p_ship_to_org,
    p_sold_to_org,
    p_operating_unit,
):
    return {
        "PROCESS_ORDER_Input": {
            "RESTHeader": {
                "Responsibility": "ORDER_MGMT_SUPER_USER",
                "RespApplication": "ONT",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Org_Id": "204"
            },
            "InputParameters": {
                "P_API_VERSION_NUMBER": 1,
                "P_INIT_MSG_LIST": "T",
                "P_RETURN_VALUES": "T",
                "P_ACTION_COMMIT": "T",
                "P_HEADER_REC": {
                    "BOOKED_FLAG": "N",
                    "CUST_PO_NUMBER": p_cust_po,
                    "ORDER_TYPE_ID": 1437,
                    "ORG_ID": 204,
                    "PAYMENT_TERM_ID": p_payment_term_id,
                    "PRICE_LIST_ID": p_price_list_id,
                    "SALESREP_ID": p_salesrep_id,
                    "SHIP_TO_ORG_ID": p_ship_to_org,
                    "SOLD_TO_ORG_ID": p_sold_to_org,
                    "TRANSACTIONAL_CURR_CODE": "USD",
                    "OPERATION": "CREATE"
                },
                "P_LINE_TBL": {
                    "P_LINE_TBL_ITEM": {
                        "INVENTORY_ITEM_ID": p_item_id,
                        "LINE_TYPE_ID": p_line_type_id,
                        "ORDERED_QUANTITY": p_qty,
                        "PAYMENT_TERM_ID": p_payment_term_id,
                        "PRICE_LIST_ID": p_price_list_id,
                        "UNIT_LIST_PRICE": p_price,
                        "UNIT_SELLING_PRICE": p_selling_price,
                        "OPERATION": "CREATE"
                    }
                },
                "P_RTRIM_DATA": "n",
                "P_OPERATING_UNIT": p_operating_unit,
                "P_DEBUG_LEVEL": 10
            }
        }
    }

def send_order(payload):
    session = requests.Session()
    session.mount("https://", ForceTLSAdapter())
    session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    session.verify = False
    response = session.post(BASE_URL, headers=HEADERS, data=json.dumps(payload), timeout=60)
    print("Status Code:", response.status_code)
    print("Response:", response.text)
    if response.status_code in (200, 201, 204):
        try:
            return response.json()
        except Exception:
            return response.text
    if response.status_code == 500:
        raise RuntimeError("Server connection error")
    response.raise_for_status()

def extract_order_header(result):
    if not isinstance(result, dict):
        return None, None
    hdr = result.get("X_HEADER_REC")
    if hdr is None:
        hdr = result.get("PROCESS_ORDER_Output", {}).get("X_HEADER_REC")
    if not isinstance(hdr, dict):
        return None, None
    return hdr.get("ORDER_NUMBER"), hdr.get("HEADER_ID")

def ask_text(prompt):
    while True:
        val = input(prompt).strip()
        if not val:
            print("Enter a value, or type 'exit' to quit.")
            continue
        if val.lower() in ("exit", "quit", "stop"):
            return None
        return val

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

def text_chat():
    print("Sales Order chat mode (text).")
    while True:
        cpo = ask_text("Customer PO Number: ")
        if cpo is None:
            break
        item_id_text = ask_text("Inventory Item ID: ")
        if item_id_text is None:
            break
        qty_text = ask_text("Ordered Quantity: ")
        if qty_text is None:
            break
        unit_price_text = ask_text("Unit List Price: ")
        if unit_price_text is None:
            break
        unit_selling_price_text = ask_text("Unit Selling Price: ")
        if unit_selling_price_text is None:
            break
        payment_term_text = ask_text("Payment Term ID: ")
        if payment_term_text is None:
            break
        price_list_text = ask_text("Price List ID: ")
        if price_list_text is None:
            break
        salesrep_text = ask_text("Salesrep ID: ")
        if salesrep_text is None:
            break
        ship_to_org_text = ask_text("Ship-to Org ID: ")
        if ship_to_org_text is None:
            break
        sold_to_org_text = ask_text("Sold-to Org ID: ")
        if sold_to_org_text is None:
            break
        operating_unit = ask_text("Operating Unit: ")
        if operating_unit is None:
            break

        try:
            item_id = int(item_id_text)
            ship_to_org = int(ship_to_org_text)
            sold_to_org = int(sold_to_org_text)
            payment_term_id = int(payment_term_text)
            price_list_id = int(price_list_text)
            salesrep_id = int(salesrep_text)

            validate_order_params(
                item_id, payment_term_id, price_list_id, salesrep_id, ship_to_org, sold_to_org
            )
        except ValueError as e:
            print("Validation failed:", e)
            continue

        qty = parse_salary_value(qty_text)
        if qty is None:
            print("Invalid quantity. Try again.")
            continue

        price = parse_salary_value(unit_price_text)
        selling_price = parse_salary_value(unit_selling_price_text)
        if price is None or selling_price is None:
            print("Invalid price. Try again.")
            continue

        payload = create_payload(
            p_cust_po=cpo,
            p_item_id=item_id,
            p_qty=qty,
            p_price=price,
            p_selling_price=selling_price,
            p_payment_term_id=payment_term_id,
            p_price_list_id=price_list_id,
            p_salesrep_id=salesrep_id,
            p_line_type_id=1427,
            p_ship_to_org=ship_to_org,
            p_sold_to_org=sold_to_org,
            p_operating_unit=operating_unit,
        )

        print("Sending payload:", json.dumps(payload, indent=2))
        result = send_order(payload)

        order_number, header_id = extract_order_header(result)
        if order_number and header_id:
            print(f"Order created: ORDER_NUMBER={order_number}, HEADER_ID={header_id}")
        else:
            print("Order created, but ORDER_NUMBER/HEADER_ID not found in response.")

def voice_chat():
    if not VOICE_AVAILABLE:
        raise RuntimeError("Voice packages not installed")
    speak("Sales order voice chatbot started. Say exit to stop.")
    while True:
        cpo = ask_voice("Please say Customer PO Number.")
        if cpo is None:
            break
        item = ask_voice("Please say item id.")
        if item is None:
            break
        qty_txt = ask_voice("Please say quantity.")
        if qty_txt is None:
            break
        price_txt = ask_voice("Please say unit list price.")
        if price_txt is None:
            break
        selling_price_txt = ask_voice("Please say unit selling price.")
        if selling_price_txt is None:
            break
        payment_term_txt = ask_voice("Please say payment term id.")
        if payment_term_txt is None:
            break
        price_list_txt = ask_voice("Please say price list id.")
        if price_list_txt is None:
            break
        salesrep_txt = ask_voice("Please say salesrep id.")
        if salesrep_txt is None:
            break
        ship_to_org_txt = ask_voice("Please say ship-to org id.")
        if ship_to_org_txt is None:
            break
        sold_to_org_txt = ask_voice("Please say sold-to org id.")
        if sold_to_org_txt is None:
            break
        operating_unit = ask_voice("Please say operating unit.")
        if operating_unit is None:
            break

        try:
            item_id = int(item)
            ship_to_org = int(ship_to_org_txt)
            sold_to_org = int(sold_to_org_txt)
            payment_term_id = int(payment_term_txt)
            price_list_id = int(price_list_txt)
            salesrep_id = int(salesrep_txt)

            validate_order_params(
                item_id, payment_term_id, price_list_id, salesrep_id, ship_to_org, sold_to_org
            )
        except ValueError as e:
            speak(f"Validation failed: {e}")
            print("Validation failed:", e)
            continue

        qty = parse_salary_value(qty_txt)
        price = parse_salary_value(price_txt)
        selling_price = parse_salary_value(selling_price_txt)
        if qty is None or price is None or selling_price is None:
            speak("Invalid numeric fields. Please try again.")
            continue

        payload = create_payload(
            p_cust_po=cpo,
            p_item_id=item_id,
            p_qty=qty,
            p_price=price,
            p_selling_price=selling_price,
            p_payment_term_id=payment_term_id,
            p_price_list_id=price_list_id,
            p_salesrep_id=salesrep_id,
            p_line_type_id=1427,
            p_ship_to_org=ship_to_org,
            p_sold_to_org=sold_to_org,
            p_operating_unit=operating_unit,
        )

        print("Payload:", json.dumps(payload, indent=2))
        result = send_order(payload)

        order_number, header_id = extract_order_header(result)
        if order_number and header_id:
            speak(f"Order created. Order number {order_number}, header id {header_id}.")
            print(f"Order created: ORDER_NUMBER={order_number}, HEADER_ID={header_id}")
        else:
            speak("Order created, but ORDER_NUMBER/HEADER_ID not found in response.")
            print("Order created, but ORDER_NUMBER/HEADER_ID not found in response.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SalesOrderbot for ISG service")
    parser.add_argument("--mode", choices=["text","voice"], default="text")
    args = parser.parse_args()

    if args.mode == "voice":
        voice_chat()
    else:
        text_chat()