# Quick Reference - Combined Operations Commands

## Most Common Scenarios

### 1️⃣ Booked Orders with Customers (2024) - YOUR TEST CASE

```
✓ Request: "Get BOOKED order details and customer details of the year 2024"

→ Query Type: combined_orders_customers
→ Tables Joined: OE_ORDER_HEADERS_ALL + HZ_PARTIES + HZ_CUST_ACCOUNTS
→ Filters: Year=2024, Status=BOOKED
→ Expected Columns: ORDER_NUMBER, CUSTOMER_NAME, ORDER_STATUS, ACCOUNT_NUMBER, etc.

Sample Results:
┌──────────┬──────────────────────┬──────────┬────────────────┐
│ ORDER_# │ CUSTOMER_NAME        │ STATUS   │ ACCOUNT_NUMBER │
├──────────┼──────────────────────┼──────────┼────────────────┤
│ 67965    │ ACME Corporation     │ BOOKED   │ 3141592        │
│ 67966    │ Tech Systems Inc     │ BOOKED   │ 2718281        │
│ 67967    │ Global Enterprises   │ BOOKED   │ 1618033        │
└──────────┴──────────────────────┴──────────┴────────────────┘
```

---

### 2️⃣ Booked Orders (Year Filter Only)

```
✓ Requests:
  - "Show BOOKED orders from 2024"
  - "Booked orders 2024"
  - "List booked orders for year 2024"

→ Query Type: combined_orders_date
→ Filters: Year=2024, Status=BOOKED
→ Returns: Order details with order amount and customer count
```

---

### 3️⃣ Orders with Inventory/Items

```
✓ Requests:
  - "Show orders with inventory item information"
  - "Orders and their line items with details"
  - "List orders with item codes and descriptions"

→ Query Type: combined_orders_inventory
→ Tables: OE_ORDER_HEADERS + OE_ORDER_LINES + MTL_SYSTEM_ITEMS_B
→ Returns: Item codes, descriptions, quantities, prices
```

---

### 4️⃣ Orders with Payment Terms & Pricing

```
✓ Requests:
  - "Show orders with payment terms and price lists"
  - "Orders with their payment terms"
  - "List orders with terms and pricing"

→ Query Type: combined_orders_setup
→ Tables: OE_ORDER_HEADERS + RA_TERMS + QP_LIST_HEADERS
→ Returns: Payment term names, price list names, order amounts
```

---

### 5️⃣ Customer Order Summary

```
✓ Requests:
  - "Show customers and their order counts"
  - "Customers with order history by status"
  - "List customers with booked/shipped/cancelled order counts"

→ Query Type: combined_customers_orders
→ Returns: Aggregated order counts by status, total value per customer
```

---

## Status Filter Reference

Use these statuses in your requests:

| Status | Meaning | Usage |
|--------|---------|-------|
| BOOKED | Order confirmed | "BOOKED orders" |
| ENTERED | Order entered but not confirmed | "ENTERED orders" |
| SHIPPED | Order shipped | "SHIPPED orders" |
| CANCELLED | Order cancelled | "CANCELLED orders" |
| CLOSED | Order closed | "CLOSED orders" |

---

## Year Filter Reference

```
Current Year: 2024, 2023, 2022, etc.

Examples:
- "2024" → Orders placed in 2024
- "from 2024" → Orders from year 2024
- "of the year 2024" → Orders in 2024
- "for year 2024" → Orders for year 2024
```

---

## Smart Rephrasing Guide

If your request isn't detected as combined operation:

### ❌ Try Avoid Phrasing:
- "Show orders" (too vague - what about them?)
- "Customer data" (incomplete - what customer data?)
- "2024" (missing operation)

### ✅ Better Phrasing Patterns:
- "Orders + Customer details" → Two elements combined
- "Orders WITH customer names" → Explicit JOIN
- "Booked orders from 2024 and their customers" → Multiple conditions + entities
- "Show orders along with customer information" → Clearly combined

---

## Pattern Recognition

The system looks for these patterns:

```
PATTERN 1: [ORDER_STATUS] orders [WITH/AND] [CUSTOMER]
  Examples:
    ✓ "Booked orders with customer details"
    ✓ "BOOKED orders and their customers"
    ✓ "Entered orders with customer information"

PATTERN 2: [ORDER_STATUS] [YEAR]
  Examples:
    ✓ "Booked orders from 2024"
    ✓ "Cancelled orders 2024"
    ✓ "Orders 2024 status booked"

PATTERN 3: [ORDERS] [WITH/AND] [INVENTORY/ITEMS]
  Examples:
    ✓ "Orders with inventory items"
    ✓ "Show orders and their line items"

PATTERN 4: [ORDERS] [WITH/AND] [SETUP_DATA]
  Examples:
    ✓ "Orders with payment terms"
    ✓ "Show orders and price lists"

PATTERN 5: [CUSTOMERS] [WITH/AND] [ORDERS]
  Examples:
    ✓ "Customers and their orders"
    ✓ "Show customers with order counts"
```

---

## Testing Your Combined Operations

### Test Case 1: Does it work?
```
Input: "Get BOOKED order details and customer details of the year 2024"
Expected Response:
  {
    "type": "dynamic_table",
    "is_combined_operation": true,
    "sql": "[SELECT statement shown]",
    "rows": [array of results],
    "columns": [ORDER_NUMBER, CUSTOMER_NAME, ...]
  }
```

### Test Case 2: Verify SQL
```
Look for these in the generated SQL:
  ✓ Multiple table names (JOINs)
  ✓ WHERE clause with filters
  ✓ EXTRACT(YEAR FROM ...) for year filter
  ✓ UPPER(FLOW_STATUS_CODE) for status
```

