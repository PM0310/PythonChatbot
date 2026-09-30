# Oracle Wallet - Quick Reference & Checklists

## 🚀 5-Minute Quickstart

### Step 1: Download Wallet
```
Go to Oracle Cloud APEX → Database → Download Wallet
Save: Wallet_ADW4Workshops.zip (or similar)
```

### Step 2: Extract Wallet
```powershell
# PowerShell
Expand-Archive -Path "C:\Downloads\Wallet_ADW4Workshops.zip" -DestinationPath "C:\oracle\wallet" -Force
```

### Step 3: View Details
```powershell
# View connection strings
Get-Content "C:\oracle\wallet\tnsnames.ora"

# View credentials
Get-Content "C:\oracle\wallet\README.txt"
```

### Step 4: Set Environment
```powershell
# Set for current session
$env:TNS_ADMIN = "C:\oracle\wallet"

# Set permanently
[Environment]::SetEnvironmentVariable("TNS_ADMIN", "C:\oracle\wallet", [EnvironmentVariableTarget]::User)
```

### Step 5: Test Connection
```powershell
sqlplus admin@adwc_low
# Enter password from README.txt
```

---

## 📊 Wallet Files Reference

| File | Size | Purpose | How to Read |
|------|------|---------|-----------|
| **cwallet.sso** | ~2KB | Signed wallet (credentials) | Binary - contains encrypted credentials |
| **ewallet.p12** | ~2KB | Personal wallet (keys) | Binary - contains private keys |
| **tnsnames.ora** | ~1KB | Connection strings | Text - list of database services |
| **sqlnet.ora** | ~200B | SQL*Net config | Text - SSL/TLS settings |
| **README.txt** | ~2KB | Instructions | Text - your connection details |

---

## 🔑 Extract These Details

After downloading your wallet, you MUST have:

```
✅ WALLET LOCATION
   Example: C:\oracle\wallet

✅ DATABASE USER
   Example: admin

✅ SERVICE NAME (from tnsnames.ora)
   Example: adwc_low, adwc_medium, adwc_high

✅ DATABASE PASSWORD
   From: README.txt file

✅ CONNECTION HOST (from tnsnames.ora)
   Example: adb.us-phoenix-1.oraclecloud.com

✅ CONNECTION PORT (from tnsnames.ora)
   Default: 1522
```

---

## 🔍 How to Find Each Detail

### 1. **Find Wallet Files**
```powershell
# Search your computer
Get-ChildItem -Path "C:\" -Filter "*Wallet*.zip" -Recurse

# Result: C:\...\Wallet_ADW4Workshops.zip
```

### 2. **Extract All Files**
```powershell
Expand-Archive -Path "Wallet_ADW4Workshops.zip" -DestinationPath "C:\oracle\wallet" -Force
```

### 3. **Read README.txt** (MOST IMPORTANT!)
```powershell
Get-Content "C:\oracle\wallet\README.txt"

# Contains:
# - Your database username: admin
# - Default password (one-time)
# - Service names to use
# - Connection instructions
```

### 4. **Read tnsnames.ora** (Connection Strings)
```powershell
Get-Content "C:\oracle\wallet\tnsnames.ora"

# Look for lines like:
# adwc_low = (description=(retry_count=20)...
#   (host=adb.us-phoenix-1.oraclecloud.com)
#   (port=1522)
#   (service_name=abc123_adwc_low.atp.oraclecloud.com))
```

### 5. **Read sqlnet.ora** (Configuration)
```powershell
Get-Content "C:\oracle\wallet\sqlnet.ora"

# Shows:
# WALLET_LOCATION = (SOURCE = (METHOD = file) (METHOD_DATA = (DIRECTORY = C:\oracle\wallet)))
# SSL_SERVER_CERT_DN = "CN=adb.us-phoenix-1.oraclecloud.com,OU=Oracle ADB,O=Oracle,C=US"
```

