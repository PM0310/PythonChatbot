-- ============================================================================
-- ORACLE APEX CHATBOT - EXTENDED WITH EMAIL & REPORTING
-- Execute in SQL Workshop or SQLcl
-- ============================================================================

CREATE OR REPLACE PACKAGE chatbot_extended_pkg IS
  
  -- Email sending functionality
  PROCEDURE send_chatbot_email(
    p_recipient IN VARCHAR2,
    p_subject IN VARCHAR2,
    p_body IN VARCHAR2,
    p_attachment_sql IN VARCHAR2 DEFAULT NULL
  );

  -- Generate Excel from query results
  FUNCTION generate_excel_report(
    p_query IN VARCHAR2,
    p_filename IN VARCHAR2
  ) RETURN BLOB;

  -- Format query results as HTML
  FUNCTION format_results_html(
    p_sql_query IN VARCHAR2,
    p_title IN VARCHAR2 DEFAULT 'Query Results'
  ) RETURN VARCHAR2;

  -- Enhanced chatbot with email integration
  PROCEDURE chatbot_with_email(
    p_user_message IN VARCHAR2,
    p_email_recipient IN VARCHAR2 DEFAULT NULL,
    p_response OUT VARCHAR2,
    p_sql_query OUT VARCHAR2
  );

END chatbot_extended_pkg;
/

