# Oracle Wallet - Complete Setup Guide for APEX & SQLcl

## 📋 What is an Oracle Wallet?

An Oracle Wallet is a secure container that stores database credentials (username, password, connection strings). It allows you to:
- Connect to Oracle databases without exposing passwords
- Use with APEX, SQLcl, and SQL*Net
- Secure authentication for applications
- Enable single sign-on (SSO)

---

## 🔍 Check If You Already Have a Wallet

### Location Where Wallets Are Typically Stored:
```
Windows:
- %ORACLE_HOME%\network\admin\wallet\
- C:\oracle\wallet\
- C:\Users\<username>\wallet\
- Your Oracle Cloud downloads folder

Example from your system:
- OneDrive\Backup\Oracle Analytics Cloud\Wallet_ADW4Workshops.zip
```

### Locate Your Wallet:
```powershell
# Search for wallet files
Get-ChildItem -Path "C:\" -Filter "*wallet*" -Recurse -ErrorAction SilentlyContinue

# Search for .zip files containing wallet
Get-ChildItem -Path "C:\" -Filter "*Wallet*" -Recurse -ErrorAction SilentlyContinue
```

---

## 📥 Option 1: Download Wallet from Oracle Cloud APEX

If you're using **Oracle Cloud APEX**, download your wallet:

### Steps:
1. **Log in to Oracle Cloud** → APEX Dashboard
2. **Click your app** → Database
3. **Click "Database Actions"** or **"Download Wallet"**
4. **Select "Wallet" download option**
5. **Save to a secure location**

### What You'll Get:
```
Wallet_ADW4Workshops.zip (or your database name)
├── cwallet.sso         (encrypted credentials)
├── ewallet.p12         (encrypted key)
├── tnsnames.ora        (connection strings)
├── sqlnet.ora          (SQL*Net config)
└── README.txt          (instructions)
```

---

## 📂 Option 2: Extract & Configure Your Wallet

### Step 1: Extract Wallet Files
```powershell
# If you have a wallet ZIP file
Expand-Archive -Path "C:\path\to\Wallet_ADW4Workshops.zip" -DestinationPath "C:\oracle\wallet" -Force

# Verify extraction
Get-ChildItem "C:\oracle\wallet"
```

### Step 2: Set Up Wallet Directory
```powershell
# Create wallet directory if it doesn't exist
$walletPath = "C:\oracle\wallet"
if (-not (Test-Path $walletPath)) {
    New-Item -ItemType Directory -Path $walletPath -Force
}
```

### Step 3: View Wallet Contents
```
C:\oracle\wallet\
├── cwallet.sso              ← Signed wallet (credentials)
├── ewallet.p12              ← Personal wallet (keys)
├── tnsnames.ora             ← Connection strings
├── sqlnet.ora               ← SQL*Net configuration
└── README.txt               ← Instructions
```

---

## 🔑 How to Get Wallet Details

### 1. **Read tnsnames.ora** (Connection Strings)
```powershell
# View connection strings
Get-Content "C:\oracle\wallet\tnsnames.ora"
```

**Output Example:**
```
adwc_low = (description= (retry_count=20)(retry_delay=3)(address=(protocol=tcps)
  (port=1522)(host=adb.us-phoenix-1.oraclecloud.com))
  (connect_data=(service_name=abc123_adwc_low.atp.oraclecloud.com))
  (security=(ssl_server_cert_dn="CN=adb.us-phoenix-1.oraclecloud.com,OU=Oracle ADB,O=Oracle,C=US")))

adwc_medium = (description= (retry_count=20)(retry_delay=3)...
adwc_high = (description= (retry_count=20)(retry_delay=3)...
adwc_tp = (description= (retry_count=20)(retry_delay=3)...
```

**Extract Connection Details:**
- **Host**: `adb.us-phoenix-1.oraclecloud.com`
- **Port**: `1522`
- **Service Name**: `abc123_adwc_low.atp.oraclecloud.com`

