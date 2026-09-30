# Oracle Wallet Setup - Complete Step-by-Step Guide

## 🎯 Your Complete Roadmap

You now have everything needed to work with Oracle Wallets for APEX, SQLcl, and Python. Follow this guide step-by-step.

---

## 📋 Files Created for You

### Documentation
1. **ORACLE_WALLET_GUIDE.md** - Comprehensive 15-section guide
2. **ORACLE_WALLET_QUICK_REFERENCE.md** - Quick reference with checklists
3. **This file** - Step-by-step walkthrough

### Tools
1. **manage_oracle_wallet.ps1** - PowerShell interactive tool
2. **manage_oracle_wallet.py** - Python utility for wallet management

### Existing Files (from previous requests)
1. **chatbot_plsql.sql** - PL/SQL chatbot
2. **chatbot_extended_plsql.sql** - Extended PL/SQL features
3. **APEX_SQL_WORKSHOP_GUIDE.sql** - APEX integration guide

---

## 🚀 QUICK START (Choose Your Path)

### Path A: I Have a Wallet ZIP File
```
1. Find your wallet ZIP file
2. Run: python manage_oracle_wallet.py extract C:\path\to\Wallet_*.zip
3. Done! Wallet is ready in C:\oracle\wallet
```

### Path B: I Need to Download Wallet First
```
1. Go to Oracle Cloud APEX
2. Click Database → Download Wallet
3. Save the ZIP file
4. Run: python manage_oracle_wallet.py extract C:\path\to\Wallet_*.zip
5. Done!
```

### Path C: I Want Interactive Setup
```
1. Open PowerShell
2. Run: powershell -ExecutionPolicy Bypass -File manage_oracle_wallet.ps1
3. Choose option 1: Extract wallet from ZIP
4. Follow prompts
5. Done!
```

---

## 📝 STEP-BY-STEP WALKTHROUGH

### STEP 1: Get Your Wallet File
**Goal:** Download wallet from Oracle Cloud

#### If Using Oracle Cloud APEX:
1. Open your Oracle Cloud console
2. Go to **Autonomous Database** or **APEX Service**
3. Select your database/workspace
4. Click **Database Actions** → **Download Client Credentials**
5. Choose **Wallet** option
6. Download the ZIP file
7. Note the location (usually C:\Users\YourName\Downloads\Wallet_*.zip)

#### If Already Have Downloaded:
1. Find the file: `Wallet_ADW4Workshops.zip` or similar
2. Note its location

---

### STEP 2: Extract Wallet Files

#### Option A: Use Python Tool (Recommended)
```powershell
cd C:\Users\pavan.maccha\Desktop\Python\CustomUI

python manage_oracle_wallet.py extract "C:\Users\pavan.maccha\Downloads\Wallet_ADW4Workshops.zip"
```

**Output:**
```
📦 Extracting wallet from: C:\Users\...\Wallet_ADW4Workshops.zip
✅ Wallet extracted to: C:\oracle\wallet

📋 Verifying wallet files...
  ✅ cwallet.sso (2,048 bytes)
  ✅ ewallet.p12 (2,048 bytes)
  ✅ tnsnames.ora (1,024 bytes)
  ✅ sqlnet.ora (256 bytes)

✅ All required wallet files found!
```

#### Option B: Use PowerShell
```powershell
Expand-Archive -Path "C:\Users\pavan.maccha\Downloads\Wallet_ADW4Workshops.zip" `
               -DestinationPath "C:\oracle\wallet" `
               -Force
```

---

### STEP 3: Verify Wallet Files

#### Check Files Exist:
```powershell
Get-ChildItem C:\oracle\wallet

# Output should show:
# cwallet.sso
# ewallet.p12
# tnsnames.ora
# sqlnet.ora
# README.txt
```

#### Or Use Python:
```powershell
python manage_oracle_wallet.py verify
```

---

### STEP 4: Read Wallet Details

#### Most Important: README.txt
```powershell
Get-Content C:\oracle\wallet\README.txt
```

**Look for:**
```
Your new ATP database is available.
Default username: admin
Default password: <copy this carefully>
Connection strings:
  adwc_low
  adwc_medium
  adwc_high
  adwc_tp
```

**Save this password securely!** You'll need it to connect.

#### View Connection Strings:
```powershell
Get-Content C:\oracle\wallet\tnsnames.ora
```

**Look for:**
```
adwc_low = (description=
  (retry_count=20)
  (address=(protocol=tcps)
  (port=1522)
  (host=adb.us-phoenix-1.oraclecloud.com))
  ...
```

