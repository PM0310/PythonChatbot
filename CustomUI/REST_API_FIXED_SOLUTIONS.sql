-- ============================================================================
-- ORACLE APEX REST API CALL - FIXED WITH ERROR HANDLING & SSL SUPPORT
-- ============================================================================
-- Original Error: ORA-29273: HTTP request failed
-- Common Causes:
-- 1. SSL/TLS certificate issues (self-signed certs)
-- 2. Network ACL not configured
-- 3. Credential not properly set up
-- 4. Network connectivity blocked
-- 5. Firewall or proxy issues
--
-- This script provides 4 solutions
-- ============================================================================

-- ============================================================================
-- SOLUTION 1: BASIC ENHANCED VERSION WITH BETTER ERROR HANDLING
-- ============================================================================

DECLARE
    l_response  CLOB;
    l_status    NUMBER;
    l_payload   CLOB;
    l_url       VARCHAR2(500) := 'https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/';
    l_error_msg VARCHAR2(2000);
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('REST API Call - Sales Order Service');
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('URL: ' || l_url);
    DBMS_OUTPUT.PUT_LINE('Time: ' || TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS'));

    -- ── Build the JSON request body ────────────────────────────────────
    l_payload :=
        '{'
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

    DBMS_OUTPUT.PUT_LINE('Request Payload (first 200 chars): ' || SUBSTR(l_payload, 1, 200));

    -- ── Set request headers ─────────────────────────────────────────────
    DBMS_OUTPUT.PUT_LINE('Setting headers...');
    APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
        p_name_01  => 'Content-Type', p_value_01 => 'application/json',
        p_name_02  => 'Accept',       p_value_02 => 'application/json',
        p_reset    => TRUE
    );

    DBMS_OUTPUT.PUT_LINE('Making REST request...');

    -- ── Make the POST request with the body ──────────────────────────────
    l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
        p_url                  => l_url,
        p_http_method          => 'POST',
        p_body                 => l_payload,
        p_credential_static_id => 'ebscreds',
        p_transfer_timeout     => 120  -- Increased timeout
    );

    l_status := APEX_WEB_SERVICE.G_STATUS_CODE;

    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('RESPONSE');
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('HTTP Status: ' || NVL(TO_CHAR(l_status), 'NULL'));
    DBMS_OUTPUT.PUT_LINE('Response Length: ' || NVL(TO_CHAR(DBMS_LOB.GETLENGTH(l_response)), 'NULL'));
    
    IF l_status IS NULL OR l_status = 0 THEN
        DBMS_OUTPUT.PUT_LINE('⚠️  WARNING: No HTTP status code returned!');
        DBMS_OUTPUT.PUT_LINE('This indicates network connectivity issue.');
    ELSIF l_status >= 200 AND l_status < 300 THEN
        DBMS_OUTPUT.PUT_LINE('✅ SUCCESS (2xx)');
    ELSIF l_status >= 300 AND l_status < 400 THEN
        DBMS_OUTPUT.PUT_LINE('⚠️  REDIRECT (3xx)');
    ELSIF l_status >= 400 AND l_status < 500 THEN
        DBMS_OUTPUT.PUT_LINE('❌ CLIENT ERROR (4xx)');
    ELSIF l_status >= 500 THEN
        DBMS_OUTPUT.PUT_LINE('❌ SERVER ERROR (5xx)');
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(l_response, 1, 1000));

EXCEPTION
    WHEN OTHERS THEN
        l_error_msg := SQLERRM;
        DBMS_OUTPUT.PUT_LINE('========================================');
        DBMS_OUTPUT.PUT_LINE('ERROR OCCURRED');
        DBMS_OUTPUT.PUT_LINE('========================================');
        DBMS_OUTPUT.PUT_LINE('Error Code: ' || SQLCODE);
        DBMS_OUTPUT.PUT_LINE('Error Message: ' || l_error_msg);
        DBMS_OUTPUT.PUT_LINE('HTTP Status: ' || NVL(TO_CHAR(APEX_WEB_SERVICE.G_STATUS_CODE), 'NULL'));
        DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(NVL(l_response, '(empty)'), 1, 500));
        
        IF l_error_msg LIKE '%29273%' THEN
            DBMS_OUTPUT.PUT_LINE('');
            DBMS_OUTPUT.PUT_LINE('💡 SOLUTION: HTTP Request Failed');
            DBMS_OUTPUT.PUT_LINE('   Possible causes:');
            DBMS_OUTPUT.PUT_LINE('   1. Network ACL not configured');
            DBMS_OUTPUT.PUT_LINE('   2. SSL certificate validation failed');
            DBMS_OUTPUT.PUT_LINE('   3. Host unreachable');
            DBMS_OUTPUT.PUT_LINE('   4. Credential not properly set up');
        END IF;
