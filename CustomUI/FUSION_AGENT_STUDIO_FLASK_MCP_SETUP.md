# Oracle Fusion Agent Studio + Flask MCP Setup

This guide wires your existing Sales Order Flask app (`app7.1.py`) to Oracle Fusion Agent Studio using a Python MCP server (`salesorder_mcp_server.py`).

## 1) Start your Flask sales-order API

From workspace root:

```powershell
c:/Users/pavan.maccha/Desktop/Python/CustomUI/.venv/Scripts/python.exe app7.1.py
```

Default Flask URL should be `http://127.0.0.1:5000` unless your config overrides it.

## 2) Start the MCP bridge server

In a second terminal:

```powershell
$env:SALESORDER_API_BASE_URL="http://127.0.0.1:5000"
$env:SALESORDER_MCP_HOST="0.0.0.0"
$env:SALESORDER_MCP_PORT="8001"
$env:SALESORDER_MCP_PATH="/mcp"
c:/Users/pavan.maccha/Desktop/Python/CustomUI/.venv/Scripts/python.exe salesorder_mcp_server.py
```

MCP endpoint URL will be:

`http://<your-host>:8001/mcp`

If Fusion Agent Studio cannot reach localhost, deploy this bridge on a reachable host and use that host URL.

## 3) Register MCP server in Fusion Agent Studio

In Oracle Fusion Agent Studio:

1. Open your agent.
2. Go to tools / integrations for MCP server configuration.
3. Add MCP server endpoint:
   - URL: `http://<reachable-host>:8001/mcp`
   - Transport: Streamable HTTP (if selectable).
4. Save and test connection.

## 4) Exposed MCP tools

The server exposes these tools:

1. `health()`
2. `salesorder_chat(message, history_json="[]")`
3. `create_sales_order(order_payload_json)`
4. `get_order_by_number(order_number)`

## 5) Sample prompts for your Fusion agent

1. "Use tool `salesorder_chat` with message: Show booked orders in last 30 days"
2. "Use tool `get_order_by_number` for order number 67965"
3. "Use tool `create_sales_order` with payload JSON for customer Vision and item AS54888"

## 6) Security notes

1. Use HTTPS and a private network path between Fusion and MCP host.
2. Keep secrets out of prompts; pass credentials as environment variables.
3. If your Flask API login is required, set:
   - `SALESORDER_API_USER`
   - `SALESORDER_API_PASSWORD`

## 7) Troubleshooting

1. MCP connection fails:
   - Ensure port `8001` is open and reachable from Fusion environment.
2. Tool errors on API calls:
   - Verify Flask app is up and `/api/chat` responds.
3. Auth errors from Flask:
   - Set `SALESORDER_API_USER` and `SALESORDER_API_PASSWORD` env vars before starting MCP server.
