# Implementation Details - Combined Operations & Dynamic SQL

## Code Changes Summary

### 1. system_prompts.py Updates

**Added:**
- `COMBINED_OPERATIONS_DETECTION_SYSTEM_PROMPT` - Prompt for detecting combined operations
- `build_combined_operations_user_prompt()` - Function to build user prompt for detection

**Purpose:**
- Allows AI to understand when user is requesting multiple data sources/operations
- Extracts filters and determines optimal SQL type

```python
COMBINED_OPERATIONS_DETECTION_SYSTEM_PROMPT = """
You are an ERP Request Analyzer.
Analyze user requests to identify if they contain COMBINED/MULTIPLE operations.

Combined Operations Examples:
- "Get BOOKED orders with customer details" → order_details + customer_details
...
"""
```

---

### 2. app7.py New Functions

#### Function: `detect_combined_operations(history, user_input)`

**Location:** After `is_safe_select_query()` function

**Purpose:** Detect if user request contains combined operations

**Logic:**
1. If no Copilot token: Use regex pattern matching
2. If Copilot available: Use AI-based detection with system prompt
3. Returns structured dict with:
   - `is_combined`: Boolean
   - `operations`: List of operations
   - `requires_dynamic_sql`: Boolean
   - `dynamic_sql_type`: Type identifier
   - `filters`: Extracted filters (year, status, etc.)

**Example Usage:**
```python
combined_ops = detect_combined_operations(history, "Get BOOKED orders with customers for 2024")
# Returns:
# {
#   "is_combined": True,
#   "operations": ["orders", "customers"],
#   "requires_dynamic_sql": True,
#   "dynamic_sql_type": "combined_orders_customers",
#   "filters": {"status": "BOOKED", "year": 2024}
# }
```

---

#### Function: `generate_combined_sql(query_type, filters)`

**Location:** After `detect_combined_operations()` function

**Purpose:** Generate SQL for specific combined operation types

**Supported Query Types:**

| Type | Purpose | Tables |
|------|---------|--------|
| `combined_orders_customers` | Orders with customer details | OE_ORDER_HEADERS_ALL, HZ_PARTIES, HZ_CUST_ACCOUNTS |
| `combined_orders_inventory` | Orders with inventory items | OE_ORDER_HEADERS_ALL, OE_ORDER_LINES_ALL, MTL_SYSTEM_ITEMS_B |
| `combined_orders_setup` | Orders with terms and pricing | OE_ORDER_HEADERS_ALL, RA_TERMS_VL, QP_LIST_HEADERS_VL |
| `combined_orders_date` | Orders by status and year | OE_ORDER_HEADERS_ALL with filters |
| `combined_customers_orders` | Customer summaries with order stats | HZ_PARTIES, HZ_CUST_ACCOUNTS, OE_ORDER_HEADERS_ALL |

**Example SQL Generated:**
```sql
SELECT 
    ooha.ORDER_NUMBER,
    ooha.HEADER_ID,
    ooha.FLOW_STATUS_CODE AS ORDER_STATUS,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    hca.ACCOUNT_NUMBER,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE
FROM OE_ORDER_HEADERS_ALL ooha
INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
INNER JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
INNER JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
WHERE ooha.ORG_ID = 204
AND UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'
AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = 2024
```

---

### 3. app7.py Chat Endpoint Modifications

**Location:** In `/api/chat` route, before "Dynamic Query fallback"

**Changes:**
Added combined operations check before falling back to AI SQL generation:

```python
# Check for combined operations (2 or more conditions/operations)
combined_ops = detect_combined_operations(history, user_msg)
if combined_ops.get("requires_dynamic_sql") and combined_ops.get("dynamic_sql_type"):
    # Generate SQL for combined operations
    combined_result = generate_combined_sql(
        combined_ops.get("dynamic_sql_type"),
        combined_ops.get("filters", {})
    )
    
    if combined_result and combined_result.get("sql"):
        sql_query = combined_result.get("sql", "").strip()
        # ... execute and return results
        return jsonify({
            "type": "dynamic_table",
            "sql": sql_query,
            "explanation": explanation,
            "columns": columns,
            "rows": rows,
            "is_combined_operation": True  # NEW FLAG
        })
```

**Key Addition:**
- Response includes `"is_combined_operation": True` flag
- Allows frontend to identify combined operation queries

---

## Data Flow Diagram