### 2. **Read sqlnet.ora** (Configuration)
```powershell
Get-Content "C:\oracle\wallet\sqlnet.ora"
```

**Output Example:**
```
WALLET_LOCATION = (SOURCE = (METHOD = file) (METHOD_DATA = (DIRECTORY = C:\oracle\wallet)))
SSL_SERVER_DN_MATCH = yes
SSL_SERVER_CERT_DN = "CN=adb.us-phoenix-1.oraclecloud.com,OU=Oracle ADB,O=Oracle,C=US"
```

### 3. **View README** (Credentials & Instructions)
```powershell
Get-Content "C:\oracle\wallet\README.txt"
```

**Output Example:**
```
Connection strings and instructions for using your wallet:

For SQL*Plus:
  sqlplus /nolog
  connect [username]@adwc_low

For SQLcl:
  sql [username]@adwc_low

Your database user is: admin
Service names: adwc_low, adwc_medium, adwc_high, adwc_tp
```

---

## 🗝️ Key Wallet Components Explained

| File | Purpose | Contains |
|------|---------|----------|
| **cwallet.sso** | Signed Wallet | Credentials (encrypted) |
| **ewallet.p12** | Personal Wallet | Private keys (encrypted) |
| **tnsnames.ora** | TNS Names | Connection strings for databases |
| **sqlnet.ora** | SQL*Net Config | SSL/TLS settings, wallet location |
| **README.txt** | Instructions | Default user, credentials, usage examples |

---

## 🔐 Extract Credentials from Wallet

### Option 1: View in Plain Text (from README)
The README.txt file usually contains:
```
Default Database User: admin
Default Password: <your wallet download contains this>
Cloud SQL Developer Role: DWROLE
```

### Option 2: Use orapki Tool (Advanced)
```powershell
# List wallet certificates
orapki wallet display -wallet C:\oracle\wallet

# Output shows:
# Certificates in this wallet:
# Oracle Security token:
#   Issuer: CN=Oracle,O=Oracle,C=US
#   User Oracle Identity:
#   Subject: CN=oracleidentityserviceuser
```

### Option 3: Use SQLcl to Test Connection
```powershell
# Navigate to SQLcl directory
cd "C:\Program Files\sqlcl\bin"

# Connect using wallet
.\sql.exe admin@adwc_low

# Enter password when prompted
# Should show: SQL>
```

---

## 📝 Complete Wallet Details Template

Create a file to store your wallet information (KEEP THIS SECURE):

```
=== ORACLE WALLET DETAILS ===

WALLET LOCATION: C:\oracle\wallet

DATABASE CREDENTIALS:
  Username: admin
  Database: Oracle Autonomous Data Warehouse (OADW)
  Cloud Service: Oracle Cloud Infrastructure (OCI)

CONNECTION STRINGS (from tnsnames.ora):
  adwc_low: adwc_low = (description=(retry_count=20)...)
  Service: abc123_adwc_low.atp.oraclecloud.com
  Host: adb.us-phoenix-1.oraclecloud.com
  Port: 1522

SQL CONNECT STRING:
  sqlplus admin@adwc_low
  
SQLcl CONNECT STRING:
  sql admin@adwc_low

FILES:
  ✓ cwallet.sso - Signed wallet (credentials)
  ✓ ewallet.p12 - Personal wallet (keys)
  ✓ tnsnames.ora - Connection strings
  ✓ sqlnet.ora - SQL*Net config

ENVIRONMENT VARIABLES:
  TNS_ADMIN = C:\oracle\wallet
  ORACLE_WALLET_LOCATION = C:\oracle\wallet

STATUS: ✓ Configured and Ready
```

---

## 🔧 Set Up Environment for SQLcl & APEX

