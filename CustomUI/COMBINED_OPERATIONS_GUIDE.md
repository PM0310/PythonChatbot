# Combined Operations & Dynamic SQL Query Guide

## Overview
The refactored Sales Order Assistant now automatically detects and handles **combined operations** - requests that require joining multiple data sources or applying multiple filters. When detected, the system automatically generates optimized SQL queries using Oracle Apps standard tables.

## What Are Combined Operations?

A combined operation involves **2 or more conditions or data sources**:

### Examples of Combined Operations:
1. **Order + Customer**: "Get BOOKED orders with customer details for 2024"
2. **Order + Inventory**: "Show orders with inventory item information"
3. **Order + Setup Data**: "List orders with payment terms and price list"
4. **Customer + Order**: "Show customers and their order history"
5. **Status + Date**: "Booked orders from 2024"

### Simple Operations (Single Action):
- "Get order 67965" → Single operation
- "Show customer ABC" → Single operation
- "Create new order" → Single operation

## Supported Combined Query Types

### 1. **combined_orders_customers**
Joins order headers with customer details (party, account information).

**Example Requests:**
- "Get BOOKED orders with customer details for 2024"
- "Show all booked orders and their customers"
- "Orders and customer names for 2024"

**Tables Used:**
- OE_ORDER_HEADERS_ALL (orders)
- OE_ORDER_LINES_ALL (line items)
- HZ_CUST_ACCOUNTS (customer accounts)
- HZ_PARTIES (customer names)

**Filters Supported:**
- Year (e.g., 2024)
- Status (e.g., BOOKED, SHIPPED, CANCELLED, ENTERED)

**Sample Query Generated:**
```sql
SELECT 
    ooha.ORDER_NUMBER,
    ooha.HEADER_ID,
    ooha.FLOW_STATUS_CODE AS ORDER_STATUS,
    ooha.CUST_PO_NUMBER,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    hca.ACCOUNT_NUMBER,
    ooha.TRANSACTIONAL_CURR_CODE AS CURRENCY,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT
FROM OE_ORDER_HEADERS_ALL ooha
INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
INNER JOIN HZ_CUST_ACCOUNTS hca ON hca.CUST_ACCOUNT_ID = ooha.SOLD_TO_ORG_ID
INNER JOIN HZ_PARTIES hp ON hp.PARTY_ID = hca.PARTY_ID
WHERE ooha.ORG_ID = 204
  AND UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'
  AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = 2024
GROUP BY ...
ORDER BY ooha.ORDERED_DATE DESC, ooha.ORDER_NUMBER DESC
```

---

### 2. **combined_orders_inventory**
Joins orders with inventory item details.

**Example Requests:**
- "Show orders with item information"
- "List booked orders and their inventory items"
- "Orders with item codes and descriptions"

**Tables Used:**
- OE_ORDER_HEADERS_ALL (orders)
- OE_ORDER_LINES_ALL (line items)
- MTL_SYSTEM_ITEMS_B (inventory items)

**Sample Query Generated:**
```sql
SELECT 
    ooha.ORDER_NUMBER,
    oola.LINE_NUMBER,
    msi.SEGMENT1 AS ITEM_CODE,
    msi.DESCRIPTION AS ITEM_DESCRIPTION,
    oola.ORDERED_QUANTITY,
    oola.ORDER_QUANTITY_UOM,
    oola.UNIT_SELLING_PRICE,
    (oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS LINE_TOTAL,
    oola.FLOW_STATUS_CODE AS LINE_STATUS
FROM OE_ORDER_HEADERS_ALL ooha
INNER JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
INNER JOIN MTL_SYSTEM_ITEMS_B msi ON msi.INVENTORY_ITEM_ID = oola.INVENTORY_ITEM_ID
WHERE ooha.ORG_ID = 204
  AND UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'
ORDER BY ooha.ORDERED_DATE DESC
```

---

### 3. **combined_orders_setup**
Joins orders with payment terms, price lists, and setup data.

**Example Requests:**
- "Show orders with payment terms"
- "List orders and their price lists"
- "Orders with terms and pricing information"

**Tables Used:**
- OE_ORDER_HEADERS_ALL
- OE_ORDER_LINES_ALL
- RA_TERMS_VL (payment terms)
- QP_LIST_HEADERS_VL (price lists)
- HZ_PARTIES

