# SQLcl MCP Setup for Chatbot Exposure

This workspace now includes `chatbot_mcp_expose.sql`, which wraps your chatbot package in MCP-friendly JSON responses.

## 1) Preconditions

- SQL Developer extension with SQLcl MCP server enabled in VS Code.
- A saved Oracle connection in SQLcl.
- Existing chatbot packages already deployed:
  - `chatbot_pkg` from `chatbot_plsql.sql`
  - `chatbot_extended_pkg` from `chatbot_extended_plsql.sql`

## 2) Deploy MCP wrapper package

Run in SQLcl or SQL Worksheet:

```sql
@chatbot_mcp_expose.sql
```

## 3) Validate objects

```sql
SELECT object_name, status
FROM user_objects
WHERE object_name IN ('CHATBOT_PKG', 'CHATBOT_EXTENDED_PKG', 'CHATBOT_MCP_API')
ORDER BY object_name;
```

## 4) Test MCP-facing methods

```sql
SELECT chatbot_mcp_api.health FROM dual;
SELECT chatbot_mcp_api.ask_json('Show me all open sales orders') FROM dual;
SELECT chatbot_mcp_api.ask_with_email_json('Send today order summary', 'user@example.com') FROM dual;
```

## 5) Use from VS Code chat with SQLcl MCP tools

Use prompts like:

- "Run SQL: SELECT chatbot_mcp_api.health FROM dual"
- "Run SQL: SELECT chatbot_mcp_api.ask_json('Show orders for customer Acme') FROM dual"

## 6) Security recommendations

- Do not hardcode API keys in package bodies.
- Grant execute only to required schema users.
- If exposing to broader audiences, create a least-privilege schema for `chatbot_mcp_api` execution.

## 7) Troubleshooting

- If package compile fails, run:

```sql
SHOW ERRORS PACKAGE chatbot_mcp_api;
SHOW ERRORS PACKAGE BODY chatbot_mcp_api;
```

- If SQLcl MCP does not show tools, in VS Code run command palette:
  - `MCP: List Servers` and ensure SQLcl MCP is enabled.