### Test Case 3: Check Results
```
Verify the results:
  ✓ Contains customer names (not just IDs)
  ✓ Shows order numbers and statuses
  ✓ Dates match 2024 if filtered by year
  ✓ Status is all BOOKED if filtered by status
```

---

## Response Format

### Successful Combined Operation:
```json
{
  "type": "dynamic_table",
  "sql": "SELECT ... FROM OE_ORDER_HEADERS_ALL...",
  "explanation": "Combined query generated for: combined orders customers",
  "columns": ["ORDER_NUMBER", "CUSTOMER_NAME", "ORDER_STATUS", ...],
  "rows": [
    ["67965", "ACME Corp", "BOOKED", ...],
    ["67966", "Tech Inc", "BOOKED", ...]
  ],
  "is_combined_operation": true
}
```

### No Results:
```json
{
  "reply": "No records found.",
  "type": "text"
}
```

### Error:
```json
{
  "reply": "SQL execution error: [error message]",
  "type": "error",
  "sql": "[the problematic SQL]"
}
```

---

## Debugging Checklist

When something doesn't work:

1. ✓ Check response has `is_combined_operation: true`
   - If false → Operation not detected, try rephrasing

2. ✓ Review generated SQL in response
   - Click "View Generated SQL"
   - Look for expected table names
   - Verify WHERE clause filters

3. ✓ Verify filters were applied
   - Look for `WHERE ooha.ORG_ID = 204`
   - Check for `EXTRACT(YEAR FROM ooha.ORDERED_DATE) = 2024`
   - Verify status filter: `UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'`

4. ✓ Test in database directly
   - Copy SQL from response
   - Run in SQL*Plus or SQL Developer
   - Verify it returns results

5. ✓ Check database connection
   - Verify config.json has correct credentials
   - Test connection independently

---

## Performance Expectations

| Query Type | Typical Response Time | Max Rows |
|------------|----------------------|----------|
| combined_orders_customers | < 2 seconds | 50 |
| combined_orders_inventory | < 3 seconds | 50 |
| combined_orders_setup | < 2 seconds | 50 |
| combined_orders_date | < 1 second | 50 |
| combined_customers_orders | < 3 seconds | 50 |

If queries are slow:
- Check database load
- Verify network connectivity
- Consider adding indexes on filter columns

---

## Real Examples

### Example 1: Daily Report
```
"Get BOOKED orders with customer details for 2024"
→ Use this to generate daily order reports
→ Shows customer names (easy to identify)
→ Can be exported to Excel
```

### Example 2: Status Analysis
```
"Show me booked orders from 2024"
→ Quick count of BOOKED orders
→ See order amounts
→ Track order trends
```

### Example 3: Inventory Check
```
"Show orders with inventory items and prices"
→ Verify what items are ordered
→ Check pricing
→ Identify patterns
```

### Example 4: Customer Health Check
```
"Customers and their order history by status"
→ See customer order patterns
→ Identify high-value customers
→ Track repeat business
```

### Example 5: Setup Review
```
"Show orders with payment terms and prices"
→ Verify terms applied correctly
→ Check pricing consistency
→ Audit configurations
```

---

## Cheat Sheet - Copy & Paste

```
🔹 Booked Orders + Customers (2024):
"Get BOOKED order details and customer details of the year 2024"

🔹 Status by Year:
"Show BOOKED orders from 2024"

🔹 Orders + Items:
"Show orders with inventory item information"

🔹 Orders + Terms:
"Show orders with payment terms and price lists"

🔹 Customer Summary:
"Show customers and their order counts by status"
```

---

## Tips & Tricks

💡 **Tip 1:** Be specific about year
- Good: "orders for 2024"
- Less good: "recent orders"

💡 **Tip 2:** Mention both elements
- Good: "orders with customers"
- Less good: "orders" (just one element)

💡 **Tip 3:** Use actual status names
- Good: "BOOKED orders"
- Less good: "confirmed orders"

💡 **Tip 4:** Ordering matters
- Good: "BOOKED orders from 2024 with customers"
- Also good: "2024 BOOKED orders and their customers"

💡 **Tip 5:** Check SQL for accuracy
- Always review generated SQL
- Click "View Generated SQL"
- Verify it matches expectations

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| "No records found" | No BOOKED orders for that period | Try different year or status |
| Combined not detected | Unclear wording | Use pattern: "orders WITH customers" |
| SQL error | Invalid table/column | Check database, verify table names |
| Connection error | DB offline | Check db_host in config.json |
| Wrong table joined | Query type misidentified | Rephrase more specifically |

---

## Next Steps

1. **Try the examples above** - Test each combined operation type
2. **Review generated SQL** - Click "View Generated SQL" to see how it works
3. **Customize if needed** - Modify queries for your specific needs
4. **Create reports** - Use for daily/weekly order reporting
5. **Export results** - Use email feature to send results

---

## Documentation Map

```
📍 You Are Here: QUICK_REFERENCE.md

📖 Related Docs:
  ├─ COMBINED_OPERATIONS_GUIDE.md (detailed guide)
  ├─ COMBINED_OPERATIONS_TEST_GUIDE.md (testing)
  ├─ IMPLEMENTATION_DETAILS.md (technical)
  ├─ COMBINED_OPERATIONS_SUMMARY.md (overview)
  └─ QUICKSTART.md (getting started)
```

---

## Support

📧 Issue? Check the detailed guides above  
🔧 Technical question? See IMPLEMENTATION_DETAILS.md  
🧪 Want to test? See COMBINED_OPERATIONS_TEST_GUIDE.md  
❓ Need examples? See COMBINED_OPERATIONS_GUIDE.md  

---

**Ready to use combined operations?** 🚀  
Go to `http://localhost:5000` and try one of the examples above!