END;
/

-- ============================================================================
-- SOLUTION 2: WITH UTL_HTTP (ALTERNATIVE TO APEX_WEB_SERVICE)
-- ============================================================================
-- Use this if APEX_WEB_SERVICE is not available or troubleshooting

/*
DECLARE
    l_response      CLOB := EMPTY_CLOB();
    l_status        NUMBER;
    l_payload       CLOB;
    l_url           VARCHAR2(500) := 'https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/';
    l_http_request  UTL_HTTP.REQ;
    l_http_response UTL_HTTP.RESP;
    l_buffer        VARCHAR2(4000);
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    -- ── Set wallet location for SSL (if needed) ─────────────────────────
    -- Uncomment if you have SSL certificate issues
    -- UTL_HTTP.SET_WALLET('file:C:\oracle\wallet', 'wallet_password');
    
    -- Allow HTTPS
    UTL_HTTP.SET_TRANSFER_TIMEOUT(120);

    -- ── Build JSON payload ───────────────────────────────────────────────
    l_payload :=
        '{'
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

    DBMS_OUTPUT.PUT_LINE('Using UTL_HTTP...');
    DBMS_OUTPUT.PUT_LINE('URL: ' || l_url);

    -- ── Create HTTP request ──────────────────────────────────────────────
    l_http_request := UTL_HTTP.BEGIN_REQUEST(l_url, 'POST', 'HTTP/1.1');
    
    -- ── Set headers ──────────────────────────────────────────────────────
    UTL_HTTP.SET_HEADER(l_http_request, 'Content-Type', 'application/json');
    UTL_HTTP.SET_HEADER(l_http_request, 'Accept', 'application/json');
    UTL_HTTP.SET_HEADER(l_http_request, 'Content-Length', DBMS_LOB.GETLENGTH(l_payload));

    -- ── Send the body ───────────────────────────────────────────────────
    UTL_HTTP.WRITE_TEXT(l_http_request, l_payload);

    -- ── Get response ────────────────────────────────────────────────────
    l_http_response := UTL_HTTP.GET_RESPONSE(l_http_request);
    l_status := l_http_response.STATUS_CODE;

    DBMS_OUTPUT.PUT_LINE('HTTP Status: ' || l_status);
    DBMS_OUTPUT.PUT_LINE('Reason: ' || l_http_response.REASON_PHRASE);

    -- ── Read response body ──────────────────────────────────────────────
    BEGIN
        LOOP
            UTL_HTTP.READ_TEXT(l_http_response, l_buffer, 4000);
            l_response := l_response || l_buffer;
        END LOOP;
    EXCEPTION
        WHEN UTL_HTTP.END_OF_BODY THEN
            NULL;
    END;

    -- ── Close response ──────────────────────────────────────────────────
    UTL_HTTP.END_RESPONSE(l_http_response);

    DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(l_response, 1, 500));

EXCEPTION
    WHEN UTL_HTTP.REQUEST_FAILED THEN
        DBMS_OUTPUT.PUT_LINE('❌ REQUEST FAILED');
        DBMS_OUTPUT.PUT_LINE('Error: ' || SQLERRM);
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('❌ ERROR: ' || SQLERRM);
        IF l_http_request IS NOT NULL THEN
            BEGIN
                UTL_HTTP.END_REQUEST(l_http_request);
            EXCEPTION
                WHEN OTHERS THEN NULL;
            END;
        END IF;
END;
/
*/

-- ============================================================================
-- SOLUTION 3: WITH NETWORK ACL SETUP (REQUIRED FOR EXTERNAL CALLS)
-- ============================================================================
-- Execute this first if you get ORA-29273
-- This grants the database permission to make external network calls

