# Fixed REST API Verification Scripts - Usage Guide

## ✅ What Was Fixed

Your `VERIFY_REST_API_CONFIG.sql` had errors because:
- It tried to query `dba_*` and `apex_*` system tables
- You may not have DBA privileges to access these
- This caused "table or view does not exist" errors

**Solution:** Created 2 versions:
1. **Fixed version** - Same script but with better error handling
2. **Simplified version** - Tests only what matters (connectivity)

---

## 🎯 Which Script Should You Use?

### **Use This First: `VERIFY_REST_API_SIMPLE.sql`**

✅ **Advantages:**
- Works with any privilege level (doesn't need DBA)
- Tests actual network connectivity (what matters)
- Gives clear pass/fail for each test
- No table lookup errors
- Recommended for most users

**Run this:**
```sql
-- Copy entire content from VERIFY_REST_API_SIMPLE.sql
-- Paste into SQL Workshop
-- Click Execute
-- Read the results
```

### **Use If You Have DBA Privileges: `VERIFY_REST_API_CONFIG.sql` (Fixed)**

✅ **Advantages:**
- Checks ACL configuration details
- Checks APEX credential setup
- More comprehensive diagnosis

**Only use if you have DBA role.**

---

## 🚀 Quick Start (Choose One)

### **Option A: Simplest (Most Users)**
```sql
-- Run VERIFY_REST_API_SIMPLE.sql
-- 3 simple tests:
-- 1. Can you reach public internet? (httpbin.org)
-- 2. Can you reach your endpoint? (cendb.ad.centroid.com)
-- 3. Can you call your REST API? (full test)
```

### **Option B: Detailed (If you have DBA)**
```sql
-- Run VERIFY_REST_API_CONFIG.sql (the fixed version)
-- Checks ACL, credentials, and network
```

---

## 📋 What Each Script Tests

### **VERIFY_REST_API_SIMPLE.sql** (Recommended)

| Test | Checks | Success = | Failure = |
|------|--------|-----------|-----------|
| Test 1 | Can reach httpbin.org | HTTP 200 | NULL or error |
| Test 2 | Can reach your EBS server | HTTP 200+ | NULL or error |
| Test 3 | Your full REST API call | HTTP 200+ | 401/403/NULL |

**Results:**
- ✅ 3/3 Passed = Everything works
- ⚠️ 2/3 Passed = Endpoint unreachable or wrong URL
- ❌ 1/3 Passed = Network ACL likely not configured
- ❌ 0/3 Passed = Severe network issue

### **VERIFY_REST_API_CONFIG.sql** (Fixed Version)

| Check | Tests | Requires |
|-------|-------|----------|
| Database Version | Oracle installation | None |
| APEX Package | APEX_WEB_SERVICE exists | None |
| Network ACL | ACL configured for cendb | DBA role |
| Credentials | ebscreds exists in APEX | APEX access |
| Public Connectivity | Can reach httpbin.org | Network |
| Endpoint Connectivity | Can reach cendb endpoint | Network |

---

## 🔧 How to Fix Based on Results

### **If Test 1 Fails (Can't reach public internet)**
```
Cause: Network ACL not configured or firewall blocking
Fix: 
1. Ask DBA to configure Network ACL
2. Or run REST_API_FIXED_SOLUTIONS.sql SOLUTION 3
3. Or check firewall settings
```

### **If Test 2 Fails (Can't reach your EBS server)**
```
Cause: Endpoint unreachable, ACL issue, or wrong URL
Fix:
1. Verify URL is correct: https://cendb.ad.centroid.com:4463
2. Check if endpoint is running
3. Check firewall allows port 4463
4. Configure Network ACL if needed
```

### **If Test 3 Fails with HTTP 401/403**
```
Cause: Authentication failed
Fix:
1. Check credential 'ebscreds' exists in APEX
2. Verify username/password are correct
3. User has permission to call the API
```

### **If Test 3 Fails with NULL status**
```
Cause: Network issue (same as Test 1)
Fix:
1. Configure Network ACL
2. Check firewall rules
3. Ensure database has network access
```

---

## ✅ Success Workflow

```
1. Run VERIFY_REST_API_SIMPLE.sql
          ↓
2. Check results for each test
          ↓
   ┌─────┴─────────────────────┐
   │                           │
  ALL PASS?               Some/All FAIL?
   │                           │
   ↓                           ↓
✅ Done!                  Check table below for fix
Your REST API            Choose appropriate fix
should work              Apply fix, re-run
```

---

## 📁 Files Summary

| File | Purpose | Use Case |
|------|---------|----------|
| `VERIFY_REST_API_SIMPLE.sql` | **Test connectivity** | **START HERE** |
| `VERIFY_REST_API_CONFIG.sql` | Comprehensive check | If you have DBA role |
| `REST_API_FIXED_SOLUTIONS.sql` | All fixes available | After identifying problem |
| `ORA-29273_QUICK_FIX.md` | 30-second solution | Most common fix |
| `ORA-29273_TROUBLESHOOTING_GUIDE.md` | Detailed steps | Complex issues |

---

## 🎯 Recommended Path

**For 95% of users:**

1. ✅ Run `VERIFY_REST_API_SIMPLE.sql`
2. ✅ Read the results
3. ✅ If Test 1 fails → Run ACL setup from `ORA-29273_QUICK_FIX.md`
4. ✅ If Test 3 fails with 401 → Check credentials in APEX
5. ✅ Re-run `VERIFY_REST_API_SIMPLE.sql` to confirm fix

**Done!** 🎉

---

## 🆘 If Still Having Issues

1. **Re-read the SIMPLE test results** - they tell you exactly what's wrong
2. **Follow the "How to Fix" table above** for your specific error
3. **Read full guide:** `ORA-29273_TROUBLESHOOTING_GUIDE.md`
4. **Contact DBA if:** You see "Network ACL" recommendations

---

## 📝 Error Messages You Should NOT See Anymore

❌ **These are fixed:**
```
ORA-00942: table or view does not exist  ← FIXED
PLS-00364: loop index variable use is invalid  ← FIXED
```

✅ **Now you'll see:**
```
✅ PASS: ...
❌ FAIL: ...
⚠️  INFO: ...
```

---

**Bottom Line: Use `VERIFY_REST_API_SIMPLE.sql` - it just works!**
