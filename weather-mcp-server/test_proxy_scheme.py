#!/usr/bin/env python3
"""
Test proxy scheme error
"""

import httpx

print("Testing proxy URL parsing...")

# Test creating Proxy objects with different URLs
test_urls = [
    "http://proxy.example.com:8080",  # Valid
    "https://proxy.example.com:8080",  # Valid
    "socks5://proxy.example.com:1080",  # Valid
    "",  # Empty string
    "invalid",  # No scheme
    "ftp://proxy.example.com",  # Unknown scheme
    "://proxy.example.com",  # Malformed
]

for url in test_urls:
    print(f"\nTesting URL: {url!r}")
    try:
        # Try to create a Proxy object
        proxy = httpx.Proxy(url)
        print(f"  ✅ Created Proxy: {proxy}")
    except ValueError as e:
        print(f"  ❌ ValueError: {e}")
    except Exception as e:
        print(f"  ❌ Other error: {type(e).__name__}: {e}")

# Test what happens with AsyncClient and proxy parameter
print("\n\nTesting AsyncClient with proxy parameter...")
try:
    # This might trigger the proxy parsing
    client = httpx.AsyncClient(proxy="")
    print("✅ Created client with proxy=''")
except Exception as e:
    print(f"❌ Error: {e}")

try:
    client = httpx.AsyncClient(proxy=None)
    print("✅ Created client with proxy=None")
except Exception as e:
    print(f"❌ Error: {e}")