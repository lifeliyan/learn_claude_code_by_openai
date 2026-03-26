#!/usr/bin/env python3
"""
Test socks proxy issue
"""

import httpx

print("Testing socks proxy URLs...")

# Test different socks URLs
test_urls = [
    "socks://127.0.0.1:7897/",  # What you have
    "socks5://127.0.0.1:7897/",  # What httpx expects
    "socks4://127.0.0.1:7897/",  # Another variant
]

for url in test_urls:
    print(f"\nTesting URL: {url!r}")
    try:
        proxy = httpx.Proxy(url)
        print(f"  ✅ Created Proxy: {proxy}")
    except ValueError as e:
        print(f"  ❌ ValueError: {e}")
    except Exception as e:
        print(f"  ❌ Other error: {type(e).__name__}: {e}")

# Check what proxy schemes httpx supports
print("\n\nChecking httpx proxy support...")
try:
    # Try to see what happens with AsyncClient
    print("Testing AsyncClient with socks://...")
    client = httpx.AsyncClient(proxy="socks://127.0.0.1:7897/")
    print("  ✅ Created client with socks://")
except Exception as e:
    print(f"  ❌ Error: {e}")

try:
    print("\nTesting AsyncClient with socks5://...")
    client = httpx.AsyncClient(proxy="socks5://127.0.0.1:7897/")
    print("  ✅ Created client with socks5://")
except Exception as e:
    print(f"  ❌ Error: {e}")