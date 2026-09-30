-- =====================================================================
-- APexpython_APEX.sql
-- PL/SQL Block for Oracle APEX to consume APexpython.py REST API
-- =====================================================================
-- Purpose: Sample PL/SQL code to integrate APexpython service with APEX
-- =====================================================================

-- =====================================================================
-- 1. FUNCTION: RETURN VALUE FROM APEXPYTHON API
-- =====================================================================
-- Use this function in APEX SQL or Page Processes
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_http_error_detail
RETURN VARCHAR2 AS
    l_detail VARCHAR2(4000);
BEGIN
    BEGIN
        l_detail := UTL_HTTP.get_detailed_sqlerrm;
    EXCEPTION
        WHEN OTHERS THEN
            l_detail := NULL;
    END;

    RETURN SUBSTR(
        SQLERRM ||
        CASE WHEN l_detail IS NOT NULL THEN ' | detail=' || l_detail ELSE NULL END ||
        ' | backtrace=' || DBMS_UTILITY.format_error_backtrace,
        1,
        4000
    );
END fn_http_error_detail;
/

CREATE OR REPLACE FUNCTION fn_get_apexpython_value (
    p_name VARCHAR2 DEFAULT 'APEX'
) RETURN VARCHAR2 AS
    l_response        CLOB;
    l_chunk           VARCHAR2(32767);
    l_url             VARCHAR2(500);
    l_http_request    UTL_HTTP.req;
    l_http_response   UTL_HTTP.resp;
    l_status_code     PLS_INTEGER;
    l_json_object     JSON_OBJECT_T;
    l_result          VARCHAR2(4000);
BEGIN
    l_url := 'http://localhost:5000/hello?name=' || UTL_URL.escape(p_name, TRUE);

    DBMS_LOB.createtemporary(l_response, TRUE);

    l_http_request := UTL_HTTP.begin_request(l_url, 'GET', 'HTTP/1.1');
    UTL_HTTP.set_header(l_http_request, 'Accept', 'application/json');

    l_http_response := UTL_HTTP.get_response(l_http_request);
    l_status_code := l_http_response.status_code;

    BEGIN
        LOOP
            UTL_HTTP.read_text(l_http_response, l_chunk, 32767);
            DBMS_LOB.writeappend(l_response, LENGTH(l_chunk), l_chunk);
        END LOOP;
    EXCEPTION
        WHEN UTL_HTTP.end_of_body THEN
            NULL;
    END;

    UTL_HTTP.end_response(l_http_response);

    IF l_status_code != 200 THEN
        l_result := 'HTTP_ERROR_' || l_status_code;
    ELSE
        BEGIN
            l_json_object := JSON_OBJECT_T.parse(l_response);
            l_result := l_json_object.get_string('message');
        EXCEPTION
            WHEN OTHERS THEN
                l_result := DBMS_LOB.substr(l_response, 4000, 1);
        END;
    END IF;

    IF DBMS_LOB.istemporary(l_response) = 1 THEN
        DBMS_LOB.freetemporary(l_response);
    END IF;

    RETURN l_result;
EXCEPTION
    WHEN OTHERS THEN
        BEGIN
            UTL_HTTP.end_response(l_http_response);
        EXCEPTION
            WHEN OTHERS THEN
                NULL;
        END;

        IF DBMS_LOB.istemporary(l_response) = 1 THEN
            DBMS_LOB.freetemporary(l_response);
        END IF;

        RETURN 'ERROR: ' || fn_http_error_detail;
END fn_get_apexpython_value;
/

-- Example:
-- SELECT fn_get_apexpython_value('APEX User') AS api_message FROM DUAL;


-- =====================================================================
-- 2. PROCEDURE: CALL APEXPYTHON HELLO ENDPOINT
-- =====================================================================
-- Create this procedure in your APEX schema to reuse across pages
-- =====================================================================

CREATE OR REPLACE PROCEDURE sp_call_apexpython_hello (
    p_name            IN  VARCHAR2 DEFAULT 'World',
    p_response_msg    OUT VARCHAR2,
    p_response_status OUT VARCHAR2
) AS
    l_response        CLOB;
    l_url             VARCHAR2(500);
    l_http_request    UTL_HTTP.req;
    l_http_response   UTL_HTTP.resp;
    l_response_text   VARCHAR2(4000);
    l_json_object     JSON_OBJECT_T;
    
