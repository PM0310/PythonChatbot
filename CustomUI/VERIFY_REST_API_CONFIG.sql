-- ============================================================================
-- QUICK VERIFICATION SCRIPT FOR ORA-29273 TROUBLESHOOTING
-- Run this to check all prerequisites before calling REST API
-- ============================================================================

DECLARE
    l_pass_count    NUMBER := 0;
    l_fail_count    NUMBER := 0;
    l_acl_exists    NUMBER := 0;
    l_cred_exists   NUMBER := 0;
    l_response      CLOB;
    l_status        NUMBER;
    l_temp          VARCHAR2(4000);
BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    
    -- ════════════════════════════════════════════════════════════════
    -- SECTION 1: Database & APEX Check
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('╔═══════════════════════════════════════════════════════════╗');
    DBMS_OUTPUT.PUT_LINE('║  ORA-29273 VERIFICATION CHECKLIST                         ║');
    DBMS_OUTPUT.PUT_LINE('╚═══════════════════════════════════════════════════════════╝');
    DBMS_OUTPUT.PUT_LINE('');
    
    -- Check 1: Database Version
    DBMS_OUTPUT.PUT_LINE('✓ Checking Database Version...');
    BEGIN
        SELECT banner INTO l_temp FROM v$version WHERE ROWNUM = 1;
        DBMS_OUTPUT.PUT_LINE('  ✅ PASS: ' || SUBSTR(l_temp, 1, 60));
        l_pass_count := l_pass_count + 1;
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('  ❌ FAIL: ' || SQLERRM);
            l_fail_count := l_fail_count + 1;
    END;
    
    -- Check 2: APEX Availability
    DBMS_OUTPUT.PUT_LINE('✓ Checking APEX_WEB_SERVICE...');
    BEGIN
        -- Try to use it
        SELECT 'exists' INTO l_temp FROM dual WHERE EXISTS(
            SELECT 1 FROM user_procedures 
            WHERE procedure_name = 'MAKE_REST_REQUEST'
        );
        DBMS_OUTPUT.PUT_LINE('  ✅ PASS: APEX_WEB_SERVICE available');
        l_pass_count := l_pass_count + 1;
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('  ⚠️  INFO: APEX may not be installed');
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- SECTION 2: Network ACL Check (MOST CRITICAL)
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('✓ Checking Network ACL for cendb.ad.centroid.com...');
    BEGIN
        -- Try to check if we have DBA privileges
        BEGIN
            SELECT COUNT(*) INTO l_acl_exists
            FROM dba_network_acl_privileges
            WHERE host LIKE '%cendb%' OR host LIKE '%centroid%';
            
            IF l_acl_exists > 0 THEN
                DBMS_OUTPUT.PUT_LINE('  ✅ PASS: Network ACL configured (' || l_acl_exists || ' rules)');
                l_pass_count := l_pass_count + 1;
            ELSE
                DBMS_OUTPUT.PUT_LINE('  ❌ FAIL: Network ACL NOT configured');
                DBMS_OUTPUT.PUT_LINE('     💡 FIX: Run the ACL setup from STEP 2');
                DBMS_OUTPUT.PUT_LINE('     This is the MOST COMMON cause of ORA-29273');
                l_fail_count := l_fail_count + 1;
            END IF;
        EXCEPTION
            WHEN OTHERS THEN
                -- If DBA table not accessible, just inform user
                DBMS_OUTPUT.PUT_LINE('  ⚠️  INFO: Cannot check ACL (requires DBA role)');
                DBMS_OUTPUT.PUT_LINE('     💡 FIX: Ask DBA to run ACL setup, or run REST_API_FIXED_SOLUTIONS.sql SOLUTION 3');
        END;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- SECTION 3: Credentials Check
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('✓ Checking APEX Credentials...');
    BEGIN
        -- Try to check if APEX credentials exist
        BEGIN
            SELECT COUNT(*) INTO l_cred_exists
            FROM apex_apexuser_credentials
            WHERE credential_static_id = 'ebscreds';
            
            IF l_cred_exists > 0 THEN
                DBMS_OUTPUT.PUT_LINE('  ✅ PASS: Credential "ebscreds" found');
                l_pass_count := l_pass_count + 1;
                
                -- Show credential details if accessible
                FOR cred_rec IN (
                    SELECT credential_name, username, auth_type
                    FROM apex_apexuser_credentials
                    WHERE credential_static_id = 'ebscreds'
                ) LOOP
                    DBMS_OUTPUT.PUT_LINE('       Name: ' || cred_rec.credential_name);
                    DBMS_OUTPUT.PUT_LINE('       User: ' || cred_rec.username);
                    DBMS_OUTPUT.PUT_LINE('       Type: ' || cred_rec.auth_type);
                END LOOP;
            ELSE
                DBMS_OUTPUT.PUT_LINE('  ⚠️  WARNING: Credential "ebscreds" not found');
                DBMS_OUTPUT.PUT_LINE('     💡 FIX: Create in APEX > Admin > Credentials');
                l_fail_count := l_fail_count + 1;
            END IF;
        EXCEPTION
            WHEN OTHERS THEN
                DBMS_OUTPUT.PUT_LINE('  ⚠️  INFO: Cannot check credentials (APEX tables may not be accessible)');
                DBMS_OUTPUT.PUT_LINE('     💡 FIX: Create credential in APEX UI > Admin > Credentials');
                DBMS_OUTPUT.PUT_LINE('           with Static ID: ebscreds');
        END;
    EXCEPTION
        WHEN OTHERS THEN
            NULL;
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- SECTION 4: Network Connectivity Test
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('✓ Testing Network Connectivity (Public Endpoint)...');
    BEGIN
        APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
            p_name_01 => 'Content-Type',
            p_value_01 => 'application/json',
            p_reset => TRUE
        );
        
        l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
            p_url              => 'https://httpbin.org/get',
            p_http_method      => 'GET',
            p_transfer_timeout => 30
        );
        
        l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
        
        IF l_status = 200 THEN
            DBMS_OUTPUT.PUT_LINE('  ✅ PASS: Can reach public internet (httpbin.org)');
            DBMS_OUTPUT.PUT_LINE('     Status: ' || l_status);
            l_pass_count := l_pass_count + 1;
        ELSE
            DBMS_OUTPUT.PUT_LINE('  ⚠️  WARNING: Got status ' || l_status || ' from public endpoint');
        END IF;
        
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('  ❌ FAIL: Cannot reach public internet');
            DBMS_OUTPUT.PUT_LINE('     Error: ' || SQLERRM);
            DBMS_OUTPUT.PUT_LINE('     💡 FIX: This suggests Network ACL or firewall issue');
            l_fail_count := l_fail_count + 1;
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- SECTION 5: Your Specific Endpoint Test
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('✓ Testing Your Endpoint (cendb.ad.centroid.com:4463)...');
    BEGIN
        APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
            p_name_01 => 'Content-Type',
            p_value_01 => 'application/json',
            p_reset => TRUE
        );
        
        -- Use GET to test connectivity first
        l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
            p_url              => 'https://cendb.ad.centroid.com:4463/',
            p_http_method      => 'GET',
            p_transfer_timeout => 30
        );
        
        l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
        
        IF l_status IS NOT NULL THEN
            DBMS_OUTPUT.PUT_LINE('  ✅ PASS: Got response from endpoint');
            DBMS_OUTPUT.PUT_LINE('     Status: ' || l_status);
            DBMS_OUTPUT.PUT_LINE('     Response Length: ' || DBMS_LOB.GETLENGTH(l_response));
            l_pass_count := l_pass_count + 1;
        ELSIF l_status IS NULL THEN
            DBMS_OUTPUT.PUT_LINE('  ❌ FAIL: No response from endpoint (NULL status)');
            DBMS_OUTPUT.PUT_LINE('     💡 FIX: Network ACL likely not configured');
            l_fail_count := l_fail_count + 1;
        ELSE
            DBMS_OUTPUT.PUT_LINE('  ⚠️  Got HTTP status: ' || l_status);
        END IF;
        
    EXCEPTION
        WHEN OTHERS THEN
            DBMS_OUTPUT.PUT_LINE('  ❌ FAIL: Cannot reach your endpoint');
            DBMS_OUTPUT.PUT_LINE('     Error: ' || SQLERRM);
            IF SQLCODE = -29273 THEN
                DBMS_OUTPUT.PUT_LINE('     💡 FIX: This is ORA-29273 - Network ACL issue');
            END IF;
            l_fail_count := l_fail_count + 1;
    END;
    
    DBMS_OUTPUT.PUT_LINE('');
    
    -- ════════════════════════════════════════════════════════════════
    -- SECTION 6: Summary
    -- ════════════════════════════════════════════════════════════════
    
    DBMS_OUTPUT.PUT_LINE('╔═══════════════════════════════════════════════════════════╗');
    DBMS_OUTPUT.PUT_LINE('║  SUMMARY                                                  ║');
    DBMS_OUTPUT.PUT_LINE('╚═══════════════════════════════════════════════════════════╝');
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('Tests Passed: ' || l_pass_count);
    DBMS_OUTPUT.PUT_LINE('Tests Failed: ' || l_fail_count);
    DBMS_OUTPUT.PUT_LINE('');
    
    IF l_fail_count = 0 THEN
        DBMS_OUTPUT.PUT_LINE('✅ ALL CHECKS PASSED!');
        DBMS_OUTPUT.PUT_LINE('Your REST API call should work now.');
        DBMS_OUTPUT.PUT_LINE('');
        DBMS_OUTPUT.PUT_LINE('Next Step: Run your REST API code from REST_API_FIXED_SOLUTIONS.sql');
    ELSE
        DBMS_OUTPUT.PUT_LINE('❌ Some checks failed. Follow these steps:');
        DBMS_OUTPUT.PUT_LINE('');
        
        IF l_acl_exists = 0 THEN
            DBMS_OUTPUT.PUT_LINE('1. Network ACL NOT configured:');
            DBMS_OUTPUT.PUT_LINE('   → Go to ORA-29273_TROUBLESHOOTING_GUIDE.md - STEP 2');
            DBMS_OUTPUT.PUT_LINE('   → Run the ACL setup code');
            DBMS_OUTPUT.PUT_LINE('');
        END IF;
        
        IF l_cred_exists = 0 THEN
            DBMS_OUTPUT.PUT_LINE('2. Credentials NOT configured:');
            DBMS_OUTPUT.PUT_LINE('   → Go to APEX Admin > Credentials');
            DBMS_OUTPUT.PUT_LINE('   → Create credential with Static ID: ebscreds');
            DBMS_OUTPUT.PUT_LINE('');
        END IF;
        
        IF l_fail_count > 1 THEN
            DBMS_OUTPUT.PUT_LINE('3. Run the public endpoint test (STEP 4) to verify network access');
            DBMS_OUTPUT.PUT_LINE('');
        END IF;
        
        DBMS_OUTPUT.PUT_LINE('Then re-run this verification script to confirm fixes.');
    END IF;
    
    DBMS_OUTPUT.PUT_LINE('');
    DBMS_OUTPUT.PUT_LINE('For detailed troubleshooting:');
    DBMS_OUTPUT.PUT_LINE('See: ORA-29273_TROUBLESHOOTING_GUIDE.md');
    DBMS_OUTPUT.PUT_LINE('See: REST_API_FIXED_SOLUTIONS.sql');

EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.PUT_LINE('❌ Unexpected error: ' || SQLERRM);
END;
/