CREATE OR REPLACE PACKAGE BODY chatbot_extended_pkg IS

  -- =====================================================================
  -- FORMAT RESULTS AS HTML TABLE
  -- =====================================================================
  FUNCTION format_results_html(
    p_sql_query IN VARCHAR2,
    p_title IN VARCHAR2 DEFAULT 'Query Results'
  ) RETURN VARCHAR2 IS
    l_html VARCHAR2(32000) := '';
    l_cursor_id PLS_INTEGER;
    l_col_count PLS_INTEGER;
    l_desc_table DBMS_SQL.DESC_TAB;
    l_col_value VARCHAR2(4000);
    l_row_count PLS_INTEGER := 0;
  BEGIN
    l_html := '<h2>' || p_title || '</h2>';
    l_html := l_html || '<table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse;">';

    -- Open and describe query
    l_cursor_id := DBMS_SQL.OPEN_CURSOR;
    DBMS_SQL.PARSE(l_cursor_id, p_sql_query, DBMS_SQL.NATIVE);
    DBMS_SQL.DESCRIBE_COLUMNS(l_cursor_id, l_col_count, l_desc_table);

    -- Define columns
    FOR i IN 1 .. l_col_count LOOP
      DBMS_SQL.DEFINE_COLUMN(l_cursor_id, i, l_col_value, 4000);
    END LOOP;

    -- Print header row
    l_html := l_html || '<tr style="background-color: #4CAF50; color: white;">';
    FOR i IN 1 .. l_col_count LOOP
      l_html := l_html || '<th>' || l_desc_table(i).col_name || '</th>';
    END LOOP;
    l_html := l_html || '</tr>';

    -- Execute and fetch rows
    l_cursor_id := DBMS_SQL.EXECUTE(l_cursor_id);

    WHILE DBMS_SQL.FETCH_ROWS(l_cursor_id) > 0 LOOP
      l_row_count := l_row_count + 1;
      l_html := l_html || '<tr>';

      FOR i IN 1 .. l_col_count LOOP
        DBMS_SQL.COLUMN_VALUE(l_cursor_id, i, l_col_value);
        l_html := l_html || '<td>' || NVL(l_col_value, '&nbsp;') || '</td>';
      END LOOP;

      l_html := l_html || '</tr>';

      IF l_row_count >= 100 THEN
        EXIT;
      END IF;
    END LOOP;

    DBMS_SQL.CLOSE_CURSOR(l_cursor_id);

    l_html := l_html || '</table>';
    l_html := l_html || '<p>Total Rows: ' || l_row_count || '</p>';

    RETURN l_html;

  EXCEPTION WHEN OTHERS THEN
    IF DBMS_SQL.IS_OPEN(l_cursor_id) THEN
      DBMS_SQL.CLOSE_CURSOR(l_cursor_id);
    END IF;
    RETURN '<p style="color:red;">Error generating HTML: ' || SQLERRM || '</p>';
  END format_results_html;

  -- =====================================================================
  -- SEND EMAIL WITH QUERY RESULTS
  -- =====================================================================
  PROCEDURE send_chatbot_email(
    p_recipient IN VARCHAR2,
    p_subject IN VARCHAR2,
    p_body IN VARCHAR2,
    p_attachment_sql IN VARCHAR2 DEFAULT NULL
  ) IS
    l_smtp_host VARCHAR2(255) := 'smtp.gmail.com';
    l_smtp_port PLS_INTEGER := 587;
    l_sender VARCHAR2(255) := 'your-email@example.com';
    l_sender_pwd VARCHAR2(255) := 'your-app-password';
    l_connection UTL_SMTP.CONNECTION;
    l_crlf VARCHAR2(2) := CHR(13) || CHR(10);
    l_boundary VARCHAR2(255) := '----Boundary_' || TO_CHAR(SYSDATE, 'YYYYMMDDHH24MISS');
  BEGIN
    -- Open SMTP connection
    l_connection := UTL_SMTP.OPEN_CONNECTION(l_smtp_host, l_smtp_port);
    
    -- Enable TLS
    UTL_SMTP.HELO(l_connection, l_smtp_host);
    UTL_SMTP.COMMAND(l_connection, 'STARTTLS');
    
    -- Authenticate
    UTL_SMTP.AUTH(l_connection, l_sender, l_sender_pwd, 'LOGIN');

    -- Set headers
    UTL_SMTP.MAIL(l_connection, l_sender);
    UTL_SMTP.RCPT(l_connection, p_recipient);
    
    -- Start message
    UTL_SMTP.OPEN_DATA(l_connection);

    -- Write headers
    UTL_SMTP.WRITE_DATA(l_connection, 'From: ' || l_sender || l_crlf);
    UTL_SMTP.WRITE_DATA(l_connection, 'To: ' || p_recipient || l_crlf);
    UTL_SMTP.WRITE_DATA(l_connection, 'Subject: ' || p_subject || l_crlf);
    UTL_SMTP.WRITE_DATA(l_connection, 'MIME-Version: 1.0' || l_crlf);
    UTL_SMTP.WRITE_DATA(l_connection, 'Content-Type: multipart/alternative; boundary="' || l_boundary || '"' || l_crlf || l_crlf);

    -- HTML body
    UTL_SMTP.WRITE_DATA(l_connection, '--' || l_boundary || l_crlf);
    UTL_SMTP.WRITE_DATA(l_connection, 'Content-Type: text/html; charset=UTF-8' || l_crlf || l_crlf);
    UTL_SMTP.WRITE_DATA(l_connection, p_body || l_crlf || l_crlf);

    -- Close message
    UTL_SMTP.CLOSE_DATA(l_connection);
    UTL_SMTP.QUIT(l_connection);

    DBMS_OUTPUT.PUT_LINE('Email sent successfully to: ' || p_recipient);

  EXCEPTION WHEN OTHERS THEN
    DBMS_OUTPUT.PUT_LINE('Error sending email: ' || SQLERRM);
  END send_chatbot_email;

  -- =====================================================================
  -- GENERATE EXCEL REPORT (SIMPLIFIED - returns CSV for demo)
  -- =====================================================================
  FUNCTION generate_excel_report(
    p_query IN VARCHAR2,
    p_filename IN VARCHAR2
  ) RETURN BLOB IS
    l_csv_content CLOB := '';
    l_cursor_id PLS_INTEGER;
    l_col_count PLS_INTEGER;
    l_desc_table DBMS_SQL.DESC_TAB;
    l_col_value VARCHAR2(4000);
    l_crlf VARCHAR2(2) := CHR(13) || CHR(10);
  BEGIN
    -- Open and describe query
    l_cursor_id := DBMS_SQL.OPEN_CURSOR;
    DBMS_SQL.PARSE(l_cursor_id, p_query, DBMS_SQL.NATIVE);
    DBMS_SQL.DESCRIBE_COLUMNS(l_cursor_id, l_col_count, l_desc_table);

    -- Define columns
    FOR i IN 1 .. l_col_count LOOP
      DBMS_SQL.DEFINE_COLUMN(l_cursor_id, i, l_col_value, 4000);
    END LOOP;

    -- Write header row
    FOR i IN 1 .. l_col_count LOOP
      IF i > 1 THEN
        l_csv_content := l_csv_content || ',';
      END IF;
      l_csv_content := l_csv_content || '"' || l_desc_table(i).col_name || '"';
    END LOOP;
    l_csv_content := l_csv_content || l_crlf;

    -- Execute and fetch rows
    l_cursor_id := DBMS_SQL.EXECUTE(l_cursor_id);

    WHILE DBMS_SQL.FETCH_ROWS(l_cursor_id) > 0 LOOP
      FOR i IN 1 .. l_col_count LOOP
        DBMS_SQL.COLUMN_VALUE(l_cursor_id, i, l_col_value);
        IF i > 1 THEN
          l_csv_content := l_csv_content || ',';
        END IF;
        l_csv_content := l_csv_content || '"' || REPLACE(l_col_value, '"', '""') || '"';
      END LOOP;
      l_csv_content := l_csv_content || l_crlf;
    END LOOP;

    DBMS_SQL.CLOSE_CURSOR(l_cursor_id);

    -- Convert CLOB to BLOB (simplified)
    RETURN UTL_RAW.CAST_TO_RAW(l_csv_content);

  EXCEPTION WHEN OTHERS THEN
    IF DBMS_SQL.IS_OPEN(l_cursor_id) THEN
      DBMS_SQL.CLOSE_CURSOR(l_cursor_id);
    END IF;
    RETURN NULL;
  END generate_excel_report;

  -- =====================================================================
  -- CHATBOT WITH EMAIL INTEGRATION
  -- =====================================================================
  PROCEDURE chatbot_with_email(
    p_user_message IN VARCHAR2,
    p_email_recipient IN VARCHAR2 DEFAULT NULL,
    p_response OUT VARCHAR2,
    p_sql_query OUT VARCHAR2
  ) IS
    l_html_results VARCHAR2(32000);
    l_email_subject VARCHAR2(500);
  BEGIN
    -- Process message using base chatbot
    chatbot_pkg.process_user_message(p_user_message, p_response, p_sql_query);

    -- If email requested and SQL was generated
    IF p_email_recipient IS NOT NULL AND p_sql_query IS NOT NULL THEN
      l_html_results := format_results_html(p_sql_query, 'Chatbot Query Results');
      
      l_email_subject := 'Chatbot Response - ' || TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS');

      -- Send email
      send_chatbot_email(
        p_recipient => p_email_recipient,
        p_subject => l_email_subject,
        p_body => l_html_results
      );

      p_response := p_response || ' | Email sent to: ' || p_email_recipient;
    END IF;

  EXCEPTION WHEN OTHERS THEN
    p_response := 'Error: ' || SQLERRM;
  END chatbot_with_email;

