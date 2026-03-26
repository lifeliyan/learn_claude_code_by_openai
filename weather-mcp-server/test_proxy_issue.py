#!/usr/bin/env python3
"""
Test proxy issue
"""

import os
import httpx

print("Testing with current environment...")
try:
    client = httpx.AsyncClient()
    print("✅ Client created with current environment")
except Exception as e:
    print(f"❌ Failed: {e}")

print("\nTesting with NO_PROXY unset...")
# Save current values
no_proxy_orig = os.environ.get('NO_PROXY')
no_proxy_lower_orig = os.environ.get('no_proxy')

# Unset them
if 'NO_PROXY' in os.environ:
    del os.environ['NO_PROXY']
if 'no_proxy' in os.environ:
    del os.environ['no_proxy']

try:
    client = httpx.AsyncClient()
    print("✅ Client created with NO_PROXY unset")
except Exception as e:
    print(f"❌ Failed: {e}")

# Restore
if no_proxy_orig:
    os.environ['NO_PROXY'] = no_proxy_orig
if no_proxy_lower_orig:
    os.environ['no_proxy'] = no_proxy_lower_orig