BEGIN
    -- Construct the URL
    l_url := 'http://localhost:5000/hello?name=' || REPLACE(p_name, ' ', '%20');
    
    -- Begin request
    l_http_request := UTL_HTTP.begin_request(l_url, 'GET', 'HTTP/1.1');
    
    -- Add headers
    UTL_HTTP.set_header(l_http_request, 'Content-Type', 'application/json');
    
    -- Get response
    l_http_response := UTL_HTTP.get_response(l_http_request);
    
    -- Read response body
    BEGIN
        LOOP
            UTL_HTTP.read_line(l_http_response, l_response_text, TRUE);
            l_response := l_response || l_response_text;
        END LOOP;
    EXCEPTION
        WHEN UTL_HTTP.end_of_body THEN
            NULL;
    END;
    
    -- Close connection
    UTL_HTTP.end_response(l_http_response);
    
    -- Parse JSON response
    BEGIN
        l_json_object := JSON_OBJECT_T.parse(l_response);
        p_response_msg := l_json_object.get_string('message');
        p_response_status := l_json_object.get_string('status');
    EXCEPTION
        WHEN OTHERS THEN
            p_response_msg := l_response;
            p_response_status := 'ERROR';
    END;
    
EXCEPTION
    WHEN OTHERS THEN
        p_response_status := 'ERROR';
    p_response_msg := fn_http_error_detail;
END sp_call_apexpython_hello;
/


-- =====================================================================
-- 3. FUNCTION: GET MESSAGE FROM APEXPYTHON
-- =====================================================================
-- Use this function to get hello message directly in SQL
-- =====================================================================

CREATE OR REPLACE FUNCTION fn_get_apexpython_hello (
    p_name VARCHAR2 DEFAULT 'World'
) RETURN VARCHAR2 AS
    l_response        CLOB;
    l_url             VARCHAR2(500);
    l_http_request    UTL_HTTP.req;
    l_http_response   UTL_HTTP.resp;
    l_response_text   VARCHAR2(4000);
    l_json_object     JSON_OBJECT_T;
    l_message         VARCHAR2(500);
    
BEGIN
    -- Construct the URL
    l_url := 'http://localhost:5000/hello?name=' || REPLACE(p_name, ' ', '%20');
    
    -- Begin request
    l_http_request := UTL_HTTP.begin_request(l_url, 'GET', 'HTTP/1.1');
    UTL_HTTP.set_header(l_http_request, 'Content-Type', 'application/json');
    
    -- Get response
    l_http_response := UTL_HTTP.get_response(l_http_request);
    
    -- Read response
    BEGIN
        LOOP
            UTL_HTTP.read_line(l_http_response, l_response_text, TRUE);
            l_response := l_response || l_response_text;
        END LOOP;
    EXCEPTION
        WHEN UTL_HTTP.end_of_body THEN
            NULL;
    END;
    
    -- Close connection
    UTL_HTTP.end_response(l_http_response);
    
    -- Parse JSON
    l_json_object := JSON_OBJECT_T.parse(l_response);
    l_message := l_json_object.get_string('message');
    
    RETURN l_message;
    
EXCEPTION
    WHEN OTHERS THEN
    RETURN 'Error: ' || fn_http_error_detail;
END fn_get_apexpython_hello;
/


-- =====================================================================
-- 4. PROCEDURE: HEALTH CHECK
-- =====================================================================

CREATE OR REPLACE PROCEDURE sp_check_apexpython_health (
    p_status     OUT VARCHAR2,
    p_message    OUT VARCHAR2,
    p_timestamp  OUT VARCHAR2
) AS
    l_response        CLOB;
    l_url             VARCHAR2(500);
    l_http_request    UTL_HTTP.req;
    l_http_response   UTL_HTTP.resp;
    l_response_text   VARCHAR2(4000);
    l_json_object     JSON_OBJECT_T;
    
BEGIN
    l_url := 'http://localhost:5000/health';

    l_http_request := UTL_HTTP.begin_request(l_url, 'GET', 'HTTP/1.1');
    UTL_HTTP.set_header(l_http_request, 'Content-Type', 'application/json');
    
    l_http_response := UTL_HTTP.get_response(l_http_request);
    
    BEGIN
        LOOP
            UTL_HTTP.read_line(l_http_response, l_response_text, TRUE);
            l_response := l_response || l_response_text;
        END LOOP;
    EXCEPTION
        WHEN UTL_HTTP.end_of_body THEN
            NULL;
    END;
    
    UTL_HTTP.end_response(l_http_response);
    
    -- Parse response
    l_json_object := JSON_OBJECT_T.parse(l_response);
    p_status := l_json_object.get_string('status');
    p_message := l_json_object.get_string('message');
    p_timestamp := l_json_object.get_string('timestamp');
    
EXCEPTION
    WHEN OTHERS THEN
        p_status := 'ERROR';
    p_message := fn_http_error_detail;
END sp_check_apexpython_health;
/


-- =====================================================================
-- 5. USAGE IN APEX - EXAMPLES
-- =====================================================================

