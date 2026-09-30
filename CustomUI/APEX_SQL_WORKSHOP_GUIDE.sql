-- ============================================================================
-- ORACLE APEX CHATBOT - SQL WORKSHOP EXECUTION GUIDE
-- ============================================================================
-- 
-- HOW TO USE:
-- 1. Open SQL Workshop in Oracle APEX
-- 2. Copy each section below
-- 3. Execute in sequence
-- 4. Modify configuration (API keys, email settings)
-- 5. Call procedures from APEX Forms or Dashboards
--
-- ============================================================================

-- ============================================================================
-- STEP 1: CREATE CHATBOT PACKAGE (Base Chatbot)
-- ============================================================================
-- Copy and paste the entire chatbot_plsql.sql file content from SQL Workshop
-- This creates chatbot_pkg package for core chatbot functionality

-- After execution, verify:
/*
SELECT object_name, object_type, status 
FROM user_objects 
WHERE object_name LIKE 'CHATBOT%';
*/

-- ============================================================================
-- STEP 2: CREATE EXTENDED CHATBOT PACKAGE
-- ============================================================================
-- Copy and paste the entire chatbot_extended_plsql.sql file content
-- This adds email, HTML formatting, and APEX integration

-- Verify:
/*
SELECT object_name 
FROM user_objects 
WHERE object_name LIKE '%CHATBOT%' OR object_name LIKE '%APEX%'
ORDER BY object_name;
*/

-- ============================================================================
-- STEP 3: CONFIGURATION - UPDATE YOUR SETTINGS
-- ============================================================================

-- Update OpenAI API Configuration (if using real AI)
-- Edit chatbot_pkg package, find this line and update:
-- OPENAI_API_KEY CONSTANT VARCHAR2(500) := 'your-api-key-here';
-- OPENAI_ENDPOINT CONSTANT VARCHAR2(500) := 'https://models.inference.ai.azure.com/chat/completions';

-- Update Email Configuration
-- Edit chatbot_extended_pkg package:
-- l_smtp_host VARCHAR2(255) := 'smtp.gmail.com';        -- Your SMTP server
-- l_sender VARCHAR2(255) := 'your-email@example.com';   -- From email
-- l_sender_pwd VARCHAR2(255) := 'your-app-password';    -- App password

-- Test Email Connection:
/*
BEGIN
  chatbot_extended_pkg.send_chatbot_email(
    p_recipient => 'test@example.com',
    p_subject => 'Test Email from Oracle APEX Chatbot',
    p_body => '<h1>Success!</h1><p>Your chatbot is working!</p>'
  );
END;
/
*/

-- ============================================================================
-- STEP 4: QUICK TEST - RUN CHATBOT
-- ============================================================================

-- Test 1: Basic Intent Detection
DECLARE
  v_intent VARCHAR2(500);
BEGIN
  v_intent := chatbot_pkg.detect_intent('Show me all orders from last 30 days');
  DBMS_OUTPUT.PUT_LINE('Intent: ' || v_intent);
END;
/

-- Test 2: SQL Generation
DECLARE
  v_sql_json VARCHAR2(4000);
BEGIN
  v_sql_json := chatbot_pkg.generate_sql('{"action":"get_range"}');
  DBMS_OUTPUT.PUT_LINE('SQL: ' || v_sql_json);
END;
/

-- Test 3: Full Chatbot Flow
DECLARE
  v_response VARCHAR2(4000);
  v_sql VARCHAR2(4000);
BEGIN
  chatbot_pkg.process_user_message(
    'Get orders for ABC Corp',
    v_response,
    v_sql
  );
  DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(v_response, 1, 200));
  DBMS_OUTPUT.PUT_LINE('SQL: ' || v_sql);
END;
/

-- Test 4: Generate HTML Report
DECLARE
  v_html VARCHAR2(32000);
BEGIN
  v_html := chatbot_extended_pkg.format_results_html(
    'SELECT * FROM oe_orders WHERE ROWNUM <= 10',
    'Order Summary Report'
  );
  DBMS_OUTPUT.PUT_LINE(SUBSTR(v_html, 1, 500));
END;
/

-- ============================================================================
-- STEP 5: CREATE APEX INTERACTIVE REPORT + CHATBOT
-- ============================================================================

-- SQL Query for APEX Interactive Report:
SELECT 
  order_id,
  order_number,
  customer_name,
  order_date,
  total_amount,
  status
FROM oe_orders
ORDER BY order_date DESC;