---

## 💾 Create Your Own Wallet Details File

Save this safely (NOT in version control):

```
=== MY ORACLE WALLET ===
Created: 2024-06-26

WALLET LOCATION:
  C:\oracle\wallet

DATABASE CREDENTIALS:
  Username: admin
  Initial Password: [FROM README.txt]
  Cloud Service: Oracle Autonomous Data Warehouse

CONNECTION INFORMATION:
  Host: adb.us-phoenix-1.oraclecloud.com
  Port: 1522
  Default Service: adwc_low

AVAILABLE SERVICES (from tnsnames.ora):
  adwc_low      - Low traffic connections
  adwc_medium   - Medium traffic connections
  adwc_high     - High traffic connections
  adwc_tp       - Transaction processing

CONNECTION STRINGS:
  SQL*Plus:  sqlplus admin@adwc_low
  SQLcl:     sql admin@adwc_low
  Python:    dsn='adwc_low'

ENVIRONMENT VARIABLES:
  TNS_ADMIN = C:\oracle\wallet
  ORACLE_HOME = C:\oracle\client

PYTHON CONNECTION EXAMPLE:
  import oracledb
  connection = oracledb.connect(
    dsn='adwc_low',
    user='admin',
    password='YourPassword'
  )

CONFIG FILE LOCATION:
  C:\oracle\wallet\wallet_config.json

WALLET FILES:
  ✓ cwallet.sso
  ✓ ewallet.p12
  ✓ tnsnames.ora
  ✓ sqlnet.ora
  ✓ README.txt
```

---

## 🛠️ Tool Commands Reference

### PowerShell Script
```powershell
# Run interactive menu
powershell -ExecutionPolicy Bypass -File manage_oracle_wallet.ps1

# Extract wallet with script
powershell -ExecutionPolicy Bypass -File manage_oracle_wallet.ps1 `
  -WalletZipPath "C:\Downloads\Wallet_ADW.zip" `
  -WalletDestination "C:\oracle\wallet" `
  -Action "setup"
```

### Python Script
```bash
# Display wallet details
python manage_oracle_wallet.py display

# Extract wallet from ZIP
python manage_oracle_wallet.py extract "C:\Downloads\Wallet_ADW.zip"

# List available services
python manage_oracle_wallet.py services

# Create configuration file
python manage_oracle_wallet.py config

# Set environment variables
python manage_oracle_wallet.py env

# Find wallet files on system
python manage_oracle_wallet.py find

# Verify wallet integrity
python manage_oracle_wallet.py verify
```

---

## ⚙️ Environment Setup

### Windows - Set TNS_ADMIN Permanently
```powershell
# Option 1: PowerShell (as Administrator)
[Environment]::SetEnvironmentVariable(
    "TNS_ADMIN",
    "C:\oracle\wallet",
    [EnvironmentVariableTarget]::User
)

# Option 2: Command Prompt (as Administrator)
setx TNS_ADMIN "C:\oracle\wallet"

# Option 3: GUI
# Settings → Environment Variables → New User Variable
# Variable name: TNS_ADMIN
# Variable value: C:\oracle\wallet
```

### Verify Environment Variable
```powershell
# Check if set
echo $env:TNS_ADMIN

# Should output: C:\oracle\wallet
```

---

## 🧪 Test Connections

### Test with SQL*Plus
```bash
sqlplus /nolog
SQL> connect admin@adwc_low
Enter password: [FROM README.txt]
SQL> SELECT * FROM dual;
```

### Test with SQLcl
```bash
sql admin@adwc_low
# Enter password
sql> SELECT * FROM dual;
```

### Test with Python
```python
import oracledb
import os

# Set wallet location
os.environ['TNS_ADMIN'] = r'C:\oracle\wallet'

# Connect
try:
    conn = oracledb.connect(
        dsn='adwc_low',
        user='admin',
        password='YourPassword'
    )
    print("✅ Connection successful!")
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dual")
    print(cursor.fetchone())
    
    conn.close()
