-- ============================================================================
-- Expose chatbot package for SQLcl MCP consumption
-- Execute after chatbot_plsql.sql and chatbot_extended_plsql.sql
-- ============================================================================

CREATE OR REPLACE PACKAGE chatbot_mcp_api IS
  -- Lightweight health check for MCP clients.
  FUNCTION health RETURN CLOB;

  -- Main MCP-facing method for chatbot interactions.
  FUNCTION ask_json(
    p_user_message IN VARCHAR2
  ) RETURN CLOB;

  -- Optional MCP-facing method that triggers email delivery.
  FUNCTION ask_with_email_json(
    p_user_message IN VARCHAR2,
    p_email_recipient IN VARCHAR2
  ) RETURN CLOB;
END chatbot_mcp_api;
/

CREATE OR REPLACE PACKAGE BODY chatbot_mcp_api IS
  FUNCTION escape_json_string(p_value IN VARCHAR2) RETURN VARCHAR2 IS
    l_value VARCHAR2(32767) := NVL(p_value, '');
  BEGIN
    l_value := REPLACE(l_value, '\\', '\\\\');
    l_value := REPLACE(l_value, '"', '\\"');
    l_value := REPLACE(l_value, CHR(10), '\\n');
    l_value := REPLACE(l_value, CHR(13), '\\r');
    l_value := REPLACE(l_value, CHR(9), '\\t');
    RETURN l_value;
  END escape_json_string;

  FUNCTION health RETURN CLOB IS
  BEGIN
    RETURN '{"success":true,"service":"chatbot_mcp_api","status":"ready","timestamp":"' ||
           TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM') ||
           '"}';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN '{"success":false,"error":"' || escape_json_string(SQLERRM) || '"}';
  END health;

  FUNCTION ask_json(
    p_user_message IN VARCHAR2
  ) RETURN CLOB IS
    l_response VARCHAR2(4000);
    l_sql_query VARCHAR2(4000);
  BEGIN
    chatbot_pkg.process_user_message(
      p_user_message => p_user_message,
      p_response => l_response,
      p_sql_query => l_sql_query
    );

    RETURN '{"success":true,' ||
           '"user_message":"' || escape_json_string(p_user_message) || '",' ||
           '"sql_query":"' || escape_json_string(l_sql_query) || '",' ||
           '"response":"' || escape_json_string(l_response) || '",' ||
           '"timestamp":"' || TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM') || '"}';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN '{"success":false,' ||
             '"user_message":"' || escape_json_string(p_user_message) || '",' ||
             '"error":"' || escape_json_string(SQLERRM) || '",' ||
             '"timestamp":"' || TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM') || '"}';
  END ask_json;

  FUNCTION ask_with_email_json(
    p_user_message IN VARCHAR2,
    p_email_recipient IN VARCHAR2
  ) RETURN CLOB IS
    l_response VARCHAR2(4000);
    l_sql_query VARCHAR2(4000);
  BEGIN
    chatbot_extended_pkg.chatbot_with_email(
      p_user_message => p_user_message,
      p_email_recipient => p_email_recipient,
      p_response => l_response,
      p_sql_query => l_sql_query
    );

    RETURN '{"success":true,' ||
           '"user_message":"' || escape_json_string(p_user_message) || '",' ||
           '"email_recipient":"' || escape_json_string(p_email_recipient) || '",' ||
           '"sql_query":"' || escape_json_string(l_sql_query) || '",' ||
           '"response":"' || escape_json_string(l_response) || '",' ||
           '"timestamp":"' || TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM') || '"}';
  EXCEPTION
    WHEN OTHERS THEN
      RETURN '{"success":false,' ||
             '"user_message":"' || escape_json_string(p_user_message) || '",' ||
             '"email_recipient":"' || escape_json_string(p_email_recipient) || '",' ||
             '"error":"' || escape_json_string(SQLERRM) || '",' ||
             '"timestamp":"' || TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM') || '"}';
  END ask_with_email_json;
END chatbot_mcp_api;
/

-- Optional: grant execute to a dedicated app user.
-- GRANT EXECUTE ON chatbot_mcp_api TO <app_user>;

-- Basic verification
SELECT chatbot_mcp_api.health AS health_json FROM dual;
SELECT chatbot_mcp_api.ask_json('Show me booked orders from last 30 days') AS chatbot_json FROM dual;
