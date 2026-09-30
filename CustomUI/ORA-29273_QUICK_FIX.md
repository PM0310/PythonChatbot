# ORA-29273: HTTP Request Failed - Quick Reference Card

## 🔴 Your Error
```
Error: ORA-29273: HTTP request failed
HTTP Status: NULL
Response: (empty)
```

---

## ⚡ Quick Fix (30 seconds)

**Run this in SQL Workshop (as DBA):**

```sql
BEGIN
    DBMS_NETWORK_ACL_ADMIN.CREATE_ACL(
        acl         => 'rest_api_acl.xml',
        description => 'REST API Access',
        principal   => 'APEX_050000',
        is_grant    => TRUE,
        privilege   => 'connect'
    );
    DBMS_NETWORK_ACL_ADMIN.ADD_PRIVILEGE(
        acl       => 'rest_api_acl.xml',
        principal => 'APEX_050000',
        is_grant  => TRUE,
        privilege => 'connect'
    );
    DBMS_NETWORK_ACL_ADMIN.ASSIGN_ACL(
        acl        => 'rest_api_acl.xml',
        host       => 'cendb.ad.centroid.com',
        lower_port => 4463,
        upper_port => 4463
    );
    COMMIT;
    DBMS_OUTPUT.PUT_LINE('✅ Fixed!');
END;
/
```

**⚠️ Change `APEX_050000` to your APEX user!**

---

## 📋 5-Step Checklist

- [ ] **STEP 1:** Run `VERIFY_REST_API_CONFIG.sql` to diagnose
- [ ] **STEP 2:** Run ACL setup above (if ACL is missing)
- [ ] **STEP 3:** Check credentials exist in APEX Admin
- [ ] **STEP 4:** Test with public endpoint (httpbin.org)
- [ ] **STEP 5:** Test your endpoint (cendb.ad.centroid.com:4463)

---

## 🔧 Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| `HTTP Status = NULL` | Network ACL not set | Run ACL setup above |
| `HTTP 401/403` | Bad credentials | Check APEX credentials |
| Timeout | Firewall blocking | Check firewall rules |
| `SSL: certificate error` | Self-signed cert | Use wallet or skip SSL |

---

## 📁 Files You Have

| File | Purpose |
|------|---------|
| `REST_API_FIXED_SOLUTIONS.sql` | 6 different solutions |
| `ORA-29273_TROUBLESHOOTING_GUIDE.md` | Complete step-by-step guide |
| `VERIFY_REST_API_CONFIG.sql` | Check all prerequisites |
| This file | Quick reference |

---

## 🚀 One-Minute Test

**Copy and run this to verify everything works:**

```sql
DECLARE
    l_response CLOB;
    l_status   NUMBER;
BEGIN
    APEX_WEB_SERVICE.SET_REQUEST_HEADERS(
        p_name_01 => 'Content-Type', p_value_01 => 'application/json',
        p_reset => TRUE
    );

    l_response := APEX_WEB_SERVICE.MAKE_REST_REQUEST(
        p_url              => 'https://httpbin.org/get',
        p_http_method      => 'GET',
        p_transfer_timeout => 30
    );

    l_status := APEX_WEB_SERVICE.G_STATUS_CODE;
    
    IF l_status = 200 THEN
        DBMS_OUTPUT.PUT_LINE('✅ Network OK - your issue is endpoint-specific');
    ELSE
        DBMS_OUTPUT.PUT_LINE('❌ Network issue - check ACL');
    END IF;
END;
/
```

---

## 💡 Most Common Cause

**99% of ORA-29273 errors are because Network ACL is not configured.**

**Solution:** Run the Quick Fix above. That's it!

---

## 🆘 Still Stuck?

1. Check database alert log:
```sql
SELECT * FROM v$diag_alert_ext WHERE inst_id = USERENV('INSTANCE') ORDER BY originating_timestamp DESC FETCH FIRST 10 ROWS ONLY;
```

2. Read full guide: `ORA-29273_TROUBLESHOOTING_GUIDE.md`

3. Run diagnostic: `VERIFY_REST_API_CONFIG.sql`

---

## ✅ Success Indicators

- ✅ HTTP Status: 200, 201, 202, etc. (not NULL)
- ✅ Response contains JSON/XML data
- ✅ No ORA-29273 errors
- ✅ No timeouts

---

**Start here → Run Quick Fix → Run Verification Script → Done!**
