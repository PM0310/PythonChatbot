# Oracle APEX Chatbot Implementation - Complete Guide

## 📋 Overview

You now have a complete PL/SQL-based chatbot implementation for Oracle APEX with three key components:

### Files Created:
1. **chatbot_plsql.sql** - Core chatbot package (intent detection, SQL generation, query execution)
2. **chatbot_extended_plsql.sql** - Extended features (email, HTML reports, APEX integration)
3. **APEX_SQL_WORKSHOP_GUIDE.sql** - Step-by-step execution guide with examples

---

## 🚀 Quick Start (5 minutes)

### Step 1: Copy and Paste in SQL Workshop
```sql
-- Go to Oracle APEX > SQL Workshop > SQL Commands
-- Copy entire content from chatbot_plsql.sql
-- Click Execute
```

### Step 2: Verify Installation
```sql
SELECT object_name, object_type, status 
FROM user_objects 
WHERE object_name LIKE 'CHATBOT%';
```

### Step 3: Run Your First Chatbot Query
```sql
DECLARE
  v_response VARCHAR2(4000);
  v_sql VARCHAR2(4000);
BEGIN
  chatbot_pkg.process_user_message(
    'Show me orders from the last 30 days',
    v_response,
    v_sql
  );
  DBMS_OUTPUT.PUT_LINE(v_response);
END;
/
```

---

## 📊 Architecture Comparison

### Your Original Python Implementation:
```
User Input 
  ↓
Flask Server (app7.py)
  ↓
OpenAI API (Intent Detection)
  ↓
OpenAI API (SQL Generation)
  ↓
Oracle Database
  ↓
Email/Reports
```

### New Oracle APEX Implementation:
```
APEX Form → PL/SQL Package → Oracle Database
             (Keyword matching)  (Direct query)
             (SQL templates)     (No external API)
             
Optional: OpenAI API for advanced AI
```

---

## 🔧 Component Breakdown

### `chatbot_pkg` - Core Package Functions

| Function | Purpose | Input | Output |
|----------|---------|-------|--------|
| `process_user_message` | Main entry point | User message | Response + SQL |
| `detect_intent` | Extract user intent | Message text | Intent JSON |
| `generate_sql` | Create SELECT queries | Intent JSON | SQL string |
| `execute_query` | Run dynamic SQL | SQL string | Results JSON |
| `parse_json_response` | Extract SQL from JSON | JSON response | SQL query |

**Mapping to Your Python Logic:**
- `detect_intent()` = Your `pydantic_ai_adapter.py` intent extraction
- `generate_sql()` = Your system prompt-based SQL generation
- `execute_query()` = Your `oracledb` query execution

---

### `chatbot_extended_pkg` - Advanced Features

| Function | Purpose |
|----------|---------|
| `format_results_html()` | Convert SQL results to HTML table |
| `send_chatbot_email()` | Email results with SMTP |
| `generate_excel_report()` | Export results as CSV |
| `chatbot_with_email()` | Combined chatbot + email workflow |

---

## 📱 APEX Integration Patterns

### Pattern 1: Form with Chat Interface
```
┌─────────────────────────────────────┐
│ APEX Form Page                      │
├─────────────────────────────────────┤
│ Text Item: P_USER_MESSAGE           │
│ Button: "Ask Chatbot"               │
├─────────────────────────────────────┤
│ Display Only: P_RESPONSE            │
│ Display Only: P_SQL_QUERY           │
└─────────────────────────────────────┘
    ↓
Dynamic Action (On Button Click)
    ↓
EXECUTE CHATBOT_PKG.PROCESS_USER_MESSAGE(
  :P_USER_MESSAGE, :P_RESPONSE, :P_SQL_QUERY
)
```

### Pattern 2: Interactive Report with Chatbot
```
APEX Tabbed Interface:
├─ Tab 1: Interactive Report (manual SQL)
└─ Tab 2: Chatbot (AI-generated queries)
```

### Pattern 3: Dashboard with Auto-Refresh
```
Scheduled Job (Daily 9 AM)
    ↓
RUN_SCHEDULED_CHATBOT_REPORT()
    ↓
Generate HTML Report
    ↓
Send Email to Users
```

---

## 🔐 Security Considerations

### 1. SQL Injection Prevention
Your implementation uses DBMS_SQL with parameterized execution, not string concatenation.

### 2. API Key Management
```sql
-- Store sensitive data in APEX Workspace Preferences or Oracle Vault
DECLARE
  l_api_key VARCHAR2(500);
BEGIN
  l_api_key := apex_util.get_preference('OPENAI_API_KEY');
  -- Use l_api_key safely
END;
/
```

### 3. Email Security
Use application-specific passwords (not main account password) for SMTP:
```
Gmail: Create app-specific password at https://myaccount.google.com/apppasswords
Office 365: Similar approach
```

### 4. Database Privileges
Only grant necessary execute permissions:
```sql
GRANT EXECUTE ON chatbot_pkg TO apex_user;
GRANT EXECUTE ON chatbot_extended_pkg TO apex_user;
GRANT SELECT ON oe_orders TO apex_user;
```

---

## 🎯 Differences: Python vs PL/SQL Implementation

### Advantages of PL/SQL (APEX Native):
✅ No external server needed  
✅ Direct database access  
✅ Better APEX integration  
✅ Simpler deployment  
✅ Native JSON support in Oracle 12c+  