```
User Input (Chat Message)
    ↓
    ├─ Quick Phrase Check (hi, hello, etc.)
    ├─ Email Pattern Check
    ├─ Intent Extraction (action type detection)
    │   ├─ create
    │   ├─ add_line
    │   ├─ email
    │   ├─ get_range
    │   ├─ get
    │   └─ dynamic_query
    │
    ↓ If none matched ↓
    ├─ COMBINED OPERATIONS DETECTION (NEW)
    │   ├─ Pattern Matching (regex)
    │   │   ├─ order.*customer → combined_orders_customers
    │   │   ├─ order.*inventory → combined_orders_inventory
    │   │   ├─ customer.*order → combined_customers_orders
    │   │   ├─ order.*setup → combined_orders_setup
    │   │   ├─ status.*date → combined_orders_date
    │   │   └─ (or AI-based if Copilot available)
    │   │
    │   └─ If Combined Operation Found:
    │       ├─ Extract Filters (year, status, etc.)
    │       └─ Generate Optimized SQL
    │           └─ Execute Query
    │               └─ Return Results
    │
    ↓ If not combined ↓
    └─ DYNAMIC SQL GENERATION (FALLBACK)
        ├─ AI creates general SQL
        └─ Execute & Return
```

---

## Filter Extraction Logic

The system extracts these filters from user input:

### Year Filter
```python
import re
year_match = re.search(r'\b(202[0-9]|20[1-9][0-9]|19[0-9]{2})\b', user_input)
year = int(year_match.group(1)) if year_match else None
```

### Status Filter
```python
statuses = ["BOOKED", "ENTERED", "SHIPPED", "CANCELLED", "CLOSED"]
for status in statuses:
    if status.lower() in user_input.lower():
        status_found = status
        break
```

### Date Range Filter
```python
date_ranges = {
    "this_month": "TRUNC(SYSDATE, 'MM')",
    "this_week": "TRUNC(SYSDATE, 'IW')",
    "last_30_days": "SYSDATE - 30",
}
```

---

## Pattern Matching Rules

### Combined Operations Detection Patterns

```python
patterns = [
    (r"(order|booked|entered|cancelled).*(customer|party|account)", 
     "combined_orders_customers"),
    
    (r"(order|booked|entered|cancelled).*(inventory|item|onhand)", 
     "combined_orders_inventory"),
    
    (r"(customer|party|account).*(order|booked)", 
     "combined_customers_orders"),
    
    (r"(order|sales).*(payment term|price list|salesrep)", 
     "combined_orders_setup"),
    
    (r"(status|booked|cancelled).*(year|month|date|2024|2023)", 
     "combined_orders_date"),
]
```

**Matching Logic:**
- Case-insensitive matching
- Patterns tested sequentially
- First match wins
- Multiple keywords can appear in any order

---

## SQL Template Examples

### Template: combined_orders_customers

```python
def generate_combined_sql(query_type, filters):
    org_id = get_org_id()
    year = filters.get("year")
    status = filters.get("status", "BOOKED")
    
    date_clause = ""
    if year:
        date_clause = f"AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = {year}"
    
    sql = f"""
    SELECT 
        ooha.ORDER_NUMBER,
        ooha.HEADER_ID,
        ooha.FLOW_STATUS_CODE AS ORDER_STATUS,
        ooha.CUST_PO_NUMBER,
        TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
        hp.PARTY_NAME AS CUSTOMER_NAME,
        hca.ACCOUNT_NUMBER,
        COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT
    FROM OE_ORDER_HEADERS_ALL ooha
    INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
    INNER JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
    INNER JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
    WHERE ooha.ORG_ID = {org_id}
    AND UPPER(ooha.FLOW_STATUS_CODE) = '{status.upper()}'
    {date_clause}
    GROUP BY ...
    """
    return sql
```

---

## Performance Optimizations

### 1. JOIN Strategy
- Use INNER JOIN when relationship is mandatory
- Use LEFT JOIN when including optional data
- Order joins by selectivity (most filtering first)

### 2. WHERE Clause
- Apply filters BEFORE GROUP BY
- Use database-level filtering vs. application-level
- Example: `WHERE EXTRACT(YEAR FROM ...) = 2024` (database filters)

### 3. Column Selection
- Only SELECT needed columns
- Avoid SELECT *
- Use aliases for clarity

### 4. Aggregations
- GROUP BY only when necessary
- Use DISTINCT sparingly
- Pre-aggregate at database level

### 5. Row Limiting
- Add ROWNUM <= 50 or similar
- Prevent returning excessive data
- Allow result pagination

---

## Error Handling

### Type 1: Invalid Status
```
User: "Show INVALID_STATUS orders"
Detection: combined_orders_date (status filter)
SQL: ... AND UPPER(ooha.FLOW_STATUS_CODE) = 'INVALID_STATUS'
Result: No records found (empty result set)
```

### Type 2: No Data for Period
```
User: "BOOKED orders from year 3000"
Detection: combined_orders_date (year filter)
Result: "No records found." message
```

### Type 3: SQL Execution Error
```
User: Request with invalid table reference
Error Flow:
  1. generate_combined_sql() creates SQL
  2. execute_query() attempts execution
  3. Database throws error
  4. Exception caught
  5. Error message returned to user with SQL displayed
```

