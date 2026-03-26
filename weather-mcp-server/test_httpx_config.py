#!/usr/bin/env python3
"""
Test httpx config initialization
"""

import os
import httpx

print("Testing httpx config initialization...")

# Set up problematic environment
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,::1'

# Clear ALL proxy variables as in our fix
proxy_vars_to_clear = [
    'http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY',
    'all_proxy', 'ALL_PROXY', 'no_proxy', 'NO_PROXY',
    'ftp_proxy', 'FTP_PROXY', 'socks_proxy', 'SOCKS_PROXY'
]

saved_proxies = {}
for var in proxy_vars_to_clear:
    if var in os.environ:
        saved_proxies[var] = os.environ[var]
        del os.environ[var]

try:
    print("1. Testing AsyncClient creation...")
    client = httpx.AsyncClient()
    print(f"   ✅ AsyncClient created: {client}")
    
    print("\n2. Testing Client creation (sync)...")
    sync_client = httpx.Client()
    print(f"   ✅ Client created: {sync_client}")
    
    print("\n3. Testing with explicit parameters...")
    client2 = httpx.AsyncClient(timeout=30.0)
    print(f"   ✅ AsyncClient with timeout created: {client2}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    # Restore
    for var, value in saved_proxies.items():
        os.environ[var] = value