/*
BEGIN
    -- Create ACL if it doesn't exist
    DBMS_NETWORK_ACL_ADMIN.CREATE_ACL(
        acl        => 'rest_api_acl.xml',
        description=> 'REST API Access',
        principal  => 'APEX_050000',  -- Change to your APEX user
        is_grant   => TRUE,
        privilege  => 'connect'
    );
    
    -- Allow connections to the specific host
    DBMS_NETWORK_ACL_ADMIN.ADD_PRIVILEGE(
        acl       => 'rest_api_acl.xml',
        principal => 'APEX_050000',
        is_grant  => TRUE,
        privilege => 'connect',
        start_date=> NULL,
        end_date  => NULL
    );
    
    -- Assign ACL to host
    DBMS_NETWORK_ACL_ADMIN.ASSIGN_ACL(
        acl  => 'rest_api_acl.xml',
        host => 'cendb.ad.centroid.com',
        lower_port => 4463,
        upper_port => 4463
    );
    
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('✅ Network ACL configured successfully');
    
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error setting ACL: ' || SQLERRM);
END;
/

-- Verify ACL
SELECT * FROM dba_network_acl_privileges WHERE host = 'cendb.ad.centroid.com';
*/

-- ============================================================================
-- SOLUTION 4: CREDENTIAL VERIFICATION & SETUP
-- ============================================================================
-- Use this to verify your APEX credentials are configured

/*
-- Check if credential exists
SELECT credential_name, username 
FROM apex_apexuser_credentials 
WHERE credential_static_id = 'ebscreds';

-- If not found, create a new credential in APEX:
-- 1. Go to APEX Admin > Credentials
-- 2. Create new credential with:
--    - Static ID: ebscreds
--    - Authentication Type: Basic Authentication
--    - Username: your_ebs_user
--    - Password: your_ebs_password

-- Or verify it with this PL/SQL in SQL Workshop:
DECLARE
    l_cred_id NUMBER;
BEGIN
    SELECT credential_id 
    INTO l_cred_id
    FROM apex_apexuser_credentials 
    WHERE credential_static_id = 'ebscreds'
    AND workspace_id = APEX_UTIL.FIND_WORKSPACE_ID('YOUR_WORKSPACE');
    
    DBMS_OUTPUT.PUT_LINE('✅ Credential found: ID=' || l_cred_id);
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        DBMS_OUTPUT.PUT_LINE('❌ Credential not found. Create it in APEX Admin > Credentials');
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('Error: ' || SQLERRM);
END;
/
*/

-- ============================================================================
-- SOLUTION 5: FULL DIAGNOSTIC VERSION - RUN THIS FIRST
-- ============================================================================

DECLARE
    l_response          CLOB;
    l_status            NUMBER;
    l_payload           CLOB;
    l_url               VARCHAR2(500) := 'https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/';
    l_host              VARCHAR2(100) := 'cendb.ad.centroid.com';
    l_port              NUMBER := 4463;
    l_protocol          VARCHAR2(10) := 'HTTPS';
    l_cred_found        NUMBER := 0;
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('DIAGNOSTIC CHECK FOR REST API CALL');
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('');
    
    -- Check 1: Network ACL
    DBMS_OUTPUT.PUT_LINE('1️⃣  Network ACL Check:');
    BEGIN
        SELECT COUNT(*)
        INTO l_cred_found
        FROM dba_network_acl_privileges
        WHERE host LIKE '%' || l_host || '%';
        
        IF l_cred_found > 0 THEN
            DBMS_OUTPUT.PUT_LINE('   ✅ Network ACL configured for ' || l_host);
        ELSE
            DBMS_OUTPUT.PUT_LINE('   ❌ Network ACL NOT configured for ' || l_host);
            DBMS_OUTPUT.PUT_LINE('   💡 Run SOLUTION 3 to configure ACL');
        END IF;
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('   ⚠️  Cannot check ACL: ' || SQLERRM);
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- Check 2: Database version
    DBMS_OUTPUT.PUT_LINE('2️⃣  Database Information:');
    SELECT banner INTO l_response FROM v$version WHERE ROWNUM = 1;
    DBMS_OUTPUT.PUT_LINE('   Version: ' || SUBSTR(l_response, 1, 50));
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- Check 3: APEX availability
    DBMS_OUTPUT.PUT_LINE('3️⃣  APEX Packages:');
    BEGIN
        SELECT 'Available'
        INTO l_response
        FROM user_procedures
        WHERE procedure_name = 'MAKE_REST_REQUEST'
        AND owner = 'APEX_050000';
        DBMS_OUTPUT.PUT_LINE('   ✅ APEX_WEB_SERVICE available');
    EXCEPTION
        WHEN NO_DATA_FOUND THEN
            DBMS_OUTPUT.PUT_LINE('   ❌ APEX_WEB_SERVICE not found');
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- Check 4: Connection details
    DBMS_OUTPUT.PUT_LINE('4️⃣  Connection Details:');
    DBMS_OUTPUT.PUT_LINE('   URL: ' || l_url);
    DBMS_OUTPUT.PUT_LINE('   Host: ' || l_host);
    DBMS_OUTPUT.PUT_LINE('   Port: ' || l_port);
    DBMS_OUTPUT.PUT_LINE('   Protocol: ' || l_protocol);
    
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('RECOMMENDATIONS:');
    DBMS_OUTPUT.PUT_LINE('1. Verify the endpoint URL is correct');
    DBMS_OUTPUT.PUT_LINE('2. Check if credentials are configured in APEX');
    DBMS_OUTPUT.PUT_LINE('3. Ensure Network ACL is set up');
    DBMS_OUTPUT.PUT_LINE('4. Try connection with UTL_HTTP first');
    DBMS_OUTPUT.PUT_LINE('5. Check firewall/proxy settings');
    
