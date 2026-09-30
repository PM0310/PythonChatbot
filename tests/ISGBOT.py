import requests
import json
import argparse
from requests.auth import HTTPBasicAuth
import urllib3
import ssl
from urllib3.util.ssl_ import create_urllib3_context

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Force TLS Adapter (Fix for old EBS servers) ─────────────────────────────
class ForceTLSAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")  # Allow older ciphers
        ctx.options |= ssl.OP_NO_SSLv2
        ctx.options |= ssl.OP_NO_SSLv3
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


# ─── Configuration ───────────────────────────────────────────────────────────
EBS_URL = "https://cendb.ad.centroid.com:4463/webservices/rest/FusionAI/XX_INSERT_EMPLOYEE/"
USERNAME = "operations"
PASSWORD = "welcome"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


# ─── API Call ─────────────────────────────────────────────────────────────────
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
        print(f"\nCalling: {EBS_URL}")
        print(f"Parameters → P_ID: {p_id} | P_NAME: {p_name} | P_SAL: {p_sal}\n")

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

        print(f"Status Code: {response.status_code}")
        print(f"Raw Response: {response.text}\n")

        if response.status_code in (200, 201, 204):
            message = "✅ Success!"
            if response.status_code == 204:
                message = "✅ Success! Employee inserted successfully (204 No Content)."
            print(message)

            if response.status_code in (200, 201):
                try:
                    result = response.json()
                    print(json.dumps(result, indent=2))
                    return result
                except Exception:
                    print("✅ Success! (non-JSON response)")
                    return response.text
            return "Employee inserted successfully."

        elif response.status_code == 500:
            print("❌ Server connection Error")
            return None
        else:
            print(f"❌ Error: {response.text}")
            response.raise_for_status()

    except requests.exceptions.SSLError as e:
        print(f"SSL Error: {str(e)}")
    except requests.exceptions.ConnectionError as e:
        print(f"Connection Error: {str(e)}")
    except requests.exceptions.Timeout:
        print("Timeout: EBS did not respond within 60 seconds.")
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error: {e.response.status_code} - {e.response.text}")

    return None


def chatbot_loop():
    print("The chatbot is turning on!")
    print("Welcome to the Oracle EBS Employee Insert Chatbot!")
    print("\nOracle EBS Chatbot mode (type 'exit' or 'quit' at any prompt to end)")
    print("Please provide employee details to insert into Oracle EBS.\n")
    while True:
        p_id = input("Employee ID: ").strip()
        if p_id.lower() in ("exit", "quit"):
            print("The Chatbot is shutting down. Goodbye!")
            break

        p_name = input("Employee Name: ").strip()
        if p_name.lower() in ("exit", "quit"):
            print("The Chatbot is shutting down. Goodbye!")
            break

        p_sal_text = input("Employee Salary: ").strip()
        if p_sal_text.lower() in ("exit", "quit"):
            print("The Chatbot is shutting down. Goodbye!")
            break

        try:
            p_sal = int(p_sal_text)
        except ValueError:
            print("Invalid salary. Enter a numeric value.\n")
            continue

        response = insert_employee(p_id, p_name, p_sal)
        if response is not None:
            print("Chatbot: Employee insert request completed.")
        else:
            print("Chatbot: Failed to submit employee insert request.")

        print("-" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insert Employee via Oracle EBS REST API")
    parser.add_argument("--p_id", required=False, help="Employee ID     e.g. 02")
    parser.add_argument("--p_name", required=False, help="Employee Name   e.g. FUSIONAI")
    parser.add_argument("--p_sal", required=False, type=int, help="Employee Salary e.g. 20000")
    parser.add_argument("--mode", choices=["argparse", "chat"], default="chat", help="Use argparse or chat mode")

    args = parser.parse_args()

    if args.mode == "chat" or (not args.p_id or not args.p_name or not args.p_sal):
        chatbot_loop()
    else:
        insert_employee(p_id=args.p_id, p_name=args.p_name, p_sal=args.p_sal)
