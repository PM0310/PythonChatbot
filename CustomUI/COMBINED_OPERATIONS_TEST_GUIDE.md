# Testing Guide - Combined Operations & Dynamic SQL Queries

## Test Environment Setup

### Prerequisites
- Python 3.8+
- Flask installed
- Oracle database configured
- config.json with database credentials
- All modules: config_manager.py, system_prompts.py

### Configuration Validation
```bash
# Verify config.json has correct settings
{
  "db_host": "your_oracle_host",
  "db_port": "1541",
  "db_service": "EBS122",
  "db_user": "apps",
  "db_password": "apps",
  "org_id": "204"
}
```

---

## Test Cases for Combined Operations

### Test Case 1: Booked Orders with Customer Details (2024)

**Objective:** Verify detection and execution of combined_orders_customers query type

**Test Request:**
```
"Get BOOKED order details and customer details of the year 2024"
```

**Expected Behavior:**
1. ✓ Intent detection recognizes combined operation
2. ✓ Detects query type: `combined_orders_customers`
3. ✓ Extracts filters: year=2024, status=BOOKED
4. ✓ Generates SQL with JOIN on HZ_PARTIES and HZ_CUST_ACCOUNTS
5. ✓ Returns results in table format

**Expected Columns:**
- ORDER_NUMBER
- HEADER_ID
- ORDER_STATUS
- CUST_PO_NUMBER
- ORDERED_DATE
- CUSTOMER_NAME
- PARTY_ID
- ACCOUNT_NUMBER
- CUST_ACCOUNT_ID
- CURRENCY
- LINE_COUNT

**Verification Steps:**
```python
# In browser console or test script
fetch('/api/chat', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    message: 'Get BOOKED order details and customer details of the year 2024',
    history: []
  })
})
.then(r => r.json())
.then(data => {
  console.log('Type:', data.type); // Should be 'dynamic_table'
  console.log('SQL:', data.sql);
  console.log('Rows Count:', data.rows.length);
  console.log('Is Combined:', data.is_combined_operation); // Should be true
});
```

**Success Criteria:**
- [ ] Response type is 'dynamic_table'
- [ ] `is_combined_operation` is true
- [ ] SQL contains JOIN on HZ_PARTIES and HZ_CUST_ACCOUNTS
- [ ] SQL filters for BOOKED status and year 2024
- [ ] Rows returned with customer information
- [ ] No SQL syntax errors

---

### Test Case 2: Booked Orders from 2024 (Status + Date Filter)

**Objective:** Verify combined_orders_date query type with multiple filters

**Test Request:**
```
"Show me booked orders from 2024"
```

**Expected Behavior:**
1. ✓ Detects combined operation: status + date
2. ✓ Query type: `combined_orders_date`
3. ✓ Filters: status=BOOKED, year=2024
4. ✓ Executes from database connection

**Expected Output:**
- ORDER_NUMBER
- HEADER_ID
- FLOW_STATUS_CODE
- ORDERED_DATE
- CUSTOMER_NAME
- LINE_COUNT
- ORDER_AMOUNT (with aggregation)

**Test SQL Validation:**
```sql
-- Expected SQL pattern
SELECT ... FROM OE_ORDER_HEADERS_ALL ooha
WHERE ooha.ORG_ID = 204
AND EXTRACT(YEAR FROM ooha.ORDERED_DATE) = 2024
AND UPPER(ooha.FLOW_STATUS_CODE) = 'BOOKED'
```

---

### Test Case 3: Orders with Inventory Details

**Objective:** Test combined_orders_inventory query type

**Test Request:**
```
"Show me booked orders with inventory items and pricing"
```

**Expected Behavior:**
1. ✓ Detects combined operation: orders + inventory
2. ✓ Query type: `combined_orders_inventory`
3. ✓ Joins to MTL_SYSTEM_ITEMS_B