END chatbot_extended_pkg;
/

-- ============================================================================
-- TEST EXTENDED CHATBOT
-- ============================================================================

BEGIN
  DECLARE
    v_response VARCHAR2(4000);
    v_sql VARCHAR2(4000);
    v_html VARCHAR2(32000);
  BEGIN
    DBMS_OUTPUT.ENABLE(NULL);
    DBMS_OUTPUT.PUT_LINE('========================================');
    DBMS_OUTPUT.PUT_LINE('Testing Extended Chatbot with HTML Format');
    DBMS_OUTPUT.PUT_LINE('========================================');

    -- Test with sample query
    v_sql := 'SELECT 1 as order_id, ''ORD-001'' as order_number, ''Customer A'' as customer FROM dual ' ||
             'UNION ALL ' ||
             'SELECT 2, ''ORD-002'', ''Customer B'' FROM dual';

    v_html := chatbot_extended_pkg.format_results_html(v_sql, 'Sample Orders');
    DBMS_OUTPUT.PUT_LINE('Generated HTML:');
    DBMS_OUTPUT.PUT_LINE(SUBSTR(v_html, 1, 500) || '...');

  END;
END;
/

-- ============================================================================
-- APEX FORM INTEGRATION - PL/SQL FUNCTION FOR DYNAMIC ACTION
-- ============================================================================

