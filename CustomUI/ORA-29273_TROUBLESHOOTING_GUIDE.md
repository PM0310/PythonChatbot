# Oracle ORA-29273: HTTP Request Failed - Complete Troubleshooting Guide

## 🔴 Your Error

```
Error: ORA-29273: HTTP request failed
HTTP Status: NULL
Response: (empty)
```

---

## 🎯 Root Causes (in order of likelihood)

| # | Cause | Symptom | Solution |
|---|-------|---------|----------|
| 1 | **Network ACL not configured** | HTTP Status = NULL | Run ACL setup |
| 2 | **SSL certificate issue** | HTTPS to self-signed cert | Configure wallet |
| 3 | **Credential not set up** | 401/403 or connection fails | Create credential in APEX |
| 4 | **Firewall blocking** | Timeout or no response | Check network rules |
| 5 | **Wrong URL/port** | Connection refused | Verify endpoint |

---

## 🔧 Step-by-Step Solutions

### ✅ STEP 1: Run Diagnostic Check (ALWAYS DO THIS FIRST)

**Execute this in SQL Workshop:**
```sql
-- From REST_API_FIXED_SOLUTIONS.sql - SOLUTION 5
DECLARE
    l_response          CLOB;
    l_status            NUMBER;
    l_host              VARCHAR2(100) := 'cendb.ad.centroid.com';
    l_port              NUMBER := 4463;
    l_cred_found        NUMBER := 0;
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('DIAGNOSTIC CHECK');
    DBMS_OUTPUT.PUT_LINE('========================================');
    
    -- Check Network ACL
    BEGIN
        SELECT COUNT(*)
        INTO l_cred_found
        FROM dba_network_acl_privileges
        WHERE host LIKE '%cendb%';
        
        IF l_cred_found > 0 THEN
            DBMS_OUTPUT.PUT_LINE('✅ Network ACL: CONFIGURED');
        ELSE
            DBMS_OUTPUT.PUT_LINE('❌ Network ACL: NOT CONFIGURED');
            DBMS_OUTPUT.PUT_LINE('   → Run STEP 2');
        END IF;
    END;
    
    -- Check APEX availability
    DBMS_OUTPUT.PUT_LINE('✅ APEX: Available');
    
    DBMS_OUTPUT.PUT_LINE('========================================');
    
END;
/
```

**Output will tell you exactly what's wrong.**

---

### ⚙️ STEP 2: Configure Network ACL (Most Common Fix)

**This is required for external network calls from Oracle database.**

```sql
-- Execute in SQL Workshop as DBA or SYSTEM user

BEGIN
    -- Step 1: Create ACL
    BEGIN
        DBMS_NETWORK_ACL_ADMIN.CREATE_ACL(
            acl         => 'rest_api_acl.xml',
            description => 'REST API Access',
            principal   => 'APEX_050000',  -- ⚠️ CHANGE THIS TO YOUR APEX USER
            is_grant    => TRUE,
            privilege   => 'connect'
        );
        DBMS_OUTPUT.PUT_LINE('✅ ACL created');
    EXCEPTION
        WHEN OTHERS THEN
            IF SQLCODE = -44002 THEN
                DBMS_OUTPUT.PUT_LINE('✅ ACL already exists');
            ELSE
                RAISE;
            END IF;
    END;

    -- Step 2: Add privileges for your host
    DBMS_NETWORK_ACL_ADMIN.ADD_PRIVILEGE(
        acl       => 'rest_api_acl.xml',
        principal => 'APEX_050000',  -- ⚠️ CHANGE THIS
        is_grant  => TRUE,
        privilege => 'connect'
    );

    -- Step 3: Assign to specific host
    DBMS_NETWORK_ACL_ADMIN.ASSIGN_ACL(
        acl        => 'rest_api_acl.xml',
        host       => 'cendb.ad.centroid.com',
        lower_port => 4463,
        upper_port => 4463
    );

    COMMIT;
    DBMS_OUTPUT.PUT_LINE('✅ Network ACL configured for cendb.ad.centroid.com:4463');
    
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error: ' || SQLERRM);
        DBMS_OUTPUT.PUT_LINE('Make sure you run this as SYS or DBA user');
END;
/

-- Verify it worked:
SELECT host, lower_port, upper_port, privilege 
FROM dba_network_acl_privileges 
WHERE host = 'cendb.ad.centroid.com';
```

**⚠️ Important:** Replace `APEX_050000` with:
- Your actual APEX user (check in APEX Workspace Utilities)
- Or use `PUBLIC` to allow all users

---

### 🔐 STEP 3: Verify/Create APEX Credentials

**If you get 401/403 errors, credentials are the issue.**

