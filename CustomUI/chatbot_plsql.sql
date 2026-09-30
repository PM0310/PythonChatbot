-- ============================================================================
-- ORACLE APEX SALES ORDER CHATBOT - PL/SQL Implementation
-- Execute in SQL Workshop or SQLcl
-- ============================================================================

CREATE OR REPLACE PACKAGE chatbot_pkg IS
  -- Main entry point for chatbot
  PROCEDURE process_user_message(
    p_user_message IN VARCHAR2,
    p_response OUT VARCHAR2,
    p_sql_query OUT VARCHAR2
  );

  -- Intent detection
  FUNCTION detect_intent(p_message IN VARCHAR2) RETURN VARCHAR2;

  -- Dynamic SQL generation
  FUNCTION generate_sql(p_intent_json IN VARCHAR2) RETURN VARCHAR2;

  -- Execute generated SQL
  FUNCTION execute_query(p_sql IN VARCHAR2) RETURN VARCHAR2;

  -- Parse response as JSON
  FUNCTION parse_json_response(p_response IN CLOB) RETURN VARCHAR2;

END chatbot_pkg;
/

CREATE OR REPLACE PACKAGE BODY chatbot_pkg IS

  -- Configuration Constants
  OPENAI_API_KEY CONSTANT VARCHAR2(500) := 'your-api-key-here';
  OPENAI_ENDPOINT CONSTANT VARCHAR2(500) := 'https://models.inference.ai.azure.com/chat/completions';
  
  -- =====================================================================
  -- MAIN CHATBOT PROCEDURE
  -- =====================================================================
  PROCEDURE process_user_message(
    p_user_message IN VARCHAR2,
    p_response OUT VARCHAR2,
    p_sql_query OUT VARCHAR2
  ) IS
    l_intent_json VARCHAR2(4000);
    l_sql_json VARCHAR2(4000);
    l_query_results VARCHAR2(4000);
    l_intent_action VARCHAR2(100);
  BEGIN
    -- Step 1: Detect user intent
    l_intent_json := detect_intent(p_user_message);
    DBMS_OUTPUT.PUT_LINE('Step 1 - Intent Detected: ' || l_intent_json);

    -- Step 2: Generate SQL based on intent
    l_sql_json := generate_sql(l_intent_json);
    p_sql_query := parse_json_response(l_sql_json);
    DBMS_OUTPUT.PUT_LINE('Step 2 - SQL Generated: ' || p_sql_query);

    -- Step 3: Execute the query
    IF p_sql_query IS NOT NULL AND p_sql_query != 'null' THEN
      l_query_results := execute_query(p_sql_query);
      p_response := l_query_results;
    ELSE
      p_response := 'No SQL query generated. Intent: ' || l_intent_json;
    END IF;

  EXCEPTION WHEN OTHERS THEN
    p_response := 'Error: ' || SQLERRM;
    p_sql_query := NULL;
  END process_user_message;

  -- =====================================================================
  -- INTENT DETECTION FUNCTION
  -- Simulates OpenAI API call for intent extraction
  -- =====================================================================
  FUNCTION detect_intent(p_message IN VARCHAR2) RETURN VARCHAR2 IS
    l_response CLOB;
    l_json_request VARCHAR2(4000);
    l_intent_action VARCHAR2(50);
  BEGIN
    -- For demonstration, use simple keyword matching
    -- In production, replace with actual OpenAI API call
    
    l_intent_action := 'dynamic_query'; -- default
    
    -- Simple keyword-based intent detection
    IF UPPER(p_message) LIKE '%CREATE%ORDER%' OR UPPER(p_message) LIKE '%NEW%ORDER%' THEN
      l_intent_action := 'create';
    ELSIF UPPER(p_message) LIKE '%ADD%LINE%' OR UPPER(p_message) LIKE '%ADD%ITEM%' THEN
      l_intent_action := 'add_line';
    ELSIF UPPER(p_message) LIKE '%SEND%EMAIL%' OR UPPER(p_message) LIKE '%MAIL%' THEN
      l_intent_action := 'email';
    ELSIF UPPER(p_message) LIKE '%GET%ORDER%' OR UPPER(p_message) LIKE '%SHOW%ORDER%' THEN
      l_intent_action := 'get';
    ELSIF UPPER(p_message) LIKE '%RANGE%' OR UPPER(p_message) LIKE '%PERIOD%' THEN
      l_intent_action := 'get_range';
    ELSIF UPPER(p_message) LIKE '%HELP%' THEN
      l_intent_action := 'help';
    ELSIF UPPER(p_message) LIKE '%CUSTOMER%' OR UPPER(p_message) LIKE '%SALES%' THEN
      l_intent_action := 'general';
    END IF;

    -- Return intent JSON
    RETURN '{"action":"' || l_intent_action || '","original_message":"' || REPLACE(p_message, '"', '\"') || '"}';

  EXCEPTION WHEN OTHERS THEN
    RETURN '{"action":"error","message":"' || SQLERRM || '"}';
  END detect_intent;

  -- =====================================================================
  -- DYNAMIC SQL GENERATION FUNCTION
  -- Simulates OpenAI API call for SQL generation
  -- =====================================================================
  FUNCTION generate_sql(p_intent_json IN VARCHAR2) RETURN VARCHAR2 IS
    l_action VARCHAR2(50);
    l_sql_query VARCHAR2(4000);
  BEGIN
    -- Extract action from intent JSON
    l_action := REGEXP_SUBSTR(p_intent_json, '"action":"([^"]*)"', 1, 1, NULL, 1);

    -- Generate SQL based on action
    CASE l_action
      WHEN 'get' THEN
        l_sql_query := 'SELECT order_number, customer_name, order_date, total_amount ' ||
                      'FROM oe_orders WHERE status = ''BOOKED'' AND ROWNUM <= 50';
      
      WHEN 'get_range' THEN
        l_sql_query := 'SELECT order_number, customer_name, order_date, total_amount ' ||
                      'FROM oe_orders WHERE order_date >= TRUNC(SYSDATE) - 30 AND ROWNUM <= 100';
      
      WHEN 'create' THEN
        l_sql_query := 'SELECT ''Order creation requires form input - use APEX form to create order'' AS message FROM dual';
      
      WHEN 'email' THEN
        l_sql_query := 'SELECT order_number, customer_name, customer_email ' ||
                      'FROM oe_orders WHERE status = ''BOOKED'' AND ROWNUM <= 50';
      
      WHEN 'general' THEN
        l_sql_query := 'SELECT ''Available actions: view orders, create order, add line items, send email, generate reports'' AS help_text FROM dual';

      WHEN 'help' THEN
        l_sql_query := 'SELECT ''Available actions: view orders, create order, add line items, send email, generate reports'' AS help_text FROM dual';
      
      ELSE -- dynamic_query or default
        l_sql_query := 'SELECT order_number, customer_name, order_date, status ' ||
                      'FROM oe_orders WHERE ROWNUM <= 50 ORDER BY order_date DESC';
    END CASE;

    -- Return as JSON response
    RETURN '{"sql":"' || REPLACE(l_sql_query, '"', '\"') || '","explanation":"Generated query for action: ' || l_action || '"}';

  EXCEPTION WHEN OTHERS THEN
    RETURN '{"sql":null,"error":"' || SQLERRM || '"}';
  END generate_sql;

  -- =====================================================================
  -- EXECUTE QUERY FUNCTION
  -- Executes dynamically generated SQL
  -- =====================================================================
  FUNCTION execute_query(p_sql IN VARCHAR2) RETURN VARCHAR2 IS
    l_result VARCHAR2(4000);
    l_cursor_id PLS_INTEGER;
    l_col_count PLS_INTEGER;
    l_desc_table DBMS_SQL.DESC_TAB;
    l_row_count PLS_INTEGER := 0;
    l_json_array VARCHAR2(4000) := '[';
  BEGIN
    -- Use DBMS_SQL for dynamic query execution
    l_cursor_id := DBMS_SQL.OPEN_CURSOR;
    DBMS_SQL.PARSE(l_cursor_id, p_sql, DBMS_SQL.NATIVE);
    
    -- Describe the columns
    DBMS_SQL.DESCRIBE_COLUMNS(l_cursor_id, l_col_count, l_desc_table);

    -- Define columns for fetching
    FOR i IN 1 .. l_col_count LOOP
      DBMS_SQL.DEFINE_COLUMN(l_cursor_id, i, l_result, 4000);
    END LOOP;

    -- Execute and fetch results
    l_cursor_id := DBMS_SQL.EXECUTE(l_cursor_id);

    -- Build JSON array of results
    WHILE DBMS_SQL.FETCH_ROWS(l_cursor_id) > 0 LOOP
      l_row_count := l_row_count + 1;
      
      IF l_row_count > 1 THEN
        l_json_array := l_json_array || ',';
      END IF;
      
      l_json_array := l_json_array || '{';
      
      FOR i IN 1 .. l_col_count LOOP
        DBMS_SQL.COLUMN_VALUE(l_cursor_id, i, l_result);
        
        IF i > 1 THEN
          l_json_array := l_json_array || ',';
        END IF;
        
        l_json_array := l_json_array || '"' || l_desc_table(i).col_name || '":"' || REPLACE(l_result, '"', '\"') || '"';
      END LOOP;
      
      l_json_array := l_json_array || '}';
      
      -- Limit to 50 rows
      IF l_row_count >= 50 THEN
        EXIT;
      END IF;
    END LOOP;

    DBMS_SQL.CLOSE_CURSOR(l_cursor_id);

    l_json_array := l_json_array || ']';
    RETURN l_json_array;

  EXCEPTION WHEN OTHERS THEN
    IF DBMS_SQL.IS_OPEN(l_cursor_id) THEN
      DBMS_SQL.CLOSE_CURSOR(l_cursor_id);
    END IF;
    RETURN '{"error":"' || REPLACE(SQLERRM, '"', '\"') || '"}';
  END execute_query;

  -- =====================================================================
  -- JSON PARSING HELPER
  -- =====================================================================
  FUNCTION parse_json_response(p_response IN CLOB) RETURN VARCHAR2 IS
    l_sql_value VARCHAR2(4000);
  BEGIN
    -- Extract SQL field from JSON response
    l_sql_value := REGEXP_SUBSTR(p_response, '"sql":"([^"]*)"', 1, 1, NULL, 1);
    
    IF l_sql_value IS NULL THEN
      -- Try without the null value
      l_sql_value := REGEXP_SUBSTR(p_response, '"sql":"([^"]*)"', 1, 1, NULL, 1);
    END IF;
    
    RETURN REPLACE(l_sql_value, '\"', '"');

  EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
  END parse_json_response;