-- ============================================================================
-- STEP 6: APEX DYNAMIC ACTION INTEGRATION
-- ============================================================================
-- 
-- In APEX App Designer:
-- 1. Create a Form Region with:
--    - P_CHATBOT_MESSAGE (Text Item) - User input
--    - P_RESPONSE (Display Only) - AI Response
--    - P_SQL_QUERY (Display Only) - Generated SQL
--
-- 2. Create a Dynamic Action:
--    Event: Change on P_CHATBOT_MESSAGE
--    Action Type: Execute PL/SQL Code
--    Code:
-- 
/*
DECLARE
  v_response VARCHAR2(4000);
  v_sql VARCHAR2(4000);
BEGIN
  chatbot_pkg.process_user_message(
    :P_CHATBOT_MESSAGE,
    v_response,
    v_sql
  );
  :P_RESPONSE := v_response;
  :P_SQL_QUERY := v_sql;
END;
*/
--
-- 3. Add Page Load JavaScript to refresh display:
/*
apex.region("chatbot_result").refresh();
*/

-- ============================================================================
-- STEP 7: APEX BUTTON + REPORT GENERATION
-- ============================================================================
--
-- Create a Button "Generate Report"
-- Dynamic Action: Execute PL/SQL
-- Code:
--
/*
DECLARE
  v_response VARCHAR2(4000);
  v_sql VARCHAR2(4000);
  v_html VARCHAR2(32000);
BEGIN
  -- Get chatbot response
  chatbot_pkg.process_user_message(:P_CHATBOT_MESSAGE, v_response, v_sql);
  
  -- Generate HTML report
  IF v_sql IS NOT NULL THEN
    v_html := chatbot_extended_pkg.format_results_html(v_sql, 'Chatbot Results');
    :P_REPORT_HTML := v_html;
  END IF;
  
  -- Optionally send email
  IF :P_SEND_EMAIL = 'Y' THEN
    chatbot_extended_pkg.send_chatbot_email(
      :P_EMAIL_TO,
      'Chatbot Report - ' || TO_CHAR(SYSDATE, 'YYYY-MM-DD'),
      v_html
    );
  END IF;
END;
*/

-- ============================================================================
-- STEP 8: AJAX CALLBACK FOR REAL-TIME CHAT
-- ============================================================================
--
-- 1. Create an Application Process (On Demand Process)
--    Process Name: GET_CHATBOT_RESPONSE
--    Type: PL/SQL
--    Code:
--
/*
DECLARE
  v_response VARCHAR2(4000);
BEGIN
  HTP.PRINT(apex_chatbot_ajax_handler(APEX_APPLICATION.G_X01));
EXCEPTION WHEN OTHERS THEN
  HTP.PRINT('{"error":"' || SQLERRM || '"}');
END;
*/
--
-- 2. In JavaScript on your Page:
--
/*
function sendChatbotMessage(message) {
  apex.server.process(
    'GET_CHATBOT_RESPONSE',
    { x01: message },
    {
      success: function(data) {
        var response = JSON.parse(data);
        console.log('Response:', response);
        document.getElementById('result').innerHTML = response.response;
      },
      error: function(error) {
        console.error('Error:', error);
      }
    }
  );
}
*/

-- ============================================================================
-- STEP 9: SCHEDULED CHATBOT REPORTS
-- ============================================================================
--
-- Create a Stored Procedure to Run Periodic Reports:
--
/*
CREATE OR REPLACE PROCEDURE run_scheduled_chatbot_report IS
  v_response VARCHAR2(4000);
  v_sql VARCHAR2(4000);
  v_html VARCHAR2(32000);
BEGIN
  -- Generate daily order summary
  chatbot_pkg.process_user_message(
    'Show all orders booked today',
    v_response,
    v_sql
  );
  
  -- Format as HTML
  v_html := chatbot_extended_pkg.format_results_html(v_sql, 'Daily Order Summary');
  
  -- Send email
  chatbot_extended_pkg.send_chatbot_email(
    'reports@example.com',
    'Daily Order Report - ' || TO_CHAR(SYSDATE, 'YYYY-MM-DD'),
    v_html
  );
  
  DBMS_OUTPUT.PUT_LINE('Scheduled report sent successfully');
END run_scheduled_chatbot_report;
/

-- Schedule using DBMS_SCHEDULER:
BEGIN
  DBMS_SCHEDULER.CREATE_JOB(
    job_name => 'CHATBOT_DAILY_REPORT',
    job_type => 'PLSQL_BLOCK',
    job_action => 'BEGIN run_scheduled_chatbot_report; END;',
    start_date => SYSDATE,
    repeat_interval => 'FREQ=DAILY;BYHOUR=9;BYMINUTE=0',
    enabled => TRUE
  );
END;
/
*/