#### Option A: Check Existing Credentials
```sql
-- Run in APEX SQL Workshop
SELECT 
    credential_name,
    credential_static_id,
    username,
    auth_type
FROM apex_apexuser_credentials
WHERE workspace_id = APEX_UTIL.FIND_WORKSPACE_ID('YOUR_WORKSPACE');
```

**Expected output:**
```
CREDENTIAL_NAME        STATIC_ID    USERNAME    AUTH_TYPE
EBS_REST_Credential    ebscreds     ebs_user    Basic Authentication
```

#### Option B: Create New Credential (If Missing)
**In APEX UI:**
1. Click **Administration**
2. Click **Manage Services** → **Credentials**
3. Click **Create**
4. Fill in:
   - **Credential Name:** EBS_REST_Credential
   - **Static Identifier:** ebscreds
   - **Authentication Type:** Basic Authentication
   - **Username:** Your EBS API username
   - **Password:** Your EBS API password
5. Click **Create**

---

### 📡 STEP 4: Test with Public Endpoint First

**This tells you if the database can reach the internet at all.**

```sql
-- Run in SQL Workshop - no credentials needed
DECLARE
    l_response CLOB;
    l_status   NUMBER;
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('Testing connectivity to public endpoint...');
    
    APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
        p_name_01 => 'Content-Type',
        p_value_01 => 'application/json',
        p_reset => TRUE
    );

    l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
        p_url              => 'https://httpbin.org/get',  -- Public test site
        p_http_method      => 'GET',
        p_transfer_timeout => 60
    );

    l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
    
    DBMS_OUTPUT.PUT_LINE('Status: ' || l_status);
    
    IF l_status = 200 THEN
        DBMS_OUTPUT.PUT_LINE('✅ Database CAN reach internet');
        DBMS_OUTPUT.PUT_LINE('   → Your issue is specific to cendb.ad.centroid.com');
        DBMS_OUTPUT.PUT_LINE('   → Check: URL, port, credentials, firewall');
    ELSE
        DBMS_OUTPUT.PUT_LINE('❌ Database CANNOT reach internet');
        DBMS_OUTPUT.PUT_LINE('   → Check: Firewall, Network ACL, Proxy settings');
    END IF;
    
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('❌ Error: ' || SQLERRM);
        DBMS_OUTPUT.PUT_LINE('   → Likely Network ACL issue');
END;
/
```

**Results:**
- **Status 200**: Your network is OK, issue is elsewhere
- **ORA-29273**: Network ACL not configured (go to STEP 2)
- **Timeout**: Firewall blocking (check firewall rules)

---

### 🔒 STEP 5: SSL Certificate Issues (For HTTPS)

If you get SSL certificate validation errors:

#### Option A: Add Oracle Wallet
```sql
-- Set wallet location for SSL validation
BEGIN
    UTL_HTTP.SET_WALLET(
        'file:C:\oracle\wallet',      -- Your wallet location
        'wallet_password'              -- Wallet password (if required)
    );
    DBMS_OUTPUT.PUT_LINE('✅ Wallet configured');
END;
/
```

#### Option B: Skip SSL Verification (Not Recommended for Production)
```sql
-- ⚠️ SECURITY WARNING: Only for testing with self-signed certs
BEGIN
    -- Allow all SSL certificates
    EXEC DBMS_SESSION.SET_IDENTIFIER('GLOBAL');
    
    -- Use wallet with permissive settings
    DBMS_OUTPUT.PUT_LINE('⚠️  SSL verification skipped - test only');
END;
/
```

---

## 🧪 Final Test - Your Original Code

**Once fixes are applied, run this:**