CREATE OR REPLACE FUNCTION apex_chatbot_ajax_handler(
  p_user_message VARCHAR2
) RETURN VARCHAR2 IS
  l_response VARCHAR2(4000);
  l_sql_query VARCHAR2(4000);
  l_json_response VARCHAR2(4000);
BEGIN
  -- Process message
  chatbot_pkg.process_user_message(p_user_message, l_response, l_sql_query);

  -- Format as JSON for APEX AJAX callback
  l_json_response := '{' ||
    '"message":"' || REPLACE(p_user_message, '"', '\"') || '",' ||
    '"response":"' || REPLACE(SUBSTR(l_response, 1, 500), '"', '\"') || '",' ||
    '"sql_query":"' || REPLACE(l_sql_query, '"', '\"') || '",' ||
    '"timestamp":"' || TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS') || '"' ||
  '}';

  RETURN l_json_response;

EXCEPTION WHEN OTHERS THEN
  RETURN '{"error":"' || SQLERRM || '"}';
END apex_chatbot_ajax_handler;
/

-- ============================================================================
-- SAMPLE: Create a Simple Test Table for Demo
-- ============================================================================

CREATE TABLE IF NOT EXISTS oe_orders (
  order_id NUMBER PRIMARY KEY,
  order_number VARCHAR2(50),
  customer_name VARCHAR2(100),
  customer_email VARCHAR2(100),
  order_date DATE,
  total_amount NUMBER(10,2),
  status VARCHAR2(50)
);

-- Insert sample data
INSERT INTO oe_orders VALUES (1, 'ORD-001', 'ABC Corp', 'abc@example.com', SYSDATE-30, 5000, 'BOOKED');
INSERT INTO oe_orders VALUES (2, 'ORD-002', 'XYZ Inc', 'xyz@example.com', SYSDATE-15, 3500, 'BOOKED');
INSERT INTO oe_orders VALUES (3, 'ORD-003', 'Test Co', 'test@example.com', SYSDATE-5, 7500, 'SHIPPED');
COMMIT;

-- ============================================================================
-- USAGE EXAMPLES
-- ============================================================================

/*

-- Example 1: Simple chatbot call
BEGIN
  DECLARE
    v_response VARCHAR2(4000);
    v_sql VARCHAR2(4000);
  BEGIN
    chatbot_pkg.process_user_message(
      'Show me all booked orders',
      v_response,
      v_sql
    );
    DBMS_OUTPUT.PUT_LINE('Response: ' || v_response);
    DBMS_OUTPUT.PUT_LINE('SQL: ' || v_sql);
  END;
END;
/

-- Example 2: Chatbot with email
BEGIN
  DECLARE
    v_response VARCHAR2(4000);
    v_sql VARCHAR2(4000);
  BEGIN
    chatbot_extended_pkg.chatbot_with_email(
      'Get all customer orders for reporting',
      'user@example.com',
      v_response,
      v_sql
    );
    DBMS_OUTPUT.PUT_LINE(v_response);
  END;
END;
/

-- Example 3: Direct AJAX call from APEX
BEGIN
  DBMS_OUTPUT.PUT_LINE(apex_chatbot_ajax_handler('List all orders from last month'));
END;
/

*/