except Exception as e:
    print(f"❌ Connection failed: {e}")
```

---

## ❌ Common Issues & Solutions

### Issue: "Cannot find wallet"
```
Error: ORA-12170: TNS:Connect timeout

Solution:
1. Verify wallet exists: dir C:\oracle\wallet
2. Check all files extracted: dir C:\oracle\wallet\*.sso
3. Set TNS_ADMIN: setx TNS_ADMIN "C:\oracle\wallet"
4. Restart PowerShell or Command Prompt
```

### Issue: "Service name not found"
```
Error: ORA-12514: TNS:listener does not currently know of service

Solution:
1. Read tnsnames.ora: Get-Content C:\oracle\wallet\tnsnames.ora
2. Use correct service name: adwc_low, adwc_medium, or adwc_high
3. Check connection string in tnsnames.ora
```

### Issue: "Cannot authenticate"
```
Error: ORA-01017: invalid username/password

Solution:
1. Check README.txt for correct password
2. Verify username: admin
3. Check for typos in password
4. Re-download wallet if password wrong multiple times
```

### Issue: "Wallet verification failed"
```
Error: ORA-28759: Failure to open file

Solution:
1. Re-extract wallet: Expand-Archive ... -Force
2. Verify all files exist in C:\oracle\wallet
3. Check file permissions (should not be read-only)
4. Download fresh wallet from Oracle Cloud
```

---

## 📋 Pre-Deployment Checklist

- [ ] Downloaded wallet from Oracle Cloud APEX
- [ ] Extracted wallet to `C:\oracle\wallet\`
- [ ] Verified all 4 files exist (cwallet.sso, ewallet.p12, tnsnames.ora, sqlnet.ora)
- [ ] Read README.txt and noted credentials
- [ ] Set TNS_ADMIN environment variable
- [ ] Tested connection with sqlplus or sqlcl
- [ ] Successfully connected with Python
- [ ] Created config file for app usage
- [ ] Saved wallet credentials securely (not in version control)
- [ ] Updated config.json in your app
- [ ] Tested chatbot with wallet configuration

---

## 🔒 Security Best Practices

```
✅ DO:
- Store wallet in secure location: C:\oracle\wallet
- Use strong passwords for database user
- Store credentials file locally only
- Restrict file permissions to admin only
- Use wallet in production for security
- Regenerate wallet regularly
- Keep wallet backed up securely

❌ DON'T:
- Commit wallet files to Git/GitHub
- Share wallet ZIP files via email
- Store passwords in plain text
- Use wallet files in version control
- Upload wallet to public locations
- Hardcode credentials in code
- Share TNS_ADMIN location with others
```

---

## 📞 Quick Support

**I have my wallet ZIP file:**
→ Follow "5-Minute Quickstart" above

**I can't find my wallet:**
→ Run: `python manage_oracle_wallet.py find`

**I need to verify the wallet:**
→ Run: `python manage_oracle_wallet.py verify`

**I need connection details:**
→ Run: `python manage_oracle_wallet.py display`

**I need to set up Python:**
→ Run: `python manage_oracle_wallet.py config`

**Wallet extraction failed:**
→ Make sure you have Administrator privileges and the ZIP file is not corrupted

---

## 📚 Related Files

- `ORACLE_WALLET_GUIDE.md` - Detailed guide
- `manage_oracle_wallet.ps1` - PowerShell management script
- `manage_oracle_wallet.py` - Python management tool
- `ORACLE_APEX_CHATBOT_IMPLEMENTATION.md` - APEX integration guide
- `APEX_SQL_WORKSHOP_GUIDE.sql` - SQL Workshop setup

---

**Version:** 1.0  
**Last Updated:** 2024-06-26  
**Oracle Database:** 12c+  
**OS:** Windows 10/11
