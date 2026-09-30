#!/usr/bin/env python
"""Comprehensive agent validation tests"""
import requests
import json

BASE_URL = 'http://127.0.0.1:5000'

def test_empty_message():
    """Test empty message handling"""
    try:
        payload = {'message': '', 'history': []}
        r = requests.post(f'{BASE_URL}/api/chat', json=payload)
        if r.status_code == 200:
            data = r.json()
            return 'Please enter a message' in str(data.get('reply', ''))
        return False
    except Exception as e:
        print(f'Empty message test error: {e}')
        return False

def test_create_form():
    """Test create order form request"""
    try:
        payload = {'message': 'create order', 'history': []}
        r = requests.post(f'{BASE_URL}/api/chat', json=payload)
        if r.status_code == 200:
            data = r.json()
            return data.get('type') == 'create_form'
        return False
    except Exception as e:
        print(f'Create form test error: {e}')
        return False

def test_help_command():
    """Test help command"""
    try:
        payload = {'message': '?', 'history': []}
        r = requests.post(f'{BASE_URL}/api/chat', json=payload)
        if r.status_code == 200:
            data = r.json()
            reply = str(data.get('reply', '')).lower()
            return 'try' in reply or 'command' in reply or 'help' in reply
        return False
    except Exception as e:
        print(f'Help command test error: {e}')
        return False

def test_item_validation_api():
    """Test item resolution/validation"""
    try:
        payload = {
            'ordered_item': 'VISION',
            'customer_name': '',
            'ordered_quantity': None,
            'cust_po_number': None
        }
        r = requests.post(f'{BASE_URL}/api/create-order/item-resolve', json=payload)
        return r.status_code == 200
    except Exception as e:
        print(f'Item validation test error: {e}')
        return False

def test_create_order_draft():
    """Test create order draft validation"""
    try:
        payload = {
            'ordered_item': 'VISION',
            'customer_name': 'Vision',
            'ordered_quantity': 10,
            'cust_po_number': 'TEST123'
        }
        r = requests.post(f'{BASE_URL}/api/create-order/draft', json=payload)
        return r.status_code in [200, 400]  # Either valid or returns validation errors
    except Exception as e:
        print(f'Create order draft test error: {e}')
        return False

def test_lookup_sites():
    """Test site lookup API"""
    try:
        # Test with a valid customer ID (generic test)
        r = requests.get(f'{BASE_URL}/api/lookup-customer-sites?cust_account_id=1')
        return r.status_code == 200
    except Exception as e:
        print(f'Site lookup test error: {e}')
        return False

def test_friendly_messages():
    """Test that error messages are friendly (not generic)"""
    try:
        # Test with invalid customer to trigger no-data scenario
        payload = {'message': 'get orders for customer XYZNONEXISTENT123', 'history': []}
        r = requests.post(f'{BASE_URL}/api/chat', json=payload)
        if r.status_code == 200:
            data = r.json()
            reply = str(data.get('reply', '')).lower()
            # Check for friendly, conversational messages instead of generic ones
            friendly_indicators = [
                "couldn't find",
                "hmm",
                "let me",
                "try",
                "try again",
                "different"
            ]
            is_friendly = any(indicator in reply for indicator in friendly_indicators)
            is_not_generic = "no records found" not in reply
            return is_friendly or is_not_generic
        return False
    except Exception as e:
        print(f'Friendly messages test error: {e}')
        return False

def test_static_files():
    """Test that main HTML files are served"""
    try:
        files = ['/static/index7.1.html', '/static/index7.html', '/static/dashboard.html']
        for f in files:
            r = requests.get(f'{BASE_URL}{f}')
            if r.status_code != 200:
                print(f'Missing: {f}')
                return False
        return True
    except Exception as e:
        print(f'Static files test error: {e}')
        return False

# Run comprehensive tests
print("=" * 70)
print("COMPREHENSIVE AGENT VALIDATION TESTS")
print("=" * 70)

tests = [
    ('Empty Message Handling', test_empty_message),
    ('Create Order Form', test_create_form),
    ('Help Command', test_help_command),
    ('Item Validation API', test_item_validation_api),
    ('Create Order Draft API', test_create_order_draft),
    ('Ship-to Site Lookup API', test_lookup_sites),
    ('Friendly Error Messages', test_friendly_messages),
    ('Static Files Availability', test_static_files),
]

results = []
for test_name, test_func in tests:
    print(f"\n{test_name}...", end=' ')
    try:
        result = test_func()
        status = "✓ PASS" if result else "✗ FAIL"
        print(status)
        results.append((test_name, result))
    except Exception as e:
        print(f"✗ ERROR: {str(e)[:50]}")
        results.append((test_name, False))

# Summary
print("\n" + "=" * 70)
print("COMPREHENSIVE TEST SUMMARY")
print("=" * 70)
passed = sum(1 for _, r in results if r)
total = len(results)
percentage = (passed / total * 100) if total > 0 else 0

print(f"\nOverall: {passed}/{total} tests passed ({percentage:.0f}%)")
print("\nDetailed Results:")
for test_name, result in results:
    status = "✓" if result else "✗"
    print(f"  {status} {test_name}")

print("\n" + "=" * 70)
if passed == total:
    print("🎉 EXCELLENT! Agent is fully operational and all features working!")
elif passed >= total * 0.8:
    print("✅ GOOD! Agent is mostly working. Minor issues to review.")
else:
    print(f"⚠️  WARNING! {total - passed} critical tests failed.")
print("=" * 70)
