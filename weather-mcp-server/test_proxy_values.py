#!/usr/bin/env python3
"""
Check for problematic proxy values
"""

import os

print("Checking proxy environment variables...")
proxy_vars = [
    'http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
    'all_proxy', 'ALL_PROXY'
]

found_issues = False
for var in proxy_vars:
    value = os.getenv(var)
    if value is not None:
        print(f"  {var} = '{value}'")
        if value.strip() == '':
            print(f"    ⚠️  WARNING: Empty string!")
            found_issues = True
        elif not value.startswith(('http://', 'https://', 'socks5://')):
            print(f"    ⚠️  WARNING: Doesn't start with http://, https://, or socks5://")
            found_issues = True

if not found_issues:
    print("No problematic proxy values found")

# Test what happens with empty proxy value
print("\nTesting httpx with empty proxy value...")
os.environ['HTTP_PROXY'] = ''  # Set empty proxy

import httpx
try:
    client = httpx.AsyncClient(trust_env=True)
    print("✅ Created client with empty proxy (trust_env=True)")
except Exception as e:
    print(f"❌ Failed with empty proxy (trust_env=True): {e}")

try:
    client = httpx.AsyncClient(trust_env=False)
    print("✅ Created client with empty proxy (trust_env=False)")
except Exception as e:
    print(f"❌ Failed with empty proxy (trust_env=False): {e}")