**Expected Columns:**
- ORDER_NUMBER
- LINE_NUMBER
- LINE_ID
- ITEM_CODE (SEGMENT1)
- ITEM_DESCRIPTION
- ORDERED_QUANTITY
- UNIT_SELLING_PRICE
- LINE_TOTAL (calculated)
- LINE_STATUS
- ORDERED_DATE

---

### Test Case 4: Customer Order Summary

**Objective:** Test combined_customers_orders aggregation query

**Test Request:**
```
"Show customers and their order history by status"
```

**Expected Behavior:**
1. ✓ Detects combined operation: customers + orders + Email
2. ✓ Query type: `combined_customers_orders`
3. ✓ Aggregates order counts by status

**Expected Columns:**
- CUSTOMER_NAME
- PARTY_ID
- ACCOUNT_NUMBER
- TOTAL_ORDERS
- BOOKED_ORDERS
- SHIPPED_ORDERS
- CANCELLED_ORDERS
- TOTAL_ORDER_VALUE

**Verification:**
```python
# Verify aggregations
data.rows.forEach(row => {
  const booked = parseInt(row[4]); // BOOKED_ORDERS
  const shipped = parseInt(row[5]); // SHIPPED_ORDERS
  const cancelled = parseInt(row[6]); // CANCELLED_ORDERS
  const total = parseInt(row[3]); // TOTAL_ORDERS
  
  // Check: Total should be >= sum of status-specific counts
  console.assert(total >= (booked + shipped + cancelled),
    'Total orders count inconsistent');
});
```

---

### Test Case 5: Orders with Payment Terms and Pricing

**Objective:** Test combined_orders_setup query type

**Test Request:**
```
"Show me booked orders with payment terms and price lists"
```

**Expected Behavior:**
1. ✓ Detects combined operation: orders + setup data
2. ✓ Query type: `combined_orders_setup`
3. ✓ LEFT JOINs to RA_TERMS_VL and QP_LIST_HEADERS_VL

**Expected Columns:**
- ORDER_NUMBER
- CUSTOMER_NAME
- PAYMENT_TERM
- PRICE_LIST_NAME
- CURRENCY
- LINE_COUNT
- ORDER_TOTAL (aggregated)

---

## Test Case 6: Fallback to AI Dynamic SQL

**Objective:** Verify non-combined complex queries still work

**Test Request:**
```
"Show orders with sales rep assigned and their total value"
```

**Expected Behavior:**
1. ✓ Not detected as pre-built combined operation
2. ✓ Falls back to AI SQL generation
3. ✓ AI generates appropriate JOIN query
4. ✓ Executes and returns results

---

## Negative Test Cases

### Test Case 7: Invalid Status Filter

**Test Request:**
```
"Show INVALID_STATUS orders from 2024"
```

**Expected Behavior:**
1. ✓ Query type detected: combined_orders_date
2. ✓ Filter applied: status=INVALID_STATUS
3. ✓ Returns: "No records found" (or empty table)
4. ✓ No SQL errors

---

### Test Case 8: Non-existent Year

**Test Request:**
```
"Get BOOKED orders from year 3000"
```

**Expected Behavior:**
1. ✓ Query executes without error
2. ✓ Returns empty result set
3. ✓ Message: "No records found."

---

### Test Case 9: Database Connection Failure

**Test Request:**
```
"Get booked orders with customer details for 2024"
(with invalid database credentials)
```

**Expected Behavior:**
1. ✓ Query detects combined operation
2. ✓ SQL is generated correctly
3. ✗ Execution fails with connection error
4. ✓ Error message returned: "SQL execution error: [specific error]"
5. ✓ SQL query shown in error response for debugging

---

## Performance Test Cases

### Test Case 10: Large Result Set Performance

**Test Request:**
```
"Get all booked orders with customer details"
(without specific year filter)
```