### Windows PowerShell - Set Environment Variables:
```powershell
# Set TNS_ADMIN to wallet location
$env:TNS_ADMIN = "C:\oracle\wallet"
$env:ORACLE_HOME = "C:\oracle\client"

# Verify
echo $env:TNS_ADMIN
echo $env:ORACLE_HOME

# Permanent setup (add to user profile)
[Environment]::SetEnvironmentVariable("TNS_ADMIN", "C:\oracle\wallet", [EnvironmentVariableTarget]::User)
[Environment]::SetEnvironmentVariable("ORACLE_HOME", "C:\oracle\client", [EnvironmentVariableTarget]::User)
```

### Test Connection with SQLcl:
```powershell
cd "C:\Program Files\sqlcl\bin"  # Adjust path as needed
.\sql.exe admin@adwc_low
```

---

## 🐍 Using Wallet with Python (app7.py)

Update your connection string in `config.json`:

### Old (without wallet):
```json
{
  "database": {
    "host": "adb.us-phoenix-1.oraclecloud.com",
    "port": 1522,
    "user": "admin",
    "password": "YourPassword123!"
  }
}
```

### New (with wallet):
```json
{
  "database": {
    "dsn": "adwc_low",
    "wallet_location": "C:\\oracle\\wallet",
    "user": "admin",
    "use_wallet": true
  }
}
```

### Update Python Code:
```python
import oracledb
import os

# Set wallet location
os.environ['TNS_ADMIN'] = r'C:\oracle\wallet'

# Connection with wallet
connection = oracledb.connect(
    dsn='adwc_low',
    user='admin',
    password='YourPassword123!'  # Still needed first time
)

# Or after wallet is registered
connection = oracledb.connect('/nolog')  # Uses wallet credentials
```

---

## 🚀 Quick Checklist

- [ ] Download wallet from Oracle Cloud APEX
- [ ] Extract wallet ZIP to `C:\oracle\wallet\`
- [ ] Verify files exist: cwallet.sso, ewallet.p12, tnsnames.ora, sqlnet.ora
- [ ] Read README.txt for credentials
- [ ] Set `TNS_ADMIN` environment variable
- [ ] Test with SQLcl: `sql admin@adwc_low`
- [ ] Update config.json with wallet settings
- [ ] Test Python connection
- [ ] Configure APEX database connection

---

## 🆘 Troubleshooting

### Problem: "Cannot find wallet"
```
Solution: 
1. Verify TNS_ADMIN is set correctly
2. Check wallet directory exists
3. Ensure all wallet files are extracted
```

### Problem: "TNS:no appropriate service handler found"
```
Solution:
1. Check tnsnames.ora file exists
2. Verify service name in connection string
3. Reload environment variables
```

### Problem: "ORA-12170: TNS:Connect timeout"
```
Solution:
1. Check network connectivity to database host
2. Verify firewall allows port 1522
3. Check sqlnet.ora SSL settings
```

### Problem: "Wallet verification failed"
```
Solution:
1. Re-download wallet from Oracle Cloud
2. Extract all files (not just some)
3. Check file permissions (not read-only)
```

---

## 📞 Where to Find Wallet in Oracle Cloud

### Oracle Autonomous Database (OADW/ATP):
1. Log in to OCI Console
2. **Bare Metal, VM, and Exadata** → Autonomous Database
3. Select your database
4. **Database Connection** → **Download Client Credentials**
5. **Wallet Type**: Single Download
6. Click **Download**

### Oracle APEX Cloud Service:
1. Log in to APEX
2. **Administration** → **Manage Services** or **Database**
3. **Action** → **Download Wallet**
4. Save the ZIP file

---

## ✅ Next Steps

1. **Download your wallet** from Oracle Cloud APEX
2. **Extract to `C:\oracle\wallet\`**
3. **Read the README.txt** for your specific details
4. **Set `TNS_ADMIN` environment variable**
5. **Test connection with SQLcl**
6. **Update your Python config**
7. **Use in APEX SQL Workshop**

---

**Note**: Keep your wallet files secure! Don't commit them to version control.