**Key details:**
- **Host:** adb.us-phoenix-1.oraclecloud.com
- **Port:** 1522
- **Services:** adwc_low, adwc_medium, adwc_high, adwc_tp

#### View Configuration:
```powershell
python manage_oracle_wallet.py display
```

---

### STEP 5: Set Environment Variables

#### Option A: Current Session Only (Temporary)
```powershell
$env:TNS_ADMIN = "C:\oracle\wallet"

# Verify
echo $env:TNS_ADMIN
# Output: C:\oracle\wallet
```

#### Option B: Permanent (All Future Sessions)
```powershell
[Environment]::SetEnvironmentVariable(
    "TNS_ADMIN",
    "C:\oracle\wallet",
    [EnvironmentVariableTarget]::User
)
```

**OR use Python:**
```powershell
python manage_oracle_wallet.py env
```

**After setting permanent environment:**
- Close all PowerShell/Command windows
- Open a new one (it will load the new environment)
- Verify: `echo $env:TNS_ADMIN`

---

### STEP 6: Create Configuration File

#### Generate Config for Your App:
```powershell
python manage_oracle_wallet.py config
```

**Creates:** `C:\oracle\wallet\wallet_config.json`

**Contains:**
```json
{
  "wallet": {
    "location": "C:\\oracle\\wallet",
    "verified": true
  },
  "connection": {
    "host": "adb.us-phoenix-1.oraclecloud.com",
    "port": 1522,
    "services": ["adwc_low", "adwc_medium", "adwc_high", "adwc_tp"],
    "default_service": "adwc_low"
  },
  "database": {
    "user": "admin"
  }
}
```

---

### STEP 7: Test Connection

#### Test 1: Check with Python
```python
import oracledb
import os

os.environ['TNS_ADMIN'] = r'C:\oracle\wallet'

try:
    conn = oracledb.connect(
        dsn='adwc_low',
        user='admin',
        password='YourPassword123'  # From README.txt
    )
    print("✅ Connection successful!")
    
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dual")
    result = cursor.fetchone()
    print(f"Query result: {result}")
    
    conn.close()
except Exception as e:
    print(f"❌ Connection failed: {e}")
```

#### Test 2: Check with SQL*Plus (if installed)
```powershell
sqlplus admin@adwc_low
# Enter password from README.txt
SQL> SELECT * FROM dual;
```

#### Test 3: Check with SQLcl (if installed)
```powershell
sql admin@adwc_low
# Enter password from README.txt
sql> SELECT * FROM dual;
```

---

### STEP 8: Update Your Python App

#### Option A: Update config.json
```json
{
  "database": {
    "use_wallet": true,
    "wallet_location": "C:\\oracle\\wallet",
    "dsn": "adwc_low",
    "user": "admin",
    "password": "YourPassword123"
  }
}
```

#### Option B: Update Python Code (app7.py)
```python
import oracledb
import os
import json

# Set wallet location
os.environ['TNS_ADMIN'] = r'C:\oracle\wallet'

# Load config
with open('config.json', 'r') as f:
    config = json.load(f)

# Connect with wallet
db_config = config.get('database', {})
connection = oracledb.connect(
    dsn=db_config.get('dsn', 'adwc_low'),
    user=db_config.get('user', 'admin'),
    password=db_config.get('password')
)

print("✅ Connected to Oracle Database with wallet!")
```

---

### STEP 9: Verify All Systems

#### Checklist:
```powershell
# 1. Check wallet files
Test-Path C:\oracle\wallet\cwallet.sso         # Should be True
Test-Path C:\oracle\wallet\ewallet.p12         # Should be True
Test-Path C:\oracle\wallet\tnsnames.ora        # Should be True
Test-Path C:\oracle\wallet\sqlnet.ora          # Should be True

# 2. Check environment variable
$env:TNS_ADMIN                                  # Should be C:\oracle\wallet

# 3. Check Python connection
python -c "import oracledb; print('✅ oracledb available')"

# 4. Run wallet verification
python manage_oracle_wallet.py verify           # Should show all ✅
```

---

### STEP 10: Deploy to APEX (Optional)

If using Oracle APEX in SQL Workshop:

1. Use wallet connection in APEX dashboard
2. Create database connection in APEX using:
   - **Database:** adwc_low
   - **Username:** admin
   - **Wallet Location:** C:\oracle\wallet

2. Test connection
3. Create APEX applications using the wallet

---

## 🎯 Common Scenarios

### Scenario 1: Running Your Chatbot with Wallet
```powershell
# Set environment
$env:TNS_ADMIN = "C:\oracle\wallet"

# Update config.json with:
# - wallet_location: C:\oracle\wallet
# - dsn: adwc_low
# - user: admin
# - password: <from README>

# Run your app
python app7.py
```