**Performance Metrics:**
- [ ] Query completes within 5 seconds
- [ ] Result pagination works (if > 50 rows)
- [ ] Memory usage remains stable
- [ ] UI remains responsive

---

## Integration Test Cases

### Test Case 11: Multiple Requests in Sequence

**Objective:** Verify state management across multiple requests

**Test Sequence:**
```
1. "Show booked orders for 2024"
   ✓ Verify combined_orders_date query executes

2. "Show me booked orders with customer details"
   ✓ Verify combined_orders_customers query executes

3. "Get that same data from 2023"
   ✓ Verify year filter updates correctly
```

**Expected Behavior:**
- Each query executes independently
- Results don't interfere with each other
- History is maintained correctly
- No state corruption

---

### Test Case 12: Email with Combined Operation Results

**Objective:** Verify email functionality with combined query results

**Test Request:**
```
"Get BOOKED orders with customer details for 2024 and send to test@example.com"
```

**Expected Behavior:**
1. ✓ Executes combined_orders_customers query
2. ✓ Generates email HTML table
3. ✓ Creates Excel attachment with results
4. ✓ Sends email successfully
5. ✓ Email contains all relevant columns

---

## Manual Testing Checklist

### UI Testing

**Step 1: Open Web Interface**
```
Navigate to: http://localhost:5000
Verify:
- [ ] Chat interface loads
- [ ] Settings panel accessible
- [ ] Quick chips visible
```

**Step 2: Test Combined Operation Detection**
```
In chat input, enter:
"Get BOOKED orders with customer details for 2024"

Verify:
- [ ] Message appears in chat
- [ ] Bot responds with table
- [ ] Table has correct columns
- [ ] SQL is shown in expandable details
- [ ] is_combined_operation = true in response
```

**Step 3: Verify SQL Display**
```
Click "View Generated SQL" on results

Verify:
- [ ] SQL is valid and readable
- [ ] Contains correct table names
- [ ] Has proper WHERE clause
- [ ] JOINs are correct
<!-- - [ ] ROWNUM <= 50 or similar limit -->
```

**Step 4: Test Different Statuses**
```
Try requests with different statuses:
- "Show ENTERED orders for 2024"
- "List CANCELLED orders from 2024"
- "Get SHIPPED orders"

Verify:
- [ ] Each status returns different results
- [ ] WHERE clause reflects correct status
- [ ] Results match expectations
```

**Step 5: Test Year Filters**
```
Try requests with different years:
- "BOOKED orders for 2024"
- "BOOKED orders for 2023"
- "Orders from 2022"

Verify:
- [ ] Year filter changes correctly
- [ ] Results differ by year
- [ ] SQL EXTRACT(YEAR) is correct
```

---

## Automated Testing Script