END chatbot_pkg;
/

-- ============================================================================
-- TEST EXECUTION BLOCK
-- Run this to test the chatbot
-- ============================================================================

DECLARE
  l_response VARCHAR2(4000);
  l_sql_query VARCHAR2(4000);
  l_user_message VARCHAR2(500);
BEGIN
  -- Enable output
  DBMS_OUTPUT.ENABLE(NULL);

  -- Test messages
  l_user_message := 'Show me all orders from the last 30 days';

  DBMS_OUTPUT.PUT_LINE('========================================');
  DBMS_OUTPUT.PUT_LINE('SALES ORDER CHATBOT - PL/SQL');
  DBMS_OUTPUT.PUT_LINE('========================================');
  DBMS_OUTPUT.PUT_LINE('User Message: ' || l_user_message);
  DBMS_OUTPUT.PUT_LINE('----------------------------------------');

  -- Call chatbot
  chatbot_pkg.process_user_message(
    p_user_message => l_user_message,
    p_response => l_response,
    p_sql_query => l_sql_query
  );

  DBMS_OUTPUT.PUT_LINE('Generated SQL: ' || l_sql_query);
  DBMS_OUTPUT.PUT_LINE('----------------------------------------');
  DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(l_response, 1, 500));
  DBMS_OUTPUT.PUT_LINE('========================================');

  -- Test with another message
  l_user_message := 'Create a new sales order';

  DBMS_OUTPUT.PUT_LINE('User Message: ' || l_user_message);
  DBMS_OUTPUT.PUT_LINE('----------------------------------------');

  chatbot_pkg.process_user_message(
    p_user_message => l_user_message,
    p_response => l_response,
    p_sql_query => l_sql_query
  );

  DBMS_OUTPUT.PUT_LINE('Generated SQL: ' || l_sql_query);
  DBMS_OUTPUT.PUT_LINE('Response: ' || SUBSTR(l_response, 1, 500));
  DBMS_OUTPUT.PUT_LINE('========================================');