END;
/

-- ============================================================================
-- SOLUTION 6: SIMPLE HTTP GET TEST (No body, easier to debug)
-- ============================================================================

/*
DECLARE
    l_response CLOB;
    l_status   NUMBER;
    l_url      VARCHAR2(500) := 'https://httpbin.org/get';  -- Public test endpoint
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('Testing with public endpoint: ' || l_url);
    
    APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
        p_name_01 => 'Content-Type',
        p_value_01 => 'application/json',
        p_reset => TRUE
    );

    l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
        p_url              => l_url,
        p_http_method      => 'GET',
        p_transfer_timeout => 60
    );

    l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
    
    DBMS_OUTPUT.PUT_LINE('Status: ' || l_status);
    DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(l_response, 1, 500));
    
    IF l_status = 200 THEN
        DBMS_OUTPUT.PUT_LINE('✅ Network connectivity OK');
        DBMS_OUTPUT.PUT_LINE('Issue is likely with your specific endpoint');
    ELSE
        DBMS_OUTPUT.PUT_LINE('❌ Network issue detected');
    END IF;
    
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('❌ Error: ' || SQLERRM);
        DBMS_OUTPUT.PUT_LINE('HTTP Status: ' || NVL(TO_CHAR(APEX_WEB_SERVICE.G_STATUS_CODE), 'NULL'));
END;
/
*/

-- ============================================================================
-- SUMMARY OF FIXES
-- ============================================================================

/*
COMMON CAUSES & FIXES:

ERROR: ORA-29273: HTTP request failed
STATUS: NULL

CAUSE 1: Network ACL Not Configured
  FIX: Run SOLUTION 3 (Network ACL Setup)
  Command: Execute the ACL creation script

CAUSE 2: SSL Certificate Issue
  FIX: Use Network Wallet for SSL
  Command: UTL_HTTP.SET_WALLET('file:C:\oracle\wallet', 'password');

CAUSE 3: Credential Not Set Up
  FIX: Configure credential in APEX
  Path: APEX Admin > Workspace Utilities > Credentials
  Create with:
    - Static ID: ebscreds
    - Type: Basic Authentication
    - Username: your_username
    - Password: your_password

CAUSE 4: Firewall/Proxy Blocking
  FIX: Check network connectivity
  Solution 6: Test with public endpoint first

CAUSE 5: Wrong URL or Port
  FIX: Verify URL and port are accessible
  Verify: 'https://cendb.ad.centroid.com:4463' is reachable

VERIFICATION:
1. Run SOLUTION 5 (Diagnostic) to identify issue
2. Run SOLUTION 6 (HTTP GET Test) to verify connectivity
3. Run SOLUTION 1 (Enhanced) with fixes applied
4. If still failing, check database alert log:
   SELECT * FROM v$diag_alert_ext WHERE inst_id = USERENV('INSTANCE') ORDER BY originating_timestamp DESC;
*/
