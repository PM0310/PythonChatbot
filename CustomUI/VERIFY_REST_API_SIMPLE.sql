-- ============================================================================
-- SIMPLIFIED VERIFICATION SCRIPT (Works without DBA privileges)
-- Run this to test REST API connectivity
-- ============================================================================

DECLARE
    l_response          CLOB;
    l_status            NUMBER;
    l_test_passed       NUMBER := 0;
    l_detailed_code     NUMBER;
    l_detailed_errm     VARCHAR2(32767);
    -- Wallet settings for outbound HTTPS from APEX/DB
    -- NOTE: Use server-side path with file: prefix, for example:
    --       file:/u01/app/oracle/admin/DBNAME/wallet
    l_wallet_path       VARCHAR2(1000) := 'file:/u01/app/oracle/admin/DBNAME/wallet';
    l_wallet_pwd        VARCHAR2(255)  := 'change_me';

    PROCEDURE print_http_diagnostics(p_host IN VARCHAR2, p_port IN NUMBER) IS
    BEGIN
        DBMS_OUTPUT.PUT_LINE('   SQLCODE: ' || SQLCODE);
        DBMS_OUTPUT.PUT_LINE('   SQLERRM: ' || SQLERRM);

        BEGIN
            l_detailed_code := UTL_HTTP.GET_DETAILED_SQLCODE;
            l_detailed_errm := UTL_HTTP.GET_DETAILED_SQLERRM;
            IF l_detailed_code IS NOT NULL THEN
                DBMS_OUTPUT.PUT_LINE('   UTL_HTTP Detailed Code: ' || l_detailed_code);
            END IF;
            IF l_detailed_errm IS NOT NULL THEN
                DBMS_OUTPUT.PUT_LINE('   UTL_HTTP Detailed Error: ' || l_detailed_errm);
            END IF;
        EXCEPTION
            WHEN OTHERS THEN
                NULL;
        END;

        IF SQLCODE = -24247 OR l_detailed_code = 24247 THEN
            DBMS_OUTPUT.PUT_LINE('   🔒 ACL ERROR (ORA-24247): Network access denied by ACL.');
            DBMS_OUTPUT.PUT_LINE('   DBA ACTION (run as SYS/DBA):');
            DBMS_OUTPUT.PUT_LINE('   BEGIN');
            DBMS_OUTPUT.PUT_LINE('     DBMS_NETWORK_ACL_ADMIN.APPEND_HOST_ACE(');
            DBMS_OUTPUT.PUT_LINE('       host => ''' || p_host || ''',');
            DBMS_OUTPUT.PUT_LINE('       lower_port => ' || p_port || ',');
            DBMS_OUTPUT.PUT_LINE('       upper_port => ' || p_port || ',');
            DBMS_OUTPUT.PUT_LINE('       ace => XS$ACE_TYPE(');
            DBMS_OUTPUT.PUT_LINE('         privilege_list => XS$NAME_LIST(''http''),');
            DBMS_OUTPUT.PUT_LINE('         principal_name => ''' || SYS_CONTEXT('USERENV','SESSION_USER') || ''',');
            DBMS_OUTPUT.PUT_LINE('         principal_type => XS_ACL.PTYPE_DB));');
            DBMS_OUTPUT.PUT_LINE('   END;');
            DBMS_OUTPUT.PUT_LINE('   /');
        ELSIF SQLCODE = -29024 OR l_detailed_code = 29024 THEN
            DBMS_OUTPUT.PUT_LINE('   📜 CERTIFICATE ERROR (ORA-29024): wallet is missing server cert chain.');
        ELSIF SQLCODE = -28759 OR l_detailed_code = 28759 THEN
            DBMS_OUTPUT.PUT_LINE('   👛 WALLET ERROR (ORA-28759): wallet path/password is invalid or inaccessible.');
        END IF;
    END;
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    DBMS_OUTPUT.PUT_LINE('╔═══════════════════════════════════════════════════════════╗');
    DBMS_OUTPUT.PUT_LINE('║  REST API CONNECTIVITY TEST (Simplified)                   ║');
    DBMS_OUTPUT.PUT_LINE('╚═══════════════════════════════════════════════════════════╝');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Wallet Path: ' || l_wallet_path);
    DBMS_OUTPUT.PUT_LINE('Wallet Pwd : ' || CASE WHEN l_wallet_pwd IS NULL OR l_wallet_pwd = 'change_me' THEN '[NOT SET]' ELSE '[SET]' END);
    IF l_wallet_pwd IS NULL OR l_wallet_pwd = 'change_me' THEN
        DBMS_OUTPUT.PUT_LINE('⚠️  Wallet password is not configured. Set l_wallet_pwd before HTTPS testing.');
    END IF;
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- TEST 1: Public Endpoint (httpbin.org)
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('TEST 1: Public Endpoint (httpbin.org)');
    DBMS_OUTPUT.PUT_LINE('─────────────────────────────────────────────────');
    
    BEGIN
        DBMS_OUTPUT.PUT_LINE('Connecting to https://httpbin.org/get...');
        
        APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
            p_name_01 => 'Content-Type',
            p_value_01 => 'application/json',
            p_reset => TRUE
        );
        
        l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
            p_url              => 'https://httpbin.org/get',
            p_http_method      => 'GET',
            p_wallet_path      => l_wallet_path,
            p_wallet_pwd       => l_wallet_pwd,
            p_transfer_timeout => 30
        );
        
        l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
        
        DBMS_OUTPUT.PUT_LINE('Status: ' || NVL(TO_CHAR(l_status), 'NULL'));
        
        IF l_status = 200 THEN
            DBMS_OUTPUT.PUT_LINE('✅ PASS: Public internet connectivity works!');
            DBMS_OUTPUT.PUT_LINE('   Response size: ' || DBMS_LOB.GETLENGTH(l_response) || ' bytes');
            l_test_passed := l_test_passed + 1;
        ELSIF l_status IS NULL THEN
            DBMS_OUTPUT.PUT_LINE('❌ FAIL: No response (NULL status)');
            DBMS_OUTPUT.PUT_LINE('   Likely causes:');
            DBMS_OUTPUT.PUT_LINE('   1. Network ACL not configured');
            DBMS_OUTPUT.PUT_LINE('   2. Firewall blocking connections');
            DBMS_OUTPUT.PUT_LINE('   3. Network connectivity issue');
        ELSE
            DBMS_OUTPUT.PUT_LINE('⚠️  Got HTTP ' || l_status);
        END IF;
        
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('❌ FAIL: ' || SQLERRM);
            print_http_diagnostics('httpbin.org', 443);
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- TEST 2: Your EBS Endpoint (cendb.ad.centroid.com:4463)
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('TEST 2: Your EBS Endpoint (cendb.ad.centroid.com:4463)');
    DBMS_OUTPUT.PUT_LINE('─────────────────────────────────────────────────');
    
    BEGIN
        DBMS_OUTPUT.PUT_LINE('Connecting to https://cendb.ad.centroid.com:4463/...');
        
        APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
            p_name_01 => 'Content-Type',
            p_value_01 => 'application/json',
            p_reset => TRUE
        );
        
        l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
            p_url              => 'https://cendb.ad.centroid.com:4463/',
            p_http_method      => 'GET',
            p_wallet_path      => l_wallet_path,
            p_wallet_pwd       => l_wallet_pwd,
            p_transfer_timeout => 30
        );
        
        l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
        
        DBMS_OUTPUT.PUT_LINE('Status: ' || NVL(TO_CHAR(l_status), 'NULL'));
        
        IF l_status IS NOT NULL THEN
            DBMS_OUTPUT.PUT_LINE('✅ PASS: Got response from endpoint!');
            DBMS_OUTPUT.PUT_LINE('   HTTP Status: ' || l_status);
            DBMS_OUTPUT.PUT_LINE('   Response size: ' || DBMS_LOB.GETLENGTH(l_response) || ' bytes');
            l_test_passed := l_test_passed + 1;
        ELSIF l_status IS NULL THEN
            DBMS_OUTPUT.PUT_LINE('❌ FAIL: No response (NULL status)');
            DBMS_OUTPUT.PUT_LINE('   This means the endpoint is unreachable');
        ELSE
            DBMS_OUTPUT.PUT_LINE('⚠️  Got HTTP ' || l_status);
            DBMS_OUTPUT.PUT_LINE('   Response: ' || SUBSTR(l_response, 1, 200));
        END IF;
        
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('❌ FAIL: ' || SQLERRM);
            print_http_diagnostics('cendb.ad.centroid.com', 4463);
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- TEST 3: Your Full REST API Call
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('TEST 3: Your Full REST API Call');
    DBMS_OUTPUT.PUT_LINE('─────────────────────────────────────────────────');
    
    BEGIN
        DECLARE
            l_payload   CLOB;
            l_url       VARCHAR2(500) := 'https://cendb.ad.centroid.com:4463/webservices/rest/sales_order/GET_ORDER/';
        BEGIN
            DBMS_OUTPUT.PUT_LINE('Building JSON payload...');
            
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
            
            DBMS_OUTPUT.PUT_LINE('Payload size: ' || DBMS_LOB.GETLENGTH(l_payload) || ' bytes');
            DBMS_OUTPUT.PUT_LINE('Sending POST request...');
            
            APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
                p_name_01 => 'Content-Type',
                p_value_01 => 'application/json',
                p_name_02 => 'Accept',
                p_value_02 => 'application/json',
                p_reset => TRUE
            );
            
            l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
                p_url                  => l_url,
                p_http_method          => 'POST',
                p_body                 => l_payload,
                p_credential_static_id => 'ebscreds',
                p_wallet_path          => l_wallet_path,
                p_wallet_pwd           => l_wallet_pwd,
                p_transfer_timeout     => 60
            );
            
            l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
            
            DBMS_OUTPUT.PUT_LINE('Status: ' || NVL(TO_CHAR(l_status), 'NULL'));
            
            IF l_status >= 200 AND l_status < 300 THEN
                DBMS_OUTPUT.PUT_LINE('✅ SUCCESS! (HTTP ' || l_status || ')');
                DBMS_OUTPUT.PUT_LINE('   Response: ' || SUBSTR(l_response, 1, 300));
                l_test_passed := l_test_passed + 1;
            ELSIF l_status = 401 OR l_status = 403 THEN
                DBMS_OUTPUT.PUT_LINE('⚠️  Authentication error (HTTP ' || l_status || ')');
                DBMS_OUTPUT.PUT_LINE('   💡 FIX: Check credentials in APEX Admin > Credentials');
            ELSIF l_status IS NULL THEN
                DBMS_OUTPUT.PUT_LINE('❌ FAIL: No response (Network issue)');
                DBMS_OUTPUT.PUT_LINE('   💡 FIX: See TEST 1 and TEST 2 results for hints');
            ELSE
                DBMS_OUTPUT.PUT_LINE('⚠️  Got HTTP ' || l_status);
                DBMS_OUTPUT.PUT_LINE('   Response: ' || SUBSTR(l_response, 1, 300));
            END IF;
        END;
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('❌ FAIL: ' || SQLERRM);
            print_http_diagnostics('cendb.ad.centroid.com', 4463);
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- SUMMARY
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('╔═══════════════════════════════════════════════════════════╗');
    DBMS_OUTPUT.PUT_LINE('║  RESULTS SUMMARY                                          ║');
    DBMS_OUTPUT.PUT_LINE('╚═══════════════════════════════════════════════════════════╝');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Tests Passed: ' || l_test_passed || '/3');
    DBMS_OUTPUT.PUT_LINE('');
    
    IF l_test_passed = 3 THEN
        DBMS_OUTPUT.PUT_LINE('✅ ALL TESTS PASSED!');
        DBMS_OUTPUT.PUT_LINE('Your REST API implementation is working correctly.');
    ELSIF l_test_passed = 2 THEN
        DBMS_OUTPUT.PUT_LINE('⚠️  PARTIAL SUCCESS');
        DBMS_OUTPUT.PUT_LINE('Public connectivity works, but your endpoint needs fixes.');
        DBMS_OUTPUT.PUT_LINE('Check: URL, credentials, firewall rules');
    ELSIF l_test_passed = 1 THEN
        DBMS_OUTPUT.PUT_LINE('❌ NETWORK ISSUE DETECTED');
        DBMS_OUTPUT.PUT_LINE('You can reach some services but not all.');
        DBMS_OUTPUT.PUT_LINE('Probable causes:');
        DBMS_OUTPUT.PUT_LINE('  1. Network ACL needs configuration');
        DBMS_OUTPUT.PUT_LINE('  2. Firewall blocking specific ports/hosts');
        DBMS_OUTPUT.PUT_LINE('  3. Endpoint is unreachable/offline');
    ELSE
        DBMS_OUTPUT.PUT_LINE('❌ COMPLETE FAILURE');
        DBMS_OUTPUT.PUT_LINE('Cannot reach any external services.');
        DBMS_OUTPUT.PUT_LINE('This is likely a Network ACL or firewall issue.');
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('NEXT STEPS:');
        DBMS_OUTPUT.PUT_LINE('1. Contact your DBA about configuring Network ACL');
        DBMS_OUTPUT.PUT_LINE('2. Check if your Oracle instance has network access');
        DBMS_OUTPUT.PUT_LINE('3. See: ORA-29273_TROUBLESHOOTING_GUIDE.md for detailed steps');
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('═════════════════════════════════════════════════════════════');

EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('❌ Unexpected error: ' || SQLERRM);
END;
/