**Error Response Format:**
```json
{
  "reply": "SQL execution error: ORA-00904: invalid column name",
  "type": "error",
  "sql": "SELECT ... [shows the problematic query]"
}
```

### Type 4: Connection Error
```
User: Any request (database down)
Error Flow:
  1. get_db_connection() fails
  2. Exception caught in execute_query()
  3. Error returned: "Database connection failed"
```

---

## Debugging Combined Operations

### Enable Debug Logging

Add to app7.py:
```python
def detect_combined_operations(history, user_input):
    print(f"[DEBUG] Input: {user_input}")
    
    # ... pattern matching ...
    
    print(f"[DEBUG] Is Combined: {combined_ops['is_combined']}")
    print(f"[DEBUG] Query Type: {combined_ops['dynamic_sql_type']}")
    print(f"[DEBUG] Filters: {combined_ops['filters']}")
    
    return combined_ops
```

### Check Generated SQL

The response includes the SQL:
```json
{
  "type": "dynamic_table",
  "sql": "SELECT ... [full SQL query here]"
}
```

### Validate SQL Syntax

Test generated SQL directly in Oracle:
```sql
-- Copy SQL from response
-- Paste into SQL*Plus or SQL Developer
-- Verify it executes correctly
```

---

## Troubleshooting Guide

### Issue: Combined Operation Not Detected

**Symptoms:**
- Request is falling back to AI SQL generation
- Not using pre-built combined operation SQL

**Diagnostics:**
1. Check browser console for response
2. Look for `is_combined_operation: false`
3. Check if SQL contains expected tables

**Solutions:**
- Rephrase request to be clearer
- Use explicit keywords: "orders WITH customers"
- Include specific status or year filter
- Try: "Get BOOKED orders with customer details for 2024"

### Issue: Wrong Query Type Detected

**Symptoms:**
- Wrong tables being joined
- Unexpected columns in results

**Diagnostics:**
1. Check `dynamic_sql_type` in response
2. Review generated SQL
3. Compare to expected SQL template

**Solutions:**
- Adjust request to be more specific
- Include both elements explicitly
- Example: Not "Orders and items" but "Order items with product details"

### Issue: No Results Returned

**Symptoms:**
- Response: "No records found."
- But you know data exists

**Diagnostics:**
1. Check filters in SQL WHERE clause
2. Verify status value (BOOKED vs booked vs Booked)
3. Check year filter is correct

**Solutions:**
- Try broader filters: "Show all orders" first
- Verify data exists in database
- Check year/status case sensitivity in request
- Try: "Orders from 2024" (without status filter first)

### Issue: SQL Execution Error

**Symptoms:**
- Error: "SQL execution error: ORA-..."
- SQL displayed in error

**Diagnostics:**
1. Copy SQL from error message
2. Test directly in Oracle SQL*Plus
3. Identify specific error

**Common Oracle Errors:**
- ORA-00904: Invalid column name → Check table aliases
- ORA-01722: Invalid number → Check data type conversion
- ORA-01858: Invalid date format → Check date functions

**Solutions:**
- Verify table names match your database
- Check column names exist
- Ensure Oracle functions used are supported

---

## Configuration for Combined Operations

### Required config.json Settings
```json
{
  "db_host": "your_oracle_host",
  "db_port": "1541",
  "db_service": "EBS122",
  "db_user": "apps",
  "db_password": "apps",
  "oracle_client_path": "C:\\Oracle\\instantclient_19_10",
  "org_id": "204"
}
```

### Optional Settings for AI-Based Detection
```json
{
  "github_copilot_token": "ghp_...",
  "copilot_model": "gpt-4o"
}
```

---

## Future Enhancements

### Planned Improvements
1. **More Query Types**: Add more pre-built combined operation templates
2. **Caching**: Cache common queries for performance
3. **Query Suggestions**: Suggest similar combined operations
4. **Analytics**: Track which combined operations are used most
5. **Export Formats**: Support CSV, JSON export in addition to Excel
6. **Saved Queries**: Allow users to save and reuse combined queries

---

## Code Review Checklist

- [x] Pattern matching for all 5 query types
- [x] Filter extraction (year, status, etc.)
- [x] SQL template generation
- [x] Proper INNER/LEFT JOIN usage
- [x] WHERE clause filtering
- [x] GROUP BY aggregations
- [x] ROWNUM limiting
- [x] Error handling
- [x] Null safety checks
- [x] Column name escaping
- [x] Response format consistency
- [x] Combined operation flag in response

---

## Related Files

- [COMBINED_OPERATIONS_GUIDE.md](COMBINED_OPERATIONS_GUIDE.md) - User guide
- [COMBINED_OPERATIONS_TEST_GUIDE.md](COMBINED_OPERATIONS_TEST_GUIDE.md) - Testing guide
- [system_prompts.py](system_prompts.py) - AI prompts for detection
- [config_manager.py](config_manager.py) - Configuration management
- [app7.py](app7.py) - Main application code
