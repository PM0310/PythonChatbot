import os
import json
import requests
import ssl
from requests.auth import HTTPBasicAuth
from urllib3.util.ssl_ import create_urllib3_context
import urllib3
import argparse

import pyttsx3
from word2number import w2n
from vosk import Model, KaldiRecognizer
import sounddevice as sd

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Force TLS Adapter (Fix for old EBS servers) ─────────────────────────────
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

# ─── EBS Configuration ─────────────────────────────────────────────────────────
EBS_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/FusionAI/XX_INSERT_EMPLOYEE/"
USERNAME = "operations"
PASSWORD = "welcome"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ─── TTS ────────────────────────────────────────────────────────────────────────
def speak(text: str):
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()

# ─── VOSK mic listening ─────────────────────────────────────────────────────────
MODEL_PATH = r"C:\Users\pavan.maccha\Desktop\Python\Model\vosk-model-small-en-us-0.15"
SAMPLE_RATE = 16000
DURATION_SECONDS = 5

def load_vosk_model():
    if not os.path.isdir(MODEL_PATH):
        raise FileNotFoundError(
            f"Vosk model directory not found: {MODEL_PATH}\n"
            "Download from https://alphacephei.com/vosk/models\n"
            "then extract into this path."
        )
    return Model(MODEL_PATH)

def recognize_speech_vosk(duration=DURATION_SECONDS):
    model = load_vosk_model()
    rec = KaldiRecognizer(model, SAMPLE_RATE)
    data = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    sd.wait()
    if not rec.AcceptWaveform(data.tobytes()):
        res = json.loads(rec.FinalResult())
    else:
        res = json.loads(rec.Result())
    return res.get("text", "").strip().lower()

# ─── EBS API call ───────────────────────────────────────────────────────────────
def insert_employee(p_id: str, p_name: str, p_sal: int):
    payload = {
        "XX_INSERT_EMPLOYEE_Input": {
            "@xmlns": "http://xmlns.oracle.com/apps/po/rest/xxcen_sample_emp_details/XX_INSERT_EMPLOYEE/",
            "RESTHeader": {
                "xmlns": "http://xmlns.oracle.com/apps/po/rest/xxcen_sample_emp_details/header",
                "Responsibility": "PURCHASING_OPERATIONS",
                "RespApplication": "PO",
                "SecurityGroup": "STANDARD",
                "NLSLanguage": "AMERICAN",
                "Org_Id": "204",
            },
            "InputParameters": {
                "P_ID": p_id,
                "P_NAME": p_name,
                "P_SAL": p_sal,
            },
        }
    }

    try:
        session = requests.Session()
        session.mount("https://", ForceTLSAdapter())
        session.auth = HTTPBasicAuth(USERNAME, PASSWORD)
        session.verify = False
        response = session.post(
            EBS_URL,
            headers=HEADERS,
            data=json.dumps(payload),
            timeout=60,
        )

        status = response.status_code
        print(f"Status Code: {status}")
        print(f"Raw Response: {response.text}")

        if status in (200, 201):
            try:
                result = response.json()
                speak("Employee inserted successfully.")
                return result
            except Exception:
                speak("Employee inserted successfully (non-JSON).")
                return response.text
        elif status == 204:
            speak("Employee inserted successfully.")
            return "Employee inserted successfully."
        elif status == 500:
            speak("Server connection error.")
            return None
        else:
            speak(f"Error {status}.")
            return None

    except Exception as exc:
        speak("Request failed.")
        print("Error:", exc)
        return None

# ─── Chat loops ───────────────────────────────────────────────────────────────
def ask_text_parameter(prompt):
    while True:
        value = input(prompt).strip()
        if value.lower() in ("exit", "quit", "stop"):
            return None
        if value:
            return value
        print("Please enter a value (or type exit to quit).")


def is_exit_command(value: str):
    if not value:
        return False
    value = value.strip().lower()
    if value in ("exit", "quit", "stop"):
        return True
    tokens = value.split()
    return any(tok in ("exit", "quit", "stop") for tok in tokens)


