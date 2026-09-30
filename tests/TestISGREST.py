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
EBS_URL  = "https://cendb.ad.centroid.com:4463/webservices/rest/FusionAI/XX_INSERT_EMPLOYEE/"
USERNAME = "operations"
PASSWORD = "welcome"

HEADERS = {
    "Content-Type": "application/json",
    "Accept":       "application/json",
}

# ─── API Call ─────────────────────────────────────────────────────────────────
def insert_employee(p_id: str, p_name: str, p_sal: int):
    payload = {
        "XX_INSERT_EMPLOYEE_Input": {
            "@xmlns": "http://xmlns.oracle.com/apps/po/rest/xxcen_sample_emp_details/XX_INSERT_EMPLOYEE/",
            "RESTHeader": {
                "xmlns":           "http://xmlns.oracle.com/apps/po/rest/xxcen_sample_emp_details/header",
                "Responsibility":  "PURCHASING_OPERATIONS",
                "RespApplication": "PO",
                "SecurityGroup":   "STANDARD",
                "NLSLanguage":     "AMERICAN",
                "Org_Id":          "204"
            },
            "InputParameters": {
                "P_ID":   p_id,
                "P_NAME": p_name,
                "P_SAL":  p_sal
            }
        }
    }

    try:
        print(f"\nCalling: {EBS_URL}")
        print(f"Parameters → P_ID: {p_id} | P_NAME: {p_name} | P_SAL: {p_sal}\n")

        # ── Use session with forced TLS adapter ───────────────────────────────
        session = requests.Session()
        session.mount("https://", ForceTLSAdapter())
        session.auth   = HTTPBasicAuth(USERNAME, PASSWORD)
        session.verify = False

        response = session.post(
            EBS_URL,
            headers=HEADERS,
            data=json.dumps(payload),
            timeout=60
        )

        print(f"Status Code: {response.status_code}")
        print(f"Raw Response: {response.text}\n")

        if response.status_code in (200, 201):
            try:
                result = response.json()
                print("✅ Success!")
                print(json.dumps(result, indent=2))
                return result
            except Exception:
                print("✅ Success! (non-JSON response)")
                return response.text
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


# ─── Argument Parser ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Insert Employee via Oracle EBS REST API")
    parser.add_argument("--p_id",   required=True,           help="Employee ID     e.g. 02")
    parser.add_argument("--p_name", required=True,           help="Employee Name   e.g. FUSIONAI")
    parser.add_argument("--p_sal",  required=True, type=int, help="Employee Salary e.g. 20000")
    args = parser.parse_args()

    insert_employee(
        p_id=args.p_id,
        p_name=args.p_name,
        p_sal=args.p_sal
    )