**Sample Query Generated:**
```sql
SELECT 
    ooha.ORDER_NUMBER,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    rt.NAME AS PAYMENT_TERM,
    qpl.NAME AS PRICE_LIST_NAME,
    ooha.TRANSACTIONAL_CURR_CODE,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT,
    SUM(oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS ORDER_TOTAL
FROM OE_ORDER_HEADERS_ALL ooha
LEFT JOIN OE_ORDER_LINES_ALL oola ON ooha.HEADER_ID = oola.HEADER_ID
...
```

---

### 4. **combined_orders_date**
Orders filtered by status and specific year.

**Example Requests:**
- "Booked orders from 2024"
- "Show cancelled orders for 2024"
- "Entered orders in 2024"

**Supported Statuses:**
- BOOKED
- ENTERED
- SHIPPED
- CANCELLED
- CLOSED

**Sample Query Generated:**
```sql
SELECT 
    ooha.ORDER_NUMBER,
    ooha.FLOW_STATUS_CODE,
    TO_CHAR(ooha.ORDERED_DATE, 'DD-MON-YYYY') AS ORDERED_DATE,
    hp.PARTY_NAME AS CUSTOMER_NAME,
    COUNT(DISTINCT oola.LINE_ID) AS LINE_COUNT,
    SUM(oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS ORDER_AMOUNT
FROM OE_ORDER_HEADERS_ALL ooha
WHERE ooha.ORG_ID = 204
  AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = 2024
  AND UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'
```

---

### 5. **combined_customers_orders**
Customer summary with their order history and status breakdown.

**Example Requests:**
- "Show customers and their orders"
- "List customers with booked, shipped, cancelled order counts"
- "Customer order summary"

**Sample Query Generated:**
```sql
SELECT 
    hp.PARTY_NAME AS CUSTOMER_NAME,
    hca.ACCOUNT_NUMBER,
    COUNT(DISTINCT ooha.HEADER_ID) AS TOTAL_ORDERS,
    COUNT(DISTINCT CASE WHEN UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED' THEN ooha.HEADER_ID END) AS BOOKED_ORDERS,
    COUNT(DISTINCT CASE WHEN UPPER(ooha.FLOW_STATUS_CODE) = 'SHIPPED' THEN ooha.HEADER_ID END) AS SHIPPED_ORDERS,
    COUNT(DISTINCT CASE WHEN UPPER(ooha.FLOW_STATUS_CODE) = 'CANCELLED' THEN ooha.HEADER_ID END) AS CANCELLED_ORDERS,
    SUM(oola.ORDERED_QUANTITY * oola.UNIT_SELLING_PRICE) AS TOTAL_ORDER_VALUE
FROM HZ_PARTIES hp
...
```

---

## How to Use Combined Operations

### Step 1: Identify Combined Operations
Look for requests that mention:
- **Multiple tables/entities**: "orders AND customer details"
- **Multiple filters**: "status AND year"
- **Relationships**: "orders WITH customers"
- **Summary data**: "customers and their orders"

### Step 2: Formulate Your Request
Use natural language that clearly indicates what you want:

```
✅ Good Combined Operation Requests:
- "Get BOOKED orders with customer details for 2024"
- "Show me booked orders and their customers from 2024"
- "List orders with customer and inventory information"
- "BOOKED orders for 2024 including customer names"

❌ Avoid Ambiguous Requests:
- "Booked orders" (missing combining element)
- "2024" (too vague)
- "Customer" (incomplete request)
```

### Step 3: System Automatically Generates SQL
The system will:
1. **Detect** the combined operation type
2. **Extract** filters (year, status, etc.)
3. **Generate** optimized SQL using Oracle Apps standard tables
4. **Execute** against the database connection
5. **Return** results in a formatted table

## Detection Algorithm

The system uses pattern matching and AI to detect combined operations:

### Pattern-Based Detection:
```
Pattern: (order|booked|entered|cancelled).*(customer|party|account)
Type: combined_orders_customers

Pattern: (order|booked|entered|cancelled).*(inventory|item|onhand)
Type: combined_orders_inventory

Pattern: (customer|party|account).*(order|booked)
Type: combined_customers_orders

Pattern: (status|booked|cancelled).*(year|month|date|2024)
Type: combined_orders_date
```

### AI-Based Detection (with Copilot token):
Uses `COMBINED_OPERATIONS_DETECTION_SYSTEM_PROMPT` to intelligently identify:
- Operations being combined
- Filters and conditions
- Required SQL type
- Necessary joins

