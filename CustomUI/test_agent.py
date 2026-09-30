#!/usr/bin/env python
"""Test the agent functionality"""
import requests
import json
import time

BASE_URL = 'http://127.0.0.1:5000'

def test_ui():
    """Test if UI is accessible"""
    try:
        r = requests.get(f'{BASE_URL}/')
        return r.status_code == 200
    except Exception as e:
        print(f'UI test failed: {e}')
        return False

def test_chat_hello():
    """Test chat with greeting"""
    try:
        payload = {'message': 'hello', 'history': []}
        r = requests.post(f'{BASE_URL}/api/chat', json=payload)
        return r.status_code == 200
    except Exception as e:
        print(f'Chat hello test failed: {e}')
        return False

def test_chat_help():
    """Test chat with help"""
    try:
        payload = {'message': 'help', 'history': []}
        r = requests.post(f'{BASE_URL}/api/chat', json=payload)
        return r.status_code == 200
    except Exception as e:
        print(f'Chat help test failed: {e}')
        return False

def test_lookup_items():
    """Test item lookup"""
    try:
        r = requests.get(f'{BASE_URL}/api/lookup-items?search=A&offset=0')
        return r.status_code == 200
    except Exception as e:
        print(f'Item lookup test failed: {e}')
        return False

def test_lookup_customers():
    """Test customer lookup"""
    try:
        r = requests.get(f'{BASE_URL}/api/lookup-customers?search=Vision&offset=0')
        return r.status_code == 200
    except Exception as e:
        print(f'Customer lookup test failed: {e}')
        return False

def test_dashboard():
    """Test dashboard page"""
    try:
        r = requests.get(f'{BASE_URL}/dashboard')
        return r.status_code == 200
    except Exception as e:
        print(f'Dashboard test failed: {e}')
        return False

# Run tests
print("=" * 60)
print("AGENT FUNCTIONALITY TESTS")
print("=" * 60)

tests = [
    ('UI Homepage', test_ui),
    ('Chat - Hello', test_chat_hello),
    ('Chat - Help', test_chat_help),
    ('Item Lookup', test_lookup_items),
    ('Customer Lookup', test_lookup_customers),
    ('Dashboard', test_dashboard),
]

results = []
for test_name, test_func in tests:
    print(f"\nTesting: {test_name}...", end=' ')
    try:
        result = test_func()
        status = "✓ PASS" if result else "✗ FAIL"
        print(status)
        results.append((test_name, result))
    except Exception as e:
        print(f"✗ ERROR: {e}")
        results.append((test_name, False))

# Summary
print("\n" + "=" * 60)
print("TEST SUMMARY")
print("=" * 60)
passed = sum(1 for _, r in results if r)
total = len(results)
print(f"Passed: {passed}/{total}")
for test_name, result in results:
    status = "✓" if result else "✗"
    print(f"  {status} {test_name}")

if passed == total:
    print("\n🎉 All tests PASSED! Agent is working fine.")
else:
    print(f"\n⚠️  {total - passed} test(s) FAILED. Please review.")