### Scenario 2: Using SQLcl to Deploy PL/SQL
```powershell
# Set environment
$env:TNS_ADMIN = "C:\oracle\wallet"

# Connect with SQLcl
sql admin@adwc_low

# Run PL/SQL scripts
@chatbot_plsql.sql
@chatbot_extended_plsql.sql

# Test
BEGIN
  chatbot_pkg.process_user_message(...);
END;
/
```

### Scenario 3: Setting Up APEX with Wallet
```
1. In Oracle Cloud, go to APEX Service
2. Create workspace with wallet credentials
3. In APEX SQL Workshop:
   - Set TNS_ADMIN environment variable
   - Use adwc_low as connection
   - Execute PL/SQL packages
```

---

## 📊 Wallet Information Template

**SAVE THIS SECURELY (not in Git):**

```
╔════════════════════════════════════════╗
║     ORACLE WALLET CONFIGURATION        ║
╚════════════════════════════════════════╝

WALLET DETAILS:
  Location: C:\oracle\wallet
  Status: ✅ Extracted and Verified
  Files: 5 (cwallet.sso, ewallet.p12, tnsnames.ora, sqlnet.ora, README.txt)

DATABASE CREDENTIALS:
  Username: admin
  Password: [KEEP SECURE - from README.txt]
  Service: adwc_low (default)
  Database: Oracle Autonomous Data Warehouse

NETWORK DETAILS:
  Host: adb.us-phoenix-1.oraclecloud.com
  Port: 1522
  Protocol: TCPS (SSL/TLS encrypted)

ENVIRONMENT:
  TNS_ADMIN: C:\oracle\wallet
  ORACLE_HOME: C:\oracle\client

CONNECTION STRINGS:
  SQL*Plus: sqlplus admin@adwc_low
  SQLcl: sql admin@adwc_low
  Python: dsn='adwc_low', user='admin'
  APEX: Database connection with wallet

AVAILABLE SERVICES:
  • adwc_low   - For light traffic
  • adwc_medium - For medium traffic
  • adwc_high  - For high traffic
  • adwc_tp    - For transaction processing

CONFIGURATIONS:
  ✅ Environment variables set
  ✅ Python connection tested
  ✅ Wallet verified
  ✅ config.json updated
  ✅ Ready for deployment

LAST UPDATED: 2024-06-26
```

---

## ✅ Final Verification Checklist

Before declaring success:

- [ ] Wallet ZIP file downloaded
- [ ] Wallet extracted to C:\oracle\wallet
- [ ] All 5 files present (cwallet.sso, ewallet.p12, tnsnames.ora, sqlnet.ora, README.txt)
- [ ] README.txt read and password noted
- [ ] tnsnames.ora checked for connection details
- [ ] TNS_ADMIN environment variable set to C:\oracle\wallet
- [ ] Python tested and connected successfully
- [ ] config.json updated with wallet details
- [ ] Wallet information template saved securely
- [ ] Configuration file created (wallet_config.json)
- [ ] Documentation reviewed

**Status: ✅ READY FOR PRODUCTION**

---

## 🆘 Quick Troubleshooting

| Issue | Solution |
|-------|----------|
| Can't find wallet file | Run: `python manage_oracle_wallet.py find` |
| Extraction failed | Check ZIP file integrity, try again |
| Connection timeout | Set TNS_ADMIN environment variable |
| Bad password | Check README.txt again, copy exactly |
| Service not found | Verify tnsnames.ora contains your service |
| Environment not working | Close and reopen PowerShell/terminal |

---

## 🔗 Related Resources

- **Full Documentation:** ORACLE_WALLET_GUIDE.md
- **Quick Reference:** ORACLE_WALLET_QUICK_REFERENCE.md
- **PowerShell Tool:** manage_oracle_wallet.ps1
- **Python Tool:** manage_oracle_wallet.py
- **Chatbot Setup:** ORACLE_APEX_CHATBOT_IMPLEMENTATION.md
- **APEX SQL:** APEX_SQL_WORKSHOP_GUIDE.sql

---

## 📞 Support Commands

```powershell
# Get help
python manage_oracle_wallet.py --help

# Display all details
python manage_oracle_wallet.py display

# Extract wallet interactively
powershell -ExecutionPolicy Bypass -File manage_oracle_wallet.ps1

# Create config
python manage_oracle_wallet.py config

# Find wallet on system
python manage_oracle_wallet.py find
```

---

**Created:** 2024-06-26  
**Version:** 1.0  
**Status:** ✅ Complete and Ready to Use  
**Next Step:** Start with STEP 1 above