## Database Connection

Combined operations queries are executed directly against the Oracle database using:
- **Function**: `execute_query(sql, params=None)`
- **Connection**: Oracle database configured in `config.json`
- **Security**: All queries validated to be SELECT-only (no INSERT, UPDATE, DELETE, DROP)

### Configuration Required:
```json
{
  "db_host": "your_host",
  "db_port": "1541",
  "db_service": "EBS122",
  "db_user": "apps",
  "db_password": "apps",
  "oracle_client_path": "C:\\Oracle\\instantclient_19_10"
}
```

## Example Scenarios

### Scenario 1: Booked Orders for 2024 with Customers
**User Request:** "Get BOOKED order details and customer details for year 2024"

**System Response:**
1. ✓ Detected: combined_orders_customers
2. ✓ Filters: year=2024, status=BOOKED
3. ✓ Generated SQL joins OE_ORDER_HEADERS_ALL + HZ_PARTIES + HZ_CUST_ACCOUNTS
4. ✓ Returns table with: ORDER_NUMBER, ORDER_STATUS, CUSTOMER_NAME, ORDERED_DATE, etc.

### Scenario 2: Orders with Line Items and Inventory
**User Request:** "Show me booked orders with their inventory items"

**System Response:**
1. ✓ Detected: combined_orders_inventory
2. ✓ Filters: status=BOOKED
3. ✓ Generated SQL joins OE_ORDER_HEADERS + OE_ORDER_LINES + MTL_SYSTEM_ITEMS_B
4. ✓ Returns table with: ORDER_NUMBER, LINE_NUMBER, ITEM_CODE, DESCRIPTION, QUANTITY, PRICE

### Scenario 3: Customer Order Summary
**User Request:** "Show customers and their order counts by status"

**System Response:**
1. ✓ Detected: combined_customers_orders
2. ✓ Generated SQL with grouped order counts
3. ✓ Returns: CUSTOMER_NAME, TOTAL_ORDERS, BOOKED_ORDERS, SHIPPED_ORDERS, CANCELLED_ORDERS, TOTAL_VALUE

## Troubleshooting

### Issue: Combined Operation Not Detected
**Solution:**
- Use clearer language indicating multiple data sources
- Include both elements: "orders AND customers"
- Add specific filters: "status AND year"
- Try rephrasing: "Get booked orders for 2024 with customer details"

### Issue: SQL Execution Error
**Solution:**
- Verify database connection in config.json
- Check Oracle client installation
- Ensure SQL syntax is valid (should be shown in error message)
- Verify table names match your Oracle instance

### Issue: No Records Found
**Possible Causes:**
- No BOOKED orders exist in the database for the specified period
- Filters are too restrictive
- Data doesn't exist for the specified year/status combination
**Solution:**
- Broaden filters: try different year or status
- Verify data exists in database independently

## Performance Considerations

The generated SQL queries are optimized for:
1. **Proper JOIN types** (INNER, LEFT, OUTER as appropriate)
2. **WHERE clause filtering** (before grouping)
3. **GROUP BY** only when aggregations needed
4. **Row limiting** (usually ROWNUM <= 50 for results)
5. **Column selection** (only needed columns)

## Security Features

✓ **SQL Injection Protection**: All user input filtered and parameterized  
✓ **SELECT-Only Enforcement**: No INSERT, UPDATE, DELETE, or DDL statements  
✓ **Read-Only Database**: Uses SELECT permissions only  
✓ **Query Validation**: Pattern matching and AI validation before execution  
✓ **Audit Logging**: Queries logged with execution details  

## Next Steps

1. **Test Combined Operations**: Try the example requests
2. **Monitor SQL Execution**: Check logs for generated SQL
3. **Customize Queries**: Modify `generate_combined_sql()` for specific needs
4. **Add New Query Types**: Extend `COMBINED_OPERATIONS_DETECTION_SYSTEM_PROMPT`
5. **Performance Tuning**: Monitor slow queries and optimize

## Support & Documentation

For more information:
- See [REFACTORING_NOTES.md](REFACTORING_NOTES.md) for architecture
- Check [app7.py](app7.py) for implementation details
- Review [system_prompts.py](system_prompts.py) for prompt templates
- Consult [config_manager.py](config_manager.py) for configuration options
