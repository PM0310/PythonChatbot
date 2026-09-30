import requests
import json

# --- CONFIGURATION ---
BASE_URL = "https://centroid.secretservercloud.com" # Replace with your URL
API_TOKEN = "AgLfpIIeXqgCftVPkpDEUUe6yyNaAqUOIFkpQIAF4RwrUWrIVkJK3Qks3rTQCogbcuY6llCesIKF792v02ddHZqF7ma8EaI9Z4ZgY4WRXedugR6q3JuVDYEsohgF_nd3oyT0AlCcDi8Y60iQTBngBz3X18oLmMwxJT-KuT7pHYwdDpQTO1u734mumZeENR_3DGiyljk6p_Vtty8n9iFCTaja5MaAg1VNF2VzsOBrhA29mhX4EpgLOAjtVFW_xvJxnr5fAZ7PtatHWK0musTLeRDmSbNFa2t4KU8as7rKEfVzFvFcKxSCWDsX_ALZxk-1jq8zPcCRJuNvJNbmwsytY61GRQ9RizRIlXWtS16-JVQigaO_bI3z6uO4ScQ1nXsr3zH0SRjusdRdAUM_r8mrjS0CLOPifs8fT6qW2RsuCdCEZI9IkZ1V0tSY3FUBTMFgJaSyO-XxZVGSG2BS24fyfI02Q6kmsVRYB3c62SsXx5gVdO5Pm2OCsQcVvSW-N6Xrl45ow-IFNwHvAqWNYTDioa6mgZtUqGVDk2yDxX7r8t8YWbtf-vC86lQ_y6pz1S-etC-sBFOQY4pePY9_RcUAhFkIjvUEl2zl9_XinZsFYczuEedy_oZuQriZ2m_EhIVFSsl0014rFpCrIxnke7w5PbZDaq2SHhvad8jvp8EUj1QPzLehM9KeARjXAjAqH81jUYVWG7z3s6j8HuvwRUGtV_9ro4EJbwfXF8F1g0TdnVkNZw"             # Replace with token from Step A
SECRET_ID = 20414                                   # The ID extracted from your HTML source

# --- SETUP HEADERS ---
headers = {
    "Authorization": f"Bearer {API_TOKEN}",          # Authorize using the Bearer scheme
    "Content-Type": "application/json"
}

# --- ENDPOINT FOR PASSWORDS/AUDIT HISTORY ---
# Delinea API format: /api/v1/secrets/{id}
endpoint_url = f"{BASE_URL}/api/v1/secrets/{SECRET_ID}"

try:
    # Send the GET request to fetch history
    params = {"includeInactive": False}
    response = requests.get(endpoint_url, headers=headers, params=params)
    
    if response.status_code == 200:
        try:
            history_data = response.json()
            print("--- Secret Data successfully retrieved ---")
            print(json.dumps(history_data, indent=4))
        except json.JSONDecodeError:
            print("--- Secret Data successfully retrieved ---")
            print(response.text)
    elif response.status_code == 401:
        print("Authentication failed. Please verify that your API Token is valid and not expired.")
        print(f"Response: {response.text[:500]}")
    elif response.status_code == 403:
        print("Access denied. Your API user account does not have permissions for this Secret.")
    else:
        print(f"Failed to fetch data. HTTP Status Code: {response.status_code}")
        print(response.text[:500])

except Exception as e:
    print(f"An error occurred while connecting to Secret Server: {e}")