def spoken_to_alphanumeric(value: str):
    if not value:
        return ""

    normalize = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'for': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8',
        'ate': '8', 'nine': '9',
        'dash': '-', 'hyphen': '-', 'minus': '-', 'underscore': '_',
        'space': '', 'dot': '.', 'period': '.', 'at': '@',
        'alpha': 'A', 'bravo': 'B', 'charlie': 'C', 'delta': 'D', 'echo': 'E',
        'foxtrot': 'F', 'golf': 'G', 'hotel': 'H', 'india': 'I', 'juliet': 'J',
        'kilo': 'K', 'lima': 'L', 'mike': 'M', 'november': 'N', 'oscar': 'O',
        'papa': 'P', 'quebec': 'Q', 'romeo': 'R', 'sierra': 'S', 'tango': 'T',
        'uniform': 'U', 'victor': 'V', 'whiskey': 'W', 'xray': 'X', 'yankee': 'Y',
        'zulu': 'Z',
    }

    tokens = value.strip().lower().split()
    result_chars = []
    for token in tokens:
        if token in normalize:
            result_chars.append(normalize[token])
            continue
        # if user speaks letters singly: e.g. 'a' or 'b'
        if len(token) == 1 and token.isalpha():
            result_chars.append(token.upper())
            continue
        if token.isalnum():
            result_chars.append(token.upper())
            continue
        # remove non-letters/digits, keep letters and digits
        numbers = ''.join(ch for ch in token if ch.isalnum())
        if numbers:
            result_chars.append(numbers.upper())

    return ''.join(result_chars)


def ask_voice_parameter(prompt):
    while True:
        speak(prompt)
        value = recognize_speech_vosk()
        if not value:
            speak("I didn't catch that. Please repeat.")
            continue
        if is_exit_command(value):
            return None
        return value


def text_chat_loop():
    print("Text mode (type 'exit' to quit).")
    while True:
        p_id = ask_text_parameter("Employee ID: ")
        if p_id is None:
            break

        p_name = ask_text_parameter("Employee Name: ")
        if p_name is None:
            break

        p_sal_text = ask_text_parameter("Employee Salary: ")
        if p_sal_text is None:
            break

        try:
            p_sal = int(p_sal_text)
        except ValueError:
            try:
                p_sal = w2n.word_to_num(p_sal_text)
            except Exception:
                print("Invalid salary. Use numeric or words (e.g. 2500 or two thousand).")
                continue

        print(f"Confirming: P_ID={p_id}, P_NAME={p_name}, P_SAL={p_sal}")
        res = insert_employee(p_id, p_name, p_sal)
        print("Result:", res)


def voice_chat_loop():
    speak("Oracle EBS voice bot started. Say exit to end.")
    while True:
        raw_p_id = ask_voice_parameter("Please say employee ID.")
        if raw_p_id is None:
            break
        p_id = spoken_to_alphanumeric(raw_p_id)

        p_name = ask_voice_parameter("Please say employee name.")
        if p_name is None:
            break

        salary_text = ask_voice_parameter("Please say employee salary.")
        if salary_text is None:
            break

        digits = "".join(ch for ch in salary_text if ch.isdigit())
        if digits:
            p_sal = int(digits)
        else:
            try:
                p_sal = w2n.word_to_num(salary_text)
            except Exception:
                speak("Could not parse salary. Please try again.")
                continue
        speak(f"You said ID {p_id}, name {p_name}, salary {p_sal}.")

        res = insert_employee(p_id, p_name, p_sal)
        if res is not None:
            speak("Employee inserted Successfully.")
        else:
            speak("Insert failed.")

    speak("Voice bot shutting down. Goodbye.")

# ─── Entrypoint ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Oracle EBS voice/text bot")
    parser.add_argument("--mode", choices=["voice", "text"], default="text")
    args = parser.parse_args()

    if args.mode == "voice":
        voice_chat_loop()
    else:
        text_chat_loop()