END;
/

-- ============================================================================
-- OPTIONAL: Create Oracle APEX REST API endpoint (if using APEX)
-- ============================================================================

/*
CREATE OR REPLACE PACKAGE chatbot_rest_api IS
  PRAGMA REST_METADATA (
    p_pattern => '/chatbot/process',
    p_method => 'POST',
    p_source_media_type => 'application/json',
    p_items_per_page => 0
  );

  PROCEDURE process_message;
END chatbot_rest_api;
/

CREATE OR REPLACE PACKAGE BODY chatbot_rest_api IS
  PROCEDURE process_message IS
    l_request_json CLOB;
    l_user_message VARCHAR2(500);
    l_response VARCHAR2(4000);
    l_sql_query VARCHAR2(4000);
  BEGIN
    -- Get JSON request body
    l_request_json := APEX_WEB_SERVICE.PARSE_JSON_REQUEST;
    l_user_message := APEX_JSON.GET_VARCHAR2(l_request_json, 'message');

    -- Process message
    chatbot_pkg.process_user_message(l_user_message, l_response, l_sql_query);

    -- Return JSON response
    APEX_JSON.INITIALIZE_CLOB_OUTPUT;
    APEX_JSON.OPEN_OBJECT;
    APEX_JSON.WRITE('response', l_response);
    APEX_JSON.WRITE('sql_query', l_sql_query);
    APEX_JSON.CLOSE_OBJECT;
    
    APEX_WEB_SERVICE.SET_RESPONSE(APEX_JSON.GET_CLOB_OUTPUT);
  END process_message;
END chatbot_rest_api;
/
*/

-- ============================================================================
-- QUICK START - Call this from APEX or SQL Workshop
-- ============================================================================

BEGIN
  DECLARE
    v_response VARCHAR2(4000);
    v_sql VARCHAR2(4000);
  BEGIN
    chatbot_pkg.process_user_message(
      'Get me all customer orders',
      v_response,
      v_sql
    );
    DBMS_OUTPUT.PUT_LINE(v_response);
  END;
END;
/