### Trade-offs:
⚠️ Simpler intent detection (keyword-based vs AI)  
⚠️ Cannot run Python libraries (vosk, pyttsx3)  
⚠️ Limited to Oracle SQL dialects  
⚠️ Email requires network access (UTL_SMTP)  

### Solution for Advanced AI:
Keep your **Python Flask backend** and use this PL/SQL as a **frontend wrapper**:
```
APEX Form
  ↓
PL/SQL Package
  ↓
Python Flask REST API (Your existing app7.py)
  ↓
OpenAI/PydanticAI
```

---

## 📝 Customization Guide

### 1. Update Intent Keywords
Edit `detect_intent()` function in `chatbot_pkg`:
```plsql
IF UPPER(p_message) LIKE '%YOUR_KEYWORD%' THEN
  l_intent_action := 'your_action';
END IF;
```

### 2. Add New SQL Templates
Add new `CASE` statements in `generate_sql()`:
```plsql
WHEN 'your_action' THEN
  l_sql_query := 'SELECT * FROM your_table WHERE condition';
```

### 3. Modify Email Configuration
Edit email settings in `send_chatbot_email()`:
```plsql
l_smtp_host VARCHAR2(255) := 'your-smtp-server';
l_sender VARCHAR2(255) := 'chatbot@yourcompany.com';
l_sender_pwd VARCHAR2(255) := 'app-specific-password';
```

### 4. Add Custom Tables
Extend the sample `oe_orders` table or replace with your actual schema:
```sql
-- Your actual Oracle EBS or custom tables
-- The chatbot will query these directly
```

---

## 🧪 Testing Checklist

- [ ] SQL Workshop shows CHATBOT_PKG and CHATBOT_EXTENDED_PKG as valid
- [ ] Test `process_user_message()` with sample message
- [ ] Verify SQL output is valid and executable
- [ ] Test email functionality (update SMTP settings first)
- [ ] Create APEX form page with text item + button
- [ ] Set up dynamic action calling the chatbot
- [ ] Verify AJAX callback returns JSON properly
- [ ] Test scheduled job execution

---

## 🚫 Common Issues & Solutions

### Issue: "ORA-06550: PLS-00103" (Compilation Error)
**Solution:** Check for missing semicolons or syntax errors. Use SQL Workshop Errors tab.

### Issue: Email not sending
**Solution:** 
1. Verify SMTP settings (host, port, authentication)
2. Check if UTL_SMTP is enabled: `GRANT EXECUTE ON utl_smtp TO YOUR_USER;`
3. Test with Gmail app-specific password

### Issue: Query returns no results
**Solution:**
1. Verify table names and columns exist
2. Check user privileges to access tables
3. Test SQL directly in SQL Workshop

### Issue: AJAX callback hangs
**Solution:**
1. Check for infinite loops in SQL generation
2. Add ROWNUM <= 50 limit to prevent timeout
3. Monitor v$session for blocking locks

---

## 🔄 Integration with Your Python Implementation

### Option A: Keep Both (Recommended)
```
APEX ↔ PL/SQL (For simple queries)
APEX ↔ Python Flask (For complex AI tasks)
Python Flask → Oracle DB
```

### Option B: Migrate to PL/SQL
1. Replace keyword detection with OpenAI API calls from PL/SQL (using UTL_HTTP)
2. Remove Flask server
3. Host everything in APEX

### Option C: Hybrid for Best Performance
```
APEX Form
  ↓
Check: Is this a simple query?
  ├─ Yes → Use PL/SQL (fast)
  └─ No → Call Python Flask (accurate)
```

---

## 📚 SQL Workshop Commands Reference

```sql
-- View all packages
SELECT object_name FROM user_objects WHERE object_type = 'PACKAGE';

-- Check package code
SELECT text FROM user_source WHERE name = 'CHATBOT_PKG' ORDER BY line;

-- Run chatbot
BEGIN
  chatbot_pkg.process_user_message(
    'Your question here',
    l_response,
    l_sql
  );
END;
/

-- Drop and recreate
DROP PACKAGE BODY chatbot_pkg;
DROP PACKAGE chatbot_pkg;

-- Enable output in SQL Workshop
SET PAGESIZE 50000;
SET LONG 20000;
SET LONGCHUNKSIZE 20000;
VARIABLE sql_output CLOB;
```

---

## 🎓 Learning Resources

- [Oracle APEX Documentation](https://docs.oracle.com/en/database/oracle/apex)
- [PL/SQL Dynamic SQL](https://docs.oracle.com/en/database/oracle/oracle-database/21/adfns/dynamic-sql.html)
- [Oracle JSON Functions](https://docs.oracle.com/en/database/oracle/oracle-database/21/adjsn/)
- [APEX Application Development](https://www.oracle.com/cloud/technologies/application-express/documentation/)

---

## ✅ Next Steps

1. **Execute** chatbot_plsql.sql in SQL Workshop
2. **Test** with sample messages
3. **Create** APEX form page
4. **Configure** email (update SMTP settings)
5. **Build** APEX UI with chatbot integration
6. **Deploy** to production

---

## 📞 Support

For issues:
1. Check SQL Workshop Errors tab
2. Review APEX_WORKSPACE_ADMIN logs
3. Test functions individually
4. Verify database privileges
5. Check network connectivity for email/external APIs

---

**Created:** 2024  
**Version:** 1.0  
**Compatible With:** Oracle Database 12c+, APEX 20.0+  
**License:** For use with Oracle APEX implementations