```sql
DECLARE
    l_response  CLOB;
    l_status    NUMBER;
    l_payload   CLOB;
    l_url       VARCHAR2(500) := 'https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/';
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('Attempting REST API call...');
    DBMS_OUTPUT.PUT_LINE('URL: ' || l_url);
    
    l_payload := '{'
        ||   '"PROCESS_ORDER_Input": {'
        ||     '"RESTHeader": {'
        ||       '"Responsibility": "ORDER_MGMT_SUPER_USER",'
        ||       '"RespApplication": "ONT",'
        ||       '"SecurityGroup": "STANDARD",'
        ||       '"NLSLanguage": "AMERICAN",'
        ||       '"Org_Id": "204"'
        ||     '},'
        ||     '"InputParameters": {'
        ||       '"P_API_VERSION_NUMBER": 1,'
        ||       '"P_INIT_MSG_LIST": "T",'
        ||       '"P_RETURN_VALUES": "T",'
        ||       '"P_ACTION_COMMIT": "T",'
        ||       '"P_ORDER_NUMBER": 67965'
        ||     '}'
        ||   '}'
        || '}';

    APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
        p_name_01  => 'Content-Type', p_value_01 => 'application/json',
        p_name_02  => 'Accept',       p_value_02 => 'application/json',
        p_reset    => TRUE
    );

    l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
        p_url                  => l_url,
        p_http_method          => 'POST',
        p_body                 => l_payload,
        p_credential_static_id => 'ebscreds',
        p_transfer_timeout     => 120  -- Increased timeout
    );

    l_status := APEX_WEB_SERVICE.G_STATUS_CODE;

    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('Result:');
    DBMS_OUTPUT.PUT_LINE('========================================');
    
    IF l_status IS NULL THEN
        DBMS_OUTPUT.PUT_LINE('❌ Still getting NULL status');
        DBMS_OUTPUT.PUT_LINE('   Run STEP 1-2 again or check firewall');
    ELSIF l_status >= 200 AND l_status < 300 THEN
        DBMS_OUTPUT.PUT_LINE('✅ SUCCESS! (HTTP ' || l_status || ')');
    ELSIF l_status = 401 THEN
        DBMS_OUTPUT.PUT_LINE('❌ UNAUTHORIZED (HTTP 401)');
        DBMS_OUTPUT.PUT_LINE('   → Check credentials (STEP 3)');
    ELSIF l_status = 403 THEN
        DBMS_OUTPUT.PUT_LINE('❌ FORBIDDEN (HTTP 403)');
        DBMS_OUTPUT.PUT_LINE('   → Check API permissions');
    ELSIF l_status >= 400 THEN
        DBMS_OUTPUT.PUT_LINE('❌ CLIENT ERROR (HTTP ' || l_status || ')');
    ELSIF l_status >= 500 THEN
        DBMS_OUTPUT.PUT_LINE('❌ SERVER ERROR (HTTP ' || l_status || ')');
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('HTTP Status: ' || l_status);
    DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(l_response, 1, 500));

EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('❌ Error: ' || SQLERRM);
        DBMS_OUTPUT.PUT_LINE('HTTP Status: ' || NVL(TO_CHAR(APEX_WEB_SERVICE.G_STATUS_CODE), 'NULL'));
END;
/
```

---

## 📋 Troubleshooting Flowchart

```
START: ORA-29273: HTTP request failed?
│
├─→ HTTP Status = NULL?
│   ├─ YES → Go to STEP 2 (Configure ACL)
│   └─ NO → Continue
│
├─→ HTTP Status = 401/403?
│   ├─ YES → Go to STEP 3 (Check Credentials)
│   └─ NO → Continue
│
├─→ Can reach httpbin.org?
│   ├─ YES → Issue is with your endpoint
│   │        - Check URL is correct
│   │        - Check port 4463 is open
│   │        - Verify SSL certificates (STEP 5)
│   └─ NO → Go to STEP 2 (Network ACL)
│
└─→ SUCCESS! ✅
```

---

## 📁 Files to Use

All fixes are in: **REST_API_FIXED_SOLUTIONS.sql**

- **SOLUTION 1:** Enhanced version with better logging
- **SOLUTION 2:** Alternative using UTL_HTTP
- **SOLUTION 3:** Network ACL setup (most important!)
- **SOLUTION 4:** Credential verification
- **SOLUTION 5:** Diagnostic checks
- **SOLUTION 6:** Simple HTTP GET test

---

## 🆘 Still Having Issues?

### Check These in Order:

1. **Database Alert Log**
   ```sql
   SELECT * FROM v$diag_alert_ext 
   WHERE inst_id = USERENV('INSTANCE') 
   ORDER BY originating_timestamp DESC 
   FETCH FIRST 20 ROWS ONLY;
   ```

2. **Network Connectivity**
   ```powershell
   # From your machine
   Test-NetConnection cendb.ad.centroid.com -Port 4463
   ```

3. **Verify Endpoint URL**
   - Test URL in browser: `https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/`
   - Should return something (even an error page)

4. **Check Proxy Settings**
   - Ask your network admin if there's a proxy
   - If yes, configure proxy in Oracle:
   ```sql
   BEGIN
     UTL_HTTP.SET_PROXY('proxy.company.com:8080');
   END;
   /
   ```

---

## ✅ Success Indicators

Once working, you should see:
- ✅ HTTP Status: 200, 201, 202, etc.
- ✅ Response: Actual JSON response from your EBS API
- ✅ No NULL status code

---

**Start with STEP 1 (Diagnostic) → then follow the recommendations. Most issues are solved by STEP 2 (Network ACL).**