-- ============================================================================
-- STEP 10: DATABASE OBJECTS VERIFICATION
-- ============================================================================

-- Check all created objects:
SELECT 
  object_name,
  object_type,
  status,
  created,
  last_ddl_time
FROM user_objects
WHERE object_name IN ('CHATBOT_PKG', 'CHATBOT_EXTENDED_PKG', 'APEX_CHATBOT_AJAX_HANDLER', 'OE_ORDERS')
ORDER BY object_name;

-- Check for compilation errors:
SELECT 
  name,
  type,
  line,
  text
FROM user_errors
WHERE name LIKE 'CHATBOT%'
ORDER BY name, line;

-- ============================================================================
-- STEP 11: TROUBLESHOOTING
-- ============================================================================

-- If you get error: "ORA-06550: line 1, column 7"
-- Solution: Check for missing packages or compilation errors
SELECT name, type, error_line, error_type, text
FROM all_errors
WHERE owner = USER
AND type != 'PACKAGE BODY'
ORDER BY name, error_line;

-- If AJAX is not working in APEX:
-- 1. Verify the On Demand Process is created
-- 2. Check browser console for JavaScript errors
-- 3. Ensure API credentials are set correctly
-- 4. Check APEX_WORKSPACE_ADMIN logs

-- Test direct API call:
BEGIN
  DBMS_OUTPUT.ENABLE;
  DBMS_OUTPUT.PUT_LINE(apex_chatbot_ajax_handler('Test message'));
END;
/

-- ============================================================================
-- STEP 12: CONVERT TO REST API (OPTIONAL - For External Integration)
-- ============================================================================

-- Create a REST-enabled endpoint for external applications:
/*
CREATE OR REPLACE PACKAGE REST_CHATBOT_API IS
  PRAGMA REST_METADATA (
    p_pattern => '/chatbot/v1/process',
    p_method => 'POST',
    p_source_media_type => 'application/json'
  );
  PROCEDURE process_chat;
END REST_CHATBOT_API;
/

CREATE OR REPLACE PACKAGE BODY REST_CHATBOT_API IS
  PROCEDURE process_chat IS
    l_response VARCHAR2(4000);
    l_sql VARCHAR2(4000);
    l_json_request CLOB;
    l_message VARCHAR2(500);
  BEGIN
    -- Parse request
    l_json_request := APEX_WEB_SERVICE.FETCH_HTTP_RESPONSE(
      APEX_WEB_SERVICE.MAKE_REQUEST(
        p_request_url => 'http://internal',
        p_http_method => 'GET'
      )
    );
    
    -- Extract message
    SELECT JSON_VALUE(l_json_request, '$.message')
    INTO l_message
    FROM dual;
    
    -- Process
    chatbot_pkg.process_user_message(l_message, l_response, l_sql);
    
    -- Return response
    APEX_JSON.INITIALIZE_CLOB_OUTPUT;
    APEX_JSON.OPEN_OBJECT;
    APEX_JSON.WRITE('status', 'success');
    APEX_JSON.WRITE('message', l_message);
    APEX_JSON.WRITE('response', l_response);
    APEX_JSON.WRITE('sql_query', l_sql);
    APEX_JSON.CLOSE_OBJECT;
    
    APEX_WEB_SERVICE.SET_RESPONSE(APEX_JSON.GET_CLOB_OUTPUT);
  END process_chat;
END REST_CHATBOT_API;
/
*/

-- ============================================================================
-- QUICK REFERENCE: Common Commands
-- ============================================================================

-- Check current user privileges:
/*
SELECT * FROM session_privs WHERE privilege LIKE 'CREATE%' OR privilege LIKE 'EXECUTE%';
*/

-- Monitor chatbot execution:
/*
SELECT * FROM v$session WHERE program LIKE '%chatbot%';
*/

-- Check package dependencies:
/*
SELECT * FROM user_dependencies WHERE name IN ('CHATBOT_PKG', 'CHATBOT_EXTENDED_PKG');
*/

-- Drop and recreate (if needed):
/*
DROP PACKAGE chatbot_extended_pkg;
DROP PACKAGE chatbot_pkg;
*/

-- ============================================================================
-- END OF ORACLE APEX CHATBOT SETUP GUIDE
-- ============================================================================