### Python Test Script
```python
import json
import requests
from datetime import datetime

BASE_URL = "http://localhost:5000/api"

def test_combined_operations():
    """Test suite for combined operations"""
    
    test_cases = [
        {
            "name": "Booked Orders + Customers 2024",
            "message": "Get BOOKED order details and customer details of the year 2024",
            "expected_type": "dynamic_table",
            "expected_combined": True,
            "expected_tables": ["OE_ORDER_HEADERS_ALL", "HZ_PARTIES"],
        },
        {
            "name": "Orders + Inventory",
            "message": "Show booked orders with inventory item information",
            "expected_type": "dynamic_table",
            "expected_combined": True,
            "expected_tables": ["OE_ORDER_HEADERS_ALL", "MTL_SYSTEM_ITEMS_B"],
        },
        {
            "name": "Customer Order Summary",
            "message": "Show customers with their order counts by status",
            "expected_type": "dynamic_table",
            "expected_combined": True,
        }
    ]
    
    results = []
    for test in test_cases:
        try:
            response = requests.post(
                f"{BASE_URL}/chat",
                json={"message": test["message"], "history": []},
                timeout=10
            )
            data = response.json()
            
            test_result = {
                "name": test["name"],
                "passed": True,
                "checks": []
            }
            
            # Check response type
            if data.get("type") != test["expected_type"]:
                test_result["passed"] = False
                test_result["checks"].append(f"❌ Type: got {data.get('type')}, expected {test['expected_type']}")
            else:
                test_result["checks"].append(f"✓ Type correct: {test['expected_type']}")
            
            # Check combined operation flag
            if data.get("is_combined_operation") != test["expected_combined"]:
                test_result["passed"] = False
                test_result["checks"].append(f"❌ Combined flag: got {data.get('is_combined_operation')}, expected {test['expected_combined']}")
            else:
                test_result["checks"].append("✓ Combined operation detected")
            
            # Check SQL validity
            sql = data.get("sql", "")
            if not sql.startswith("SELECT"):
                test_result["passed"] = False
                test_result["checks"].append("❌ Invalid SQL: doesn't start with SELECT")
            else:
                test_result["checks"].append("✓ SQL is valid SELECT statement")
            
            # Check for expected table names
            if "expected_tables" in test:
                for table in test["expected_tables"]:
                    if table in sql:
                        test_result["checks"].append(f"✓ Table {table} found in SQL")
                    else:
                        test_result["passed"] = False
                        test_result["checks"].append(f"❌ Table {table} not found in SQL")
            
            # Check for results
            if not data.get("rows"):
                test_result["checks"].append("⚠ No rows returned (may be valid if no data)")
            else:
                test_result["checks"].append(f"✓ Returned {len(data['rows'])} rows")
            
            results.append(test_result)
            
        except Exception as e:
            results.append({
                "name": test["name"],
                "passed": False,
                "error": str(e)
            })
    
    # Print results
    print("\n" + "="*60)
    print("COMBINED OPERATIONS TEST RESULTS")
    print("="*60)
    
    for result in results:
        status = "✓ PASS" if result["passed"] else "✗ FAIL"
        print(f"\n{status} - {result['name']}")
        if "error" in result:
            print(f"  Error: {result['error']}")
        else:
            for check in result["checks"]:
                print(f"  {check}")
    
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    print(f"\n{'='*60}")
    print(f"Results: {passed_count}/{total_count} tests passed")
    print("="*60)

if __name__ == "__main__":
    test_combined_operations()
```

**Run the test script:**
```bash
python test_combined_operations.py
```

---

## Debugging Tips

### Enable SQL Logging
Add to app7.py:
```python
def execute_query(sql, params=None):
    print(f"[SQL EXECUTION] {sql[:200]}...")  # Log first 200 chars
    # ... rest of function
```

### Check Generated SQL
Look for "View Generated SQL" in web UI to see exact SQL executed.

### Monitor Database Calls
```sql
-- In Oracle, check recent queries
SELECT sql_text, executions, disk_reads
FROM v$sqlarea
WHERE upper(sql_text) LIKE '%OE_ORDER_HEADERS_ALL%'
ORDER BY executions DESC;
```

### Verify Filters
Check WHERE clause in the "View Generated SQL" section to confirm:
- Status filters (BOOKED, ENTERED, etc.)
- Year filters (EXTRACT(YEAR FROM ...))
- ORG_ID filters (should be 204 or configured value)

---

## Success Criteria

✅ All test cases pass  
✅ No SQL syntax errors  
✅ Combined operations detected correctly  
✅ Proper JOINs used  
✅ Filters applied correctly  
✅ Results match expectations  
✅ Performance acceptable (< 5 seconds)  
✅ Error handling works  
✅ Email integration works  

---

## Report Template

```markdown
# Combined Operations Test Report
Date: [DATE]
Tester: [NAME]

## Summary
- Tests Passed: X/Y
- Tests Failed: 0/Y
- Critical Issues: 0

## Test Results
[Include test case results]

## Issues Found
[List any issues with severity]

## Recommendations
[Any improvements needed]
```