/*
EXAMPLE 1: Call in Page Process (On Load)
-------------------------------------------
DECLARE
    l_msg       VARCHAR2(500);
    l_status    VARCHAR2(100);
BEGIN
    sp_call_apexpython_hello('APEX User', l_msg, l_status);
    :P1_MESSAGE := l_msg;
    :P1_STATUS := l_status;
END;
/

EXAMPLE 2: Set Item Value Using Function in SQL Query
-------------------------------------------------------
SELECT fn_get_apexpython_hello('John') AS hello_message FROM DUAL;

EXAMPLE 3: Health Check Before Processing
-------------------------------------------
DECLARE
    l_status    VARCHAR2(100);
    l_message   VARCHAR2(500);
    l_timestamp VARCHAR2(500);
BEGIN
    sp_check_apexpython_health(l_status, l_message, l_timestamp);
    
    IF l_status = 'success' THEN
        DBMS_OUTPUT.put_line('Service is up: ' || l_message);
    ELSE
        DBMS_OUTPUT.put_line('Service is down!');
    END IF;
END;
/

EXAMPLE 4: Dynamic APEX Page Process
--------------------------------------
BEGIN
    -- Get the user name from APEX item
    DECLARE
        l_msg       VARCHAR2(500);
        l_status    VARCHAR2(100);
        l_user_name VARCHAR2(100) := :P1_USER_NAME;
    BEGIN
        sp_call_apexpython_hello(l_user_name, l_msg, l_status);
        
        -- Update APEX items
        :P1_HELLO_MSG := l_msg;
        :P1_API_STATUS := l_status;
        
        -- Log the action
        INSERT INTO api_call_log (user_name, message, status, call_date)
        VALUES (l_user_name, l_msg, l_status, SYSDATE);
        COMMIT;
    END;
END;
/

EXAMPLE 5: REST Data Source Configuration in APEX
---------------------------------------------------
URL:        http://localhost:5000/hello
Method:     GET
Format:     JSON
Headers:    Content-Type: application/json

Response Parsing:
- message (VARCHAR2) - The hello message
- status (VARCHAR2) - Status of the call
- timestamp (VARCHAR2) - Timestamp of response

*/

-- =====================================================================
-- 6. TEST PROCEDURE
-- =====================================================================

CREATE OR REPLACE PROCEDURE sp_test_apexpython AS
    l_msg       VARCHAR2(500);
    l_status    VARCHAR2(100);
    l_ts        VARCHAR2(500);
BEGIN
    DBMS_OUTPUT.put_line('=== APexpython API Test ===');
    DBMS_OUTPUT.put_line('');
    
    -- Test Hello endpoint
    DBMS_OUTPUT.put_line('1. Testing Hello Endpoint...');
    sp_call_apexpython_hello('TestUser', l_msg, l_status);
    DBMS_OUTPUT.put_line('   Status: ' || l_status);
    DBMS_OUTPUT.put_line('   Message: ' || l_msg);
    DBMS_OUTPUT.put_line('');
    
    -- Test Health endpoint
    DBMS_OUTPUT.put_line('2. Testing Health Endpoint...');
    sp_check_apexpython_health(l_status, l_msg, l_ts);
    DBMS_OUTPUT.put_line('   Status: ' || l_status);
    DBMS_OUTPUT.put_line('   Message: ' || l_msg);
    DBMS_OUTPUT.put_line('   Timestamp: ' || l_ts);
    DBMS_OUTPUT.put_line('');
    
    -- Test Function
    DBMS_OUTPUT.put_line('3. Testing Function...');
    l_msg := fn_get_apexpython_hello('FunctionTest');
    DBMS_OUTPUT.put_line('   Result: ' || l_msg);
    DBMS_OUTPUT.put_line('');
    
    DBMS_OUTPUT.put_line('=== Test Complete ===');
    
EXCEPTION
    WHEN OTHERS THEN
        DBMS_OUTPUT.put_line('Error during test: ' || SQLERRM);
END sp_test_apexpython;
/


-- =====================================================================
-- 7. ACL SETUP (Required for making HTTP calls)
-- =====================================================================
-- Run this as SYSDBA if you get "ORA-24247" errors
-- =====================================================================

/*
-- Create ACL for network access
BEGIN
    DBMS_NETWORK_ACL_ADMIN.create_acl(
        acl         => 'utl_http.xml',
        description => 'UTL_HTTP access for APexpython',
        principal   => 'APEX_050100',
        is_grant    => TRUE,
        privilege   => 'connect'
    );
    
    COMMIT;
END;
/

-- Add host permission
BEGIN
    DBMS_NETWORK_ACL_ADMIN.add_privilege(
        acl       => 'utl_http.xml',
        principal => 'APEX_050100',
        is_grant  => TRUE,
        privilege => 'connect',
        host      => 'localhost'
    );
    
    COMMIT;
END;
/

-- Assign ACL to host
BEGIN
    DBMS_NETWORK_ACL_ADMIN.assign_acl(
        acl  => 'utl_http.xml',
        host => 'localhost'
    );
    
    COMMIT;
END;
/

*/

-- =====================================================================
-- END OF SCRIPT
-- =====================================================================
